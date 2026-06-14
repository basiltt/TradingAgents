# Phase 1 — WebSocket Live Status Transport (parallelizable, fail-open)

**Goal:** Stream the post-scan tail's progress to the Scanner page in real time, mirroring the proven backtest pattern, with a guaranteed-correct polling fallback. Transport-only and fail-open — it must NEVER block or change trade execution.

**Requirements:** FR-010..024, R1-R28, R164a-h, R165a/b/d/h, R172-R174, R176-R177, R187/R189/R190/R192/R193, FF-1/3/4, AC-FIX-4.
**Depends on:** nothing (can build alongside Phase 0). **Blocks:** nothing (Phase 2 emits TO it via the injected sink, but the sink is None-safe).

---

## Files
| File | Action | Purpose |
|---|---|---|
| `backend/services/scan_progress_manager.py` | Create | `ScanProgressManager` pub/sub (mirror `BacktestProgressManager`) |
| `backend/routers/ws_scan_progress.py` | Create | `/ws/v1/scanner/{scan_id}/auto-trade` endpoint |
| `backend/schemas/__init__.py` | Modify | `ScanAutoTradeProgressEvent` Pydantic model |
| `backend/main.py` | Modify | Wire `app.state.scan_progress_manager`; include WS router (no `/api/v1` prefix); graceful drain on shutdown |
| `backend/services/scanner_service.py` | Modify | `_serialize`/`_serialize_db`: add `auto_trade_config_count`; stamp `acct_ordinal` on summaries |
| `frontend/src/api/ws.ts` | Create | Shared `wsBaseUrl()` util |
| `frontend/src/api/client.ts` | Modify | `ScanAutoTradeProgressEvent` TS type + `{accounts,orders}` projections; `ScanStatus.auto_trade_config_count` |
| `frontend/src/hooks/useScanAutoTradeProgressWS.ts` | Create | Live-status hook (close-code-aware, StrictMode-safe) |
| `frontend/src/components/scanner/PostScanExecutionPanel.tsx` | Create | Live panel (stepper + per-account rows + order feed) |
| `frontend/src/components/scanner/ScannerPage.tsx` | Modify | Mount panel; polling-through-tail; `active` predicate; single-renderer; suppress-auto-switch |
| `tests/backend/test_scan_progress_manager.py` | Create | Manager unit tests |
| `frontend/src/hooks/__tests__/useScanAutoTradeProgressWS.test.ts` | Create | Hook tests |

---

## Tasks

### TASK-1.1 — `ScanProgressManager` service (FR-010, R1, R11, R12)
- **Notes:** Mirror `backtest_progress_manager.py` exactly: `emit(scan_id, stage, label, *, detail, pct, status, account_id, acct_ordinal, symbol, phase, substatus, side, reason_code, trades_executed, trades_failed, trades_skipped, cooloff_seconds)`, `subscribe(scan_id)` (pre-loaded with bounded history), `unsubscribe`, `history`, terminal-retention GC (~60s), monotonic `seq`, bounded queues (256, drop-oldest). Keyed by `scan_id`.
- **TDD:** emit→subscribe replay; late subscriber gets history; bounded-queue drop-oldest; terminal GC; monotonic seq under concurrent emits.

### TASK-1.2 — `ScanAutoTradeProgressEvent` schema + TS type (FR-014, R172, HR-6)
- **Notes:** Pydantic model in `backend/schemas` with `schema_version`, all fields above; emitted via `.model_dump()`. **Free-text `detail`/`label` are NOT in the emitted payload** (log-only) — only machine codes (`stage`/`status`/`reason_code`/`side`/numeric fields) cross the wire (FF-4). Co-locate the TS `ScanAutoTradeProgressEvent` type + `{accounts,orders}` projection shapes in `frontend/src/api/client.ts` (not the hook).
- **TDD:** schema round-trips; no free-text leaks; TS type matches.

### TASK-1.3 — WS endpoint (FR-012, FR-013, R3, R189, R192, HR-4, AC-FIX-4)
- **Notes:** `/ws/v1/scanner/{scan_id}/auto-trade` in `ws_scan_progress.py`. Mirror `ws_backtest.py` STRUCTURE (subscribe/replay/30s ping-pong/terminal close) but: **exact-origin match** (reject missing Origin, drop the port-only fallback); validate `scan_id` UUID; **verify the scan exists before subscribe**; **identical empty-then-close** for unknown/foreign ids (no distinct 4404 → no oracle); None-guard a missing manager (1011). Register in `main.py` without `/api/v1`; graceful shutdown drains subscribers with a terminal close.
- **TDD:** unknown scan == empty scan close path; missing origin rejected; exists→streams; ping/pong; terminal close.

### TASK-1.4 — Scan serialization additions (FR-018 signal, CR-6, FF-3, R173)
- **Notes:** `_serialize` (~1118) and `_serialize_db` (~1153): add `auto_trade_config_count: int` derived from `scan["config"]["auto_trade_configs"]` (retroactive for old scans, no migration); on `_serialize_db` config-parse failure, fall back to a presence check via the frozen `auto_trade_results`/`auto_trade_summaries` columns (not count=0). Stamp `acct_ordinal` (per distinct `account_id`) onto each `auto_trade_summaries` row (JSON field, passes opaquely through both serializers). Add `auto_trade_config_count` to the frontend `ScanStatus` type.
- **TDD:** count present in both serializers; parse-failure fallback; old-scan retroactive; ordinal stamped.

### TASK-1.5 — Shared `wsBaseUrl()` util (FR-015, R176, NFR-012)
- **Notes:** `frontend/src/api/ws.ts` exporting `wsBaseUrl()` (`VITE_WS_BASE_URL || ws(s)://host`) + the reconnect/backoff + StrictMode CONNECTING-defer teardown helpers. The new hook consumes it; enumerate the legacy copies (`useBacktestProgressWS`, `useAccountWebSocket`, `useAnalysisWebSocket`) as deferred follow-ups (not migrated now).
- **TDD:** util returns correct base for http/https.

### TASK-1.6 — `useScanAutoTradeProgressWS` hook (FR-015, FR-020, HR-7, R165b)
- **Notes:** Mirror `useBacktestProgressWS` but DIVERGE: (a) onclose reads `event.code`, NO reconnect on permanent codes (4403/4404/1011), only transient (1006/1005); (b) scanId-change reset clears ALL state (`steps, accounts, orders, pct, terminal, connected`) + a `currentScanIdRef` drops prior-scan events in onmessage; (c) **guard-parse** every payload against the typed schema — malformed data dropped+warned, never reaches state (keeps render pure); (d) coalesce-by-stage; exposes `{steps, accounts, orders, pct, connected, terminal}`. Connects to `/ws/v1/scanner/{scanId}/auto-trade`.
- **TDD:** StrictMode double-mount (one socket, clean teardown); late-join replay; reconnect/backoff transient-only; scanId-change teardown + late-event drop; bad-payload dropped not crashing.

### TASK-1.7 — `PostScanExecutionPanel` (FR-016, FR-017, FR-021..024, FF-2/3)
- **Notes:** In the Progress `TabsContent`, between the symbol-scan bar and the existing block. Pre-seeded stepper (init_balances→execute_batch→fill→recheck→cleanup→summaries) with pending/active/done/failed; per-account rows (salted handle, status pill, live counters from authoritative event counts reconciled to summaries on terminal, stopped_reason); bounded order feed (symbol/side/✓✗/reason_code). Mount only when `auto_trade_config_count>0`. **Single-renderer:** suppress ONLY the legacy executions + account-status sub-blocks (`ScannerPage.tsx:1190-1234`); LEAVE the AI-manager reduced-protection notice (`1236-1251`) rendered (FF-2). Error boundary degrades to the polled block on a render crash. Reuse `ScannerMetricCard`/`TonePill`/`SCANNER_PANEL_CLASS`/`--neu-*`. Render copy from `stage`/`status`/`reason_code` enums via ONE frontend map (R165d).
- **TDD (component):** renders stepper from steps; empty state; error-boundary fallback; single-renderer (no double executions block); AI-manager notice preserved.

### TASK-1.8 — ScannerPage integration (FR-018, FR-019, FR-020, FR-024, FF-1)
- **Notes:** `scanQuery.refetchInterval` continues 3s polling while a tail is plausibly active — predicate: `status==="completed" && auto_trade_config_count>0 && auto_trade_summaries absent` (auto tail) OR manual-rerun-in-progress, with an UPPER TIME BOUND so a missed terminal can't poll/socket forever (FF-1 stuck-active guard). The `active` flag gating the WS uses the same predicate. Reconciliation: WS projection during the tail; on terminal, `scanQuery` snapshot authoritative + debounced deduped `invalidateQueries(["scan", scanId])`; live counts monotonic, terminal REPLACES. Suppress the running→completed auto-switch-to-Results (505-511) while a tail is active. Cold-load: empty WS history + terminal → render persisted state from `scanQuery`.
- **TDD:** poll continues through tail; predicate correct on cold-load; no flicker on terminal handoff; suppress auto-switch.

---

## Verification (Phase 1)
1. `python -m pytest tests/backend/test_scan_progress_manager.py -x -q`; backend WS endpoint test.
2. `cd frontend && npx tsc --noEmit && npm run test` (hook + panel).
3. Manual: run a scan with auto-trade configs; watch the panel stream live; kill the WS → page still converges via poll; reload mid-tail → history replay.

## Completion criteria
- Live panel streams stage/account/order events; polling fallback converges; predicate correct on cold-load/reload; no double-render; AI-manager notice preserved; no free-text leak; emit is fail-open (Phase 2 proves execution unaffected).

## Rollback
- The panel mounts only when `auto_trade_config_count>0`; remove the mount + revert `refetchInterval` to revert the UI. The backend manager/endpoint are additive (old polling clients unaffected).

## Risks
- **State-sync flicker:** mitigated by reconciliation precedence (FR-020) + monotonic-live/replace-on-terminal.
- **Stuck-active predicate** (executor never ran): mitigated by the upper time bound (FF-1).
