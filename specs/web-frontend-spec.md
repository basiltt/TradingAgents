# TradingAgents Web Frontend — Specification

## Metadata

- **Feature**: Web Frontend for TradingAgents
- **Author**: Claude
- **Status**: Approved (R15 — 2 consecutive clean rounds at Critical/High level)
- **Created**: 2026-05-02

---

## Discovery Summary

### Existing Architecture

- **Backend**: Python framework using LangGraph for multi-agent orchestration
- **CLI**: Typer + Rich interactive terminal UI (`cli/main.py`, `cli/utils.py`)
- **12 agents** across 5 phases: Analysts (4) -> Research (3) -> Trading (1) -> Risk (3) -> Portfolio (1)
- **State**: `AgentState` TypedDict with 25+ fields flowing through graph
- **Config**: `DEFAULT_CONFIG` dict with env var overrides
- **LLM Providers**: OpenAI, Anthropic, Google, xAI, DeepSeek, Qwen, GLM, OpenRouter, Azure, Ollama
- **Data Vendors**: yfinance (default), Alpha Vantage (fallback)
- **Persistence**: Memory log (`~/.tradingagents/memory/trading_memory.md`), SQLite checkpoints
- **Callbacks**: `StatsCallbackHandler` tracks llm_calls, tool_calls, tokens_in, tokens_out

### Key Files

- `tradingagents/graph/trading_graph.py` — `TradingAgentsGraph` class, `propagate()` method
- `tradingagents/graph/setup.py` — LangGraph node/edge wiring via `GraphSetup`
- `tradingagents/graph/propagation.py` — `Propagator.propagate()` streams graph execution
- `tradingagents/agents/utils/agent_states.py` — `AgentState`, `InvestDebateState`, `RiskDebateState`
- `tradingagents/default_config.py` — All configuration options
- `tradingagents/llm_clients/model_catalog.py` — `MODEL_OPTIONS` dict with provider/mode model lists
- `tradingagents/llm_clients/factory.py` — `create_llm_client()` factory
- `cli/main.py` — `run_analysis()`, `get_user_selections()`, `MessageBuffer`, streaming loop
- `cli/utils.py` — All interactive prompts, provider list with URLs
- `cli/stats_handler.py` — `StatsCallbackHandler` (thread-safe LLM/tool tracking)

---

## Feature Overview

Build a modern web frontend that fully replaces the terminal CLI, exposing all TradingAgents workflows through a browser-based interface with real-time WebSocket updates during analysis runs.

### Business Goal

Enable users to configure, launch, and monitor trading analyses from a web browser with a rich real-time dashboard, eliminating the need for terminal interaction.

---

## Scope

### In Scope

- FastAPI backend serving REST API + WebSocket endpoints
- React frontend with Vite + TanStack Router (file-based routing), TanStack Query, Redux Toolkit (client-local UI state only), shadcn/ui, Magic UI
- All 8 CLI configuration steps replicated as a web form
- Real-time analysis dashboard with WebSocket-streamed agent status, reports, messages, and stats
- Report viewing and download
- Configuration management (LLM provider, models, data vendors, etc.)
- Memory log viewing
- Multiple concurrent analysis support (each in its own WebSocket session)

### Out of Scope

- Authentication / authorization (explicitly excluded; server binds to 127.0.0.1 only)
- Broker API integration
- Backtesting / batch analysis
- Mobile-specific layouts (responsive but desktop-first)
- Deployment / CI/CD configuration

---

## Functional Requirements

### FR-001: Analysis Configuration Form

The frontend must present a multi-step configuration form mirroring the CLI's 8-step questionnaire:

1. **Ticker Symbol** — Text input, uppercase normalization, validated against regex `^[A-Z0-9.\-^]{1,15}$` (server-side and client-side)
2. **Analysis Date** — Date picker, YYYY-MM-DD format, cannot be in the future
3. **Output Language** — Dropdown with 12 presets (English, Chinese, Japanese, Korean, Hindi, Spanish, Portuguese, French, German, Arabic, Russian, Custom) + custom text input
4. **Analyst Selection** — Checkbox group: Market, Social, News, Fundamentals (min 1 required)
5. **Research Depth** — Radio/select: Shallow (1), Medium (3), Deep (5) debate rounds
6. **LLM Provider** — Dropdown validated against enum: openai, google, anthropic, xai, deepseek, qwen, glm, openrouter, azure, ollama
7. **Model Selection** — Two dropdowns (quick-think, deep-think) populated from `MODEL_OPTIONS` for selected provider, plus "Custom model ID" text input option. Custom model IDs validated against `^[a-zA-Z0-9._:/-]{1,100}$`. On provider change, model dropdowns are cleared and disabled with loading indicator until new model list resolves; previous selections reset. On model fetch failure, show inline error with retry button; user can switch to "Custom model ID" input as fallback
8. **Provider Config** — Conditional fields based on provider:
   - Google: Thinking level (high/minimal)
   - OpenAI: Reasoning effort (low/medium/high)
   - Anthropic: Effort level (low/medium/high)

Additional fields not in CLI but available in config:
9. **Backend URL** — Optional text input for custom LLM endpoint/proxy. Server-side: only allow `http://` or `https://` schemes; block private IP ranges except `127.0.0.1` and `localhost` (for local proxies)
10. **Checkpoint** — Toggle for checkpoint/resume. When ticker+date entered, UI queries `GET /api/v1/checkpoints?ticker=X&date=Y` to indicate if a resumable checkpoint exists
11. **Data Vendors** — Category-level vendor selection (yfinance/alpha_vantage per category)

### FR-002: Analysis Execution

- POST to start analysis returns a `run_id`
- Backend creates `TradingAgentsGraph` with provided config
- Runs `graph.propagate()` via streaming
- WebSocket connection streams real-time updates to frontend

### FR-003: Real-Time Dashboard

During analysis, the dashboard must display (mirroring CLI's Rich layout):

1. **Agent Status Table** — All agents grouped by team (Analyst, Research, Trading, Risk, Portfolio) with status indicators: pending, in_progress, completed
2. **Live Messages Panel** — Scrollable feed of timestamped messages (agent name, content, tool calls)
3. **Current Report Panel** — Markdown-rendered current report section being generated
4. **Statistics Footer** — Agents completed/total, LLM calls, Tool calls, Tokens in/out, Elapsed time
5. **Progress Bar** — Reports completed / total reports

### FR-004: Report Viewing

After analysis completes:
1. Display complete structured report with sections:
   - I. Analyst Team Reports (Market, Social, News, Fundamentals)
   - II. Research Team Decision (Bull, Bear, Research Manager)
   - III. Trading Team Plan (Trader)
   - IV. Risk Management (Aggressive, Conservative, Neutral)
   - V. Portfolio Manager Decision
2. Markdown rendering for all report sections
3. Download report as markdown file (filename: `{ticker}_{date}_report.md`, Content-Disposition header with quoted sanitized filename)

### FR-005: Analysis History

- List past analyses with ticker, date, decision, timestamp
- View any past analysis report
- Read from SQLite persistence layer (not the memory log, which is covered by FR-007)

### FR-006: Configuration Management

- View and edit default configuration
- Override via form fields or env-var-style key-value pairs
- Show current active configuration (resolved from defaults + env vars + user overrides)
- Provider-specific model catalogs displayed for reference

### FR-007: Memory Log Viewer

- Display contents of `~/.tradingagents/memory/trading_memory.md`
- Parse and display individual entries with status (pending/resolved)
- Show reflection text and returns when available

### FR-008: Analysis Cancellation

- `POST /api/v1/analysis/{run_id}/cancel` stops a running analysis
- Cancel requires user confirmation (dialog: "Cancel this analysis? This cannot be undone.")
- Backend sets a cancellation flag, graph execution terminates at next node boundary
- WebSocket sends `{ type: "cancelled" }` message
- Dashboard shows cancelled state with partial results available

### FR-009: Checkpoint Management

- `GET /api/v1/checkpoints?ticker=X&date=Y` checks if a checkpoint exists; returns `{ exists: bool, created_at: str | null }`
- `DELETE /api/v1/checkpoints` clears all checkpoints (requires `?confirm=true` query param)
- `DELETE /api/v1/checkpoints/{ticker}` clears checkpoints for a specific ticker (requires `?confirm=true`)
- UI affordance on config page or analysis form

### FR-010: Error Handling

- When analysis fails mid-execution, WebSocket sends `{ type: "error", message: "..." }`
- Dashboard displays error banner with failure message
- `AnalysisResponse` includes `error: string | null` field
- UI offers "Retry with same config" and "Reconfigure" actions. "Retry" deserializes the run's persisted `config` JSON back into form state
- When `POST /api/v1/analysis` returns 429 (concurrent cap reached), display inline error on the form: "Maximum concurrent analyses reached (3). Please wait for a running analysis to complete."
- Crash-recovered runs (`error='Server crash recovery'`) may have no report sections; frontend shows the error state rather than an empty report

### FR-011: WebSocket Reconnection

- Frontend auto-reconnects with exponential backoff (1s, 2s, 4s, max 30s)
- On reconnect, frontend sends `{ type: "replay" }` to server
- Server responds with a `snapshot` message containing full current state; this is the sole reconciliation path (no parallel REST fetch)
- On receiving `snapshot`, frontend replaces TanStack Query cache atomically for query key `["analysis", runId, "ws-state"]` only (does not affect other runs). Defense-in-depth: client buffers any messages received between `replay` and `snapshot`, applies only those with `seq > snapshot.seq` (server guarantees no events are sent in this window, but the client guards against implementation bugs)
- UI shows "Reconnecting..." indicator during disconnection
- Maximum 10 reconnection attempts before showing "Connection lost" with manual retry button
- WebSocket opens on mount of Analysis Dashboard route, closes on unmount (useEffect cleanup), not shared across routes
- All inbound WebSocket messages validated at runtime (e.g., zod schema) before dispatching to state handlers; messages failing validation logged (raw content truncated to 200 chars) and discarded
- On re-mount of a completed analysis, no WebSocket opened — data fetched via REST only. If `replay` is received for a terminal run whose buffer is discarded, server responds with `snapshot` from SQLite persisted state

---

## Non-Functional Requirements

### NFR-001: Real-Time Latency

WebSocket updates must be delivered within 500ms of backend state change.

### NFR-002: Concurrent Analyses

Support at least 3 concurrent analysis runs, each with independent WebSocket streams.

### NFR-003: Browser Compatibility

Support latest Chrome, Firefox, Edge, Safari.

### NFR-004: Responsive Layout

Desktop-first but usable on tablet viewports (min 768px width). At viewports below 1024px, the dashboard switches to a single-column stacked layout (Status -> Report -> Messages -> Stats) with collapsible/tabbed panels. Default: Status and Report open, Messages and Stats collapsed. Stop button remains visible in a sticky header. Configuration form: single-column field layout below 1024px, full-width dropdowns, stacked model selectors.

### NFR-005: Accessibility

- Messages feed: no `aria-live` on the scrolling container (too noisy during streaming); instead, a visually-hidden summary element with `aria-live="polite"` announces "N new messages" at most every 10 seconds
- `aria-live="polite"` on stats bar
- `aria-live="assertive"` on error banner
- `role="status"` on progress indicators and reconnection indicator (announces "Reconnecting..." and "Connected" to screen readers)
- Keyboard-navigable agent status grid and form wizard
- Focus moves to ErrorBanner when it appears
- Focus moves to first field of each wizard step on advancement and backward navigation

### NFR-006: Frontend Performance

- WebSocket messages accumulated in a ref and flushed to React state via `requestAnimationFrame` or at 100ms intervals (batching)
- `React.memo` on all dashboard panels with selector-based subscriptions
- Markdown rendering debounced to at most every 200ms during active streaming; full render on section completion
- Each report section rendered by an independent memoized markdown component (update to one section does not re-parse others)
- Messages panel auto-scroll only when user is at bottom (within 50px); "Jump to latest" button when scrolled up

### NFR-007: Form Validation UX

- Text inputs: validate on blur
- Selects/checkboxes: validate on change
- Inline error messages below each field
- Wizard step cannot advance until current step is valid
- Enter on last field of a step advances; Back button or browser back returns to previous step (no Escape key capture, to avoid conflicts with dropdowns and assistive technology)

### NFR-008: Empty States

- History page: illustration + "No analyses yet — start your first analysis" CTA
- Memory page: "No trading memory entries recorded yet"
- Home dashboard: welcome message with quick-start CTA when no active/recent analyses

### NFR-009: History Pagination

- `GET /api/v1/analysis` supports `?page=1&limit=20` (default limit 20, max 100, server-side clamped)
- Frontend paginates with page controls

---

## Architecture

### Backend (FastAPI)

```
backend/
  main.py              — FastAPI app, CORS (explicit origins only), lifespan, bind 127.0.0.1
  routers/
    analysis.py        — POST /api/v1/analysis, GET, cancel
    config.py          — GET/PATCH /api/v1/config (redacts API keys)
    models.py          — GET /api/v1/models/{provider}
    checkpoints.py     — GET/DELETE /api/v1/checkpoints
    memory.py          — GET /api/v1/memory
    ws.py              — WebSocket /ws/analysis/{run_id} (origin-validated)
  services/
    analysis_service.py — Manages runs; active in-memory, completed persisted to SQLite
    config_service.py   — Configuration resolution with secret redaction
    memory_service.py   — Memory log parsing (hardcoded path, no user input in path)
  schemas.py           — Pydantic request/response models with validation
  ws_manager.py        — WebSocket connection management with origin check
  event_bus.py         — Event bus: callbacks emit events, WS subscriber consumes
  callbacks.py         — Custom callback handler emitting domain events (not WS-aware)
  persistence.py       — SQLite store for completed analysis runs and reports
```

### Frontend (React + Vite + TanStack Router)

```
frontend/
  app/
    routes/
      index.tsx            — Home / dashboard
      analysis/
        new.tsx            — Analysis configuration form
        $runId.tsx         — Real-time analysis dashboard
      history.tsx          — Past analyses list
      config.tsx           — Configuration management
      memory.tsx           — Memory log viewer
    components/
      analysis/
        ConfigForm.tsx     — Multi-step analysis config form
        AgentStatusTable.tsx — Agent status grid
        MessagesPanel.tsx  — Live messages feed
        ReportPanel.tsx    — Markdown report viewer (rehype-sanitize enabled, no raw HTML)
        StatsBar.tsx       — Statistics footer
        ErrorBanner.tsx    — Error/failure display with retry actions
      ui/                  — shadcn/ui components
    store/
      index.ts             — Redux store (client-local UI state only)
      slices/
        uiSlice.ts         — Form wizard step, sidebar state, theme
    hooks/
      useAnalysisWebSocket.ts — WebSocket hook with reconnection logic (ephemeral state like reconnection attempt count, buffered messages, and idle timer uses useRef, not Redux or TanStack Query)
    lib/
      api.ts               — TanStack Query API functions (all server state)
```

### Communication Flow

1. User fills config form -> POST `/api/v1/analysis` -> returns `{ run_id }`
2. Frontend connects WebSocket `/ws/analysis/{run_id}` (server validates Origin header)
3. Backend runs `TradingAgentsGraph.propagate()` in background thread via `asyncio.to_thread()`
4. Custom callback handler emits domain events to event bus
5. Async consumer task drains event bus via `asyncio.Queue` and sends JSON over WebSocket (thread-safe bridge using `asyncio.run_coroutine_threadsafe`)
6. Graph stream chunks update agent states/reports -> pushed to WebSocket
7. Frontend receives messages via TanStack Query cache updates from WebSocket hook. The hook uses `queryClient.setQueryData(["analysis", runId, "ws-state"], updater)` to accumulate streaming state. Cache shape: `{ agents: Record<string, AgentStatus>, reports: Record<string, string>, messages: Message[], stats: Stats, progress: Progress }`. This key uses `staleTime: Infinity` and `gcTime` matching the analysis session. On run completion, the WS-state cache is invalidated and replaced by a REST fetch to `GET /api/v1/analysis/{run_id}`
8. On completion, final state sent via WebSocket, REST endpoint also returns full report

### WebSocket Message Protocol

```typescript
// Server -> Client messages (all include monotonic seq:uint64 for reconnection, resets per run)
type WSMessage =
  | { type: "agent_status"; seq: number; agent: string; status: "pending" | "in_progress" | "completed" }
  | { type: "report_chunk"; seq: number; section: string; delta: string }  // append-only delta, frontend concatenates
  | { type: "message"; seq: number; timestamp: string; sender: string; content: string }
  | { type: "tool_call"; seq: number; timestamp: string; tool: string; args: Record<string, any> }
  | { type: "stats"; seq: number; llm_calls: number; tool_calls: number; tokens_in: number; tokens_out: number }
  | { type: "progress"; seq: number; agents_completed: number; agents_total: number; reports_completed: number; reports_total: number }
  | { type: "complete"; seq: number; final_state: Record<string, any>; decision: string }
  | { type: "cancelled"; seq: number }
  | { type: "error"; seq: number; message: string }
  | { type: "snapshot"; seq: number; state: FullAnalysisState }  // full state on reconnect
  | { type: "heartbeat"; seq: number }  // server keepalive every 30s; resets client idle timer

// Client -> Server messages
type WSClientMessage =
  | { type: "replay" }  // request full snapshot on reconnect (server always sends snapshot)
```

**Delta semantics**: `report_chunk` sends only new text appended to a section. Section keys: `analyst_market`, `analyst_social`, `analyst_news`, `analyst_fundamentals`, `research_bull`, `research_bear`, `research_manager`, `trader`, `risk_aggressive`, `risk_conservative`, `risk_neutral`, `portfolio_manager`. Display order matches this list. The frontend concatenates deltas. On reconnect, a `snapshot` message provides full accumulated state — no replay of individual chunks needed. The ring buffer excludes `report_chunk` messages (since `snapshot` reconstructs report state); only status/message/stats events are buffered (capped at 500 per run by count).

---

## API Requirements

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/analysis` | Start new analysis. Body: `AnalysisRequest`. Returns `{ run_id }` |
| GET | `/api/v1/analysis` | List all analyses (active + completed, persisted). Supports `?page=1&limit=20` (default limit 20, max 100) and optional filters `?ticker=X&status=Y&from_date=Z&to_date=W` |
| GET | `/api/v1/analysis/{run_id}` | Get analysis status, results, and current state snapshot |
| GET | `/api/v1/analysis/{run_id}/report` | Download complete report (markdown). Filename: `{ticker}_{date}_report.md` |
| POST | `/api/v1/analysis/{run_id}/cancel` | Cancel a running analysis |
| GET | `/api/v1/config` | Get current config (API keys redacted/masked) |
| PATCH | `/api/v1/config` | Update configuration overrides (partial patch) |
| GET | `/api/v1/models/{provider}` | Get model options for provider |
| GET | `/api/v1/providers` | Get list of available providers with URLs |
| GET | `/api/v1/checkpoints` | Check if checkpoint exists (query: `?ticker=X&date=Y`) |
| DELETE | `/api/v1/checkpoints` | Clear all checkpoints |
| DELETE | `/api/v1/checkpoints/{ticker}` | Clear checkpoints for specific ticker |
| GET | `/api/v1/memory` | Get parsed memory log entries (`?page=1&limit=50`); cached with file-mtime invalidation |
| GET | `/api/v1/health` | Health check, returns `{ status: "ok" }`. Frontend polls on startup (10 attempts, 2s interval) before rendering; shows "Backend unavailable" full-page error with manual retry button on failure |

### WebSocket Endpoint

| Path | Description |
|------|-------------|
| `/ws/analysis/{run_id}` | Real-time analysis updates stream |

### Request/Response Schemas

```python
class AnalysisRequest(BaseModel):
    ticker: str  # validated: ^[A-Z0-9.\-^]{1,15}$
    analysis_date: str  # YYYY-MM-DD, not in future; no minimum date enforced (data vendor returns error for unavailable dates, surfaced to user)
    analysts: list[str]  # validated against ["market", "social", "news", "fundamentals"]
    research_depth: int  # validated: 1, 3, or 5
    llm_provider: str  # validated against provider enum
    backend_url: str | None = None  # validated: http/https only, blocks private IPs except localhost
    quick_think_llm: str  # validated: ^[a-zA-Z0-9._:/-]{1,100}$
    deep_think_llm: str  # same validation
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    output_language: str = "English"  # validated: known preset or custom ^[A-Z][a-z]+([\s\-][A-Z][a-z]+)*$ max 30 chars
    checkpoint: bool = False
    data_vendors: dict[str, str] | None = None  # keys: known categories only, values: "yfinance"|"alpha_vantage"

class AnalysisCreateResponse(BaseModel):
    run_id: str  # UUID4
    status: str  # "running"

class AnalysisResponse(BaseModel):
    run_id: str  # UUID4
    status: str  # "running", "completed", "failed", "cancelled"
    ticker: str
    analysis_date: str
    started_at: str
    completed_at: str | None
    decision: str | None
    error: str | None  # failure reason if status == "failed"
    config: dict  # API keys redacted

class AnalysisListItem(BaseModel):
    run_id: str
    ticker: str
    analysis_date: str
    status: str
    decision: str | None
    error: str | None
    started_at: str
    completed_at: str | None

class AnalysisListResponse(BaseModel):
    items: list[AnalysisListItem]
    total: int
    page: int
    limit: int

class ConfigResponse(BaseModel):
    defaults: dict  # API key values masked as "***"
    overrides: dict  # API key values masked as "***"
    resolved: dict  # API key values masked as "***"

class ConfigUpdateRequest(BaseModel):
    """Partial patch — only allowlisted keys accepted, unknown keys rejected."""
    llm_provider: str | None = None  # validated against provider enum
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None
    backend_url: str | None = None  # same SSRF validation as AnalysisRequest
    output_language: str | None = None
    data_vendors: dict[str, str] | None = None  # same validation as AnalysisRequest
    # Path-based keys (results_dir, data_cache_dir, memory_log_path) are NOT settable via API

class MemoryEntry(BaseModel):
    date: str
    ticker: str
    decision: str
    status: str  # "pending" or "resolved"
    content: str
    reflection: str | None
    returns: dict | None

class MemoryListResponse(BaseModel):
    items: list[MemoryEntry]
    total: int
    page: int
    limit: int

class CheckpointResponse(BaseModel):
    exists: bool
    created_at: str | None
```

---

## UI/UX Requirements

### Pages

1. **Home/Dashboard** (`/`) — Overview with active analyses, recent history, quick-start button
2. **New Analysis** (`/analysis/new`) — Multi-step configuration form with validation
3. **Analysis Dashboard** (`/analysis/:runId`) — Real-time monitoring during run, report view after completion
4. **History** (`/history`) — Table of past analyses with filtering
5. **Configuration** (`/config`) — View/edit default settings
6. **Memory Log** (`/memory`) — Parsed memory log entries

### Design System

- **shadcn/ui** for all base components (Button, Input, Select, Checkbox, Card, Table, Tabs, Dialog, Sheet, Badge, Progress, Skeleton)
- **Magic UI** for enhanced components (animated cards, number tickers for stats, shimmer effects for loading states)
- Dark mode default (trading app aesthetic)
- Monospace font for data/numbers

### Analysis Dashboard Layout

```
+----------------------------------------------------------+
| Header: Ticker | Date | Provider | Status     [Stop btn] |
+----------------------------------------------------------+
| Agent Status Grid          | Current Report Panel        |
| (grouped by team,          | (markdown rendered,         |
|  color-coded badges)       |  auto-scrolling)            |
|                            |                             |
+----------------------------+-----------------------------+
| Messages Feed              | Stats Panel                 |
| (timestamped, scrollable,  | (LLM calls, Tool calls,    |
|  auto-scroll to bottom)    |  Tokens, Elapsed, Progress) |
+----------------------------+-----------------------------+
```

---

## Backend Requirements

### FastAPI Application

- Bind to `127.0.0.1:8000` (localhost only, no external access)
- CORS: explicit `allow_origins` set to frontend origin via `WEB_CORS_ORIGIN` env var (default `http://localhost:5173`), never wildcard. Startup rejects `*` as value and validates well-formed single origin (scheme+host+optional port)
- Lifespan handler for cleanup of running analyses on shutdown
- Background task execution via `asyncio.to_thread()` for graph propagation
- Hard cap of 3 concurrent analyses; return HTTP 429 when exceeded. An `asyncio.Lock` guards the check-and-insert to prevent race conditions
- WebSocket origin validation: reject connections from non-allowed origins

### Analysis Service

- Active runs in `dict[str, AnalysisRun]` (in-memory for running analyses). All mutations (insert, status update, removal) go through a single `asyncio.Lock`. Background threads use `run_coroutine_threadsafe` to mutate from the event loop thread only
- Completed runs persisted to SQLite database (`~/.tradingagents/cache/web_runs.db`) with WAL mode (`PRAGMA journal_mode=WAL`)
- History queries served directly from SQLite (not preloaded into memory) using existing indexes
- On shutdown, lifespan handler iterates active in-memory runs, sets status to "failed" with error "Server shutdown", persists each to SQLite, then closes WebSocket connections with code 1001
- Each run: config, graph instance, status, results, error info, connected WebSocket clients
- Stream processing mirrors `cli/main.py` lines 965-1153: extract reports, debate states, agent statuses from each chunk. Implementation should extract parsing logic into `backend/stream_parser.py` (web-backend-local module, not placed in `tradingagents/` core library to avoid coupling web concerns into the pip-installable package)
- Signal processing via `graph.process_signal()` for final decision extraction
- Cancellation: set flag checked at each graph node boundary
- Per-analysis wall-clock timeout: 30 minutes default (configurable). On timeout, auto-cancels via the existing cancellation flag and marks run as failed with `error='Analysis timed out after 30 minutes'`
- On run completion/cancellation/timeout, release `TradingAgentsGraph` instance and tool/LLM references to free memory; retain only lightweight result data
- `research_depth` mapping: value N sets both `max_debate_rounds` and `max_risk_discuss_rounds` to N
- State machine: `running` -> `completed | failed | cancelled` (terminal states are final). UPDATE queries include `WHERE status = 'running'` to enforce valid transitions
- Cancel idempotency: if run is already terminal, return 200 with current status (no-op); if run_id not found, return 404
- Individual LLM/tool calls MUST have 5-minute HTTP timeouts (mandatory, not optional) so the cancellation flag is checked at reasonable intervals. Python threads cannot be forcibly killed; the timeout is cooperative. When a run is marked failed due to timeout, its concurrency slot is released immediately regardless of whether the background thread has returned. Cap zombie threads (past-timeout, still running) at 3; refuse new analyses if zombie count exceeds cap

### Event Bus (Thread-Safe Bridge)

Decoupled architecture for thread safety:
- Callback handler (runs in background thread) emits domain events to an `asyncio.Queue` via `asyncio.run_coroutine_threadsafe(queue.put(event), loop)`
- Async consumer task drains queue and broadcasts to WebSocket subscribers
- Separate subscribers for: WebSocket push, stats aggregation, logging
- Ring buffer of last 500 messages per run for replay on reconnect. Buffer discarded immediately when run reaches terminal state (SQLite has persisted data for any subsequent reconnect)

### Custom Callback Handler

Emits domain events (does NOT directly touch WebSocket):
- `on_llm_start` -> message event
- `on_llm_end` -> stats update event
- `on_tool_start` -> tool_call event
- `on_tool_end` -> message event

### WebSocket Manager

- Track connections per `run_id`
- Validate Origin header on upgrade
- Multiple clients can watch same analysis
- Auto-cleanup on disconnect
- Heartbeat/ping to detect stale connections
- On client `replay` message: send a `snapshot` message with full current state (report content + agent statuses + stats + progress). Server does NOT broadcast live events to a newly connected client until after receiving `replay` and sending `snapshot`. Ring buffer of 500 non-chunk events retained for diagnostics but not used for replay
- WebSocket server enables `permessage-deflate` extension for compression (reduces snapshot and report payload sizes)
- Heartbeat: server sends application-level `{ type: "heartbeat", seq: N }` every 30s (browser JS cannot observe native ping/pong frames). Server also sends native ping frames and disconnects after 90s without pong. Frontend uses a client-side idle timer: if no message of any kind (including heartbeat) received in 45s, trigger reconnection logic
- Run IDs are UUID4 (cryptographically random)

### Database (SQLite)

Schema:

```sql
-- Applied on first startup; schema_version tracked via PRAGMA user_version
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed', 'cancelled')),
    decision TEXT,
    error TEXT,
    config TEXT NOT NULL CHECK(json_valid(config)),  -- JSON, API keys redacted before storage
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS report_sections (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (run_id, section)
);

CREATE INDEX IF NOT EXISTS idx_runs_ticker_date ON analysis_runs(ticker, analysis_date);
CREATE INDEX IF NOT EXISTS idx_runs_started ON analysis_runs(started_at DESC);
```

Lifecycle:
- A row with `status='running'` is inserted into `analysis_runs` at analysis start (not just on completion), so crashes leave a record
- On startup, detect orphan rows with `status='running'` and mark them `status='failed'` with `error='Server crash recovery'`
- Report content stored in `report_sections` (separate from runs table to keep history list queries fast)

Migration strategy:
- `PRAGMA user_version` tracks schema version (integer, starting at 1)
- On startup, app reads `user_version` and applies pending migrations from a numbered list in code
- Each migration is a transaction; failure rolls back that migration, logs the error (migration number + description) to stderr, and exits with code 1. The health endpoint will not be available; frontend shows "Backend unavailable"

### Shared Validation Rules

These rules apply wherever referenced in `AnalysisRequest`, `ConfigUpdateRequest`, and SEC requirements:
- **ticker_regex**: `^[A-Z0-9.\-^]{1,15}$`
- **model_id_regex**: `^[a-zA-Z0-9._:/-]{1,100}$`
- **provider_enum**: `openai | google | anthropic | xai | deepseek | qwen | glm | openrouter | azure | ollama`
- **backend_url**: http/https only; resolve hostname and pin the resolved IP for connection (no second DNS lookup). Check resolved IP against private ranges (blocks RFC 1918, link-local `169.254.0.0/16`, CGN `100.64.0.0/10`, IPv6 loopback `::1`, non-standard representations). Also block requests targeting `127.0.0.1:{WEB_PORT}` (self-request prevention). Allows `127.0.0.1` and `localhost` on non-self ports only. No redirect following
- **output_language**: known preset or custom capped at 30 chars matching `^[A-Z][a-z]+([\s\-][A-Z][a-z]+)*$` (proper noun language names only, e.g., "Brazilian Portuguese"). Custom values interpolated into prompts via structured template (JSON-encoded)
- **data_vendors**: keys must be known categories (`core_stock_apis`, `technical_indicators`, `fundamental_data`, `news_data`), values must be `"yfinance"` or `"alpha_vantage"`

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WEB_CORS_ORIGIN` | No | `http://localhost:5173` | Allowed CORS origin for frontend |
| `WEB_HOST` | No | `127.0.0.1` | Backend bind address. Hardcoded to `127.0.0.1`; non-loopback binding not supported (no auth exists) |
| `WEB_PORT` | No | `8000` | Backend bind port |
| `TRADINGAGENTS_LLM_PROVIDER` | No | `openai` | Default LLM provider |
| `TRADINGAGENTS_BACKEND_URL` | No | None | Custom LLM endpoint/proxy URL |
| `TRADINGAGENTS_DEEP_THINK_LLM` | No | `gpt-5.4` | Default deep-thinking model |
| `TRADINGAGENTS_QUICK_THINK_LLM` | No | `gpt-5.4-mini` | Default quick-thinking model |
| `*_API_KEY` | Per provider | None | Provider API keys (validated before analysis start; 422 if missing) |

### Build and Serving

- Frontend build: `npm run build` produces static assets in `frontend/dist/`
- Production: FastAPI mounts `frontend/dist/` via `StaticFiles` at `/` (SPA fallback to `index.html`)
- Development: Vite dev server on port 5173, API requests proxied to FastAPI on port 8000
- Frontend build env var: `VITE_API_BASE_URL` (default `http://localhost:8000`) for API endpoint

### Security Requirements
- **SEC-001**: Server binds to `127.0.0.1` only; not accessible from network
- **SEC-002**: CORS `allow_origins` set to explicit frontend origin, never `*`
- **SEC-003**: WebSocket Origin header validated before accepting upgrade
- **SEC-004**: All API key values masked in config endpoint responses (`***`)
- **SEC-005**: `backend_url` validated: http/https only, blocks private IPs except localhost
- **SEC-006**: Ticker validated server-side against `^[A-Z0-9.\-^]{1,15}$`
- **SEC-007**: `llm_provider` validated against known enum
- **SEC-008**: Markdown rendering uses `rehype-sanitize`; no raw HTML, no `dangerouslySetInnerHTML`
- **SEC-009**: Memory log path hardcoded server-side; no user input in file path construction
- **SEC-010**: Run IDs are UUID4 (cryptographically random)
- **SEC-011**: Hard cap on concurrent analyses (3) to prevent resource exhaustion
- **SEC-012**: WebSocket inbound frame max size 4KB; client message rate limit 10/second per connection; disconnect on exceed
- **SEC-013**: `output_language` validated server-side: known preset or custom capped at 30 chars, `^[A-Z][a-z]+([\s\-][A-Z][a-z]+)*$`
- **SEC-014**: `data_vendors` keys validated against known categories, values against `["yfinance", "alpha_vantage"]`
- **SEC-015**: `PATCH /api/v1/config` allowlisted keys only; path-based keys never settable via API
- **SEC-016**: Report download `Content-Disposition` filename quoted and sanitized
- **SEC-017**: All SQLite queries use parameterized statements (`?` placeholders); no string interpolation of user-supplied values
- **SEC-018**: Error messages sent to clients are generic user-facing strings; internal details (tracebacks, file paths) logged server-side only with correlation ID
- **SEC-019**: Content-Security-Policy header on all HTML responses: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://localhost:*; img-src 'self' data:; frame-src 'none'`

---

## Testing Requirements

### Backend Unit Tests

- Analysis service: config building, run lifecycle, cancellation flag, status transitions, concurrency cap enforcement (rejects 4th run, race condition safety), analysis timeout fires and marks run failed
- WebSocket manager: connect, disconnect, broadcast, origin validation, heartbeat timeout
- Event bus: queue put/drain, thread-to-async bridging via `run_coroutine_threadsafe`, ring buffer overflow, replay from seq, report_chunk exclusion from buffer
- Memory log parser: empty file, file not found (returns empty list), malformed entries skipped, missing reflection/returns fields, large file
- Callback handler: event formatting for each event type
- Persistence layer: store run at start (status=running), update on completion, load on startup, orphan recovery (running→failed), WAL mode, busy_timeout, concurrent writes, corrupt DB handling, schema migration (multi-step sequences, partial failure rollback, no-op for current schema, unknown higher version detection)
- Config service: secret redaction (API keys masked), override merging
- Backend URL validator (unit): scheme enforcement, private IP detection (IPv4-mapped IPv6, hex notation, octal notation, DNS-resolving-to-private), localhost allowlist with port check, percent-encoded bypasses, DNS pinning mechanism

### Backend Integration Tests

- REST API endpoints (FastAPI TestClient): all CRUD operations, validation error responses (400), 429 on 4th concurrent analysis
- WebSocket flow: mock graph execution, message delivery, cancel mid-run
- Concurrent analysis: 3 runs have isolated WS streams, cancellation of one doesn't affect others
- WebSocket reconnection: disconnect mid-analysis then reconnect — verify snapshot contains accumulated state and live events resume
- WebSocket reconnect after completion: verify snapshot reflects terminal state from SQLite
- Multiple rapid disconnects: no duplicate messages or state corruption
- Graceful shutdown: active analyses marked failed, WS connections closed with 1001
- Analysis timeout: run exceeding 30min auto-cancelled, status=failed, WS clients receive error event
- Timeout concurrency slot release: start 3 analyses, let one timeout, verify 4th analysis is accepted while timed-out thread still alive
- Zombie thread cap: start 3 analyses, let all 3 timeout (creating 3 zombies), verify 4th analysis rejected due to zombie cap
- Zombie recovery: let a zombie thread complete, verify zombie count decrements and new analyses accepted again
- Orphan recovery integration: seed DB with status=running row, start server, verify history returns it as failed with crash recovery error
- WS rate limiting: send 11 messages in 1 second, verify server disconnects client

### Backend Security Tests

- CORS rejection for unknown origins
- WebSocket upgrade rejected for invalid Origin header
- `backend_url` blocks `http://192.168.x.x`, `http://10.x.x.x`, `http://172.16.x.x`, `http://[::1]`, `http://[::ffff:10.0.0.1]`, `http://0x7f000001`; allows `http://localhost:4141`
- Config endpoint masks all `*_API_KEY` values
- Ticker regex rejects `../etc/passwd`, `; rm -rf`, empty string
- Provider enum rejects arbitrary strings
- PATCH /api/v1/config with unknown keys returns 422 (SEC-015)
- Report download filename with special chars (`../../evil.md`, `ticker\ninjection`) produces safe Content-Disposition (SEC-016)
- Internal error (e.g., corrupt DB) returns generic message + correlation ID, no traceback or file path (SEC-018)
- `backend_url` blocks self-request (`http://127.0.0.1:{WEB_PORT}`)
- CORS startup rejects `WEB_CORS_ORIGIN=*`
- Custom model ID regex rejects invalid chars
- output_language custom rejects strings exceeding 30 chars or not matching proper noun pattern
- WebSocket inbound frame exceeding 4KB is rejected
- backend_url with DNS-rebinding-style hostname blocked via IP pinning
- WEB_HOST override to non-loopback is rejected (hardcoded to 127.0.0.1)
- CSP header present on served HTML responses (SEC-019)

### Frontend Component Tests

- ConfigForm: validate-on-blur for ticker (empty, lowercase normalization, invalid chars), future date rejected, zero analysts error, custom model ID invalid chars, backend_url with ftp:// rejected, wizard step gating
- AgentStatusTable: status rendering for all states, grouped by team, responsive collapse
- ReportPanel: sanitized markdown rendering (rehype-sanitize blocks `<script>`, `<iframe>`), section-independent memoized rendering
- MessagesPanel: auto-scroll at bottom, pause on scroll-up, "Jump to latest" button
- ErrorBanner: displays on error, focus received, retry/reconfigure actions
- StatsBar: number formatting, elapsed time ticking
- Empty states: History, Memory, Home dashboard
- ReconnectionIndicator: renders with attempt count, disappears on successful reconnect

### Frontend Hook Tests

- useAnalysisWebSocket: message batching (100ms flush), exponential backoff timing (1s, 2s, 4s), max 10 attempts then "Connection lost", `replay` message sent on reconnect, `snapshot` replaces cache atomically, snapshot with missing/invalid fields rejected (triggers reconnection rather than corrupting cache), heartbeat resets idle timer, 45s idle timer triggers reconnection (fake timers), WS cleanup on unmount, no WS for completed analyses, malformed JSON ignored without crash, unknown message type logged and skipped, missing required fields do not corrupt state, messages arriving after replay but before snapshot are handled (defense-in-depth: filtered by seq if any arrive despite server-side guarantee)

### Frontend Store Tests

- uiSlice: wizard step transitions, sidebar toggle, theme

### E2E Tests (Playwright)

- Full analysis flow: fill form -> submit -> WS dashboard shows progress -> completion -> report viewable and downloadable
- Cancel mid-run: stop button -> cancelled state -> partial results visible
- Reconnection during active analysis: simulate disconnect -> reconnecting indicator -> snapshot reconciliation
- Error flow: analysis fails -> error banner -> retry action works
- History page: list with pagination controls, click navigates to report
- Checkpoint resume: configure with existing checkpoint -> resume analysis
- Memory log page: renders parsed entries with status indicators
- Concurrent analyses: two simultaneous runs show independent dashboards
- Configuration management: edit provider and backend_url on config page, verify changes persist after reload and apply to next analysis
- 429 rejection: submit when 3 analyses running, verify inline form error with "Maximum concurrent" text
- Crash-recovered run: navigate to a crash-recovered analysis, verify error state shown (not empty report)
- Retry flow: click "Retry" on a failed run, verify form pre-populated with original config values
- Graceful shutdown: start analysis, trigger server shutdown, verify WS closes with 1001, verify restarted server shows run as failed with shutdown error
- Analysis timeout: start analysis with short configurable timeout, verify dashboard transitions to failed state with timeout error message

### Performance Tests

- WebSocket latency: emit timestamped event from callback -> measure receipt at WS client -> assert < 500ms under active analysis load
- Concurrent throughput: 3 analyses each streaming 50 msgs/sec maintains <500ms latency
- MessagesPanel rendering: 500 messages without frame budget exceeded
- No memory growth over 30-min WebSocket session

---

## Acceptance Criteria

### AC-001: Configuration Form

- User can fill all 8 CLI-equivalent steps in a web form
- Form validates: non-empty ticker, valid date, at least 1 analyst, required provider fields
- Model dropdowns populate based on selected provider
- Custom model ID input appears when "Custom" selected
- Form submits and receives run_id

### AC-002: Real-Time Dashboard

- Agent status table shows all agents grouped by team with live status updates
- Messages panel shows timestamped messages, auto-scrolls
- Report panel renders sanitized markdown content as it arrives
- Stats bar shows LLM calls, tool calls, tokens, elapsed time
- All updates arrive via WebSocket within 500ms
- Error banner displays on analysis failure with retry/reconfigure actions
- "Reconnecting..." indicator shown during WebSocket disconnection
- Stop button cancels a running analysis

### AC-003: Report Viewing

- Complete report displays all sections with markdown rendering after analysis completes
- Report downloadable as markdown file named `{ticker}_{date}_report.md`
- Report sections collapsible/expandable

### AC-004: Analysis History

- List shows all past analyses with ticker, date, status, decision
- Clicking an entry shows the full report

### AC-005: Configuration Management

- Current config displayed with all options
- User can modify provider, models, backend URL, data vendors
- Changes persist and apply to next analysis

### AC-006: Memory Log

- Memory entries displayed with date, ticker, decision, status
- Resolved entries show reflection and returns

### AC-007: Checkpoint Management

- Checkpoint existence shown when configuring analysis (ticker+date)
- User can clear all checkpoints or per-ticker from UI
- Checkpoint toggle in analysis form works correctly

### AC-008: Graceful Shutdown

- On server shutdown, active analyses marked "failed" in SQLite
- WebSocket connections closed with 1001 code
- No orphan threads remain

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LangGraph streaming not compatible with async WebSocket push | Low | High | Use `asyncio.to_thread()` + queue-based bridge |
| Large report content causes WebSocket frame issues | Low | Medium | Chunk large updates, use compression |
| Multiple concurrent analyses exhaust LLM rate limits | Medium | Medium | Document limitation, queue analyses if needed |

---

## Assumptions

- **A-001**: The backend FastAPI server and frontend dev server will run on the same machine as TradingAgents
- **A-002**: Node.js 20+ and npm/pnpm are available on the host for frontend build
- **A-003**: The existing `TradingAgentsGraph` API is stable and won't change during implementation
- **A-004**: WebSocket connections are reliable on localhost (no proxy/firewall issues)

---

## Traceability Matrix

| Requirement | Tasks | Tests | Acceptance Criteria |
|-------------|-------|-------|-------------------|
| FR-001 | Backend config endpoint + Frontend form | ConfigForm tests, API tests | AC-001 |
| FR-002 | Analysis service + WebSocket handler | Service tests, WS integration | AC-002 |
| FR-003 | Dashboard components + WS hook | Component tests, hook tests | AC-002 |
| FR-004 | Report endpoint + ReportPanel | ReportPanel tests, API tests | AC-003 |
| FR-005 | Analysis list endpoint + History page | API tests, component tests | AC-004 |
| FR-006 | Config service + Config page | Service tests, component tests | AC-005 |
| FR-007 | Memory service + Memory page | Parser tests, component tests | AC-006 |
| FR-008 | Cancel endpoint + Stop button | Cancel API test, WS cancelled msg | AC-002 |
| FR-009 | Checkpoint endpoints + UI | Checkpoint API tests | AC-007 |
| FR-010 | Error handling + ErrorBanner | Error flow tests | AC-002 |
| FR-011 | WS reconnection hook | Hook reconnection tests | AC-002 |
| SEC-001-019 | Security validation across all layers | Security-specific tests | All |
