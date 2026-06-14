"""Regression tests for PositionReconciler safety guards.

Focused on the untrusted-empty-positions guard: an OK-but-empty get_positions()
result must NOT force-close live DB trades (which would orphan real exchange
positions). See position_reconciler._reconcile_account.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.position_reconciler import PositionReconciler


class _AsyncCtx:
    """Async context manager yielding a fixed value (for pool.acquire())."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return False


def _old_ts() -> datetime:
    """A timestamp well outside the 90s young-trade grace window."""
    return datetime(2020, 1, 1, tzinfo=timezone.utc)


def _make_open_trade(symbol="BTCUSDT", side="Buy") -> dict:
    return {
        "id": "t-1",
        "account_id": "acc-1",
        "symbol": symbol,
        "side": side,
        "qty": "0.1",
        "filled_qty": "0",
        "status": "open",
        "version": 1,
        "created_at": _old_ts(),
        "opened_at": _old_ts(),
    }


def _build_reconciler(positions: list[dict], open_trades: list[dict]):
    """Wire a PositionReconciler with mocked deps. Returns (reconciler, trade_service)."""
    client = AsyncMock()
    client.get_positions = AsyncMock(return_value=positions)

    accounts_service = AsyncMock()
    accounts_service.get_client = AsyncMock(return_value=client)

    trade_service = AsyncMock()
    trade_service.get_open_trades = AsyncMock(return_value=open_trades)
    trade_service.invalidate_stats_cache = MagicMock()

    # conn.fetch returns [] for both the stalled and zero-pnl queries.
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    db = MagicMock()
    db.pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    reconciler = PositionReconciler(
        db=db, accounts_service=accounts_service, trade_service=trade_service,
    )
    return reconciler, trade_service, client


@pytest.mark.asyncio
async def test_empty_positions_does_not_force_close_open_trades():
    """GUARD: get_positions() returns [] (transient API blip) while the DB has an
    eligible open trade → the trade must NOT be force-closed (reconcile_close not
    called). Trusting the empty list would orphan a live exchange position."""
    reconciler, trade_service, _ = _build_reconciler(
        positions=[], open_trades=[_make_open_trade()],
    )
    await reconciler._reconcile_account("acc-1")
    trade_service.reconcile_close.assert_not_awaited()


@pytest.mark.asyncio
async def test_present_position_does_not_force_close():
    """A matching live position present on the exchange → the open DB trade is NOT
    stale, so no force-close (normal healthy case, unaffected by the guard)."""
    reconciler, trade_service, _ = _build_reconciler(
        positions=[{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1"}],
        open_trades=[_make_open_trade()],
    )
    await reconciler._reconcile_account("acc-1")
    trade_service.reconcile_close.assert_not_awaited()


@pytest.mark.asyncio
async def test_genuinely_absent_position_with_other_live_positions_reconciles():
    """When get_positions() is NON-empty (trustworthy) but does NOT contain the DB
    trade's (symbol, side), that trade IS stale and gets reconciled. This proves the
    untrusted-empty guard does not block legitimate stale-detection — only the
    all-empty case is skipped."""
    reconciler, trade_service, client = _build_reconciler(
        # A different live position confirms the exchange reading is real;
        # the DB's ETHUSDT/Buy trade is genuinely gone.
        positions=[{"symbol": "BTCUSDT", "side": "Buy", "size": "0.5"}],
        open_trades=[_make_open_trade(symbol="ETHUSDT", side="Buy")],
    )
    # _reconcile_trade looks up a closedPnl record via client.get_closed_pnl;
    # return a well-formed empty payload so the close path proceeds to reconcile_close.
    client.get_closed_pnl = AsyncMock(return_value={"list": []})
    trade_service.reconcile_close = AsyncMock(return_value={"status": "closed"})
    await reconciler._reconcile_account("acc-1")
    trade_service.reconcile_close.assert_awaited()


@pytest.mark.asyncio
async def test_closed_pnl_match_pages_past_first_page():
    """REGRESSION: _fetch_closed_pnl_match must walk the cursor past the first page.
    Previously it read only 2 pages (200 records) — a busy account whose target
    close sat on page 3+ never reconciled. Here the symbol's record only appears on
    the 3rd page; the matcher must still find it."""
    from backend.services.position_reconciler import PositionReconciler

    pages = [
        {"list": [{"symbol": "OTHER1USDT", "side": "Sell", "updatedTime": "1"}], "nextPageCursor": "c1"},
        {"list": [{"symbol": "OTHER2USDT", "side": "Sell", "updatedTime": "2"}], "nextPageCursor": "c2"},
        {"list": [{"symbol": "BTCUSDT", "side": "Sell", "updatedTime": "3",
                   "closedPnl": "12.5", "avgExitPrice": "51000", "execType": "Trade"}], "nextPageCursor": ""},
    ]
    call = {"n": 0}

    async def get_closed_pnl(**kwargs):
        i = call["n"]
        call["n"] += 1
        return pages[min(i, len(pages) - 1)]

    client = AsyncMock()
    client.get_closed_pnl = get_closed_pnl
    reconciler = PositionReconciler(db=MagicMock(), accounts_service=AsyncMock(), trade_service=AsyncMock())

    match = await reconciler._fetch_closed_pnl_match(client, "BTCUSDT", "Buy", 0, 9999)
    assert match is not None, "must find the BTCUSDT record on page 3 (cursor walk)"
    assert match["closedPnl"] == "12.5"
    assert call["n"] == 3  # walked all three pages


@pytest.mark.asyncio
async def test_reconcile_window_includes_record_created_before_opened_at():
    """REGRESSION (FIX-001): Bybit stamps a closed-PnL record's createdTime at
    position-OPEN time, which can be a few seconds BEFORE our DB's opened_at (clock
    skew between Bybit's position-create and our fill-record write). Bybit's
    closed-pnl endpoint filters by createdTime in [startTime, endTime], so a window
    starting exactly at opened_at EXCLUDES the record — the match fails forever and
    the trade stays net_pnl=0 (the Unni/Brother ESPORTS bug). _reconcile_trade must
    pad the window start backward so such records are still found.
    """
    from datetime import datetime, timezone
    from backend.services.position_reconciler import PositionReconciler, _CLOSED_PNL_WINDOW_PAD_MS

    # opened_at = a fixed instant; the exchange record was created 8s earlier.
    opened_dt = datetime(2026, 6, 14, 1, 31, 39, tzinfo=timezone.utc)
    opened_ms = int(opened_dt.timestamp() * 1000)
    record_created_ms = opened_ms - 8_000  # 8s before opened_at

    captured = {"start_ms": None}

    async def get_closed_pnl(start_time, end_time, limit=100, cursor=""):
        captured["start_ms"] = start_time
        # The exchange only returns the record when the query window's start is at or
        # before the record's createdTime — emulate Bybit's createdTime filter.
        if start_time <= record_created_ms:
            return {"list": [{"symbol": "ESPORTSUSDT", "side": "Buy",
                              "closedPnl": "-19.07806468", "avgExitPrice": "0.07486",
                              "execType": "Trade", "orderType": "Market",
                              "createdTime": str(record_created_ms),
                              "updatedTime": str(opened_ms + 6_000_000)}],
                    "nextPageCursor": ""}
        return {"list": [], "nextPageCursor": ""}

    client = AsyncMock()
    client.get_positions = AsyncMock(return_value=[{"symbol": "BTCUSDT", "side": "Buy", "size": "1"}])
    client.get_closed_pnl = get_closed_pnl

    accounts_service = AsyncMock()
    accounts_service.get_client = AsyncMock(return_value=client)

    trade = _make_open_trade(symbol="ESPORTSUSDT", side="Sell")
    trade["opened_at"] = opened_dt
    trade["created_at"] = opened_dt
    trade["entry_price"] = "0.06654"
    trade["qty"] = "2280"
    trade["stop_loss_price"] = "0.07474"  # real SL; exit 0.07486 is within 0.5% → stop_loss

    trade_service = AsyncMock()
    trade_service.get_open_trades = AsyncMock(return_value=[trade])
    trade_service.invalidate_stats_cache = MagicMock()
    trade_service.reconcile_close = AsyncMock(return_value={"status": "closed"})

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    db = MagicMock()
    db.pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    reconciler = PositionReconciler(
        db=db, accounts_service=accounts_service, trade_service=trade_service,
    )
    # The unrelated BTCUSDT live position (used only to make get_positions() trusted)
    # has no DB trade, so the reverse orphan-detection pass calls
    # pending_intents.lookup_strategy — stub it so this unit test stays focused on the
    # closed-PnL window, not the orphan path (which has its own coverage).
    import backend.services.pending_intents as _pi
    monkeypatch_target = AsyncMock(return_value=None)
    _orig = _pi.lookup_strategy
    _pi.lookup_strategy = monkeypatch_target
    try:
        await reconciler._reconcile_account("acc-1")
    finally:
        _pi.lookup_strategy = _orig

    # The window start must be padded back below the record's createdTime so the
    # match (and thus the real PnL) is found — not the bare opened_at.
    assert captured["start_ms"] is not None, "closed-pnl was queried"
    assert captured["start_ms"] <= record_created_ms, (
        f"window start {captured['start_ms']} must be padded below the record "
        f"createdTime {record_created_ms} (pad={_CLOSED_PNL_WINDOW_PAD_MS}ms)"
    )
    # And the trade must be reconciled with the REAL pnl, not zeroed.
    trade_service.reconcile_close.assert_awaited()
    kwargs = trade_service.reconcile_close.await_args.kwargs
    assert abs(kwargs["net_pnl"] - (-19.07806468)) < 1e-6, f"got {kwargs.get('net_pnl')}"
    assert kwargs["close_reason"] != "external", "real match should infer stop_loss, not external-zero"
