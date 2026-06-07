"""Unit tests for ScanSchedulerService — validation, CRUD, scheduling logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.scan_scheduler_service import (
    ScanSchedulerService,
    MAX_SCHEDULES,
    MIN_INTERVAL_MINUTES,
    MIN_CRON_INTERVAL_SECONDS,
    COOLDOWN_SECONDS,
    MAX_CONSECUTIVE_FAILURES,
)


@pytest.fixture
def scanner():
    return AsyncMock()


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def config_svc():
    m = MagicMock()
    m.get_config.return_value = {"resolved": {
        "llm_provider": "openai", "deep_think_llm": "gpt-4",
        "quick_think_llm": "gpt-3.5", "workflow_mode": "quick_trade",
        "research_depth": 2, "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1, "max_recur_limit": 100,
        "max_parallel": 5, "output_language": "English",
    }}
    return m


@pytest.fixture
def svc(scanner, db, config_svc):
    return ScanSchedulerService(scanner, db, config_svc)


class TestValidateSchedule:
    def test_interval_too_short_raises(self, svc):
        with pytest.raises(ValueError, match="at least"):
            svc._validate_schedule("interval", {"interval_minutes": 5})

    def test_interval_valid(self, svc):
        svc._validate_schedule("interval", {"interval_minutes": 30})

    def test_daily_invalid_time_format(self, svc):
        with pytest.raises(ValueError, match="HH:MM"):
            svc._validate_schedule("daily", {"time": "9am"})

    def test_daily_invalid_time_value(self, svc):
        with pytest.raises(ValueError, match="Invalid time"):
            svc._validate_schedule("daily", {"time": "25:00"})

    def test_weekly_valid(self, svc):
        svc._validate_schedule("weekly", {"time": "09:00"})

    def test_cron_too_frequent(self, svc):
        with pytest.raises(ValueError, match="too frequently"):
            svc._validate_schedule("cron", {"cron_expression": "* * * * *"})

    def test_cron_valid(self, svc):
        svc._validate_schedule("cron", {"cron_expression": "0 */6 * * *"})


class TestCreate:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_success(self, svc, db):
        db.count_scheduled_scans = AsyncMock(return_value=0)
        db.insert_scheduled_scan = AsyncMock()
        db.get_scheduled_scan = AsyncMock(return_value={"id": "abc", "name": "Test"})
        result = await svc.create({
            "name": "Test", "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 60},
            "scan_config": {},
        })
        assert result["name"] == "Test"
        db.insert_scheduled_scan.assert_awaited_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_create_at_max_raises(self, svc, db):
        db.count_scheduled_scans = AsyncMock(return_value=MAX_SCHEDULES)
        with pytest.raises(ValueError, match="Maximum"):
            await svc.create({
                "name": "Test", "schedule_type": "interval",
                "schedule_config": {"interval_minutes": 60},
                "scan_config": {},
            })


class TestUpdate:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_not_found_raises(self, svc, db):
        db.get_scheduled_scan = AsyncMock(return_value=None)
        with pytest.raises(KeyError, match="not found"):
            await svc.update("missing", {"name": "New"})

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_preserves_masked_api_key(self, svc, db):
        db.get_scheduled_scan = AsyncMock(return_value={
            "id": "s1", "name": "Old", "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 60},
            "scan_config": {"llm_api_key": "real-key"},
        })
        db.update_scheduled_scan = AsyncMock()
        db.get_scheduled_scan.side_effect = [
            {"id": "s1", "name": "Old", "schedule_type": "interval",
             "schedule_config": {"interval_minutes": 60},
             "scan_config": {"llm_api_key": "real-key"}},
            {"id": "s1", "name": "New"},
        ]
        await svc.update("s1", {"name": "New", "scan_config": {"llm_api_key": "***"}})
        call_args = db.update_scheduled_scan.call_args
        updates = call_args[0][1]
        assert updates.get("scan_config", {}).get("llm_api_key") == "real-key"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_non_timing_field_preserves_next_run(self, svc, db):
        """Editing name/scan_config must NOT reset the existing countdown.

        Regression: the edit form always resends schedule_type, schedule_config,
        and timezone unchanged. update() used to recompute next_run_at
        unconditionally, and because last_run_at is in the past,
        max(now, last_run_at) collapsed to now, pushing next_run_at out by a
        full interval on every metadata edit.
        """
        existing = {
            "id": "s1", "name": "Old", "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 180},
            "scan_config": {},
            "timezone": "UTC",
            "last_run_at": "2026-06-07T09:00:00Z",   # in the past
            "next_run_at": "2026-06-07T12:00:00Z",   # already scheduled
        }
        db.get_scheduled_scan = AsyncMock()
        db.get_scheduled_scan.side_effect = [existing, {**existing, "name": "New"}]
        db.update_scheduled_scan = AsyncMock()

        # Form re-sends timing fields with identical values + a changed name.
        await svc.update("s1", {
            "name": "New",
            "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 180},
            "scan_config": {"asset_type": "crypto"},
            "timezone": "UTC",
        })

        updates = db.update_scheduled_scan.call_args[0][1]
        # Countdown must be left untouched: either omit next_run_at, or keep the
        # stored value verbatim.
        assert updates.get("next_run_at", "2026-06-07T12:00:00Z") == "2026-06-07T12:00:00Z"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_timing_field_recomputes_next_run(self, svc, db):
        """Changing the interval SHOULD recompute next_run_at."""
        existing = {
            "id": "s1", "name": "Sched", "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 180},
            "scan_config": {},
            "timezone": "UTC",
            "last_run_at": "2026-06-07T09:00:00Z",
            "next_run_at": "2026-06-07T12:00:00Z",
        }
        db.get_scheduled_scan = AsyncMock()
        db.get_scheduled_scan.side_effect = [existing, existing]
        db.update_scheduled_scan = AsyncMock()

        await svc.update("s1", {
            "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 60},  # changed 180 -> 60
            "timezone": "UTC",
        })

        updates = db.update_scheduled_scan.call_args[0][1]
        assert "next_run_at" in updates
        assert updates["next_run_at"] is not None
        # Recomputed value must differ from the previously stored one.
        assert updates["next_run_at"] != "2026-06-07T12:00:00Z"


class TestDelete:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_success(self, svc, db):
        db.get_scheduled_scan = AsyncMock(return_value={"id": "s1", "status": "active"})
        db.delete_scheduled_scan = AsyncMock()
        await svc.delete("s1")
        db.delete_scheduled_scan.assert_awaited_once_with("s1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_not_found_returns_falsy(self, svc, db):
        db.delete_scheduled_scan = AsyncMock(return_value=False)
        result = await svc.delete("missing")
        assert not result


class TestSanitizeError:
    def test_truncates_long(self):
        result = ScanSchedulerService._sanitize_error("x" * 1000)
        assert len(result) <= 500

    def test_redacts_api_keys(self):
        result = ScanSchedulerService._sanitize_error("key sk-1234abcdef")
        assert "[redacted]" in result

    def test_none_passthrough(self):
        assert ScanSchedulerService._sanitize_error(None) is None

    def test_empty_passthrough(self):
        assert ScanSchedulerService._sanitize_error("") == ""

    def test_redacts_paths(self):
        result = ScanSchedulerService._sanitize_error("Error at C:\\Users\\secret\\file.py")
        assert "[path]" in result


class TestResolveConfig:
    def test_fills_defaults(self, svc):
        result = svc._resolve_scan_config({})
        assert result["provider"] == "openai"
        assert result["workflow_mode"] == "quick_trade"

    def test_preserves_explicit_values(self, svc):
        result = svc._resolve_scan_config({"provider": "anthropic"})
        assert result["provider"] == "anthropic"


class TestAIManagerTrigger:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_reconcile_triggered_on_crud(self, svc, db):
        import asyncio
        mock_aim = MagicMock()
        mock_aim.reconcile_active_schedules = AsyncMock()
        svc.set_ai_manager_service(mock_aim)

        # Trigger create
        db.count_scheduled_scans = AsyncMock(return_value=0)
        db.insert_scheduled_scan = AsyncMock()
        db.get_scheduled_scan = AsyncMock(return_value={"id": "s1", "name": "Test"})
        await svc.create({
            "name": "Test", "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 60},
            "scan_config": {},
        })
        await asyncio.sleep(0.01) # Yield to background tasks
        mock_aim.reconcile_active_schedules.assert_called_once()
        mock_aim.reconcile_active_schedules.reset_mock()

        # Trigger update
        db.get_scheduled_scan = AsyncMock(return_value={
            "id": "s1", "name": "Old", "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 60},
            "scan_config": {},
        })
        db.update_scheduled_scan = AsyncMock()
        db.get_scheduled_scan.side_effect = [
            {"id": "s1", "name": "Old", "schedule_type": "interval", "schedule_config": {"interval_minutes": 60}, "scan_config": {}},
            {"id": "s1", "name": "New"},
        ]
        await svc.update("s1", {"name": "New"})
        await asyncio.sleep(0.01)
        mock_aim.reconcile_active_schedules.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reconcile_triggered_on_completion(self, svc, db, scanner):
        import asyncio
        mock_aim = MagicMock()
        mock_aim.reconcile_active_schedules = AsyncMock()
        svc.set_ai_manager_service(mock_aim)

        # Mock an in-flight scan
        svc._in_flight["s1"] = 123  # exec_id = 123
        
        db.get_scheduled_scan = AsyncMock(return_value={"id": "s1", "last_scan_id": "scan-123", "schedule_type": "once"})
        scanner.get_scan = AsyncMock(return_value={"status": "completed"})
        db.update_schedule_execution = AsyncMock()
        db.update_scheduled_scan = AsyncMock()

        await svc._check_in_flight_completions()
        await asyncio.sleep(0.01)  # Yield to background tasks
        
        mock_aim.reconcile_active_schedules.assert_called_once()
