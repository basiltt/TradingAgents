# Discovery Summary — Post-Market-Scan Optimization

**Feature:** Optimize the post-market-scan steps — (1) live WebSocket status, (2) parallelization/perf, (3) centralized Bybit rate-limit compliance, (4) UX polish.
**Date:** 2026-06-14
**Skill:** `/new-feature`

---

## 1. Repository Overview

- **Backend:** FastAPI (Python 3.12+, asyncio throughout), `backend/`. PostgreSQL via `asyncpg` (`AsyncAnalysisDB`).
- **Frontend:** React 18 + TypeScript (strict) + Vite + TanStack Query/Router, `frontend/src/`. Dark **neumorphic** theme (CSS variables `--neu-*`, Tailwind, `cn()` util).
- **Trading engine:** LangGraph multi-agent at `tradingagents/`.
- **Architecture style:** Service layer (`backend/services/`) + thin routers (`backend/routers/`), Pydantic v2 schemas (`backend/schemas/__init__.py`), app-wide singletons wired in `backend/main.py` lifespan onto `app.state`.

---

## 2. What "post-market-scan steps" actually are

After per-symbol analysis finishes, `ScannerService._run_scan` (`backend/services/scanner_service.py`, **lines 1298-1397**) runs this **sequential** auto-trade tail against `AutoTradeExecutor` (`backend/services/auto_trade_service.py`):

| # | Call | Location | What it does |
|---|------|----------|--------------|
| 1 | `executor.execute_batch(all_results)` | scanner_service:1312; auto_trade_service:**795** | Batch-mode configs → dedup tickers → per-account, per-symbol `_try_trade` (places orders). Holds `self._lock`. |
| 2 | `executor.fill_immediate_remaining(all_results)` | scanner_service:1318; auto_trade_service:**838** | Backfill immediate-mode `fill_to_max_trades` slots. Holds `self._lock`. |
| 3 | `executor.post_scan_recheck(all_results)` | scanner_service:1325; auto_trade_service:**961** | Re-check accounts skipped due to open positions / close_on_profit threshold; per-account network I/O OUTSIDE lock (961-1090+). |
| 4 | `executor.cleanup_unused_rules()` | scanner_service:1353; auto_trade_service:**924** | Delete close rules for accounts with 0 trades. Per-rule DB deletes. |
| 5 | `executor.get_summaries()` / `emit_account_summaries()` | scanner_service:1360,1369; auto_trade_service:**865/888** | Build per-account summary dicts; emit debug account traces (per-account `get_account` lookups). |

**Pre-step (also slow):** `executor.init_balances()` (auto_trade_service:**469-770**) runs BEFORE the per-symbol scan in `start_scan`, but is the same money-critical class of per-account sequential network I/O. It is invoked on the manual re-run path at `backend/routers/scanner.py:252`.

**Manual re-run path:** `POST /scanner/{scan_id}/auto-trade` (`backend/routers/scanner.py:160-349`) runs the SAME 5-step sequence in a background task `_run_auto_trade` (252-321). **Any optimization must cover both call sites.**

---

## 3. THE SLOWNESS — sequential `await` hot spots

All of these are **per-account or per-symbol sequential awaits** that can be parallelized (bounded):

### `init_balances` (auto_trade_service:469-770) — the biggest offender
- **Lines 489-536:** per-account loop `accounts_with_close_target` → each does `await get_wallet` + `await list_rules` + (maybe) `await close_all_positions` + `await asyncio.sleep(2)`. Sequential.
- **Lines 540-770:** the main per-`state` loop → per account: `await get_account` (549-555), `await _is_account_paused` (562), `await _account_in_cooloff` (566), `await get_positions` (577), `await get_wallet` (596), plus close-rule creation network calls further down. **All sequential, one account at a time.**
- Caches exist (`positions_cache`, `account_valid_cache`) but only dedup WITHIN the loop — they don't parallelize across accounts.

### `execute_batch` (795-836) / `evaluate_result` (774-793) / `fill_immediate_remaining` (838-863)
- Nested loop: for each batch `state` (account-config), for each `unique_result` (symbol) → `await self._try_trade(...)` (824). `_try_trade` → `_do_place` (1788) → `place_trade` (places a real order: `get_mark_price`+`get_instrument_info` gathered, then `set_leverage`, then `place_market_order`, then `set_trading_stop`). **Sequential across symbols AND across accounts**, all under `self._lock` (797).
- **Cross-account independence:** different accounts are independent (separate `BybitClient`, separate balances). Symbols within one account are sequenced by design (slot counting, dedup `traded` set, `existing_symbols`).

### `post_scan_recheck` (961-1090+)
- **Lines 1014+:** `for account_id, states in accounts_to_recheck.items():` → per-account `await get_positions` (1017), `await get_wallet` (1035/1082), `await list_rules` (1041), `await close_all_positions`+`sleep(2)` (1064-1065), then places trades. Sequential across accounts.

### `cleanup_unused_rules` (924-960) & `emit_account_summaries` (888-922)
- Per-rule `await delete` and per-account `await get_account` label lookups, sequential.

**Conclusion:** The dominant axis to parallelize is **across accounts** (independent), with bounded concurrency. Symbol-level ordering within an account must be preserved.

---

## 4. Shared mutable state & concurrency primitives (RACE-CRITICAL)

`AutoTradeExecutor.__init__` (auto_trade_service:77-104):
- `self._state: Dict[str, _AccountState]` — keyed `f"{account_id}_{i}"`. Each `_AccountState` (class at line **2009**) holds: `trades_executed`, `trades_failed`, `trades_skipped`, `executions[]`, `existing_symbols set`, `stopped`, `stopped_reason`, `base_capital`, `close_rule_id`, `drawdown_rule_id`, `created_rule_ids`, MR flags.
- `self._lock = asyncio.Lock()` (91) — single executor-wide lock; `execute_batch`/`fill_immediate_remaining`/`evaluate_result` run ENTIRELY inside it. `post_scan_recheck` only snapshots under it then releases.
- `self._position_lock_registry` (94) — per-(account,symbol) lock guarding placement vs AI-manager/close loop.
- `self._ai_manager_enabled_accounts: set` (95), `self._ai_manager_disabled_caps: Dict` (98).
- Per-scan caches: `self._mr_mean_cache`, `self._mr_price_cache` (reset in `init_configs`).
- Cross-config dedup `traded: set` of `(account_id, symbol)` is **function-local** to execute_batch/fill (NOT instance state) — shared across accounts within ONE call. **This is the key cross-account coupling:** the dedup set prevents two accounts... actually it's `(account_id, symbol)` keyed, so it's per-account-symbol — accounts are independent on the dedup axis too.

**Implication for parallelization:** Parallelizing across accounts means each account's `_AccountState` is touched by exactly one task → no per-state races. The shared `traded` set and `executions` list appends need a lock OR per-account partition then merge. The `self._lock` currently serializes everything; a redesign must replace coarse serialization with per-account isolation + bounded gather, without weakening the per-(account,symbol) placement lock.

---

## 5. Bybit rate limiting — current state

### Centralized gate ALREADY EXISTS: `backend/services/bybit_rate_gate.py`
- `BybitRateGate` process-wide singleton (`get_rate_gate()`), rolling-window token gate.
- Channels: `public` (budget 400/5s), `private` (budget 100/5s), `ws_connect` (450/5min).
- Lanes (priority on private): `order` (full budget, shortest backoff), `live` (default, reserves 1 slot headroom), `mcp` (reserves 25%).
- `acquire_async(channel, lane)` and `acquire_sync(channel, timeout)`.

### Where it's applied
- `bybit_client.py:_request` (130) → `_wait_for_rate_limit` (222) → `get_rate_gate().acquire_async(channel="private", lane=lane)`. **EVERY** bybit_client HTTP call goes through it. Order/leverage use `lane="order"` (place_market_close_order:381, set_leverage:420, place_market_order:469).
- Plus a per-client `self._semaphore = asyncio.Semaphore(10)` (bybit_client:47) — caps concurrency PER ACCOUNT client.

### GAPS identified (requirement #3)
1. **Channel mis-assignment:** `_wait_for_rate_limit` ALWAYS uses `channel="private"` (226), even for PUBLIC endpoints `get_mark_price` (529), `get_instrument_info` (543), `get_kline`/`get_tickers`. Public calls wrongly consume the scarce private budget (100/5s) instead of public (400/5s). Bybit classifies market endpoints as public/IP-limited.
2. **No per-endpoint limit:** Bybit non-VIP has PER-ENDPOINT limits (e.g. order create/amend/cancel **10 req/s**, position/wallet **10-20 req/s** per UID). The gate is a single global IP-window counter — it does NOT enforce per-endpoint caps. Under heavy multi-account post-scan order bursts this can trip `10006`/per-endpoint 429s (the client retries on `is_rate_limited`, 186-197, but that's reactive, not preventive).
3. **Per-UID vs per-IP:** Bybit private limits are PER UID (per account); public are per IP. The gate is purely per-IP/global. Multiple accounts share the single private budget of 100/5s — overly conservative for private (each UID has its own 10/s order budget) yet not enforcing the real per-UID per-endpoint cap.
4. **`market_data.py` fetcher / `kline_cache_service.py`:** kline fetches during scan — need to confirm they route through a rate-gated path (the F2/regime fetcher). `market_data._build` already bounds concurrency with `asyncio.Semaphore(concurrency=8)` (222).

### NOT the Bybit limiter (don't confuse): `backend/rate_limit.py`
- That is the API-side limiter for OUR OWN HTTP API clients (inbound request throttling), unrelated to Bybit egress.

---

## 6. WebSocket / progress infrastructure (requirement #1)

### Current scan progress delivery = POLLING (the "one shot at the last")
- Frontend `ScannerPage.tsx:479-488`: `scanQuery` polls `GET /api/v1/scanner/{scan_id}` every **3000ms while running**, stops when terminal.
- `auto_trade_results` / `auto_trade_summaries` are attached to the scan dict and only become visible once the WHOLE post-scan tail finishes and `_serialize` (1084-1120) returns them. The 3s poll only sees the FINAL state → "everything in one shot at the last."
- Rendered at `ScannerPage.tsx:1190-1251` (executions list + account-status + AI-manager-reduced-protection blocks).

### Two existing WS patterns to mirror
**(A) EventBus + WSManager** (`backend/event_bus.py`, `backend/ws_manager.py`, `backend/routers/ws.py:38`): used for per-symbol ANALYSIS streaming, keyed by `run_id`. Heavyweight (ring buffer, snapshot replay, heartbeat). Scanner only uses `ws_manager.broadcast(SCAN_LIST_TOPIC, ...)` for scan-list-changed (scanner_service:390-393); it does NOT stream scan progress.

**(B) BacktestProgressManager** (`backend/services/backtest_progress_manager.py`) + `ws_backtest.py:34` + frontend `useBacktestProgressWS.ts` — **THE IDEAL REFERENCE MODEL.** A tiny per-run pub/sub:
- `emit(run_id, stage, label, detail, pct, status)` → appends to bounded history + fans out to subscriber queues. Terminal GC after 60s.
- WS endpoint `/ws/v1/backtest/{run_id}` (ws_backtest.py): `subscribe()` (replays history first), ping/pong keepalive, closes on terminal stage.
- Service emits via `_emit_stage` (backtest_service:2149-2160) at each named stage.
- Frontend hook `useBacktestProgressWS(runId, active)` — coalesces by stage, reconnect w/ backoff, StrictMode-safe teardown, exposes `{steps, pct, connected, terminal}`.

**Decision:** Build a `ScanAutoTradeProgressManager` mirroring `BacktestProgressManager`, a `/ws/v1/scanner/{scan_id}/auto-trade` (or `/ws/v1/scan/{scan_id}/progress`) endpoint mirroring `ws_backtest.py`, and a `useScanAutoTradeProgressWS` hook mirroring `useBacktestProgressWS`. Wire the manager onto `app.state` in `main.py` (mirror line 312) and emit from the executor / scanner post-scan tail.

### Wiring reference (`backend/main.py`)
- Managers created in lifespan and attached to `app.state` (event_bus:242, ws_manager:243, backtest_progress_manager:312).
- WS routers imported + included (ws_backtest_router import:734 — note WS routers are included WITHOUT the `/api/v1` prefix; `/ws/...` is top-level).

---

## 7. Frontend map (requirements #1 & #4)

- `ScannerPage.tsx` (1679 lines): big stateful page. Header stat cards, `Tabs` (`@/components/ui/tabs`) with Results/Progress/Config. Progress tab at **1162-1260+**: progress bar (1167-1178), stat cards `ScannerMetricCard` (1181-1188), auto-trade executions (1190-1217), account status (1219-1234), currently-analyzing chips (1252+).
- Data: `scanQuery` (3s poll, 479), `configQuery` (431), `accountsList` query (333), `startMutation`/`cancelMutation` (455/460).
- UI primitives: `@/components/ui/*` (tabs, button, etc.), local `ScannerMetricCard` + `TonePill` (defined in ScannerPage), neumorphic classes `neu-surface-*`, `--neu-*`, `--shadow-*`, `gradient-primary`.
- Reference hooks: `useBacktestProgressWS.ts` (model), `useAnalysisWebSocket.ts`, `useAccountWebSocket.ts`. WS base: `import.meta.env.VITE_WS_BASE_URL || ws(s)://window.location.host`.
- `ScanDetailPage.tsx` (637) — historical scan view (DB-backed). `AutoTradeSection.tsx` (992) — auto-trade CONFIG form (not execution status).

---

## 8. Key constraints / risks

- **Money-critical:** behavior must be byte-for-byte preserved. Parallelization must not double-place, mis-count slots, or weaken the per-(account,symbol) placement lock. Symbol ordering within an account is semantically meaningful (best-score-first slot fill).
- **Two call sites** for the post-scan tail (auto scan tail in scanner_service + manual re-run in scanner.py). Both must emit progress and both benefit from parallelization.
- **Backtest builds neither** `_close_svc` nor cooloff — guards must stay None-safe; the new progress manager must be optional (None-guarded) so backtests/tests are unaffected.
- **Rate-gate correctness:** Increasing concurrency across accounts raises Bybit request pressure → the centralized gate + (new) per-endpoint controls become MORE important, not less. Public/private channel fix is a prerequisite to safely raising concurrency.
- **Fail-open WS:** progress streaming must never block or break the actual trade execution (mirror backtest: emit is best-effort, never raises).
- **DB persistence cadence:** `_append_auto_trade_results` (1156) appends under lock + persists; incremental emission must keep DB state consistent for late/no-WS clients (polling fallback must still converge to correct final state).

---

## 9. Initial assumptions (risk-rated)

| # | Assumption | Risk |
|---|-----------|------|
| A1 | Cross-account parallelism is safe with bounded concurrency; within-account symbol ordering preserved | Low |
| A2 | Mirror BacktestProgressManager pattern rather than reuse EventBus (simpler, proven) | Low |
| A3 | Fix public/private channel assignment in bybit_client per endpoint type | Low |
| A4 | Add per-endpoint token control (order=10/s) inside the centralized gate as a new channel/sub-limit | Medium |
| A5 | Keep `self._lock` semantics by partitioning per-account work, merging results deterministically | Medium |
| A6 | Polling (3s) stays as fallback; WS is additive (progressive enhancement) | Low |
