"""Unit tests for AccountWSManager — covers start, stop, subscribe, broadcast."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.account_ws_manager import AccountWSManager


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def mgr(db):
    return AccountWSManager(db=db)


class TestStartShutdown:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_creates_clients_for_active_accounts(self, mgr, db):
        db.list_accounts = AsyncMock(return_value=[
            {"id": "acc1", "is_active": True},
            {"id": "acc2", "is_active": False},
        ])
        db.get_account_credentials = AsyncMock(return_value=None)
        await mgr.start()
        db.get_account_credentials.assert_awaited_once_with("acc1")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_skips_missing_creds(self, mgr, db):
        db.list_accounts = AsyncMock(return_value=[{"id": "acc1", "is_active": True}])
        db.get_account_credentials = AsyncMock(return_value=None)
        await mgr.start()
        assert "acc1" not in mgr._clients

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_clears_clients(self, mgr):
        mock_client = AsyncMock()
        mgr._clients["acc1"] = mock_client
        await mgr.shutdown()
        mock_client.stop.assert_awaited_once()
        assert len(mgr._clients) == 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_shutdown_handles_stop_error(self, mgr):
        mock_client = AsyncMock()
        mock_client.stop.side_effect = Exception("ws error")
        mgr._clients["acc1"] = mock_client
        await mgr.shutdown()
        assert len(mgr._clients) == 0


class TestStartStopAccount:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_account_skips_existing(self, mgr, db):
        mgr._clients["acc1"] = MagicMock()
        await mgr.start_account("acc1")
        db.get_account_credentials.assert_not_awaited()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stop_account_removes_client(self, mgr):
        mock_client = AsyncMock()
        mgr._clients["acc1"] = mock_client
        await mgr.stop_account("acc1")
        assert "acc1" not in mgr._clients
        mock_client.stop.assert_awaited_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stop_account_noop_missing(self, mgr):
        await mgr.stop_account("missing")


class TestSubscribeUnsubscribe:
    def test_subscribe_returns_queue(self, mgr):
        q = mgr.subscribe()
        assert isinstance(q, asyncio.Queue)
        assert q in mgr._frontend_queues

    def test_unsubscribe_removes_queue(self, mgr):
        q = mgr.subscribe()
        mgr.unsubscribe(q)
        assert q not in mgr._frontend_queues

    def test_unsubscribe_idempotent(self, mgr):
        q = asyncio.Queue()
        mgr.unsubscribe(q)


class TestBroadcast:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_broadcast_sends_to_subscribers(self, mgr):
        q = mgr.subscribe()
        await mgr.broadcast_event({"type": "test"})
        event = q.get_nowait()
        assert event["type"] == "test"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_broadcast_drops_when_full(self, mgr):
        q = asyncio.Queue(maxsize=1)
        mgr._frontend_queues.add(q)
        q.put_nowait({"type": "old"})
        await mgr._broadcast({"type": "new"})
        items = []
        while not q.empty():
            items.append(q.get_nowait())
        types = [i["type"] for i in items]
        assert "new" in types

    @pytest.mark.asyncio(loop_scope="function")
    async def test_broadcast_to_account(self, mgr):
        q = mgr.subscribe()
        await mgr.broadcast_to_account("acc1", "wallet_update", {"balance": 100})
        event = q.get_nowait()
        assert event["type"] == "wallet_update"
        assert event["account_id"] == "acc1"
        assert event["balance"] == 100


class TestDecryptFailure:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_start_account_decrypt_error_logged(self, mgr, db):
        db.get_account_credentials = AsyncMock(return_value={
            "api_key_encrypted": "bad", "api_secret_encrypted": "bad", "account_type": "demo",
        })
        with patch("backend.services.account_ws_manager.decrypt_value", side_effect=Exception("decrypt fail")):
            await mgr._start_account("acc1")
        assert "acc1" not in mgr._clients
