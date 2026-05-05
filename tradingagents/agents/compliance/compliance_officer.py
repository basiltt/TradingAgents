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
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

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
    "## Past Trade Context\n{past_context}\n\n"
    "Perform all compliance checks and provide your structured assessment."
)


def create_compliance_officer(llm, max_leverage: int = 20):
    structured_llm = bind_structured(llm, ComplianceCheck, "Compliance Officer")

    def node(state):
        company = state["company_of_interest"]
        instrument_context = build_instrument_context(company)
        trader_plan = state.get("trader_investment_plan", "")
        price_context = state.get("current_price_context", "")
        past_context = state.get("past_context", "")

        prompt = [
            {"role": "system", "content": _COMPLIANCE_SYSTEM},
            {
                "role": "user",
                "content": _COMPLIANCE_USER.format(
                    company=company,
                    instrument_context=instrument_context,
                    trader_plan=trader_plan,
                    price_context=price_context or "Not available",
                    past_context=past_context or "No prior trade history available",
                ),
            },
        ]

        text, obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_compliance_check,
            "Compliance Officer",
        )

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

        return {
            "messages": [AIMessage(content=text)],
            "compliance_result": text,
            "sender": "Compliance Officer",
            "_compliance_verdict": overall.value,
        }

    return node
