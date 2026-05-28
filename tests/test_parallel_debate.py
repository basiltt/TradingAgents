"""Tests for parallel debate wrappers (performance optimization)."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from tradingagents.graph.parallel_debate import (
    create_parallel_risk_round1,
    create_parallel_researcher_round1,
    _run_with_retry,
    reset_debate_executor,
)


@pytest.fixture(autouse=True)
def _reset_executor():
    reset_debate_executor()
    yield
    reset_debate_executor()


def _base_state():
    return {
        "messages": [],
        "company_of_interest": "BTCUSDT",
        "trade_date": "2025-01-15",
        "market_report": "bullish",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_plan": "",
        "current_price_context": "Last Traded Price: $100000.00",
        "trader_investment_plan": "Long BTC 5x",
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "final_trade_decision": "",
        "past_context": "",
    }


class TestParallelRiskRound1:
    def test_merges_two_debaters(self):
        def bull_debater(state):
            return {"risk_debate_state": {
                "history": "\nBull Analyst: bullish",
                "aggressive_history": "\nBull Analyst: bullish",
                "conservative_history": "",
                "neutral_history": "",
                "latest_speaker": "Bull",
                "current_aggressive_response": "Bull Analyst: bullish",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 1,
            }}

        def bear_debater(state):
            return {"risk_debate_state": {
                "history": "\nBear Analyst: bearish",
                "aggressive_history": "",
                "conservative_history": "\nBear Analyst: bearish",
                "neutral_history": "",
                "latest_speaker": "Bear",
                "current_aggressive_response": "",
                "current_conservative_response": "Bear Analyst: bearish",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 1,
            }}

        node = create_parallel_risk_round1([bull_debater, bear_debater])
        result = node(_base_state())

        rds = result["risk_debate_state"]
        assert rds["count"] == 2
        assert "Bull Analyst: bullish" in rds["history"]
        assert "Bear Analyst: bearish" in rds["history"]
        assert rds["current_aggressive_response"] == "Bull Analyst: bullish"
        assert rds["current_conservative_response"] == "Bear Analyst: bearish"

    def test_merges_three_debaters(self):
        def agg(state):
            return {"risk_debate_state": {
                "history": "\nAggressive Analyst: agg",
                "aggressive_history": "\nAggressive Analyst: agg",
                "conservative_history": "",
                "neutral_history": "",
                "latest_speaker": "Aggressive",
                "current_aggressive_response": "Aggressive Analyst: agg",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 1,
            }}

        def con(state):
            return {"risk_debate_state": {
                "history": "\nConservative Analyst: con",
                "aggressive_history": "",
                "conservative_history": "\nConservative Analyst: con",
                "neutral_history": "",
                "latest_speaker": "Conservative",
                "current_aggressive_response": "",
                "current_conservative_response": "Conservative Analyst: con",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 1,
            }}

        def neu(state):
            return {"risk_debate_state": {
                "history": "\nNeutral Analyst: neu",
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "\nNeutral Analyst: neu",
                "latest_speaker": "Neutral",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "Neutral Analyst: neu",
                "judge_decision": "",
                "count": 1,
            }}

        node = create_parallel_risk_round1([agg, con, neu])
        result = node(_base_state())

        rds = result["risk_debate_state"]
        assert rds["count"] == 3
        assert "Aggressive Analyst: agg" in rds["history"]
        assert "Conservative Analyst: con" in rds["history"]
        assert "Neutral Analyst: neu" in rds["history"]

    def test_actually_runs_in_parallel(self):
        barrier = threading.Barrier(2, timeout=5)

        def slow_bull(state):
            barrier.wait()
            return {"risk_debate_state": {
                "history": "\nbull", "aggressive_history": "\nbull",
                "conservative_history": "", "neutral_history": "",
                "latest_speaker": "Bull", "current_aggressive_response": "bull",
                "current_conservative_response": "", "current_neutral_response": "",
                "judge_decision": "", "count": 1,
            }}

        def slow_bear(state):
            barrier.wait()
            return {"risk_debate_state": {
                "history": "\nbear", "aggressive_history": "",
                "conservative_history": "\nbear", "neutral_history": "",
                "latest_speaker": "Bear", "current_aggressive_response": "",
                "current_conservative_response": "bear", "current_neutral_response": "",
                "judge_decision": "", "count": 1,
            }}

        node = create_parallel_risk_round1([slow_bull, slow_bear])
        result = node(_base_state())
        assert result["risk_debate_state"]["count"] == 2

    def test_propagates_exceptions(self):
        def good(state):
            return {"risk_debate_state": {
                "history": "\nok", "aggressive_history": "", "conservative_history": "",
                "neutral_history": "", "latest_speaker": "Bull",
                "current_aggressive_response": "", "current_conservative_response": "",
                "current_neutral_response": "", "judge_decision": "", "count": 1,
            }}

        def bad(state):
            raise RuntimeError("LLM failed")

        node = create_parallel_risk_round1([good, bad])
        with pytest.raises(RuntimeError, match="LLM failed"):
            node(_base_state())


class TestParallelResearcherRound1:
    def test_merges_bull_and_bear(self):
        def bull(state):
            return {"investment_debate_state": {
                "history": "\nBull Analyst: bull case",
                "bull_history": "\nBull Analyst: bull case",
                "bear_history": "",
                "current_response": "Bull Analyst: bull case",
                "count": 1,
            }}

        def bear(state):
            return {"investment_debate_state": {
                "history": "\nBear Analyst: bear case",
                "bull_history": "",
                "bear_history": "\nBear Analyst: bear case",
                "current_response": "Bear Analyst: bear case",
                "count": 1,
            }}

        node = create_parallel_researcher_round1(bull, bear)
        result = node(_base_state())

        ids = result["investment_debate_state"]
        assert ids["count"] == 2
        assert "Bull Analyst: bull case" in ids["history"]
        assert "Bear Analyst: bear case" in ids["history"]
        assert ids["bull_history"].strip() == "Bull Analyst: bull case"
        assert ids["bear_history"].strip() == "Bear Analyst: bear case"
        # Last result is bear, so current_response should be bear's
        assert ids["current_response"] == "Bear Analyst: bear case"

    def test_actually_runs_in_parallel(self):
        barrier = threading.Barrier(2, timeout=5)

        def bull(state):
            barrier.wait()
            return {"investment_debate_state": {
                "history": "\nbull", "bull_history": "\nbull", "bear_history": "",
                "current_response": "bull", "count": 1,
            }}

        def bear(state):
            barrier.wait()
            return {"investment_debate_state": {
                "history": "\nbear", "bull_history": "", "bear_history": "\nbear",
                "current_response": "bear", "count": 1,
            }}

        node = create_parallel_researcher_round1(bull, bear)
        result = node(_base_state())
        assert result["investment_debate_state"]["count"] == 2


class TestRunWithRetry:
    """Tests for the timeout-and-retry mechanism."""

    def test_retry_succeeds_after_first_timeout(self):
        call_count = [0]

        def slow_then_fast(state):
            call_count[0] += 1
            if call_count[0] == 1:
                time.sleep(5)  # will exceed our patched timeout
            return {"value": "ok"}

        def fast(state):
            return {"value": "fast"}

        with patch("tradingagents.graph.parallel_debate._DEBATE_TIMEOUT", 1):
            results = _run_with_retry([slow_then_fast, fast], {}, "test")

        assert results[0] == {"value": "ok"}
        assert results[1] == {"value": "fast"}
        assert call_count[0] == 2  # first attempt + retry

    def test_raises_after_retry_also_times_out(self):
        def always_slow(state):
            time.sleep(5)
            return {"value": "never"}

        def fast(state):
            return {"value": "fast"}

        with patch("tradingagents.graph.parallel_debate._DEBATE_TIMEOUT", 1):
            with pytest.raises(RuntimeError, match="timed out after retry"):
                _run_with_retry([always_slow, fast], {}, "test")

    def test_no_retry_when_all_succeed(self):
        call_counts = [0, 0]

        def fn0(state):
            call_counts[0] += 1
            return {"value": 0}

        def fn1(state):
            call_counts[1] += 1
            return {"value": 1}

        results = _run_with_retry([fn0, fn1], {}, "test")
        assert results == [{"value": 0}, {"value": 1}]
        assert call_counts == [1, 1]
