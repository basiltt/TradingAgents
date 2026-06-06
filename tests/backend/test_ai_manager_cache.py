"""Tests for AI Manager sampling-param gating and cache_control."""


class TestSamplingParams:
    def test_omits_temperature_for_opus_4_7(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        params = _sampling_params("claude-opus-4-7")
        assert "temperature" not in params
        assert "temperature" not in _sampling_params("anthropic/claude-opus-4-8")

    def test_omits_temperature_for_opus_4_8(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        assert "temperature" not in _sampling_params("claude-opus-4-8")

    def test_keeps_temperature_for_sonnet(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        params = _sampling_params("claude-sonnet-4-6")
        assert params["temperature"] == 0.2

    def test_keeps_temperature_for_gpt(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        assert _sampling_params("gpt-5.4")["temperature"] == 0.2

    def test_always_sets_max_tokens(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        assert _sampling_params("claude-opus-4-8")["max_tokens"] == 1024
        assert _sampling_params("claude-sonnet-4-6")["max_tokens"] == 1024


class TestAIManagerUsageExtraction:
    def test_anthropic_usage_cache_fields(self):
        from backend.services.ai_manager_llm_provider import _extract_cache_usage
        data = {"usage": {"input_tokens": 12,
                          "cache_read_input_tokens": 1840,
                          "cache_creation_input_tokens": 0}}
        m = _extract_cache_usage(data, provider="anthropic")
        assert m["cache_read"] == 1840

    def test_openai_usage_cache_fields(self):
        from backend.services.ai_manager_llm_provider import _extract_cache_usage
        data = {"usage": {"prompt_tokens": 12,
                          "prompt_tokens_details": {"cached_tokens": 900}}}
        m = _extract_cache_usage(data, provider="openai")
        assert m["cache_read"] == 900

    def test_missing_usage_returns_none(self):
        from backend.services.ai_manager_llm_provider import _extract_cache_usage
        assert _extract_cache_usage({}, provider="anthropic")["cache_read"] is None
