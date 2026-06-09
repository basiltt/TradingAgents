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
from backend.services.trading_rules import (
    DEFAULT_CAPITAL_PCT,
    DEFAULT_LEVERAGE,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
)

logger = logging.getLogger(__name__)


class BacktestCancelled(Exception):
    """Raised when a backtest is cancelled via cancel_event."""


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
    # Regime Multi-Strategy: "trend" (default) or "mean_reversion". An MR position
    # also carries its own fast time-stop (minutes) — F2's strategy-critical exit.
    strategy_kind: str = "trend"
    time_stop_minutes: Optional[float] = None
    # Trailing profit state
    trailing_active: bool = False
    trailing_peak: float = 0.0
    # MFE/MAE tracking
    max_favorable_price: float = 0.0
    max_adverse_price: float = 0.0
    # Cumulative funding paid by this position (positive = cost to the trader,
    # negative = credit). Folded into the recorded trade pnl at close so that
    # sum(trade.pnl) reconciles with the wallet/final_equity.
    funding_paid: float = 0.0
    # 1-minute drill-down state. entry_bar_open = the 5m bar (open_time) the entry
    # filled in (used by the service to locate the exit-bar window). Entry drill-down
    # is price-only, so it never restricts a bar's evaluation.
    entry_bar_open: Optional[datetime] = None
    # Stable equity-reference entry price = the UN-drilled 5m next-bar-open fill. The
    # equity close-rules (drawdown / rise / close_on_profit) value this position's uPnL
    # off THIS price, NOT the drilled entry_price, so toggling drill-down never changes
    # the equity cascade — i.e. never changes WHICH trades happen (selection +
    # skip_if_positions_open stay identical to the pure 5m run). Drill-down refines
    # entry_price for the trade's reported fill + realized PnL only. 0.0 ⇒ fall back to
    # entry_price (no drill), so the two are equal and behaviour is unchanged.
    equity_ref_entry: float = 0.0


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
    signals_entered: int = 0  # LIFETIME entries across the whole backtest (stats + target_goal)
    scan_entered: int = 0  # entries in the CURRENT scan only — reset each scan; gates max_trades
                           # (production creates a fresh executor per scan, so max_trades is per-cycle)
    signals_no_kline: int = 0  # signals dropped because the symbol had NO cached candles —
                               # production would have traded them, so this means the backtest
                               # UNDER-trades vs reality; surfaced as a warning, not a silent skip.
    slippage_bps: int = 0  # round-trip slippage; applied adversely on BOTH entry fill and exit fill
                           # (production closes via Bybit market reduce-only orders that slip)
    smart_drawdown_fired: bool = False  # EQUITY_DROP_PCT_SMART is ONE-SHOT per scan
                           # window: production closes losers once, marks the rule
                           # "executed", and never re-arms it until the next scan
                           # re-creates it. Reset each scan; gates re-firing so the
                           # backtest can't over-close winners-turned-losers mid-window.
    # Last 8h funding boundary already charged, as (date, hour) — guards against
    # charging funding more than once per 0/8/16h event regardless of candle density
    # (so a finer interval than 5m can't multi-charge a single boundary).
    last_funding_boundary: Optional[tuple] = None


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
        instrument_info: Optional[dict[str, dict[str, float]]] = None,
        scan_contexts: Optional[dict[str, Any]] = None,
        fine_klines: Optional[dict[str, dict[int, list[dict[str, Any]]]]] = None,
    ) -> SimulationResult:
        """Execute the backtest simulation.

        Args:
            config: Full backtest configuration (all AutoTradeConfig fields + backtest-specific).
            signals: Chronological list of scan result signals (from _load_signals).
            klines: Dict mapping symbol → list of kline dicts (ascending by open_time).
            cancel_event: If set, engine raises BacktestCancelled at next check point.
            on_progress: Called with percentage (0-100) at regular intervals.
            instrument_info: Optional {symbol: {qty_step, min_qty, tick_size,
                max_leverage}} resolved by the service from the InstrumentInfoCache.
                When provided, position sizing rounds qty to the symbol's real lot
                step / rejects below min_qty, TP/SL are rounded to tick_size, and
                leverage is capped to the symbol's max — matching live trading. When
                None, conservative defaults (0.001 / 0.001 / 0.01 / no cap) are used.

        Returns:
            SimulationResult with trades, equity_curve, metrics, warnings, filter_stats.

        Raises:
            BacktestCancelled: If cancel_event is set during execution.
        """
        # Per-symbol instrument parameters (lot step, min qty, tick size, max
        # leverage). Stored on the instance so the pure sizing/_open_position path can
        # read it without threading it through every call. Empty dict → defaults.
        self._instrument_info: dict[str, dict[str, float]] = instrument_info or {}

        # Regime Multi-Strategy (F1/F2/F3): {scan_id: ScanContext} from the service.
        # None/{} ⇒ no feature active ⇒ the regime block in _apply_filter_chain /
        # _open_position is never entered, so the engine is byte-identical to before
        # (golden guarantee). self._ctx / self._mr_params are per-scan / per-signal
        # transients set during the single-threaded run (safe: one run() per thread).
        self._scan_contexts: dict[str, Any] = scan_contexts or {}
        self._ctx: Any = None            # current scan's ScanContext (or None)
        self._mr_mean: float | None = None  # scan-time EMA mean for the signal being opened (MR)

        # 1-minute drill-down windows: {symbol: {bar_open_epoch: [1m candles covering
        # that 5m bar, ascending]}}. None/{} ⇒ NO drill-down ⇒ every drill code path
        # short-circuits and the engine is byte-identical to the 5m-only behaviour
        # (golden guarantee). The service builds this only for the entry+exit bars of
        # actual trades (two-phase). The engine branches solely on the PRESENCE of a
        # window here — never on any config flag.
        self._fine_klines: dict[str, dict[int, list[dict[str, Any]]]] = fine_klines or {}

        # Initialize state
        starting_capital = config["starting_capital"]
        state = SimulationState(
            wallet_balance=starting_capital,
            sizing_capital=starting_capital,
            slippage_bps=config.get("slippage_bps", 2),
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

        # Seed the equity curve with the starting-capital anchor at the first
        # signal time, so the curve begins at (start, starting_capital). Without
        # this, the first recorded point would be the first trade's CLOSE, hiding
        # the start→first-close move from drawdown/run-up/Sharpe and leaving a
        # single-trade run with a degenerate 1-point curve.
        if scan_order:
            state.equity_curve.append({
                "ts": scans[scan_order[0]][0]["signal_time"],
                "equity": starting_capital,
                "drawdown_pct": 0.0,
            })

        # Fallback default matches the contract default (BacktestCreateRequest /
        # production AutoTradeConfig both default execution_mode to "immediate"). The
        # API always sends the key explicitly, so this only governs internal/partial
        # config dicts — but it must agree with the schema so they can't silently diverge.
        execution_mode = config.get("execution_mode", "immediate")
        candle_count = 0

        for scan_idx, scan_id in enumerate(scan_order):
            # Check cancellation every scan
            if cancel_event and cancel_event.is_set():
                raise BacktestCancelled("Cancelled during simulation")

            scan_signals = scans[scan_id]
            current_time = scan_signals[0]["signal_time"]

            # Bind this scan's ScanContext (or None) for the regime gate/route block.
            self._ctx = self._scan_contexts.get(scan_id)

            # Reset the per-scan entry counter. max_trades caps NEW trades per scan
            # (cycle), mirroring production, which builds a fresh AutoTradeExecutor
            # per scan with trades_executed=0. The lifetime signals_entered is left
            # untouched (it drives the backtest-level target_goal early-stop + stats).
            state.scan_entered = 0

            # NOTE: the equity-rule reference (cycle_start_equity) is re-anchored
            # below at the per-scan sizing refresh — for EVERY non-skipped scan, to the
            # available-balance basis, mirroring production. See that block for the
            # full rationale. The skip_if_positions_open early-continue below preserves
            # the existing anchor (production's only preservation case).

            # --- CYCLE LOCK (Task 3.9) ---
            # If skip_if_positions_open=True AND positions exist → skip entire scan
            if config.get("skip_if_positions_open") and state.open_positions:
                state.signals_filtered += len(scan_signals)
                # Still evaluate close rules on the carried positions until the next
                # scan. We deliberately do NOT re-trade this scan's signals if the
                # book clears mid-window: production's post_scan_recheck fires ONCE,
                # synchronously at scan completion (scanner_service calls it right
                # after execute_batch — auto_trade_service.post_scan_recheck is a
                # single non-looping pass). Because each scan is anchored to its
                # completed_at timestamp, that instant is already modelled by the
                # per-scan open branch; positions clearing LATER in the window are not
                # re-traded by production until the NEXT scheduled scan (with its own
                # signals). See "Known Modeling Approximations" in the spec.
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

            # Refresh the per-scan available balance + re-anchor the equity reference,
            # then open this scan's signals. Extracted into a helper so the open
            # sequence (balance refresh, reference anchor, batch/immediate dispatch)
            # lives in exactly one place.
            self._open_scan_signals(config, scan_signals, klines, state, current_time, execution_mode)

            # --- CANDLE-BY-CANDLE CLOSE RULE EVALUATION (Task 3.3+) ---
            # After opening positions, evaluate close rules on subsequent candles
            # until next scan event (or end of data)
            next_scan_time = None
            if scan_idx + 1 < len(scan_order):
                next_scan_id = scan_order[scan_idx + 1]
                next_scan_time = scans[next_scan_id][0]["signal_time"]

            # Evaluate open positions against candles until the next scan event.
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
            if "backtest_end" not in list(warnings):
                warnings.append(f"force_closed_{len([t for t in state.closed_trades if t.get('close_reason') == 'backtest_end'])}_positions_at_end")

        if on_progress:
            on_progress(100)

        # Ensure the equity curve is chronological before deriving path-dependent
        # metrics. Closes are appended in simulation-time order during the run,
        # but the end-of-data force-close tail stamps each position with its own
        # symbol's last candle time, which can be out of order across symbols.
        # Stable-sort by ts (the anchor's earliest ts and any None sort first).
        state.equity_curve.sort(
            key=lambda p: (p.get("ts") is not None, p.get("ts"))
        )

        # Append the AUTHORITATIVE terminal equity point AFTER the sort, so
        # equity_curve[-1] always reflects the true final wallet balance. (Without
        # this, an out-of-order force-close point from a short-coverage symbol
        # could sort to the end and make final_equity — read from curve[-1] by the
        # metrics layer — disagree with the wallet, breaking reconciliation.) Skip
        # only when the last sorted point already equals the final wallet, to
        # avoid a zero-length duplicate segment.
        final_equity = state.wallet_balance
        last_equity = state.equity_curve[-1]["equity"] if state.equity_curve else None
        if last_equity is None or abs(final_equity - last_equity) > 1e-9:
            state.equity_curve.append({
                "ts": signals[-1]["signal_time"] if signals else None,
                "equity": final_equity,
                "drawdown_pct": 0.0,
            })

        # Backfill real drawdown-from-peak on every equity point. The points were
        # appended with a 0.0 placeholder; compute the actual running-peak
        # drawdown so the persisted curve drives the frontend drawdown chart
        # correctly (the frontend only derives drawdown when the field is absent,
        # so a 0.0 placeholder would otherwise render a flat-zero overlay).
        _peak = float("-inf")
        for _pt in state.equity_curve:
            _eq = _pt.get("equity")
            if _eq is None:
                continue
            if _eq > _peak:
                _peak = _eq
            _pt["drawdown_pct"] = (
                round(((_eq - _peak) / _peak) * 100.0, 4) if _peak > 0 else 0.0
            )

        # Compute all metrics from trades + equity curve
        from backend.services.backtest_metrics import compute_all_metrics
        metrics = compute_all_metrics(state.closed_trades, state.equity_curve, config)

        # Surface any input sanitization the metrics layer had to perform as
        # warnings — silent coercion of bad engine data would otherwise hide
        # data-integrity problems behind plausible-but-wrong numbers.
        diag = metrics.get("diagnostics") or {}
        if diag.get("trades_dropped_non_dict"):
            warnings.append(f"metrics_dropped_{diag['trades_dropped_non_dict']}_malformed_trades")
        if diag.get("equity_points_dropped_non_dict"):
            warnings.append(f"metrics_dropped_{diag['equity_points_dropped_non_dict']}_malformed_equity_points")
        if diag.get("trade_pnls_sanitized"):
            warnings.append(f"metrics_sanitized_{diag['trade_pnls_sanitized']}_non_finite_pnls")
        if diag.get("equity_values_sanitized"):
            warnings.append(f"metrics_sanitized_{diag['equity_values_sanitized']}_non_finite_equity_values")

        return SimulationResult(
            trades=state.closed_trades,
            equity_curve=state.equity_curve,
            metrics=metrics,
            warnings=warnings,
            filter_stats={
                "signals_total": len(signals),
                "signals_filtered": state.signals_filtered,
                "signals_entered": state.signals_entered,
                "signals_no_kline": state.signals_no_kline,
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
            if (
                self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=False)
                and self._open_position(config, sig, klines, state, current_time)
            ):
                entered += 1

        # Step 4: fill_to_max_trades relaxed pass
        if config.get("fill_to_max_trades") and entered < config.get("max_trades", 999):
            remaining = [s for s in unique_signals if s["ticker"] not in
                         {p.symbol for p in state.open_positions}]
            remaining.sort(key=lambda s: abs(s.get("score", 0)), reverse=True)
            for sig in remaining:
                if entered >= config.get("max_trades", 999):
                    break
                if (
                    self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=True)
                    and self._open_position(config, sig, klines, state, current_time, relaxed=True)
                ):
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
            if (
                self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=False)
                and self._open_position(config, sig, klines, state, current_time)
            ):
                entered += 1

        # fill_to_max_trades backfill — mirrors production's fill_immediate_remaining
        # (auto_trade_service), which after the strict immediate pass relaxes the
        # filters to top the cycle up to max_trades, ranking the leftover signals by
        # abs(score). Without this the backtest under-fills any immediate-mode config
        # that enables fill_to_max_trades, diverging from real trading.
        if config.get("fill_to_max_trades") and state.scan_entered < config.get("max_trades", 999):
            open_syms = {p.symbol for p in state.open_positions}
            remaining = [
                s for s in scan_signals
                if s.get("ticker") not in open_syms and s.get("direction", "hold") != "hold"
            ]
            remaining.sort(key=lambda s: abs(s.get("score", 0)), reverse=True)
            for sig in remaining:
                if state.scan_entered >= config.get("max_trades", 999):
                    break
                if (
                    self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=True)
                    and self._open_position(config, sig, klines, state, current_time, relaxed=True)
                ):
                    entered += 1
        return entered

    @staticmethod
    def _regime_active(config: dict[str, Any]) -> bool:
        """True if any regime feature (F1/F2/F3) could affect this signal — the cheap
        top gate that keeps a default-off backtest on the exact original code path."""
        return bool(
            config.get("regime_filter_enabled")
            or config.get("mean_reversion_enabled")
            or (config.get("strategy_cohort") == "mean_reversion")
        )

    def _resolve_strategy(
        self,
        config: dict[str, Any],
        symbol: str,
        direction: str,
        current_time: datetime,
    ):
        """Resolve trend vs mean_reversion + apply F1 gates (mirror of live _try_trade).

        Returns (strategy, mr_mean|None), or None to SKIP the signal. Reuses the same
        pure functions as live: features.resolve_cohort, strategy_router.route_strategy,
        regime_filter.{gate_session,gate_btc_vol}. For an MR route it returns the
        ScanContext EMA mean; the fade side / geometry / TP are computed in
        _open_position from the REAL next-bar-open entry (more faithful + no look-ahead,
        no entry-price hack). A missing mean fails closed (MR unavailable)."""
        from backend.services import features as _feat
        from backend.services import regime_filter as _f1
        from backend.services import strategy_router as _router

        ctx = self._ctx
        cohort = _feat.resolve_cohort(config.get("strategy_cohort"), None) or "trend"
        is_mr_account = cohort == "mean_reversion" and bool(config.get("mean_reversion_enabled"))

        # Strategy routing (MR only runs in its regime; else "none" => skip).
        if is_mr_account:
            iv = config.get("btc_vol_interval", "1h")
            lb = int(config.get("btc_vol_lookback_candles", 14))
            regime = ctx.routing_regime(iv, lb) if ctx is not None else "unknown"
            strategy = _router.route_strategy("mean_reversion", regime,
                                              mr_regime=config.get("mr_regime", "ranging"))
            if strategy == "none":
                return None
        else:
            strategy = "trend"

        # F1 market-condition gates (apply to BOTH strategies; subtractive). Honor the
        # one-time manual session-filter override flag (mirrors live).
        if config.get("regime_filter_enabled"):
            if _f1.gate_session(config, current_time) is not None:
                return None
            if ctx is not None and _f1.gate_btc_vol(config, ctx) is not None:
                return None

        if strategy != "mean_reversion":
            return ("trend", None)

        # MR needs the scan-time EMA mean; the side/geometry/TP are computed at open
        # against the real next-bar-open entry. Missing mean => fail-closed skip.
        if ctx is None:
            return None
        period = int(config.get("mr_mean_period", 20))
        mean_iv = config.get("mr_mean_interval", "1h")
        mean = ctx.get_mean(symbol, period, mean_iv)
        if mean is None:
            return None  # MR_MEAN_UNAVAILABLE (fail-closed)
        return ("mean_reversion", mean)

    def _apply_filter_chain(
        self,
        config: dict[str, Any],
        signal: dict[str, Any],
        state: SimulationState,
        current_time: datetime,
        klines: dict[str, list[dict[str, Any]]],
        relaxed: bool = False,
    ) -> bool:
        """Apply 17-step filter chain (+ optional regime gate/route). Returns True if
        the signal passes all filters. When a regime feature is active, the F1/F2/F3
        block (mirroring live _try_trade) runs after the existing-position check; on an
        MR route the signal-direction gates (max_same_direction, signal_sides) are
        skipped because MR places in fade-space, not signal-space (live C3/C4)."""
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

        # Normalize the ticker to a full symbol exactly as production does
        # (auto_trade_service: f"{ticker}USDT" unless it already ends with USDT), then
        # match the blacklist/whitelist against THAT — production does NOT also match a
        # bare ticker, so neither must the backtest, or a bare-listed symbol would be
        # filtered here while production trades it.
        symbol = ticker if ticker.endswith("USDT") else f"{ticker}USDT"

        # 3. Blacklist
        blacklist = config.get("symbol_blacklist") or []
        if blacklist and symbol in blacklist:
            state.signals_filtered += 1
            return False

        # 4. Whitelist (if set, must be in it)
        whitelist = config.get("symbol_whitelist")
        if whitelist and symbol not in whitelist:
            state.signals_filtered += 1
            return False

        # 5. Existing position (no duplicate positions on same symbol)
        existing_symbols = {p.symbol for p in state.open_positions}
        if ticker in existing_symbols:
            state.signals_filtered += 1
            return False

        # ── Regime Multi-Strategy gate/route (no-op unless a feature is enabled) ──
        # Mirrors live _try_trade: resolve strategy (trend vs MR vs none) + F1 gates.
        # On an MR route, self._mr_mean carries the scan-time EMA mean forward to
        # _open_position (which computes the fade side/geometry/TP from the REAL
        # next-bar-open entry). Reset per signal.
        self._mr_mean = None
        is_mr = False
        if self._regime_active(config):
            resolved = self._resolve_strategy(config, symbol, direction, current_time)
            if resolved is None:
                state.signals_filtered += 1
                return False
            strategy, mr_mean = resolved
            if strategy == "mean_reversion":
                is_mr = True
                self._mr_mean = mr_mean
                # IR6 parity: enforce the consented MR CONCURRENT cap (mr_max_trades,
                # default 2), NOT the generic max_trades (default 999). Live counts
                # existing open MR positions (auto_trade_service _compute_mr_params); an
                # MR cohort is all-MR, so every open position counts. Without this the
                # backtest opens MR essentially every scan and wildly over-trades vs live.
                mr_cap = int(config.get("mr_max_trades", 2))
                if len(state.open_positions) >= mr_cap:
                    state.signals_filtered += 1
                    return False

        # 6. Signal age — enforced in BOTH strict and relaxed/fill mode, mirroring live
        # _try_trade (auto_trade_service): a stale signal is stale regardless of which
        # pass admits it. The relaxed fill bypasses min_score/confidence only, NOT the
        # freshness bound — without this the backtest over-fills any config that pairs
        # fill_to_max_trades with max_signal_age_minutes, diverging from real trading.
        #
        # Age is measured from the PER-TICKER analysis completion (analysis_completed_at),
        # NOT the scan-level signal_time: every signal in one scan shares the same
        # signal_time (the loader anchors it to the scan's completed_at), so measuring age
        # from signal_time would always yield 0 and make this gate a no-op on real data.
        # analysis_completed_at is the backtest analog of live's per-ticker
        # result.completed_at (set when each symbol's analysis finishes). Fall back to
        # signal_time when per-ticker completion is absent (legacy/synthetic data) so the
        # gate still enforces rather than silently bypassing.
        max_age = config.get("max_signal_age_minutes")
        if max_age is not None:
            age_anchor = signal.get("analysis_completed_at") or signal.get("signal_time")
            if age_anchor and current_time:
                age_minutes = (current_time - age_anchor).total_seconds() / 60
                if age_minutes > max_age:
                    state.signals_filtered += 1
                    return False

        # 7. Hold skip
        if direction == "hold":
            state.signals_filtered += 1
            return False

        # 8. Max same direction — operates in SIGNAL space, so SKIP for MR (which
        # places in fade-space, decoupled from the signal direction; live C3 fix).
        max_same_dir = config.get("max_same_direction")
        if max_same_dir is not None and not is_mr:
            trade_side = determine_side(direction, config.get("direction", "straight"))
            same_dir_count = sum(1 for p in state.open_positions if p.side == trade_side)
            if same_dir_count >= max_same_dir:
                state.signals_filtered += 1
                return False

        # 9. Sector concentration limit — NOT enforced in the backtest engine.
        # Real sector classification requires the IO-bound sector service
        # (CoinGecko/LLM/DB cache), which the pure synchronous engine cannot call.
        # max_same_sector is therefore intentionally a no-op here; the service
        # surfaces a `max_same_sector_not_enforced` warning when it is set so the
        # user knows results may diverge from live trading (which DOES enforce it).

        # 10. Adaptive blacklist (computed from backtest's own trade history)
        if (
            config.get("adaptive_blacklist_enabled")
            and self._is_adaptively_blacklisted(config, ticker, state, current_time)
        ):
            state.signals_filtered += 1
            return False

        # 11. Signal sides filter — also signal-space; SKIP for MR (live C4 fix; MR
        # side is governed by mr_short_enabled/mr_long_enabled, not signal_sides).
        signal_sides = config.get("signal_sides", "both")
        if signal_sides != "both" and not is_mr:
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

        # 14. Max trades limit (PER SCAN/CYCLE — matches production, which resets
        # trades_executed=0 for each scan's executor). Uses the per-scan counter so
        # a later scan can open fresh trades even after earlier cycles filled up.
        max_trades = config.get("max_trades", 999)
        if state.scan_entered >= max_trades:
            state.signals_filtered += 1
            return False

        # 15. Target goal (trade_count type) — backtest-level early stop, so this
        # legitimately uses the LIFETIME entry count, not the per-scan one.
        target_type = config.get("target_goal_type")
        target_value = config.get("target_goal_value")
        if target_type == "trade_count" and target_value and state.signals_entered >= target_value:
            state.signals_filtered += 1
            return False

        # 16. Balance check
        if state.sizing_capital <= 0:
            state.signals_filtered += 1
            return False

        # 17. Price drift validation — skip only if price already moved too far IN THE
        # SIGNAL'S DIRECTION (the move is "consumed"). Mirrors production exactly
        # (auto_trade_service._evaluate_result): a signed, direction-aware check, NOT a
        # symmetric abs() one. A buy whose price has DROPPED is a BETTER entry and is
        # admitted (production trades it); only a buy that already ran UP past the cap
        # is rejected. Uses the raw signal direction (production checks pre-reverse).
        # SKIPPED for MR (is_mr): the check is on the signal axis, but MR places on the
        # fade side (decoupled) — matches live's `not mr_fade` guard (SD12).
        max_drift = config.get("max_price_drift_pct")
        if max_drift is not None and not is_mr:
            analysis_price = signal.get("analysis_price")
            if analysis_price and analysis_price > 0:
                # Compare analysis_price against the price the trade would FILL at —
                # the next bar's OPEN (same next-bar-open basis as _open_position, no
                # look-ahead). Using the bar's close here would drift-check against a
                # price ~one candle in the future AND disagree with the actual fill.
                symbol_klines = klines.get(ticker, [])
                current_price = None
                for k in symbol_klines:
                    if k["open_time"] >= current_time:
                        current_price = k["open"]
                        break
                if current_price is not None:
                    drift_pct = (current_price - analysis_price) / analysis_price * 100
                    if direction in ("buy", "long") and drift_pct > max_drift:
                        state.signals_filtered += 1
                        return False
                    if direction in ("sell", "short") and drift_pct < -max_drift:
                        state.signals_filtered += 1
                        return False

        return True  # All 17 filters passed

    def _fine_window(
        self, symbol: str, bar_open_time: datetime
    ) -> Optional[list[dict[str, Any]]]:
        """Return the 1-minute candles covering the 5m bar that opens at
        `bar_open_time`, or None when no drill-down window was injected for it.

        Keyed by the integer epoch of the bar's open_time (the same tz-aware
        datetime the candle loop iterates). None ⇒ caller uses 5m logic unchanged.
        """
        if not self._fine_klines:
            return None
        per_symbol = self._fine_klines.get(symbol)
        if not per_symbol:
            return None
        return per_symbol.get(int(bar_open_time.timestamp()))

    @staticmethod
    def _sim_bar_seconds(symbol_klines: list[dict[str, Any]]) -> int:
        """Infer the simulation bar size (seconds) from the spacing of the first two
        candles. open_time may be a datetime (the service path) or an int/float epoch
        (the optimizer snapshot path) — handle both. Falls back to 300 (5m)."""
        if len(symbol_klines) >= 2:
            d = symbol_klines[1]["open_time"] - symbol_klines[0]["open_time"]
            s = int(d.total_seconds()) if hasattr(d, "total_seconds") else int(d)
            if s > 0:
                return s
        return 300

    def _bar_extremes_for(
        self, pos: "Position", candle: dict[str, Any], candle_time: datetime
    ) -> tuple[float, float]:
        """Return the (high, low) of `candle` to evaluate `pos` on this bar.

        Entry drill-down is PRICE-ONLY (it never moves the trade lifecycle: a position
        opens at the 5m next-bar-open bar and is only ever evaluated on bars STRICTLY
        AFTER its fill), so there is no entry-bar look-ahead to guard against — the 5m
        candle's own high/low are always correct. Kept as a single seam in case a future
        timing-shifting drill mode needs to restrict a bar's extremes again.
        """
        return candle["high"], candle["low"]

    def _resolve_exit_fine(
        self, pos: "Position", window: list[dict[str, Any]]
    ) -> Optional[tuple[str, float]]:
        """Walk a 5m exit bar's 1m candles in order and return the FIRST of
        liquidation / SL / TP actually touched → (close_reason, exit_price). Used only
        when ≥2 of those levels fall inside the 5m bar's range (ambiguous order), to
        replace the pessimistic "SL-wins" 5m default with the real first-touch.

        Within a single 1m candle the order STILL can't be known (its own high & low
        could both cross), so per-candle we keep the same pessimistic precedence the 5m
        path uses: liquidation, then SL, then TP. 1m shrinks the ambiguity window but
        cannot fully remove it. Returns None if no level is touched in the window.
        """
        for c in window:
            hi, lo = c["high"], c["low"]
            if pos.side == "Buy":
                # liquidation first (lowest price), then SL-if-closer, then TP.
                if lo <= pos.liq_price:
                    if pos.sl_price > 0 and pos.sl_price > pos.liq_price and lo <= pos.sl_price:
                        return "sl", pos.sl_price
                    return "liquidation", pos.liq_price
                if pos.sl_price > 0 and lo <= pos.sl_price:
                    return "sl", pos.sl_price
                if pos.tp_price > 0 and hi >= pos.tp_price:
                    return "tp", pos.tp_price
            else:
                if hi >= pos.liq_price:
                    if pos.sl_price > 0 and pos.sl_price < pos.liq_price and hi >= pos.sl_price:
                        return "sl", pos.sl_price
                    return "liquidation", pos.liq_price
                if pos.sl_price > 0 and hi >= pos.sl_price:
                    return "sl", pos.sl_price
                if pos.tp_price > 0 and lo <= pos.tp_price:
                    return "tp", pos.tp_price
        return None

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
            apply_slippage,
            compute_fee,
            compute_liquidation_price,
            compute_locked_margin,
            compute_position_size,
            compute_tp_sl,
            determine_side,
            round_price_to_tick,
        )

        ticker = signal["ticker"]
        direction = signal["direction"]

        # Get entry price from klines at signal time
        symbol_klines = klines.get(ticker, [])
        if not symbol_klines:
            # No cached candles for this symbol → we cannot simulate the trade, but
            # production WOULD have traded it. Count it distinctly (not as a filtered
            # signal) so the service can warn that the backtest under-traded here.
            state.signals_no_kline += 1
            return False

        # Entry fills at the NEXT BAR'S OPEN — the first tradeable price strictly
        # after the decision instant (next-bar-open convention). The signal fires at
        # current_time (= the scan's completed_at, a wall-clock instant almost never
        # candle-aligned); we fill at the open of the first candle whose open_time is
        # >= current_time. Using that candle's CLOSE instead would be LOOK-AHEAD: the
        # close is the end-of-bar price (~one full candle in the future), yet the SAME
        # candle's high/low are evaluated for TP/SL below — so a pre-entry intrabar
        # spike could fabricate an exit on a move that happened BEFORE the fill. Filling
        # at the open makes that bar's high/low strictly post-entry, so evaluating them
        # is correct. Fallback: a signal after the last candle has no future bar to fill
        # against → use the last available close (the only price we have).
        entry_base_price = symbol_klines[-1]["close"]
        entry_bar_open: Optional[datetime] = None
        for k in symbol_klines:
            if k["open_time"] >= current_time:
                entry_base_price = k["open"]
                entry_bar_open = k["open_time"]
                break

        # No candle exists at/after the signal instant → the symbol's cached series is
        # truncated BEFORE this signal (partial/stale coverage). There is no real price
        # at which this trade could have filled (production would have no fill either),
        # so we must NOT fabricate one from the last stale candle's close — that would
        # enter at an arbitrarily old price (regression: a short filled 2h stale at 0.161
        # vs the real 0.178), cascading into wrong PnL and a held-to-max_duration
        # position. Count it like a no-kline drop (surfaced as a warning) and skip.
        if entry_bar_open is None:
            state.signals_no_kline += 1
            return False

        # ── 1-minute ENTRY DRILL-DOWN (price-only) ──
        # Production fills a market order at the scan's completed_at INSTANT (mid-5m-bar,
        # e.g. 11:55:41). The 5m engine defers the fill to the NEXT bar's open to avoid
        # look-ahead. We keep that LIFECYCLE (entry_bar_open / open+close timing) exactly
        # — so the skip_if_positions_open cascade and trade COUNT are unchanged — but
        # refine the fill PRICE to the 1m open at/after current_time. That 1m minute lies
        # in the signal's own bar (at/before entry_bar_open), so the price is a real PAST
        # price and the position's same-bar evaluation still starts at entry_bar_open
        # (strictly after the fill minute) → no look-ahead, no perturbation of which bars
        # the position is open for. This tightens the entry price toward production's
        # mid-bar fill without moving the trade lifecycle. No window ⇒ unchanged 5m open.
        # equity_ref_base = the UN-drilled 5m fill, preserved so the equity close-rules
        # value uPnL off a price that is INVARIANT to drill-down → identical selection.
        equity_ref_base = entry_base_price
        if self._fine_klines and entry_bar_open is not None:
            sim_secs = self._sim_bar_seconds(symbol_klines)
            signal_bar_epoch = (int(current_time.timestamp()) // sim_secs) * sim_secs if sim_secs else None
            for cand_bar_epoch in (signal_bar_epoch,
                                   int(entry_bar_open.timestamp())):
                if cand_bar_epoch is None:
                    continue
                fine = self._fine_window(ticker, datetime.fromtimestamp(cand_bar_epoch, tz=timezone.utc))
                if not fine:
                    continue
                picked = next((fk for fk in fine if fk["open_time"] >= current_time), None)
                if picked is not None:
                    entry_base_price = picked["open"]
                    break


        # Apply slippage to get the actual ENTRY FILL price (used for PnL, fee, and
        # margin — mirrors production filling a market order at the slipped avgPrice).
        side = determine_side(direction, config.get("direction", "straight"))

        # ── Mean-Reversion override (F2) ──
        # If the filter chain routed this signal to MR, compute the placement from the
        # REAL next-bar-open entry (entry_base_price) against the scan-time EMA mean,
        # using the SAME pure core as live (mean_reversion_math.compute_mr_placement).
        # This overrides the trend side and the leverage/TP/SL/capital below. A geometry
        # guard at the real entry (which can differ from the routing estimate) skips the
        # trade — fail-closed, matching live. self._mr_mean is set only on the MR path.
        mr_placement = None
        if self._mr_mean is not None:
            from backend.services import mean_reversion_math as _mr
            from backend.services.strategy_reason_codes import ReasonCode as _RC
            mr_placement = _mr.compute_mr_placement(entry_base_price, self._mr_mean, config)
            if isinstance(mr_placement, _RC):
                # geometry/direction guard fired at the real entry → skip (no trade).
                state.signals_filtered += 1
                return False
            side = "Buy" if mr_placement["signal_direction"] == "long" else "Sell"

        entry_price = apply_slippage(entry_base_price, side, config.get("slippage_bps", 2))
        # Slipped equity-reference fill (the un-drilled 5m price + same slippage). Equals
        # entry_price when no drill occurred. The equity close-rules use this so drill
        # never shifts selection.
        equity_ref_entry = apply_slippage(equity_ref_base, side, config.get("slippage_bps", 2))

        # Per-symbol instrument parameters (lot step, min qty, tick size, max
        # leverage). When the service didn't resolve real values for this symbol the
        # defaults are intentionally NO-OPs (qty_step/min_qty 0.001 as before; tick=0
        # and max_leverage=0 mean "don't round / don't cap") so behaviour is unchanged
        # for callers that pass no instrument_info — only REAL resolved values change
        # sizing/rounding/leverage to match the exchange.
        info = self._instrument_info.get(ticker) or {}
        qty_step = float(info.get("qty_step", 0.001))
        min_qty = float(info.get("min_qty", 0.001))
        tick_size = float(info.get("tick_size", 0.0))  # 0 → no TP/SL rounding
        max_leverage = int(info.get("max_leverage", 0) or 0)  # 0 → no cap

        # Compute position size. MR uses its own leverage/capital from the placement.
        leverage = int(mr_placement["leverage"]) if mr_placement else config.get("leverage", DEFAULT_LEVERAGE)
        # Cap leverage to the symbol's max, matching production (accounts_service caps
        # to the instrument's maxLeverage). Over-leveraging would mis-price liq/margin.
        if max_leverage > 0 and leverage > max_leverage:
            leverage = max_leverage
        capital_pct = mr_placement["capital_pct"] if mr_placement else config.get("capital_pct", DEFAULT_CAPITAL_PCT)

        # Available-balance basis for the margin-affordability check. Use the SAME
        # totalAvailableBalance basis the per-scan sizing uses (wallet + carried
        # unrealised PnL − locked margin), not wallet−locked alone — otherwise the
        # check and the sizing capital disagree on what "available" means, and a book
        # carrying a winning position would be under-credited (the gate would reject a
        # trade the real account, whose availableBalance includes that uPnL, could
        # afford). Bybit's totalAvailableBalance = walletBalance + unrealisedPnL −
        # initialMargin, so mirror that. carried_upnl is marked to each position's last
        # close at/before now (no look-ahead), matching _open_scan_signals.
        from backend.services.trading_rules import compute_unrealized_pnl as _cu_avail
        locked = sum(p.locked_margin for p in state.open_positions)
        carried_upnl = 0.0
        for _p in state.open_positions:
            _ref = _p.equity_ref_entry or _p.entry_price
            _mark = _ref
            for _k in klines.get(_p.symbol, []):
                if _k["open_time"] <= current_time:
                    _mark = _k["close"]
                else:
                    break
            carried_upnl += _cu_avail(_ref, _mark, _p.qty, _p.side)
        available = state.wallet_balance + carried_upnl - locked

        # Size off the UN-SLIPPED mark (entry_base_price), matching production, which
        # computes qty = usdt_amount × leverage / mark_price (accounts_service), NOT
        # off the slipped fill. Sizing off the slipped price would understate qty and
        # (combined with the TP/SL anchor below) bias every exit in the trader's favor.
        # qty_step/min_qty come from the resolved instrument info so a coarse-lot symbol
        # (e.g. 1000PEPE) rounds qty DOWN to its real step and rejects below min_qty,
        # exactly as live trading — not the 0.001 placeholder.
        qty = compute_position_size(
            sizing_capital=state.sizing_capital,
            capital_pct=capital_pct,
            leverage=leverage,
            price=entry_base_price,
            qty_step=qty_step,
            min_qty=min_qty,
            available_balance=available,
        )
        if qty is None:
            state.signals_filtered += 1
            return False

        # Compute TP/SL — anchored to the UN-SLIPPED mark (entry_base_price), matching
        # production (tp = mark_price × (1 ± tp_pct/100), accounts_service). The entry
        # FILLS at the slipped entry_price, so realized PnL = (mark-anchored TP −
        # slipped fill), i.e. slightly less than the nominal TP% — exactly as live
        # trading. Anchoring TP/SL to the slipped price instead would hand the trader
        # the full nominal move plus the slippage, a systematic favorable bias.
        tp_pct = mr_placement["take_profit_pct"] if mr_placement else config.get("take_profit_pct", DEFAULT_TAKE_PROFIT_PCT)
        sl_pct = mr_placement["stop_loss_pct"] if mr_placement else config.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)
        tp_price, sl_price = compute_tp_sl(entry_base_price, side, tp_pct, sl_pct, leverage)
        # Round TP/SL DOWN to the instrument tick size, matching production
        # (accounts_service round_price uses ROUND_DOWN to tick_size). Unrounded
        # trigger prices would fill at levels the exchange can't represent, shifting
        # exit PnL vs live.
        if tick_size > 0:
            tp_price = round_price_to_tick(tp_price, tick_size)
            sl_price = round_price_to_tick(sl_price, tick_size)

        # Compute liquidation price — anchored to the SLIPPED entry_price (the fill),
        # because Bybit isolated-margin liquidation is computed off the average fill
        # price (avgPrice), not the mark. Keeping this slipped mirrors the exchange.
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
            # F2: tag MR positions + carry their fast time-stop (minutes).
            strategy_kind=("mean_reversion" if mr_placement else "trend"),
            time_stop_minutes=(float(config.get("mr_time_stop_minutes", 120)) if mr_placement else None),
            # 1m drill-down: the 5m bar the entry filled in (the service uses it to
            # locate the exit-bar window). Entry drill is price-only — the lifecycle is
            # unchanged, so exits are always strictly after the fill (no look-ahead).
            entry_bar_open=entry_bar_open,
            equity_ref_entry=equity_ref_entry,
        )
        state.open_positions.append(position)
        state.signals_entered += 1  # lifetime counter (stats + target_goal early-stop)
        state.scan_entered += 1  # per-scan counter (gates max_trades, reset each scan)

        # Fallback seed for cycle_start_equity. The per-scan refresh in run() already
        # re-anchors this to sizing_capital (= wallet − locked margin) before any
        # signal is processed, so this normally no-ops. It only fires if an equity
        # rule zeroed the reference mid-scan (cycle termination) and a later open
        # occurs before the next per-scan refresh — use the SAME available-balance
        # basis (sizing_capital), never the full wallet, so the basis can't drift.
        if state.cycle_start_equity == 0:
            state.cycle_start_equity = state.sizing_capital

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

    def _open_scan_signals(
        self,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        current_time: datetime,
        execution_mode: str,
    ) -> int:
        """Refresh the per-scan AVAILABLE balance, re-anchor the equity reference, and
        open this scan's signals. The single source of the per-scan open sequence.

        Returns the number of NEW positions opened (scan_entered before vs after).

        Available balance mirrors production's totalAvailableBalance =
        totalWalletBalance + unrealised_pnl − initial_margin: wallet_balance (margin
        never deducted here, only entry fees) + carried_upnl (marked to the candle
        at/just-before current_time — no look-ahead) − Σ locked_margin. Both the
        new-position sizing basis AND the equity-rule reference derive from this one
        value, exactly as production derives both from base_capital. On an empty book
        carried_upnl=0 and locked=0 → it reduces to the full wallet.
        """
        from backend.services.trading_rules import compute_unrealized_pnl as _cu
        # A non-skipped scan re-creates the close rules in production, including a
        # fresh EQUITY_DROP_PCT_SMART. Re-arm the one-shot SMART guard here (NOT on a
        # skipped scan, which preserves the prior rule's executed state).
        state.smart_drawdown_fired = False
        carried_upnl = 0.0
        for _p in state.open_positions:
            _ks = klines.get(_p.symbol, [])
            _ref = _p.equity_ref_entry or _p.entry_price
            _mark = _ref
            for _k in _ks:
                if _k["open_time"] <= current_time:
                    _mark = _k["close"]
                else:
                    break
            carried_upnl += _cu(_ref, _mark, _p.qty, _p.side)
        locked_margin = sum(p.locked_margin for p in state.open_positions)
        available_balance = max(0.0, state.wallet_balance + carried_upnl - locked_margin)
        state.sizing_capital = available_balance
        state.cycle_start_equity = available_balance

        before = state.scan_entered
        if execution_mode == "batch":
            self._process_batch_signals(config, scan_signals, klines, state, current_time)
        else:
            self._process_immediate_signals(config, scan_signals, klines, state, current_time)
        return state.scan_entered - before

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
            idx: dict[datetime, dict] = {}
            for k in klines.get(sym, []):
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

        # Seed each open position's mark with its last close AT/BEFORE the window
        # start, NOT its entry price. A position carried from a prior scan may have
        # moved far from entry; marking it at entry until its first in-window candle
        # would make the equity rules (which run on the very first timestamp) evaluate
        # a stale, wrong equity — firing equity_drop/close_on_profit spuriously or
        # late under uneven multi-symbol coverage. This mirrors the carried-uPnL
        # mark used for the per-scan reference (run()), so numerator and reference
        # agree. No look-ahead: only candles with open_time <= start_time are used.
        latest_prices: dict[str, float] = {}
        for p in state.open_positions:
            mark = p.entry_price
            for k in klines.get(p.symbol, []):
                if k["open_time"] <= start_time:
                    mark = k["close"]
                else:
                    break
            latest_prices[p.symbol] = mark
        candle_count = 0

        # Process timestamps chronologically — unified timeline
        for candle_time in sorted_timestamps:
            if not state.open_positions:
                break

            candle_count += 1
            if candle_count % 100 == 0 and cancel_event and cancel_event.is_set():
                raise BacktestCancelled("Cancelled during candle evaluation")

            # Gather candles for all open symbols at this timestamp; update latest prices
            candles_at_time: dict[str, dict] = {}
            for sym in list(open_symbols):
                candle = symbol_time_idx.get(sym, {}).get(candle_time)
                if candle:
                    latest_prices[sym] = candle["close"]
                    candles_at_time[sym] = candle

            # --- FUNDING RATE (once per 8h boundary) ---
            funding_model = config.get("funding_rate_model", "none")
            if funding_model == "fixed_8h":
                # Charge once per 0/8/16h boundary. Gating on a per-boundary key
                # (date, hour) — rather than only "minute < 5" — makes this correct
                # regardless of candle granularity: a finer interval would land
                # multiple candles inside [hh:00, hh:05), but only the FIRST charges.
                in_window = candle_time.hour in (0, 8, 16) and candle_time.minute < 5
                boundary_key = (candle_time.date(), candle_time.hour)
                if in_window and state.last_funding_boundary != boundary_key:
                    state.last_funding_boundary = boundary_key
                    funding_rate = config.get("funding_rate_fixed_pct", 0.01) / 100.0
                    for fp in state.open_positions:
                        price = latest_prices.get(fp.symbol, fp.entry_price)
                        payment = fp.qty * price * funding_rate
                        if fp.side == "Buy":
                            state.wallet_balance -= payment
                            fp.funding_paid += payment  # longs pay funding (cost)
                        else:
                            state.wallet_balance += payment
                            fp.funding_paid -= payment  # shorts receive funding (credit)

            # --- PER-POSITION: liquidation + TP/SL (only symbols with a candle now) ---
            positions_to_close: list[tuple] = []
            for pos in list(state.open_positions):
                candle = candles_at_time.get(pos.symbol)
                if not candle:
                    continue
                # Effective bar extremes: 5m high/low normally, but POST-ENTRY 1m
                # high/low on a 1m-drilled position's own entry bar (look-ahead guard).
                high, low = self._bar_extremes_for(pos, candle, candle_time)

                # Update MFE/MAE
                if pos.side == "Buy":
                    pos.max_favorable_price = max(pos.max_favorable_price, high)
                    pos.max_adverse_price = min(pos.max_adverse_price, low) if pos.max_adverse_price > 0 else low
                else:
                    pos.max_favorable_price = min(pos.max_favorable_price, low) if pos.max_favorable_price > 0 else low
                    pos.max_adverse_price = max(pos.max_adverse_price, high)

                # ── 1-minute EXIT DRILL-DOWN ──
                # When this 5m bar has ≥2 of {liq, sl, tp} inside its range, the order
                # they were hit is ambiguous and the 5m path resolves it pessimistically
                # (SL/liq wins). If a 1m window exists for this bar, walk it to take the
                # REAL first-touch instead. One-level-only bars are already exact at 5m
                # (the trigger is that level's price) → no drill needed.
                levels_in_range = 0
                for lvl in (pos.liq_price, pos.sl_price, pos.tp_price):
                    if lvl and low <= lvl <= high:
                        levels_in_range += 1
                if levels_in_range >= 2:
                    window = self._fine_window(pos.symbol, candle_time)
                    if window:
                        drilled = self._resolve_exit_fine(pos, window)
                        if drilled is not None:
                            positions_to_close.append((pos, drilled[0], drilled[1], candle_time))
                            continue
                        # window present but nothing touched (shouldn't happen when a
                        # level is in the 5m range) → fall through to 5m logic.

                # LIQUIDATION (SL-wins-if-closer). The `sl_price > 0` guards are
                # defence-in-depth: a non-positive SL (should never happen now that
                # tick-rounding can't zero a price) must NEVER be treated as a closer
                # stop — that would fabricate a near-100% PnL. A 0 SL falls through to
                # liquidation, the correct outcome.
                if pos.side == "Buy" and low <= pos.liq_price:
                    if pos.sl_price > 0 and pos.sl_price > pos.liq_price and low <= pos.sl_price:
                        positions_to_close.append((pos, "sl", pos.sl_price, candle_time))
                    else:
                        positions_to_close.append((pos, "liquidation", pos.liq_price, candle_time))
                    continue
                if pos.side == "Sell" and high >= pos.liq_price:
                    if pos.sl_price > 0 and pos.sl_price < pos.liq_price and high >= pos.sl_price:
                        positions_to_close.append((pos, "sl", pos.sl_price, candle_time))
                    else:
                        positions_to_close.append((pos, "liquidation", pos.liq_price, candle_time))
                    continue

                # TP/SL (pessimistic: SL wins when both hit). The `> 0` guards ensure
                # a non-positive trigger (which round_price_to_tick can no longer
                # produce, but defend in depth) is never treated as hit — a 0 SL on a
                # short would otherwise satisfy `high >= 0` and fabricate a ~100% win.
                close_reason = None
                exit_price = None
                if pos.side == "Buy":
                    sl_hit = pos.sl_price > 0 and low <= pos.sl_price
                    tp_hit = pos.tp_price > 0 and high >= pos.tp_price
                    if sl_hit:
                        close_reason, exit_price = "sl", pos.sl_price
                    elif tp_hit:
                        close_reason, exit_price = "tp", pos.tp_price
                else:
                    sl_hit = pos.sl_price > 0 and high >= pos.sl_price
                    tp_hit = pos.tp_price > 0 and low <= pos.tp_price
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
                self._evaluate_equity_rules(config, state, latest_prices, candle_time, fee_rate, candles_at_time)

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
        from backend.services.trading_rules import (
            apply_slippage,
            compute_fee,
            compute_liquidation_pnl,
            compute_unrealized_pnl,
        )

        # Compute realized PnL
        if close_reason == "liquidation":
            # Liquidation: full margin loss (Bybit isolated). Already net of both
            # fees (compute_liquidation_pnl subtracts entry_fee; no exit fee). The
            # wallet update below deducts locked_margin directly (not wallet_delta).
            # No exit-slippage modeled: liquidation is a forced full-margin loss, not
            # a market fill, so exit_price is unused here.
            net_pnl = compute_liquidation_pnl(position.locked_margin, position.entry_fee)
            exit_fee = 0.0  # liquidation fee already in the pnl calc
            wallet_delta = 0.0  # unused for liquidation; wallet loses locked_margin
            recorded_pnl = net_pnl - position.funding_paid
        else:
            # Apply adverse exit slippage — production closes via Bybit market
            # reduce-only orders, which fill worse than the trigger/close price. The
            # CLOSE side is the inverse of the position side (a long sells to close →
            # fills lower; a short buys to close → fills higher), so slippage_bps is a
            # round-trip cost (entry fill was already slipped on open). Both the
            # realized PnL and the taker exit fee use this slipped exit price.
            close_side = "Sell" if position.side == "Buy" else "Buy"
            filled_exit_price = apply_slippage(exit_price, close_side, state.slippage_bps)
            pnl = compute_unrealized_pnl(position.entry_price, filled_exit_price, position.qty, position.side)
            exit_fee = compute_fee(position.qty, filled_exit_price, fee_rate)
            # Wallet delta excludes entry_fee because it was already deducted from
            # the wallet at open (line ~522), and excludes funding because funding
            # was already applied live to the wallet at each funding event. But the
            # RECORDED trade pnl must be net of BOTH fees AND funding so that
            # sum(trade.pnl) reconciles with final_equity - starting_capital
            # (TradingView "Net Profit" semantics) and stays consistent with the
            # liquidation branch above.
            wallet_delta = pnl - exit_fee
            recorded_pnl = pnl - exit_fee - position.entry_fee - position.funding_paid
            # Record the actual filled exit price (with slippage) on the trade.
            exit_price = filled_exit_price

        # Update wallet
        # Model: wallet_balance includes locked margin (never deducted on open, only entry_fee deducted)
        # On normal close: add wallet_delta (margin stays in wallet, PnL adjusts it)
        # On liquidation: LOSE the locked margin (deduct it now)
        if close_reason == "liquidation":
            state.wallet_balance -= position.locked_margin  # margin is lost
        else:
            state.wallet_balance += wallet_delta  # PnL adjusts wallet (no margin return needed)

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
            "pnl": recorded_pnl,
            "pnl_pct": (recorded_pnl / position.locked_margin) * 100 if position.locked_margin else 0,
            "fees_paid": position.entry_fee + exit_fee + position.funding_paid,
            "close_reason": close_reason,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "signal_score": position.signal_score,
            "signal_confidence": position.signal_confidence,
            "scan_id": position.scan_id,
            "strategy_kind": position.strategy_kind,
        }
        state.closed_trades.append(trade_record)

        # Remove from open positions
        state.open_positions.remove(position)

        # Record a realized-equity point at each close so the equity curve has
        # intermediate samples (not just start/end). This is the per-trade equity
        # curve TradingView shows: wallet_balance here reflects all realized PnL,
        # fees, and funding to date. Path-dependent metrics (max drawdown, Sharpe,
        # run-up, etc.) are computed from these points — without them they would
        # all degenerate to zero on a 2-point line.
        state.equity_curve.append({
            "ts": exit_time,
            "equity": state.wallet_balance,
            "drawdown_pct": 0.0,
        })

    def _full_book_fine_window(
        self, state: SimulationState, candle_time: datetime
    ) -> Optional[dict[str, list[dict[str, Any]]]]:
        """Return {symbol: [1m candles asc]} for THIS 5m bar IFF every open position's
        symbol has an injected 1m window for it — else None.

        The portfolio-equity walk sums uPnL across the WHOLE open book, so it is only
        valid when every open symbol has 1-minute coverage for the bar. If any symbol is
        missing (partial coverage), the caller falls back to the 5m evaluation for this
        bar (fail-soft). None when no drill-down data at all (golden path).
        """
        if not self._fine_klines or not state.open_positions:
            return None
        book: dict[str, list[dict[str, Any]]] = {}
        for pos in state.open_positions:
            if pos.symbol in book:
                continue
            window = self._fine_window(pos.symbol, candle_time)
            if not window:
                return None  # partial coverage → not full-book → fall back to 5m
            book[pos.symbol] = window
        return book

    def _evaluate_equity_rules(
        self,
        config: dict[str, Any],
        state: SimulationState,
        latest_prices: dict[str, float],
        candle_time: datetime,
        fee_rate: float,
        candles_at_time: Optional[dict[str, dict]] = None,
    ) -> None:
        """Dispatch the portfolio-equity close rules at the right time resolution.

        When a FULL-BOOK 1-minute window exists for this 5m bar, walk the bar
        minute-by-minute (`_evaluate_equity_rules_fine`) so a drawdown / smart / rise /
        close_on_profit fires at the true 1-minute crossing — at that minute's timestamp
        and price — instead of the 5m bar boundary using each symbol's own-bar adverse
        extreme (which look-aheads to ~end-of-bar prices and can fabricate a
        synchronized-wick drawdown that never simultaneously happened).

        Otherwise (no drill-down, or partial book coverage) evaluate once on the 5m bar
        exactly as before — preserving the byte-identical golden guarantee and keeping
        the sweep/optimizer (which injects no fine data) structurally unchanged.
        """
        if not state.open_positions:
            return
        book = self._full_book_fine_window(state, candle_time)
        if book is None:
            self._eval_equity_core(config, state, latest_prices, candle_time, fee_rate, candles_at_time)
            return
        self._evaluate_equity_rules_fine(config, state, latest_prices, candle_time, fee_rate, book)

    def _evaluate_equity_rules_fine(
        self,
        config: dict[str, Any],
        state: SimulationState,
        latest_prices: dict[str, float],
        candle_time: datetime,
        fee_rate: float,
        book: dict[str, list[dict[str, Any]]],
    ) -> None:
        """1-minute portfolio-equity walk over a single 5m bar.

        Runs the SAME 5m evaluation kernel (`_eval_equity_core`) once per 1-minute
        candle, with that minute's per-symbol price as the close mark and its own 1m
        high/low as the adverse extreme. The first minute a rule truly crosses, the
        kernel closes the book / terminates the cycle (stamped at that minute) and the
        remaining minutes naturally no-op. If no minute crosses, nothing fires (a 5m
        synchronized-wick phantom is correctly rejected).

        Marks are carried forward minute-to-minute: a symbol with no 1m candle at a
        given minute keeps its last-known price (the incoming 5m mark until its first 1m
        candle), so the simultaneous-equity sum is always defined across the full book.
        """
        # Union of all 1-minute timestamps across the open book, in order. Each symbol's
        # window is ascending; merge-dedupe their open_times.
        minute_set: set[datetime] = set()
        per_symbol_at: dict[str, dict[datetime, dict[str, Any]]] = {}
        for sym, window in book.items():
            idx: dict[datetime, dict[str, Any]] = {}
            for c in window:
                ot = c["open_time"]
                if isinstance(ot, datetime):
                    idx[ot] = c
                    minute_set.add(ot)
            per_symbol_at[sym] = idx
        if not minute_set:
            # Degenerate (windows held no datetime-keyed candles) → 5m fallback.
            self._eval_equity_core(config, state, latest_prices, candle_time, fee_rate, None)
            return

        # Local carry-forward marks seeded from the incoming 5m marks (never mutate the
        # caller's dict — a non-firing walk must leave outer state untouched).
        marks = dict(latest_prices)
        for minute in sorted(minute_set):
            if not state.open_positions:
                break
            candles_at_minute: dict[str, dict[str, Any]] = {}
            for sym in list({p.symbol for p in state.open_positions}):
                candle = per_symbol_at.get(sym, {}).get(minute)
                if candle is not None:
                    marks[sym] = candle["close"]
                    candles_at_minute[sym] = candle
            # Evaluate the full equity-rule kernel at this minute, stamped at the minute.
            self._eval_equity_core(config, state, marks, minute, fee_rate, candles_at_minute)

    def _eval_equity_core(
        self,
        config: dict[str, Any],
        state: SimulationState,
        latest_prices: dict[str, float],
        candle_time: datetime,
        fee_rate: float,
        candles_at_time: Optional[dict[str, dict]] = None,
    ) -> None:
        """Evaluate equity-based close rules: EQUITY_DROP_PCT, SMART, close_on_profit.

        Called once per candle AFTER TP/SL closures (wallet already updated).
        Uses per-symbol latest close price for unrealized PnL calculation.

        Drawdown is additionally evaluated on the bar's INTRA-CANDLE adverse extreme
        (high for shorts, low for longs), not just the close: production's drawdown
        rule runs on live WS equity ticks with zero debounce, so a transient
        intra-minute breach that recovers by the bar close still fires live. A
        close-only backtest would miss it and hold positions production flattened.
        candles_at_time supplies this bar's OHLC per symbol; when absent (callers
        that don't pass it) the evaluator degrades to close-only (prior behaviour).

        At 5m resolution this kernel values every open position at ITS OWN bar adverse
        extreme — a synchronized-worst-case. The 1-minute walk
        (`_evaluate_equity_rules_fine`) calls this same kernel per minute so the adverse
        window shrinks to one minute and the firing time/price match the true crossing.
        """
        from backend.services.trading_rules import (
            check_close_on_profit,
            check_equity_drop,
            check_equity_rise,
            compute_unrealized_pnl,
        )

        if not state.open_positions:
            return

        candles_at_time = candles_at_time or {}

        # Compute current equity at the bar CLOSE (wallet + Σ unrealized PnL at the
        # per-symbol latest close). This drives the profit-side goals (rise /
        # close_on_profit), which live evaluates with a ~1.5s debounce — close
        # granularity is the faithful sampling there.
        total_upnl = 0.0
        losing_positions = []
        for pos in state.open_positions:
            current_price = latest_prices.get(pos.symbol, pos.entry_price)
            # Equity rules value uPnL off the STABLE 5m reference entry (invariant to
            # drill-down) so toggling drill-down never changes which threshold fires →
            # identical trade selection. Falls back to entry_price when not drilled.
            ref = pos.equity_ref_entry or pos.entry_price
            upnl = compute_unrealized_pnl(ref, current_price, pos.qty, pos.side)
            total_upnl += upnl
            if upnl < 0:
                losing_positions.append(pos)

        equity = state.wallet_balance + total_upnl

        # --- EQUITY_DROP_PCT / EQUITY_DROP_PCT_SMART (INTRABAR-AWARE) ---
        max_drawdown_pct = config.get("max_drawdown_pct", 100.0)
        if max_drawdown_pct < 100.0:
            # Worst-case intra-candle equity: value every open position at its
            # adverse extreme THIS bar (short → high, long → low). A position with
            # no candle this timestamp keeps its latest-close mark (no new info).
            # This is the price at which the live tick-driven rule would have seen
            # the deepest drawdown within the bar.
            drawdown_upnl = 0.0
            adverse_price: dict[str, float] = {}
            for pos in state.open_positions:
                candle = candles_at_time.get(pos.symbol)
                if candle is not None:
                    # Entry-bar guard: a 1m-drilled position uses its POST-ENTRY 1m
                    # extreme on its own entry bar, so pre-fill price action can't
                    # fabricate a drawdown close (look-ahead). Otherwise the 5m extreme.
                    hi, lo = self._bar_extremes_for(pos, candle, candle_time)
                    extreme = hi if pos.side == "Sell" else lo
                else:
                    extreme = latest_prices.get(pos.symbol, pos.entry_price)
                adverse_price[pos.symbol] = extreme
                drawdown_upnl += compute_unrealized_pnl(
                    pos.equity_ref_entry or pos.entry_price, extreme, pos.qty, pos.side
                )
            intrabar_equity = state.wallet_balance + drawdown_upnl
            # Fire on the worse of (close, intrabar) — the intrabar extreme is by
            # construction ≤ close-equity for a drawdown, so this strictly widens
            # detection to real breaches the close hid; it never fires when even the
            # adverse extreme stays above the threshold (verified by the control test).
            drop_equity = min(equity, intrabar_equity)

            def _exit_px(pos: "Position") -> float:
                # Close at the adverse extreme when the breach was intrabar (so the
                # booked exit reflects where the rule tripped), else the latest close.
                if intrabar_equity < equity:
                    return adverse_price.get(pos.symbol, latest_prices.get(pos.symbol, pos.entry_price))
                return latest_prices.get(pos.symbol, pos.entry_price)

            if check_equity_drop(drop_equity, state.cycle_start_equity, max_drawdown_pct):
                if config.get("smart_drawdown_close"):
                    # SMART is ONE-SHOT per scan window. Production closes the losing
                    # symbols once, transitions the rule to "executed", and does NOT
                    # re-arm or re-anchor it (close_rule_evaluator.py:314) — surviving
                    # winners get no further drawdown protection until the NEXT scan
                    # re-creates the rule. The old backtest re-anchored cycle_start_equity
                    # and stayed active, letting SMART re-fire on a winner that later
                    # turned losing within the same window — closing positions
                    # production would have held. Gate on the fired-flag for parity.
                    #
                    # Losers are judged at the SAME adverse extreme used for the
                    # breach, so a position only pulled negative by the intrabar wick
                    # is correctly closed (matching live, which sees the live tick).
                    intrabar_losers = [
                        pos for pos in state.open_positions
                        if compute_unrealized_pnl(
                            pos.equity_ref_entry or pos.entry_price,
                            adverse_price.get(pos.symbol, pos.equity_ref_entry or pos.entry_price),
                            pos.qty, pos.side,
                        ) < 0
                    ]
                    if state.smart_drawdown_fired:
                        pass  # already fired this scan window — production holds
                    elif intrabar_losers:
                        for pos in list(intrabar_losers):
                            self._close_position(state, pos, "equity_drop_smart", _exit_px(pos), candle_time, fee_rate)
                        # Mark one-shot fired. Do NOT re-anchor cycle_start_equity:
                        # production leaves the (now-executed) rule's reference
                        # untouched, and the shared reference still feeds the
                        # close_on_profit / equity_rise goals unchanged.
                        state.smart_drawdown_fired = True
                    else:
                        # No losers: production resets the reference to current equity
                        # to prevent immediate re-trigger (close_rule_evaluator.py:292),
                        # WITHOUT marking executed — so it can still fire later if a
                        # position turns losing. Mirror that: re-anchor, don't set flag.
                        state.cycle_start_equity = equity
                else:
                    # Non-SMART: close ALL positions, deactivate cycle
                    for pos in list(state.open_positions):
                        self._close_position(state, pos, "equity_drop", _exit_px(pos), candle_time, fee_rate)
                    state.cycle_start_equity = 0  # Cycle terminated
                return  # Don't evaluate further rules after equity drop

        # --- close_on_profit_pct ---
        # Production gates this on `if close_pct and target_goal` (auto_trade_service:
        # both must be truthy) — a missing/zero target_goal_value means NO close_on_profit
        # at all. The backtest must NOT silently default target to 100, or it would fire
        # a force-close that production never would. (Production's request schema also
        # REQUIRES target_goal_value when close_on_profit_pct is set; the backtest schema
        # now enforces the same cross-field rule, but defend in depth here too.)
        close_on_profit = config.get("close_on_profit_pct")
        target_goal_value = config.get("target_goal_value")
        if (
            close_on_profit
            and target_goal_value
            and state.cycle_start_equity > 0
            and check_close_on_profit(equity, state.cycle_start_equity, close_on_profit, target_goal_value)
        ):
            for pos in list(state.open_positions):
                self._close_position(state, pos, "close_on_profit", latest_prices.get(pos.symbol, pos.entry_price), candle_time, fee_rate)
            state.cycle_start_equity = 0  # Cycle terminated
            return  # Cycle closed — don't also evaluate the rise goal this candle

        # --- EQUITY_RISE_PCT (target_goal_type == "profit_pct") ---
        # Production maps a profit_pct target goal to an EQUITY_RISE_PCT close rule
        # (auto_trade_service: reference_value = base_capital, threshold = goal_value),
        # closing ALL positions when equity rises goal_value% from the cycle reference.
        # Mirror that here so a profit_pct goal terminates the cycle in the backtest the
        # same way it does in live trading (the trade_count goal is handled separately
        # as an admission early-stop in the filter chain).
        if (
            config.get("target_goal_type") == "profit_pct"
            and target_goal_value
            and state.cycle_start_equity > 0
            and check_equity_rise(equity, state.cycle_start_equity, target_goal_value)
        ):
            for pos in list(state.open_positions):
                self._close_position(state, pos, "equity_rise", latest_prices.get(pos.symbol, pos.entry_price), candle_time, fee_rate)
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
        from backend.services.trading_rules import (
            check_trailing_activation,
            check_trailing_trigger,
            compute_unrealized_pnl,
        )

        trailing_pct = config.get("trailing_profit_pct", 0)
        if not trailing_pct:
            return

        close_price = candle["close"]
        positions_to_close = []

        for pos in state.open_positions:
            # ONLY evaluate positions on THIS symbol (uses THIS symbol's candle)
            if pos.symbol != symbol:
                continue

            # Trailing is a lifecycle (close-timing) rule → value it off the stable 5m
            # reference entry so drill-down never changes whether/when it triggers.
            ref_entry = pos.equity_ref_entry or pos.entry_price

            # Compute unrealized PnL at candle close
            upnl = compute_unrealized_pnl(ref_entry, close_price, pos.qty, pos.side)

            # Step 1: If upnl <= 0, clear peak and skip
            if upnl <= 0:
                pos.trailing_active = False
                pos.trailing_peak = 0.0
                continue

            # Step 2: Check activation (price move % >= threshold AND upnl > 0)
            if not check_trailing_activation(close_price, ref_entry, trailing_pct, upnl):
                # Below activation: production (_evaluate_trailing_profit) `continue`s
                # here WITHOUT checking the retracement trigger — a position whose
                # current profit% has fallen below the activation threshold is NEVER
                # trailing-closed (close_rule_evaluator.py: `if profit_pct <
                # activation_pct: continue`). It only re-arms if price rises back above
                # activation. Preserve the peak (do NOT clear it) but do NOT trigger —
                # mirroring production exactly. The old code checked the trigger here,
                # closing positions production would have held.
                continue

            # Position is profitable and above activation threshold
            per_unit_pnl = upnl / pos.qty if pos.qty > 0 else 0.0

            # Use candle high/low for peak (more accurate)
            if pos.side == "Buy":
                peak_price = candle["high"]
                peak_upnl = compute_unrealized_pnl(ref_entry, peak_price, pos.qty, pos.side)
            else:
                peak_price = candle["low"]
                peak_upnl = compute_unrealized_pnl(ref_entry, peak_price, pos.qty, pos.side)

            peak_per_unit = peak_upnl / pos.qty if pos.qty > 0 and peak_upnl > 0 else per_unit_pnl

            # Step 3: Update peak if new high
            if peak_per_unit > pos.trailing_peak:
                pos.trailing_peak = peak_per_unit
                pos.trailing_active = True
                continue

            # Step 4: Check trigger — per_unit_pnl < peak × 0.5 (shared SSOT so live
            # and backtest apply the identical retracement rule).
            if pos.trailing_active and check_trailing_trigger(per_unit_pnl, pos.trailing_peak):
                positions_to_close.append(pos)

        # Close triggered positions. Guard against a position already closed by an
        # earlier rule this candle (defensive parity with the TP/SL close loop —
        # _close_position would raise on a double .remove()).
        for pos in positions_to_close:
            if pos in state.open_positions:
                self._close_position(state, pos, "trailing_profit", close_price, candle_time, fee_rate)

    def _evaluate_time_rules(
        self,
        config: dict[str, Any],
        state: SimulationState,
        candle_time: datetime,
        fee_rate: float,
        latest_prices: Optional[dict[str, float]] = None,
    ) -> None:
        """Evaluate time-based close rules: BREAKEVEN_TIMEOUT, MAX_DURATION, and the
        per-position MR fast time-stop (F2).

        BREAKEVEN_TIMEOUT: account-level — closes ALL remaining positions once total
            open uPnL >= fee buffer, after the breakeven window.
        MAX_DURATION: force-closes after elapsed hours at the symbol's latest price.
        MR time-stop: force-closes a mean_reversion position after its own
            time_stop_minutes (F2's strategy-critical fast exit), independent of the
            account-level MAX_DURATION.
        """
        from backend.services.trading_rules import compute_unrealized_pnl

        breakeven_hours = config.get("breakeven_timeout_hours")
        max_duration_hours = config.get("max_trade_duration_hours")
        # Any MR position carries its own time-stop, so we must run even when the
        # account-level time rules are unset.
        any_mr_timestop = any(p.time_stop_minutes for p in state.open_positions)

        if not breakeven_hours and not max_duration_hours and not any_mr_timestop:
            return

        latest_prices = latest_prices or {}
        positions_to_close = []          # (pos, close_reason)

        for pos in list(state.open_positions):
            elapsed_hours = (candle_time - pos.entry_time).total_seconds() / 3600.0

            # MR fast time-stop (per-position): close after its own minutes elapse.
            if pos.time_stop_minutes and elapsed_hours * 60.0 >= pos.time_stop_minutes:
                positions_to_close.append((pos, "mr_time_stop"))
                continue

            # MAX_DURATION: force close after max hours
            if max_duration_hours and elapsed_hours >= max_duration_hours:
                positions_to_close.append((pos, "max_duration"))
                continue

        # BREAKEVEN_TIMEOUT (account-level, mirrors live close_rule_evaluator): once the
        # cycle has aged past the breakeven window, close ALL remaining open positions
        # the moment total open unrealised PnL clears the fee buffer (Σ notional × fee
        # × 1.5), so the mass close nets ~flat. Positions already queued for MR/
        # MAX_DURATION close above are excluded. Empty remaining → do nothing (no
        # positions = cannot be at breakeven).
        if breakeven_hours:
            already = {id(p) for p, _ in positions_to_close}
            remaining = [p for p in state.open_positions if id(p) not in already]
            if remaining:
                # All positions in a cycle share ~one entry_time (no mid-cycle entries), so the oldest position's age is the cycle's age past the breakeven window.
                oldest_elapsed = max(
                    (candle_time - p.entry_time).total_seconds() / 3600.0 for p in remaining
                )
                if oldest_elapsed >= breakeven_hours:
                    total_upnl = 0.0
                    total_buffer = 0.0
                    for p in remaining:
                        mark = latest_prices.get(p.symbol, p.entry_price)
                        ref = p.equity_ref_entry or p.entry_price
                        total_upnl += compute_unrealized_pnl(ref, mark, p.qty, p.side)
                        total_buffer += p.qty * mark * (fee_rate / 100.0) * 1.5
                    if total_upnl >= total_buffer:
                        for p in remaining:
                            positions_to_close.append((p, "breakeven"))

        # Close time-stopped positions at the symbol's latest price. Guard against a
        # position already closed by an earlier rule this candle (defensive parity
        # with the TP/SL close loop — _close_position would raise on a double .remove()).
        for pos, reason in positions_to_close:
            if pos in state.open_positions:
                exit_price = latest_prices.get(pos.symbol, pos.entry_price)
                self._close_position(state, pos, reason, exit_price, candle_time, fee_rate)
