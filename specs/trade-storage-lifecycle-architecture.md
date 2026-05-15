# Architecture: Trade Storage & Lifecycle Tracking

## 1. Architecture Decision Record (ADR)

### Decision
Extend the existing service architecture with a new `trades` table, `TradeRepository`, and hooks into existing services (`AccountsService`, `ClosePositionsService`, `TradingCycleEngine`, `CloseRuleEvaluator`). Add a `TradeReconciliationService` background job for TP/SL detection and external close detection.

### Context
Individual trades placed via the direct trade endpoint are not stored locally — only Bybit's orderId is returned. Cycle trades exist in `cycle_trades` but lack PnL/closure tracking. There is no unified trade record for the full lifecycle.

### Alternatives Considered

| Alternative | Rejected Because |
|-------------|------------------|
| Extend `cycle_trades` for all trades | `cycle_trades` is tightly coupled to cycle_id (NOT NULL FK). Manual trades have no cycle. Would require nullable FK and semantic overload. |
| Store trades as JSONB in `trading_cycles` | Already done for results. Loses queryability, indexability, and relational integrity. |
| Event-sourced trade log only | Over-engineered for a single-user local tool. Adds complexity without proportional benefit. |
| Rely solely on Bybit API for trade history | Bybit API has rate limits, pagination complexity, and no local query flexibility. Cannot track close reasons or user intent. |

### Consequences
- New table + migration in both persistence files (migration #25)
- Hooks added to 4 existing services (non-breaking, additive)
- New background job adds ~1 DB query + 1 Bybit API call per account per 60s
- `cycle_trades` remains for backward compatibility; new trades also written to `trades`

## 2. System Context

```
┌─────────────┐     HTTP/WS      ┌──────────────────┐     REST API      ┌────────────┐
│  React UI   │ ◄──────────────► │  FastAPI Backend  │ ◄──────────────► │  Bybit API  │
│  (Browser)  │                  │                   │                  │  (Exchange) │
└─────────────┘                  │  ┌─────────────┐  │                  └────────────┘
                                 │  │ trades table │  │
                                 │  │ trade_events │  │
                                 │  └──────┬──────┘  │
                                 │         │         │
                                 │  ┌──────▼──────┐  │
                                 │  │ PostgreSQL   │  │
                                 │  └─────────────┘  │
                                 └──────────────────┘
```

**Data Flows:**
1. Trade Placement: UI → API → Bybit → DB (trades table) → WS event → UI
2. Trade Closure (manual): UI → API → Bybit → DB update → WS event → UI
3. Trade Closure (TP/SL): Bybit fills → Reconciliation detects → DB update → WS event → UI
4. Trade Closure (rule): CloseRuleEvaluator → ClosePositionsService → Bybit → DB update → WS event → UI
5. Trade Closure (close-all): UI → ClosePositionsService → Bybit → DB update → WS event → UI

## 3. Component Architecture

### New Components

| Component | Responsibility | Location |
|-----------|---------------|----------|
| `TradeRepository` | CRUD for `trades` and `trade_events` tables, state machine validation, optimistic locking, keyset pagination. Pure data access — no Bybit calls, no WS broadcasts, no cache management. | `backend/services/trade_repository.py` |
| `TradeService` | Orchestration layer for trade lifecycle operations (close, cancel, partial close). Coordinates TradeRepository + Bybit calls + post-commit WS broadcast + cache invalidation. Constructor: `TradeService(db, trade_repo, accounts_service, ws_manager)`. | `backend/services/trade_service.py` |
| `TradeReconciliationService` | Periodic reconciliation of local trades vs Bybit positions. Constructor: `TradeReconciliationService(db, trade_repo, accounts_service, ws_manager)`. | `backend/services/trade_reconciliation.py` |

### Modified Components

| Component | Changes |
|-----------|---------|
| `AccountsService.place_trade()` | After Bybit success, call `TradeRepository.create_trade()` |
| `ClosePositionsService.close_all_positions()` | After closing, call `TradeRepository.close_trades()` for each closed position |
| `ClosePositionsService.close_all_for_rule()` | Same as above, with close_reason=rule and rule_id |
| `TradingCycleEngine._execute_cycle()` | After placing each trade, also insert into `trades` with source=cycle |
| `CloseRuleEvaluator` | Pass rule_id and trigger_type through to close service |
| `async_persistence.py` | Add migration #25 (trades + trade_events tables) |
| `persistence.py` | Add migration #25 (same DDL) |
| `schemas.py` | Add TradeResponse, TradeListResponse, TradeEventResponse Pydantic models |
| `routers/accounts.py` | Add trade history/detail endpoints |
| `AccountWSManager` | Broadcast trade.opened and trade.closed events |

### Component Dependencies

```
AccountsService.place_trade() ──► TradeRepository.create_trade()
                                          │
TradingCycleEngine ─────────────► TradeRepository.create_trade()
                                          │
TradeService ───────────────────► TradeRepository + AccountsService + AccountWSManager
  (close, cancel, partial close orchestration; post-commit WS + cache)
                                          │
ClosePositionsService ──────────► TradeService.close_trade() (for each position)
                                          │
CloseRuleEvaluator ─────────────► ClosePositionsService ──► TradeService
                                          │
TradeReconciliationService ─────► TradeRepository + AccountsService + AccountWSManager
```

No circular dependencies. All flows are unidirectional.

## 4. Data Architecture

### trades Table

```sql
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE RESTRICT,
    symbol VARCHAR(30) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('Buy', 'Sell')),
    order_type VARCHAR(10) NOT NULL DEFAULT 'market' CHECK (order_type IN ('market', 'limit')),
    qty NUMERIC(20,8) NOT NULL,
    filled_qty NUMERIC(20,8),
    entry_price NUMERIC(20,8),
    avg_fill_price NUMERIC(20,8),
    exit_price NUMERIC(20,8),
    stop_loss_price NUMERIC(20,8),
    take_profit_price NUMERIC(20,8),
    leverage INTEGER NOT NULL DEFAULT 1,
    margin_mode VARCHAR(10) DEFAULT 'isolated' CHECK (margin_mode IN ('cross', 'isolated')),
    position_idx INTEGER NOT NULL DEFAULT 0,
    mark_price_at_open NUMERIC(20,8),
    capital_pct NUMERIC(8,4),
    base_capital NUMERIC(20,8),
    signal_direction VARCHAR(4) CHECK (signal_direction IN ('buy', 'sell')),
    trade_direction VARCHAR(8) CHECK (trade_direction IN ('straight', 'reverse')),
    take_profit_pct NUMERIC(8,4),
    stop_loss_pct NUMERIC(8,4),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'open', 'partially_filled', 'closing', 'partially_closed', 'closed', 'failed', 'cancelled')),
    order_id VARCHAR(50),
    order_link_id VARCHAR(50),
    close_reason VARCHAR(20)
        CHECK (close_reason IN ('take_profit', 'stop_loss', 'manual_single', 'manual_close_all',
               'rule_triggered', 'cycle_target', 'cycle_drawdown', 'external', 'liquidation', 'adl')),
    close_rule_id UUID REFERENCES close_rules(id) ON DELETE SET NULL,
    parent_trade_id UUID REFERENCES trades(id) ON DELETE RESTRICT,
    realized_pnl NUMERIC(20,8),
    realized_pnl_pct NUMERIC(12,4),
    fees NUMERIC(20,8) DEFAULT 0,
    net_pnl NUMERIC(20,8),
    source VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'cycle')),
    source_id INTEGER REFERENCES trading_cycles(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}' CHECK (octet_length(metadata::text) < 8192),
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_source_id CHECK (
        (source = 'cycle' AND source_id IS NOT NULL) OR
        (source = 'manual' AND source_id IS NULL)
    )
);

-- Indexes
CREATE INDEX idx_trades_account_status_created ON trades(account_id, status, created_at DESC, id DESC);
CREATE INDEX idx_trades_account_created ON trades(account_id, created_at DESC, id DESC);
CREATE INDEX idx_trades_account_opened ON trades(account_id, opened_at DESC, id DESC);
CREATE INDEX idx_trades_account_closed ON trades(account_id, closed_at DESC NULLS LAST, id DESC);
CREATE INDEX idx_trades_account_pnl ON trades(account_id, realized_pnl DESC NULLS LAST, id DESC);
CREATE INDEX idx_trades_account_symbol ON trades(account_id, symbol, created_at DESC, id DESC);
CREATE INDEX idx_trades_order_id ON trades(order_id) WHERE order_id IS NOT NULL;
CREATE INDEX idx_trades_active ON trades(account_id) WHERE status IN ('open', 'partially_filled', 'closing', 'partially_closed');
CREATE INDEX idx_trades_source ON trades(source, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX idx_trades_parent ON trades(parent_trade_id) WHERE parent_trade_id IS NOT NULL;
CREATE UNIQUE INDEX idx_trades_order_link_id ON trades(order_link_id) WHERE order_link_id IS NOT NULL;
CREATE INDEX idx_trades_archived ON trades(archived_at) WHERE archived_at IS NOT NULL;
CREATE INDEX idx_trades_pending_orphan ON trades(created_at) WHERE status = 'pending' AND order_id IS NULL;

-- updated_at trigger
CREATE OR REPLACE FUNCTION update_trades_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_trades_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_trades_updated_at();
```

### trade_events Table

```sql
CREATE TABLE IF NOT EXISTS trade_events (
    id BIGSERIAL PRIMARY KEY,
    trade_id UUID NOT NULL REFERENCES trades(id) ON DELETE RESTRICT,
    event_type VARCHAR(30) NOT NULL
        CHECK (event_type IN ('placed', 'filled', 'partially_filled', 'tp_triggered', 'sl_triggered',
               'close_requested', 'closed', 'failed', 'cancelled', 'amended', 'reconciled')),
    old_status VARCHAR(20) CHECK (old_status IS NULL OR old_status IN ('pending','open','partially_filled','closing','partially_closed','closed','failed','cancelled')),
    new_status VARCHAR(20) CHECK (new_status IS NULL OR new_status IN ('pending','open','partially_filled','closing','partially_closed','closed','failed','cancelled')),
    fill_qty NUMERIC(20,8),
    fill_price NUMERIC(20,8),
    actor VARCHAR(20) NOT NULL DEFAULT 'system'
        CHECK (actor IN ('system', 'user', 'rule_engine', 'cycle_engine', 'reconciliation', 'exchange')),
    payload JSONB DEFAULT '{}' CHECK (octet_length(payload::text) < 8192),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_events_trade_id ON trade_events(trade_id, created_at);

-- Immutability: trade_events is append-only (UPDATE always rejected; DELETE only with purge_mode)
CREATE OR REPLACE FUNCTION prevent_trade_events_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'trade_events: UPDATE is prohibited';
    END IF;
    IF TG_OP = 'DELETE' AND current_setting('app.purge_mode', 'false') <> 'true' THEN
        RAISE EXCEPTION 'trade_events: DELETE requires purge_mode';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_trade_events_immutable BEFORE UPDATE OR DELETE ON trade_events
    FOR EACH ROW EXECUTE FUNCTION prevent_trade_events_mutation();
```

### Entity Relationships

```
trading_accounts (1) ──► (N) trades
trades (1) ──► (N) trade_events
trades (1) ──► (N) trades (via parent_trade_id, for partial closes)
close_rules (1) ──► (N) trades (via close_rule_id, nullable)
trading_cycles (1) ──► (N) trades (via source_id when source='cycle')
```

### State Machine

Valid status transitions (all others rejected by TradeRepository):

```
pending → open              (Bybit confirms full fill)
pending → partially_filled  (Bybit reports partial fill on limit order)
pending → failed            (Bybit rejects order)
pending → cancelled         (user cancels before fill)
partially_filled → open     (fully filled)
partially_filled → closing  (close before full fill)
partially_filled → open     (user cancels unfilled remainder; filled portion becomes open position)
open → closing              (close initiated)
open → partially_closed     (partial close executed)
closing → closed            (Bybit confirms close)
closing → open              (close failed, reverted)
closing → partially_closed  (close partially executed)
partially_closed → closing  (close remainder)
partially_closed → closed   (fully closed)
```

The close endpoint (`POST .../close`) returns `INVALID_STATUS_TRANSITION` for trades in `pending`, `cancelled`, `failed`, or `closed` status. Use the cancel endpoint for `pending` trades.

Reconciliation may perform `open → closing → closed` atomically in a single transaction with two version increments when it detects a position no longer exists on Bybit.

**Cancel endpoint semantics:** For `pending` trades, cancels the order on Bybit and transitions to `cancelled`. For `partially_filled` trades, cancels the unfilled remainder on Bybit; the filled portion transitions to `open` (as a live position), not `cancelled`.

### Concurrency Control

All status updates use optimistic locking via the `version` column:
```sql
UPDATE trades SET status = $new, version = version + 1
WHERE id = $id AND status = $expected_old AND version = $expected_version;
```
If zero rows affected, the trade was concurrently modified — retry or abort.

### Transaction Boundaries

| Operation | Boundary | Isolation |
|-----------|----------|-----------|
| create_trade + initial trade_event | Single transaction | READ COMMITTED |
| close_trade + closure trade_event + PnL fields | Single transaction | READ COMMITTED |
| WebSocket broadcast + cache invalidation | AFTER commit (outside transaction) | N/A |

Optimistic locking via the `version` column is sufficient for concurrency safety — SERIALIZABLE is not needed.

### Data Lifecycle

1. **Creation**: Trade inserted with status=pending BEFORE calling Bybit (fail-safe: DB failure prevents exchange call)
2. **Open**: Updated to status=open with order_id after Bybit confirms
3. **Monitoring**: Reconciliation checks position existence every 60s
4. **Closure**: Updated with exit_price, PnL, close_reason, closed_at
5. **Archive**: Soft-archive via archived_at after retention period

## 5. API Architecture

### New Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/accounts/{id}/trades` | List trades (paginated, filtered) |
| GET | `/api/v1/accounts/{id}/trades/{trade_id}` | Single trade with events |
| GET | `/api/v1/accounts/{id}/trades/open` | Open trades only |
| GET | `/api/v1/accounts/{id}/trades/stats` | Aggregate statistics (cached) |
| POST | `/api/v1/accounts/{id}/trades/{trade_id}/close` | Close single trade (optional `qty` for partial close; `qty` must be positive and ≤ remaining open quantity, validated server-side) |
| POST | `/api/v1/accounts/{id}/trades/{trade_id}/cancel` | Cancel pending/limit order |

### Pagination
Cursor-based keyset pagination on `(sort_column, id)`. The cursor encodes the sort column value and trade id as an opaque base64 token. After decoding, the trade ID must be a valid UUID and the sort value must match the expected type (TIMESTAMPTZ or NUMERIC) — malformed cursors return 400. Each sort option requires a matching composite index. Default page size 50, max 200. The cursor query always includes `WHERE account_id = $account_id` so forged cursors cannot leak data across accounts.

### Filters (GET /trades)
- `status`: any valid status (pending, open, partially_filled, closing, partially_closed, closed, failed, cancelled)
- `symbol`: exact match (max 30 chars, alphanumeric + slash)
- `side`: Buy, Sell
- `close_reason`: any CloseReason enum value
- `from_date`, `to_date`: ISO 8601 date range (validated)
- `sort`: created_at, opened_at, closed_at, realized_pnl (default: created_at DESC) — validated against hardcoded allowlist, never interpolated
- `include_total`: boolean, default false — when true, includes total count (expensive)

### Response Shape

```json
{
  "items": [TradeResponse],
  "cursor": "base64...",
  "has_more": true,
  "total": 150  // only present when include_total=true
}
```

### Error Codes

| Code | HTTP | When |
|------|------|------|
| TRADE_NOT_FOUND | 404 | Trade ID does not exist or belongs to another account |
| TRADE_ALREADY_CLOSED | 409 | Close attempted on non-open trade |
| INVALID_STATUS_TRANSITION | 409 | Illegal state transition |
| CONCURRENT_MODIFICATION | 409 | Optimistic lock version mismatch |
| EXCHANGE_REJECTION | 502 | Bybit rejected the order |
| INSUFFICIENT_MARGIN | 400 | Bybit reports insufficient margin |

### Error Contract
All errors follow existing pattern: `{"detail": "...", "code": "ERROR_CODE"}` with appropriate HTTP status.

### IDOR Prevention
All single-trade lookups and mutations MUST filter by both `trade_id` AND `account_id`: `WHERE id = $trade_id AND account_id = $account_id`. Never look up a trade by `trade_id` alone.

### JSONB Safety
Metadata and payload JSONB fields must have keys validated against an application-layer allowlist before insertion. When rendered in UI, values are treated as untrusted (output-encoded, never raw HTML).

### Retryable Errors
DB write retries apply only to transient errors (connection refused, lock wait timeout, PostgreSQL error class `08xxx`, `40001` serialization failure). Constraint violations (`23xxx`) and syntax errors are NOT retried.

## 6. Integration Architecture

### Bybit Integration Points

| Operation | Bybit API | Existing? |
|-----------|-----------|-----------|
| Place order | POST /v5/order/create | Yes (BybitClient.place_market_order) |
| Close order | POST /v5/order/create (reduce-only) | Yes (BybitClient.place_market_close_order) |
| Get positions | GET /v5/position/list | Yes (BybitClient.get_positions) |
| Get closed PnL | GET /v5/position/closed-pnl | Yes (synced to closed_pnl_records) |

No new Bybit API integrations needed. Reconciliation reuses existing `get_positions()` and correlates with `closed_pnl_records`.

### Retry Strategy
- Bybit API calls: existing retry logic in BybitClient (exponential backoff)
- DB writes: 5 retries with jittered exponential backoff (1-2s, 2-4s, 4-8s, 8-16s, 16-30s)
- Reconciliation on Bybit 429: skip cycle, retry next interval

## 7. Resilience & Failure Modes

| Failure | Behavior | Recovery |
|---------|----------|----------|
| DB insert fails (pre-Bybit) | Trade never sent to Bybit (fail-safe) | User retries |
| Bybit succeeds, DB status update fails | Retry 5x with jitter; log CRITICAL | Reconciliation catches within 60s |
| DB update fails on close | Retry 5x; trade stays `closing` locally | Reconciliation detects and updates |
| Bybit returns 429 during close-all | Pause, retry remaining with backoff | User sees partial progress |
| Bybit API key expired | Mark account degraded, suspend rules | User re-authenticates |
| DB connection pool exhaustion | Return 503, background jobs wait | Pool drains naturally |
| Process crash mid-close | `closing` status trades detected on startup | TradeReconciliationService runs immediate reconciliation on startup before entering 60s loop |

### Idempotency
- Trade placement: `order_link_id` UNIQUE constraint prevents duplicates
- Close operations: trade-level optimistic lock (`WHERE status IN ('open', 'partially_filled') AND version = $v`) — if 0 rows updated, trade is already being closed
- Trade events: append-only (immutability trigger prevents mutation)

## 8. Observability

### Logging
- Trade state transitions: `trade_id`, `old_status`, `new_status`, `close_reason`, `latency_ms`
- Reconciliation: `account_id`, `open_count`, `discrepancies_found`
- Errors: full context with trade_id reference (never log API keys)

### WebSocket Events

All events are scoped to the account's channel — only clients subscribed to the specific `account_id` receive that account's trade events (existing `AccountWSManager` pattern).

| Event | Payload | When |
|-------|---------|------|
| `trade.opened` | `{trade_id, account_id, symbol, side, qty, entry_price, leverage}` | After trade insert (post-commit) |
| `trade.closed` | `{trade_id, account_id, symbol, close_reason, realized_pnl, net_pnl}` | After trade closure (post-commit) |
| `trade.close_failed` | `{trade_id, account_id, symbol, error_code}` | When close attempt fails (error is a sanitized code, never raw exception) |

## 9. Performance

### Query Performance
- Open trades query: partial index on status IN ('open', 'partially_filled') — O(1) per account
- Trade history: keyset pagination on `(sort_column, id)` with matching composite indexes avoids OFFSET scan
- Trade list endpoint: does NOT include events; use detail endpoint for events (avoids N+1)
- PnL aggregation for `/trades/stats`: served from in-memory cache, invalidated on trade close events

### Caching
- **Open trades cache**: in-memory dict keyed by `account_id`, invalidated post-commit only on status-changing events (`filled`, `closed`, `failed`, `cancelled`) and on `reconciled` events that modify price/qty fields on open trades. Non-mutating `reconciled` and `amended` events do not flush the cache. Rule evaluator must tolerate a brief stale window (up to one reconciliation cycle).
- **Stats cache**: per-account aggregate stats (total PnL, win rate, avg hold time) cached in-memory, invalidated post-commit on trade closure. Prevents expensive full-table aggregation per request.

### Background Job Load
- Reconciliation: 1 Bybit API call + 1 DB query per account per 60s
- Reconciliation fetches open trades as a dict keyed by `order_id` in a single query, performs set-difference against Bybit positions in application code
- Uses `pg_try_advisory_lock` (non-blocking) — if lock held, skip cycle
- Max 5 accounts concurrent (existing semaphore pattern)
- Runs immediate reconciliation on startup before entering 60s loop

### Advisory Lock Key Allocation

Uses two-key advisory locks (`pg_try_advisory_lock(app_namespace, job_id)`) where `app_namespace = 7001` is a fixed application constant. Locks are released explicitly after each job cycle, not relying on session disconnect.

| Lock Key | Job |
|----------|-----|
| (7001, 1) | Trade reconciliation |
| (7001, 2) | Close rule evaluation |

Trade events retention: events for archived trades (where `trades.archived_at IS NOT NULL`) may be exported to cold storage and purged via a dedicated maintenance function that uses a session-level flag (`SET LOCAL app.purge_mode = 'true'`) checked inside the immutability trigger, running under a dedicated DB role. The trigger function allows DELETE only when this flag is set. Alternatively, partition `trade_events` by month and detach/drop old partitions.

### Connection Pool
- Pool size: 20 connections, `max_overflow`: 10, `pool_timeout`: 30s
- Background jobs limited to 3 concurrent connections via semaphore
- Separate connection budget: API requests get 17 base + overflow, background jobs capped at 3

### Migration Rollback

Migration #25 rollback DDL (data-destructive — requires pg_dump backup before rollback):
```sql
DROP TRIGGER IF EXISTS trg_trade_events_immutable ON trade_events;
DROP FUNCTION IF EXISTS prevent_trade_events_mutation();
DROP TRIGGER IF EXISTS trg_trades_updated_at ON trades;
DROP FUNCTION IF EXISTS update_trades_updated_at();
DROP TABLE IF EXISTS trade_events;
DROP TABLE IF EXISTS trades;
```

### Idempotency Keys

`order_link_id` is server-generated (UUID v4) on every trade placement, never client-supplied. Generated in `TradeRepository.create_trade()` before the DB insert.

### Orphaned Pending Trade Cleanup

Reconciliation sweeps for trades with `status = 'pending'` and `order_id IS NULL` older than 5 minutes. These are transitioned to `failed` with metadata `{"reason": "pending_timeout"}`. This handles crashes between DB insert and Bybit API call.

### Startup Ordering

```
1. DB migrations complete
2. WebSocket manager initialized
3. TradeReconciliationService starts (immediate reconciliation)
4. API begins accepting requests (health check returns "ready")
```

WebSocket events emitted during startup reconciliation (before clients connect) are fire-and-forget. Clients must perform a full state sync (`GET /trades/open`) upon WebSocket connection.

### Reconciliation Dependencies

`TradeReconciliationService` depends on `TradeRepository` and `AccountsService` (for Bybit client access via a public `get_client(account_id)` method). While this couples reconciliation to AccountsService, it avoids duplicating credential decryption logic and aligns with how ClosePositionsService already obtains clients.

