# Specification — Post-Market-Scan Optimization

## A. Title and Metadata

- **Feature:** Post-Market-Scan Optimization (live WS status + bounded parallelization + Bybit rate-limit enforcement + UX polish)
- **Date:** 2026-06-14
- **Author:** Claude (`/new-feature`, LITE mode)
- **Status:** Draft → In Review
- **Related user request:** "Optimize the Post Market Scan Steps — (1) live WebSocket status on the Scanner page instead of one-shot at the end; (2) parallelize/speed up the slow post-scan activities without bugs (money-critical); (3) follow Bybit non-VIP rate limits via centralized semaphore controls; (4) look-and-feel / UX improvements."
- **Related modules:** scanner_service, auto_trade_service, bybit_client, bybit_rate_gate, scanner router, ws routers, ScannerPage (frontend)
- **Related files:** see Section B
- **Version:** 1.0
- **Requirements source:** `specs/post-scan-optimization-requirements.md` (~196 requirements, MoSCoW-partitioned). This spec implements the **MUST-HAVE** partition; SHOULD/WON'T items are listed as Out-of-Scope / Future Scope.

---

## B. Discovery Summary

Full discovery in `plans/post-scan-optimization/discovery-summary.md`. Key facts:

**The post-scan tail** (`scanner_service._run_scan`, lines 1298-1397) runs sequentially after per-symbol analysis:
`executor.init_balances()` (pre-step, ~469-770) → `execute_batch()` (795) → `fill_immediate_remaining()` (838) → `post_scan_recheck()` (961) → `cleanup_unused_rules()` (924) → `get_summaries()`/`emit_account_summaries()` (865/888). The same 5-step sequence is **duplicated** in the manual re-run path `scanner.py:_run_auto_trade` (160-349).

**Slowness:** every step loops per-account with sequential `await`s for Bybit calls (`get_wallet`, `get_account`, `get_positions`, `list_rules`, `place_trade`→`set_leverage`+`place_market_order`+`set_trading_stop`, `close_all_positions`+`sleep(2)`). `execute_batch`/`fill`/`evaluate_result` run **entirely inside `self._lock`**.

**Shared mutable state:** `self._state: Dict[str,_AccountState]` keyed `f"{account_id}_{i}"`; per-state counters (`trades_executed/failed/skipped`, `executions[]`, `existing_symbols`, `position_directions`, `created_rule_ids`); function-local cross-account `traded:set` of `(account_id,symbol)` (disjoint across accounts); per-`(account,symbol)` `_position_lock_registry` (shared with AI-manager + CloseRuleEvaluator).

**Rate gate (exists):** `bybit_rate_gate.py` — process-wide singleton, channels `public`(400/5s)/`private`(100/5s)/`ws_connect`, lanes `order`/`live`/`mcp`. `bybit_client._request` routes all calls through it but **hardcodes `channel="private"`** even for public market endpoints. `_do_sync_time` (line 77) **bypasses the gate**. Per-client `Semaphore(10)`. No per-endpoint or per-UID limit.

**Bybit non-VIP limits (live doc):** IP 600/5s (ban ≥10min on 10006); order-create 10/s floor (UTA2.0/Inverse) to 20/s (Linear) per UID; position-list/wallet 50/s per UID; set-leverage/set-trading-stop 10/s per UID; market reads IP-bounded only.

**WS pattern to mirror (proven):** `BacktestProgressManager` (per-run pub/sub, history replay, terminal GC) + `ws_backtest.py` (`/ws/v1/backtest/{run_id}`, subscribe+replay+ping/pong) + `useBacktestProgressWS.ts` (reconnect/backoff, StrictMode-safe, coalesce-by-stage). Wired in `main.py` lifespan onto `app.state`.

**Frontend:** `ScannerPage.tsx` polls `GET /scanner/{scan_id}` every 3s **only while `status==="running"`** — the tail runs AFTER `completed`, so post-scan results appear in one shot. Rendered at 1190-1251 (executions/account-status/AI-notice). Neumorphic theme (`--neu-*`, `ScannerMetricCard`, `TonePill`).

**asyncpg pool:** `DB_POOL_MAX=10`, acquire `timeout=10`, `command_timeout=10`. A second resource ceiling alongside the rate gate.

**App has no per-request auth/authz** on the REST/WS surface; boundary is the loopback/trusted-LAN bind (`mcp/router.py:4`). `admin.py` kill-switch is unauthenticated, `updated_by` read from body.

---

## C. Feature Overview

- **What:** (1) Stream the post-scan auto-trade tail's progress to the Scanner page live over a new WebSocket; (2) parallelize the tail's per-account network I/O under a bounded, rate-gated, behavior-preserving fan-out; (3) correct and extend the centralized Bybit rate gate (public/private channel fix, per-UID/per-endpoint sub-limits, gate-bypass fix) so the new concurrency cannot trip Bybit's limits; (4) polish the live panel and Progress tab.
- **Why:** the tail is slow (sequential per-account Bybit round-trips) and opaque (results appear only at the very end). Speed matters because it is a money path; opacity erodes trust while real orders are placed.
- **Who:** the trader operating the scanner (live), and the system on the scheduled path (unattended → durable record).
- **Problem solved:** slow + opaque + rate-fragile post-scan execution.
- **Expected outcome:** a measurably faster tail (benchmark-gated), a live per-account/per-symbol status panel, provably rate-compliant Bybit egress, all with **byte-identical trade behavior** to today (golden-equality gate).

## D. Business Goal

- **Objective:** faster, observable, rate-safe post-scan order execution without changing which orders are placed.
- **User value:** real-time confidence in what the system is doing with their money; less waiting.
- **Operational value:** Bybit ban avoidance (a ban halts all trading); runtime kill/rollback controls; observability.
- **Success definition:** (a) golden-equality — identical orders/counts vs sequential for identical inputs; (b) measurable speedup at N≥5 accounts under rate compliance; (c) zero `10006` in the benchmark; (d) live panel reflects each stage/account/order in real time with a polling fallback.

## E. Current System Behavior

- After analysis, the tail runs sequentially; `auto_trade_results`/`auto_trade_summaries` attach to the scan dict and are surfaced only when the whole tail finishes.
- Frontend polls `GET /scanner/{scan_id}` every 3s while `status==="running"`; the tail runs after `completed`, so the poll captures only the final state.
- All Bybit calls route through `bybit_client._request` → the rate gate on `channel="private"` (including public market reads); `_do_sync_time` bypasses the gate.
- **Pain points:** (1) slow tail (sequential per-account); (2) opaque ("one shot at the last"); (3) rate gate mislabels public traffic and lacks per-endpoint/per-UID enforcement — fragile if concurrency rises; (4) Progress-tab UX is static.

## F. Expected New Behavior

- **Tail orchestration** is extracted to ONE shared async method used by both call sites (auto tail + manual re-run), so behavior, persistence cadence, and progress emission are identical.
- **Bounded cross-account parallelism:** the tail fans out across accounts under a single **process-wide** bounded semaphore; each account's symbol loop stays sequential (best-score-first). Default fan-out width = **1 (sequential)** on first deploy; raising it is operator opt-in. Per-account work is isolated; results merge deterministically.
- **Rate gate** correctly charges public market reads to the public channel, adds per-UID per-endpoint sub-limits (order 8/s, etc.), routes `_do_sync_time` through the gate, and keeps the existing lane priority. Every leaf Bybit call remains gated; the new fan-out is gated, not bare `gather`.
- **Live status:** a new `ScanProgressManager` (mirrors `BacktestProgressManager`) is emitted-to by the tail; a new WS endpoint streams events; the Scanner page renders a live `PostScanExecutionPanel` (stepped progress + per-account rows + order feed). The 3s poll continues **through the tail** as a guaranteed-correct fallback.
- **Persistence:** incremental, single-writer-serialized, idempotent across resume; final results commit **before** the terminal WS event.
- **Behavior invariant:** for identical inputs the parallel path places the identical set of orders with identical per-account counts — proven by a golden-equality test.

## G. Scope

### In Scope (MUST-HAVE partition)

**Phase 0 — Rate-gate correctness (prerequisite, R59-R78, R169, R171):**
- Public/private channel classification per endpoint (`get_mark_price`/`get_instrument_info`/`get_kline`/`get_tickers`/`/v5/market/time` → public).
- Route `_do_sync_time` through the gate.
- Per-UID, per-endpoint sub-limiter (keyed on the real Bybit UID) with safe-floor caps; single all-or-none critical section across IP + per-UID dimensions; preserve lane priority and the atomic check+append invariant.
- `_wait_count` telemetry made thread-safe.
- Endpoint→class→limit registry (single source of truth); assert any unmapped `_request`.
- All gated behind a runtime kill-switch that reverts to current behavior.

**Phase 1 — WS transport (R1-R12, R14-R22, R24, R26-R28, R164a-h, R165a/b/d/h, R172-R174, R176-R177, R187/R189/R190/R192/R193):**
- `ScanProgressManager` service; `/ws/v1/scanner/{scan_id}/auto-trade` endpoint (strict origin, scan-existence check, ping/pong, history replay, terminal close); typed Pydantic event + co-located TS type with `schema_version`; shared `wsBaseUrl()` util; `useScanAutoTradeProgressWS` hook; `PostScanExecutionPanel` (stepper + per-account rows + order feed); polling-through-tail fix; `active` predicate; reconciliation precedence; single-renderer; error boundary; account-label opaque handle.

**Phase 2 — Bounded parallelism + data integrity (R29-R58, R126-R130, R139-R140, R160, R166-R170, R182-R183):**
- Shared `run_post_scan_tail` orchestrator; process-wide account-concurrency semaphore (default 1); per-account partition/merge; preserve within-account ordering, per-`(account,symbol)` lock, idempotency, slot counting; parallelize `init_balances`/`post_scan_recheck`/`cleanup`/`summaries`; failure isolation; incremental idempotent persistence (commit-before-terminal); pool-aware sizing + orphan-order-on-pool-timeout safety; resume tail-in-progress sub-state; pre-flight feasibility; runtime kill-switch (force sequential).

**Phase 3 — UX polish + cross-cutting (R79-R80, R82, R84, R88, R90, R195, R98-R119, R123-R125, R148-startup-validation, R151, R179-R181, R184-R186, R188, R191, R194, R196):**
- Native theming, status semantics, skip-reason transparency, DRY-RUN/LIVE badge, distinct ban-cooloff state; cancellation/None-safety/secret-scrub/audit; golden + speedup benchmarks; default-off rollout + startup config validation + active regression detectors; Definition-of-Done gate.

### Out of Scope (SHOULD-HAVE — deferred to a tracked backlog, may fast-follow behind flags)
R13, R23, R25, R81, R83, R85, R86/R87, R91-R97, R120-R121, R131-R138, R141, R145, R147, R152, R156, R158, R161-R163, R165c/e/f/g, R175, R178, R185(extended telemetry).

### Future Scope (WON'T-HAVE-NOW — YAGNI / risk to a money-critical change)
R146 (durable timeline via migration), R149 (runbook), R150 (introspection endpoint), R154 (cross-stage balance cache — stale-balance risk), R155 (batch order endpoints), R157 (FE virtualization), R161 (latency percentiles), R129-multi-replica + R141-AI-manager-pause-lane (document constraints only), R153 (poll-until-settled), general scanner-page redesign.

### Architecture Decisions (Step 3 — folded in)
- **AD1.** Mirror `BacktestProgressManager`/`ws_backtest`/`useBacktestProgressWS` rather than reuse the heavier EventBus/WSManager — proven, simpler, per-run history+GC already solved. *(D1)*
- **AD2.** Parallelize across **accounts** (independent: separate BybitClient/UID/state), never within an account (symbol order is best-score-first slot fill). *(D2)*
- **AD3.** Account-concurrency limiter is a **process-wide singleton** (like the rate gate), default width **1**. *(R129/R179)*
- **AD4.** The `ScanProgressManager` is a long-lived `app.state` singleton injected into the tail as an optional, None-defaulted `ProgressSink`; the executor never imports the WS layer; emit is fail-open. *(R2/R7/R8)*
- **AD5.** No new DB column in the MUST scope (R146 deferred); use the existing in-memory manager + existing `auto_trade_results`/`auto_trade_summaries` columns. A tail-in-progress sub-state (R183) reuses the existing `status` field semantics or an existing nullable column — confirmed during planning to avoid a migration.
- **AD6.** Rate-gate redesign keeps the existing public/private deques + lanes and ADDS a per-UID per-endpoint dimension inside the same critical section (all-or-none commit, R169).
- **AD7.** Each risky change (fan-out, channel-fix, per-endpoint limiter) is independently revertible at runtime via the existing `feature_kill_switches` (R180).

## H. Functional Requirements

### Phase 0 — Rate gate
- **FR-001:** `bybit_client` must classify each endpoint as public or private and pass the correct `channel` to the rate gate; market-data endpoints (`get_mark_price`, `get_instrument_info`, `get_kline`, `get_tickers`, `/v5/market/time`) use `channel="public"`; account/order/position/wallet use `channel="private"`. *(R60, R64)*
- **FR-002:** `_do_sync_time` must acquire a public-channel gate token before its HTTP call (no bypass). *(R65)*
- **FR-003:** The gate must enforce a per-UID, per-endpoint sub-limit keyed on the real Bybit UID (resolved once and cached on the client), independent of the IP window, with safe-floor caps: order-create/cancel/amend ≤8/s, set-leverage ≤8/s, set-trading-stop ≤8/s, position-list ≤40/s, wallet-balance ≤40/s, other ≤20/s. *(R61, R62, R63)*
- **FR-004:** A placement requiring both an IP token and a per-UID/endpoint token must acquire them in a single all-or-none critical section (check all dimensions; append to all or none), under one consistent lock, never holding the lock across an `await`. *(R169, R71, R160)*
- **FR-005:** A central endpoint→class→limit registry is the single source of truth; any `_request` path lacking a mapping raises/asserts. *(R67)*
- **FR-006:** The IP window enforces a hard ceiling of 600/5s with an operating target ≤480/5s; the combined budget after the channel fix stays provably ≤540/5s. *(R59)*
- **FR-007:** Existing lane priority (`order`/`live`/`mcp`) is preserved and extended to the per-UID/endpoint tier so order-create never starves behind position/wallet/MCP traffic. *(R70)*
- **FR-008:** `_wait_count` increments/decrements are thread-safe (inside the gate lock or atomic). *(R171)*
- **FR-009:** The channel-fix and per-endpoint limiter are each independently revertible at runtime via `feature_kill_switches`, falling back to the pre-change behavior. *(R180)*

### Phase 1 — WS transport
- **FR-010:** A `ScanProgressManager` service provides `emit(scan_id, stage, label, *, detail, pct, status, account_id, account_label, symbol, phase, substatus)`, `subscribe(scan_id)` (pre-loaded with bounded history), `unsubscribe`, `history`, and terminal-retention GC; `seq` is strictly monotonic per scan. *(R1, R5, R11, R12)*
- **FR-011:** The manager is created in `main.py` lifespan and attached to `app.state.scan_progress_manager`; the emitter-vs-manager startup order guarantees no emit hits a `None` manager. *(R2, R177a)*
- **FR-012:** A WS endpoint `/ws/v1/scanner/{scan_id}/auto-trade`: strict reject-on-missing-Origin (mirror `ws.py`, NOT `ws_backtest`); validates `scan_id` as UUID; verifies the scan exists before subscribe (identical empty-then-close for unknown/foreign ids); 30s ping/pong; closes cleanly on terminal stage; None-guards a missing manager (1011). *(R3, R189, R192, R118)*
- **FR-013:** The endpoint is registered in `main.py` without the `/api/v1` prefix; graceful shutdown drains subscribers with a terminal close. *(R4, R177b)*
- **FR-014:** The progress event is a backend Pydantic model emitted via `.model_dump()` carrying a `schema_version`; the TS event type and `{accounts, orders}` projections live in `frontend/src/api/client.ts`. *(R172)*
- **FR-015:** A `useScanAutoTradeProgressWS(scanId, active)` hook mirrors `useBacktestProgressWS` (reconnect/backoff, StrictMode-safe teardown, coalesce-by-stage, ping/pong, scanId-change teardown + late-event isolation by `scan_id`), built on a shared `wsBaseUrl()` util; exposes `{steps, accounts, orders, pct, connected, terminal}`; close-code → reconnect-decision contract (permanent 4403 does not reconnect-loop). *(R14, R15, R165b, R176, R177c)*
- **FR-016:** A `PostScanExecutionPanel` renders in the Progress tab: a pre-seeded stepped list (init_balances→execute_batch→fill→recheck→cleanup→summaries) with pending/active/done/failed states; per-account rows (label-handle, status pill, live counters, stopped_reason); a bounded streaming order feed (symbol/side/account/✓✗/error). *(R16-R19, R21)*
- **FR-017:** The panel mounts only when the scan has auto-trade configs; the legacy static executions block (1190-1251) is suppressed while the panel is mounted (single renderer); an error boundary degrades to the polled block on a bad payload. *(R164d, R165a, R82)*
- **FR-018:** `ScannerPage`'s `scanQuery` continues 3s polling while a post-scan tail is plausibly active (not only while `status==="running"`), until `auto_trade_summaries` land or a terminal WS event arrives. *(R164a — CRITICAL)*
- **FR-019:** The client-side `active` predicate is defined for both paths: auto tail = `status==="completed" && auto_trade_configs present && auto_trade_summaries absent`; manual re-run = trigger→terminal; with an upper time bound so a missed terminal can't hold the socket open forever. *(R164b)*
- **FR-020:** Reconciliation precedence: during a live tail the WS projection is the display source; on terminal the DB-backed `scanQuery` snapshot is authoritative and re-renders; counts are monotonic (never tick down on a stale poll). The terminal WS event triggers a debounced, deduped `invalidateQueries(["scan", scanId])`. *(R164c, R164e)*
- **FR-021:** Per-account counters derive from authoritative event counts (reconciled to `auto_trade_summaries` on terminal), independent of the truncated feed. *(R164f)*
- **FR-022:** Cold-load/post-GC: mounting for an already-terminal scan with empty WS history renders the persisted final state from `scanQuery` (not an empty skeleton or perpetual "connecting"); byte-identical whether reached live or cold. *(R164h)*
- **FR-023:** Account identity over WS is an opaque per-scan handle (`acct#1..N` / hashed id); the human label resolves only in the authenticated DB-backed view. *(R190)*
- **FR-024:** The auto-switch-to-Results effect is suppressed/deferred while a tail is active (keep Progress focused) until terminal. *(R164g)*

### Phase 2 — Bounded parallelism + data integrity
- **FR-025:** A single shared `run_post_scan_tail(results, *, progress=None)` orchestrator runs the 5-step sequence and is called by both `scanner_service._run_scan` and `scanner.py:_run_auto_trade`. *(R29, R57)*
- **FR-026:** A process-wide `scan_id`-keyed single-flight guard prevents an auto tail and a manual re-run for the same scan from running the tail concurrently. *(R30)*
- **FR-027:** A process-wide bounded account-concurrency limiter (default width 1) fans out the tail across accounts; each account's symbol loop runs sequentially; the fan-out is gated, never bare `gather`. *(R31, R33, R68, R129)*
- **FR-028:** Partition unit is `account_id` (one task owns all of an account's `_AccountState`s); per-account `traded`/`executions` are local and merged after gather in deterministic (`self._state` insertion × symbol) order. *(R32, R34, R49)*
- **FR-029:** `_fill_to_max` runs per-account using only that account's `traded` subset; the `self._lock.locked()` assert is removed/replaced without weakening isolation; fill never re-introduces an already-traded symbol. *(R35)*
- **FR-030:** Each `_AccountState` (incl. `position_directions`, `mr_duration_rule_created`) is written by exactly one task; the per-`(account,symbol)` `_position_lock_registry` stays intact; MR caches tolerate concurrent same-symbol reads (no KeyError/corruption). *(R36, R37, R38, R39, R166)*
- **FR-031:** `init_balances` (both loops), `post_scan_recheck` (per-account loop), `cleanup_unused_rules` (per-rule), and `emit_account_summaries` (per-account) are parallelized under the bounded limiter; cleanup/summaries run only after the gather fully joins. *(R40, R41, R42, R43)*
- **FR-032:** A `=1` concurrency setting produces an exact sequential execution path. *(R44, R179, R113)*
- **FR-033:** Each `(account_id, symbol)` is processed by exactly one task across the whole tail; the per-account `traded` check-and-mark is atomic; slot counting stays single-writer; order-create keeps `retry_on_network_error=False` and reuses its `orderLinkId`; the live-position re-check remains the dup backstop; `evaluate_result` (immediate) stays serialized/out-of-scope. *(R47, R48, R50, R51, R52)*
- **FR-034:** One account erroring/timing-out/rate-limited does not abort others (per-account isolation); the failure is captured into that account's summary + a `status:"failed"` event; a partial-failure account's counts stay consistent; a placed-order-but-rule-create-failure does not roll back the order and cleanup does not delete its rules. *(R53, R54, R55)*
- **FR-035:** Post-gather merge and `cleanup_unused_rules` read authoritative data from `self._state`, never from `gather(return_exceptions=True)` return values; on cancel in the orphan window (`trades_executed==0`), cleanup skips interrupted accounts. *(R170)*
- **FR-036:** Incremental persistence is single-writer-serialized (or a DB-side single-statement append), atomic w.r.t. the merge, and idempotent across resume (de-dup by `(account_id,symbol,order_id)` or replace-by-stage); final results commit before the terminal WS event. *(R56, R128, R135, R140)*
- **FR-037:** Account-fanout width is sized against BOTH the Bybit IP budget and the asyncpg pool (`DB_POOL_MAX=10`); a pre-flight feasibility check projects peak 5s requests (incl. headroom for reconciler/AI-manager/evaluator) and auto-reduces concurrency if it would exceed ≤480/5s. *(R45, R69, R77, R126, R130)*
- **FR-038:** An already-placed order's DB write survives pool contention (reserved/priority connection or bounded retry with the same `orderLinkId`, plus a guaranteed recovery record so the reconciler can adopt an orphan); never silently drop a placed order on pool timeout. *(R127)*
- **FR-039:** A durable tail-in-progress sub-state is persisted before fan-out so a restart mid-tail re-runs-or-finalizes the interrupted tail (engaging R135 idempotency); the per-placement multi-table write boundary is defined. *(R183, R139)*
- **FR-040:** The fan-out is independently revertible to sequential at runtime via `feature_kill_switches`; the kill-switch is re-checked cooperatively at the safe launch point between accounts. *(R180, R132, R133)*

### Phase 3 — UX + cross-cutting
- **FR-041:** The panel reuses native primitives (`ScannerMetricCard`, `TonePill`, `SCANNER_PANEL_CLASS`, `--neu-*`); status colors are semantically consistent (green=placed, red=failed, amber=skipped, grey=pending, accent=running/waiting); distinct in-progress/completed/failed/cancelled headers. *(R79, R80, R84)*
- **FR-042:** Every skip names its reason; each placed order shows side/symbol; a DRY-RUN vs LIVE badge is shown; an IP-ban cooloff state is visually distinct from a micro-throttle pulse with a reset countdown. *(R88, R89, R90, R195)*
- **FR-043:** Cancellation is cooperative at safe points (between symbols/accounts), never mid-order; the order→stop section is shielded so a cancel cannot orphan a position without TP/SL; a cancelled scan persists every order that hit the exchange and emits a terminal event. *(R98, R99, R100, R10)*
- **FR-044:** Backtest/None-safe paths run the full parallel tail green (no `_close_svc`, no progress manager, `_position_lock_registry=None`, tracing off → no `get_account` calls). *(R116, R117)*
- **FR-045:** Progress event payloads are scrubbed via an allow-list (no keys/secrets/headers/balances; account identity as the opaque handle). *(R119)*
- **FR-046:** Operator controls (runtime kill/concurrency-override) fail closed on a non-loopback bind and write a tamper-evident audit entry with a transport-derived principal (never a caller-supplied string). *(R187, R188)*

## I. Non-Functional Requirements

- **NFR-001 (Performance):** The parallel tail must be measurably faster than sequential at N≥5 accounts under rate compliance; a committed benchmark (deterministic mock `BybitClient` with configurable per-call latency) asserts a minimum speedup at 5/10/20 accounts and captures per-stage wall-clock. *(R151)*
- **NFR-002 (Performance ceiling):** Document the rate-limited throughput ceiling (~13-14 placements/s at ≤480/5s, ~6-9 req/placement) and the account-count plateau, so the speedup is not over-promised. *(R152 — documented in spec/plan)*
- **NFR-003 (Behavior fidelity):** For identical inputs the parallel path is byte-identical to sequential (orders, counts, final summaries), proven by a golden-equality test; `<1%` deviation is the project bar. *(R46, R58)*
- **NFR-004 (Rate compliance):** Zero `10006` under the NFR-001 benchmark; the gate never exceeds 540/5s; a near-ban early-warning fires before a 10006. *(R59, R186b)*
- **NFR-005 (Reliability / fail-open):** Progress emission never blocks, delays, or breaks trade execution; a raising/None manager leaves execution byte-identical. *(R8, R26-fail-open)*
- **NFR-006 (Concurrency safety):** No double-placed order, no slot leakage, no deadlock across (position-lock-registry × rate-gate × per-client-semaphore × account-semaphore × DB-pool); the gate's critical section holds for O(1) work and never across an await. *(R47, R160, R169)*
- **NFR-007 (Resource bounds):** Account fan-out respects both the Bybit IP budget and the 10-connection asyncpg pool; WS subscriber queues are bounded with drop-oldest; a 500+-event scan never backpressures execution. *(R12, R126, R104)*
- **NFR-008 (Observability):** Structured per-account/per-stage timing logs keyed by `scan_id`+`account_id`; active duplicate-placement + near-ban detectors. *(R121-basic, R186)*
- **NFR-009 (Security):** Strict WS origin policy; scan-existence check; opaque account handle; scrubbed payloads; fail-closed operator endpoints on non-loopback bind. *(R187, R189, R190, R192)*
- **NFR-010 (Compatibility):** Existing 3s polling clients, the `_serialize` scan shape (6-field `auto_trade_results` frozen, additive-only scan-level), `ScanDetailPage`, and existing non-tail Bybit flows (dashboard/reconciler/evaluator/cycle-engine/AI-manager/MCP) suffer no regression from the channel/limit changes. *(R114, R115, R163, R185)*
- **NFR-011 (Rollout):** Ships default concurrency=1; each risky change independently runtime-revertible; staged ramp gated on telemetry; a single Definition-of-Done gate (golden + speedup + zero-10006 + sequential-fallback + orphan-safety). *(R179, R180, R184, R194, R196)*
- **NFR-012 (Maintainability):** WS base-url + reconnect logic extracted to one shared util; one typed event contract co-located in `client.ts`; the endpoint→class→limit registry is the single rate source of truth. *(R176, R172, R67)*

## J. User Flows

**Primary (live, attended):**
1. Trader launches a scan with auto-trade configs.
2. Symbols analyze (existing progress bar). Scan reaches `completed`; the post-scan tail begins.
3. The `PostScanExecutionPanel` shows the stepper advancing (init_balances→…→summaries); per-account rows light up as each account is processed; orders stream into the feed (✓/✗ with reason).
4. On terminal, the panel collapses to a compact summary; `scanQuery` is invalidated → authoritative final state renders.

**Alternate (manual re-run):** Trader triggers re-run; the same panel resets and streams; single-flight prevents a concurrent auto tail.

**Failure flows:** One account fails → its row shows failed + reason, others continue. Rate-limit throttle → muted "waiting" sub-label; an actual IP ban → distinct "Trading paused ~Nm" with countdown. WS down → badge shows "Polling"; the page still converges from the 3s poll.

**Empty-state:** No auto-trade configs → quiet "no auto-trade routes" placeholder. All symbols skipped → "no trades placed (see reasons)".

**Cold-load:** Opening a long-finished scan (history GC'd) → renders the persisted final summary from `scanQuery`, no live skeleton.

## K. API Requirements

**New WS:** `GET /ws/v1/scanner/{scan_id}/auto-trade` (WebSocket).
- Path param `scan_id` (UUID, validated).
- Auth: strict origin allow-list (reject missing Origin); scan-existence check before subscribe; identical empty-then-close for unknown/foreign ids.
- Messages (server→client): `scan_auto_trade_progress` events (`schema_version`, `scan_id`, `stage`, `label`, `detail`, `pct`, `status`, `seq`, `ts`, `account_id`(opaque handle), `symbol`, `phase`, `substatus`); `ping` keepalive.
- Messages (client→server): `pong`.
- Close codes: 4403 (origin — permanent, no reconnect), 4404/clean (unknown scan), 1011 (no manager), 1000 (unmount), terminal close on `complete`/`failed`/`cancelled`.
- Backward-compat: purely additive; no change to existing REST endpoints' shapes.

**Modified REST:** `GET /api/v1/scanner/{scan_id}` — response gains nothing breaking; the 6-field `auto_trade_results` dict is frozen; any new scan-level field is additive and lands in BOTH `_serialize` and `_serialize_db` and the frontend `ScanStatus` in lockstep. `ScanStatusResponse` is either synced+applied or explicitly documented as an untyped superset (no silent strip). *(R173, R174)*

**Modified REST:** `POST /api/v1/scanner/{scan_id}/auto-trade` — unchanged response shape (`{status, scan_id}`); now also drives the shared orchestrator + progress emission.

## L. UI/UX Requirements

- **Pages:** Scanner (Progress tab) — new `PostScanExecutionPanel`. `ScanDetailPage` — unchanged (poll-only historical view; R165g defers live there).
- **Components:** new `PostScanExecutionPanel.tsx` + sub-rows; reuse `ScannerMetricCard`, `TonePill`, `SCANNER_PANEL_CLASS`, `ScannerPanelHeader`.
- **States:** pending/active/done/failed steps; connecting (skeleton), live, terminal-collapsed, empty, error-boundary-fallback; connection badge (LIVE/Reconnecting/Polling); ban-cooloff distinct from throttle.
- **A11y (MUST subset):** status by icon+text not color alone; the rest (aria-live, reduced-motion) is SHOULD (R93/R94).
- **Responsive:** the panel is legible on mobile (full responsive polish R95 is SHOULD).
- **Patterns:** neumorphic theme tokens; coalesce-by-stage to avoid flicker.

## M. Backend Requirements

- **New service:** `backend/services/scan_progress_manager.py` (`ScanProgressManager`, mirror `BacktestProgressManager`).
- **New router:** `backend/routers/ws_scan_progress.py` (`/ws/v1/scanner/{scan_id}/auto-trade`).
- **New schema:** `ScanAutoTradeProgressEvent` (Pydantic, `backend/schemas`).
- **Modified:** `auto_trade_service.py` — add optional `progress` sink to `__init__`; extract `run_post_scan_tail`; parallelize the 5 steps under a bounded limiter; per-account partition/merge; preserve locks/ordering/idempotency; thread the kill-switch + concurrency setting.
- **Modified:** `scanner_service.py` — call `run_post_scan_tail`; pass the progress manager; tail-in-progress sub-state; incremental idempotent persistence (commit-before-terminal); cancel/terminal emission.
- **Modified:** `scanner.py` (`_run_auto_trade`) — call the same orchestrator; emit progress; single-flight.
- **Modified:** `bybit_client.py` — per-endpoint channel classification; route `_do_sync_time`; resolve+cache UID; pass endpoint class to the gate.
- **Modified:** `bybit_rate_gate.py` — per-UID per-endpoint sub-limiter; all-or-none multi-dimension acquire; thread-safe `_wait_count`; endpoint→class→limit registry; runtime kill-switch fallbacks.
- **New singleton:** process-wide account-concurrency limiter (e.g. `backend/services/post_scan_concurrency.py` or a gate method).
- **Modified:** `main.py` — wire `scan_progress_manager` + the new WS router; startup config validation.
- **Patterns:** follow None-guard idioms (`_emit_life`), fail-open emits, existing structured logging.

## N. Database/Data Requirements

- **No new column in MUST scope** (R146 deferred). Reuse `auto_trade_results`/`auto_trade_summaries` columns.
- **Tail-in-progress sub-state (R183):** confirmed during planning whether to reuse the existing `status` field (keep `running` until the tail joins) or an existing nullable column — chosen to AVOID a migration. If a migration proves unavoidable, it must be additive-nullable, `ADD COLUMN IF NOT EXISTS`, metadata-only, NULL-tolerant, ignored by old code (R181).
- **Incremental persistence:** single-writer-serialized or DB-side single-statement JSON append; idempotent across resume by `(account_id, symbol, order_id)`.
- **Data integrity:** an already-placed order always yields a durable record (trade row or recovery record); no orphan on pool timeout.

## O. Integration Requirements

- **Bybit V5:** existing `aiohttp` client; all egress through the centralized gate; non-VIP limits per Section B; reactive 429/`10006` retry stays as a backstop; respect `X-Bapi-Limit-Reset-Timestamp`; idempotent order-create (`orderLinkId`, no network retry).
- **Internal:** shares the rate gate + `_position_lock_registry` with `position_reconciler`, `close_rule_evaluator`, `ai_manager_task`, `trading_cycle_engine`; the feasibility check reserves headroom for these; document the single-egress-process constraint.

## P. Security Requirements

- Strict WS origin policy (reject missing Origin); UUID `scan_id` validation; scan-existence check pre-subscribe (no enumeration/oracle).
- Account identity over WS = opaque per-scan handle; payloads scrubbed via allow-list (no keys/secrets/headers/balances/labels).
- Operator runtime controls fail closed on a non-loopback bind; audit entries bind to a transport-derived principal, not a caller-supplied string.
- No new injection surface; any persisted reason/error rendered as text (not HTML).

## Q. Performance Requirements

- Benchmark-gated speedup (NFR-001); documented ceiling (NFR-002); the gate must not serialize the fan-out (O(1) critical section, no await under lock); cold-start credential decryption off the event loop is SHOULD (R158) but the fan-out must not block the loop on CPU-bound work.

## R. Logging, Monitoring, Observability

- Log per-account/per-stage timing keyed by `scan_id`+`account_id`; log every rate-limit wait, `10006`, and order placement under concurrency (UID, symbol, lane, queue-wait).
- Active detectors: duplicate-placement invariant + near-ban early-warning. Do NOT log secrets/keys/balances.

## S. Edge Cases

Covered by FR-033/34/35/43/44 and the requirements: zero accounts/results/all-stopped; exactly-50% failure boundary (does not skip); single account == sequential; late WS subscriber (history replay); multi-client same scan; no client connected (still persists); WS down (poll converges); cold-load post-GC; cancel mid-tail (shielded order→stop); crash/resume mid-tail (idempotent, tail-in-progress); pool exhaustion (no orphan); manual re-run vs auto interleave (single-flight + live re-check); per-UID 10006 isolation vs IP ban.

## T. Testing Requirements

- **Unit:** rate-gate channel classification, per-UID/endpoint limiter, all-or-none acquire, thread-safe `_wait_count`; per-account partition/merge determinism; `_fill_to_max` per-account; cancel-orphan-window cleanup skip.
- **Golden-equality (critical):** deterministic mock `BybitClient` → parallel vs sequential places the identical order set + identical counts (NFR-003).
- **Concurrency:** no double-placement under fan-out; slot integrity; no deadlock; one-account-failure isolation; cancel mid-tail; pool-timeout orphan safety.
- **Persistence:** concurrent-persist no lost update; crash-resume idempotency; commit-before-terminal ordering.
- **WS:** history replay (late join), reconnect/backoff, scanId-change teardown, strict origin, scan-existence, terminal close.
- **Frontend:** StrictMode double-mount (one socket), poll↔WS reconciliation no-flicker, polling-through-tail, cold-load persisted render, error-boundary fallback.
- **Benchmark:** speedup at 5/10/20 accounts; zero `10006`.
- **Regression:** existing non-tail Bybit flows unaffected by the channel/limit changes (steady-state).
- **None-safety:** full parallel tail green in backtest mode.

## U. Acceptance Criteria

- **AC-001:** Given identical scan results + configs, when the tail runs parallel vs sequential, then the placed-order set and per-account `trades_executed/failed/skipped` are identical. *(FR-033, NFR-003)*
- **AC-002:** Given N≥5 accounts with mock latency, when the tail runs at the default-raised concurrency, then wall-clock is measurably less than sequential AND zero `10006` occurs. *(NFR-001, NFR-004)*
- **AC-003:** Given a public market read, when it executes, then it consumes the public channel budget (not private). *(FR-001)*
- **AC-004:** Given a burst of order-creates for one UID, when they exceed 8/s, then the gate throttles them without a `10006`. *(FR-003)*
- **AC-005:** Given a running tail, when a client subscribes, then it sees the stepper/account/order state via history replay then live events; when WS is down, the page still converges to the correct final state via the 3s poll. *(FR-015, FR-018)*
- **AC-006:** Given a scan cancelled mid-tail, when cancellation lands, then no order is left without TP/SL and every order that hit the exchange is persisted. *(FR-043)*
- **AC-007:** Given one account errors mid-tail, when it fails, then other accounts complete and the failure is isolated to that account's summary. *(FR-034)*
- **AC-008:** Given concurrency=1, when the tail runs, then the execution path is exactly sequential and byte-identical to today. *(FR-032)*
- **AC-009:** Given a restart mid-tail, when the app resumes, then the interrupted tail re-runs-or-finalizes without re-placing already-placed orders. *(FR-036, FR-039)*
- **AC-010:** Given a pool timeout after an order is placed, when the trade-row write fails, then a durable recovery record exists so the reconciler can adopt the position (no silent drop). *(FR-038)*
- **AC-011:** Given the panel is mounted, when the legacy static block would render, then only one renderer shows the post-scan results. *(FR-017)*
- **AC-012:** Given a backtest executor (no close_svc, no progress manager), when the full parallel tail runs, then it completes green. *(FR-044)*

## V. Risks

- **R-1 (Critical, Med):** Parallelization double-places an order or mis-counts slots. → Mitigation: account-axis-only partition (disjoint state), golden-equality test, per-`(account,symbol)` lock + live re-check, default concurrency=1, staged ramp.
- **R-2 (Critical, Low):** New concurrency trips Bybit's IP limit → 10-min ban halts trading. → Mitigation: Phase 0 (channel fix + per-UID/endpoint caps) BEFORE fan-out; gated fan-out; feasibility pre-flight; near-ban detector; default sequential.
- **R-3 (High, Med):** Pool exhaustion orphans a placed order (live position, no DB row). → Mitigation: pool-aware sizing, reserved write connection / bounded retry, guaranteed recovery record.
- **R-4 (High, Low):** Cancel/restart mid-tail orphans a position without TP/SL. → Mitigation: shield order→stop; tail-in-progress resume; cleanup skips interrupted accounts.
- **R-5 (Med, Med):** WS/state-sync flicker or a silently-broken polling fallback on ScannerPage. → Mitigation: poll-through-tail fix (FR-018), reconciliation precedence, single renderer, cold-load fallback.
- **R-6 (Med, Low):** The channel/limit changes regress existing non-tail Bybit flows. → Mitigation: steady-state regression tests; runtime kill-switch per change.
- **R-7 (Med, Low):** Scope bloat destabilizes a money path. → Mitigation: MoSCoW partition; SHOULD/WON'T deferred to a tracked backlog.
- **R-8 (Low, Low):** WS feed leaks account labels / trade intent. → Mitigation: opaque handle, scrubbed payloads, strict origin + existence check, loopback boundary documented.

## W. Assumptions

- **A-001** — Cross-account work is independent and safe to parallelize with within-account ordering preserved. Risk: Low. Reason: separate BybitClient/UID/state; `traded` keyed `(account_id,symbol)`. Impact if wrong: double-placement → caught by golden test + default=1.
- **A-002** — The tail-in-progress sub-state can reuse existing schema (no migration). Risk: Medium. Reason: `status` already gates resume. Impact if wrong: an additive-nullable migration (R181) is added in planning.
- **A-003** — The existing `feature_kill_switches` mechanism can gate the three changes at runtime. Risk: Low. Reason: it exists and is DB-backed/fail-closed. Impact if wrong: env-flag fallback (requires redeploy to flip).
- **A-004** — Mirroring the backtest WS pattern is sufficient for scan progress. Risk: Low. Reason: proven, richer-schema superset. Impact if wrong: extend the manager.
- **A-005** — Single egress process (rate gate is per-process). Risk: Medium in multi-replica deploys. Reason: discovery §5. Impact if wrong: document constraint; cross-process coordination is WON'T-now.

## X. Open Questions

- **Q-001:** Does the tail-in-progress sub-state reuse `status='running'` or a new nullable column? Why it matters: resume correctness vs migration. Recommended default: reuse `status` semantics (keep running until tail joins), confirmed in Step 10 plan-validation. Impact if unanswered: deploy-mid-tail abandons a partial tail.
- **Q-002:** Default-raised concurrency width for the speedup benchmark target (e.g. 3 or 5)? Why: sets NFR-001 numbers. Recommended default: derive from feasibility (≤480/5s ÷ ~7 req/placement) → start at 3. Impact: benchmark target undefined.
- **Q-003:** Per-UID order cap — assume the 10/s safe floor for all accounts, or detect Linear-20/s? Recommended default: 10/s floor (fail-safe). Impact: marginally lower throughput, far safer.

## Y. Traceability Matrix (summary; full matrix maintained in the plan)

| Req (MUST) | Spec FR/NFR | Phase | Tests |
|---|---|---|---|
| R60/R65/R61/R169 | FR-001/002/003/004 | 0 | rate-gate unit + regression |
| R1-R12 | FR-010/011/012/013/014 | 1 | WS unit + replay |
| R14-R28,R164* | FR-015..024 | 1 | frontend hook/panel tests |
| R29-R58 | FR-025..036 | 2 | golden-equality + concurrency |
| R126-R140,R183 | FR-036/037/038/039 | 2 | persistence/pool/resume |
| R151/R179/R196 | NFR-001/011 | 3 | benchmark + DoD gate |
| R79-R90,R195 | FR-041/042 | 3 | component tests |

## Z. Definition of Ready

- [x] Scope clear (MoSCoW partition; in/out/future explicit).
- [x] Requirements testable (FR/NFR mapped to ACs).
- [x] Edge cases documented (Section S).
- [x] Codebase impact understood (Section M, discovery).
- [x] Dependencies identified (Phase 0 → Phase 2 sequencing).
- [x] Risks documented (Section V).
- [x] Acceptance criteria measurable (Section U).
- [ ] No unresolved Critical/High findings — pending Step 5 spec review.

---

## AA. Spec Review R1 — Findings & Resolutions

Round 1 (5 agents, code-verified) raised ~74 findings. Critical/High resolutions below are AUTHORITATIVE and override the earlier FR text where they conflict. Mediums/Lows folded into the plan are noted.

### Critical resolutions

**CR-1 — `orderLinkId` idempotency was FALSE; placement idempotency redefined.** *(backend F1, product F7, qa F2)*
Verified: every order-create mints a fresh uuid `orderLinkId` (`bybit_client.py:449`) and `retry_on_network_error=False` (`:469`), so the unique `idx_trades_order_link_id` cannot dedup a re-placement, and the only real backstop is the fail-open live-position re-check (`auto_trade_service.py:1683-1691`).
**Resolution:** (a) Generate a **deterministic, replayable `orderLinkId`** keyed on `(scan_id, account_id, symbol)` (stable across resume/retry) and write it to `pending_intents` BEFORE submit; reuse the SAME value on any resume/retry so Bybit's own `orderLinkId` uniqueness rejects a duplicate. (b) The live-position re-check remains the secondary backstop. (c) FR-033/036/038/039 are amended: the resume/orphan idempotency key is **`orderLinkId`** (always present, deterministic), NOT the exchange `order_id`. Update **FR-033, FR-036, FR-038, FR-039**.

**CR-2 — Per-UID rate limiter: key on internal `account_id`, not a Bybit UID we never resolve.** *(security F1, backend)*
Verified: `test_connection` returns `uid: None` (`bybit_client.py:232`) → `bybit_uid` is persisted as None; no UID-resolution endpoint exists.
**Resolution:** Key the per-UID/per-endpoint sub-limiter on the **internal `account_id`** (the part before the `_i` config suffix), which maps 1:1 to a `BybitClient`/credential set = one Bybit UID. This is implementable with no new Bybit endpoint. Residual risk (two distinct `account_id`s configured with the SAME real API key → same real UID, sharing the per-UID cap but counted as two) is **accepted/low** (pathological config) and documented. Update **FR-003** ("keyed on the internal `account_id`"). Remove the "resolve the real Bybit UID" claim.

**CR-3 — Feasibility/ceiling math under-counted; recompute on worst case.** *(security F2, backend F10)*
Verified: `place_market_order` internally calls `_poll_order_fill` (up to 7 `/v5/order/history` calls, `bybit_client.py:491,501`), so one placement ≈ 2 (mark+instrument) + set_leverage + create + **up to 7 polls** + set_trading_stop ≈ **12-13 calls** worst case (not 6-9); and the per-client `Semaphore(10)` is **per-account**, so N parallel accounts admit up to **10·N** concurrent gate acquirers.
**Resolution:** NFR-002 and FR-037 recompute on **worst case**: ceiling ≈ 480/5s (96/s) ÷ 13 ≈ **~7 placements/s**; the pre-flight feasibility projects **peak = 10·N + background consumers (reconciler/AI-manager/evaluator)** and auto-reduces concurrency so a fully-polling burst stays ≤480/5s. The benchmark default width (Q-002) starts at **2** (conservative), not 3. Update **NFR-002, FR-037, Q-002**.

**CR-4 — A true combined-IP ceiling must exist (or budgets pinned).** *(security F6)*
Verified: the gate keeps two independent deques (public/private); the only structural bound is the sum of per-channel maxes; there is no 600/5s combined counter, and FR-006's ≤480 "operating target" is enforced by nothing.
**Resolution:** Pin `public_max + private_max ≤ 540` numerically (keep public=400, private=100 → 500, headroom to the 600 ban line) AND add a **combined-IP counter** (one derived count of public+private timestamps within 5s) that hard-stops at 540 inside the same critical section. The bound `_poll_order_fill`/`get_positions` multipliers count against it. Update **FR-006**; add **FR-006a** (combined counter).

**CR-5 — Golden-equality test strengthened (the central regression net).** *(qa F1/F2/F3/F4, product F1/F14)*
Verified: "order set + counts" is blind to (a) within-account ordering/slot-selection under `max_trades`, (b) per-order payload (size/leverage/TP/SL/reduceOnly/orderLinkId), (c) close-rule create/delete lifecycle, (d) the mock's own race-free recording.
**Resolution:** The golden test asserts, parallel-vs-sequential under the deterministic mock:
1. **Per-account ORDERED sequence** of placements (list, not set), in merge order.
2. Each placement's full tuple `(account, symbol, side, size, leverage, tp, sl, reduceOnly, orderLinkId)` exactly equal.
3. The set of close rules **created** (`created_rule_ids` + types/params) AND **deleted** by `cleanup_unused_rules` equal.
4. Per-account `trades_executed/failed/skipped` equal.
The mock `BybitClient` uses deterministic per-symbol market data, a deterministic `order_id` derivation (or excludes it from compare), and a **concurrency-safe per-account-ordered** recording structure with a self-test under forced interleaving. Update **Section T (golden)**, **NFR-003** (exact equality of the above; the `<1%` project bar applies to live-latency wall-clock fidelity, NOT the golden assertion which is exact-0%).

**CR-6 — The poll/WS/mount predicate needs a scan-sourced config signal.** *(frontend F1)*
Verified: `_serialize` omits `auto_trade_configs`; the frontend's only `autoTradeConfigs` is local localStorage → wrong on cold-load/reload, reintroducing the R164a freeze.
**Resolution:** Add a config-derived scalar **`auto_trade_config_count: int`** (and/or `has_auto_trade_configs: bool`) to BOTH `_serialize` (~1118) and `_serialize_db` (~1153), sourced from `scan["config"]["auto_trade_configs"]`, and to the frontend `ScanStatus` type — the canonical R173 lockstep example (no new DB column; AD5 preserved). FR-018/FR-019 predicates read THIS, never local state. Update **FR-018, FR-019, FR-014, Section K**.

**CR-7 — Canonical global lock-ordering (deadlock prevention).** *(product F10, backend F2, qa F5)*
Verified: `position_lock_registry` (an asyncio.Lock held across awaits incl. the `create_trade` DB write) × the asyncpg pool (max 10) can cycle with the reconciler/evaluator; no canonical order is specified.
**Resolution:** Mandate the canonical acquisition order **account-semaphore → per-`(account,symbol)` position-lock → per-client `Semaphore(10)` → rate-gate (leaf, await-free) → DB-pool**, and the invariant **"never block on the asyncpg pool while holding a position-lock"** (acquire the pool connection for the trade-row write so it does not deadlock against a pool-holding subsystem that then waits on the same position-lock — or release the lock before the terminal write if safe). Add **FR-004a / NFR-006** clause; add a test asserting no path inverts the order.

### High resolutions

**HR-1 — Ban-time safety: registry-lock held across a paused gate starves the protective close.** *(qa F5/R167-R168, product F4-F5)*
Under a Phase-3-deferred ban breaker (R74 is SHOULD), a tail task parked in the gate while holding a per-`(account,symbol)` registry lock would block `CloseRuleEvaluator`'s emergency close for the ban window. **Resolution:** (a) Promote the **basic ban circuit-breaker (R74) + near-ban detector (R186b)** into the MUST scope, sequenced into **Phase 0** (it is rate-gate behavior). (b) The gate's `acquire_async` wait-loop polls the breaker/kill-switch each iteration and, on an active ban, **fails fast with a distinct abortable outcome** so the caller releases the registry lock and re-queues (never pins a lock across a ≥10-min pause). (c) `CloseRuleEvaluator`'s protective path is not gated behind a tail-held placement lock during a ban. Add **FR-047** (ban breaker + lock-release-on-ban). Move R74/R186b from SHOULD→MUST.

**HR-2 — R135/R139 (resume idempotency + write boundary) mis-partitioned as SHOULD; promote to MUST.** *(product F9)*
R183 (MUST) depends on R135 idempotency; without it, resume double-places. **Resolution:** Re-classify **R135, R139, R136/R138 (intent-row dedup)** into MUST (Phase 2). R134 (scheduler single-flight vs breaker) stays SHOULD but is noted as a real money path. Update the MoSCoW partition + FR-036/FR-039 dependency note.

**HR-3 — Resume durability is incoherent with "no schema change"; use `trades`/`pending_intents` as the source of truth.** *(backend F3, product F9)*
Verified: `auto_trade_results` is written only at the final `update_scan`; `_append_auto_trade_results` mutates in-memory only; on a mid-tail crash all partial results + `_AccountState` are lost. **Resolution:** The resume reconciliation source is the **durable `trades` table + `pending_intents`** (written per-placement, `trade_repository.py:140-156`), NOT the in-memory results buffer. On resume of a tail-in-progress scan: re-derive already-placed orders from `trades`/intents by the deterministic `orderLinkId` (CR-1), skip them, finalize the rest. The tail-in-progress sub-state (FR-039) marks the scan resumable; **Q-001 is now blocking and answered in plan-validation (Step 10)** — default: keep `status='running'` until the tail joins (no migration). Update **FR-036, FR-039, Section N, A-002 (downgrade to resolved-in-plan)**.

**HR-4 — WS existence/close-code oracle; identical close path for unknown vs empty.** *(security F8, product F6)*
**Resolution:** Use ONE identical close path (same code, same/no payload, same timing) for unknown-scan AND known-but-empty-scan; do NOT mirror `ws.py`'s `{"type":"error","message":"Run not found"}` + distinct 4404 branch. Origin policy mirrors `ws.py`'s **reject-missing-Origin** but with **exact-origin match** (drop `ws.py`'s port-only fallback) for this money feed. Update **FR-012, Section K** (remove the distinct 4404 for unknown scan).

**HR-5 — Operator-control trust boundary: gate on the TCP PEER (loopback), not the server bind; handle the proxy.** *(security F4/F5/F10/F11)*
Verified: the app runs on a trusted-LAN bind (non-loopback is normal), and requests arrive via the Vite proxy (so `request.client.host` is the proxy). "Fail closed on non-loopback bind" would self-disable the control. **Resolution:** Gate each operator request on the **TCP peer address being loopback** (independent of bind), PLUS a shared-secret/token for the privileged width-override + kill-switch (they are ban-inducing), PLUS audit+alert on every flip. For the proxy: trust `X-Forwarded-For` only from an allow-listed proxy IP, else require the admin surface to bypass the proxy. The principal is transport/token-derived, not the body `updated_by` (deprecate-but-accept the field for back-compat; record the API-shape note in Section K). Update **FR-046**, add the back-compat note to **Section K**.

**HR-6 — Event schema is missing fields the panel's own FRs require.** *(frontend F2/F3/F4, security F7)*
**Resolution:** The `ScanAutoTradeProgressEvent` Pydantic model (FR-014) carries typed fields: `side`, `reason_code` (ENUM from `strategy_reason_codes.py`, not free text), cumulative per-account `trades_executed/failed/skipped`, a stable per-scan account **ordinal** (`acct_ordinal`) that is ALSO stamped onto each `auto_trade_summaries` row (additive) so the opaque-handle live rows deterministically join to terminal summaries (resolves FR-023↔FR-021), `dry_run` (or via the scan-level config field, CR-6), and numeric `cooloff_seconds`/`cooloff_until`. Free-text `detail`/`label` are advisory/log-only; the frontend derives ALL display copy from `stage`/`status`/`reason_code` codes via one frontend map (R165d). Account identity = per-scan ordinal (or per-scan-salted hash — never a stable cross-scan hash). Update **FR-014, FR-016, FR-021, FR-023, FR-045, Section K**.

**HR-7 — Frontend reconnect/teardown divergences from the reference hook.** *(frontend F9/F7/F5/F14)*
**Resolution:** `useScanAutoTradeProgressWS` intentionally DIVERGES from `useBacktestProgressWS`: (a) onclose reads `event.code` and does NOT reconnect on permanent codes (4403/4404/1011), only transient (1006/1005); (b) the scanId-change reset clears ALL exposed state (`steps, accounts, orders, pct, terminal, connected`) and a `currentScanIdRef` drops prior-scan events in onmessage; (c) the hook guard-parses every payload (validate against the typed schema) so malformed data never reaches state — drop+warn — keeping render pure for the error boundary; the hook mounts INSIDE the error boundary so the fallback also tears down the socket. (d) Monotonic counts apply to the LIVE polling phase only; the terminal `scanQuery` snapshot REPLACES (even if lower). Update **FR-015, FR-017, FR-020**.

**HR-8 — Steady-state regression of non-tail flows from the channel fix is real (not a no-op); test per-subsystem.** *(security F12, qa F12)*
The channel fix moves all market reads private→public system-wide, raising max combined-IP concurrency. **Resolution:** NFR-010 is operationalized into per-subsystem regression tests (dashboard/reconciler/evaluator/cycle-engine/AI-manager/MCP each still charges the correct channel, no new throttle/latency) + the combined-IP ceiling test (CR-4). Promote the **MCP-lane non-starvation guard (R163) into MUST**. Add an **AC for NFR-010**.

### Structural / medium fixes folded into the plan
- **init_balances loop ordering (backend F7):** parallelize WITHIN each of the two loops; loop1 (force-close + populate `force_closed_accounts`) must fully JOIN before loop2 (which reads it) starts — a hard barrier. Update FR-031.
- **`refresh_configs` is a second `self._state` writer (backend F5):** the invariant "no config refresh overlaps the fan-out" is explicit; the orchestrator drains/forbids refresh during `run_post_scan_tail`. Update FR-030.
- **MR cache stampede (backend F6, qa):** pre-warm `_mr_mean_cache`/`_mr_price_cache` single-threaded before fan-out (or per-key in-flight future); FR-037's request projection accounts for any residual dedup loss. Update FR-030/FR-037.
- **Orchestrator injects persist-strategy + owns single-flight (backend F8):** the two call sites differ in persist order/guard; the orchestrator takes an injected persist-callback + the canonical persist→summaries→terminal order, and FR-026 single-flight lives in the orchestrator so BOTH paths participate (the auto path currently has no such guard). Update FR-025/FR-026.
- **Shield boundary is in `accounts_service.place_trade` (backend F9):** add `accounts_service.py` to Section M; FR-043 specifies the shield spans set_leverage→place_market_order→set_trading_stop.
- **Shutdown drain (qa, integration):** graceful shutdown bounds the shielded order→stop→commit within the 15s `_SHUTDOWN_TIMEOUT` or flushes every placed order to a recovery record before exit (R182). Add FR-048.
- **=1 exact-sequential path (backend F13):** at width 1 use await-in-`self._state`-insertion-order (no `gather`+Semaphore(1)), so it is the golden oracle. Update FR-032.
- **`_do_sync_time` off-loop (backend F14, security F16):** the now-gated time-sync uses a non-loop-blocking path / dedicated high-priority lane so a saturated gate never starves it (stale clock → 10002). Update FR-002.
- **Startup config validation (product F18):** add FR-049 — at startup compute worst-case 5s peak from (concurrency × worst-case per-placement cost) and fail-closed/clamp if >540/5s.
- **Edge cases added to Section S (qa F10/F11/F22, product F21):** multi-client/slow-consumer/no-client-connected; exactly-50%-failure boundary; R104 history-truncation-retains-terminal; R109 crash-resume slot-reset over-placement (document the accepted pre-existing exposure under parallelization); R110 `executions=[]` reset vs cumulative buffer; mock-vs-real-Bybit fidelity risk (add to Section V).
- **AC/test coverage (qa F9):** add ACs+tests for FR-002, FR-005, FR-006/006a, FR-007, FR-009, FR-026, FR-037, FR-040, FR-045, FR-046, FR-047, FR-048, FR-049, NFR-010.
- **Doc hygiene (product F22-F24, frontend F11-F13):** Section C scheduled-path durable-record → Future Scope; AD1 caveat (mirror structure, adopt stricter origin/existence than ws_backtest); traceability matrix annotate SHOULD sub-Rs; NFR-012 enumerate which WS-util copies migrate now vs deferred; FR-022 reword to "terminal+cold render from scanQuery, identical" (not live≡cold mid-stream).

### Spec axes affirmed SOUND (no change)
- Account-axis partitioning + process-wide default-1 limiter (no double-place on the partition axis).
- Phase ordering rate-gate→WS→parallelism→UX (the R125 prerequisite honored; ban-breaker pulled into Phase 0 by HR-1).
- Order/leverage/stop per-UID caps (≤8/s under Bybit's 10/s floor) — conservative-correct.
- Fail-open emit / None-safety (AD4, FR-044) — backtest path explicitly green.
- The all-or-none multi-dimension acquire is implementable without gate deadlock (one await-free critical section), given the lock-ordering (CR-7) and combined-max() backoff.

**Outcome:** All Critical (CR-1..7) and High (HR-1..8) findings have a written resolution that amends the named FRs and the MoSCoW partition. These resolutions are inputs to Step 6 (plan) and Step 10 (plan-validation, where Q-001/Q-002 are finalized against current code). Round 1 is recorded; per LITE mode, Rounds 2-3 will verify the resolutions and surface residual gaps.

---

## AB. Spec Review R2 — Consolidated Resolutions (SUPERSEDES Section AA where they conflict)

Round 2 (5 agents, code-verified) found that several R1 resolutions were themselves incoherent against the real schema/code, and that the by-reference amendments left inline FR text contradicting them. **Precedence:** Section AB > Section AA > original Sections F-Z. The corrected decisions below are FINAL inputs to the plan.

### SCOPE DECISION (key) — de-scope the durable crash-resume idempotency system

R2 verified CR-1's "deterministic `orderLinkId` written to `pending_intents`" is **impossible** (`pending_trade_intents` PK is `(account_id,symbol,side)` — no `order_link_id`/`scan_id` column; `async_persistence.py:1585`), that there are **two unreconciled uuid mints** (`bybit_client.py:449` + `trade_repository.py:140`), that the executor has **no `scan_id`**, and that the whole mechanism addresses **crash-resume double-placement, which is PRE-EXISTING (R108/R109)** — not introduced by parallelization. The parallelization double-place risk is already covered by golden-equality + the live-position re-check + default concurrency=1.

**Decision (SC-1):** **DE-SCOPE the deterministic-orderLinkId / tail-in-progress / trades-table-reconciliation resume system to the backlog (WON'T-NOW).** Replace with the minimal, sufficient guard:
- **SC-1a:** Crash-resume behavior must be **no worse than today**. Today's sequential tail already has the R108/R109 exposure; parallelization at default=1 does not change it. Document R108/R109 in Section S as an **accepted pre-existing exposure**, explicitly NOT regressed.
- **SC-1b:** Incremental persistence (FR-036) is **replace-by-stage**, not append: each stage writes the cumulative `auto_trade_results` for that scan (idempotent overwrite), so a resume that re-runs a stage cannot double-count the JSON array. No new column, no deterministic-key write-ahead.
- **SC-1c:** Orphan-on-pool-timeout (FR-038): on a `create_trade` pool timeout AFTER an order is placed, log a HIGH-severity structured `orphan_order` record (existing logging, no new table) carrying `(account_id, symbol, side, exchange order id if known)` so the existing `position_reconciler` adopts the live position on its next tick (it already reconciles positions↔trades). This is the existing reconciliation path, not a new write-ahead log.
- **SC-1d:** CR-1, CR-1's `pending_intents` write, HR-3's trades-table resume re-derivation, FR-039's tail-in-progress sub-state, and Q-001 are **WITHDRAWN** from MUST. The existing `resume_incomplete_scans` (status='running' only) behavior is unchanged. R135/R139 return to SHOULD/backlog.

This removes the entire CR-1/HR-3/R2-F1..F6/F9/F12/F15 incoherence cluster and keeps the change focused on the 4 goals.

### Corrected rate model (R2-F1/F2 security, the binding constraint)

R2 verified placements are **PRIVATE-channel-bound**, not IP-bound: after the FR-001 channel fix, of ~12-13 calls/placement only 2 are public (mark+instrument); the rest (set_leverage, order/create, up to 7 fill-polls, set_trading_stop ≈ 10-11 calls) stay **private**. The private budget is **100/5s = 20/s process-wide** (`bybit_rate_gate.py:18`). Aggregate placement rate ≈ 100/5 ÷ ~10 ≈ **~2 placements/s across ALL accounts** — the private sub-budget saturates long before the IP 480.

**Decision (SC-2):**
- **SC-2a (NFR-002 corrected, supersedes the "13-14 placements/s" text):** the throughput ceiling is **private-channel-bound ≈ ~2 placements/s aggregate** (20/s private ÷ ~10 private calls/placement); cross-account parallelism's real win is **hiding per-call RTT latency** (today each account serially pays full network RTT per call) up to the private cap, then it **plateaus hard**. Adding accounts beyond the plateau does not reduce wall-clock. NFR-001's "measurable speedup at N≥5" is reframed: the win is **latency-hiding** (a tail dominated by serial RTT becomes RTT-overlapped up to the 20/s private ceiling), NOT raw throughput beyond the gate.
- **SC-2b (FR-037 corrected):** the pre-flight feasibility projects the **PRIVATE-channel 5s load** (not IP), auto-reducing concurrency so private stays ≤ ~80/5s (80% of 100) AND combined-IP ≤480/5s. Worst-case peak uses **10·N** concurrent acquirers (per-account `Semaphore(10)`) and the 7-poll fill multiplier.
- **SC-2c (FR-006/006a corrected, supersedes CR-4's inert 540 counter):** keep public=400 + private=100 pinned (combined ≤500 < 600 ban line — structurally enforced by the two per-channel caps, which is sufficient; the separate "540 combined counter" is **dropped as redundant/inert**). The ≤480 "operating target" is **informational/observability** (the near-ban detector), not a second gate mechanism. The real protections are the per-channel caps + the per-`account_id`/endpoint sub-limiter + the feasibility auto-reduce.

### Lock-order arbitration (R2-F6 — CR-7 self-contradiction)

CR-7 named both "pool is the leaf (acquired UNDER the position-lock)" and "never block on the pool while holding a position-lock" — mutually exclusive; the trade-row write under the lock is what closes the orphan window.

**Decision (SC-3, supersedes CR-7):** Keep the trade-row write **under** the per-`(account,symbol)` position-lock (atomicity wins; pool is the leaf). Deadlock-freedom is achieved by the **dual invariant**: NO subsystem (`position_reconciler`, `close_rule_evaluator`, `ai_manager_task`, the tail) may acquire a position-lock **while already holding** a pooled DB connection — they acquire the position-lock FIRST, then the pool connection, in the canonical order **account-sem → position-lock → client-`Semaphore(10)` → rate-gate (critical section is O(1)/await-free) → DB-pool**. Add a test-only lock-rank validator (task-local held-rank stack; pool-acquire asserts no position-lock rank is "above" it via a held-lock registry). This is enforceable and the audit during planning verifies the reconciler/evaluator already obey it (or fixes them).

### New FRs (now NORMATIVE — R2-F3 found they only lived in prose)

- **FR-047 (Ban breaker, Phase 0):** the gate detects a confirmed IP ban (repeated 10006 after retry) and opens a process-wide circuit breaker pausing egress for the ban window; `acquire_async` AND `acquire_sync` poll the breaker each wait iteration and raise a distinct `RateGateBanAbort` so a caller **releases any held position-lock and re-queues** (never pins a lock across the ≥10-min pause); breaker recovery is **half-open** (single probe, then ramp 1→2→4), not a thundering-herd release (R2-F9). `CloseRuleEvaluator`'s protective close is never gated behind a tail-held placement lock during a ban. AC: 10·N parked tasks at ban-expiry keep post-recovery 5s egress ≤ caps.
- **FR-048 (Shutdown drain, Phase 2):** graceful shutdown bounds the shielded order→stop→`create_trade` commit within the 15s `_SHUTDOWN_TIMEOUT`, or logs the `orphan_order` record (SC-1c) before exit; never SIGTERM out mid-shield-pre-commit.
- **FR-049 (Startup validation, Phase 0/3):** at startup compute worst-case 5s **private + combined-IP** peak from (max-configured concurrency × worst-case per-placement private-call cost incl. 7 polls); **fail-closed/clamp** if private >80/5s or combined >480/5s; documented safe ranges; operator-only config.
- **FR-004a (Lock-order, Phase 2):** the canonical acquisition order (SC-3) is mandated; a test-only validator asserts no path inverts it.
- **FR-006a (Per-channel pin, Phase 0):** assert `public_max + private_max ≤ 500`; the per-`account_id`/endpoint sub-limiter (FR-003) is the per-UID protection; (the standalone combined counter is dropped per SC-2c).

### Frontend residual fixes (R2 frontend agent)

- **FF-1 (R2-F2/F8 — predicate stuck-active):** CR-6's `auto_trade_config_count>0` is true even when the executor never ran (accounts service unavailable at scan start) → the FR-019 predicate would be permanently "active" → cold-load opens a WS to a dead scan. **Add a terminal signal:** the predicate also requires that a tail is plausibly running — gate on `auto_trade_config_count>0 && auto_trade_summaries absent && (a fresh `auto_trade_attempted` flag is unset OR the scan completed within an upper time bound)`. Simpler: the auto path always writes `auto_trade_summaries` (even empty `[]`) at tail finalization when an executor was constructed; when NO executor ran, summaries stay absent but the **upper time bound** (FR-019) closes the socket. On `_serialize_db` config-parse failure, fall back to a presence check via the frozen columns, not count=0.
- **FF-2 (R2-F5 — AI-manager reduced-protection):** the single-renderer suppression (FR-017) covers ONLY the executions + account-status sub-blocks (`ScannerPage.tsx:1190-1234`); the AI-manager "reduced protection" notice (`1236-1251`) is **left rendered** (or reproduced in the panel). Never suppress a money-safety surface. Update FR-017 to name the exact range `1190-1234`.
- **FF-3 (R2-F3 — acct_ordinal 1:many):** `acct_ordinal` is **per distinct `account_id`** (not per `_state` entry); the terminal handoff **sums** the N summary rows that share one `account_id` into the one live row. Stamp `acct_ordinal` on each `auto_trade_summaries` row (JSON field, passes opaquely through both serializers — no dual-serializer edit needed) and derive it from one shared per-scan account enumeration used by BOTH the event emitter and `get_summaries`. The over-the-wire handle is a **per-scan-salted** form (salt discarded at GC), not a stable cross-scan ordinal (R2-F7); the raw ordinal stays server-side for the join only.
- **FF-4 (R2-F8 lane / R2-F4 security):** `set_trading_stop` + the post-create fill-polls use **lane="order"** (they complete an open position — must not starve behind the order lane on the private channel); free-text `detail`/`label` are **omitted from the emitted WS payload** (log-only server-side) — the frontend renders only from `stage`/`status`/`reason_code` enums (R165d); this closes the raw-error-string leak (R2-F8 security).

### Coherence cleanups (architecture agent — to apply when writing the plan)
- The original inline text of FR-003 ("real Bybit UID"), FR-006 ("600 ceiling"), NFR-002 ("13-14 placements/s"), Section G Phase-0 scope, Section K (distinct 4404), Section M (add `admin.py` + `accounts_service.py`; the new endpoint uses exact-origin not ws.py's port fallback), Section Y traceability, and the MoSCoW partition (promote R163; R74/R186b were already MUST under R59-R78/R184-R186; R135/R139 RETURN to backlog per SC-1) are **superseded by AB** — the plan reflects AB's values, and Step 6 writes the plan against AB, not the stale inline text.
- The DoR "Requirements testable" box stays UNchecked until the new FRs (FR-047/048/049/004a/006a) and the AC-gap FRs have ACs — added in the plan's per-task acceptance criteria.

### R2 affirmed SOUND
- CR-2 (key on internal `account_id`) — verified 1:1 `account_id`↔client↔credential (`accounts_service.py:205-223`); residual re-rated to **Medium** (two account_ids on one real UID → per-UID 10006), mitigated by FR-049 startup warn.
- CR-6 source path (config derived at serialize from the persisted config JSON; retroactive for old scans; no migration) — sound.
- HR-7 hook divergences — implementable.
- `max_same_sector`/`max_same_direction` — prior R3 brainstorm verified these read per-`_AccountState` state (`existing_symbols`/`position_directions`), GIL-safe, never lock-dependent (Round-3 requirements NOTE). The golden test will still seed a binding sector cap to prove no cross-account overshoot (QA R2-F5).

**Outcome:** the rate model is corrected (private-bound), the idempotency over-reach is cut (SC-1), the lock-order is arbitrated (SC-3), the missing FRs are normative, and the frontend predicate/leak/ordinal gaps are closed. Round 3 verifies these and the plan is built from Section AB.

---

## AC. Spec Review R3 — Final Corrections (PLAN-READY; SUPERSEDES AB where they conflict)

Round 3 (3 agents, code-verified) returned verdict **PLAN-READY**: all contested points resolve to one value under precedence. These final corrections (precedence AC > AB > AA > F-Z) close the last code-verified gaps. The plan (Step 6) is written from the effective AC values.

- **AC-FIX-1 (orphan handling — SC-1c was FALSE).** Verified: `position_reconciler` reconciles trades→positions and, on a position with no trade row, **only logs `ORPHAN_POSITION_DETECTED` + WS alert; it NEVER auto-adopts** (`position_reconciler.py:215-245,:224`). **Correction:** SC-1c is reworded — on a `create_trade` pool-timeout after an order is placed, log a structured `orphan_order` record (existing logging) which surfaces via the EXISTING orphan-detection alert → **manual intervention** (NOT auto-adopt). The position is generally still protected because `place_market_order` carries `takeProfit`/`stopLoss` **inline at creation** (`bybit_client.py:461-470`), so there is no naked position. The untracked-orphan window is documented in Section S as an **accepted pre-existing exposure, NOT regressed** (parity with R108/R109). No new adoption code, no new table.
- **AC-FIX-2 (FR-049 formula — under-counted, security R3-F1).** The startup/feasibility projection uses the **sustained** rate, not one-placement-per-window: private 5s load ≈ `W_accounts × ceil(5s ÷ min-placement-latency) × private-calls-per-placement` (≈ `20·W` at ~2.6s/placement), clamped on the LARGER of this sustained figure and the burst figure (`10·N` acquirers). Clamp targets: private ≤80/5s, combined-IP ≤480/5s. Disambiguate "concurrency" = W distinct accounts in flight.
- **AC-FIX-3 (shared-UID residual — security R3-F2).** FR-049 ALSO detects, at startup, two account configs sharing the same `api_key`/credential (→ one real Bybit UID → per-UID 10006 risk since each gets its own 8/s bucket = 16/s > 10/s floor) and **warns + clamps** (sum their per-endpoint budgets under one key) OR the operator is instructed never to split one UID across account_ids. The CR-2 residual is **Medium** (ban consequence), now actually mitigated (not merely asserted).
- **AC-FIX-4 (operator-control text — security R3-F3).** The D14/HR-5 decision is FINAL and overrides the stale inline FR-046/NFR-009/Section-P "non-loopback bind" wording: gate on **TCP peer address = loopback** (independent of bind) + shared token (for the ban-inducing width-override + kill-switch) + allow-listed-proxy XFF; principal is transport/token-derived (deprecate-but-accept body `updated_by`). **`admin.py` and `routers/ws.py` are added to Section M's modified set**; the new WS endpoint uses **exact-origin** match (NOT ws.py's port-only fallback). **Scope note:** the loopback-peer gate is MUST; the shared token MAY be SHOULD for the first ship (default concurrency=1 means the width-override is inert until opt-in) — finalized in the plan.
- **AC-FIX-5 (FR-047 ban breaker — mechanism pinned, security R3-F4).** Half-open recovery uses a **process-wide half-open admission counter/semaphore** (not a bool waiters re-check): on ban-expiry, admit K=1 for one full 5s window, on success ramp K→2→4 per subsequent window; probe-failure re-arms a fresh ban window. Both `acquire_async` AND `acquire_sync` poll the breaker and honor the admission counter (today `acquire_sync` has neither). Parked waiters acquire an admission token, so 10·N parked tasks cannot flood at recovery. AC: simulated ban-expiry with 10·N parked tasks keeps post-recovery 5s egress ≤ caps.
- **AC-FIX-6 (stale numerals/assertions — coherence R3-F1/F4/F5/F6, non-blocking).** The plan writes: NFR-002 = "~2 placements/s aggregate, private-bound; win is RTT latency-hiding up to the private cap, then plateau"; NFR-004 = "combined ≤500/5s structural; ≤480 observability-only" (drop "540"); AC-009 = "on restart mid-tail, no-worse-than-today (R108/R109 accepted), no NEW double-placement vs sequential" (drop FR-039 citation); NFR-001/AC-002 benchmark = "parallel < sequential at EACH N (RTT-overlap), curve flattens past the plateau" (assert vs same-N sequential, NOT monotonic-in-N); split MoSCoW "R182-R183" (R182=FR-048 MUST; R183=backlog); FR-049 validation LOGIC pinned to **Phase 0** (width>1 gated on it), operator docs to Phase 3.
- **AC affirmed SOUND (R3 code-verified):** SC-1b replace-by-stage (single writer per stage, post-join — no lost update); SC-3 lock invariant **holds in current reconciler/evaluator/ai_manager code — no pre-fix required** (reconciler never takes a position-lock; evaluator uses per-account debounce locks; AI-manager takes position-lock before pool); SC-2 private-bound model is ban-safe (combined 500 < 600) and the ~4-5× latency-hiding speedup at N=10 is real (Goal 2 NOT neutralized); FF-4 lane=order does not over-subscribe (lanes share one private deque; close is already lane=order; TP/SL inline at creation = no naked-position-during-ban window).

### Definition of Ready — FINAL
- [x] Scope clear (MoSCoW + SC-1 de-scope; tightly aligned to the 4 goals).
- [x] Requirements testable (FR/NFR mapped to ACs; the 5 new FRs get per-task ACs in the plan).
- [x] Edge cases documented (Section S + R108/R109/orphan accepted-exposure notes).
- [x] Codebase impact understood (Section M + admin.py/ws.py/accounts_service additions).
- [x] Dependencies identified (Phase 0 rate-gate+ban-breaker → Phase 2 parallelism).
- [x] Risks documented (Section V).
- [x] Acceptance criteria measurable (Section U + AC-FIX-6 rewrites).
- [x] **No unresolved Critical/High findings** — all CR/HR/SC/AC-FIX carry written resolutions; R3 verdict PLAN-READY.

**SPEC STATUS: FINAL — PLAN-READY.** Step 6 builds the plan from the effective AC > AB > AA > F-Z values.
