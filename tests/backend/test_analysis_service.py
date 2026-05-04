"""Tests for analysis service — TASK-012."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def db(tmp_path):
    from backend.persistence import AnalysisDB
    return AnalysisDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def bus(event_loop):
    from backend.event_bus import EventBus
    return EventBus(loop=event_loop)


@pytest.fixture
def ws_manager():
    from backend.ws_manager import WSManager
    return WSManager()


@pytest.fixture
def config_service(db):
    from backend.services.config_service import ConfigService
    return ConfigService(db=db)


@pytest.fixture
def service(db, bus, ws_manager, config_service):
    from backend.services.analysis_service import AnalysisService
    return AnalysisService(
        persistence=db, event_bus=bus, ws_manager=ws_manager, config_service=config_service
    )


@pytest.fixture
def sample_request():
    return {
        "ticker": "SPY",
        "analysis_date": "2025-06-01",
        "provider": "anthropic",
        "analysts": ["market", "news"],
    }


def test_start_analysis_returns_run_id(service, sample_request, event_loop):
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", return_value={"final_trade_decision": "BUY"}):
        async def _test():
            run_id = await service.start_analysis(sample_request)
            assert run_id is not None
            assert len(run_id) == 36  # UUID
            await asyncio.sleep(0.2)

        event_loop.run_until_complete(_test())


def test_concurrency_cap(service, sample_request, event_loop):
    from backend.services.analysis_service import ConcurrencyLimitError

    import time

    def slow_graph(*args, **kwargs):
        time.sleep(5)
        return None

    with patch("backend.services.analysis_service.AnalysisService._execute_graph", side_effect=slow_graph):
        async def _test():
            ids = []
            for _ in range(10):
                rid = await service.start_analysis(sample_request)
                ids.append(rid)

            await asyncio.sleep(0.1)

            with pytest.raises(ConcurrencyLimitError):
                await service.start_analysis(sample_request)

            for rid in ids:
                await service.cancel_analysis(rid)
            await asyncio.sleep(0.3)

        event_loop.run_until_complete(_test())


def test_cancel_idempotent(service, sample_request, event_loop):
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", return_value=None):
        async def _test():
            run_id = await service.start_analysis(sample_request)
            await asyncio.sleep(0.1)
            result1 = await service.cancel_analysis(run_id)
            result2 = await service.cancel_analysis(run_id)
            assert result1 is True
            assert result2 is True
            await asyncio.sleep(0.2)

        event_loop.run_until_complete(_test())


def test_cancel_unknown_run(service, event_loop):
    async def _test():
        result = await service.cancel_analysis("nonexistent-id")
        assert result is False

    event_loop.run_until_complete(_test())


def test_research_depth_mapping(service):
    config = service._build_config({
        "ticker": "SPY",
        "analysis_date": "2025-06-01",
        "research_depth": 3,
    })
    assert config["max_debate_rounds"] == 3
    assert config["max_risk_discuss_rounds"] == 3


def test_error_sanitization(service, sample_request, event_loop, db):
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", side_effect=RuntimeError("secret internal error")):
        async def _test():
            run_id = await service.start_analysis(sample_request)
            await asyncio.sleep(0.5)
            run = db.get_run(run_id)
            assert run["status"] == "failed"
            assert "Internal error" in run["error"]
            assert "secret" not in run["error"]

        event_loop.run_until_complete(_test())


def test_get_report_no_sections(service, db, event_loop):
    async def _test():
        result = await service.get_report("nonexistent")
        assert result is None
    event_loop.run_until_complete(_test())


def test_get_report_joins_sections(service, db, event_loop):
    async def _test():
        run_id = "11111111-1111-1111-1111-111111111111"
        db.insert_run({"run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10", "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z"})
        db.save_report_section(run_id, "market", "Market Analysis")
        db.save_report_section(run_id, "news", "News Analysis")
        db.save_report_section(run_id, "_snapshot", '{"agents":{}}')
        report = await service.get_report(run_id)
        assert "Market Analysis" in report
        assert "News Analysis" in report
        assert "_snapshot" not in report and "agents" not in report
    event_loop.run_until_complete(_test())


def test_get_snapshot_returns_parsed_json(service, db, event_loop):
    async def _test():
        run_id = "22222222-2222-2222-2222-222222222222"
        db.insert_run({"run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10", "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z"})
        db.save_report_section(run_id, "_snapshot", '{"reports":{"market":"data"}}')
        snap = await service.get_snapshot(run_id)
        assert snap is not None
        assert snap["reports"]["market"] == "data"
    event_loop.run_until_complete(_test())


def test_get_snapshot_backfills_from_sections(service, db, event_loop):
    async def _test():
        run_id = "33333333-3333-3333-3333-333333333333"
        db.insert_run({"run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10", "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z"})
        db.save_report_section(run_id, "_snapshot", '{"reports":{}}')
        db.save_report_section(run_id, "market", "Market Analysis")
        snap = await service.get_snapshot(run_id)
        assert snap["reports"]["market"] == "Market Analysis"
    event_loop.run_until_complete(_test())


def test_get_snapshot_none_when_no_snapshot(service, db, event_loop):
    async def _test():
        run_id = "44444444-4444-4444-4444-444444444444"
        db.insert_run({"run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10", "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z"})
        snap = await service.get_snapshot(run_id)
        assert snap is None
    event_loop.run_until_complete(_test())


def test_get_snapshot_bad_json(service, db, event_loop):
    async def _test():
        run_id = "55555555-5555-5555-5555-555555555555"
        db.insert_run({"run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10", "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z"})
        db.save_report_section(run_id, "_snapshot", "not json at all")
        snap = await service.get_snapshot(run_id)
        assert snap is None
    event_loop.run_until_complete(_test())


def test_build_config_crypto(service):
    config = service._build_config({
        "ticker": "BTCUSDT", "analysis_date": "2025-01-10",
        "asset_type": "crypto", "interval": "4h",
    })
    assert config["asset_type"] == "crypto"
    assert config["crypto_interval"] == "4h"


def test_build_config_overrides(service):
    config = service._build_config({
        "ticker": "SPY", "analysis_date": "2025-01-10",
        "provider": "google",
        "deep_think_llm": "gemini-2.5-pro",
        "quick_think_llm": "gemini-2.5-flash",
        "output_language": "Japanese",
        "max_debate_rounds": 5,
        "max_risk_discuss_rounds": 3,
        "max_recur_limit": 10,
        "checkpoint_enabled": False,
    })
    assert config["llm_provider"] == "google"
    assert config["deep_think_llm"] == "gemini-2.5-pro"
    assert config["quick_think_llm"] == "gemini-2.5-flash"
    assert config["output_language"] == "Japanese"
    assert config["max_debate_rounds"] == 5
    assert config["max_risk_discuss_rounds"] == 3
    assert config["max_recur_limit"] == 10
    assert config["checkpoint_enabled"] is False


def test_build_config_backend_url(service):
    with patch("backend.services.analysis_service.validate_backend_url", return_value="http://ollama:11434") as mock_val:
        config = service._build_config({
            "ticker": "SPY", "analysis_date": "2025-01-10",
            "backend_url": "http://ollama:11434",
        })
    assert config["backend_url"] == "http://ollama:11434"
    mock_val.assert_called_once()


def test_shutdown(service, sample_request, event_loop):
    with patch("backend.services.analysis_service.AnalysisService._execute_graph", return_value=None):
        async def _test():
            await service.start_analysis(sample_request)
            await asyncio.sleep(0.1)
            await service.shutdown()
            assert all(
                r.get("cancel_event") is None or r["cancel_event"].is_set()
                for r in service._active_runs.values()
            )
        event_loop.run_until_complete(_test())
