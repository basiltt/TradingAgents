"""Tests for FR-030: strategy-scoped adaptive blacklist.

A mean-reversion losing streak must feed ONLY the MR blacklist and never the trend
blacklist (and vice-versa). The query joins trades.strategy_kind; the _try_trade gate
reads the MR-scoped key on the fade path. Default-off / trend-only stays byte-identical.
"""

from __future__ import annotations

import pytest

from backend.services.scanner_service import ScannerService


class _FakePool:
    """Records fetch() calls and returns rows keyed by the strategy_kind arg ($3)."""

    def __init__(self, rows_by_strategy):
        self._rows_by_strategy = rows_by_strategy
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        strategy_kind = args[2]  # $3
        return self._rows_by_strategy.get(strategy_kind, [])


class _FakeDB:
    def __init__(self, rows_by_strategy):
        self.pool = _FakePool(rows_by_strategy)


def _row(symbol, total, wins):
    return {"symbol": symbol, "total": total, "wins": wins}


def _cfg(**kw):
    base = {"adaptive_blacklist_enabled": True, "adaptive_blacklist_min_trades": 5,
            "adaptive_blacklist_max_win_rate": 30.0, "adaptive_blacklist_lookback_hours": 48}
    base.update(kw)
    return base


def _svc(db):
    return ScannerService(analysis_service=object(), db=db)


# --- query scoping ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_joins_trades_and_filters_by_strategy_kind():
    db = _FakeDB({"trend": [_row("BADUSDT", 10, 1)]})
    svc = _svc(db)
    result = await svc._compute_adaptive_blacklist([_cfg()], "trend")
    assert result == {"BADUSDT"}
    sql, args = db.pool.calls[0]
    assert "JOIN trades t ON t.id = sp.trade_id" in sql
    assert "t.strategy_kind = $3" in sql
    assert args[2] == "trend"


@pytest.mark.asyncio
async def test_mr_losses_do_not_appear_in_trend_blacklist():
    # MR-scoped query returns the loser; trend-scoped returns nothing.
    db = _FakeDB({"trend": [], "mean_reversion": [_row("FADEUSDT", 8, 0)]})
    svc = _svc(db)
    trend_bl = await svc._compute_adaptive_blacklist([_cfg()], "trend")
    mr_bl = await svc._compute_adaptive_blacklist([_cfg(mean_reversion_enabled=True)], "mean_reversion", require_mr=True)
    assert trend_bl == set()
    assert mr_bl == {"FADEUSDT"}


@pytest.mark.asyncio
async def test_require_mr_skips_when_no_config_enables_mr():
    db = _FakeDB({"mean_reversion": [_row("FADEUSDT", 8, 0)]})
    svc = _svc(db)
    # adaptive blacklist on, but mean_reversion_enabled is absent -> no MR scope.
    result = await svc._compute_adaptive_blacklist([_cfg()], "mean_reversion", require_mr=True)
    assert result == set()
    assert db.pool.calls == []  # never queried


@pytest.mark.asyncio
async def test_win_rate_threshold_excludes_good_symbols():
    db = _FakeDB({"trend": [_row("GOODUSDT", 10, 9), _row("BADUSDT", 10, 2)]})
    svc = _svc(db)
    result = await svc._compute_adaptive_blacklist([_cfg(adaptive_blacklist_max_win_rate=30.0)], "trend")
    assert result == {"BADUSDT"}  # 90% kept, 20% blacklisted


@pytest.mark.asyncio
async def test_disabled_returns_empty_without_query():
    db = _FakeDB({"trend": [_row("BADUSDT", 10, 1)]})
    svc = _svc(db)
    result = await svc._compute_adaptive_blacklist([_cfg(adaptive_blacklist_enabled=False)], "trend")
    assert result == set()
    assert db.pool.calls == []


# --- gate selection (the executor reads the right key by mr_fade) ----------------

from backend.services.strategy_router import select_adaptive_blacklist as _gate_pick_impl


def _gate_pick(cfg, mr_fade):
    # Imports the REAL executor helper (no mirrored copy that could drift).
    return _gate_pick_impl(cfg, mr_fade=mr_fade)


def test_gate_picks_mr_key_on_fade_path():
    cfg = {"_computed_adaptive_blacklist": ["TRENDBAD"],
           "_computed_mr_adaptive_blacklist": ["MRBAD"]}
    assert _gate_pick(cfg, mr_fade=True) == ["MRBAD"]
    assert _gate_pick(cfg, mr_fade=False) == ["TRENDBAD"]


def test_gate_mr_key_absent_means_no_mr_blacklist():
    cfg = {"_computed_adaptive_blacklist": ["TRENDBAD"]}
    assert _gate_pick(cfg, mr_fade=True) is None  # MR not blocked by trend list
