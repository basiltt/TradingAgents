"""Tests for structured-output agents (Trader and Research Manager).

The Portfolio Manager has its own coverage in tests/test_memory_log.py
(which exercises the full memory-log → PM injection cycle).  This file
covers the parallel schemas, render functions, and graceful-fallback
behavior we added for the Trader and Research Manager so all three
decision-making agents share the same shape.
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.schemas import (
    OrderType,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderDirection,
    TraderProposal,
    render_research_plan,
    render_trader_proposal,
)
from tradingagents.agents.trader.trader import create_trader


# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderTraderProposal:
    def test_minimal_required_fields(self):
        p = TraderProposal(action=TraderAction.HOLD, reasoning="Balanced setup; no edge.")
        md = render_trader_proposal(p)
        assert "**Action**: Hold" in md
        assert "**Reasoning**: Balanced setup; no edge." in md
        # The trailing FINAL TRANSACTION PROPOSAL line is preserved for the
        # analyst stop-signal text and any external code that greps for it.
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in md

    def test_optional_fields_included_when_present(self):
        p = TraderProposal(
            action=TraderAction.BUY,
            reasoning="Strong technicals + fundamentals.",
            entry_price=189.5,
            stop_loss=178.0,
            position_sizing="6% of portfolio",
            order_type=OrderType.LIMIT,
            scaling_plan="50% at TP1, 50% at TP2",
            invalidation_thesis="Close below 200 SMA invalidates the thesis.",
            catalyst_timing="Earnings May 15 — enter before.",
        )
        md = render_trader_proposal(p)
        assert "**Action**: Buy" in md
        assert "**Entry Price**: 189.5" in md
        assert "**Stop Loss**: 178.0" in md
        assert "**Position Sizing**: 6% of portfolio" in md
        assert "**Order Type**: Limit" in md
        assert "**Scaling Plan**: 50% at TP1" in md
        assert "**Invalidation Thesis**: Close below 200 SMA" in md
        assert "**Catalyst/Timing**: Earnings May 15" in md
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in md

    def test_optional_fields_omitted_when_absent(self):
        p = TraderProposal(action=TraderAction.SELL, reasoning="Guidance cut.")
        md = render_trader_proposal(p)
        assert "Entry Price" not in md
        assert "Stop Loss" not in md
        assert "Position Sizing" not in md
        assert "FINAL TRANSACTION PROPOSAL: **SELL**" in md


@pytest.mark.unit
class TestRenderResearchPlan:
    def test_required_fields(self):
        p = ResearchPlan(
            recommendation=PortfolioRating.OVERWEIGHT,
            rationale="Bull case carried; tailwinds intact.",
            strategic_actions="Build position over two weeks; cap at 5%.",
        )
        md = render_research_plan(p)
        assert "**Recommendation**: Overweight" in md
        assert "**Rationale**: Bull case carried" in md
        assert "**Strategic Actions**: Build position" in md

    def test_all_5_tier_ratings_render(self):
        for rating in PortfolioRating:
            p = ResearchPlan(
                recommendation=rating,
                rationale="r",
                strategic_actions="s",
            )
            md = render_research_plan(p)
            assert f"**Recommendation**: {rating.value}" in md


# ---------------------------------------------------------------------------
# Trader agent: structured happy path + fallback
# ---------------------------------------------------------------------------


def _make_trader_state():
    return {
        "company_of_interest": "NVDA",
        "investment_plan": "**Recommendation**: Buy\n**Rationale**: ...\n**Strategic Actions**: ...",
        "market_report": "RSI: 65, ATR: 3.2, Close: 189.0, MACD: positive",
        "sentiment_report": "73% bullish sentiment across retail and institutional.",
        "news_report": "Earnings beat expectations by 12%.",
        "fundamentals_report": "P/E 25x, revenue growth 15%, strong free cash flow.",
        "current_price_context": "",
    }


def _two_pass_trader_llm(
    captured: dict,
    direction: TraderDirection | None = None,
    proposal: TraderProposal | None = None,
):
    """Build a mock LLM that handles both with_structured_output bindings.

    The LLM's with_structured_output is called twice: once for TraderDirection
    (Pass 1) and once for TraderProposal (Pass 2). Each returns its own mock.
    """
    if direction is None:
        direction = TraderDirection(
            action=TraderAction.BUY,
            confidence=8,
            reasoning="Strong alignment across all four reports.",
        )
    if proposal is None:
        proposal = TraderProposal(
            action=TraderAction.BUY,
            confidence=8,
            reasoning="Strong alignment across all four reports.",
            entry_price=189.0,
            stop_loss=185.0,
        )

    direction_mock = MagicMock()
    def _direction_invoke(prompt):
        captured["direction_prompt"] = prompt
        return direction
    direction_mock.invoke.side_effect = _direction_invoke

    proposal_mock = MagicMock()
    def _levels_invoke(prompt):
        captured["levels_prompt"] = prompt
        return proposal
    proposal_mock.invoke.side_effect = _levels_invoke

    call_count = {"n": 0}

    def with_structured_output(schema, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return direction_mock
        return proposal_mock

    llm = MagicMock()
    llm.with_structured_output.side_effect = with_structured_output
    return llm


@pytest.mark.unit
class TestTraderAgent:
    def test_two_pass_produces_rendered_markdown(self):
        captured = {}
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="AI capex cycle intact; institutional flows constructive.",
            entry_price=189.5,
            stop_loss=178.0,
            position_sizing="6% of portfolio",
            order_type=OrderType.LIMIT,
        )
        llm = _two_pass_trader_llm(captured, proposal=proposal)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        plan = result["trader_investment_plan"]
        assert "**Action**: Buy" in plan
        assert "**Entry Price**: 189.5" in plan
        assert "**Order Type**: Limit" in plan
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in plan
        assert plan in result["messages"][0].content

    def test_pass1_receives_all_analyst_reports(self):
        captured = {}
        llm = _two_pass_trader_llm(captured)
        trader = create_trader(llm)
        trader(_make_trader_state())
        prompt = captured["direction_prompt"]
        user_msg = next(m["content"] for m in prompt if m["role"] == "user")
        assert "Investment Plan" in user_msg
        assert "Technical Levels Summary" in user_msg

    def test_pass2_receives_price_data(self):
        captured = {}
        state = _make_trader_state()
        state["current_price_context"] = "Last Price: 95000.0\n24h High: 96500.0"
        llm = _two_pass_trader_llm(captured)
        trader = create_trader(llm)
        trader(state)
        prompt = captured["levels_prompt"]
        user_msg = next(m["content"] for m in prompt if m["role"] == "user")
        assert "LIVE PRICE DATA" in user_msg
        assert "95000.0" in user_msg

    def test_pass2_uses_technical_levels_when_no_live_data(self):
        captured = {}
        state = _make_trader_state()
        state["current_price_context"] = ""
        state["technical_levels_summary"] = "RSI: 65, ATR: 3.2, Close: 189.0"
        llm = _two_pass_trader_llm(captured)
        trader = create_trader(llm)
        trader(state)
        prompt = captured["levels_prompt"]
        user_msg = next(m["content"] for m in prompt if m["role"] == "user")
        assert "TECHNICAL LEVELS" in user_msg
        assert "RSI: 65" in user_msg

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = (
            "**Action**: Sell\n\nGuidance cut hits margins.\n\n"
            "FINAL TRANSACTION PROPOSAL: **SELL**"
        )
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        plan = result["trader_investment_plan"]
        assert "FINAL TRANSACTION PROPOSAL" in plan

    def test_signal_data_returned(self):
        captured = {}
        direction = TraderDirection(
            action=TraderAction.SELL,
            confidence=7,
            reasoning="Breakdown confirmed across technicals and sentiment.",
        )
        proposal = TraderProposal(
            action=TraderAction.SELL,
            reasoning="Breakdown confirmed.",
            entry_price=180.0,
            stop_loss=185.0,
            invalidation_thesis="Reclaim above 186 invalidates.",
        )
        llm = _two_pass_trader_llm(captured, direction=direction, proposal=proposal)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        obj = result["_trader_signal_data"]
        assert obj.action == TraderAction.SELL
        assert obj.invalidation_thesis == "Reclaim above 186 invalidates."

    def test_pass2_action_override_matches_pass1(self):
        """If Pass 2 LLM returns a different action than Pass 1 decided,
        the final proposal must be corrected to match Pass 1."""
        captured = {}
        direction = TraderDirection(
            action=TraderAction.BUY,
            confidence=8,
            reasoning="Strong buy signal.",
        )
        proposal = TraderProposal(
            action=TraderAction.SELL,
            reasoning="Contradictory output.",
            entry_price=100.0,
            stop_loss=95.0,
        )
        llm = _two_pass_trader_llm(captured, direction=direction, proposal=proposal)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        obj = result["_trader_signal_data"]
        assert obj.action == TraderAction.BUY
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in result["trader_investment_plan"]

    def test_no_live_price_warning_appended(self):
        """When no live price data is available and levels are produced,
        a warning note must be appended to the output."""
        captured = {}
        state = _make_trader_state()
        state["current_price_context"] = ""
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="Strong setup.",
            entry_price=189.0,
            stop_loss=185.0,
        )
        llm = _two_pass_trader_llm(captured, proposal=proposal)
        trader = create_trader(llm)
        result = trader(state)
        assert "No live price feed was available" in result["trader_investment_plan"]

    def test_live_price_no_warning(self):
        """When live price data IS available, no warning is appended."""
        captured = {}
        state = _make_trader_state()
        state["current_price_context"] = "Last Price: 95000.0\n24h High: 96500.0"
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="Strong setup.",
            entry_price=95100.0,
            stop_loss=94000.0,
        )
        llm = _two_pass_trader_llm(captured, proposal=proposal)
        trader = create_trader(llm)
        result = trader(state)
        assert "No live price feed" not in result["trader_investment_plan"]


# ---------------------------------------------------------------------------
# Research Manager agent: structured happy path + fallback
# ---------------------------------------------------------------------------


def _make_rm_state():
    return {
        "company_of_interest": "NVDA",
        "investment_debate_state": {
            "history": "Bull and bear arguments here.",
            "bull_history": "Bull says...",
            "bear_history": "Bear says...",
            "current_response": "",
            "judge_decision": "",
            "count": 1,
        },
    }


def _structured_rm_llm(captured: dict, plan: ResearchPlan | None = None):
    if plan is None:
        plan = ResearchPlan(
            recommendation=PortfolioRating.HOLD,
            rationale="Balanced view across both sides.",
            strategic_actions="Hold current position; reassess after earnings.",
        )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or plan
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
class TestResearchManagerAgent:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        plan = ResearchPlan(
            recommendation=PortfolioRating.OVERWEIGHT,
            rationale="Bull case is stronger; AI tailwind intact.",
            strategic_actions="Build position gradually over two weeks.",
        )
        llm = _structured_rm_llm(captured, plan)
        rm = create_research_manager(llm)
        result = rm(_make_rm_state())
        ip = result["investment_plan"]
        assert "**Recommendation**: Overweight" in ip
        assert "**Rationale**: Bull case" in ip
        assert "**Strategic Actions**: Build position" in ip

    def test_prompt_uses_5_tier_rating_scale(self):
        """The RM prompt must list all five tiers so the schema enum matches user expectations."""
        captured = {}
        llm = _structured_rm_llm(captured)
        rm = create_research_manager(llm)
        rm(_make_rm_state())
        prompt = captured["prompt"]
        for tier in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            assert f"**{tier}**" in prompt, f"missing {tier} in prompt"

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = "**Recommendation**: Sell\n\n**Rationale**: ...\n\n**Strategic Actions**: ..."
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        rm = create_research_manager(llm)
        result = rm(_make_rm_state())
        assert result["investment_plan"] == plain_response
