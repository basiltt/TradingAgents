# Specification: Trade Storage & Lifecycle Tracking

## A. Title and Metadata

- **Feature:** Trade Storage & Lifecycle Tracking
- **Date:** 2026-05-15
- **Author:** Claude Agent
- **Status:** Draft
- **Related user request:** Store all trades in DB with full lifecycle tracking including PnL on close
- **Related modules:** backend/services/, backend/routers/, backend/persistence
- **Related files:** backend/services/accounts_service.py, backend/services/close_positions_service.py, backend/services/trading_cycle_engine.py, backend/services/close_rule_evaluator.py, backend/async_persistence.py, backend/persistence.py, backend/schemas.py, backend/routers/accounts.py
- **Version:** 1.0

## B. Discovery Summary

- **Trade placement:** `AccountsService.place_trade()` calls Bybit API, returns orderId but does NOT store the trade locally
- **Cycle trades:** `TradingCycleEngine._execute_cycle()` stores trades in `cycle_trades` table but only with cycle context (NOT standalone PnL tracking)
- **Close flows:** `ClosePositionsService.close_all_positions()` and `close_all_for_rule()` close via Bybit but don't track closure reason/PnL locally
- **Close rules:** `CloseRuleEvaluator` triggers closes based on balance/equity/PnL thresholds via WebSocket, delegates to ClosePositionsService
- **DB layer:** 24 migrations across persistence.py and async_persistence.py, uses asyncpg (async) and psycopg2 (sync) with PostgreSQL, raw SQL migrations kept in lockstep across both files
- **WebSocket:** `AccountWSManager` broadcasts account events to subscribed clients
- **Key gap:** No unified trade record exists for the full lifecycle (open → monitor → close with PnL)

## C. Feature Overview

- **What:** A new `trades` table and `trade_events` audit log that captures every trade from placement through closure, with full PnL attribution
- **Why:** Currently trades placed via the direct endpoint are fire-and-forget — no local record exists after the Bybit API returns
- **Who:** The tool operator viewing trade history, monitoring open positions, and analyzing performance
- **Problem solved:** No visibility into trade lifecycle, no PnL tracking per trade, no close reason attribution
- **Expected outcome:** Every trade has a complete lifecycle record with entry/exit prices, PnL, close reason, and an event audit trail

## D. Business Goal

- **Business objective:** Full trade lifecycle visibility for a trading tool
- **User value:** See all trades, their current status, and historical performance with close reasons
- **Operational value:** Detect orphaned trades, reconcile with exchange, track rule-triggered closures
- **Success definition:** Every trade placed through the tool appears in the trades table with correct PnL on closure

## E. Current System Behavior

- **Trade placement:** `AccountsService.place_trade()` → Bybit API → returns `{"orderId": "..."}` → no DB write
- **Cycle trades:** Stored in `cycle_trades` with FK to `trading_cycles`, but no standalone PnL tracking
- **Close-all:** `ClosePositionsService.close_all_positions()` → Bybit API for each position → no local record of what was closed
- **Rule-triggered close:** `CloseRuleEvaluator` evaluates rules → calls `close_all_for_rule()` → no attribution of which rule triggered which close
- **PnL data:** `closed_pnl_records` synced from Bybit API — aggregated per symbol, not per individual trade
- **Limitations:** No per-trade PnL, no close reason tracking, no trade status tracking, no event audit trail

## F. Expected New Behavior

- **Trade placement:** Insert trade record (status=pending) → call Bybit → update status to open/failed
- **Trade closure (manual):** User clicks close → status=closing → Bybit API → status=closed with PnL
- **Trade closure (close-all):** ClosePositionsService → updates each trade with close_reason=manual_close_all
- **Trade closure (rule):** CloseRuleEvaluator → ClosePositionsService → close_reason=rule_triggered with rule_id
- **Trade closure (TP/SL):** Reconciliation detects position gone → correlates with closed_pnl_records → close_reason=take_profit/stop_loss
- **Trade closure (external):** Reconciliation detects closure not initiated by tool → close_reason=external/liquidation/adl
- **WebSocket:** `trade.opened` and `trade.closed` events broadcast post-commit
- **API:** New endpoints for trade list, detail, open trades, stats, close, cancel

## G. Scope

### In Scope
- `trades` table with full schema (see architecture doc)
- `trade_events` append-only audit table
- `TradeRepository` for CRUD operations
- `TradeReconciliationService` background job
- Hooks into AccountsService, ClosePositionsService, TradingCycleEngine, CloseRuleEvaluator
- REST API endpoints for trade history/detail/stats/close/cancel
- WebSocket events for trade lifecycle
- Migration #25 with rollback DDL
- Pydantic schemas for request/response

### Out of Scope
- Frontend UI changes (backend-only feature)
- Modifying existing `cycle_trades` table structure
- Historical backfill of past trades from Bybit
- Real-time P&L streaming (use existing WebSocket position updates)
- Multi-user authentication system

### Future Scope
- Trade analytics dashboard
- Export trade history to CSV
- Historical backfill from Bybit closed PnL
- Trade tagging/notes

## H. Functional Requirements

```
FR-001: The system must insert a trade record with status=pending into the trades table BEFORE calling the Bybit API (fail-safe ordering).
FR-002: The system must update the trade record with order_id and status=open after Bybit confirms the order.
FR-003: The system must update the trade to status=failed if Bybit rejects the order.
FR-004: The system must generate a server-side UUID v4 as order_link_id for each trade placement (never client-supplied).
FR-005: The system must record entry_price, avg_fill_price, leverage, margin_mode, qty, and all placement parameters on the trade record.
FR-006: The system must create a trade_event with event_type=placed on trade creation.
FR-007: The system must create a trade_event with event_type=filled when the order is fully filled.
FR-008: The system must support partial fills with event_type=partially_filled and incremental avg_fill_price updates.
FR-009: The system must track trades from TradingCycleEngine with source=cycle and source_id=cycle.id.
FR-010: The system must track trades from AccountsService.place_trade() with source=manual.
FR-011: When a user manually closes a single trade, the system must set close_reason=manual_single.
FR-012: When a user closes all trades via close-all, the system must set close_reason=manual_close_all for each trade.
FR-013: When a close rule triggers, the system must set close_reason=rule_triggered and close_rule_id to the rule's UUID.
FR-014: The reconciliation service must detect TP/SL fills and set close_reason=take_profit or stop_loss.
FR-015: The reconciliation service must detect external closures and set close_reason=external, liquidation, or adl as appropriate.
FR-016: On trade closure, the system must record exit_price, realized_pnl, realized_pnl_pct, fees, net_pnl, and closed_at.
FR-017: The system must use optimistic locking (version column) for all trade status updates.
FR-018: The system must validate state transitions against the defined state machine and reject invalid transitions with INVALID_STATUS_TRANSITION.
FR-019: The system must support partial close via the close endpoint with an optional qty parameter.
FR-020: Partial close must create a child trade (with parent_trade_id) for the closed portion with PnL attribution.
FR-021: The cancel endpoint must cancel pending orders on Bybit and transition to cancelled.
FR-022: For partially_filled trades, cancel must cancel the unfilled remainder; the filled portion transitions to open.
FR-023: The reconciliation service must run every 60 seconds per account.
FR-024: The reconciliation service must run an immediate sweep on startup before entering the 60s loop.
FR-025: The reconciliation service must sweep for orphaned pending trades (order_id IS NULL, older than 5 minutes) and transition them to failed.
FR-026: The reconciliation service must use pg_try_advisory_lock (non-blocking) with key (7001, 1).
FR-027: The GET /trades endpoint must support cursor-based keyset pagination on (sort_column, id).
FR-028: The GET /trades endpoint must support filters: status, symbol, side, close_reason, from_date, to_date, sort, include_total.
FR-029: The GET /trades/{trade_id} endpoint must return the trade with all trade_events.
FR-030: The GET /trades/open endpoint must return only open/partially_filled trades.
FR-031: The GET /trades/stats endpoint must return cached aggregate statistics.
FR-032: WebSocket events trade.opened and trade.closed must be broadcast post-commit, scoped to the account's channel.
FR-033: All trade queries (single, list, aggregate, stats) must include WHERE account_id = $path_account_id. No endpoint may return trades belonging to a different account.
FR-034: The sort parameter must be validated against a hardcoded allowlist (created_at, opened_at, closed_at, realized_pnl).
FR-035: Trade events table must be append-only, enforced by an immutability trigger.
FR-036: All SQL queries must use parameterized placeholders for user-supplied values. String interpolation of query parameters is prohibited.
FR-037: Every trade state transition must emit a structured log entry with trade_id, old_status, new_status, close_reason, and latency_ms.
FR-038: Reconciliation must persist its results (account_id, open_count, discrepancies_found) in a structured log entry per sweep.
FR-039: Bybit error responses stored in trade metadata must be sanitized — strip headers, credentials, and raw request bodies. Only store error code and message.
FR-040: All state-changing POST endpoints must use the JSONResponse with {detail, code} error pattern (matching existing accounts/close_positions routers).
FR-041: TradeRepository must accept db: AsyncAnalysisDB in its constructor, wired into app.state during startup (matching existing service DI pattern).
FR-042: Trade list endpoint must filter/display parent vs child trades — child trades are nested under their parent or filterable via parent_trade_id parameter. Stats aggregation counts only leaf trades to avoid double-counting PnL.
FR-043: State-changing endpoints (place, close, cancel) must be rate-limited per account (in-memory token bucket, 10 req/s). Log when limit is hit.
FR-044: JSONB metadata keys must be validated against an explicit allowlist: trade placement errors (error_code, error_message), reconciliation (reason, detected_at, bybit_exec_id), partial close (parent_trade_id, child_qty). Unknown keys are rejected at the repository layer.
FR-045: The sort column must be resolved via a hardcoded dictionary mapping (SORT_COLUMNS = {"created_at": "t.created_at", ...}). The mapped value, not user input, is interpolated into SQL. Direct interpolation of user-supplied sort values is prohibited even after allowlist validation.
FR-046: The symbol filter parameter must match ^[A-Z0-9/]{1,30}$. Non-matching values return 400.
FR-047: Routes /trades/open and /trades/stats MUST be registered before /trades/{trade_id} in the router to prevent path parameter capture. Additionally, trade_id must be validated as UUID format.
FR-048: WebSocket event payloads must follow defined schemas — trade.opened: {trade_id, account_id, symbol, side, qty, entry_price, status}. trade.closed: {trade_id, account_id, symbol, close_reason, realized_pnl, exit_price}. trade.close_failed: {trade_id, account_id, error_code}. No metadata or internal fields.
FR-049: All post-commit WebSocket broadcasts are fire-and-forget. Failures are logged at WARN level but do not trigger retries or rollbacks. Clients must treat WS events as best-effort and use GET /trades/open on connect for authoritative state.
FR-050: The immutability trigger on trade_events must check current_setting('app.purge_mode', true) = 'true' for DELETE operations to allow authorized retention purges. UPDATE is always rejected.
FR-051: Reconciliation may perform open→closing→closed atomically via a dedicated reconcile_close() method that performs both transitions within one transaction with two version increments. This bypasses per-step state machine validation.
FR-052: New trade endpoints should use FastAPI response_model parameter for automatic Pydantic serialization (improvement over existing raw dict returns).
FR-053: WebSocket channel subscription must validate that the connecting client is authorized for the requested account_id. Unauthorized subscription attempts rejected with WS close frame (4403).
FR-054: Trade lookup must use WHERE account_id = $account_id AND id = $trade_id as a single query. 404 returned for any trade_id not owned by the path account regardless of actual status. Status-specific 409 codes only returned after account ownership confirmed.
FR-055: After a failed close attempt (Bybit error), before reverting to open, query Bybit position status. If position is gone, proceed to reconcile_close() instead of reverting.
FR-056: When total_trades=0, stats endpoint returns win_rate=0.0, avg_pnl=0.0, total_pnl=0.0, avg_hold_time=null.
FR-057: Stats cache invalidation must trigger on trade INSERT with terminal status (closed/failed/cancelled), not only on UPDATE transitions.
FR-058: Rate limiter is in-memory per-process (single-worker deployment). Implemented as FastAPI dependency injection, not middleware.
FR-059: Cursor query parameter must be rejected if it exceeds 256 bytes before base64 decoding.
FR-060: Stats cache must use LRU with max 1000 entries to prevent memory exhaustion from varied filter combinations.
```

## I. Non-Functional Requirements

```
NFR-001: Trade list endpoint must respond within 200ms for up to 200 results per page.
NFR-002: Open trades endpoint must respond within 50ms (served from partial index or cache).
NFR-003: Reconciliation must complete within 10s per account per cycle.
NFR-004: DB writes must use jittered exponential backoff (5 retries) for transient errors only (08xxx, 40001). Never retry constraint violations (23xxx).
NFR-005: Connection pool: 20 base + 10 overflow, 30s timeout. Background jobs capped at 3 connections.
NFR-006: All JSONB metadata/payload fields limited to 8KB (octet_length check).
NFR-007: JSONB keys validated against application-layer allowlist. Values treated as untrusted on render.
NFR-008: API keys and secrets must never appear in logs or WebSocket payloads.
NFR-009: WebSocket error payloads must use sanitized error codes, never raw exceptions.
NFR-010: Cursor components validated after decode (UUID for trade_id, correct type for sort value). Malformed cursors return 400.
NFR-011: Trade state transitions validated by TradeRepository before UPDATE. Invalid transitions rejected.
NFR-012: trade_events uses BIGSERIAL PK for append-only durability.
NFR-013: updated_at column maintained by BEFORE UPDATE trigger.
NFR-014: All monetary/price columns use NUMERIC(20,8) for consistency.
```

## J. User Flows

### Primary: Place a trade
1. User selects account, enters trade parameters, clicks "Place Trade"
2. API inserts trade with status=pending, generates order_link_id
3. API calls Bybit place_market_order
4. On success: update trade to status=open, create filled event, broadcast trade.opened via WS
5. On failure: update trade to status=failed, create failed event

### Primary: Close a single trade
1. User clicks close on a specific trade
2. API validates trade is open/partially_filled (INVALID_STATUS_TRANSITION otherwise)
3. API sets status=closing with optimistic lock check
4. API calls Bybit place_market_close_order
5. On success: update with exit_price, PnL, close_reason=manual_single, status=closed, broadcast trade.closed
6. On failure: revert status to open, broadcast trade.close_failed

### Primary: Close all trades
1. User clicks "Close All" on account card
2. ClosePositionsService iterates open trades for account
3. Each trade: status=closing → Bybit close → status=closed with close_reason=manual_close_all
4. Broadcast trade.closed for each

### Primary: Rule-triggered close
1. CloseRuleEvaluator detects threshold breach
2. Calls close_all_for_rule with rule_id
3. Each trade: status=closing → Bybit → status=closed with close_reason=rule_triggered, close_rule_id set
4. Broadcast trade.closed for each

### Alternate: TP/SL detected by reconciliation
1. Reconciliation queries Bybit positions, finds position gone
2. Correlates with closed_pnl_records to determine TP vs SL
3. Updates trade: exit_price, PnL, close_reason=take_profit or stop_loss
4. Broadcast trade.closed

### Failure: Bybit rejects order
1. place_trade inserts pending trade
2. Bybit returns error
3. Trade updated to status=failed with error in metadata
4. No WS broadcast for trade.opened (trade never opened)

### Edge: Orphaned pending trade
1. Trade inserted as pending, process crashes before Bybit call
2. Reconciliation sweeps pending trades older than 5 min with no order_id
3. Transitions to failed with metadata {"reason": "pending_timeout"}

### Primary: Cancel a pending trade
1. User clicks cancel on a pending trade
2. API validates trade is in `pending` status
3. API cancels order on Bybit
4. Trade transitions to status=cancelled
5. No PnL calculation (trade never opened)

### Alternate: Cancel a partially filled trade
1. User clicks cancel on a partially filled limit order
2. API cancels the unfilled remainder on Bybit
3. The filled portion transitions to status=open (as a live position)
4. The trade qty is updated to reflect only the filled amount
5. Broadcast trade.opened for the now-open position

### Alternate: Partial close
1. User specifies qty < remaining open qty on close endpoint
2. API validates qty is positive and ≤ remaining open quantity
3. API creates a child trade (parent_trade_id = original trade) for the closed portion
4. API closes qty on Bybit
5. Parent trade transitions to partially_closed
6. Child trade is created with status=closed, PnL for the closed portion
7. Subsequent full close closes the remainder

### Failure: Close attempt fails on Bybit
1. API sets trade status to closing
2. Bybit returns error (e.g., position not found, insufficient qty)
3. Trade status reverts to open
4. Broadcast trade.close_failed with sanitized error_code

## K. API Requirements

### GET /accounts/{account_id}/trades
- **Method:** GET
- **Parameters:** status, symbol, side, close_reason, from_date, to_date, sort, cursor, limit (default 50, max 200), include_total
- **Response:** `{items: [TradeResponse], cursor: string|null, has_more: bool, total?: int}`
- **Status codes:** 200 OK, 400 invalid filter/cursor, 404 account not found
- **Pagination:** Keyset on (sort_column, id), cursor is base64-encoded, validated on decode

### GET /accounts/{account_id}/trades/{trade_id}
- **Method:** GET
- **Response:** `TradeDetailResponse` (trade + events array)
- **Status codes:** 200 OK, 404 TRADE_NOT_FOUND (filters by account_id AND trade_id)

### GET /accounts/{account_id}/trades/open
- **Method:** GET
- **Response:** `{items: [TradeResponse]}` (no pagination, open trades only)
- **Status codes:** 200 OK, 404 account not found

### GET /accounts/{account_id}/trades/stats
- **Method:** GET
- **Response:** `TradeStatsResponse` (total_trades, win_rate, avg_pnl, total_pnl, avg_hold_time)
- **Status codes:** 200 OK
- **Caching:** Served from in-memory cache, invalidated on trade closure and terminal state transitions

### POST /accounts/{account_id}/trades/{trade_id}/close
- **Method:** POST
- **Body:** `{qty?: number}` (optional for partial close; must be positive and ≤ remaining open qty)
- **Response:** `TradeResponse` (updated trade)
- **Status codes:** 200 OK, 400 invalid qty, 404 TRADE_NOT_FOUND, 409 TRADE_ALREADY_CLOSED / INVALID_STATUS_TRANSITION / CONCURRENT_MODIFICATION, 502 EXCHANGE_REJECTION

### POST /accounts/{account_id}/trades/{trade_id}/cancel
- **Method:** POST
- **Response:** `TradeResponse` (updated trade)
- **Status codes:** 200 OK, 404 TRADE_NOT_FOUND, 409 INVALID_STATUS_TRANSITION / CONCURRENT_MODIFICATION, 502 EXCHANGE_REJECTION

## L. UI/UX Requirements

Not applicable — backend-only feature. Frontend changes are out of scope.

## M. Backend Requirements

### Services to create
- `TradeRepository` (`backend/services/trade_repository.py`): CRUD for trades and trade_events, state machine validation, optimistic locking, keyset pagination. Pure data access — no Bybit calls, no WS broadcasts, no cache management.
- `TradeService` (`backend/services/trade_service.py`): Orchestration layer for trade lifecycle operations (close, cancel, partial close). Coordinates TradeRepository + Bybit calls + post-commit WS broadcast + cache invalidation. Constructor: `TradeService(trade_repo: TradeRepository, accounts_service: AccountsService, ws_manager: AccountWSManager)`. Bybit client obtained via `accounts_service.get_client(account_id)` (new public method wrapping _build_client).
- `TradeReconciliationService` (`backend/services/trade_reconciliation.py`): 60s background job, startup sweep, orphan cleanup, Bybit position correlation. Constructor: `TradeReconciliationService(trade_repo: TradeRepository, accounts_service: AccountsService, ws_manager: AccountWSManager)`. Bybit client obtained via `accounts_service.get_client(account_id)`.

### Services to modify
- `AccountsService.place_trade()`: Insert trade (pending) before Bybit call, update after. **Breaking change:** Response now returns TradeResponse instead of raw Bybit dict. Frontend must be updated to use new shape.
- `AccountsService`: Add public `get_client(account_id) -> BybitClient` method wrapping existing `_build_client` for use by TradeService and TradeReconciliationService.
- `ClosePositionsService.close_all_positions()`: After closing a Bybit position for (symbol, side), query TradeRepository for all open trades matching account_id + symbol + side, then transition each to closed with close_reason=manual_close_all. A single Bybit position may correspond to multiple local trade records.
- `ClosePositionsService.close_all_for_rule()`: Same mapping strategy with close_reason=rule_triggered and rule_id
- `TradingCycleEngine._execute_cycle()`: Insert into trades with source=cycle after each trade
- `CloseRuleEvaluator`: Pass rule_id through to close service
- `AccountWSManager`: Broadcast trade.opened and trade.closed events (post-commit)
- `DELETE /accounts/{account_id}`: Catch FK constraint violation (IntegrityError) and return 409 with "Cannot delete account with existing trades"

### Schemas to add (backend/schemas.py)
- `TradeResponse`: Full trade fields
- `TradeDetailResponse`: Trade + events
- `TradeListResponse`: Items + cursor + has_more + optional total
- `TradeStatsResponse`: Aggregate stats
- `TradeEventResponse`: Event fields
- `TradeCloseRequest`: Optional qty with gt=0 constraint

### Routes to add (backend/routers/accounts.py)
- 6 new endpoints as defined in Section K

### Transaction boundaries
- create_trade + initial trade_event: single transaction, READ COMMITTED
- close_trade + closure trade_event + PnL: single transaction, READ COMMITTED
- WebSocket broadcast + cache invalidation: AFTER commit, owned by TradeService (not TradeRepository)

## N. Database/Data Requirements

Full DDL is defined in `specs/trade-storage-lifecycle-architecture.md` Section 4. Key points:

- **New tables:** `trades` (40+ columns, UUID PK) and `trade_events` (BIGSERIAL PK, append-only)
- **Migration #25** in both `persistence.py` and `async_persistence.py`
- **Rollback DDL:** Drop triggers, functions, tables (data-destructive, requires backup)
- **Indexes:** 13 indexes on trades (idx_trades_account_status_created for filtered pagination, idx_trades_active for non-terminal statuses, idx_trades_archived for retention, idx_trades_account_symbol for symbol filter, idx_trades_pending_orphan for reconciliation orphan sweep, plus keyset pagination indexes and unique constraints), 1 on trade_events (by trade_id).
- **Triggers:** updated_at auto-update on trades, immutability on trade_events (allows DELETE only with session flag app.purge_mode='true')
- **FKs:** account_id → trading_accounts (RESTRICT), source_id → trading_cycles (SET NULL), close_rule_id → close_rules (SET NULL), parent_trade_id → trades (RESTRICT), trade_events.trade_id → trades (RESTRICT)
- **Constraints:** CHECK on status, side, source, close_reason, order_type, margin_mode, metadata size, payload size, source/source_id consistency. CHECK on trade_events.old_status and new_status matching valid status enum (NULL allowed for old_status on initial event).
- **Dual persistence sync:** Extract migration #25 DDL into a shared SQL string constant or add CI check to diff migration SQL from both files.
- **Partitioning:** trade_events should use monthly range partitioning on created_at (cheap to add at creation, expensive to retrofit).

## O. Integration Requirements

### Bybit API
- **Place order:** POST /v5/order/create (existing BybitClient.place_market_order)
- **Close order:** POST /v5/order/create reduce-only (existing BybitClient.place_market_close_order)
- **Get positions:** GET /v5/position/list (existing, used by reconciliation)
- **Get closed PnL:** GET /v5/position/closed-pnl (existing, synced to closed_pnl_records)
- **No new Bybit integrations required**
- **Retry:** Existing exponential backoff in BybitClient
- **Rate limits:** Reconciliation skips cycle on 429, retries next interval

## P. Security Requirements

- **IDOR:** All trade queries (single, list, aggregate) filter by account_id from path parameter
- **Input validation:** Sort validated against hardcoded allowlist and resolved via dictionary mapping (never interpolated directly). Symbol must match ^[A-Z0-9/]{1,30}$. Dates validated as ISO 8601 (from_date ≤ to_date, max 1 year range, no future dates). Qty must be positive and ≤ remaining.
- **Rate limiting:** Per-account token bucket (10 req/s) on state-changing endpoints (place, close, cancel).
- **JSONB:** Keys validated against explicit allowlist (error_code, error_message, reason, detected_at, bybit_exec_id, parent_trade_id, child_qty). Values output-encoded on render. Size limited to 8KB.
- **Cursors:** Base64-decoded components validated (UUID for id, correct type for sort value). Forged cursors cannot leak cross-account data (WHERE account_id always applied).
- **Audit:** trade_events is append-only (immutability trigger). Purge via session-level flag under dedicated DB role.
- **Secrets:** API keys never logged. Error payloads use codes, not raw exceptions.
- **WebSocket:** Events scoped to account channel.

## Q. Performance Requirements

- **Caching:** Open trades cache (in-memory dict, invalidated post-commit on status changes and reconciled price updates). Stats cache (in-memory, invalidated on terminal state transitions, with 10s TTL as coalescing mechanism for rapid closures).
- **Pagination:** Keyset on (sort_column, id) with matching composite indexes. No OFFSET. Cursor encoding handles NULL sort values via sentinel.
- **include_total:** Optional, expensive — COUNT query only when requested. Cached per (account_id, filter_hash) with 30s TTL.
- **Connection pool:** 20 base + 10 overflow, 30s timeout. Background jobs capped at 3 via semaphore.
- **Advisory locks:** pg_try_advisory_lock with key (7001, 1) for reconciliation only. Non-blocking — skip if held.
- **Reconciliation:** 1 Bybit API call + 1 DB query per account per 60s. Max 5 accounts concurrent.
- **List endpoint:** Does NOT include events (avoids N+1). Use detail endpoint for events.

## R. Logging, Monitoring, and Observability

- **Trade state transitions:** Log trade_id, old_status, new_status, close_reason, latency_ms
- **Reconciliation:** Log account_id, open_count, discrepancies_found
- **Errors:** Full context with trade_id. Never log API keys.
- **WebSocket events:** trade.opened, trade.closed, trade.close_failed (sanitized error_code)
- **Critical alerts:** Bybit succeeds but DB update fails after all retries

## S. Edge Cases

- **Duplicate order_link_id:** UNIQUE constraint rejects — prevents duplicate trade placement
- **Concurrent close (user + reconciliation):** Optimistic lock (version column) — second writer gets 0 rows affected. If revert-to-open fails on lock, re-read trade: if now closed, return success (idempotent close); if unexpected status, return 409 CONCURRENT_MODIFICATION.
- **Close fails but position gone:** After Bybit close error, check position status before reverting. If position is gone (TP/SL hit during close attempt), reconcile_close() instead of reverting to open.
- **Close on already-closed trade:** Returns TRADE_ALREADY_CLOSED (409)
- **Close on pending trade:** Returns INVALID_STATUS_TRANSITION — use cancel endpoint
- **Partial close qty > remaining:** Returns 400 validation error
- **Process crash mid-close:** Trade stuck in closing status → startup reconciliation resolves
- **Orphaned pending trade:** Reconciliation sweeps after 5 min → transitions to failed
- **Bybit position gone (TP/SL):** Reconciliation detects → correlates with closed_pnl_records → updates trade
- **Cancel partially filled order:** Unfilled remainder cancelled, filled portion transitions to open
- **WebSocket events during startup:** Fire-and-forget. Clients must GET /trades/open on connect.
- **Deleted account with trades:** ON DELETE RESTRICT blocks deletion. Accounts with trades cannot be deleted.
- **Invalid date range:** from_date > to_date or range > 1 year returns 400. Future dates rejected.

## T. Testing Requirements

- **Unit tests:** TradeRepository (CRUD, state machine validation, optimistic locking, pagination), TradeReconciliationService (position correlation, orphan cleanup, advisory lock)
- **Integration tests:** Full trade lifecycle (place → close with PnL verification), reconciliation against mock Bybit responses, migration up/down
- **API tests:** All 6 endpoints — success cases, error cases (404, 409, 400), pagination, filters, cursor validation
- **Edge case tests:** Concurrent close, duplicate order_link_id, orphaned pending cleanup, partial close with child trade, cancel partially filled
- **Regression tests:** Existing place_trade still works, existing close-all still works, existing cycle trades still work, close rules still trigger correctly
- **WebSocket tests:** trade.opened broadcast on successful placement, trade.closed on closure, trade.close_failed on failure, events scoped to correct account channel, no broadcast on failed placement
- **Security tests:** Cross-account trade access returns 404 (IDOR), forged cursor cannot leak data, JSONB keys outside allowlist rejected, sort injection blocked, API keys never in error responses
- **NFR tests:** JSONB 8KB limit enforcement, cursor validation (malformed returns 400), NUMERIC precision verification, retry behavior for transient vs constraint errors

## U. Acceptance Criteria

```
AC-001: Given a trade placed via the API, when the Bybit order succeeds, then a trade record exists with status=open, correct entry_price, and a trade_event with event_type=filled.
AC-002: Given an open trade, when the user closes it manually, then the trade has status=closed, close_reason=manual_single, and realized_pnl is computed correctly.
AC-003: Given multiple open trades, when the user clicks close-all, then all trades have status=closed with close_reason=manual_close_all.
AC-004: Given an active close rule, when the threshold is breached, then all trades in the account are closed with close_reason=rule_triggered and correct close_rule_id.
AC-005: Given a trade with TP set, when Bybit fills the TP, then reconciliation detects it and sets close_reason=take_profit within 60 seconds.
AC-006: Given a trade with SL set, when Bybit fills the SL, then reconciliation detects it and sets close_reason=stop_loss within 60 seconds.
AC-007: Given a pending trade with no order_id older than 5 minutes, when reconciliation runs, then the trade is transitioned to status=failed.
AC-008: Given the GET /trades endpoint with sort=realized_pnl and cursor pagination, when requesting page 2, then results are correctly ordered and no records are skipped or duplicated.
AC-009: Given two concurrent close attempts on the same trade, when both hit the optimistic lock, then exactly one succeeds and the other receives CONCURRENT_MODIFICATION.
AC-010: Given a partial close request with qty=0.5 on a trade with qty=1.0, then a child trade is created with the closed portion's PnL, and the parent trade has status=partially_closed.
AC-011: Given a pending trade, when the user cancels it, then the order is cancelled on Bybit and the trade transitions to status=cancelled.
AC-012: Given a partially_filled trade, when the user cancels it, then the unfilled remainder is cancelled on Bybit and the filled portion transitions to status=open.
AC-013: Given a valid trade_id belonging to account A, when queried with account B's account_id, then a 404 TRADE_NOT_FOUND is returned.
AC-014: Given a sort parameter not in the allowlist (e.g., "id"), the API returns 400.
AC-015: Given an existing trade_event row, any UPDATE or DELETE statement is rejected by the immutability trigger.
AC-016: Given an open trade, when a close attempt fails on Bybit, then the trade status reverts to open and a trade.close_failed WebSocket event is broadcast with a sanitized error_code.
AC-017: Given a trade with status=closing and no corresponding open Bybit position, when the startup reconciliation sweep runs, then the trade is transitioned to status=closed with PnL.
AC-018: Given a trade placed via the API, when Bybit rejects the order, then the trade has status=failed and a trade_event with event_type=failed exists.
```

## V. Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Bybit API changes position response format | Medium | Low | Reconciliation logs discrepancies, manual review |
| Reconciliation misidentifies TP vs SL | Medium | Medium | Correlate with closed_pnl_records; log when uncertain |
| High index count impacts write performance | Low | Low | Single-user tool with low write volume; defer indexes if needed |
| Orphaned pending trades during prolonged outage | Medium | Low | 5-minute timeout + reconciliation sweep |
| Cache staleness affects rule evaluator | Medium | Medium | Post-commit invalidation + rule evaluator tolerates brief stale window |

## W. Assumptions

```
A-001:
Assumption: Bybit API position/closed-PnL endpoints remain stable
Risk level: Low
Reason: Using existing BybitClient methods already in production
Impact if incorrect: Reconciliation breaks, manual fix required

A-002:
Assumption: Single-user, single-instance deployment
Risk level: Low
Reason: Tool description and existing architecture assume local deployment
Impact if incorrect: Advisory locks and in-memory caches would need distributed alternatives

A-003:
Assumption: trading_cycles.id is SERIAL (INTEGER)
Risk level: Low
Reason: Verified in persistence.py and async_persistence.py
Impact if incorrect: source_id FK type mismatch
```

## X. Open Questions

No unresolved open questions. All design decisions documented in architecture ADR.

## Y. Traceability Matrix

| Requirement | Spec Section | Files Affected | Tests | Acceptance Criteria |
|-------------|-------------|----------------|-------|---------------------|
| FR-001 to FR-005 | H, M | accounts_service.py, trade_repository.py | Unit + Integration | AC-001 |
| FR-006 to FR-008 | H, N | trade_repository.py, async_persistence.py | Unit | AC-001 |
| FR-009 to FR-010 | H, M | trading_cycle_engine.py, accounts_service.py | Integration | AC-001 |
| FR-011 to FR-013 | H, M | close_positions_service.py, trade_repository.py | Integration | AC-002, AC-003, AC-004 |
| FR-014 to FR-016 | H, M | trade_reconciliation.py, trade_repository.py | Integration | AC-005, AC-006 |
| FR-017 to FR-018 | H, M | trade_repository.py | Unit | AC-009 |
| FR-019 to FR-020 | H, K | trade_repository.py, accounts.py | Unit + API | AC-010 |
| FR-021 to FR-022 | H, K | trade_repository.py, accounts.py | API | — |
| FR-023 to FR-026 | H, M | trade_reconciliation.py | Unit + Integration | AC-005, AC-006, AC-007 |
| FR-027 to FR-031 | H, K | trade_repository.py, accounts.py, schemas.py | API | AC-008 |
| FR-032 | H, R | account_ws_manager, trade_repository.py | Integration | AC-001, AC-002 |
| FR-033 to FR-035 | H, P | trade_repository.py, accounts.py | Unit + API | — |
| FR-036 | H, P | trade_repository.py | Unit | — |
| FR-037 | H, R | trade_service.py, close_positions_service.py | Unit | AC-016 |
| FR-038 | H, R | trade_reconciliation.py | Unit | AC-017 |
| FR-039 | H, P | trade_service.py | Unit | AC-018 |
| FR-040 | H, K | accounts.py (trade routes) | API | AC-014 |
| FR-041 | H, M | trade_repository.py, main.py | Integration | — |
| FR-042 | H, K | trade_repository.py, accounts.py | API + Unit | — |
| AC-011 | U | accounts_service.py, trade_service.py | Integration | FR-021 |
| AC-012 | U | accounts_service.py, trade_service.py | Integration | FR-022 |
| AC-013 | U | accounts.py, trade_repository.py | API | FR-033 |
| AC-014 | U | accounts.py | API | FR-034 |
| AC-015 | U | async_persistence.py (trigger) | Integration | FR-035 |
| AC-016 | U | trade_service.py, close_positions_service.py | Integration | FR-037 |
| AC-017 | U | trade_reconciliation.py | Integration | FR-023 |
| AC-018 | U | accounts_service.py, trade_repository.py | Integration | FR-001 |
| FR-043 | H, P | trade_service.py, accounts.py | Unit + API | — |
| FR-044 | H, M | trade_repository.py | Unit | — |
| FR-045 | H, M | trade_repository.py | Unit | FR-034 |
| FR-046 | H, P | accounts.py | API | — |
| FR-047 | H, K | accounts.py (router) | API | — |
| FR-048 | H, R | trade_service.py | Unit | — |
| FR-049 | H, M | trade_service.py | Unit | — |
| FR-050 | H, N | async_persistence.py (trigger) | Integration | AC-015 |
| FR-051 | H, M | trade_reconciliation.py | Integration | AC-017 |
| FR-052 | H, K | accounts.py, schemas.py | API | — |

## Z. Definition of Ready

- [x] Scope is clear (Section G)
- [x] Requirements are testable (Sections H, I — all numbered)
- [x] Edge cases documented (Section S)
- [x] Codebase impact understood (Section M — specific files listed)
- [x] Dependencies identified (Section O — Bybit only, all existing)
- [x] Risks documented (Section V)
- [x] Acceptance criteria measurable (Section U — 18 ACs)
- [x] No unresolved Critical or High findings (Architecture review R4+R5 clean)

---

## Appendix A: Deferred Requirements

The following requirement areas from the brainstorm (specs/trade-storage-lifecycle-requirements.md) are explicitly out of scope for this spec and deferred to future work:

- **Frontend trade history UI** — Requirements related to rendering trade tables, filters, and detail views in React. This spec covers backend/API only.
- **Advanced analytics dashboards** — Win rate charts, drawdown visualizations, strategy performance comparisons.
- **Multi-exchange support** — Currently Bybit-only; abstracting the exchange layer is future scope.
- **Trade journaling/notes** — User-attached notes or tags on individual trades.
- **Alert/notification system** — Push notifications for trade events beyond WebSocket broadcasts.

## Appendix B: Design Decision Notes

**Pagination pattern (cursor vs offset/limit):** The architecture specifies cursor-based keyset pagination on `(sort_column, id)` for the trade list endpoint. The existing codebase uses offset/limit (e.g., `PaginatedCycleList`). This spec adopts cursor-based pagination for the new trade endpoints because trade tables will grow unboundedly and offset pagination degrades at high offsets. Existing offset-based endpoints are not modified.
