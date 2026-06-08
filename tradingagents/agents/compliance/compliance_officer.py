"""Compliance Officer: pre-trade gate that validates proposals against institutional rules.

Sits between Trader and Risk Analysts in both stock and crypto flows.
Never changes the trade — only passes, flags, or blocks it.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    ComplianceCheck,
    ComplianceVerdict,
    render_compliance_check,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.dual_node import dual_node
from tradingagents.agents.utils.structured import (
    ainvoke_structured_or_freetext,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.utils.prompt_guard import wrap_external_data

logger = logging.getLogger(__name__)

_COMPLIANCE_SYSTEM = (
    "You are an institutional Compliance Officer reviewing a proposed trade. "
    "Your job is to validate the proposal against risk management rules. "
    "You do NOT make trading decisions — you only gate them.\n\n"
    "For each check, assign a verdict:\n"
    "- **Pass**: The proposal meets the requirement\n"
    "- **Flag**: A concern that should be noted but doesn't block the trade\n"
    "- **Block**: A violation that prevents the trade from proceeding\n\n"
    "Checks to perform:\n"
    "1. **Position Size**: Block if sizing exceeds 10% of portfolio\n"
    "2. **Leverage Cap**: Block if leverage exceeds the configured maximum\n"
    "3. **Stop-Loss Presence**: Block if no stop-loss is defined for a directional trade\n"
    "4. **Price Sanity**: Flag if entry price deviates >5% from current market price\n"
    "5. **Risk/Reward Floor**: Flag if risk:reward ratio < 1.0\n"
    "6. **Concentration Risk**: Flag if past trades show repeated exposure to this asset\n\n"
    "Overall verdict: Block if ANY check is Block. Flag if any is Flag. Pass otherwise."
)

_COMPLIANCE_USER = (
    "Review the following trade proposal for {company}.\n"
    "{instrument_context}\n\n"
    "## Trader's Proposal\n{trader_plan}\n\n"
    "## Current Price Data\n{price_context}\n\n"
    "Perform all compliance checks and provide your structured assessment."
)


def create_compliance_officer(llm, max_leverage: int = 20):
    structured_llm = bind_structured(llm, ComplianceCheck, "Compliance Officer")

    def _prepare(state):
        from tradingagents.agents.utils.state_filter import filter_state_for_read, validate_state_write

        filtered = filter_state_for_read(state, "compliance_officer")
        company = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company, crypto_interval)
        trader_plan = wrap_external_data(filtered.get("trader_investment_plan", ""), "trader")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")

        prompt = [
            {"role": "system", "content": _COMPLIANCE_SYSTEM},
            {
                "role": "user",
                "content": _COMPLIANCE_USER.format(
                    company=company,
                    instrument_context=instrument_context,
                    trader_plan=trader_plan,
                    price_context=price_context or "Not available",
                ),
            },
        ]

        return prompt

    def _apply(text, obj):
        from tradingagents.agents.utils.state_filter import validate_state_write

        if obj is not None:
            # Programmatic override: if ANY individual finding is Block,
            # force overall to Block regardless of what the LLM returned.
            if any(f.verdict == ComplianceVerdict.BLOCK for f in obj.findings):
                overall = ComplianceVerdict.BLOCK
            elif any(f.verdict == ComplianceVerdict.FLAG for f in obj.findings):
                overall = ComplianceVerdict.FLAG if obj.overall_verdict != ComplianceVerdict.BLOCK else ComplianceVerdict.BLOCK
            else:
                overall = obj.overall_verdict
        else:
            # Fail-closed: structured parse failure defaults to BLOCK.
            # A compliance gate on real money must never fail-open.
            if "pass" in text.lower() and "block" not in text.lower():
                overall = ComplianceVerdict.FLAG
                logger.warning(
                    "Compliance Officer: structured parsing failed; "
                    "freetext mentions 'pass' but defaulting to FLAG for safety."
                )
            else:
                overall = ComplianceVerdict.BLOCK
                logger.warning(
                    "Compliance Officer: structured parsing failed; "
                    "defaulting to BLOCK (fail-closed)."
                )

        updates = {
            "messages": [AIMessage(content=text)],
            "compliance_result": text,
            "sender": "Compliance Officer",
            "_compliance_verdict": overall.value,
        }
        return validate_state_write(updates, "compliance_officer")

    def node(state):
        prompt = _prepare(state)
        text, obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_compliance_check,
            "Compliance Officer",
            schema=ComplianceCheck,
        )
        return _apply(text, obj)

    async def anode(state):
        prompt = _prepare(state)
        text, obj = await ainvoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_compliance_check,
            "Compliance Officer",
            schema=ComplianceCheck,
        )
        return _apply(text, obj)

    return dual_node(node, anode)
