# AI Manager Dashboard Enhancement — Requirements

## Feature Goal
Transform the AI Account Manager tab from a monitoring dashboard into a **personal account manager experience** that shows all LLM calls, capabilities status, market insights, and proactive analysis — making the AI's thinking transparent and actionable.

---

## Functional Requirements

### FR-1xx: LLM Call Visibility

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-101 | The backend shall log every LLM call to a new `ai_manager_llm_calls` table capturing: account_id, timestamp, system_prompt_hash, context_prompt_length, response_length, latency_ms, input_tokens, output_tokens, attempt_number, success/failure, model identifier | Must | Backend-R1 |
| FR-102 | The backend shall expose `GET /api/ai-manager/{account_id}/llm-calls` with cursor-based pagination, time-range filter, and success/failure filter | Must | Backend-R3 |
| FR-103 | The UI shall display a real-time feed of LLM calls per account, with most recent expanded and older collapsed | Must | UX-R2 |
| FR-104 | The UI shall show a "thinking" indicator when an LLM call is in-flight, indicating account and decision type | Must | UX-R3 |
| FR-105 | The backend shall emit WebSocket event `ai_manager.llm_call_complete` after each LLM invocation with latency_ms, token_estimate, action, retry status | Must | Backend-R5 |
| FR-106 | The system shall calculate and display rolling LLM cost per account (hourly, daily) | Should | UX-R4 |
| FR-107 | The UI shall show per-call details: token counts (in/out), latency, model, truncated prompt/response previews (expandable) | Must | Frontend-R5 |
| FR-108 | The backend shall buffer and batch-insert LLM call logs asynchronously (flush every 5s or 10 records) to avoid decision-path latency | Must | Backend-R17 |
| FR-109 | The backend shall expose `GET /api/ai-manager/{account_id}/decision-graph-trace` returning node path, per-node latency, and intermediate signals for the most recent invocation | Should | Backend-R16 |

### FR-2xx: Capabilities Dashboard

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-201 | The backend shall expose `GET /api/ai-manager/{account_id}/capabilities-status` aggregating health of MTF, correlation, orderbook, regime, memory, sweep detection with per-capability last_updated and status | Must | Backend-R4 |
| FR-202 | The UI shall display all capabilities as a responsive grid of cards with status indicators: active, armed, cooldown, disabled | Must | UX-R5 |
| FR-203 | The backend shall emit WebSocket event `ai_manager.capability_update` when a capability transitions state | Must | Backend-R6 |
| FR-204 | The UI shall show per-capability: last trigger time, trigger count (session), threshold condition for next trigger | Should | UX-R7 |
| FR-205 | The backend shall expose `GET /api/ai-manager/{account_id}/capability-history` with 24h time-series availability data | Could | Backend-R25 |
| FR-206 | The UI shall animate capability state transitions in real-time | Should | UX-R6 |

### FR-3xx: Market Insights & Commentary

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-301 | The backend shall generate market commentary via a lightweight LLM call on configurable interval (default 5 min while monitoring), stored in `ai_manager_commentary` table | Must | Backend-R10 |
| FR-302 | The backend shall emit WebSocket event `ai_manager.market_commentary` when new commentary is generated | Must | Backend-R11 |
| FR-303 | The UI shall present market commentary in a conversational card format with confidence indicator and supporting data points | Must | UX-R10 |
| FR-304 | The backend shall expose `GET /api/ai-manager/{account_id}/market-insights` returning latest commentary plus structured regime, correlation highlights, sweep summary | Must | Backend-R13 |
| FR-305 | The system shall provide per-position AI commentary explaining hold rationale, close triggers, and what's being watched | Should | UX-R11 |
| FR-306 | The UI shall display a "day quality score" (good/neutral/caution/danger) with one-sentence justification | Must | UX-R12 |
| FR-307 | The backend shall expose `GET /api/ai-manager/{account_id}/analysis-context` returning last enrichment state (regime, session, correlation, MTF, orderbook, sweeps) without triggering new analysis | Must | Backend-R7 |

### FR-4xx: Personal Account Manager Experience

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-401 | The UI shall present a proactive "attention needed" section at top, surfacing positions/conditions ranked by urgency | Must | UX-R13 |
| FR-402 | The UI shall default to a summary view (day score, total P&L, attention items, active capability count) with drill-down | Must | UX-R17 |
| FR-403 | The UI shall provide a three-tier layout: top (health + alerts), middle (insights + positions), bottom (logs + analytics) | Should | UX-R19 |
| FR-404 | The system shall stream updates via WebSocket so LLM results, capability changes, and commentary appear within 1 second | Must | UX-R20 |
| FR-405 | The UI shall display "last updated" timestamps per section and heartbeat indicator confirming AI process is alive | Must | UX-R21 |

### FR-5xx: Token Budget & Cost Tracking

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-501 | The backend shall expose detailed token budget endpoint: daily used, daily limit, per-call average, projected exhaustion, breakdown by call type | Should | Backend-R9 |
| FR-502 | The backend shall emit WebSocket event `ai_manager.budget_warning` at 80% and 95% of daily budget | Should | Backend-R18 |
| FR-503 | The commentary LLM calls shall use a dedicated sub-budget capped at 10% of daily token budget | Must | Backend-R10 |

---

## Non-Functional Requirements

### NFR-1xx: Performance

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| NFR-101 | LLM call log retention: 7 days default (configurable), max 10,000 entries per account | Must | Perf-R1 |
| NFR-102 | Cursor-based pagination with default page size 50, no OFFSET queries | Must | Perf-R2 |
| NFR-103 | Commentary generation must be async (not inline with FSM evaluation cycle) | Must | Perf-R9 |
| NFR-104 | WebSocket LLM log events throttled to max one batch per 5 seconds per account | Should | Perf-R5 |
| NFR-105 | Frontend: virtualize LLM call list with react-window, render <16ms regardless of total count | Must | Perf-R7 |
| NFR-106 | Redux store: MAX_LLM_CALLS=200 per account, FIFO eviction | Must | Perf-R8 |
| NFR-107 | Database indexes on (account_id, created_at DESC) for llm_calls and analysis_snapshots | Must | Perf-R6 |
| NFR-108 | Debounce WebSocket updates at 200ms intervals using Redux middleware buffer | Should | Frontend-R12 |
| NFR-109 | Market commentary cached for validity window (min 60s), served from cache to concurrent subscribers | Must | Perf-R4 |
| NFR-110 | Commentary LLM timeout: 10s hard limit, circuit-breaker disables for 5 min after 3 consecutive timeouts | Must | Perf-R12 |
| NFR-111 | Lazy-load analysis detail views (full prompt/response) only on expand | Must | Perf-R14 |

### NFR-2xx: Security

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| NFR-201 | Redact raw system/context prompts from API responses; expose only prompt_hash and prompt_length | Must | Security-R1, Backend-R22 |
| NFR-202 | Apply HTML entity escaping to all AI-generated commentary before rendering | Must | Security-R4 |
| NFR-203 | Enforce per-user rate limits (60 req/min) on all new endpoints | Must | Security-R5 |
| NFR-204 | Validate WebSocket subscriptions: session token must match account_id | Must | Security-R6 |
| NFR-205 | Never log/store/transmit API keys in LLM call records; scan payloads at write time | Must | Security-R8 |
| NFR-206 | LLM call log responses served with Cache-Control: no-store | Should | Security-R12 |
| NFR-207 | Data retention: auto-delete LLM logs older than configurable period (default 90 days) | Should | Security-R7 |
| NFR-208 | Stored LLM responses truncated to 4KB max in primary table | Should | Security-R3 |

### NFR-3xx: Frontend Architecture

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| NFR-301 | Decompose into lazy-loaded sub-panels (each <200 lines): FSMState, LLMCallFeed, CapabilitiesGrid, MarketInsights, ConversationalSection | Must | Frontend-R1 |
| NFR-302 | Code-split each sub-panel behind React.lazy with NeuSkeleton placeholders | Should | Frontend-R10 |
| NFR-303 | Responsive layout: single-column <1024px, two-column 1024-1440px, three-column >1440px | Must | Frontend-R13 |
| NFR-304 | Memoize selector results with createSelector per sub-panel to prevent cross-panel re-renders | Must | Frontend-R16 |
| NFR-305 | Persist user layout preferences to localStorage keyed by account ID | Could | Frontend-R17 |
| NFR-306 | Memory bounds on all new collections matching existing MAX_DECISIONS/MAX_LOGS pattern | Must | Frontend-R18 |
| NFR-307 | Unified status bar at dashboard top showing connection/loading/error per sub-panel | Should | Frontend-R14 |

### NFR-4xx: Backward Compatibility

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| NFR-401 | Existing WebSocket events (state_change, execution) unchanged; new fields optional only | Must | Backend-R19 |
| NFR-402 | All new endpoint responses validated via Pydantic response models | Must | Backend-R21 |
| NFR-403 | Existing AIMonitorPanel functionality preserved (no regressions) | Must | — |

---

## Assumptions (with risk levels)

| # | Assumption | Risk |
|---|-----------|------|
| A1 | The existing token budget (100k/day) can accommodate commentary calls within 10% sub-budget | Low |
| A2 | PostgreSQL is sufficient for LLM call log storage at expected scale (<10k calls/account/day) | Low |
| A3 | The neumorphism design system has sufficient primitives for the new components | Low |
| A4 | WebSocket infrastructure can handle 3-4 additional event types per account | Low |
| A5 | Users have a single browser tab per account (no cross-tab sync needed) | Medium |

---

## Out of Scope (Deferred)

- "Ask your manager" conversational input (future phase — high token cost, complex UX)
- Daily summary generation at market open (requires scheduler, notifications)
- Push browser notifications (requires service worker, permission flow)
- Mobile swipe gestures (existing responsive design sufficient)
- Cross-account aggregate view (per-account only in this phase)
- Capability dependency graph visualization
- "Power user" raw JSON toggle mode
- Table partitioning (simple table + cleanup job sufficient at this scale)
- Enterprise observability/alerting (PagerDuty, p95 histograms)
- Decision graph trace endpoint (developer tooling, not user value)
- Analysis context snapshot persistence (current context API sufficient)
- Dedicated commentary sub-budget accounting (budget is effectively unlimited at 20M/1000-per-call)
- BroadcastChannel cross-tab sync
- Commentary feedback (thumbs up/down)
- Per-account localStorage layout persistence

---

## Key Design Decisions (from Round 3 analysis)

### D1: Prompt Visibility Resolution
**Contradiction**: NFR-201 (redact prompts) vs FR-107 (show previews)
**Resolution**: Show sanitized reasoning text (already truncated to 2000 chars by backend) and structured metadata (token counts, latency, model). Never expose raw system/context prompts. FR-107 reworded to "sanitized response summary" not "truncated prompt."

### D2: Commentary Approach
**Contradiction**: Token budget concerns vs 5-min commentary
**Resolution**: Budget is effectively unlimited (20M tokens, flat 1000/call = 20k calls/day). Commentary at 5-min uses 1.44% of budget. MVP approach: surface existing decision reasoning as commentary formatted for humans. Optional: periodic LLM narrative call for richer summaries (cost: ~$0.72-3.60/day/account in real API cost).

### D3: Evaluation Cycle ID
**Issue**: FR-604 references evaluation_cycle_id which doesn't exist
**Resolution**: Generate UUID at start of each evaluation, thread through graph state, persist with decision and LLM call logs for correlation.

### D4: Atomic Panel Updates
**Issue**: FR-706 is not feasible as specified (React limitation)
**Resolution**: Rewrite to "single-dispatch pattern" — collect all FSM-transition data into one WebSocket message and dispatch once to Redux store.

### D5: Scale Assumptions
Simple PostgreSQL table with (account_id, created_at DESC) index + 90-day cleanup job. No partitioning needed at <10k rows/account/day scale.

---

## Round 2 Additions

### FR-6xx: Integration & State Management

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-601 | The UI shall render insights panels in "no data" state with "Account Sleeping" indicator when FSM is SLEEPING, issuing no fetch requests until transition to MONITORING | Must | Integration-IR1 |
| FR-602 | The capabilities grid shall show "Bypassed" for EMERGENCY urgency events (no LLM involved) | Must | Integration-IR2 |
| FR-603 | The LLM call feed shall suspend appending in PAUSED state, display "Feed Paused" banner, and resume from correct offset on un-pause | Must | Integration-IR3 |
| FR-604 | Each LLM call entry shall be correlated to its decision log entry via shared evaluation_cycle_id; selecting one highlights the other | Should | Integration-IR4 |
| FR-605 | New WebSocket events shall use same reconnection/backoff logic as existing events (no separate connections) | Must | Integration-IR5 |
| FR-606 | 30-second polling fallback shall include new data types via backward-compatible optional fields | Must | Integration-IR6 |
| FR-607 | The LLM call feed shall distinguish FAST/STANDARD/DEEP urgency tiers with tier label, latency budget, and roundtrip count | Must | Integration-IR11 |
| FR-608 | Capabilities grid shall highlight active capability during ANALYZING, reset to idle on return to MONITORING, driven by state_change event | Should | Integration-IR12 |

### FR-7xx: Error States & Edge Cases

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-701 | When commentary generation fails, show last successful content with "stale data" timestamp indicator and manual retry button | Must | Gap-R1 |
| FR-702 | LLM call logs rendered in chronological order by server timestamp regardless of delivery order; deduplicate by call ID | Must | Gap-R2 |
| FR-703 | Display contextual onboarding prompts for accounts with zero positions, zero history, zero LLM calls | Should | Gap-R3 |
| FR-704 | When token budget exhausted: cease non-critical LLM calls, display "budget exhausted" with reset timing, queue pending analyses | Must | Gap-R4 |
| FR-705 | The UI shall detect connectivity loss within 5s, show persistent "connection lost" banner, preserve last-known state, auto-reconnect with exponential backoff | Must | Gap-R12 |
| FR-706 | All panels update atomically within single render cycle on FSM state transition | Should | StateMatrix-R15 |

### FR-8xx: UI State Matrix (Panel behavior per FSM state)

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| FR-801 | LLM Feed: SLEEPING → empty "No LLM activity"; MONITORING → health-check calls with "Listening..."; ANALYZING → full streaming with "thinking" spinner; EXECUTING → frozen with "executing trade" | Must | StateMatrix |
| FR-802 | Capabilities Grid: SLEEPING/PAUSED → disabled/muted; ANALYZING → active capability highlighted with progress; ERROR → red badges on all cards | Must | StateMatrix |
| FR-803 | Market Insights: SLEEPING → stale with "inactive" warning; MONITORING/ANALYZING → live with green badge; PAUSED → frozen with "Paused" overlay | Must | StateMatrix |
| FR-804 | Attention Section: SLEEPING → "Nothing requires attention"; EXECUTING → active trade as top item; ERROR → urgent red card; PAUSED → pause info card with Resume | Must | StateMatrix |

### NFR-5xx: Data Model

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| NFR-501 | New `ai_manager_llm_calls` table partitioned by month with columns: id, account_id, timestamp, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, response_summary, purpose, decision_id, cost_usd | Must | DB-R1 |
| NFR-502 | New `ai_manager_capabilities` table with unique constraint on (account_id, capability_key), status enum (healthy/degraded/failed/disabled) | Must | DB-R3 |
| NFR-503 | New `ai_manager_market_commentary` table with 4KB commentary cap, index on (account_id, generated_at DESC) | Must | DB-R4 |
| NFR-504 | New `ai_manager_analysis_context` table with JSONB snapshots (regime, MTF, correlation, orderbook), 32KB per field cap | Should | DB-R5 |
| NFR-505 | All migrations additive-only: no ALTER existing columns, no DROP, no NOT NULL on existing tables | Must | DB-R6 |
| NFR-506 | Retention: llm_calls 90 days, commentary 7 days, analysis_context 30 days | Must | DB-R7 |
| NFR-507 | Schema added to both sync (persistence.py) and async (async_persistence.py) persistence layers | Must | DB-R12-finding |

### NFR-6xx: Observability

| ID | Requirement | Priority | Source |
|----|-------------|----------|--------|
| NFR-601 | Metric: ai_manager.commentary.generation_failures_total, alert on 20% failure rate in 5 minutes | Should | OBS-1 |
| NFR-602 | Track LLM log table row count and size as gauge metrics, alert on >500MB/day growth | Should | OBS-2 |
| NFR-603 | Histogram: ai_manager.websocket.event_delivery_latency_ms, alert on p95 >500ms | Could | OBS-3 |
| NFR-604 | Per-endpoint error rate counter for dashboard API routes, alert on 5xx >5/min | Should | OBS-5 |
| NFR-605 | Structured LLM call logging with: purpose, model, tokens, latency, circuit_breaker_state | Must | OBS-6 |
| NFR-606 | Commentary staleness gauge: alert when age exceeds 3x evaluation interval | Should | OBS-8 |

---

## Round 3-5 Refinements

### Resolved Gaps

**G1: FR-201 API Response Schema** — The capabilities-status endpoint shall return per capability:
```json
{
  "capability_key": "mtf_analysis",
  "display_name": "Multi-Timeframe Analysis",
  "enabled": true,
  "status": "healthy|degraded|failed|disabled",
  "last_triggered_at": "2026-05-28T10:30:00Z",
  "trigger_count_session": 42,
  "next_trigger_condition": "Next evaluation cycle in 45s",
  "countdown_seconds": 45,
  "armed": false
}
```

**G2: FR-306 Day Quality Score Formula** — Score derived from:
- Regime alignment (trending with positions = positive, volatile against = negative)
- Portfolio P&L trajectory (rising = good, flat = neutral, falling = caution)
- Urgency level distribution (mostly STANDARD = good, frequent FAST = caution, any EMERGENCY = danger)
- Correlation heat (low = good, high = caution)

Mapping: good (score 70-100), neutral (40-69), caution (20-39), danger (0-19). LLM generates the one-sentence justification from analysis context. Score recomputed each evaluation cycle.

**G3: WebSocket Event Payload Schemas**
```
ai_manager.llm_call_complete:
  { account_id, call_id, timestamp, latency_ms, input_tokens, output_tokens, model, 
    action_returned, confidence, reasoning_preview (200 chars), urgency_tier, attempt_number, success }

ai_manager.capability_update:
  { account_id, capability_key, old_status, new_status, timestamp, trigger_reason }

ai_manager.market_commentary:
  { account_id, commentary_id, day_score, day_score_label, summary_text, generated_at, 
    regime, symbols_referenced[] }

ai_manager.llm_started:
  { account_id, call_id, timestamp, urgency_tier, node_name }
```

---

## Acceptance Criteria (Top 5 Requirements)

### AC for FR-101/105: LLM Call Logging + Streaming

| AC | Given | When | Then |
|----|-------|------|------|
| AC-1.1 | AI Manager makes an LLM call in action_generation node | Call completes (success or failure) | A log entry is persisted with: timestamp, model, input/output tokens, latency_ms, success, evaluation_cycle_id |
| AC-1.2 | Client has active WebSocket connection | New LLM call log entry is created | Client receives the entry as a JSON message within 2 seconds |
| AC-1.3 | AI Manager is in ANALYZING state | LLM call begins | Client receives `ai_manager.llm_started` event immediately, UI shows "thinking" indicator |

### AC for FR-201/203: Capabilities Status + Updates

| AC | Given | When | Then |
|----|-------|------|------|
| AC-2.1 | AI Manager has 6 active capabilities | Client calls `GET /capabilities-status` | Response contains all 6 with current state, last_triggered_at, countdown_seconds |
| AC-2.2 | Client connected to WebSocket | Sweep detection triggers | Client receives capability_update event with old_status, new_status, trigger_reason |
| AC-2.3 | Degradation tier increases to 2 | Tier change is applied | Affected capabilities show status=degraded, UI reflects in capabilities grid |

### AC for FR-301/304: Market Insights

| AC | Given | When | Then |
|----|-------|------|------|
| AC-3.1 | AI Manager is MONITORING with positions | 5 minutes since last commentary | New commentary generated from current analysis context (regime, PnL, indicators) |
| AC-3.2 | Client calls `GET /market-insights` | Backend has analysis context | Response includes latest commentary, regime, correlation summary, current positions health |
| AC-3.3 | Commentary generation fails | LLM call times out | Last successful commentary served with `stale: true` flag and retry button shown |

### AC for FR-306: Day Quality Score

| AC | Given | When | Then |
|----|-------|------|------|
| AC-4.1 | Market trending_up, positions aligned, no EMERGENCY events | Score computed | Score is 70-100 ("good"), one-sentence justification references trend alignment |
| AC-4.2 | Frequent FAST urgency, portfolio drawdown >2% | Score computed | Score is 20-39 ("caution"), justification references elevated urgency + drawdown |
| AC-4.3 | Zero positions, SLEEPING state | Score requested | Score returns null with message "No active positions to evaluate" |

### AC for FR-401: Attention Needed Section

| AC | Given | When | Then |
|----|-------|------|------|
| AC-5.1 | Urgency changes from STANDARD to FAST for BTC position | Evaluation cycle completes | Attention item created: "BTC position deteriorating — urgency escalated to FAST" |
| AC-5.2 | Token budget reaches 80% | Budget check runs | Attention item: "Token budget at 80% — AI commentary may reduce frequency" |
| AC-5.3 | FSM is in SLEEPING state | Attention section rendered | Shows "Nothing requires your attention" empty state |

---

## Removed Requirements (from Round 3 YAGNI analysis)

| Removed | Reason |
|---------|--------|
| NFR-501 partitioning | Overkill for <10k rows/account/day |
| NFR-601-604, NFR-606 | Enterprise alerting for personal dashboard |
| FR-205 | 24h time-series history is SRE tooling |
| FR-503 | Sub-budget unnecessary (budget is 20M/20k calls) |
| NFR-504 | Historical JSONB snapshots unnecessary; current context API suffices |
| FR-604 highlight-linking | Defer to v2 (simple label sufficient) |
| FR-706 atomic render | Infeasible; replaced with single-dispatch pattern |
| NFR-305 localStorage | Defer to v2 |
| FR-109 graph trace | Developer tooling, not user value |
| NFR-110 commentary circuit breaker | FR-701 stale+retry is sufficient |
| FR-502 budget push events | Budget gauge visible in UI |
| FR-703 onboarding prompts | Simple empty state message sufficient |
