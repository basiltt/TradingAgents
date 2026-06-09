"""Scheduled scan service — manages scheduled market scans."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from croniter import croniter

from backend.schemas import PROVIDER_API_KEY_MAP
from backend.services.scanner_service import ScannerBusyError

logger = logging.getLogger(__name__)

MAX_SCHEDULES = 20
POLL_INTERVAL_SECONDS = 30
COOLDOWN_SECONDS = 60
MAX_CONSECUTIVE_FAILURES = 3
MISSED_ONCE_WINDOW_HOURS = 24
SCAN_TIMEOUT_SECONDS = 7200
MIN_INTERVAL_MINUTES = 15
MIN_CRON_INTERVAL_SECONDS = 900
SENTINEL_STALE_SECONDS = 120


def _is_sentinel(val: Any) -> bool:
    return isinstance(val, datetime)


class ScanSchedulerService:
    """Manages scheduled market scans: CRUD, the polling loop, and execution.

    Tracks in-flight runs to enforce single-flight execution, computes next-run
    times from interval/cron/daily/weekly/once schedules, and optionally
    notifies the AI manager service when active schedules change.
    """

    def __init__(self, scanner_service: Any, db: Any, config_service: Any, ai_manager_service: Any = None):
        self._scanner = scanner_service
        self._db = db
        self._config = config_service
        self._ai_manager_service = ai_manager_service
        self._loop_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._in_flight: Dict[str, Any] = {}  # schedule_id -> exec_id (int/str) or sentinel datetime
        self._last_cleanup: Optional[datetime] = None

    def set_ai_manager_service(self, ai_manager_service: Any) -> None:
        """Inject the AI manager service (resolves a startup wiring cycle)."""
        self._ai_manager_service = ai_manager_service

    # ── CRUD ─────────────────────────────────────────────────────────

    def _validate_schedule(self, schedule_type: str, schedule_config: Dict[str, Any]) -> None:
        if schedule_type == "interval":
            mins = schedule_config.get("interval_minutes", 0)
            if mins < MIN_INTERVAL_MINUTES:
                raise ValueError(f"Interval must be at least {MIN_INTERVAL_MINUTES} minutes")
        elif schedule_type == "cron":
            expr = schedule_config.get("cron_expression", "")
            if expr:
                self._validate_cron_frequency(expr)
        if schedule_type in ("daily", "weekly"):
            time_str = schedule_config.get("time", "09:00")
            if not re.match(r"^\d{2}:\d{2}$", time_str):
                raise ValueError("time must be in HH:MM format")
            h, m = map(int, time_str.split(":"))
            if h > 23 or m > 59:
                raise ValueError("Invalid time value")

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create and persist a new schedule; return the stored row.

        Validates the schedule timing, enforces the MAX_SCHEDULES cap (raising
        ValueError when exceeded), resolves the scan config (injecting API keys),
        computes the first next_run_at, and triggers AI-manager reconciliation.
        """
        self._validate_schedule(data["schedule_type"], data.get("schedule_config", {}))
        count = await self._db.count_scheduled_scans()
        if count >= MAX_SCHEDULES:
            raise ValueError(f"Maximum of {MAX_SCHEDULES} schedules reached")

        scan_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        schedule = {
            "id": scan_id,
            "name": data["name"],
            "schedule_type": data["schedule_type"],
            "schedule_config": data["schedule_config"],
            "scan_config": self._resolve_scan_config(data["scan_config"]),
            "status": "active",
            "timezone": data.get("timezone", "UTC"),
            "next_run_at": None,
            "created_at": now,
            "updated_at": now,
        }

        schedule["next_run_at"] = self._compute_next_run(schedule)
        await self._db.insert_scheduled_scan(schedule)
        logger.info("Created schedule %s (%s)", scan_id, data["name"])
        if self._ai_manager_service:
            asyncio.create_task(self._ai_manager_service.reconcile_active_schedules())
        return await self._db.get_scheduled_scan(scan_id)

    async def update(self, scan_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing schedule and return the stored row.

        Raises KeyError if the schedule is missing. Preserves the existing LLM
        API key when a masked/blank one is sent, resets consecutive_failures,
        and only recomputes next_run_at when a timing field actually changed.
        """
        existing = await self._db.get_scheduled_scan(scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")

        updates: Dict[str, Any] = {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for k in ("name", "schedule_type", "schedule_config", "scan_config", "timezone"):
            if k in fields and fields[k] is not None:
                updates[k] = fields[k]

        if "scan_config" in updates:
            updates["scan_config"] = self._resolve_scan_config(updates["scan_config"])
            new_key = updates["scan_config"].get("llm_api_key")
            if not new_key or new_key == "***":
                old_key = existing.get("scan_config", {}).get("llm_api_key")
                if old_key:
                    updates["scan_config"]["llm_api_key"] = old_key
                elif "llm_api_key" in updates["scan_config"]:
                    del updates["scan_config"]["llm_api_key"]

        updates["consecutive_failures"] = 0
        updates["updated_at"] = now

        merged = {**existing, **updates}

        self._validate_schedule(merged["schedule_type"], merged.get("schedule_config", {}))

        # Only recompute next_run_at when a TIMING field actually changed in
        # value. The edit form re-sends schedule_type/schedule_config/timezone
        # unchanged on every save, so recomputing unconditionally would reset the
        # countdown to a full interval: _compute_next_run anchors intervals to
        # max(now, last_run_at), and after a run last_run_at is in the past, so
        # the anchor collapses to "now" and the next run jumps out by a whole
        # interval instead of preserving the time already remaining.
        timing_changed = any(
            existing.get(k) != merged.get(k)
            for k in ("schedule_type", "schedule_config", "timezone")
        )
        if timing_changed:
            updates["next_run_at"] = self._compute_next_run(merged)

        await self._db.update_scheduled_scan(scan_id, updates)
        logger.info("Updated schedule %s", scan_id)
        if self._ai_manager_service:
            asyncio.create_task(self._ai_manager_service.reconcile_active_schedules())
        return await self._db.get_scheduled_scan(scan_id)

    async def delete(self, scan_id: str) -> bool:
        """Delete a schedule, clear any in-flight marker, and reconcile.

        Returns True if a row was deleted, False otherwise.
        """
        result = await self._db.delete_scheduled_scan(scan_id)
        if result:
            self._in_flight.pop(scan_id, None)
            logger.info("Deleted schedule %s", scan_id)
            if self._ai_manager_service:
                asyncio.create_task(self._ai_manager_service.reconcile_active_schedules())
        return result

    async def list_all(self) -> List[Dict[str, Any]]:
        """Return all scheduled scans."""
        return await self._db.list_scheduled_scans()

    def get_running_schedule_ids(self) -> set:
        """Return the set of schedule ids with a run currently in flight."""
        return set(self._in_flight.keys())

    async def get(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Return a single schedule by id, or None if not found."""
        return await self._db.get_scheduled_scan(scan_id)

    async def pause(self, scan_id: str) -> Dict[str, Any]:
        """Pause an active/error schedule, clearing its next_run_at.

        Raises KeyError if missing, or ValueError if the schedule is not in an
        'active' or 'error' status. Returns the updated row.
        """
        existing = await self._db.get_scheduled_scan(scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")
        if existing["status"] not in ("active", "error"):
            raise ValueError(f"Cannot pause schedule in '{existing['status']}' status")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self._db.update_scheduled_scan(
            scan_id,
            {"status": "paused", "next_run_at": None, "updated_at": now},
        )
        logger.info("Paused schedule %s", scan_id)
        if self._ai_manager_service:
            asyncio.create_task(self._ai_manager_service.reconcile_active_schedules())
        return await self._db.get_scheduled_scan(scan_id)

    async def resume(self, scan_id: str) -> Dict[str, Any]:
        """Reactivate a paused/error/cancelled schedule and recompute next_run_at.

        Raises KeyError if missing, or ValueError if the status is not
        resumable. For 'once' schedules whose computed next run is already in
        the past, schedules it immediately. Returns the updated row.
        """
        existing = await self._db.get_scheduled_scan(scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")
        if existing["status"] not in ("paused", "error", "cancelled"):
            raise ValueError(f"Cannot resume schedule in '{existing['status']}' status")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        next_run = self._compute_next_run(existing)
        if existing["schedule_type"] == "once" and next_run:
            parsed = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
            if parsed < datetime.now(timezone.utc):
                next_run = now
        await self._db.update_scheduled_scan(
            scan_id,
            {"status": "active", "next_run_at": next_run, "consecutive_failures": 0, "updated_at": now},
        )
        logger.info("Resumed schedule %s", scan_id)
        if self._ai_manager_service:
            asyncio.create_task(self._ai_manager_service.reconcile_active_schedules())
        return await self._db.get_scheduled_scan(scan_id)

    async def trigger(self, scan_id: str) -> Dict[str, Any]:
        """Run a schedule immediately ("run now"); return the updated row.

        Raises KeyError if missing, or ValueError if the schedule is
        completed/cancelled, another scan is already in flight, or the 60s
        cooldown since the last run has not elapsed. Clears the in-flight
        sentinel and re-raises on execution failure.
        """
        existing = await self._db.get_scheduled_scan(scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")
        if existing["status"] in ("completed", "cancelled"):
            raise ValueError(f"Cannot trigger a {existing['status']} schedule")
        if self._in_flight:
            raise ValueError("Another scheduled scan is currently running — please wait for it to complete")

        if existing["last_run_at"]:
            last = datetime.fromisoformat(existing["last_run_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last).total_seconds() < COOLDOWN_SECONDS:
                raise ValueError("Cooldown: must wait 60 seconds between triggers")

        # AI-CONTEXT: cross-instance claim. The _in_flight + cooldown checks above are
        # per-PROCESS; in a multi-instance deployment two instances could each pass
        # them and double-fire the same schedule. claim_manual_trigger does a DB CAS on
        # last_run_at (stamp only if unchanged since we read it), so exactly one caller
        # wins — the same single-runner guarantee the scheduled loop gets from
        # claim_scheduled_scan.
        claimed = await self._db.claim_manual_trigger(scan_id, existing.get("last_run_at"))
        if not claimed:
            raise ValueError("Another runner already triggered this schedule — please wait")

        self._in_flight[scan_id] = datetime.now(timezone.utc)  # sentinel to prevent concurrent execution
        try:
            await self._execute_schedule(existing, triggered_by="run_now")
        except Exception:
            if _is_sentinel(self._in_flight.get(scan_id)):
                del self._in_flight[scan_id]
            raise
        return await self._db.get_scheduled_scan(scan_id)

    async def list_executions(self, schedule_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent execution records for a schedule, newest first."""
        return await self._db.list_schedule_executions(schedule_id, limit)

    # ── Scheduler Loop ───────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler poll loop (idempotent if already running)."""
        if self._loop_task and not self._loop_task.done():
            return
        self._shutdown_event.clear()
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler loop started")

    async def shutdown(self) -> None:
        """Stop the poll loop and mark any in-flight executions cancelled."""
        self._shutdown_event.set()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for _schedule_id, exec_id in list(self._in_flight.items()):
            if not _is_sentinel(exec_id):
                try:
                    await self._db.update_schedule_execution(
                        exec_id,
                        {"status": "cancelled", "completed_at": now,
                         "error_message": "Service shutting down"},
                    )
                except Exception:
                    logger.warning("Failed to mark execution %s as cancelled on shutdown", exec_id)
        self._in_flight.clear()

        logger.info("Scheduler loop stopped")

    async def _scheduler_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._check_in_flight_completions()
            except Exception:
                logger.exception("Error checking in-flight completions")

            try:
                # Global concurrency gate: only one scheduled scan at a time
                if self._in_flight:
                    logger.debug("Scheduler: scan in-flight, deferring due schedules")
                else:
                    due = await self._db.get_due_scheduled_scans()
                    for schedule in due:
                        if self._shutdown_event.is_set():
                            break
                        if self._in_flight:
                            break  # just launched one — wait for next cycle
                        if schedule["id"] in self._in_flight:
                            continue
                        await self._try_execute(schedule)

                await self._maybe_cleanup()
            except Exception:
                logger.exception("Scheduler loop error")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=POLL_INTERVAL_SECONDS
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _try_execute(self, schedule: Dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        schedule_for_next = {**schedule, "last_run_at": now_str}
        next_run = self._compute_next_run(schedule_for_next) if schedule["schedule_type"] != "once" else None

        claimed = await self._db.claim_scheduled_scan(
            schedule["id"],
            schedule["next_run_at"],
            next_run,
        )
        if not claimed:
            return

        self._in_flight[schedule["id"]] = datetime.now(timezone.utc)  # sentinel until _execute_schedule sets real exec_id
        try:
            await self._execute_schedule(schedule, triggered_by="scheduled")
        except Exception:
            if _is_sentinel(self._in_flight.get(schedule["id"])):
                del self._in_flight[schedule["id"]]
            raise

    async def _execute_schedule(self, schedule: Dict[str, Any], triggered_by: str = "scheduled") -> None:
        schedule_id = schedule["id"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        scan_config = dict(schedule.get("scan_config", {}))

        if not scan_config.get("analysis_date"):
            scan_config["analysis_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        provider = scan_config.get("provider")
        if not provider:
            resolved = self._config.get_config()["resolved"]
            provider = resolved.get("llm_provider", "openai")

        env_key = PROVIDER_API_KEY_MAP.get(provider)
        backend_url = scan_config.get("backend_url")
        has_api_key = scan_config.get("llm_api_key") or (env_key and os.getenv(env_key))
        if env_key and not backend_url and not has_api_key:
            self._in_flight.pop(schedule_id, None)
            await self._db.insert_schedule_execution(
                {"schedule_id": schedule_id, "status": "skipped_no_key",
                 "started_at": now, "completed_at": now,
                 "error_message": f"API key {env_key} not set"},
            )
            logger.warning("Schedule %s skipped: %s not set", schedule_id, env_key)
            if schedule["schedule_type"] == "once":
                await self._db.update_scheduled_scan(
                    schedule_id,
                    {"status": "error", "next_run_at": None, "updated_at": now},
                )
            return

        exec_id = await self._db.insert_schedule_execution({"schedule_id": schedule_id, "status": "started", "started_at": now})

        try:
            scan_id = await self._scanner.start_scan(
                scan_config, schedule_id=schedule_id, triggered_by=triggered_by,
            )
            await self._db.update_schedule_execution(
                exec_id,
                {"scan_id": scan_id, "status": "started"},
            )
            update_fields: Dict[str, Any] = {
                "last_scan_id": scan_id,
                "last_run_at": now,
                "updated_at": now,
            }
            await self._db.update_scheduled_scan(schedule_id, update_fields)
            self._in_flight[schedule_id] = exec_id
            logger.info("Schedule %s fired scan %s", schedule_id, scan_id)

        except ScannerBusyError:
            self._in_flight.pop(schedule_id, None)
            await self._db.update_schedule_execution(
                exec_id,
                {"status": "skipped_busy", "completed_at": now,
                 "error_message": "Scanner busy"},
            )
            if schedule["schedule_type"] == "once":
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=COOLDOWN_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
                await self._db.update_scheduled_scan(
                    schedule_id,
                    {"next_run_at": retry_at, "updated_at": now},
                )
            logger.info("Schedule %s skipped: scanner busy", schedule_id)

        except Exception as e:
            self._in_flight.pop(schedule_id, None)
            error_msg = self._sanitize_error(str(e))
            await self._db.update_schedule_execution(
                exec_id,
                {"status": "failed", "completed_at": now, "error_message": error_msg},
            )
            if schedule["schedule_type"] == "once":
                await self._db.update_scheduled_scan(
                    schedule_id,
                    {"status": "error", "next_run_at": None, "updated_at": now},
                )
            else:
                await self._record_failure(schedule_id)
            logger.exception("Schedule %s execution failed", schedule_id)

    async def _check_in_flight_completions(self) -> None:
        completed = []
        for schedule_id, exec_id in list(self._in_flight.items()):
            if _is_sentinel(exec_id):
                age = (datetime.now(timezone.utc) - exec_id).total_seconds()
                if age < SENTINEL_STALE_SECONDS:
                    continue
                logger.warning("Stale sentinel in _in_flight for %s (%.0fs old), removing", schedule_id, age)
                completed.append(schedule_id)
                continue

            schedule = await self._db.get_scheduled_scan(schedule_id)
            if not schedule or not schedule.get("last_scan_id"):
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await self._db.update_schedule_execution(
                    exec_id,
                    {"status": "cancelled", "completed_at": now,
                     "error_message": "Schedule deleted while scan was running"},
                )
                completed.append(schedule_id)
                continue

            scan = await self._scanner.get_scan(schedule["last_scan_id"])
            if not scan:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await self._db.update_schedule_execution(
                    exec_id,
                    {"status": "failed", "completed_at": now,
                     "error_message": "Scan record not found"},
                )
                completed.append(schedule_id)
                continue

            if scan.get("status") in ("completed", "failed", "cancelled"):
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                status = scan["status"]

                await self._db.update_schedule_execution(
                    exec_id,
                    {"status": status, "completed_at": now},
                )

                if schedule.get("status") == "paused":
                    if status == "completed":
                        await self._db.update_scheduled_scan(
                            schedule_id,
                            {"consecutive_failures": 0, "updated_at": now},
                        )
                elif status == "failed":
                    if schedule.get("schedule_type") == "once":
                        await self._db.update_scheduled_scan(
                            schedule_id,
                            {"status": "error", "next_run_at": None, "consecutive_failures": schedule.get("consecutive_failures", 0) + 1, "updated_at": now},
                        )
                    else:
                        await self._record_failure(schedule_id)
                elif status == "cancelled":
                    if schedule.get("schedule_type") == "once":
                        await self._db.update_scheduled_scan(
                            schedule_id,
                            {"status": "cancelled", "next_run_at": None, "updated_at": now},
                        )
                elif status == "completed":
                    updates: Dict[str, Any] = {"consecutive_failures": 0, "updated_at": now}
                    if schedule.get("schedule_type") == "once":
                        updates["status"] = "completed"
                        updates["next_run_at"] = None
                    await self._db.update_scheduled_scan(schedule_id, updates)

                completed.append(schedule_id)
            else:
                # Timeout: cancel scan if running longer than SCAN_TIMEOUT_SECONDS
                started_at = scan.get("started_at") or scan.get("created_at")
                if started_at:
                    try:
                        start_dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                        elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
                        if elapsed > SCAN_TIMEOUT_SECONDS:
                            logger.warning("Scan %s timed out (%.0fs > %ds), cancelling", scan.get("id"), elapsed, SCAN_TIMEOUT_SECONDS)
                            try:
                                await self._scanner.cancel_scan(scan["id"])
                            except Exception:
                                pass
                            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            await self._db.update_schedule_execution(
                                exec_id,
                                {"status": "failed", "completed_at": now, "error_message": f"Scan timed out after {int(elapsed)}s"},
                            )
                            completed.append(schedule_id)
                    except (ValueError, TypeError):
                        pass

        for sid in completed:
            self._in_flight.pop(sid, None)
        if completed and self._ai_manager_service:
            asyncio.create_task(self._ai_manager_service.reconcile_active_schedules())

    async def _record_failure(self, schedule_id: str) -> None:
        schedule = await self._db.get_scheduled_scan(schedule_id)
        if not schedule:
            return
        failures = schedule.get("consecutive_failures", 0) + 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        updates: Dict[str, Any] = {"consecutive_failures": failures, "updated_at": now}
        if failures >= MAX_CONSECUTIVE_FAILURES:
            updates["status"] = "error"
            updates["next_run_at"] = None
            logger.warning("Schedule %s auto-paused after %d failures", schedule_id, failures)
        await self._db.update_scheduled_scan(schedule_id, updates)

    # ── Recovery ─────────────────────────────────────────────────────

    async def recover_on_startup(self) -> None:
        """Reconcile schedules whose next_run_at was missed while the service was down.

        Replays at most one recently-missed 'once' schedule (within the missed
        window), marks older 'once' schedules completed, rolls recurring
        schedules forward to their next run, and flags orphaned executions failed.
        """
        schedules = await self._db.list_scheduled_scans()
        now = datetime.now(timezone.utc)
        replayed = 0

        for schedule in schedules:
            if schedule["status"] != "active":
                continue
            if not schedule.get("next_run_at"):
                continue

            next_run = datetime.fromisoformat(schedule["next_run_at"].replace("Z", "+00:00"))
            if next_run >= now:
                continue

            if schedule["schedule_type"] == "once":
                age = now - next_run
                if age <= timedelta(hours=MISSED_ONCE_WINDOW_HOURS) and replayed < 1:
                    logger.info("Replaying missed once schedule %s", schedule["id"])
                    self._in_flight[schedule["id"]] = datetime.now(timezone.utc)
                    try:
                        await self._execute_schedule(schedule, triggered_by="scheduled")
                    except Exception:
                        if _is_sentinel(self._in_flight.get(schedule["id"])):
                            del self._in_flight[schedule["id"]]
                        logger.exception("Recovery replay failed for schedule %s", schedule["id"])
                    replayed += 1
                else:
                    await self._db.update_scheduled_scan(
                        schedule["id"],
                        {"status": "completed", "next_run_at": None,
                         "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                    )
            else:
                new_next = self._compute_next_run(schedule)
                await self._db.update_scheduled_scan(
                    schedule["id"],
                    {"next_run_at": new_next,
                     "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                )
                logger.info("Schedule %s: skipped to next run %s", schedule["id"], new_next)

        logger.info("Recovery complete: %d schedules processed", len(schedules))

        orphaned = await self._db.mark_orphaned_executions()
        if orphaned:
            logger.info("Marked %d orphaned executions as failed", orphaned)

    async def _maybe_cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_cleanup and (now - self._last_cleanup) < timedelta(hours=24):
            return
        self._last_cleanup = now
        deleted = await self._db.cleanup_old_executions()
        if deleted:
            logger.info("Cleaned up %d old executions", deleted)

    # ── next_run_at Calculation ──────────────────────────────────────

    def _compute_next_run(self, schedule: Dict[str, Any]) -> Optional[str]:
        stype = schedule["schedule_type"]
        config = schedule.get("schedule_config", {})
        tz_name = schedule.get("timezone", "UTC")

        import pytz
        tz = pytz.timezone(tz_name)
        now = datetime.now(timezone.utc)

        if stype == "once":
            run_at = config.get("run_at")
            if not run_at:
                return None
            dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = tz.localize(dt)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        elif stype == "interval":
            minutes = config.get("interval_minutes", 60)
            base = now
            if schedule.get("last_run_at"):
                last = datetime.fromisoformat(schedule["last_run_at"].replace("Z", "+00:00"))
                base = max(now, last)
            return (base + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        elif stype == "daily":
            time_str = config.get("time", "09:00")
            days = config.get("days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
            day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            h, m = map(int, time_str.split(":"))

            now_local = now.astimezone(tz)
            for offset in range(8):
                candidate = now_local + timedelta(days=offset)
                candidate = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
                if hasattr(tz, 'localize'):
                    candidate = tz.localize(candidate.replace(tzinfo=None), is_dst=False)
                day_name = list(day_map.keys())[candidate.weekday()]
                if day_name in days and candidate > now_local:
                    return candidate.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return None

        elif stype == "weekly":
            day = config.get("day", "mon")
            time_str = config.get("time", "09:00")
            day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            target_wd = day_map.get(day, 0)
            h, m = map(int, time_str.split(":"))

            now_local = now.astimezone(tz)
            for offset in range(8):
                candidate = now_local + timedelta(days=offset)
                candidate = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
                if hasattr(tz, 'localize'):
                    candidate = tz.localize(candidate.replace(tzinfo=None), is_dst=False)
                if candidate.weekday() == target_wd and candidate > now_local:
                    return candidate.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return None

        elif stype == "cron":
            expr = config.get("cron_expression", "0 9 * * *")
            now_local = now.astimezone(tz)
            cron = croniter(expr, now_local)
            next_dt = cron.get_next(datetime)
            if next_dt.tzinfo is None:
                if hasattr(tz, 'localize'):
                    next_dt = tz.localize(next_dt, is_dst=False)
                else:
                    next_dt = next_dt.replace(tzinfo=tz)
            return next_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return None

    def _validate_cron_frequency(self, expression: str) -> None:
        now = datetime.now(timezone.utc)
        cron = croniter(expression, now)
        first = cron.get_next(datetime)
        second = cron.get_next(datetime)
        gap = (second - first).total_seconds()
        if gap < MIN_CRON_INTERVAL_SECONDS:
            raise ValueError(
                f"Cron expression fires too frequently ({int(gap)}s gap). Minimum is 15 minutes."
            )

    def _resolve_scan_config(self, scan_config: Dict[str, Any]) -> Dict[str, Any]:
        scan_config = copy.deepcopy(scan_config)
        resolved = self._config.get_config()["resolved"]
        defaults = {
            "provider": resolved.get("llm_provider", "openai"),
            "deep_think_llm": resolved.get("deep_think_llm"),
            "quick_think_llm": resolved.get("quick_think_llm"),
            "workflow_mode": resolved.get("workflow_mode", "quick_trade"),
            "research_depth": int(resolved.get("research_depth", 2)),
            "max_debate_rounds": int(resolved.get("max_debate_rounds", 1)),
            "max_risk_discuss_rounds": int(resolved.get("max_risk_discuss_rounds", 1)),
            "max_recur_limit": int(resolved.get("max_recur_limit", 100)),
            "max_parallel": int(resolved.get("max_parallel", 5)),
            "output_language": resolved.get("output_language", "English"),
        }
        for k, v in defaults.items():
            if scan_config.get(k) is None and v is not None:
                scan_config[k] = v
        return scan_config

    @staticmethod
    def _sanitize_error(msg: Optional[str]) -> Optional[str]:
        if not msg:
            return msg
        msg = msg[:500]
        msg = re.sub(r"[A-Za-z]:\\[^\s]+", "[path]", msg)
        msg = re.sub(r"/[^\s]+/[^\s]+", "[path]", msg)
        msg = re.sub(r"(sk-|key-|Bearer\s+|ant-|xai-)[A-Za-z0-9\-_]+", "[redacted]", msg)
        return msg
