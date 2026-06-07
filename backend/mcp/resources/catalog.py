"""MCP resources + prompts — TASK-P1-10/11.

Resources are stable, low-cost reads exposed under the tradingagents:// scheme
(they don't consume a tool slot). Prompts are bundled guided-journey templates.
Both are server-owned and read-only; this module is trading-light (it reads via
the same ctx.services accessors at call time).
"""
from __future__ import annotations

import re
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
    {
        "uri": "tradingagents://portfolio/snapshot",
        "name": "Portfolio snapshot",
        "description": "Aggregated portfolio P&L summary over the trailing 30 days (redacted to ratios).",
        "mimeType": "application/json",
    },
]

# Resource URI TEMPLATES (RFC-6570-ish) advertised via resources/templates/list.
RESOURCE_TEMPLATES: list[dict[str, str]] = [
    {
        "uriTemplate": "tradingagents://scan/{scan_id}",
        "name": "Scan by id",
        "description": "A specific stored scan by id (no re-run). scan_id must be a valid scan identifier.",
        "mimeType": "application/json",
    },
]

# A scan id is a uuid-like / alphanumeric-dash token. Anything with path or
# scheme characters (.. / : %) is rejected to prevent traversal / cross-scope.
_SCAN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DAY_MS = 86_400_000


def _parse_scan_template(uri: str) -> str | None:
    """Return a VALIDATED scan_id if `uri` matches tradingagents://scan/{id}
    (and is not the literal /latest), else None. Rejects traversal payloads."""
    prefix = "tradingagents://scan/"
    if not uri.startswith(prefix):
        return None
    tail = uri[len(prefix):]
    if tail == "latest" or not tail:
        return None
    if not _SCAN_ID_RE.match(tail):
        raise ValueError("invalid scan id in resource uri")
    return tail


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
    if uri == "tradingagents://portfolio/snapshot":
        db = getattr(services, "db", None)
        clock = getattr(services, "_clock", None)
        if db is None:
            return {"summary": None}
        # 30-day trailing window; tolerate absence of a clock accessor
        import time

        now_ms = int(time.time() * 1000) if clock is None else int(clock.now().timestamp() * 1000)
        try:
            from backend.mcp.core.redact import redact_record

            summary = await db.get_portfolio_pnl_summary(now_ms - 30 * _DAY_MS, now_ms)
            return {"window_days": 30, "summary": redact_record(dict(summary), allow_financial_detail=False)}
        except Exception:  # noqa: BLE001 — resource read is best-effort
            return {"window_days": 30, "summary": None}
    # templated: tradingagents://scan/{id}
    scan_id = _parse_scan_template(uri)
    if scan_id is not None:
        db = getattr(services, "db", None)
        if db is None:
            return {"scan": None}
        from backend.mcp.core.redact import strip_secret_keys

        scan = await db.get_scan(scan_id)
        return {"scan": strip_secret_keys(scan) if scan else None}
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
    "explain_trade_close": {
        "name": "explain_trade_close",
        "description": "Explain why a specific trade was closed (rule, P&L, timing).",
        "arguments": [
            {"name": "account_id", "description": "Account that owns the trade.", "required": True},
            {"name": "trade_id", "description": "The trade to explain.", "required": True},
        ],
        "template": (
            "Explain the close of trade {trade_id} on account {account_id}. "
            "Call trades_get for the trade, identify its close_reason and P&L "
            "ratio, and relate the close to the active close rules (take-profit, "
            "stop-loss, drawdown, breakeven-timeout, max-duration, or trailing). "
            "Be concise and factual; do not propose new trades."
        ),
    },
}


def _clean_arg(value: Any, *, maxlen: int = 64) -> str:
    """Validate + escape a prompt argument before interpolation (alnum/_-/space)."""
    s = str(value or "").strip()
    return "".join(c for c in s if c.isalnum() or c in " _-")[:maxlen]


def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render a bundled prompt with validated, escaped arguments."""
    spec = PROMPTS.get(name)
    if spec is None:
        raise ValueError(f"unknown prompt: {name!r}")
    args = arguments or {}
    if name == "explain_trade_close":
        text = spec["template"].format(
            account_id=_clean_arg(args.get("account_id")) or "<account_id>",
            trade_id=_clean_arg(args.get("trade_id")) or "<trade_id>",
        )
    else:
        obj = _clean_arg(args.get("objective"), maxlen=40)
        objective = f" ({obj})" if obj else ""
        text = spec["template"].format(objective=objective)
    return {"description": spec["description"], "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


class ResourceProvider:
    """Composition wrapper injected into MCPServer (keeps core trading-free)."""

    @property
    def resources(self) -> list[dict[str, str]]:
        return list(RESOURCES)

    @property
    def templates(self) -> list[dict[str, str]]:
        return list(RESOURCE_TEMPLATES)

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
