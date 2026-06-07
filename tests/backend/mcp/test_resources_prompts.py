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

        async def get_scan(self, scan_id):
            return {"scan_id": scan_id, "status": "completed", "api_secret": "STRIP_ME"}

        async def get_portfolio_pnl_summary(self, start, end, account_type=None):
            return {"total_pnl": "500", "win_rate": 0.6}

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
async def test_read_portfolio_snapshot():
    out = await read_resource("tradingagents://portfolio/snapshot", _Services())
    assert out["window_days"] == 30
    assert out["summary"] is not None


@pytest.mark.asyncio
async def test_read_scan_template_by_id_strips_secrets():
    import json

    out = await read_resource("tradingagents://scan/abc-123", _Services())
    assert out["scan"]["scan_id"] == "abc-123"
    assert "STRIP_ME" not in json.dumps(out)  # secret never reaches the agent


@pytest.mark.asyncio
async def test_scan_template_rejects_traversal():
    with pytest.raises(ValueError):
        await read_resource("tradingagents://scan/../../etc/passwd", _Services())


@pytest.mark.asyncio
async def test_unknown_resource_rejected():
    with pytest.raises(ValueError):
        await read_resource("tradingagents://evil/nope", _Services())


def test_resource_provider_lists_and_templates():
    rp = ResourceProvider()
    uris = {r["uri"] for r in rp.resources}
    assert "tradingagents://server/info" in uris
    assert "tradingagents://portfolio/snapshot" in uris
    templates = {t["uriTemplate"] for t in rp.templates}
    assert "tradingagents://scan/{scan_id}" in templates


def test_prompt_get_renders_and_escapes_argument():
    out = get_prompt("optimize_my_config", {"objective": "sharpe;<script>"})
    text = out["messages"][0]["content"]["text"]
    # the injected argument is rendered sanitized as "(sharpescript)"
    assert "(sharpescript)" in text
    # the dangerous characters from the argument never survive
    assert "sharpe;" not in text
    assert "<script>" not in text


def test_explain_trade_close_prompt_escapes_args():
    out = get_prompt("explain_trade_close", {"account_id": "acc-1", "trade_id": "t1;<x>"})
    text = out["messages"][0]["content"]["text"]
    # the sanitized args appear; the raw injected token does not
    assert "acc-1" in text and "t1x" in text
    assert "t1;<x>" not in text and "<x>" not in text


def test_prompt_unknown_rejected():
    with pytest.raises(ValueError):
        get_prompt("nonexistent")


def test_prompt_provider_lists():
    pp = PromptProvider()
    names = {p["name"] for p in pp.list()}
    assert "optimize_my_config" in names
    assert "audit_last_scan" in names
    assert "explain_trade_close" in names
