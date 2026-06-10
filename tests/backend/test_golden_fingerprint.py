"""Golden-master fingerprint tests (Phase P0) — the parity oracle.

These freeze the CURRENT engine output as stored snapshots covering every
close-rule branch, and assert the three-way Σ reconciliation on each. Later
optimization phases (P1-P6) re-run these; any DISCRETE divergence (which trades
happened / why) or >epsilon MONEY divergence fails CI.

This file changes NO production code — it is pure parity scaffolding built on the
existing engine seam `BacktestEngine().run(config, signals, klines, ...)`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.backtest_engine import BacktestEngine
from tests.backend.golden import (
    assert_matches_snapshot,
    assert_reconciles,
    diff_fingerprints,
    fingerprint,
)

BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
START_CAP = 10000.0


# --------------------------------------------------------------------------- #
# Builders (mirror test_backtest_golden.py so snapshots are comparable)
# --------------------------------------------------------------------------- #

def _config(**overrides):
    cfg = {
        "starting_capital": START_CAP,
        "leverage": 10,
        "capital_pct": 10.0,
        "take_profit_pct": 5.0,
        "stop_loss_pct": 50.0,
        "direction": "straight",
        "fee_rate_pct": 0.055,
        "slippage_bps": 0,
        "funding_rate_model": "none",
        "execution_mode": "batch",
        "max_trades": 999,
        "skip_if_positions_open": False,
    }
    cfg.update(overrides)
    return cfg


def _signal(ticker="BTCUSDT", direction="buy", price=50000.0, minute=0, sid=1, scan_id="s1"):
    return {
        "id": sid, "ticker": ticker, "direction": direction, "confidence": "high",
        "score": 8, "signal_time": BASE + timedelta(minutes=minute), "scan_id": scan_id,
        "signal_source": "structured", "analysis_price": price,
    }


def _candle(minute, open_, high, low, close, vol=100.0):
    return {
        "open_time": BASE + timedelta(minutes=minute),
        "open": open_, "high": high, "low": low, "close": close, "volume": vol,
    }


def _rising_klines(symbol="BTCUSDT", start=50000.0, step=100.0, n=60):
    return {symbol: [_candle(5 * i, start + i * step, start + i * step + 200,
                             start + i * step - 50, start + i * step) for i in range(n)]}


def _falling_klines(symbol="BTCUSDT", start=50000.0, step=100.0, n=60):
    return {symbol: [_candle(5 * i, start - i * step, start - i * step + 50,
                             start - i * step - 200, start - i * step) for i in range(n)]}


def _flat_klines(symbol="BTCUSDT", price=50000.0, n=600):
    return {symbol: [_candle(5 * i, price, price + 10, price - 10, price) for i in range(n)]}


# Each scenario: (snapshot_name, config, signals, klines). Covers every close-rule
# branch + selection-mode + the P0-latch fixtures the plan calls out.
SCENARIOS = [
    ("long_take_profit", _config(), [_signal()], _rising_klines()),
    ("long_stop_loss", _config(), [_signal()], _falling_klines()),
    ("reverse_direction", _config(direction="reverse"), [_signal()], _rising_klines()),
    ("trailing_profit",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, trailing_profit_pct=2.0),
     [_signal()], _rising_klines()),
    ("close_on_profit",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, close_on_profit_pct=5.0, target_goal_value=100.0),
     [_signal()], _rising_klines()),
    ("max_duration",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, max_trade_duration_hours=1.0),
     [_signal()], _flat_klines(n=30)),
    ("breakeven_timeout",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, breakeven_timeout_hours=1.0),
     [_signal()],
     {"BTCUSDT": ([_candle(5 * i, 50000.0, 50010.0, 49990.0, 50000.0) for i in range(14)]
                  + [_candle(5 * i, 50100.0, 50150.0, 50050.0, 50100.0) for i in range(14, 30)])}),
    ("funding_fixed_8h",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, max_trade_duration_hours=48.0,
             funding_rate_model="fixed_8h", funding_rate_fixed_pct=0.01),
     [_signal()], _flat_klines(n=600)),
    ("equity_drop",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, max_drawdown_pct=2.0),
     [_signal()], _falling_klines()),
    ("smart_drawdown",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, max_drawdown_pct=2.0, smart_drawdown_close=True),
     [_signal()], _falling_klines()),
    ("slippage_applied", _config(slippage_bps=10), [_signal()], _rising_klines()),
    ("immediate_mode", _config(execution_mode="immediate"), [_signal()], _rising_klines()),
    # P0-latch fixtures the plan flags as previously-uncovered:
    ("skip_if_positions_open",
     _config(take_profit_pct=500.0, stop_loss_pct=500.0, skip_if_positions_open=True),
     [_signal(minute=0, sid=1, scan_id="s1"), _signal(minute=5, sid=2, scan_id="s2")],
     _rising_klines()),
    ("multi_symbol_batch",
     _config(),
     [_signal(ticker="BTCUSDT", sid=1), _signal(ticker="ETHUSDT", price=3000.0, sid=2)],
     {**_rising_klines("BTCUSDT"), **_rising_klines("ETHUSDT", start=3000.0, step=10.0)}),
]


@pytest.mark.parametrize("name,config,signals,klines", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_golden_snapshot(name, config, signals, klines):
    """Each close-rule branch: capture/assert the stored-snapshot oracle."""
    result = BacktestEngine().run(config, signals, klines)
    assert_matches_snapshot(f"p0_{name}", result)


@pytest.mark.parametrize("name,config,signals,klines", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_three_way_reconciliation(name, config, signals, klines):
    """Σ trade.pnl == net_profit == final_equity − start on EVERY fixture."""
    result = BacktestEngine().run(config, signals, klines)
    assert_reconciles(result, config["starting_capital"])


def test_reconciliation_meta_catches_broken_term():
    """Meta-test: prove the three-way Σ actually catches a corrupted term.

    Remove one trade's pnl from the sum and confirm assert_reconciles turns RED —
    this guards against a tautological reconciliation that would pass on a bug.
    """
    result = BacktestEngine().run(_config(), [_signal()], _rising_klines())
    assert result.trades, "fixture must produce at least one trade"

    class _Tampered:
        # net_profit/final_equity stay consistent, but a trade pnl is corrupted →
        # the per-trade-sum term (1st) must diverge from net_profit (2nd).
        metrics = result.metrics
        trades = [dict(t) for t in result.trades]
    _Tampered.trades[0]["pnl"] = _Tampered.trades[0]["pnl"] + 999.0

    with pytest.raises(AssertionError, match="per-trade-sum"):
        assert_reconciles(_Tampered, START_CAP)


def test_degenerate_zero_trades_has_total_trades_key():
    """A config that filters out every signal still yields total_trades=0 (the
    frontend trap: BacktestResultsPage routes to 'no trades' only if the KEY is
    absent, never if it is 0). Guards the metrics contract."""
    # min_score above the signal score → everything filtered.
    result = BacktestEngine().run(_config(min_score=10.0), [_signal(price=50000.0)],
                                  _rising_klines(start=50000.0))
    assert result.trades == []
    assert "total_trades" in result.metrics
    assert result.metrics["total_trades"] == 0


def test_noop_byte_identity_fine_klines():
    """The golden NO-OP guarantee: empty/None fine_klines ⇒ byte-identical to the
    pure 5m path. This is the invariant the drill-down phases must preserve."""
    cfg, sigs, klines = _config(), [_signal()], _rising_klines()
    base = BacktestEngine().run(cfg, sigs, klines)
    none = BacktestEngine().run(cfg, sigs, klines, fine_klines=None)
    empty = BacktestEngine().run(cfg, sigs, klines, fine_klines={})
    fp_base = fingerprint(base)
    assert diff_fingerprints(fp_base, fingerprint(none)).ok
    assert diff_fingerprints(fp_base, fingerprint(empty)).ok


def test_fingerprint_self_identity():
    """A fingerprint diffed against itself is always identical (sanity on the comparator)."""
    result = BacktestEngine().run(_config(), [_signal()], _rising_klines())
    fp = fingerprint(result)
    assert diff_fingerprints(fp, fp).ok
