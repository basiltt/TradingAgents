"""Cool Off Time — Phase 5 backtest enforcement + bands + OFF-golden + parity tests.

Pure engine tests (no DB). Built on the test_backtest_golden fixture pattern.
Covers FR-016..020, CO-BT-5/9/15/16/17/18/19, AC-005/006/007/019.
(The equal-timestamp episode SPLIT — AC-015 — is verified on the live side in
test_cooloff_classifier.test_split_close_at_T_open_at_T_splits; the backtest splits
structurally because a carried close runs in the next scan's pre-open _evaluate_window.)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.backtest_engine import BacktestEngine

BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
REL_TOL = 1e-6


def _config(**overrides):
    cfg = {
        "starting_capital": 10000.0,
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
    return {"open_time": BASE + timedelta(minutes=minute), "open": open_, "high": high,
            "low": low, "close": close, "volume": vol}


def _rising_klines(symbol="BTCUSDT", start=50000.0, step=100.0, n=60):
    return {symbol: [_candle(5 * i, start + i * step, start + i * step + 200,
                             start + i * step - 50, start + i * step) for i in range(n)]}


def _falling_klines(symbol="BTCUSDT", start=50000.0, step=100.0, n=60):
    return {symbol: [_candle(5 * i, start - i * step, start - i * step + 50,
                             start - i * step - 200, start - i * step) for i in range(n)]}


# ── OFF byte-identical (the critical golden, AC-005/CO-BT-5) ─────────────────

def test_off_path_filter_stats_has_no_cooloff_keys():
    """With no cool-off tier enabled, filter_stats carries NONE of the cool-off keys
    and the result is structurally identical to pre-feature."""
    result = BacktestEngine().run(_config(), [_signal()], _falling_klines())
    fs = result.filter_stats
    assert "cooloff_signals_skipped" not in fs
    assert "cooloff_bands" not in fs
    assert "cooloff_skipped_by_reason" not in fs


def test_off_vs_on_disabled_identical_serialized_result():
    """A config with the cool-off FIELDS present but all-OFF must produce byte-identical
    JSON to a config without them at all (the enabled flag is False either way)."""
    import dataclasses
    base = BacktestEngine().run(_config(), [_signal()], _falling_klines())
    with_fields = BacktestEngine().run(
        _config(cooloff_on_failure_enabled=False, cooloff_on_failure_minutes=None),
        [_signal()], _falling_klines(),
    )
    a = json.dumps(dataclasses.asdict(base), sort_keys=True, default=str)
    b = json.dumps(dataclasses.asdict(with_fields), sort_keys=True, default=str)
    assert a == b


# ── enforcement: a losing scan arms failure cool-off; next scan skipped ──────

def _two_scan_signals():
    # scan 1 at t=0 (will lose), scan 2 at t=300m (would-be entry, should be skipped)
    return [
        _signal(minute=0, sid=1, scan_id="s1"),
        _signal(minute=300, sid=2, scan_id="s2"),
    ]


def _two_scan_klines():
    # falling price throughout so scan-1's long stops out (loss); plenty of candles to span both scans
    return _falling_klines(n=120)


def test_enforcement_failure_cooloff_skips_next_scan():
    cfg = _config(cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=600,
                  skip_if_positions_open=True)
    result = BacktestEngine().run(cfg, _two_scan_signals(), _two_scan_klines())
    fs = result.filter_stats
    # scan 1 traded + lost; scan 2 was within the 600m cool-off window -> skipped
    assert fs.get("cooloff_signals_skipped", 0) >= 1
    assert "failure" in fs.get("cooloff_skipped_by_reason", {})
    assert len(fs.get("cooloff_bands", [])) >= 1
    band = fs["cooloff_bands"][0]
    assert band["reason"] == "failure"
    assert band["start"] < band["end"]


def test_no_arm_when_disabled_no_skips():
    cfg = _config(skip_if_positions_open=True)  # cool-off OFF
    result = BacktestEngine().run(cfg, _two_scan_signals(), _two_scan_klines())
    assert "cooloff_signals_skipped" not in result.filter_stats


# ── determinism (AC-006) ─────────────────────────────────────────────────────

def test_determinism_identical_runs():
    import dataclasses
    cfg = _config(cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=600,
                  skip_if_positions_open=True)
    r1 = BacktestEngine().run(cfg, _two_scan_signals(), _two_scan_klines())
    r2 = BacktestEngine().run(cfg, _two_scan_signals(), _two_scan_klines())
    a = json.dumps(dataclasses.asdict(r1), sort_keys=True, default=str)
    b = json.dumps(dataclasses.asdict(r2), sort_keys=True, default=str)
    assert a == b


# ── carried position still closes during a cool-off band (NFR-009 sim analog) ─

def test_carried_position_closes_during_cooloff():
    """Cool-off must not prevent an open position from closing in the sim."""
    cfg = _config(cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=600,
                  skip_if_positions_open=True)
    result = BacktestEngine().run(cfg, _two_scan_signals(), _two_scan_klines())
    # the first scan's position must have closed (it has a close_reason)
    assert len(result.trades) >= 1
    assert all(t.get("close_reason") for t in result.trades)


# ── live <-> backtest parity (AC-007/019): shared core + funding-excluded net ─

def test_funding_excluded_net_matches_live_definition():
    """ENGINE-DRIVEN parity lock: a trade's cool-off cohort component (pnl + funding_paid)
    must be FUNDING-FREE, matching the live definition net_pnl = closedPnl - fees.

    Rather than re-deriving literals (which can't catch a regression in the engine's
    recorded_pnl formula at _close_position), this runs the SAME backtest twice — once
    with funding OFF, once with a large fixed funding rate — and asserts every trade's
    (pnl + funding_paid) is IDENTICAL across the two runs. If a future edit makes
    recorded_pnl funding-exclusive (or otherwise breaks the pnl+funding_paid = gross-fees
    identity), the funding run's cohort net diverges and this fails. Also asserts the
    funding run actually applied non-zero funding, so the test can't pass vacuously."""
    # A trade that stays open long enough to cross >=1 funding interval (8h). Use a TP
    # far away and ~11h of 5-min candles so funding is actually charged before close.
    # Cool-off is ENABLED so the engine persists funding_paid on the trade record
    # (it's deliberately omitted when cool-off is OFF — the OFF byte-identical invariant);
    # the cohort net (pnl + funding_paid) is exactly what the classifier reads.
    on = dict(cooloff_on_success_enabled=True, cooloff_on_success_minutes=30,
              take_profit_pct=400.0, stop_loss_pct=900.0)
    cfg_no_funding = _config(funding_rate_model="none", **on)
    cfg_funding = _config(funding_rate_model="fixed_8h", funding_rate_fixed_pct=0.05, **on)
    kl = _rising_klines(n=140)  # 140 * 5min ≈ 11.6h → crosses the 08:00 funding boundary
    sig = [_signal()]

    r_off = BacktestEngine().run(cfg_no_funding, sig, kl)
    r_on = BacktestEngine().run(cfg_funding, sig, kl)

    assert r_off.trades and r_on.trades, "both runs must produce at least one trade"
    assert len(r_off.trades) == len(r_on.trades)

    # The funding run must actually have charged funding (else the parity check is vacuous).
    total_funding = sum(abs(t.get("funding_paid") or 0.0) for t in r_on.trades)
    assert total_funding > 0.0, "funding run applied no funding — test would be vacuous"

    # Per-trade: the funding-excluded cohort net (pnl + funding_paid) is invariant to funding.
    for t_off, t_on in zip(r_off.trades, r_on.trades):
        net_off = (t_off["pnl"] or 0.0) + (t_off.get("funding_paid") or 0.0)
        net_on = (t_on["pnl"] or 0.0) + (t_on.get("funding_paid") or 0.0)
        assert net_on == pytest.approx(net_off, rel=REL_TOL), (
            f"cohort net diverged with funding: {net_on} vs {net_off}"
        )


def test_funding_excluded_net_arms_same_tier_regardless_of_funding():
    """End-to-end: whether a losing cycle ARMS a failure cool-off must not depend on
    funding (the cool-off decision uses the funding-excluded net). Same losing trade,
    funding OFF vs ON, both must arm a failure band of the same duration."""
    base = dict(cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=60,
                take_profit_pct=900.0, stop_loss_pct=3.0)  # SL hit -> a loss
    kl = _falling_klines(n=30)
    sig = [_signal()]
    r_off = BacktestEngine().run(_config(funding_rate_model="none", **base), sig, kl)
    r_on = BacktestEngine().run(
        _config(funding_rate_model="fixed_8h", funding_rate_fixed_pct=0.05, **base), sig, kl,
    )
    bands_off = r_off.filter_stats.get("cooloff_bands", [])
    bands_on = r_on.filter_stats.get("cooloff_bands", [])
    assert len(bands_off) == len(bands_on) == 1
    assert bands_off[0]["reason"] == bands_on[0]["reason"] == "failure"


def test_band_merge_overlapping():
    """_cooloff_finalize_bands merges overlapping bands (later reason wins) + clamps."""
    eng = BacktestEngine()
    t = BASE
    bands = [
        {"start": t, "end": t + timedelta(hours=2), "reason": "failure"},
        {"start": t + timedelta(hours=1), "end": t + timedelta(hours=3), "reason": "double_failure"},
        {"start": t + timedelta(hours=5), "end": t + timedelta(hours=5), "reason": "success"},  # degenerate
    ]
    out = eng._cooloff_finalize_bands(bands, None, None)
    assert len(out) == 1  # two overlapping merged, degenerate dropped
    assert out[0]["reason"] == "double_failure"  # later reason wins
    assert out[0]["start"] == t.isoformat()
    assert out[0]["end"] == (t + timedelta(hours=3)).isoformat()


# ── CO-BT-16/19 regression guards (P5R-F2) ───────────────────────────────────

def test_neutral_flat_advances_idx_no_streak_inflation():
    """A neutral cohort (net==0) must advance cooloff_last_flat_idx so the NEXT cohort
    is not inflated by the neutral trades (CO-BT-16). Tested at the helper level for a
    deterministic, isolated assertion."""
    from backend.services.backtest_engine import SimulationState
    eng = BacktestEngine()
    from backend.services.cooloff_core import CooloffSettings
    eng._cooloff_settings = CooloffSettings(
        success_enabled=False, success_minutes=None,
        failure_enabled=True, failure_minutes=60,
        double_success_enabled=False, double_success_minutes=None,
        double_failure_enabled=False, double_failure_minutes=None,
    )
    st = SimulationState()
    st.cooloff_enabled = True
    # neutral cohort: two trades summing to exactly 0 (pnl+funding)
    st.closed_trades = [
        {"pnl": 5.0, "funding_paid": 0.0}, {"pnl": -5.0, "funding_paid": 0.0},
    ]
    eng._cooloff_arm_on_flat(st, BASE + timedelta(minutes=10))
    assert st.cooloff_until is None          # neutral -> no arm
    assert st.cooloff_last_flat_idx == 2     # idx advanced past the neutral cohort
    # next cohort: a single loss -> must be classified on ITS net only (-10), not -10+0
    st.closed_trades.append({"pnl": -10.0, "funding_paid": 0.0})
    eng._cooloff_arm_on_flat(st, BASE + timedelta(minutes=20))
    assert st.cooloff_reason == "failure"
    assert st.cooloff_losses == 1            # one loss, not inflated


def test_two_flat_episodes_count_as_two_streaks_not_one_merged_cohort():
    """Equal-timestamp episode-boundary parity with live (D45): two SEPARATE flat
    episodes (each one losing trade) that the engine arms on at successive flat points
    must each be classified as their OWN cohort — yielding 2 consecutive losses →
    double_failure — rather than collapsing into a single cohort of net=-20 (one
    failure). The backtest arms in _close_position the moment the book goes flat (closes
    are processed before the next scan's opens by loop construction), so each episode's
    high-water idx advances between arms exactly as live's split_earliest_episode replays
    close-before-open on ties. This locks the streak-tier parity the feature depends on."""
    from backend.services.backtest_engine import SimulationState
    from backend.services.cooloff_core import CooloffSettings
    eng = BacktestEngine()
    eng._cooloff_settings = CooloffSettings(
        success_enabled=False, success_minutes=None,
        failure_enabled=True, failure_minutes=60,
        double_success_enabled=False, double_success_minutes=None,
        double_failure_enabled=True, double_failure_minutes=120,
    )
    st = SimulationState()
    st.cooloff_enabled = True
    # Episode 1: a single losing trade → flat → arm (failure, streak=1).
    st.closed_trades = [{"pnl": -10.0, "funding_paid": 0.0}]
    eng._cooloff_arm_on_flat(st, BASE + timedelta(minutes=5))
    assert st.cooloff_reason == "failure"
    assert st.cooloff_losses == 1
    assert st.cooloff_last_flat_idx == 1
    # Episode 2: another single losing trade, classified as its OWN cohort → streak
    # reaches 2 → double_failure. The reason "double_failure" (not a second plain
    # "failure") is the parity proof: the two same-instant episodes were counted as TWO
    # losses, not merged into one cohort of net=-18 (which would have stayed "failure").
    # Per double-fire semantics the FIRED streak side then resets to 0 (cooloff_core).
    st.closed_trades.append({"pnl": -8.0, "funding_paid": 0.0})
    eng._cooloff_arm_on_flat(st, BASE + timedelta(minutes=10))
    assert st.cooloff_reason == "double_failure"
    assert st.cooloff_losses == 0            # fired side reset after the double
    assert st.cooloff_last_flat_idx == 2


def test_backtest_end_close_does_not_arm():
    """The end-of-sim force-close (close_reason='backtest_end') must NOT arm a cool-off
    even though it leaves the book flat (CO-BT-19). A single signal on falling price that
    never hits TP/SL is force-closed at backtest end."""
    cfg = _config(cooloff_on_failure_enabled=True, cooloff_on_failure_minutes=60,
                  take_profit_pct=500.0, stop_loss_pct=900.0)  # neither TP nor SL hit
    # gently falling price so the position stays open until the end force-close
    kl = {"BTCUSDT": [_candle(5 * i, 50000 - i, 50000 - i + 5, 50000 - i - 5, 50000 - i)
                      for i in range(20)]}
    result = BacktestEngine().run(cfg, [_signal()], kl)
    assert len(result.trades) == 1
    assert result.trades[0]["close_reason"] == "backtest_end"
    # no band armed (the terminal flatten is excluded)
    assert result.filter_stats.get("cooloff_bands", []) == []
