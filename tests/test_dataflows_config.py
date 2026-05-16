"""Tests for tradingagents.dataflows.config — Phase 1 unit tests."""

from tradingagents.dataflows import config as cfg_mod


class TestDataflowsConfig:
    def test_get_config_returns_dict(self):
        result = cfg_mod.get_config()
        assert isinstance(result, dict)
        assert "llm_provider" in result

    def test_set_config_overrides(self):
        original = cfg_mod.get_config()
        cfg_mod.set_config({"output_language": "Japanese"})
        assert cfg_mod.get_config()["output_language"] == "Japanese"
        cfg_mod.set_config({"output_language": original.get("output_language", "English")})

    def test_get_config_returns_copy(self):
        c1 = cfg_mod.get_config()
        c2 = cfg_mod.get_config()
        assert c1 is not c2

    def test_set_config_when_none(self):
        original = cfg_mod._config
        try:
            cfg_mod._config = None
            cfg_mod.set_config({"output_language": "French"})
            assert cfg_mod.get_config()["output_language"] == "French"
        finally:
            cfg_mod._config = original

    def test_get_config_when_none(self):
        original = cfg_mod._config
        try:
            cfg_mod._config = None
            result = cfg_mod.get_config()
            assert isinstance(result, dict)
        finally:
            cfg_mod._config = original
