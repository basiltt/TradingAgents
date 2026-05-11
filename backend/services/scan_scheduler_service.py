"""Scheduled scan service — manages scheduled market scans."""

from __future__ import annotations

import asyncio
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


class ScanSchedulerService:
    def __init__(self, scanner_service: Any, db: Any, config_service: Any):
        self._scanner = scanner_service
        self._db = db
        self._config = config_service
        self._loop_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._in_flight: Dict[str, int] = {}  # schedule_id -> execution_id
        self._last_cleanup: Optional[datetime] = None

    # ── CRUD ─────────────────────────────────────────────────────────

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        count = await asyncio.to_thread(self._db.count_scheduled_scans)
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
        await asyncio.to_thread(self._db.insert_scheduled_scan, schedule)
        logger.info("Created schedule %s (%s)", scan_id, data["name"])
        return await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)

    async def update(self, scan_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        existing = await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")

        updates: Dict[str, Any] = {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for k in ("name", "schedule_type", "schedule_config", "scan_config", "timezone"):
            if k in fields and fields[k] is not None:
                updates[k] = fields[k]

        if "scan_config" in updates:
            updates["scan_config"] = self._resolve_scan_config(updates["scan_config"])

        updates["consecutive_failures"] = 0
        updates["updated_at"] = now

        merged = {**existing, **updates}

        updates["next_run_at"] = self._compute_next_run(merged)
        await asyncio.to_thread(self._db.update_scheduled_scan, scan_id, updates)
        logger.info("Updated schedule %s", scan_id)
        return await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)

    async def delete(self, scan_id: str) -> bool:
        result = await asyncio.to_thread(self._db.delete_scheduled_scan, scan_id)
        if result:
            self._in_flight.pop(scan_id, None)
            logger.info("Deleted schedule %s", scan_id)
        return result

    async def list_all(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._db.list_scheduled_scans)

    async def get(self, scan_id: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)

    async def pause(self, scan_id: str) -> Dict[str, Any]:
        existing = await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")
        if existing["status"] not in ("active", "error"):
            raise ValueError(f"Cannot pause schedule in '{existing['status']}' status")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await asyncio.to_thread(
            self._db.update_scheduled_scan, scan_id,
            {"status": "paused", "next_run_at": None, "updated_at": now},
        )
        logger.info("Paused schedule %s", scan_id)
        return await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)

    async def resume(self, scan_id: str) -> Dict[str, Any]:
        existing = await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")
        if existing["status"] not in ("paused", "error"):
            raise ValueError(f"Cannot resume schedule in '{existing['status']}' status")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        next_run = self._compute_next_run(existing)
        await asyncio.to_thread(
            self._db.update_scheduled_scan, scan_id,
            {"status": "active", "next_run_at": next_run, "consecutive_failures": 0, "updated_at": now},
        )
        logger.info("Resumed schedule %s", scan_id)
        return await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)

    async def trigger(self, scan_id: str) -> Dict[str, Any]:
        existing = await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)
        if not existing:
            raise KeyError(f"Schedule {scan_id} not found")
        if existing["status"] == "completed":
            raise ValueError("Cannot trigger a completed schedule")
        if scan_id in self._in_flight:
            raise ValueError("A scan is already running for this schedule")

        if existing["last_run_at"]:
            last = datetime.fromisoformat(existing["last_run_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last).total_seconds() < COOLDOWN_SECONDS:
                raise ValueError("Cooldown: must wait 60 seconds between triggers")

        await self._execute_schedule(existing, triggered_by="run_now")
        return await asyncio.to_thread(self._db.get_scheduled_scan, scan_id)

    async def list_executions(self, schedule_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._db.list_schedule_executions, schedule_id, limit)

    # ── Scheduler Loop ───────────────────────────────────────────────

    def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._shutdown_event.clear()
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler loop started")

    async def shutdown(self) -> None:
        self._shutdown_event.set()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler loop stopped")

    async def _scheduler_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                await self._check_in_flight_completions()
                due = await asyncio.to_thread(self._db.get_due_scheduled_scans)
                for schedule in due:
                    if self._shutdown_event.is_set():
                        break
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

        claimed = await asyncio.to_thread(
            self._db.claim_scheduled_scan,
            schedule["id"],
            schedule["next_run_at"],
            next_run,
        )
        if not claimed:
            return

        await self._execute_schedule(schedule, triggered_by="scheduled")

    async def _execute_schedule(self, schedule: Dict[str, Any], triggered_by: str = "scheduled") -> None:
        schedule_id = schedule["id"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        scan_config = schedule.get("scan_config", {})

        if not scan_config.get("analysis_date"):
            scan_config["analysis_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        provider = scan_config.get("provider")
        if not provider:
            resolved = self._config.get_config()["resolved"]
            provider = resolved.get("llm_provider", "openai")

        env_key = PROVIDER_API_KEY_MAP.get(provider)
        backend_url = scan_config.get("backend_url")
        if env_key and not backend_url and not os.getenv(env_key):
            await asyncio.to_thread(
                self._db.insert_schedule_execution,
                {"schedule_id": schedule_id, "status": "skipped_no_key",
                 "started_at": now, "completed_at": now,
                 "error_message": f"API key {env_key} not set"},
            )
            logger.warning("Schedule %s skipped: %s not set", schedule_id, env_key)
            if schedule["schedule_type"] == "once":
                await asyncio.to_thread(
                    self._db.update_scheduled_scan, schedule_id,
                    {"status": "completed", "next_run_at": None, "updated_at": now},
                )
            return

        exec_id = await asyncio.to_thread(
            self._db.insert_schedule_execution,
            {"schedule_id": schedule_id, "status": "started", "started_at": now},
        )

        try:
            scan_id = await self._scanner.start_scan(
                scan_config, schedule_id=schedule_id, triggered_by=triggered_by,
            )
            await asyncio.to_thread(
                self._db.update_schedule_execution, exec_id,
                {"scan_id": scan_id, "status": "started"},
            )
            update_fields: Dict[str, Any] = {
                "last_scan_id": scan_id,
                "last_run_at": now,
                "updated_at": now,
            }
            await asyncio.to_thread(
                self._db.update_scheduled_scan, schedule_id, update_fields,
            )
            self._in_flight[schedule_id] = exec_id
            logger.info("Schedule %s fired scan %s", schedule_id, scan_id)

        except ScannerBusyError:
            await asyncio.to_thread(
                self._db.update_schedule_execution, exec_id,
                {"status": "skipped_busy", "completed_at": now,
                 "error_message": "Scanner busy"},
            )
            if schedule["schedule_type"] == "once":
                retry_at = (datetime.now(timezone.utc) + timedelta(seconds=COOLDOWN_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
                await asyncio.to_thread(
                    self._db.update_scheduled_scan, schedule_id,
                    {"next_run_at": retry_at, "updated_at": now},
                )
            logger.info("Schedule %s skipped: scanner busy", schedule_id)

        except Exception as e:
            error_msg = self._sanitize_error(str(e))
            await asyncio.to_thread(
                self._db.update_schedule_execution, exec_id,
                {"status": "failed", "completed_at": now, "error_message": error_msg},
            )
            await self._record_failure(schedule_id)
            if schedule["schedule_type"] == "once":
                await asyncio.to_thread(
                    self._db.update_scheduled_scan, schedule_id,
                    {"status": "completed", "next_run_at": None, "updated_at": now},
                )
            logger.exception("Schedule %s execution failed", schedule_id)

    async def _check_in_flight_completions(self) -> None:
        completed = []
        for schedule_id, exec_id in list(self._in_flight.items()):
            schedule = await asyncio.to_thread(self._db.get_scheduled_scan, schedule_id)
            if not schedule or not schedule.get("last_scan_id"):
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await asyncio.to_thread(
                    self._db.update_schedule_execution, exec_id,
                    {"status": "cancelled", "completed_at": now,
                     "error_message": "Schedule deleted while scan was running"},
                )
                completed.append(schedule_id)
                continue

            scan = await self._scanner.get_scan(schedule["last_scan_id"])
            if not scan:
                completed.append(schedule_id)
                continue

            if scan.get("status") in ("completed", "failed", "cancelled"):
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                status = scan["status"]

                await asyncio.to_thread(
                    self._db.update_schedule_execution, exec_id,
                    {"status": status, "completed_at": now},
                )

                if status == "failed":
                    await self._record_failure(schedule_id)
                elif status == "completed":
                    updates: Dict[str, Any] = {"consecutive_failures": 0, "updated_at": now}
                    if schedule.get("schedule_type") == "once":
                        updates["status"] = "completed"
                        updates["next_run_at"] = None
                    await asyncio.to_thread(
                        self._db.update_scheduled_scan, schedule_id, updates,
                    )

                completed.append(schedule_id)

        for sid in completed:
            self._in_flight.pop(sid, None)

    async def _record_failure(self, schedule_id: str) -> None:
        schedule = await asyncio.to_thread(self._db.get_scheduled_scan, schedule_id)
        if not schedule:
            return
        failures = schedule.get("consecutive_failures", 0) + 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        updates: Dict[str, Any] = {"consecutive_failures": failures, "updated_at": now}
        if failures >= MAX_CONSECUTIVE_FAILURES:
            updates["status"] = "error"
            updates["next_run_at"] = None
            logger.warning("Schedule %s auto-paused after %d failures", schedule_id, failures)
        await asyncio.to_thread(self._db.update_scheduled_scan, schedule_id, updates)

    # ── Recovery ─────────────────────────────────────────────────────

    async def recover_on_startup(self) -> None:
        schedules = await asyncio.to_thread(self._db.list_scheduled_scans)
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
                    await self._execute_schedule(schedule, triggered_by="scheduled")
                    replayed += 1
                else:
                    await asyncio.to_thread(
                        self._db.update_scheduled_scan, schedule["id"],
                        {"status": "completed", "next_run_at": None,
                         "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                    )
            else:
                new_next = self._compute_next_run(schedule)
                await asyncio.to_thread(
                    self._db.update_scheduled_scan, schedule["id"],
                    {"next_run_at": new_next,
                     "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                )
                logger.info("Schedule %s: skipped to next run %s", schedule["id"], new_next)

        logger.info("Recovery complete: %d schedules processed", len(schedules))

        orphaned = await asyncio.to_thread(self._db.mark_orphaned_executions)
        if orphaned:
            logger.info("Marked %d orphaned executions as failed", orphaned)

    async def _maybe_cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_cleanup and (now - self._last_cleanup) < timedelta(hours=24):
            return
        self._last_cleanup = now
        deleted = await asyncio.to_thread(self._db.cleanup_old_executions)
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
        if gap < 900:
            raise ValueError(
                f"Cron expression fires too frequently ({int(gap)}s gap). Minimum is 15 minutes."
            )

    def _resolve_scan_config(self, scan_config: Dict[str, Any]) -> Dict[str, Any]:
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
