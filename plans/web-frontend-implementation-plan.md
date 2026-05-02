# Web Frontend — Implementation Plan

## A. Title and Metadata

- **Plan name**: Web Frontend for TradingAgents
- **Date**: 2026-05-02
- **Author**: Claude
- **Status**: Draft
- **Related spec**: `specs/web-frontend-spec.md` (R15, Approved)
- **Version**: 1.0

---

## B. Planning Summary

### What
Build a full web frontend (FastAPI backend + React SPA) that replaces the terminal CLI, with real-time WebSocket streaming during analysis runs.

### Why
Enable browser-based configuration, launch, and monitoring of trading analyses with a rich real-time dashboard.

### High-Level Approach
6-phase implementation: backend foundation → backend analysis+WS → frontend foundation → frontend analysis UI → frontend remaining pages → integration/E2E/production build.

### Key Files Affected
- New: `backend/` directory (FastAPI app), `frontend/` directory (React SPA), `backend/stream_parser.py`
- Modified: `pyproject.toml` (add `[project.optional-dependencies] web = [...]` extras group)

### Key Risks
- LangGraph streaming compatibility with async WebSocket push (mitigated by asyncio.to_thread + event bus)
- Thread safety between sync callbacks and async WS layer (mitigated by asyncio.Queue bridge)

### Accepted Risks (reviewed, intentionally deferred)
- **No authentication**: Localhost-only binding (127.0.0.1 hardcoded) is the sole access control. Acceptable for single-user desktop tool. If multi-user deployment is needed in the future, add optional `WEB_AUTH_TOKEN` bearer auth.
- **No REST rate limiting**: Only WS rate limiting (10/sec) and analysis concurrency cap (3) exist. Local-only binding makes DoS impractical. If exposed to network, add `slowapi` middleware.

### Key Assumptions
- A-001: Backend and frontend run on same machine
- A-002: Node.js 20+ available
- A-003: TradingAgentsGraph API stable during implementation

---

## C. Source Specification Reference

- **Spec file**: `specs/web-frontend-spec.md`
- **Spec version**: R15 (Approved)
- **Requirements covered**: FR-001 through FR-011, SEC-001 through SEC-019, NFR-001 through NFR-009, AC-001 through AC-008

---

## D. Implementation Strategy

### Overall Approach
Backend-first: build the API and WebSocket layer first, test with curl/wscat, then build the frontend against the running backend.

### Architecture Alignment
- FastAPI follows existing Python project structure
- Frontend is a standalone SPA in `frontend/` directory
- Shared stream parsing logic extracted to `backend/stream_parser.py` (backend-only; not placed in `tradingagents/` core library to avoid coupling web concerns into the pip-installable package)

### Existing Patterns to Reuse
- `cli/main.py` stream processing logic (lines 965-1153) → extracted to `stream_parser.py`
- `cli/utils.py` provider list and model catalog → reused via API endpoints
- `tradingagents/default_config.py` → config resolution logic
- `cli/stats_handler.py` → callback handler pattern

### Dependency Order
Phase 1 (backend foundation) → Phase 2 (backend analysis+WS) → Phase 3 (frontend foundation) → Phase 4 (frontend analysis) → Phase 5 (frontend pages) → Phase 6 (integration/E2E)

---

## E. Phase Breakdown

### Phase 1: Backend Foundation
**Goal**: FastAPI app skeleton, schemas, SQLite persistence, config service, health endpoint.

**Scope**: Routers (config, models, providers, health, checkpoints, memory), persistence layer, config service, memory service, schemas, backend URL validator.

**Completion criteria**: All REST endpoints (except analysis) return correct responses. SQLite schema created. Config service resolves defaults+env vars+overrides. Health endpoint works. All Phase 1 unit tests pass.

### Phase 2: Backend Analysis & WebSocket
**Goal**: Analysis service, event bus, callback handler, WebSocket manager, stream parser.

**Scope**: Analysis router, analysis service (start/cancel/status/list), event bus (asyncio.Queue bridge), custom callback handler, WebSocket endpoint with reconnection/snapshot/heartbeat, stream parser extraction.

**Completion criteria**: Can start analysis via POST, receive WebSocket updates, cancel, view completion. Concurrency cap works. Timeout works. All Phase 2 tests pass.

### Phase 3: Frontend Foundation
**Goal**: Vite + React + TanStack Router + shadcn/ui + Redux Toolkit + TanStack Query setup.

**Scope**: Project scaffold, routing, theme (dark mode), layout components, Redux store (uiSlice), TanStack Query client, API client module, WebSocket hook shell.

**Completion criteria**: App runs, routes work, dark theme applied, shadcn/ui components render. API client connects to backend health endpoint.

### Phase 4: Frontend Analysis UI
**Goal**: Analysis configuration form and real-time dashboard.

**Scope**: ConfigForm (multi-step wizard), AgentStatusTable, MessagesPanel, ReportPanel, StatsBar, ErrorBanner, ReconnectionIndicator, useAnalysisWebSocket hook.

**Completion criteria**: Can configure and submit analysis from browser, see real-time updates on dashboard, cancel, view completed report, download report. All component and hook tests pass.

### Phase 5: Frontend Remaining Pages
**Goal**: History, Configuration, Memory, Home pages.

**Scope**: History page with pagination/filtering, Config page with edit, Memory page with pagination, Home dashboard with active analyses overview.

**Completion criteria**: All pages render with correct data. Empty states shown. Pagination works. Config changes persist.

### Phase 6: Integration, E2E, Production Build
**Goal**: End-to-end testing, production build, final polish.

**Scope**: E2E tests (Playwright), security tests, performance tests, production build (FastAPI serving frontend dist), start scripts.

**Completion criteria**: All E2E scenarios pass. Security tests pass. Production build serves SPA correctly. `start.bat` updated to launch both backend and frontend.

---

## F. Task Breakdown — Phase 1: Backend Foundation

### TASK-001: FastAPI Application Skeleton
- **Covers**: SEC-001, SEC-002, SEC-019
- **Files**: Create `backend/__init__.py`, `backend/main.py`
- **Details**: FastAPI app with lifespan handler. Bind `127.0.0.1:8000` (hardcoded, ignore WEB_HOST env). CORS middleware with `WEB_CORS_ORIGIN` env var (default `http://localhost:5173`), startup validates not `*` and well-formed origin. CSP middleware on HTML responses. CSRF protection: require `X-Requested-With: XMLHttpRequest` custom header on all state-mutating endpoints (POST, PATCH, DELETE) — browsers won't send custom headers in simple cross-origin requests, forcing a preflight that CORS blocks. Health endpoint `GET /api/v1/health` returning `{"status": "ok", "db": "ok"}` — verifies SQLite reachable (`SELECT 1`) and reports degraded if not. Graceful shutdown in lifespan handler: on shutdown signal, cancel all running analyses (set cancel flag, await thread joins with 10s timeout), close all WebSocket connections with 1001 Going Away, close SQLite connection pool.
- **Tests**: `tests/backend/test_main.py` — health returns 200 with db check, CORS rejects unknown origin, CSP header present, CSRF header required on state-mutating endpoints, graceful shutdown cancels active runs and closes WS connections. Also create `tests/backend/conftest.py` with shared fixtures: sample AnalysisRequest factory, mock TradingAgentsGraph factory, sample WS event sequences, test DB setup/teardown helper. Add Ruff configuration to `pyproject.toml` for backend Python linting.
- **Deps**: None

### TASK-002: Pydantic Schemas
- **Covers**: FR-001, SEC-006, SEC-007, SEC-013, SEC-014
- **Files**: Create `backend/schemas.py`
- **Details**: All request/response models from spec: `AnalysisRequest`, `AnalysisCreateResponse`, `AnalysisResponse`, `AnalysisListItem`, `AnalysisListResponse`, `ConfigResponse`, `ConfigUpdateRequest`, `MemoryEntry`, `MemoryListResponse`, `CheckpointResponse`, `ErrorResponse` (standard envelope: `{ detail: str, code: str | None }`; all non-422 errors use this; 422 uses FastAPI's native format). Validation: ticker regex `^[A-Z0-9.\-^]{1,15}$`, model ID regex `^[a-zA-Z0-9._:/-]{1,100}$`, provider enum, output_language dual-path: accept any of 12 preset strings exactly (English, Chinese, Japanese, Korean, Hindi, Spanish, Portuguese, French, German, Arabic, Russian, Custom) OR validate custom input against `^[A-Z][a-z]+([\s\-][A-Z][a-z]+)*$` max 30 chars, data_vendors categories (`core_stock_apis`, `technical_indicators`, `fundamental_data`, `news_data`) with values `yfinance|alpha_vantage`, analysis_date not in future. DELETE checkpoints returns 204 No Content.
- **Tests**: `tests/backend/test_schemas.py` — valid/invalid ticker, date, provider, model ID, output_language, data_vendors
- **Deps**: None

### TASK-003: Backend URL Validator
- **Covers**: SEC-005
- **Files**: Create `backend/validators.py`
- **Details**: `validate_backend_url(url: str, server_port: int) -> str` — accepts http/https only, resolves hostname, pins resolved IP, checks against RFC 1918, link-local `169.254.0.0/16`, CGN `100.64.0.0/10`, IPv6 loopback `::1`, non-standard representations. Blocks self-request (`127.0.0.1:{server_port}`). Allows localhost on other ports. No redirect following.
- **Tests**: `tests/backend/test_validators.py` — scheme enforcement, private IP detection (IPv4-mapped IPv6, hex notation, octal, DNS-to-private), localhost allowlist with port check, percent-encoded bypasses, self-request blocking
- **Deps**: None

### TASK-004: SQLite Persistence Layer
- **Covers**: FR-005, SEC-017, Database schema
- **Files**: Create `backend/persistence.py`
- **Details**: `AnalysisDB` class. Constructor accepts `db_path` parameter (default `~/.tradingagents/cache/web_runs.db`) for testability — tests pass `tmp_path`. On init: create/open DB with `check_same_thread=False`. Thread safety: use `threading.Lock` around all connection operations (cursor create, execute, commit) to prevent interleaved cursor operations from concurrent `asyncio.to_thread` workers. `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, check `PRAGMA user_version`, apply migrations. Migration framework: `_MIGRATIONS` list of `(version: int, sql: str)` tuples. `_apply_migrations()`: first create pre-migration backup (`shutil.copy2(db_path, db_path + f'.backup.v{current_version}')`), then acquire `BEGIN EXCLUSIVE` transaction to prevent concurrent access during schema changes, then iterate from current `user_version` to latest, executing each SQL with `SAVEPOINT`/`RELEASE`/`ROLLBACK TO` for per-step rollback on failure. If a migration step fails, log the error and raise — do not skip. On higher version than known: refuse to start with actionable error message ("Database schema v{N} is newer than this application supports (max v{M}). Please upgrade the application or restore from backup at {backup_path}"). Schema v1: `analysis_runs` and `report_sections` tables per spec DDL, plus additional index: `CREATE INDEX idx_runs_status_started ON analysis_runs(status, started_at DESC)` for status-filtered history queries. Add `instance_id TEXT NOT NULL` column to `analysis_runs` (populated with server's startup UUID). `recover_orphans()` marks ALL `status='running'` rows as `'failed'` on startup (the prior process is definitionally dead on a single-machine deployment; instance_id retained for diagnostic logging only). Remove `IF NOT EXISTS` from DDL inside versioned migrations (user_version already guards re-execution; IF NOT EXISTS masks schema drift). Add `CHECK(started_at GLOB '????-??-??T??:??:??*')` on `started_at` and same pattern-or-NULL on `completed_at`. Clarify `from_date`/`to_date` in `list_runs` filters on `analysis_date` (not `started_at`), which is covered by `idx_runs_ticker_date`. All queries parameterized. Methods: `insert_run(run)`, `update_run_status(run_id, status, error, completed_at) -> bool` with `WHERE status='running'` (returns True if row updated, False if already transitioned; caller must check to avoid duplicate terminal events or double-decrementing concurrency counter), `save_report_section(run_id, section, content)`, `get_run(run_id)`, `list_runs(page, limit, ticker, status, from_date, to_date)` with COUNT for total, `get_report_sections(run_id)`, `recover_orphans()` (running→failed on startup), `get_checkpoint_exists(ticker, date)`.
- **Tests**: `tests/backend/test_persistence.py` — CRUD, orphan recovery (marks all running→failed on startup), WAL mode, busy_timeout, concurrent writes, corrupt DB, schema migration (multi-step sequential, partial failure rollback via savepoint, no-op for current version, higher version refusal with actionable error message, no IF NOT EXISTS masking, EXCLUSIVE transaction during migration), state transition enforcement, list_runs filter combinations (ticker only, status only, date range on analysis_date, all combined, no matches, COUNT correctness), started_at CHECK constraint enforcement, pre-migration backup creation
- **Deps**: None

### TASK-005: Config Service
- **Covers**: FR-006, SEC-004, SEC-015
- **Files**: Create `backend/services/config_service.py`
- **Details**: `ConfigService` class. Resolves config from `DEFAULT_CONFIG` + env vars + runtime overrides (in-memory dict). `get_config()` returns defaults/overrides/resolved with API keys masked (`***`). `update_config(patch)` validates allowlisted keys only, rejects unknown. Runtime overrides lost on restart (documented). Note: API keys and backend_url are NOT persisted or included in runtime overrides — they are always read from env vars at analysis-submission time. The retry flow (ErrorBanner → Reconfigure) deserializes the original submission config JSON into the form; env vars are re-read when the user resubmits, not carried from the failed run.
- **Tests**: `tests/backend/test_config_service.py` — secret redaction, override merging, unknown key rejection, env var resolution, API key not in overrides
- **Deps**: TASK-002, TASK-004

### TASK-006: Memory Service
- **Covers**: FR-007, SEC-009
- **Files**: Create `backend/services/memory_service.py`
- **Details**: `MemoryService` class. Constructor accepts `memory_path` parameter (default `~/.tradingagents/memory/trading_memory.md`) for testability. Pagination (`page`, `limit`). File-mtime-based cache invalidation. Returns `MemoryListResponse`. Handles: empty file, file not found (empty list), malformed entries skipped.
- **Tests**: `tests/backend/test_memory_service.py` — empty file, missing file, malformed entries, large file, pagination, cache invalidation
- **Deps**: TASK-002

### TASK-007: REST Routers (Config, Models, Providers, Checkpoints, Memory, Health)
- **Covers**: FR-006, FR-007, FR-009, FR-001 (model catalog)
- **Files**: Create `backend/routers/config.py`, `backend/routers/models.py`, `backend/routers/checkpoints.py`, `backend/routers/memory.py`
- **Details**: `GET/PATCH /api/v1/config`, `GET /api/v1/models/{provider}` (from `model_catalog.py`), `GET /api/v1/providers`, `GET /api/v1/checkpoints?ticker=X&date=Y` → `CheckpointResponse`, `DELETE /api/v1/checkpoints?confirm=true`, `DELETE /api/v1/checkpoints/{ticker}?confirm=true`, `GET /api/v1/memory?page=1&limit=50`.
- **Tests**: `tests/backend/test_router_config.py`, `tests/backend/test_router_models.py`, `tests/backend/test_router_checkpoints.py`, `tests/backend/test_router_memory.py` — per-router test files for independent review; cover all endpoints, validation errors (400), pagination, confirm param required for delete
- **Deps**: TASK-002, TASK-004, TASK-005, TASK-006

---

## F. Task Breakdown — Phase 2: Backend Analysis & WebSocket

### TASK-008: Stream Parser Extraction
- **Covers**: FR-002, FR-003
- **Files**: Create `backend/stream_parser.py`
- **Details**: Extract stream chunk parsing from `cli/main.py` lines 965-1153 into a backend-local module (not `tradingagents/` — keeps web concerns out of the pip-installable core library). Functions: `parse_stream_chunk(chunk) -> list[DomainEvent]` where DomainEvent is a dataclass union (AgentStatusEvent, ReportChunkEvent, MessageEvent, ToolCallEvent, StatsEvent, ProgressEvent). Section keys: `analyst_market`, `analyst_social`, `analyst_news`, `analyst_fundamentals`, `research_bull`, `research_bear`, `research_manager`, `trader`, `risk_aggressive`, `risk_conservative`, `risk_neutral`, `portfolio_manager`.
- **Tests**: `tests/backend/test_stream_parser.py` — parse each event type, unknown chunk types skipped, malformed chunks handled
- **Deps**: None

### TASK-009: Event Bus
- **Covers**: FR-002, FR-003, NFR-001
- **Files**: Create `backend/event_bus.py`
- **Details**: `EventBus` class. Thread-safe bridge: `emit(event)` calls `asyncio.run_coroutine_threadsafe(queue.put(event), loop)`. Async consumer `drain()` reads from `asyncio.Queue(maxsize=1000)` and broadcasts to subscribers. If queue is full, drop oldest event, log warning, and emit a synthetic `events_dropped` event into the ring buffer so reconnecting clients see the gap in their replay snapshot. Subscribers: WebSocket push, stats aggregation. Ring buffer of 500 non-report_chunk events per run, capped at 2MB total byte size measured as JSON-serialized string length (evict oldest on either limit). Buffer discarded immediately on terminal state.
- **Tests**: `tests/backend/test_event_bus.py` — queue put/drain, thread-to-async bridge, queue full back-pressure (drop oldest), ring buffer overflow (count and byte size), report_chunk exclusion, buffer cleanup on terminal
- **Deps**: None

### TASK-010: Custom Callback Handler
- **Covers**: FR-002, FR-003
- **Files**: Create `backend/callbacks.py`
- **Details**: `WebCallbackHandler(BaseCallbackHandler)`. Emits domain events to event bus (NOT WebSocket-aware). Maps: `on_llm_start` → message event, `on_llm_end` → stats update, `on_tool_start` → tool_call event, `on_tool_end` → message event.
- **Tests**: `tests/backend/test_callbacks.py` — event formatting for each event type
- **Deps**: TASK-009

### TASK-011: WebSocket Manager
- **Covers**: FR-002, FR-003, FR-011, SEC-003, SEC-012
- **Files**: Create `backend/ws_manager.py`
- **Details**: `WSManager` class. Track connections per `run_id`. Origin header validation on upgrade (reject missing Origin; non-browser tools like wscat must use matching Origin header). Multiple clients per analysis. Auto-cleanup on disconnect. Per-client outbound buffer: bounded `asyncio.Queue(maxsize=64)` with dedicated send task per connection; if buffer fills (slow consumer), disconnect with 1008 Policy Violation close code. Application-level heartbeat every 30s (`{type: "heartbeat", seq: N}`). Client must respond with `{type: "pong"}` (add to client→server message union). Server disconnects after 90s without pong. On `replay` message: hold live events until snapshot sent, then resume broadcasting. Inbound frame max 4KB, rate limit 10/second, disconnect on exceed. `permessage-deflate` enabled. On invalid `run_id` connect: accept, send `{type: "error", seq: 0, message: "Run not found"}`, close with code 4404.
- **Tests**: `tests/backend/test_ws_manager.py` — connect, disconnect, broadcast, origin validation (reject missing Origin), heartbeat, pong response tracking, 90s timeout without pong, replay/snapshot, rate limiting, frame size limit, partial JSON frame handling (discard without crash), rapid open/close cycling, invalid run_id → 4404 close, slow consumer disconnect (buffer full → 1008)
- **Deps**: TASK-009

### TASK-012: Analysis Service
- **Covers**: FR-002, FR-008, NFR-002, SEC-010, SEC-011, SEC-018
- **Files**: Create `backend/services/analysis_service.py`
- **Details**: `AnalysisService` class. Constructor accepts persistence, event_bus, ws_manager, config_service as parameters (composition root in `backend/main.py` lifespan wires them). `asyncio.Lock` guards the active-runs dict; `start_analysis` holds the lock for the entire check-and-insert sequence (cap check + dict mutation atomic). Per-run `asyncio.Lock` instances for individual state transitions (running→terminal) to avoid global serialization; state transitions MUST only occur from coroutines on the event loop (never directly from the worker thread — worker thread completion fires an event loop callback via `asyncio.to_thread`'s return path). Add assertion guard in transition code verifying execution on the event loop thread. `start_analysis(request)` → check concurrency cap (3 active + 3 zombie max), insert SQLite row (status=running), generate UUID4 run_id (SEC-010), create `TradingAgentsGraph`, run `propagate()` via `asyncio.to_thread()`. 30-min wall-clock timeout via `asyncio.wait_for`. Cancellation flag. State machine: running → completed|failed|cancelled (enforced). Cancel is idempotent (terminal → 200 no-op, 404 for unknown). On completion/cancel/timeout: release graph+LLM refs (verify via weakref in tests), persist to SQLite, call `persistence.checkpoint()` (which acquires `threading.Lock` before `PRAGMA wal_checkpoint(PASSIVE)`), decrement zombie count when thread completes. Secondary hard timeout at 35min: if zombie thread still hasn't exited 5min after the 30-min wall-clock timeout, forcibly reclaim the zombie slot (decrement counter, log error, mark run failed) to prevent permanent slot exhaustion. Generic error messages to clients (SEC-018), internal details logged with correlation ID. `research_depth` → `max_debate_rounds` + `max_risk_discuss_rounds`.
- **Tests**: `tests/backend/test_analysis_service.py` — lifecycle, concurrency cap (race condition safety), timeout, cancel idempotency, state transitions, zombie cap, zombie recovery via secondary hard timeout, error sanitization, research_depth mapping, weakref graph/LLM release verification after completion
- **Deps**: TASK-002, TASK-003, TASK-004, TASK-008, TASK-009, TASK-010

### TASK-013: Analysis Router
- **Covers**: FR-002, FR-004, FR-005, FR-008
- **Files**: Create `backend/routers/analysis.py`
- **Details**: `POST /api/v1/analysis` → start, returns `AnalysisCreateResponse`. `GET /api/v1/analysis` → list with pagination+filters. `GET /api/v1/analysis/{run_id}` → status+results. `GET /api/v1/analysis/{run_id}/report` → markdown download with `Content-Type: text/markdown; charset=utf-8` and sanitized Content-Disposition (filename constructed as `report-{run_id}.md` using UUID — guaranteed filesystem-safe; do NOT incorporate user-controlled ticker in filename). `POST /api/v1/analysis/{run_id}/cancel` → cancel. API key validation: check relevant `*_API_KEY` env var for chosen provider, 422 if missing. All custom error responses use `ErrorResponse` schema. All state-mutating endpoints require `X-Requested-With: XMLHttpRequest` header.
- **Tests**: `tests/backend/test_analysis_router.py` — all CRUD, 429 on 4th, validation errors, report download filename sanitization + Content-Type assertion, API key missing 422, error response schema consistency, CSRF header required on POST/cancel, config JSON round-trip fidelity (start with all optional fields populated including nested data_vendors and provider config, force failure, GET run, assert config matches original)
- **Deps**: TASK-002, TASK-012

### TASK-014: WebSocket Endpoint
- **Covers**: FR-002, FR-003, FR-011
- **Files**: Create `backend/routers/ws.py`
- **Details**: `WebSocket /ws/v1/analysis/{run_id}`. Delegates to WSManager. Subscribes to event bus for the run. Sends messages as JSON with monotonic `seq` (integer, resets per run, will not exceed Number.MAX_SAFE_INTEGER). On reconnect: replay message → snapshot from current state or SQLite for terminal runs → resume broadcasting.
- **Tests**: `tests/backend/test_ws_endpoint.py` — full flow (mock graph), reconnection, snapshot, cancel mid-run, concurrent streams isolated, invalid run_id → 4404 close
- **Deps**: TASK-011, TASK-012

### TASK-015: Backend Integration Tests
- **Covers**: All backend requirements
- **Files**: `tests/backend/test_integration.py`
- **Details**: Full REST+WS integration tests. 429 on 4th analysis. Timeout concurrency slot release. Zombie thread cap + recovery (secondary hard timeout at 35min reclaims zombie slot even if thread hasn't exited — logs error, decrements counter, marks run as failed). Graceful shutdown (verifies lifespan shutdown cancels runs and closes WS). Orphan recovery. WS reconnection mid-analysis. WS reconnect after completion. Multiple rapid disconnects. Concurrent analyses isolation. Real-stream integration test: instantiate `TradingAgentsGraph` with a mock/stub LLM, call `propagate()` via `asyncio.to_thread`, verify stream events flow through event bus → WS → client with correct types and ordering (not just mocked events).
- **Deps**: All Phase 2 tasks

---

## F. Task Breakdown — Phase 3: Frontend Foundation

### TASK-016: Vite + React Project Scaffold
- **Covers**: Architecture
- **Files**: Create `frontend/` with Vite React TypeScript template
- **Details**: `npm create vite@latest frontend -- --template react-ts`. Install deps: `@tanstack/react-router`, `@tanstack/react-query`, `@reduxjs/toolkit`, `react-redux`, `zod`. Configure `vite.config.ts` with API proxy to `http://localhost:8000`. Set `VITE_API_BASE_URL` env var. Install test deps: `vitest`, `@testing-library/react`, `msw` (Mock Service Worker for integration tests), `@testing-library/user-event`. Create `frontend/src/test/` with MSW handlers (REST mock responses) and WS message factories for shared test infrastructure. Configure ESLint + Prettier for frontend code consistency.
- **Deps**: None

### TASK-017: shadcn/ui + Tailwind Setup
- **Covers**: UI/UX design system
- **Files**: Modify `frontend/` config files, create `frontend/src/components/ui/`
- **Details**: Install shadcn/ui via CLI. Dark mode default. Monospace font for data. Install components: Button, Input, Select, Checkbox, Card, Table, Tabs, Dialog, Sheet, Badge, Progress, Skeleton. Install Magic UI for enhanced components: animated cards (Home page), number tickers (StatsBar), shimmer loading effects. Install `@tanstack/react-virtual` for MessagesPanel virtualization. Install `react-markdown` with `remark-gfm` and `rehype-sanitize` plugins for streaming-friendly markdown rendering.
- **Deps**: TASK-016

### TASK-018: TanStack Router Setup
- **Covers**: FR routing
- **Files**: Create `frontend/src/routes/` with file-based routing
- **Details**: Routes: `/` (home), `/analysis/new`, `/analysis/$runId`, `/history`, `/config`, `/memory`. Layout component with sidebar navigation.
- **Tests**: `frontend/src/routes/__tests__/routing.test.tsx` — unknown route renders 404, invalid runId handled, navigation updates document title
- **Deps**: TASK-016

### TASK-019: Redux Store + TanStack Query Client
- **Covers**: State management
- **Files**: Create `frontend/src/store/index.ts`, `frontend/src/store/slices/uiSlice.ts`, `frontend/src/lib/queryClient.ts`
- **Details**: Redux store with uiSlice (wizard step, sidebar state, theme). Wizard form field values stored under nested key `uiSlice.wizard.formValues` with dedicated sub-reducer to isolate form concerns (reset on successful submission or explicit cancel). TanStack Query client with defaults. Provider wrappers in app root.
- **Tests**: `frontend/src/store/__tests__/uiSlice.test.ts` — wizard step transitions, sidebar toggle, theme
- **Deps**: TASK-016

### TASK-020: API Client Module
- **Covers**: Frontend API layer
- **Files**: Create `frontend/src/lib/api.ts`
- **Details**: TanStack Query hooks for all REST endpoints: `useHealth()`, `useConfig()`, `useUpdateConfig()`, `useProviders()`, `useModels(provider)`, `useAnalysisList(params)`, `useAnalysis(runId)`, `useMemory(params)`, `useCheckpoint(ticker, date)`, `useStartAnalysis()`, `useCancelAnalysis()`, `useDeleteCheckpoints()`. Typed with Zod schemas matching backend. `useHealth()` used as startup gate: app shows loading spinner until health returns 200, with retry every 2s and error message after 10 failed attempts ("Backend not reachable") with manual retry button (aligned with spec R15.1). Per-query staleTime: config/models 5min, history list 30s, active analysis status Infinity (WS-driven), memory 60s.
- **Tests**: `frontend/src/lib/__tests__/api.test.ts` — health gate retry (succeeds on 3rd), health gate timeout (10 failures → error), Zod validation rejects malformed responses, query key structure, staleTime configuration
- **Deps**: TASK-016, TASK-019

---

## F. Task Breakdown — Phase 4: Frontend Analysis UI

### TASK-021: Analysis Config Form (ConfigForm.tsx)
- **Covers**: FR-001, NFR-007, AC-001
- **Files**: Create `frontend/src/components/analysis/ConfigForm.tsx`
- **Details**: Multi-step wizard (8 steps matching CLI). Redux uiSlice tracks current step. Client-side validation: ticker regex, date not future, min 1 analyst, model ID regex, backend_url scheme check. Provider-conditional config fields: show `google_thinking_level` selector for Google, `openai_reasoning_effort` for OpenAI, `anthropic_effort` for Anthropic (hide/show on provider change, validate enum values). On provider change: clear+disable model dropdowns, fetch new list, show loading. On model fetch failure: inline error + retry + custom ID fallback. Enter advances, Back button goes back, focus moves to first field on step change. Checkpoint toggle checkbox (enabled/disabled); checkpoint existence query debounced at 300ms after last ticker/date field change, with loading spinner replacing indicator during re-fetch. Submit calls `useStartAnalysis()`, navigates to `/analysis/{runId}`. Responsive: single-column below 1024px, full-width dropdowns, stacked model selectors.
- **Tests**: `frontend/src/components/analysis/__tests__/ConfigForm.test.tsx` — validation, wizard gating, provider change loading state, model fetch error, provider-conditional fields show/hide, focus management on step change, checkpoint toggle, responsive layout at 1024px breakpoint
- **Deps**: TASK-018, TASK-019, TASK-020

### TASK-022: useAnalysisWebSocket Hook
- **Covers**: FR-002, FR-003, FR-011, NFR-001, NFR-006
- **Files**: Create `frontend/src/hooks/useAnalysisWebSocket.ts`
- **Details**: WebSocket connection to `/ws/v1/analysis/{run_id}` on mount, cleanup on unmount. No WS for completed analyses. Reconnection: exponential backoff (1s, 2s, 4s, max 30s), max 10 attempts. On connect: send `{type: "replay"}`, buffer messages until snapshot, apply only `seq > snapshot.seq`. Respond to server `heartbeat` with `{type: "pong"}`. Application-level heartbeat resets 45s idle timer. 100ms message batching via `requestAnimationFrame`. Runtime zod validation of all inbound messages. Updates TanStack Query cache via `queryClient.setQueryData(["analysis", runId, "ws-state"], updater)`. Cache shape: `{agents, reports, messages, stats, progress}`. `staleTime: Infinity`, `gcTime: 0` (clear stale WS data immediately on unmount to prevent flash of outdated data on re-mount). On completion event: cache the final complete message's `final_state` as the terminal cache entry (do NOT invalidate and refetch via REST — the WS complete message is authoritative). For cold-load of completed runs (direct navigation): use `GET /api/v1/analysis/{run_id}` + `GET /api/v1/analysis/{run_id}/report` to populate a separate `["analysis", runId, "rest-state"]` query key, with an adapter that maps REST shape to dashboard component props. Snapshot with invalid fields → reject + reconnect. Ephemeral state (attempt count, buffer, timer) in `useRef`.
- **Tests**: `frontend/src/hooks/__tests__/useAnalysisWebSocket.test.ts` — batching, backoff, max attempts, replay, snapshot atomic replace, snapshot validation/rejection, heartbeat pong response, 45s idle trigger, cleanup, gcTime=0 clears cache on unmount, no WS for completed, malformed JSON, unknown type, missing fields, defense-in-depth seq filtering, cold-load REST adapter
- **Deps**: TASK-019, TASK-020

### TASK-023: Dashboard Components
- **Covers**: FR-003, FR-004, FR-008, FR-010, NFR-004, NFR-005, NFR-006, SEC-008, AC-002
- **Files**: Create `frontend/src/components/analysis/AgentStatusTable.tsx`, `MessagesPanel.tsx`, `ReportPanel.tsx`, `StatsBar.tsx`, `ErrorBanner.tsx`, `ReconnectionIndicator.tsx`
- **Details**:
  - **AgentStatusTable**: Agents grouped by team, color-coded badges, roving tabindex for keyboard nav. Responsive collapse.
  - **MessagesPanel**: Timestamped messages, virtualized list via `@tanstack/react-virtual` for 500+ messages without DOM bloat. Auto-scroll when at bottom (50px threshold), "Jump to latest" button. No aria-live on container; visually-hidden summary with `aria-live="polite"` announces "N new messages" every 10s max.
  - **ReportPanel**: Per-section memoized markdown rendering with `rehype-sanitize` (SEC-008: no raw HTML, no dangerouslySetInnerHTML). Coordinated debounce at ReportPanel level: single shared RAF callback flushes all pending section updates in one render pass (not per-section independent debounce).
  - **StatsBar**: LLM calls, tool calls, tokens in/out, elapsed time (ticking). `aria-live="polite"`.
  - **ErrorBanner**: `aria-live="assertive"`, focus on appear. Retry (deserializes config JSON → form, navigates to `/analysis/new`, focuses submit button or first invalid field) and Reconfigure (navigates to `/analysis/new` step 1, focuses first field) actions. 429 inline error. Crash-recovered run error state.
  - **ReconnectionIndicator**: `role="status"`, shows attempt count, announces "Connected" on success.
  - Cancel button with confirmation dialog.
  - Responsive: below 1024px single-column, Status+Report open, Messages+Stats collapsed via disclosure buttons (`aria-expanded`, keyboard-operable via Enter/Space). Below 768px: full-screen panels, sidebar collapsed to hamburger menu, touch-friendly tap targets (min 44px). Stop in sticky header at all breakpoints.
  - Error Boundary wrapper around each dashboard panel: fallback UI ("This panel encountered an error") with retry action.
- **Tests**: `frontend/src/components/analysis/__tests__/*.test.tsx` — all component states, accessibility, responsive
- **Deps**: TASK-022

### TASK-024: Analysis Dashboard Route
- **Covers**: FR-002, FR-003, FR-004, AC-002, AC-003
- **Files**: Create/update `frontend/src/routes/analysis/$runId.tsx`
- **Details**: Composes all dashboard components. Uses `useAnalysisWebSocket` for active runs (ws-state query key), REST fetch for completed runs (rest-state query key with adapter, `staleTime: Infinity` since terminal run data is immutable). On receiving a terminal WS event (completed/failed/cancelled): mark ws-state inactive, promote the ws-state terminal snapshot into the rest-state query key so subsequent re-mounts use cached terminal data without a REST round-trip (consistent with TASK-022's "WS complete message is authoritative" rule). The rest-state key only triggers a real REST fetch for cold-load scenarios (direct navigation to a completed run with no prior WS data). On re-mount: route checks if rest-state is cached; if not, fetches via REST. Loading state: show skeleton placeholders for AgentStatusTable, MessagesPanel, ReportPanel, and StatsBar until first snapshot or REST data arrives (covers initial load and reconnection gap). 404 state: "Analysis not found" message with link to Home/History. Report download button. Report sections collapsible/expandable. Error Boundary per panel.
- **Tests**: `frontend/src/routes/analysis/__tests__/$runId.test.tsx` — renders WS-driven state for active runs, renders REST data for completed runs, loading skeleton shown before data, report download triggers correct endpoint, report sections expand/collapse, 404 run_id shows not-found UI, error boundary catches panel crash
- **Deps**: TASK-022, TASK-023

---

## F. Task Breakdown — Phase 5: Frontend Remaining Pages

### TASK-025: Home Dashboard
- **Covers**: NFR-008
- **Files**: Create/update `frontend/src/routes/index.tsx`
- **Details**: Active analyses overview (cards), recent history (last 5), quick-start CTA. Empty state: welcome + start CTA.
- **Tests**: `frontend/src/routes/__tests__/index.test.tsx` — active analyses cards render, empty state, quick-start navigation
- **Deps**: TASK-020

### TASK-026: History Page
- **Covers**: FR-005, NFR-009, AC-004
- **Files**: Create/update `frontend/src/routes/history.tsx`
- **Details**: Table with pagination controls. Filters: ticker, status, date range. Click navigates to analysis dashboard. Empty state.
- **Tests**: `frontend/src/routes/__tests__/history.test.tsx` — table renders, pagination, filters, empty state, row click navigation
- **Deps**: TASK-020

### TASK-027: Configuration Page
- **Covers**: FR-006, AC-005
- **Files**: Create/update `frontend/src/routes/config.tsx`
- **Details**: View current config (defaults, overrides, resolved). Edit form for allowlisted keys. Provider model catalog reference display. Save via `useUpdateConfig()`. Checkpoint management section: clear all checkpoints button, clear per-ticker button, confirmation dialog before delete.
- **Tests**: `frontend/src/routes/__tests__/config.test.tsx` — displays config, edit form validation, save success/error, unknown key rejection, checkpoint clear with confirmation
- **Deps**: TASK-020

### TASK-028: Memory Log Page
- **Covers**: FR-007, AC-006
- **Files**: Create/update `frontend/src/routes/memory.tsx`
- **Details**: Parsed memory entries with status badges. Reflection and returns for resolved entries. Pagination. Empty state.
- **Tests**: `frontend/src/routes/__tests__/memory.test.tsx` — entries render, pagination, empty state, malformed entries handled
- **Deps**: TASK-020

---

## F. Task Breakdown — Phase 6: Integration, E2E, Production

### TASK-029: Backend Security Tests
- **Covers**: SEC-001 through SEC-019
- **Files**: `tests/backend/test_security.py`
- **Details**: CORS rejection, WS origin rejection, SSRF (all IP variants + self-request + DNS rebinding), API key masking, ticker regex injection attempts, provider enum rejection, PATCH config unknown keys, Content-Disposition sanitization, error message sanitization, CORS startup wildcard rejection, CSP header, WS frame size + rate limit, output_language validation, WEB_HOST hardcoded, UUID4 run_id format validation (SEC-010), concurrent POST race condition (10 simultaneous → exactly 3 accepted, rest 429), rapid WS reconnection flood (50 connects in 1s → server stable), grep-based audit: no `dangerouslySetInnerHTML` in frontend source (SEC-008).
- **Deps**: All backend tasks

### TASK-030: E2E Tests (Playwright) + Frontend Integration Tests
- **Covers**: AC-001 through AC-008, NFR-003
- **Files**: `tests/e2e/`
- **Details**: Full analysis flow, cancel mid-run, reconnection, error flow, history pagination, checkpoint resume, memory page, concurrent analyses, configuration management, 429 rejection, crash-recovered run, retry flow, graceful shutdown, analysis timeout. Accessibility tests: axe-core audit on each page (no Critical/Serious violations), keyboard-only navigation through wizard and dashboard, screen reader announcements for status changes. Responsive viewport tests: 1024px breakpoint single-column layout, 768px mobile layout, sticky header with Stop button on narrow viewports. Cross-browser: run core E2E suite on chromium and webkit Playwright projects (NFR-003). Frontend integration tests (vitest + MSW + fake WS): submit form → mock 201 → navigate → WS messages arrive → dashboard components update correctly; covers the gap between component unit tests and full E2E.
- **Deps**: All tasks

### TASK-031: Performance Tests
- **Covers**: NFR-001, NFR-006
- **Files**: `tests/backend/test_performance.py`, `tests/e2e/test_performance.py`
- **Details**: Backend (`tests/backend/test_performance.py`): WS latency <500ms, concurrent throughput (3 analyses × 50 msgs/sec), no memory growth over 30-min WS session. Frontend (`tests/e2e/test_performance.py`): Playwright-based MessagesPanel 500 messages rendering test using `page.metrics()` or Performance Observer to verify frame budget (no jank).
- **Deps**: All tasks

### TASK-032: Production Build & Start Scripts
- **Covers**: Build/serving
- **Files**: Modify `start.bat`, create `start.sh`, create `backend/static_files.py`
- **Details**: Frontend `npm run build` → `frontend/dist/`. FastAPI mounts `dist/` via StaticFiles with SPA fallback. Update `start.bat` and create `start.sh` (cross-platform) to build frontend and launch backend. Add web deps to `pyproject.toml` as optional extras group: `[project.optional-dependencies] web = ["fastapi>=0.115", "uvicorn[standard]>=0.34"]`. Install via `pip install -e ".[web]"`. (No `aiosqlite` — persistence uses synchronous `sqlite3` with `check_same_thread=False` accessed via `asyncio.to_thread`.) Do NOT add web deps to the base `[project.dependencies]` — CLI/library users should not pull in FastAPI. Create `.env.example` files for both `backend/` and `frontend/` documenting all env vars (WEB_CORS_ORIGIN, VITE_API_BASE_URL, API keys with `CHANGE_ME_NOT_A_REAL_KEY` placeholders). Verify `.env` is in `.gitignore` for root and `frontend/`. Rollback note: pre-migration DB backup enables restore; document upgrade procedure in README (drain active analyses, backup DB, upgrade, start).
- **Deps**: All tasks

---

## G. File-Level Change Plan

| File | Action | Purpose | Tasks |
|------|--------|---------|-------|
| `backend/__init__.py` | Create | Package init | TASK-001 |
| `tests/backend/conftest.py` | Create | Shared test fixtures | TASK-001 |
| `backend/main.py` | Create | FastAPI app, CORS, CSP, lifespan, health | TASK-001 |
| `backend/schemas.py` | Create | All Pydantic models | TASK-002 |
| `backend/validators.py` | Create | Backend URL SSRF validator | TASK-003 |
| `backend/persistence.py` | Create | SQLite WAL persistence layer | TASK-004 |
| `backend/event_bus.py` | Create | Thread-safe event bus + ring buffer | TASK-009 |
| `backend/callbacks.py` | Create | LangGraph callback handler | TASK-010 |
| `backend/ws_manager.py` | Create | WebSocket connection manager | TASK-011 |
| `backend/services/__init__.py` | Create | Package init | TASK-005 |
| `backend/services/config_service.py` | Create | Config resolution + redaction | TASK-005 |
| `backend/services/memory_service.py` | Create | Memory log parser | TASK-006 |
| `backend/services/analysis_service.py` | Create | Analysis lifecycle manager | TASK-012 |
| `backend/routers/__init__.py` | Create | Package init | TASK-007 |
| `backend/routers/config.py` | Create | Config REST endpoints | TASK-007 |
| `backend/routers/models.py` | Create | Model catalog endpoint | TASK-007 |
| `backend/routers/checkpoints.py` | Create | Checkpoint endpoints | TASK-007 |
| `backend/routers/memory.py` | Create | Memory endpoint | TASK-007 |
| `backend/routers/analysis.py` | Create | Analysis CRUD endpoints | TASK-013 |
| `backend/routers/ws.py` | Create | WebSocket endpoint | TASK-014 |
| `backend/stream_parser.py` | Create | Backend-local stream chunk parser | TASK-008 |
| `frontend/` | Create | Entire frontend SPA | TASK-016-028 |
| `start.bat` | Modify | Launch both backend and frontend | TASK-032 |
| `start.sh` | Create | Cross-platform start script | TASK-032 |
| `.env.example` | Create | Document all env vars | TASK-032 |
| `pyproject.toml` | Modify | Add `[project.optional-dependencies] web` extras group + Ruff config + add `"backend*"` to setuptools packages.find include | TASK-032 |

---

## Q. Dependency and Sequencing Plan

### Critical Path
TASK-001 → TASK-002 → TASK-004 → TASK-012 → TASK-013 → TASK-014 → (frontend) → TASK-030

### Parallel Tracks Within Phases
- **Phase 1**: TASK-001, TASK-002, TASK-003, TASK-004 can start in parallel. TASK-005 depends on TASK-002 and TASK-004. TASK-006 depends on TASK-002. TASK-007 depends on TASK-002/004/005/006.
- **Phase 2**: TASK-008, TASK-009 parallel. TASK-010 after TASK-009. TASK-011 after TASK-009. TASK-012 after TASK-002/003/004/008/009/010. TASK-013/014 after TASK-012.
- **Phase 3**: All tasks mostly parallel after TASK-016.
- **Phase 4**: TASK-021 and TASK-022 parallel. TASK-023 after TASK-022. TASK-024 after both.
- **Phase 5**: All tasks parallel (depend only on TASK-020).
- **Phase 6**: All tasks depend on prior phases.

---

## S. Definition of Done

- All 32 tasks implemented and tested
- All unit, integration, security, component, hook, E2E, performance tests passing
- Production build serves SPA via FastAPI
- `start.bat` launches the full application
- No Critical or High unresolved findings
- Spec requirements (FR, SEC, NFR, AC) traceable to tasks and tests
