"""Tests for config service — TASK-005."""

import pytest


@pytest.fixture
def config_service(tmp_path):
    from backend.persistence import AnalysisDB
    from backend.services.config_service import ConfigService

    db = AnalysisDB(db_path=str(tmp_path / "test.db"))
    return ConfigService(db=db)


def test_get_config_returns_resolved(config_service):
    result = config_service.get_config()
    assert "defaults" in result
    assert "overrides" in result
    assert "resolved" in result
    assert result["resolved"]["llm_provider"] is not None


def test_api_keys_masked(config_service):
    result = config_service.get_config()
    for key, value in result["resolved"].items():
        if "api_key" in key.lower() or "key" in key.lower():
            if isinstance(value, str) and len(value) > 0:
                assert "***" in str(value) or value == "***"


def test_update_config_valid_key(config_service):
    config_service.update_config({"output_language": "Japanese"})
    result = config_service.get_config()
    assert result["overrides"]["output_language"] == "Japanese"
    assert result["resolved"]["output_language"] == "Japanese"


def test_update_config_unknown_key_rejected(config_service):
    with pytest.raises(ValueError, match="unknown"):
        config_service.update_config({"nonexistent_key": "value"})


def test_api_key_not_in_overrides(config_service):
    with pytest.raises(ValueError):
        config_service.update_config({"OPENAI_API_KEY": "sk-test"})


def test_env_var_resolution(config_service, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "google")
    result = config_service.get_config()
    assert result["resolved"]["llm_provider"] == "google"


def test_llm_api_key_masked():
    from backend.utils import mask_secrets
    config = {"llm_provider": "anthropic", "llm_api_key": "sk-secret-123"}
    masked = mask_secrets(config)
    assert masked["llm_api_key"] == "***"
    assert masked["llm_provider"] == "anthropic"
