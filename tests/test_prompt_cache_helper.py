"""Tests for the prompt-cache shaping helper."""
from langchain_core.messages import SystemMessage, HumanMessage


class TestApplyCacheControl:
    def test_rewrites_first_system_message_to_block(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [SystemMessage(content="STABLE"), HumanMessage(content="volatile")]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0].content, list)
        block = out[0].content[0]
        assert block["type"] == "text"
        assert block["text"] == "STABLE"
        assert block["cache_control"] == {"type": "ephemeral"}
        assert out[1].content == "volatile"

    def test_handles_dict_role_system(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [{"role": "system", "content": "STABLE"}, {"role": "user", "content": "v"}]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0]["content"], list)
        assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_noop_when_no_system_message(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [HumanMessage(content="only human")]
        out = apply_cache_control_to_messages(msgs)
        assert out[0].content == "only human"

    def test_only_first_system_message_marked(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [SystemMessage(content="A"), SystemMessage(content="B")]
        out = apply_cache_control_to_messages(msgs)
        assert isinstance(out[0].content, list)
        assert out[1].content == "B"

    def test_noop_when_content_already_blocks(self):
        from tradingagents.agents.utils.prompt_cache import apply_cache_control_to_messages
        msgs = [SystemMessage(content=[{"type": "text", "text": "X"}])]
        out = apply_cache_control_to_messages(msgs)
        assert out[0].content == [{"type": "text", "text": "X"}]
