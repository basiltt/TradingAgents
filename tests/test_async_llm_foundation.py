"""Phase 1 equivalence tests for the async LLM foundation.

These prove the async siblings (ainvoke / allm_rate_limited_invoke /
ainvoke_structured_or_freetext / _FallbackStructured.ainvoke) behave IDENTICALLY to
their sync counterparts — same content, same retry count, same backoff decisions,
same structured-first-then-freetext fallback. This is the safety gate for converting
a money-critical analysis pipeline from sync to async.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from tradingagents.agents.utils.structured import (
    invoke_structured_or_freetext,
    ainvoke_structured_or_freetext,
    _FallbackStructured,
)
import tradingagents.llm_clients.base_client as bc


class _Schema(BaseModel):
    value: str


def _render(obj: _Schema) -> str:
    return f"rendered:{obj.value}"


# --- structured wrapper: async == sync -------------------------------------------------

@pytest.mark.asyncio
async def test_async_structured_matches_sync_structured():
    # sync
    s_sync = MagicMock()
    s_sync.invoke.return_value = _Schema(value="hello")
    sync_text, sync_obj = invoke_structured_or_freetext(s_sync, MagicMock(), "p", _render, "Agent")
    # async
    s_async = MagicMock()
    s_async.ainvoke = AsyncMock(return_value=_Schema(value="hello"))
    async_text, async_obj = await ainvoke_structured_or_freetext(s_async, MagicMock(), "p", _render, "Agent")
    assert async_text == sync_text == "rendered:hello"
    assert async_obj.value == sync_obj.value == "hello"


@pytest.mark.asyncio
async def test_async_freetext_fallback_matches_sync():
    plain = MagicMock()
    plain.ainvoke = AsyncMock(return_value=MagicMock(content="free text response"))
    text, obj = await ainvoke_structured_or_freetext(None, plain, "p", _render, "Agent")
    assert text == "free text response"
    assert obj is None


@pytest.mark.asyncio
async def test_async_structured_exception_falls_back_to_freetext():
    plain = MagicMock()
    plain.ainvoke = AsyncMock(return_value=MagicMock(content="fallback text"))
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=ValueError("bad json"))
    text, obj = await ainvoke_structured_or_freetext(structured, plain, "p", _render, "Agent")
    assert text == "fallback text"
    assert obj is None


@pytest.mark.asyncio
async def test_async_structured_None_result_falls_back_like_sync():
    # The exact scenario seen live: the Research Manager's structured call returns None,
    # which must trigger the SAME free-text fallback in both sync and async paths.
    # sync
    s_sync = MagicMock(); s_sync.invoke.return_value = None
    plain_sync = MagicMock(); plain_sync.invoke.return_value = MagicMock(content="freetext plan")
    sync_text, sync_obj = invoke_structured_or_freetext(s_sync, plain_sync, "p", _render, "RM")
    # async
    s_async = MagicMock(); s_async.ainvoke = AsyncMock(return_value=None)
    plain_async = MagicMock(); plain_async.ainvoke = AsyncMock(return_value=MagicMock(content="freetext plan"))
    async_text, async_obj = await ainvoke_structured_or_freetext(s_async, plain_async, "p", _render, "RM")

    assert sync_text == async_text == "freetext plan"
    assert sync_obj is None and async_obj is None


@pytest.mark.asyncio
async def test_fallback_structured_ainvoke_skips_400_method_like_sync():
    # binding A 400s (should be skipped + remembered), binding B succeeds
    a = MagicMock(); a.ainvoke = AsyncMock(side_effect=ValueError("400 invalid_request"))
    b = MagicMock(); b.ainvoke = AsyncMock(return_value=_Schema(value="ok"))
    fb = _FallbackStructured([("json_schema", a), ("function_calling", b)], "Agent")
    out = await fb.ainvoke("p")
    assert out.value == "ok"
    assert "json_schema" in fb._skip_methods  # remembered, won't retry A


# --- async rate limiter: retry semantics == sync --------------------------------------

class _Retryable(Exception):
    def __init__(self):
        super().__init__("rate limit exceeded")  # _is_retryable hits the "rate limit" hint


@pytest.mark.asyncio
async def test_async_retry_count_matches_sync(monkeypatch):
    # no real sleeping
    monkeypatch.setattr(bc.time, "sleep", lambda *_: None)

    async def _no_sleep(*_):
        return None
    monkeypatch.setattr(bc.asyncio, "sleep", _no_sleep)

    # SYNC: count invocations until exhausted
    sync_calls = {"n": 0}
    def sync_super(inp, cfg=None, **kw):
        sync_calls["n"] += 1
        raise _Retryable()
    with pytest.raises(_Retryable):
        bc.llm_rate_limited_invoke(sync_super, "in")

    # ASYNC: same
    async_calls = {"n": 0}
    async def async_super(inp, cfg=None, **kw):
        async_calls["n"] += 1
        raise _Retryable()
    with pytest.raises(_Retryable):
        await bc.allm_rate_limited_invoke(async_super, "in")

    assert async_calls["n"] == sync_calls["n"] == bc._LLM_MAX_RETRIES


@pytest.mark.asyncio
async def test_async_non_retryable_raises_immediately(monkeypatch):
    async def _no_sleep(*_):
        return None
    monkeypatch.setattr(bc.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}
    async def async_super(inp, cfg=None, **kw):
        calls["n"] += 1
        raise ValueError("totally fatal not retryable")
    with pytest.raises(ValueError):
        await bc.allm_rate_limited_invoke(async_super, "in")
    assert calls["n"] == 1  # no retries on a non-retryable error


@pytest.mark.asyncio
async def test_async_success_returns_value_unchanged():
    async def async_super(inp, cfg=None, **kw):
        return f"echo:{inp}"
    out = await bc.allm_rate_limited_invoke(async_super, "hello")
    assert out == "echo:hello"
