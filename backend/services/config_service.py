"""Config service — resolves defaults + env vars + runtime overrides — TASK-005."""

from __future__ import annotations

import os
from typing import Any, Dict

from backend.utils import mask_secrets
from tradingagents.default_config import DEFAULT_CONFIG

_ALLOWLISTED_KEYS = frozenset(DEFAULT_CONFIG.keys()) - {
    "project_dir",
    "results_dir",
    "data_cache_dir",
}

_FORBIDDEN_OVERRIDE_KEYS = frozenset(
    k for k in DEFAULT_CONFIG if "api_key" in k.lower() or k == "backend_url"
)

_ENV_MAP = {
    "llm_provider": "TRADINGAGENTS_LLM_PROVIDER",
    "deep_think_llm": "TRADINGAGENTS_DEEP_THINK_LLM",
    "quick_think_llm": "TRADINGAGENTS_QUICK_THINK_LLM",
    "backend_url": "TRADINGAGENTS_BACKEND_URL",
    "results_dir": "TRADINGAGENTS_RESULTS_DIR",
    "data_cache_dir": "TRADINGAGENTS_CACHE_DIR",
    "memory_log_path": "TRADINGAGENTS_MEMORY_LOG_PATH",
}


class ConfigService:
    """Resolves runtime config from DEFAULT_CONFIG, env vars, and validated overrides."""

    def __init__(self, db: Any = None):
        self._db = db
        self._overrides: Dict[str, Any] = {}

    def get_config(self) -> Dict[str, Any]:
        """Return masked {"defaults", "overrides", "resolved"} config maps.

        `resolved` layers env-var values then runtime overrides over the defaults;
        secrets are masked in all three.
        """
        defaults = dict(DEFAULT_CONFIG)
        resolved = dict(DEFAULT_CONFIG)

        for key, env_var in _ENV_MAP.items():
            val = os.getenv(env_var)
            if val is not None:
                resolved[key] = val

        resolved.update(self._overrides)

        return {
            "defaults": mask_secrets(defaults),
            "overrides": mask_secrets(dict(self._overrides)),
            "resolved": mask_secrets(resolved),
        }

    def update_config(self, patch: Dict[str, Any]) -> None:
        """Apply runtime config overrides after validation.

        Raises ValueError for forbidden keys (api keys / backend_url), unknown
        keys, type mismatches, or values exceeding size limits.
        """
        for key, value in patch.items():
            if key in _FORBIDDEN_OVERRIDE_KEYS:
                raise ValueError(
                    f"Cannot override '{key}' via API — read from environment variables"
                )
            if key not in _ALLOWLISTED_KEYS:
                raise ValueError(f"unknown config key: '{key}'")

            default_val = DEFAULT_CONFIG.get(key)
            if default_val is not None and not isinstance(value, type(default_val)):
                raise ValueError(
                    f"invalid type for '{key}': expected {type(default_val).__name__}"
                )
            if isinstance(default_val, int) and not isinstance(default_val, bool) and isinstance(value, bool):
                raise ValueError(
                    f"invalid type for '{key}': expected int, got bool"
                )
            if isinstance(value, (int, float)) and value > 1_000_000:
                raise ValueError(f"value for '{key}' exceeds maximum allowed")
            if isinstance(value, str) and len(value) > 1024:
                raise ValueError(f"value for '{key}' exceeds maximum length")

        self._overrides.update(patch)
