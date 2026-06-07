"""Tests for FR-051: pending-trade-intent records for strategy-aware orphan reconciliation.

Covers the intent store (write/lookup/delete/gc) and the reconciler enrichment that
recovers an orphan's strategy_kind instead of mislabeling it 'trend'.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import pending_intents as pi


# --- in-memory fake asyncpg pool -------------------------------------------------

class _FakePool:
    """Minimal asyncpg-pool stand-in keyed by (account, symbol, side)."""

    def __init__(self):
        self.rows: dict[tuple[str, str, str], dict] = {}

    async def execute(self, sql, *args):
        s = " ".join(sql.split()).upper()
        if s.startswith("INSERT INTO PENDING_TRADE_INTENTS"):
            account_id, symbol, side, strategy_kind, created_at = args
            self.rows[(account_id, symbol, side)] = {
                "strategy_kind": strategy_kind, "created_at": created_at}
            return "INSERT 0 1"
        if s.startswith("DELETE FROM PENDING_TRADE_INTENTS WHERE ACCOUNT_ID"):
            account_id, symbol, side = args
            existed = self.rows.pop((account_id, symbol, side), None)
            return f"DELETE {1 if existed else 0}"
        if s.startswith("DELETE FROM PENDING_TRADE_INTENTS WHERE CREATED_AT"):
            (cutoff,) = args
            old = [k for k, v in self.rows.items() if v["created_at"] < cutoff]
            for k in old:
                self.rows.pop(k, None)
            return f"DELETE {len(old)}"
        raise AssertionError(f"unexpected SQL: {sql}")

    async def fetchrow(self, sql, *args):
        account_id, symbol, side = args
        return self.rows.get((account_id, symbol, side))


class _FakeDB:
    def __init__(self):
        self.pool = _FakePool()


# --- intent store ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_then_lookup_recovers_strategy():
    db = _FakeDB()
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "mean_reversion")
    assert await pi.lookup_strategy(db, "acct1", "BTCUSDT", "Sell") == "mean_reversion"


@pytest.mark.asyncio
async def test_lookup_is_side_specific():
    db = _FakeDB()
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "mean_reversion")
    # wrong side must NOT match (a Buy orphan is a different position)
    assert await pi.lookup_strategy(db, "acct1", "BTCUSDT", "Buy") is None


@pytest.mark.asyncio
async def test_delete_after_create_removes_intent():
    db = _FakeDB()
    await pi.write_intent(db, "acct1", "ETHUSDT", "Buy", "mean_reversion")
    await pi.delete_intent(db, "acct1", "ETHUSDT", "Buy")
    assert await pi.lookup_strategy(db, "acct1", "ETHUSDT", "Buy") is None


@pytest.mark.asyncio
async def test_write_is_idempotent_upsert():
    db = _FakeDB()
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "trend")
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "mean_reversion")
    # second write wins (ON CONFLICT DO UPDATE)
    assert await pi.lookup_strategy(db, "acct1", "BTCUSDT", "Sell") == "mean_reversion"
    assert len(db.pool.rows) == 1


@pytest.mark.asyncio
async def test_gc_stale_sweeps_only_old_intents():
    db = _FakeDB()
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "mean_reversion")
    # age this intent past the window
    db.pool.rows[("acct1", "BTCUSDT", "Sell")]["created_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=120))
    await pi.write_intent(db, "acct1", "ETHUSDT", "Buy", "mean_reversion")  # fresh
    removed = await pi.gc_stale(db, max_age_minutes=60)
    assert removed == 1
    assert await pi.lookup_strategy(db, "acct1", "BTCUSDT", "Sell") is None
    assert await pi.lookup_strategy(db, "acct1", "ETHUSDT", "Buy") == "mean_reversion"


# --- fail-open guarantees (intent plumbing must never block a real trade) ---------

@pytest.mark.asyncio
async def test_write_failopen_when_db_none():
    await pi.write_intent(None, "a", "BTCUSDT", "Sell", "mean_reversion")  # no raise


@pytest.mark.asyncio
async def test_lookup_returns_none_when_db_none():
    assert await pi.lookup_strategy(None, "a", "BTCUSDT", "Sell") is None


@pytest.mark.asyncio
async def test_write_failopen_when_pool_raises():
    class _Boom:
        class pool:
            @staticmethod
            async def execute(*a, **k):
                raise RuntimeError("db down")
    await pi.write_intent(_Boom(), "a", "BTCUSDT", "Sell", "mean_reversion")  # swallowed


@pytest.mark.asyncio
async def test_lookup_returns_none_when_pool_raises():
    class _Boom:
        class pool:
            @staticmethod
            async def fetchrow(*a, **k):
                raise RuntimeError("db down")
    assert await pi.lookup_strategy(_Boom(), "a", "BTCUSDT", "Sell") is None


# --- reconciler enrichment (orphan recovers strategy instead of mislabeling) ------

class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _ReconPool(_FakePool):
    """Adds the acquire()/conn.fetch() surface the reconciler uses for stalled trades."""

    def acquire(self):
        pool = self

        class _Conn:
            async def fetch(self, *a, **k):
                return []  # no stalled / zero-pnl trades

        return _AcquireCtx(_Conn())


class _ReconDB:
    def __init__(self):
        self.pool = _ReconPool()


class _StubClient:
    def __init__(self, positions):
        self._positions = positions

    async def get_positions(self):
        return self._positions


class _StubAccountsSvc:
    def __init__(self, client):
        self._client = client

    async def get_client(self, account_id):
        return self._client


class _StubTradeSvc:
    def __init__(self, open_trades):
        self._open = open_trades

    async def get_open_trades(self, account_id, limit=500):
        return list(self._open)


class _CaptureWS:
    def __init__(self):
        self.events = []

    async def broadcast_to_account(self, account_id, event, payload):
        self.events.append((account_id, event, payload))


@pytest.mark.asyncio
async def test_orphan_recovers_mean_reversion_strategy_from_intent():
    from backend.services.position_reconciler import PositionReconciler

    db = _ReconDB()
    # An MR order filled but its trades-row write failed -> pre-submit intent survives.
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "mean_reversion")

    # Exchange shows the orphan position; one unrelated DB trade keeps us past the
    # early-return (candidates non-empty). Its matching exchange position makes it
    # neither stale nor orphan, so all_to_process stays empty (early return after
    # the orphan broadcast) and no downstream trade reconciliation runs.
    positions = [
        {"symbol": "BTCUSDT", "side": "Sell", "size": "1"},   # orphan (no DB trade)
        {"symbol": "ETHUSDT", "side": "Buy", "size": "1"},    # matches the DB trade
    ]
    open_trades = [{"symbol": "ETHUSDT", "side": "Buy", "status": "open"}]

    ws = _CaptureWS()
    rec = PositionReconciler(
        db, _StubAccountsSvc(_StubClient(positions)), _StubTradeSvc(open_trades), ws_manager=ws)
    await rec._reconcile_account("acct1")

    orphan_events = [e for e in ws.events if e[1] == "orphan_position_detected"]
    assert len(orphan_events) == 1
    payload = orphan_events[0][2]
    assert payload["symbol"] == "BTCUSDT" and payload["side"] == "Sell"
    assert payload["strategy_kind"] == "mean_reversion"
    assert "mean_reversion" in payload["message"]


@pytest.mark.asyncio
async def test_orphan_without_intent_reports_unknown_not_trend():
    from backend.services.position_reconciler import PositionReconciler

    db = _ReconDB()  # no intent written
    positions = [
        {"symbol": "BTCUSDT", "side": "Sell", "size": "1"},   # orphan
        {"symbol": "ETHUSDT", "side": "Buy", "size": "1"},    # matches the DB trade
    ]
    open_trades = [{"symbol": "ETHUSDT", "side": "Buy", "status": "open"}]

    ws = _CaptureWS()
    rec = PositionReconciler(
        db, _StubAccountsSvc(_StubClient(positions)), _StubTradeSvc(open_trades), ws_manager=ws)
    await rec._reconcile_account("acct1")

    payload = [e for e in ws.events if e[1] == "orphan_position_detected"][0][2]
    # never silently 'trend' — strategy_kind is None and message stays generic
    assert payload["strategy_kind"] is None
    assert "mean_reversion" not in payload["message"]


@pytest.mark.asyncio
async def test_reconciler_sweep_gc_collects_stale_intents():
    # The per-sweep reconcile loop must garbage-collect abandoned intents so a
    # rejected/never-filled MR order can't mislabel a later orphan (FR-051).
    from backend.services.position_reconciler import PositionReconciler

    db = _ReconDB()
    # one fresh + one aged-out intent
    await pi.write_intent(db, "acct1", "BTCUSDT", "Sell", "mean_reversion")
    db.pool.rows[("acct1", "BTCUSDT", "Sell")]["created_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=180))
    await pi.write_intent(db, "acct1", "ETHUSDT", "Buy", "mean_reversion")

    # no active accounts -> the loop body is skipped but the gc sweep still runs
    db.list_accounts = _noop_list  # type: ignore[attr-defined]
    rec = PositionReconciler(db, _StubAccountsSvc(_StubClient([])), _StubTradeSvc([]))
    await rec._reconcile_all_accounts()

    assert await pi.lookup_strategy(db, "acct1", "BTCUSDT", "Sell") is None  # swept
    assert await pi.lookup_strategy(db, "acct1", "ETHUSDT", "Buy") == "mean_reversion"  # kept


async def _noop_list():
    return []
