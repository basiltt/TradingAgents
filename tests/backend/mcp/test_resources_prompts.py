"""Resources + prompts tests — TASK-P1-10/11."""
from __future__ import annotations

import pytest

from backend.mcp.resources.catalog import (
    PromptProvider,
    ResourceProvider,
    get_prompt,
    read_resource,
)


class _Services:
    class _DB:
        async def list_scans(self):
            return [{"scan_id": "s1", "status": "completed"}]

        async def list_scheduled_scans(self):
            return [{"id": "x"}]

    db = _DB()


@pytest.mark.asyncio
async def test_read_server_info():
    out = await read_resource("tradingagents://server/info", _Services(), server_version="1.2.3")
    assert out["name"] == "tradingagents-mcp"
    assert out["version"] == "1.2.3"


@pytest.mark.asyncio
async def test_read_latest_scan():
    out = await read_resource("tradingagents://scan/latest", _Services())
    assert out["scan"]["scan_id"] == "s1"


@pytest.mark.asyncio
async def test_unknown_resource_rejected():
    with pytest.raises(ValueError):
        await read_resource("tradingagents://evil/../etc", _Services())


def test_resource_provider_lists():
    rp = ResourceProvider()
    uris = {r["uri"] for r in rp.resources}
    assert "tradingagents://server/info" in uris


def test_prompt_get_renders_and_escapes_argument():
    out = get_prompt("optimize_my_config", {"objective": "sharpe;<script>"})
    text = out["messages"][0]["content"]["text"]
    # the injected argument is rendered sanitized as "(sharpescript)"
    assert "(sharpescript)" in text
    # the dangerous characters from the argument never survive
    assert "sharpe;" not in text
    assert "<script>" not in text


def test_prompt_unknown_rejected():
    with pytest.raises(ValueError):
        get_prompt("nonexistent")


def test_prompt_provider_lists():
    pp = PromptProvider()
    names = {p["name"] for p in pp.list()}
    assert "optimize_my_config" in names
    assert "audit_last_scan" in names
