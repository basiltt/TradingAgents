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
        """An order-lane caller (raise_on_ban=True) gets RateGateBanAbort while OPEN."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=600)
        with pytest.raises(RateGateBanAbort) as exc:
            await gate.acquire_async(channel="private", lane="order",
                                     account_key="A", endpoint_class="order_create",
                                     raise_on_ban=True)
        assert exc.value.cooloff_until is not None
        gate.clear_ban()

    @pytest.mark.asyncio
    async def test_background_caller_waits_out_ban_no_raise(self):
        """A background caller (raise_on_ban=False, the default) does NOT raise — it
        waits until the ban clears, then proceeds. Crucial: an IP ban must PAUSE the
        reconciler/AI-manager loops, never crash them with a BaseException."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=0.3)
        # Default raise_on_ban=False: this should block ~0.3s then succeed, not raise.
        await asyncio.wait_for(
            gate.acquire_async(channel="private", lane="live",
                               account_key="A", endpoint_class="order_create"),
            timeout=3.0,
        )
        assert gate.current_usage["private"] >= 1

    @pytest.mark.asyncio
    async def test_breaker_clears_after_window(self):
        """After the cooloff window the breaker allows acquisition again (half-open probe)."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=0.2)
        await asyncio.sleep(0.35)
        # half-open admits the probe (order lane)
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create",
                                 raise_on_ban=True)
        assert gate.current_usage["private"] >= 1
        gate.clear_ban()

    @pytest.mark.asyncio
    async def test_half_open_admits_exactly_one_of_many_concurrent(self):
        """At cooloff expiry, only ONE concurrent order-lane caller is admitted as the
        probe; the rest are held (RateGateBanAbort) until the probe reports back. This
        is the thundering-herd guard that prevents a herd re-tripping a still-active ban."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=0.15)
        await asyncio.sleep(0.25)  # past the cooloff deadline -> half-open

        async def _try():
            try:
                await gate.acquire_async(channel="private", lane="order",
                                         account_key="A", endpoint_class="order_create",
                                         raise_on_ban=True)
                return "admitted"
            except RateGateBanAbort:
                return "held"

        results = await asyncio.gather(*[_try() for _ in range(10)])
        # Exactly one probe admitted; the other 9 held (no herd).
        assert results.count("admitted") == 1
        assert results.count("held") == 9
        gate.clear_ban()

    @pytest.mark.asyncio
    async def test_probe_success_clears_breaker(self):
        """Once the probe is admitted, clear_ban (called on a successful request)
        closes the breaker so normal traffic resumes."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=0.15)
        await asyncio.sleep(0.25)
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="A", endpoint_class="order_create",
                                 raise_on_ban=True)
        gate.clear_ban()  # simulates a successful probe request
        # Now a fresh caller proceeds with no ban in effect.
        await gate.acquire_async(channel="private", lane="order",
                                 account_key="B", endpoint_class="order_create",
                                 raise_on_ban=True)
        assert gate.ban_cooloff_until is None

    @pytest.mark.asyncio
    async def test_acquire_sync_returns_false_on_open_ban(self):
        """Sync callers keep their bool contract under a ban (return False, no raise)."""
        gate = BybitRateGate(public_budget=100, private_budget=100, window=5.0)
        gate.trip_ban(cooloff_seconds=600)
        # Sync acquire must NOT raise a BaseException — it times out to False.
        assert gate.acquire_sync(channel="public", timeout=0.3) is False
        gate.clear_ban()

    def test_clear_ban(self):
        """clear_ban() removes an active ban (operator override / test isolation)."""
        gate = BybitRateGate(public_budget=10, private_budget=10, window=1.0)
        gate.trip_ban(cooloff_seconds=600)
        assert gate.ban_cooloff_until is not None
        gate.clear_ban()
        assert gate.ban_cooloff_until is None

    def test_clear_ban_generation_guard_blocks_stale_clear(self):
        """A clear_ban with a stale generation must NOT wipe a fresher ban (ABA guard)."""
        gate = BybitRateGate(public_budget=10, private_budget=10, window=1.0)
        gate.trip_ban(cooloff_seconds=600)
        gen1 = gate.ban_generation
        # A fresh ban supersedes the first.
        gate.trip_ban(cooloff_seconds=600)
        # A stale success (observed gen1) must be refused.
        assert gate.clear_ban(expected_generation=gen1) is False
        assert gate.ban_cooloff_until is not None  # fresh ban still in effect
        # The matching generation clears it.
        assert gate.clear_ban(expected_generation=gate.ban_generation) is True
        assert gate.ban_cooloff_until is None

    def test_ban_abort_is_base_exception(self):
        """RateGateBanAbort must subclass BaseException (so a broad `except Exception`
        in the placement path cannot swallow it)."""
        assert issubclass(RateGateBanAbort, BaseException)
        assert not issubclass(RateGateBanAbort, Exception)

