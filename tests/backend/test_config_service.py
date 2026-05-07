"""Tests for config service — TASK-005."""

import pytest


@pytest.fixture
def config_service(tmp_path):
    from backend.persistence import AnalysisDB
    from backend.services.config_service import ConfigService

    import os
    dsn = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test")
    db = AnalysisDB(dsn=dsn)
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


def test_forbidden_key_rejected(config_service):
    with pytest.raises(ValueError, match="Cannot override"):
        config_service.update_config({"backend_url": "http://evil.com"})


def test_type_mismatch_rejected(config_service):
    with pytest.raises(ValueError, match="invalid type"):
        config_service.update_config({"max_debate_rounds": "not_an_int"})


def test_bool_as_int_rejected(config_service):
    with pytest.raises(ValueError, match="invalid type.*expected int"):
        config_service.update_config({"max_debate_rounds": True})


def test_value_too_large(config_service):
    with pytest.raises(ValueError, match="exceeds maximum"):
        config_service.update_config({"max_debate_rounds": 2_000_000})


def test_string_too_long(config_service):
    with pytest.raises(ValueError, match="exceeds maximum length"):
        config_service.update_config({"llm_provider": "x" * 2000})

