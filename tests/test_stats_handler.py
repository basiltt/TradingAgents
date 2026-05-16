"""Tests for cli.stats_handler — Phase 1 unit tests."""



class TestStatsCallbackHandler:
    def _make(self):
        from cli.stats_handler import StatsCallbackHandler
        return StatsCallbackHandler()

    def test_initial_stats(self):
        h = self._make()
        assert h.get_stats() == {
            "llm_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0,
        }

    def test_on_llm_start_increments(self):
        h = self._make()
        h.on_llm_start({}, ["prompt"])
        h.on_llm_start({}, ["prompt2"])
        assert h.get_stats()["llm_calls"] == 2

    def test_on_chat_model_start_increments(self):
        h = self._make()
        h.on_chat_model_start({}, [[]])
        assert h.get_stats()["llm_calls"] == 1

    def test_on_tool_start_increments(self):
        h = self._make()
        h.on_tool_start({}, "input")
        h.on_tool_start({}, "input2")
        assert h.get_stats()["tool_calls"] == 2

    def test_on_llm_end_extracts_tokens(self):
        from langchain_core.outputs import LLMResult, ChatGeneration
        from langchain_core.messages import AIMessage

        h = self._make()
        msg = AIMessage(content="hi")
        msg.usage_metadata = {"input_tokens": 10, "output_tokens": 20}
        gen = ChatGeneration(message=msg)
        result = LLMResult(generations=[[gen]])
        h.on_llm_end(result)
        stats = h.get_stats()
        assert stats["tokens_in"] == 10
        assert stats["tokens_out"] == 20

    def test_on_llm_end_empty_generations(self):
        from langchain_core.outputs import LLMResult
        h = self._make()
        h.on_llm_end(LLMResult(generations=[]))
        assert h.get_stats()["tokens_in"] == 0

    def test_on_llm_end_no_usage_metadata(self):
        from langchain_core.outputs import LLMResult, Generation
        h = self._make()
        gen = Generation(text="hi")
        result = LLMResult(generations=[[gen]])
        h.on_llm_end(result)
        assert h.get_stats()["tokens_in"] == 0

    def test_on_llm_end_message_not_ai(self):
        from langchain_core.outputs import LLMResult, ChatGeneration
        from langchain_core.messages import HumanMessage
        h = self._make()
        gen = ChatGeneration(message=HumanMessage(content="hi"))
        result = LLMResult(generations=[[gen]])
        h.on_llm_end(result)
        assert h.get_stats()["tokens_in"] == 0
