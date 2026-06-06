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
        assert out[1].content == "v"

    def test_enabled_anthropic_no_system_message_noop(self):
        from langchain_core.messages import HumanMessage
        llm = _make("anthropic/claude-sonnet-4-6", cache_enabled=True)
        out = self._capture_input(llm, [HumanMessage(content="only human")])
        assert out[0].content == "only human"  # no system msg → clean no-op, no crash

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


class TestRealBindingPayload:
    def test_cache_control_reaches_anthropic_system_param(self):
        """Drive the REAL langchain-community -> litellm Anthropic transform (no
        mock) and assert cache_control reaches Anthropic's top-level `system`
        param exactly once. This is the on-the-wire guard: it fails loudly if a
        library upgrade silently stops emitting the breakpoint.

        NOTE: it exercises litellm's *internal* `AnthropicConfig.transform_request`
        (a private path that can move between litellm minors). To distinguish
        "caching genuinely broke" from "litellm relocated its internals", a moved
        import/signature is reported as a SKIP (needs-update), not a red failure
        that would mask a real regression. If this skips after a litellm bump,
        update the import/call to match — do not assume caching is fine.
        """
        import json
        import pytest

        # Private litellm path — importorskip so a relocation skips, not errors.
        transformation = pytest.importorskip(
            "litellm.llms.anthropic.chat.transformation",
            reason="litellm AnthropicConfig moved; update the real-binding test import",
        )
        AnthropicConfig = getattr(transformation, "AnthropicConfig", None)
        if AnthropicConfig is None:
            pytest.skip("litellm AnthropicConfig symbol moved; update the real-binding test")

        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        from langchain_community.chat_models.litellm import _convert_message_to_dict
        from langchain_core.messages import SystemMessage, HumanMessage

        msgs = apply_cache_control_to_messages(
            [SystemMessage(content="STABLE " * 300), HumanMessage(content="date 2026-06-06")])
        dicts = [_convert_message_to_dict(m) for m in msgs]
        try:
            out = AnthropicConfig().transform_request(
                model="claude-sonnet-4-6", messages=dicts,
                optional_params={}, litellm_params={}, headers={})
        except TypeError as e:
            pytest.skip(
                f"litellm AnthropicConfig.transform_request signature changed "
                f"({e}); update the real-binding test to match")

        # When the transform DOES run, the assertion is strict — a real breakpoint
        # regression must fail here, not pass.
        payload = json.dumps(out)
        assert "cache_control" in payload, (
            "cache_control did NOT reach the Anthropic payload — the breakpoint "
            "is being dropped (real regression, not a library move)")
        assert payload.count("cache_control") == 1
        assert out.get("system") and out["system"][0]["cache_control"] == {"type": "ephemeral"}
