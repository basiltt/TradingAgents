"""Tests for AccountWSManager wallet listener registration."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from backend.services.account_ws_manager import AccountWSManager


@pytest.fixture()
def ws_manager():
    db = AsyncMock()
    db.list_accounts = AsyncMock(return_value=[])
    mgr = AccountWSManager(db=db)
    return mgr


@pytest.mark.asyncio
async def test_register_wallet_listener_receives_events(ws_manager):
    received = []

    async def listener(account_id: str, wallet_data: dict):
        received.append((account_id, wallet_data))

    ws_manager.register_wallet_listener(listener)

    wallet_data = {"totalEquity": "1000", "totalWalletBalance": "950", "totalPerpUPL": "50"}
    await ws_manager._notify_wallet_listeners("acc_123", wallet_data)

    assert len(received) == 1
    assert received[0] == ("acc_123", wallet_data)


@pytest.mark.asyncio
async def test_multiple_listeners(ws_manager):
    calls_a = []
    calls_b = []

    async def listener_a(account_id, data):
        calls_a.append(account_id)

    async def listener_b(account_id, data):
        calls_b.append(account_id)

    ws_manager.register_wallet_listener(listener_a)
    ws_manager.register_wallet_listener(listener_b)

    await ws_manager._notify_wallet_listeners("x", {"totalEquity": "1"})
    assert len(calls_a) == 1
    assert len(calls_b) == 1


@pytest.mark.asyncio
async def test_listener_exception_does_not_crash(ws_manager):
    async def bad_listener(account_id, data):
        raise RuntimeError("boom")

    good_calls = []

    async def good_listener(account_id, data):
        good_calls.append(account_id)

    ws_manager.register_wallet_listener(bad_listener)
    ws_manager.register_wallet_listener(good_listener)

    await ws_manager._notify_wallet_listeners("acc", {"totalEquity": "1"})
    assert len(good_calls) == 1
