# Specification: Account Close Positions with Conditional Rules

## A. Title and Metadata
- **Feature:** Account Close Positions with Conditional Rules
- **Date:** 2026-05-12
- **Author:** Claude Code
- **Status:** Draft
- **Related modules:** accounts, trading
- **Related files:** `frontend/src/components/accounts/AccountCard.tsx`, `backend/routers/accounts.py`, `backend/services/accounts_service.py`, `backend/services/bybit_client.py`, `backend/persistence.py`, `backend/scheduler.py`
- **Version:** 1.0

## B. Discovery Summary
- **AccountCard.tsx** (117 lines): Renders account cards with equity, PnL, positions. No actions menu exists.
- **BybitClient** (258 lines): Read-only — wallet balance, positions, orders, closed PnL. No order placement.
- **AccountsService** (994 lines): CRUD, caching (2-10s TTL), portfolio aggregation, analytics. No trade execution.
- **Persistence** (1764 lines): PostgreSQL with sequential migration keys. Tables: trading_accounts, closed_pnl_records, daily_snapshots, high_freq_snapshots.
- **Scheduler** (79 lines): SnapshotScheduler with snapshot_loop (60s) and cleanup_loop (3 AM). Pattern: async tasks with graceful cancellation.
- **Existing patterns:** Service injection via app.state, Fernet encryption for API keys, CSRF via X-Requested-With header, WebSocket fan-out via AccountWSManager.
- **Bybit V5 API:** POST /v5/order/create supports market orders with `reduceOnly=true` for closing positions.

## C. Feature Overview
- **What:** Add a 3-dot kebab menu to each account card with: (1) Close All Positions immediately, (2) Set Conditional Close Rules that auto-close positions when conditions are met.
- **Why:** Users need to manage risk by quickly closing all positions or setting automated guards (stop-loss, take-profit, drawdown limits) at the account level.
- **Who:** All users with connected trading accounts.
- **Problem solved:** No way to close positions or set automated risk management from the app — users must log into Bybit separately.
- **Expected outcome:** Users can close all positions with one click and set persistent server-side rules that protect against adverse market moves.

## D. Business Goal
- **Objective:** Enable active position management and automated risk protection.
- **User value:** One-click close-all + automated conditional close rules eliminate manual monitoring.
- **Success:** Users can close all positions within 5 seconds; conditional rules evaluate every 30 seconds and fire reliably.

## E. Current System Behavior
- Account cards display: label, type badge, equity, unrealized PnL, today PnL, positions count.
- Cards are clickable — navigate to account detail view.
- No actions/menus on cards.
- BybitClient is read-only (GET endpoints only).
- No order placement capability exists.
- Background scheduler only handles snapshots.

## F. Expected New Behavior
- Each account card has a 3-dot kebab menu in the top-right header area.
- Menu options: "Close All Positions" (destructive, red), "Conditional Rules", "View History".
- "Close All Positions" shows confirmation dialog, then submits market close orders for all open positions via Bybit V5 POST /v5/order/create with reduceOnly=true.
- "Conditional Rules" opens a modal to create/edit/delete/toggle rules.
- Rules are evaluated server-side every 30 seconds by a background service.
- When a condition is met, all open positions for that account are closed automatically.
- Close execution results (per-symbol success/failure) are stored in DB and surfaced in UI.
- WebSocket events notify the frontend of rule triggers and position closes.

## G. Scope

### In Scope
- 3-dot kebab menu on account cards
- Close All Positions (immediate market close via Bybit V5)
- Conditional close rules CRUD (create, read, update, delete, toggle)
- Rule types: balance threshold (above/below), equity % change (up/down), unrealized PnL threshold
- Server-side rule evaluation (30s polling interval)
- Close execution history and audit log
- WebSocket notifications for rule triggers
- DB migrations for close_rules and close_executions tables
- BybitClient extension for POST /v5/order/create

### Out of Scope
- Per-position selective close (only close-all)
- Multi-broker support (Bybit V5 only)
- User authentication/authorization (no auth system exists)
- Email/SMS notifications (in-app only)
- Rule templates or sharing between users
- Complex rule logic (no nested AND/OR — single condition per rule, multiple rules per account)
- Spot or inverse contract positions (linear USDT-settled only)

### Future Scope
- Per-position close from positions table
- Trailing stop rules
- Time-based rules (close at specific time)
- Webhook notifications
- Rule performance analytics

## H. Functional Requirements

FR-001: The system must display a 3-dot kebab menu icon on each account card header.
FR-002: The kebab menu must contain options: "Close All Positions", "Conditional Rules", "View History".
FR-003: "Close All Positions" must show a confirmation dialog with position count before executing.
FR-004: The system must close all open positions by placing market orders via Bybit V5 POST /v5/order/create with reduceOnly=true for each position.
FR-005: Close-all must execute orders concurrently (asyncio.gather) with per-account rate limiting.
FR-006: The system must return per-symbol results (success/failure with reason) for each close order.
FR-007: The system must store close execution records in the database (symbols, order responses, errors, trigger source).
FR-008: Users must be able to create conditional close rules for an account.
FR-009: Supported rule trigger types: BALANCE_BELOW, BALANCE_ABOVE, EQUITY_DROP_PCT, EQUITY_RISE_PCT, PNL_BELOW, PNL_ABOVE.
FR-010: Each rule stores: trigger_type, threshold_value, reference_value (for % rules), status (active/paused/triggered/expired).
FR-011: Maximum 10 active rules per account.
FR-012: Users must be able to pause/resume, edit, and delete rules.
FR-013: The server must evaluate all active rules every 30 seconds.
FR-014: When a rule condition is met, the system must close all open positions for that account.
FR-015: After triggering, the rule status must change to "triggered" (one-shot by default).
FR-016: The system must emit WebSocket events when a rule triggers or positions are closed.
FR-017: API key validity must be checked before allowing rule creation.
FR-018: Rules for deleted accounts must be cleaned up by the evaluator.
FR-019: Close execution history must be viewable per account.
FR-020: The kebab menu must not interfere with the card's click-to-navigate behavior.

## I. Non-Functional Requirements

NFR-001: Close-all API must respond within 30 seconds for up to 50 positions.
NFR-002: Rule evaluation loop must complete all accounts within one 30-second interval.
NFR-003: Per-account evaluation timeout of 10 seconds (skip on timeout, log warning).
NFR-004: Idempotency lock with 60-second TTL to prevent double-execution.
NFR-005: Decrypted API keys must never appear in logs or error responses.
NFR-006: All threshold comparisons must use Decimal precision, not floating-point.
NFR-007: Position cache must be flushed after close-all to prevent stale re-triggers.
NFR-008: Kebab menu must be keyboard navigable (arrow keys, Enter, Escape).
NFR-009: All new UI must support dark theme.
NFR-010: Mobile touch targets minimum 44x44px.

## J. User Flows

### Flow 1: Close All Positions (Happy Path)
1. User clicks 3-dot icon on account card.
2. Dropdown menu appears with options.
3. User clicks "Close All Positions".
4. Confirmation dialog shows: "Close all 20 positions for Sister-Demo? This action cannot be undone."
5. User clicks "Confirm".
6. Loading spinner appears on confirm button.
7. Backend receives POST /api/v1/accounts/{id}/positions/close-all.
8. Backend fetches current positions, places market close orders concurrently.
9. Response returns per-symbol results.
10. Success toast: "All 20 positions closed for Sister-Demo".
11. Account card updates (positions count drops, PnL adjusts via WebSocket/polling).

### Flow 2: Close All — Partial Failure
1-6. Same as Flow 1.
7. Backend closes 18 of 20 positions; 2 fail (no liquidity).
8. Warning toast: "18 of 20 positions closed. 2 failed — XYZUSDT: insufficient liquidity".
9. Failed positions remain open.

### Flow 3: Create Conditional Rule
1. User clicks 3-dot icon → "Conditional Rules".
2. Modal opens showing existing rules (or empty state).
3. User clicks "Add Rule".
4. New rule row appears: condition type dropdown + threshold input.
5. User selects "Equity Drop %" and enters "5".
6. Reference value auto-set to current equity at creation time.
7. User clicks "Save".
8. Rule saved to backend, modal shows updated list with toggle switch.
9. Account card shows active rule count badge.

### Flow 4: Rule Triggers
1. Background evaluator detects equity dropped 5% from reference.
2. System acquires idempotency lock for account.
3. System places market close orders for all positions.
4. Execution record stored in DB.
5. Rule status set to "triggered".
6. WebSocket event sent to frontend.
7. Toast notification: "Rule triggered: Equity dropped 5% — closing positions for Sister-Demo".
8. Account card updates.

### Flow 5: No Open Positions
1. User clicks 3-dot icon.
2. "Close All Positions" is disabled/greyed out with tooltip: "No open positions".

## K. API Requirements

### POST /api/v1/accounts/{account_id}/positions/close-all
- **Request:** Empty body
- **Response 200:** `{ "total": 20, "closed": 18, "failed": 2, "results": [{"symbol": "BTCUSDT", "status": "closed", "orderId": "..."}, {"symbol": "XYZUSDT", "status": "failed", "error": "..."}] }`
- **Response 404:** Account not found
- **Response 409:** Close already in progress (idempotency lock held)
- **Response 502:** Bybit API error

### POST /api/v1/accounts/{account_id}/close-rules
- **Request:** `{ "trigger_type": "EQUITY_DROP_PCT", "threshold_value": "5.0", "reference_value": "147.47" }` (reference_value is optional — server auto-sets from current equity if omitted for % rules)
- **Response 201:** Created rule object
- **Response 400:** Validation error / API key invalid / API key lacks trade permissions
- **Response 409:** Max rules reached

### GET /api/v1/accounts/{account_id}/close-rules
- **Response 200:** Array of rule objects

### PUT /api/v1/accounts/{account_id}/close-rules/{rule_id}
- **Request:** Partial update (threshold_value, status, reference_value)
- **Response 200:** Updated rule object
- **Response 404:** Rule not found

### DELETE /api/v1/accounts/{account_id}/close-rules/{rule_id}
- **Response 200:** `{ "status": "deleted" }`
- **Response 404:** Rule not found

### GET /api/v1/accounts/{account_id}/close-executions
- **Request query:** `page`, `limit`
- **Response 200:** Paginated array of execution records

## L. UI/UX Requirements

### Components
- **KebabMenu:** 3-dot icon button with dropdown (base-ui Menu or custom). Stops event propagation to prevent card navigation.
- **CloseAllConfirmDialog:** Modal with position count, warning text, confirm/cancel buttons.
- **ConditionalRulesDialog:** Full modal with rule list, add/edit/delete/toggle per rule.
- **RuleRow:** Condition type dropdown, threshold input, reference value display, toggle switch, delete button.
- **ActiveRuleBadge:** Small count badge on account card.
- **CloseHistoryDialog:** Paginated list of past close executions.

### States
- Menu: open/closed
- Close-all: idle → confirming → executing → success/error
- Rules dialog: loading (skeleton) → loaded → saving → saved/error
- Each rule: active/paused/triggered visual states

### Validation
- Threshold value: required, numeric, > 0 for amounts, 0.01-100 for percentages
- Reference value: auto-populated, optionally editable

### Accessibility
- Kebab button: `aria-label="Account actions for {label}"`
- Menu: keyboard navigable, focus trap
- Dialogs: focus trap, Escape to close, focus returns to trigger

## M. Backend Requirements

### New Files
- `backend/services/close_positions_service.py` — close-all logic, rule evaluation, execution recording
- `backend/routers/close_positions.py` — API endpoints

### Modified Files
- `backend/services/bybit_client.py` — add `place_market_close_order(symbol, side, qty)` method
- `backend/persistence.py` — add migration + CRUD methods for close_rules, close_executions
- `backend/schemas.py` — add request/response models
- `backend/main.py` — register new router, start rule evaluator in lifespan
- `backend/scheduler.py` — add CloseRuleEvaluator class (or separate file)

### Patterns to Follow
- Service injection via `request.app.state`
- `asyncio.to_thread()` for DB calls
- Fernet decrypt only at call time
- Rate limiting via existing BybitClient deque

## N. Database Requirements

### Table: close_rules
```sql
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
account_id UUID NOT NULL REFERENCES trading_accounts(id),
trigger_type VARCHAR(30) NOT NULL,  -- BALANCE_BELOW, BALANCE_ABOVE, EQUITY_DROP_PCT, EQUITY_RISE_PCT, PNL_BELOW, PNL_ABOVE
threshold_value NUMERIC(20,8) NOT NULL,
reference_value NUMERIC(20,8),  -- for % rules: equity at rule creation
comparison_op VARCHAR(5) DEFAULT '<=',
status VARCHAR(15) NOT NULL DEFAULT 'active',  -- active, paused, triggered, expired
expires_at TIMESTAMPTZ,
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
triggered_at TIMESTAMPTZ
```
Index: `(status, account_id)` for evaluator hot path.

### Table: close_executions
```sql
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
account_id UUID NOT NULL REFERENCES trading_accounts(id),
rule_id UUID REFERENCES close_rules(id),  -- NULL for manual close
trigger_source VARCHAR(10) NOT NULL,  -- 'manual' or 'rule'
total_positions INT NOT NULL,
closed_count INT NOT NULL,
failed_count INT NOT NULL,
results JSONB NOT NULL,  -- per-symbol details
executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

### Migration Strategy
- Add as next sequential migration key in `_MIGRATIONS` dict.
- Forward-only (no rollback — tables are additive).

## O. Integration Requirements

### Bybit V5 — POST /v5/order/create
- **Category:** linear
- **orderType:** Market
- **side:** Opposite of position side (Buy position → Sell to close, Sell position → Buy to close)
- **qty:** Full position size
- **reduceOnly:** true
- **Auth:** HMAC-SHA256 signing — **CRITICAL: POST requests must include JSON body in the signature string** (unlike GET which signs query params). The existing `_request` method passes empty string for POST; must serialize JSON body and pass to `_sign`.
- **Rate limit:** 10 orders/second (enforce via existing rate limiter)
- **Retry:** 3 attempts, exponential backoff (0.5s, 1s, 2s)
- **Idempotency:** Check position still exists before placing order
- **Error sanitization:** Map Bybit error codes to internal error messages; never pass raw Bybit errors to client

## P. Security Requirements
- Close-all endpoint rate-limited: max 1 request per 5 seconds per account.
- API keys decrypted only in-memory during order placement.
- Threshold values validated: amounts between -1,000,000 and 10,000,000; percentages between 0.01 and 100.
- Execution records immutable (no update/delete endpoints).
- CSRF protection via existing X-Requested-With middleware.

## Q. Performance Requirements
- Close-all for 50 positions: < 30 seconds (concurrent, rate-limited).
- Rule evaluation for 100 accounts × 10 rules: < 30 seconds total.
- Per-account evaluation timeout: 10 seconds.
- Position/wallet cache reused from existing 2-3s TTL cache.

## R. Logging & Observability
- Log each close order attempt: account_id, symbol, side, qty, result (no API keys).
- Log each rule evaluation: rule_id, condition_result, action_taken.
- Log execution summary: account_id, trigger_source, closed/failed counts.
- Emit WebSocket events: `close_positions.started`, `close_positions.completed`, `rule.triggered`.

## S. Edge Cases
- Zero open positions: return success with total=0.
- Position already closed between fetch and order: Bybit rejects with retCode, handle gracefully.
- Account deactivated mid-close: complete in-flight orders, don't start new ones.
- Rule triggers on empty position set: log event, rule still transitions to "triggered".
- Concurrent manual + rule close: idempotency lock prevents double-execution (409 for second caller).
- Bybit maintenance/downtime: orders fail, retries exhaust, execution records failure.
- Scheduler restart: rules re-evaluate on next tick (stateless evaluation).

## T. Testing Requirements
- Unit tests: BybitClient.place_market_close_order, rule evaluation logic, threshold comparisons.
- Integration tests: close-all API endpoint, rule CRUD endpoints.
- Edge case tests: partial failure, zero positions, concurrent lock, expired rules.
- Frontend tests: kebab menu rendering, confirmation dialog flow, rule form validation.

## U. Acceptance Criteria

AC-001: Given an account with 20 open positions, when user clicks "Close All Positions" and confirms, then all 20 market close orders are placed and per-symbol results are shown.
AC-002: Given no open positions, when user opens kebab menu, then "Close All Positions" is disabled.
AC-003: Given a rule "Equity Drop 5%" with reference $147.47, when equity drops to $140.10, then all positions are closed automatically.
AC-004: Given a rule triggers, when close completes, then the rule status changes to "triggered" and a WebSocket notification is sent.
AC-005: Given a close-all is in progress, when another close-all is attempted, then 409 is returned.
AC-006: Given partial failure (3 of 20 fail), when close completes, then response shows 17 closed, 3 failed with per-symbol details.
AC-007: Given the user creates 10 rules, when they try to add an 11th, then 409 is returned with "max rules reached".

## V. Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Bybit API key lacks trade permissions | High | Medium | Validate key permissions at rule creation; show clear error |
| Rate limit exceeded during large close-all | Medium | Low | Respect 10 req/s limit; queue/throttle orders |
| Rule evaluator misses condition due to stale cache | Medium | Medium | Use fresh API data for rule evaluation, not cached |
| Partial close leaves inconsistent state | Medium | Medium | Store per-symbol results; surface to user for manual retry |

## W. Assumptions

A-001: Bybit V5 API supports market close with reduceOnly=true for all linear positions. Risk: Low.
A-002: Existing API key permissions include trade scope (users configured this at account creation). Risk: Medium. Impact: close orders rejected.
A-003: No user authentication system needed (single-user app). Risk: Low.
A-004: USDT-settled linear contracts only. Risk: Low.

## X. Open Questions — RESOLVED

Q-001: Rules are **one-shot** — trigger once, status becomes "triggered". User can manually reactivate by setting status back to "active" via PUT endpoint.
Q-002: Rule evaluation uses **fresh API call** to Bybit (not cached data) to ensure accuracy. Rate limit managed by existing BybitClient throttling.

## X.1 Review Fixes Applied (Round 1)
- POST signing: spec updated to require JSON body in HMAC signature string
- Idempotency lock: in-memory asyncio.Lock per account_id (single-process deployment)
- Rule evaluator lifecycle: separate service started in main.py lifespan (follows ScanSchedulerService pattern)
- Reference_value: optional in POST body; server auto-sets from current equity if omitted
- Bybit error sanitization: map to internal error codes before client response
- Soft-deleted accounts: rule evaluator filters by `deleted_at IS NULL`
- Threshold validation: Pydantic model enforces numeric type, min/max bounds, decimal precision

## Y. Traceability Matrix

| Req | Spec Section | Files | Tests | AC |
|-----|-------------|-------|-------|----|
| FR-001 | L | AccountCard.tsx | Frontend test | - |
| FR-004 | K, O | bybit_client.py, close_positions_service.py | Unit + Integration | AC-001 |
| FR-008-012 | K | close_positions.py, persistence.py | CRUD tests | AC-007 |
| FR-013-015 | M | close_positions_service.py, scheduler.py | Unit test | AC-003, AC-004 |
| FR-006 | K | close_positions_service.py | Unit test | AC-006 |
