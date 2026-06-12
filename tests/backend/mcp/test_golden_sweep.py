"""P4 acceptance + security guards — AC-005/006/007, allow-list fail-on-new-field."""
from __future__ import annotations

import pytest

from backend.mcp.tools.optimizer.apply import SWEEPABLE_FIELDS
from backend.mcp.tools.optimizer.orchestrator import run_sweep_inproc


class _GoldenRunner:
    """Deterministic metrics: a single config (leverage=10, tp=200) is the known
    winner; everything else is clearly worse."""

    async def run_one(self, config, signals, snapshot, instrument_info, *, deadline=None):
        lev = config.get("leverage", 0)
        tp = config.get("take_profit_pct", 0)
        is_winner = (lev == 10 and tp == 200.0)
        return {
            "sharpe": 3.0 if is_winner else 1.0,
            "total_return": 30.0 if is_winner else 8.0,
            "max_drawdown": 8.0 if is_winner else 12.0,
            "total_trades": 50,
            "top_trade_pnl_share": 0.2,
            "expectancy": 2.0,
        }


@pytest.mark.asyncio
async def test_golden_sweep_finds_known_winner_with_uplift_and_verdict():
    """AC-005/007: the committed golden sweep crowns the expected winner that
    clears the full FR-018 bar, with uplift + verdict + caveat + provenance."""
    space = {"leverage": [5, 10, 20], "take_profit_pct": [100.0, 150.0, 200.0]}
    baseline = {"sharpe": 1.0, "total_return": 8.0, "max_drawdown": 12.0, "expectancy": 1.0}
    result = await run_sweep_inproc(
        runner=_GoldenRunner(),
        space=space, base={"capital_pct": 5.0}, strategy="grid",
        objective="total_return", signals=[], snapshot={}, instrument_info={},
        baseline_metrics=baseline,
    )
    winner = result["winner"]
    assert winner is not None, "expected a robust winner"
    # the known winner config
    assert winner["config"]["leverage"] == 10
    assert winner["config"]["take_profit_pct"] == 200.0
    # full FR-018 bar evidence
    assert winner["uplift"]["delta_total_return"] > 0
    assert winner["verdict"] in ("robust", "moderate")
    # provenance: every winner carries its config_hash
    assert len(winner["config_hash"]) == 64
    # fidelity caveat present
    assert "1%" in result["fidelity_caveat"] or "approximate" in result["fidelity_caveat"]
    # deterministic
    r2 = await run_sweep_inproc(
        runner=_GoldenRunner(), space=space, base={"capital_pct": 5.0},
        strategy="grid", objective="total_return", signals=[], snapshot={},
        instrument_info={}, baseline_metrics=baseline,
    )
    assert r2["winner"]["config_hash"] == winner["config_hash"]


@pytest.mark.asyncio
async def test_null_result_honesty():
    """AC-006: nothing beats an unbeatable baseline -> keep current, no winner."""
    result = await run_sweep_inproc(
        runner=_GoldenRunner(),
        space={"leverage": [5, 20]}, base={}, strategy="grid",
        objective="total_return", signals=[], snapshot={}, instrument_info={},
        baseline_metrics={"sharpe": 99.0, "total_return": 999.0, "max_drawdown": 2.0},
    )
    assert result["winner"] is None
    assert result["keep_current"] is True


def test_allow_list_fail_on_new_autotradeconfig_field():
    """Security: every AutoTradeConfig field must be explicitly classified as
    sweepable or deny. A new unclassified field FAILS the build (so a future
    live-enabling field can never be silently auto-admitted)."""
    from backend.schemas import AutoTradeConfig

    model_fields = set(AutoTradeConfig.model_fields.keys())
    # fields we deliberately exclude from sweeping (identity + live-enabling +
    # AI-manager toggles + per-account bindings)
    KNOWN_DENY = {
        "account_id",          # identity
        "ai_manager_enabled",  # AI-manager toggle (out of scope for sweep)
        "ai_pause_cycles",
        "ai_manager_capabilities",  # per-scan AI-manager capability selection (out of scope for sweep)
        "symbol_blacklist",    # large/free-form lists — not swept
        "symbol_whitelist",
        # ── Regime Multi-Strategy fields (merged after the MCP optimizer was
        # built). DENIED from sweeping: the optimizer has no model of MR/regime
        # strategy interactions, so it must NOT silently auto-tune these
        # money-critical knobs. They stay fail-closed (not in SWEEPABLE_FIELDS)
        # until a human deliberately promotes specific numeric ones. Toggles,
        # enums, human-ack gates, and free-form hour lists are deny by nature.
        "mean_reversion_enabled", "mr_short_enabled", "mr_long_enabled",
        "mr_long_ack_requested",          # explicit human-ack gate — never auto-swept
        "strategy_cohort",                # routing identity (which strategy runs)
        "mr_regime", "mr_mean_interval", "mr_mean_period",
        "mr_capital_pct", "mr_leverage", "mr_max_trades",
        "mr_target_capture_pct", "mr_tight_stop_pct", "mr_time_stop_minutes",
        "mr_min_edge_pct", "mr_extreme_min_abs_score",
        "regime_filter_enabled", "regime_staleness_minutes",
        "regime_trend_ema_dist_pct", "regime_volatile_atr",
        "session_filter_enabled", "session_allowed_hours_utc", "session_blocked_hours_utc",
        "btc_vol_filter_enabled", "btc_vol_interval", "btc_vol_lookback_candles",
        "btc_vol_min_threshold", "btc_vol_max_threshold",
        # ── Cool Off Time fields. DENIED from sweeping: these are risk-management
        # pacing knobs (pause-after-outcome), not strategy parameters. The optimizer
        # must never auto-tune how long an account halts after a win/loss streak;
        # they stay fail-closed until a human deliberately promotes them.
        "cooloff_on_success_enabled", "cooloff_on_success_minutes",
        "cooloff_on_failure_enabled", "cooloff_on_failure_minutes",
        "cooloff_on_double_success_enabled", "cooloff_on_double_success_minutes",
        "cooloff_on_double_failure_enabled", "cooloff_on_double_failure_minutes",
    }
    classified = SWEEPABLE_FIELDS | KNOWN_DENY
    unclassified = model_fields - classified
    assert not unclassified, (
        f"AutoTradeConfig gained unclassified field(s) {unclassified}; classify "
        f"each as sweepable (apply.SWEEPABLE_FIELDS) or deny before merge."
    )


def test_sweepable_fields_are_real_model_fields():
    """No SWEEPABLE_FIELDS entry may reference a non-existent field."""
    from backend.schemas import AutoTradeConfig

    model_fields = set(AutoTradeConfig.model_fields.keys())
    stray = SWEEPABLE_FIELDS - model_fields
    assert not stray, f"SWEEPABLE_FIELDS references non-existent fields: {stray}"
