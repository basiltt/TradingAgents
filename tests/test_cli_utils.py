"""Tests for cli.utils — Phase 1 unit tests."""

import pytest


class TestNormalizeTickerSymbol:
    def test_basic(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("aapl") == "AAPL"

    def test_strips_whitespace(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("  spy  ") == "SPY"

    def test_preserves_suffix(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("cnc.to") == "CNC.TO"

    def test_already_upper(self):
        from cli.utils import normalize_ticker_symbol
        assert normalize_ticker_symbol("GOOG") == "GOOG"


class TestFetchOpenRouterModels:
    def test_success(self):
        from unittest.mock import patch, MagicMock
        from cli.utils import _fetch_openrouter_models
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "model-1", "name": "Model One"},
                {"id": "model-2"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = _fetch_openrouter_models()
        assert result == [("Model One", "model-1"), ("model-2", "model-2")]

    def test_failure_returns_empty(self):
        from unittest.mock import patch
        from cli.utils import _fetch_openrouter_models
        with patch("requests.get", side_effect=Exception("fail")):
            result = _fetch_openrouter_models()
        assert result == []


class TestGetTicker:
    def test_returns_normalized(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.text.return_value.ask.return_value = "  aapl  "
            mq.Style = MagicMock()
            from cli.utils import get_ticker
            assert get_ticker() == "AAPL"

    def test_none_exits(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.text.return_value.ask.return_value = None
            mq.Style = MagicMock()
            with pytest.raises(SystemExit):
                from cli.utils import get_ticker
                get_ticker()


class TestGetAnalysisDate:
    def test_returns_date(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.text.return_value.ask.return_value = "2025-01-10"
            mq.Style = MagicMock()
            from cli.utils import get_analysis_date
            assert get_analysis_date() == "2025-01-10"

    def test_none_exits(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.text.return_value.ask.return_value = None
            mq.Style = MagicMock()
            with pytest.raises(SystemExit):
                from cli.utils import get_analysis_date
                get_analysis_date()


class TestSelectAnalysts:
    def test_returns_choices(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.checkbox.return_value.ask.return_value = ["market", "news"]
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import select_analysts
            assert select_analysts() == ["market", "news"]

    def test_none_exits(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.checkbox.return_value.ask.return_value = None
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            with pytest.raises(SystemExit):
                from cli.utils import select_analysts
                select_analysts()


class TestSelectResearchDepth:
    def test_returns_value(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = 3
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import select_research_depth
            assert select_research_depth() == 3

    def test_none_exits(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = None
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            with pytest.raises(SystemExit):
                from cli.utils import select_research_depth
                select_research_depth()


class TestSelectLlmProvider:
    def test_returns_provider(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = ("openai", "https://api.openai.com/v1")
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import select_llm_provider
            provider, url = select_llm_provider()
            assert provider == "openai"

    def test_none_exits(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = None
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            with pytest.raises(SystemExit):
                from cli.utils import select_llm_provider
                select_llm_provider()


class TestSelectModel:
    def test_azure_provider(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.text.return_value.ask.return_value.strip.return_value = "my-deploy"
            mq.Style = MagicMock()
            from cli.utils import _select_model
            assert _select_model("azure", "deep") == "my-deploy"

    def test_custom_model(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "custom"
            mq.text.return_value.ask.return_value.strip.return_value = "gpt-5"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import _select_model
            assert _select_model("openai", "quick") == "gpt-5"

    def test_normal_selection(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "gpt-4o"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import _select_model
            assert _select_model("openai", "quick") == "gpt-4o"

    def test_none_exits(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = None
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            with pytest.raises(SystemExit):
                from cli.utils import _select_model
                _select_model("openai", "quick")


class TestAskOutputLanguage:
    def test_normal_selection(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "Japanese"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import ask_output_language
            assert ask_output_language() == "Japanese"

    def test_custom_language(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "custom"
            mq.text.return_value.ask.return_value.strip.return_value = "Turkish"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import ask_output_language
            assert ask_output_language() == "Turkish"


class TestAskReasoningEffort:
    def test_openai(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "high"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import ask_openai_reasoning_effort
            assert ask_openai_reasoning_effort() == "high"

    def test_anthropic(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "medium"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import ask_anthropic_effort
            assert ask_anthropic_effort() == "medium"

    def test_gemini(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq:
            mq.select.return_value.ask.return_value = "high"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import ask_gemini_thinking_config
            assert ask_gemini_thinking_config() == "high"


class TestSelectOpenRouterModel:
    def test_normal_selection(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq, \
             patch("cli.utils._fetch_openrouter_models", return_value=[("M1", "m1")]):
            mq.select.return_value.ask.return_value = "m1"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import select_openrouter_model
            assert select_openrouter_model() == "m1"

    def test_custom_selection(self):
        from unittest.mock import patch, MagicMock
        with patch("cli.utils.questionary") as mq, \
             patch("cli.utils._fetch_openrouter_models", return_value=[]):
            mq.select.return_value.ask.return_value = "custom"
            mq.text.return_value.ask.return_value.strip.return_value = "google/gemma-4"
            mq.Style = MagicMock()
            mq.Choice = MagicMock()
            from cli.utils import select_openrouter_model
            assert select_openrouter_model() == "google/gemma-4"
