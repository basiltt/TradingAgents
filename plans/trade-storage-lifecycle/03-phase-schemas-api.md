# Phase 3: Schemas & API Endpoints

## Goal
Add Pydantic schemas for trade responses and 6 API endpoints with rate limiting, input validation, and cursor-based pagination.

## Entry Criteria
- Phase 2 complete (TradeRepository tested)

## Files to Modify
- `backend/schemas.py` — add Trade* schemas, TradeCloseRequest
- `backend/routers/accounts.py` — add 6 endpoints, rate limiter dependency

## Files to Create
- `tests/test_trade_api.py`

## Tasks

### TASK-020: Add Pydantic schemas to schemas.py
**Requirement IDs:** FR-052
**File:** `backend/schemas.py`

```python
class TradeEventResponse(BaseModel):
    id: int
    trade_id: str
    event_type: str
    old_status: str | None = None
    new_status: str | None = None
    fill_qty: float | None = None
    fill_price: float | None = None
    actor: str
    payload: dict = {}
    created_at: datetime

class TradeResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    side: str
    order_type: str
    qty: float
    filled_qty: float | None = None
    entry_price: float | None = None
    avg_fill_price: float | None = None
    exit_price: float | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    leverage: int
    margin_mode: str
    status: str
    order_id: str | None = None
    order_link_id: str | None = None
    close_reason: str | None = None
    close_rule_id: str | None = None
    parent_trade_id: str | None = None
    realized_pnl: float | None = None
    realized_pnl_pct: float | None = None
    fees: float | None = None
    net_pnl: float | None = None
    source: str
    source_id: int | None = None
    version: int
    metadata: dict = {}
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

class TradeDetailResponse(TradeResponse):
    events: list[TradeEventResponse] = []

class TradeListResponse(BaseModel):
    items: list[TradeResponse]
    cursor: str | None = None
    has_more: bool
    total: int | None = None

class TradeStatsResponse(BaseModel):
    total_trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    avg_hold_time: float | None = None

class TradeCloseRequest(BaseModel):
    qty: float | None = None

    @field_validator('qty')
    @classmethod
    def qty_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError('qty must be positive')
        return v
```

### TASK-021: Implement rate limiter dependency
**Requirement IDs:** FR-043, FR-058
**File:** `backend/routers/accounts.py`

```python
import time
from collections import defaultdict

class _TokenBucket:
    def __init__(self, rate: float = 10.0, capacity: float = 10.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

_rate_limiters: dict[str, _TokenBucket] = {}
_RATE_LIMITER_MAX_ENTRIES = 1000
_RATE_LIMITER_STALE_SECONDS = 3600  # evict entries idle > 1 hour

async def _check_rate_limit(account_id: str) -> None:
    now = time.monotonic()
    # Evict stale entries if at capacity
    if len(_rate_limiters) >= _RATE_LIMITER_MAX_ENTRIES:
        stale = [k for k, v in _rate_limiters.items() if now - v.last_refill > _RATE_LIMITER_STALE_SECONDS]
        for k in stale:
            del _rate_limiters[k]
    if account_id not in _rate_limiters:
        if len(_rate_limiters) >= _RATE_LIMITER_MAX_ENTRIES:
            # Still at capacity after eviction — reject to prevent unbounded growth
            logger.warning("rate_limiter_capacity_exceeded")
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        _rate_limiters[account_id] = _TokenBucket()
    if not _rate_limiters[account_id].consume():
        logger.warning("rate_limit_hit", extra={"account_id": account_id})
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
```

Used as: `await _check_rate_limit(account_id)` at the top of each state-changing endpoint.

### TASK-022: Add GET /accounts/{account_id}/trades endpoint
**Requirement IDs:** FR-027, FR-028, FR-033, FR-034, FR-045, FR-046, FR-047, FR-052, FR-059
**File:** `backend/routers/accounts.py`

```python
@router.get("/accounts/{account_id}/trades", response_model=TradeListResponse)
async def list_trades(
    account_id: str,
    status: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
    close_reason: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sort: str = "created_at",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = False,
    parent_trade_id: str | None = None,
    request: Request = None,
):
```

- Get `trade_repo` from `request.app.state.trade_repo`
- Validate `account_id` exists (reuse `_validate_account_id` pattern)
- Call `trade_repo.list_trades(...)` within a connection
- Return `TradeListResponse`
- Handle ValueError from sort/symbol/cursor validation → 400

### TASK-023: Add GET /accounts/{account_id}/trades/open endpoint
**Requirement IDs:** FR-030, FR-033, FR-047
**File:** `backend/routers/accounts.py`
**IMPORTANT:** Register BEFORE /trades/{trade_id}

```python
@router.get("/accounts/{account_id}/trades/open")
async def get_open_trades(account_id: str, request: Request):
```

### TASK-024: Add GET /accounts/{account_id}/trades/stats endpoint
**Requirement IDs:** FR-031, FR-033, FR-047, FR-056, FR-057, FR-060
**File:** `backend/routers/accounts.py`
**IMPORTANT:** Register BEFORE /trades/{trade_id}

**Note:** The stats cache lives in TradeService (TASK-030), not in the router. The router delegates to `trade_service.get_cached_stats(account_id)` which handles caching and invalidation internally. This avoids the split-brain problem where the router has a cache that TradeService cannot invalidate.

```python
@router.get("/accounts/{account_id}/trades/stats")
async def get_trade_stats(account_id: str, request: Request):
    trade_service = request.app.state.trade_service
    if trade_service is None:
        return JSONResponse(status_code=503, content={"detail": "Trading not configured"})
    stats = await trade_service.get_cached_stats(account_id)
    return TradeStatsResponse(**stats)
```

### TASK-025: Add GET /accounts/{account_id}/trades/{trade_id} endpoint
**Requirement IDs:** FR-029, FR-033, FR-054
**File:** `backend/routers/accounts.py`

- Validate trade_id is UUID format
- Call `trade_repo.get_trade_with_events()`
- If None → 404 TRADE_NOT_FOUND
- Return `TradeDetailResponse`

### TASK-026: Add POST /accounts/{account_id}/trades/{trade_id}/close endpoint
**Requirement IDs:** FR-011, FR-016, FR-019, FR-020, FR-040, FR-043, FR-054, FR-055
**File:** `backend/routers/accounts.py`

```python
@router.post("/accounts/{account_id}/trades/{trade_id}/close")
async def close_trade(account_id: str, trade_id: str,
                      body: TradeCloseRequest = TradeCloseRequest(),
                      request: Request = None):
```

- Rate limit check
- Validate trade_id UUID
- Get trade (IDOR-safe lookup)
- If not found → 404
- Validate status allows close (must be open/partially_filled/partially_closed)
- If body.qty provided and > remaining qty → 400
- Delegate to `trade_service.close_single_trade()` (Phase 4)
- Handle exceptions:
  - `InvalidStatusTransition` → 409 INVALID_STATUS_TRANSITION
  - `ConcurrentModification` → 409 CONCURRENT_MODIFICATION
  - Bybit error → 502 EXCHANGE_REJECTION
- Return `TradeResponse`

### TASK-027: Add POST /accounts/{account_id}/trades/{trade_id}/cancel endpoint
**Requirement IDs:** FR-021, FR-022, FR-040, FR-043, FR-054
**File:** `backend/routers/accounts.py`

```python
@router.post("/accounts/{account_id}/trades/{trade_id}/cancel")
async def cancel_trade(account_id: str, trade_id: str, request: Request):
```

- Rate limit check
- Validate trade_id UUID
- Delegate to `trade_service.cancel_trade()`
- Same error handling as close
- Return `TradeResponse`

### TASK-028: Write API endpoint tests
**File:** `tests/test_trade_api.py`
**Test cases:**

1. `test_list_trades_empty` — GET /trades returns empty list
2. `test_list_trades_pagination_cursor` — AC-008
3. `test_list_trades_filter_by_status` — FR-028
4. `test_list_trades_invalid_sort_400` — AC-014
5. `test_list_trades_invalid_symbol_400` — FR-046
6. `test_list_trades_cursor_too_long_400` — FR-059
7. `test_get_trade_detail_with_events` — FR-029
8. `test_get_trade_not_found_404` — FR-054
9. `test_get_trade_idor_404` — AC-013
10. `test_get_open_trades` — FR-030
11. `test_get_stats_empty_account` — FR-056
12. `test_close_trade_success` — AC-002
13. `test_close_trade_already_closed_409` — Edge case
14. `test_close_trade_partial` — AC-010
15. `test_cancel_pending_trade` — AC-011
16. `test_cancel_partially_filled` — AC-012
17. `test_rate_limit_429` — FR-043
18. `test_route_ordering_open_not_captured_as_trade_id` — FR-047
19. `test_rate_limit_isolation_per_account` — rate limit account A does not affect account B
20. `test_rate_limit_eviction_stale_entries` — stale entries evicted when at capacity
21. `test_rate_limit_recovery_after_refill` — after cooldown (mock time.monotonic), requests succeed again

**Note:** Close/cancel tests will initially fail until Phase 4 (TradeService) is implemented. Mark them with `@pytest.mark.skip("Phase 4")` during Phase 3, remove skip in Phase 4.

## Exit Criteria
- All schemas defined and importable
- All 6 endpoints registered (routes exist)
- Read endpoints (GET) fully functional with tests
- Write endpoints (POST) have route stubs that delegate to TradeService
- Rate limiter functional
- All non-skipped tests pass

## Verification Commands
```bash
python -m pytest tests/test_trade_api.py -x -q --tb=short
python -m pytest tests/ -x -q --tb=short
```

## Traceability
| Task | FRs | ACs |
|------|-----|-----|
| TASK-020 | FR-052 | — |
| TASK-021 | FR-043, FR-058 | — |
| TASK-022 | FR-027,028,033,034,045,046,059 | AC-008,014 |
| TASK-023 | FR-030,033,047 | — |
| TASK-024 | FR-031,033,047,056,057,060 | — |
| TASK-025 | FR-029,033,054 | AC-013 |
| TASK-026 | FR-011,016,019,020,040,043,054,055 | AC-002,010 |
| TASK-027 | FR-021,022,040,043,054 | AC-011,012 |
