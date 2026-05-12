# Scheduled Market Scans — Implementation Plan

## Phase 1: Database & Schema Foundation

### Task 1.1: Add database migrations (v13, v14, v15)
**File**: `backend/persistence.py`
- Add migration (13, ...) for `scheduled_scans` table per spec section 3
- Add migration (14, ...) for `schedule_executions` table per spec section 3
- Add migration (15, ...) for `scans` table alterations (schedule_id, triggered_by)
- Add to `_MIGRATIONS` list after existing migration 12

### Task 1.2: Add persistence CRUD methods
**File**: `backend/persistence.py`
- `insert_scheduled_scan(data: dict) -> None`
- `update_scheduled_scan(id: str, fields: dict) -> None`
- `delete_scheduled_scan(id: str) -> bool`
- `list_scheduled_scans() -> list`
- `get_scheduled_scan(id: str) -> Optional[dict]`
- `get_due_scheduled_scans() -> list` — `WHERE status='active' AND next_run_at <= now() ORDER BY next_run_at ASC LIMIT 5`
- `claim_scheduled_scan(id: str, old_next: str, new_next: Optional[str]) -> bool` — atomic UPDATE...WHERE RETURNING
- `insert_schedule_execution(data: dict) -> int` — returns execution id
- `update_schedule_execution(id: int, fields: dict) -> None`
- `list_schedule_executions(schedule_id: str, limit: int = 20) -> list`
- `cleanup_old_executions(days: int = 90, min_keep: int = 100) -> int`
- `update_scan_schedule_link(scan_id: str, schedule_id: str, triggered_by: str) -> None`

### Task 1.3: Add Pydantic schemas
**File**: `backend/schemas.py`
- `ScheduleType` enum
- `ScheduleConfig` model with field validators
- `CreateScheduledScanRequest` with all validators (timezone, cron, scan_config, cross-validation)
- `UpdateScheduledScanRequest` with timezone + scan_config validators
- `ScheduledScanResponse`, `ScheduleExecutionResponse`

## Phase 2: Backend Service

### Task 2.1: Create ScanSchedulerService
**File**: `backend/services/scan_scheduler_service.py` (new)
- Constructor: scanner_service, db, config_service (config_service needed to resolve Optional scan_config fields at creation time)
- CRUD methods: create/update/delete/list/get/pause/resume
- `trigger_schedule(id)` — fire immediately, reject with 429 if last execution < 60s ago (cooldown check)
- `_compute_next_run(schedule)` — handles all 5 types per spec "next_run_at Calculation" rules:
  - once: run_at datetime (None after execution)
  - interval: max(now, last_completed_at) + interval_minutes
  - daily: next occurrence of time on specified days in schedule timezone
  - weekly: next occurrence of day at time in schedule timezone
  - cron: croniter.get_next() from now
- `_validate_cron_frequency(expression)` — check gap between first 2 runs >= 15 min
- `_sanitize_error(msg)` — truncate to 500 chars, strip file paths, never include API keys

### Task 2.2: Implement scheduler loop
**File**: `backend/services/scan_scheduler_service.py`
- `start()` / `shutdown()` — asyncio task lifecycle
- `_scheduler_loop()` — 30s polling, atomic claim, execution logic
- `_execute_schedule(schedule)` — API key check, start_scan, record execution
- In-flight tracking: `_in_flight: Dict[scan_id, execution_id]`
- Completion detection in loop: check if in-flight scans have completed
- **All `db.*` calls must be wrapped in `asyncio.to_thread()`** — persistence layer is synchronous, matching the existing pattern in ScannerService (e.g., `await asyncio.to_thread(self._db.insert_scan, ...)`)

### Task 2.3: Implement recovery
**File**: `backend/services/scan_scheduler_service.py`
- `recover_on_startup()` — missed once (24h window, older → mark completed), missed recurring (skip to next), orphaned executions. **Max 1 replay per schedule on startup** to prevent thundering herd.
- `_cleanup_executions()` — daily cleanup of old records

### Task 2.4: Modify ScannerService for schedule integration
**File**: `backend/services/scanner_service.py`
- Modify `start_scan()` to accept optional `schedule_id` and `triggered_by` params
- Pass these through to the scan record insertion
- No other changes needed — scanner is otherwise unchanged

## Phase 3: API Router

### Task 3.1: Create scheduled scans router
**File**: `backend/routers/scheduled_scans.py` (new)
- POST /scheduled-scans — create, validate UUID, 201 Created
- GET /scheduled-scans — list all
- GET /scheduled-scans/{id} — get with recent executions
- PATCH /scheduled-scans/{id} — update
- DELETE /scheduled-scans/{id} — delete with 200
- POST /scheduled-scans/{id}/pause — pause
- POST /scheduled-scans/{id}/resume — resume
- POST /scheduled-scans/{id}/trigger — manual trigger with 60s cooldown
- GET /scheduled-scans/{id}/executions — execution history
- UUID validation helper on all {id} params

### Task 3.2: Wire into main.py
**File**: `backend/main.py`
- Import and create ScanSchedulerService in lifespan
- Call recover_on_startup() and start()
- Shutdown in lifespan teardown (before scanner_service.shutdown)
- Register router with prefix /api/v1

## Phase 4: Frontend

### Task 4.1: Add API client methods
**File**: `frontend/src/api/client.ts`
- TypeScript interfaces: ScheduledScan, ScheduleExecution, CreateScheduledScanRequest
- API methods: list, create, get, update, delete, pause, resume, trigger, listExecutions

### Task 4.2: Create ScheduledScansPage component
**File**: `frontend/src/components/scanner/ScheduledScansPage.tsx` (new)
- Schedule list with React Query polling (10s)
- Status badges, relative time display
- Actions: pause/resume, edit, delete, trigger
- Empty state
- Loading/error states

### Task 4.3: Create schedule creation/edit dialog
**File**: `frontend/src/components/scanner/ScheduledScansPage.tsx` (same file, dialog within)
- Schedule type segmented control
- Type-specific config fields
- Scan config section (provider, models, workflow mode fields)
- Timezone selector
- Form validation
- Next runs preview for ALL schedule types (not just cron)
- Delete confirmation dialog with warning about execution history removal

### Task 4.4: Add route and sidebar link
**Files**: `frontend/src/routes/route-tree.tsx`, `frontend/src/components/layout/RootLayout.tsx`
- Route: /scanner/schedules → ScheduledScansPage
- Sidebar: "Scheduled Scans" with clock icon after "Scan History"
- Route ordering: scheduledScansRoute before scannerDetailRoute

## Phase 5: Dependencies & Testing

### Task 5.1: Add croniter dependency
**File**: `pyproject.toml`
- Add `croniter>=1.4.0` to dependencies

### Task 5.2: Manual testing
- Start backend, verify migrations run
- Create/list/update/delete schedules via API
- Test all 5 schedule types
- Verify scheduler triggers scans at correct times
- Test pause/resume/trigger
- Test error handling (busy scanner, missing API key)
- Verify frontend UI works end-to-end

---

## Implementation Order
Phase 5.1 (croniter dep) → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5.2

Each phase must pass validation (no import errors, correct SQL) before proceeding.
