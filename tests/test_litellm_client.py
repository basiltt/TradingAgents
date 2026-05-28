"""Tests for the LiteLLM unified client."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestLiteLLMClientModelName:
    def test_openai_no_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("gpt-4", provider="openai")
        assert client._get_litellm_model_name() == "gpt-4"

    def test_anthropic_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("claude-sonnet-4-6", provider="anthropic")
        assert client._get_litellm_model_name() == "anthropic/claude-sonnet-4-6"

    def test_google_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("gemini-2.5-flash", provider="google")
        assert client._get_litellm_model_name() == "gemini/gemini-2.5-flash"

    def test_deepseek_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("deepseek-chat", provider="deepseek")
        assert client._get_litellm_model_name() == "deepseek/deepseek-chat"

    def test_ollama_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("llama3:latest", provider="ollama")
        assert client._get_litellm_model_name() == "openai/llama3:latest"

    def test_model_with_slash_unchanged(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("anthropic/claude-3-opus", provider="openai")
        assert client._get_litellm_model_name() == "anthropic/claude-3-opus"

    def test_nvidia_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("deepseek-v4-flash", provider="nvidia")
        assert client._get_litellm_model_name() == "nvidia_nim/deepseek-v4-flash"

    def test_xai_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("grok-4", provider="xai")
        assert client._get_litellm_model_name() == "xai/grok-4"

    def test_azure_prefix(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("gpt-4", provider="azure")
        assert client._get_litellm_model_name() == "azure/gpt-4"


class TestLiteLLMClientGetLlm:
    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_basic_openai(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            client = LiteLLMClient("gpt-4", provider="openai")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "gpt-4"
        assert kwargs["api_key"] == "sk-test"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_custom_base_url(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            client = LiteLLMClient("gpt-4", base_url="http://my-proxy:8080", provider="openai")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_base"] == "http://my-proxy:8080"
        assert kwargs["api_key"] == "dummy"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_anthropic_with_env_key(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            client = LiteLLMClient("claude-sonnet-4-6", provider="anthropic")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "anthropic/claude-sonnet-4-6"
        assert kwargs["api_key"] == "sk-ant-test"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_explicit_api_key_kwarg(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        client = LiteLLMClient("gpt-4", provider="openai", api_key="explicit-key")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_key"] == "explicit-key"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_ollama_base_url(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        client = LiteLLMClient("llama3", provider="ollama")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_base"] == "http://localhost:11434/v1"
        assert kwargs["api_key"] == "ollama"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_passthrough_kwargs(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}):
            client = LiteLLMClient("gpt-4", provider="openai", temperature=0.5, max_tokens=100)
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 100

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_reasoning_effort(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}):
            client = LiteLLMClient("gpt-5.4", provider="openai", reasoning_effort="high")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model_kwargs"]["reasoning_effort"] == "high"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_anthropic_effort(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            client = LiteLLMClient("claude-sonnet-4-6", provider="anthropic", effort="high")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model_kwargs"]["thinking"]["type"] == "enabled"
        assert kwargs["model_kwargs"]["thinking"]["budget_tokens"] == 32000

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_google_thinking_level(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            client = LiteLLMClient("gemini-2.5-flash", provider="google", thinking_level="high")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model_kwargs"]["thinking_level"] == "high"

    def test_validate_model_always_true(self):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        client = LiteLLMClient("any-model-name", provider="openai")
        assert client.validate_model() is True

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_azure_env_vars(self, mock_cls):
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {
            "AZURE_OPENAI_API_KEY": "az-key",
            "AZURE_OPENAI_ENDPOINT": "https://myresource.openai.azure.com/",
        }, clear=False):
            os.environ.pop("AZURE_API_KEY", None)
            os.environ.pop("AZURE_API_BASE", None)
            client = LiteLLMClient("gpt-4", provider="azure")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "azure/gpt-4"
        assert kwargs["api_key"] == "az-key"
        assert kwargs["api_base"] == "https://myresource.openai.azure.com/"


class TestFactoryWithLiteLLM:
    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_default_uses_litellm(self, mock_cls):
        from tradingagents.llm_clients.factory import create_llm_client
        mock_cls.return_value = MagicMock()
        client = create_llm_client("openai", "gpt-4")
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        assert isinstance(client, LiteLLMClient)

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_all_providers_work(self, mock_cls):
        from tradingagents.llm_clients.factory import create_llm_client
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        for provider in ("openai", "anthropic", "google", "azure", "deepseek", "xai", "ollama"):
            client = create_llm_client(provider, "some-model")
            assert isinstance(client, LiteLLMClient)

    def test_legacy_fallback_openai(self):
        from tradingagents.llm_clients.factory import create_llm_client
        from tradingagents.llm_clients.openai_client import OpenAIClient
        client = create_llm_client("openai", "gpt-4", use_litellm=False)
        assert isinstance(client, OpenAIClient)

    def test_legacy_fallback_anthropic(self):
        from tradingagents.llm_clients.factory import create_llm_client
        from tradingagents.llm_clients.anthropic_client import AnthropicClient
        client = create_llm_client("anthropic", "claude-3", use_litellm=False)
        assert isinstance(client, AnthropicClient)

    def test_unknown_provider_raises_in_factory(self):
        from tradingagents.llm_clients.factory import create_llm_client
        with pytest.raises(ValueError, match="Unsupported"):
            create_llm_client("unknown_provider", "some-model")

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_gpt_model_reroutes_to_openai(self, mock_cls):
        from tradingagents.llm_clients.factory import create_llm_client
        from tradingagents.llm_clients.litellm_client import LiteLLMClient
        mock_cls.return_value = MagicMock()
        client = create_llm_client("google", "gpt-4")
        assert isinstance(client, LiteLLMClient)
        assert client.provider == "openai"

    @patch("tradingagents.llm_clients.litellm_client.NormalizedChatLiteLLM")
    def test_custom_base_url_passthrough(self, mock_cls):
        from tradingagents.llm_clients.factory import create_llm_client
        mock_cls.return_value = MagicMock()
        client = create_llm_client("openai", "gpt-4", base_url="http://proxy:8080")
        llm = client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_base"] == "http://proxy:8080"


class TestFetchModelsFromEndpoint:
    @patch("tradingagents.llm_clients.litellm_client.httpx.Client")
    def test_success(self, mock_client_cls):
        from tradingagents.llm_clients.litellm_client import fetch_models_from_endpoint
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "gpt-3.5-turbo"},
            ]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        models = fetch_models_from_endpoint("http://localhost:8080")
        assert len(models) == 2
        assert models[0]["id"] == "gpt-4"
        assert models[0]["name"] == "GPT-4"
        assert models[1]["id"] == "gpt-3.5-turbo"
        assert models[1]["name"] == "gpt-3.5-turbo"

    @patch("tradingagents.llm_clients.litellm_client.httpx.Client")
    def test_failure_returns_empty(self, mock_client_cls):
        from tradingagents.llm_clients.litellm_client import fetch_models_from_endpoint
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        models = fetch_models_from_endpoint("http://localhost:8080", api_key="bad")
        assert models == []

    @patch("tradingagents.llm_clients.litellm_client.httpx.Client")
    def test_connection_error_returns_empty(self, mock_client_cls):
        from tradingagents.llm_clients.litellm_client import fetch_models_from_endpoint
        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client_cls.return_value = mock_client

        models = fetch_models_from_endpoint("http://localhost:9999")
        assert models == []

    @patch("tradingagents.llm_clients.litellm_client.httpx.Client")
    def test_appends_v1_models_path(self, mock_client_cls):
        from tradingagents.llm_clients.litellm_client import fetch_models_from_endpoint
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        fetch_models_from_endpoint("http://localhost:8080/")
        call_url = mock_client.get.call_args[0][0]
        assert call_url == "http://localhost:8080/v1/models"

    @patch("tradingagents.llm_clients.litellm_client.httpx.Client")
    def test_url_already_has_v1_models(self, mock_client_cls):
        from tradingagents.llm_clients.litellm_client import fetch_models_from_endpoint
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        fetch_models_from_endpoint("http://localhost:8080/v1/models")
        call_url = mock_client.get.call_args[0][0]
        assert call_url == "http://localhost:8080/v1/models"


class TestGetLiteLLMSupportedProviders:
    def test_returns_sorted_list(self):
        from tradingagents.llm_clients.litellm_client import get_litellm_supported_providers
        providers = get_litellm_supported_providers()
        assert isinstance(providers, list)
        assert providers == sorted(providers)
        assert "openai" in providers
        assert "anthropic" in providers
        assert "google" in providers
