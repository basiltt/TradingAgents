"""Tests for invoke_structured_or_freetext return shape change."""
from unittest.mock import MagicMock
from pydantic import BaseModel
from tradingagents.agents.utils.structured import invoke_structured_or_freetext


class _Schema(BaseModel):
    value: str


def _render(obj: _Schema) -> str:
    return f"rendered:{obj.value}"


def test_structured_path_returns_tuple_with_object():
    llm = MagicMock()
    structured = MagicMock()
    structured.invoke.return_value = _Schema(value="hello")
    text, obj = invoke_structured_or_freetext(structured, llm, "prompt", _render, "Agent")
    assert text == "rendered:hello"
    assert isinstance(obj, _Schema)
    assert obj.value == "hello"


def test_freetext_fallback_returns_tuple_with_none():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="free text response")
    text, obj = invoke_structured_or_freetext(None, llm, "prompt", _render, "Agent")
    assert text == "free text response"
    assert obj is None


def test_structured_exception_falls_back_to_freetext():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="fallback text")
    structured = MagicMock()
    structured.invoke.side_effect = ValueError("bad json")
    text, obj = invoke_structured_or_freetext(structured, llm, "prompt", _render, "Agent")
    assert text == "fallback text"
    assert obj is None
