"""Tests for tradingagents.llm_clients — Phase 1 unit tests."""

import warnings
from unittest.mock import patch, MagicMock

import pytest


class TestNormalizeContent:
    def test_string_content_unchanged(self):
        from tradingagents.llm_clients.base_client import normalize_content
        resp = MagicMock()
        resp.content = "Hello world"
        result = normalize_content(resp)
        assert result.content == "Hello world"

    def test_list_content_extracts_text(self):
        from tradingagents.llm_clients.base_client import normalize_content
        resp = MagicMock()
        resp.content = [
            {"type": "reasoning", "text": "thinking..."},
            {"type": "text", "text": "Final answer"},
        ]
        result = normalize_content(resp)
        assert result.content == "Final answer"

    def test_list_with_strings(self):
        from tradingagents.llm_clients.base_client import normalize_content
        resp = MagicMock()
        resp.content = ["plain string", {"type": "text", "text": "block text"}]
        result = normalize_content(resp)
        assert "plain string" in result.content
        assert "block text" in result.content

    def test_empty_list(self):
        from tradingagents.llm_clients.base_client import normalize_content
        resp = MagicMock()
        resp.content = []
        result = normalize_content(resp)
        assert result.content == ""


class TestConfigureLlmConcurrency:
    def test_zero_sets_none(self):
        from tradingagents.llm_clients.base_client import configure_llm_concurrency
        import tradingagents.llm_clients.base_client as mod
        configure_llm_concurrency(0)
        assert mod._llm_semaphore is None

    def test_positive_sets_semaphore(self):
        import threading
        from tradingagents.llm_clients.base_client import configure_llm_concurrency
        import tradingagents.llm_clients.base_client as mod
        configure_llm_concurrency(5)
        assert isinstance(mod._llm_semaphore, threading.Semaphore)
        configure_llm_concurrency(0)  # cleanup


class TestLlmRateLimitedInvoke:
    def test_no_semaphore_calls_directly(self):
        from tradingagents.llm_clients.base_client import llm_rate_limited_invoke
        import tradingagents.llm_clients.base_client as mod
        old = mod._llm_semaphore
        mod._llm_semaphore = None
        try:
            fn = MagicMock(return_value="result")
            result = llm_rate_limited_invoke(fn, "input")
            assert result == "result"
        finally:
            mod._llm_semaphore = old

    def test_with_semaphore(self):
        import threading
        from tradingagents.llm_clients.base_client import llm_rate_limited_invoke
        import tradingagents.llm_clients.base_client as mod
        old = mod._llm_semaphore
        mod._llm_semaphore = threading.Semaphore(1)
        try:
            fn = MagicMock(return_value="result")
            result = llm_rate_limited_invoke(fn, "input")
            assert result == "result"
        finally:
            mod._llm_semaphore = old


class TestBaseLLMClient:
    def test_get_provider_name_from_class(self):
        from tradingagents.llm_clients.base_client import BaseLLMClient

        class TestClient(BaseLLMClient):
            def get_llm(self): ...
            def validate_model(self): return True

        client = TestClient("model-1")
        assert client.get_provider_name() == "test"

    def test_warn_if_unknown_model(self):
        from tradingagents.llm_clients.base_client import BaseLLMClient

        class FakeClient(BaseLLMClient):
            def get_llm(self): ...
            def validate_model(self): return False

        client = FakeClient("bad-model")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client.warn_if_unknown_model()
            assert len(w) == 1
            assert "not in the known model list" in str(w[0].message)

    def test_no_warning_for_known_model(self):
        from tradingagents.llm_clients.base_client import BaseLLMClient

        class FakeClient(BaseLLMClient):
            def get_llm(self): ...
            def validate_model(self): return True

        client = FakeClient("good-model")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client.warn_if_unknown_model()
            assert len(w) == 0


class TestFactory:
    def test_openai_provider(self):
        from tradingagents.llm_clients.factory import create_llm_client
        mock_cls = MagicMock()
        with patch("tradingagents.llm_clients.openai_client.OpenAIClient", mock_cls):
            with patch.dict("sys.modules", {}):
                result = create_llm_client("openai", "gpt-4")
        assert result is not None

    def test_unsupported_provider_raises(self):
        from tradingagents.llm_clients.factory import create_llm_client
        with pytest.raises(ValueError, match="Unsupported"):
            create_llm_client("nonexistent", "model", use_litellm=False)

    def test_unsupported_provider_raises_litellm(self):
        from tradingagents.llm_clients.factory import create_llm_client
        with pytest.raises(ValueError, match="Unsupported"):
            create_llm_client("nonexistent", "model")

    def test_anthropic_provider(self):
        from tradingagents.llm_clients.factory import create_llm_client
        mock_cls = MagicMock()
        with patch("tradingagents.llm_clients.anthropic_client.AnthropicClient", mock_cls):
            result = create_llm_client("anthropic", "claude-3")
        assert result is not None

    def test_google_provider(self):
        from tradingagents.llm_clients.factory import create_llm_client
        mock_cls = MagicMock()
        with patch("tradingagents.llm_clients.google_client.GoogleClient", mock_cls):
            result = create_llm_client("google", "gemini-pro")
        assert result is not None

    def test_azure_provider(self):
        from tradingagents.llm_clients.factory import create_llm_client
        mock_cls = MagicMock()
        with patch("tradingagents.llm_clients.azure_client.AzureOpenAIClient", mock_cls):
            result = create_llm_client("azure", "gpt-4")
        assert result is not None


class TestAnthropicClient:
    @patch("tradingagents.llm_clients.anthropic_client.NormalizedChatAnthropic")
    def test_get_llm_basic(self, mock_chat):
        from tradingagents.llm_clients.anthropic_client import AnthropicClient
        client = AnthropicClient("claude-3-opus")
        with patch.object(client, "warn_if_unknown_model"):
            client.get_llm()
        mock_chat.assert_called_once()
        kwargs = mock_chat.call_args[1]
        assert kwargs["model"] == "claude-3-opus"

    @patch("tradingagents.llm_clients.anthropic_client.NormalizedChatAnthropic")
    def test_get_llm_with_base_url_injects_dummy_key(self, mock_chat):
        from tradingagents.llm_clients.anthropic_client import AnthropicClient
        client = AnthropicClient("claude-3", base_url="http://local:8080")
        with patch.object(client, "warn_if_unknown_model"):
            client.get_llm()
        kwargs = mock_chat.call_args[1]
        assert kwargs["api_key"] == "dummy"
        assert kwargs["base_url"] == "http://local:8080"

    @patch("tradingagents.llm_clients.anthropic_client.NormalizedChatAnthropic")
    def test_passthrough_kwargs(self, mock_chat):
        from tradingagents.llm_clients.anthropic_client import AnthropicClient
        client = AnthropicClient("claude-3", max_tokens=1000, timeout=30)
        with patch.object(client, "warn_if_unknown_model"):
            client.get_llm()
        kwargs = mock_chat.call_args[1]
        assert kwargs["max_tokens"] == 1000
        assert kwargs["timeout"] == 30

    def test_validate_model(self):
        from tradingagents.llm_clients.anthropic_client import AnthropicClient
        client = AnthropicClient("claude-3-opus-20240229")
        assert isinstance(client.validate_model(), bool)


class TestAzureClient:
    @patch("tradingagents.llm_clients.azure_client.NormalizedAzureChatOpenAI")
    def test_get_llm_basic(self, mock_chat):
        from tradingagents.llm_clients.azure_client import AzureOpenAIClient
        client = AzureOpenAIClient("gpt-4")
        with patch.object(client, "warn_if_unknown_model"):
            client.get_llm()
        mock_chat.assert_called_once()
        kwargs = mock_chat.call_args[1]
        assert kwargs["model"] == "gpt-4"

    @patch("tradingagents.llm_clients.azure_client.NormalizedAzureChatOpenAI")
    def test_uses_deployment_env_var(self, mock_chat):
        import os
        from tradingagents.llm_clients.azure_client import AzureOpenAIClient
        with patch.dict(os.environ, {"AZURE_OPENAI_DEPLOYMENT_NAME": "my-deploy"}):
            client = AzureOpenAIClient("gpt-4")
            with patch.object(client, "warn_if_unknown_model"):
                client.get_llm()
        kwargs = mock_chat.call_args[1]
        assert kwargs["azure_deployment"] == "my-deploy"

    def test_validate_model_always_true(self):
        from tradingagents.llm_clients.azure_client import AzureOpenAIClient
        client = AzureOpenAIClient("anything")
        assert client.validate_model() is True
