"""Pure, stateless portfolio-statistics math (Sharpe, Sortino, Calmar, drawdowns).

Extracted from ``accounts_service.py`` so these risk/return calculations can be
reused and unit-tested independently of any service state. Every function here
is a pure function of its arguments.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List


def clamp(value: float, lo: float = -999.99, hi: float = 999.99) -> float:
    """Clamp a float to [lo, hi], returning 0.0 for NaN/Inf."""
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(lo, min(hi, value))


def calc_sharpe(daily_returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio from daily return percentages."""
    if len(daily_returns) < 2:
        return 0.0
    mean_r = sum(daily_returns) / len(daily_returns) - risk_free_rate / 365
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1))
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * math.sqrt(365)


def calc_sortino(daily_returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Annualized Sortino ratio (downside deviation only) from daily return percentages."""
    if len(daily_returns) < 2:
        return 0.0
    mean_r = sum(daily_returns) / len(daily_returns) - risk_free_rate / 365
    downside_sq = [min(r, 0) ** 2 for r in daily_returns]
    downside_dev = math.sqrt(sum(downside_sq) / (len(daily_returns) - 1))
    if downside_dev == 0:
        return 0.0
    return (mean_r / downside_dev) * math.sqrt(365)


def calc_calmar(daily_returns: List[float], max_drawdown: float) -> float:
    """Calmar ratio: annualized mean return divided by max drawdown percentage."""
    if not daily_returns or max_drawdown == 0:
        return 0.0
    annual_return = sum(daily_returns) / len(daily_returns) * 365
    return annual_return / max_drawdown


def max_consecutive(daily_returns: List[float], negative: bool) -> int:
    """Count the longest consecutive streak of positive (or negative) returns."""
    max_count = 0
    count = 0
    for r in daily_returns:
        if (negative and r < 0) or (not negative and r > 0):
            count += 1
            max_count = max(max_count, count)
        else:
            count = 0
    return max_count


def calc_drawdown_duration(snapshots: List[Dict[str, Any]]) -> tuple[int, int]:
    """Return (max_drawdown_duration, max_recovery_time) in snapshot periods."""
    if not snapshots:
        return 0, 0
    max_duration = 0
    current_duration = 0
    max_recovery = 0
    recovery_start = -1
    for i, s in enumerate(snapshots):
        if s.get("drawdown_pct", 0) > 0:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
            if recovery_start < 0:
                recovery_start = i
        else:
            if recovery_start >= 0:
                max_recovery = max(max_recovery, i - recovery_start)
            current_duration = 0
            recovery_start = -1
    if recovery_start >= 0:
        max_recovery = max(max_recovery, len(snapshots) - recovery_start)
    return max_duration, max_recovery
