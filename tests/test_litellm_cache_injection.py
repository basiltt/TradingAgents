"""Tests for cache_control injection in NormalizedChatLiteLLM."""
from unittest.mock import patch
from langchain_core.messages import SystemMessage, HumanMessage


def _make(model_name, cache_enabled):
    from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM
    llm = NormalizedChatLiteLLM(model=model_name, api_key="dummy")
    llm._cache_enabled = cache_enabled
    return llm


class TestCacheInjection:
    def _capture_input(self, llm, messages):
        captured = {}
        def fake_super_invoke(input, config=None, **kwargs):
            captured["input"] = input
            from unittest.mock import MagicMock
            return MagicMock(content="ok", usage_metadata=None)
        with patch("tradingagents.llm_clients.litellm_client.llm_rate_limited_invoke",
                   side_effect=lambda fn, inp, cfg, **kw: fake_super_invoke(inp, cfg, **kw)):
            llm.invoke(messages)
        return captured["input"]

    def test_marks_system_for_anthropic_when_enabled(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        out = self._capture_input(llm, [SystemMessage(content="STABLE"), HumanMessage(content="v")])
        assert isinstance(out[0].content, list)
        assert out[0].content[0]["cache_control"] == {"type": "ephemeral"}

    def test_no_mark_when_disabled(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=False)
        out = self._capture_input(llm, [SystemMessage(content="STABLE"), HumanMessage(content="v")])
        assert out[0].content == "STABLE"

    def test_no_mark_for_non_anthropic(self):
        llm = _make("gpt-5.4", cache_enabled=True)
        out = self._capture_input(llm, [SystemMessage(content="STABLE"), HumanMessage(content="v")])
        assert out[0].content == "STABLE"

    def test_handles_chatpromptvalue_shape(self):
        from langchain_core.prompt_values import ChatPromptValue
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        pv = ChatPromptValue(messages=[SystemMessage(content="STABLE"), HumanMessage(content="v")])
        out = self._capture_input(llm, pv)
        assert isinstance(out[0].content, list)

    def test_handles_bare_string_noop(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        out = self._capture_input(llm, "just a string, no system message")
        assert out == "just a string, no system message"

    def test_handles_list_of_tuples_noop(self):
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        msgs = [("system", "STABLE"), ("human", "v")]
        out = self._capture_input(llm, msgs)
        assert out == msgs


class TestCacheFlagWiring:
    def test_get_llm_sets_cache_enabled_from_kwarg(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        llm = LiteLLMClient("claude-sonnet-4-6", provider="anthropic",
                            prompt_cache_enabled=True).get_llm()
        assert llm._cache_enabled is True

    def test_get_llm_defaults_cache_disabled(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        llm = LiteLLMClient("claude-sonnet-4-6", provider="anthropic").get_llm()
        assert getattr(llm, "_cache_enabled", False) is False

    def test_factory_forwards_flag(self):
        from tradingagents.llm_clients.factory import create_llm_client
        client = create_llm_client("anthropic", "claude-sonnet-4-6",
                                   prompt_cache_enabled=True)
        llm = client.get_llm()
        assert llm._cache_enabled is True
