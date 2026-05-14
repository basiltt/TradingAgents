"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.prompt_guard import wrap_external_data
from tradingagents.agents.utils.state_filter import (
    filter_state_for_read,
    validate_state_write,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        filtered = filter_state_for_read(state, "portfolio_manager")
        company = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company, crypto_interval)

        risk_debate_state = filtered.get("risk_debate_state", {})
        history = risk_debate_state.get("history", "")
        research_plan = wrap_external_data(filtered.get("investment_plan", ""), "research_manager")
        trader_plan = wrap_external_data(filtered.get("trader_investment_plan", ""), "trader")
        risk_manager_result = wrap_external_data(filtered.get("risk_manager_result", ""), "risk_manager")

        past_context = filtered.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )
        risk_manager_line = (
            f"- Risk Manager assessment:\n{risk_manager_result}\n"
            if risk_manager_result
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}{risk_manager_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts. Include a confidence score (1-10) reflecting your overall conviction.{get_language_instruction()}"""

        final_trade_decision, decision_obj = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
            schema=PortfolioDecision,
        )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state.get("history", ""),
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state.get("current_aggressive_response", ""),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "count": risk_debate_state.get("count", 0),
        }

        updates = {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
            "_pm_signal_data": decision_obj,
        }
        return validate_state_write(updates, "portfolio_manager")

    return portfolio_manager_node
