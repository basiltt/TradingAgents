"""Market commentary generation and day quality score computation."""
from __future__ import annotations

from typing import Any


def compute_day_score(
    regime_label: str | None,
    position_directions: list[str],
    unrealized_pnl_trend: str,
    urgency_history_1h: list[str],
    correlation_heat: float | None,
) -> tuple[int, str, str]:
    """Compute day quality score (0-100) with label and justification.

    Formula: base=50 + per-category exclusive adjustments, clamped [0,100].
    """
    BASE = 50
    adjustment = 0

    regime_direction = _regime_to_direction(regime_label)
    if regime_direction and position_directions:
        aligned_count = sum(1 for d in position_directions if d == regime_direction)
        ratio = aligned_count / len(position_directions)
        if ratio >= 0.8:
            adjustment += 25
        elif ratio <= 0.2:
            adjustment -= 20

    if unrealized_pnl_trend == "rising":
        adjustment += 25
    elif unrealized_pnl_trend == "falling":
        adjustment -= 20

    if "EMERGENCY" in urgency_history_1h:
        adjustment -= 30
    elif "FAST" in urgency_history_1h:
        adjustment -= 10
    elif urgency_history_1h and all(u == "STANDARD" for u in urgency_history_1h):
        adjustment += 15

    if correlation_heat is not None:
        if correlation_heat < 0.3:
            adjustment += 10
        elif correlation_heat > 0.7:
            adjustment -= 15

    score = max(0, min(100, BASE + adjustment))

    if score >= 70:
        label = "good"
    elif score >= 40:
        label = "neutral"
    elif score >= 20:
        label = "caution"
    else:
        label = "danger"

    justification = _build_justification(regime_label, unrealized_pnl_trend, urgency_history_1h, correlation_heat)
    return score, label, justification


def _regime_to_direction(regime_label: str | None) -> str | None:
    if regime_label == "trending_up":
        return "Buy"
    elif regime_label == "trending_down":
        return "Sell"
    return None


def _build_justification(
    regime_label: str | None,
    pnl_trend: str,
    urgency_history: list[str],
    correlation_heat: float | None,
) -> str:
    parts: list[str] = []
    if regime_label:
        parts.append(f"Market is {regime_label.replace('_', ' ')}")
    if pnl_trend == "rising":
        parts.append("positions performing well")
    elif pnl_trend == "falling":
        parts.append("positions under pressure")
    if "EMERGENCY" in urgency_history:
        parts.append("emergency conditions detected")
    elif "FAST" in urgency_history:
        parts.append("elevated urgency present")
    if correlation_heat and correlation_heat > 0.7:
        parts.append("high portfolio correlation")
    return ". ".join(parts) + "." if parts else "Insufficient data for assessment."


def generate_template_commentary(
    regime_label: str | None,
    session: str | None,
    positions: list[dict[str, Any]],
    day_score: int,
    day_score_label: str,
    indicators: dict[str, Any] | None = None,
) -> str:
    """Generate human-readable commentary from analysis context (no LLM call)."""
    parts: list[str] = []

    session_name = {"asia": "Asian", "london": "London", "new_york": "New York", "off_hours": "off-hours"}.get(session or "", "current")
    parts.append(f"During the {session_name} session, the market is in a {(regime_label or 'unknown').replace('_', ' ')} regime.")

    if positions:
        long_count = sum(1 for p in positions if p.get("side") == "Buy")
        short_count = len(positions) - long_count
        total_upnl = sum(p.get("current_upnl", 0) for p in positions)
        pnl_word = "profit" if total_upnl >= 0 else "loss"
        parts.append(f"Managing {len(positions)} position{'s' if len(positions) > 1 else ''} ({long_count} long, {short_count} short) with total unrealized {pnl_word}.")
    else:
        parts.append("No active positions currently being managed.")

    parts.append(f"Overall day assessment: {day_score_label} ({day_score}/100).")

    return " ".join(parts)[:2000]
