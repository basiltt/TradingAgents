"""Shared output formatting for LangChain tool wrappers."""

from __future__ import annotations

import html

_MAX_OUTPUT_CHARS = 50 * 1024


def sanitize_tool_output(raw: str) -> str:
    """Truncate, escape, and wrap tool output for safe LLM consumption."""
    if len(raw) > _MAX_OUTPUT_CHARS:
        raw = raw[:_MAX_OUTPUT_CHARS] + "\n[truncated]"
    escaped = html.escape(raw, quote=False)
    return f"<data>{escaped}</data>"
