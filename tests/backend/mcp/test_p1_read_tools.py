"""P1 read-tool registration + redaction contract tests."""
from __future__ import annotations

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.discovery import discover_tools

discover_tools()


class _Services:
    def __init__(self, db):
        self.db = db


class _DB:
    async def list_accounts(self):
        return [
            {"id": "acc1", "label": "Main", "account_type": "demo", "bybit_uid": "999",
             "api_key_masked": "ab***yz", "equity": 5000.0, "available_balance": 4000.0},
        ]

    async def get_account(self, account_id):
        return {"id": account_id, "label": "Main", "account_type": "demo",
                "bybit_uid": "999", "equity": 5000.0}

    async def list_scheduled_scans(self):
        return [{"id": "sch1", "name": "daily", "schedule_config": {"cron": "0 9 * * *"}}]

    async def list_strategies(self):
        return [{"id": "st1", "name": "momentum"}]


def _ctx(db):
    return CallContext(principal="t", session_id="s", tier="READ_ONLY",
                       correlation_id=None, services=_Services(db), clock=RealClock())


def test_p1_tools_registered():
    from backend.mcp.core.registry import _REGISTRY

    for name in ("scans_list", "scans_get", "accounts_list", "accounts_get",
                 "scheduled_list", "strategies_list"):
        assert name in _REGISTRY, f"{name} not registered"


@pytest.mark.asyncio
async def test_accounts_list_redacts_uid_and_money_by_default():
    from backend.mcp.core.registry import _REGISTRY

    spec = _REGISTRY["accounts_list"]
    result = await dispatch(spec, {"limit": 20}, _ctx(_DB()), audit=lambda r: None)
    assert result["isError"] is False
    acc = result["structuredContent"]["accounts"][0]
    assert "bybit_uid" not in acc  # opaque-id policy
    assert acc["equity"] == "redacted"  # money masked by default
    assert acc["available_balance"] == "redacted"
    # key-shaped fields are stripped (defense in depth), even when pre-masked
    assert "api_key_masked" not in acc
    assert acc["id"] == "acc1" and acc["label"] == "Main"


@pytest.mark.asyncio
async def test_accounts_list_financial_detail_optin():
    from backend.mcp.core.registry import _REGISTRY

    spec = _REGISTRY["accounts_list"]
    result = await dispatch(spec, {"limit": 20, "financial_detail": True}, _ctx(_DB()), audit=lambda r: None)
    acc = result["structuredContent"]["accounts"][0]
    assert acc["equity"] == 5000.0


@pytest.mark.asyncio
async def test_scheduled_and_strategies_list():
    from backend.mcp.core.registry import _REGISTRY

    r1 = await dispatch(_REGISTRY["scheduled_list"], {}, _ctx(_DB()), audit=lambda r: None)
    assert r1["structuredContent"]["count"] == 1
    r2 = await dispatch(_REGISTRY["strategies_list"], {}, _ctx(_DB()), audit=lambda r: None)
    assert r2["structuredContent"]["count"] == 1


@pytest.mark.asyncio
async def test_accounts_list_secret_key_stripped():
    """A row that accidentally carries an encrypted key must never surface it."""
    from backend.mcp.core.registry import _REGISTRY

    class _LeakyDB(_DB):
        async def list_accounts(self):
            return [{"id": "a", "api_secret_encrypted": "SECRET", "label": "L"}]

    spec = _REGISTRY["accounts_list"]
    result = await dispatch(spec, {"limit": 20}, _ctx(_LeakyDB()), audit=lambda r: None)
    acc = result["structuredContent"]["accounts"][0]
    assert "api_secret_encrypted" not in acc
    assert "SECRET" not in str(result["structuredContent"])
