"""Token-budget estimation — pure, deterministic, trading-free (core).

The MCP protocol sends each enabled tool's name, description, and input JSON
Schema to the model as part of the tools array. That text consumes context
window. This module estimates that cost so the operator UI can let the user
enable only the tools that fit — directly addressing the requirement that
"if we enable all the tools at the same time the context size of the model
will be full".

Estimation is intentionally tokenizer-free: a ~4-characters-per-token heuristic
(well established for English + JSON) plus a fixed per-tool envelope overhead
for the protocol wrapper. It is deterministic (no clock, no randomness) so the
UI shows stable numbers and tests are reproducible. It is an estimate, not a
billing figure — the goal is relative guidance ("optimizer is expensive, scans
are cheap"), not exact accounting.
"""
from __future__ import annotations

import json
from collections import defaultdict

from backend.mcp.core.registry import ToolSpec

# Average English/JSON characters per token (GPT/Claude BPE family ~3.5-4.2).
_CHARS_PER_TOKEN = 4.0
# Fixed protocol envelope per tool (JSON wrapper keys, delimiters, role framing).
_ENVELOPE_TOKENS = 12


def _schema_text(spec: ToolSpec) -> str:
    """The input JSON Schema as the model sees it, serialized stably."""
    try:
        schema = spec.input_schema.model_json_schema()
    except Exception:  # noqa: BLE001 — a malformed schema must not crash the UI
        return ""
    # sort_keys => deterministic regardless of field declaration order
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


def estimate_tool_tokens(spec: ToolSpec) -> int:
    """Estimate the context-token cost of advertising one tool to the model.

    Counts the name, the agent-facing description, and the serialized input
    schema, plus a fixed protocol envelope. Deterministic and side-effect free.
    """
    text = f"{spec.name}\n{spec.description}\n{_schema_text(spec)}"
    return _ENVELOPE_TOKENS + int(len(text) / _CHARS_PER_TOKEN)


def estimate_total_tokens(specs: list[ToolSpec]) -> int:
    """Sum of per-tool estimates for the given set."""
    return sum(estimate_tool_tokens(s) for s in specs)


def estimate_group_tokens(specs: list[ToolSpec]) -> dict[str, int]:
    """Per-group token rollup keyed by ToolGroup value."""
    out: dict[str, int] = defaultdict(int)
    for s in specs:
        out[s.group.value] += estimate_tool_tokens(s)
    return dict(out)
