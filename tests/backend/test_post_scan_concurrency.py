"""Tests for the process-wide account-concurrency primitive (TASK-2.3).

Covers:
  * default width = 1 (ships sequential)
  * FR-049 validation/clamp of configured width
  * the fanout_disabled kill-switch forces effective width 1
  * loop-binding safety (a process singleton Semaphore must recreate on a new loop)
  * resize recreates the semaphore at the new width
  * width=1 strictly serializes; width=2 permits 2 concurrent holders
  * single-flight registry blocks a concurrent same-scan tail, independent per scan
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services import post_scan_concurrency as psc
from backend.services import post_scan_flags


@pytest.fixture(autouse=True)
def _reset_concurrency_state():
    psc.reset_for_tests()
    post_scan_flags.reset_for_tests()
    yield
    psc.reset_for_tests()
    post_scan_flags.reset_for_tests()


def test_default_width_is_one():
    assert psc.effective_width() == 1


def test_configure_clamps_invalid_width():
    assert psc.configure_account_concurrency(4) == 4
    assert psc.effective_width() == 4
    # zero / negative clamp up to 1
    assert psc.configure_account_concurrency(0) == 1
    assert psc.configure_account_concurrency(-5) == 1
    # absurdly large clamps to the ceiling
    assert psc.configure_account_concurrency(10_000) == psc.MAX_WIDTH
    # non-numeric => fall back to default (1), never raise
    assert psc.configure_account_concurrency("nonsense") == 1
    assert psc.configure_account_concurrency(None) == 1


def test_fanout_disabled_forces_width_one():
    psc.configure_account_concurrency(8)
    assert psc.effective_width() == 8
    post_scan_flags._fanout_disabled = True  # simulate revert kill-switch on
    assert psc.effective_width() == 1


@pytest.mark.asyncio
async def test_semaphore_reflects_effective_width():
    psc.configure_account_concurrency(3)
    sem = psc.get_account_semaphore()
    assert isinstance(sem, asyncio.Semaphore)
    assert sem._value == 3


@pytest.mark.asyncio
async def test_semaphore_is_stable_within_loop_and_width():
    psc.configure_account_concurrency(2)
    a = psc.get_account_semaphore()
    b = psc.get_account_semaphore()
    assert a is b  # same object => same fan-out shares one limiter


@pytest.mark.asyncio
async def test_semaphore_recreated_on_width_change():
    psc.configure_account_concurrency(1)
    a = psc.get_account_semaphore()
    psc.configure_account_concurrency(4)
    b = psc.get_account_semaphore()
    assert a is not b
    assert b._value == 4


def test_semaphore_recreated_on_new_event_loop():
    # A process-singleton Semaphore created on loop A must NOT be reused on loop B
    # (asyncio raises "bound to a different event loop"). Two asyncio.run() calls
    # create two distinct loops; both must succeed.
    psc.configure_account_concurrency(2)

    async def _use():
        sem = psc.get_account_semaphore()
        async with sem:
            return id(sem)

    first = asyncio.run(_use())
    second = asyncio.run(_use())
    # Distinct objects (recreated for the second loop); neither call raised.
    assert first != second


@pytest.mark.asyncio
async def test_width_one_serializes():
    psc.configure_account_concurrency(1)
    sem = psc.get_account_semaphore()
    observed_max = 0
    current = 0

    async def worker():
        nonlocal observed_max, current
        async with sem:
            current += 1
            observed_max = max(observed_max, current)
            await asyncio.sleep(0.005)
            current -= 1

    await asyncio.gather(*[worker() for _ in range(5)])
    assert observed_max == 1


@pytest.mark.asyncio
async def test_width_two_allows_two_concurrent():
    psc.configure_account_concurrency(2)
    sem = psc.get_account_semaphore()
    observed_max = 0
    current = 0

    async def worker():
        nonlocal observed_max, current
        async with sem:
            current += 1
            observed_max = max(observed_max, current)
            await asyncio.sleep(0.01)
            current -= 1

    await asyncio.gather(*[worker() for _ in range(6)])
    assert observed_max == 2


def test_single_flight_blocks_same_scan():
    assert psc.try_begin_tail("scan-1") is True
    # A second begin for the same scan while in-flight is rejected.
    assert psc.try_begin_tail("scan-1") is False
    psc.end_tail("scan-1")
    # After release it can begin again.
    assert psc.try_begin_tail("scan-1") is True
    psc.end_tail("scan-1")


def test_single_flight_independent_per_scan():
    assert psc.try_begin_tail("scan-A") is True
    assert psc.try_begin_tail("scan-B") is True
    assert psc.try_begin_tail("scan-A") is False
    assert psc.try_begin_tail("scan-B") is False
    psc.end_tail("scan-A")
    psc.end_tail("scan-B")


def test_end_tail_is_idempotent():
    # Discarding a never-started / already-ended scan must not raise.
    psc.end_tail("never-started")
    assert psc.try_begin_tail("x") is True
    psc.end_tail("x")
    psc.end_tail("x")  # double end is safe
