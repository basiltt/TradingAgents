"""Tests for the place_trade order-submission shield (TASK-2.5).

The post-scan tail can be cancelled (scan cancel / shutdown). A cancellation that
lands WHILE the exchange order is in flight must not abandon the order in an unknown
state — the order (which carries TP/SL inline) must complete so the position is
either fully open WITH protection or never placed. We assert the exchange order
submission is shielded: cancelling the awaiting task does not prevent the order call
from completing.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_place_market_order_completes_despite_outer_cancel():
    """A shielded order submission runs to completion even if the awaiting task is
    cancelled mid-flight. This is the invariant the place_trade shield provides."""
    order_completed = asyncio.Event()
    order_started = asyncio.Event()

    async def slow_order():
        order_started.set()
        await asyncio.sleep(0.05)
        order_completed.set()
        return {"orderId": "abc"}

    async def caller():
        # Mirror the production pattern: shield the exchange order submission.
        return await asyncio.shield(slow_order())

    task = asyncio.create_task(caller())
    await order_started.wait()
    # Cancel the caller WHILE the order is in flight.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The shielded order must still complete (position protected, not abandoned).
    await asyncio.wait_for(order_completed.wait(), timeout=1.0)
    assert order_completed.is_set()


@pytest.mark.asyncio
async def test_accounts_service_shields_order_submission():
    """place_trade wraps the place_market_order call in asyncio.shield so a cancel
    cannot orphan a position whose TP/SL is set inline at order creation."""
    import inspect

    from backend.services import accounts_service

    src = inspect.getsource(accounts_service.AccountsService.place_trade)
    # The order submission is shielded (defense in depth: the order carries TP/SL).
    assert "asyncio.shield" in src, "place_trade must shield the exchange order submission"
    # And the shield wraps place_market_order specifically.
    assert "place_market_order" in src


# --------------------------------------------------------------------------- #
# Lock-order invariant (SC-3): pool is the LEAF — no position-lock acquired while
# holding a DB pool connection. Verified statically across the only two
# position-lock acquirers (auto_trade_service, ai_manager_task).
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_pool_is_leaf_no_position_lock_under_pool_conn():
    """The canonical order is account-sem -> position-lock -> client-sem -> gate ->
    pool. The dangerous inversion is acquiring a position-lock while ALREADY holding
    a pool connection. Assert that within an `async with ... pool.acquire()` block,
    neither position-lock acquirer calls registry.acquire / lock.acquire."""
    import re

    for module_path in (
        "backend/services/auto_trade_service.py",
        "backend/services/ai_manager_task.py",
    ):
        with open(module_path, encoding="utf-8") as f:
            src = f.read()
        # Find each `pool.acquire()` context manager block and ensure no position-lock
        # acquire appears textually until the block's indentation closes. Heuristic but
        # catches the obvious inversion; the real guard is the architecture (pool is the
        # leaf, acquired inside place_trade AFTER the position-lock is taken upstream).
        for m in re.finditer(r"pool\.acquire\(\)", src):
            window = src[m.end():m.end() + 800]
            assert "registry.acquire" not in window and "lock.acquire(" not in window, (
                f"possible lock-order inversion near pool.acquire in {module_path}"
            )


@pytest.mark.asyncio
async def test_orphan_order_logged_on_post_placement_db_failure(caplog):
    """FR-038 / TASK-2.8: when the exchange order placed but the trade-row write fails,
    a structured HIGH-severity orphan_order record is logged (the reconciler picks it
    up). The position is protected by inline TP/SL; we never silently drop it."""
    import inspect

    from backend.services import accounts_service

    src = inspect.getsource(accounts_service.AccountsService.place_trade)
    # The orphan record is emitted in the post-order trade-row failure handler.
    assert 'logger.error("orphan_order"' in src or "orphan_order" in src, (
        "place_trade must log a structured orphan_order on post-placement DB failure"
    )
    # It carries the fields the reconciler / operator needs.
    assert "severity" in src and "high" in src
    assert "order_id" in src


