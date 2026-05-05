"""Tests for tradingagents.llm_clients.openai_client and google_client — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock
import os
import pytest


class TestInputToMessages:
    def test_list_passthrough(self):
        from tradingagents.llm_clients.openai_client import _input_to_messages
        msgs = [MagicMock()]
        assert _input_to_messages(msgs) is msgs

    def test_chat_prompt_value(self):
        from tradingagents.llm_clients.openai_client import _input_to_messages
        obj = MagicMock()
        obj.to_messages.return_value = ["m1", "m2"]
        assert _input_to_messages(obj) == ["m1", "m2"]

    def test_other_returns_empty(self):
        from tradingagents.llm_clients.openai_client import _input_to_messages
        assert _input_to_messages("string") == []


class TestOpenAIClientGetLlm:
    @patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI")
    def test_native_openai_uses_responses_api(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        client = OpenAIClient("gpt-4", provider="openai")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["use_responses_api"] is True

    @patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI")
    def test_xai_provider(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"XAI_API_KEY": "key123"}):
            client = OpenAIClient("grok-3", provider="xai")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["base_url"] == "https://api.x.ai/v1"
        assert kwargs["api_key"] == "key123"

    @patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI")
    def test_ollama_provider(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        client = OpenAIClient("llama3", provider="ollama")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_key"] == "ollama"

    @patch("tradingagents.llm_clients.openai_client.DeepSeekChatOpenAI")
    def test_deepseek_uses_subclass(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "dk"}):
            client = OpenAIClient("deepseek-chat", provider="deepseek")
            client.get_llm()
        mock_cls.assert_called_once()

    @patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI")
    def test_custom_base_url_with_dummy_key(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        client = OpenAIClient("model", base_url="http://proxy", provider="custom")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["base_url"] == "http://proxy"
        assert kwargs["api_key"] == "dummy"

    @patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI")
    def test_passthrough_kwargs(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        client = OpenAIClient("gpt-4", provider="openai", timeout=30, reasoning_effort="high")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["timeout"] == 30
        assert kwargs["reasoning_effort"] == "high"

    @patch("tradingagents.llm_clients.openai_client.NormalizedChatOpenAI")
    def test_provider_no_env_key_with_base_url_gets_dummy(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        mock_cls.return_value = MagicMock()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            client = OpenAIClient("model", base_url="http://myproxy", provider="xai")
            client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["api_key"] == "dummy"


class TestDeepSeekStructuredOutput:
    @patch("tradingagents.llm_clients.openai_client.DeepSeekChatOpenAI")
    def test_reasoner_raises(self, mock_cls):
        from tradingagents.llm_clients.openai_client import OpenAIClient
        # Test via OpenAIClient to avoid Pydantic construction issues
        mock_instance = MagicMock()
        mock_instance.with_structured_output.side_effect = NotImplementedError("no tool_choice")
        mock_cls.return_value = mock_instance
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "dk"}):
            client = OpenAIClient("deepseek-reasoner", provider="deepseek")
            llm = client.get_llm()
        with pytest.raises(NotImplementedError):
            llm.with_structured_output(dict)


class TestGoogleClientGetLlm:
    @patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI")
    def test_basic(self, mock_cls):
        from tradingagents.llm_clients.google_client import GoogleClient
        mock_cls.return_value = MagicMock()
        client = GoogleClient("gemini-pro")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "gemini-pro"

    @patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI")
    def test_gemini3_thinking_level(self, mock_cls):
        from tradingagents.llm_clients.google_client import GoogleClient
        mock_cls.return_value = MagicMock()
        client = GoogleClient("gemini-3-flash", thinking_level="high")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["thinking_level"] == "high"

    @patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI")
    def test_gemini3_pro_minimal_mapped_to_low(self, mock_cls):
        from tradingagents.llm_clients.google_client import GoogleClient
        mock_cls.return_value = MagicMock()
        client = GoogleClient("gemini-3-pro", thinking_level="minimal")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["thinking_level"] == "low"

    @patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI")
    def test_gemini25_thinking_budget(self, mock_cls):
        from tradingagents.llm_clients.google_client import GoogleClient
        mock_cls.return_value = MagicMock()
        client = GoogleClient("gemini-2.5-flash", thinking_level="high")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["thinking_budget"] == -1

    @patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI")
    def test_gemini25_thinking_budget_low(self, mock_cls):
        from tradingagents.llm_clients.google_client import GoogleClient
        mock_cls.return_value = MagicMock()
        client = GoogleClient("gemini-2.5-flash", thinking_level="low")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["thinking_budget"] == 0

    @patch("tradingagents.llm_clients.google_client.NormalizedChatGoogleGenerativeAI")
    def test_google_api_key(self, mock_cls):
        from tradingagents.llm_clients.google_client import GoogleClient
        mock_cls.return_value = MagicMock()
        client = GoogleClient("gemini-pro", api_key="mykey")
        client.get_llm()
        kwargs = mock_cls.call_args[1]
        assert kwargs["google_api_key"] == "mykey"
