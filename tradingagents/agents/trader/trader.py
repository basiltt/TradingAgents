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
from tradingagents.agents.utils.prompt_guard import wrap_external_data
from tradingagents.agents.utils.state_filter import (
    filter_state_for_read,
    validate_state_write,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_DIRECTION_SYSTEM = (
    "You are a senior trader synthesising the research manager's investment "
    "plan into a directional trading decision. You receive the research "
    "manager's synthesised plan (not raw analyst reports) and any technical "
    "levels summary. Your job is to determine:\n\n"
    "1. **Direction**: Buy, Hold, or Sell\n"
    "2. **Confidence**: 1-10 conviction score based on signal alignment\n"
    "3. **Reasoning**: cite specific signals from the plan\n\n"
    "Scoring guide:\n"
    "- 1-3: Signals are weak or conflicting\n"
    "- 4-6: Moderate alignment, some uncertainty remains\n"
    "- 7-10: Strong alignment across all dimensions\n\n"
    "Do NOT calculate price levels yet — focus only on the directional decision."
)

_DIRECTION_USER = (
    "Analyse the following for {company} and decide the trading direction.\n"
    "{instrument_context}\n\n"
    "## Research Manager's Investment Plan\n{investment_plan}\n\n"
    "## Technical Levels Summary\n{technical_levels}\n\n"
    "Based on the alignment (or conflict) in the plan, provide your "
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


def _build_price_data_section(filtered: dict) -> str:
    """Build the price data section from filtered state data."""
    parts: list[str] = []

    price_ctx = filtered.get("current_price_context", "")
    if price_ctx and price_ctx.strip():
        parts.append("## LIVE PRICE DATA (real-time)\n" + wrap_external_data(price_ctx, "exchange_ticker"))

    tech_levels = filtered.get("technical_levels_summary", "")
    if tech_levels and tech_levels.strip():
        parts.append("## TECHNICAL LEVELS\n" + wrap_external_data(tech_levels, "technical_analyst"))

    if not parts:
        parts.append(
            "## PRICE DATA\n"
            "No live price data available. Use conservative estimates based on "
            "the investment plan and clearly state that levels are approximate."
        )

    return "\n\n".join(parts) + "\n\n"


def create_trader(llm):
    direction_llm = bind_structured(llm, TraderDirection, "Trader-Direction")
    levels_llm = bind_structured(llm, TraderProposal, "Trader-Levels")

    def trader_node(state, name):
        filtered = filter_state_for_read(state, "trader")
        company_name = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company_name, crypto_interval)
        investment_plan = wrap_external_data(filtered.get("investment_plan", ""), "research_manager")
        technical_levels = wrap_external_data(filtered.get("technical_levels_summary", "Not available"), "technical_analyst")

        # ---- Pass 1: Directional Decision ----
        direction_messages = [
            {"role": "system", "content": _DIRECTION_SYSTEM},
            {
                "role": "user",
                "content": _DIRECTION_USER.format(
                    company=company_name,
                    instrument_context=instrument_context,
                    investment_plan=investment_plan,
                    technical_levels=technical_levels,
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
        price_data_section = _build_price_data_section(filtered)

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
            filtered.get("current_price_context", "").strip()
        )
        if not has_live_prices and proposal_obj.entry_price is not None:
            levels_text += (
                "\n\n> **Note**: No live price feed was available. "
                "Entry, stop-loss, and take-profit levels are derived from "
                "analyst report data and should be verified against current "
                "market prices before execution."
            )

        updates = {
            "messages": [AIMessage(content=levels_text)],
            "trader_investment_plan": levels_text,
            "_trader_signal_data": proposal_obj,
            "sender": name,
        }
        return validate_state_write(updates, "trader")

    return functools.partial(trader_node, name="Trader")
