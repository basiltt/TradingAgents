"""Execution Monitor: post-decision review that adds execution-readiness notes.

Sits after Portfolio Manager, before END in both flows.
Does NOT override the PM's decision — only appends warnings and monitoring notes.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)

logger = logging.getLogger(__name__)

_MONITOR_PROMPT = (
    "You are an Execution Monitor performing a final pre-execution review. "
    "The Portfolio Manager has made the final trading decision. Your job is to "
    "add execution-specific warnings and a monitoring plan — NOT to override "
    "the decision.\n\n"
    "Check for:\n"
    "1. **Stale Price Warning**: Flag if the price data may be outdated\n"
    "2. **Slippage Estimate**: Estimate expected slippage based on available data\n"
    "3. **Execution Timing**: Note optimal execution windows\n"
    "4. **Order Splitting**: Suggest splitting if the position is large\n"
    "5. **Post-Trade Monitoring**: Define what to watch after execution\n\n"
    "Be concise. Output a structured addendum.\n\n"
    "## Asset\n{instrument_context}\n\n"
    "## Current Price Data\n{price_context}\n\n"
    "## PM's Final Decision\n{final_decision}\n\n"
    "## Trader's Proposal\n{trader_plan}\n\n"
    "## Compliance Result\n{compliance_result}\n"
    "{language_instruction}"
)


def create_execution_monitor(llm):
    def node(state):
        instrument_context = build_instrument_context(state["company_of_interest"])
        price_context = state.get("current_price_context", "") or "Not available"
        final_decision = state.get("final_trade_decision", "")
        trader_plan = state.get("trader_investment_plan", "")
        compliance_result = state.get("compliance_result", "") or "Not reviewed"

        prompt = _MONITOR_PROMPT.format(
            instrument_context=instrument_context,
            price_context=price_context,
            final_decision=final_decision,
            trader_plan=trader_plan,
            compliance_result=compliance_result,
            language_instruction=get_language_instruction(),
        )

        response = llm.invoke(prompt)
        notes = response.content

        updated_decision = (
            final_decision
            + "\n\n---\n\n## Execution Monitor Notes\n"
            + notes
        )

        return {
            "messages": [AIMessage(content=notes)],
            "execution_notes": notes,
            "final_trade_decision": updated_decision,
            "sender": "Execution Monitor",
        }

    return node
