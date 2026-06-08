"""Active-preset reporting + allow_debug gate — operator-console bug fixes.

Covers two reported defects in the Tool budget UI:

1. Applying a preset gave no indication which preset was active. The registry
   endpoint now returns `active_preset` (the preset whose exact selection is
   persisted, or null for a custom selection) so the UI can highlight it.

2. The "Full (no live money)" preset left a few tools off with no explanation.
   Two distinct causes, both asserted here:
     - exchange-facing tools (cache_warmup) are excluded by design and must
       never be selected by a preset;
     - DEBUG forensic tools are gated behind safe_mode_flags.allow_debug and
       stay dark until the operator flips that gate. The gate is now flippable
       via PATCH /mcp/config {allow_debug}, merged so the money-path flags are
       preserved.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def app_with_mcp(mcp_pool):
    from fastapi import FastAPI

    from backend.mcp.mount import MCPManager, register_mcp

    class _DB:
        def __init__(self, pool):
            self.pool = pool

        async def list_scans(self):
            return []

    app = FastAPI()
    app.state.db = _DB(mcp_pool)
    # backing services so backtest/optimizer/debug tools resolve as available
    app.state.backtest_service = object()
    app.state.mcp_backtest_runner = object()
    app.state.accounts_service = object()
    app.state.trade_repo = object()
    app.state.mcp_sweep_repo = object()
    app.state.debug_trace_recorder = object()
    register_mcp(app)
    mgr = MCPManager(app)
    app.state.mcp_manager = mgr
    await mgr.boot()
    yield app, mgr
    await mgr.shutdown()


async def _apply(client, preset: str, row_version: int):
    return await client.post(
        "/api/v1/mcp/registry/preset",
        json={"preset": preset, "expected_row_version": row_version},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_active_preset_null_before_any_preset(app_with_mcp):
    """A fresh config (nothing enabled) is not any named preset."""
    app, _ = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/api/v1/mcp/registry")).json()
    assert body["active_presets"] == []
    assert body["active_preset"] is None  # back-compat scalar
    assert "allow_debug" in body and body["allow_debug"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_reports_active_preset_after_apply(app_with_mcp):
    """Applying a preset makes the registry report it as active (Issue 1).

    'full' currently coincides with 'standard' and 'backtest_only' (identical tool
    set for this catalog), so ALL of them are reported active — and 'full' is among
    them. The UI highlights every coincident preset rather than guessing one."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg = await mgr.config_repo.get()
        body = (await _apply(client, "full", cfg.row_version)).json()
    assert "full" in body["active_presets"]
    # back-compat scalar is the first match (registry order), never null here
    assert body["active_preset"] in body["active_presets"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_active_preset_clears_to_empty_on_custom_toggle(app_with_mcp):
    """Hand-toggling a tool off after a preset makes the selection custom (empty)."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg = await mgr.config_repo.get()
        applied = (await _apply(client, "full", cfg.row_version)).json()
        assert "full" in applied["active_presets"]
        # turn one enabled tool off → no longer matches any preset's exact set
        on_tool = next(t["name"] for t in applied["tools"] if t["enabled"])
        overrides = {t["name"]: t["enabled"] for t in applied["tools"]}
        overrides[on_tool] = False
        cfg2 = await mgr.config_repo.get()
        rp = await client.patch(
            "/api/v1/mcp/config",
            json={"enabled_tools": overrides, "expected_row_version": cfg2.row_version},
        )
        assert rp.status_code == 200
        body = (await client.get("/api/v1/mcp/registry")).json()
    assert body["active_presets"] == []
    assert body["active_preset"] is None


def _by_name(body):
    return {t["name"]: t for t in body["tools"]}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_preset_leaves_debug_tools_dark_until_gate_opens(app_with_mcp):
    """Reproduces the report: after 'Full', the 2 debug tools are NOT advertised
    because allow_debug is off — even though the preset intends them. Flipping the
    gate via PATCH lights them up WITHOUT re-applying the preset."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg = await mgr.config_repo.get()
        applied = (await _apply(client, "full", cfg.row_version)).json()

        # the preset's INTENT includes the debug tools...
        full_intent = set(applied["presets"]["full"])
        assert {"debug_scan_trace", "debug_symbol_decisions"} <= full_intent

        # ...but they resolve as NOT enabled while the gate is closed.
        tools = _by_name(applied)
        assert applied["allow_debug"] is False
        assert tools["debug_scan_trace"]["enabled"] is False
        assert tools["debug_symbol_decisions"]["enabled"] is False
        # active preset still includes 'full' — the gate doesn't change the intent.
        assert "full" in applied["active_presets"]

        # open the gate (no re-apply of the preset)
        cfg2 = await mgr.config_repo.get()
        rp = await client.patch(
            "/api/v1/mcp/config",
            json={"allow_debug": True, "expected_row_version": cfg2.row_version},
        )
        assert rp.status_code == 200

        after = (await client.get("/api/v1/mcp/registry")).json()
        tools2 = _by_name(after)
    assert after["allow_debug"] is True
    assert tools2["debug_scan_trace"]["enabled"] is True
    assert tools2["debug_symbol_decisions"]["enabled"] is True
    # still recognized as the 'full' preset after the gate opens
    assert "full" in after["active_presets"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_preset_never_selects_exchange_facing_cache_warmup(app_with_mcp):
    """cache_warmup is exchange-facing and must stay off under 'Full' by design,
    independent of the debug gate (Issue 2b: excluded, not a bug)."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg = await mgr.config_repo.get()
        applied = (await _apply(client, "full", cfg.row_version)).json()
        # open the debug gate too, to prove cache_warmup stays off regardless
        cfg2 = await mgr.config_repo.get()
        await client.patch(
            "/api/v1/mcp/config",
            json={"allow_debug": True, "expected_row_version": cfg2.row_version},
        )
        after = (await client.get("/api/v1/mcp/registry")).json()
    assert "cache_warmup" not in set(after["presets"]["full"])
    assert _by_name(after)["cache_warmup"]["enabled"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_allow_debug_patch_preserves_money_flags(app_with_mcp):
    """Flipping allow_debug must MERGE — never clobber read_only / allow_real_trades
    (the money-path opt-ins live in the same safe_mode_flags blob)."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = await mgr.config_repo.get()
        # sanity: defaults from the schema
        assert before.safe_mode_flags.get("read_only") is True
        assert before.safe_mode_flags.get("allow_real_trades") is False

        rp = await client.patch(
            "/api/v1/mcp/config",
            json={"allow_debug": True, "expected_row_version": before.row_version},
        )
        assert rp.status_code == 200

    after = await mgr.config_repo.get()
    assert after.safe_mode_flags.get("allow_debug") is True
    # the money flags survived the merge untouched
    assert after.safe_mode_flags.get("read_only") is True
    assert after.safe_mode_flags.get("allow_real_trades") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coincident_presets_all_reported_and_stable(app_with_mcp):
    """When several presets share one tool set (full == standard == backtest_only
    for the current catalog), ALL are reported active — and the set is STABLE: it
    does not change between the apply response, a cold GET, and after an unrelated
    toggle (opening the debug gate). This is the anti-jump guard: an earlier design
    that guessed ONE preset would flip the highlight between equivalent presets."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg = await mgr.config_repo.get()
        # apply the NARROW preset; the response already lists every coincident match
        applied = (await _apply(client, "backtest_only", cfg.row_version)).json()
        on_apply = set(applied["active_presets"])
        assert on_apply == {"backtest_only", "standard", "full"}

        # cold GET (page reload): identical set — no flip to a single "winner"
        reloaded = set((await client.get("/api/v1/mcp/registry")).json()["active_presets"])
        assert reloaded == on_apply

        # an unrelated change (open the debug gate) must not perturb the set
        cfg2 = await mgr.config_repo.get()
        await client.patch(
            "/api/v1/mcp/config",
            json={"allow_debug": True, "expected_row_version": cfg2.row_version},
        )
        after_gate = set((await client.get("/api/v1/mcp/registry")).json()["active_presets"])
    assert after_gate == on_apply


@pytest.mark.integration
@pytest.mark.asyncio
async def test_minimal_preset_is_distinct_and_singular(app_with_mcp):
    """A preset with a genuinely unique tool set (minimal: 17 tools, narrower than
    the 30-tool cluster) reports exactly itself — proving the multi-match is real
    coincidence, not a blanket 'everything matches'."""
    app, mgr = app_with_mcp
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cfg = await mgr.config_repo.get()
        applied = (await _apply(client, "minimal", cfg.row_version)).json()
    assert applied["active_presets"] == ["minimal"]
    assert applied["active_preset"] == "minimal"
