# Implementation Plan: Account Close Positions with Conditional Rules

## A. Metadata
- **Date:** 2026-05-12
- **Status:** Draft
- **Spec:** `specs/account-close-positions-spec.md` v1.0
- **Version:** 1.0

## B. Planning Summary
- **What:** 3-dot kebab menu on account cards → close all positions + conditional auto-close rules
- **Approach:** 4 phases — DB + Bybit writes → Backend service + API → Frontend UI → Rule evaluator
- **Key files:** bybit_client.py, persistence.py, new close_positions_service.py, new close_positions.py router, AccountCard.tsx, new dialog components, main.py, schemas.py
- **Key risk:** Bybit POST signing (body in HMAC) — must test thoroughly

## C. Source Specification
- Spec: `specs/account-close-positions-spec.md`
- Requirements: FR-001 through FR-020, NFR-001 through NFR-010
- Acceptance criteria: AC-001 through AC-007

## D. Implementation Strategy
- **Phase 1 — Foundation:** DB migrations + BybitClient POST support
- **Phase 2 — Backend Service & API:** ClosePositionsService + REST endpoints
- **Phase 3 — Frontend:** Kebab menu, confirmation dialog, rules dialog, history dialog
- **Phase 4 — Rule Evaluator:** Background scheduler for condition monitoring
- **Pattern reuse:** Follow existing service injection, persistence migration pattern, SnapshotScheduler lifecycle, AccountCard component structure
- **TDD:** Write tests first for each task, then implement

## E. Phase Breakdown

### Phase 1: Foundation (DB + Bybit Write)
**Goal:** Add database tables and Bybit order placement capability.
**Files:** persistence.py, bybit_client.py, schemas.py
**Completion:** Can place market close orders via BybitClient and store rules/executions in DB.

### Phase 2: Backend Service & API
**Goal:** Create ClosePositionsService and REST endpoints.
**Files:** new close_positions_service.py, new close_positions.py, main.py, schemas.py
**Completion:** All 6 API endpoints functional and tested.

### Phase 3: Frontend UI
**Goal:** Kebab menu on cards, all dialogs, WebSocket integration.
**Files:** AccountCard.tsx, new KebabMenu.tsx, CloseAllConfirmDialog.tsx, ConditionalRulesDialog.tsx, CloseHistoryDialog.tsx, client.ts
**Completion:** Full UI flow works end-to-end.

### Phase 4: Rule Evaluator
**Goal:** Background service that evaluates rules every 30s.
**Files:** new close_rule_evaluator.py, main.py
**Completion:** Rules auto-trigger position closes when conditions met.

## F. Task Breakdown

### Phase 1 Tasks

TASK-001: Add DB migration for close_rules and close_executions tables
- **Req:** FR-008, FR-010, FR-007
- **File:** `backend/persistence.py`
- **Details:** Add next sequential migration key(s) to `_MIGRATIONS` dict. Create `close_rules` table (id UUID, account_id UUID FK, trigger_type VARCHAR(30), threshold_value NUMERIC(20,8), reference_value NUMERIC(20,8), status VARCHAR(15) DEFAULT 'active', expires_at TIMESTAMPTZ, created_at, updated_at, triggered_at). Create `close_executions` table (id UUID, account_id UUID FK, rule_id UUID FK nullable, trigger_source VARCHAR(10), total_positions INT, closed_count INT, failed_count INT, results JSONB, executed_at TIMESTAMPTZ). Add index on close_rules(status, account_id).
- **Test:** Verify migration runs, tables exist, constraints hold.

TASK-002: Add CRUD methods to persistence.py for close_rules
- **Req:** FR-008, FR-012
- **File:** `backend/persistence.py`
- **Details:** Add methods: `insert_close_rule(rule_dict) -> dict`, `list_close_rules(account_id) -> list[dict]`, `get_close_rule(rule_id) -> dict|None`, `update_close_rule(rule_id, **fields) -> dict|None`, `delete_close_rule(rule_id) -> bool`, `list_active_rules() -> list[dict]` (filters status='active' AND account deleted_at IS NULL).
- **Test:** Unit test each CRUD method.

TASK-003: Add CRUD methods to persistence.py for close_executions
- **Req:** FR-007, FR-019
- **File:** `backend/persistence.py`
- **Details:** Add methods: `insert_close_execution(execution_dict) -> dict`, `list_close_executions(account_id, page, limit) -> dict` (paginated with total_count).
- **Test:** Unit test each method.

TASK-004: Add POST request support to BybitClient._request
- **Req:** FR-004, spec section O (CRITICAL: POST signing)
- **File:** `backend/services/bybit_client.py`
- **Details:** Modify `_request` method to handle POST: serialize params as JSON body, pass JSON string to `_sign` for HMAC signature (not empty string). Add `json=params` to `session.request` for POST method. Key change: `if method == "POST": body_str = json.dumps(params, separators=(',', ':')); headers = self._headers(timestamp, body_str)` and pass `json=params` to aiohttp request.
- **Test:** Unit test that POST requests produce correct HMAC signature including body.

TASK-005: Add place_market_close_order method to BybitClient
- **Req:** FR-004
- **File:** `backend/services/bybit_client.py`
- **Details:** Add method `async def place_market_close_order(self, symbol: str, side: str, qty: str) -> dict` that calls POST /v5/order/create with `{"category": "linear", "symbol": symbol, "side": "Sell" if side == "Buy" else "Buy", "orderType": "Market", "qty": qty, "reduceOnly": true}`. Returns order result dict.
- **Test:** Unit test with mocked HTTP.

TASK-006: Add Pydantic schemas for close rules and executions
- **Req:** FR-008, FR-009, section P validation
- **File:** `backend/schemas.py`
- **Details:** Add `CreateCloseRuleRequest(trigger_type: Literal[...], threshold_value: Decimal, reference_value: Optional[Decimal])` with validators: threshold > 0 for amounts, 0.01-100 for percentages. Add `UpdateCloseRuleRequest(threshold_value, reference_value, status: Optional[Literal['active','paused']])`. Add response models.
- **Test:** Unit test validation (valid + invalid inputs).

### Phase 2 Tasks

TASK-007: Create ClosePositionsService
- **Req:** FR-004, FR-005, FR-006, FR-014
- **File:** `backend/services/close_positions_service.py` (new)
- **Details:** Class with `__init__(self, db, accounts_service)`. Methods:
  - `async close_all_positions(account_id) -> dict`: Acquires in-memory asyncio.Lock per account_id. Fetches positions via accounts_service. Places market close orders concurrently (asyncio.gather with return_exceptions=True). Records execution in DB. Returns per-symbol results. Rate-limits at 10/s.
  - `async create_rule(account_id, rule_data) -> dict`: Validates API key, checks max rules (10), auto-sets reference_value from current equity for % rules if not provided. Inserts into DB.
  - `async list_rules(account_id) -> list`
  - `async update_rule(rule_id, data) -> dict`
  - `async delete_rule(rule_id) -> bool`
  - `async list_executions(account_id, page, limit) -> dict`
- **Deps:** TASK-001, TASK-002, TASK-003, TASK-005
- **Test:** Unit test each method with mocked dependencies.

TASK-008: Create close_positions router
- **Req:** FR-001 through FR-020 (API surface)
- **File:** `backend/routers/close_positions.py` (new)
- **Details:** FastAPI router with 6 endpoints matching spec section K. Follow existing pattern from accounts.py: `_get_service()`, `_validate_account_id()`, try/except for ValueError, BybitAPIError. Sanitize Bybit errors before returning. Rate-limit close-all: reject if lock held (409).
- **Deps:** TASK-006, TASK-007
- **Test:** Integration test each endpoint.

TASK-009: Register service and router in main.py
- **Req:** System integration
- **File:** `backend/main.py`
- **Details:** In lifespan: create ClosePositionsService, attach to app.state. Register close_positions router with prefix `/api/v1`. Order: after AccountsService creation.
- **Deps:** TASK-007, TASK-008
- **Test:** App starts without error, endpoints accessible.

### Phase 3 Tasks

TASK-010: Add API client methods for close positions
- **Req:** Frontend integration
- **File:** `frontend/src/api/client.ts`
- **Details:** Add methods: `closeAllPositions(accountId)`, `getCloseRules(accountId)`, `createCloseRule(accountId, data)`, `updateCloseRule(accountId, ruleId, data)`, `deleteCloseRule(accountId, ruleId)`, `getCloseExecutions(accountId, page, limit)`.
- **Deps:** TASK-008

TASK-011: Add KebabMenu to AccountCard
- **Req:** FR-001, FR-002, FR-020
- **File:** `frontend/src/components/accounts/AccountCard.tsx`
- **Details:** Add 3-dot icon button (lucide MoreVertical) in card header, positioned after status. Use onClick with stopPropagation to prevent card navigation. Dropdown menu with 3 items: "Close All Positions" (red, XCircle icon), "Conditional Rules" (SlidersHorizontal icon), "View History" (History icon). Menu state managed with useState. Close on outside click (useEffect listener) and Escape key. Disable "Close All" when positions_count === 0.
- **Deps:** TASK-010
- **Test:** Component renders, menu opens/closes, items clickable.

TASK-012: Create CloseAllConfirmDialog
- **Req:** FR-003, AC-001, AC-006
- **File:** `frontend/src/components/accounts/CloseAllConfirmDialog.tsx` (new)
- **Details:** Modal dialog: "Close all {N} positions for {label}? This cannot be undone." Confirm button (red, destructive). Loading state while executing. On success: green toast. On partial failure: warning toast with details. On total failure: error toast with retry. Calls `closeAllPositions(accountId)`.
- **Deps:** TASK-010, TASK-011

TASK-013: Create ConditionalRulesDialog
- **Req:** FR-008-012, AC-003, AC-007
- **File:** `frontend/src/components/accounts/ConditionalRulesDialog.tsx` (new)
- **Details:** Modal with: skeleton loading state → rule list (or empty state "No rules set"). Each rule row: condition type dropdown (BALANCE_BELOW, BALANCE_ABOVE, EQUITY_DROP_PCT, EQUITY_RISE_PCT, PNL_BELOW, PNL_ABOVE), threshold input, reference value display (for % rules), toggle switch (active/paused), delete button. "Add Rule" button. Save button. Inline validation (red border + message). Max 10 rules enforced in UI.
- **Deps:** TASK-010, TASK-011

TASK-014: Create CloseHistoryDialog
- **Req:** FR-019
- **File:** `frontend/src/components/accounts/CloseHistoryDialog.tsx` (new)
- **Details:** Modal with paginated list of close executions. Each row: timestamp, trigger source (manual/rule), positions closed/failed, expandable details. Empty state: "No close history yet."
- **Deps:** TASK-010, TASK-011

TASK-015: Add active rule count badge to AccountCard
- **Req:** FR-012 visual indicator
- **File:** `frontend/src/components/accounts/AccountCard.tsx`
- **Details:** Fetch rule count via API (or include in dashboard response). Show small badge next to kebab icon when active rules > 0. Badge: small circle with count, accent color.
- **Deps:** TASK-013

TASK-016: Add WebSocket handling for close events
- **Req:** FR-016
- **File:** `frontend/src/hooks/useAccountWebSocket.ts` (modify)
- **Details:** Handle new event types: `close_positions.completed`, `rule.triggered`. On receipt: show toast notification, trigger dashboard refresh.
- **Deps:** TASK-009

### Phase 4 Tasks

TASK-017: Create CloseRuleEvaluator service
- **Req:** FR-013, FR-014, FR-015, AC-003, AC-004
- **File:** `backend/services/close_rule_evaluator.py` (new)
- **Details:** Class with async `start()`, `shutdown()`, `_evaluation_loop()` methods (follow SnapshotScheduler pattern). Every 30 seconds: fetch all active rules (filtered by deleted_at IS NULL on accounts). For each rule, fetch fresh wallet/position data from Bybit. Evaluate condition. If triggered: acquire lock → close all positions → record execution → update rule status to 'triggered' → emit WebSocket event. Per-account timeout: 10s. Concurrency: semaphore(5) for parallel account evaluation.
- **Deps:** TASK-007
- **Test:** Unit test evaluation logic with various conditions.

TASK-018: Wire CloseRuleEvaluator into app lifespan
- **Req:** System integration
- **File:** `backend/main.py`
- **Details:** In lifespan: create CloseRuleEvaluator(close_service, accounts_service, db). Start in startup, shutdown in cleanup.
- **Deps:** TASK-017

TASK-019: Add dashboard endpoint enhancement for active_rules_count
- **Req:** FR-012 visual indicator (backend support)
- **File:** `backend/services/accounts_service.py`, `backend/routers/portfolio.py`
- **Details:** In get_dashboard(), add `active_rules_count` field per account card by querying close_rules count where status='active'.
- **Deps:** TASK-002

## G. File-Level Change Plan

| File | Action | Purpose | Tasks |
|------|--------|---------|-------|
| `backend/persistence.py` | Modify | Add migrations + CRUD for close_rules, close_executions | 1,2,3 |
| `backend/services/bybit_client.py` | Modify | POST signing fix + place_market_close_order | 4,5 |
| `backend/schemas.py` | Modify | Add request/response models | 6 |
| `backend/services/close_positions_service.py` | Create | Core close-all + rule management logic | 7 |
| `backend/routers/close_positions.py` | Create | REST API endpoints | 8 |
| `backend/main.py` | Modify | Register service, router, evaluator | 9,18 |
| `backend/services/close_rule_evaluator.py` | Create | Background rule evaluation loop | 17 |
| `backend/services/accounts_service.py` | Modify | Add active_rules_count to dashboard | 19 |
| `frontend/src/api/client.ts` | Modify | Add close positions API methods | 10 |
| `frontend/src/components/accounts/AccountCard.tsx` | Modify | Add kebab menu + rule badge | 11,15 |
| `frontend/src/components/accounts/CloseAllConfirmDialog.tsx` | Create | Confirmation dialog | 12 |
| `frontend/src/components/accounts/ConditionalRulesDialog.tsx` | Create | Rule builder modal | 13 |
| `frontend/src/components/accounts/CloseHistoryDialog.tsx` | Create | Execution history modal | 14 |
| `frontend/src/hooks/useAccountWebSocket.ts` | Modify | Handle close events | 16 |

## H. API Change Plan
See spec section K for complete endpoint specifications. All new endpoints under `/api/v1/accounts/{id}/`. No breaking changes to existing endpoints.

## I. Database/Migration Plan
- Two new tables: close_rules, close_executions (see TASK-001)
- Forward-only migration (additive tables)
- No data backfill needed
- Index on close_rules(status, account_id) for evaluator performance

## Q. Dependency and Sequencing

**Critical path:** TASK-001 → TASK-002/3 → TASK-004/5/6 → TASK-007 → TASK-008 → TASK-009 → TASK-010 → TASK-011 → TASK-012/13/14

**Parallelizable:**
- TASK-002 and TASK-003 (both persistence, independent tables)
- TASK-004 and TASK-006 (different files)
- TASK-012, TASK-013, TASK-014 (independent dialog components)
- TASK-017 can start after TASK-007

## R. Traceability Matrix

| Req | Task | Files | AC |
|-----|------|-------|----|
| FR-001 | 11 | AccountCard.tsx | - |
| FR-002 | 11 | AccountCard.tsx | - |
| FR-003 | 12 | CloseAllConfirmDialog.tsx | AC-001 |
| FR-004 | 4,5,7 | bybit_client.py, close_positions_service.py | AC-001 |
| FR-005 | 7 | close_positions_service.py | AC-001 |
| FR-006 | 7,8 | close_positions_service.py, close_positions.py | AC-006 |
| FR-007 | 3,7 | persistence.py, close_positions_service.py | - |
| FR-008 | 2,6,7,8,13 | persistence.py, schemas.py, service, router, dialog | AC-007 |
| FR-009 | 6,13 | schemas.py, ConditionalRulesDialog.tsx | AC-003 |
| FR-013-015 | 17 | close_rule_evaluator.py | AC-003, AC-004 |
| FR-016 | 16,17 | useAccountWebSocket.ts, evaluator | AC-004 |
| FR-020 | 11 | AccountCard.tsx | - |

## N. Manual Verification Checklist
1. Start backend + frontend
2. Open Accounts page — verify kebab icons visible on cards
3. Click kebab → verify menu appears, doesn't navigate
4. Click "Close All Positions" → verify confirmation dialog
5. Confirm → verify positions close (on demo account)
6. Check toast notification
7. Click "Conditional Rules" → verify dialog opens
8. Create a rule (Equity Drop 5%) → verify saved
9. Verify rule badge appears on card
10. Wait for condition to trigger (or simulate) → verify auto-close
11. Click "View History" → verify execution records

## S. Definition of Done
- All 19 tasks complete with tests passing
- All 7 acceptance criteria verified
- Manual verification checklist passed on demo account
- No unresolved Critical/High findings

## T. Plan Review Fixes Applied

### TASK-007 Lock Pattern (Critical)
- Use `defaultdict(asyncio.Lock)` at class level: `self._locks: dict[str, asyncio.Lock] = {}`
- Always use `async with self._get_lock(account_id):` context manager pattern (auto-releases on exception)
- For non-blocking check (409): use `lock.locked()` pre-check, then `try: await asyncio.wait_for(lock.acquire(), timeout=0.1)` pattern

### TASK-006 Trigger Types (Resolved)
- `trigger_type: Literal["BALANCE_BELOW", "BALANCE_ABOVE", "EQUITY_DROP_PCT", "EQUITY_RISE_PCT", "PNL_BELOW", "PNL_ABOVE"]`

### TASK-017 Evaluation Atomicity
- Use atomic SQL: `UPDATE close_rules SET status='triggered', triggered_at=NOW() WHERE id=%s AND status='active' RETURNING id` — if no row returned, another tick already triggered it (skip)
- Filter expired rules: `WHERE (expires_at IS NULL OR expires_at > NOW())`

### TASK-019 N+1 Fix
- Single batch query: `SELECT account_id, COUNT(*) FROM close_rules WHERE status='active' GROUP BY account_id`
- Merge into dashboard results in Python

### TASK-013 Save Behavior
- Save is **batch** (all rules saved together on "Save" click)
- Unsaved-changes guard: track dirty state, warn on dialog close if dirty
- Save button disabled when no changes

### TASK-015 Badge Strategy
- Consume `active_rules_count` from dashboard endpoint (TASK-019). No separate fetch.
- Depends on: TASK-019

### TASK-016 Toast Content
- Rule triggered: "Rule triggered for {label}: {N} positions closed" (green toast, 5s, auto-dismiss)
- Rule triggered with failures: "Rule triggered for {label}: {closed}/{total} positions closed" (amber toast, manual dismiss)
- No action link in toast (user can check via View History)

### API Key Permission Check
- In TASK-005: add method `async def test_trade_permission(self) -> bool` that attempts a minimal invalid order and checks error code (Bybit returns specific code for no-permission vs invalid-params)
- Called in TASK-007 `create_rule()` to validate before saving
