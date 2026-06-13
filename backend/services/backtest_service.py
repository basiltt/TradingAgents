"""Backtest Service — orchestrates backtest lifecycle.

Handles: create, run (background), cancel, list, get, delete, compare.
Delegates simulation to BacktestEngine (pure, synchronous) run in a bounded
ThreadPoolExecutor, and metric computation to backtest_metrics.

Concurrency model:
- An explicit _active_slots counter (reserved synchronously at create time)
  gates concurrent runs (503/BacktestBusyError when full) — avoids the TOCTOU
  race a Semaphore acquired later in the background task would leave open.
- A per-client sliding-window rate limit caps creates (429 when exceeded),
  recorded only on a successful create.
- Each run gets a threading.Event for cooperative cancellation + a Timer for
  the wall-clock timeout. The engine checks the event every 100 candles.
- Progress flows engine -> on_progress callback -> DB progress_pct (throttled).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    # AI-CONTEXT: Import for type-checkers/static analysis only. ScanContext is
    # imported lazily at runtime inside _build_scan_contexts() to avoid an
    # import cycle (scan_context -> services -> backtest_service); this block
    # lets the `dict[str, "ScanContext"]` return annotation resolve without
    # paying that cost or tripping F821 (undefined name) in linters.
    from backend.services.scan_context import ScanContext

logger = logging.getLogger(__name__)

# Hard limit on signals loaded — prevents OOM on large date ranges
_MAX_SIGNALS = 50_000
# Max candles a single backtest may span (≈ 1095 days / 3y × 288 5-min candles)
_MAX_CANDLES = 315_360
# Max TOTAL candle-rows held in memory at once (symbols × candles-per-symbol).
# Guards against OOM when a backtest touches many distinct symbols over a long
# range (the per-symbol _MAX_CANDLES cap alone doesn't bound the product).
_MAX_TOTAL_KLINES = 9_000_000
# Candles per day by simulation interval (24h)
_CANDLES_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6}
# Concurrency / timeout
_MAX_CONCURRENT = 3
_TIMEOUT_SECONDS = 120
# Target points for the equity curve served to the frontend (LTTB downsample)
_EQUITY_TARGET_POINTS = 2000
# Share of the progress bar reserved for the pre-simulation cache warm-up, so the bar
# advances during a slow fetch instead of freezing at 0%. The engine passes then fill
# the remaining [_WARMUP_BAND, 100].
_WARMUP_BAND = 10
# Per-client create rate limit: max creates in a sliding window
_RATE_LIMIT_MAX = 1000
_RATE_LIMIT_WINDOW_SECONDS = 3600

# Production processes auto-trade configs sequentially after a scan completes.
# Specific Schedule backtests cannot use account/trade references, so they estimate
# the wall-clock selector time from the copied scan config list position. The
# post-scan recheck runs after the batch/fill phases, so it uses the full list size
# plus the matched config index.
_SCHEDULE_BATCH_CONFIG_STEP_SECONDS = 20
_SCHEDULE_RECHECK_CONFIG_STEP_SECONDS = 15
_KLINE_EXPANSION_PASSES = 4

_AUTO_TRADE_CONFIG_MATCH_KEYS = (
    "leverage", "direction", "min_score", "max_trades", "capital_pct",
    "signal_sides", "stop_loss_pct", "execution_mode", "max_same_sector",
    "take_profit_pct", "max_drawdown_pct", "symbol_blacklist",
    "symbol_whitelist", "target_goal_type", "confidence_filter",
    "target_goal_value", "fill_to_max_trades", "max_same_direction",
    "close_on_profit_pct", "max_price_drift_pct", "trailing_profit_pct",
    "smart_drawdown_close", "max_signal_age_minutes", "skip_if_positions_open",
    "breakeven_timeout_hours", "max_trade_duration_hours",
    "adaptive_blacklist_enabled", "adaptive_blacklist_min_trades",
    "adaptive_blacklist_max_win_rate", "adaptive_blacklist_lookback_hours",
    "regime_filter_enabled", "session_filter_enabled",
    "session_allowed_hours_utc", "session_blocked_hours_utc",
    "btc_vol_filter_enabled", "btc_vol_interval", "btc_vol_lookback_candles",
    "btc_vol_min_threshold", "btc_vol_max_threshold", "strategy_cohort",
    "mean_reversion_enabled", "mr_short_enabled", "mr_long_enabled",
    "mr_max_trades", "mr_capital_pct", "mr_leverage", "mr_min_edge_pct",
    "mr_target_capture_pct", "mr_tight_stop_pct", "mr_extreme_min_abs_score",
    "mr_time_stop_minutes", "mr_mean_period", "mr_mean_interval", "mr_regime",
)

class BacktestValidationError(Exception):
    """Raised when a backtest request fails validation (maps to HTTP 422)."""


class BacktestConflictError(Exception):
    """Raised when an operation conflicts with run state (maps to HTTP 409)."""


class BacktestBusyError(Exception):
    """Raised when all concurrency slots are taken (maps to HTTP 503)."""


class BacktestNotFoundError(Exception):
    """Raised when a referenced run does not exist (maps to HTTP 404)."""


class BacktestRateLimitError(Exception):
    """Raised when the per-client create rate limit is exceeded (maps to HTTP 429)."""


class BacktestService:
    """Orchestration service for backtesting.

    Args:
        db: AsyncAnalysisDB instance with a `pool` attribute.
        kline_cache: Optional KlineCacheService for warming/reading kline data.
    """

    def __init__(self, db: Any, kline_cache: Any = None, instrument_cache: Any = None,
                 progress_manager: Any = None) -> None:
        self._db = db
        self._kline_cache = kline_cache
        # Per-symbol instrument parameters (qty_step/min_qty/tick_size/max_leverage)
        # used to make sizing/leverage/TP-SL rounding match the live exchange. Lazily
        # created if not injected; refreshed best-effort before each run.
        self._instrument_cache = instrument_cache
        # Optional BacktestProgressManager — when set, the run path emits structured
        # per-stage events (loading signals, warming cache, simulating, …) that the
        # /ws/v1/backtest/{run_id} endpoint streams to the UI for step-by-step
        # progress. None ⇒ the run still works (and still writes progress_pct), just
        # without the live step stream. Decoupled so tests + the MCP path need no WS.
        self._progress = progress_manager
        self._running_tasks: set[asyncio.Task] = set()
        # run_id -> threading.Event (cooperative cancel signal to the engine).
        # Registered synchronously at create time (before the background task is
        # scheduled) so a cancel that arrives in the launch gap is never lost.
        self._cancel_events: dict[str, threading.Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT,
                                             thread_name_prefix="backtest")
        # Explicit slot counter reserved synchronously in create_backtest. Under
        # single-threaded asyncio, the check-and-increment between awaits is
        # atomic, eliminating the TOCTOU race a Semaphore (acquired later, in the
        # background task) would leave open.
        self._active_slots = 0
        # Per-client sliding-window create timestamps (monotonic seconds).
        self._create_history: dict[str, list[float]] = {}

    async def shutdown(self) -> None:
        """Graceful shutdown — signal cancel, cancel tasks, stop the executor."""
        for ev in self._cancel_events.values():
            ev.set()
        for task in list(self._running_tasks):
            task.cancel()
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        self._running_tasks.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("backtest_service_shutdown")

    def has_free_slot(self) -> bool:
        """True if a concurrency slot is available (no 503 needed)."""
        return self._active_slots < _MAX_CONCURRENT

    def _reserve_create_token(self, client_id: str) -> float:
        """Atomically check the per-client sliding-window create limit AND consume a
        token, returning the timestamp recorded so it can be refunded if the create
        later fails.

        This MUST run synchronously (no await between the check and the append) so two
        concurrent creates from the same client can't both pass a stale check and
        over-admit past _RATE_LIMIT_MAX. Failed creates call _refund_create_token() to
        avoid burning the budget on 422/503/DB errors — so only successful creates
        count against the window, while the race is closed.

        Raises:
            BacktestRateLimitError: If the client is already at the limit (HTTP 429).
        """
        now = time.monotonic()
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        history = [t for t in self._create_history.get(client_id, []) if t > cutoff]
        if len(history) >= _RATE_LIMIT_MAX:
            raise BacktestRateLimitError(
                f"Rate limit exceeded: max {_RATE_LIMIT_MAX} backtests per hour."
            )
        history.append(now)
        self._create_history[client_id] = history
        # Opportunistic cleanup so the dict can't grow unbounded across clients.
        if len(self._create_history) > 1000:
            self._create_history = {
                k: [t for t in v if t > cutoff]
                for k, v in self._create_history.items()
                if any(t > cutoff for t in v)
            }
        return now

    def _refund_create_token(self, client_id: str, token: float) -> None:
        """Refund a reserved create token when the create fails before launch, so a
        rejected attempt (422/503/DB error) doesn't count against the client."""
        hist = self._create_history.get(client_id)
        if not hist:
            return
        try:
            hist.remove(token)
        except ValueError:
            # Already evicted by window cleanup — nothing to refund.
            pass


    # ------------------------------------------------------------------ #
    # Validation helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _estimate_candles(config: dict[str, Any]) -> int:
        """Estimate total candles a backtest would span (per-symbol basis)."""
        start = config["date_range_start"]
        end = config["date_range_end"]
        days = max((end - start).total_seconds() / 86400.0, 0)
        per_day = _CANDLES_PER_DAY.get(config.get("simulation_interval", "5m"), 288)
        return int(days * per_day)

    # ------------------------------------------------------------------ #
    # CRUD + lifecycle
    # ------------------------------------------------------------------ #

    async def create_backtest(self, config: dict[str, Any], client_id: str = "anonymous") -> str:
        """Insert a new backtest run (status=pending) and launch it in the background.

        Args:
            config: Validated backtest config dict (BacktestCreateRequest.model_dump()).
            client_id: Identifier for per-client rate limiting (e.g. request IP).

        Returns:
            The new run_id (UUID string).

        Raises:
            BacktestRateLimitError: If the client exceeded the create rate limit.
            BacktestValidationError: If the candle estimate exceeds the cap.
            BacktestBusyError: If all concurrency slots are taken.
        """
        # Validate the (cheap, stateless) candle estimate FIRST so an oversized config
        # is rejected with 422 without consuming a rate-limit token or a slot.
        candles = self._estimate_candles(config)
        if candles > _MAX_CANDLES:
            raise BacktestValidationError(
                f"Date range too large: ~{candles} candles exceeds the {_MAX_CANDLES} limit. "
                f"Reduce the range or use a coarser interval."
            )

        # Reserve a rate-limit token AND a concurrency slot SYNCHRONOUSLY, before the
        # first await — both must be atomic under single-threaded asyncio so that
        # concurrent creates from one client can't both pass a stale check and
        # over-admit. The token is refunded on any failure before launch so rejected
        # attempts (422 above is already past; DB errors / busy below) don't burn the
        # client's budget.
        rate_token = self._reserve_create_token(client_id)
        if self._active_slots >= _MAX_CONCURRENT:
            # Refund the just-reserved token — this attempt is rejected, not consumed.
            self._refund_create_token(client_id, rate_token)
            raise BacktestBusyError("All backtest slots are busy — try again shortly.")
        self._active_slots += 1
        launched = False  # True once the background task owns the slot
        try:
            scan_source = config.get("scan_source", {})
            row = await self._db.pool.fetchrow(
                """
                INSERT INTO backtest_runs (status, config, scan_source, progress_pct)
                VALUES ('pending', $1, $2, 0)
                RETURNING id
                """,
                json.dumps(config, default=str),
                json.dumps(scan_source, default=str),
            )
            run_id = str(row["id"])
            # Register the cancel event NOW (before scheduling the task) so a cancel
            # arriving during the launch gap is delivered to the engine, not lost.
            self._cancel_events[run_id] = threading.Event()
            await self._launch_background(run_id, config)
            # The task now owns the slot — its finally will release it, so create's
            # except must NOT release again (would double-decrement, over-subscribing).
            launched = True
            logger.info("backtest_created", extra={"run_id": run_id, "candles_est": candles})
            return run_id
        except Exception:
            # Release the slot ONLY if the background task never took ownership.
            # Once launched, the task's finally is responsible for the release —
            # decrementing here too would double-release and over-subscribe.
            if not launched:
                self._active_slots = max(0, self._active_slots - 1)
                # The create failed before launch — refund the rate-limit token so a
                # DB/launch error doesn't count against the client.
                self._refund_create_token(client_id, rate_token)
            raise

    async def get_backtest(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch a run with its results (equity curve LTTB-downsampled for the UI)."""
        run = await self._db.pool.fetchrow(
            """
            SELECT id, status, config, scan_source, progress_pct, error_message,
                   started_at, completed_at, created_at
            FROM backtest_runs WHERE id = $1
            """,
            run_id,
        )
        if run is None:
            return None

        result = self._row_to_run(run)

        results_row = await self._db.pool.fetchrow(
            "SELECT metrics, equity_curve, summary, warnings FROM backtest_results WHERE run_id = $1",
            run_id,
        )
        result["results"] = self._build_results(results_row) if results_row is not None else None
        return result

    async def list_backtests(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """List runs (newest first), optionally filtered by status."""
        status = filters.get("status")
        limit = int(filters.get("limit", 100))
        if status:
            rows = await self._db.pool.fetch(
                """
                SELECT id, status, config, scan_source, progress_pct, error_message,
                       started_at, completed_at, created_at
                FROM backtest_runs WHERE status = $1
                ORDER BY created_at DESC LIMIT $2
                """,
                status, limit,
            )
        else:
            rows = await self._db.pool.fetch(
                """
                SELECT id, status, config, scan_source, progress_pct, error_message,
                       started_at, completed_at, created_at
                FROM backtest_runs
                ORDER BY created_at DESC LIMIT $1
                """,
                limit,
            )
        return [self._row_to_run(r) for r in rows]

    async def cancel_backtest(self, run_id: str) -> bool:
        """Signal a pending/running backtest to cancel.

        Returns:
            False if the run doesn't exist.

        Raises:
            BacktestConflictError: If the run is already in a terminal state
            (completed/failed/cancelled) — nothing to cancel (maps to HTTP 409).
        """
        run = await self._db.pool.fetchrow(
            "SELECT status FROM backtest_runs WHERE id = $1", run_id
        )
        if run is None:
            return False
        if run["status"] not in ("pending", "running"):
            raise BacktestConflictError(
                f"Cannot cancel a backtest with status '{run['status']}'."
            )
        ev = self._cancel_events.get(run_id)
        if ev is not None:
            ev.set()
        # Mark cancelled eagerly (the background task will also transition). Guard
        # against the completion-wins race: if results already exist, the run
        # finished between our status SELECT and here, so DON'T flip it to
        # cancelled (that would contradict the atomic "results ⟺ completed"
        # invariant and could leave the UI showing 'cancelled' for a completed run).
        await self._db.pool.execute(
            "UPDATE backtest_runs SET status = 'cancelled', completed_at = now() "
            "WHERE id = $1 AND status IN ('pending','running') "
            "AND NOT EXISTS (SELECT 1 FROM backtest_results WHERE run_id = $1)",
            run_id,
        )
        return True

    async def delete_backtest(self, run_id: str) -> bool:
        """Delete a run (cascades to results+trades). Rejects running/pending runs."""
        run = await self._db.pool.fetchrow(
            "SELECT status FROM backtest_runs WHERE id = $1", run_id
        )
        if run is None:
            return False
        if run["status"] in ("running", "pending"):
            raise BacktestConflictError(
                f"Cannot delete a backtest with status '{run['status']}' — cancel it first."
            )
        await self._db.pool.execute("DELETE FROM backtest_runs WHERE id = $1", run_id)
        return True

    async def delete_all_backtests(self) -> int:
        """Delete ALL terminal backtest runs (completed/failed/cancelled), cascading
        to their results+trades. Running/pending runs are LEFT INTACT so an in-flight
        backtest is never yanked out from under its executor — the user must cancel
        those first. Returns the number of runs deleted.

        One statement, transactionally atomic on the DB side. The WHERE clause is the
        safety boundary: a status NOT IN the active set is terminal and safe to drop.
        """
        result = await self._db.pool.execute(
            "DELETE FROM backtest_runs WHERE status NOT IN ('running', 'pending')"
        )
        # asyncpg returns e.g. "DELETE 17" — parse the affected-row count defensively.
        try:
            return int(str(result).split()[-1])
        except (ValueError, IndexError):
            return 0

    async def compare_backtests(self, run_ids: list[str]) -> dict[str, Any]:
        """Compare 2-4 completed runs side by side.

        Raises:
            BacktestValidationError: If count is outside 2-4 or any run is not completed.
        """
        if not (2 <= len(run_ids) <= 4):
            raise BacktestValidationError("Comparison requires between 2 and 4 run IDs.")

        rows = await self._db.pool.fetch(
            """
            SELECT r.id, r.status, r.config, r.scan_source, r.progress_pct,
                   r.error_message, r.started_at, r.completed_at, r.created_at,
                   res.metrics, res.equity_curve, res.summary, res.warnings
            FROM backtest_runs r
            LEFT JOIN backtest_results res ON res.run_id = r.id
            WHERE r.id = ANY($1)
            """,
            run_ids,
        )
        found = {str(r["id"]): r for r in rows}
        missing = [rid for rid in run_ids if rid not in found]
        if missing:
            raise BacktestNotFoundError(f"Run(s) not found: {', '.join(missing)}")

        runs = []
        for rid in run_ids:
            r = found[rid]
            if r["status"] != "completed":
                raise BacktestValidationError(
                    f"Run {rid} is '{r['status']}' — only completed runs can be compared."
                )
            run = self._row_to_run(r)
            run["results"] = self._build_results(r)
            runs.append(run)
        return {"runs": runs}

    async def cache_status(
        self, symbols: list[str], interval: str, start: datetime, end: datetime
    ) -> dict[str, Any]:
        """Report kline-cache coverage for the requested symbols/range.

        Returns:
            {symbols_total, symbols_cached, symbols_with_gaps: [...], ready: bool}.
            ready is True when every symbol has full coverage (no warm-up needed).
        """
        if self._kline_cache is None:
            return {
                "symbols_total": len(symbols), "symbols_cached": 0,
                "symbols_with_gaps": list(symbols), "ready": False,
            }
        gaps = await self._kline_cache.get_coverage_gaps(symbols, interval, start, end)
        with_gaps = list(gaps.keys())
        return {
            "symbols_total": len(symbols),
            "symbols_cached": len(symbols) - len(with_gaps),
            "symbols_with_gaps": with_gaps,
            "ready": len(with_gaps) == 0,
        }

    async def warmup_cache(
        self, symbols: list[str], interval: str, start: datetime, end: datetime
    ) -> dict[str, Any]:
        """Ensure kline coverage for the requested symbols/range (fetch missing).

        Delegates to KlineCacheService.ensure_coverage, which fills gaps from the
        exchange. Returns the coverage stats (cached/fetched/failed/gaps).

        Bounds the request the same way create does (date range ≤ 365 days, total
        symbols × candles ≤ _MAX_TOTAL_KLINES) so a single warmup can't trigger an
        unbounded exchange-fetch storm.

        Raises:
            BacktestValidationError: cache unavailable, bad range, or too-large fetch.
        """
        if self._kline_cache is None:
            raise BacktestValidationError("Kline cache is not available.")
        if end <= start:
            raise BacktestValidationError("end must be after start.")
        days = (end - start).total_seconds() / 86400.0
        if days > 365:
            raise BacktestValidationError(f"Date range cannot exceed 365 days (got {days:.0f}).")
        per_day = _CANDLES_PER_DAY.get(interval, 288)
        total = int(len(symbols) * days * per_day)
        if total > _MAX_TOTAL_KLINES:
            raise BacktestValidationError(
                f"Warmup too large: ~{total} candles across {len(symbols)} symbols "
                f"exceeds the {_MAX_TOTAL_KLINES} limit. Narrow the range or symbols."
            )
        return await self._kline_cache.ensure_coverage(symbols, interval, start, end)

    # ------------------------------------------------------------------ #
    # Serialization helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _coerce_json(value: Any) -> Any:
        """asyncpg may return JSONB as a str or already-parsed object."""
        if isinstance(value, (str, bytes)):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return None
        return value

    def _row_to_run(self, row: Any) -> dict[str, Any]:
        """Map a backtest_runs DB row to a response dict."""
        return {
            "id": str(row["id"]),
            "status": row["status"],
            "config": self._coerce_json(row["config"]) or {},
            "scan_source": self._coerce_json(row["scan_source"]) or {},
            "progress_pct": row["progress_pct"],
            "error_message": row["error_message"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
        }

    def _build_results(self, row: Any) -> dict[str, Any]:
        """Build the results sub-dict from a row carrying metrics/equity/summary/warnings.

        Shared by get_backtest and compare_backtests. The equity curve is
        LTTB-downsampled for the UI; JSONB columns are coerced from str/object.
        """
        equity = self._coerce_json(row["equity_curve"]) or []
        summary_obj = self._coerce_json(row["summary"]) or {}
        return {
            "metrics": self._coerce_json(row["metrics"]) or {},
            "equity_curve": self._downsample_equity(equity),
            "summary": summary_obj,
            # Present only for replay-mode runs (nested in summary); None otherwise.
            "replay_comparison": summary_obj.get("replay_comparison"),
            "warnings": self._coerce_json(row["warnings"]) or [],
        }

    @staticmethod
    def _downsample_equity(equity: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """LTTB-downsample the equity curve to a UI-friendly point count.

        The curve uses {ts, equity, ...} dicts; lttb_downsample wants {x, y}.
        We map index->x and equity->y, then restore the original dicts.

        The max-drawdown point (the point whose per-point drawdown_pct is the most
        negative) is force-included so the chart's visible trough always matches the
        max_dd_pct metric tile — LTTB otherwise picks largest-triangle points and can
        drop a sharp, narrow trough, making the chart understate the drawdown the tile
        reports. NOTE: this must key on drawdown_pct, NOT min equity — max_dd_pct is a
        peak-to-trough percentage, so on a curve whose peak rises after an early
        absolute low the deepest %-drawdown point differs from the lowest-equity point.
        """
        if len(equity) <= _EQUITY_TARGET_POINTS:
            return equity
        from backend.services.trading_rules import lttb_downsample
        indexed = [{"x": i, "y": (p.get("equity") or 0.0), "_orig": p}
                   for i, p in enumerate(equity)]
        sampled = lttb_downsample(indexed, _EQUITY_TARGET_POINTS)
        sampled_indices = {s["x"] for s in sampled}

        # Force-include the MAX-DRAWDOWN index (most-negative per-point drawdown_pct,
        # which is exactly the point max_dd_pct reports) if LTTB dropped it, then
        # re-sort by original index to keep the curve ordered. The engine stamps a
        # real drawdown_pct on every point; default to 0.0 only if a point lacks it.
        trough_idx = min(range(len(equity)), key=lambda i: equity[i].get("drawdown_pct") or 0.0)
        if trough_idx not in sampled_indices:
            sampled.append(indexed[trough_idx])
            sampled.sort(key=lambda s: s["x"])
        return [s["_orig"] for s in sampled]

    @staticmethod
    def _to_symbol(ticker: str) -> str:
        return ticker if ticker.endswith("USDT") else f"{ticker}USDT"

    async def _prepare_live_selection_context(
        self,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        """Preload the non-price selector inputs live auto-trading has at scan time."""
        scan_source = config.get("scan_source") or {}
        mode = scan_source.get("mode")

        # Schedule backtests are the local optimization path: they run from copied
        # scheduled scan rows and the submitted backtest config only. Do not infer
        # production accounts, persisted account snapshots, or exact live trade
        # references here; local strategy tuning must remain account-free and able
        # to vary selector knobs such as max_trades/TP/SL independently.
        if mode == "schedule":
            if config.get("max_same_sector") is not None:
                config["_sector_map"] = await self._load_sector_map(signals)
            if config.get("adaptive_blacklist_enabled"):
                config["_adaptive_blacklist_history"] = await self._load_adaptive_blacklist_history(
                    config, date_range
                )
            return

        # Replay is the explicit account-ground-truth validation mode. It can pin
        # exact live selections because the caller intentionally supplied an account.
        account_id = None
        if mode == "replay":
            account_id = scan_source.get("replay_account_id") or config.get("replay_account_id")
        elif config.get("account_id") or config.get("replay_account_id"):
            account_id = await self._resolve_live_replay_account_id(config)

        if account_id:
            account_id = str(account_id)
            config["_live_replay_account_id"] = account_id
            config["_selection_time_by_scan"] = await self._load_live_selection_times(
                account_id, date_range
            )
            config["_live_selection_by_scan"] = await self._load_live_selection_by_scan(
                account_id, date_range
            )
        if config.get("max_same_sector") is not None:
            config["_sector_map"] = await self._load_sector_map(signals)
        if config.get("adaptive_blacklist_enabled"):
            config["_adaptive_blacklist_history"] = await self._load_adaptive_blacklist_history(
                config, date_range
            )

    @staticmethod
    def _config_values_match(a: Any, b: Any) -> bool:
        if isinstance(a, list) or isinstance(b, list):
            return list(a or []) == list(b or [])
        if isinstance(a, bool) or isinstance(b, bool):
            return bool(a) == bool(b)
        if a is None or b is None:
            return a is None and b is None
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return str(a) == str(b)

    @classmethod
    def _config_key_values_match(cls, key: str, a: Any, b: Any) -> bool:
        if key == "strategy_cohort":
            a = a or "trend"
            b = b or "trend"
        return cls._config_values_match(a, b)

    @staticmethod
    def _coerce_scan_config(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _auto_trade_config_matches(self, submitted: dict[str, Any], candidate: Any) -> bool:
        """True when a scan snapshot contains the submitted selector config.

        Account identity is deliberately ignored: Specific Schedule must stay
        account-free. Missing candidate keys are tolerated for old snapshots so newly
        added default fields do not make historical config snapshots unusable.
        """
        if not isinstance(candidate, dict):
            return False
        checked = 0
        for key in _AUTO_TRADE_CONFIG_MATCH_KEYS:
            if key not in submitted or key not in candidate:
                continue
            checked += 1
            if not self._config_key_values_match(key, submitted.get(key), candidate.get(key)):
                return False
        return checked > 0

    def _matching_auto_trade_config_indices(
        self,
        submitted: dict[str, Any],
        candidates: list[Any],
    ) -> list[int]:
        return [
            idx for idx, candidate in enumerate(candidates)
            if self._auto_trade_config_matches(submitted, candidate)
        ]

    @staticmethod
    def _offset_time(value: Any, seconds: int) -> Optional[datetime]:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value + timedelta(seconds=seconds)

    async def _resolve_schedule_config_scan_filter(
        self,
        config: dict[str, Any],
        date_range: tuple[datetime, datetime],
    ) -> Optional[dict[str, Any]]:
        """Account-free scan eligibility from copied scan-time config snapshots.

        When the submitted config appears in scan.config.auto_trade_configs, the
        backtest should only let those scan rounds seed selector/position state. This
        prevents a config that became active mid-window from inheriting positions from
        older scans that live never ran for that config. If no snapshot matches (the
        user is researching hypothetical numbers), return None and preserve the
        existing full-window behavior.
        """
        scan_source = config.get("scan_source") or {}
        if scan_source.get("mode") != "schedule" or not scan_source.get("schedule_id"):
            return None

        start, end = date_range
        try:
            rows = await self._db.pool.fetch(
                """
                SELECT s.scan_id,
                       s.started_at::timestamptz AS started_at,
                       s.completed_at::timestamptz AS completed_at,
                       s.config,
                       s.auto_trade_results,
                       se.status AS schedule_execution_status,
                       NULLIF(se.completed_at, '')::timestamptz AS schedule_execution_completed_at
                FROM scans s
                LEFT JOIN LATERAL (
                    SELECT status, completed_at, id
                    FROM schedule_executions
                    WHERE schedule_id = s.schedule_id
                      AND scan_id = s.scan_id
                    ORDER BY
                        CASE WHEN status = 'completed' THEN 0 ELSE 1 END,
                        NULLIF(completed_at, '')::timestamptz DESC NULLS LAST,
                        id DESC
                    LIMIT 1
                ) se ON TRUE
                WHERE s.schedule_id = $1
                  AND s.started_at::timestamptz >= $2
                  AND s.started_at::timestamptz <= $3
                ORDER BY s.started_at::timestamptz
                """,
                scan_source.get("schedule_id"),
                start,
                end,
            )
        except Exception:
            logger.warning("backtest_schedule_config_filter_load_failed", exc_info=True)
            return None

        if not rows:
            return None

        matching: set[str] = set()
        uninspectable_after_first: set[str] = set()
        first_match_started_at: Optional[datetime] = None
        inspectable_count = 0
        matched_config_indices: dict[str, int] = {}
        selection_time_by_scan: dict[str, datetime] = {}
        post_recheck_time_by_scan: dict[str, datetime] = {}

        for row in rows:
            scan_id = str(row.get("scan_id") or "")
            if not scan_id:
                continue
            scan_config = self._coerce_scan_config(row.get("config"))
            candidates = scan_config.get("auto_trade_configs") if scan_config else None
            if not isinstance(candidates, list) or not candidates:
                if first_match_started_at is not None:
                    uninspectable_after_first.add(scan_id)
                continue
            # schedule_executions.status is advisory only for historical schedule
            # backtests. Production can mark a schedule execution failed after scanner
            # trades were already placed, and older copied rows can have empty
            # auto_trade_results even when live trades exist. If the scan completed and
            # the config snapshot matches, keep the scan eligible and let the selector
            # reproduce the trade attempt from scan data.
            inspectable_count += 1
            match_indices = self._matching_auto_trade_config_indices(config, candidates)
            if match_indices:
                match_index = match_indices[0]
                matching.add(scan_id)
                matched_config_indices[scan_id] = match_index
                completed_at = row.get("completed_at")
                selection_time = self._offset_time(
                    completed_at,
                    (match_index + 1) * _SCHEDULE_BATCH_CONFIG_STEP_SECONDS,
                )
                post_recheck_time = self._offset_time(
                    completed_at,
                    (len(candidates) + match_index + 1) * _SCHEDULE_RECHECK_CONFIG_STEP_SECONDS,
                )
                schedule_execution_completed_at = row.get("schedule_execution_completed_at")
                if (
                    row.get("schedule_execution_status") == "completed"
                    and isinstance(schedule_execution_completed_at, datetime)
                    and isinstance(completed_at, datetime)
                    and schedule_execution_completed_at >= completed_at
                ):
                    # schedule_executions.completed_at is written after live has run
                    # batch/fill/post_scan_recheck for the schedule. For account-free
                    # Specific Schedule rechecks, anchor from that copied end-time and
                    # walk backwards by the submitted config's position. This keeps the
                    # local recheck clock close to live without copying account/trade
                    # references.
                    remaining_configs = max(1, len(candidates) - match_index)
                    execution_recheck_time = schedule_execution_completed_at - timedelta(
                        seconds=remaining_configs * _SCHEDULE_BATCH_CONFIG_STEP_SECONDS
                    )
                    if execution_recheck_time >= completed_at:
                        post_recheck_time = execution_recheck_time
                if selection_time is not None:
                    selection_time_by_scan[scan_id] = selection_time
                if post_recheck_time is not None:
                    post_recheck_time_by_scan[scan_id] = post_recheck_time
                started_at = row.get("started_at")
                if (
                    isinstance(started_at, datetime)
                    and (first_match_started_at is None or started_at < first_match_started_at)
                ):
                    first_match_started_at = started_at

        if not matching:
            return None

        eligible = set(matching)
        eligible.update(uninspectable_after_first)
        return {
            "eligible_scan_ids": eligible,
            "matched_scan_count": len(matching),
            "eligible_scan_count": len(eligible),
            "total_scan_count": len(rows),
            "inspectable_scan_count": inspectable_count,
            "first_match_started_at": first_match_started_at,
            "matched_config_indices": matched_config_indices,
            "selection_time_by_scan": selection_time_by_scan,
            "post_recheck_time_by_scan": post_recheck_time_by_scan,
        }

    async def _resolve_live_replay_account_id(self, config: dict[str, Any]) -> str | None:
        """Resolve the account whose live execution clock should be replayed.

        Prefer an explicit replay/account id. For schedule-sourced backtests created
        from an account config, older run records do not store account_id; infer it
        by matching the run config against the schedule's auto_trade_configs.
        """
        scan_source = config.get("scan_source") or {}
        explicit = (
            scan_source.get("replay_account_id")
            or config.get("replay_account_id")
            or config.get("account_id")
        )
        if explicit:
            return str(explicit)

        if scan_source.get("mode") != "schedule" or not scan_source.get("schedule_id"):
            return None

        try:
            row = await self._db.pool.fetchrow(
                "SELECT scan_config FROM scheduled_scans WHERE id = $1",
                scan_source.get("schedule_id"),
            )
        except Exception:
            logger.warning("backtest_replay_account_infer_failed", exc_info=True)
            return None
        if not row:
            return None

        scan_config = row["scan_config"]
        if isinstance(scan_config, str):
            import json as _json
            try:
                scan_config = _json.loads(scan_config)
            except Exception:
                return None
        candidates = (scan_config or {}).get("auto_trade_configs") or []
        matches: list[str] = []
        for candidate in candidates:
            if not candidate.get("account_id"):
                continue
            if all(
                key not in config
                or key not in candidate
                or self._config_key_values_match(key, config.get(key), candidate.get(key))
                for key in _AUTO_TRADE_CONFIG_MATCH_KEYS
            ):
                matches.append(str(candidate["account_id"]))
        return matches[0] if len(matches) == 1 else None

    async def _load_live_selection_times(
        self,
        account_id: str,
        date_range: tuple[datetime, datetime],
    ) -> dict[str, datetime]:
        start, end = date_range
        try:
            rows = await self._db.pool.fetch(
                """
                WITH trace_times AS (
                    SELECT dr.scan_id,
                           MIN(dat.created_at)::timestamptz AS trace_time
                    FROM debug_account_traces dat
                    JOIN debug_runs dr ON dr.id = dat.run_id
                    WHERE dat.account_id = $1
                      AND dr.scan_started_at >= $2
                      AND dr.scan_started_at <= $3
                    GROUP BY dr.scan_id
                ),
                trade_times AS (
                    SELECT s.scan_id,
                           MIN(COALESCE(t.opened_at, t.created_at))::timestamptz AS trade_time
                    FROM trades t
                    JOIN scan_results sr ON sr.id = t.scan_result_id
                    JOIN scans s ON s.scan_id = sr.scan_id
                    WHERE t.account_id = $1
                      AND COALESCE(t.source, 'scanner') = 'scanner'
                      AND COALESCE(t.ai_closed, false) = false
                      AND s.started_at::timestamptz >= $2
                      AND s.started_at::timestamptz <= $3
                    GROUP BY s.scan_id
                )
                SELECT COALESCE(tt.scan_id, tr.scan_id) AS scan_id,
                       COALESCE(tr.trade_time, tt.trace_time)::timestamptz AS selection_time
                FROM trace_times tt
                FULL OUTER JOIN trade_times tr ON tr.scan_id = tt.scan_id
                """,
                account_id,
                start,
                end,
            )
        except Exception:
            logger.warning("backtest_live_selection_times_load_failed", exc_info=True)
            try:
                rows = await self._db.pool.fetch(
                    """
                    SELECT s.scan_id,
                           MIN(COALESCE(t.opened_at, t.created_at))::timestamptz AS selection_time
                    FROM trades t
                    JOIN scan_results sr ON sr.id = t.scan_result_id
                    JOIN scans s ON s.scan_id = sr.scan_id
                    WHERE t.account_id = $1
                      AND COALESCE(t.source, 'scanner') = 'scanner'
                      AND COALESCE(t.ai_closed, false) = false
                      AND s.started_at::timestamptz >= $2
                      AND s.started_at::timestamptz <= $3
                    GROUP BY s.scan_id
                    """,
                    account_id,
                    start,
                    end,
                )
            except Exception:
                logger.warning("backtest_live_trade_selection_times_load_failed", exc_info=True)
                return {}
        return {
            str(row["scan_id"]): row["selection_time"]
            for row in rows
            if row.get("scan_id") and row.get("selection_time")
        }

    async def _load_live_selection_by_scan(
        self,
        account_id: str,
        date_range: tuple[datetime, datetime],
    ) -> dict[str, list[dict[str, Any]]]:
        """Load the exact symbols live selected for an account per scan.

        Debug traces identify scans where the account ran but selected nothing; trade
        rows identify the symbols live actually placed. This keeps schedule-mode
        backtests pinned to the same trade membership as live when a historical
        account can be resolved, while generic backtests still use the pure selector.
        """
        start, end = date_range
        selected: dict[str, list[dict[str, Any]]] = {}
        try:
            trace_rows = await self._db.pool.fetch(
                """
                SELECT DISTINCT dr.scan_id
                FROM debug_account_traces dat
                JOIN debug_runs dr ON dr.id = dat.run_id
                JOIN scans s ON s.scan_id = dr.scan_id
                WHERE dat.account_id = $1
                  AND s.started_at::timestamptz >= $2
                  AND s.started_at::timestamptz <= $3
                """,
                account_id,
                start,
                end,
            )
            for row in trace_rows:
                if row.get("scan_id"):
                    selected.setdefault(str(row["scan_id"]), [])
        except Exception:
            logger.warning("backtest_live_selection_trace_load_failed", exc_info=True)

        try:
            trade_rows = await self._db.pool.fetch(
                """
                SELECT s.scan_id,
                       t.symbol,
                       t.side,
                       COALESCE(t.opened_at, t.created_at)::timestamptz AS opened_at
                FROM trades t
                JOIN scan_results sr ON sr.id = t.scan_result_id
                JOIN scans s ON s.scan_id = sr.scan_id
                WHERE t.account_id = $1
                  AND COALESCE(t.source, 'scanner') = 'scanner'
                  AND COALESCE(t.ai_closed, false) = false
                  AND s.started_at::timestamptz >= $2
                  AND s.started_at::timestamptz <= $3
                ORDER BY s.scan_id, COALESCE(t.opened_at, t.created_at), t.id
                """,
                account_id,
                start,
                end,
            )
        except Exception:
            logger.warning("backtest_live_selection_trades_load_failed", exc_info=True)
            return selected

        for row in trade_rows:
            scan_id = row.get("scan_id")
            symbol = row.get("symbol")
            if not scan_id or not symbol:
                continue
            selected.setdefault(str(scan_id), []).append({
                "symbol": str(symbol),
                "side": row.get("side"),
                "opened_at": row.get("opened_at"),
            })
        return selected

    async def _load_sector_map(self, signals: list[dict[str, Any]]) -> dict[str, str]:
        symbols = sorted({self._to_symbol(s.get("ticker", "")) for s in signals if s.get("ticker")})
        if not symbols:
            return {}

        sector_map: dict[str, str] = {}
        try:
            rows = await self._db.pool.fetch(
                "SELECT symbol, sector FROM symbol_sectors WHERE symbol = ANY($1)",
                symbols,
            )
            for row in rows:
                record = dict(row)
                if record.get("symbol") and record.get("sector"):
                    sector_map[record["symbol"]] = record["sector"]
        except Exception:
            logger.warning("backtest_sector_map_load_failed", exc_info=True)

        from backend.services.sector_map import _SECTOR_MAP
        for symbol in symbols:
            if symbol in _SECTOR_MAP:
                sector_map.setdefault(symbol, _SECTOR_MAP[symbol])
        return sector_map

    async def _load_adaptive_blacklist_history(
        self,
        config: dict[str, Any],
        date_range: tuple[datetime, datetime],
    ) -> list[dict[str, Any]]:
        """Load DB history so adaptive blacklist can be computed per scan time."""
        lookback_hours = config.get("adaptive_blacklist_lookback_hours", 48)
        start, end = date_range
        history_start = start - timedelta(hours=lookback_hours)
        is_schedule = (config.get("scan_source") or {}).get("mode") == "schedule"
        try:
            rows = await self._db.pool.fetch(
                "SELECT symbol, is_win, closed_at::timestamptz AS closed_at, "
                "strategy_kind "
                "FROM backtest_adaptive_blacklist_history "
                "WHERE closed_at::timestamptz > $1 "
                "AND closed_at::timestamptz <= $2 "
                "AND strategy_kind = ANY($3)",
                history_start,
                end,
                ["trend", "mean_reversion"],
            )
            if rows and "is_win" not in dict(rows[0]):
                rows = []
            if rows or is_schedule:
                return [
                    {
                        "symbol": row["symbol"],
                        "is_win": bool(row["is_win"]),
                        "closed_at": row["closed_at"],
                        "strategy_kind": row.get("strategy_kind") or "trend",
                    }
                    for row in rows
                ]
        except Exception:
            # Older local DBs may not have the sanitized copy table yet. Fall back to
            # the legacy live tables when present. Schedule mode deliberately does
            # not use those account/trade tables; it must remain portable to local
            # scan-only copies.
            logger.debug("backtest_adaptive_blacklist_copy_history_unavailable", exc_info=True)
            if is_schedule:
                return []

        try:
            rows = await self._db.pool.fetch(
                "SELECT sp.symbol AS symbol, sp.is_win AS is_win, "
                "sp.closed_at::timestamptz AS closed_at, t.strategy_kind AS strategy_kind "
                "FROM signal_performance sp "
                "JOIN trades t ON t.id = sp.trade_id "
                "WHERE sp.closed_at::timestamptz > $1 "
                "AND sp.closed_at::timestamptz <= $2 "
                "AND t.strategy_kind = ANY($3)",
                history_start,
                end,
                ["trend", "mean_reversion"],
            )
            history = []
            for row in rows:
                record = dict(row)
                history.append({
                    "symbol": record["symbol"],
                    "is_win": bool(record["is_win"]),
                    "closed_at": record["closed_at"],
                    "strategy_kind": record.get("strategy_kind") or "trend",
                })
            return history
        except Exception:
            logger.warning("backtest_adaptive_blacklist_history_load_failed", exc_info=True)
            return []

    @staticmethod
    def _parse_candidate_time(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    @staticmethod
    def _candidate_confidence_ok(confidence: Any, required_filter: Any) -> bool:
        if required_filter in (None, "", "any"):
            return True
        levels = {"high": 3, "moderate": 2, "low": 1, "none": 0}
        required = levels.get(str(required_filter).lower(), 0)
        actual = levels.get(str(confidence or "none").lower(), 0)
        return actual >= required

    @classmethod
    def _candidate_passes_price_free_filters(
        cls,
        config: dict[str, Any],
        signal: dict[str, Any],
        current_time: Optional[datetime],
        *,
        relaxed: bool,
    ) -> bool:
        """Cheap subset of the live selector used only to choose kline symbols.

        The real engine still applies the full filter chain. This only removes
        symbols the engine cannot reach without needing candle data, so cold-cache
        schedule backtests do not warm hundreds of irrelevant scan symbols first.
        """
        ticker = signal.get("ticker") or ""
        if not ticker:
            return False

        symbol = cls._to_symbol(ticker)
        blacklist = config.get("symbol_blacklist") or []
        if blacklist and symbol in blacklist:
            return False
        whitelist = config.get("symbol_whitelist")
        if whitelist and symbol not in whitelist:
            return False

        direction = str(signal.get("direction") or "").lower()
        if direction == "hold":
            return False

        signal_sides = config.get("signal_sides", "both")
        if signal_sides != "both":
            side_filter = str(signal_sides).lower()
            if side_filter in ("buy", "long") and direction not in ("buy", "long"):
                return False
            if side_filter in ("sell", "short") and direction not in ("sell", "short"):
                return False

        max_age = config.get("max_signal_age_minutes")
        if max_age is not None and current_time is not None:
            age_anchor = (
                signal.get("completed_at")
                or signal.get("analysis_completed_at")
                or signal.get("signal_time")
            )
            age_anchor = cls._parse_candidate_time(age_anchor)
            if age_anchor is not None:
                try:
                    if (current_time - age_anchor).total_seconds() / 60 > float(max_age):
                        return False
                except (TypeError, ValueError):
                    pass

        if not relaxed:
            try:
                if abs(float(signal.get("score") or 0.0)) < float(config.get("min_score", 0.0)):
                    return False
            except (TypeError, ValueError):
                return False
            if not cls._candidate_confidence_ok(signal.get("confidence"), config.get("confidence_filter", "any")):
                return False

        return True

    @classmethod
    def _candidate_limit_per_scan(cls, config: dict[str, Any], unique_count: int) -> int:
        if unique_count <= 0:
            return 0
        try:
            max_trades = int(config.get("max_trades", 999))
        except (TypeError, ValueError):
            max_trades = 999
        if max_trades <= 0:
            return 0
        if max_trades >= 100:
            return unique_count
        # Warm only the first selector slice up front. Price/position-dependent gates
        # can force the engine to reach lower-ranked candidates; those are discovered
        # by the bounded expansion pass after the first dry run and warmed on demand.
        return min(unique_count, max_trades)

    @classmethod
    def _select_price_free_candidates(
        cls,
        config: dict[str, Any],
        scan_signals: list[dict[str, Any]],
        current_time: Optional[datetime],
        *,
        selection_mode: str,
    ) -> list[dict[str, Any]]:
        from backend.services.backtest_engine import BacktestEngine

        if not scan_signals:
            return []
        execution_mode = config.get("execution_mode", "immediate")
        if selection_mode in ("batch", "post_scan_recheck"):
            deduped: dict[str, dict[str, Any]] = {}
            for sig in scan_signals:
                deduped[sig["ticker"]] = sig
            ordered = list(deduped.values())
            if selection_mode == "post_scan_recheck":
                ordered.sort(key=BacktestEngine._post_recheck_sort_key)
            else:
                ordered.sort(key=BacktestEngine._rank_key, reverse=True)
        elif execution_mode == "batch":
            deduped = {}
            for sig in scan_signals:
                deduped[sig["ticker"]] = sig
            ordered = list(deduped.values())
            ordered.sort(key=BacktestEngine._rank_key, reverse=True)
        else:
            ordered = list(scan_signals)

        limit = cls._candidate_limit_per_scan(config, len(ordered))
        strict_all = [
            sig for sig in ordered
            if cls._candidate_passes_price_free_filters(config, sig, current_time, relaxed=False)
        ]
        strict = strict_all[:limit]
        if not config.get("fill_to_max_trades"):
            return strict
        try:
            max_trades = int(config.get("max_trades", 999))
        except (TypeError, ValueError):
            max_trades = limit
        if len(strict_all) >= max_trades:
            return strict

        open_like = {BacktestEngine._to_symbol(s["ticker"]) for s in strict if s.get("ticker")}
        relaxed = [
            sig for sig in ordered
            if sig.get("ticker")
            and BacktestEngine._to_symbol(sig["ticker"]) not in open_like
            and cls._candidate_passes_price_free_filters(config, sig, current_time, relaxed=True)
        ]
        relaxed.sort(key=BacktestEngine._fill_rank_key, reverse=True)
        relaxed_slots = max(0, max_trades - len(strict_all))
        return strict + relaxed[:max(0, min(limit, relaxed_slots))]

    @classmethod
    def _derive_required_kline_symbols(
        cls,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
    ) -> Optional[set[str]]:
        """Return the kline symbol subset reachable by account-free trade picking.

        None means "do not reduce" for configs whose route depends on extra market
        context not represented by the price-free selector.
        """
        if not signals:
            return set()
        if (
            config.get("regime_filter_enabled")
            or config.get("mean_reversion_enabled")
            or config.get("strategy_cohort") == "mean_reversion"
            or config.get("_live_selection_by_scan")
        ):
            return None

        from collections import defaultdict

        scans: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for sig in signals:
            if sig.get("ticker"):
                scans[str(sig.get("scan_id") or "")].append(sig)

        required: set[str] = set()
        selection_times = config.get("_schedule_selection_time_by_scan") or {}
        recheck_times = config.get("_schedule_post_scan_recheck_time_by_scan") or {}
        for scan_id, scan_signals in scans.items():
            default_time = cls._parse_candidate_time(scan_signals[0].get("signal_time"))
            selection_time = cls._parse_candidate_time(selection_times.get(scan_id)) or default_time
            recheck_time = cls._parse_candidate_time(recheck_times.get(scan_id)) or selection_time
            normal = cls._select_price_free_candidates(
                config,
                scan_signals,
                selection_time,
                selection_mode=config.get("execution_mode", "immediate"),
            )
            for sig in normal:
                if sig.get("ticker"):
                    required.add(sig["ticker"])
            if config.get("skip_if_positions_open"):
                recheck = cls._select_price_free_candidates(
                    config,
                    scan_signals,
                    recheck_time,
                    selection_mode="post_scan_recheck",
                )
                for sig in recheck:
                    if sig.get("ticker"):
                        required.add(sig["ticker"])

        return required

    @classmethod
    def _required_kline_symbols_for(
        cls,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
    ) -> list[str]:
        if "_required_kline_symbols" in config:
            required = config.get("_required_kline_symbols") or []
            return sorted({str(sym) for sym in required if sym})
        return sorted({s["ticker"] for s in signals if s.get("ticker")})

    async def _resolve_schedule_warmup_start(self, config: dict[str, Any]) -> datetime:
        """Find an optional account-free schedule warm-up start before the window.

        This is opt-in because local strategy tuning often starts at a known config
        change date. Enabling it replays earlier copied scans from the same schedule
        to approximate carried selector/position state without accounts or trades.
        """
        scan_source = config.get("scan_source") or {}
        if scan_source.get("mode") != "schedule" or not scan_source.get("schedule_id"):
            return config["date_range_start"]

        requested_start = config["date_range_start"]
        try:
            max_trade_hours = float(config.get("max_trade_duration_hours") or 0)
        except (TypeError, ValueError):
            max_trade_hours = 0.0
        try:
            breakeven_hours = float(config.get("breakeven_timeout_hours") or 0)
        except (TypeError, ValueError):
            breakeven_hours = 0.0
        try:
            adaptive_hours = float(config.get("adaptive_blacklist_lookback_hours") or 0)
        except (TypeError, ValueError):
            adaptive_hours = 0.0

        warmup_days = max(
            7,
            int((max_trade_hours + 23) // 24) + 2,
            int((breakeven_hours + 23) // 24) + 2,
            int((adaptive_hours + 23) // 24) + 1,
        )
        warmup_days = max(0, min(warmup_days, 30))
        if warmup_days <= 0:
            return requested_start

        candidate_start = requested_start - timedelta(days=warmup_days)
        try:
            row = await self._db.pool.fetchrow(
                """
                SELECT MIN(started_at)::timestamptz AS warmup_start
                FROM scans
                WHERE schedule_id = $1
                  AND started_at::timestamptz >= $2
                  AND started_at::timestamptz < $3
                """,
                scan_source.get("schedule_id"),
                candidate_start,
                requested_start,
            )
        except Exception:
            logger.warning("backtest_schedule_warmup_start_failed", exc_info=True)
            return requested_start

        warmup_start = row.get("warmup_start") if row else None
        if warmup_start and warmup_start < requested_start:
            return warmup_start
        return requested_start

    async def _load_signals(
        self,
        scan_source: dict[str, Any],
        date_range: tuple[datetime, datetime],
        config: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Load historical scan result signals for the backtest engine.

        Supports 3 modes:
        - "schedule": Load all scan results from a specific scheduled scanner
        - "date_range": Load all scan results within date range (any scanner)
        - "explicit": Load scan results from specific scan IDs

        signal_time is anchored to the scan's COMPLETED_AT (the moment production
        actually placed the trade — execute_batch runs after the full per-ticker
        analysis finishes), NOT started_at. Anchoring at scan start would enter every
        trade at a pre-analysis price the live account never got (the scan takes
        minutes), systematically inflating PnL. COALESCE falls back to started_at for
        any legacy scan missing completed_at. The date-range WHERE still filters on
        started_at (the user picks the window by when scans RAN).

        Per-result completed_at is loaded from scan_results because live ranks on
        result["completed_at"]. Historical rows that have NULL scan_results.completed_at
        must keep completed_at=NULL: those live result objects did not have the
        timestamp tie-breaker either, so equal-score candidates kept scan insertion
        order. analysis_runs.completed_at remains available as separate diagnostic
        data, but it must not be promoted into completed_at for selection.

        Returns:
            List of signal dicts with: id, ticker, direction, confidence, score,
            signal_time, completed_at, analysis_completed_at, scan_id,
            signal_source, analysis_price.
        """
        mode = scan_source.get("mode", "date_range")
        start, end = date_range
        schedule_config_filter = None
        if mode == "schedule" and config is not None:
            schedule_config_filter = await self._resolve_schedule_config_scan_filter(config, date_range)

        if mode == "schedule":
            schedule_id = scan_source.get("schedule_id")
            query = f"""
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
                       s.started_at::timestamptz AS scan_started_at,
                       sr.completed_at::timestamptz AS completed_at,
                       ar.completed_at::timestamptz AS analysis_completed_at,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                LEFT JOIN analysis_runs ar ON ar.run_id = sr.run_id
                WHERE s.schedule_id = $1
                  AND s.started_at::timestamptz >= $2
                  AND s.started_at::timestamptz <= $3
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY signal_time, sr.id
                LIMIT {_MAX_SIGNALS}
            """
            rows = await self._db.pool.fetch(query, schedule_id, start, end)

        elif mode == "explicit":
            scan_ids = scan_source.get("scan_ids", [])
            query = f"""
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
                       s.started_at::timestamptz AS scan_started_at,
                       sr.completed_at::timestamptz AS completed_at,
                       ar.completed_at::timestamptz AS analysis_completed_at,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                LEFT JOIN analysis_runs ar ON ar.run_id = sr.run_id
                WHERE s.scan_id = ANY($1)
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY signal_time, sr.id
                LIMIT {_MAX_SIGNALS}
            """
            rows = await self._db.pool.fetch(query, scan_ids)

        else:  # date_range (default)
            query = f"""
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
                       s.started_at::timestamptz AS scan_started_at,
                       sr.completed_at::timestamptz AS completed_at,
                       ar.completed_at::timestamptz AS analysis_completed_at,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                LEFT JOIN analysis_runs ar ON ar.run_id = sr.run_id
                WHERE s.started_at::timestamptz >= $1
                  AND s.started_at::timestamptz <= $2
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY signal_time, sr.id
                LIMIT {_MAX_SIGNALS}
            """
            rows = await self._db.pool.fetch(query, start, end)

        # Convert asyncpg Records to plain dicts
        signals = []
        for row in rows:
            record = dict(row)
            signals.append({
                "id": record["id"],
                "ticker": record["ticker"],
                "direction": record["direction"],
                "confidence": record["confidence"],
                "score": record["score"],
                "signal_time": record["signal_time"],
                "scan_started_at": record.get("scan_started_at"),
                # Preserve the live selector field exactly. If historical
                # scan_results.completed_at is NULL, live had no timestamp tie-breaker
                # and no max-signal-age timestamp for that result.
                "completed_at": record.get("completed_at"),
                "analysis_completed_at": record.get("analysis_completed_at"),
                "scan_id": record["scan_id"],
                "signal_source": record.get("signal_source", "unknown"),
                "analysis_price": float(record["analysis_price"]) if record.get("analysis_price") else None,
            })

        if schedule_config_filter is not None:
            # Fresh-capital schedule backtests start FLAT, so the live rationale for
            # dropping pre-activation scans (don't inherit positions from scans the
            # config never ran for) does not apply: there are no inherited positions to
            # protect against. Dropping the earlier scans silently discarded days of
            # signals and made results NON-MONOTONIC — extending date_range_end past the
            # config's mid-window activation flipped this filter on and erased the
            # earlier, profitable scans. We therefore keep EVERY scan in the requested
            # window and use the match result only to anchor per-scan live-clock timing
            # for the scans that did match. Coverage (which scans run) and timing
            # fidelity (when matched scans trade) are now decoupled.
            before_scan_ids = {str(s["scan_id"]) for s in signals if s.get("scan_id")}
            after_scan_ids = before_scan_ids
            config["_schedule_config_filter"] = {
                "matched_scan_count": schedule_config_filter.get("matched_scan_count", 0),
                "eligible_scan_count": schedule_config_filter.get("eligible_scan_count", 0),
                "total_scan_count": schedule_config_filter.get("total_scan_count", 0),
                "inspectable_scan_count": schedule_config_filter.get("inspectable_scan_count", 0),
                "filtered_scan_count": 0,
                "filtered_signal_count": 0,
                "first_match_started_at": (
                    schedule_config_filter["first_match_started_at"].isoformat()
                    if isinstance(schedule_config_filter.get("first_match_started_at"), datetime)
                    else None
                ),
                "matched_config_indices": dict(
                    schedule_config_filter.get("matched_config_indices") or {}
                ),
            }
            selection_time_by_scan = schedule_config_filter.get("selection_time_by_scan") or {}
            post_recheck_time_by_scan = schedule_config_filter.get("post_recheck_time_by_scan") or {}
            if selection_time_by_scan:
                config["_schedule_selection_time_by_scan"] = {
                    str(scan_id): ts.isoformat()
                    for scan_id, ts in selection_time_by_scan.items()
                    if str(scan_id) in after_scan_ids and isinstance(ts, datetime)
                }
            if post_recheck_time_by_scan:
                config["_schedule_post_scan_recheck_time_by_scan"] = {
                    str(scan_id): ts.isoformat()
                    for scan_id, ts in post_recheck_time_by_scan.items()
                    if str(scan_id) in after_scan_ids and isinstance(ts, datetime)
                }

        logger.info(
            "backtest_signals_loaded",
            extra={"mode": mode, "count": len(signals), "date_range": f"{start} to {end}"},
        )
        return signals

    # ------------------------------------------------------------------ #
    # Background execution (Task 5.2)
    # ------------------------------------------------------------------ #

    async def recover_stale_runs(self) -> int:
        """On startup, mark orphaned running/pending runs as failed.

        A process restart leaves in-flight runs with no executor; they can never
        complete, so transition them to 'failed' with an explanatory message.

        Returns:
            Number of runs marked failed.
        """
        result = await self._db.pool.execute(
            """
            UPDATE backtest_runs
            SET status = 'failed',
                error_message = 'Interrupted by server restart',
                completed_at = now()
            WHERE status IN ('running', 'pending')
            """
        )
        # asyncpg execute returns a status string like "UPDATE 3"
        count = 0
        try:
            count = int(str(result).split()[-1])
        except (ValueError, IndexError):
            pass
        if count:
            logger.warning("backtest_stale_runs_recovered", extra={"count": count})
        return count

    async def _launch_background(self, run_id: str, config: dict[str, Any]) -> None:
        """Spawn the backtest as a tracked asyncio task (non-blocking)."""
        task = asyncio.create_task(self._execute_backtest(run_id, config))
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

    async def _execute_backtest(self, run_id: str, config: dict[str, Any]) -> None:
        """Run a single backtest end-to-end: load → simulate → persist.

        Runs the (synchronous) engine in the thread pool with a cancellation event
        + timeout Timer, then persists results or records the failure. Every failure
        path is caught and recorded — a failing backtest must never crash the
        service or leak its concurrency slot.

        The cancel event was registered in create_backtest; we reuse it so a cancel
        arriving in the launch gap is honored. The reserved slot is released here.
        """
        from backend.services.backtest_engine import BacktestCancelled, BacktestEngine

        # Reuse the event registered at create time (cancel may already be set).
        cancel_event = self._cancel_events.get(run_id) or threading.Event()
        self._cancel_events[run_id] = cancel_event
        timed_out = threading.Event()
        timer: Optional[threading.Timer] = None
        engine_done = False  # True once the simulation itself succeeds
        t0 = time.monotonic()

        try:
            # Cancelled before we even started?
            if cancel_event.is_set():
                await self._mark_status(run_id, "cancelled", completed=True, guard_cancel=False)
                return

            await self._mark_status(run_id, "running", started=True)

            # --- REPLAY MODE ---
            # Validate the engine against an account's ACTUAL live trades (selection
            # pinned from ground truth; simulation only). Branch here, INSIDE the try,
            # so the method's finally still releases the concurrency slot + cancel event.
            # The CPU-bound engine replay is offloaded to the executor (run_sync) so it
            # never blocks the event loop. run_replay enforces cycle/symbol bounds and
            # raises ReplayError (→ failed run with a clear message) for empty/oversized
            # windows. A bounded replay (one account, days) completes in seconds, so the
            # wall-clock timeout wiring below is not applied to this path.
            scan_source = config.get("scan_source", {})
            if scan_source.get("mode") == "replay":
                from backend.diagnostics.parity.data_access import ParityDataAccess
                from backend.services.backtest.replay_runner import run_replay, ReplayError
                from backend.services.backtest_metrics import compute_all_metrics
                from backend.schemas.backtest_schemas import SimulationResult
                account_id = scan_source.get("replay_account_id")
                replay_loop = asyncio.get_running_loop()

                async def _run_in_executor(fn):
                    return await replay_loop.run_in_executor(self._executor, fn)

                try:
                    result_dict, comparison = await run_replay(
                        ParityDataAccess(self._db), self._kline_cache, account_id,
                        config["date_range_start"], config["date_range_end"], config,
                        run_sync=_run_in_executor)
                except ReplayError as exc:
                    await self._mark_status(run_id, "failed", completed=True,
                                            error=str(exc)[:480], guard_cancel=False)
                    return
                # Anchor metrics to the SAME compounding basis the replay used (the
                # account's first-cycle base_capital), NOT the user's starting_capital
                # field — otherwise net_profit_pct/cagr degenerate.
                metrics_config = {**config,
                                  "starting_capital": result_dict.get("starting_capital")
                                  or config.get("starting_capital") or 0.0}
                metrics = compute_all_metrics(
                    result_dict["trades"], result_dict["equity_curve"], metrics_config)
                # Surface any excluded/missing trades so a truncated comparison is never
                # silent (AI-Manager/non-scanner trades and unresolved scan rows).
                warnings = [f"replay_mode_account_{account_id}"]
                # Replay reconstructs the account's ACTUAL live trades; it does not re-run
                # the cool-off gate. If the config enabled cool-off, say so explicitly so a
                # user doesn't assume the replay reflects cool-off-gated entries.
                if any(config.get(f"cooloff_on_{t}_enabled") for t in
                       ("success", "failure", "double_success", "double_failure")):
                    warnings.append("cooloff_not_simulated_in_replay")
                exc_counts = comparison.get("excluded_trades") or {}
                n_excluded = sum(int(v) for v in exc_counts.values())
                if n_excluded:
                    warnings.append(f"replay_excluded_{n_excluded}_non_scanner_or_ai_trades")
                if comparison.get("missing_pins"):
                    warnings.append(f"replay_{comparison['missing_pins']}_pins_without_signal")
                if comparison.get("symbols_no_kline"):
                    warnings.append(f"replay_{comparison['symbols_no_kline']}_symbols_no_kline_data")
                sim = SimulationResult(
                    trades=result_dict["trades"], equity_curve=result_dict["equity_curve"],
                    metrics=metrics, warnings=warnings,
                    filter_stats={"signals_total": comparison["pinned_trades"],
                                  "signals_entered": len(result_dict["trades"]),
                                  "signals_filtered": 0, "signals_no_kline": 0})
                await self._persist_results(run_id, sim, replay_comparison=comparison)
                return

            def _on_timeout() -> None:
                timed_out.set()
                cancel_event.set()

            def _start_timeout() -> None:
                nonlocal timer
                if timer is not None:
                    return
                timer = threading.Timer(_TIMEOUT_SECONDS, _on_timeout)
                timer.daemon = True
                timer.start()

            # Progress plumbing — defined up-front so the cache warm-up (below) can
            # report into the reserved warm-up band. `loop` is the running event loop
            # (engine progress callbacks hop to it from pool threads); progress_state
            # keeps the last OVERALL scaled value so progress stays monotonic across the
            # warm-up + both engine passes.
            loop = asyncio.get_running_loop()
            progress_state = {"last": 0}

            simulation_config = config
            if config.get("schedule_warmup_enabled"):
                warmup_start = await self._resolve_schedule_warmup_start(config)
                if warmup_start < config["date_range_start"]:
                    simulation_config = dict(config)
                    simulation_config["date_range_start"] = warmup_start
                    simulation_config["_report_start"] = config["date_range_start"]
                    simulation_config["_report_end"] = config["date_range_end"]
                    simulation_config["_schedule_warmup_start"] = warmup_start
                    logger.info(
                        "backtest_schedule_warmup_enabled",
                        extra={
                            "run_id": run_id,
                            "warmup_start": warmup_start.isoformat(),
                            "report_start": config["date_range_start"].isoformat(),
                        },
                    )

            self._emit_stage(run_id, "loading_signals", "Loading scan signals", pct=0)
            signals = await self._load_signals(
                simulation_config.get("scan_source", {}),
                (simulation_config["date_range_start"], simulation_config["date_range_end"]),
                simulation_config,
            )
            if cancel_event.is_set():
                raise BacktestCancelled
            await self._prepare_live_selection_context(
                simulation_config,
                signals,
                (simulation_config["date_range_start"], simulation_config["date_range_end"]),
            )
            if cancel_event.is_set():
                raise BacktestCancelled

            required_symbols = self._derive_required_kline_symbols(simulation_config, signals)
            raw_symbols = sorted({s["ticker"] for s in signals if s.get("ticker")})
            if required_symbols is not None and set(required_symbols) != set(raw_symbols):
                simulation_config = dict(simulation_config)
                simulation_config["_required_kline_symbols"] = sorted(required_symbols)
                logger.info(
                    "backtest_kline_symbol_set_reduced",
                    extra={
                        "run_id": run_id,
                        "required_symbols": len(required_symbols),
                        "raw_symbols": len(raw_symbols),
                    },
                )
            # Bound total kline memory BEFORE loading (symbols × candles-per-symbol)
            # so a many-symbol long-range backtest can't OOM the process.
            self._check_total_kline_budget(simulation_config, signals)
            n_symbols_needed = len(raw_symbols)
            n_required_symbols = len(self._required_kline_symbols_for(simulation_config, signals))
            self._emit_stage(
                run_id, "loading_signals", "Loaded scan signals",
                detail=(
                    f"{len(signals)} signals · {n_symbols_needed} symbols"
                    if n_required_symbols == n_symbols_needed
                    else (
                        f"{len(signals)} signals · {n_required_symbols} candidate symbols "
                        f"from {n_symbols_needed} scan symbols"
                    )
                ),
                pct=2, status="done",
            )

            # WARM the cache before reading it. Without this, a run reads whatever
            # candles happen to be cached — and a partially-warmed symbol (e.g. 73 of
            # 288 candles for a day, with the fill bar missing) yields a TRUNCATED series
            # that makes the engine fabricate fills on stale candles (root cause of the
            # Dad-Demo PnL gap: a short filled 2h-stale at 0.161 vs the real 0.178).
            # ensure_coverage fetches+stores any missing/partial-day candles (the
            # partial-day coverage fix makes it actually complete them). Best-effort: a
            # warming failure must not abort the run — the post-load _check_kline_coverage
            # still guards the result, and the engine now SKIPS (not fabricates) any
            # signal still lacking a candle at its fill time.
            # Tracks whether the warm-up had to fetch any not-yet-sealed candles for
            # this window. >0 means the cache did NOT already hold final data for every
            # day — so the run reflects freshly-fetched (still-maturing) candles and may
            # differ once the window fully seals. Drives the unfinalized-window warning.
            warmup_fetched = 0
            if self._kline_cache is not None:
                try:
                    symbols = self._required_kline_symbols_for(simulation_config, signals)
                    interval = simulation_config.get("simulation_interval", "5m")
                    self._emit_stage(
                        run_id, "warming_cache", "Warming price-data cache",
                        detail=(
                            f"{len(symbols)} symbols"
                            if len(symbols) == n_symbols_needed
                            else f"{len(symbols)} candidate symbols from {n_symbols_needed} scan symbols"
                        ),
                        pct=2,
                    )
                    # Warm-up owns the first WARMUP_BAND% of the progress bar so the bar
                    # ADVANCES during the (potentially slow) fetch instead of freezing at
                    # 0%. ensure_coverage calls back with 0-100 of warm-up; we scale it
                    # into [0, WARMUP_BAND] and write it straight to the DB (we're already
                    # on the event loop here — no thread hop needed).
                    def _warm_progress(warm_pct: int) -> None:
                        scaled = self._scale_progress(warm_pct, 0, _WARMUP_BAND)
                        if scaled > progress_state["last"]:
                            progress_state["last"] = scaled
                            self._schedule_progress(run_id, scaled)

                    cov = await self._kline_cache.ensure_coverage(
                        symbols, interval,
                        simulation_config.get("_report_start", simulation_config["date_range_start"]),
                        simulation_config["date_range_end"],
                        on_progress=_warm_progress,
                        cancel_check=cancel_event.is_set,
                        max_concurrency=12,
                    )
                    if cancel_event.is_set():
                        raise BacktestCancelled
                    logger.info("backtest_cache_warmed", extra={"run_id": run_id, **(cov or {})})
                    _fetched = (cov or {}).get("fetched", 0)
                    warmup_fetched = int(_fetched or 0)
                    self._emit_stage(
                        run_id, "warming_cache", "Price-data cache ready",
                        detail=(f"{_fetched} symbols fetched from exchange" if _fetched
                                else "all data already cached"),
                        pct=_WARMUP_BAND, status="done",
                    )
                except Exception:  # noqa: BLE001 — warming is best-effort, never fatal
                    if cancel_event.is_set() or timed_out.is_set():
                        raise BacktestCancelled
                    logger.warning("backtest_cache_warm_failed", extra={"run_id": run_id}, exc_info=False)
                    self._emit_stage(run_id, "warming_cache", "Cache warm-up skipped",
                                     detail="proceeding with cached data", pct=_WARMUP_BAND, status="done")

            self._emit_stage(run_id, "loading_klines", "Loading price data into memory", pct=_WARMUP_BAND)
            klines = await self._load_klines(simulation_config, signals)
            if cancel_event.is_set():
                raise BacktestCancelled
            self._emit_stage(
                run_id, "loading_klines", "Price data loaded",
                detail=f"{len(klines)} symbols", pct=_WARMUP_BAND, status="done",
            )
            logger.info("backtest_started", extra={
                "run_id": run_id, "n_signals": len(signals), "n_symbols": len(klines),
            })

            # Coverage guard: if >20% of required symbols have NO kline data, the
            # backtest would be misleading (most signals un-simulatable). Fail it
            # with a clear message rather than silently producing garbage. The
            # frontend can pre-check via GET /backtest-cache/status to avoid this.
            self._check_kline_coverage(
                signals,
                klines,
                set(self._required_kline_symbols_for(simulation_config, signals)),
            )

            # Regime Multi-Strategy (F1/F2/F3): build per-scan ScanContexts so the
            # engine can replay session/vol gating + MR routing/means. Returns {} (no
            # extra fetches) unless a regime feature is enabled — default-off stays free.
            scan_contexts = await self._build_scan_contexts(simulation_config, signals)

            def _make_progress_cb(band_lo: int, band_hi: int):
                """Build an engine progress callback scoped to the [band_lo, band_hi]
                slice of the overall bar.

                Runs in the POOL WORKER THREAD — hops to the event loop to schedule
                the async DB write. Best-effort: if the loop is closing during
                shutdown, call_soon_threadsafe raises; swallow it so progress
                reporting can never abort an otherwise-healthy simulation. Throttled
                on the OVERALL scaled value (≥5% steps, terminal 100 always allowed)
                and kept monotonic across phases via the shared progress_state.
                """
                def _cb(engine_pct: int) -> None:
                    scaled = self._scale_progress(engine_pct, band_lo, band_hi)
                    if scaled - progress_state["last"] < 5 and scaled < 100:
                        return
                    progress_state["last"] = scaled
                    try:
                        loop.call_soon_threadsafe(self._schedule_progress, run_id, scaled)
                    except RuntimeError:
                        pass  # loop closed — drop this progress update
                return _cb

            # Resolve per-symbol instrument parameters (qty step, min qty, tick size,
            # max leverage) so the engine sizes, caps leverage, and rounds TP/SL the
            # way the live exchange does. Best-effort: if the cache/network is
            # unavailable the engine falls back to no-op defaults (unchanged behaviour).
            instrument_info = await self._resolve_instrument_info(signals)

            engine = BacktestEngine()
            klines = await self._expand_reached_kline_symbols(
                run_id,
                simulation_config,
                signals,
                klines,
                cancel_event,
                instrument_info,
                scan_contexts,
            )
            if cancel_event.is_set():
                raise BacktestCancelled
            self._check_kline_coverage(
                signals,
                klines,
                set(self._required_kline_symbols_for(simulation_config, signals)),
            )
            _start_timeout()

            # ── 1-minute DRILL-DOWN (two-phase) ──
            # The engine computes each trade's entry/exit + tp/sl internally, so the
            # ambiguous 1m windows can only be known AFTER a run. The engine is pure
            # and deterministic, so we run it twice cheaply:
            #   Phase A — dry run (no fine data) → learn each trade's entry/exit bars.
            #   fetch  — pull 1m ONLY for those bars (entry + exit ±1 neighbour).
            #   Phase B — re-run WITH fine_klines; return Phase B.
            # Disabled (flag off) or no kline cache → single run, byte-identical to
            # before. fine_klines={} keeps the engine on its 5m path either way.
            drilldown_on = config.get("drilldown_enabled", True) and self._kline_cache is not None
            fine_klines: dict[str, dict[int, list[dict[str, Any]]]] = {}
            # Progress banding: the cache warm-up already filled [0, _WARMUP_BAND]. The
            # engine passes fill the REMAINDER. When drill-down runs the engine TWICE,
            # Phase A owns the first half of that remainder and Phase B the second, so
            # the polled progress_pct climbs monotonically across warm-up + both passes
            # instead of freezing. Single-pass runs use the whole remaining band. The
            # post-A fine-kline fetch sits at the seam between the two engine bands.
            if drilldown_on:
                _mid = _WARMUP_BAND + (100 - _WARMUP_BAND) // 2
                phase_a_cb = _make_progress_cb(_WARMUP_BAND, _mid)
                self._emit_stage(run_id, "simulating", "Simulating trades (pass 1/2)",
                                 detail="resolving entry/exit bars", pct=_WARMUP_BAND)
                phase_a = await loop.run_in_executor(
                    self._executor,
                    lambda: engine.run(simulation_config, signals, klines, cancel_event, phase_a_cb, instrument_info, scan_contexts),
                )
                if not (cancel_event.is_set() or timed_out.is_set()):
                    self._emit_stage(run_id, "drilldown", "Refining fills (1-minute drill-down)",
                                     detail=f"{len(phase_a.trades or [])} trades", pct=_mid)
                    fine_klines = await self._build_fine_klines(simulation_config, phase_a.trades or [])
                phase_b_cb = _make_progress_cb(_mid, 100)
                self._emit_stage(run_id, "simulating", "Simulating trades (pass 2/2)",
                                 detail="applying drilled fills", pct=_mid)
            else:
                phase_b_cb = _make_progress_cb(_WARMUP_BAND, 100)
                self._emit_stage(run_id, "simulating", "Simulating trades",
                                 detail="candle-by-candle replay", pct=_WARMUP_BAND)

            result = await loop.run_in_executor(
                self._executor,
                lambda: engine.run(simulation_config, signals, klines, cancel_event, phase_b_cb, instrument_info, scan_contexts, fine_klines or None),
            )
            engine_done = True
            schedule_filter = simulation_config.get("_schedule_config_filter") or {}
            if schedule_filter and result.warnings is not None:
                filtered_scans = int(schedule_filter.get("filtered_scan_count") or 0)
                if filtered_scans:
                    result.warnings.append(
                        "schedule_config_filter_applied_"
                        f"{schedule_filter.get('eligible_scan_count', 0)}_of_"
                        f"{schedule_filter.get('total_scan_count', 0)}_scans"
                    )
            # Tell the consumer drill-down actually ran (and on how many trades).
            if fine_klines and result.warnings is not None:
                result.warnings.append(f"drilldown_applied_{len(fine_klines)}_symbols")

            # Regime Multi-Strategy modeling notes: surface the parity caveats so the
            # user knows where the backtest necessarily approximates live trading.
            if result.warnings is not None:
                mr_on = bool(config.get("mean_reversion_enabled")) or (config.get("strategy_cohort") == "mean_reversion")
                if mr_on:
                    # F2-long ack is server-authoritative live; there is no live account
                    # in a backtest, so it's honored via mr_long_enabled (bypassed).
                    if config.get("mr_long_enabled"):
                        result.warnings.append("f2_long_ack_bypassed_in_backtest")
                    # MR side/geometry use the engine's next-bar-open fill (vs live's
                    # scan-time mark) — documented, slightly more faithful, no look-ahead.
                    result.warnings.append("mr_entry_uses_next_bar_open")
                if config.get("regime_filter_enabled") and config.get("btc_vol_filter_enabled"):
                    result.warnings.append("btc_vol_uses_historical_klines_at_scan_time")

            # Surface signals that were dropped purely because the symbol had no cached
            # candles — production would have traded them, so the backtest UNDER-trades
            # here. This is data coverage, not a strategy filter, so the user must know.
            no_kline = (result.filter_stats or {}).get("signals_no_kline", 0)
            if no_kline and result.warnings is not None:
                result.warnings.append(f"signals_dropped_no_kline_data_{no_kline}")

            # Unfinalized-window guard: a backtest is only reproducible once EVERY day
            # in its window is SEALED (recorded immutable). A day can be "closed" (below
            # the completion frontier) yet still unsealed — and a closed-but-unsealed day
            # is re-fetched one last time to seal it, which can return CORRECTED candles
            # that differ from an earlier provisional fetch. So the run that warms those
            # candles uses provisional data; a later run uses the finalized data, and the
            # SAME config can yield a DIFFERENT result with no code/config change. This is
            # exactly the "my 1000+ result dropped" surprise — the morning run filled
            # mid-window (Jun 8-9) trades on provisional candles; once they sealed at
            # corrected prices, two trades flipped to losses, tripping a cool-off.
            #
            # The precise signal is whether THIS run had to fetch any not-yet-sealed
            # candle for the window (warmup_fetched > 0) — measured against the actual
            # cache state for the actual window, so it catches MID-window unsealed days,
            # not just an unfinalized end (the earlier frontier-vs-end check missed this
            # case: the window ended on an already-closed day while interior days were
            # still settling). We warn rather than freeze provisional data — the finalized
            # result is the CORRECT one; reproducibility comes once the window seals.
            if result.warnings is not None and warmup_fetched > 0:
                result.warnings.append("window_not_finalized_results_may_change")

            # Buy & Hold benchmark + excess return (Phase 4 carry-forward):
            # compare the strategy against simply holding BTC over the same window.
            self._emit_stage(run_id, "computing_metrics", "Computing metrics",
                             detail=f"{len(result.trades or [])} trades", pct=98)
            await self._attach_buy_hold(config, result)

            # Persist with one retry. _persist_results is idempotent (upsert +
            # delete-then-insert) AND flips status to 'completed' atomically in the
            # SAME transaction — so the invariant "results exist ⟺ status=completed"
            # holds even if the status write would otherwise fail separately, and a
            # minute-long simulation isn't wasted on a transient DB blip.
            #
            # completion wins over a late cancel: engine_done is True here, so any
            # in-flight cancel is a LATE one (mid-sim cancels raise BacktestCancelled;
            # launch-gap cancels are handled at the top). The transactional UPDATE has
            # no cancel guard, so it overwrites a late eager-cancel back to completed.
            try:
                await self._persist_results(run_id, result)
            except Exception:  # noqa: BLE001 — retry once before giving up
                logger.warning("backtest_persist_retry", extra={"run_id": run_id})
                await asyncio.sleep(0.5)
                await self._persist_results(run_id, result)
            logger.info("backtest_completed", extra={
                "run_id": run_id,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "n_trades": len(result.trades or []),
                "n_warnings": len(result.warnings or []),
            })
            self._emit_stage(
                run_id, "complete", "Backtest complete",
                detail=f"{len(result.trades or [])} trades simulated",
                pct=100, status="done",
            )

        except BacktestCancelled:
            if timed_out.is_set():
                logger.warning("backtest_timed_out",
                               extra={"run_id": run_id, "timeout_s": _TIMEOUT_SECONDS})
                self._emit_stage(run_id, "failed", "Timed out",
                                 detail=f"exceeded {_TIMEOUT_SECONDS}s limit", pct=100, status="failed")
                await self._mark_status(
                    run_id, "failed", completed=True, guard_cancel=False,
                    error=f"Backtest exceeded the {_TIMEOUT_SECONDS}s time limit.",
                )
            else:
                logger.info("backtest_cancelled", extra={"run_id": run_id})
                self._emit_stage(run_id, "failed", "Cancelled", pct=100, status="failed")
                await self._mark_status(run_id, "cancelled", completed=True, guard_cancel=False)
        except BacktestValidationError as exc:
            # A pre-flight validation failure (e.g. insufficient kline coverage) —
            # surface the clean, user-facing message rather than mangling it through
            # the generic "simulation error: ..." path.
            logger.info("backtest_validation_failed",
                        extra={"run_id": run_id, "reason": str(exc)[:200]})
            self._emit_stage(run_id, "failed", "Validation failed",
                             detail=str(exc)[:120], pct=100, status="failed")
            await self._mark_status(run_id, "failed", completed=True, error=str(exc)[:480])
        except Exception:  # noqa: BLE001 — must never crash the service
            # Distinguish a SIMULATION failure from a POST-simulation persistence
            # failure: the latter still means the backtest computed successfully.
            phase = "persistence" if engine_done else "simulation"
            # Log the full exception server-side, but store only a generic,
            # disclosure-safe message in the user-visible error_message column.
            logger.exception("backtest_execution_failed",
                             extra={"run_id": run_id, "phase": phase})
            self._emit_stage(run_id, "failed", f"Failed during {phase}", pct=100, status="failed")
            try:
                await self._mark_status(
                    run_id, "failed", completed=True,
                    error=f"Backtest failed during {phase}. Reference run {run_id}.",
                )
            except Exception:  # noqa: BLE001 — DB down; nothing more we can do
                logger.exception("backtest_mark_failed_errored", extra={"run_id": run_id})
        finally:
            if timer is not None:
                timer.cancel()
            self._cancel_events.pop(run_id, None)
            self._active_slots = max(0, self._active_slots - 1)

    @staticmethod
    def _scale_progress(engine_pct: int, band_lo: int, band_hi: int) -> int:
        """Map one engine pass's own 0-100 progress onto the [band_lo, band_hi] slice
        of the OVERALL progress bar.

        The drill-down path runs the engine twice; each pass reports 0-100 about
        ITSELF. Without banding, the first (silent) pass left progress at 0% for the
        front half of the run and the second pass then swept 0→100 again. Scaling each
        pass into its own band makes the polled progress_pct advance monotonically
        across the whole lifecycle. Engine input is clamped to [0, 100] so a
        misbehaving pass can never drive progress outside its band.
        """
        clamped = min(100, max(0, engine_pct))
        return int(round(band_lo + (clamped / 100.0) * (band_hi - band_lo)))

    def _schedule_progress(self, run_id: str, pct: int) -> None:
        """Schedule a progress DB write on the loop, keeping a strong task ref.

        asyncio holds only weak references to bare tasks, so we retain the task in
        _running_tasks until it completes to prevent mid-flight GC.
        """
        task = asyncio.ensure_future(self._update_progress(run_id, pct))
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

    def _emit_stage(
        self, run_id: str, stage: str, label: str, *,
        detail: str = "", pct: Optional[int] = None, status: str = "active",
    ) -> None:
        """Emit a real-time stage event to the progress manager (best-effort, no-op
        when no manager is wired). Never raises into the run path."""
        if self._progress is None:
            return
        try:
            self._progress.emit(run_id, stage, label, detail=detail, pct=pct, status=status)
        except Exception:  # noqa: BLE001 — progress streaming must never fail a run
            logger.debug("backtest_stage_emit_failed", extra={"run_id": run_id, "stage": stage})


    async def _load_klines(
        self, config: dict[str, Any], signals: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Load cached klines for every symbol referenced by the signals.

        Reads run CONCURRENTLY (asyncio.gather) instead of a sequential per-symbol
        await loop — the old N+1 pattern serialized one DB round-trip per symbol, so
        a 50-symbol backtest paid 50 sequential latencies before the sim could start.
        Results are byte-identical to the serial load (same get_klines call per
        symbol, same args); only the wall-clock overlaps. Order is restored by
        zipping back to the sorted symbol list, so the returned dict is deterministic.
        """
        if self._kline_cache is None:
            return {}
        symbols = self._required_kline_symbols_for(config, signals)
        return await self._load_klines_for_symbols(config, symbols)

    async def _load_klines_for_symbols(
        self, config: dict[str, Any], symbols: list[str] | set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Load cached klines for a specific symbol set."""
        if self._kline_cache is None:
            return {}
        symbols = sorted({str(symbol) for symbol in symbols if symbol})
        interval = config.get("simulation_interval", "5m")
        start = config["date_range_start"]
        end = config["date_range_end"]
        results = await asyncio.gather(
            *(self._kline_cache.get_klines(symbol, interval, start, end) for symbol in symbols)
        )
        return {symbol: series for symbol, series in zip(symbols, results)}

    @staticmethod
    def _result_missing_kline_symbols(result: Any) -> set[str]:
        stats = getattr(result, "filter_stats", None) or {}
        raw = stats.get("signals_no_kline_symbols") or []
        if not isinstance(raw, list):
            return set()
        return {str(symbol) for symbol in raw if symbol}

    async def _expand_reached_kline_symbols(
        self,
        run_id: str,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        cancel_event: threading.Event,
        instrument_info: dict[str, dict[str, float]],
        scan_contexts: dict[str, "ScanContext"],
    ) -> dict[str, list[dict[str, Any]]]:
        """Warm symbols the live-like selector actually reaches but lacks klines for.

        The first cache warm-up is intentionally small: top-N per scan by the same
        account-free ordering live uses. If price drift, sector, existing positions,
        or adaptive blacklist cause the engine to walk further down a scan's ranked
        candidates, the dry run reports those reached-but-unloaded symbols here. We
        warm only those symbols and rerun from the beginning. This preserves trade
        selection parity without warming every raw scan symbol.
        """
        if self._kline_cache is None or "_required_kline_symbols" not in config:
            return klines
        if config.get("_live_selection_by_scan"):
            return klines

        from backend.services.backtest_engine import BacktestEngine

        loop = asyncio.get_running_loop()
        attempted: set[str] = set()
        required = set(self._required_kline_symbols_for(config, signals))
        interval = config.get("simulation_interval", "5m")
        warm_start = config.get("_report_start", config["date_range_start"])
        end = config["date_range_end"]

        for pass_idx in range(_KLINE_EXPANSION_PASSES):
            if cancel_event.is_set():
                break
            probe_engine = BacktestEngine()
            probe = await loop.run_in_executor(
                self._executor,
                lambda: probe_engine.run(
                    config,
                    signals,
                    klines,
                    cancel_event,
                    None,
                    instrument_info,
                    scan_contexts,
                ),
            )
            missing = self._result_missing_kline_symbols(probe)
            to_warm = sorted(missing - attempted)
            if not to_warm:
                break

            attempted.update(to_warm)
            required.update(to_warm)
            config["_required_kline_symbols"] = sorted(required)
            self._emit_stage(
                run_id,
                "warming_cache",
                "Expanding price-data cache",
                detail=f"{len(to_warm)} reached selector symbols",
                pct=_WARMUP_BAND,
            )
            try:
                await self._kline_cache.ensure_coverage(
                    to_warm,
                    interval,
                    warm_start,
                    end,
                    cancel_check=cancel_event.is_set,
                    max_concurrency=12,
                )
            except Exception:  # noqa: BLE001 — final run will surface no-kline warnings
                if cancel_event.is_set():
                    break
                logger.warning(
                    "backtest_kline_expansion_warm_failed",
                    extra={"run_id": run_id, "symbols": len(to_warm), "pass": pass_idx + 1},
                    exc_info=False,
                )
            klines.update(await self._load_klines_for_symbols(config, to_warm))
            logger.info(
                "backtest_kline_symbol_set_expanded",
                extra={
                    "run_id": run_id,
                    "pass": pass_idx + 1,
                    "added_symbols": len(to_warm),
                    "required_symbols": len(required),
                },
            )

        return klines

    @staticmethod
    def _interval_minutes(interval: str) -> int:
        return {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(interval, 60)

    async def _build_fine_klines(
        self, config: dict[str, Any], trades: list[dict[str, Any]]
    ) -> dict[str, dict[int, list[dict[str, Any]]]]:
        """Fetch 1-minute candles for the bars Phase-A trades can touch,
        indexed for engine drill-down: {symbol: {bar_open_epoch: [1m candles asc]}}.

        - All modes stay sparse: entry bar + exit bar ±1 neighbour (entry-drill can
          shift tp/sl so the real exit may land one bar over). Specific Schedule must
          not inject continuous holding windows because that changes the
          skip_if_positions_open/post-scan cascade and makes the simulator pick
          different scan rounds than live.
        - Uses `_fetch_klines_from_bybit` DIRECTLY (not get_klines/ensure_coverage): the
          coverage table marks a partial day "covered" and would skip refetching newer
          1m candles; and we deliberately DO NOT `store_klines` (that would re-poison the
          coverage table for later requests). 1m data stays in-memory for this run only.
        - Any symbol/window that fails or returns no candles is simply omitted → the
          engine falls back to its 5m logic for that bar (fail-soft, never wrong).
        """
        if self._kline_cache is None or not trades:
            return {}

        sim_min = self._interval_minutes(config.get("simulation_interval", "5m"))
        bar_s = sim_min * 60  # seconds per simulation bar (5m → 300)

        def _bar_open_epoch(dt: datetime) -> int:
            # Floor a timestamp to its simulation-bar boundary (epoch-aligned, as the
            # cached candles' open_times are).
            return (int(dt.timestamp()) // bar_s) * bar_s

        # Collect the distinct (symbol, bar_open_epoch) windows to fetch.
        wanted: dict[str, set[int]] = {}

        def _remember_epoch(sym: str, epoch: int) -> None:
            wanted.setdefault(sym, set()).add(epoch)

        for t in trades:
            sym = t.get("symbol")
            if not sym:
                continue
            et, xt = t.get("entry_time"), t.get("exit_time")
            epochs: set[int] = set()
            if isinstance(et, datetime):
                # Entry fills at the NEXT bar's open when the signal instant isn't
                # bar-aligned, so the actual entry bar may be entry_time's bar OR the
                # one after. Fetch both (forward neighbour) so the engine's real entry
                # bar always has a 1m window.
                ee = _bar_open_epoch(et)
                epochs.update({ee, ee + bar_s})
            if isinstance(xt, datetime):
                xe = _bar_open_epoch(xt)
                epochs.update({xe - bar_s, xe, xe + bar_s})  # exit ±1 neighbour
            for epoch in epochs:
                _remember_epoch(sym, epoch)

        # ── FULL-BOOK coverage for PORTFOLIO-equity closes ──
        # The engine's 1-minute portfolio-equity walk (drawdown / smart / rise /
        # close_on_profit) only engages on a bar when EVERY open position has a 1m
        # window for it — equity is a book-wide sum. The per-trade loop above covers
        # each trade's OWN exit bar, but a portfolio mass-close fires on the equity of
        # the WHOLE book, so every position open at that instant needs the firing bar
        # too. For each Phase-A trade closed by a portfolio rule, add its exit bar (±1
        # neighbour) to every OTHER trade that was open at that time. Bounded by the
        # number of portfolio closes; still only the bars that can actually fire.
        _PORTFOLIO_REASONS = {"equity_drop", "equity_drop_smart", "equity_rise", "close_on_profit", "breakeven"}
        portfolio_exits: list[tuple[int, datetime]] = [
            (_bar_open_epoch(t["exit_time"]), t["exit_time"])
            for t in trades
            if t.get("close_reason") in _PORTFOLIO_REASONS and isinstance(t.get("exit_time"), datetime)
        ]
        for fire_epoch, _fire_time in portfolio_exits:
            fire_epochs = {fire_epoch - bar_s, fire_epoch, fire_epoch + bar_s}
            for t in trades:
                sym = t.get("symbol")
                et, xt = t.get("entry_time"), t.get("exit_time")
                if not sym or not isinstance(et, datetime):
                    continue
                # Was this trade open across the firing instant? Open at/just-after its
                # entry bar through its exit bar (inclusive of the firing bar itself).
                open_from = _bar_open_epoch(et)
                open_until = _bar_open_epoch(xt) if isinstance(xt, datetime) else fire_epoch
                if open_from <= fire_epoch <= open_until:
                    for epoch in fire_epochs:
                        _remember_epoch(sym, epoch)

        if not wanted:
            return {}

        requests: list[tuple[str, datetime, datetime]] = []
        for sym, epochs in wanted.items():
            lo = min(epochs)
            hi = max(epochs) + bar_s
            requests.append((
                sym,
                datetime.fromtimestamp(lo, tz=timezone.utc),
                datetime.fromtimestamp(hi, tz=timezone.utc),
            ))

        # Fetch 1m windows CONCURRENTLY, but bounded. The sparse request set keeps
        # drilldown from changing the trade lifecycle while avoiding the old sequential
        # round-trip cost.
        sem = asyncio.Semaphore(8)

        async def _fetch_one(req: tuple[str, datetime, datetime]):
            sym, ws, we = req
            try:
                async with sem:
                    ones = await self._kline_cache._fetch_klines_from_bybit(sym, "1m", ws, we)
                return sym, ones, None
            except Exception as exc:  # fail-soft per symbol/range
                return sym, [], exc

        fetched = await asyncio.gather(*(_fetch_one(req) for req in requests))

        out: dict[str, dict[int, list[dict[str, Any]]]] = {}
        for sym, ones, exc in fetched:
            epochs = wanted[sym]
            if exc is not None:
                logger.warning("backtest_drilldown_fetch_failed", extra={"symbol": sym}, exc_info=False)
                continue
            if not ones:
                continue
            # Bucket each 1m candle into its simulation-bar window.
            buckets = out.setdefault(sym, {})
            for c in ones:
                ot = c["open_time"]
                if not isinstance(ot, datetime):
                    continue
                key = (int(ot.timestamp()) // bar_s) * bar_s
                if key in epochs:
                    buckets.setdefault(key, []).append(c)
        for buckets in out.values():
            for key, bucket in list(buckets.items()):
                seen: set[datetime] = set()
                deduped: list[dict[str, Any]] = []
                for candle in sorted(bucket, key=lambda c: c["open_time"]):
                    ot = candle.get("open_time")
                    if ot in seen:
                        continue
                    seen.add(ot)
                    deduped.append(candle)
                buckets[key] = deduped
        return out

    async def _build_scan_contexts(
        self, config: dict[str, Any], signals: list[dict[str, Any]]
    ) -> dict[str, "ScanContext"]:
        """Replay live build_scan_context per historical scan for F1/F2/F3 (FR-003).

        Returns {scan_id: ScanContext}. Empty {} unless a regime feature is active, so a
        default-off backtest fetches NO extra klines and the engine no-ops (preserving
        the byte-identical golden guarantee).

        For each scan_id (anchored at its first signal's signal_time) we slice the
        pre-fetched BTC + per-symbol kline series to candles with open_time <= scan_time
        (no look-ahead) and assemble a ScanContext with the BTC regime
        (classify_regime) and per-MR-symbol EMA means (compute_ema_mean). computed_at is
        the historical scan instant — NOT now() — so is_stale uses real time and the
        engine stays deterministic. Degraded when BTC data is unavailable (MR
        fail-closed downstream, matching live).
        """
        from backend.services import market_data as _md
        from backend.services.scan_context import ScanContext

        # Which features need scan-time market data?
        btc_needed = bool(config.get("regime_filter_enabled") and config.get("btc_vol_filter_enabled"))
        mr_active = bool(config.get("mean_reversion_enabled")) or (config.get("strategy_cohort") == "mean_reversion")
        if not (btc_needed or mr_active):
            return {}
        if self._kline_cache is None:
            return {}

        # Group signals by scan_id; each scan's time = its first signal's signal_time.
        from collections import defaultdict
        scans: dict[str, list[dict]] = defaultdict(list)
        for s in signals:
            scans[s["scan_id"]].append(s)
        if not scans:
            return {}

        win_start = config["date_range_start"]
        win_end = config["date_range_end"]
        btc_iv = config.get("btc_vol_interval", "1h")
        btc_lb = int(config.get("btc_vol_lookback_candles", 14))
        # Warm-up buffer: enough candles before the window for the first scan's
        # classify_regime/EMA (required_depth = 2*lookback+1; pad generously).
        from datetime import timedelta as _td
        btc_buffer = _td(minutes=self._interval_minutes(btc_iv) * (2 * btc_lb + 5))

        # BTC series (for vol filter AND MR routing regime).
        btc_series: list[dict] = []
        try:
            btc_series = await self._kline_cache.get_klines("BTCUSDT", btc_iv, win_start - btc_buffer, win_end)
        except Exception:
            logger.warning("backtest_scan_ctx_btc_fetch_failed", exc_info=False)

        # Per-symbol MR mean series (only when MR active).
        mr_iv = config.get("mr_mean_interval", "1h")
        mr_period = int(config.get("mr_mean_period", 20))
        mean_series: dict[str, list[dict]] = {}
        if mr_active:
            mr_buffer = _td(minutes=self._interval_minutes(mr_iv) * (mr_period + 5))
            mr_symbols = sorted({
                (t if t.endswith("USDT") else f"{t}USDT")
                for t in {s["ticker"] for s in signals}
            })
            for sym in mr_symbols:
                try:
                    mean_series[sym] = await self._kline_cache.get_klines(sym, mr_iv, win_start - mr_buffer, win_end)
                except Exception:
                    # Log + fail-closed (this symbol won't route MR), matching the
                    # log-and-fallback convention used by _load_klines / _attach_buy_hold
                    # rather than swallowing the error silently.
                    logger.warning("backtest_scan_ctx_mr_fetch_failed", extra={"symbol": sym}, exc_info=False)
                    mean_series[sym] = []

        volatile_atr = float(config.get("regime_volatile_atr", 2.0))
        trend_ema = float(config.get("regime_trend_ema_dist_pct", 1.0))

        # A candle is usable for a decision at scan_time only once it has CLOSED, i.e.
        # open_time + interval <= scan_time  <=>  open_time <= scan_time - interval.
        # Slicing on open_time <= scan_time would include the in-progress candle whose
        # stored close is a FUTURE price (the bar hasn't ended at scan_time) — a classic
        # look-ahead that contaminates the EMA mean's highest-weight term and the BTC
        # regime label. This mirrors the engine's own next-bar-open fill convention.
        #
        # Perf: the series are sorted ascending by open_time, so for each scan we binary-
        # search the cutoff index (bisect) instead of an O(n) re-scan, and pass only the
        # bounded tail the indicators need (regime: 2*lookback+1; mean: period). With S
        # scans / B BTC candles / M symbols / C candles this turns O(S*(B + M*C)) into
        # O(B + M*C + S*M*log C) — seconds at the 365-day / 3M-candle ceiling, not minutes.
        from bisect import bisect_right
        from datetime import timedelta as _td2
        btc_closed_by = _td2(minutes=self._interval_minutes(btc_iv))
        mr_closed_by = _td2(minutes=self._interval_minutes(mr_iv))
        btc_times = [k["open_time"] for k in btc_series]
        btc_tail = 2 * btc_lb + 1                          # = live required_depth(lookback)
        mean_times = {sym: [k["open_time"] for k in s] for sym, s in mean_series.items()}
        # Live fetches EXACTLY period+1 candles for the EMA mean (auto_trade_service
        # _lazy_mr_mean / market_data build_scan_context). The EMA value depends on how
        # much history is passed (it seeds from the first `period` then iterates), so we
        # must use the SAME depth as live, not the full buffered series — this is a
        # parity fix as well as a perf one (the prior full-series slice diverged from live).
        mr_tail = mr_period + 1

        contexts: dict[str, ScanContext] = {}
        for scan_id, scan_sigs in scans.items():
            scan_time = scan_sigs[0]["signal_time"]
            # BTC regime from candles that have CLOSED at/<= scan_time (no look-ahead).
            bi = bisect_right(btc_times, scan_time - btc_closed_by)
            btc_slice = btc_series[max(0, bi - btc_tail):bi]
            btc_regime = _md.classify_regime(
                btc_slice, lookback=btc_lb, volatile_atr=volatile_atr, trend_ema_dist_pct=trend_ema,
            )
            degraded = bool(btc_regime.get("unavailable"))
            btc_map = {(btc_iv, btc_lb): btc_regime}

            means: dict[tuple[str, int, str], float] = {}
            if mr_active:
                cutoff = scan_time - mr_closed_by
                for sym, series in mean_series.items():
                    mi = bisect_right(mean_times[sym], cutoff)
                    sl = series[max(0, mi - mr_tail):mi]
                    m = _md.compute_ema_mean(sl, mr_period)
                    if m is not None:
                        means[(sym, mr_period, mr_iv)] = m

            contexts[scan_id] = ScanContext(
                btc=btc_map, means=means, prices={}, computed_at=scan_time,
                degraded=degraded, kill={},
            )
        return contexts

    async def _resolve_instrument_info(
        self, signals: list[dict[str, Any]]
    ) -> dict[str, dict[str, float]]:
        """Resolve per-symbol instrument parameters for the scan's tickers.

        Returns {ticker: {qty_step, min_qty, tick_size, max_leverage}} so the engine
        can size positions to the real lot step, reject below min qty, cap leverage to
        the symbol's max, and round TP/SL to the tick — matching live trading. The
        symbol keys are the signal tickers (same keys the engine looks up).

        Best-effort and fail-open: lazily creates the InstrumentInfoCache, refreshes it
        once if empty, and on ANY error returns {} so the engine uses its no-op
        defaults (unchanged behaviour) rather than failing the run.
        """
        try:
            symbols = sorted({s["ticker"] for s in signals})
            if not symbols:
                return {}
            if self._instrument_cache is None:
                from backend.services.kline_cache_service import InstrumentInfoCache
                self._instrument_cache = InstrumentInfoCache()
            cache = self._instrument_cache
            # Refresh once if the cache has never been populated. refresh() is itself
            # guarded and returns 0 on failure; get_or_default then yields conservative
            # defaults per symbol.
            if getattr(cache, "_last_refresh", None) is None:
                try:
                    await cache.refresh()
                except Exception:
                    logger.warning("instrument_cache_refresh_failed", exc_info=False)
            return {sym: cache.get_or_default(sym) for sym in symbols}
        except Exception:
            logger.warning("instrument_info_resolve_failed", exc_info=False)
            return {}

    async def load_inputs(
        self, config: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
        """Load (signals, klines snapshot, instrument_info) ONCE for a sweep.

        The optimizer loads the historical signals + klines + instrument params a
        single time for the baseline date range, then replays every config combo
        against that same in-sample snapshot via run_one. Returns the three inputs
        the engine needs. Best-effort/fail-open mirrors _execute_backtest's loaders
        but without a run row.
        """
        signals = await self._load_signals(
            config.get("scan_source", {}),
            (config["date_range_start"], config["date_range_end"]),
            config,
        )
        klines = await self._load_klines(config, signals)
        instrument_info = await self._resolve_instrument_info(signals)
        return signals, klines, instrument_info

    async def run_one(
        self,
        config: dict[str, Any],
        signals: list[dict[str, Any]],
        snapshot: dict[str, list[dict[str, Any]]],
        instrument_info: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """BacktestRunner adapter: run ONE config against a pre-loaded klines
        snapshot via the real BacktestEngine and return its metrics dict.

        This is the in-process baseline path the optimizer uses (the ProcessPool
        worker uses a separate sync entrypoint for the same engine). It does NOT
        touch the DB — no run row, no persistence — so a sweep can fan thousands
        of these out cheaply. `snapshot` IS the engine's `klines` argument
        (symbol → ascending kline dicts), pre-loaded once by the caller.

        `deadline` (monotonic seconds) bounds the run via the engine's
        cooperative cancel event; on timeout the engine raises BacktestCancelled
        which we surface as an empty metrics dict (the ranker treats a missing
        objective as non-finite and excludes it — never a crash).
        """
        import threading
        import time

        from backend.services.backtest_engine import BacktestCancelled, BacktestEngine

        cancel_event = threading.Event()
        timer: threading.Timer | None = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {}
            timer = threading.Timer(remaining, cancel_event.set)
            timer.daemon = True
            timer.start()

        def _run() -> dict[str, Any]:
            try:
                engine = BacktestEngine()
                result = engine.run(
                    config, signals, snapshot or {}, cancel_event, None, instrument_info or {}
                )
                return dict(result.metrics or {})
            except BacktestCancelled:
                return {}

        try:
            loop = asyncio.get_running_loop()
            executor = getattr(self, "_executor", None)
            if executor is not None:
                return await loop.run_in_executor(executor, _run)
            return await loop.run_in_executor(None, _run)
        finally:
            if timer is not None:
                timer.cancel()

    async def _attach_buy_hold(self, config: dict[str, Any], result: Any) -> None:
        """Compute the BTC Buy & Hold benchmark + excess return and merge into metrics.

        Fetches BTCUSDT klines for the backtest window, computes the hold return
        via backtest_metrics.compute_buy_hold_return, and adds buy_hold_return_pct,
        buy_hold_final_value, and excess_return (strategy net% − buy&hold%) to the
        result's metrics dict.

        Best-effort: if the BTC cache is missing/empty or the fetch fails, the
        benchmark is genuinely unknown, so the fields are set to None (N/A) rather
        than a misleading flat-0% benchmark — and a failed fetch never fails the
        whole backtest.
        """
        from backend.services.backtest_metrics import compute_buy_hold_return

        metrics = result.metrics or {}
        starting_capital = config.get("starting_capital", 0.0)
        btc_klines: list[dict[str, Any]] = []
        if self._kline_cache is not None:
            interval = config.get("simulation_interval", "5m")
            try:
                btc_klines = await self._kline_cache.get_klines(
                    "BTCUSDT", interval, config["date_range_start"], config["date_range_end"]
                )
            except Exception:  # noqa: BLE001 — benchmark is best-effort, never fatal
                logger.warning("backtest_buy_hold_fetch_failed", exc_info=True)
                btc_klines = []

        if not btc_klines:
            # No benchmark data → benchmark is unknown (N/A), NOT a flat 0% return.
            metrics["buy_hold_return_pct"] = None
            metrics["buy_hold_final_value"] = None
            metrics["excess_return"] = None
            result.metrics = metrics
            return

        try:
            bh = compute_buy_hold_return(btc_klines, starting_capital)
            metrics["buy_hold_return_pct"] = bh["return_pct"]
            metrics["buy_hold_final_value"] = bh["final_value"]
            # Excess return = strategy net profit % − buy & hold return %.
            net_pct = metrics.get("net_profit_pct")
            if net_pct is not None and bh.get("return_pct") is not None:
                metrics["excess_return"] = net_pct - bh["return_pct"]
            else:
                metrics["excess_return"] = None
        except Exception:  # noqa: BLE001 — benchmark is best-effort, never fatal
            logger.warning("backtest_buy_hold_compute_failed",
                           extra={"run_id": "n/a"}, exc_info=True)
            metrics["buy_hold_return_pct"] = None
            metrics["buy_hold_final_value"] = None
            metrics["excess_return"] = None
        result.metrics = metrics

    @staticmethod
    def _check_total_kline_budget(
        config: dict[str, Any], signals: list[dict[str, Any]]
    ) -> None:
        """Reject a run whose total kline footprint would risk OOM.

        Estimates symbols × candles-per-symbol and rejects if it exceeds
        _MAX_TOTAL_KLINES — the per-symbol _MAX_CANDLES cap alone does not bound
        the product across many distinct symbols.

        Raises:
            BacktestValidationError: If the estimated total candle count is too large.
        """
        symbols = set(BacktestService._required_kline_symbols_for(config, signals))
        if not symbols:
            return
        start = config["date_range_start"]
        end = config["date_range_end"]
        days = max((end - start).total_seconds() / 86400.0, 0)
        per_day = _CANDLES_PER_DAY.get(config.get("simulation_interval", "5m"), 288)
        total = int(len(symbols) * days * per_day)
        if total > _MAX_TOTAL_KLINES:
            raise BacktestValidationError(
                f"Backtest too large: ~{total} total candles across {len(symbols)} "
                f"symbols exceeds the {_MAX_TOTAL_KLINES} limit. Narrow the date range, "
                f"use a coarser interval, or filter to fewer symbols."
            )

    @staticmethod
    def _check_kline_coverage(
        signals: list[dict[str, Any]],
        klines: dict[str, list[dict[str, Any]]],
        required_symbols: Optional[set[str] | list[str]] = None,
    ) -> None:
        """Reject a run when >20% of required symbols have no kline data.

        Raises:
            BacktestValidationError: If more than 20% of the symbols referenced by
            the signals have empty kline data — the simulation would be misleading.
        """
        symbols = (
            {str(sym) for sym in required_symbols if sym}
            if required_symbols is not None
            else {s["ticker"] for s in signals if s.get("ticker")}
        )
        if not symbols:
            return
        missing = [sym for sym in symbols if not klines.get(sym)]
        missing_pct = len(missing) / len(symbols) * 100
        if missing_pct > 20:
            raise BacktestValidationError(
                f"Insufficient kline data: {len(missing)}/{len(symbols)} symbols "
                f"({missing_pct:.0f}%) have no cached candles. Warm the cache first "
                f"(GET /backtest-cache/status to check coverage)."
            )

    async def _persist_results(self, run_id: str, result: Any,
                               replay_comparison: Optional[dict[str, Any]] = None) -> None:
        """Persist the simulation output atomically: results row + per-trade rows.

        Wrapped in a single transaction so a trade-insert failure can never leave
        an orphan results row with zero trades. Trades are delete-before-insert so
        re-persisting a run is idempotent (mirrors the results ON CONFLICT upsert).

        per_trade detail is intentionally NOT duplicated into the metrics JSONB;
        the full trade rows live in backtest_trades for the paginated trade list.
        Numeric values are converted to Decimal — asyncpg's NUMERIC codec rejects
        raw Python floats.
        """
        from decimal import Decimal

        def _num(v: Any) -> Any:
            # asyncpg NUMERIC columns require Decimal, not float. Decimal(str(x))
            # avoids binary-float artifacts (Decimal(0.1) != Decimal("0.1")).
            # CRITICAL: reject non-finite values — Decimal(str(inf)) yields
            # Decimal('Infinity') / Decimal('NaN'), which a NUMERIC column rejects on
            # PostgreSQL < 14, aborting the ENTIRE persist transaction and losing a
            # completed simulation. The engine guards its divisors, but this is the
            # persistence boundary and must self-defend.
            if v is None:
                return None
            try:
                d = Decimal(str(v))
            except (ValueError, TypeError, ArithmeticError):
                return None
            return d if d.is_finite() else None

        # Strip the per_trade array out of the metrics JSONB — the full per-trade
        # detail is persisted relationally in backtest_trades (and the cumulative
        # series is reconstructable from there). Storing the 50k-entry array in the
        # JSONB cell would duplicate the trades table and bloat every results read.
        metrics = dict(result.metrics or {})
        metrics.pop("per_trade", None)
        # Route the equity curve through _json_safe (same as metrics) before
        # serialization: it normalizes datetimes to ISO-8601 with a 'T' separator
        # (consistent with the rest of the payload; the raw str(datetime) "space"
        # form fails Date parsing in Safari) and coerces any non-finite equity to
        # None so a NaN/Inf can never emit invalid JSON that asyncpg would reject.
        from backend.services.backtest_metrics import _json_safe
        equity_curve = _json_safe(result.equity_curve or [])
        warnings = result.warnings or []
        # summary carries filter_stats; in replay mode we NEST the live-vs-backtest
        # comparison under "replay_comparison" so we never clobber filter_stats (the
        # normal path passes replay_comparison=None → unchanged).
        summary = dict(result.filter_stats or {})
        if replay_comparison is not None:
            summary["replay_comparison"] = replay_comparison
        trades = result.trades or []

        records = [
            (
                run_id, t.get("symbol"), t.get("side"),
                _num(t.get("entry_price")), _num(t.get("exit_price")),
                _num(t.get("qty")), t.get("leverage"),
                t.get("entry_time"), t.get("exit_time"),
                _num(t.get("pnl")), _num(t.get("pnl_pct")), _num(t.get("fees_paid")),
                t.get("close_reason"), _num(t.get("mfe_pct")), _num(t.get("mae_pct")),
                t.get("signal_score"), t.get("signal_confidence"), t.get("scan_id"),
                t.get("strategy_kind") or "trend",
            )
            for t in trades
        ]

        async with self._db.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                    INSERT INTO backtest_results (run_id, metrics, equity_curve, summary, warnings)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (run_id) DO UPDATE
                      SET metrics = EXCLUDED.metrics, equity_curve = EXCLUDED.equity_curve,
                          summary = EXCLUDED.summary, warnings = EXCLUDED.warnings
                    """,
                run_id,
                json.dumps(metrics, default=str),
                json.dumps(equity_curve, default=str),
                json.dumps(_json_safe(summary), default=str),
                json.dumps(warnings, default=str),
            )
            # Idempotent: clear any prior trades for this run before inserting.
            await conn.execute("DELETE FROM backtest_trades WHERE run_id = $1", run_id)
            if records:
                await conn.executemany(
                    """
                        INSERT INTO backtest_trades
                          (run_id, symbol, side, entry_price, exit_price, qty, leverage,
                           entry_time, exit_time, pnl, pnl_pct, fees_paid, close_reason,
                           mfe_pct, mae_pct, signal_score, signal_confidence, scan_id,
                           strategy_kind)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                        """,
                    records,
                )
            # Flip status to 'completed' IN THE SAME TRANSACTION so the
            # invariant "results exist ⟺ status=completed" is atomic — a DB
            # blip can't leave results committed with status=failed/running.
            # guard_cancel is intentionally absent: completion wins over a late
            # cancel (the work is done; mid-sim cancels never reach persist).
            await conn.execute(
                "UPDATE backtest_runs SET status = 'completed', "
                "completed_at = now(), progress_pct = 100, error_message = NULL WHERE id = $1",
                run_id,
            )


    async def get_backtest_trades(
        self,
        run_id: str,
        page: int = 1,
        limit: int = 50,
        sort_by: str = "entry_time",
        side: Optional[str] = None,
        close_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return a paginated, filterable slice of a run's trades.

        Returns:
            {trades: [...], total: int, page: int} — total is the FILTERED count.
        """
        # Whitelist sort columns to avoid SQL injection on an interpolated ORDER BY
        sort_col = {
            "entry_time": "entry_time", "exit_time": "exit_time",
            "pnl": "pnl", "pnl_pct": "pnl_pct", "symbol": "symbol",
        }.get(sort_by, "entry_time")

        where = ["run_id = $1"]
        params: list[Any] = [run_id]
        if side is not None:
            params.append(side)
            where.append(f"side = ${len(params)}")
        if close_reason is not None:
            params.append(close_reason)
            where.append(f"close_reason = ${len(params)}")
        where_sql = " AND ".join(where)

        total_row = await self._db.pool.fetchrow(
            f"SELECT COUNT(*) AS n FROM backtest_trades WHERE {where_sql}", *params
        )
        total = total_row["n"] if total_row else 0

        page = max(page, 1)
        limit = max(min(limit, 500), 1)
        offset = (page - 1) * limit
        params.extend([limit, offset])
        rows = await self._db.pool.fetch(
            f"""
            SELECT id, symbol, side, entry_price, exit_price, qty, leverage,
                   entry_time, exit_time, pnl, pnl_pct, fees_paid, close_reason,
                   mfe_pct, mae_pct, signal_score, signal_confidence, scan_id,
                   strategy_kind
            FROM backtest_trades
            WHERE {where_sql}
            ORDER BY {sort_col} ASC, id ASC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """,
            *params,
        )
        trades = [self._trade_row_to_dict(r) for r in rows]
        return {"trades": trades, "total": total, "page": page}

    @staticmethod
    def _trade_row_to_dict(row: Any) -> dict[str, Any]:
        def _f(v: Any) -> Any:
            return float(v) if v is not None else None
        return {
            "id": row["id"], "symbol": row["symbol"], "side": row["side"],
            "entry_price": _f(row["entry_price"]), "exit_price": _f(row["exit_price"]),
            "qty": _f(row["qty"]), "leverage": row["leverage"],
            "entry_time": row["entry_time"], "exit_time": row["exit_time"],
            "pnl": _f(row["pnl"]), "pnl_pct": _f(row["pnl_pct"]),
            "fees_paid": _f(row["fees_paid"]), "close_reason": row["close_reason"],
            "mfe_pct": _f(row["mfe_pct"]), "mae_pct": _f(row["mae_pct"]),
            "signal_score": row["signal_score"], "signal_confidence": row["signal_confidence"],
            "scan_id": row["scan_id"],
            # strategy that produced the trade (F2 validation). The column is NOT NULL
            # with a 'trend' default (migration 51), so this is always a concrete value.
            "strategy_kind": row["strategy_kind"] or "trend",
        }

    # ------------------------------------------------------------------ #
    # Status transitions
    # ------------------------------------------------------------------ #

    async def _mark_status(
        self,
        run_id: str,
        status: str,
        started: bool = False,
        completed: bool = False,
        progress: Optional[int] = None,
        error: Optional[str] = None,
        guard_cancel: bool = True,
    ) -> None:
        """Transition a run's status.

        guard_cancel (default True): only apply the update if the run is NOT
        already 'cancelled'. This prevents a 'running'/'completed' transition from
        clobbering a user cancel that landed during the launch/execution gap.
        The terminal cancel/fail transitions pass guard_cancel=False so they can
        finalize the row.
        """
        sets = ["status = $2"]
        params: list[Any] = [run_id, status]
        if started:
            sets.append("started_at = now()")
        if completed:
            sets.append("completed_at = now()")
        if progress is not None:
            params.append(progress)
            sets.append(f"progress_pct = ${len(params)}")
        if error is not None:
            params.append(error)
            sets.append(f"error_message = ${len(params)}")
        where = "WHERE id = $1"
        if guard_cancel:
            where += " AND status <> 'cancelled'"
        await self._db.pool.execute(
            f"UPDATE backtest_runs SET {', '.join(sets)} {where}", *params
        )

    async def _update_progress(self, run_id: str, pct: int) -> None:
        try:
            await self._db.pool.execute(
                "UPDATE backtest_runs SET progress_pct = $2 WHERE id = $1 AND status = 'running'",
                run_id, pct,
            )
        except Exception:  # noqa: BLE001 — progress updates are best-effort
            logger.debug("backtest_progress_update_failed", extra={"run_id": run_id})

