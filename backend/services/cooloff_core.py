"""cooloff_core — pure decision engine for the Cool Off Time feature.

This module is I/O-free and deterministic: no datetime.now, no DB, no logging side
effects. It is shared verbatim by the LIVE classifier (CooloffClassifier) and the
BACKTEST engine so that the streak/arming decision is identical in both (CR-5). The
caller supplies `now` and computes the absolute `cooloff_until` timestamp; this module
only decides the streak transition, whether to arm, and which duration/reason applies.

Spec: FR-005 (classify_outcome), FR-006 (decide / streak state machine),
FR-007 decision part. Decisions D2/D5/D9, CO-STREAK-2..7, CO-CORE-4/6, CR-6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

# ── Constants (CR-6) ─────────────────────────────────────────────────────────
# STALE_MIN_MINUTES: how long an unsettled episode may block classification before
#   the classifier advances past it as neutral (must exceed the reconciler's 24h
#   backfill horizon + margin — D51).
# CLAMP_MAX_DAYS: a cooloff_until further out than this is treated as corrupt (D27/D7).
# DOUBLE_THRESHOLD: consecutive count at which a "double" tier becomes eligible.
# STREAK_CLAMP: streak counters are bounded here (only >=2 matters; keeps state small).
STALE_MIN_MINUTES = 1560  # 26 hours
CLAMP_MAX_DAYS = 31
DOUBLE_THRESHOLD = 2
STREAK_CLAMP = 2

Outcome = Literal["success", "failure", "neutral"]
CooloffReason = Literal["success", "failure", "double_success", "double_failure"]


@dataclass(frozen=True)
class CooloffSettings:
    """The 4 cool-off tiers for one account (enabled flag + duration in minutes)."""

    success_enabled: bool
    success_minutes: Optional[int]
    failure_enabled: bool
    failure_minutes: Optional[int]
    double_success_enabled: bool
    double_success_minutes: Optional[int]
    double_failure_enabled: bool
    double_failure_minutes: Optional[int]


@dataclass(frozen=True)
class StreakState:
    """Per-account consecutive win/loss counters (clamped at STREAK_CLAMP)."""

    consecutive_wins: int
    consecutive_losses: int


@dataclass(frozen=True)
class ArmDecision:
    """Result of decide(): the new streak, whether to arm, and the duration/reason."""

    streaks: StreakState
    arm: bool
    duration_minutes: Optional[int]
    reason: Optional[CooloffReason]


def classify_outcome(net_pnl: Optional[float]) -> Outcome:
    """Classify a cycle's net realized P&L into success/failure/neutral (FR-005).

    None or a non-finite value (NaN/Inf) is treated as neutral — never fabricate a
    win/loss from indeterminate data (CO-DET-7). Exactly zero is neutral.
    """
    if net_pnl is None:
        return "neutral"
    try:
        if not math.isfinite(net_pnl):
            return "neutral"
    except (TypeError, ValueError):
        return "neutral"
    if net_pnl > 0:
        return "success"
    if net_pnl < 0:
        return "failure"
    return "neutral"


def any_tier_enabled(settings: CooloffSettings) -> bool:
    """True if any of the 4 cool-off tiers is enabled for the account."""
    return (
        settings.success_enabled
        or settings.failure_enabled
        or settings.double_success_enabled
        or settings.double_failure_enabled
    )


def _clamp(n: int) -> int:
    return n if n < STREAK_CLAMP else STREAK_CLAMP


def decide(state: StreakState, outcome: Outcome, settings: CooloffSettings) -> ArmDecision:
    """Decide the streak transition and whether/how to arm a cool-off (FR-006).

    Rules:
    - neutral: transparent — counters unchanged, no arm (CO-STREAK-3).
    - success: wins+1 (clamped), losses->0. If the new win streak >= DOUBLE_THRESHOLD
      and the double_success tier is enabled, arm double_success and RESET wins to 0
      (CO-STREAK-5); else if success tier enabled, arm success. Double overrides single
      (CO-CORE-6).
    - failure: symmetric.
    Defensive: never arm with a None duration (the schema rejects enabled-without-minutes,
    but decide() must not produce an arm=True/duration=None pair).
    """
    if outcome == "neutral":
        return ArmDecision(streaks=state, arm=False, duration_minutes=None, reason=None)

    if outcome == "success":
        new_wins = _clamp(state.consecutive_wins + 1)
        # double overrides single
        if (
            new_wins >= DOUBLE_THRESHOLD
            and settings.double_success_enabled
            and settings.double_success_minutes is not None
        ):
            # reset ONLY the fired (win) side; the loss side is already 0 for any
            # reachable state but we preserve it explicitly to match the spec (FR-006).
            return ArmDecision(
                streaks=StreakState(0, state.consecutive_losses),
                arm=True,
                duration_minutes=settings.double_success_minutes,
                reason="double_success",
            )
        new_state = StreakState(new_wins, 0)
        if settings.success_enabled and settings.success_minutes is not None:
            return ArmDecision(new_state, True, settings.success_minutes, "success")
        return ArmDecision(new_state, False, None, None)

    # outcome == "failure"
    new_losses = _clamp(state.consecutive_losses + 1)
    if (
        new_losses >= DOUBLE_THRESHOLD
        and settings.double_failure_enabled
        and settings.double_failure_minutes is not None
    ):
        # reset ONLY the fired (loss) side (FR-006).
        return ArmDecision(
            streaks=StreakState(state.consecutive_wins, 0),
            arm=True,
            duration_minutes=settings.double_failure_minutes,
            reason="double_failure",
        )
    new_state = StreakState(0, new_losses)
    if settings.failure_enabled and settings.failure_minutes is not None:
        return ArmDecision(new_state, True, settings.failure_minutes, "failure")
    return ArmDecision(new_state, False, None, None)
