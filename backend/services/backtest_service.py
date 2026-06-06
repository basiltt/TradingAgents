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
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Hard limit on signals loaded — prevents OOM on large date ranges
_MAX_SIGNALS = 50_000
# Max candles a single backtest may span (≈ 365 days × 288 5-min candles)
_MAX_CANDLES = 105_120
# Max TOTAL candle-rows held in memory at once (symbols × candles-per-symbol).
# Guards against OOM when a backtest touches many distinct symbols over a long
# range (the per-symbol _MAX_CANDLES cap alone doesn't bound the product).
_MAX_TOTAL_KLINES = 3_000_000
# Candles per day by simulation interval (24h)
_CANDLES_PER_DAY = {"5m": 288, "15m": 96, "1h": 24, "4h": 6}
# Concurrency / timeout
_MAX_CONCURRENT = 3
_TIMEOUT_SECONDS = 120
# Target points for the equity curve served to the frontend (LTTB downsample)
_EQUITY_TARGET_POINTS = 2000
# Per-client create rate limit: max creates in a sliding window
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW_SECONDS = 3600


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

    def __init__(self, db: Any, kline_cache: Any = None, instrument_cache: Any = None) -> None:
        self._db = db
        self._kline_cache = kline_cache
        # Per-symbol instrument parameters (qty_step/min_qty/tick_size/max_leverage)
        # used to make sizing/leverage/TP-SL rounding match the live exchange. Lazily
        # created if not injected; refreshed best-effort before each run.
        self._instrument_cache = instrument_cache
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
        return {
            "metrics": self._coerce_json(row["metrics"]) or {},
            "equity_curve": self._downsample_equity(equity),
            "summary": self._coerce_json(row["summary"]) or {},
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

    async def _load_signals(
        self,
        scan_source: dict[str, Any],
        date_range: tuple[datetime, datetime],
    ) -> list[dict[str, Any]]:
        """Load historical scan result signals for the backtest engine.

        Supports 3 modes:
        - "schedule": Load all scan results from a specific scheduled scanner
        - "date_range": Load all scan results within date range (any scanner)
        - "explicit": Load scan results from specific scan IDs

        The query JOINs scan_results with scans to get signal timestamps,
        since scan_results has no timestamp column itself.

        signal_time is anchored to the scan's COMPLETED_AT (the moment production
        actually placed the trade — execute_batch runs after the full per-ticker
        analysis finishes), NOT started_at. Anchoring at scan start would enter every
        trade at a pre-analysis price the live account never got (the scan takes
        minutes), systematically inflating PnL. COALESCE falls back to started_at for
        any legacy scan missing completed_at. The date-range WHERE still filters on
        started_at (the user picks the window by when scans RAN). A deterministic
        `, sr.id` tiebreak makes the per-scan ordering stable on equal abs(score).

        Returns:
            List of signal dicts with: id, ticker, direction, confidence,
            score, signal_time, scan_id, signal_source, analysis_price.
        """
        mode = scan_source.get("mode", "date_range")
        start, end = date_range

        if mode == "schedule":
            schedule_id = scan_source.get("schedule_id")
            query = f"""
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                WHERE s.schedule_id = $1
                  AND s.started_at::timestamptz >= $2
                  AND s.started_at::timestamptz <= $3
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY signal_time, ABS(sr.score) DESC, sr.id
                LIMIT {_MAX_SIGNALS}
            """
            rows = await self._db.pool.fetch(query, schedule_id, start, end)

        elif mode == "explicit":
            scan_ids = scan_source.get("scan_ids", [])
            query = f"""
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                WHERE s.scan_id = ANY($1)
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY signal_time, ABS(sr.score) DESC, sr.id
                LIMIT {_MAX_SIGNALS}
            """
            rows = await self._db.pool.fetch(query, scan_ids)

        else:  # date_range (default)
            query = f"""
                SELECT sr.id, sr.ticker, sr.direction, sr.confidence, sr.score,
                       COALESCE(s.completed_at, s.started_at)::timestamptz AS signal_time,
                       s.scan_id, sr.signal_source, sr.analysis_price
                FROM scan_results sr
                JOIN scans s ON sr.scan_id = s.scan_id
                WHERE s.started_at::timestamptz >= $1
                  AND s.started_at::timestamptz <= $2
                  AND sr.status = 'completed'
                  AND sr.direction IN ('buy', 'sell')
                ORDER BY signal_time, ABS(sr.score) DESC, sr.id
                LIMIT {_MAX_SIGNALS}
            """
            rows = await self._db.pool.fetch(query, start, end)

        # Convert asyncpg Records to plain dicts
        signals = []
        for row in rows:
            signals.append({
                "id": row["id"],
                "ticker": row["ticker"],
                "direction": row["direction"],
                "confidence": row["confidence"],
                "score": row["score"],
                "signal_time": row["signal_time"],
                "scan_id": row["scan_id"],
                "signal_source": row.get("signal_source", "unknown"),
                "analysis_price": float(row["analysis_price"]) if row.get("analysis_price") else None,
            })

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
        from backend.services.backtest_engine import BacktestEngine, BacktestCancelled

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

            signals = await self._load_signals(
                config.get("scan_source", {}),
                (config["date_range_start"], config["date_range_end"]),
            )
            # Bound total kline memory BEFORE loading (symbols × candles-per-symbol)
            # so a many-symbol long-range backtest can't OOM the process.
            self._check_total_kline_budget(config, signals)
            klines = await self._load_klines(config, signals)
            logger.info("backtest_started", extra={
                "run_id": run_id, "n_signals": len(signals), "n_symbols": len(klines),
            })

            # Coverage guard: if >20% of required symbols have NO kline data, the
            # backtest would be misleading (most signals un-simulatable). Fail it
            # with a clear message rather than silently producing garbage. The
            # frontend can pre-check via GET /backtest-cache/status to avoid this.
            self._check_kline_coverage(signals, klines)

            def _on_timeout() -> None:
                timed_out.set()
                cancel_event.set()

            timer = threading.Timer(_TIMEOUT_SECONDS, _on_timeout)
            timer.daemon = True
            timer.start()

            loop = asyncio.get_running_loop()
            progress_state = {"last": 0}

            def _on_progress(pct: int) -> None:
                # Runs in the POOL WORKER THREAD — hop to the event loop to schedule
                # the async DB write. Best-effort: if the loop is closing during
                # shutdown, call_soon_threadsafe raises; swallow it so progress
                # reporting can never abort an otherwise-healthy simulation.
                if pct - progress_state["last"] < 5 and pct < 100:
                    return
                progress_state["last"] = pct
                try:
                    loop.call_soon_threadsafe(self._schedule_progress, run_id, pct)
                except RuntimeError:
                    pass  # loop closed — drop this progress update

            # Resolve per-symbol instrument parameters (qty step, min qty, tick size,
            # max leverage) so the engine sizes, caps leverage, and rounds TP/SL the
            # way the live exchange does. Best-effort: if the cache/network is
            # unavailable the engine falls back to no-op defaults (unchanged behaviour).
            instrument_info = await self._resolve_instrument_info(signals)

            engine = BacktestEngine()
            result = await loop.run_in_executor(
                self._executor,
                lambda: engine.run(config, signals, klines, cancel_event, _on_progress, instrument_info),
            )
            engine_done = True

            # Surface config knobs the engine cannot honor so results aren't
            # silently misleading. max_same_sector needs the IO-bound sector
            # service (unavailable to the pure engine), so live trading enforces it
            # but the backtest does not — warn when the user set it.
            if config.get("max_same_sector") is not None and result.warnings is not None:
                result.warnings.append("max_same_sector_not_enforced")

            # Surface signals that were dropped purely because the symbol had no cached
            # candles — production would have traded them, so the backtest UNDER-trades
            # here. This is data coverage, not a strategy filter, so the user must know.
            no_kline = (result.filter_stats or {}).get("signals_no_kline", 0)
            if no_kline and result.warnings is not None:
                result.warnings.append(f"signals_dropped_no_kline_data_{no_kline}")

            # Buy & Hold benchmark + excess return (Phase 4 carry-forward):
            # compare the strategy against simply holding BTC over the same window.
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

        except BacktestCancelled:
            if timed_out.is_set():
                logger.warning("backtest_timed_out",
                               extra={"run_id": run_id, "timeout_s": _TIMEOUT_SECONDS})
                await self._mark_status(
                    run_id, "failed", completed=True, guard_cancel=False,
                    error=f"Backtest exceeded the {_TIMEOUT_SECONDS}s time limit.",
                )
            else:
                logger.info("backtest_cancelled", extra={"run_id": run_id})
                await self._mark_status(run_id, "cancelled", completed=True, guard_cancel=False)
        except BacktestValidationError as exc:
            # A pre-flight validation failure (e.g. insufficient kline coverage) —
            # surface the clean, user-facing message rather than mangling it through
            # the generic "simulation error: ..." path.
            logger.info("backtest_validation_failed",
                        extra={"run_id": run_id, "reason": str(exc)[:200]})
            await self._mark_status(run_id, "failed", completed=True, error=str(exc)[:480])
        except Exception as exc:  # noqa: BLE001 — must never crash the service
            # Distinguish a SIMULATION failure from a POST-simulation persistence
            # failure: the latter still means the backtest computed successfully.
            phase = "persistence" if engine_done else "simulation"
            # Log the full exception server-side, but store only a generic,
            # disclosure-safe message in the user-visible error_message column.
            logger.exception("backtest_execution_failed",
                             extra={"run_id": run_id, "phase": phase})
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

    def _schedule_progress(self, run_id: str, pct: int) -> None:
        """Schedule a progress DB write on the loop, keeping a strong task ref.

        asyncio holds only weak references to bare tasks, so we retain the task in
        _running_tasks until it completes to prevent mid-flight GC.
        """
        task = asyncio.ensure_future(self._update_progress(run_id, pct))
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)


    async def _load_klines(
        self, config: dict[str, Any], signals: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Load cached klines for every symbol referenced by the signals."""
        if self._kline_cache is None:
            return {}
        symbols = sorted({s["ticker"] for s in signals})
        interval = config.get("simulation_interval", "5m")
        start = config["date_range_start"]
        end = config["date_range_end"]
        klines: dict[str, list[dict[str, Any]]] = {}
        for symbol in symbols:
            klines[symbol] = await self._kline_cache.get_klines(symbol, interval, start, end)
        return klines

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
        symbols = {s["ticker"] for s in signals}
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
        signals: list[dict[str, Any]], klines: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Reject a run when >20% of required symbols have no kline data.

        Raises:
            BacktestValidationError: If more than 20% of the symbols referenced by
            the signals have empty kline data — the simulation would be misleading.
        """
        symbols = {s["ticker"] for s in signals}
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

    async def _persist_results(self, run_id: str, result: Any) -> None:
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
        summary = result.filter_stats or {}
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
            )
            for t in trades
        ]

        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
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
                           mfe_pct, mae_pct, signal_score, signal_confidence, scan_id)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
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
                    "completed_at = now(), progress_pct = 100 WHERE id = $1",
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
                   mfe_pct, mae_pct, signal_score, signal_confidence, scan_id
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

