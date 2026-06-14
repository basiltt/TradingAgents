# Phase 2 — Bounded Parallelism + Data Integrity (MONEY-CRITICAL)

**Goal:** Parallelize the per-account post-scan tail under a process-wide bounded semaphore (default width **1**), preserving byte-identical trade behavior, and emit progress to the Phase-1 sink. This is the highest-risk phase — every task is TDD with the golden-equality test as the net.

**Requirements:** FR-025..040, FR-004a, FR-043, FR-044, FR-048, R29-R58, R126-R130, R166-R170, SC-1/SC-2/SC-3, AC-FIX-1/6.
**Depends on:** Phase 0 (rate-gate correct). **Ships:** default concurrency=1 (sequential path, byte-identical) — width>1 is operator opt-in after the DoD gate.

---

## Files
| File | Action | Purpose |
|---|---|---|
| `backend/services/auto_trade_service.py` | Modify | `progress` sink param; extract `run_post_scan_tail`; per-account partition/merge; parallelize 5 steps; lock-order; shield |
| `backend/services/post_scan_concurrency.py` | Create | Process-wide account-concurrency semaphore singleton + single-flight registry |
| `backend/services/scanner_service.py` | Modify | Call `run_post_scan_tail`; replace-by-stage persist; pass progress manager; emit cancel/terminal |
| `backend/routers/scanner.py` | Modify | `_run_auto_trade` calls the SAME orchestrator + progress + single-flight |
| `backend/services/accounts_service.py` | Modify | `place_trade` shield boundary (order→stop); accept the deterministic-nothing (resume de-scoped) |
| `backend/services/bybit_client.py` | Modify | `get_positions` page-budget already gated (Phase 0); confirm no extra |
| `backend/main.py` | Modify | Wire the concurrency singleton; pass scan_progress_manager into the tail |
| `tests/backend/test_post_scan_golden.py` | Create | **Golden-equality** (the central net) |
| `tests/backend/test_post_scan_concurrency.py` | Create | Race/deadlock/cancel/isolation/orphan tests |
| `tests/backend/test_post_scan_orchestrator.py` | Create | Both-call-sites + single-flight + persist-cadence |

---

## Tasks

### TASK-2.1 — Deterministic mock `BybitClient` for tests (R123, CR-5)
- **Notes:** A test double recording every placement in a **concurrency-safe, per-account-ordered** structure; deterministic per-symbol market data; deterministic `order_id` = pure fn of `(account_id, symbol)`; configurable per-call latency, 429/10006 injection (rate-aware: emits 10006 if observed call rate exceeds a configured per-account/IP threshold), and a configurable fill model (immediate-full / N-poll-then-full). Self-test: records identically under forced interleaving.
- **TDD:** the mock's own recording is race-free; rate-aware 10006 fires when un-throttled.

### TASK-2.2 — Inject `progress` sink + extract `run_post_scan_tail` (FR-025, FR-007 sink, R7/R8)
- **Notes:** Add optional `progress=None` to `AutoTradeExecutor.__init__` (mirror `_recorder` None-guard); a fail-open `_emit_progress(...)` helper (swallows all exceptions, never blocks). Extract the 5-step sequence (`init_balances` already ran pre-scan; the tail is execute_batch→fill→recheck→cleanup→summaries) into `async def run_post_scan_tail(self, results, *, persist_cb=None)`. Both `scanner_service._run_scan` (replace lines 1312-1369) and `scanner.py:_run_auto_trade` (replace 257-298) call it with an injected `persist_cb` (auto = incremental replace-by-stage; manual = same). Pass `scan_id` to the executor at construction (both sites) for emit context.
- **TDD:** both call sites invoke the single orchestrator (spy); emit is fail-open (forced-raising sink → execution byte-identical); identical persist cadence both sites.

### TASK-2.3 — Process-wide account-concurrency semaphore + single-flight (FR-026, FR-027, R129, R30)
- **Notes:** `post_scan_concurrency.py`: a module singleton `get_account_semaphore()` (an `asyncio.Semaphore(width)`, width from config default **1**) shared across auto tail + manual re-run + scheduled; and a `scan_id`-keyed in-flight set so an auto tail and a manual re-run for the SAME scan cannot run the tail concurrently (extend the existing `_in_flight_auto_trades`). Width read from config (FR-049-validated).
- **TDD:** width=1 → strict serialization; single-flight blocks concurrent same-scan tails.

### TASK-2.4 — Per-account partition/merge for execute_batch/fill (FR-028, FR-029, FR-030, FR-034, R32-R39)
- **Notes:** Refactor `execute_batch` (795) / `fill_immediate_remaining` (838): replace the executor-wide `self._lock` body with per-`account_id` tasks. Partition unit = **`account_id`** (one task owns ALL of an account's `_state` entries `f"{account_id}_{i}"`). Each task: iterate the shared read-only `unique_results` (sorted best-`|score|`-first) sequentially; maintain a **per-account-local** `traded` set + `executions` list; run `_fill_to_max` per-account using only its subset (remove the `self._lock.locked()` assert at 1312). Fan out tasks under `get_account_semaphore()` with `return_exceptions=True`; **merge AFTER gather reading from `self._state`** (NOT from gather return values — a cancelled child returns CancelledError; FR-035/R170) in deterministic `self._state` insertion order. Per-`_AccountState` (incl. `position_directions`, `mr_duration_rule_created`) is single-writer-per-task. Keep the per-`(account,symbol)` `_position_lock_registry` intact.
- **TDD:** golden (TASK-2.10); one-account-failure isolation (others complete); no double-placement; merge deterministic; `_AccountState` no cross-task write.

### TASK-2.5 — Lock-order + shield (FR-004a, FR-043, SC-3, R99)
- **Notes:** Enforce canonical order **account-sem → position-lock → client-Semaphore(10) → gate(O(1)) → DB-pool**; invariant "no subsystem acquires a position-lock while holding a pool conn" (verified true today — confirm in plan-validation, fix reconciler/evaluator only if violated). Add an `asyncio.shield` around the order→stop span in `accounts_service.place_trade` (set_leverage→place_market_order→set_trading_stop) so a cancel cannot orphan a position without TP/SL (note: TP/SL also inline at order create — defense in depth). Add a test-only lock-rank validator (task-local held-rank stack; pool-acquire asserts no position-lock rank held above it).
- **TDD:** cancel mid-order → shielded span completes, position has TP/SL; lock-rank validator catches an inverted path.

### TASK-2.6 — Parallelize init_balances, post_scan_recheck, cleanup, summaries (FR-031, FR-042, R40-R43)
- **Notes:**
  - `init_balances` (469-770): parallelize WITHIN each loop under the semaphore; **hard barrier** — loop1 (force-close, populates `force_closed_accounts`) fully JOINS before loop2 (reads it) starts. Parallel unit = `account_id` (account-keyed caches `positions_cache`/`account_valid_cache`/`marked_stopped_for` are per-account → one task per account owns them).
  - Pre-warm `_mr_mean_cache`/`_mr_price_cache` single-threaded before the fan-out (avoid stampede + preserve the per-symbol dedup the feasibility math assumes).
  - `post_scan_recheck` (1014+): parallelize the per-account loop under the semaphore (snapshot-under-lock-then-release stays).
  - `cleanup_unused_rules` (924) / `emit_account_summaries` (888): parallelize per-rule/per-account AFTER the gather joins.
  - `refresh_configs` invariant: the orchestrator forbids a config refresh during the fan-out (a generation guard / the existing pre-fan-out refresh call stays before launch).
- **TDD:** init_balances loop2 sees fully-populated force_closed (barrier); MR cache no stampede; recheck isolation; cleanup after join.

### TASK-2.7 — Replace-by-stage incremental persistence (FR-036, SC-1b, R56, R128)
- **Notes:** Change `_append_auto_trade_results` usage to **replace-by-stage**: each stage (post-join) writes the cumulative `auto_trade_results` for the scan as an idempotent overwrite (so a re-run of a stage can't double-count). Persist happens at the stage boundary (single writer, post-fan-out-join), NEVER inside the per-account fan-out. Final results commit BEFORE the terminal progress event (FR-036 ordering). Manual + auto paths use the same `persist_cb`.
- **TDD:** concurrent-stage-write no lost update; commit-before-terminal ordering; replace-by-stage idempotent.

### TASK-2.8 — Orphan-on-pool-timeout safety (FR-038, FR-048, SC-1c, AC-FIX-1)
- **Notes:** On a `create_trade` pool-acquire/command timeout AFTER an order is placed, log a structured HIGH-severity `orphan_order` record (existing logging; `account_id, symbol, side, exchange order id if known`) — this surfaces via the EXISTING `position_reconciler` orphan-detection alert (`ORPHAN_POSITION_DETECTED`) → manual intervention. The position is protected by the inline TP/SL at order create. Document in Section S as accepted pre-existing exposure (no new table, no auto-adopt — reconciler does NOT adopt). Shutdown drain (FR-048): bound the shielded order→stop→commit within the 15s `_SHUTDOWN_TIMEOUT` or log the orphan record before exit.
- **TDD:** injected pool-timeout after placement → orphan_order logged, no silent drop, no crash; shutdown mid-shield logs orphan.

### TASK-2.9 — Cancel + None-safety (FR-043, FR-044, R98-R100, R116-R117)
- **Notes:** Cancellation cooperative at safe points (between accounts/symbols), never mid-order (shield from TASK-2.5); a cancelled scan persists every order that hit the exchange + emits a terminal event. Backtest path (no `_close_svc`, no progress manager, `_position_lock_registry=None`, tracing off) runs the full parallel tail green.
- **TDD:** cancel mid-tail → clean stop, placed orders persisted, terminal emitted; full parallel tail green in backtest/no-services mode.

### TASK-2.10 — GOLDEN-EQUALITY test (CR-5, NFR-003, the central net)
- **Notes:** With the TASK-2.1 mock, assert parallel (width≥2) vs sequential (width=1) for the same inputs:
  1. Per-account **ORDERED sequence** of placements (list, in merge order).
  2. Each placement tuple `(account, symbol, side, size, leverage, tp, sl, reduceOnly, orderLinkId)` exactly equal.
  3. Close rules **created** (`created_rule_ids` + types/params, ordered) AND **deleted** by cleanup — equal.
  4. Per-account `trades_executed/failed/skipped` — equal.
  5. Per-account skipped `(symbol, reason_code)` ordered list — equal.
  Seed scenarios: multi-config-per-account, a binding `max_trades` (slot selection), a binding `max_same_sector`/`max_same_direction` (cross-account overshoot guard), `fill_to_max`, all-stopped, single account.
- **TDD:** this IS the test; must pass at width 1 and 2.

---

## Verification (Phase 2)
1. `python -m pytest tests/backend/test_post_scan_golden.py tests/backend/test_post_scan_concurrency.py tests/backend/test_post_scan_orchestrator.py -x -q`.
2. Full backend suite — no regression.
3. Manual (testnet): run a multi-account scan at width=1 (default) → identical to today; flip width=2 → faster, same orders.

## Completion criteria
- Golden-equality green at width 1 & 2; no double-placement/deadlock/lost-result under fan-out; failure isolation; replace-by-stage idempotent; orphan-safe; both call sites unified; backtest green; ships default width=1.

## Rollback
- Set account-concurrency width=1 (config or runtime kill-switch) → exact sequential path. The orchestrator extraction is behavior-neutral at width=1.

## Risks
- **Double-placement (Critical):** golden test + per-(account,symbol) lock + live re-check + default=1 + staged ramp.
- **Deadlock:** canonical lock order + rank-validator test.
- **Orphan:** inline TP/SL + structured log + reconciler alert.
