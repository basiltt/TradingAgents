"""Tool discovery — composition layer (NOT core).

Importing tool modules triggers their `@tool` decorators to register into the
core registry. This lives outside `core/` so that `backend.mcp.core` stays
trading-free (import-linter contract): core defines the registry; this module
populates it by importing `backend.mcp.tools.*`.
"""
from __future__ import annotations

import importlib
import pkgutil

_DISCOVERED = False


def discover_tools() -> None:
    """Import every tool module so its `@tool` decorator runs. Idempotent."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    import backend.mcp.tools as tools_pkg

    for mod in pkgutil.walk_packages(tools_pkg.__path__, tools_pkg.__name__ + "."):
        if mod.ispkg:
            continue
        importlib.import_module(mod.name)
    _DISCOVERED = True
