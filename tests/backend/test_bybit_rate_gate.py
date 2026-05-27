"""Tests for process-wide Bybit IP-level rate gate."""
import asyncio
import threading
import time

import pytest

from backend.services.bybit_rate_gate import BybitRateGate, get_rate_gate


class TestBybitRateGate:
    def setup_method(self):
        self.gate = BybitRateGate(public_budget=5, private_budget=3, window=1.0)

    @pytest.mark.asyncio
    async def test_acquire_async_within_budget(self):
        """Should acquire immediately when within budget."""
        for _ in range(5):
            await self.gate.acquire_async(channel="public")
        assert self.gate.current_usage["public"] == 5

    @pytest.mark.asyncio
    async def test_acquire_async_blocks_when_full(self):
        """Should block when budget exhausted, resume after window expires."""
        for _ in range(5):
            await self.gate.acquire_async(channel="public")

        start = time.monotonic()
        await self.gate.acquire_async(channel="public")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.9  # waited ~1s for window to expire

    @pytest.mark.asyncio
    async def test_private_channel_independent(self):
        """Private and public budgets are independent."""
        for _ in range(5):
            await self.gate.acquire_async(channel="public")
        # Public full, but private should still work
        await self.gate.acquire_async(channel="private")
        assert self.gate.current_usage["private"] == 1

    def test_acquire_sync_within_budget(self):
        """Sync acquire should work within budget."""
        for _ in range(5):
            assert self.gate.acquire_sync(channel="public") is True
        assert self.gate.current_usage["public"] == 5

    def test_acquire_sync_timeout(self):
        """Sync acquire should return False on timeout."""
        for _ in range(5):
            self.gate.acquire_sync(channel="public")
        result = self.gate.acquire_sync(channel="public", timeout=0.2)
        assert result is False

    def test_thread_safety(self):
        """Multiple threads acquiring concurrently should not exceed budget."""
        gate = BybitRateGate(public_budget=50, private_budget=10, window=5.0)
        acquired = []

        def worker():
            if gate.acquire_sync(channel="public", timeout=1.0):
                acquired.append(1)

        threads = [threading.Thread(target=worker) for _ in range(60)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(acquired) == 50  # exactly budget

    @pytest.mark.asyncio
    async def test_wait_count_tracking(self):
        """wait_count should reflect waiting callers."""
        for _ in range(5):
            await self.gate.acquire_async(channel="public")
        # Next acquire will wait
        task = asyncio.create_task(self.gate.acquire_async(channel="public"))
        await asyncio.sleep(0.1)
        assert self.gate.wait_count >= 1
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestGetRateGate:
    def test_singleton(self):
        """get_rate_gate returns same instance."""
        import backend.services.bybit_rate_gate as mod
        mod._gate = None  # reset
        g1 = get_rate_gate()
        g2 = get_rate_gate()
        assert g1 is g2
        mod._gate = None  # cleanup


@pytest.mark.asyncio
async def test_bybit_client_uses_gate(monkeypatch):
    """BybitClient._wait_for_rate_limit delegates to centralized gate."""
    from unittest.mock import AsyncMock, patch
    from backend.services.bybit_client import BybitClient

    mock_gate = AsyncMock()
    mock_gate.acquire_async = AsyncMock()

    with patch("backend.services.bybit_client.get_rate_gate", return_value=mock_gate):
        client = BybitClient("key", "secret", "demo")
        await client._wait_for_rate_limit()
        mock_gate.acquire_async.assert_called_once_with(channel="private")
