"""MCP resources + prompts — TASK-P1-10/11.

Resources are stable, low-cost reads exposed under the tradingagents:// scheme
(they don't consume a tool slot). Prompts are bundled guided-journey templates.
Both are server-owned and read-only; this module is trading-light (it reads via
the same ctx.services accessors at call time).
"""
from __future__ import annotations

from typing import Any

# --- static resource catalog ---

RESOURCES: list[dict[str, str]] = [
    {
        "uri": "tradingagents://server/info",
        "name": "Server info",
        "description": "MCP server name, version, and contract/schema version.",
        "mimeType": "application/json",
    },
    {
        "uri": "tradingagents://scan/latest",
        "name": "Latest scan",
        "description": "Summary of the most recent market scan.",
        "mimeType": "application/json",
    },
    {
        "uri": "tradingagents://config/current",
        "name": "Current config",
        "description": "The current scheduled-scanner AutoTradeConfig baseline (redacted).",
        "mimeType": "application/json",
    },
]


async def read_resource(uri: str, services: Any, *, server_version: str = "0.1.0") -> dict[str, Any]:
    """Return the contents for a resource URI. Validates the scheme/path."""
    if uri == "tradingagents://server/info":
        return {
            "name": "tradingagents-mcp",
            "version": server_version,
            "contract_schema_version": 1,
        }
    if uri == "tradingagents://scan/latest":
        db = getattr(services, "db", None)
        if db is None:
            return {"scan": None}
        scans = await db.list_scans()
        return {"scan": scans[0] if scans else None}
    if uri == "tradingagents://config/current":
        db = getattr(services, "db", None)
        if db is None:
            return {"schedules": []}
        rows = await db.list_scheduled_scans()
        return {"schedule_count": len(rows)}
    raise ValueError(f"unknown resource uri: {uri!r}")


# --- bundled prompts ---

PROMPTS: dict[str, dict[str, Any]] = {
    "optimize_my_config": {
        "name": "optimize_my_config",
        "description": "Guide the agent to find a better AutoTradeConfig via a sweep.",
        "arguments": [
            {"name": "objective", "description": "Objective metric (e.g. sharpe).", "required": False},
        ],
        "template": (
            "You are optimizing the trading configuration. First read the current "
            "config and recent scan data. Then call sweep_estimate, then "
            "optimize_config with the user's objective{objective}. Report the best "
            "config with its uplift vs the current baseline and its robustness "
            "verdict. You can only PROPOSE; a human approves the change."
        ),
    },
    "audit_last_scan": {
        "name": "audit_last_scan",
        "description": "Walk through the most recent scan's results and decisions.",
        "arguments": [],
        "template": (
            "Read the latest scan (scans_list, then scans_get). Summarize the "
            "ranked signals and any auto-trade outcomes. Use the debug tools only "
            "if allow_debug is enabled."
        ),
    },
}


def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render a bundled prompt with validated, escaped arguments."""
    spec = PROMPTS.get(name)
    if spec is None:
        raise ValueError(f"unknown prompt: {name!r}")
    args = arguments or {}
    obj = str(args.get("objective", "")).strip()
    obj = "".join(c for c in obj if c.isalnum() or c in " _-")[:40]
    objective = f" ({obj})" if obj else ""
    text = spec["template"].format(objective=objective)
    return {"description": spec["description"], "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


class ResourceProvider:
    """Composition wrapper injected into MCPServer (keeps core trading-free)."""

    @property
    def resources(self) -> list[dict[str, str]]:
        return list(RESOURCES)

    async def read(self, uri: str, services: Any, server_version: str) -> dict[str, Any]:
        return await read_resource(uri, services, server_version=server_version)


class PromptProvider:
    def list(self) -> list[dict[str, Any]]:
        return [
            {"name": p["name"], "description": p["description"], "arguments": p["arguments"]}
            for p in PROMPTS.values()
        ]

    def get(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return get_prompt(name, arguments)
