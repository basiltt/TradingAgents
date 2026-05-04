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
            for _ in range(3):
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


def test_build_config_passes_llm_api_key(service):
    config = service._build_config({
        "ticker": "SPY",
        "analysis_date": "2025-06-01",
        "provider": "anthropic",
        "llm_api_key": "sk-test-key-123",
    })
    assert config["llm_api_key"] == "sk-test-key-123"
    assert config["llm_provider"] == "anthropic"


def test_build_config_omits_llm_api_key_when_absent(service):
    config = service._build_config({
        "ticker": "SPY",
        "analysis_date": "2025-06-01",
        "provider": "anthropic",
    })
    assert "llm_api_key" not in config or config.get("llm_api_key") is None


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
