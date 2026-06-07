"""Single source of truth for regime-multistrategy feature keys and cohort resolution.

Centralizes the things that were previously hand-synced across admin.py,
strategy_router.py, auto_trade_service.py and scanner_service.py — so adding a
feature or changing the kill-switch key set is a one-file edit, not a four-file hunt.
"""

from __future__ import annotations

from typing import Any, Optional

# Kill-switch feature keys understood across the system. "__all__" is the master kill.
# Per-account cohorts map to f1 (trend) / f2 (mean_reversion); f2_long is the extra
# kill checked only on the live-long fade path.
FEATURE_ALL = "__all__"
FEATURE_F1 = "f1"
FEATURE_F2 = "f2"
FEATURE_F2_LONG = "f2_long"

KILL_SWITCH_FEATURES: frozenset[str] = frozenset(
    {FEATURE_ALL, FEATURE_F1, FEATURE_F2, FEATURE_F2_LONG}
)

# Valid strategy cohorts (must match the DB CHECK on trading_accounts.strategy_cohort
# and trades.strategy_cohort, and the AutoTradeConfig.strategy_cohort Literal).
COHORTS: frozenset[str] = frozenset({"trend", "mean_reversion"})
DEFAULT_COHORT = "trend"


def feature_for_cohort(cohort: str) -> str:
    """Kill-switch feature key gating an account's cohort (trend->f1, MR->f2).

    The f2_long kill is checked separately on the long-fade path, not here.
    """
    return FEATURE_F2 if cohort == "mean_reversion" else FEATURE_F1


def resolve_cohort(scan_cohort: Optional[str], stored_cohort: Optional[str]) -> str:
    """Resolve an account's effective cohort for a scan (F3 precedence, FR-040).

    Tri-state precedence: an EXPLICIT per-scan choice wins; else the stored account
    field; else the default. The per-scan ``AutoTradeConfig.strategy_cohort`` is
    ``None`` when the form was left to inherit, so any non-None value — INCLUDING an
    explicit "trend" — is a real override (this is what makes "run trend this scan
    even though the account is stored mean_reversion" expressible). A stored cohort
    drives routing only when the scan defers (None). Invalid values are ignored.
    """
    if scan_cohort is not None and scan_cohort in COHORTS:
        return scan_cohort
    if stored_cohort and stored_cohort in COHORTS:
        return stored_cohort
    return DEFAULT_COHORT


# Triggers on which the one-time F1 session-filter override is honoured (FR-066/SD20).
# Deliberately excludes "scheduled" so a saved schedule can't carry a persistent bypass.
SESSION_OVERRIDE_TRIGGERS: frozenset[str] = frozenset({"manual", "run_now"})


def apply_session_override(config: dict, auto_configs: list, trigger: str) -> int:
    """Stamp the one-time F1 session-filter override onto eligible per-scan configs.

    Honoured ONLY on a manual/run-now scan (FR-066). Marks each F1-enabled config so
    its gates bypass for THIS scan only (non-persistent — the flag rides the per-scan
    config copy). Returns the count stamped. Single source of truth shared by start_scan
    and its tests, so the scheduled-bypass guard can't drift. In-place; skips non-dicts.
    """
    if not config.get("session_filter_override") or trigger not in SESSION_OVERRIDE_TRIGGERS:
        return 0
    n = 0
    for cfg in auto_configs:
        if isinstance(cfg, dict) and cfg.get("regime_filter_enabled"):
            cfg["_session_filter_override_active"] = True
            n += 1
    return n
