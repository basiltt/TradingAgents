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
    from backend.services.analysis_service import ConcurrencyLimitError, _MAX_CONCURRENT

    import time

    def slow_graph(*args, **kwargs):
        time.sleep(5)
        return None

    with patch("backend.services.analysis_service.AnalysisService._execute_graph", side_effect=slow_graph):
        async def _test():
            ids = []
            for _ in range(_MAX_CONCURRENT):
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


def test_persist_signal_sections_saves_pm_signal(tmp_path):
    """_persist_signal_sections writes _pm_signal JSON when _pm_signal_data is present."""
    import json
    from unittest.mock import MagicMock
    from pydantic import BaseModel
    from backend.services.analysis_service import AnalysisService

    class FakePMDecision(BaseModel):
        rating: str = "Buy"
        confidence: int = 8

    db = MagicMock()
    event_bus = MagicMock()
    event_bus.get_snapshot.return_value = []
    ws = MagicMock()
    config_svc = MagicMock()
    config_svc.get_config.return_value = {"resolved": {}}

    service = AnalysisService(
        persistence=db, event_bus=event_bus, ws_manager=ws, config_service=config_svc
    )

    last_chunk = {"_pm_signal_data": FakePMDecision(), "_trader_signal_data": None}
    service._persist_signal_sections("run-123", last_chunk)

    # Should have called save_report_section with "_pm_signal" and valid JSON
    calls = {call[0][1]: call[0][2] for call in db.save_report_section.call_args_list}
    assert "_pm_signal" in calls
    data = json.loads(calls["_pm_signal"])
    assert data["rating"] == "Buy"
    assert data["confidence"] == 8


def test_persist_signal_sections_skips_none_values(tmp_path):
    """_persist_signal_sections does nothing when both signal objects are None."""
    from unittest.mock import MagicMock
    from backend.services.analysis_service import AnalysisService

    db = MagicMock()
    event_bus = MagicMock()
    event_bus.get_snapshot.return_value = []
    ws = MagicMock()
    config_svc = MagicMock()
    config_svc.get_config.return_value = {"resolved": {}}

    service = AnalysisService(
        persistence=db, event_bus=event_bus, ws_manager=ws, config_service=config_svc
    )
    service._persist_signal_sections("run-456", {"_pm_signal_data": None, "_trader_signal_data": None})
    db.save_report_section.assert_not_called()


def test_persist_signal_sections_handles_none_chunk(tmp_path):
    """_persist_signal_sections does nothing when last_chunk is None."""
    from unittest.mock import MagicMock
    from backend.services.analysis_service import AnalysisService

    db = MagicMock()
    event_bus = MagicMock()
    event_bus.get_snapshot.return_value = []
    ws = MagicMock()
    config_svc = MagicMock()
    config_svc.get_config.return_value = {"resolved": {}}

    service = AnalysisService(
        persistence=db, event_bus=event_bus, ws_manager=ws, config_service=config_svc
    )
    service._persist_signal_sections("run-789", None)
    db.save_report_section.assert_not_called()


def _make_service_with_sections(sections: list):
    """Return an AnalysisService whose DB returns the given sections list."""
    import asyncio
    from unittest.mock import MagicMock
    from backend.services.analysis_service import AnalysisService

    db = MagicMock()
    db.get_report_sections.return_value = sections
    event_bus = MagicMock()
    event_bus.get_snapshot.return_value = []
    ws = MagicMock()
    config_svc = MagicMock()
    config_svc.get_config.return_value = {"resolved": {}}
    return AnalysisService(persistence=db, event_bus=event_bus, ws_manager=ws, config_service=config_svc)


def test_get_snapshot_injects_signal_sections_into_existing_reports():
    """Signal sections saved after snapshot must appear in snapshot['reports']."""
    import asyncio
    import json

    snapshot_json = json.dumps({"agents": {}, "messages": [], "stats": None, "reports": {
        "portfolio_manager": "Some markdown",
    }})
    sections = [
        {"section": "_snapshot", "content": snapshot_json},
        {"section": "portfolio_manager", "content": "Some markdown"},
        {"section": "_pm_signal", "content": json.dumps({"rating": "Buy", "confidence": 8})},
        {"section": "_trader_signal", "content": json.dumps({"action": "Buy", "confidence": 7})},
    ]
    service = _make_service_with_sections(sections)
    snapshot = asyncio.run(service.get_snapshot("run-42"))

    assert snapshot is not None
    reports = snapshot["reports"]
    assert "_pm_signal" in reports
    assert "_trader_signal" in reports
    # Existing key must not be overwritten by DB section
    assert reports["portfolio_manager"] == "Some markdown"


def test_get_snapshot_does_not_overwrite_existing_snapshot_key():
    """DB section for a key already in snapshot['reports'] must not win."""
    import asyncio
    import json

    snapshot_json = json.dumps({"agents": {}, "messages": [], "stats": None, "reports": {
        "trader": "Snapshot version",
    }})
    sections = [
        {"section": "_snapshot", "content": snapshot_json},
        {"section": "trader", "content": "DB version (should not overwrite)"},
    ]
    service = _make_service_with_sections(sections)
    snapshot = asyncio.run(service.get_snapshot("run-43"))

    assert snapshot["reports"]["trader"] == "Snapshot version"


def test_get_report_excludes_underscore_prefixed_sections():
    """get_report must not expose raw JSON signal blobs in the human-readable output."""
    import asyncio
    import json

    sections = [
        {"section": "portfolio_manager", "content": "Some markdown"},
        {"section": "_pm_signal", "content": json.dumps({"rating": "Buy"})},
        {"section": "_trader_signal", "content": json.dumps({"action": "Buy"})},
    ]
    service = _make_service_with_sections(sections)
    report = asyncio.run(service.get_report("run-44"))

    assert report is not None
    assert "_pm_signal" not in report
    assert "_trader_signal" not in report
    assert "portfolio_manager" in report or "Some markdown" in report
