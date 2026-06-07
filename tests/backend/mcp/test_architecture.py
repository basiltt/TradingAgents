"""Architecture-boundary + deny-list tests — TASK-P0-04/14."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


def test_import_linter_contracts_pass():
    """The one-way dependency + trading-free-core + removability contracts hold."""
    result = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_registered_tool_handler_references_deny_method():
    """Static guard: no tool handler's source references a deny-listed money/
    config/exchange sink. (A coarse source-substring check; a negative control
    proves it has teeth.)"""
    import inspect

    from backend.mcp.core.registry import _DENY_METHODS, _REGISTRY
    from backend.mcp.discovery import discover_tools

    discover_tools()
    assert _REGISTRY, "expected at least one registered tool"
    for name, spec in _REGISTRY.items():
        try:
            src = inspect.getsource(spec.handler)
        except (OSError, TypeError):
            continue
        for deny in _DENY_METHODS:
            assert deny not in src, f"tool {name!r} references deny-listed method {deny!r}"


def test_deny_list_negative_control():
    """A handler that DOES reference a deny method must be detected by the check."""
    from backend.mcp.core.registry import _DENY_METHODS

    def _bad_handler(args, ctx):
        # deliberately references a deny-listed sink
        return ctx.services.db.update_scheduled_scan("x", {})

    import inspect

    src = inspect.getsource(_bad_handler)
    assert any(deny in src for deny in _DENY_METHODS)
