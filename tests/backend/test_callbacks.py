"""Tests for callback handler — TASK-010."""

from unittest.mock import MagicMock
from uuid import uuid4


def test_on_llm_start_emits_message():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)
    handler.on_llm_start(
        {"name": "gpt-4"}, ["prompt"], run_id=uuid4()
    )
    bus.emit_threadsafe.assert_called_once()
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.type == "message"
    assert "gpt-4" in event.content


def test_on_llm_end_emits_stats():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)
    handler._llm_calls = 1

    response = MagicMock()
    response.llm_output = {"token_usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    handler.on_llm_end(response, run_id=uuid4())
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.type == "stats"
    assert event.tokens_in == 100
    assert event.tokens_out == 50


def test_on_tool_start_emits_tool_call():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)
    handler.on_tool_start({"name": "search"}, "query", run_id=uuid4())
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.type == "tool_call"
    assert event.tool_name == "search"


def test_on_tool_end_emits_message():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)
    handler.on_tool_end("result data", run_id=uuid4())
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.type == "message"
    assert event.sender == "Tool"


def test_on_llm_end_fallback_usage_metadata():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)
    handler._llm_calls = 1

    gen = MagicMock()
    gen.message.usage_metadata = {"input_tokens": 200, "output_tokens": 75}

    response = MagicMock()
    response.llm_output = {}
    response.generations = [gen]

    handler.on_llm_end(response, run_id=uuid4())
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.tokens_in == 200
    assert event.tokens_out == 75


def test_on_llm_end_no_usage():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)

    response = MagicMock()
    response.llm_output = None
    response.generations = []

    handler.on_llm_end(response, run_id=uuid4())
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.tokens_in == 0
    assert event.tokens_out == 0


def test_on_tool_end_non_string():
    from backend.callbacks import WebCallbackHandler

    bus = MagicMock()
    handler = WebCallbackHandler(run_id="run1", event_bus=bus)
    handler.on_tool_end({"key": "value"}, run_id=uuid4())
    event = bus.emit_threadsafe.call_args[0][1]
    assert event.type == "message"
