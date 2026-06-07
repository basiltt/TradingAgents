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

    Precedence: an explicit per-scan override wins; otherwise the stored account
    field; otherwise the default. Because the per-scan ``AutoTradeConfig.strategy_cohort``
    defaults to "trend" (indistinguishable from an untouched form), we treat the
    per-scan value as an override ONLY when it escalates to a non-default cohort.
    A stored "mean_reversion" therefore drives routing for a fleet assigned via the
    roster UI, while a per-scan explicit "mean_reversion" still works. A stored value
    can never silently override a per-scan non-default choice.
    """
    if scan_cohort and scan_cohort != DEFAULT_COHORT and scan_cohort in COHORTS:
        return scan_cohort
    if stored_cohort and stored_cohort in COHORTS:
        return stored_cohort
    return DEFAULT_COHORT
