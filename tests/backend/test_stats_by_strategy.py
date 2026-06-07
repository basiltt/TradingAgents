"""Tests for the per-strategy PnL breakdown (FR-052/AC-016): get_stats_by_strategy."""

from __future__ import annotations

import pytest

from backend.services.trade_repository import TradeRepository


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.sql = None
        self.args = None

    async def fetch(self, sql, *args):
        self.sql = sql
        self.args = args
        return self._rows


def _row(strategy_kind, side, count, total_pnl, avg_pnl, avg_hold, win_rate):
    return {
        "strategy_kind": strategy_kind, "side": side, "count": count,
        "total_pnl": total_pnl, "avg_pnl": avg_pnl,
        "avg_hold_minutes": avg_hold, "win_rate": win_rate,
    }


@pytest.mark.asyncio
async def test_maps_side_to_direction_and_shapes_rows():
    conn = _FakeConn([
        _row("trend", "Sell", 10, 100.0, 10.0, 90.0, 0.6),
        _row("mean_reversion", "Buy", 4, -8.0, -2.0, 45.0, 0.25),
    ])
    repo = TradeRepository(None)
    out = await repo.get_stats_by_strategy(conn, account_ids=["a1"])
    assert out[0]["strategy_kind"] == "trend" and out[0]["direction"] == "short"
    assert out[1]["strategy_kind"] == "mean_reversion" and out[1]["direction"] == "long"
    assert out[1]["count"] == 4 and out[1]["total_pnl"] == -8.0
    # query is grouped by strategy_kind and side
    assert "GROUP BY strategy_kind, side" in conn.sql
    assert conn.args[0] == ["a1"]


@pytest.mark.asyncio
async def test_empty_result_returns_empty_list():
    repo = TradeRepository(None)
    out = await repo.get_stats_by_strategy(_FakeConn([]), account_ids=["a1"])
    assert out == []


@pytest.mark.asyncio
async def test_null_aggregates_coerced_to_zero():
    conn = _FakeConn([_row("trend", "Buy", 1, None, None, None, None)])
    repo = TradeRepository(None)
    out = await repo.get_stats_by_strategy(conn, account_ids=["a1"])
    assert out[0]["total_pnl"] == 0.0
    assert out[0]["avg_hold_minutes"] == 0.0
    assert out[0]["win_rate"] == 0.0
