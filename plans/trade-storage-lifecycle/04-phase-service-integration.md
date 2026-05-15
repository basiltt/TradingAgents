# Phase 4: TradeService & Integration

## Goal
Create TradeService orchestration layer and integrate trade storage into existing place_trade, close-all, rule-triggered close, and cycle trade flows. Wire DI in main.py.

## Entry Criteria
- Phase 3 complete (endpoints exist, schemas defined)

## Files to Create
- `backend/services/trade_service.py`
- `tests/test_trade_service.py`

## Files to Modify
- `backend/services/accounts_service.py` — add get_client(), modify place_trade()
- `backend/services/close_positions_service.py` — integrate with TradeService
- `backend/services/trading_cycle_engine.py` — insert trade with source=cycle
- `backend/services/close_rule_evaluator.py` — pass rule_id
- `backend/services/account_ws_manager.py` — add trade broadcast methods
- `backend/main.py` — wire TradeRepository, TradeService into app.state

## Shared Context (from Phase 2)
- `TradeRepository` is available at `app.state.trade_repo`
- Custom exceptions: `TradeNotFound`, `InvalidStatusTransition`, `ConcurrentModification`
- State machine: `VALID_TRANSITIONS`, `TERMINAL_STATUSES`

## Tasks

### TASK-029: Add get_client() to AccountsService
**Requirement IDs:** FR-041 (DI pattern)
**File:** `backend/services/accounts_service.py`

Add public method wrapping existing private `_build_client`:
```python
async def get_client(self, account_id: str) -> BybitClient:
    return await self._build_client(account_id)
```

### TASK-030: Create TradeService class
**Requirement IDs:** FR-011, FR-016, FR-019, FR-020, FR-021, FR-022, FR-032, FR-048, FR-049, FR-055
**File:** `backend/services/trade_service.py`

```python
import logging
from backend.services.trade_repository import (
    TradeRepository, InvalidStatusTransition, ConcurrentModification, TradeNotFound
)
from backend.services.accounts_service import AccountsService

logger = logging.getLogger(__name__)

class TradeService:
    def __init__(self, db: AsyncAnalysisDB, trade_repo: TradeRepository,
                 accounts_service: AccountsService,
                 ws_manager=None) -> None:
        self._db = db
        self._repo = trade_repo
        self._accounts = accounts_service
        self._ws = ws_manager
        self._stats_cache: dict[str, tuple[float, dict]] = {}
        self._STATS_CACHE_TTL = 10.0
        self._STATS_CACHE_MAX = 1000

    async def get_cached_stats(self, account_id: str) -> dict:
        import time
        now = time.monotonic()
        cached = self._stats_cache.get(account_id)
        if cached and (now - cached[0]) < self._STATS_CACHE_TTL:
            return cached[1]
        async with self._db.pool.acquire() as conn:
            stats = await self._repo.get_trade_stats(conn, account_id=account_id)
        # Evict if at capacity
        if len(self._stats_cache) >= self._STATS_CACHE_MAX and account_id not in self._stats_cache:
            oldest_key = min(self._stats_cache, key=lambda k: self._stats_cache[k][0])
            del self._stats_cache[oldest_key]
        self._stats_cache[account_id] = (now, stats)
        return stats

    def _invalidate_stats_cache(self, account_id: str) -> None:
        self._stats_cache.pop(account_id, None)
```

### TASK-031: Implement close_single_trade()
**Requirement IDs:** FR-011, FR-016, FR-019, FR-020, FR-040, FR-055
**File:** `backend/services/trade_service.py`

```python
async def close_single_trade(self, account_id: str, trade_id: str,
                             qty: float | None = None) -> dict:
```

Flow:
1. Get trade from repo (IDOR-safe)
2. If not found → raise TradeNotFound
3. If qty provided and qty < trade.qty → partial close flow:
   a. Set parent status=closing (optimistic lock)
   b. Call Bybit close with reduce-only for qty
   c. On success: create child trade via `repo.create_child_trade()`, set parent to partially_closed
   d. On Bybit failure: revert parent to open; before reverting, check Bybit position — if gone, reconcile_close() instead (FR-055)
4. If no qty (full close):
   a. Set status=closing (optimistic lock)
   b. Call Bybit close reduce-only
   c. On success: close_trade() with PnL from Bybit response
   d. On Bybit failure: check position status; if gone → reconcile_close(); else revert to open. **On revert: catch ConcurrentModification and log warning with trade_id — reconciliation will pick up stuck "closing" trades within 60s.**
5. Post-commit: broadcast WS event (fire-and-forget), invalidate stats cache
6. Return updated trade

**WebSocket broadcast (FR-048, FR-049):**
```python
async def _broadcast_trade_event(self, event_type: str, trade: dict) -> None:
    if not self._ws:
        return
    try:
        if event_type == 'trade.closed':
            payload = {
                "trade_id": str(trade["id"]),
                "account_id": trade["account_id"],
                "symbol": trade["symbol"],
                "close_reason": trade.get("close_reason"),
                "realized_pnl": float(trade["realized_pnl"]) if trade.get("realized_pnl") else None,
                "exit_price": float(trade["exit_price"]) if trade.get("exit_price") else None,
            }
        elif event_type == 'trade.opened':
            payload = {
                "trade_id": str(trade["id"]),
                "account_id": trade["account_id"],
                "symbol": trade["symbol"],
                "side": trade["side"],
                "qty": float(trade["qty"]),
                "entry_price": float(trade["entry_price"]) if trade.get("entry_price") else None,
                "status": trade["status"],
            }
        elif event_type == 'trade.close_failed':
            payload = {
                "trade_id": str(trade["id"]),
                "account_id": trade["account_id"],
                "error_code": trade.get("metadata", {}).get("error_code", "UNKNOWN"),
            }
        else:
            return
        await self._ws.broadcast_to_account(trade["account_id"], event_type, payload)
    except Exception:
        logger.warning("ws_broadcast_failed", extra={"event_type": event_type, "trade_id": str(trade["id"])})
```

### TASK-032: Implement cancel_trade()
**Requirement IDs:** FR-021, FR-022
**File:** `backend/services/trade_service.py`

```python
async def cancel_trade(self, account_id: str, trade_id: str) -> dict:
```

Flow:
1. Get trade (IDOR-safe)
2. If status == 'pending':
   a. Cancel on Bybit (if order_id exists)
   b. Update to status=cancelled
3. If status == 'partially_filled':
   a. Cancel unfilled remainder on Bybit
   b. Adjust qty to filled_qty
   c. Transition to status=open (filled portion becomes live position)
4. Post-commit: broadcast, invalidate cache
5. Return updated trade

### TASK-033: Modify AccountsService.place_trade()
**Requirement IDs:** FR-001, FR-002, FR-003, FR-005, FR-006, FR-010, FR-039
**File:** `backend/services/accounts_service.py`

Modify the existing `place_trade()` method:
1. **Before** Bybit call: `trade = await trade_repo.create_trade(conn, account_id=account_id, symbol=symbol, side=side, qty=qty, ...)` — returns trade with status=pending
2. Call Bybit as before
3. **On success:** `await trade_repo.update_trade_status(conn, trade_id=trade['id'], ..., new_status='open', updates={'order_id': result['orderId'], 'entry_price': ..., 'opened_at': NOW()})`, broadcast trade.opened
4. **On failure:** `await trade_repo.update_trade_status(conn, ..., new_status='failed', updates={'metadata': sanitized_error})` — sanitize Bybit error per FR-039
5. Return TradeResponse dict instead of raw Bybit dict (**BREAKING CHANGE**)

**Error sanitization (FR-039):**
```python
def _sanitize_bybit_error(self, error: dict) -> dict:
    return {
        "error_code": str(error.get("retCode", "UNKNOWN")),
        "error_message": str(error.get("retMsg", ""))[:200],
    }
```

### TASK-034: Modify ClosePositionsService
**Requirement IDs:** FR-012, FR-013
**File:** `backend/services/close_positions_service.py`

In `close_all_positions()`:
- After closing a Bybit position for (symbol, side), query `trade_repo.get_open_trades_by_symbol_side(account_id, symbol, side)`
- For each matching trade, call `trade_service.close_single_trade()` with close_reason='manual_close_all'
- Pass trade_service as constructor dependency or obtain from app.state

In `close_all_for_rule()`:
- Same pattern but close_reason='rule_triggered', close_rule_id=rule_id

### TASK-035: Modify TradingCycleEngine
**Requirement IDs:** FR-009
**File:** `backend/services/trading_cycle_engine.py`

After each trade placement in `_execute_cycle()`:
- Call `trade_repo.create_trade(conn, ..., source='cycle', source_id=cycle.id)`

### TASK-036: Pass rule_id in CloseRuleEvaluator
**Requirement IDs:** FR-013
**File:** `backend/services/close_rule_evaluator.py`

Ensure rule_id is passed through to `close_all_for_rule()` call.

### TASK-037: Add trade broadcast methods to AccountWSManager
**Requirement IDs:** FR-032, FR-048
**File:** `backend/services/account_ws_manager.py`

Add method if not already present:
```python
async def broadcast_to_account(self, account_id: str, event_type: str, payload: dict) -> None:
```

### TASK-038: Wire DI in main.py
**Requirement IDs:** FR-041
**File:** `backend/main.py`

**IMPORTANT:** All account-related services are guarded by `if os.environ.get("ACCOUNTS_ENCRYPTION_KEY"):` (line ~175). TradeRepository, TradeService, and TradeReconciliationService MUST be wired inside this same guard block, since TradeService depends on AccountsService.

In the `if os.environ.get("ACCOUNTS_ENCRYPTION_KEY"):` block, after AccountsService is created:
```python
trade_repo = TradeRepository(db=app.state.db)
trade_service = TradeService(
    db=app.state.db,
    trade_repo=trade_repo,
    accounts_service=app.state.accounts_service,
    ws_manager=app.state.ws_manager,
)
app.state.trade_repo = trade_repo
app.state.trade_service = trade_service
```

In the `else` branch (line ~228-234), add:
```python
app.state.trade_repo = None
app.state.trade_service = None
app.state.recon_service = None
```

API endpoints must handle `None` service gracefully — return 503 if `request.app.state.trade_service is None`.

### TASK-039: Update DELETE /accounts endpoint for FK handling
**Requirement IDs:** (from R3 backend finding)
**File:** `backend/routers/accounts.py`

In the delete_account handler, catch IntegrityError and return:
```python
except asyncpg.ForeignKeyViolationError:
    return JSONResponse(status_code=409, content={"detail": "Cannot delete account with existing trades", "code": "ACCOUNT_HAS_TRADES"})
```

### TASK-040: Remove Phase 3 test skips, write integration tests
**File:** `tests/test_trade_service.py`

Test cases:
1. `test_close_single_trade_full` — AC-002
2. `test_close_single_trade_partial` — AC-010
3. `test_cancel_pending_trade` — AC-011
4. `test_cancel_partially_filled_trade` — AC-012
5. `test_close_already_closed_409` — Edge case
6. `test_close_concurrent_modification` — AC-009
7. `test_place_trade_creates_record` — AC-001, AC-018
8. `test_place_trade_bybit_failure_marks_failed` — AC-018
9. `test_close_all_maps_positions_to_trades` — AC-003
10. `test_rule_triggered_close` — AC-004
11. `test_ws_broadcast_on_close` — FR-032
12. `test_ws_broadcast_fire_and_forget` — FR-049
13. `test_close_failure_checks_position` — FR-055, AC-016: assert ws_manager.broadcast_to_account called with event_type='trade.close_failed', payload contains 'error_code', no API keys in payload
14. `test_stats_cache_invalidated_on_close` — close a trade → get_cached_stats returns fresh data (not stale)
15. `test_partial_close_failure_position_gone_reconciles` — partial close Bybit failure + position gone → reconcile_close
16. `test_stats_cache_eviction_at_capacity` — fill cache to max, insert one more, assert oldest evicted

Also update `tests/test_trade_api.py` — remove `@pytest.mark.skip("Phase 4")` from close/cancel tests.

## Exit Criteria
- TradeService fully functional
- place_trade creates trade records
- close/cancel endpoints work end-to-end
- WS broadcasts fire on trade events
- DI wired in main.py
- All integration tests pass
- Existing tests pass (regression)

## Verification Commands
```bash
python -m pytest tests/test_trade_service.py -x -q --tb=short
python -m pytest tests/test_trade_api.py -x -q --tb=short
python -m pytest tests/ -x -q --tb=short
```

## Traceability
| Task | FRs | ACs |
|------|-----|-----|
| TASK-029 | FR-041 | — |
| TASK-030/031 | FR-011,016,019,020,032,048,049,055 | AC-002,010,016 |
| TASK-032 | FR-021,022 | AC-011,012 |
| TASK-033 | FR-001,002,003,005,006,010,039 | AC-001,018 |
| TASK-034 | FR-012,013 | AC-003,004 |
| TASK-035 | FR-009 | — |
| TASK-036 | FR-013 | AC-004 |
| TASK-037 | FR-032,048 | — |
| TASK-038 | FR-041 | — |
| TASK-039 | — | — |
