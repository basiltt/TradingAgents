# Scheduled Market Scans — Specification

## 1. Overview

Add the ability to schedule market scans to run automatically at specified times/intervals. Users configure a schedule with timing parameters and scan settings; the backend scheduler triggers scans at the right times and tracks execution history.

## 2. Schedule Types

| Type | Config Fields | Example |
|------|--------------|---------|
| `once` | `run_at` (ISO datetime) | Run at 2026-05-12T09:00:00 |
| `interval` | `interval_minutes`, `start_at` | Every 240 minutes starting now |
| `daily` | `time` (HH:MM), `days` (0-6 array) | Daily at 09:00 on Mon-Fri |
| `weekly` | `day` (0-6), `time` (HH:MM) | Every Monday at 14:00 |
| `cron` | `expression` (5-field cron) | `0 */4 * * *` |

All schedules store an IANA timezone (default UTC). Internal computation always in UTC.

## 3. Database Schema

### Migration v13: `scheduled_scans` table

```sql
CREATE TABLE IF NOT EXISTS scheduled_scans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schedule_type TEXT NOT NULL CHECK(schedule_type IN ('once','interval','daily','weekly','cron')),
    schedule_config TEXT NOT NULL DEFAULT '{}',
    scan_config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','error')),
    timezone TEXT NOT NULL DEFAULT 'UTC',
    next_run_at TEXT,
    last_run_at TEXT,
    last_scan_id TEXT REFERENCES scans(scan_id) ON DELETE SET NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_scans_status_next ON scheduled_scans(status, next_run_at);
```

### Migration v14: `schedule_executions` table

```sql
CREATE TABLE IF NOT EXISTS schedule_executions (
    id SERIAL PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES scheduled_scans(id) ON DELETE CASCADE,
    scan_id TEXT REFERENCES scans(scan_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK(status IN ('started','completed','failed','skipped_busy','skipped_no_key','cancelled')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_executions_lookup ON schedule_executions(schedule_id, started_at DESC);
```

### Migration v15: Add `schedule_id` to `scans` table

```sql
ALTER TABLE scans ADD COLUMN IF NOT EXISTS schedule_id TEXT REFERENCES scheduled_scans(id) ON DELETE SET NULL;
ALTER TABLE scans ADD COLUMN IF NOT EXISTS triggered_by TEXT NOT NULL DEFAULT 'manual' CHECK(triggered_by IN ('manual','scheduled'))
```

**Note**: `ADD COLUMN IF NOT EXISTS` requires PostgreSQL 17+, which matches existing migration patterns in the codebase (migrations 2, 6).

## 4. Pydantic Schemas (`backend/schemas.py`)

```python
class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    CRON = "cron"

class ScheduleConfig(BaseModel):
    run_at: Optional[str] = None          # ISO datetime for 'once'
    interval_minutes: Optional[int] = Field(None, ge=15, le=43200)  # min 15m, max 30d
    start_at: Optional[str] = None         # For 'interval'
    time: Optional[str] = None             # HH:MM for daily/weekly
    days: Optional[List[int]] = Field(None, max_length=7)  # 0-6 for daily (0=Mon)
    day: Optional[int] = Field(None, ge=0, le=6)  # 0-6 for weekly
    expression: Optional[str] = None       # 5-field cron

    @field_validator("days")
    def validate_days(cls, v):
        if v is not None:
            if not all(0 <= d <= 6 for d in v):
                raise ValueError("Days must be 0-6")
            if len(set(v)) != len(v):
                raise ValueError("Duplicate days")
        return v

    @field_validator("expression")
    def validate_cron(cls, v):
        if v is not None:
            import re
            if not re.match(r'^[0-9,\-\*/]+(\s+[0-9,\-\*/]+){4}$', v):
                raise ValueError("Must be a 5-field cron expression")
            # Frequency check done in service layer using croniter
        return v

class CreateScheduledScanRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r'^[^\x00-\x1f]*$')
    schedule_type: ScheduleType
    schedule_config: ScheduleConfig
    scan_config: Dict[str, Any]            # Validated against ScanRequest in service layer
    timezone: str = "UTC"

    @field_validator("timezone")
    def validate_timezone(cls, v):
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(v)
        except (KeyError, Exception):
            raise ValueError(f"Invalid IANA timezone: {v}")
        return v

    @model_validator(mode="after")
    def validate_type_config(self):
        """Ensure schedule_config has required fields for the schedule_type."""
        cfg = self.schedule_config
        t = self.schedule_type
        if t == ScheduleType.ONCE and not cfg.run_at:
            raise ValueError("'once' type requires 'run_at'")
        if t == ScheduleType.INTERVAL and not cfg.interval_minutes:
            raise ValueError("'interval' type requires 'interval_minutes'")
        if t == ScheduleType.DAILY and not cfg.time:
            raise ValueError("'daily' type requires 'time'")
        if t == ScheduleType.WEEKLY and (cfg.day is None or not cfg.time):
            raise ValueError("'weekly' type requires 'day' and 'time'")
        if t == ScheduleType.CRON and not cfg.expression:
            raise ValueError("'cron' type requires 'expression'")
        return self

    @field_validator("scan_config")
    def validate_scan_config(cls, v):
        """Validate against ScanRequest and strip API keys."""
        # Remove any key-like fields (API keys must never be stored)
        for key in list(v.keys()):
            if 'api_key' in key.lower() or 'secret' in key.lower():
                del v[key]
        # Validate against ScanRequest (done in service layer for full validation)
        return v

class UpdateScheduledScanRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, pattern=r'^[^\x00-\x1f]*$')
    schedule_type: Optional[ScheduleType] = None
    schedule_config: Optional[ScheduleConfig] = None  # Full replacement, not merge
    scan_config: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = None

    @field_validator("timezone")
    def validate_timezone(cls, v):
        if v is not None:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(v)
            except (KeyError, Exception):
                raise ValueError(f"Invalid IANA timezone: {v}")
        return v

    @field_validator("scan_config")
    def validate_scan_config(cls, v):
        if v is not None:
            for key in list(v.keys()):
                if 'api_key' in key.lower() or 'secret' in key.lower():
                    del v[key]
        return v

    # Note: type-config cross-validation done in service layer after merging
    # with existing record, since PATCH may omit schedule_type

class ScheduledScanResponse(BaseModel):
    id: str
    name: str
    schedule_type: ScheduleType
    schedule_config: Dict[str, Any]
    scan_config: Dict[str, Any]
    status: str
    timezone: str
    next_run_at: Optional[str]
    last_run_at: Optional[str]
    last_scan_id: Optional[str]
    consecutive_failures: int
    created_at: str
    updated_at: str
    recent_executions: Optional[List[Dict[str, Any]]] = None

class ScheduleExecutionResponse(BaseModel):
    id: int
    schedule_id: str
    scan_id: Optional[str]
    status: str
    started_at: str
    completed_at: Optional[str]
    error_message: Optional[str]
```

## 5. API Endpoints (`backend/routers/scheduled_scans.py`)

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| POST | `/api/v1/scheduled-scans` | Create schedule | 201 |
| GET | `/api/v1/scheduled-scans` | List all schedules | 200 |
| GET | `/api/v1/scheduled-scans/{id}` | Get schedule + recent executions | 200 |
| PATCH | `/api/v1/scheduled-scans/{id}` | Update schedule | 200 |
| DELETE | `/api/v1/scheduled-scans/{id}` | Delete schedule | 200 |
| POST | `/api/v1/scheduled-scans/{id}/pause` | Pause schedule | 200 |
| POST | `/api/v1/scheduled-scans/{id}/resume` | Resume schedule | 200 |
| POST | `/api/v1/scheduled-scans/{id}/trigger` | Trigger immediate run | 200 |
| GET | `/api/v1/scheduled-scans/{id}/executions` | List execution history | 200 |

### Request/Response Examples

**POST /api/v1/scheduled-scans** (Daily scan at 09:00 UTC):
```json
{
  "name": "Morning Scan",
  "schedule_type": "daily",
  "schedule_config": {"time": "09:00", "days": [0,1,2,3,4]},
  "scan_config": {
    "provider": "anthropic",
    "workflow_mode": "quick_trade",
    "deep_think_llm": "claude-sonnet-4-6",
    "quick_think_llm": "claude-haiku-4-5-20251001",
    "asset_type": "crypto",
    "interval": "240",
    "max_parallel": 10
  },
  "timezone": "UTC"
}
```

**Response**: `ScheduledScanResponse` with computed `next_run_at`.

## 6. Backend Service (`backend/services/scan_scheduler_service.py`)

### Class: `ScanSchedulerService`

**Constructor**: `__init__(scanner_service: ScannerService, db: AnalysisDB)`

**Public Methods**:
- `create_schedule(data: dict) -> dict` — Validate config, resolve Optional scan_config fields via ConfigService, compute next_run_at, insert DB, return schedule
- `update_schedule(id: str, data: dict) -> dict` — Update fields, reset consecutive_failures, recompute next_run_at
- `delete_schedule(id: str) -> bool` — Delete from DB (cascades to executions)
- `list_schedules() -> list` — Return all schedules with last 5 executions each (wrapped as `{"schedules": [...]}`)
- `get_schedule(id: str) -> dict` — Return schedule with recent executions (wrapped as `ScheduledScanResponse`)
- `pause_schedule(id: str) -> dict` — Set status='paused', clear next_run_at
- `resume_schedule(id: str) -> dict` — Set status='active', recompute next_run_at
- `trigger_schedule(id: str) -> dict` — Fire immediately (respects busy check)
- `start() -> None` — Launch scheduler loop task
- `shutdown() -> None` — Cancel loop, await any in-flight execution to finalize records, then stop
- `recover_on_startup() -> None` — Handle missed runs, orphaned executions (see Recovery section below)

**Important**: `scan_config` must never contain API keys. Keys are resolved from environment variables at execution time via the same `_PROVIDER_KEY_MAP` pattern used in `scanner.py`. The `scan_config` is stripped of any `*api_key*` or `*secret*` fields at creation time.

**Private Methods**:
- `_scheduler_loop()` — Every 30s: query due schedules, attempt execution
- `_execute_schedule(schedule: dict)` — Validate API keys, call scanner_service.start_scan(), record execution, update next_run_at
- `_compute_next_run(schedule: dict) -> Optional[str]` — Calculate next UTC datetime based on type+config+timezone
- `_validate_schedule_config(type, config)` — Type-specific validation
- `_validate_cron(expression)` — 5-field only, check effective frequency >= 15 min

### Execution Flow
1. Scheduler loop wakes every 30s
2. Queries `scheduled_scans WHERE status='active' AND next_run_at <= now() ORDER BY next_run_at ASC LIMIT 5`
3. For each due schedule:
   a. **Atomic claim**: `UPDATE scheduled_scans SET next_run_at = :new_next WHERE id = :id AND next_run_at = :old_next RETURNING id`. If 0 rows returned, another tick already claimed it — skip.
   b. Check API key availability for configured provider
   c. Try `scanner_service.start_scan(schedule.scan_config, schedule_id=id, triggered_by='scheduled')` — catch `ScannerBusyError`
   d. On success: insert execution record (started), update last_run_at, set last_scan_id
   e. On busy: insert execution (skipped_busy). **For `once` type: revert next_run_at to original value so it retries next tick**
   f. On key missing: insert execution (skipped_no_key), log warning. **For `once` type: revert next_run_at to original value so it retries next tick**
   g. On failure: insert execution (failed), increment consecutive_failures
4. If consecutive_failures >= 3: set status='error', log warning
5. **Skipped runs do NOT count toward consecutive_failures** (only actual execution failures do)

### Execution Completion Tracking
When a scheduled scan completes (or fails), the execution record must be updated:
- `ScannerService` already tracks scan completion internally
- `ScanSchedulerService` registers a callback/poll mechanism:
  - After starting a scan, store `(scan_id, execution_id)` in an in-memory set
  - In the scheduler loop, also check for any in-flight executions whose scans have completed
  - When detected: update `schedule_executions.status` to `completed`/`failed`, set `completed_at`
  - Reset `consecutive_failures` to 0 on success

### Recovery on Startup (`recover_on_startup`)
1. **Missed `once` schedules**: If `next_run_at` is in the past and status='active', check staleness. If missed by <= 24 hours, attempt execution immediately. If older, mark as `completed` with note "missed — server was down"
2. **Missed recurring schedules**: Skip missed runs, compute next future `next_run_at` from now
3. **Orphaned executions**: Any `schedule_executions` with status='started' that have no matching running scan → mark as 'failed' with error "interrupted by server restart"
4. **Maximum**: Never replay more than 1 missed execution per schedule on startup

### Execution History Cleanup
Periodically (daily, piggyback on scheduler loop), delete execution records older than 90 days per schedule, keeping at minimum the last 100 records per schedule.

### Error Message Sanitization
Before storing `error_message` in `schedule_executions`, truncate to 500 chars and strip file paths/stack frames. Use generic messages for unexpected exceptions. Never store API keys or connection strings in error messages.

### Trigger Cooldown
The `/trigger` endpoint rejects requests if the last execution for the schedule started less than 60 seconds ago (returns 429).

### next_run_at Calculation
- **once**: `run_at` datetime (no recalculation after execution)
- **interval**: `max(now, last_completed_at) + interval_minutes`
- **daily**: next occurrence of `time` on any of the specified `days` in the schedule's timezone
- **weekly**: next occurrence of `day` at `time` in the schedule's timezone
- **cron**: use `croniter` to compute next match from now

## 7. Persistence Layer Methods (`backend/persistence.py`)

Add to `AnalysisDB`:
- `insert_scheduled_scan(data: dict) -> None`
- `update_scheduled_scan(id: str, data: dict) -> None`
- `delete_scheduled_scan(id: str) -> bool`
- `list_scheduled_scans() -> list`
- `get_scheduled_scan(id: str) -> Optional[dict]`
- `get_due_scheduled_scans() -> list` — `WHERE status='active' AND next_run_at <= now()`
- `insert_schedule_execution(data: dict) -> None`
- `list_schedule_executions(schedule_id: str, limit: int = 20) -> list`
- `update_scan_schedule_link(scan_id: str, schedule_id: str, triggered_by: str) -> None`

## 8. Wiring in `backend/main.py`

In lifespan startup (after scanner_service creation):
```python
from backend.services.scan_scheduler_service import ScanSchedulerService
scan_scheduler = ScanSchedulerService(
    scanner_service=app.state.scanner_service,
    db=db,
    config_service=config_service,
)
app.state.scan_scheduler_service = scan_scheduler
await scan_scheduler.recover_on_startup()
await scan_scheduler.start()
```

In lifespan shutdown (before scanner_service shutdown):
```python
await app.state.scan_scheduler_service.shutdown()
```

Register router:
```python
from backend.routers.scheduled_scans import router as scheduled_scans_router
app.include_router(scheduled_scans_router, prefix="/api/v1")
```

## 9. Frontend API Client (`frontend/src/api/client.ts`)

Add methods:
```typescript
// Scheduled Scans
async listScheduledScans(): Promise<{schedules: ScheduledScan[]}>
async createScheduledScan(data: CreateScheduledScanRequest): Promise<ScheduledScan>
async getScheduledScan(id: string): Promise<ScheduledScan>
async updateScheduledScan(id: string, data: Partial<CreateScheduledScanRequest>): Promise<ScheduledScan>
async deleteScheduledScan(id: string): Promise<{status: string}>
async pauseScheduledScan(id: string): Promise<ScheduledScan>
async resumeScheduledScan(id: string): Promise<ScheduledScan>
async triggerScheduledScan(id: string): Promise<{status: string, scan_id?: string}>
async listScheduleExecutions(id: string): Promise<{executions: ScheduleExecution[]}>
```

TypeScript types:
```typescript
type ScheduleType = 'once' | 'interval' | 'daily' | 'weekly' | 'cron';
type ScheduleStatus = 'active' | 'paused' | 'completed' | 'error';
type ExecutionStatus = 'started' | 'completed' | 'failed' | 'skipped_busy' | 'skipped_no_key' | 'cancelled';

interface ScheduledScan {
  id: string;
  name: string;
  schedule_type: ScheduleType;
  schedule_config: Record<string, any>;
  scan_config: Record<string, any>;
  status: ScheduleStatus;
  timezone: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_scan_id: string | null;
  consecutive_failures: number;
  created_at: string;
  updated_at: string;
  recent_executions?: ScheduleExecution[];
}

interface ScheduleExecution {
  id: number;
  schedule_id: string;
  scan_id: string | null;
  status: ExecutionStatus;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

interface CreateScheduledScanRequest {
  name: string;
  schedule_type: ScheduleType;
  schedule_config: Record<string, any>;
  scan_config: Record<string, any>;
  timezone?: string;
}
```

**Query keys**: `['scheduled-scans']` for list, `['scheduled-scans', id]` for detail. All mutations call `queryClient.invalidateQueries({ queryKey: ['scheduled-scans'] })`.

## 10. Frontend Page (`frontend/src/components/scanner/ScheduledScansPage.tsx`)

### Layout
- Header: "Scheduled Scans" with "+ New Schedule" button
- Schedule list table with columns: Name, Type, Status, Next Run, Last Run, Actions
- Create/Edit modal dialog
- Loading state: skeleton rows matching table structure
- Error state: error banner with retry button

### Scan Config Form Sharing
The scan configuration fields (provider, models, workflow mode, etc.) are currently embedded in `ScannerPage.tsx` as local state. For the scheduled scans dialog, the implementation should **duplicate the relevant form fields** within the dialog rather than extracting a shared component — this avoids a large refactor of the 63KB ScannerPage and keeps the implementation focused. The scan config fields needed are: provider, deep_think_llm, quick_think_llm, workflow_mode, asset_type, interval, max_parallel, ta_prefilter_enabled, ta_prefilter_threshold.

### Schedule List
- Polling via React Query (refetchInterval: 10000)
- Status badges: active (green), paused (yellow), completed (gray), error (red)
- Relative time display for next/last run ("in 2 hours", "3 hours ago")
- Actions column: Trigger | Pause/Resume | Edit | Delete
- Empty state: illustration + "Create your first scheduled scan" CTA

### Create/Edit Dialog
- Name input (required)
- Schedule type segmented control: Once | Interval | Daily | Weekly | Cron
- Type-specific fields:
  - **Once**: Date picker + time picker
  - **Interval**: Number input + unit select (minutes/hours), min 15 min
  - **Daily**: Time picker + day-of-week checkboxes (Mon-Sun)
  - **Weekly**: Day-of-week dropdown + time picker
  - **Cron**: Text input with help tooltip, next 3 runs preview
- Timezone selector (defaults to Intl.DateTimeFormat().resolvedOptions().timeZone)
- Collapsible "Scan Configuration" section with same fields as ScannerPage form
- "Next 3 scheduled runs" preview below the timing config
- Save / Cancel buttons

### Delete Confirmation
- Dialog: "Delete schedule 'Morning Scan'? This will cancel any future runs. Execution history will be removed."
- Confirm / Cancel buttons

## 11. Route & Sidebar

### Route (`frontend/src/routes/route-tree.tsx`)
```typescript
import { ScheduledScansPage } from "@/components/scanner/ScheduledScansPage";

function ScheduledScansPageWrapper() {
  return <ScheduledScansPage />;
}

const scheduledScansRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scanner/schedules",
  component: ScheduledScansPageWrapper,
});

// Add to routeTree children — MUST be before scannerDetailRoute to avoid
// /scanner/$scanId matching "schedules" as a dynamic param
```

### Sidebar (`frontend/src/components/layout/RootLayout.tsx`)
Add after "Scan History" NavLink:
```tsx
<NavLink
  to="/scanner/schedules"
  icon={<svg ...><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
>
  Scheduled Scans
</NavLink>
```

## 12. Dependencies

Add to `pyproject.toml`:
```
croniter>=1.4.0
```

## 13. Requirement Traceability

| Requirement | Implementation |
|------------|----------------|
| FR-001 | ScheduleType enum, _compute_next_run() |
| FR-002 | Router CRUD endpoints |
| FR-003 | pause/resume endpoints + service methods |
| FR-004 | scheduled_scans table schema |
| FR-005 | /trigger endpoint |
| FR-006 | _execute_schedule sets status='completed' for once type |
| FR-007 | delete_schedule checks for running scan |
| FR-008 | Frontend: "Schedule This Scan" button (future) |
| FR-009-010 | Schema validation |
| FR-011-019 | ScanSchedulerService execution logic |
| FR-020-023 | _compute_next_run with zoneinfo |
| FR-024-040 | Frontend components |
| FR-041-052 | Integration: migrations v15, execution tracking |
| NFR-001-006 | Validation in schemas + service |
| NFR-007-014 | Service reliability + observability |
