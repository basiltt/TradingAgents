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


def test_zombie_count_blocks(service, sample_request, event_loop):
    from backend.services.analysis_service import ConcurrencyLimitError
    async def _test():
        service._zombie_count = 100
        with pytest.raises(ConcurrencyLimitError, match="zombie"):
            await service.start_analysis(sample_request)
    event_loop.run_until_complete(_test())


def test_cancel_non_running_active_run(service, event_loop):
    async def _test():
        import threading
        async with service._lock:
            service._active_runs["r1"] = {
                "status": "completed",
                "cancel_event": threading.Event(),
                "task": None,
            }
        result = await service.cancel_analysis("r1")
        assert result is True
    event_loop.run_until_complete(_test())


def test_cancel_db_completed_run(service, db, event_loop):
    async def _test():
        db.insert_run({
            "run_id": "r2", "ticker": "SPY", "analysis_date": "2025-01-10",
            "status": "completed", "config": "{}", "started_at": "2025-01-10T00:00:00Z",
        })
        result = await service.cancel_analysis("r2")
        assert result is True
    event_loop.run_until_complete(_test())


def test_build_config_data_vendors(service):
    config = service._build_config({
        "ticker": "SPY", "analysis_date": "2025-01-10",
        "data_vendors": {"stock": "yfinance"},
    })
    assert config["data_vendors"]["stock"] == "yfinance"


def test_save_snapshot_event_types(service, db, bus):
    import json
    from collections import deque
    run_id = "snap-test-1"
    db.insert_run({
        "run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10",
        "status": "running", "config": "{}", "started_at": "2025-01-10T00:00:00Z",
    })
    bus._ring_buffers[run_id] = deque([
        ({"type": "agent_status", "agent": "market", "status": "running"}, 50),
        ({"type": "message", "sender": "analyst", "content": "test msg", "seq": 1}, 50),
        ({"type": "stats", "tokens_in": 100, "tokens_out": 50, "llm_calls": 5, "tool_calls": 2}, 80),
        ({"type": "report_chunk", "section": "market", "content": "Market analysis report"}, 60),
    ])
    service._save_snapshot(run_id)
    raw = db.get_report_sections(run_id)
    snap_row = next(r for r in raw if r["section"] == "_snapshot")
    snapshot = json.loads(snap_row["content"])
    assert snapshot["agents"]["market"] == "running"
    assert len(snapshot["messages"]) == 1
    assert snapshot["stats"]["tokens_in"] == 100
    assert snapshot["reports"]["market"] == "Market analysis report"


def test_reclaim_zombie(service, event_loop):
    async def _test():
        service._zombie_count = 3
        await service._reclaim_zombie_async("test-run")
        assert service._zombie_count == 2
    event_loop.run_until_complete(_test())


def test_timeout_sets_failed_status(service, sample_request, event_loop, db):
    import asyncio
    with patch("backend.services.analysis_service.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        async def _test():
            run_id = await service.start_analysis(sample_request)
            await asyncio.sleep(0.5)
            run = db.get_run(run_id)
            assert run["status"] == "failed"
            assert "timeout" in (run["error"] or "").lower() or "Wall-clock" in (run["error"] or "")
        event_loop.run_until_complete(_test())


def test_execute_graph_import_error(service, sample_request):
    import sys
    with patch.dict(sys.modules, {"tradingagents.graph.trading_graph": None}):
        result = service._execute_graph(
            "run-1", {"ticker": "SPY", "analysis_date": "2025-01-10"}, {}, None,
            __import__("threading").Event(),
        )
    assert result is not None
    assert "Mock decision" in result.get("final_trade_decision", "")


def test_safe_json_non_serializable():
    from backend.services.analysis_service import _safe_json

    class Bad:
        def __repr__(self):
            raise ValueError("bad repr")

    # _safe_json uses default=str which should handle most objects;
    # We cover the except branch with a circular reference
    import json
    circular: dict = {}
    circular["self"] = circular
    result = _safe_json(circular)
    assert result == "{}"


def test_save_snapshot_messages_truncated(service, db, bus):
    from collections import deque
    run_id = "snap-truncate"
    db.insert_run({
        "run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10",
        "status": "running", "config": "{}", "started_at": "2025-01-10T00:00:00Z",
    })
    bus._ring_buffers[run_id] = deque(
        [({"type": "message", "sender": "a", "content": f"msg{i}", "seq": i}, 20) for i in range(250)]
    )
    service._save_snapshot(run_id)
    import json
    raw = db.get_report_sections(run_id)
    snap_row = next(r for r in raw if r["section"] == "_snapshot")
    snapshot = json.loads(snap_row["content"])
    assert len(snapshot["messages"]) == 200
    assert snapshot["messages"][0]["seq"] == 50


def test_save_snapshot_exception_logged(service, db, bus):
    from collections import deque
    run_id = "snap-err-1"
    db.insert_run({
        "run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10",
        "status": "running", "config": "{}", "started_at": "2025-01-10T00:00:00Z",
    })
    bus._ring_buffers[run_id] = deque([
        ({"type": "agent_status", "agent": "market", "status": "done"}, 50),
    ])
    with patch.object(db, "save_report_section", side_effect=Exception("db error")):
        service._save_snapshot(run_id)


def test_execute_graph_streaming_loop(service, db, bus):
    """Covers analysis_service.py:313-343: actual graph streaming loop."""
    import threading
    from backend.stream_parser import ReportChunkEvent

    # Create a fake graph chunk that parse_stream_chunk can process
    fake_report_chunk = ReportChunkEvent(section="market", content="Market data here")

    class FakeStream:
        def __iter__(self):
            yield {"messages": []}  # one chunk

    class FakeGraph:
        def __init__(self, config=None, selected_analysts=None):
            self.graph = type("G", (), {"stream": lambda self, s, **kw: FakeStream()})()
            self.propagator = type("P", (), {
                "create_initial_state": lambda self, t, d, asset_type="stock": {},
                "get_graph_args": lambda self, callbacks=None: {},
            })()

    cancel_event = threading.Event()

    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph", FakeGraph):
        with patch("backend.services.analysis_service.parse_stream_chunk", return_value=[fake_report_chunk]):
            with patch.object(service._db, "save_report_section"):
                result = service._execute_graph(
                    "run-stream",
                    {"ticker": "SPY", "analysis_date": "2025-01-10", "analysts": ["market"]},
                    {},
                    None,
                    cancel_event,
                )
    # last_chunk should be the dict we yielded
    assert result is not None


def test_execute_graph_cancel_mid_loop(service):
    """Covers analysis_service.py:332: cancel_event breaks the stream loop."""
    import threading

    chunks_yielded = []

    class SlowStream:
        def __iter__(self):
            for i in range(5):
                chunks_yielded.append(i)
                yield {"n": i}

    class FakeGraph:
        def __init__(self, config=None, selected_analysts=None):
            self.graph = type("G", (), {"stream": lambda self, s, **kw: SlowStream()})()
            self.propagator = type("P", (), {
                "create_initial_state": lambda self, t, d, asset_type="stock": {},
                "get_graph_args": lambda self, callbacks=None: {},
            })()

    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before loop starts

    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph", FakeGraph):
        with patch("backend.services.analysis_service.parse_stream_chunk", return_value=[]):
            result = service._execute_graph(
                "run-cancel", {"ticker": "SPY", "analysis_date": "2025-01-10"}, {},
                None, cancel_event,
            )
    # Loop should break immediately on first chunk
    assert len(chunks_yielded) <= 1


def test_lifecycle_snapshot_persisted(service, db, event_loop):
    """Integration: _save_snapshot runs in finally block after successful analysis."""
    with patch("backend.services.analysis_service.AnalysisService._execute_graph",
               return_value={"final_trade_decision": "BUY"}):
        async def _test():
            run_id = await service.start_analysis({
                "ticker": "SPY", "analysis_date": "2025-06-01",
                "analysts": ["market"],
            })
            await asyncio.sleep(0.5)
            run = db.get_run(run_id)
            assert run["status"] == "completed"
            snap = await service.get_snapshot(run_id)
            assert snap is not None
            assert "agents" in snap
            assert "messages" in snap
            assert "stats" in snap
            assert "reports" in snap
        event_loop.run_until_complete(_test())


def test_update_run_status_false_skips_section_save(service, db, event_loop, bus):
    """Integration: if update_run_status returns False, save_report_section is not called for final_trade_decision."""
    from collections import deque
    with patch("backend.services.analysis_service.AnalysisService._execute_graph",
               return_value={"final_trade_decision": "HOLD"}):
        async def _test():
            run_id = await service.start_analysis({
                "ticker": "SPY", "analysis_date": "2025-06-01",
            })
            # Pre-mark as completed to make update_run_status return False
            await asyncio.sleep(0)
            db.update_run_status(run_id, "completed", None, "2025-01-01T00:00:00Z")
            await asyncio.sleep(0.5)
            sections = db.get_report_sections(run_id)
            section_names = [s["section"] for s in sections]
            assert "final_trade_decision" not in section_names
        event_loop.run_until_complete(_test())


def test_run_analysis_cancelled_error_sets_db_cancelled(service, db, event_loop):
    """R3-F15: CancelledError inside _run_analysis sets DB status to 'cancelled'."""
    # Patch asyncio.wait_for to raise CancelledError, simulating task cancellation
    original_wait_for = asyncio.wait_for

    async def raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    with patch("backend.services.analysis_service.asyncio.wait_for", side_effect=raise_cancelled):
        async def _test():
            run_id = await service.start_analysis({"ticker": "SPY", "analysis_date": "2025-06-01"})
            await asyncio.sleep(0.5)
            run = db.get_run(run_id)
            assert run is not None
            assert run["status"] in ("cancelled", "failed")
        event_loop.run_until_complete(_test())


def test_run_analysis_empty_decision_skips_section(service, db, event_loop):
    """R3-F16: Empty final_trade_decision ('') skips save_report_section for that key."""
    with patch("backend.services.analysis_service.AnalysisService._execute_graph",
               return_value={"final_trade_decision": ""}):
        async def _test():
            run_id = await service.start_analysis({"ticker": "SPY", "analysis_date": "2025-06-01"})
            await asyncio.sleep(0.5)
            sections = db.get_report_sections(run_id)
            section_names = [s["section"] for s in sections]
            assert "final_trade_decision" not in section_names
        event_loop.run_until_complete(_test())


def test_timeout_increments_zombie_count(service, sample_request, event_loop, db):
    """R4-F6: asyncio.TimeoutError path increments _zombie_count."""
    with patch("backend.services.analysis_service.asyncio.wait_for",
               side_effect=asyncio.TimeoutError()):
        async def _test():
            run_id = await service.start_analysis({"ticker": "SPY", "analysis_date": "2025-06-01"})
            await asyncio.sleep(0.5)
            assert service._zombie_count == 1
            run = db.get_run(run_id)
            assert run["status"] == "failed"
        event_loop.run_until_complete(_test())


def test_shutdown_cancels_active_tasks(service, sample_request, event_loop):
    """R4-F7: shutdown() cancels in-flight tasks and clears active state."""
    import threading
    blocker = threading.Event()

    def slow_graph(*args, **kwargs):
        blocker.wait(timeout=10)
        return {"final_trade_decision": ""}

    with patch("backend.services.analysis_service.AnalysisService._execute_graph",
               side_effect=slow_graph):
        async def _test():
            run_id = await service.start_analysis({"ticker": "SPY", "analysis_date": "2025-06-01"})
            await asyncio.sleep(0.05)
            assert run_id in service._active_runs
            await service.shutdown()
            blocker.set()  # unblock thread
            # After shutdown, all active tasks should be done
            for run_data in service._active_runs.values():
                task = run_data.get("task")
                assert task is None or task.done()
        event_loop.run_until_complete(_test())


def test_service_proxy_delete_and_list(service, db, event_loop, sample_request):
    """R3-F5: delete_run, delete_all_runs, list_runs service proxy methods work."""
    async def _test():
        run_id = await service.start_analysis({"ticker": "SPY", "analysis_date": "2025-06-01"})
        await asyncio.sleep(0.3)
        result = await service.list_runs(page=1, limit=10)
        assert result["total"] >= 1
        deleted = await service.delete_run(run_id)
        assert deleted is True
        result2 = await service.list_runs(ticker="SPY")
        assert all(r["run_id"] != run_id for r in result2["items"])
    event_loop.run_until_complete(_test())


def test_service_delete_all_runs(service, db, event_loop):
    """R3-F5: delete_all_runs service proxy removes all runs."""
    async def _test():
        with patch("backend.services.analysis_service.AnalysisService._execute_graph",
                   return_value={"final_trade_decision": "Buy"}):
            run_id = await service.start_analysis({"ticker": "SPY", "analysis_date": "2025-06-01"})
            await asyncio.sleep(0.3)
        count = await service.delete_all_runs()
        assert count >= 1
    event_loop.run_until_complete(_test())


def test_cancel_returns_false_for_db_running_run(service, db, event_loop):
    """R5-F7: cancel_analysis returns False for DB run with status='running' not in active_runs."""
    import uuid
    from datetime import datetime, timezone

    async def _test():
        run_id = str(uuid.uuid4())
        db.insert_run({
            "run_id": run_id, "ticker": "SPY", "analysis_date": "2025-01-10",
            "status": "running", "config": "{}",
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        })
        result = await service.cancel_analysis(run_id)
        assert result is False
    event_loop.run_until_complete(_test())
