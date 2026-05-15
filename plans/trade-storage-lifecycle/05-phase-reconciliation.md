# Phase 5: TradeReconciliationService

## Goal
Create background reconciliation service that periodically syncs local trade records with Bybit positions, detects TP/SL fills, cleans up orphaned trades, and resolves stuck closing states.

## Entry Criteria
- Phase 4 complete (TradeService functional, trade records being created)

## Files to Create
- `backend/services/trade_reconciliation.py`
- `tests/test_trade_reconciliation.py`

## Shared Context (from prior phases)
- `TradeRepository` at `app.state.trade_repo` — `get_open_trades()`, `reconcile_close()`, `get_pending_orphans()`, `update_trade_status()`
- `AccountsService` at `app.state.accounts_service` — `get_client()` for Bybit access
- Advisory lock key: `(7001, 1)`
- Reconciliation interval: 60 seconds
- Orphan timeout: 5 minutes

## Tasks

### TASK-041: Create TradeReconciliationService class
**Requirement IDs:** FR-023, FR-024, FR-026, FR-038
**File:** `backend/services/trade_reconciliation.py`

```python
import asyncio
import logging
from backend.services.trade_repository import TradeRepository
from backend.services.accounts_service import AccountsService

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = (7001, 1)
RECONCILIATION_INTERVAL = 60
ORPHAN_TIMEOUT_MINUTES = 5

class TradeReconciliationService:
    def __init__(self, db: AsyncAnalysisDB, trade_repo: TradeRepository,
                 accounts_service: AccountsService,
                 ws_manager=None) -> None:
        self._db = db
        self._repo = trade_repo
        self._accounts = accounts_service
        self._ws = ws_manager
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
```

### TASK-042: Implement _run_loop() with startup sweep
**Requirement IDs:** FR-023, FR-024, FR-026
**File:** `backend/services/trade_reconciliation.py`

```python
async def _run_loop(self) -> None:
    # Startup sweep (FR-024)
    await self._sweep_all_accounts()
    # Periodic loop (FR-023)
    while self._running:
        await asyncio.sleep(RECONCILIATION_INTERVAL)
        if not self._running:
            break
        await self._sweep_all_accounts()

async def _sweep_all_accounts(self) -> None:
    # Acquire advisory lock (non-blocking) on a dedicated connection held for sweep duration
    lock_conn = await self._db.pool.acquire()
    try:
        locked = await lock_conn.fetchval(
            "SELECT pg_try_advisory_lock($1, $2)", *ADVISORY_LOCK_KEY
        )
        if not locked:
            logger.debug("reconciliation_lock_held_skipping")
            return
        try:
            # Get accounts with open trades (short query on lock conn)
            accounts = await lock_conn.fetch(
                "SELECT DISTINCT account_id FROM trades WHERE status IN ('open', 'partially_filled', 'closing', 'partially_closed')"
            )

            # Sweep each account — uses separate connections for DB reads/writes
            # Bybit API calls happen WITHOUT holding any pooled connection
            for account_row in accounts:
                account_id = account_row["account_id"]
                try:
                    await self._sweep_account(account_id)
                except Exception:
                    logger.exception("reconciliation_account_error", extra={"account_id": account_id})

            # Orphan cleanup — acquire fresh connection
            async with self._db.pool.acquire() as conn:
                await self._cleanup_orphans(conn)
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1, $2)", *ADVISORY_LOCK_KEY)
    finally:
        await self._db.pool.release(lock_conn)
```

### TASK-043: Implement _sweep_account()
**Requirement IDs:** FR-014, FR-015, FR-038, FR-051, NFR-003
**File:** `backend/services/trade_reconciliation.py`

```python
async def _sweep_account(self, account_id: str) -> None:
    import time
    start = time.monotonic()

    # DB read: get local open trades (short-lived connection)
    async with self._db.pool.acquire() as conn:
        open_trades = await self._repo.get_open_trades(conn, account_id=account_id)
    open_by_order_id = {t["order_id"]: t for t in open_trades if t.get("order_id")}

    # Bybit calls — NO connection held
    try:
        client = await self._accounts.get_client(account_id)
        positions = await client.get_positions()
    except Exception:
        logger.warning("reconciliation_bybit_error", extra={"account_id": account_id})
        return

    # Build set of Bybit position symbols (normalize side to match DB casing)
    bybit_symbols = set()
    for pos in positions:
        if float(pos.get("size", 0)) > 0:
            bybit_symbols.add((pos["symbol"], pos["side"]))

    discrepancies = 0

    # Check each local open trade against Bybit
    # Note: DB stores side as 'Buy'/'Sell' (Bybit-native casing) — invariant enforced by CHECK constraint
    for trade in open_trades:
        key = (trade["symbol"], trade["side"])
        if key not in bybit_symbols and trade["status"] in ("open", "partially_filled", "closing"):
            # Position gone on Bybit — likely TP/SL/liquidation
            discrepancies += 1
            await self._resolve_closed_position(trade, client)

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info("reconciliation_sweep", extra={
        "account_id": account_id,
        "open_count": len(open_trades),
        "discrepancies_found": discrepancies,
        "elapsed_ms": round(elapsed_ms, 1),
    })
```

### TASK-044: Implement _resolve_closed_position()
**Requirement IDs:** FR-014, FR-015, FR-051
**File:** `backend/services/trade_reconciliation.py`

```python
async def _resolve_closed_position(self, trade: dict, client) -> None:
    # Bybit call — no connection held
    try:
        closed_pnl = await client.get_closed_pnl(symbol=trade["symbol"], limit=20)
    except Exception:
        logger.warning("reconciliation_pnl_fetch_error", extra={"trade_id": str(trade["id"])})
        return

    # Match by order_id (time-proximity matching deferred — see spec appendix)
    matched_pnl = None
    for record in closed_pnl:
        if record.get("orderId") == trade.get("order_id"):
            matched_pnl = record
            break

    if matched_pnl:
        close_reason = self._determine_close_reason(matched_pnl)
        exit_price = float(matched_pnl.get("avgExitPrice", 0))
        realized_pnl = float(matched_pnl.get("closedPnl", 0))
        fees = abs(float(matched_pnl.get("cumExecFee", 0)))
        entry_price = float(trade.get("entry_price") or trade.get("avg_fill_price") or 0)
        pnl_pct = (realized_pnl / (entry_price * float(trade["qty"])) * 100) if entry_price and float(trade["qty"]) else 0

        # DB write — short-lived connection with explicit transaction
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                await self._repo.reconcile_close(
                    conn, trade_id=str(trade["id"]), account_id=trade["account_id"],
                    exit_price=exit_price, realized_pnl=realized_pnl,
                    realized_pnl_pct=pnl_pct, fees=fees, close_reason=close_reason,
                )
                trade_updated = await self._repo.get_trade(conn, account_id=trade["account_id"], trade_id=str(trade["id"]))
        if self._ws and trade_updated:
            try:
                await self._ws.broadcast_to_account(trade["account_id"], "trade.closed", {
                    "trade_id": str(trade["id"]),
                    "account_id": trade["account_id"],
                    "symbol": trade["symbol"],
                    "close_reason": close_reason,
                    "realized_pnl": realized_pnl,
                    "exit_price": exit_price,
                })
            except Exception:
                logger.warning("ws_broadcast_failed", extra={"trade_id": str(trade["id"])})
    else:
        logger.warning("reconciliation_no_pnl_match", extra={"trade_id": str(trade["id"]), "order_id": trade.get("order_id")})

def _determine_close_reason(self, pnl_record: dict) -> str:
    exec_type = pnl_record.get("execType", "")
    if exec_type == "BustTrade":
        return "liquidation"
    if exec_type == "AdlTrade":
        return "adl"
    # Check if TP or SL by comparing close price to stopLoss/takeProfit
    # Heuristic: if filled at TP price → take_profit, SL price → stop_loss
    order_type = pnl_record.get("orderType", "")
    if "TakeProfit" in order_type or "TP" in str(pnl_record.get("stopOrderType", "")):
        return "take_profit"
    if "StopLoss" in order_type or "SL" in str(pnl_record.get("stopOrderType", "")):
        return "stop_loss"
    return "external"
```

### TASK-045: Implement _cleanup_orphans()
**Requirement IDs:** FR-025
**File:** `backend/services/trade_reconciliation.py`

```python
async def _cleanup_orphans(self, conn) -> None:
    orphans = await self._repo.get_pending_orphans(conn, max_age_minutes=ORPHAN_TIMEOUT_MINUTES)
    for trade in orphans:
        try:
            await self._repo.update_trade_status(
                conn, trade_id=str(trade["id"]), account_id=trade["account_id"],
                expected_version=trade["version"], new_status="failed",
                event_type="failed", actor="reconciliation",
                event_payload={"reason": "orphaned_pending_timeout"},
            )
            logger.info("orphan_cleaned", extra={"trade_id": str(trade["id"])})
        except Exception:
            logger.exception("orphan_cleanup_error", extra={"trade_id": str(trade["id"])})
```

### TASK-046: Wire reconciliation in main.py
**Requirement IDs:** FR-024
**File:** `backend/main.py`

In startup:
```python
recon_service = TradeReconciliationService(
    db=app.state.db,
    trade_repo=trade_repo,
    accounts_service=app.state.accounts_service,
    ws_manager=app.state.ws_manager,
)
app.state.recon_service = recon_service
await recon_service.start()
```

In shutdown:
```python
if hasattr(app.state, 'recon_service'):
    await app.state.recon_service.stop()
```

### TASK-047: Write reconciliation tests
**File:** `tests/test_trade_reconciliation.py`

Test cases:
1. `test_startup_sweep_runs_immediately` — FR-024
2. `test_sweep_detects_tp_fill` — AC-005
3. `test_sweep_detects_sl_fill` — AC-006
4. `test_sweep_orphan_cleanup` — AC-007
5. `test_advisory_lock_prevents_concurrent_sweeps` — FR-026
6. `test_advisory_lock_skip_if_held` — FR-026
7. `test_sweep_logs_structured_output` — FR-038
8. `test_bybit_error_skips_account` — Robustness
9. `test_reconcile_stuck_closing` — AC-017
10. `test_determine_close_reason_liquidation` — FR-015
11. `test_determine_close_reason_external` — FR-015
12. `test_ws_broadcast_after_reconcile` — FR-032
13. `test_sweep_no_pnl_match_leaves_trade_open` — trade stays open when no PnL record matches

## Exit Criteria
- Reconciliation service starts on app startup
- Startup sweep executes before loop
- Advisory locking prevents concurrent sweeps
- TP/SL detection works
- Orphan cleanup works
- All reconciliation tests pass

## Verification Commands
```bash
python -m pytest tests/test_trade_reconciliation.py -x -q --tb=short
python -m pytest tests/ -x -q --tb=short
```

## Traceability
| Task | FRs | ACs |
|------|-----|-----|
| TASK-041/042 | FR-023,024,026 | — |
| TASK-043 | FR-014,015,038 | AC-005,006 |
| TASK-044 | FR-014,015,051 | AC-005,006,017 |
| TASK-045 | FR-025 | AC-007 |
| TASK-046 | FR-024 | — |
