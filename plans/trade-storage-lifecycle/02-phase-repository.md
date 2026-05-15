# Phase 2: TradeRepository

## Goal
Create `TradeRepository` — pure data access layer for trades and trade_events with state machine validation, optimistic locking, and keyset pagination.

## Entry Criteria
- Phase 1 complete (tables exist)
- Migration tests pass

## Files to Create
- `backend/services/trade_repository.py`
- `tests/test_trade_repository.py`

## Shared Constants (used by Phases 3-5)

```python
VALID_STATUSES = {'pending', 'open', 'partially_filled', 'closing', 'partially_closed', 'closed', 'failed', 'cancelled'}
TERMINAL_STATUSES = {'closed', 'failed', 'cancelled'}

VALID_TRANSITIONS = {
    'pending': {'open', 'failed', 'cancelled', 'partially_filled'},
    'open': {'closing', 'partially_closed'},
    'partially_filled': {'open', 'closing'},
    'closing': {'closed', 'open', 'partially_closed'},
    'partially_closed': {'closing', 'closed'},
}

SORT_COLUMNS = {
    'created_at': 't.created_at',
    'opened_at': 't.opened_at',
    'closed_at': 't.closed_at',
    'realized_pnl': 't.realized_pnl',
}

METADATA_ALLOWLIST = {
    'error_code', 'error_message', 'reason', 'detected_at',
    'bybit_exec_id', 'parent_trade_id', 'child_qty',
}

SYMBOL_PATTERN = r"^[A-Z0-9/]{1,30}$"

UPDATABLE_COLUMNS = {
    'order_id', 'entry_price', 'avg_fill_price', 'exit_price',
    'mark_price_at_open', 'opened_at', 'filled_qty',
    'stop_loss_price', 'take_profit_price',
}

VALID_SIDES = {'Buy', 'Sell'}

VALID_CLOSE_REASONS = {
    'manual', 'stop_loss', 'take_profit', 'liquidation',
    'reconciliation', 'signal', 'partial_close', 'close_rule',
    'balance_below', 'balance_above', 'equity_drop', 'equity_rise',
    'pnl_loss', 'pnl_profit',
}

VALID_EVENT_TYPES = {
    'placed', 'filled', 'partially_filled', 'closing',
    'closed', 'cancelled', 'failed', 'reconciled',
}
```

## Tasks

### TASK-006: Create TradeRepository class skeleton
**Requirement IDs:** FR-041
**File:** `backend/services/trade_repository.py`
**Action:** Create class with DI constructor

```python
from __future__ import annotations
import uuid
import json
import logging
from typing import Any
from backend.async_persistence import AsyncAnalysisDB

logger = logging.getLogger(__name__)

class TradeRepository:
    def __init__(self, db: AsyncAnalysisDB) -> None:
        self._db = db
```

### TASK-007: Implement create_trade()
**Requirement IDs:** FR-001, FR-004, FR-005, FR-006, FR-009, FR-010, FR-044
**File:** `backend/services/trade_repository.py`

```python
async def create_trade(self, conn, *, account_id: str, symbol: str, side: str,
                       qty: float, leverage: int = 1, margin_mode: str = 'isolated',
                       order_type: str = 'market', source: str = 'manual',
                       source_id: int | None = None, position_idx: int = 0,
                       stop_loss_price: float | None = None,
                       take_profit_price: float | None = None,
                       mark_price_at_open: float | None = None,
                       capital_pct: float | None = None,
                       base_capital: float | None = None,
                       signal_direction: str | None = None,
                       trade_direction: str | None = None,
                       take_profit_pct: float | None = None,
                       stop_loss_pct: float | None = None,
                       metadata: dict | None = None) -> dict:
```

- Generate `order_link_id = str(uuid.uuid4())`
- Validate metadata keys against `METADATA_ALLOWLIST` if metadata provided
- Validate `octet_length(json.dumps(metadata)) < 8192`
- INSERT into trades with status='pending', version=0
- INSERT into trade_events with event_type='placed', new_status='pending', actor based on source
- Return the created trade row as dict
- Use parameterized queries ($1, $2, etc.)

### TASK-008: Implement update_trade_status() with optimistic locking
**Requirement IDs:** FR-017, FR-018, FR-037, NFR-011
**File:** `backend/services/trade_repository.py`

```python
async def update_trade_status(self, conn, *, trade_id: str, account_id: str,
                              expected_version: int, new_status: str,
                              updates: dict[str, Any] | None = None,
                              event_type: str | None = None,
                              actor: str = 'system',
                              event_payload: dict | None = None) -> dict | None:
```

- Validate `new_status` is in `VALID_STATUSES`
- Validate `event_type` against `VALID_EVENT_TYPES` if provided (before any DB access)
- Validate `updates` keys against `UPDATABLE_COLUMNS` allowlist
- Fetch current trade: `SELECT status FROM trades WHERE id = $1 AND account_id = $2 FOR UPDATE` (pessimistic + optimistic locking)
- If not found, return None
- Validate state transition: `current_status -> new_status` against `VALID_TRANSITIONS`
- If invalid transition, raise `InvalidStatusTransition(current_status, new_status)`
- UPDATE with optimistic lock: `UPDATE trades SET status=$1, version=version+1, ... WHERE id=$2 AND version=$3`
- If 0 rows affected, raise `ConcurrentModification(trade_id)`
- Create trade_event with old_status, new_status, event_type, actor
- Log structured entry: `logger.info("trade_status_changed", extra={"trade_id": ..., "old_status": ..., "new_status": ..., "latency_ms": ...})`
- Return updated trade dict

**Custom exceptions (define at module level):**
```python
class TradeNotFound(Exception): pass
class InvalidStatusTransition(Exception): pass
class ConcurrentModification(Exception): pass
```

### TASK-009: Implement close_trade()
**Requirement IDs:** FR-016, FR-011, FR-012, FR-013
**File:** `backend/services/trade_repository.py`

```python
async def close_trade(self, conn, *, trade_id: str, account_id: str,
                      expected_version: int, exit_price: float,
                      realized_pnl: float, realized_pnl_pct: float,
                      fees: float, close_reason: str,
                      close_rule_id: str | None = None) -> dict | None:
```

- Compute `net_pnl = realized_pnl - fees` — **UPDATED: net_pnl passed by caller** (business logic moved to TradeService per review)
- Set `closed_at = NOW()`
- **UPDATED:** Uses direct SQL (SELECT FOR UPDATE + UPDATE with version check) instead of delegating to `update_trade_status()` — avoids complexity with PnL/close-specific fields
- Create trade_event with event_type='closed', actor='system'
- Return updated trade

### TASK-010: Implement reconcile_close()
**Requirement IDs:** FR-051
**File:** `backend/services/trade_repository.py`

```python
async def reconcile_close(self, conn, *, trade_id: str, account_id: str,
                          exit_price: float, realized_pnl: float,
                          realized_pnl_pct: float, fees: float,
                          close_reason: str) -> dict:
```

- **UPDATED:** Single transition with `version=version+1` and one trade_event (event_type='reconciled') — simplified from planned double-transition per review. `net_pnl` passed by caller.
- Use `SELECT ... FOR UPDATE` to prevent concurrent close_trade() from racing:
  `SELECT status, version FROM trades WHERE id = $1 AND account_id = $2 AND status IN ('open', 'partially_filled', 'closing', 'partially_closed') FOR UPDATE`
- If no row matched, raise `ConcurrentModification` (another thread already closed it)
- `UPDATE trades SET status='closed', version=version+1, exit_price=$1, ... WHERE id=$2 AND version=$3`
- Create one trade_event with event_type='reconciled', actor='reconciliation'
- Return updated trade dict

### TASK-011: Implement get_trade() and get_trade_with_events()
**Requirement IDs:** FR-029, FR-033, FR-054
**File:** `backend/services/trade_repository.py`

```python
async def get_trade(self, conn, *, account_id: str, trade_id: str) -> dict | None:
    # WHERE id = $1 AND account_id = $2 — single query, IDOR safe
    row = await conn.fetchrow(
        "SELECT * FROM trades WHERE id = $1 AND account_id = $2",
        trade_id, account_id
    )
    return dict(row) if row else None

async def get_trade_with_events(self, conn, *, account_id: str, trade_id: str) -> dict | None:
    trade = await self.get_trade(conn, account_id=account_id, trade_id=trade_id)
    if not trade:
        return None
    events = await conn.fetch(
        "SELECT * FROM trade_events WHERE trade_id = $1 ORDER BY created_at ASC",
        trade_id
    )
    trade['events'] = [dict(e) for e in events]
    return trade
```

### TASK-012: Implement list_trades() with keyset pagination
**Requirement IDs:** FR-027, FR-028, FR-034, FR-042, FR-045, FR-046, FR-059, NFR-001, NFR-010
**File:** `backend/services/trade_repository.py`

```python
async def list_trades(self, conn, *, account_id: str,
                      status: str | None = None,
                      symbol: str | None = None,
                      side: str | None = None,
                      close_reason: str | None = None,
                      from_date: str | None = None,
                      to_date: str | None = None,
                      sort: str = 'created_at',
                      cursor: str | None = None,
                      limit: int = 50,
                      include_total: bool = False,
                      parent_trade_id: str | None = None) -> dict:
```

- Validate sort against `SORT_COLUMNS` keys
- Resolve sort column via `SORT_COLUMNS[sort]` (never interpolate user input)
- If symbol provided, validate against `^[A-Z0-9/]{1,30}$`
- If cursor provided, validate length ≤ 256 bytes, base64-decode, parse components (sort_value, trade_id), validate trade_id is UUID
- Build WHERE clause with parameterized placeholders:
  - Always: `account_id = $N`
  - Optional: `status = $N`, `symbol = $N`, `side = $N`, `close_reason = $N`
  - Optional: `created_at >= $N` (from_date), `created_at <= $N` (to_date)
  - Optional: `parent_trade_id = $N` or `parent_trade_id IS NULL` (top-level only)
  - Cursor: `(sort_col, id) < ($N, $N)` for DESC ordering (handle NULL sort values)
- ORDER BY `{mapped_sort_col} DESC NULLS LAST, id DESC`
- LIMIT `$N` (limit + 1 to detect has_more)
- If include_total, run COUNT query separately
- Build next_cursor from last row's (sort_value, id) base64-encoded
- Return `{"items": [...], "cursor": next_cursor, "has_more": bool, "total": int | None}`

### TASK-013: Implement get_open_trades()
**Requirement IDs:** FR-030, NFR-002
**File:** `backend/services/trade_repository.py`

```python
async def get_open_trades(self, conn, *, account_id: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM trades WHERE account_id = $1 AND status IN ('open', 'partially_filled') ORDER BY created_at DESC",
        account_id
    )
    return [dict(r) for r in rows]
```

### TASK-014: Implement get_trade_stats()
**Requirement IDs:** FR-031, FR-042, FR-056
**File:** `backend/services/trade_repository.py`

```python
async def get_trade_stats(self, conn, *, account_id: str) -> dict:
    row = await conn.fetchrow("""
        SELECT
            COUNT(*) as total_trades,
            COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0), 0) as win_rate,
            COALESCE(AVG(net_pnl), 0) as avg_pnl,
            COALESCE(SUM(net_pnl), 0) as total_pnl,
            AVG(EXTRACT(EPOCH FROM (closed_at - opened_at))) as avg_hold_time
        FROM trades
        WHERE account_id = $1
          AND status = 'closed'
          AND parent_trade_id IS NULL
    """, account_id)
    return {
        "total_trades": row["total_trades"],
        "win_rate": float(row["win_rate"] or 0),
        "avg_pnl": float(row["avg_pnl"] or 0),
        "total_pnl": float(row["total_pnl"] or 0),
        "avg_hold_time": float(row["avg_hold_time"]) if row["avg_hold_time"] else None,
    }
```

### TASK-015: Implement create_child_trade() for partial close
**Requirement IDs:** FR-019, FR-020
**File:** `backend/services/trade_repository.py`

```python
async def create_child_trade(self, conn, *, parent_trade: dict,
                             closed_qty: float, exit_price: float,
                             realized_pnl: float, realized_pnl_pct: float,
                             fees: float, close_reason: str) -> dict:
```

- INSERT new trade with:
  - `parent_trade_id = parent_trade['id']`
  - Copy symbol, side, account_id, entry_price, leverage, etc. from parent
  - `qty = closed_qty`, `status = 'closed'`, `closed_at = NOW()`
  - PnL fields set (including `net_pnl` passed by caller)
  - `source = parent_trade['source']`, `source_id = parent_trade['source_id']`
- Create trade_event for child (closed)
- **Parent update deferred to TradeService (Phase 4)** — repo only creates the child record; service layer handles parent status transition via `update_trade_status()` with proper version locking
- Return child trade dict

### TASK-016: Implement validate_metadata()
**Requirement IDs:** FR-044, NFR-006
**File:** `backend/services/trade_repository.py`

```python
def _validate_metadata(self, metadata: dict) -> None:
    if not metadata:
        return
    invalid_keys = set(metadata.keys()) - METADATA_ALLOWLIST
    if invalid_keys:
        raise ValueError(f"Invalid metadata keys: {invalid_keys}")
    raw = json.dumps(metadata)
    if len(raw.encode('utf-8')) >= 8192:
        raise ValueError("Metadata exceeds 8KB limit")
```

### TASK-017: Implement get_pending_orphans()
**Requirement IDs:** FR-025
**File:** `backend/services/trade_repository.py`

```python
async def get_pending_orphans(self, conn, *, max_age_minutes: int = 5) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM trades WHERE status = 'pending' AND order_id IS NULL "
        "AND created_at < NOW() - INTERVAL '1 minute' * $1",
        max_age_minutes
    )
    return [dict(r) for r in rows]
```

### TASK-018: Implement get_open_trades_by_symbol_side()
**Requirement IDs:** FR-012 (close-all mapping)
**File:** `backend/services/trade_repository.py`

```python
async def get_open_trades_by_symbol_side(self, conn, *, account_id: str,
                                         symbol: str, side: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM trades WHERE account_id = $1 AND symbol = $2 AND side = $3 "
        "AND status IN ('open', 'partially_filled') ORDER BY created_at ASC",
        account_id, symbol, side
    )
    return [dict(r) for r in rows]
```

### TASK-019: Write repository unit tests
**File:** `tests/test_trade_repository.py`
**Test cases (TDD — write FIRST, then implement):**

1. `test_create_trade_returns_pending_with_order_link_id` — FR-001, FR-004
2. `test_create_trade_creates_placed_event` — FR-006
3. `test_create_trade_cycle_source` — FR-009
4. `test_create_trade_invalid_metadata_key_rejected` — FR-044
5. `test_create_trade_metadata_size_limit` — NFR-006
6. `test_update_status_valid_transition` — FR-018
7. `test_update_status_invalid_transition_raises` — FR-018
8. `test_update_status_optimistic_lock_conflict` — FR-017, AC-009
9. `test_update_status_creates_event` — FR-006/007
10. `test_close_trade_sets_pnl_fields` — FR-016, AC-002
11. `test_reconcile_close_atomic_double_transition` — FR-051
12. `test_get_trade_idor_prevention` — FR-054, AC-013
13. `test_list_trades_pagination` — FR-027, AC-008
14. `test_list_trades_filters` — FR-028
15. `test_list_trades_sort_allowlist` — FR-034, AC-014
16. `test_list_trades_invalid_sort_raises` — FR-034
17. `test_list_trades_symbol_validation` — FR-046
18. `test_list_trades_cursor_size_limit` — FR-059
19. `test_get_open_trades` — FR-030
20. `test_get_trade_stats_with_trades` — FR-031
21. `test_get_trade_stats_empty` — FR-056
22. `test_create_child_trade` — FR-019, FR-020, AC-010
23. `test_get_pending_orphans` — FR-025

## Exit Criteria
- All 23 repository tests pass
- Existing tests still pass
- All repository methods have tests

## Verification Commands
```bash
python -m pytest tests/test_trade_repository.py -x -q --tb=short
python -m pytest tests/ -x -q --tb=short
```

## Traceability
| Task | FRs | ACs |
|------|-----|-----|
| TASK-007 | FR-001,004,005,006,009,010,044 | AC-001 |
| TASK-008 | FR-017,018,037 | AC-009 |
| TASK-009 | FR-011,012,013,016 | AC-002,003,004 |
| TASK-010 | FR-051 | AC-017 |
| TASK-011 | FR-029,033,054 | AC-013 |
| TASK-012 | FR-027,028,034,042,045,046,059 | AC-008,014 |
| TASK-013 | FR-030 | — |
| TASK-014 | FR-031,042,056 | — |
| TASK-015 | FR-019,020 | AC-010 |
| TASK-017 | FR-025 | AC-007 |
| TASK-018 | FR-012 | AC-003 |
