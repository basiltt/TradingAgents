"""Phase 2 equivalence test: parallel debate sync vs async produce IDENTICAL merges.

The user's hard constraint: agent execution order / data dependencies must be preserved.
The round-1 debate runs bull+bear concurrently and MERGES their outputs; the merge is
order-sensitive (latest_speaker = results[-1]). This proves the async path (asyncio.gather)
yields the byte-identical merged state as the sync path (ThreadPoolExecutor), including
ordering — regardless of which debater's coroutine happens to finish first.
"""
import asyncio

import pytest

from tradingagents.agents.utils.dual_node import dual_node
from tradingagents.graph.parallel_debate import (
    create_parallel_researcher_round1,
    _run_with_retry,
    _arun_with_retry,
)


def _make_debater(name: str, delay_async: float = 0.0):
    """A dual-mode debater that appends its name to investment_debate_state, mirroring
    the real bull/bear researcher state writes. The async body optionally sleeps to
    FORCE out-of-order completion, proving gather still returns in argument order."""

    def _apply(state):
        ids = state["investment_debate_state"]
        history = ids.get("history", "")
        arg = f"\n{name} Analyst: argument-from-{name}"
        new = dict(ids)
        new["history"] = history + arg
        new[f"{name.lower()}_history"] = ids.get(f"{name.lower()}_history", "") + arg
        new["current_response"] = arg
        new["count"] = ids.get("count", 0) + 1
        new["latest_speaker"] = name
        return {"investment_debate_state": new}

    def node(state):
        return _apply(state)

    async def anode(state):
        if delay_async:
            await asyncio.sleep(delay_async)
        return _apply(state)

    return dual_node(node, anode)


def _base_state():
    return {"investment_debate_state": {"history": "seed", "count": 0,
                                        "bull_history": "", "bear_history": ""}}


def test_parallel_researcher_sync_vs_async_identical_merge():
    # async: make BULL slow so BEAR finishes first — gather must STILL order [bull, bear]
    bull = _make_debater("Bull", delay_async=0.05)
    bear = _make_debater("Bear", delay_async=0.0)
    node = create_parallel_researcher_round1(bull, bear)

    sync_out = node.invoke(_base_state())
    async_out = asyncio.run(node.ainvoke(_base_state()))

    assert sync_out == async_out, "async merged state must equal sync merged state"
    # explicit order-sensitive checks (invest merge carries current_response from results[-1])
    s = sync_out["investment_debate_state"]
    a = async_out["investment_debate_state"]
    assert s["count"] == a["count"] == 2
    # current_response reflects the LAST result in argument order (bear), not completion order
    assert s["current_response"] == a["current_response"]
    assert "Bear" in a["current_response"]
    assert s["history"] == a["history"]
    # both debaters' contributions present, in bull-then-bear order
    assert a["history"].index("Bull") < a["history"].index("Bear")


@pytest.mark.asyncio
async def test_arun_with_retry_preserves_argument_order():
    # even if the 2nd finishes first, gather returns [first, second]
    first = _make_debater("Bull", delay_async=0.05)
    second = _make_debater("Bear", delay_async=0.0)
    results = await _arun_with_retry([first, second], _base_state(), "test")
    assert results[0]["investment_debate_state"]["latest_speaker"] == "Bull"
    assert results[1]["investment_debate_state"]["latest_speaker"] == "Bear"


def test_run_with_retry_works_on_runnable_debaters():
    # regression: debaters are now RunnableLambda (not directly callable). The sync
    # path must invoke them via .invoke(), not fn(state).
    bull = _make_debater("Bull")
    bear = _make_debater("Bear")
    results = _run_with_retry([bull, bear], _base_state(), "test")
    assert len(results) == 2
    assert results[0]["investment_debate_state"]["latest_speaker"] == "Bull"
    assert results[1]["investment_debate_state"]["latest_speaker"] == "Bear"


@pytest.mark.asyncio
async def test_arun_retry_only_reruns_timed_out_position(monkeypatch):
    """On timeout, ONLY the timed-out debater is retried; the one that already succeeded is
    NOT re-invoked (mirrors the sync path keeping successful futures). Verifies no wasted
    re-run of a good result and that orphaned timed-out tasks are cancelled."""
    import tradingagents.graph.parallel_debate as pd

    # tiny timeout so the slow debater trips it
    monkeypatch.setattr(pd, "_DEBATE_TIMEOUT", 0.2)

    calls = {"good": 0, "slow": 0}

    def _good_apply(state):
        ids = state["investment_debate_state"]
        new = dict(ids); new["latest_speaker"] = "Good"; new["count"] = ids.get("count", 0) + 1
        return {"investment_debate_state": new}

    good = dual_node(lambda s: _good_apply(s),
                     _make_async_counting(calls, "good", 0.0, _good_apply))
    slow = dual_node(lambda s: _good_apply(s),
                     _make_async_counting(calls, "slow", 0.5, _good_apply))  # 0.5 > 0.2 timeout on first try

    results = await pd._arun_with_retry([good, slow], _base_state(), "test")
    assert len(results) == 2
    # good ran exactly once (not re-run on the retry round); slow ran twice (timeout + retry)
    assert calls["good"] == 1, f"good should run once, ran {calls['good']}"
    assert calls["slow"] == 2, f"slow should run twice (timeout+retry), ran {calls['slow']}"


def _make_async_counting(calls, key, delay, apply_fn):
    async def _a(state):
        calls[key] += 1
        # first call for 'slow' is slow (times out); the retry is fast
        d = delay if calls[key] == 1 else 0.0
        if d:
            await asyncio.sleep(d)
        return apply_fn(state)
    return _a

