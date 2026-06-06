"""Shared trading rules — pure functions used by both live auto-trade and backtest engine.

This module is the SINGLE SOURCE OF TRUTH for trade execution formulas.
Both `auto_trade_service.py` (live) and `backtest_engine.py` import from here.
"""

from __future__ import annotations

import math
from typing import Optional


def determine_side(signal_direction: str, trade_direction: str) -> str:
    """Determine trade side from signal direction and trade config direction.

    Args:
        signal_direction: "buy" or "sell" from scan result.
        trade_direction: "straight" or "reverse" from config.

    Returns:
        "Buy" or "Sell" (Bybit API format).
    """
    if trade_direction == "straight":
        return "Buy" if signal_direction == "buy" else "Sell"
    else:  # reverse
        return "Sell" if signal_direction == "buy" else "Buy"


def compute_tp_sl(
    entry: float, side: str, tp_pct: float, sl_pct: float, leverage: int
) -> tuple[float, float]:
    """Compute take-profit and stop-loss prices from leverage-adjusted percentages.

    The input percentages represent ROI% (equity change). To convert to price change:
        price_move_pct = pct / leverage

    Args:
        entry: Entry price.
        side: "Buy" (long) or "Sell" (short).
        tp_pct: Take-profit as leverage-adjusted % (e.g., 100% at 20x = 5% price move).
        sl_pct: Stop-loss as leverage-adjusted % (e.g., 50% at 20x = 2.5% price move).
        leverage: Applied leverage.

    Returns:
        Tuple of (tp_price, sl_price).
    """
    tp_price_pct = tp_pct / leverage / 100.0
    sl_price_pct = sl_pct / leverage / 100.0

    if side == "Buy":
        tp_price = entry * (1.0 + tp_price_pct)
        sl_price = entry * (1.0 - sl_price_pct)
    else:  # Sell
        tp_price = entry * (1.0 - tp_price_pct)
        sl_price = entry * (1.0 + sl_price_pct)

    return tp_price, sl_price


def compute_position_size(
    sizing_capital: float,
    capital_pct: float,
    leverage: int,
    price: float,
    qty_step: float,
    min_qty: float,
    available_balance: Optional[float] = None,
) -> Optional[float]:
    """Compute position quantity from capital allocation.

    Formula: qty = (sizing_capital × capital_pct/100 × leverage) / price
    Rounded DOWN to qty_step. Returns None if below min_qty or insufficient margin.

    Args:
        sizing_capital: Current wallet balance used for sizing (refreshed per scan/cycle).
        capital_pct: Percentage of capital to use per trade.
        leverage: Applied leverage.
        price: Entry price.
        qty_step: Instrument's minimum quantity increment.
        min_qty: Instrument's minimum order quantity.
        available_balance: If provided, checks that intended_margin <= available_balance.

    Returns:
        Rounded quantity, or None if insufficient for min_qty or margin.
    """
    if price <= 0 or qty_step <= 0:
        return None

    margin = sizing_capital * capital_pct / 100.0

    # Check available balance (wallet - locked margins of open positions)
    if available_balance is not None and margin > available_balance:
        return None

    raw_qty = (margin * leverage) / price

    # Round DOWN to qty_step
    qty = math.floor(raw_qty / qty_step) * qty_step

    # Round to avoid floating-point artifacts
    decimals = max(0, -int(math.floor(math.log10(qty_step)))) if qty_step < 1 else 0
    qty = round(qty, decimals)

    if qty < min_qty:
        return None

    return qty


def round_price_to_tick(price: float, tick_size: float) -> float:
    """Round a price DOWN to the instrument's tick size.

    Mirrors production's accounts_service.place_trade round_price (which uses
    Decimal ROUND_DOWN to tick_size) so backtest TP/SL trigger prices land on the
    same grid the exchange would accept. A non-positive tick_size returns the price
    unchanged (no rounding).
    """
    if tick_size <= 0:
        return price
    ticks = math.floor(price / tick_size)
    rounded = ticks * tick_size
    # Snap away float artifacts to the tick's decimal precision.
    decimals = max(0, -int(math.floor(math.log10(tick_size)))) if tick_size < 1 else 0
    return round(rounded, decimals)


def compute_liquidation_price(
    entry: float, side: str, leverage: int, mmr: float = 0.005
) -> float:
    """Compute liquidation price for isolated margin.

    Bybit isolated margin formula:
        Long:  liq = entry × (1 - (1/leverage - MMR))
        Short: liq = entry × (1 + (1/leverage - MMR))

    Args:
        entry: Entry price.
        side: "Buy" (long) or "Sell" (short).
        leverage: Applied leverage.
        mmr: Maintenance margin rate (default 0.5% for tier 1).

    Returns:
        Liquidation price.
    """
    margin_rate = 1.0 / leverage - mmr

    if side == "Buy":
        return entry * (1.0 - margin_rate)
    else:
        return entry * (1.0 + margin_rate)


def compute_unrealized_pnl(
    entry: float, current: float, qty: float, side: str
) -> float:
    """Compute unrealized PnL for an open position.

    Args:
        entry: Entry price.
        current: Current mark/close price.
        qty: Position quantity.
        side: "Buy" or "Sell".

    Returns:
        Unrealized PnL in USDT (positive = profit).
    """
    if side == "Buy":
        return (current - entry) * qty
    else:
        return (entry - current) * qty


def check_equity_rise(equity: float, reference: float, threshold: float) -> bool:
    """Check if equity has risen above threshold percentage from reference.

    Args:
        equity: Current total equity.
        reference: Reference equity (at cycle start).
        threshold: Rise percentage threshold (e.g., 5.0 = 5%).

    Returns:
        True if rise condition is met.
    """
    if reference <= 0:
        return False
    rise_pct = ((equity - reference) / reference) * 100.0
    return rise_pct >= threshold


def check_equity_drop(equity: float, reference: float, threshold: float) -> bool:
    """Check if equity has dropped below threshold percentage from reference.

    Args:
        equity: Current total equity.
        reference: Reference equity (at cycle start).
        threshold: Drop percentage threshold (e.g., 10.0 = 10%).

    Returns:
        True if drop condition is met.
    """
    if reference <= 0:
        return False
    drop_pct = ((reference - equity) / reference) * 100.0
    return drop_pct >= threshold


def check_trailing_trigger(
    per_unit_pnl: float, peak: float, ratio: float = 0.5
) -> bool:
    """Check if trailing profit should trigger position close.

    Triggers when per_unit_pnl drops STRICTLY BELOW ratio × peak.

    Args:
        per_unit_pnl: Current per-unit PnL (unrealized_pnl / qty).
        peak: Highest recorded per-unit PnL since activation.
        ratio: Drawdown ratio from peak (default 0.5 = 50%).

    Returns:
        True if trailing trigger condition is met.
    """
    if peak <= 0:
        return False
    return per_unit_pnl < peak * ratio


def apply_slippage(price: float, side: str, slippage_bps: int) -> float:
    """Apply slippage to a price (unfavorable direction).

    Buy: price increases (worse fill for buyer).
    Sell: price decreases (worse fill for seller).

    Args:
        price: Base price.
        side: "Buy" or "Sell".
        slippage_bps: Slippage in basis points.

    Returns:
        Price with slippage applied.
    """
    slippage_factor = slippage_bps / 10000.0
    if side == "Buy":
        return price * (1.0 + slippage_factor)
    else:
        return price * (1.0 - slippage_factor)


def compute_fee(qty: float, price: float, fee_rate_pct: float) -> float:
    """Compute trading fee for a fill.

    Fee = qty × price × fee_rate_pct / 100

    Args:
        qty: Position quantity.
        price: Fill price.
        fee_rate_pct: Fee rate as percentage (e.g., 0.055 for 0.055%).

    Returns:
        Fee amount in USDT.
    """
    return qty * price * fee_rate_pct / 100.0


def compute_breakeven_price(entry: float, side: str, leverage: int) -> float:
    """Compute breakeven take-profit price (covers fees at leverage).

    Formula: entry × (1 ± 1/(leverage×100))
    This produces a ~1% leveraged PnL buffer to cover round-trip fees.

    Args:
        entry: Entry price.
        side: "Buy" or "Sell".
        leverage: Applied leverage.

    Returns:
        Breakeven TP price.
    """
    buffer = 1.0 / (leverage * 100.0)
    if side == "Buy":
        return entry * (1.0 + buffer)
    else:
        return entry * (1.0 - buffer)


def check_close_on_profit(
    equity: float,
    cycle_start_equity: float,
    close_on_profit_pct: float,
    target_goal_value: float = 100.0,
) -> bool:
    """Check if cycle profit has reached the close_on_profit threshold.

    Production formula: effective_threshold = (close_on_profit_pct / 100) * target_goal_value
    Triggers when cycle PnL% >= effective_threshold.

    Args:
        equity: Current total equity (wallet + unrealized).
        cycle_start_equity: Equity at the start of this cycle.
        close_on_profit_pct: Configured close-on-profit percentage.
        target_goal_value: Target goal value from config (default 100.0).

    Returns:
        True if cycle profit >= effective threshold.
    """
    if cycle_start_equity <= 0:
        return False
    effective_threshold = (close_on_profit_pct / 100.0) * target_goal_value
    cycle_pnl_pct = ((equity - cycle_start_equity) / cycle_start_equity) * 100.0
    return cycle_pnl_pct >= effective_threshold


def lttb_downsample(points: list[dict], target_n: int) -> list[dict]:
    """Downsample time-series data using Largest-Triangle-Three-Buckets algorithm.

    Preserves visual shape of the data while reducing point count.
    Always preserves first and last points.

    Args:
        points: List of dicts with "x" and "y" keys.
        target_n: Target number of output points.

    Returns:
        Downsampled list of points.
    """
    n = len(points)
    if n <= target_n or target_n < 3:
        return points[:]

    # Always include first and last
    sampled = [points[0]]

    # Bucket size (excluding first and last points)
    bucket_size = (n - 2) / (target_n - 2)

    a_index = 0  # Previous selected point index

    for i in range(1, target_n - 1):
        # Calculate bucket boundaries
        bucket_start = int(math.floor((i - 1) * bucket_size)) + 1
        bucket_end = int(math.floor(i * bucket_size)) + 1
        bucket_end = min(bucket_end, n - 1)

        # Calculate average of next bucket for the triangle
        next_bucket_start = int(math.floor(i * bucket_size)) + 1
        next_bucket_end = int(math.floor((i + 1) * bucket_size)) + 1
        next_bucket_end = min(next_bucket_end, n)

        avg_x = 0.0
        avg_y = 0.0
        next_count = next_bucket_end - next_bucket_start
        if next_count > 0:
            for j in range(next_bucket_start, next_bucket_end):
                avg_x += points[j]["x"]
                avg_y += points[j]["y"]
            avg_x /= next_count
            avg_y /= next_count

        # Find point in current bucket with largest triangle area
        max_area = -1.0
        max_index = bucket_start

        point_a_x = points[a_index]["x"]
        point_a_y = points[a_index]["y"]

        for j in range(bucket_start, bucket_end):
            # Triangle area (simplified — no need for /2 since comparing)
            area = abs(
                (point_a_x - avg_x) * (points[j]["y"] - point_a_y)
                - (point_a_x - points[j]["x"]) * (avg_y - point_a_y)
            )
            if area > max_area:
                max_area = area
                max_index = j

        sampled.append(points[max_index])
        a_index = max_index

    sampled.append(points[-1])
    return sampled


def compute_liquidation_pnl(initial_margin: float, entry_fee: float) -> float:
    """Compute realized PnL on liquidation (full margin loss).

    On Bybit isolated margin, user loses the entire initial margin on liquidation.

    Args:
        initial_margin: Margin allocated at position open (qty × entry / leverage).
        entry_fee: Fee paid on entry.

    Returns:
        Negative PnL representing total loss (-(margin + fee)).
    """
    return -(initial_margin + entry_fee)


def check_trailing_activation(
    current_price: float,
    entry_price: float,
    threshold_pct: float,
    upnl: float,
) -> bool:
    """Check if trailing profit should activate for a position.

    Activation requires: (1) position is profitable (upnl > 0), AND
    (2) price has moved >= threshold_pct from entry.

    CRITICAL: Uses abs(price_move) — works for both long and short.
    Returns False if upnl <= 0 (the guard from production code).

    Args:
        current_price: Current mark/close price.
        entry_price: Position entry price.
        threshold_pct: Activation threshold as price movement % (NOT leveraged ROI).
        upnl: Current unrealized PnL (must be > 0 for activation).

    Returns:
        True if trailing should activate/remain active.
    """
    if upnl <= 0:
        return False
    if entry_price <= 0:
        return False
    profit_pct = abs(current_price - entry_price) / entry_price * 100.0
    return profit_pct >= threshold_pct


def compute_locked_margin(qty: float, entry_price: float, leverage: int) -> float:
    """Compute margin locked by an open position (isolated margin).

    Args:
        qty: Position quantity.
        entry_price: Entry price.
        leverage: Applied leverage.

    Returns:
        Locked margin in USDT (= position_notional / leverage).
    """
    if leverage <= 0:
        return 0.0
    return (qty * entry_price) / leverage
