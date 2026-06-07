"""MCP control-plane router — TASK-P0-12.

Same-origin REST at /api/v1/mcp/* for the operator UI (existing app auth + CSRF
via the global middleware). 503 when the MCP module is absent; 200 {state:"off"}
when present-but-disabled.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["mcp"])


def _manager(request: Request):
    mgr = getattr(request.app.state, "mcp_manager", None)
    if mgr is None or mgr.config_repo is None:
        raise HTTPException(503, detail="MCP module not available")
    return mgr


class ConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    capability_tier: Optional[str] = None
    enabled_groups: Optional[list[str]] = None
    enabled_tools: Optional[dict[str, bool]] = None
    expected_row_version: int


async def _pending_proposals(mgr) -> int:
    repo = mgr.config_repo
    try:
        async with repo._pool.acquire() as conn:  # noqa: SLF001 — read-only count
            return await conn.fetchval(
                "SELECT count(*) FROM mcp_proposals WHERE status='pending'"
            ) or 0
    except Exception:
        return 0


@router.get("/mcp/config")
async def get_config(request: Request) -> dict[str, Any]:
    mgr = _manager(request)
    cfg = await mgr.config_repo.get()
    return {
        "enabled": cfg.enabled,
        "capability_tier": cfg.capability_tier,
        "enabled_groups": cfg.enabled_groups,
        "enabled_tools": cfg.enabled_tools,
        "safe_mode_flags": cfg.safe_mode_flags,
        "row_version": cfg.row_version,
        "bind_host": cfg.bind_host,
        "has_token": bool(cfg.access_token_hash),
    }


@router.patch("/mcp/config")
async def patch_config(request: Request, body: ConfigPatch) -> dict[str, Any]:
    mgr = _manager(request)
    patch = body.model_dump(exclude_none=True, exclude={"expected_row_version"})
    from backend.mcp.core.errors import MCPConflictError

    try:
        await mgr.config_repo.update(patch, expected_row_version=body.expected_row_version)
    except MCPConflictError as exc:
        raise HTTPException(409, detail=str(exc))
    return await get_config(request)


@router.post("/mcp/enable")
async def enable(request: Request) -> dict[str, Any]:
    mgr = _manager(request)
    from backend.mcp.core.preflight import run_preflight
    from backend.mcp.core.registry import ToolGroup

    cfg = await mgr.config_repo.get()
    optimizer_on = ToolGroup.OPTIMIZER.value in cfg.enabled_groups
    result = run_preflight(cfg, schema_version=44, optimizer_enabled=optimizer_on)
    if not result.ok:
        raise HTTPException(422, detail={"preflight_failed": result.failed_invariant})
    await mgr.enable()
    return {"enabled": True}


@router.post("/mcp/disable")
async def disable(request: Request, kill: bool = False) -> dict[str, Any]:
    mgr = _manager(request)
    await mgr.disable(kill=kill)
    return {"enabled": False, "killed": kill}


@router.post("/mcp/token/regenerate")
async def regenerate_token(request: Request) -> dict[str, Any]:
    mgr = _manager(request)
    from backend.mcp.core.auth import generate_token

    plaintext, token_hash = generate_token()
    await mgr.config_repo.set_token_hash(token_hash)
    # plaintext shown once; never stored
    return {"token": plaintext}


@router.get("/mcp/status")
async def status(request: Request) -> dict[str, Any]:
    mgr = getattr(request.app.state, "mcp_manager", None)
    if mgr is None or mgr.config_repo is None:
        raise HTTPException(503, detail="MCP module not available")
    cfg = await mgr.config_repo.get()
    running = getattr(request.app.state, "mcp_server", None) is not None
    return {
        "state": "running" if running else "off",
        "enabled": cfg.enabled,
        "active_tools": len(mgr.server.list_tools()) if running and mgr.server else 0,
        "pending_proposals": await _pending_proposals(mgr),
        "last_error": getattr(mgr, "last_error", None),
        "last_error_at": None,
    }


@router.get("/mcp/health")
async def health(request: Request) -> dict[str, Any]:
    """Ops probe — 200 even when OFF (feature-disabled is healthy)."""
    mgr = getattr(request.app.state, "mcp_manager", None)
    running = getattr(request.app.state, "mcp_server", None) is not None
    pending = await _pending_proposals(mgr) if mgr and mgr.config_repo else 0
    return {"state": "running" if running else "off", "pending_proposals": pending}


@router.get("/mcp/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    """Minimal P0 stub: enabled tool names. Enriched (full registry + est_tokens
    + presets) in P2 via /mcp/registry."""
    mgr = _manager(request)
    server = getattr(request.app.state, "mcp_server", None)
    if server is None:
        return {"tools": []}
    return {"tools": [t["name"] for t in server.list_tools()]}


def _service_available(request: Request, group) -> bool:
    """Delegate to the manager's single source of truth so the OFF-state budget
    reflects the same availability logic the live resolver uses (no drift)."""
    mgr = getattr(request.app.state, "mcp_manager", None)
    if mgr is not None and hasattr(mgr, "_service_available"):
        return mgr._service_available(group)  # noqa: SLF001 — intentional single-source reuse
    # Fallback mirrors MCPManager._service_available if the manager is absent.
    from backend.mcp.core.registry import ToolGroup

    if group == ToolGroup.SCANS:
        return getattr(request.app.state, "db", None) is not None
    return True


@router.get("/mcp/registry")
async def registry(request: Request) -> dict[str, Any]:
    """Full tool catalog annotated with token cost + enabled/available state.

    Returns EVERY registered tool (not just the enabled set) so the operator UI
    can render the context-budget manager while the server is OFF — the user
    selects what fits the model's context window before turning the server on.
    """
    mgr = _manager(request)
    from backend.mcp.core.budget import estimate_tool_tokens
    from backend.mcp.core.registry import (
        PRESETS,
        iter_specs,
        resolve_enabled,
        tier_allows,
    )
    from backend.mcp.discovery import discover_tools

    discover_tools()  # idempotent; populate the registry even when OFF
    cfg = await mgr.config_repo.get()
    debug_allowed = bool(cfg.safe_mode_flags.get("allow_debug", False))

    from backend.mcp.core.registry import MCPConfigView

    view = MCPConfigView(
        capability_tier=cfg.capability_tier,
        enabled_groups=cfg.enabled_groups,
        enabled_tools=cfg.enabled_tools,
    )
    enabled_names = {
        s.name
        for s in resolve_enabled(
            view,
            available=lambda g: _service_available(request, g),
            debug_allowed=debug_allowed,
        )
    }

    tools: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    total = 0
    selected = 0
    for spec in iter_specs():
        est = estimate_tool_tokens(spec)
        is_enabled = spec.name in enabled_names
        available = _service_available(request, spec.group)
        tier_ok = tier_allows(spec.safety_class, cfg.capability_tier)
        tools.append(
            {
                "name": spec.name,
                "group": spec.group.value,
                "safety_class": spec.safety_class.value,
                "est_tokens": est,
                "enabled": is_enabled,
                "available": available and tier_ok,
                "mutating": spec.mutating,
                "exchange_facing": spec.exchange_facing,
                "description": spec.description,
            }
        )
        g = groups.setdefault(
            spec.group.value, {"est_tokens": 0, "tool_count": 0, "enabled_count": 0}
        )
        g["est_tokens"] += est
        g["tool_count"] += 1
        if is_enabled:
            g["enabled_count"] += 1
            selected += est
        total += est

    # Presets are predicates over registry metadata → the tool names they select.
    preset_map = {
        name: [s.name for s in iter_specs() if pred(s)]
        for name, pred in PRESETS.items()
    }

    return {
        "tools": tools,
        "groups": groups,
        "presets": preset_map,
        "total_est_tokens": total,
        "selected_est_tokens": selected,
        "capability_tier": cfg.capability_tier,
        "enabled_groups": cfg.enabled_groups,
        "row_version": cfg.row_version,
    }


class PresetApply(BaseModel):
    preset: str
    expected_row_version: int


@router.post("/mcp/registry/preset")
async def apply_preset(request: Request, body: PresetApply) -> dict[str, Any]:
    """Apply a named preset by writing per-tool overrides (most-restrictive).

    Translates a preset predicate into an explicit enabled_tools map so the
    selection is exact and auditable, and clears group-level enables to avoid
    double-counting. The UI then reflects the new selection via /mcp/registry.
    """
    mgr = _manager(request)
    from backend.mcp.core.errors import MCPConflictError
    from backend.mcp.core.registry import (
        _TIER_RANK,
        PRESETS,
        iter_specs,
        required_tier,
    )
    from backend.mcp.discovery import discover_tools

    discover_tools()
    pred = PRESETS.get(body.preset)
    if pred is None:
        raise HTTPException(422, detail={"unknown_preset": body.preset})

    selected = [s for s in iter_specs() if pred(s)]
    overrides = {s.name: (s in selected) for s in iter_specs()}
    # A preset is a complete intent: raise the tier ceiling to whatever the
    # selection needs. Hard-clamp at BACKTEST so even a future buggy preset
    # predicate can never write a money-capable tier from this endpoint —
    # arming the live-money path must always go through the explicit tier
    # control in PATCH /mcp/config, never a one-click preset.
    want = required_tier(selected)
    tier = want if _TIER_RANK.get(want, 99) <= _TIER_RANK["BACKTEST"] else "BACKTEST"
    try:
        await mgr.config_repo.update(
            {"enabled_tools": overrides, "enabled_groups": [], "capability_tier": tier},
            expected_row_version=body.expected_row_version,
        )
    except MCPConflictError as exc:
        raise HTTPException(409, detail=str(exc))
    return await registry(request)


@router.get("/mcp/audit")
async def audit_feed(request: Request, limit: int = 50) -> dict[str, Any]:
    mgr = _manager(request)
    from backend.mcp.repositories.audit_repo import AuditRepository

    repo = AuditRepository(mgr.config_repo._pool)  # noqa: SLF001
    rows = await repo.recent(limit=min(max(limit, 1), 200))
    return {"items": rows}


# --- proposals (human-apply money path) ---

def _proposal_repo(request: Request):
    mgr = _manager(request)
    from backend.mcp.repositories.proposal_repo import ProposalRepository

    return ProposalRepository(mgr.config_repo._pool), mgr  # noqa: SLF001


@router.get("/mcp/proposals")
async def list_proposals(request: Request, status: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    repo, _ = _proposal_repo(request)
    items = await repo.list(status=status, limit=min(max(limit, 1), 200))
    return {"items": items}


@router.get("/mcp/proposals/{proposal_id}")
async def get_proposal(request: Request, proposal_id: str) -> dict[str, Any]:
    repo, _ = _proposal_repo(request)
    prop = await repo.get(proposal_id)
    if prop is None:
        raise HTTPException(404, detail="proposal not found")
    return prop


@router.post("/mcp/proposals/{proposal_id}/approve")
async def approve_proposal_endpoint(request: Request, proposal_id: str) -> dict[str, Any]:
    repo, mgr = _proposal_repo(request)
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, detail="storage unavailable")
    from backend.mcp.tools.optimizer.proposal_service import (
        ProposalApplyError,
        approve_proposal,
    )

    try:
        summary = await approve_proposal(
            proposal_repo=repo, db=db, proposal_id=proposal_id, approver="operator",
        )
    except ProposalApplyError as exc:
        raise HTTPException(409, detail=str(exc))
    return {"applied": True, **summary}


@router.post("/mcp/proposals/{proposal_id}/reject")
async def reject_proposal_endpoint(request: Request, proposal_id: str) -> dict[str, Any]:
    repo, _ = _proposal_repo(request)
    try:
        await repo.transition(proposal_id, to_status="rejected", approver="operator")
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc))
    return {"rejected": True}


@router.post("/mcp/proposals/{proposal_id}/revert")
async def revert_proposal_endpoint(request: Request, proposal_id: str) -> dict[str, Any]:
    repo, _ = _proposal_repo(request)
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, detail="storage unavailable")
    from backend.mcp.tools.optimizer.proposal_service import (
        ProposalApplyError,
        revert_proposal,
    )

    try:
        summary = await revert_proposal(
            proposal_repo=repo, db=db, proposal_id=proposal_id, approver="operator",
        )
    except ProposalApplyError as exc:
        raise HTTPException(409, detail=str(exc))
    return summary
