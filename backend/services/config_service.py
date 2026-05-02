"""Config service — resolves defaults + env vars + runtime overrides — TASK-005."""

from __future__ import annotations

import os
from typing import Any, Dict

from tradingagents.default_config import DEFAULT_CONFIG

_ALLOWLISTED_KEYS = frozenset(DEFAULT_CONFIG.keys()) - {
    "project_dir",
    "results_dir",
    "data_cache_dir",
}

_SECRET_KEYS = frozenset(k for k in DEFAULT_CONFIG if "key" in k.lower() or "api_key" in k.lower())

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
    def __init__(self, db: Any = None):
        self._db = db
        self._overrides: Dict[str, Any] = {}

    def get_config(self) -> Dict[str, Any]:
        defaults = dict(DEFAULT_CONFIG)
        resolved = dict(DEFAULT_CONFIG)

        for key, env_var in _ENV_MAP.items():
            val = os.getenv(env_var)
            if val is not None:
                resolved[key] = val

        for key, val in self._overrides.items():
            resolved[key] = val

        masked_resolved = {}
        for k, v in resolved.items():
            if k in _SECRET_KEYS and isinstance(v, str) and v:
                masked_resolved[k] = "***"
            else:
                masked_resolved[k] = v

        return {
            "defaults": defaults,
            "overrides": dict(self._overrides),
            "resolved": masked_resolved,
        }

    def update_config(self, patch: Dict[str, Any]) -> None:
        for key in patch:
            if key in _FORBIDDEN_OVERRIDE_KEYS:
                raise ValueError(
                    f"Cannot override '{key}' via API — read from environment variables"
                )
            if key not in _ALLOWLISTED_KEYS:
                raise ValueError(f"unknown config key: '{key}'")

        self._overrides.update(patch)
