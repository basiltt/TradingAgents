"""Trader: two-pass agent that turns the Research Manager's plan into a concrete transaction proposal.

Pass 1 — Directional Decision: synthesises all analyst reports and the
research plan into an action (Buy/Hold/Sell) with confidence and reasoning.

Pass 2 — Level Calculation: given the direction from Pass 1 and real price
data (current_price_context for crypto, market_report for stocks), computes
entry, stop-loss, take-profit, sizing, order type, and execution strategy.
"""

from __future__ import annotations

import functools
import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    TraderDirection,
    TraderProposal,
    render_trader_proposal,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_DIRECTION_SYSTEM = (
    "You are a senior trader synthesising analyst reports into a directional "
    "trading decision. You have four analyst reports and a research manager's "
    "investment plan. Your job is to determine:\n\n"
    "1. **Direction**: Buy, Hold, or Sell\n"
    "2. **Confidence**: 1-10 conviction score based on analyst signal alignment\n"
    "3. **Reasoning**: cite specific signals from the reports\n\n"
    "Scoring guide:\n"
    "- 1-3: Analysts conflict or signals are weak/mixed\n"
    "- 4-6: Moderate alignment, some uncertainty remains\n"
    "- 7-10: Strong alignment across technicals, sentiment, news, and fundamentals\n\n"
    "Do NOT calculate price levels yet — focus only on the directional decision."
)

_DIRECTION_USER = (
    "Analyse the following reports for {company} and decide the trading direction.\n"
    "{instrument_context}\n\n"
    "## Research Manager's Investment Plan\n{investment_plan}\n\n"
    "## Market Analyst Report\n{market_report}\n\n"
    "## Sentiment Report\n{sentiment_report}\n\n"
    "## News Report\n{news_report}\n\n"
    "## Fundamentals Report\n{fundamentals_report}\n\n"
    "Based on the alignment (or conflict) across these reports, provide your "
    "directional decision."
)

_LEVELS_SYSTEM = (
    "You are a senior trader calculating precise execution levels for a trade. "
    "The directional decision has already been made by the desk — your job is "
    "to calculate execution levels, NOT to reconsider the direction.\n\n"
    "CRITICAL: Your output `action` field MUST match the directional decision "
    "provided below. Do not change it.\n\n"
    "Requirements:\n"
    "- **Entry price**: must be close to the current market price, not invented\n"
    "- **Stop-loss**: based on ATR, recent support/resistance, or volatility — "
    "not an arbitrary percentage\n"
    "- **Take-profit levels**: 1-3 targets at realistic resistance/extension levels\n"
    "- **Risk/reward ratio**: should be >= 1.5 to justify the trade\n"
    "- **Position sizing**: as percentage of portfolio, volatility-adjusted "
    "(higher volatility = smaller size)\n"
    "- **Order type**: Market for urgency, Limit for patient entries, "
    "Stop-Limit for breakout setups\n"
    "- **Scaling plan**: how to distribute entry/exit across levels\n"
    "- **Invalidation thesis**: what would make this trade wrong\n"
    "- **Catalyst timing**: any upcoming events that affect timing\n\n"
    "If the direction is Hold, set entry_price to the current price and "
    "leave stop/TP levels null. Focus on invalidation and catalyst timing."
)

_LEVELS_USER = (
    "Execute level calculation for {company}.\n"
    "{instrument_context}\n\n"
    "## Your Directional Decision\n"
    "Action: {action} | Confidence: {confidence}/10\n"
    "Reasoning: {reasoning}\n\n"
    "{price_data_section}"
    "Calculate precise execution levels grounded in the price data above."
)


def _build_price_data_section(state: dict) -> str:
    """Build the price data section from available state data."""
    parts: list[str] = []

    price_ctx = state.get("current_price_context", "")
    if price_ctx and price_ctx.strip():
        parts.append("## LIVE PRICE DATA (real-time)\n" + price_ctx)

    market_report = state.get("market_report", "")
    if market_report and market_report.strip():
        parts.append(
            "## TECHNICAL INDICATORS (from Market Analyst)\n" + market_report
        )

    if not parts:
        parts.append(
            "## PRICE DATA\n"
            "No live price data available. Use conservative estimates based on "
            "the analyst reports and clearly state that levels are approximate."
        )

    return "\n\n".join(parts) + "\n\n"


def create_trader(llm):
    direction_llm = bind_structured(llm, TraderDirection, "Trader-Direction")
    levels_llm = bind_structured(llm, TraderProposal, "Trader-Levels")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state.get("investment_plan", "")

        # ---- Pass 1: Directional Decision ----
        direction_messages = [
            {"role": "system", "content": _DIRECTION_SYSTEM},
            {
                "role": "user",
                "content": _DIRECTION_USER.format(
                    company=company_name,
                    instrument_context=instrument_context,
                    investment_plan=investment_plan,
                    market_report=state.get("market_report", "N/A"),
                    sentiment_report=state.get("sentiment_report", "N/A"),
                    news_report=state.get("news_report", "N/A"),
                    fundamentals_report=state.get(
                        "fundamentals_report",
                        state.get("crypto_fundamentals_report", "N/A"),
                    ),
                ),
            },
        ]

        direction_text, direction_obj = invoke_structured_or_freetext(
            direction_llm,
            llm,
            direction_messages,
            lambda d: (
                f"**Action**: {d.action.value}\n"
                f"**Confidence**: {d.confidence}/10\n"
                f"**Reasoning**: {d.reasoning}"
            ),
            "Trader-Direction",
            schema=TraderDirection,
        )

        if direction_obj is not None:
            action = direction_obj.action.value
            confidence = direction_obj.confidence
            reasoning = direction_obj.reasoning
        else:
            action = "Hold"
            confidence = 1
            reasoning = direction_text
            logger.warning(
                "Trader-Direction: structured output failed for %s; "
                "defaulting to Hold with confidence 1. Freetext: %s",
                company_name, direction_text[:200],
            )

        # ---- Pass 2: Level Calculation ----
        price_data_section = _build_price_data_section(state)

        levels_messages = [
            {"role": "system", "content": _LEVELS_SYSTEM},
            {
                "role": "user",
                "content": _LEVELS_USER.format(
                    company=company_name,
                    instrument_context=instrument_context,
                    action=action,
                    confidence=confidence,
                    reasoning=reasoning,
                    price_data_section=price_data_section,
                ),
            },
        ]

        levels_text, proposal_obj = invoke_structured_or_freetext(
            levels_llm,
            llm,
            levels_messages,
            render_trader_proposal,
            "Trader-Levels",
            schema=TraderProposal,
        )

        from tradingagents.agents.schemas import TraderAction

        if proposal_obj is None:
            proposal_obj = TraderProposal(
                action=TraderAction(action),
                confidence=confidence,
                reasoning=reasoning,
            )
            levels_text = render_trader_proposal(proposal_obj)
        elif proposal_obj.action.value != action:
            logger.warning(
                "Trader-Levels: Pass 2 returned action=%s but Pass 1 decided %s "
                "for %s; overriding to match Pass 1.",
                proposal_obj.action.value, action, company_name,
            )
            proposal_obj = proposal_obj.model_copy(
                update={"action": TraderAction(action)}
            )
            levels_text = render_trader_proposal(proposal_obj)

        has_live_prices = bool(
            state.get("current_price_context", "").strip()
        )
        if not has_live_prices and proposal_obj.entry_price is not None:
            levels_text += (
                "\n\n> **Note**: No live price feed was available. "
                "Entry, stop-loss, and take-profit levels are derived from "
                "analyst report data and should be verified against current "
                "market prices before execution."
            )

        return {
            "messages": [AIMessage(content=levels_text)],
            "trader_investment_plan": levels_text,
            "_trader_signal_data": proposal_obj,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
