# Scheduled Market Scans — Requirements

## Functional Requirements

### Schedule Management
- FR-001: Support 5 schedule types: one-time, interval, daily, weekly, cron expression
- FR-002: CRUD operations for schedules (create, read, update, delete) via API and UI
- FR-003: Pause/resume schedules — pausing prevents future firings, resuming recalculates next run from now
- FR-004: Each schedule stores: name, schedule_type, schedule_config, scan_config (frozen ScanRequest snapshot), status, timezone, next_run_at, last_run_at
- FR-005: Manual trigger ("Run Now") button fires a schedule immediately regardless of timing
- FR-006: One-time schedules auto-transition to "completed" after successful execution
- FR-007: Schedule deletion while scan is running: allow current scan to finish, then clean up
- FR-008: "Schedule This Scan" action from completed scan results to clone config into new schedule
- FR-009: Schedule names required, max 255 chars
- FR-010: Maximum 20 schedules total to bound resource usage

### Schedule Execution
- FR-011: Scheduler loop runs as asyncio task, polling every 30 seconds for due schedules
- FR-012: When scheduled scan fires but scanner is busy: skip the run, log "skipped_busy", calculate next run
- FR-013: If a scan is still running at next scheduled time: skip the overlapping run, log missed execution
- FR-014: Minimum interval of 15 minutes between recurring triggers
- FR-015: next_run_at recalculated after run completes (not at start), to prevent drift
- FR-016: On server restart: detect schedules with next_run_at in the past, skip to next future run
- FR-017: On server restart: detect orphaned running scans from schedules, mark as failed
- FR-018: After 3 consecutive failed runs, auto-pause the schedule and notify user
- FR-019: Each execution records: schedule_id, scan_id, status, started_at, completed_at, error_message

### Timezone
- FR-020: Schedules store IANA timezone (e.g., "America/New_York"), all internal computation in UTC
- FR-021: DST spring-forward: fire at next valid wall-clock time
- FR-022: DST fall-back: fire once using first occurrence
- FR-023: Month-end edge cases: fire on last valid day for 29th/30th/31st schedules

### UI — Navigation & Layout
- FR-024: "Scheduled Scans" sidebar link under MARKET SCANNER, after Scan History
- FR-025: Route /scanner/schedules for list view
- FR-026: Schedule creation dialog/page with type selector and config form
- FR-027: Schedule list shows: name, type, status badge, next run, last run, actions

### UI — Schedule Creation
- FR-028: Schedule type as segmented control (Once | Interval | Daily | Weekly | Cron)
- FR-029: One-time: date picker + time picker, disable past dates
- FR-030: Interval: numeric input + unit selector (minutes/hours), min 15 minutes
- FR-031: Daily: time picker + day-of-week multi-select (default all 7)
- FR-032: Weekly: day-of-week select + time picker
- FR-033: Cron: text input with syntax help tooltip, human-readable preview, next 3 run times preview
- FR-034: Scan config section reuses existing scan form fields (provider, models, workflow mode, etc.)
- FR-035: Timezone selector defaulting to user's local timezone

### UI — Schedule List & Actions
- FR-036: Status badges: active (green), paused (yellow), completed (gray), error (red)
- FR-037: Pause/resume toggle, edit, delete, trigger buttons per schedule
- FR-038: Delete confirmation dialog
- FR-039: Empty state with "Create your first scheduled scan" CTA
- FR-040: Toast notifications for actions (created, updated, deleted, paused, resumed, triggered)

### Integration (from Round 2 gap analysis)
- FR-041: Add schedule_id column to scans table to link scheduled scans back to their originating schedule
- FR-042: Add triggered_by column to scans table ('manual' | 'schedule' | 'run_now')
- FR-043: Scan History page shows "Scheduled" badge for schedule-triggered scans
- FR-044: Frontend polls GET /api/v1/scheduled-scans every 10 seconds to refresh schedule list status
- FR-045: Skipped executions (busy/no-key) tracked in schedule_executions table, visible in UI
- FR-046: Scheduler calls ScannerService.start_scan() directly (not via HTTP), catches ScannerBusyError
- FR-047: API key validation moved into a shared utility callable by both router and scheduler
- FR-048: Schedule update resets consecutive_failures counter and recalculates next_run_at
- FR-049: Resolve all Optional fields in ScanRequest at schedule creation time (frozen = fully resolved)
- FR-050: Unified shutdown sequence: stop scheduler loop → wait for in-progress scan → stop other schedulers
- FR-051: Cron expressions validated as 5-field only, effective frequency checked against 15-min minimum
- FR-052: Schedule execution history table (schedule_executions) for tracking all attempts including skips

## Non-Functional Requirements

### Security
- NFR-001: Validate cron expressions server-side, reject non-standard extensions (@reboot, shell metacharacters)
- NFR-002: Validate timezone against IANA tz database
- NFR-003: Schedule mutation endpoints require X-Requested-With CSRF header (existing middleware)
- NFR-004: Schedule IDs are UUIDs, not sequential integers
- NFR-005: Schedule names stripped of control characters, length-bounded
- NFR-006: API key availability checked at execution time, skip with warning if missing

### Reliability
- NFR-007: Scheduler survives server restarts via persisted next_run_at
- NFR-008: Graceful shutdown cancels scheduler loop, allows running scan to complete
- NFR-009: Execution timeout: max 120 minutes per scan, then terminate
- NFR-010: Tolerate up to 5 seconds of clock drift

### Performance
- NFR-011: Indexed next_run_at column for efficient due-scan queries
- NFR-012: Scheduler loop is lightweight (single SQL query per tick)

### Observability
- NFR-013: Log schedule creation, updates, deletions, executions, skips, failures
- NFR-014: Execution history retained per schedule (linked via scan_id)
