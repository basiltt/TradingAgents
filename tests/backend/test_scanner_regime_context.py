"""Phase 2 — scanner per-scan regime-context compute (spec FR-2, FR-5).

Tests the flag helper + the _build_scan_regime_context method in isolation by
mocking the LIVE Bybit kline fetch (get_bybit_klines -> CSV) and the DB skew
query, including the fail-open paths and the Bybit interval code ("60" = 1h).

The BTC data is read live from Bybit (NOT the kline_cache table, which only
holds stale 5m backtest candles), so these tests patch get_bybit_klines.
"""
import asyncio

import pytest

import backend.services.scanner_service as ss


def test_flag_helper_off_by_default(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_REGIME_CONTEXT", raising=False)
    assert ss._regime_context_enabled() is False


def test_flag_helper_on(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "1")
    assert ss._regime_context_enabled() is True
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "true")
    assert ss._regime_context_enabled() is True


def test_btc_interval_is_bybit_1h_code():
    # Bybit uses numeric interval codes: "60" = 1 hour. (NOT "1h", which the
    # live Bybit API would reject, and NOT a kline_cache lookup.)
    assert ss.REGIME_BTC_INTERVAL_BYBIT == "60"


def _make_scanner():
    # Construct a bare scanner with stubbable attrs (no real services).
    s = ss.ScannerService.__new__(ss.ScannerService)
    s._db = None
    s._kline_cache = None
    return s


def _rising_csv(n=40):
    # Bybit returns rows NEWEST-FIRST; closes ascend with time, so newest has the
    # highest close. Emit newest-first to prove the parser sorts correctly.
    lines = ["timestamp,open,high,low,close,volume"]
    for i in range(n - 1, -1, -1):  # newest (i=n-1) first
        ts = 1_000_000 + i * 3_600_000
        c = 100 + i
        lines.append(f"{ts},{c},{c+1},{c-1},{c},10")
    return "\n".join(lines)


def _patch_klines(monkeypatch, csv_or_exc):
    def _fake(symbol, interval, start, end, *a, **k):
        assert symbol == "BTCUSDT"
        assert interval == "60"  # Bybit 1h code
        if isinstance(csv_or_exc, Exception):
            raise csv_or_exc
        return csv_or_exc
    monkeypatch.setattr(
        "tradingagents.dataflows.bybit_data.get_bybit_klines", _fake, raising=True
    )


def test_build_regime_context_off_returns_empty(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_REGIME_CONTEXT", raising=False)
    s = _make_scanner()
    out = asyncio.run(s._build_scan_regime_context("scan-1"))
    assert out == ""


def test_build_regime_context_on_rising(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "1")
    _patch_klines(monkeypatch, _rising_csv())
    s = _make_scanner()

    class _DB:
        async def get_recent_signal_skew(self, **kw):
            return {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 200, "window": 200}
    s._db = _DB()

    out = asyncio.run(s._build_scan_regime_context("scan-1"))
    assert "rising" in out.lower()
    assert "89" in out


def test_build_regime_context_btc_fetch_fail_still_emits_skew(monkeypatch):
    # If the live BTC fetch fails, we still emit the skew-only block (no crash).
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "1")
    _patch_klines(monkeypatch, RuntimeError("bybit down"))
    s = _make_scanner()

    class _DB:
        async def get_recent_signal_skew(self, **kw):
            return {"short_pct": 89.0, "long_pct": 8.0, "sample_n": 200, "window": 200}
    s._db = _DB()

    out = asyncio.run(s._build_scan_regime_context("scan-1"))
    # BTC direction absent, but skew line present
    assert "89" in out
    assert "rising" not in out.lower() and "falling" not in out.lower()


def test_build_regime_context_empty_klines_no_btc(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "1")
    _patch_klines(monkeypatch, "timestamp,open,high,low,close,volume")  # header only
    s = _make_scanner()
    s._db = None
    out = asyncio.run(s._build_scan_regime_context("scan-1"))
    assert out == ""  # no BTC, no skew -> empty


def test_build_regime_context_fail_open_on_db_error(monkeypatch):
    # The DB skew path raising must fail-open the whole compute.
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "1")
    _patch_klines(monkeypatch, _rising_csv())
    s = _make_scanner()

    class _DB:
        async def get_recent_signal_skew(self, **kw):
            raise RuntimeError("db down")
    s._db = _DB()
    out = asyncio.run(s._build_scan_regime_context("scan-1"))
    assert out == ""  # fail-open across the whole compute


def test_build_regime_context_times_out_on_hang(monkeypatch):
    # A HANG (not an exception) in the skew query must still degrade to "" via
    # the wall-clock budget, never stalling the scan's fan-out.
    monkeypatch.setenv("TRADINGAGENTS_REGIME_CONTEXT", "1")
    monkeypatch.setattr(ss, "REGIME_COMPUTE_TIMEOUT_S", 0.2)
    _patch_klines(monkeypatch, _rising_csv())
    s = _make_scanner()

    class _HangDB:
        async def get_recent_signal_skew(self, **kw):
            await asyncio.sleep(5)  # simulate a stalled DB
            return {}
    s._db = _HangDB()
    out = asyncio.run(s._build_scan_regime_context("scan-1"))
    assert out == ""  # timed out -> fail-open
