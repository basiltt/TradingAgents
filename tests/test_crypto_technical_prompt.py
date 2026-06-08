"""Content-preservation for the crypto technical analyst prompt refactor."""
import re
from unittest.mock import MagicMock, patch
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import SystemMessage


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _msg_text(m) -> str:
    content = getattr(m, "content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _crypto_tools():
    names = ("get_crypto_klines", "get_crypto_indicators",
             "get_volatility_regime", "get_btc_eth_correlation")
    tools = []
    for n in names:
        t = MagicMock()
        t.name = n
        tools.append(t)
    return tools


def _state(date="2026-06-06", symbol="BTCUSDT",
           price="Last Traded Price: $123456.00"):
    return {
        "trade_date": date,
        "company_of_interest": symbol,
        "crypto_interval": "60",
        "current_price_context": price,
        "messages": [],
    }


def _render_crypto_technical(date="2026-06-06", symbol="BTCUSDT",
                             instrument="Asset: BTCUSDT futures",
                             price="Last Traded Price: $123456.00",
                             lang=" RESPOND_IN_TESTLANG."):
    captured = {}
    def fake_model(prompt_value):
        captured["messages"] = (prompt_value.to_messages()
                                if hasattr(prompt_value, "to_messages") else prompt_value)
        return MagicMock(tool_calls=[], content="ok")
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = RunnableLambda(fake_model)
    from tradingagents.agents.crypto_analysts import create_crypto_technical_analyst
    with patch("tradingagents.agents.crypto_analysts.get_language_instruction",
               return_value=lang), \
         patch("tradingagents.agents.crypto_analysts.build_instrument_context",
               return_value=instrument):
        node = create_crypto_technical_analyst(mock_llm, _crypto_tools())
        node.invoke(_state(date=date, symbol=symbol, price=price))
    return captured["messages"]


class TestCryptoTechnicalContentPreserved:
    def test_all_content_reaches_model(self):
        msgs = _render_crypto_technical()
        joined = " ".join(_norm(_msg_text(m)) for m in msgs)
        for fragment in ["crypto futures technical analyst", "2026-06-06",
                         "BTCUSDT futures",
                         "CURRENT PRICE DATA (use this as the reference price for your analysis)",
                         "123456.00", "RESPOND_IN_TESTLANG"]:
            assert _norm(fragment) in joined, f"missing: {fragment}"

    def test_system_message_has_no_volatile_tokens(self):
        msgs = _render_crypto_technical()
        sys_msgs = [m for m in msgs if isinstance(m, SystemMessage)]
        assert sys_msgs, "expected a leading system message"
        assert "2026-06-06" not in _msg_text(sys_msgs[0])
        assert "BTCUSDT futures" not in _msg_text(sys_msgs[0])
        assert "123456.00" not in _msg_text(sys_msgs[0])

    def test_system_prefix_byte_stable_across_runs(self):
        def _sys_for(date, symbol, instrument, price):
            msgs = _render_crypto_technical(date=date, symbol=symbol,
                                            instrument=instrument, price=price, lang="")
            return _msg_text([m for m in msgs if isinstance(m, SystemMessage)][0])
        a = _sys_for("2026-06-06", "BTCUSDT", "Asset: BTC", "Price A")
        b = _sys_for("2025-01-02", "ETHUSDT", "Asset: ETH", "Price B")
        assert a == b, "system prefix differs across runs → caching will never hit"

    def test_constants_concatenate_to_original_prefix(self):
        from tradingagents.agents.crypto_analysts import (
            _ANALYST_SYSTEM_PREFIX, _ANALYST_STABLE_PREFIX, _ANALYST_VOLATILE_TAIL,
        )
        # Behavior-preservation guarantee: the new split constants must
        # concatenate byte-for-byte back into the original shared prefix.
        assert _ANALYST_STABLE_PREFIX + _ANALYST_VOLATILE_TAIL == _ANALYST_SYSTEM_PREFIX

    def test_shared_prefix_constant_unchanged(self):
        # The 4 OTHER crypto analysts still use _ANALYST_SYSTEM_PREFIX; it must
        # remain intact (FINAL ANALYSIS boilerplate + volatile tail in one string).
        from tradingagents.agents.crypto_analysts import _ANALYST_SYSTEM_PREFIX
        assert "FINAL ANALYSIS" in _ANALYST_SYSTEM_PREFIX
        assert "{current_date}" in _ANALYST_SYSTEM_PREFIX
        assert "{current_price_context}" in _ANALYST_SYSTEM_PREFIX
