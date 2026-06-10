"""Phase P3 tests: _MarkIndex parity + the RC-2 quadratic-kill speedup.

The bisect-based mark lookup must return EXACTLY the close the old linear prefix
scan would (parity), and must turn the per-mark cost from O(T) into O(log N) so a
long carried-position timeline no longer scales quadratically.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from backend.services.backtest_engine import _MarkIndex

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _series(n, step_min=5):
    return [{"open_time": BASE + timedelta(minutes=step_min * i),
             "open": 100.0 + i, "high": 100.0 + i, "low": 100.0 + i,
             "close": 100.0 + i, "volume": 1.0} for i in range(n)]


def _linear_mark(series, t, default):
    """The ORIGINAL linear-scan semantics, kept here as the parity oracle."""
    mark = default
    for k in series:
        if k["open_time"] <= t:
            mark = k["close"]
        else:
            break
    return mark


class TestMarkIndexParity:
    def test_matches_linear_scan_at_every_timestamp(self):
        series = _series(200)
        klines = {"BTCUSDT": series}
        idx = _MarkIndex(klines)
        # probe at, between, before, and after every candle boundary
        for i in range(len(series)):
            for offset in (timedelta(0), timedelta(minutes=2), timedelta(minutes=-1)):
                t = series[i]["open_time"] + offset
                assert idx.mark_at_or_before("BTCUSDT", t, -1.0) == _linear_mark(series, t, -1.0)

    def test_before_first_candle_returns_default(self):
        idx = _MarkIndex({"BTCUSDT": _series(10)})
        t = BASE - timedelta(minutes=10)
        assert idx.mark_at_or_before("BTCUSDT", t, 42.0) == 42.0

    def test_after_last_candle_returns_last_close(self):
        series = _series(10)
        idx = _MarkIndex({"BTCUSDT": series})
        t = series[-1]["open_time"] + timedelta(days=1)
        assert idx.mark_at_or_before("BTCUSDT", t, -1.0) == series[-1]["close"]

    def test_exact_boundary_is_inclusive(self):
        series = _series(10)
        idx = _MarkIndex({"BTCUSDT": series})
        # open_time <= t is inclusive → at exactly candle[3] open, mark is candle[3] close
        assert idx.mark_at_or_before("BTCUSDT", series[3]["open_time"], -1.0) == series[3]["close"]

    def test_unknown_symbol_returns_default(self):
        idx = _MarkIndex({"BTCUSDT": _series(10)})
        assert idx.mark_at_or_before("NOPE", BASE, 7.0) == 7.0

    def test_empty_series_returns_default(self):
        idx = _MarkIndex({"BTCUSDT": []})
        assert idx.mark_at_or_before("BTCUSDT", BASE, 7.0) == 7.0


class TestMarkIndexSpeedup:
    def test_bisect_far_faster_than_linear_on_long_series(self):
        """On a long series probed many times near the END (worst case for the
        linear scan), bisect must be dramatically faster — the RC-2 quadratic kill."""
        n = 20000
        series = _series(n)
        klines = {"BTCUSDT": series}
        idx = _MarkIndex(klines)  # built once (amortized, as in a real run)
        probes = [series[-1]["open_time"] - timedelta(minutes=5 * (j % 50)) for j in range(2000)]

        t0 = time.perf_counter()
        for t in probes:
            idx.mark_at_or_before("BTCUSDT", t, -1.0)
        bisect_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        for t in probes:
            _linear_mark(series, t, -1.0)
        linear_s = time.perf_counter() - t0

        # Bisect should be at least 10x faster probing near the end of a 20k series.
        assert bisect_s * 10 < linear_s, (
            f"bisect {bisect_s:.4f}s not >=10x faster than linear {linear_s:.4f}s"
        )
