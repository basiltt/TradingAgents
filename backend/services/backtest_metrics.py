"""Backtest Metrics — TradingView-parity metric computation.

Pure functions computing all standard backtest metrics from a trade list
and equity curve. No I/O, fully deterministic.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional


def compute_sharpe(daily_returns: list[float], risk_free: float = 0.0) -> Optional[float]:
    """Compute Sharpe ratio, annualized for crypto (√365).

    Args:
        daily_returns: List of period returns (as decimals).
        risk_free: Risk-free rate (default 0).

    Returns:
        Annualized Sharpe ratio, or None if <2 data points or zero std.
    """
    if len(daily_returns) < 2:
        return None
    mean_return = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return ((mean_return - risk_free) / std) * math.sqrt(365)


def compute_sortino(daily_returns: list[float], risk_free: float = 0.0) -> Optional[float]:
    """Compute Sortino ratio (downside deviation only), annualized √365.

    Args:
        daily_returns: List of period returns.
        risk_free: Risk-free rate.

    Returns:
        Annualized Sortino ratio, or None if <2 data points.
    """
    if len(daily_returns) < 2:
        return None
    mean_return = sum(daily_returns) / len(daily_returns)
    downside = [r for r in daily_returns if r < risk_free]
    if not downside:
        # No downside — use a floor to avoid div by zero
        downside_dev = 0.0001
    else:
        downside_var = sum((r - risk_free) ** 2 for r in downside) / len(daily_returns)
        downside_dev = math.sqrt(downside_var)
        if downside_dev == 0:
            downside_dev = 0.0001
    return ((mean_return - risk_free) / downside_dev) * math.sqrt(365)


def compute_max_drawdown(equity_curve: list[dict[str, Any]]) -> dict[str, float]:
    """Compute maximum drawdown from equity curve.

    Args:
        equity_curve: List of {ts, equity, drawdown_pct} dicts.

    Returns:
        Dict with max_dd_pct, max_dd_usd, max_dd_duration_hours, avg_dd_pct.
    """
    if not equity_curve:
        return {"max_dd_pct": 0.0, "max_dd_usd": 0.0, "max_dd_duration_hours": 0.0, "avg_dd_pct": 0.0}

    peak = equity_curve[0]["equity"]
    peak_time = equity_curve[0].get("ts")
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    max_dd_duration = 0.0
    drawdowns = []

    for point in equity_curve:
        equity = point["equity"]
        ts = point.get("ts")
        if equity > peak:
            peak = equity
            peak_time = ts
        if peak > 0:
            dd_usd = peak - equity
            dd_pct = (dd_usd / peak) * 100
            drawdowns.append(dd_pct)
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_usd = dd_usd
                # Duration from peak to this trough
                if ts and peak_time and isinstance(ts, datetime) and isinstance(peak_time, datetime):
                    max_dd_duration = (ts - peak_time).total_seconds() / 3600.0

    avg_dd = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0

    return {
        "max_dd_pct": max_dd_pct,
        "max_dd_usd": max_dd_usd,
        "max_dd_duration_hours": max_dd_duration,
        "avg_dd_pct": avg_dd,
    }


def compute_streaks(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute consecutive win/loss streaks.

    Args:
        trades: List of trade dicts with 'pnl' field.

    Returns:
        Dict with max_consecutive_wins/losses (count) and their $ amounts.
    """
    max_wins = 0
    max_losses = 0
    cur_wins = 0
    cur_losses = 0
    max_win_usd = 0.0
    max_loss_usd = 0.0
    cur_win_usd = 0.0
    cur_loss_usd = 0.0

    for trade in trades:
        pnl = trade.get("pnl") or 0
        if pnl > 0:
            cur_wins += 1
            cur_win_usd += pnl
            cur_losses = 0
            cur_loss_usd = 0.0
            if cur_wins > max_wins:
                max_wins = cur_wins
                max_win_usd = cur_win_usd
        elif pnl < 0:
            cur_losses += 1
            cur_loss_usd += pnl
            cur_wins = 0
            cur_win_usd = 0.0
            if cur_losses > max_losses:
                max_losses = cur_losses
                max_loss_usd = cur_loss_usd

    return {
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "max_consecutive_wins_usd": max_win_usd,
        "max_consecutive_losses_usd": max_loss_usd,
    }


def compute_mfe_mae(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract per-trade MFE/MAE (already computed during simulation).

    Args:
        trades: List of trade dicts with mfe_pct, mae_pct fields.

    Returns:
        List of {symbol, mfe_pct, mae_pct, pnl} dicts.
    """
    return [
        {
            "symbol": t.get("symbol"),
            "mfe_pct": t.get("mfe_pct", 0.0),
            "mae_pct": t.get("mae_pct", 0.0),
            "pnl": t.get("pnl", 0.0),
        }
        for t in trades
    ]


def _direction_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the core metric subset for a trade list (used by split_by_direction)."""
    if not trades:
        return {
            "total_trades": 0, "winners": 0, "losers": 0,
            "net_profit": 0.0, "win_rate": None,
            "avg_win": None, "avg_loss": None,
        }

    winners = [t for t in trades if (t.get("pnl") or 0) > 0]
    losers = [t for t in trades if (t.get("pnl") or 0) < 0]
    net = sum(t.get("pnl") or 0 for t in trades)

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "net_profit": net,
        "win_rate": (len(winners) / len(trades) * 100) if trades else None,
        "avg_win": (sum(t["pnl"] for t in winners) / len(winners)) if winners else None,
        "avg_loss": (sum(t["pnl"] for t in losers) / len(losers)) if losers else None,
    }


def split_by_direction(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Split metrics into All / Long / Short.

    Args:
        trades: List of trade dicts with 'side' field.

    Returns:
        Dict with 'all', 'long', 'short' keys, each a metric subset.
    """
    longs = [t for t in trades if t.get("side") == "Buy"]
    shorts = [t for t in trades if t.get("side") == "Sell"]

    return {
        "all": _direction_metrics(trades),
        "long": _direction_metrics(longs),
        "short": _direction_metrics(shorts),
    }


def compute_buy_hold_return(
    btc_klines: list[dict[str, Any]],
    starting_capital: float,
) -> dict[str, float]:
    """Compute Buy & Hold benchmark return for BTC/USDT.

    Args:
        btc_klines: BTC kline data (ascending by time) with 'close' field.
        starting_capital: Initial capital.

    Returns:
        Dict with return_pct, final_value, start_price, end_price.
    """
    if not btc_klines:
        return {"return_pct": 0.0, "final_value": starting_capital, "start_price": 0.0, "end_price": 0.0}

    start_price = btc_klines[0]["close"]
    end_price = btc_klines[-1]["close"]

    if start_price <= 0:
        return {"return_pct": 0.0, "final_value": starting_capital, "start_price": start_price, "end_price": end_price}

    return_pct = (end_price - start_price) / start_price * 100
    final_value = starting_capital * (1 + return_pct / 100)

    return {
        "return_pct": return_pct,
        "final_value": final_value,
        "start_price": start_price,
        "end_price": end_price,
    }


def compute_all_metrics(
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Compute ALL TradingView-parity metrics.

    Args:
        trades: List of closed trade dicts.
        equity_curve: List of equity points.
        config: Backtest config (for starting_capital, etc).

    Returns:
        Complete metrics dict.
    """
    starting_capital = config.get("starting_capital", 0.0)

    # Handle zero trades
    if not trades:
        final_equity = equity_curve[-1]["equity"] if equity_curve else starting_capital
        return {
            "total_trades": 0, "winners": 0, "losers": 0,
            "net_profit": 0.0, "net_profit_pct": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0,
            "win_rate": None, "profit_factor": None,
            "sharpe": None, "sortino": None,
            "max_dd_pct": 0.0, "max_dd_usd": 0.0,
            "avg_win": None, "avg_loss": None,
            "largest_win": None, "largest_loss": None,
            "total_commission": 0.0, "recovery_factor": None,
            "cagr": None, "calmar": None, "expectancy": None,
            "max_consecutive_wins": 0, "max_consecutive_losses": 0,
            "avg_trade_duration_hours": None,
            "final_equity": final_equity,
            "by_direction": split_by_direction([]),
        }

    winners = [t for t in trades if (t.get("pnl") or 0) > 0]
    losers = [t for t in trades if (t.get("pnl") or 0) < 0]

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = sum(t["pnl"] for t in losers)  # negative
    net_profit = sum(t.get("pnl") or 0 for t in trades)
    total_commission = sum(t.get("fees_paid") or 0 for t in trades)

    # Profit factor
    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else None
    else:
        profit_factor = gross_profit / abs(gross_loss)

    # Win rate
    win_rate = (len(winners) / len(trades)) * 100

    # Avg win/loss
    avg_win = (gross_profit / len(winners)) if winners else None
    avg_loss = (gross_loss / len(losers)) if losers else None

    # Largest
    largest_win = max((t["pnl"] for t in winners), default=None)
    largest_loss = min((t["pnl"] for t in losers), default=None)

    # Expectancy
    loss_rate = (len(losers) / len(trades)) if trades else 0
    expectancy = None
    if avg_win is not None and avg_loss is not None:
        expectancy = (win_rate / 100 * avg_win) + (loss_rate * avg_loss)
    elif avg_win is not None:
        expectancy = win_rate / 100 * avg_win

    # Equity-based metrics
    final_equity = equity_curve[-1]["equity"] if equity_curve else (starting_capital + net_profit)
    net_profit_pct = (net_profit / starting_capital * 100) if starting_capital > 0 else 0.0

    # Drawdown
    dd = compute_max_drawdown(equity_curve)

    # Recovery factor = net profit / max drawdown $
    recovery_factor = (net_profit / dd["max_dd_usd"]) if dd["max_dd_usd"] > 0 else None

    # Daily returns for Sharpe/Sortino (from equity curve)
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["equity"]
        curr = equity_curve[i]["equity"]
        if prev > 0:
            daily_returns.append((curr - prev) / prev)

    sharpe = compute_sharpe(daily_returns)
    sortino = compute_sortino(daily_returns)

    # CAGR
    cagr = None
    if equity_curve and len(equity_curve) >= 2 and starting_capital > 0:
        first_ts = equity_curve[0].get("ts")
        last_ts = equity_curve[-1].get("ts")
        if first_ts and last_ts and isinstance(first_ts, datetime) and isinstance(last_ts, datetime):
            days = max((last_ts - first_ts).total_seconds() / 86400.0, 1)
            if final_equity > 0:
                cagr = ((final_equity / starting_capital) ** (365 / days) - 1) * 100

    # Calmar = CAGR / max_dd_pct
    calmar = (cagr / dd["max_dd_pct"]) if (cagr is not None and dd["max_dd_pct"] > 0) else None

    # Streaks
    streaks = compute_streaks(trades)

    # Durations
    durations = []
    for t in trades:
        et = t.get("entry_time")
        xt = t.get("exit_time")
        if et and xt and isinstance(et, datetime) and isinstance(xt, datetime):
            durations.append((xt - et).total_seconds() / 3600.0)
    avg_duration = (sum(durations) / len(durations)) if durations else None

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "net_profit": net_profit,
        "net_profit_pct": net_profit_pct,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd_pct": dd["max_dd_pct"],
        "max_dd_usd": dd["max_dd_usd"],
        "max_dd_duration_hours": dd["max_dd_duration_hours"],
        "avg_dd_pct": dd["avg_dd_pct"],
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "total_commission": total_commission,
        "recovery_factor": recovery_factor,
        "cagr": cagr,
        "calmar": calmar,
        "expectancy": expectancy,
        "max_consecutive_wins": streaks["max_consecutive_wins"],
        "max_consecutive_losses": streaks["max_consecutive_losses"],
        "max_consecutive_wins_usd": streaks["max_consecutive_wins_usd"],
        "max_consecutive_losses_usd": streaks["max_consecutive_losses_usd"],
        "avg_trade_duration_hours": avg_duration,
        "final_equity": final_equity,
        "by_direction": split_by_direction(trades),
    }
