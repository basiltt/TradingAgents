"""Backtest Simulation Engine — pure, synchronous, all data pre-loaded.

This module contains the core simulation loop that replays historical signals
through the full auto-trade cycle. It is designed to run in a ThreadPoolExecutor
and has ZERO I/O — all data (signals, klines, config) is injected.

The only external dependency is an optional `threading.Event` for cancellation
and an optional progress callback.
"""

from __future__ import annotations

import bisect
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


class _MarkIndex:
    """Per-run cache of per-symbol open_time arrays for O(log N) mark lookups.

    Phase P3 (RC-2 fix): the engine repeatedly needs "the close of the last candle
    with open_time <= t" to mark a carried position. The original code did a linear
    scan from index 0 with an early break — O(k) per call, O(positions × scans × T)
    overall (quadratic in the timeline). Because each symbol's kline list is sorted
    by open_time, that lookup is a binary search: bisect_right(open_times, t) - 1.

    This is PARITY-EXACT — it returns the close of exactly the same candle the linear
    scan would land on (the last one at/before t), so every downstream value
    (carried uPnL, sizing capital, equity reference) is byte-identical. Only the
    cost changes (O(log N) vs O(T)). The per-symbol open_time list + close list are
    built once per run and reused across all three call sites.
    """

    __slots__ = ("_open_times", "_closes", "_series")

    def __init__(self, klines: dict[str, list[dict[str, Any]]]):
        self._open_times: dict[str, list[datetime]] = {}
        self._closes: dict[str, list[float]] = {}
        self._series: dict[str, list[dict[str, Any]]] = {}
        for sym, series in klines.items():
            # series is sorted by open_time (cache returns ORDER BY open_time ASC).
            self._series[sym] = series
            self._open_times[sym] = [k["open_time"] for k in series]
            self._closes[sym] = [k["close"] for k in series]

    def mark_at_or_before(self, symbol: str, t: datetime, default: float) -> float:
        """Close of the last candle with open_time <= t, or `default` if none.

        Equivalent to the legacy loop:
            mark = default
            for k in klines[symbol]:
                if k["open_time"] <= t: mark = k["close"]
                else: break
            return mark
        """
        ots = self._open_times.get(symbol)
        if not ots:
            return default
        # bisect_right finds the insertion point AFTER any equal element, so
        # idx-1 is the last index with open_time <= t (matches the <= comparison).
        idx = bisect.bisect_right(ots, t) - 1
        if idx < 0:
            return default
        return self._closes[symbol][idx]

    def candle_at_or_before(self, symbol: str, t: datetime) -> Optional[dict[str, Any]]:
        """Last candle with open_time <= t, or None if the series has no mark yet."""
        ots = self._open_times.get(symbol)
        if not ots:
            return None
        idx = bisect.bisect_right(ots, t) - 1
        if idx < 0:
            return None
        series = self._series.get(symbol) or []
        return series[idx] if idx < len(series) else None

    def candles_after_until(
        self, symbol: str, start_time: datetime, end_time: Optional[datetime]
    ) -> list[dict[str, Any]]:
        """Candles with start_time < open_time < end_time.

        Parity-exact replacement for the legacy per-window full-series scan:
            for k in klines[symbol]:
                if k["open_time"] <= start_time: continue
                if end_time and k["open_time"] >= end_time: continue
                ...

        The kline series are sorted, so a pair of bisections finds the exact same
        half-open window without walking all historical candles for every scan
        segment.
        """
        ots = self._open_times.get(symbol)
        if not ots:
            return []
        lo = bisect.bisect_right(ots, start_time)
        hi = bisect.bisect_left(ots, end_time) if end_time is not None else len(ots)
        if hi <= lo:
            return []
        # _series is attached below for the range lookup; keeping the mark arrays as
        # plain lists preserves the hot mark_at_or_before path.
        return self._series.get(symbol, [])[lo:hi]


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
    # Equity-reference entry price used by portfolio close rules. Production's wallet
    # equity is based on the exchange avgPrice, so this must follow the simulated
    # actual fill (including entry drill-down/slippage), not a synthetic 5m fill.
    # 0.0 => fall back to entry_price for legacy fixtures.
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
    # Production's account close rules use rule.reference_value as the clock start.
    # These are refreshed only when live would create fresh rules for a non-skipped
    # scan/recheck; skipped scans preserve the previous active-rule clock.
    breakeven_rule_started_at: Optional[datetime] = None
    max_duration_rule_started_at: Optional[datetime] = None
    # Tracking
    signals_processed: int = 0
    signals_filtered: int = 0
    signals_entered: int = 0  # LIFETIME entries across the whole backtest (stats + target_goal)
    scan_entered: int = 0  # entries in the CURRENT scan only — reset each scan; gates max_trades
                           # (production creates a fresh executor per scan, so max_trades is per-cycle)
    signals_no_kline: int = 0  # signals dropped because the symbol had NO cached candles —
                               # production would have traded them, so this means the backtest
                               # UNDER-trades vs reality; surfaced as a warning, not a silent skip.
    no_kline_symbols: set[str] = field(default_factory=set)
    slippage_bps: int = 0  # round-trip slippage; applied adversely on BOTH entry fill and exit fill
                           # (production closes via Bybit market reduce-only orders that slip)
    smart_drawdown_fired: bool = False  # EQUITY_DROP_PCT_SMART is ONE-SHOT per scan
                           # window: production closes losers once, marks the rule
                           # "executed", and never re-arms it until the next scan
                           # re-creates it. Reset each scan; gates re-firing so the
                           # backtest can't over-close winners-turned-losers mid-window.
    smart_drawdown_closed_at: Optional[datetime] = None  # timestamp of the last SMART
                           # loser close. Used to keep BREAKEVEN_TIMEOUT from
                           # immediately evaluating a post-SMART survivor-only
                           # book in the same rule sampling window; production's
                           # account-rule pass uses the pre-close wallet snapshot.
    breakeven_suppressed_after_smart: bool = False  # SMART is a partial-cycle
                           # account close. Live leaves survivors to later
                           # position/time rules instead of letting breakeven
                           # immediately operate on the reduced survivor book.
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

        # Phase P3: per-symbol open_time index for O(log N) "mark at/before t" lookups,
        # built ONCE per run and reused at every carried-position marking site. Replaces
        # the O(T) linear prefix scans (RC-2). Parity-exact (same candle, same close).
        self._mark_index = _MarkIndex(klines)

        # Initialize state
        starting_capital = config["starting_capital"]
        state = SimulationState(
            wallet_balance=starting_capital,
            sizing_capital=starting_capital,
            slippage_bps=config.get("slippage_bps", 2),
        )

        warnings: list[str] = []
        report_start = self._as_aware_datetime(config.get("_report_start"))
        report_end = self._as_aware_datetime(config.get("_report_end"))
        report_started = report_start is None

        def _start_report_window() -> None:
            """Reset accounting at the requested window after selector warm-up."""
            nonlocal report_started
            if report_started or report_start is None:
                return
            state.wallet_balance = starting_capital
            state.equity_curve = [{
                "ts": report_start,
                "equity": starting_capital,
                "drawdown_pct": 0.0,
            }]
            # Carried positions were opened before the report window. Their entry fees
            # and pre-window funding are already reflected in the user's supplied
            # starting balance, so do not charge those costs again when they close.
            for pos in state.open_positions:
                pos.entry_fee = 0.0
                pos.funding_paid = 0.0
            report_started = True
            warnings.append("schedule_warmup_applied")

        def _maybe_start_report_window(at_time: Optional[datetime]) -> None:
            if report_started or report_start is None or at_time is None:
                return
            at = self._as_aware_datetime(at_time)
            if at is not None and at >= report_start:
                _start_report_window()

        def _evaluate_window(
            cfg: dict[str, Any],
            start_time: datetime,
            end_time: Optional[datetime],
        ) -> None:
            nonlocal report_started
            if (
                report_start is not None
                and not report_started
                and start_time < report_start
                and (end_time is None or end_time > report_start)
            ):
                self._evaluate_candles_until(
                    cfg, klines, state, start_time, report_start, cancel_event
                )
                _start_report_window()
                self._evaluate_candles_until(
                    cfg, klines, state, report_start, end_time, cancel_event
                )
                return
            _maybe_start_report_window(start_time)
            self._evaluate_candles_until(cfg, klines, state, start_time, end_time, cancel_event)

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
                filter_stats={
                    "signals_total": 0,
                    "signals_filtered": 0,
                    "signals_entered": 0,
                    "signals_no_kline": 0,
                    "signals_no_kline_symbols": [],
                },
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
        if scan_order and report_started:
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

            scan_config = config
            scan_execution_mode = scan_config.get("execution_mode", execution_mode)
            scan_signals = scans[scan_id]
            current_time = scan_signals[0]["signal_time"]
            scan_started_at = scan_signals[0].get("scan_started_at") or current_time
            selection_time = self._scan_selection_time(scan_config, scan_id, current_time)
            post_recheck_time = self._scan_post_scan_recheck_time(scan_config, scan_id, selection_time)
            live_selection = self._scan_live_selection(scan_config, scan_id)

            # Bind this scan's ScanContext (or None) for the regime gate/route block.
            self._ctx = self._scan_contexts.get(scan_id)

            # Reset the per-scan entry counter. max_trades caps NEW trades per scan
            # (cycle), mirroring production, which builds a fresh AutoTradeExecutor
            # per scan with trades_executed=0. The lifetime signals_entered is left
            # untouched (it drives the backtest-level target_goal early-stop + stats).
            state.scan_entered = 0

            next_scan_start = None
            if scan_idx + 1 < len(scan_order):
                next_scan_id = scan_order[scan_idx + 1]
                next_scan_start = scans[next_scan_id][0].get("scan_started_at") or scans[next_scan_id][0]["signal_time"]

            if live_selection is not None:
                if live_selection:
                    self._force_close_for_live_selection(scan_config, klines, state, selection_time)
                    self._open_scan_signals(
                        scan_config,
                        scan_signals,
                        klines,
                        state,
                        selection_time,
                        scan_execution_mode,
                        selection_mode="live_selection",
                        live_selection=live_selection,
                    )
                else:
                    state.signals_filtered += len(scan_signals)

                if state.open_positions:
                    _evaluate_window(scan_config, selection_time, next_scan_start)
                    candle_count += 1

                if on_progress:
                    pct = int(((scan_idx + 1) / len(scan_order)) * 100)
                    on_progress(min(pct, 99))
                continue

            # Live evaluates skip_if_positions_open at scan START, then executes the
            # scan at completion. If positions existed at start but closed during the
            # scan, post_scan_recheck trades the completed results using its own
            # abs(score)-only ordering. The backtest must preserve that split or it
            # selects a normal batch set that live never attempted for this account.
            positions_open_at_scan_start = bool(state.open_positions)
            if positions_open_at_scan_start:
                _evaluate_window(scan_config, scan_started_at, post_recheck_time)

            evaluate_from_time = selection_time
            if scan_config.get("skip_if_positions_open") and positions_open_at_scan_start:
                if state.open_positions:
                    state.signals_filtered += len(scan_signals)
                    _evaluate_window(scan_config, post_recheck_time, next_scan_start)
                    if on_progress:
                        pct = int(((scan_idx + 1) / len(scan_order)) * 100)
                        on_progress(min(pct, 99))
                    continue
                _maybe_start_report_window(post_recheck_time)
                self._open_scan_signals(
                    scan_config,
                    scan_signals,
                    klines,
                    state,
                    post_recheck_time,
                    scan_execution_mode,
                    selection_mode="post_scan_recheck",
                )
                evaluate_from_time = post_recheck_time
            else:
                _maybe_start_report_window(selection_time)
                self._open_scan_signals(
                    scan_config, scan_signals, klines, state, selection_time, scan_execution_mode
                )

            # Evaluate open positions until the next scan START, because live
            # init_balances observes positions at that instant.
            if state.open_positions:
                _evaluate_window(scan_config, evaluate_from_time, next_scan_start)
                candle_count += 1

            # Report progress
            if on_progress:
                pct = int(((scan_idx + 1) / len(scan_order)) * 100)
                on_progress(min(pct, 99))

        # --- FORCE-CLOSE AT BACKTEST END (Task 3.10) ---
        fee_rate = config.get("fee_rate_pct", 0.055)
        if report_start is not None and not report_started:
            _start_report_window()
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

        def _in_report_window(trade: dict[str, Any]) -> bool:
            if report_start is None:
                return True
            entry_time = self._as_aware_datetime(trade.get("entry_time"))
            exit_time = self._as_aware_datetime(trade.get("exit_time"))
            activity_time = exit_time or entry_time
            if activity_time is None:
                return False
            if activity_time < report_start:
                return False
            if report_end is not None and entry_time is not None and entry_time > report_end:
                return False
            return True

        result_trades = [t for t in state.closed_trades if _in_report_window(t)]

        # Compute all metrics from reported trades + reported equity curve. Warm-up
        # trades remain in state.closed_trades for adaptive selector history, but are
        # not surfaced as user-visible backtest trades.
        from backend.services.backtest_metrics import compute_all_metrics
        metrics = compute_all_metrics(result_trades, state.equity_curve, config)

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
            trades=result_trades,
            equity_curve=state.equity_curve,
            metrics=metrics,
            warnings=warnings,
            filter_stats={
                "signals_total": len(signals),
                "signals_filtered": state.signals_filtered,
                "signals_entered": state.signals_entered,
                "signals_no_kline": state.signals_no_kline,
                "signals_no_kline_symbols": sorted(state.no_kline_symbols),
            },
        )

    # --- Filter chain implementation ---

    @staticmethod
    def _completed_timestamp(s: dict[str, Any]) -> tuple[int, float]:
        completed_at = s.get("completed_at") or s.get("analysis_completed_at")
        has_ts = 0
        ts = 0.0
        if isinstance(completed_at, datetime):
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=timezone.utc)
            has_ts = 1
            ts = completed_at.timestamp()
        elif isinstance(completed_at, str) and completed_at:
            try:
                parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                has_ts = 1
                ts = parsed.timestamp()
            except ValueError:
                has_ts = 0
                ts = 0.0
        return has_ts, ts

    @classmethod
    def _rank_key(cls, s: dict[str, Any]) -> tuple:
        """Selection rank used by live auto_trade_service.execute_batch.

        Live sorts the deduped in-memory results by
        ``(abs(score), result["completed_at"])`` descending and relies on Python's
        stable sort for exact ties. Copied schedule rows can have
        scan_results.completed_at NULL even though the live in-memory result had
        the per-symbol analysis completion timestamp, so reconstruct that timestamp
        from analysis_completed_at before ranking. There is deliberately no final
        id tiebreak here: adding one changes which equal-score/equal-time signals
        enter when max_trades cuts the candidate list.
        """
        has_ts, ts = cls._completed_timestamp(s)
        return (abs(s.get("score", 0)), has_ts, ts)

    @staticmethod
    def _fill_rank_key(s: dict[str, Any]) -> float:
        """Live relaxed fill ranks leftover candidates by abs(score) only."""
        return abs(s.get("score", 0))

    @classmethod
    def _post_recheck_sort_key(cls, s: dict[str, Any]) -> tuple:
        """Live post_scan_recheck ranks by abs(score), preserving completion order.

        The scanner's in-memory ``results`` list is appended as analyses complete.
        post_scan_recheck then applies a stable ``abs(score)`` sort, so equal-score
        candidates keep completion-time ASC order. Historical local rows are loaded
        by scan_result id, so reconstruct that stable order from analysis_completed_at
        when scan_results.completed_at is absent.
        """
        has_ts, ts = cls._completed_timestamp(s)
        return (-abs(s.get("score", 0)), 0 if has_ts else 1, ts)

    @staticmethod
    def _to_symbol(ticker: str) -> str:
        return ticker if ticker.endswith("USDT") else f"{ticker}USDT"

    @staticmethod
    def _sector_for(config: dict[str, Any], symbol: str) -> str:
        sector_map = config.get("_sector_map") or {}
        sector = sector_map.get(symbol)
        if sector:
            return sector
        from backend.services.sector_map import get_sector as _static_get_sector
        return _static_get_sector(symbol)

    @staticmethod
    def _as_aware_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    def _scan_selection_time(
        self,
        config: dict[str, Any],
        scan_id: str,
        default_time: datetime,
    ) -> datetime:
        """Live account replay clock for this scan, falling back to scan completion.

        Production checks signal age and places market orders at the account's actual
        executor time, not at scan completion. For account-aware backtests the service
        injects that per-scan timestamp from debug traces / trade rows.
        """
        default_time = self._as_aware_datetime(default_time) or default_time
        by_scan = config.get("_selection_time_by_scan") or {}
        raw = None
        if isinstance(by_scan, dict):
            raw = by_scan.get(scan_id) or by_scan.get(str(scan_id))
        selection_time = self._as_aware_datetime(raw)
        if selection_time is not None:
            return selection_time
        by_scan = config.get("_schedule_selection_time_by_scan") or {}
        raw = None
        if isinstance(by_scan, dict):
            raw = by_scan.get(scan_id) or by_scan.get(str(scan_id))
        selection_time = self._as_aware_datetime(raw)
        return selection_time or default_time

    def _scan_post_scan_recheck_time(
        self,
        config: dict[str, Any],
        scan_id: str,
        default_time: datetime,
    ) -> datetime:
        """Estimated live clock for post_scan_recheck.

        Account replay supplies exact `_selection_time_by_scan` values. Account-free
        Specific Schedule supplies `_schedule_post_scan_recheck_time_by_scan`, derived
        from the copied scan config order.
        """
        default_time = self._as_aware_datetime(default_time) or default_time
        by_scan = config.get("_selection_time_by_scan") or {}
        raw = None
        if isinstance(by_scan, dict):
            raw = by_scan.get(scan_id) or by_scan.get(str(scan_id))
        recheck_time = self._as_aware_datetime(raw)
        if recheck_time is not None:
            return recheck_time
        by_scan = config.get("_schedule_post_scan_recheck_time_by_scan") or {}
        raw = None
        if isinstance(by_scan, dict):
            raw = by_scan.get(scan_id) or by_scan.get(str(scan_id))
        recheck_time = self._as_aware_datetime(raw)
        return recheck_time or default_time

    def _scan_live_selection(
        self,
        config: dict[str, Any],
        scan_id: str,
    ) -> Optional[list[dict[str, Any]]]:
        by_scan = config.get("_live_selection_by_scan")
        if not isinstance(by_scan, dict):
            return None
        if scan_id in by_scan:
            return list(by_scan.get(scan_id) or [])
        key = str(scan_id)
        if key in by_scan:
            return list(by_scan.get(key) or [])
        return None

    @staticmethod
    def _side_name(side: Any) -> str:
        value = str(side or "").strip().lower()
        if value in ("buy", "long"):
            return "buy"
        if value in ("sell", "short"):
            return "sell"
        return value

    def _signals_for_live_selection(
        self,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        live_selection: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        from backend.services.trading_rules import determine_side

        remaining = list(scan_signals)
        selected: list[dict[str, Any]] = []
        for item in live_selection:
            wanted_symbol = self._to_symbol(str(item.get("symbol") or ""))
            wanted_side = self._side_name(item.get("side"))
            match_idx = None
            for idx, sig in enumerate(remaining):
                if self._to_symbol(sig.get("ticker", "")) != wanted_symbol:
                    continue
                if wanted_side:
                    sig_side = self._side_name(
                        determine_side(sig.get("direction", ""), config.get("direction", "straight"))
                    )
                    if sig_side != wanted_side:
                        continue
                match_idx = idx
                break
            if match_idx is not None:
                selected.append(remaining.pop(match_idx))
        return selected

    def _force_close_for_live_selection(
        self,
        config: dict[str, Any],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        close_time: datetime,
    ) -> None:
        """Clear simulated positions before a pinned live selection opens.

        If live placed new scanner trades for this account, the live account had no
        blocking positions at that instant. The simulated close timing can still lag;
        close those carried positions at the current mark so they are recorded and do
        not block the exact live-selected membership.
        """
        if not state.open_positions:
            return
        fee_rate = config.get("fee_rate_pct", 0.055)
        for pos in list(state.open_positions):
            exit_price = self._mark_index.mark_at_or_before(pos.symbol, close_time, pos.entry_price)
            self._close_position(state, pos, "live_selection_sync", exit_price, close_time, fee_rate)

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

        # Step 2: Rank exactly like live execute_batch (see _rank_key).
        unique_signals.sort(key=self._rank_key, reverse=True)

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
            remaining = [s for s in unique_signals if self._to_symbol(s["ticker"]) not in
                         {p.symbol for p in state.open_positions}]
            remaining.sort(key=self._fill_rank_key, reverse=True)
            remaining_slots = max(0, config.get("max_trades", 999) - entered)
            for sig in remaining[:remaining_slots]:
                if (
                    self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=True)
                    and self._open_position(config, sig, klines, state, current_time, relaxed=True)
                ):
                    entered += 1

        return entered

    def _process_post_scan_recheck_signals(
        self,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        current_time: datetime,
    ) -> int:
        """Process a scan through live post_scan_recheck ordering.

        post_scan_recheck dedupes by ticker, then sorts only by abs(score)
        descending. Python's stable sort preserves scan-result completion order for
        equal scores, which is why rescued scans can pick a different top-N set than
        execute_batch.
        """
        deduped: dict[str, dict] = {}
        for sig in scan_signals:
            deduped[sig["ticker"]] = sig
        unique_signals = list(deduped.values())
        unique_signals.sort(key=self._post_recheck_sort_key)

        entered = 0
        for sig in unique_signals:
            if (
                self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=False)
                and self._open_position(config, sig, klines, state, current_time)
            ):
                entered += 1

        if config.get("fill_to_max_trades") and entered < config.get("max_trades", 999):
            remaining = [s for s in unique_signals if self._to_symbol(s["ticker"]) not in
                         {p.symbol for p in state.open_positions}]
            remaining.sort(key=self._fill_rank_key, reverse=True)
            remaining_slots = max(0, config.get("max_trades", 999) - entered)
            for sig in remaining[:remaining_slots]:
                if (
                    self._apply_filter_chain(config, sig, state, current_time, klines, relaxed=True)
                    and self._open_position(config, sig, klines, state, current_time, relaxed=True)
                ):
                    entered += 1

        return entered

    def _process_live_selection_signals(
        self,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        live_selection: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        state: SimulationState,
        current_time: datetime,
    ) -> int:
        """Open the exact symbols that the live account selected for this scan."""
        entered = 0
        for sig in self._signals_for_live_selection(config, scan_signals, live_selection):
            if self._open_position(config, sig, klines, state, current_time):
                entered += 1
        skipped = max(0, len(scan_signals) - entered)
        state.signals_filtered += skipped
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
                if self._to_symbol(s.get("ticker", "")) not in open_syms and s.get("direction", "hold") != "hold"
            ]
            remaining.sort(key=self._fill_rank_key, reverse=True)
            remaining_slots = max(0, config.get("max_trades", 999) - state.scan_entered)
            for sig in remaining[:remaining_slots]:
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
        symbol = self._to_symbol(ticker)

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
        if symbol in existing_symbols:
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
        # Age is measured from the per-symbol completion timestamp. Copied rows can
        # have NULL scan_results.completed_at even though analysis_runs.completed_at
        # preserves the timestamp _try_trade used for freshness. Use the same fallback
        # as normal batch ranking so stale early completions are skipped like live.
        max_age = config.get("max_signal_age_minutes")
        if max_age is not None:
            age_anchor = (
                signal.get("completed_at")
                or signal.get("analysis_completed_at")
                or signal.get("signal_time")
            )
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

        # 9. Sector concentration limit. The service preloads the live sector cache
        # into config["_sector_map"]; unknown/static-only symbols fall back to the
        # same static map live uses when the dynamic service is unavailable.
        max_same_sector = config.get("max_same_sector")
        if max_same_sector is not None:
            sector = self._sector_for(config, symbol)
            if sector != "other":
                same_sector_count = sum(
                    1 for p in state.open_positions
                    if self._sector_for(config, p.symbol) == sector
                )
                if same_sector_count >= max_same_sector:
                    state.signals_filtered += 1
                    return False

        # 10. Adaptive blacklist. Live computes this from signal_performance before
        # placement. Local schedule backtests do not have account trade history, so
        # compute the same rolling win-rate rule from simulated trades already closed
        # earlier in this run. Explicit replay/precomputed inputs still win when
        # intentionally supplied.
        if config.get("adaptive_blacklist_enabled") and self._is_adaptively_blacklisted(
            config, state, symbol, current_time, is_mr=is_mr
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
                # Live checks drift against the exchange mark at the decision instant
                # (`accounts_service.get_mark_price`), before placement. The closest
                # account-free historical equivalent is the last cached mark at or before
                # the decision time, not the future entry bar's open.
                current_price = self._mark_index.mark_at_or_before(ticker, current_time, None)
                if (config.get("scan_source") or {}).get("mode") == "schedule":
                    candle = self._mark_index.candle_at_or_before(ticker, current_time)
                    if candle is not None:
                        # Live checks an exchange mark at the decision instant. Copied
                        # account-free schedule data has only OHLC bars, so approximate
                        # the mark from where the decision lands inside the 5m bar:
                        # near the bar open, the adverse side best protects against
                        # trades live skipped on a fast current-mark move; once the
                        # decision is materially inside the bar, the close is the better
                        # point estimate and avoids rejecting trades live still admitted.
                        elapsed = None
                        open_time = candle.get("open_time")
                        if isinstance(open_time, datetime):
                            elapsed = (current_time - open_time).total_seconds()
                        bar_seconds = self._sim_bar_seconds(klines.get(ticker, [])) or 300
                        early_window = min(30.0, max(1.0, bar_seconds * 0.10))
                        if elapsed is not None and 0 <= elapsed <= early_window:
                            current_price = (
                                candle["high"] if direction in ("buy", "long") else candle["low"]
                            )
                        else:
                            current_price = candle["close"]
                if current_price is not None and current_price > 0:
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
            state.no_kline_symbols.add(ticker)
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
            state.no_kline_symbols.add(ticker)
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
        # Equity rules must value uPnL from the same fill basis live sees in wallet
        # equity: the exchange avgPrice. Using the un-drilled 5m open here can make a
        # profit-target/drawdown rule fire before production would, which changes the
        # skip_if_positions_open and post_scan_recheck trade-picking path.
        equity_ref_entry = entry_price

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
            # P3: O(log N) mark lookup (was a linear prefix scan). Parity-exact —
            # same candle close the loop would land on (last open_time <= current_time).
            _mark = self._mark_index.mark_at_or_before(_p.symbol, current_time, _ref)
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
        state: SimulationState,
        symbol: str,
        current_time: datetime,
        *,
        is_mr: bool = False,
    ) -> bool:
        """Check the same adaptive blacklist rule live auto-trading uses.

        Live injects a precomputed symbol set from signal_performance before the
        executor runs. In schedule backtests, there is no local account/trade table;
        the equivalent source is the simulated closed-trade ledger up to this scan.
        """
        from backend.services.strategy_router import select_adaptive_blacklist

        precomputed = select_adaptive_blacklist(config, mr_fade=is_mr)
        if precomputed:
            precomputed_set = precomputed if isinstance(precomputed, set) else set(precomputed)
            return symbol in precomputed_set

        lookback_hours = config.get("adaptive_blacklist_lookback_hours", 48)
        min_trades = config.get("adaptive_blacklist_min_trades", 5)
        max_win_rate = config.get("adaptive_blacklist_max_win_rate", 30.0)
        strategy_kind = "mean_reversion" if is_mr else "trend"
        cutoff = current_time - timedelta(hours=lookback_hours)

        wins = 0
        total = 0

        def _count(symbol_value: Any, strategy_value: Any, closed_at_value: Any, is_win_value: Any) -> None:
            nonlocal wins, total
            if symbol_value != symbol:
                return
            if (strategy_value or "trend") != strategy_kind:
                return
            closed_at = self._as_aware_datetime(closed_at_value)
            if closed_at is None:
                return
            if cutoff < closed_at <= current_time:
                total += 1
                if bool(is_win_value):
                    wins += 1

        for row in config.get("_adaptive_blacklist_history") or []:
            if row.get("symbol") != symbol:
                continue
            _count(
                row.get("symbol"),
                row.get("strategy_kind"),
                row.get("closed_at"),
                row.get("is_win"),
            )

        for trade in state.closed_trades:
            _count(
                trade.get("symbol"),
                trade.get("strategy_kind"),
                trade.get("exit_time"),
                float(trade.get("pnl") or 0.0) > 0.0,
            )

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
        selection_mode: Optional[str] = None,
        live_selection: Optional[list[dict[str, Any]]] = None,
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
        state.breakeven_suppressed_after_smart = False
        state.breakeven_rule_started_at = (
            current_time if config.get("breakeven_timeout_hours") else None
        )
        state.max_duration_rule_started_at = (
            current_time if config.get("max_trade_duration_hours") else None
        )
        carried_upnl = 0.0
        for _p in state.open_positions:
            _ref = _p.equity_ref_entry or _p.entry_price
            # P3: O(log N) mark lookup (was a linear prefix scan). Parity-exact.
            _mark = self._mark_index.mark_at_or_before(_p.symbol, current_time, _ref)
            carried_upnl += _cu(_ref, _mark, _p.qty, _p.side)
        locked_margin = sum(p.locked_margin for p in state.open_positions)
        available_balance = max(0.0, state.wallet_balance + carried_upnl - locked_margin)
        state.sizing_capital = available_balance
        state.cycle_start_equity = available_balance

        before = state.scan_entered
        if selection_mode == "live_selection":
            self._process_live_selection_signals(
                config, scan_signals, live_selection or [], klines, state, current_time
            )
        elif selection_mode == "post_scan_recheck":
            self._process_post_scan_recheck_signals(config, scan_signals, klines, state, current_time)
        elif execution_mode == "batch":
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
            for k in self._mark_index.candles_after_until(sym, start_time, end_time):
                kt = k["open_time"]
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
            # P3: O(log N) seed of each carried position's mark at/just-before the
            # window start (was a linear prefix scan from index 0). Parity-exact —
            # same candle close, so the equity-rule reference on the first timestamp
            # is byte-identical. This kills the O(positions × T) seeding (RC-2).
            latest_prices[p.symbol] = self._mark_index.mark_at_or_before(
                p.symbol, start_time, p.entry_price
            )
        candle_count = 0

        # Process timestamps chronologically — unified timeline
        for idx, candle_time in enumerate(sorted_timestamps):
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
                next_candle_time = (
                    sorted_timestamps[idx + 1]
                    if idx + 1 < len(sorted_timestamps)
                    else candle_time + timedelta(minutes=5)
                )
                smart_closed_at = state.smart_drawdown_closed_at
                suppress_breakeven = (
                    smart_closed_at is not None
                    and candle_time <= smart_closed_at < next_candle_time
                )
                breakeven_prices = dict(latest_prices)
                if config.get("breakeven_timeout_hours"):
                    for pos in state.open_positions:
                        candle = candles_at_time.get(pos.symbol)
                        if not candle:
                            continue
                        # Live BREAKEVEN_TIMEOUT evaluates the exchange wallet's
                        # totalPerpUPL, not last-trade candle closes. Without a
                        # historical mark-price stream, use the adverse side of the
                        # current bar as a conservative account-level mark so a brief
                        # favorable close cannot trigger a mass close live would not
                        # confirm.
                        breakeven_prices[pos.symbol] = (
                            candle["low"] if pos.side == "Buy" else candle["high"]
                        )
                self._evaluate_time_rules(
                    config,
                    state,
                    candle_time,
                    fee_rate,
                    latest_prices,
                    breakeven_prices=breakeven_prices,
                    suppress_breakeven=suppress_breakeven,
                )

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
            # Equity rules value uPnL off the simulated exchange avgPrice, matching
            # production wallet equity. Falls back to entry_price for legacy positions.
            ref = pos.equity_ref_entry or pos.entry_price
            upnl = compute_unrealized_pnl(ref, current_price, pos.qty, pos.side)
            total_upnl += upnl
            if upnl < 0:
                losing_positions.append(pos)

        equity = state.wallet_balance + total_upnl

        # --- EQUITY_DROP_PCT / EQUITY_DROP_PCT_SMART ---
        max_drawdown_pct = config.get("max_drawdown_pct", 100.0)
        if max_drawdown_pct < 100.0:
            smart_drawdown = bool(config.get("smart_drawdown_close"))
            adverse_price: dict[str, float] = {}
            intrabar_equity = equity
            if smart_drawdown:
                # Live SMART evaluates the sampled account mark/equity and closes
                # currently losing positions. It does not replay a completed 5m
                # candle's hidden high/low after the fact.
                drop_equity = equity
            else:
                # Non-SMART remains intrabar-aware: value every open position at its
                # adverse extreme THIS bar (short -> high, long -> low). A position
                # with no candle this timestamp keeps its latest-close mark.
                drawdown_upnl = 0.0
                for pos in state.open_positions:
                    candle = candles_at_time.get(pos.symbol)
                    if candle is not None:
                        # Entry-bar guard: a 1m-drilled position uses its POST-ENTRY
                        # 1m extreme on its own entry bar, so pre-fill price action
                        # cannot fabricate a drawdown close.
                        hi, lo = self._bar_extremes_for(pos, candle, candle_time)
                        extreme = hi if pos.side == "Sell" else lo
                    else:
                        extreme = latest_prices.get(pos.symbol, pos.entry_price)
                    adverse_price[pos.symbol] = extreme
                    drawdown_upnl += compute_unrealized_pnl(
                        pos.equity_ref_entry or pos.entry_price, extreme, pos.qty, pos.side
                    )
                intrabar_equity = state.wallet_balance + drawdown_upnl
                drop_equity = min(equity, intrabar_equity)

            def _exit_px(pos: "Position") -> float:
                # Non-SMART closes at the adverse extreme when the breach was
                # intrabar. SMART closes at the sampled latest mark/close.
                if not smart_drawdown and intrabar_equity < equity:
                    return adverse_price.get(pos.symbol, latest_prices.get(pos.symbol, pos.entry_price))
                return latest_prices.get(pos.symbol, pos.entry_price)

            if check_equity_drop(drop_equity, state.cycle_start_equity, max_drawdown_pct):
                if smart_drawdown:
                    # SMART is ONE-SHOT per scan window. Production closes the losing
                    # symbols once, transitions the rule to "executed", and does NOT
                    # re-arm or re-anchor it (close_rule_evaluator.py:314) — surviving
                    # winners get no further drawdown protection until the NEXT scan
                    # re-creates the rule. The old backtest re-anchored cycle_start_equity
                    # and stayed active, letting SMART re-fire on a winner that later
                    # turned losing within the same window — closing positions
                    # production would have held. Gate on the fired-flag for parity.
                    #
                    if state.smart_drawdown_fired:
                        pass  # already fired this scan window — production holds
                    elif losing_positions:
                        for pos in list(losing_positions):
                            self._close_position(state, pos, "equity_drop_smart", _exit_px(pos), candle_time, fee_rate)
                        state.smart_drawdown_closed_at = candle_time
                        state.breakeven_suppressed_after_smart = True
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
        breakeven_prices: Optional[dict[str, float]] = None,
        suppress_breakeven: bool = False,
    ) -> None:
        """Evaluate time-based close rules: BREAKEVEN_TIMEOUT, MAX_DURATION, and the
        per-position MR fast time-stop (F2).

        BREAKEVEN_TIMEOUT: account-level — closes ALL remaining positions once total
            open uPnL >= fee buffer, after the rule-created breakeven window.
        MAX_DURATION: account-level — force-closes all remaining positions after the
            rule-created duration window.
        MR time-stop: force-closes a mean_reversion position after its own
            time_stop_minutes (F2's strategy-critical fast exit), independent of the
            account-level MAX_DURATION.
        """
        from backend.services.trading_rules import compute_fee, compute_unrealized_pnl

        breakeven_hours = config.get("breakeven_timeout_hours")
        max_duration_hours = config.get("max_trade_duration_hours")
        # Any MR position carries its own time-stop, so we must run even when the
        # account-level time rules are unset.
        any_mr_timestop = any(p.time_stop_minutes for p in state.open_positions)

        if not breakeven_hours and not max_duration_hours and not any_mr_timestop:
            return

        latest_prices = latest_prices or {}
        breakeven_prices = breakeven_prices or latest_prices
        positions_to_close = []          # (pos, close_reason)

        for pos in list(state.open_positions):
            elapsed_hours = (candle_time - pos.entry_time).total_seconds() / 3600.0

            # MR fast time-stop (per-position): close after its own minutes elapse.
            if pos.time_stop_minutes and elapsed_hours * 60.0 >= pos.time_stop_minutes:
                positions_to_close.append((pos, "mr_time_stop"))

        # BREAKEVEN_TIMEOUT (account-level, mirrors live close_rule_evaluator): once the
        # cycle has aged past the breakeven window, close ALL remaining open positions
        # the moment total open unrealised PnL clears the fee buffer (Σ notional × fee
        # × 1.5), so the mass close nets ~flat. Positions already queued for MR/
        # MAX_DURATION close above are excluded. Empty remaining → do nothing (no
        # positions = cannot be at breakeven).
        account_free_schedule = (config.get("scan_source") or {}).get("mode") == "schedule"
        schedule_profit_round = (
            account_free_schedule
            and config.get("target_goal_type") == "profit_pct"
            and bool(config.get("target_goal_value"))
        )
        if (
            breakeven_hours
            and not schedule_profit_round
            and not suppress_breakeven
            and not state.breakeven_suppressed_after_smart
        ):
            already = {id(p) for p, _ in positions_to_close}
            remaining = [p for p in state.open_positions if id(p) not in already]
            started_at = state.breakeven_rule_started_at
            if remaining and started_at is not None:
                rule_elapsed = (candle_time - started_at).total_seconds() / 3600.0
                if rule_elapsed >= breakeven_hours:
                    total_upnl = 0.0
                    total_buffer = 0.0
                    for p in remaining:
                        mark = breakeven_prices.get(p.symbol, latest_prices.get(p.symbol, p.entry_price))
                        ref = p.equity_ref_entry or p.entry_price
                        total_upnl += compute_unrealized_pnl(ref, mark, p.qty, p.side)
                        total_buffer += compute_fee(p.qty, mark, fee_rate) * 1.5
                    if total_upnl >= total_buffer:
                        for p in remaining:
                            positions_to_close.append((p, "breakeven"))

        # MAX_DURATION is also an account-level production close rule. It is created
        # after BREAKEVEN_TIMEOUT, so breakeven gets first chance on a candle where
        # both elapsed clocks are true; if it did not close, duration closes the rest.
        if max_duration_hours:
            already = {id(p) for p, _ in positions_to_close}
            remaining = [p for p in state.open_positions if id(p) not in already]
            started_at = state.max_duration_rule_started_at
            if remaining and started_at is not None:
                rule_elapsed = (candle_time - started_at).total_seconds() / 3600.0
                if rule_elapsed >= max_duration_hours:
                    for p in remaining:
                        positions_to_close.append((p, "max_duration"))

        # Close time-stopped positions at the symbol's latest price. Guard against a
        # position already closed by an earlier rule this candle (defensive parity
        # with the TP/SL close loop — _close_position would raise on a double .remove()).
        for pos, reason in positions_to_close:
            if pos in state.open_positions:
                exit_price = latest_prices.get(pos.symbol, pos.entry_price)
                self._close_position(state, pos, reason, exit_price, candle_time, fee_rate)
