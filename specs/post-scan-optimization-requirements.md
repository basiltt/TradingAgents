# Requirements: Post-Market-Scan Optimization

**Feature:** Optimize the post-market-scan steps in the TradingAgents crypto trading system.
**Date:** 2026-06-14 · **Skill:** `/new-feature` · **Rounds Completed:** 1 (in progress)

## Feature Description

After a market scan finishes analyzing symbols, the system runs a sequential auto-trade tail on `AutoTradeExecutor` (`init_balances` pre-step → `execute_batch` → `fill_immediate_remaining` → `post_scan_recheck` → `cleanup_unused_rules` → `get_summaries`/`emit_account_summaries`) that places **real-money** orders on Bybit. Four goals:

1. **Live WebSocket status** of post-scan activity on the Scanner page — replace the 3s polling "one-shot at the end" view with real-time, stage-by-stage, per-account/per-symbol updates.
2. **Parallelize/optimize** the slow sequential per-account post-scan network I/O **without changing trade behavior** (money-critical; byte-for-byte identical orders/counts for identical inputs).
3. **Enforce Bybit non-VIP rate limits** via centralized semaphore-based controls (`BybitRateGate`) — fix public/private channel mis-assignment, add per-endpoint + per-UID limits, respect the 600/5s IP ceiling.
4. **Look-and-feel / UX** improvements across the Scanner page and the new live panel.

**Grounding — Bybit V5 non-VIP limits (fetched live 2026-06-14):**
- IP ceiling (all HTTP): **600 req / 5s (~120/s) per IP**. Violation → `retCode 10006` "Too many visits!" → **IP ban ≥ 10 min**.
- Order create `/v5/order/create`: 20/s Linear, **10/s UTA2.0 Pro & Inverse** (per UID) → enforce **10/s safe floor**.
- Order amend: 10/s; Order cancel: 20/s Linear / 10/s UTA2.0 (per UID).
- Position list `/v5/position/list`: **50/s** (per UID). Wallet balance: **50/s** (per UID).
- Set leverage `/v5/position/set-leverage`: **10/s** (per UID). Set trading-stop `/v5/position/trading-stop`: **10/s** (per UID).
- Market (tickers/kline/time): not per-UID-listed → bound only by the 600/5s IP cap (public/per-IP).
- Headers: `X-Bapi-Limit`, `X-Bapi-Limit-Status`, `X-Bapi-Limit-Reset-Timestamp`.

---

## Goal 1 — Live WebSocket Status [REALTIME / WS]

### Backend progress infrastructure
- R1. New `ScanAutoTradeProgressManager` service mirroring `BacktestProgressManager` (`emit/subscribe/unsubscribe/history/_gc`, bounded `_MAX_HISTORY`, terminal-retention GC, monotonic `seq`), keyed by `scan_id`. [ASYNC]
- R2. Manager is a long-lived app singleton wired in `main.py` lifespan onto `app.state.scan_progress_manager` (mirror backtest_progress_manager); passed INTO the per-scan tail (executor is per-scan, not the manager owner). [INTEGRATION]
- R3. New WS endpoint `/ws/v1/scanner/{scan_id}/auto-trade` (`backend/routers/ws_scan_progress.py`) mirroring `ws_backtest.py`: origin check, `subscribe()` history replay, 30s ping/pong keepalive, clean close on terminal stage, None-guard (1011) when manager absent. [API]
- R4. Router registered in `main.py` WITHOUT `/api/v1` prefix (WS routers are top-level `/ws/...`). [INTEGRATION]
- R5. Progress event schema: `{type:"scan_auto_trade_progress", scan_id, stage, label, detail, pct, status, seq, ts}` plus post-scan fields `account_id`, `account_label`, `symbol`, `phase`, optional `substatus` (e.g. `rate_wait`). [DATA]
- R6. Stage taxonomy (machine-stable keys): `init_balances → execute_batch → fill_immediate → post_scan_recheck → cleanup_rules → account_summaries → complete`, each carrying account-level sub-progress (`x/N accounts done`) so the bar advances DURING a stage. [DATA]
- R7. Thin `ProgressSink` protocol (`emit(stage,label,*,account_id,symbol,pct,status,...)`) injected into `AutoTradeExecutor.__init__` as optional, None-defaulted dependency (mirror `_recorder`/`_debug_ctx` idiom). Executor never imports the WS manager. [ASYNC]
- R8. Fail-open `_emit_progress` helper that swallows ALL exceptions and never blocks placement (mirror `_emit_life`). Progress must never gate or delay a real order. [ASYNC]
- R9. Terminal/cancel events: cancel branch (`scanner_service.py:1299`) emits a terminal `complete`/`cancelled` event so the WS closes cleanly and the client stops reconnecting. [OBSERVABILITY]
- R10. Terminal event ALWAYS emitted even on exception — wrap the whole tail in try/finally that emits `complete`/`failed` (no perpetual spinner). [WS]
- R11. `seq` strictly monotonic under concurrent emits (assigned synchronously, no await between read+increment). [WS][CONCURRENCY]
- R12. Bounded subscriber queues with drop-oldest / coalesce so a slow consumer cannot backpressure trade execution; history covers catch-up (mirror backtest 256-queue drop-on-full). [WS]
- R13. Optional REST snapshot of `history(scan_id)` for an initial render before the socket attaches (progressive enhancement). [API]

### Frontend live status
- R14. New hook `useScanAutoTradeProgressWS(scanId, active)` mirroring `useBacktestProgressWS.ts` — reconnect/backoff (1500→8000ms), StrictMode-safe CONNECTING-defer teardown, coalesce-by-stage, ping/pong; connects to `/ws/v1/scanner/{scanId}/auto-trade`. [REALTIME]
- R15. Hook exposes a superset `{ steps, accounts, orders, pct, connected, terminal }` (per-account + per-order projections beyond backtest's `{steps,pct,connected,terminal}`). [REALTIME]
- R16. New `PostScanExecutionPanel.tsx` rendered in the Progress `TabsContent` between the symbol-scan progress bar and the existing static auto-trade block — keeps ScannerPage.tsx from growing. [COMPONENT]
- R17. Stepped progress list, one row per backend stage in fixed order, pre-seeded as `pending` so the full pipeline shape is visible before events arrive. [COMPONENT]
- R18. Four step states: `pending` (dimmed), `active` (spinner+pulse), `done` (check), `failed` (danger ✗); per-step mini progress bar when `pct != null`. [STATE]
- R19. Per-account live rows: account label (via `accountLabelMap`), status pill, live counters `trades_executed/skipped/failed`; highlight currently-executing account, dim queued; live `stopped_reason` pill. [REALTIME]
- R20. Per-account row expand/collapse to reveal that account's order sub-feed. [COMPONENT]
- R21. Streaming order feed: each order row = symbol (mono), side TonePill, account label, ✓/✗ outcome, inline error; newest-on-top, animate-in, bounded (last ~200 rows). [REALTIME]
- R22. Order feed filter (All / Executed / Failed / Skipped) via segmented control; outcome count pills. [COMPONENT]
- R23. Auto-scroll to newest only when user is at top; otherwise pause and show "↑ N new" jump chip. [POLISH]
- R24. Connection status badge: `LIVE` (pulse dot), `Reconnecting…`, `Polling` (WS unavailable, 3s fallback). [FEEDBACK]
- R25. Post-scan elapsed-time ticker (scan can be 100% while orders still place — "scan complete ≠ trading complete"). [REALTIME]
- R26. WS opened only while the tail is plausibly active (`active` gating); not held on a long-completed scan. [REALTIME]
- R27. Late-join correctness: opening mid-tail reconstructs the stepped list + account rows from WS history replay. [WS]
- R28. Both call sites stream identically: automatic scan tail AND manual re-run (`POST /scanner/{scan_id}/auto-trade`). Panel header distinguishes "scan tail" vs "re-run"; resets on a fresh re-run. [SCREEN]

## Goal 2 — Parallelization & Performance (behavior-preserving) [CONCURRENCY / PERF]

### Orchestration & call-site unification
- R29. Extract a single shared post-scan orchestrator (e.g. `executor.run_post_scan_tail(results, progress=...)` or a free function) invoked by BOTH `scanner_service._run_scan` (1312-1369) and `scanner.py:_run_auto_trade` (257-298). Eliminates the duplicated/drifted 5-step sequence. [INTEGRATION]
- R30. `scan_id`-keyed in-flight single-flight guard so an auto tail and a manual re-run for the SAME scan cannot run the tail concurrently (double-placement risk). Manual already has `_in_flight_auto_trades`; extend to cover the auto tail. [CONCURRENCY]

### Bounded cross-account parallelism
- R31. Replace the executor-wide `self._lock` coarse serialization in `execute_batch`/`fill_immediate_remaining`/`evaluate_result` with per-account partitioning: each account's symbol loop runs sequentially inside its own task; tasks fan out across accounts under a bounded `asyncio.Semaphore`. [CONCURRENCY]
- R32. Partition unit MUST be `account_id` (the real Bybit UID), NOT `_AccountState`. `self._state` keyed `f"{account_id}_{i}"` means one account can own multiple config-states (trend + MR) sharing the same `(account_id,symbol)` traded entries, the same `BybitClient`, and slot counting → all of an account's states processed by exactly one task. [CONCURRENCY]
- R33. Preserve within-account symbol ordering: the `unique_results` sort (best-`|score|`-first, 804-808) and slot-fill semantics are money-meaningful; each account task iterates that ordered list sequentially. Only the account axis parallelizes. [CONCURRENCY]
- R34. Shared-state partition/merge: function-local `traded:set` and `executions:list` become per-account-local (trade_key `(account_id,symbol)` → accounts disjoint), merged AFTER gather in deterministic order (stable `self._state` insertion order × symbol order) so persisted `auto_trade_results` is reproducible for audit. [CONCURRENCY]
- R35. `_fill_to_max` (834, 861) currently asserts `self._lock.locked()` (1312) and reads the cross-account `traded` set. Redesign per-account: each account's fill uses ONLY its own `traded` subset; remove/replace the stale assert without weakening isolation; fill must not re-introduce a symbol the account already traded. [CONCURRENCY]
- R36. Per-`_AccountState` single-writer invariant: each `_AccountState` (`trades_executed/failed/skipped`, `executions[]`, `existing_symbols`, `created_rule_ids`) touched by exactly one task → no per-state lock needed if invariant holds; verify `_try_trade`/slot counting reads no cross-account counter. [CONCURRENCY]
- R37. Keep the per-`(account,symbol)` `_position_lock_registry` wrapping `_do_place` intact (registry of per-key locks, not one shared lock) so independent symbols don't serialize; raising account concurrency raises contention but disjoint keys stay parallel. [CONCURRENCY]
- R38. `_mr_mean_cache`/`_mr_price_cache` (reset in `init_configs`) read/written during MR placement: under concurrency two accounts may compute the same symbol's mean (cache stampede) — no `KeyError`/corruption; idempotent value; ideally single-flight per symbol. [CONCURRENCY]
- R39. `_ai_manager_enabled_accounts`/`_ai_manager_disabled_caps` writes in `_maybe_enable_ai_manager` stay on one task per account (enable-once-per-account holds). [CONCURRENCY]

### Parallelize the slow steps
- R40. Parallelize `init_balances` (469-770) BOTH loops: `accounts_with_close_target` (489-536: per-account `get_wallet`+`list_rules`+`close_all_positions`+`sleep(2)`) and the main per-state loop (540-770: `get_account`/`_is_account_paused`/`_account_in_cooloff`/`get_positions`/`get_wallet`/rule-create) — bounded semaphore; the `sleep(2)` settlement waits overlap across accounts. [ASYNC][PERF]
- R41. Parallelize `post_scan_recheck` per-account loop (1014+: `get_positions`/`get_wallet`/`list_rules`/`close_all`+`sleep(2)`/place) — bounded gather; preserve the snapshot-under-lock-then-release pattern. [ASYNC][PERF]
- R42. Parallelize `cleanup_unused_rules` per-rule `delete` and `emit_account_summaries` per-account `get_account` label lookups — bounded gather; lowest risk. [ASYNC][PERF]
- R43. `cleanup_unused_rules`/`get_summaries`/`emit_account_summaries` run strictly AFTER the per-account gather fully joins — never concurrently with in-flight placement. [CONCURRENCY]
- R44. Single tunable account-concurrency bound (const/env, e.g. `POST_SCAN_ACCOUNT_CONCURRENCY`) sized from the IP budget; `=1` ⇒ EXACT sequential fallback for safe rollout and byte-for-byte A/B vs current behavior. [CONCURRENCY][PERF]
- R45. Account-fanout × per-client `Semaphore(10)` interaction: total in-flight = `N_accounts × ≤10`; the centralized gate is the real backstop, account bound chosen WITH gate budgets in mind. [RATE_LIMIT]

### Determinism & idempotency
- R46. Golden equality: for fixed inputs, parallel run places the IDENTICAL set of orders (symbol/side/size/leverage/TP/SL) and identical per-account `trades_executed/failed/skipped` vs sequential baseline. [REGRESSION]
- R47. Each `(account_id, symbol)` processed by exactly one task across the ENTIRE tail (strict + fill + recheck); check-and-mark of the per-account `traded` set is atomic per key (no double-pass). [IDEMPOTENCY]
- R48. Slot-count integrity: `max_trades`/`fill_to_max_trades` accounting stays single-writer-per-state; no inter-account slot leakage when fill runs in parallel. [IDEMPOTENCY]
- R49. Deterministic merged output: after gather, sort merged `executions` and `get_summaries()` into a stable order before `_append_auto_trade_results`/`update_scan`. [DATA]
- R50. Order create keeps `retry_on_network_error=False` (a lost-response retry could double-place) and reuses the same `orderLinkId` across internal retries; the "order may or may not have been placed" message preserved. Parallelization must NOT change this. [IDEMPOTENCY]
- R51. The live-position re-check inside `_try_trade` (get_positions under registry lock, 1681-1689) remains the authoritative dup backstop: a symbol opened mid-scan is skipped (`already_held_live`), not double-placed. [IDEMPOTENCY]
- R52. `evaluate_result` (immediate, per-symbol DURING scan, 774) is OUT of scope for parallelization — only the POST-scan tail parallelizes; the immediate path stays serialized/unchanged; `fill_immediate_remaining` still seeds `traded` from `state.executions`. [REGRESSION]

### Failure isolation & persistence cadence
- R53. One account erroring/timing-out/rate-limited mid-batch must NOT abort others: per-account isolation (`return_exceptions=True` or per-task try/except), failure captured into that account's summary (`stopped_reason`) + a `status:"failed"` progress event; siblings continue. [PARTIAL]
- R54. A failing account's partial state stays consistent (`trades_executed/failed` match recorded executions; no half-counted slot). [PARTIAL]
- R55. Order placed but close-rule creation fails: `cleanup_unused_rules` must NOT delete (account has `trades_executed>0`); orphan-stop left for reconciler/AI-manager; rule-create failure does NOT roll back the live order. [PARTIAL]
- R56. Incremental DB persistence under parallelism: `_append_auto_trade_results` appends atomically w.r.t. the merge; persist per-stage so the 3s poll fallback converges. [DATA]
- R57. Manual-path persistence parity: align manual (`scanner.py:294`, final-only) and auto (incremental) via the shared orchestrator so polling behaves identically regardless of call site. [DATA]
- R58. Behavior must be byte-identical to sequential for identical inputs (same orders, same counts, same final summaries) — proven by the parallel-vs-sequential golden test. [REGRESSION]

## Goal 3 — Bybit Non-VIP Rate-Limit Enforcement [RATE_LIMIT / BACKOFF]

- R59. Enforce a true per-IP window of **600 req/5s** as the hard ceiling, operating target **≤480/5s (80% headroom)**, hard internal stop **540/5s (90%)**. Keep the combined ceiling provably ≤540/5s after the public/private fix. [RATE_LIMIT]
- R60. Fix public/private channel mis-assignment: `bybit_client._wait_for_rate_limit` (226) hardcodes `channel="private"`. Classify per endpoint — market data `get_mark_price` (529), `get_instrument_info` (543), `get_kline`/`get_tickers`, `/v5/market/time` → `channel="public"`; account/order/position/wallet → `private`. Implement via per-method channel arg or method→channel map. [RATE_LIMIT]
- R61. Add a per-UID, per-endpoint sub-limiter keyed `(uid, endpoint_class)`, independent of the IP window. Enforced caps (~20% headroom): `order_create/cancel` → 8/s (80% of 10/s safe floor), `order_amend` → 8/s, `set_leverage` → 8/s, `set_trading_stop` → 8/s, `position_list` → 40/s, `wallet_balance` → 40/s, `order_history`/`order_realtime` → conservative 20/s. [RATE_LIMIT]
- R62. Key the per-UID limiter on the ACTUAL Bybit UID / API key, NOT `f"{account_id}_{i}"` (configs share one BybitClient/UID). Resolve UID once (via `test_connection`/wallet) and cache on the client. [RATE_LIMIT]
- R63. Order create/cancel cap is tier-aware but fail-safe: default to the 10/s floor; only raise to 20/s when confirmed Linear + non-UTA2.0-Pro. Misclassifying upward risks a ban → floor is default. [RATE_LIMIT]
- R64. Charge market-data endpoints to the IP/public budget ONLY and exempt them from any per-UID order/private sub-limit. [RATE_LIMIT]
- R65. Fix the gate-bypass in `_do_sync_time` (`bybit_client.py:72-88`): line 77 calls `session.get(".../v5/market/time")` directly, never touching the gate. Every client re-syncs every 5 min and on `10002` → route through the gate (public channel) or explicitly account for it. [RATE_LIMIT]
- R66. Bound the pagination/poll multipliers: `get_positions` loops up to 50 pages of `/v5/position/list` (279-289); `_poll_order_fill` fires up to 7 `/v5/order/history` calls per order (500-527). Each page/poll independently acquires IP + per-UID tokens; concurrency sized for worst-case multiplier. [RATE_LIMIT]
- R67. Central registry of endpoint→class→limit (single source of truth); every `bybit_client` method maps to exactly one class; assert/reject any `_request` path lacking a mapping (prevents silent mis-charging). [RATE_LIMIT]
- R68. New cross-account parallelism MUST be gated, not fired with bare `asyncio.gather`: wrap account fan-out in a bounded limiter AND keep every leaf HTTP call behind the rate gate. [CONCURRENCY]
- R69. Size the global account-parallelism cap from the IP budget: ~6-9 requests per symbol-placement (mark+instrument+set_leverage+create+trading_stop+poll×k); cap simultaneous in-flight accounts so peak × per-op cost stays under 480/5s; single configurable const default conservatively (e.g. 3-5). [CONCURRENCY]
- R70. Preserve `lane` priority (order full budget/shortest backoff, live headroom, mcp 25% reserve) and extend it to the per-UID/endpoint tier so a real order create never starves behind `position_list`/`wallet_balance`/MCP traffic. [CONCURRENCY]
- R71. Window-pruning + append stays atomic under GIL-released await boundaries: preserve the check+append-inside-the-same-`with self._lock` invariant when adding UID/endpoint tiers (no two coroutines both pass `len < budget`). [CONCURRENCY]
- R72. Keep reactive 429/`10006` retry (186-197) as a LAST-resort backstop behind the preventive gate; emit a high-severity audit event whenever a 10006 retry fires (means the gate under-provisioned). [BACKOFF]
- R73. Respect `X-Bapi-Limit-Reset-Timestamp` for backoff (already parsed, 208-220) AND feed `X-Bapi-Limit`/`X-Bapi-Limit-Status` back into the gate to dynamically tighten when remaining is low (status < ~10% → throttle that UID/endpoint). [BACKOFF]
- R74. On a confirmed 10-min IP ban (repeated 10006 after retries), enter a process-wide circuit-breaker / cooloff that pauses all egress for the ban window rather than hammering and extending it; surface ban state to telemetry. [BACKOFF]
- R75. Distinguish IP-ban (global) from per-UID 10006 so a per-UID throttle does not trip the global breaker and vice-versa (failure isolation). [BACKOFF]
- R76. Confirm kline/regime fetchers (`market_data._build`, already `Semaphore(8)`) and `kline_cache_service` route through the public-channel rate-gated path so scan-time reads don't consume private/order budget. [CACHE][RATE_LIMIT]
- R77. Pre-flight feasibility check before the parallel tail: given N accounts × M symbols × per-op multipliers, assert projected peak 5s request count stays under 480/5s; if not, AUTO-reduce concurrency rather than risk a ban; make the estimate part of tests. [VALIDATION]
- R78. Budget constants audit: `_PUBLIC_BUDGET=400`/`_PRIVATE_BUDGET=100` should reflect real non-VIP caps and the new per-UID dimension; document the math relating account-concurrency bound to per-UID order budget. [RATE_LIMIT]

## Goal 4 — Look-and-Feel / UX [POLISH / THEME / A11Y]

- R79. Reuse `ScannerMetricCard`, `TonePill`, `SCANNER_PANEL_CLASS`, `SCANNER_SECTION_CLASS`, `ScannerPanelHeader`, and `--neu-*`/`--shadow-*` tokens throughout the new panel — zero bespoke surfaces; visually native to the Progress tab. [THEME]
- R80. Status color system, semantically consistent everywhere (stepper, badges, rows): green=placed, red=failed, amber=skipped, grey=pending, accent/pulse=running/waiting. Audit executions block (1206-1210) and currently-analyzing chips (1252-1267). [POLISH]
- R81. Smooth jank-free incremental updates: coalesce by stage; counters animate, rows fade in, no full-list re-render flicker per WS message. [ANIMATION]
- R82. Deliberate empty/zero states: "0 accounts configured for auto-trade", "all symbols skipped — no trades placed (see reasons)" so a no-trade outcome reads as intentional, not broken. [STATE]
- R83. Skeleton loaders (shimmer on `neu-surface` blocks) for the step list and account rows during WS connecting/initial state. [STATE]
- R84. Distinct in-progress / completed / failed / cancelled headers reusing the status-icon treatment (1112-1133) extended with a "cancelled" variant. [STATE]
- R85. Terminal collapse: on complete, auto-collapse the verbose feed into a compact Executed/Failed/Skipped `ScannerMetricCard` triplet, still expandable — live view becomes historical view in place. [STATE]
- R86. Rate-limit "throttling" indicator (active account row shows muted "Waiting on rate limit…" + slow pulse) so perceived slowness reads as intentional safety, not a hang; neutral/accent coloring (NOT warning/danger). Requires backend `rate_wait` substatus. [FEEDBACK]
- R87. Throttle indicator paired with tooltip/`aria-description` explaining the pause respects Bybit API rate limits (orders queued, not stuck). [A11Y]
- R88. Skip-reason transparency: every skip names the why (open position, close_on_profit threshold not met, paused, cooloff, blacklisted incl. adaptive, sector-cap, price-drift, max-trades, slot filled, dedup already-traded). [ERROR]
- R89. Money-fact display per placed order: side, symbol, leverage, capital %/size, entry/mark price, TP/SL applied, order id; visual weighting so money events stand out over informational events. [UX]
- R90. DRY-RUN vs LIVE badge on the whole post-scan panel so the user is never unsure whether real money moved. [UX]
- R91. "Re-run auto-trade" action near the status header triggering the manual endpoint + switching the panel to live mode; disabled while a tail is non-terminal (mirrors "no new trades while previous cycle running") with explanatory tooltip. [FEEDBACK]
- R92. Toast on terminal transition (success/failure summary), click-through focuses the panel; deduped so polling-fallback doesn't double-fire; optional user-toggleable audio cue persisted to localStorage (default off). [FEEDBACK]
- R93. `aria-live="polite"` region announcing stage transitions and trade outcomes, throttled to avoid SR flooding; status conveyed by icon + text (never color alone, colorblind-safe). [A11Y]
- R94. Honor `prefers-reduced-motion` (pulses/spinners/shimmer degrade to static); keyboard-navigable expand/collapse/filters with visible focus rings; AA contrast on muted text and tone pills. [A11Y]
- R95. Responsive/mobile: stack step list / account rows / order feed vertically, wrap in `MobileCollapse` (order feed collapsed by default, step list + active account expanded); shrink feed `max-h` on mobile; background-tab reconnect+replay. [RESPONSIVE]
- R96. Scanner-page polish: tighten Progress-tab hierarchy (top divider + `ScannerPanelHeader`); reduce header stat-card density on small widths; "TRADE DESK" card deep-links/scrolls to the live panel when a tail is active. [POLISH]
- R97. Keep the existing AI-Manager "reduced protection" notice (1236-1251) and surface it live if capability overrides are emitted during the tail. [STATE]

## Edge Cases & Cross-Cutting [BOUNDARY / PERSISTENCE / COMPAT / NONE_SAFETY]

- R98. Cancellation during parallel tail is cooperative at safe points (between symbols/accounts), never mid-order; stops launching NEW work but lets in-flight placements finish. [CANCEL]
- R99. ⚠️ `CancelledError` inside `_do_place` between `place_market_order` and `set_trading_stop` would orphan a position with no TP/SL → that section is shielded (`asyncio.shield`/finally) OR reconciler guarantees a stop is attached. [CANCEL]
- R100. Cancelled scan persists every order that DID hit the exchange (no lost result for a placed order); `auto_trade_executor`/`task` cleared; no orphan background task. [CANCEL]
- R101. Late subscriber receives full history replay before live events; reconnect → fresh replay; client dedups by `seq`. [WS]
- R102. Multiple clients on the same `scan_id` each get independent queues; one slow/full client (drop-oldest) doesn't stall the other or the emitter. [WS]
- R103. No client connected: `emit` still appends to history AND the tail still persists to DB; polling converges to identical final state. [WS][PERSISTENCE]
- R104. High-volume scan (e.g. 50 accts × 10 symbols = 500+ events) exceeds `_MAX_HISTORY`: early events truncated for late subscribers, but the terminal event is always retained and DB/poll remains source-of-truth. [BOUNDARY]
- R105. Terminal-retention GC boundary (~60s): a client connecting >60s post-completion gets empty history → falls back to the DB-backed scan view. [BOUNDARY]
- R106. Manual re-run `_in_flight_auto_trades` guard returns 409 while running; `finally` always discards the guard even on early raise; two concurrent POSTs → exactly one runs. [IDEMPOTENCY]
- R107. Auto-finalize vs manual re-run interleave: manual requires DB `status=='completed'`; in the window where auto sets completed but is still writing summaries, manual builds its OWN executor and the live re-check prevents duplicate placement across both executors. [IDEMPOTENCY]
- R108. Crash between a phase-append and the final write leaves DB recoverable; `resume_incomplete_scans` re-runs the tail but orders placed before the crash are NOT re-placed (live-position re-check); at most one scan resumes. [PERSISTENCE]
- R109. Document the existing crash/resume slot-accounting risk: `state.trades_executed` resets to 0 on resume while live positions exist → fill could exceed `max_trades` across the crash boundary (pre-existing; flag explicitly under parallelization, do not regress). [PERSISTENCE]
- R110. `post_scan_recheck` reset block sets `state.executions = []` (1127) for rechecked accounts: final `get_summaries()` (state-based) must stay consistent with the cumulative `auto_trade_results` buffer (which already captured the wiped executions). [PERSISTENCE]
- R111. Boundary: zero accounts / zero results / all-accounts-stopped → no-op; terminal progress still emitted; `get_summaries()` returns `[]`; DB persists empty arrays; status still finalizes. [BOUNDARY]
- R112. `>50%` symbol-failure skip boundary: `too_many_failures = total>0 and failed_count > total*0.5` skips the ENTIRE tail (exactly 50% does NOT skip; `total==0` guarded); emit a "skipped" terminal progress reason (not a hang). [BOUNDARY]
- R113. Single account: parallelization degenerates to sequential — byte-identical orders/counts/list-order/summaries. [REGRESSION]
- R114. Existing 3s polling clients unaffected: scan dict / `_serialize` shape unchanged; `auto_trade_results` keeps the 6-field dict (`symbol/side/status/order_id/error/account_id`); WS purely additive. [COMPAT]
- R115. `ScanDetailPage` historical (DB-backed) view reads the same persisted `auto_trade_results`/`auto_trade_summaries` shape + order semantics — no regression. [COMPAT]
- R116. Backtest builds the executor WITHOUT `_close_svc` and WITHOUT a progress manager: `cleanup_unused_rules` early-returns, `post_scan_recheck` close branch is `_close_svc`-guarded, every `emit(...)` None-guarded, `_position_lock_registry=None` places without the shared lock — full parallel tail runs green in backtest/no-services mode. [NONE_SAFETY]
- R117. `recorder`/`debug_ctx` None: `emit_account_summaries` short-circuits (no `get_account` DB calls). [NONE_SAFETY]
- R118. WS endpoint authz/origin check mirrors existing WS endpoints; strict `scan_id` validation (UUID) with clean close on malformed; non-existent vs unauthorized return identically (no enumeration). [WS_SECURITY]
- R119. Progress event payloads scrubbed (allow-list, not deny-list): never API keys/secrets/signatures/`X-BAPI-*` headers/raw balances; only derived non-sensitive status (symbol, side, stage, counts, redacted ratios). [SECRETS]
- R120. Cap concurrent WS subscribers per scan and per IP (DoS protection), idle timeouts, max-subscribers ceiling; inbound frame-size + message-rate limits; the new browser→server WS does NOT consume Bybit's 500/5min WS-connect budget (that is outbound to Bybit). [WS_SECURITY]
- R121. Structured per-account/per-stage timing logs keyed by `scan_id`+`account_id`; metrics surface total tail duration, per-stage/per-account duration, fan-out width, rate-gate `current_usage`/`wait_count` extended per-endpoint/per-UID sampled during the tail. [OBSERVABILITY]
- R122. No new DB column required (in-memory manager + existing `auto_trade_results`/`auto_trade_summaries` columns suffice); if a progress-snapshot column is added, route through the auto-apply migration path (`persistence.py`/`async_persistence.py`). [MIGRATION]
- R123. Test seams: inject the concurrency bound and progress sink as parameters with safe defaults; default bound to a deterministic value (or 1) in tests so parallel merges are reproducible; deterministic mock `BybitClient` (records placements, configurable latency/errors/429s) for golden equality. [TEST]
- R124. Additive, reversible rollout: WS endpoint additive (old clients keep polling); parallelism gated behind the `=1`-sequential concurrency flag; rate-gate fixes behind their own switch — the three risky changes (fan-out, channel fix, per-endpoint limit) enable/rollback independently. [MIGRATION]
- R125. Implementation sequence (hard prerequisite): rate-gate correctness (R59-R67) BEFORE bounded parallelism (R31-R45) — fanning out before public calls stop consuming private budget and before per-endpoint order caps exist would INCREASE 429/ban risk. Progress/WS (transport-only, fail-open) can be built in parallel. [SEQUENCING]

- R150. Live rate-gate introspection: a read-only operator endpoint exposing current gate state (per-channel/per-UID/per-endpoint usage, wait counts, ban/cooloff status, current fan-out width) for real-time diagnosis — distinct from the user-facing `rate_wait` hint (R86). [OBSERVABILITY]

### Performance contract & latency levers
- R151. Quantified speedup acceptance criteria + repeatable benchmark: define pass/fail targets for representative loads (5/10/20 accounts × M symbols) measured as full-tail wall-clock, sequential (`concurrency=1`) vs parallel, using the deterministic mock `BybitClient` with configurable per-call latency (R123); assert a minimum speedup in a committed benchmark test; capture per-stage wall-clock so it simultaneously proves the speedup AND that golden-equality (R46/R58) holds. [PERF]
- R152. Quantified throughput ceiling (expectation-setting): document the sustained ceiling — with ≤480/5s IP budget (R59) and ~6-9 requests/placement (R69), max ≈ ~13-14 placements/sec regardless of account count, further per-account-capped by 8/s per-UID order limit (R61); define the account-count plateau beyond which adding accounts no longer reduces wall-clock. [PERF]
- R153. Replace fixed `asyncio.sleep(2)` settle-wait (init_balances 489-536 / post_scan_recheck 1064-1065) with a bounded poll-until-settled (re-query positions/wallet at ~250ms until flat, 2s hard timeout, same fallback), preserving the "positions confirmed closed before re-evaluation" invariant. [PERF]
- R154. Short-TTL per-UID wallet/positions snapshot cache shared across the WHOLE tail (init_balances → execute_batch → post_scan_recheck), invalidated on any placement/close that mutates that account — reduces both latency AND Bybit request count (relieves the Goal-2-vs-Goal-3 tension). [CACHE]
- R155. Evaluate/adopt Bybit V5 batch order endpoints (`/v5/order/create-batch`, up to ~20 orders/request linear): either adopt batch placement for an account's multi-symbol set (preserving per-order `orderLinkId`/idempotency R50, per-(account,symbol) live re-check R51, per-order outcome mapping for the WS feed), or document a concrete deferral rationale; quantify the request-count reduction either way. [PERF][RATE_LIMIT]
- R156. Server-side emit batching/throttling of high-frequency per-order events (a 500+-order scan emits a burst): source-side coalesce per-order events on a bounded cadence (~100ms or every K events) with compact payloads; stage-transition + terminal events bypass batching for immediacy. [WS][PERF]
- R157. Frontend virtualization / render budget for the streaming feed: windowed rendering (or a hard cap on concurrently-rendered DOM nodes + simultaneous animations) for the order feed and account rows, verified under a synthetic 500-event burst. [PERF]
- R158. Cold-start client warm-up: pre-warm/pool each account's `BybitClient` (decrypt + UID resolve + time-sync, R65) BEFORE the parallel placement fan-out (avoid a thundering herd of `/v5/market/time` syncs); run CPU-bound credential decryption/HMAC signing in a thread executor so it never blocks the event loop (which would also stall fail-open progress emits). [PERF]
- R159. Size the aiohttp `TCPConnector` total/per-host limits to the chosen account-concurrency × per-client `Semaphore(10)` so the connector pool is not a hidden serialization bottleneck; document the per-host connection ceiling to Bybit. [PERF]
- R160. The rate gate must not itself serialize the fan-out: its `acquire` path holds the internal lock for O(1) work only, never across an `await`; a micro-benchmark proves gate overhead per acquire stays negligible under target concurrency. [PERF]
- R161. Straggler/tail-latency observability: capture per-account/per-stage latency distribution (p50/p95/p99), not just totals; identify the straggler account + its dominant stage per tail (bounded-gather wall-clock is dominated by the slowest account). [OBSERVABILITY]
- R162. Bound order-fill-confirmation latency: `_poll_order_fill` fires up to 7 sequential `/v5/order/history` calls/order (500-527); bound the poll count/interval for latency and/or decouple fill confirmation from launching the next placement, WITHOUT changing whether/when an order is treated as confirmed (no regression to R50/R51). [PERF]

### MCP-lane backward-compat
- R163. MCP/sweep/backtest lane regression guard: the public/private reclassification (R60) changes the math the `mcp` 25% reserve sits on. Add a test proving a live concurrent MCP sweep/backtest is neither starved by the parallel order tail nor starves real order creates; assert MCP/backtest traffic is exempt from the new per-UID ORDER sub-limiter (R61) yet still charged to the public IP budget for live market reads. [COMPAT]

### Frontend state-sync corrections (CRITICAL fixes to Goal-1 reqs)
- R164a. (CRITICAL) ScannerPage `scanQuery` must keep polling THROUGH the post-scan tail: `refetchInterval` (483-486) returns `false` when `status !== "running"`, but the tail runs AFTER `status === "completed"` — so the "Polling fallback" (R24/R114) never actually fires on ScannerPage and, with WS down, the page freezes at completed-but-no-trades. Continue 3s polling while a tail is plausibly active (until `auto_trade_summaries` land or a terminal WS event arrives). Mirror `ScanDetailPage.tsx:272-283` `stillAutoTrading`. [STATE]
- R164b. Define the `active` predicate that gates the WS open (R14/R26), client-side, for BOTH paths: automatic tail = `status === "completed" && auto_trade_configs present && auto_trade_summaries absent`; manual re-run = from trigger until summaries/terminal. Include an upper time bound so a missed terminal event can't hold the socket open indefinitely. [STATE]
- R164c. Reconciliation precedence (WS live vs polled `scanQuery`): during a live tail the WS projection is the display source; on terminal the DB-backed `scanQuery` snapshot becomes authoritative and the panel re-renders from it; counts are MONOTONIC (never tick down when a stale poll lands). [STATE]
- R164d. De-duplicate the post-scan info: hide/suppress the legacy static executions block (1190-1251) whenever `PostScanExecutionPanel` is mounted for the active scan — exactly one renderer at a time (R85 terminal-collapse is the single historical view). [COMPONENT]
- R164e. WS terminal event triggers a debounced `queryClient.invalidateQueries(["scan", scanId])` (deduped against the poll, fires once) so the DB-authoritative final state is fetched. [STATE]
- R164f. Per-account counters come from authoritative per-account event counts (reconciled to `auto_trade_summaries` on terminal), independent of the truncated ~200-row feed (R21) — truncation must not understate counters on high-volume scans. [STATE]
- R164g. Auto-switch must not yank the user off the live tail: the running→completed effect (505-511) force-switches to Results exactly when the tail begins; when a tail is active, suppress/defer the auto-switch (keep Progress focused) until terminal; reconcile with the new-scan snap-back (516-519). [STATE]
- R164h. Cold-load / post-GC fallback: when the panel mounts for an already-terminal scan with empty WS history (fresh load >60s after the tail, or `active` never opens the socket), render the persisted final state from `scanQuery` (R85 terminal-collapsed triplet), NOT an empty live skeleton or perpetual "connecting"; byte-identical whether reached live or cold. [STATE]
- R165a. Error boundary around `PostScanExecutionPanel`: a malformed WS payload that throws during render must degrade to the polled static block + "live view unavailable" notice, never unmount the page. [STATE]
- R165b. `scanId`-change teardown & late-event isolation: on `activeScanId` change, tear down the old socket and discard in-flight events tagged with the prior `scan_id` (events carry `scan_id` per R5 — filter on it). [STATE]
- R165c. Multi-tab duplicate-alert guard: scope terminal toast + audio cue to the focused/visible tab (`document.visibilityState`) so N tabs don't produce N notification storms; pref writes tolerate cross-tab races (best-effort last-write-wins). [FEEDBACK]
- R165d. UI-string localization clarification: the app has NO i18n layer (`output_language` only drives LLM output); new panel labels remain hardcoded English; the frontend derives display copy from the machine-stable `stage`/`status` codes (R6) in ONE frontend map, NOT from the backend's human `label`/`detail` prose (so a backend copy tweak can't silently change the UI). [I18N]
- R165e. Persisted UI-pref contract: namespaced localStorage keys + defaults for autoscroll (on), order-feed filter ("all"), per-account expand (collapsed), audio (off); follow the `useTabPersistence` discipline (try/catch, written only on user interaction, never a mount-time write). [CONFIG]
- R165f. "TRADE DESK" card correction (R96 was mis-scoped): the card lives in the GLOBAL `AppMarketBar` (rendered on every route, sourced from `tradesQuery`, currently no click handler), NOT the ScannerPage header. Decide: keep it a portfolio stat with a new deep-link (router navigate to /scanner + select Progress tab + scroll-to-anchor, handling the cross-route case) vs reflect live progress. [POLISH]
- R165g. ScanDetailPage manual re-run parity (R28/R140 correction): R28's "both call sites stream identically" is narrowed — the automatic tail streams live on ScannerPage; the manual re-run streams live on ScannerPage; decide explicitly whether `PostScanExecutionPanel` is also mounted in ScanDetailPage for its re-run (`ScanDetailPage.tsx:295-303`) or ScanDetailPage stays poll-only. [SCREEN]
- R165h. Frontend test coverage: StrictMode double-mount (one socket, clean teardown), late-join history replay, reconnect/backoff, scanId-change teardown, poll↔WS reconciliation/no-flicker, cold-load persisted render, error-boundary fallback. [TEST]

## Total Requirements Count: 125 + Round-2 additions (R126-R165, ~52 net new) = ~177
## Rounds Completed: 2 (Round 3 pending)

---

## Round 2 Gap-Finding — New Requirements (R126-R165)

### Backend / Data-Integrity / Resource Limits
- R126. Size the account-fanout bound against the asyncpg pool too (not only the Bybit IP budget): `DB_POOL_MAX=10`/`min_size=2`, acquire `timeout=10`, `command_timeout=10` (`async_persistence.py:1781-1784`). Document `POST_SCAN_ACCOUNT_CONCURRENCY × DB-ops-per-account ≤ DB_POOL_MAX − reserved_headroom`; decide whether an account task holds one connection for its run vs acquire/release per op; pre-flight assert the bound cannot starve the pool. [DATA]
- R127. The post-placement DB write of an ALREADY-placed order must survive pool contention: a `create_trade` queued behind an exhausted pool can raise `TimeoutError` AFTER the order hit Bybit → orphan (live position, no DB row). Use a reserved/priority connection or bounded retry with the SAME `orderLinkId`, plus a guaranteed fallback record (pending_intents / recovery log) so the reconciler can adopt the orphan. Never silently drop a placed order on pool timeout. [DATA]
- R128. Incremental per-stage persist (R56) must not lose updates under concurrent stage writes: if `update_scan` is a read-modify-write of the JSON array, two concurrent persists drop appends. Serialize incremental persistence single-writer OR use a DB-side JSONB append in one statement; prove with a concurrent-persist test. [DATA]
- R135. Incremental persistence must be idempotent across crash-resume: `resume_incomplete_scans` re-runs the tail (R108); the persisted partial array must not be re-appended/double-counted. De-dup by `(account_id, symbol, order_id)` or replace-by-stage; prove with a crash-mid-tail-then-resume test. [PERSISTENCE]
- R139. Define the per-placement multi-table write boundary (`pending_intents` + `trades` + `close_rules`): specify whether trade-row + close-rule writes for one placement share one connection/transaction (bounds pool usage to ~1 conn per in-flight placement, makes the multi-row write atomic) vs remain independent with explicit compensating recovery. The chosen boundary makes R126's pool math computable. [DATA]
- R140. Persist-before-terminal causal ordering: the DB persist of final results/summaries must COMMIT before the terminal progress event (R10) is emitted, so a client dropping to polling on the terminal signal cannot read pre-commit/stale DB state. [PERSISTENCE]

### Cross-subsystem coordination (shared rate gate + shared locks)
- R129/R137. The account-concurrency limiter is a PROCESS-WIDE singleton (like the rate gate), shared across the auto tail, the manual re-run, scheduled tails, and any other caller — so combined fan-out is globally bounded and R77's per-tail feasibility holds. (Multi-replica note: `get_rate_gate()` is per-process; document/assert a single-egress-process constraint or add cross-process coordination, else replicas sharing one IP can exceed 600/5s.) [CONCURRENCY]
- R130. Pre-flight feasibility (R77) reserves explicit headroom for concurrent NON-tail Bybit consumers: `position_reconciler` (60s loop, up to 50 `/v5/position/list` pages × all accounts), AI-manager loop, `close_rule_evaluator`, `trading_cycle_engine`. The ≤480/5s projection must not be silently overcommitted when a reconciler tick lands mid-tail. [RATE_LIMIT]
- R131. `position_reconciler` coordination during an active parallel tail (tail can exceed its 60s interval): either skip reconciliation for an `account_id` while it has an in-flight tail task, or verify+document the reconciler's status guards are safe against half-written tail state; test the reconciler against a mid-tail account. [CONCURRENCY]
- R136/R138. pending_intents writes (`write_intent` before submit + `delete_intent` after `create_trade` = 2 pool ops/MR order, `ON CONFLICT (account_id,symbol,side)` clobber) are counted in R126's per-account DB-op budget; the one-task-per-`(account_id,symbol)` invariant (R47/R32) extends to intent rows; `gc_stale` (reconciler) must not delete an intent for an order still being placed. [DATA]
- R137b. close_rule_evaluator / trading_cycle_engine tolerate mid-creation rule state (trade placed, close-rule row not yet written — R55 window): make place-order + close-rule-create observable atomically per `(account,symbol)` OR have the evaluator tolerate the gap; test the evaluator against an account mid-rule-creation. [CONCURRENCY]
- R141. AI Account Manager coordination: `ai_manager_task.py` independently places/amends/closes trades, competing for the SAME global gate AND the SAME `_position_lock_registry`. Define whether it is paused/deferred during a post-scan tail or runs concurrently; give it an explicit gate lane; include its egress in the R77/R130 feasibility estimate; do not begin managing an account until its tail task fully joins (enable only in the R43 post-gather phase). [CONCURRENCY]

### Operations / Kill-switch / Scheduled path
- R132. Kill-switch enforced mid-tail and on the manual path: `kill_switch.read_kill_switches` is read only in `start_scan` today. (a) Manual re-run reads the kill switch before fan-out (fail-closed); (b) the per-account fan-out re-checks at the safe launch point between accounts and stops launching NEW account tasks when killed (cooperative, like R98), emitting a terminal "killed" reason. [SECURITY]
- R133/R136b. Runtime admin controls without redeploy: a hot-readable (DB-backed `feature_kill_switches`) toggle to force `concurrency=1` and to abort an in-flight tail, checked at the start of each tail and cooperatively mid-tail — complements the automatic ban breaker (R74) which is reactive. [OPERATIONS]
- R134. Scheduler single-flight vs the circuit-breaker / tail lifecycle: a scheduled scan must remain "in-flight" until its post-scan tail fully joins (so the next scheduled tail's egress doesn't overlap — `scan_scheduler_service.py:399-411,438`); the R74 ban cooloff must surface to the scheduler bounded by the ban window (not the 7200s `SCAN_TIMEOUT_SECONDS`), and a tail stalled on the breaker must be reclaimed, not wedge the scheduler. [OPERATIONS]
- R145. Scheduled-scan tail is a first-class emitting path: emits progress identically to auto/manual; every progress event + persisted scan record carries `triggered_by ∈ {scheduled, auto, manual_rerun}`. [OBSERVABILITY]
- R146. Durable post-scan execution summary for unattended review (in-memory history GCs ~60s): persist a compact execution timeline (per-stage durations, per-account outcome + skip/stop reason, total rate-wait time, peak in-flight concurrency, 10006/ban count, fan-out width) into the durable scan record via the auto-apply migration path. [OBSERVABILITY]
- R147. Out-of-band terminal notification for zero-subscriber / scheduled tails ending in failure/partial-failure, via the existing notification channel (real-money failures must surface without a watching browser). [FEEDBACK]
- R148. Operator-owned, validated tuning surface: centralize all rate/concurrency knobs (R44 concurrency, R61 caps, R59 IP target %, lane reserves) as deployment-level config, operator-only (never end-user editable), with startup validation that rejects/clamps any combination whose worst-case peak exceeds the 540/5s hard stop; documented safe ranges + ownership. [CONFIG]
- R149. Operator runbook deliverable: diagnose 10006/IP-ban, read the new telemetry, flip the runtime kill-switch, tune concurrency, interpret rate_wait/throttle/ban states. [DOCS]
- R150. Live rate-gate introspection: a read-only operator endpoint exposing current gate state (per-channel/per-UID/per-endpoint usage, wait counts, ban/cooloff status, current fan-out width) for real-time diagnosis — distinct from the user-facing `rate_wait` hint (R86). [OBSERVABILITY]

---

## Round 3 Gap-Finding — New Requirements (R166-R196)

### Concurrency / race (verified against source)
- NOTE (hypothesis refuted): `max_same_sector` (`auto_trade_service.py:1567-1576`, off `state.existing_symbols`) and `max_same_direction` (1551-1564, off `state.position_directions`) are PER-`_AccountState`, GIL-safe, and never relied on the executor `self._lock` → R31's lock removal introduces NO sector/direction race.
- R166. R36's single-writer field enumeration is incomplete: say "EVERY non-config `_AccountState` field" and explicitly name `position_directions` (read by the direction gate :1560) and `mr_duration_rule_created` (:1879,1900). [CONCURRENCY]
- R167. Registry-lock-pinned-across-ban starves the close path: `_try_trade` holds `_position_lock_registry[(account,symbol)]` through the entire `_do_place` chain (:1675-1694); every leaf waits in the gate's unbounded loop. Under R74's ban (≥10min), N tail tasks pin N registry keys shared with CloseRuleEvaluator (`acquire timeout=30s`) → an emergency protective close can't fire for the ban window. Bound registry hold independent of gate state (breaker makes in-gate waiters release/fail-fast), OR the evaluator's protective path isn't gated behind a tail-held placement lock during a ban. [CONCURRENCY][money-safety]
- R168. The gate's `acquire_async` wait-loop polls the R74 breaker / R133 kill-switch each iteration so cooperative abort (R98/R133) is reachable while parked in a ban. [CONCURRENCY][CANCEL]
- R169. Multi-dimension token acquisition (IP + per-UID/endpoint, R61) needs an all-or-none single-critical-section commit (one consistent lock; check all dims, append to all or none) — R71 covers one tier only; a two-step design leaks an IP token per retry or holds the IP lock across an await. [CONCURRENCY][RATE_LIMIT]
- R170. Post-gather merge + `cleanup_unused_rules` read authoritative data from `self._state`, NEVER from `gather(return_exceptions=True)` return values (a cancelled child returns a `CancelledError`, not its executions; all `_do_place` branches write through to state :1863-1972). Sub-point: on cancel in R99's orphan window (`trades_executed` still 0), `cleanup_unused_rules` (:930-959) must SKIP interrupted accounts — else it deletes the close rules of a live position with no TP/SL. [CONCURRENCY][money-safety]
- R171. `BybitRateGate._wait_count` is mutated outside `self._lock` from both the loop thread and `acquire_sync` worker threads (:90,110,116,130) → corrupted telemetry feeding R73/R121/R150; move inc/dec inside the lock or use an atomic counter. [OBSERVABILITY]

### Integration / API-contract / compat
- R172. Single-source typing + versioning for the WS event: a backend Pydantic model (`ScanAutoTradeProgressEvent`) emitted via `.model_dump()`; the TS event type + `{accounts,orders}` projections co-located in `frontend/src/api/client.ts` (NOT buried in the hook); a `schema_version` field for forward-compat. [INTEGRATION]
- R173. Dual-serializer + frontend-type lockstep for any new persisted scan field (R145 `triggered_by`, R146 timeline): enumerate keys added to BOTH `_serialize` AND `_serialize_db` AND `ScanStatus`; parity assertion the two serializers produce the same key set; amend R114 to "additive-only; the 6-field `auto_trade_results` dict frozen". [COMPAT]
- R174. `ScanStatusResponse` (schemas 838-849) is a dead schema lacking `auto_trade_results`/`auto_trade_summaries`, not applied as `response_model` on GET `/scanner/{scan_id}` — a latent strip-trap. Either sync+apply it or add a comment+test documenting the endpoint returns an untyped superset. [COMPAT]
- R175. MCP `scans_get` (`scheduled/read.py:48`) `strip_secret_keys(scan)` raw passthrough surfaces any new persisted field to MCP clients; R119's WS-only scrub doesn't run here — extend allow-list to the persisted path + MCP-shape regression test. [SECRETS][COMPAT]
- R176. Extract a shared `wsBaseUrl()` (+ reconnect/backoff + CONNECTING-defer teardown) into `frontend/src/api/ws.ts` — the resolver is already copied 4×; the new hook consumes it (legacy callers = follow-ups). [MAINTAINABILITY]
- R177. WS lifecycle: pin emitter-vs-manager STARTUP ordering (no emit to a `None` manager); graceful SHUTDOWN drains subscribers with a terminal close (fits the 15s `_SHUTDOWN_TIMEOUT`); a close-code → reconnect-decision contract so a permanent 4403/auth close isn't an infinite reconnect loop. [RELIABILITY]
- R178. Committed WS contract doc (AsyncAPI/markdown) for `/ws/v1/scanner/{scan_id}/auto-trade` (schema + `schema_version`, stage keys, keepalive, close codes), referenced by router + hook (WS is invisible to OpenAPI). [DOCS]

### Migration / rollback / deployment-safety
- R179. (MUST) Shipped DEFAULT on first deploy = concurrency 1 (parallelism OFF): the refactored parallel path runs at width-1 in prod (byte-identical orders R46/R113); raising above 1 = explicit operator opt-in after width-1 is proven. [ROLLOUT]
- R180. Each of the 3 risky changes (fan-out, channel-fix R60, per-endpoint limiter R61) independently revertible at RUNTIME without redeploy via hot `feature_kill_switches`, gate falling back to pre-change behavior when flipped — resolves the R148(deploy-config) vs R133(hot) contradiction. [ROLLOUT]
- R181. R146 timeline column contract (migrations are forward-only): `ADD COLUMN IF NOT EXISTS` constant/NULL default = metadata-only no rewrite; written only by new code; read-tolerant of NULL; ignored by old code (rollback = orphaned-harmless); safe under rolling deploy. [MIGRATION]
- R182. Deploy-during-tail drain vs the 15s `_SHUTDOWN_TIMEOUT` (main.py:638-660): SIGTERM drain must NOT exit mid-`asyncio.shield(_do_place)` before the trade row commits (R127 orphan) nor mid rate-wait — bound the shielded section + DB flush to the window, or flush every placed order to recovery before exit. [MIGRATION]
- R183. (MOST IMPORTANT) Durable "tail-in-progress" sub-state: `resume_incomplete_scans` (:960-974) only re-runs `status='running'`, but the tail runs AFTER status flips `completed` (R164a) → a deploy mid-tail silently abandons a partial tail and R135 idempotency never engages. Persist a tail-in-progress sub-state (or keep `status='running'` until the tail joins) so restart re-runs-or-finalizes it. [PERSISTENCE]
- R184. Staged production ramp gated on telemetry: deploy at =1 → soak (no 10006, byte-identical) → ramp 1→2→N with an observation gate each step + one-flip rollback. Optional shadow-compare: diff the parallel vs sequential launch plan, log divergence WITHOUT doubling placement. [ROLLOUT]
- R185. Steady-state regression verification that the channel-fix (R60, ALL market reads private→public system-wide) and per-UID limiter (R61, newly charges AI-manager/evaluator/cycle-engine order-creates) cause NO new throttling/latency/ban-risk to the accounts dashboard, reconciler, evaluator, cycle engine, AI-manager (R163 covers only MCP; R130/R141 only during-tail). [COMPAT]
- R186. Active regression DETECTORS (push): (a) duplicate-placement monitor alerting when >1 order for `(account_id,symbol,cycle)` or placements exceed `max_trades` across the fan-out; (b) near-ban early-warning when `X-Bapi-Limit-Status` headroom drops below threshold, BEFORE a 10006 — distinct from reactive R74 and pull-based R150. [OBSERVABILITY]

### Security
- R187. (Critical) Operator-control endpoints (R133/R136 kill/override/abort, R150 introspection) need an explicit trust boundary: inherit API mutation defenses (CSRF `X-Requested-With`, content-size, origin), FAIL-CLOSED on a non-loopback bind. Today `admin.py` ships an UNAUTHENTICATED kill-switch — unauth abort-in-flight-tail is a money-system DoS lever. [WS_SECURITY]
- R188. Audit trail for kill/override/abort binds the principal to the authenticated transport context, NEVER a caller-supplied string (`admin.py:68` reads `updated_by` from the body = forgeable); R146 timeline carries abort/override provenance. [SECURITY]
- R189. The real-money progress WS adopts the STRICT reject-on-missing-Origin policy (`ws.py:17-35`), explicitly NOT the `ws_backtest`/`ws_accounts` no-Origin bypass that R3/discovery prescribed mirroring — name the authoritative origin policy in R118. [WS_SECURITY]
- R190. `account_label` streamed over WS (R5) is absent from R119's scrub allow-list; labels are user-chosen PII / position-sizing hints. Stream an opaque per-scan handle (`acct#1..N`/hashed id), resolve the human label only in the authenticated DB-backed view; default to non-leaking. [SECRETS]
- R191. R146 durable timeline is a SEPARATE secret sink from R119 (WS-only): scrub reasons/error/substatus via the existing redactor (`scan_scheduler_service.py:817`) BEFORE persist; `ScanDetailPage` renders it as TEXT not HTML (stored-XSS risk). [SECRETS]
- R192. Verify the scan exists (and is auto-trade-bearing) BEFORE subscribe (mirror `ws.py:57-62`, NOT `ws_backtest` which has no existence check) so a foreign scan_id yields identical empty-then-close and the stream isn't an existence/timing oracle. [WS_SECURITY]
- R193. Document the single-operator loopback/trusted-LAN boundary for streaming cross-account live trade INTENT; if the bind becomes non-loopback the feed fails closed or gains per-principal authz (front-running guard). The R99 shield must hold against an externally-triggered abort, not only cooperative `CancelledError`. [WS_SECURITY]

### Product / scope (key Round-3 output)
- R194. (MUST) Encode the scope partition + default-off phased rollout AS a requirement: ship Goal-by-Goal behind R124/R180 flags, prod defaults to concurrency=1 until golden + speedup + zero-10006 gates pass on a canary, WON'T-HAVE-NOW items are a SEPARATE backlog. [SCOPE]
- R195. (MUST) Distinct IP-ban cooloff (R74) state in the live panel, DIFFERENTIATED from R86's micro-throttle pulse (a user staring at a 10-min slow-pulse force-kills → extends the ban). Show "Trading paused ~Nm — rate-limit cooloff" with the `X-Bapi-Limit-Reset` countdown. [FEEDBACK]
- R196. (MUST) A single Definition-of-Done / release gate: golden-equality (R46/R58) green, speedup target (R151) met, ZERO `10006` under the R151 benchmark, `=1` fallback byte-identical (R113), orphan-on-pool-timeout (R127) green. [SCOPE]

---

## MoSCoW Scope Partition (drives the Spec's in/out scope — Step 4)

**MUST-HAVE (core; the 4 goals, ship safely):**
- Goal 1 transport: R1-R12, R14-R22, R24, R26-R28; frontend correctness R164a-h, R165a/b/d/h; typed contract R172-R174, R176, R177; strict WS security R187(core)/R189/R190/R192/R193.
- Goal 2 (money-critical heart, cut nothing): R29-R58; data-integrity R126-R128, R139-R140, R166, R169-R170; global bound R129/R130; resume/deploy safety R182-R183; gate-not-serializing R160; R167-R168.
- Goal 3 (all): R59-R78; R171.
- Goal 4 core: R79, R80, R82, R84, R88, R90, R195.
- Cross-cutting: R98-R119, R123-R125, R148(startup-validation only), R151, R159(verify)/R160, R179-R181, R184-R186, R188, R191, R194/R196.

**SHOULD-HAVE (quality/ops; fast-follow, behind flags):** R13, R23, R25, R81, R83, R85, R86/R87, R91-R97, R120, R121, R131-R138, R141, R145, R147, R152, R156, R158, R161-R163, R165c/e/f/g, R175, R178, R185(extended).

**WON'T-HAVE-NOW (defer to a tracked backlog — YAGNI / adds risk):** R146 (durable timeline via migration), R149 (runbook→PR notes), R150 (introspection endpoint; also dedupe its duplicate), R154 (stale-balance cache = the exact bug to avoid), R155 (batch orders — high idempotency risk), R157 (FE virtualization), R161 (percentiles), R129 multi-replica + R141 AI-manager pause-lane (document constraint, don't build distributed coordination), R153 (poll-until-settled — touches confirmed-closed invariant), general scanner-page redesign.

## Total Requirements Count: ~196 raw (R1-R196), partitioned ~118 MUST / ~38 SHOULD / ~21 WON'T-NOW
## Rounds Completed: 3 (LITE mode per user directive)
