"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.dual_node import dual_node
from tradingagents.agents.utils.prompt_guard import wrap_external_data
from tradingagents.agents.utils.state_filter import (
    filter_state_for_read,
    validate_state_write,
)
from tradingagents.agents.utils.structured import (
    ainvoke_structured_or_freetext,
    bind_structured,
    invoke_structured_or_freetext,
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def _prepare(state):
        filtered = filter_state_for_read(state, "research_manager")
        company = filtered.get("company_of_interest", "")
        crypto_interval = filtered.get("crypto_interval")
        instrument_context = build_instrument_context(company, crypto_interval)

        investment_debate_state = filtered.get("investment_debate_state", {})
        confluence = wrap_external_data(
            filtered.get("confluence_summary", ""), "confluence_checker"
        )
        history = wrap_external_data(
            investment_debate_state.get("history", ""), "debate_history"
        )

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

Commit to a clear stance based on the weight of evidence. Hold is a fully valid recommendation when the evidence is balanced or insufficient — not a last resort.

---

**Confluence Summary** (cross-analyst synthesis — use as a safety net to catch data points the debaters may have missed):
{confluence}

---

**Debate History:**
{history}"""

        return investment_debate_state, prompt

    def _apply(investment_debate_state, investment_plan) -> dict:
        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state.get("count", 0),
        }

        return validate_state_write({
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }, "research_manager")

    def research_manager_node(state) -> dict:
        investment_debate_state, prompt = _prepare(state)
        investment_plan, _ = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
            schema=ResearchPlan,
        )
        return _apply(investment_debate_state, investment_plan)

    async def aresearch_manager_node(state) -> dict:
        investment_debate_state, prompt = _prepare(state)
        investment_plan, _ = await ainvoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
            schema=ResearchPlan,
        )
        return _apply(investment_debate_state, investment_plan)

    return dual_node(research_manager_node, aresearch_manager_node)
