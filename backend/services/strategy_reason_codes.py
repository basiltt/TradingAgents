"""Single source of truth for auto-trade decision reason codes (TASK-0.2).

Each ReasonCode's string value equals the legacy literal that was previously
passed to AutoTradeExecutor._emit_decision(..., reason_code, ...). Because the
enum subclasses str, existing call sites and trace output are byte-identical —
critical for the all-off golden snapshot (FR-001).

New F1/F2/F3 reason codes are appended below the legacy block.
"""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    """Auto-trade skip/decision reason codes. Value == legacy trace string."""

    # ── Legacy (migrated verbatim from string literals in auto_trade_service) ──
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"
    ALREADY_HELD = "already_held"
    MAX_SIGNAL_AGE = "max_signal_age"
    HOLD_SIGNAL = "hold_signal"
    MAX_SAME_DIRECTION = "max_same_direction"
    MAX_SAME_SECTOR = "max_same_sector"
    ADAPTIVE_BLACKLIST = "adaptive_blacklist"
    SIGNAL_SIDES = "signal_sides"
    MIN_SCORE = "min_score"
    CONFIDENCE_FILTER = "confidence_filter"
    MAX_TRADES = "max_trades"
    TARGET_GOAL_REACHED = "target_goal_reached"
    PRICE_DRIFT = "price_drift"
    NO_BALANCE = "no_balance"

    # ── F1 — Regime/Session Entry Filter ──
    SESSION_FILTER = "session_filter"
    BTC_VOL_FILTER = "btc_vol_filter"
    VOL_UNAVAILABLE = "vol_unavailable"

    # ── F3 — Strategy-Cohort routing ──
    COHORT_MISMATCH = "cohort_mismatch"

    # ── F2 — Mean-Reversion strategy ──
    MR_REGIME_EXCLUDED = "mr_regime_excluded"
    MR_LONG_DISABLED = "mr_long_disabled"
    MR_SHORT_DISABLED = "mr_short_disabled"
    MR_LONG_UNACKNOWLEDGED = "mr_long_unacknowledged"
    MR_NO_EDGE = "mr_no_edge"
    MR_DEGENERATE_TARGET = "mr_degenerate_target"
    MR_MEAN_UNAVAILABLE = "mr_mean_unavailable"
    MR_INSUFFICIENT_HISTORY = "mr_insufficient_history"
    MR_FEE_FLOOR = "mr_fee_floor"
    MR_SL_LIQUIDATION = "mr_sl_liquidation"
    MR_INVERTED_GEOMETRY = "mr_inverted_geometry"
    MR_REGIME_STALE = "mr_regime_stale"
    MR_PRICE_UNAVAILABLE = "mr_price_unavailable"

    # ── Kill-switch (PR1-1) ──
    FEATURE_KILLED = "feature_killed"

    def __str__(self) -> str:  # ensures f-strings/logging emit the bare value
        return self.value
