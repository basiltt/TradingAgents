"""Tests for the prompt_cache_enabled config flag (default OFF, env-overridable)."""
import importlib


class TestPromptCacheFlag:
    def test_defaults_off(self, monkeypatch):
        monkeypatch.delenv("TRADINGAGENTS_PROMPT_CACHE_ENABLED", raising=False)
        import tradingagents.default_config as dc
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["prompt_cache_enabled"] is False

    def test_env_override_on(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_PROMPT_CACHE_ENABLED", "true")
        import tradingagents.default_config as dc
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["prompt_cache_enabled"] is True

    def test_env_override_off_explicit(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_PROMPT_CACHE_ENABLED", "false")
        import tradingagents.default_config as dc
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["prompt_cache_enabled"] is False
