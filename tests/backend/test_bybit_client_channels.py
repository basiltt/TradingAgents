"""Tests for bybit_client endpoint channel routing through the rate gate (TASK-0.5)."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.bybit_client import BybitClient
from backend.services import post_scan_flags as flags


class _Recorder:
    """Captures acquire_async kwargs."""
    def __init__(self):
        self.calls = []

    async def acquire_async(self, channel="public", *, lane="live", account_key=None, endpoint_class=None):
        self.calls.append({"channel": channel, "lane": lane, "account_key": account_key, "endpoint_class": endpoint_class})


@pytest.fixture(autouse=True)
def _reset_flags():
    flags.reset_for_tests()
    yield
    flags.reset_for_tests()


@pytest.mark.asyncio
async def test_wait_for_rate_limit_routes_public_for_market_read():
    rec = _Recorder()
    client = BybitClient("k", "s", "demo", account_id="acct-1")
    with patch("backend.services.bybit_client.get_rate_gate", return_value=rec):
        await client._wait_for_rate_limit("/v5/market/tickers", lane="live")
    assert rec.calls[0]["channel"] == "public"
    assert rec.calls[0]["endpoint_class"] == "market"


@pytest.mark.asyncio
async def test_wait_for_rate_limit_routes_private_for_order_create():
    rec = _Recorder()
    client = BybitClient("k", "s", "demo", account_id="acct-1")
    with patch("backend.services.bybit_client.get_rate_gate", return_value=rec):
        await client._wait_for_rate_limit("/v5/order/create", lane="order")
    call = rec.calls[0]
    assert call["channel"] == "private"
    assert call["endpoint_class"] == "order_create"
    assert call["account_key"] == "acct-1"
    assert call["lane"] == "order"


@pytest.mark.asyncio
async def test_revert_switch_forces_all_private():
    """When the channel-fix revert is on, everything goes private with no sub-limiter."""
    rec = _Recorder()
    flags.apply_snapshot({"rate_gate_channel_fix": True})
    client = BybitClient("k", "s", "demo", account_id="acct-1")
    with patch("backend.services.bybit_client.get_rate_gate", return_value=rec):
        await client._wait_for_rate_limit("/v5/market/tickers", lane="live")
    call = rec.calls[0]
    assert call["channel"] == "private"
    assert call["account_key"] is None
    assert call["endpoint_class"] is None


@pytest.mark.asyncio
async def test_per_endpoint_limiter_revert_drops_account_key():
    """Channel fix active but per-endpoint limiter reverted => channel routed, no account dim."""
    rec = _Recorder()
    flags.apply_snapshot({"rate_gate_per_endpoint_limiter": True})
    client = BybitClient("k", "s", "demo", account_id="acct-1")
    with patch("backend.services.bybit_client.get_rate_gate", return_value=rec):
        await client._wait_for_rate_limit("/v5/order/create", lane="order")
    call = rec.calls[0]
    assert call["channel"] == "private"        # channel fix still active
    assert call["account_key"] is None          # sub-limiter reverted
    assert call["endpoint_class"] is None
