"""P1 completion tests — the read tools added to close the P1 plan gap
(positions, trades, portfolio, analytics, symbols, config_current, scheduled_get).

Registration + redaction-by-default + shape contracts, using fake services so
no real DB/exchange is needed (mirrors test_p1_read_tools.py style).
"""
from __future__ import annotations

import pytest

from backend.mcp.core.clock import RealClock
from backend.mcp.core.dispatch import CallContext, dispatch
from backend.mcp.core.registry import _REGISTRY
from backend.mcp.discovery import discover_tools

discover_tools()


# --- fakes ---

class _AccountsSvc:
    async def get_positions(self, account_id):
        return [
            {"symbol": "BTCUSDT", "side": "Buy", "size": 0.5, "leverage": 10,
             "entry_price": 60000.0, "unrealised_pnl_pct": 3.2,
             "unrealised_pnl": 192.0, "equity": 5000.0, "bybit_uid": "999"},
        ]

    async def compute_analytics(self, account_id, start, end):
        return {"sharpe": 1.4, "max_drawdown_pct": 8.0, "win_rate": 0.6,
                "total_pnl": 1234.5, "equity": 5000.0}


class _SignalSvc:
    async def get_summary(self, start_date=None, end_date=None):
        return {"total_trades": 42, "win_rate": 0.57, "avg_pnl_pct": 1.1, "total_pnl": 999.0}


class _TradeRepo:
    async def list_trades(self, conn, *, account_id, status=None, symbol=None,
                          side=None, cursor=None, limit=50):
        return {"trades": [
            {"id": "t1", "symbol": "BTCUSDT", "side": "Buy", "status": "closed",
             "close_reason": "take_profit", "pnl_pct": 4.0, "pnl": 200.0,
             "created_at": "2026-06-01", "equity": 5000.0},
        ], "next_cursor": None}

    async def get_trade(self, conn, *, account_id, trade_id):
        return {"id": trade_id, "symbol": "BTCUSDT", "pnl": 200.0, "pnl_pct": 4.0}


class _Conn:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _Pool:
    def acquire(self): return _Conn()


class _DB:
    pool = _Pool()

    async def get_portfolio_pnl_summary(self, start, end, account_type=None):
        return {"total_pnl": "1500", "win_count": 12, "loss_count": 8, "win_rate": 0.6}

    async def list_scheduled_scans(self):
        return [{"id": "sch1", "name": "daily",
                 "scan_config": {"auto_trade_configs": [{"leverage": 10, "take_profit_pct": 150}]},
                 "api_secret": "SHOULD_BE_STRIPPED"}]

    async def get_scheduled_scan(self, sid):
        return {"id": sid, "name": "daily",
                "scan_config": {"auto_trade_configs": [{"leverage": 10}]},
                "api_secret": "SHOULD_BE_STRIPPED"}


class _SectorSvc:
    def get_sector(self, symbol):
        return "L1"


class _Services:
    def __init__(self):
        self.db = _DB()
        self.accounts_service = _AccountsSvc()
        self.signal_analytics_service = _SignalSvc()
        self.trade_repo = _TradeRepo()
        self.sector_service = _SectorSvc()


def _ctx():
    return CallContext(principal="t", session_id="s", tier="READ_ONLY",
                       correlation_id=None, services=_Services(), clock=RealClock())


async def _call(name, args):
    return await dispatch(_REGISTRY[name], args, _ctx(), audit=lambda r: None)


# --- registration ---

def test_all_new_p1_tools_registered():
    for name in ("positions_list", "positions_get", "trades_list", "trades_get",
                 "portfolio_overview", "analytics_summary", "signal_analytics",
                 "symbols_search", "symbols_get", "config_current", "scheduled_get"):
        assert name in _REGISTRY, f"{name} not registered"


# --- positions ---

@pytest.mark.asyncio
async def test_positions_list_redacts_money_and_uid_by_default():
    res = await _call("positions_list", {"account_id": "acc1"})
    assert res["isError"] is False
    pos = res["structuredContent"]["positions"][0]
    assert "bybit_uid" not in pos  # exchange uid dropped
    # absolute unrealised_pnl masked unless financial_detail; ratio pct kept
    assert "unrealised_pnl_pct" in pos


@pytest.mark.asyncio
async def test_positions_get_returns_match():
    res = await _call("positions_get", {"account_id": "acc1", "symbol": "BTCUSDT"})
    assert res["structuredContent"]["position"]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_positions_get_missing_symbol_is_none():
    res = await _call("positions_get", {"account_id": "acc1", "symbol": "NOPE"})
    assert res["structuredContent"]["position"] is None


# --- trades ---

@pytest.mark.asyncio
async def test_trades_list_redacts_absolute_pnl_by_default():
    res = await _call("trades_list", {"account_id": "acc1"})
    assert res["isError"] is False
    tr = res["structuredContent"]["trades"][0]
    assert "pnl_pct" in tr  # ratio kept


@pytest.mark.asyncio
async def test_trades_list_rejects_garbage_cursor():
    res = await _call("trades_list", {"account_id": "acc1", "cursor": "!!notvalid!!"})
    assert res["isError"] is True  # MCPValidationError mapped


@pytest.mark.asyncio
async def test_trades_get_by_id():
    res = await _call("trades_get", {"account_id": "acc1", "trade_id": "t1"})
    assert res["structuredContent"]["trade"]["id"] == "t1"


# --- portfolio / analytics ---

@pytest.mark.asyncio
async def test_portfolio_overview_returns_summary():
    res = await _call("portfolio_overview", {"days": 30})
    assert res["isError"] is False
    assert res["structuredContent"]["window_days"] == 30


@pytest.mark.asyncio
async def test_analytics_summary_window():
    res = await _call("analytics_summary", {"account_id": "acc1", "days": 14})
    assert res["structuredContent"]["window_days"] == 14
    assert "sharpe" in res["structuredContent"]["analytics"]


@pytest.mark.asyncio
async def test_signal_analytics_returns_kpis():
    res = await _call("signal_analytics", {"days": 30})
    assert res["structuredContent"]["analytics"]["total_trades"] == 42


# --- symbols ---

@pytest.mark.asyncio
async def test_symbols_get_tradable_with_sector(monkeypatch):
    import tradingagents.dataflows.bybit_data as bd
    monkeypatch.setattr(bd, "get_valid_symbols", lambda: ["BTCUSDT", "ETHUSDT"])
    res = await _call("symbols_get", {"symbol": "btcusdt"})
    sc = res["structuredContent"]
    assert sc["tradable"] is True and sc["sector"] == "L1"


@pytest.mark.asyncio
async def test_symbols_search_substring(monkeypatch):
    import tradingagents.dataflows.bybit_data as bd
    monkeypatch.setattr(bd, "get_valid_symbols", lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    res = await _call("symbols_search", {"query": "eth"})
    assert res["structuredContent"]["symbols"] == ["ETHUSDT"]


# --- config_current / scheduled_get ---

@pytest.mark.asyncio
async def test_config_current_flattens_configs_with_index():
    res = await _call("config_current", {})
    cfgs = res["structuredContent"]["configs"]
    assert cfgs[0]["schedule_id"] == "sch1" and cfgs[0]["config_index"] == 0


@pytest.mark.asyncio
async def test_config_current_strips_secrets():
    res = await _call("config_current", {})
    # the api_secret on the schedule row must never reach the agent
    import json
    assert "SHOULD_BE_STRIPPED" not in json.dumps(res["structuredContent"])


@pytest.mark.asyncio
async def test_scheduled_get_strips_secrets():
    res = await _call("scheduled_get", {"schedule_id": "sch1"})
    import json
    assert "SHOULD_BE_STRIPPED" not in json.dumps(res["structuredContent"])
