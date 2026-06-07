"""Pure strategy-routing and side-resolution functions (Phase 2 TASK-2.1/2.2).

These are module-level pure functions (no I/O, no executor coupling) so they are
unit-testable in isolation and reusable. The executor imports FROM this module
(one-way; no cycle).
"""

from __future__ import annotations

from typing import Literal

Strategy = Literal["trend", "mean_reversion", "none"]
Side = Literal["long", "short"]


def route_strategy(cohort: str, regime: str, *, mr_regime: str = "ranging") -> Strategy:
    """Select which strategy an account runs for a given market regime.

    - trend-cohort accounts run trend in ALL regimes.
    - mean_reversion-cohort accounts run MR ONLY when regime == mr_regime,
      else "none" (fail-closed: e.g. trending/volatile/unknown => no MR).
    - any unknown cohort defaults to "trend" (safe).
    """
    if cohort == "trend":
        return "trend"
    if cohort == "mean_reversion":
        return "mean_reversion" if regime == mr_regime else "none"
    return "trend"


def resolve_final_side(signal_dir: str, reverse: bool, mr_fade: bool) -> Side:
    """Compute the exchange side exactly once from the signal + transforms.

    base = long if the signal is buy/long else short.
    `reverse` (the existing trend knob) and `mr_fade` (mean-reversion inversion)
    each flip the side; applying BOTH is the identity (reverse ∧ fade => no flip),
    which is the double-invert case the truth table pins.
    """
    base: Side = "long" if signal_dir in ("buy", "long", "Buy", "Long") else "short"
    flip = reverse ^ mr_fade
    if not flip:
        return base
    return "short" if base == "long" else "long"


def feature_for(cohort: str) -> str:
    """Kill-switch feature key for an account's cohort.

    trend-cohort accounts are gated by the "f1" kill; mean_reversion-cohort by "f2".
    (The "f2_long" kill is checked separately on the long-fade path.)
    """
    return "f2" if cohort == "mean_reversion" else "f1"
