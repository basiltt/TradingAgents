"""Risk Manager: independent risk gate between Compliance and Risk Debate.

Performs quantitative risk checks on the trader's proposal using market
microstructure data. Fail-closed: structured parse failure defaults to Reject.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    RiskAssessment,
    RiskVerdict,
    render_risk_assessment,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.dual_node import dual_node
from tradingagents.agents.utils.state_filter import (
    filter_state_for_read,
    validate_state_write,
)
from tradingagents.agents.utils.structured import (
    ainvoke_structured_or_freetext,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.utils.prompt_guard import wrap_external_data

logger = logging.getLogger(__name__)

_RISK_SYSTEM = (
    "You are an institutional Risk Manager performing quantitative risk checks "
    "on a proposed trade. You have independent veto power.\n\n"
    "You do NOT have access to any market data tools. Do NOT attempt to call "
    "get_klines, get_crypto_klines, get_crypto_indicators, or any other "
    "data-fetching function. Base your assessment solely on the data provided below.\n\n"
    "For each check, assign a verdict:\n"
    "- **Approve**: Risk is acceptable\n"
    "- **Modify**: Risk can be managed by adjusting parameters\n"
    "- **Reject**: Risk is unacceptable, trade should not proceed\n\n"
    "Checks to perform:\n"
    "1. **Position Size**: Reject if > 10% of portfolio\n"
    "2. **Leverage vs Volatility**: Reject if leverage > 10x in High volatility regime\n"
    "3. **Liquidation Proximity**: Reject if liquidation price is within 2x ATR of entry\n"
    "4. **Funding Rate Impact**: Modify if projected funding cost > 1% of expected profit\n"
    "5. **Order Book Liquidity**: Modify if spread > 10bps or insufficient depth\n"
    "6. **Risk/Reward Ratio**: Modify if < 1.5\n"
    "7. **Correlation Concentration**: Flag if multiple open positions in same sector\n"
    "8. **Volatility Regime Sizing**: Modify to reduce size in High volatility\n\n"
    "Overall verdict: Reject if ANY check is Reject. Modify if any is Modify. "
    "Approve otherwise.\n\n"
    "Provide a risk score 0-100 (0 = no risk, 100 = maximum risk).\n"
    "If modifying, specify adjusted_leverage and/or adjusted_position_size."
)

_RISK_USER = (
    "Review the following trade proposal for {company}.\n"
    "{instrument_context}\n\n"
    "Max allowed leverage: {max_leverage}x\n\n"
    "## Trader's Proposal\n{trader_plan}\n\n"
    "## Current Price Data\n{price_context}\n\n"
    "## Market Microstructure\n{microstructure}\n\n"
    "{performance_section}"
    "Perform all risk checks and provide your structured assessment."
)


def create_risk_manager(llm, max_leverage: int = 20):
    structured_llm = bind_structured(llm, RiskAssessment, "Risk Manager")

    def _prepare(state):
        filtered = filter_state_for_read(state, "risk_manager")
        company = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company, crypto_interval)
        trader_plan = wrap_external_data(filtered.get("trader_investment_plan", ""), "trader")
        price_context = wrap_external_data(filtered.get("current_price_context", ""), "exchange_ticker")
        microstructure = filtered.get("market_microstructure", "")
        cfg_max_leverage = filtered.get("max_leverage") or max_leverage
        performance_context = filtered.get("performance_context") or ""

        micro_str = wrap_external_data(str(microstructure) if microstructure else "Not available", "market_microstructure")

        performance_section = ""
        if performance_context:
            performance_section = (
                f"## Historical Signal Performance\n{performance_context}\n\n"
                "Consider the above performance history when assessing position sizing risk: "
                "flag elevated risk in regimes with historically poor win rates.\n\n"
            )

        prompt = [
            {"role": "system", "content": _RISK_SYSTEM},
            {
                "role": "user",
                "content": _RISK_USER.format(
                    company=company,
                    instrument_context=instrument_context,
                    max_leverage=cfg_max_leverage,
                    trader_plan=trader_plan,
                    price_context=price_context or "Not available",
                    microstructure=micro_str,
                    performance_section=performance_section,
                ),
            },
        ]

        return cfg_max_leverage, prompt

    def _apply(cfg_max_leverage, text, obj):
        if obj is not None:
            if not obj.findings:
                overall = RiskVerdict.REJECT
                logger.warning(
                    "Risk Manager: LLM returned empty findings list; "
                    "defaulting to REJECT (fail-closed)."
                )
            elif any(f.verdict == RiskVerdict.REJECT for f in obj.findings):
                overall = RiskVerdict.REJECT
            elif any(f.verdict == RiskVerdict.MODIFY for f in obj.findings):
                overall = RiskVerdict.MODIFY if obj.overall_verdict != RiskVerdict.REJECT else RiskVerdict.REJECT
            else:
                overall = obj.overall_verdict

            if obj.adjusted_leverage is not None:
                obj = obj.model_copy(
                    update={"adjusted_leverage": min(obj.adjusted_leverage, cfg_max_leverage)}
                )
        else:
            overall = RiskVerdict.REJECT
            logger.warning(
                "Risk Manager: structured parsing failed; "
                "defaulting to REJECT (fail-closed)."
            )

        updates = {
            "messages": [AIMessage(content=text)],
            "risk_manager_result": text,
            "sender": "Risk Manager",
            "_risk_manager_verdict": overall.value,
        }
        return validate_state_write(updates, "risk_manager")

    def node(state):
        cfg_max_leverage, prompt = _prepare(state)
        text, obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_risk_assessment,
            "Risk Manager",
            schema=RiskAssessment,
        )
        return _apply(cfg_max_leverage, text, obj)

    async def anode(state):
        cfg_max_leverage, prompt = _prepare(state)
        text, obj = await ainvoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_risk_assessment,
            "Risk Manager",
            schema=RiskAssessment,
        )
        return _apply(cfg_max_leverage, text, obj)

    return dual_node(node, anode)
