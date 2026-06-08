"""Content-preservation for the market_analyst prompt refactor."""
import re
from unittest.mock import MagicMock, patch
from langchain_core.runnables import RunnableLambda


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _msg_text(m) -> str:
    content = getattr(m, "content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _render_market_analyst():
    captured = {}
    def fake_model(prompt_value):
        captured["messages"] = (prompt_value.to_messages()
                                if hasattr(prompt_value, "to_messages") else prompt_value)
        return MagicMock(tool_calls=[], content="ok")
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = RunnableLambda(fake_model)
    from tradingagents.agents.analysts.market_analyst import create_market_analyst
    with patch("tradingagents.agents.analysts.market_analyst.get_language_instruction",
               return_value=" RESPOND_IN_TESTLANG."), \
         patch("tradingagents.agents.analysts.market_analyst.build_instrument_context",
               return_value="Asset: BTCUSDT futures"):
        node = create_market_analyst(mock_llm)
        node.invoke({"trade_date": "2026-06-06", "company_of_interest": "BTCUSDT", "messages": []})
    return captured["messages"]


class TestMarketAnalystContentPreserved:
    def test_all_content_reaches_model(self):
        msgs = _render_market_analyst()
        joined = " ".join(_norm(_msg_text(m)) for m in msgs)
        for fragment in ["trading assistant", "2026-06-06", "BTCUSDT futures",
                         "Markdown table", "RESPOND_IN_TESTLANG"]:
            assert _norm(fragment) in joined, f"missing: {fragment}"

    def test_system_message_has_no_volatile_tokens(self):
        from langchain_core.messages import SystemMessage
        msgs = _render_market_analyst()
        sys_msgs = [m for m in msgs if isinstance(m, SystemMessage)]
        assert sys_msgs, "expected a leading system message"
        assert "2026-06-06" not in _msg_text(sys_msgs[0])
        assert "BTCUSDT futures" not in _msg_text(sys_msgs[0])

    def test_system_prefix_byte_stable_across_date_and_symbol(self):
        from langchain_core.messages import SystemMessage
        def _sys_for(date, symbol, instrument):
            captured = {}
            def fake_model(pv):
                captured["m"] = pv.to_messages() if hasattr(pv, "to_messages") else pv
                return MagicMock(tool_calls=[], content="ok")
            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = RunnableLambda(fake_model)
            from tradingagents.agents.analysts.market_analyst import create_market_analyst
            with patch("tradingagents.agents.analysts.market_analyst.get_language_instruction", return_value=""), \
                 patch("tradingagents.agents.analysts.market_analyst.build_instrument_context", return_value=instrument):
                create_market_analyst(mock_llm).invoke({"trade_date": date, "company_of_interest": symbol, "messages": []})
            return _msg_text([m for m in captured["m"] if isinstance(m, SystemMessage)][0])
        a = _sys_for("2026-06-06", "BTCUSDT", "Asset: BTC")
        b = _sys_for("2025-01-02", "ETHUSDT", "Asset: ETH")
        assert a == b, "system prefix differs across runs → caching will never hit"
