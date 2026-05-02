"""Shared utilities for the web backend."""

from __future__ import annotations

from typing import Any, Dict

_SECRET_SUBSTRINGS = frozenset({"api_key", "secret", "token", "password"})


def mask_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: "***" if any(s in k.lower() for s in _SECRET_SUBSTRINGS) and isinstance(v, str) and v else v
        for k, v in config.items()
    }
