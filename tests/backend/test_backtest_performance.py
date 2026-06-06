"""Performance benchmarks for the backtest engine (Phase 7, Task 7.3).

Asserts that a representative 30-day backtest completes well under the 3-second
budget (AC-001). The engine is pure/synchronous and operates on pre-loaded
klines (the "warm cache" condition), so this benchmarks the simulation hot path
without DB or network. A generous ceiling keeps the test stable across CI
hardware while still catching an algorithmic regression (e.g. an accidental
O(n^2) over candles).
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone, timedelta

import pytest

from backend.services.backtest_engine import BacktestEngine


BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

# 30 days of 5-minute candles.
CANDLES_30D_5M = 30 * 288  # 8640

# Hard budget from AC-001 is 3s; the single-symbol 30-day case is far faster, so
# we keep a tighter ceiling there to catch regressions early, with headroom for
# slow CI runners. The heavier multi-symbol case asserts against the full 3s AC.
BUDGET_SECONDS = 3.0
TIGHT_CEILING_SECONDS = 2.0


def _oscillating_klines(symbol: str, n: int) -> dict:
    """A sinusoidal price path so trades repeatedly open and hit TP/SL — exercises
    the close-rule evaluation path far more than a monotonic series would."""
    candles = []
    for i in range(n):
        mid = 50000.0 + 2000.0 * math.sin(i / 20.0)
        candles.append(
            {
                "open_time": BASE + timedelta(minutes=5 * i),
                "open": mid,
                "high": mid + 300.0,
                "low": mid - 300.0,
                "close": 50000.0 + 2000.0 * math.sin(i / 20.0 + 0.1),
                "volume": 100.0,
            }
        )
    return {symbol: candles}


def _spread_signals(n: int, span_hours: float) -> list:
    step = span_hours / max(1, n)
    return [
        {
            "id": k,
            "ticker": "BTCUSDT",
            "direction": "buy" if k % 2 == 0 else "sell",
            "confidence": "high",
            "score": 8,
            "signal_time": BASE + timedelta(hours=step * k),
            "scan_id": f"s{k}",
            "signal_source": "structured",
            "analysis_price": 50000.0,
        }
        for k in range(n)
    ]


def _perf_config(**overrides):
    cfg = {
        "starting_capital": 10000.0,
        "leverage": 10,
        "capital_pct": 5.0,
        "take_profit_pct": 5.0,
        "stop_loss_pct": 5.0,
        "direction": "straight",
        "fee_rate_pct": 0.055,
        "slippage_bps": 0,
        "funding_rate_model": "none",
        "execution_mode": "batch",
        "max_trades": 50,
        "skip_if_positions_open": False,
    }
    cfg.update(overrides)
    return cfg


class TestEnginePerformance:
    def test_30_day_backtest_under_budget(self):
        """A 30-day, 5m backtest with ~50 signals completes well under 3s."""
        klines = _oscillating_klines("BTCUSDT", CANDLES_30D_5M)
        signals = _spread_signals(50, span_hours=30 * 24)
        config = _perf_config()

        start = time.perf_counter()
        result = BacktestEngine().run(config, signals, klines)
        elapsed = time.perf_counter() - start

        # Sanity: the run actually did work (produced trades + an equity curve).
        assert len(result.trades) > 0
        assert len(result.equity_curve) > 0
        # Primary assertion: comfortably within the AC budget.
        assert elapsed < TIGHT_CEILING_SECONDS, (
            f"30-day backtest took {elapsed:.3f}s, exceeding the {TIGHT_CEILING_SECONDS}s "
            f"tight ceiling (AC budget {BUDGET_SECONDS}s)"
        )

    def test_engine_scales_roughly_linearly_in_candles(self):
        """Doubling the candle count should not super-linearly blow up runtime —
        guards against an accidental O(n^2) over the candle loop."""
        signals = _spread_signals(20, span_hours=30 * 24)
        config = _perf_config()

        def timed(n: int) -> float:
            klines = _oscillating_klines("BTCUSDT", n)
            start = time.perf_counter()
            BacktestEngine().run(config, signals, klines)
            return time.perf_counter() - start

        small = timed(CANDLES_30D_5M // 2)
        large = timed(CANDLES_30D_5M)

        # Both must be fast; the ratio guards against quadratic blowup. Use a
        # floor on `small` so timing jitter on a sub-millisecond run can't inflate
        # the ratio. Allow up to 4x (linear would be ~2x) for scheduling noise.
        assert large < TIGHT_CEILING_SECONDS
        ratio = large / max(small, 0.01)
        assert ratio < 4.0, f"runtime scaled {ratio:.1f}x for 2x candles — possible super-linear cost"

    def test_heavy_multi_symbol_load_under_budget(self):
        """A heavier, more realistic load — 5 symbols, ~86k total candles, 300
        signals, with the price-drift filter ENABLED — must still beat the 3s AC.
        This co-scales the dimensions a single-symbol benchmark leaves constant and
        exercises the per-signal filter path (which references the klines map)."""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        base_price = {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0, "BNBUSDT": 400.0, "XRPUSDT": 0.5}
        per_symbol = 2 * CANDLES_30D_5M  # ~60 days each

        klines = {}
        for sym in symbols:
            bp = base_price[sym]
            klines[sym] = [
                {
                    "open_time": BASE + timedelta(minutes=5 * i),
                    "open": bp * (1 + 0.04 * math.sin(i / 30.0)),
                    "high": bp * (1 + 0.04 * math.sin(i / 30.0)) + bp * 0.006,
                    "low": bp * (1 + 0.04 * math.sin(i / 30.0)) - bp * 0.006,
                    "close": bp * (1 + 0.04 * math.sin(i / 30.0 + 0.1)),
                    "volume": 100.0,
                }
                for i in range(per_symbol)
            ]

        signals = [
            {
                "id": k,
                "ticker": symbols[k % len(symbols)],
                "direction": "buy" if k % 2 == 0 else "sell",
                "confidence": "high",
                "score": 8,
                "signal_time": BASE + timedelta(hours=4.8 * k),
                "scan_id": f"s{k}",
                "signal_source": "structured",
                "analysis_price": base_price[symbols[k % len(symbols)]],
            }
            for k in range(300)
        ]
        config = _perf_config(max_trades=20, capital_pct=2.0, max_price_drift_pct=10.0)

        start = time.perf_counter()
        result = BacktestEngine().run(config, signals, klines)
        elapsed = time.perf_counter() - start

        assert len(result.trades) > 0
        assert elapsed < BUDGET_SECONDS, (
            f"heavy multi-symbol backtest took {elapsed:.3f}s, exceeding the AC-001 "
            f"{BUDGET_SECONDS}s budget"
        )
