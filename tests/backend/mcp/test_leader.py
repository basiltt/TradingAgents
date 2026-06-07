"""MCP leader-election tests — G2-5 (FR-034), real DB."""
from __future__ import annotations

import os

import pytest

_TEST_DSN = os.environ.get(
    "MCP_TEST_DATABASE_URL",
    "postgresql://postgres:Mywings123@localhost:5432/tradingagents_test",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_one_leader_wins_the_lock():
    """Two MCPLeader instances contend; exactly one becomes leader (FR-034)."""
    from backend.mcp.leader import MCPLeader

    a, b = MCPLeader(), MCPLeader()
    try:
        got_a = await a.acquire(_TEST_DSN)
        got_b = await b.acquire(_TEST_DSN)
        assert got_a is True
        assert got_b is False  # second worker degrades (non-blocking try-lock)
        assert a.is_leader and not b.is_leader
    finally:
        await a.release()
        await b.release()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_leadership_fails_over_after_release():
    """After the leader releases, a new contender can become leader."""
    from backend.mcp.leader import MCPLeader

    a = MCPLeader()
    assert await a.acquire(_TEST_DSN) is True
    await a.release()
    assert a.is_leader is False

    b = MCPLeader()
    try:
        assert await b.acquire(_TEST_DSN) is True  # lock freed → b wins
    finally:
        await b.release()
