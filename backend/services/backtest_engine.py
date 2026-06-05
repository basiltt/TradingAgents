"""Backtest Simulation Engine — pure, synchronous, all data pre-loaded.

This module contains the core simulation loop that replays historical signals
through the full auto-trade cycle. It is designed to run in a ThreadPoolExecutor
and has ZERO I/O — all data (signals, klines, config) is injected.

The only external dependency is an optional `threading.Event` for cancellation
and an optional progress callback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from backend.schemas.backtest_schemas import SimulationResult

logger = logging.getLogger(__name__)


class BacktestCancelled(Exception):
    """Raised when a backtest is cancelled via cancel_event."""
    pass


@dataclass
class Position:
    """A single open simulated position."""

    symbol: str
    side: str  # "Buy" or "Sell"
    entry_price: float
    qty: float
    leverage: int
    entry_time: datetime
    tp_price: float
    sl_price: float
    liq_price: float
    entry_fee: float
    locked_margin: float
    scan_id: str = ""
    signal_score: int = 0
    signal_confidence: str = ""
    # Trailing profit state
    trailing_active: bool = False
    trailing_peak: float = 0.0
    # MFE/MAE tracking
    max_favorable_price: float = 0.0
    max_adverse_price: float = 0.0


@dataclass
class SimulationState:
    """Internal mutable state of the simulation engine."""

    wallet_balance: float = 0.0
    sizing_capital: float = 0.0  # refreshed per scan (matches production init_balances)
    open_positions: list[Position] = field(default_factory=list)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    # Cycle state
    cycle_active: bool = False
    cycle_start_equity: float = 0.0
    cycle_start_time: Optional[datetime] = None
    # Tracking
    signals_processed: int = 0
    signals_filtered: int = 0
    signals_entered: int = 0


class BacktestEngine:
    """Pure simulation engine for backtesting.

    All data is pre-loaded. Engine is synchronous (designed for ThreadPoolExecutor).
    cancel_event (threading.Event) checked every 100 candles for cooperative cancellation.
    """

    def run(
        self,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> SimulationResult:
        """Execute the backtest simulation.

        Args:
            config: Full backtest configuration (all AutoTradeConfig fields + backtest-specific).
            signals: Chronological list of scan result signals (from _load_signals).
            klines: Dict mapping symbol → list of kline dicts (ascending by open_time).
            cancel_event: If set, engine raises BacktestCancelled at next check point.
            on_progress: Called with percentage (0-100) at regular intervals.

        Returns:
            SimulationResult with trades, equity_curve, metrics, warnings, filter_stats.

        Raises:
            BacktestCancelled: If cancel_event is set during execution.
        """
        # Initialize state
        starting_capital = config["starting_capital"]
        state = SimulationState(
            wallet_balance=starting_capital,
            sizing_capital=starting_capital,
        )

        warnings: list[str] = []

        # Handle empty signals
        if not signals:
            warnings.append("no_signals_found")
            if on_progress:
                on_progress(100)
            return SimulationResult(
                trades=[],
                equity_curve=[{"ts": None, "equity": starting_capital, "drawdown_pct": 0.0}],
                metrics={},
                warnings=warnings,
                filter_stats={"signals_total": 0, "signals_filtered": 0, "signals_entered": 0},
            )

        # Check cancellation before starting
        if cancel_event and cancel_event.is_set():
            raise BacktestCancelled("Cancelled before simulation start")

        # --- SIGNAL PROCESSING (Task 3.2) ---
        # Group signals by scan_id (each scan is a batch event)
        from collections import defaultdict
        scans: dict[str, list[dict]] = defaultdict(list)
        for sig in signals:
            scans[sig["scan_id"]].append(sig)

        # Sort scans chronologically by their first signal's timestamp
        scan_order = sorted(scans.keys(), key=lambda sid: scans[sid][0]["signal_time"])

        execution_mode = config.get("execution_mode", "batch")
        candle_count = 0

        for scan_idx, scan_id in enumerate(scan_order):
            # Check cancellation every scan
            if cancel_event and cancel_event.is_set():
                raise BacktestCancelled("Cancelled during simulation")

            scan_signals = scans[scan_id]
            current_time = scan_signals[0]["signal_time"]

            # --- CYCLE LOCK (Task 3.9) ---
            # If skip_if_positions_open=True AND positions exist → skip entire scan
            if config.get("skip_if_positions_open") and state.open_positions:
                state.signals_filtered += len(scan_signals)
                # Still evaluate close rules on existing positions
                if state.open_positions:
                    next_scan_time = None
                    if scan_idx + 1 < len(scan_order):
                        next_scan_id = scan_order[scan_idx + 1]
                        next_scan_time = scans[next_scan_id][0]["signal_time"]
                    self._evaluate_candles_until(config, klines, state, current_time, next_scan_time, cancel_event)
                if on_progress:
                    pct = int(((scan_idx + 1) / len(scan_order)) * 100)
                    on_progress(min(pct, 99))
                continue

            # Refresh sizing_capital at each scan (matches production init_balances per scan)
            # Clamp to >= 0 so a negative wallet doesn't produce negative position sizes
            state.sizing_capital = max(0.0, state.wallet_balance)

            # Process signals through filter chain
            if execution_mode == "batch":
                self._process_batch_signals(config, scan_signals, klines, state, current_time)
            else:
                self._process_immediate_signals(config, scan_signals, klines, state, current_time)

            # --- CANDLE-BY-CANDLE CLOSE RULE EVALUATION (Task 3.3+) ---
            # After opening positions, evaluate close rules on subsequent candles
            # until next scan event (or end of data)
            next_scan_time = None
            if scan_idx + 1 < len(scan_order):
                next_scan_id = scan_order[scan_idx + 1]
                next_scan_time = scans[next_scan_id][0]["signal_time"]

            # Evaluate open positions against candles
            if state.open_positions:
                self._evaluate_candles_until(
                    config, klines, state, current_time, next_scan_time, cancel_event
                )
                candle_count += 1

            # Report progress
            if on_progress:
                pct = int(((scan_idx + 1) / len(scan_order)) * 100)
                on_progress(min(pct, 99))

        # --- FORCE-CLOSE AT BACKTEST END (Task 3.10) ---
        fee_rate = config.get("fee_rate_pct", 0.055)
        if state.open_positions:
            # Close all remaining positions at last available price
            for pos in list(state.open_positions):
                # Find last kline close for this symbol
                symbol_klines = klines.get(pos.symbol, [])
                last_price = symbol_klines[-1]["close"] if symbol_klines else pos.entry_price
                last_time = symbol_klines[-1]["open_time"] if symbol_klines else signals[-1]["signal_time"]
                self._close_position(state, pos, "backtest_end", last_price, last_time, fee_rate)
            if "backtest_end" not in [w for w in warnings]:
                warnings.append(f"force_closed_{len([t for t in state.closed_trades if t.get('close_reason') == 'backtest_end'])}_positions_at_end")

        # Record final equity point
        final_equity = state.wallet_balance
        state.equity_curve.append({
            "ts": signals[-1]["signal_time"] if signals else None,
            "equity": final_equity,
            "drawdown_pct": 0.0,
        })

        if on_progress:
            on_progress(100)

        # Compute all metrics from trades + equity curve
        from backend.services.backtest_metrics import compute_all_metrics
        metrics = compute_all_metrics(state.closed_trades, state.equity_curve, config)

        return SimulationResult(
            trades=state.closed_trades,
            equity_curve=state.equity_curve,
            metrics=metrics,
            warnings=warnings,
            filter_stats={
                "signals_total": len(signals),
                "signals_filtered": state.signals_filtered,
                "signals_entered": state.signals_entered,
            },
        )

    # --- Filter chain implementation ---

    def _process_batch_signals(
        self,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        current_time: datetime,
    ) -> int:
        """Process signals in batch mode: dedup → rank → filter → enter."""
        # Step 1: Deduplicate by ticker (keep LAST occurrence — dict overwrite)
        deduped: dict[str, dict] = {}
        for sig in scan_signals:
            deduped[sig["ticker"]] = sig
        unique_signals = list(deduped.values())

        # Step 2: Rank by abs(score) descending
        unique_signals.sort(key=lambda s: abs(s.get("score", 0)), reverse=True)

        # Step 3: Apply filter chain (strict pass)
        entered = 0
        for sig in unique_signals:
            if self._apply_filter_chain(config, sig, state, current_time, relaxed=False):
                if self._open_position(config, sig, klines, state, current_time):
                    entered += 1

        # Step 4: fill_to_max_trades relaxed pass
        if config.get("fill_to_max_trades") and entered < config.get("max_trades", 999):
            remaining = [s for s in unique_signals if s["ticker"] not in
                         {p.symbol for p in state.open_positions}]
            remaining.sort(key=lambda s: abs(s.get("score", 0)), reverse=True)
            for sig in remaining:
                if entered >= config.get("max_trades", 999):
                    break
                if self._apply_filter_chain(config, sig, state, current_time, relaxed=True):
                    if self._open_position(config, sig, klines, state, current_time, relaxed=True):
                        entered += 1

        return entered

    def _process_immediate_signals(
        self,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        current_time: datetime,
    ) -> int:
        """Process signals in immediate mode: one-at-a-time, no dedup."""
        entered = 0
        for sig in scan_signals:
            if self._apply_filter_chain(config, sig, state, current_time, relaxed=False):
                if self._open_position(config, sig, klines, state, current_time):
                    entered += 1
        return entered

    def _apply_filter_chain(
        self,
        config: dict[str, Any],
        signal: dict[str, Any],
        state: SimulationState,
        current_time: datetime,
        relaxed: bool = False,
    ) -> bool:
        """Apply 17-step filter chain. Returns True if signal passes all filters."""
        from backend.services.trading_rules import determine_side

        ticker = signal.get("ticker", "")
        direction = signal.get("direction", "")
        score = signal.get("score", 0)
        confidence = signal.get("confidence", "none")

        # 1. Status check (already filtered in _load_signals, but double-check)
        # (Skipped — signals are pre-filtered to status='completed')

        # 2. Ticker validity
        if not ticker:
            state.signals_filtered += 1
            return False

        # 3. Blacklist
        blacklist = config.get("symbol_blacklist") or []
        if ticker in blacklist or f"{ticker}USDT" in blacklist:
            state.signals_filtered += 1
            return False

        # 4. Whitelist (if set, must be in it)
        whitelist = config.get("symbol_whitelist")
        if whitelist and ticker not in whitelist and f"{ticker}USDT" not in whitelist:
            state.signals_filtered += 1
            return False

        # 5. Existing position (no duplicate positions on same symbol)
        existing_symbols = {p.symbol for p in state.open_positions}
        if ticker in existing_symbols:
            state.signals_filtered += 1
            return False

        # 6. Signal age (strict only)
        if not relaxed:
            max_age = config.get("max_signal_age_minutes")
            if max_age is not None:
                signal_time = signal.get("signal_time")
                if signal_time and current_time:
                    age_minutes = (current_time - signal_time).total_seconds() / 60
                    if age_minutes > max_age:
                        state.signals_filtered += 1
                        return False

        # 7. Hold skip
        if direction == "hold":
            state.signals_filtered += 1
            return False

        # 8. Max same direction
        max_same_dir = config.get("max_same_direction")
        if max_same_dir is not None:
            trade_side = determine_side(direction, config.get("direction", "straight"))
            same_dir_count = sum(1 for p in state.open_positions if p.side == trade_side)
            if same_dir_count >= max_same_dir:
                state.signals_filtered += 1
                return False

        # 9. Sector concentration limit (simplified — no sector service in backtest)
        # TODO: Could add sector lookup if needed. For now, skip.

        # 10. Adaptive blacklist (computed from backtest's own trade history)
        if config.get("adaptive_blacklist_enabled"):
            if self._is_adaptively_blacklisted(config, ticker, state, current_time):
                state.signals_filtered += 1
                return False

        # 11. Signal sides filter
        signal_sides = config.get("signal_sides", "both")
        if signal_sides != "both":
            if signal_sides in ("buy", "long") and direction not in ("buy", "long"):
                state.signals_filtered += 1
                return False
            if signal_sides in ("sell", "short") and direction not in ("sell", "short"):
                state.signals_filtered += 1
                return False

        # 12. Min score (strict only)
        if not relaxed:
            min_score = config.get("min_score", 0.0)
            if abs(score) < min_score:
                state.signals_filtered += 1
                return False

        # 13. Confidence filter (strict only)
        if not relaxed:
            conf_filter = config.get("confidence_filter", "any")
            if conf_filter != "any":
                conf_levels = {"high": 3, "moderate": 2, "low": 1, "none": 0}
                required = conf_levels.get(conf_filter, 0)
                actual = conf_levels.get(confidence, 0)
                if actual < required:
                    state.signals_filtered += 1
                    return False

        # 14. Max trades limit
        max_trades = config.get("max_trades", 999)
        if state.signals_entered >= max_trades:
            state.signals_filtered += 1
            return False

        # 15. Target goal (trade_count type)
        target_type = config.get("target_goal_type")
        target_value = config.get("target_goal_value")
        if target_type == "trade_count" and target_value:
            if state.signals_entered >= target_value:
                state.signals_filtered += 1
                return False

        # 16. Balance check
        if state.sizing_capital <= 0:
            state.signals_filtered += 1
            return False

        # 17. Price drift validation
        max_drift = config.get("max_price_drift_pct")
        if max_drift is not None:
            analysis_price = signal.get("analysis_price")
            if analysis_price and analysis_price > 0:
                # Get price at signal time (NOT end of dataset — avoid look-ahead bias)
                symbol_klines = klines.get(ticker, [])
                current_price = None
                for k in symbol_klines:
                    if k["open_time"] >= current_time:
                        current_price = k["close"]
                        break
                if current_price is not None:
                    drift = abs(current_price - analysis_price) / analysis_price * 100
                    if drift > max_drift:
                        state.signals_filtered += 1
                        return False

        return True  # All 17 filters passed

    def _open_position(
        self,
        config: dict[str, Any],
        signal: dict[str, Any],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        current_time: datetime,
        relaxed: bool = False,
    ) -> bool:
        """Open a new position from a qualifying signal. Returns True on success."""
        from backend.services.trading_rules import (
            determine_side, apply_slippage, compute_tp_sl,
            compute_position_size, compute_liquidation_price,
            compute_fee, compute_locked_margin,
        )

        ticker = signal["ticker"]
        direction = signal["direction"]

        # Get entry price from klines at signal time
        symbol_klines = klines.get(ticker, [])
        if not symbol_klines:
            return False

        # Find the kline at or near signal_time (use last available candle close)
        entry_base_price = symbol_klines[-1]["close"]
        for k in symbol_klines:
            if k["open_time"] >= current_time:
                entry_base_price = k["close"]
                break

        # Apply slippage
        side = determine_side(direction, config.get("direction", "straight"))
        entry_price = apply_slippage(entry_base_price, side, config.get("slippage_bps", 2))

        # Compute position size
        leverage = config.get("leverage", 20)
        capital_pct = config.get("capital_pct", 5.0)

        # Available balance = wallet - locked margins
        locked = sum(p.locked_margin for p in state.open_positions)
        available = state.wallet_balance - locked

        qty = compute_position_size(
            sizing_capital=state.sizing_capital,
            capital_pct=capital_pct,
            leverage=leverage,
            price=entry_price,
            qty_step=0.001,  # TODO: get from instrument cache
            min_qty=0.001,   # TODO: get from instrument cache
            available_balance=available,
        )
        if qty is None:
            state.signals_filtered += 1
            return False

        # Compute TP/SL
        tp_pct = config.get("take_profit_pct", 150.0)
        sl_pct = config.get("stop_loss_pct", 100.0)
        tp_price, sl_price = compute_tp_sl(entry_price, side, tp_pct, sl_pct, leverage)

        # Compute liquidation price
        liq_price = compute_liquidation_price(entry_price, side, leverage)

        # Compute entry fee
        fee_rate = config.get("fee_rate_pct", 0.055)
        entry_fee = compute_fee(qty, entry_price, fee_rate)

        # Compute locked margin
        margin = compute_locked_margin(qty, entry_price, leverage)

        # Deduct entry fee from wallet
        state.wallet_balance -= entry_fee

        # Create position
        position = Position(
            symbol=ticker,
            side=side,
            entry_price=entry_price,
            qty=qty,
            leverage=leverage,
            entry_time=current_time,
            tp_price=tp_price,
            sl_price=sl_price,
            liq_price=liq_price,
            entry_fee=entry_fee,
            locked_margin=margin,
            scan_id=signal.get("scan_id", ""),
            signal_score=signal.get("score", 0),
            signal_confidence=signal.get("confidence", ""),
            max_favorable_price=entry_price,
            max_adverse_price=entry_price,
        )
        state.open_positions.append(position)
        state.signals_entered += 1  # Increment immediately so max_trades filter works

        # Set cycle_start_equity on first position of a cycle
        if state.cycle_start_equity == 0:
            state.cycle_start_equity = state.wallet_balance

        return True

    def _is_adaptively_blacklisted(
        self,
        config: dict[str, Any],
        ticker: str,
        state: SimulationState,
        current_time: datetime,
    ) -> bool:
        """Check if symbol is adaptively blacklisted based on backtest trade history."""
        lookback_hours = config.get("adaptive_blacklist_lookback_hours", 48)
        min_trades = config.get("adaptive_blacklist_min_trades", 5)
        max_win_rate = config.get("adaptive_blacklist_max_win_rate", 30.0)

        cutoff = current_time - timedelta(hours=lookback_hours)

        # Count wins and total trades for this ticker in simulated time window
        wins = 0
        total = 0
        for trade in state.closed_trades:
            if trade.get("symbol") != ticker:
                continue
            exit_time = trade.get("exit_time")
            if exit_time and exit_time >= cutoff:
                total += 1
                if (trade.get("pnl") or 0) > 0:
                    wins += 1

        if total < min_trades:
            return False

        win_rate = (wins / total) * 100.0
        return win_rate < max_win_rate

    def _compute_total_unrealized(self, state: SimulationState, current_price_unused: float) -> float:
        """Compute total unrealized PnL across all open positions."""
        from backend.services.trading_rules import compute_unrealized_pnl
        total = 0.0
        for pos in state.open_positions:
            # Use entry_price as proxy when no current price available
            total += compute_unrealized_pnl(pos.entry_price, pos.entry_price, pos.qty, pos.side)
        return total

    def _evaluate_candles_until(
        self,
        config: dict[str, Any],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        start_time: datetime,
        end_time: Optional[datetime],
        cancel_event: Optional[threading.Event],
    ) -> None:
        """Evaluate close rules using a UNIFIED chronological timeline.

        Merges all open-position symbols' candles into one sorted-by-time stream.
        At each timestamp, ALL symbols' prices are available so equity/trailing
        rules compute correctly for multi-symbol backtests.
        """
        if not state.open_positions:
            return

        fee_rate = config.get("fee_rate_pct", 0.055)
        open_symbols = {p.symbol for p in state.open_positions}

        # Build per-symbol filtered candle series (after start_time, before end_time)
        symbol_time_idx: dict[str, dict[datetime, dict]] = {}
        all_timestamps: set[datetime] = set()
        for sym in open_symbols:
            sym_klines = klines.get(sym, [])
            idx: dict[datetime, dict] = {}
            for k in sym_klines:
                kt = k["open_time"]
                if kt <= start_time:
                    continue
                if end_time and kt >= end_time:
                    continue
                idx[kt] = k
                all_timestamps.add(kt)
            if idx:
                symbol_time_idx[sym] = idx

        if not all_timestamps:
            return

        sorted_timestamps = sorted(all_timestamps)

        # Track latest known close per symbol (seed with entry price)
        latest_prices: dict[str, float] = {p.symbol: p.entry_price for p in state.open_positions}
        candle_count = 0

        # Process timestamps chronologically — unified timeline
        for candle_time in sorted_timestamps:
            if not state.open_positions:
                break

            candle_count += 1
            if candle_count % 100 == 0 and cancel_event and cancel_event.is_set():
                raise BacktestCancelled("Cancelled during candle evaluation")

            # Gather candles for all symbols at this timestamp; update latest prices
            candles_at_time: dict[str, dict] = {}
            for sym in list(open_symbols):
                candle = symbol_time_idx.get(sym, {}).get(candle_time)
                if candle:
                    latest_prices[sym] = candle["close"]
                    candles_at_time[sym] = candle

            # --- FUNDING RATE (once per timestamp) ---
            funding_model = config.get("funding_rate_model", "none")
            if funding_model == "fixed_8h":
                if candle_time.hour in (0, 8, 16) and candle_time.minute < 5:
                    funding_rate = config.get("funding_rate_fixed_pct", 0.01) / 100.0
                    for fp in state.open_positions:
                        price = latest_prices.get(fp.symbol, fp.entry_price)
                        payment = fp.qty * price * funding_rate
                        if fp.side == "Buy":
                            state.wallet_balance -= payment
                        else:
                            state.wallet_balance += payment

            # --- PER-POSITION: liquidation + TP/SL (only symbols with a candle now) ---
            positions_to_close: list[tuple] = []
            for pos in list(state.open_positions):
                candle = candles_at_time.get(pos.symbol)
                if not candle:
                    continue
                high = candle["high"]
                low = candle["low"]

                # Update MFE/MAE
                if pos.side == "Buy":
                    pos.max_favorable_price = max(pos.max_favorable_price, high)
                    pos.max_adverse_price = min(pos.max_adverse_price, low) if pos.max_adverse_price > 0 else low
                else:
                    pos.max_favorable_price = min(pos.max_favorable_price, low) if pos.max_favorable_price > 0 else low
                    pos.max_adverse_price = max(pos.max_adverse_price, high)

                # LIQUIDATION (SL-wins-if-closer)
                if pos.side == "Buy" and low <= pos.liq_price:
                    if pos.sl_price > pos.liq_price and low <= pos.sl_price:
                        positions_to_close.append((pos, "sl", pos.sl_price, candle_time))
                    else:
                        positions_to_close.append((pos, "liquidation", pos.liq_price, candle_time))
                    continue
                elif pos.side == "Sell" and high >= pos.liq_price:
                    if pos.sl_price < pos.liq_price and high >= pos.sl_price:
                        positions_to_close.append((pos, "sl", pos.sl_price, candle_time))
                    else:
                        positions_to_close.append((pos, "liquidation", pos.liq_price, candle_time))
                    continue

                # TP/SL (pessimistic: SL wins when both hit)
                close_reason = None
                exit_price = None
                if pos.side == "Buy":
                    sl_hit = low <= pos.sl_price
                    tp_hit = high >= pos.tp_price
                    if sl_hit:
                        close_reason, exit_price = "sl", pos.sl_price
                    elif tp_hit:
                        close_reason, exit_price = "tp", pos.tp_price
                else:
                    sl_hit = high >= pos.sl_price
                    tp_hit = low <= pos.tp_price
                    if sl_hit:
                        close_reason, exit_price = "sl", pos.sl_price
                    elif tp_hit:
                        close_reason, exit_price = "tp", pos.tp_price

                if close_reason and exit_price:
                    positions_to_close.append((pos, close_reason, exit_price, candle_time))

            # Close TP/SL/liquidation positions
            for pos, reason, exit_price, exit_time in positions_to_close:
                if pos in state.open_positions:
                    self._close_position(state, pos, reason, exit_price, exit_time, fee_rate)

            # --- EQUITY RULES (complete latest_prices for ALL symbols) ---
            if state.open_positions and state.cycle_start_equity > 0:
                self._evaluate_equity_rules(config, state, latest_prices, candle_time, fee_rate)

            # --- TRAILING PROFIT (per symbol, using that symbol's candle) ---
            trailing_pct = config.get("trailing_profit_pct")
            if trailing_pct and state.open_positions:
                for sym, candle in candles_at_time.items():
                    self._evaluate_trailing_profit_for_symbol(config, state, sym, candle, candle_time, fee_rate)

            # --- TIME RULES (use per-symbol latest price for exits) ---
            if state.open_positions:
                self._evaluate_time_rules(config, state, candle_time, fee_rate, latest_prices)

    def _close_position(
        self,
        state: SimulationState,
        position: Position,
        close_reason: str,
        exit_price: float,
        exit_time: datetime,
        fee_rate: float,
    ) -> None:
        """Close a position: compute PnL, update wallet, record trade."""
        from backend.services.trading_rules import compute_unrealized_pnl, compute_fee, compute_liquidation_pnl

        # Compute realized PnL
        if close_reason == "liquidation":
            # Liquidation: full margin loss (Bybit isolated)
            net_pnl = compute_liquidation_pnl(position.locked_margin, position.entry_fee)
            exit_fee = 0.0  # liquidation fee already in the pnl calc
        else:
            pnl = compute_unrealized_pnl(position.entry_price, exit_price, position.qty, position.side)
            exit_fee = compute_fee(position.qty, exit_price, fee_rate)
            net_pnl = pnl - exit_fee  # entry_fee already deducted at open

        # Update wallet
        # Model: wallet_balance includes locked margin (never deducted on open, only entry_fee deducted)
        # On normal close: add net_pnl (margin stays in wallet, PnL adjusts it)
        # On liquidation: LOSE the locked margin (deduct it now)
        if close_reason == "liquidation":
            state.wallet_balance -= position.locked_margin  # margin is lost
        else:
            state.wallet_balance += net_pnl  # PnL adjusts wallet (no margin return needed)

        # Compute MFE/MAE percentages (guard against zero entry_price)
        if position.entry_price <= 0:
            mfe_pct = 0.0
            mae_pct = 0.0
        elif position.side == "Buy":
            mfe_pct = (position.max_favorable_price - position.entry_price) / position.entry_price * 100 * position.leverage
            mae_pct = (position.entry_price - position.max_adverse_price) / position.entry_price * 100 * position.leverage
        else:
            mfe_pct = (position.entry_price - position.max_favorable_price) / position.entry_price * 100 * position.leverage
            mae_pct = (position.max_adverse_price - position.entry_price) / position.entry_price * 100 * position.leverage

        # Record closed trade
        trade_record = {
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "qty": position.qty,
            "leverage": position.leverage,
            "entry_time": position.entry_time,
            "exit_time": exit_time,
            "pnl": net_pnl,
            "pnl_pct": (net_pnl / position.locked_margin) * 100 if position.locked_margin else 0,
            "fees_paid": position.entry_fee + exit_fee,
            "close_reason": close_reason,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "signal_score": position.signal_score,
            "signal_confidence": position.signal_confidence,
            "scan_id": position.scan_id,
        }
        state.closed_trades.append(trade_record)

        # Remove from open positions
        state.open_positions.remove(position)

    def _evaluate_equity_rules(
        self,
        config: dict[str, Any],
        state: SimulationState,
        latest_prices: dict[str, float],
        candle_time: datetime,
        fee_rate: float,
    ) -> None:
        """Evaluate equity-based close rules: EQUITY_DROP_PCT, SMART, close_on_profit.

        Called once per candle AFTER TP/SL closures (wallet already updated).
        Uses per-symbol latest close price for unrealized PnL calculation.
        """
        from backend.services.trading_rules import (
            compute_unrealized_pnl, check_equity_drop, check_close_on_profit,
        )

        if not state.open_positions:
            return

        # Compute current equity (wallet + sum of unrealized PnL)
        total_upnl = 0.0
        losing_positions = []
        for pos in state.open_positions:
            # Use per-symbol latest price (not a single symbol's close)
            current_price = latest_prices.get(pos.symbol, pos.entry_price)
            # Approximation: use same close_price for simplicity in per-symbol loop
            # In production this uses actual mark price per symbol
            upnl = compute_unrealized_pnl(pos.entry_price, current_price, pos.qty, pos.side)
            total_upnl += upnl
            if upnl < 0:
                losing_positions.append(pos)

        equity = state.wallet_balance + total_upnl

        # --- EQUITY_DROP_PCT / EQUITY_DROP_PCT_SMART ---
        max_drawdown_pct = config.get("max_drawdown_pct", 100.0)
        if max_drawdown_pct < 100.0:
            if check_equity_drop(equity, state.cycle_start_equity, max_drawdown_pct):
                if config.get("smart_drawdown_close"):
                    # SMART: close only LOSING positions, keep others active
                    if losing_positions:
                        for pos in list(losing_positions):
                            self._close_position(state, pos, "equity_drop_smart", latest_prices.get(pos.symbol, pos.entry_price), candle_time, fee_rate)
                        # Reset reference equity (prevents immediate re-trigger)
                        new_equity = state.wallet_balance + sum(
                            compute_unrealized_pnl(p.entry_price, latest_prices.get(p.symbol, p.entry_price), p.qty, p.side)
                            for p in state.open_positions
                        )
                        state.cycle_start_equity = new_equity
                    else:
                        # No losers → reset reference, don't close anything
                        state.cycle_start_equity = equity
                else:
                    # Non-SMART: close ALL positions, deactivate cycle
                    for pos in list(state.open_positions):
                        self._close_position(state, pos, "equity_drop", latest_prices.get(pos.symbol, pos.entry_price), candle_time, fee_rate)
                    state.cycle_start_equity = 0  # Cycle terminated
                return  # Don't evaluate further rules after equity drop

        # --- close_on_profit_pct ---
        close_on_profit = config.get("close_on_profit_pct")
        target_goal_value = config.get("target_goal_value", 100.0)
        if close_on_profit and state.cycle_start_equity > 0:
            if check_close_on_profit(equity, state.cycle_start_equity, close_on_profit, target_goal_value or 100.0):
                for pos in list(state.open_positions):
                    self._close_position(state, pos, "close_on_profit", latest_prices.get(pos.symbol, pos.entry_price), candle_time, fee_rate)
                state.cycle_start_equity = 0  # Cycle terminated

    def _evaluate_trailing_profit_for_symbol(
        self,
        config: dict[str, Any],
        state: SimulationState,
        symbol: str,
        candle: dict[str, Any],
        candle_time: datetime,
        fee_rate: float,
    ) -> None:
        """Evaluate trailing profit for positions on a SPECIFIC symbol.

        State machine (matches production _evaluate_trailing_profit):
        1. If upnl <= 0: clear peak, skip (position underwater)
        2. If profit_pct < activation_pct: skip but DO NOT clear peak
        3. If per_unit_pnl > stored_peak: update peak (new high)
        4. If per_unit_pnl < peak × 0.5: CLOSE position
        """
        from backend.services.trading_rules import compute_unrealized_pnl, check_trailing_activation

        trailing_pct = config.get("trailing_profit_pct", 0)
        if not trailing_pct:
            return

        close_price = candle["close"]
        positions_to_close = []

        for pos in state.open_positions:
            # ONLY evaluate positions on THIS symbol (uses THIS symbol's candle)
            if pos.symbol != symbol:
                continue

            # Compute unrealized PnL at candle close
            upnl = compute_unrealized_pnl(pos.entry_price, close_price, pos.qty, pos.side)

            # Step 1: If upnl <= 0, clear peak and skip
            if upnl <= 0:
                pos.trailing_active = False
                pos.trailing_peak = 0.0
                continue

            # Step 2: Check activation (price move % >= threshold AND upnl > 0)
            if not check_trailing_activation(close_price, pos.entry_price, trailing_pct, upnl):
                # Below activation — DO NOT clear peak (preserve from prior activation)
                # BUT: if already trailing, still check trigger (price retraced below activation)
                if pos.trailing_active and pos.trailing_peak > 0:
                    per_unit_pnl = upnl / pos.qty if pos.qty > 0 else 0.0
                    if per_unit_pnl < pos.trailing_peak * 0.5:
                        positions_to_close.append(pos)
                continue

            # Position is profitable and above activation threshold
            per_unit_pnl = upnl / pos.qty if pos.qty > 0 else 0.0

            # Use candle high/low for peak (more accurate)
            if pos.side == "Buy":
                peak_price = candle["high"]
                peak_upnl = compute_unrealized_pnl(pos.entry_price, peak_price, pos.qty, pos.side)
            else:
                peak_price = candle["low"]
                peak_upnl = compute_unrealized_pnl(pos.entry_price, peak_price, pos.qty, pos.side)

            peak_per_unit = peak_upnl / pos.qty if pos.qty > 0 and peak_upnl > 0 else per_unit_pnl

            # Step 3: Update peak if new high
            if peak_per_unit > pos.trailing_peak:
                pos.trailing_peak = peak_per_unit
                pos.trailing_active = True
                continue

            # Step 4: Check trigger — per_unit_pnl < peak × 0.5
            if pos.trailing_active and pos.trailing_peak > 0:
                if per_unit_pnl < pos.trailing_peak * 0.5:
                    positions_to_close.append(pos)

        # Close triggered positions
        for pos in positions_to_close:
            self._close_position(state, pos, "trailing_profit", close_price, candle_time, fee_rate)

    def _evaluate_time_rules(
        self,
        config: dict[str, Any],
        state: SimulationState,
        candle_time: datetime,
        fee_rate: float,
        latest_prices: Optional[dict[str, float]] = None,
    ) -> None:
        """Evaluate time-based close rules: BREAKEVEN_TIMEOUT and MAX_DURATION.

        BREAKEVEN_TIMEOUT: modifies TP to breakeven (does NOT close).
            If position is actively trailing → SKIP (trailing takes priority).
        MAX_DURATION: force-closes after elapsed hours at the symbol's latest price.
        """
        from backend.services.trading_rules import compute_breakeven_price

        breakeven_hours = config.get("breakeven_timeout_hours")
        max_duration_hours = config.get("max_trade_duration_hours")

        if not breakeven_hours and not max_duration_hours:
            return

        latest_prices = latest_prices or {}
        positions_to_close = []

        for pos in list(state.open_positions):
            elapsed_hours = (candle_time - pos.entry_time).total_seconds() / 3600.0

            # MAX_DURATION: force close after max hours
            if max_duration_hours and elapsed_hours >= max_duration_hours:
                positions_to_close.append(pos)
                continue

            # BREAKEVEN_TIMEOUT: modify TP to breakeven price
            if breakeven_hours and elapsed_hours >= breakeven_hours:
                # If position is in active trailing → SKIP (trailing takes priority)
                if pos.trailing_active:
                    continue
                # Modify TP to breakeven price
                new_tp = compute_breakeven_price(pos.entry_price, pos.side, pos.leverage)
                pos.tp_price = new_tp

        # Close MAX_DURATION positions at the symbol's latest price
        for pos in positions_to_close:
            exit_price = latest_prices.get(pos.symbol, pos.entry_price)
            self._close_position(state, pos, "max_duration", exit_price, candle_time, fee_rate)
