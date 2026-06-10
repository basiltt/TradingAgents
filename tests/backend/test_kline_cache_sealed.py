"""Integration tests for the sealed-manifest cache fix (Phase P1, AC-007).

The headline guarantee: a closed day is fetched from the exchange EXACTLY ONCE
across N reruns — the fix for "re-downloads klines every time". Validated headless
(N3) with a fake asyncpg pool + a call-counting fetch, so no Postgres/network.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.services.kline_cache_service import KlineCacheService

UTC = timezone.utc


class FakePool:
    """Minimal in-memory stand-in for the asyncpg pool used by KlineCacheService.

    Models the two tables the sealed path touches: kline_cache_coverage rows
    (symbol, interval, date, candle_count, sealed) and is enough to exercise
    get_coverage_gaps + the seal UPDATE. fetch/execute parse only the queries the
    service actually issues.
    """

    def __init__(self):
        # (symbol, interval, date) -> {"candle_count": int, "sealed": bool}
        self.coverage: dict[tuple, dict] = {}
        self.executed: list[str] = []

    async def fetch(self, query, *args):
        if "FROM kline_cache_coverage" in query:
            symbols, interval, start_date, end_date = args
            out = []
            for (sym, iv, d), row in self.coverage.items():
                if sym in symbols and iv == interval and start_date <= d <= end_date:
                    out.append({"symbol": sym, "date": d,
                                "candle_count": row["candle_count"], "sealed": row["sealed"]})
            return out
        return []

    async def executemany(self, query, records):
        if "INSERT INTO kline_cache_coverage" in query:
            for sym, iv, d, count in records:
                key = (sym, iv, d)
                cur = self.coverage.get(key, {"candle_count": 0, "sealed": False})
                cur["candle_count"] = max(cur["candle_count"], count)
                self.coverage[key] = cur
        elif "INSERT INTO kline_cache" in query:
            pass  # candle rows — not needed for coverage assertions

    async def execute(self, query, *args):
        self.executed.append(query)
        if "UPDATE kline_cache_coverage" in query and "SET sealed = true" in query:
            symbols, interval, days = args
            n = 0
            for (sym, iv, d), row in self.coverage.items():
                if sym in symbols and iv == interval and d in days and not row["sealed"]:
                    row["sealed"] = True
                    n += 1
            return f"UPDATE {n}"
        if "CREATE TABLE" in query or "ALTER TABLE" in query:
            return "OK"
        return "OK"


class FakeDB:
    def __init__(self):
        self.pool = FakePool()


@pytest.fixture
def service_and_fetch(monkeypatch):
    """A KlineCacheService whose Bybit fetch is replaced by a call-counter that
    returns one closed day's worth of (short) candles."""
    db = FakeDB()
    svc = KlineCacheService(db)
    calls = {"count": 0, "symbols": []}

    # A closed day, well below the completion frontier (yesterday relative to a
    # fixed "now" we control via the frontier — here just use a past date).
    closed_day = date(2026, 6, 1)

    async def fake_fetch(symbol, interval, fetch_start, fetch_end):
        calls["count"] += 1
        calls["symbols"].append(symbol)
        # Return a deliberately SHORT day (144 candles vs 288 expected) — the exact
        # RC-3 trigger. open_time within the closed day.
        base = datetime(closed_day.year, closed_day.month, closed_day.day, tzinfo=UTC)
        return [
            {"open_time": base + timedelta(minutes=5 * i), "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.0, "volume": 10.0}
            for i in range(144)
        ]

    monkeypatch.setattr(svc, "_fetch_klines_from_bybit", fake_fetch)
    return svc, calls, closed_day


@pytest.mark.asyncio
async def test_sealed_day_fetched_exactly_once_across_reruns(service_and_fetch):
    """AC-007: the closed day is fetched ONCE, then never again — even though it is
    legitimately short (144/288). Three reruns ⇒ call_count stays 1."""
    svc, calls, closed_day = service_and_fetch
    start = datetime(closed_day.year, closed_day.month, closed_day.day, tzinfo=UTC)
    end = start + timedelta(days=1) - timedelta(seconds=1)

    # Run 1: cold — must fetch once, then seal.
    await svc.ensure_coverage(["BTCUSDT"], "5m", start, end)
    assert calls["count"] == 1, "cold run should fetch the closed day once"

    # Runs 2 & 3: warm — the day is sealed, so ZERO additional exchange calls.
    await svc.ensure_coverage(["BTCUSDT"], "5m", start, end)
    await svc.ensure_coverage(["BTCUSDT"], "5m", start, end)
    assert calls["count"] == 1, (
        f"sealed closed day re-fetched (call_count={calls['count']}) — RC-3 NOT fixed"
    )

    # And the coverage row is actually marked sealed.
    assert svc._db.pool.coverage[("BTCUSDT", "5m", closed_day)]["sealed"] is True


@pytest.mark.asyncio
async def test_gaps_empty_for_sealed_short_day(service_and_fetch):
    """After sealing, get_coverage_gaps returns NO gap for the short closed day —
    the direct assertion that a 144/288 sealed day is treated as complete."""
    svc, calls, closed_day = service_and_fetch
    start = datetime(closed_day.year, closed_day.month, closed_day.day, tzinfo=UTC)
    end = start + timedelta(days=1) - timedelta(seconds=1)

    await svc.ensure_coverage(["BTCUSDT"], "5m", start, end)  # fetch + seal
    gaps = await svc.get_coverage_gaps(["BTCUSDT"], "5m", start, end)
    assert gaps == {}, f"sealed short day still flagged as gap: {gaps}"


@pytest.mark.asyncio
async def test_unsealed_short_day_is_a_gap_before_sealing(service_and_fetch):
    """Pre-seal sanity: a short day with a coverage row but sealed=false IS a gap
    (so it gets fetched once). Guards against the seal logic masking real gaps."""
    svc, calls, closed_day = service_and_fetch
    # Pre-seed a short, unsealed coverage row directly.
    svc._db.pool.coverage[("BTCUSDT", "5m", closed_day)] = {"candle_count": 144, "sealed": False}
    start = datetime(closed_day.year, closed_day.month, closed_day.day, tzinfo=UTC)
    end = start + timedelta(days=1) - timedelta(seconds=1)

    gaps = await svc.get_coverage_gaps(["BTCUSDT"], "5m", start, end)
    assert closed_day in gaps.get("BTCUSDT", []), "unsealed short day must be a gap"
