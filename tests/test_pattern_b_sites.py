from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages


class TestPatternBDictSystem:
    def test_dict_system_marked(self):
        msgs = [{"role": "system", "content": "STABLE TRADER SYSTEM"},
                {"role": "user", "content": "volatile per-trade data"}]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0]["content"], list)
        assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert out[1]["content"] == "volatile per-trade data"


class TestStructuredOutputRoutesThroughOverride:
    def test_with_structured_output_invoke_hits_override(self):
        from unittest.mock import patch, MagicMock
        from pydantic import BaseModel
        from langchain_core.messages import SystemMessage, HumanMessage
        from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM
        class Out(BaseModel):
            action: str
        llm = NormalizedChatLiteLLM(model="anthropic/claude-sonnet-4-6", api_key="dummy")
        fired = {"hit": False}
        def spy(self, input, config=None, **kwargs):
            fired["hit"] = True
            return MagicMock(content='{"action":"Hold"}', tool_calls=[], usage_metadata=None)
        with patch.object(NormalizedChatLiteLLM, "invoke", spy):
            structured = llm.with_structured_output(Out, method="function_calling")
            try:
                structured.invoke([SystemMessage(content="S"), HumanMessage(content="u")])
            except Exception:
                pass
        assert fired["hit"], "structured-output path bypassed NormalizedChatLiteLLM.invoke"
