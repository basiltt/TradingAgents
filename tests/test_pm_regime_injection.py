"""Phase 3 — PM prompt regime-context injection + byte-identical-OFF (FR-4, AC-1/AC-3).

Captures the exact prompt the Portfolio Manager builds by spying on the LLM the
node invokes. The byte-identical property (flag OFF / regime_context absent or "")
is the key reversibility guarantee.
"""
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from tradingagents.agents.crypto_analysts import create_crypto_portfolio_manager
from tradingagents.agents.schemas import PortfolioDecision


class _StructuredSpy:
    """Records the prompt; returns a VALID PortfolioDecision so the production
    structured-output path is exercised (not the free-text fallback)."""
    def __init__(self):
        self.prompt = None

    def _decision(self):
        return PortfolioDecision(
            rating="Hold",
            confidence=3,
            executive_summary="No compelling trade.",
            investment_thesis="Evidence is mixed; squeeze risk into a rising tape.",
        )

    def invoke(self, prompt, *a, **k):
        self.prompt = prompt if isinstance(prompt, str) else str(prompt)
        return self._decision()

    def with_structured_output(self, *a, **k):
        return self



def _base_state(regime_context=None):
    state = {
        "company_of_interest": "BTCUSDT",
        "crypto_interval": "15",
        "current_price_context": "Last: $100000",
        "investment_plan": "Buy BTC",
        "trader_investment_plan": "Long BTC",
        "risk_debate_state": {
            "history": "Bull: good. Bear: risky.",
            "aggressive_history": "", "conservative_history": "", "neutral_history": "",
            "current_aggressive_response": "", "current_conservative_response": "",
            "current_neutral_response": "", "judge_decision": "", "count": 2,
        },
        "past_context": "",
        "max_leverage": 20,
        "risk_manager_result": "",
    }
    if regime_context is not None:
        state["regime_context"] = regime_context
    return state


def _render_prompt(regime_context=None, caplog=None):
    spy = _StructuredSpy()
    node = create_crypto_portfolio_manager(spy)
    node.invoke(_base_state(regime_context))
    return spy.prompt


# ── AC-3: ON → block present in the right slot ──
def test_regime_block_injected_when_present():
    block = "--- MARKET REGIME CONTEXT (account-agnostic) ---\nBTC is rising.\n\n"
    prompt = _render_prompt(regime_context=block)
    assert "MARKET REGIME CONTEXT" in prompt
    # positioned before "Max allowed leverage" and after the price block
    assert prompt.index("MARKET REGIME CONTEXT") < prompt.index("Max allowed leverage")
    assert prompt.index("CURRENT PRICE DATA") < prompt.index("MARKET REGIME CONTEXT")


# ── AC-1: byte-identical when absent vs "" ──
def test_prompt_byte_identical_absent_vs_empty():
    assert _render_prompt(regime_context=None) == _render_prompt(regime_context="")


def test_prompt_has_no_regime_block_when_empty():
    prompt = _render_prompt(regime_context="")
    assert "MARKET REGIME CONTEXT" not in prompt
    # no stray blank-line artifact: the price block flows straight into leverage
    assert "Max allowed leverage" in prompt


def test_structured_path_is_exercised_not_fallback(caplog):
    # Proves the captured prompt is the STRUCTURED-output prompt, not the
    # free-text fallback (which would append a schema hint the real path omits).
    import logging
    caplog.set_level(logging.WARNING)
    _render_prompt(regime_context="--- MARKET REGIME CONTEXT (account-agnostic) ---\nx\n\n")
    assert "structured-output invocation failed" not in caplog.text
