# Auto-Trade Debug Tracing & Forensics — Design

**Date:** 2026-06-06
**Status:** Approved (design), pending implementation plan
**Author:** Brainstorming session
**Component area:** `backend/services/`, `backend/routers/`, `backend/async_persistence.py`

---

## 1. Problem Statement

A scheduled market scan's auto-trade cycle behaved in a way that was extremely hard to diagnose after the fact. Investigating a single past event ("did account X correctly start a new auto-trade cycle after its prior positions closed mid-scan?") required manually stitching together **seven-plus** data sources by hand:

- `scans` (analysis timing/status)
- `schedule_executions` (a *different* completion timestamp than `scans`)
- the `auto_trade_summaries` JSON blob on the scan row
- `trades` (open/close lifecycle)
- `close_rules` / `close_executions` (why positions closed)
- `closed_pnl_records` (exchange-authoritative closes)
- the **live exchange position API** (the only source of "what the executor actually saw")

### Root causes of the diagnostic pain

1. **Auto-trade decisions are ephemeral.** Nothing durably records *why* each account traded, skipped, or was rescued. The only persisted artifact is `auto_trade_summaries`, which:
   - is **overwritten** on every re-run (manual "Auto Trade" button re-execution destroys the scheduled run's record), and
   - contains only final counts + `stopped_reason`, not the gate-by-gate decision path or per-symbol reasons.

2. **The live exchange position/wallet state at each decision gate is never persisted.** The executor's skip/trade decisions hinge on what `get_positions()` returned at that instant, but that snapshot vanishes. The `trades` table is *not* a substitute (it can lag/diverge from the exchange).

3. **Two distinct "completed" timestamps** (`scans.completed_at` = analysis done; `schedule_executions.completed_at` = auto-trade phase done) are not surfaced together, hiding the multi-minute auto-trade execution window where rescues happen.

4. **Per-symbol filter decisions are invisible.** Why a specific signal was skipped (min_score, max_signal_age, sector cap, price drift, already-held, etc.) is never recorded.

### Architectural facts established during investigation

- The **live auto-trade path is entirely `AutoTradeExecutor`**, driven by `ScannerService` (scheduled and manual). The `TradingCycleEngine` / `trading_cycles` / `cycle_trades` subsystem is **dormant (0 rows in production)** and is NOT involved in scheduled auto-trade. The debug system targets the `AutoTradeExecutor` path.
- Database schema is at **migration version 37**; migrations are an append-only `_MIGRATIONS` list in `backend/async_persistence.py`.
- Routers register under `/api/v1` in `backend/main.py`; services are wired onto `app.state` in the lifespan.
- Existing observability (`backend/observability.py`) already provides structured JSON logging + correlation IDs + an in-process metrics store to build on.

---

## 2. Goals & Non-Goals

### Goals
- **Always-on** durable capture of every auto-trade execution's full decision trace (scheduled + manual), so **any past run** is reconstructable after the fact.
- Capture **all levels**: run → account → lifecycle events → per-symbol decisions → exchange snapshots.
- Preserve **re-run history** (new immutable run per execution; never overwrite).
- Provide **end-to-end debug API routes** (one deep aggregate tree + focused sub-routes) that return everything previously dug for manually, including a plain-English narrative per account.
- **Configurable retention** (default 60 days, auto-delete older, user-adjustable at runtime).
- **Strict performance safety:** the trading hot path must NEVER be slowed or blocked by tracing. This is a money-handling path; latency could cause financial loss.

### Non-Goals
- No frontend/debug-viewer UI in this scope (API + DB only). May be added later.
- No changes to the dormant `TradingCycleEngine` subsystem.
- No replacement of existing `auto_trade_summaries` (it stays; the new system is additive).
- Not a general APM/tracing framework — scoped to the auto-trade decision path.

---

## 3. Architecture Overview

One new durable anchor concept: the **auto-trade debug run**. Every time the executor runs against a scan (scheduled or manual), it opens a new immutable `debug_run` and writes a complete decision trace beneath it. Re-runs create *new* runs instead of overwriting — history is preserved.

```
ScannerService ──► AutoTradeExecutor ──► DebugTraceRecorder
                                              │  (sync emit: flag-check + dict + append to bounded buffer)
                                              │  fail-open, NO await, NO I/O on hot path
                                              ▼
                                     in-memory bounded buffer (deque, drop-on-pressure)
                                              │
                                  background drainer task (every few seconds)
                                              │  bulk COPY on a DEDICATED connection
                                              ▼
                                    debug_* tables (Postgres, v38 migration)
                                              ▲
              /api/v1/debug/*  ───────────────┘   (read side: deep tree + sub-routes, paginated)
```

### Components

- **`DebugTraceRecorder`** (`backend/services/debug_trace_recorder.py`): new service injected into `ScannerService` and `AutoTradeExecutor`. Exposes synchronous `emit(...)`-style methods. Owns the in-memory buffer, the kill-switch flag, the cached config, and the background drainer task. Started/stopped in the app lifespan like other schedulers.
- **`debug_*` tables**: six new tables (Section 5).
- **`debug_router`** (`backend/routers/debug.py`): registered at `/api/v1/debug` (Section 6).

### Why this structure
- Reuses existing patterns: append-only `_MIGRATIONS`, `app.state` service injection, `/api/v1` registration, lifespan-managed background tasks (mirrors `CloseRuleEvaluator` and the snapshot scheduler), and the existing structured-logging/correlation-id infra.
- Keeps the write side (instrumentation) and read side (API) decoupled from each other and from the trade path.

---

## 4. Performance Safety Model (Hard Requirement)

**Golden rule: the trading path must never wait on the debug system.** Capture and persistence are fully decoupled. This section is a binding constraint, not a guideline.

1. **Hot path does zero I/O.** The executor never `await`s a DB write for tracing. Each `emit(...)` is a *synchronous* in-memory op: check the kill-switch flag, build a small dict, append to an in-memory buffer. Microseconds; no network; no `await`. Critically, it never yields the executor's `asyncio.Lock` mid-capture and never extends the critical section.

2. **Bounded buffer with drop-on-pressure.** The buffer is a capped `collections.deque(maxlen=N)`. If the drainer falls behind (slow DB / outage), `emit` **drops the event and increments `dropped_count`** rather than blocking. Trading is never backpressured by debug storage. `dropped_count` is persisted on the run record (honest coverage — no silent gaps).

3. **Decoupled background drainer.** A separate async task (lifespan-managed) wakes on a short interval, drains the buffer, and bulk-inserts via Postgres `COPY` (asyncpg `copy_records_to_table`) on a **dedicated connection**, so debug writes never compete with trade-placement queries for the main pool.

4. **Instant kill-switch.** A single in-memory boolean is checked first in every `emit`. Tracing can be disabled instantly via `PUT /api/v1/debug/config` (no redeploy). When off, `emit` returns after one boolean check.

5. **Off-path serialization.** JSON serialization of position/wallet payloads happens in the drainer, not the trade path. The hot path only references data the executor *already fetched* — no extra exchange API calls are ever made for tracing.

6. **Total isolation of failures.** Every recorder entry point is wrapped so an exception logs a warning and returns — it can never propagate into trading. Worst case under full DB failure: some debug data is lost; **trading runs at full speed, unaffected.**

### Performance proof obligation (enforced in tests)
- A benchmark asserts batch-execution timing is statistically unchanged with tracing ON vs OFF.
- `emit` overhead asserted sub-microsecond per event (enabled), and effectively free when disabled.
- A drop-on-pressure test asserts trading completes normally when the drainer is artificially stalled.

---

## 5. Data Model

Six new tables, added via a single append-only migration (v37 → **v38**) in `backend/async_persistence.py`. All child tables `REFERENCES debug_runs(id) ON DELETE CASCADE`, so retention cleanup is a single delete on `debug_runs`.

> Column types follow existing conventions (`BIGSERIAL`/`SERIAL` PKs, `TIMESTAMPTZ` for new timestamps, `JSONB` for structured payloads, `TEXT` for ids/labels). Account ids and scan ids are `TEXT` to match existing tables.

### 5.1 `debug_runs` — immutable anchor (one row per executor execution)
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `scan_id` | TEXT NOT NULL | not a strict FK (scans may be pruned independently); indexed |
| `trigger_source` | TEXT | `scheduled` / `manual` / `run_now` |
| `schedule_id` | TEXT NULL | |
| `schedule_execution_id` | BIGINT NULL | links to `schedule_executions.id` |
| `scan_started_at` | TIMESTAMPTZ NULL | analysis start |
| `scan_completed_at` | TIMESTAMPTZ NULL | analysis done (`scans.completed_at`) |
| `exec_started_at` | TIMESTAMPTZ NULL | auto-trade phase start |
| `exec_completed_at` | TIMESTAMPTZ NULL | auto-trade phase done (matches `schedule_executions.completed_at`) |
| `config_snapshot` | JSONB | scan-level config (sanitized: no API keys) |
| `total_symbols` / `completed_symbols` / `failed_symbols` | INT | |
| `num_accounts` | INT | |
| `phase_reached` | TEXT | last phase entered (`init_balances`/`batch`/`fill`/`post_scan_recheck`/`cleanup`/`finalized`) |
| `dropped_event_count` | INT DEFAULT 0 | buffer drops during this run (coverage honesty) |
| `created_at` | TIMESTAMPTZ DEFAULT now() | |

Indexes: `(scan_id)`, `(created_at DESC)`, `(schedule_id, created_at DESC)`.

### 5.2 `debug_account_traces` — one row per account per run (the verdict)
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT FK→debug_runs ON DELETE CASCADE | |
| `account_id` | TEXT | indexed |
| `account_label` | TEXT | resolved name (e.g. "Dad - Demo") — no more UUID hunting |
| `execution_mode` | TEXT | `immediate` / `batch` |
| `final_stopped_reason` | TEXT NULL | e.g. `positions_already_open`, `ai_paused_trading`, NULL if traded |
| `gate_that_stopped` | TEXT NULL | which gate set the stop |
| `rescued_by_recheck` | BOOLEAN DEFAULT FALSE | post_scan_recheck reset + traded |
| `base_capital` | NUMERIC NULL | |
| `equity_at_start` | NUMERIC NULL | |
| `positions_at_start_count` | INT NULL | |
| `trades_executed` / `trades_failed` / `trades_skipped` | INT | |
| `rules_created` | JSONB | list of {rule_id, trigger_type} |
| `config_snapshot` | JSONB | per-account auto_trade_config (sanitized) |
| `created_at` | TIMESTAMPTZ DEFAULT now() | |

Indexes: `(run_id)`, `(account_id, created_at DESC)`.

### 5.3 `debug_lifecycle_events` — chronological "what happened" stream
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT FK→debug_runs ON DELETE CASCADE | |
| `account_id` | TEXT | indexed |
| `seq` | INT | monotonic per (run, account) for stable ordering |
| `phase` | TEXT | `init_balances`/`batch`/`fill`/`post_scan_recheck`/`cleanup` |
| `event_type` | TEXT | e.g. `marked_stopped`, `force_close_triggered`, `recheck_entered`, `recheck_positions_still_open`, `state_reset`, `pause_detected`, `rules_created`, `rules_expired` |
| `detail` | JSONB | event-specific payload |
| `ts` | TIMESTAMPTZ | event time |

Indexes: `(run_id, account_id, seq)`.

### 5.4 `debug_symbol_decisions` — per-symbol-per-account forensics
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT FK→debug_runs ON DELETE CASCADE | |
| `account_id` | TEXT | |
| `phase` | TEXT | which pass produced the decision |
| `symbol` | TEXT | |
| `scan_score` / `scan_confidence` / `scan_direction` | INT/TEXT/TEXT | signal at decision time |
| `decision` | TEXT | `placed` / `skipped` / `rejected` / `failed` |
| `reason_code` | TEXT | `min_score`, `confidence_filter`, `max_signal_age`, `already_held`, `max_same_sector`, `max_same_direction`, `price_drift`, `blacklist`, `whitelist`, `max_trades`, `target_goal_reached`, `placed_ok`, `place_error`, `timeout`, … |
| `reason_detail` | JSONB | the **actual values**, e.g. `{"score": -7, "min_score": 7}` |
| `order_id` | TEXT NULL | set when placed |
| `ts` | TIMESTAMPTZ | |

Indexes: `(run_id, account_id)`, `(symbol, ts DESC)`.

**Volume guard:** capped per (account, phase) at `symbol_decision_cap` (default 200, configurable). On overflow, one synthetic row with `reason_code='truncated'` and `reason_detail={"omitted": N}` is written — no silent gaps.

### 5.5 `debug_exchange_snapshots` — what the executor actually saw (highest-value artifact)
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT FK→debug_runs ON DELETE CASCADE | |
| `account_id` | TEXT | |
| `gate` | TEXT | `scan_start` (init_balances) / `recheck` (post_scan_recheck) |
| `positions` | JSONB | full positions list as returned to the executor (symbol/side/size/…) |
| `position_count` | INT | |
| `wallet` | JSONB | wallet payload (sanitized) |
| `equity` | NUMERIC NULL | |
| `ts` | TIMESTAMPTZ | |

Indexes: `(run_id, account_id, gate)`. Reuses data the executor already fetched (no extra API calls).

### 5.6 `debug_config` — single-row runtime control
| Column | Type | Notes |
|---|---|---|
| `id` | INT PK CHECK (id = 1) | enforce single row |
| `tracing_enabled` | BOOLEAN DEFAULT TRUE | kill-switch |
| `retention_days` | INT DEFAULT 60 | auto-delete `debug_runs` older than this |
| `symbol_decision_cap` | INT DEFAULT 200 | per (account, phase) cap |
| `updated_at` | TIMESTAMPTZ DEFAULT now() | |

The recorder caches these in memory (refreshed on update via the config endpoint and periodically). A nightly cleanup task deletes `debug_runs` older than `retention_days`; CASCADE removes all children.

---

## 6. Read API (`/api/v1/debug`)

New `debug_router` in `backend/routers/debug.py`, registered with prefix `/api/v1`. All routes are read-only (except `PUT /debug/config`), paginated where list-shaped, and never touch the trade path.

### 6.1 The deep aggregate tree
`GET /api/v1/debug/scan/{scan_id}` — complete end-to-end forensic tree for a scan.
- Query params: `run_id` (specific run), `all_runs=true` (include re-run history); default = most recent run for the scan.
- Response includes:
  - **Run metadata** + explicit timing breakdown (scan-analysis window vs auto-trade-execution window — the gap that confused the RCA), `dropped_event_count`.
  - **Per account:** resolved label, entry state, `gate_that_stopped` (or that it traded), `rescued_by_recheck`, balances, rules created/expired.
  - **Lifecycle events** (chronological) per account.
  - **Exchange snapshots** per account (scan_start vs recheck, presented side by side).
  - **Per-symbol decisions** per account with actual reason values.
  - **Linked records** joined in: `close_rules`, `close_executions`, resulting `trades`.
  - **Computed narrative** per account — plain-English story, e.g.: *"Skipped at scan-start (3 positions open) → positions closed 02:00:47 during scan → rescued by recheck → placed 3 trades (B3/MU/IBM)."*

### 6.2 Focused sub-routes
- `GET /api/v1/debug/runs?limit=&offset=&trigger_source=&account_id=&from=&to=` — index of recent runs.
- `GET /api/v1/debug/scan/{scan_id}/account/{account_id}` — one account's full journey for a run.
- `GET /api/v1/debug/account/{account_id}/timeline?from=&to=&limit=` — one account across **multiple** runs (surfaces recurring patterns, e.g. "skipped 3 scans in a row").
- `GET /api/v1/debug/symbol/{symbol}?scan_id=` — every account's decision on one symbol.
- `GET /api/v1/debug/config` / `PUT /api/v1/debug/config` — read/update kill-switch, retention days, symbol cap (updates the cached config live).

### 6.3 Response shape
Pydantic v2 schemas in `backend/schemas/` (new module section). The aggregate tree is a nested model: `DebugRunDetail → [DebugAccountTrace → {events[], snapshots[], symbol_decisions[], linked_rules[], linked_trades[], narrative}]`. Large arrays (symbol decisions) are themselves capped/paginated within the account node to bound payload size.

---

## 7. Instrumentation Points (Write Side)

`DebugTraceRecorder` is injected into `ScannerService` and `AutoTradeExecutor`. All hooks are synchronous, fail-open, buffer-only.

| Location (`auto_trade_service.py` / `scanner_service.py`) | Emitted |
|---|---|
| `init_balances` — position check | exchange snapshot @ `scan_start`; per-account entry state (mode, equity, base_capital, positions count) |
| `init_balances` — skip / force-close / pause branches | lifecycle: `marked_stopped`, `force_close_triggered`, `pause_detected` |
| `init_balances` — rule creation | lifecycle: `rules_created` (+ ids/types) |
| `execute_batch` / `fill_immediate_remaining` — inside `_try_trade` | per-symbol decision (accept + every reject reason with actual values) |
| `post_scan_recheck` — entry | exchange snapshot @ `recheck`; lifecycle `recheck_entered` |
| `post_scan_recheck` — still-open vs reset | lifecycle `recheck_positions_still_open` / `state_reset`; rule recreation |
| `post_scan_recheck` — rescue trades | per-symbol decisions for placed/skipped |
| Scanner finalize (`_run` completion) | open `debug_run` at exec start; close it at exec end (timing, counts, `dropped_event_count`, `phase_reached`) |

A small hook signature is added to `_try_trade` so each early-return records its `reason_code` + `reason_detail` (the function currently returns `None`/increments counters silently at ~12 decision points). The recorder reference is passed via the executor; if absent (recorder not wired, e.g. unit tests), hooks are no-ops.

### 7.1 Run lifecycle in the executor
- `ScannerService` creates the recorder's run context when the auto-trade phase starts (it already holds `scan_id`, `schedule_id`, trigger source).
- Both the scheduled path (`scanner_service` finalize block) and the manual path (`routers/scanner.py` `_run_auto_trade`) open a run, so manual re-triggers produce a **new** run rather than overwriting — preserving history.

---

## 8. Lifespan / Wiring

- Instantiate `DebugTraceRecorder(db=db)` in `backend/main.py` lifespan; store on `app.state.debug_trace_recorder`.
- Inject into `ScannerService` and (via scanner) `AutoTradeExecutor`; also inject into the manual route handler.
- Start the background drainer task and the nightly retention-cleanup task on startup; stop them on shutdown via the existing `_safe_shutdown` pattern.
- Register `debug_router` with the other `/api/v1` routers.
- Load `debug_config` row (create default if missing) during startup and cache it on the recorder.

---

## 9. Testing Strategy

- **Unit:** each `_try_trade` early-return maps to the correct `reason_code`; lifecycle events emitted on the right branches; run open/close timing captured; retention cleanup deletes only expired runs (and cascades).
- **Fail-open:** recorder method raises → trade still succeeds; buffer full → `emit` drops + increments `dropped_count`, trade unaffected.
- **Performance:** batch timing tracing-ON vs OFF statistically unchanged; `emit` sub-microsecond enabled / near-zero disabled; stalled-drainer test confirms trading completes normally.
- **Integration:** replay a scenario mirroring the real incident (positions open at scan-start → close mid-scan → recheck rescues → trades placed). Assert the aggregate tree narrates the full story and exchange snapshots show the state transition.
- **API:** aggregate tree returns all levels; sub-routes filter correctly; pagination bounds payloads; `PUT /debug/config` updates cached config live.

---

## 10. Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Tracing slows the money path | Sync buffer-only emit, drop-on-pressure, dedicated-connection drainer, kill-switch, benchmark gate. Worst case = lost debug data, trading unaffected. |
| Storage growth | Configurable retention (default 60d) + nightly CASCADE cleanup + per-(account,phase) symbol cap. |
| Buffer drops hide gaps | `dropped_event_count` persisted on run; `truncated` marker rows for symbol caps. |
| Sensitive data in snapshots | Sanitize wallet/config payloads (strip API keys/secrets) before persisting, reusing existing sanitization helpers. |
| Schema drift / partial migration | Single append-only v38 migration under the existing advisory-locked migration runner. |

---

## 11. Out of Scope (this iteration)
- Frontend debug-viewer page (API + DB only).
- Instrumenting the dormant `TradingCycleEngine`.
- Replacing `auto_trade_summaries` (additive system).

