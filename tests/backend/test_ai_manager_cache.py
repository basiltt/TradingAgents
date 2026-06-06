"""Tests for AI Manager sampling-param gating and cache_control."""


class TestSamplingParams:
    def test_omits_temperature_for_opus_4_7(self):
        from backend.services.ai_manager_llm_provider import _sampling_params
        params = _sampling_params("claude-opus-4-7")
        assert "temperature" not in params
        assert "top_p" not in params

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
