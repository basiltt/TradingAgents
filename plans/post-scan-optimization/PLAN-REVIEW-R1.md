# Plan Review — R1 Findings & Resolutions

Round 1 (5 agents, code-verified) found the plan largely sound (dependency ordering, TDD coverage, rollback intent, no-migration story all correct) with mechanical gaps. Resolutions below are AUTHORITATIVE and amend the phase files. Applied at implementation time (Step 12) and reflected in plan-validation (Step 10).

## Blocking / High resolutions

**PR1-1 — `set_trading_stop` does NOT exist in `place_trade`; TP/SL are INLINE (backend F1/F2, frontend, qa).** Verified: `accounts_service.place_trade` calls `set_leverage` → `place_market_order` (which sends `takeProfit`/`stopLoss` inline in `/v5/order/create`, `bybit_client.py:459-463`) → DB write. There is NO separate `set_trading_stop` in the placement path.
**Resolution:** (a) TASK-2.5 shield span = **`set_leverage → place_market_order`** (TP/SL inline → position protected the instant the order returns); the DB write (`accounts_service.py:435-475`) is **OUTSIDE** the shield = the accepted orphan window (TASK-2.8). (b) The shield is INNER to the existing `asyncio.wait_for(place_trade, timeout=30)` (`auto_trade_service.py:1828`): a timeout can still abandon the DB write → routes to the orphan log; add a test "timeout mid-shield → order placed w/ inline TP/SL, orphan logged". (c) FF-4's "`set_trading_stop` on lane=order" applies to the SEPARATE standalone `set_trading_stop` (`bybit_client.py:554`) used elsewhere (e.g. AI-manager/close paths), not the placement path — keep that lane fix in Phase 0 but note it does not affect `place_trade`.

**PR1-2 — Golden tuple `orderLinkId`/rule-id are non-deterministic; fix the comparison (qa F1/F2/F3, product F2).** `orderLinkId` is a fresh uuid per create (CR-1 withdrawn by SC-1d); rule IDs are DB-serial/uuid.
**Resolution (TASK-2.10):** (a) **Pin the mock interception boundary at the HTTP transport (`_request`)** so the real payload/lane/orderLinkId-construction path is exercised. (b) **Exclude `orderLinkId` and raw `order_id`/rule-id from the equality tuple**; instead assert presence + uniqueness + correct `(account,symbol)` mapping. (c) Compare close rules on the **normalized identity `(symbol, rule_type, params)`** per account (created-set and cleanup-deleted-set), not raw IDs. The equality tuple becomes `(account, symbol, side, size, leverage, tp, sl, reduceOnly)` ordered per account.

**PR1-3 — Fan-out has NO real runtime revert; the Semaphore can't resize (migration F2/F3, product F4).** A constructed `asyncio.Semaphore(width)` cannot be resized at runtime, so "set width=1 at runtime" and the admin width-override are both inert as written.
**Resolution:** TASK-2.3 builds a **resizable limiter**: read the effective width from a **hot config/kill-switch at each tail launch AND re-check it at the cooperative between-accounts safe point** (not a fixed Semaphore). Implementation = a width read per `run_post_scan_tail` invocation that bounds the `gather` batch size, plus a `post_scan_fanout_disabled` kill-switch (THIRD flag, added to TASK-0.6) that forces strict sequential regardless of configured width (FR-040). The admin width-override (TASK-3.3) writes the hot config the next launch reads. This is the real runtime revert.

**PR1-4 — Manual re-run tail is NOT drainable at shutdown (migration F1).** The manual `_run_auto_trade` task lives in a router-level `_background_tasks` set the lifespan never awaits.
**Resolution (TASK-2.8/FR-048):** register the manual tail task in a registry the lifespan drains (add it to a `scanner_service`-tracked set, or add a router-level drain step awaited before loop teardown). Add a test: deploy-mid-manual-tail drains the shielded span.

**PR1-5 — Kill-switch polarity/default-state + correct file (migration F4/F9, product F9).** The real reader is `backend/services/kill_switch.py` (`feature_kill_switches`, `is_killed`: no row = NOT killed = feature ACTIVE; fail-closed to all-killed on DB error). `feature_flags.py` does not exist.
**Resolution (TASK-0.6):** (a) Use `kill_switch.py` + the existing `admin.py` flip endpoint; drop the `feature_flags.py` reference. (b) **Polarity:** the new switches are REVERTS — the channel-fix + per-endpoint-limiter are **correctness fixes that ship ON** (no row = active); a `killed=true` row REVERTS to current behavior. Reconcile the Phase-0 header wording: "when the REVERT switch is set, fall back to current behavior." (c) Because they ship ON, **TASK-3.7 steady-state regression must gate the Phase-0 deploy** (pull it forward, or ship the flags as `killed=true` dormant until the regression suite passes, then flip live). Add first-deploy (empty table) + fail-closed tests.

**PR1-6 — `init_balances` orchestrator boundary is ambiguous (product F1/F11, backend F4).** Auto path runs `init_balances` pre-scan (inside `start_scan`); manual path runs it at `scanner.py:252`. The tail extraction must not make the manual path skip it.
**Resolution (TASK-2.2):** `run_post_scan_tail(results, *, run_init_balances: bool)` — auto passes `False` (already ran pre-scan), manual passes `True`. The extracted tail is EXACTLY the 5 calls (execute_batch, fill, recheck, cleanup, summaries) WITHOUT the `scanner_service.py:1330-1348` status-finalize block (that stays in `_run_scan`). The stepper (TASK-1.7): `init_balances` is shown as a step only on the manual path (auto runs it pre-`completed` so its emits would land before the panel is active) — OR drop it from the auto stepper. The pre-tail `refresh_configs` call (`scanner_service.py:1310`) stays before the fan-out launch (the no-refresh-during-fan-out invariant).

## Medium resolutions

**PR1-7 — FR-037 (pre-flight feasibility + pool dimension) unmapped (product F3, qa F12).** **Resolution:** Fold FR-037 into TASK-0.7/FR-049 AND add a per-tail check in TASK-2.3: before launch, project the tail's peak 5s PRIVATE load (`W × placements × ~10 private calls`) + pool dimension (`width × DB-ops-per-account ≤ DB_POOL_MAX − reserved`) and auto-reduce the effective width if it would exceed private ≤80/5s, combined-IP ≤480/5s, or starve the pool. Add a test (per-tail projection above budget → width reduced before launch).

**PR1-8 — `_fill_to_max` contract change must cover ALL THREE callers (backend F6).** **Resolution (TASK-2.4/2.6):** change `_fill_to_max` to accept a per-account-local `traded` set + drop the `assert self._lock.locked()`; update batch (834), fill (861), AND `post_scan_recheck` callers in the same change.

**PR1-9 — `dry_run` + `cooloff_until` event fields missing (product F5, frontend F3/F4, backend F6).** **Resolution:** Add `dry_run: bool` and `cooloff_until` (absolute) to the `ScanAutoTradeProgressEvent` (TASK-1.2) + emit signature (TASK-1.1) + TS type. The FE DRY/LIVE badge (TASK-3.1) reads `dry_run`; the cooloff countdown (TASK-3.2) computes `cooloff_until - now` (survives replay). The executor maps `RateGateBanAbort` (which carries `cooloff_until`, TASK-0.4) → `_emit_progress(substatus="ban", cooloff_until=...)`. Route `X-Bapi-Limit-Status` from `bybit_client` into the gate's near-ban hook.

**PR1-10 — `RateGateBanAbort` handling (backend F3).** **Resolution (TASK-0.4/2.x):** `RateGateBanAbort` subclasses **`BaseException`** (so `_do_place`'s broad `except Exception` at `auto_trade_service.py:1959` cannot swallow it); the tail catches it ABOVE the generic handler, releases the position-lock (the `finally` at 1693 already does), and either re-queues OR (simpler, parity-with-today) records it as skipped/failed — pick "skipped + emit ban substatus" so the run continues for other accounts. Carry `cooloff_until` on the exception.

**PR1-11 — Width-1 exact-sequential oracle path (backend F13, qa F9/F13).** **Resolution (TASK-2.4):** at width=1, short-circuit to **direct await in `self._state` insertion order (no `gather`)** so the oracle path is byte-identical. Capture a **golden-master baseline** from current `main` at width=1 (recorded placement sequence + counts for the seed scenarios) so the DoD #3 "byte-identical to today" has a real pre-change oracle. Run the golden ALSO at width=N (number of seeded accounts) to exercise full interleave (not just width=2).

**PR1-12 — Deterministic test seams (qa F6/F11, product).** **Resolution:** Add named `asyncio.Event`/barrier seams in `run_post_scan_tail` at: between-account launch, inside the shielded span (before the order returns), before `create_trade` commit, and inside the mock `record()`. Mock market data = pure fn of `(symbol)` (time-independent, so price-drift skips are deterministic); poll-count = pure fn of `(account_id, symbol)`; the rate-aware 10006 threshold = pinned to the gate's enforced caps (private 100/5s, per-UID 8/s) with stated window/aggregation. Replace TASK-2.4's "no double-placement" assertion with a single-writer detector on `_AccountState` (each state's writer task-id constant).

**PR1-13 — Missing money-critical tests (qa F4/F5/F10/F15).** **Resolution:** Add: (a) **ban-during-tail lock-release** test (task holds position-lock → set `_ban_until=now` → assert `RateGateBanAbort` + lock released + concurrent CloseRuleEvaluator close acquires within a bound); (b) **mid-fan-out kill-switch** test (flip `post_scan_fanout_disabled` after account A's safe point → account B never launches, terminal "killed" emitted); (c) a **fail-injected golden seed** (one account errors mid-batch + the exactly-50%-failure boundary → counts/reason_codes/persisted-orders equal across modes); (d) cancel-orphan-window **cleanup-skip** assertion (FR-035: interrupted account's rules not deleted).

## Low resolutions (folded into plan at Step 12)
- TASK-2.10 wording: `max_same_sector`/`max_same_direction` are **per-account** (verified) — reword "cross-account overshoot guard" → "per-account cap holds identically parallel-vs-sequential" (keep as seeds). (backend F7, qa F14, product)
- TASK-3.4: `FR-119` → `R119` typo. (product F12)
- TASK-1.4 line refs: `_serialize`=1084, `_serialize_db`=1122 (def lines). (frontend F8)
- TASK-1.4/FF-3: stamp `acct_ordinal` at `get_summaries()` (upstream, opaque through serializers — no dual-serializer edit); add `acct_ordinal?: number` to FE `AutoTradeSummary`; terminal handoff SUMS the N summary rows sharing one `account_id` into the ordinal row. (frontend F6, product F13)
- TASK-1.8 predicate: use `(scan.auto_trade_summaries?.length ?? 0) === 0` for the "absent" leg; the WS `terminal` flag + upper time bound authoritatively clear `active` (summaries-empty alone is ambiguous). (frontend F1)
- TASK-1.8 auto-switch: **permanently suppress** the running→completed auto-switch when a tail is active (user stays on Progress to watch the panel) — simplest; documented. (frontend F2)
- TASK-1.7 single-renderer gate: render legacy `1190-1234` only when `!(panel mounted)`; panel owns live+terminal when mounted; legacy block is also the error-boundary fallback. (frontend F7)
- BybitClient `account_id` = OPTIONAL kw (default None → per-endpoint dim disabled, matches revert-switch); enumerate construction sites. (backend F8)
- `acquire_sync` has no real callers (`_do_sync_time` is async → `acquire_async`); mark the sync-mirror work defensive/deferred (don't ship an untested money-path branch). (backend F9)
- DoD §F additions: (7) revert-switches in their ship state + (8) TASK-3.7 steady-state regression green + (9) FR-049 startup validation active, all required before width>1. Cap production at validated width=2 until a width-N gate exists. (product F8, migration F6)
- Phase 1+2 deploy coupling: gate the single-renderer suppression on "≥1 WS event received this scan" (fall back to legacy/polled block until then) so shipping Phase 1 alone doesn't blank the panel. (migration F7)
- Tracker D15 note corrected to "detect + alert → manual" (already correct in plan files). (product F15)
- Scan-row terminal status write stays strictly AFTER tail finalization + final commit (test). (migration F11)
- Width-override does not persist across deploy (reverts to config default=1 — safe; documented in operator notes). (migration F10)

## Affirmed SOUND (R1 verified)
- Phase 0 → Phase 2 dependency ordering correct; Phase 1 fail-open/None-safe.
- No DB migration (all reuse existing JSONB columns / config-derived fields).
- Default concurrency=1 ships; golden asserts byte-identical.
- Resume de-scope does NOT open a new width-1 hole (parity-with-today verified: `resume_incomplete_scans` already drops an interrupted tail today).
- TASK-0.2 all-or-none sub-limiter is implementable in the existing await-free critical section.
- TASK-2.4 account-axis partition is sound (disjoint per-account state).
- TASK-2.8 orphan→reconciler ALERTS (not adopts) — correctly characterized.
- All cited line numbers verified accurate.
