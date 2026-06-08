"""Phase 3 integration test: a real (small) LangGraph of CONVERTED dual-nodes produces
identical final state under sync .stream() and async .astream().

This is the end-to-end safety proof for the flag: the SAME graph, driven two ways, must
yield byte-identical output. It exercises the actual converted agent nodes (crypto bull/bear
researchers + the parallel-debate round) wired into a StateGraph, with a deterministic stub
LLM so any divergence would be a real ordering/merge bug, not LLM nondeterminism.
"""
import asyncio

from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from operator import add

from unittest.mock import MagicMock, AsyncMock

from tradingagents.agents.crypto_analysts import (
    create_crypto_bull_researcher,
    create_crypto_bear_researcher,
)
from tradingagents.graph.parallel_debate import create_parallel_researcher_round1


class _GState(TypedDict, total=False):
    investment_debate_state: dict
    market_report: str
    news_report: str
    derivatives_report: str
    crypto_fundamentals_report: str
    sentiment_report: str
    current_price_context: str
    company_of_interest: str
    crypto_interval: str
    messages: Annotated[list, add]


def _stub_llm(text: str):
    """An llm exposing BOTH sync .invoke and async .ainvoke returning the same content,
    so sync-graph and async-graph paths get identical model output."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=text)
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=text))
    return llm


def _build_graph():
    bull = create_crypto_bull_researcher(_stub_llm("BULL-CASE"))
    bear = create_crypto_bear_researcher(_stub_llm("BEAR-CASE"))
    debate = create_parallel_researcher_round1(bull, bear)

    g = StateGraph(_GState)
    g.add_node("debate", debate)
    g.add_edge(START, "debate")
    g.add_edge("debate", END)
    return g.compile()


def _initial_state():
    return {
        "investment_debate_state": {"history": "seed", "count": 0, "bull_history": "", "bear_history": ""},
        "market_report": "M", "news_report": "N", "derivatives_report": "D",
        "crypto_fundamentals_report": "CF", "sentiment_report": "S",
        "current_price_context": "P", "company_of_interest": "BTCUSDT", "crypto_interval": "15",
    }


def test_graph_sync_stream_vs_async_astream_identical():
    app = _build_graph()

    # sync path
    sync_chunks = list(app.stream(_initial_state()))

    # async path
    async def _run():
        return [c async for c in app.astream(_initial_state())]
    async_chunks = asyncio.run(_run())

    # final merged debate state must be identical
    sync_final = sync_chunks[-1]["debate"]["investment_debate_state"]
    async_final = async_chunks[-1]["debate"]["investment_debate_state"]
    assert sync_final == async_final, f"sync != async\nsync={sync_final}\nasync={async_final}"
    # both debaters contributed, count advanced by 2, bull-before-bear order preserved
    assert sync_final["count"] == 2
    assert "BULL-CASE" in sync_final["history"]
    assert "BEAR-CASE" in sync_final["history"]
    assert sync_final["history"].index("Bull") < sync_final["history"].index("Bear")
