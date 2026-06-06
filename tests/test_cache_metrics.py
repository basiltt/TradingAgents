"""Tests for cache-metric extraction/logging."""
import logging
from unittest.mock import MagicMock, patch


class TestExtractCacheMetrics:
    def test_reads_usage_metadata_cache_read(self):
        from tradingagents.llm_clients.base_client import extract_cache_metrics
        resp = MagicMock()
        resp.usage_metadata = {"input_tokens": 10,
                               "input_token_details": {"cache_read": 1840, "cache_creation": 0}}
        m = extract_cache_metrics(resp)
        assert m["cache_read"] == 1840
        assert m["cache_creation"] == 0

    def test_absent_details_is_none_not_zero(self):
        from tradingagents.llm_clients.base_client import extract_cache_metrics
        resp = MagicMock()
        resp.usage_metadata = {"input_tokens": 10}  # no input_token_details
        m = extract_cache_metrics(resp)
        assert m["cache_read"] is None  # not reported, NOT a real zero

    def test_no_usage_metadata_returns_none_metrics(self):
        from tradingagents.llm_clients.base_client import extract_cache_metrics
        resp = MagicMock()
        resp.usage_metadata = None
        m = extract_cache_metrics(resp)
        assert m["cache_read"] is None


class TestInvokeLogsCacheMetrics:
    def test_invoke_logs_when_cache_read_present(self, caplog):
        from langchain_community.chat_models import ChatLiteLLM
        from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM

        inst = NormalizedChatLiteLLM(model="anthropic/claude-x", api_key="dummy")
        fake = MagicMock()
        fake.content = "hi"
        fake.usage_metadata = {"input_tokens": 10,
                               "input_token_details": {"cache_read": 1840, "cache_creation": 0}}
        with patch.object(ChatLiteLLM, "invoke", return_value=fake), \
                caplog.at_level(logging.INFO, logger="tradingagents.llm_clients.litellm_client"):
            inst.invoke([{"role": "user", "content": "x"}])

        records = [r for r in caplog.records if "LLM cache" in r.getMessage()]
        assert records, "expected an LLM cache log record"
        assert "cache_read=1840" in records[0].getMessage()

    def test_invoke_quiet_when_no_cache_fields(self, caplog):
        from langchain_community.chat_models import ChatLiteLLM
        from tradingagents.llm_clients.litellm_client import NormalizedChatLiteLLM

        inst = NormalizedChatLiteLLM(model="anthropic/claude-x", api_key="dummy")
        fake = MagicMock()
        fake.content = "hi"
        fake.usage_metadata = {"input_tokens": 10}  # no input_token_details
        with patch.object(ChatLiteLLM, "invoke", return_value=fake), \
                caplog.at_level(logging.INFO, logger="tradingagents.llm_clients.litellm_client"):
            inst.invoke([{"role": "user", "content": "x"}])

        assert not [r for r in caplog.records if "LLM cache" in r.getMessage()]
