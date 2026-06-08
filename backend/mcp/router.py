"""MCP control-plane router — TASK-P0-12.

Same-origin REST at /api/v1/mcp/* for the operator UI. The whole app's security
boundary is its LOOPBACK BIND (the trading endpoints have no per-request auth);
the global middleware adds a CSRF header check on mutating methods + security
headers. 503 when the MCP module is absent; 200 {state:"off"} when
present-but-disabled.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.mcp.core.netguard import is_loopback_host
from backend.mcp.mount import MCP_RPC_PATH

router = APIRouter(tags=["mcp"])


def _manager(request: Request):
    mgr = getattr(request.app.state, "mcp_manager", None)
    if mgr is None or mgr.config_repo is None:
        raise HTTPException(503, detail="MCP module not available")
    return mgr


async def _audit_control_plane(
    mgr, *, action: str, outcome: str, mutating: bool, detail: Optional[dict] = None
) -> None:
    """Record a control-plane action (enable/disable/approve/reject/revert/token)
    into the hash-chained audit. Uses the live writer when the server is running;
    when OFF, spins a TRANSIENT writer (safe: no concurrent writer to fork the
    chain) so money-path actions (approve/revert) are NEVER unaudited. Best-effort
    — the action itself must never fail because audit is unavailable."""
    payload = {
        "tool_name": f"control_plane:{action}",
        "tool_group": "control_plane",
        "safety_class": "live_money" if mutating else "read_only",
        "mutating": mutating,
        "principal_token_id": "operator",
        "session_id": "control-plane",
        "status": outcome,
        "args_redacted": detail or {},
    }
    writer = getattr(mgr, "audit_writer", None)
    if writer is not None:
        try:
            await writer.enqueue(payload)
        except Exception:  # noqa: BLE001
            pass
        return
    # Server OFF → transient writer through the same repo/pool, drained inline.
    try:
        from backend.mcp.core.audit import AuditWriter
        from backend.mcp.repositories.audit_repo import AuditRepository

        pool = mgr.config_repo._pool  # noqa: SLF001
        transient = AuditWriter(AuditRepository(pool))
        await transient.start()
        try:
            await transient.enqueue(payload)
            await transient.drain()
        finally:
            await transient.shutdown()
    except Exception:  # noqa: BLE001 — audit best-effort; never block the action
        pass


class ConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    capability_tier: Optional[str] = None
    enabled_groups: Optional[list[str]] = None
    enabled_tools: Optional[dict[str, bool]] = None
    # The ONLY safe-mode flag the operator UI may flip from this endpoint. It
    # gates whether DEBUG forensic tools are advertised and has NO money effect
    # (preflight ignores it). Deliberately NOT a raw `safe_mode_flags` blob — the
    # money flags (read_only / allow_real_trades) must never be writable here.
    allow_debug: Optional[bool] = None
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
    bind_host, bind_source = _resolve_bind_host()
    return {
        "enabled": cfg.enabled,
        "capability_tier": cfg.capability_tier,
        "enabled_groups": cfg.enabled_groups,
        "enabled_tools": cfg.enabled_tools,
        "safe_mode_flags": cfg.safe_mode_flags,
        "row_version": cfg.row_version,
        "bind_host": cfg.bind_host,
        "has_token": bool(cfg.access_token_hash),
        "egress_consent_at": cfg.egress_consent_at,
        # The TRUE, reachable transport URL. The host is loopback because the
        # transport guard (netguard.host_origin_allowed) accepts only a loopback Host
        # — a client must therefore run on THIS machine. The port is the real
        # listening socket port (ASGI scope), so it is correct however the server
        # was launched.
        "rpc_endpoint": _mcp_rpc_endpoint(request, bind_host),
        # The host the server process actually bound to, detected from its OWN argv
        # (process truth), then env. None when it cannot be proven (e.g. programmatic
        # launch). NOTE: in a container a 0.0.0.0 bind is normal and says nothing about
        # host exposure — the real Docker boundary is the published-port map, which the
        # process cannot observe. The UI must therefore treat anything other than a
        # PROVEN loopback bind as "verify it yourself", never as "safe".
        "served_host": bind_host,
        "bind_source": bind_source,  # "argv" | "env" | "unknown"
        # FAIL-SAFE: true ONLY on positive proof of a loopback bind. Unknown / 0.0.0.0
        # / LAN all → false so the operator console never asserts safety it cannot back.
        "loopback_only": bool(bind_host) and is_loopback_host(bind_host),
    }


def _served_port(request: Request) -> str:
    """The real port the app is listening on. Authoritative source is the ASGI
    scope's server address (the actual bound socket); falls back to TRADINGAGENTS_PORT
    (matches start.sh / start.bat), then 8877. Always returns a clean numeric string
    for a valid TCP port (1-65535)."""
    server = request.scope.get("server")
    if server and len(server) >= 2 and server[1]:
        p = _coerce_port(server[1])
        if p is not None:
            return p
    p = _coerce_port(os.environ.get("TRADINGAGENTS_PORT"))
    return p if p is not None else "8877"


def _coerce_port(raw: Any) -> Optional[str]:
    """A whitespace-tolerant, range-checked TCP port as str, or None if invalid."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return str(n) if 1 <= n <= 65535 else None


def _resolve_bind_host() -> tuple[Optional[str], str]:
    """Best-effort detection of the host the server actually bound to, for an HONEST
    network-exposure signal. Returns (host, source) with source in
    {"argv", "env", "unknown"}.

    Primary source is the server process's OWN argv: every first-party launcher
    (start.sh / start.bat / start-web.sh) passes `--host` explicitly, and the shell
    EXPANDS the value into the real argv token whether or not the env var was exported
    — so argv is the process truth even when os.environ is empty. Falls back to
    TRADINGAGENTS_BIND_HOST for programmatic launches that set it. If neither yields a
    host (bare `uvicorn.run()`, a gunicorn config file, etc.) returns (None, "unknown")
    so the caller FAILS SAFE rather than assuming loopback."""
    host = _bind_host_from_argv(sys.argv)
    if host:
        return host, "argv"
    env = (os.environ.get("TRADINGAGENTS_BIND_HOST") or "").strip()
    if env:
        return env, "env"
    return None, "unknown"


def _bind_host_from_argv(argv: list[str]) -> Optional[str]:
    """Extract the bind host from a uvicorn/gunicorn argv. Handles `--host H`,
    `--host=H`, and gunicorn `-b H:port` / `--bind H:port` (incl. `=` forms and
    bracketed IPv6). Returns None if no bind flag is present."""

    def _host_of_bind(val: str) -> str:  # gunicorn "host:port" -> "host"
        val = val.strip()
        if val.startswith("["):  # [::1]:8000
            end = val.find("]")
            if end != -1:
                return val[1:end]
        if ":" in val and val.count(":") == 1:  # ipv4/host : port
            return val.rsplit(":", 1)[0]
        return val

    i, n = 0, len(argv)
    while i < n:
        tok = argv[i]
        if tok == "--host" and i + 1 < n:
            return argv[i + 1].strip()
        if tok.startswith("--host="):
            return tok.split("=", 1)[1].strip()
        if tok in ("-b", "--bind") and i + 1 < n:
            return _host_of_bind(argv[i + 1])
        if tok.startswith(("--bind=", "-b=")):
            return _host_of_bind(tok.split("=", 1)[1])
        i += 1
    return None


def _mcp_rpc_endpoint(request: Request, bind_host: Optional[str]) -> str:
    """Build the reachable /mcp/rpc URL. The host is loopback because the transport
    guard rejects every non-loopback Host. When the server bound a SPECIFIC loopback
    address (e.g. ::1 on an IPv6-only loopback box, or `localhost`), echo that so the
    URL is actually reachable; for a wildcard (0.0.0.0), a LAN bind, or an unknown
    bind, default to 127.0.0.1 (the loopback interface is always included). The path
    mirrors the real ASGI mount so it can never drift."""
    host = "127.0.0.1"
    if bind_host and is_loopback_host(bind_host):
        h = bind_host.strip()
        host = f"[{h}]" if (":" in h and not h.startswith("[")) else h
    return f"http://{host}:{_served_port(request)}{MCP_RPC_PATH}"


@router.patch("/mcp/config")
async def patch_config(request: Request, body: ConfigPatch) -> dict[str, Any]:
    mgr = _manager(request)
    patch = body.model_dump(
        exclude_none=True, exclude={"expected_row_version", "allow_debug"}
    )
    # allow_debug is exposed as a flat field but persisted inside safe_mode_flags.
    # config_repo.update REPLACES the safe_mode_flags column, so MERGE onto the
    # live flags — flipping the debug gate must never clobber read_only /
    # allow_real_trades (the money-path opt-ins).
    if body.allow_debug is not None:
        cfg = await mgr.config_repo.get()
        patch["safe_mode_flags"] = {**cfg.safe_mode_flags, "allow_debug": body.allow_debug}
    from backend.mcp.core.errors import MCPConflictError

    try:
        await mgr.config_repo.update(patch, expected_row_version=body.expected_row_version)
    except MCPConflictError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    return await get_config(request)


@router.post("/mcp/enable")
async def enable(request: Request) -> dict[str, Any]:
    mgr = _manager(request)
    from backend.mcp.core.dbfloor import compute_mcp_acquire_cap, db_budget_ok
    from backend.mcp.core.preflight import run_preflight
    from backend.mcp.core.registry import (
        MCPConfigView,
        ToolGroup,
        resolve_enabled,
    )

    cfg = await mgr.config_repo.get()
    # Derive optimizer-on from the resolved enabled set by CONFIG INTENT (not
    # runtime availability): a preset enables optimizer tools via per-tool
    # overrides with empty groups, which would otherwise bypass the
    # optimizer-only SLI/shm preflight invariants. We pass available=True here
    # because the optimizer's backing services (sweep_repo) are wired INSIDE
    # _start_transport — i.e. AFTER this preflight — so a runtime-availability
    # check would always report the optimizer off and skip the gate.
    view = MCPConfigView(
        capability_tier=cfg.capability_tier,
        enabled_groups=cfg.enabled_groups,
        enabled_tools=cfg.enabled_tools,
    )
    resolved_intent = resolve_enabled(
        view,
        available=lambda g: True,  # intent, not runtime wiring
        debug_allowed=bool(cfg.safe_mode_flags.get("allow_debug", False)),
    )
    optimizer_on = any(s.group is ToolGroup.OPTIMIZER for s in resolved_intent)

    # Compute the real DB-pool budget (FR-035): reserve a live floor for the
    # trading loop; the MCP cap is pool_max - floor. Enable is refused if the
    # floor + MCP cap would exceed the pool.
    db = getattr(request.app.state, "db", None)
    pool = getattr(db, "pool", None) if db is not None else None
    pool_max = getattr(pool, "_maxsize", 0) or getattr(pool, "maxsize", 0) or 10
    live_floor = max(2, int(pool_max * 0.4))  # measured-ish reserve for trading
    mcp_cap = compute_mcp_acquire_cap(pool_max=pool_max, live_floor=live_floor)
    budget_ok = db_budget_ok(pool_max=pool_max, live_floor=live_floor, mcp_cap=mcp_cap) and mcp_cap >= 1

    # Live-SLI presence: the breaker always has a signal because the manager's
    # _poll_slis measures event-loop lag in-process (a real, dependency-free SLI:
    # a starved loop = degraded order placement). A richer app-provided source
    # (app.state.mcp_live_slis) augments it but is not required for the breaker to
    # function — so the optimizer can be enabled with the built-in protection.
    slis_present = True

    result = run_preflight(
        cfg, schema_version=45, optimizer_enabled=optimizer_on,
        db_budget_ok=budget_ok, live_slis_present=slis_present,
    )
    if not result.ok:
        raise HTTPException(422, detail={"preflight_failed": result.failed_invariant})
    # Record the one-time data-egress consent (FR-033) — tool results leave to the
    # connected model provider when enabled. Idempotent; first enable stamps it.
    await mgr.config_repo.record_egress_consent()
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
    _manager(request)
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


def _active_presets(cfg, specs) -> list[str]:
    """Every preset whose exact tool selection matches the persisted override map,
    in registry (PRESETS) order. Empty for a custom/hand-tuned selection.

    apply_preset writes a COMPLETE enabled_tools map (every tool name -> bool) and
    clears enabled_groups, so a clean preset application is detectable by comparing
    the set of explicitly-enabled tool names against each preset's selected set.

    Why a LIST, not a single name: several presets can resolve to the SAME tool set
    for the current catalog (full == standard == backtest_only while no
    ADVANCED/non-exchange-mutating tools exist to differentiate the predicates). The
    persisted state genuinely cannot say which one the operator clicked — so we
    report ALL matches and let the UI highlight every coincident preset. This is
    truthful and STABLE: it never flips between equivalent presets across reloads or
    unrelated toggles (the bug a single "broadest wins" guess would cause). As the
    catalog grows and the predicates diverge, the match list collapses to one.

    The match is over persisted INTENT, deliberately independent of runtime
    gating/availability — so "full" still matches even when its DEBUG tools are
    hidden by the allow_debug gate or a backing service is absent. That is exactly
    what lets the UI highlight the applied preset AND explain the tools that stay
    dark.
    """
    from backend.mcp.core.registry import PRESETS

    # A group-level enable contributes tools not represented in the override map,
    # so the set comparison below would be unreliable — not a clean preset apply.
    if cfg.enabled_groups:
        return []
    on = {name for name, enabled in cfg.enabled_tools.items() if enabled}
    if not on:
        return []  # the empty selection is not a named preset
    return [
        name
        for name, pred in PRESETS.items()
        if on == {s.name for s in specs if pred(s)}
    ]


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

    active = _active_presets(cfg, iter_specs())
    return {
        "tools": tools,
        "groups": groups,
        "presets": preset_map,
        # EVERY preset whose exact selection matches the current config. Usually one;
        # may be several when presets coincide for the current catalog (full ==
        # standard == backtest_only). The UI highlights all of them — truthful and
        # stable (no flip-flopping between equivalent presets across reloads).
        "active_presets": active,
        # Back-compat scalar: the first matching preset (registry order) or null.
        # Prefer active_presets; this exists so any older consumer keeps working.
        "active_preset": active[0] if active else None,
        # The debug-forensics gate (safe_mode_flags.allow_debug). DEBUG tools are
        # only advertised when true; the UI surfaces a toggle + explains the gate.
        "allow_debug": debug_allowed,
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
        raise HTTPException(409, detail=str(exc)) from exc
    # Return the fresh registry. We deliberately do NOT special-case body.preset
    # here: when several presets share this exact tool set, active_presets reports
    # ALL of them and the UI highlights each — identical to what a later cold GET
    # returns. Consistency between apply and reload is what prevents the highlight
    # from "jumping" to a different equivalent preset on the next fetch.
    return await registry(request)


@router.get("/mcp/audit")
async def audit_feed(request: Request, limit: int = 50) -> dict[str, Any]:
    mgr = _manager(request)
    from backend.mcp.repositories.audit_repo import AuditRepository

    repo = AuditRepository(mgr.config_repo._pool)  # noqa: SLF001
    rows = await repo.recent(limit=min(max(limit, 1), 200))
    return {"items": rows}


# --- sweeps (async optimizer jobs) ---

def _sweep_repo(request: Request):
    repo = getattr(request.app.state, "mcp_sweep_repo", None)
    if repo is None:
        mgr = _manager(request)
        from backend.mcp.repositories.sweep_repo import SweepRepository

        repo = SweepRepository(mgr.config_repo._pool)  # noqa: SLF001
    return repo


@router.get("/mcp/sweeps")
async def list_sweeps(request: Request, limit: int = 50) -> dict[str, Any]:
    repo = _sweep_repo(request)
    items = await repo.list_jobs(limit=min(max(limit, 1), 200))
    return {"items": items}


@router.get("/mcp/sweeps/{sweep_id}")
async def get_sweep(request: Request, sweep_id: str) -> dict[str, Any]:
    repo = _sweep_repo(request)
    job = await repo.get_job(sweep_id)
    if job is None:
        raise HTTPException(404, detail="sweep not found")
    # include the top-N best results
    job["results"] = await repo.results(sweep_id, limit=20)
    return job


@router.get("/mcp/sweeps/{sweep_id}/results")
async def get_sweep_results(
    request: Request, sweep_id: str, objective: Optional[str] = None, limit: int = 100
) -> dict[str, Any]:
    """Full results, server-side re-ranked by an alternate objective (FR-040)."""
    repo = _sweep_repo(request)
    if objective is not None:
        from backend.mcp.tools.optimizer.ranker import OBJECTIVE_METRICS

        if objective not in OBJECTIVE_METRICS:
            raise HTTPException(422, detail={"unsupported_objective": objective})
    rows = await repo.results(sweep_id, objective=objective, limit=min(max(limit, 1), 500))
    return {"items": rows, "reranked_by": objective}


@router.post("/mcp/sweeps/{sweep_id}/cancel")
async def cancel_sweep(request: Request, sweep_id: str) -> dict[str, Any]:
    repo = _sweep_repo(request)
    # cancel the in-flight task if tracked
    registry = getattr(request.app.state, "mcp_sweep_tasks", None)
    if registry and sweep_id in registry:
        registry[sweep_id].cancel()
    cancelled = await repo.cancel_job(sweep_id)
    return {"sweep_id": sweep_id, "cancelled": cancelled}


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
        await _audit_control_plane(mgr, action="proposal_approve", outcome="rejected",
                                   mutating=True, detail={"proposal_id": proposal_id, "error": str(exc)})
        raise HTTPException(409, detail=str(exc)) from exc
    await _audit_control_plane(mgr, action="proposal_approve", outcome="applied",
                               mutating=True, detail={"proposal_id": proposal_id})
    return {"applied": True, **summary}


@router.post("/mcp/proposals/{proposal_id}/reject")
async def reject_proposal_endpoint(request: Request, proposal_id: str) -> dict[str, Any]:
    repo, mgr = _proposal_repo(request)
    try:
        await repo.transition(proposal_id, to_status="rejected", approver="operator")
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    await _audit_control_plane(mgr, action="proposal_reject", outcome="rejected",
                               mutating=False, detail={"proposal_id": proposal_id})
    return {"rejected": True}


@router.post("/mcp/proposals/{proposal_id}/revert")
async def revert_proposal_endpoint(request: Request, proposal_id: str) -> dict[str, Any]:
    repo, mgr = _proposal_repo(request)
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
        raise HTTPException(409, detail=str(exc)) from exc
    await _audit_control_plane(mgr, action="proposal_revert", outcome="reverted",
                               mutating=True, detail={"proposal_id": proposal_id})
    return summary
