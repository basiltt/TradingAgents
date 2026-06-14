"""Tests for the per-account/endpoint sub-limiter, thread-safe wait_count, and
ban breaker added to BybitRateGate (TASK-0.2/0.3/0.4)."""
import asyncio
import threading
import time

import pytest

from backend.services.bybit_rate_gate import BybitRateGate, RateGateBanAbort


class TestPerAccountEndpointSubLimiter:
    @pytest.mark.asyncio
    async def test_per_account_endpoint_cap_throttles(self):
        """A single account+endpoint over its 1s cap waits, even with channel budget free."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        # order_create cap is 2/s for this test
        gate.set_endpoint_caps({"order_create": 2}, per_window=1.0)
        for _ in range(2):
            await gate.acquire_async(channel="private", lane="order",
                                     account_key="A", endpoint_class="order_create")
        start = time.monotonic()
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.9  # waited ~1s for the per-endpoint window

    @pytest.mark.asyncio
    async def test_distinct_accounts_independent(self):
        """Two accounts each get their own per-endpoint budget."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.set_endpoint_caps({"order_create": 1}, per_window=1.0)
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create")
        # account B is independent — should not block
        start = time.monotonic()
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="B", endpoint_class="order_create")
        assert time.monotonic() - start < 0.5

    @pytest.mark.asyncio
    async def test_all_or_none_no_ip_token_leak_on_endpoint_miss(self):
        """When the per-endpoint dim is full but the channel is free, the channel
        deque must NOT be charged (all-or-none) — else the IP budget leaks."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.set_endpoint_caps({"order_create": 1}, per_window=5.0)
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create")
        private_after_first = gate.current_usage["private"]
        assert private_after_first == 1
        # Second acquire for the same account+endpoint will block on the endpoint dim.
        # Kick it off and cancel quickly; the private channel must still read 1
        # (no token appended while the endpoint dim was full).
        task = asyncio.create_task(gate.acquire_async(
            channel="private", lane="order",
            account_key="A", endpoint_class="order_create"))
        await asyncio.sleep(0.1)
        assert gate.current_usage["private"] == 1, "IP token leaked while endpoint dim full"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_backward_compat_no_account_key(self):
        """Existing callers without account_key/endpoint_class still work (channel-only)."""
        gate = BybitRateGate(public_budget=5, private_budget=3, window=1.0)
        for _ in range(3):
            await gate.acquire_async(channel="private", lane="order")
        assert gate.current_usage["private"] == 3


class TestThreadSafeWaitCount:
    def test_wait_count_no_lost_update(self):
        """Concurrent sync+async-style inc/dec must not corrupt _wait_count."""
        gate = BybitRateGate(public_budget=1000, private_budget=1000, window=5.0)
        # Drive many concurrent sync acquires from threads; _wait_count must end at 0.
        def worker():
            for _ in range(50):
                gate.acquire_sync(channel="public", timeout=2.0)
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert gate.wait_count == 0


class TestBanBreaker:
    @pytest.mark.asyncio
    async def test_open_breaker_raises_ban_abort(self):
        """When the breaker is OPEN, acquire raises RateGateBanAbort with cooloff."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=600)
        with pytest.raises(RateGateBanAbort) as exc:
            await gate.acquire_async(channel="private", lane="order",
                                     account_key="A", endpoint_class="order_create")
        assert exc.value.cooloff_until is not None

    @pytest.mark.asyncio
    async def test_breaker_clears_after_window(self):
        """After the cooloff window the breaker allows acquisition again (half-open probe)."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=0.2)
        await asyncio.sleep(0.35)
        # half-open admits the probe
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create")
        assert gate.current_usage["private"] >= 1

    @pytest.mark.asyncio
    async def test_half_open_admits_single_probe_then_clears(self):
        """At cooloff expiry only ONE caller is admitted; it then fully clears (no herd)."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=0.15)
        await asyncio.sleep(0.25)
        # First caller is the probe — admitted and clears the breaker.
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create")
        # Breaker is now cleared; a subsequent caller proceeds normally.
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="B", endpoint_class="order_create")
        assert gate.ban_cooloff_until is None

    def test_clear_ban(self):
        """clear_ban() removes an active ban (operator override / test isolation)."""
        gate = BybitRateGate(public_budget=10, private_budget=10, window=1.0)
        gate.trip_ban(cooloff_seconds=600)
        assert gate.ban_cooloff_until is not None
        gate.clear_ban()
        assert gate.ban_cooloff_until is None

    def test_ban_abort_is_base_exception(self):
        """RateGateBanAbort must subclass BaseException (so a broad `except Exception`
        in the placement path cannot swallow it)."""
        assert issubclass(RateGateBanAbort, BaseException)
        assert not issubclass(RateGateBanAbort, Exception)
