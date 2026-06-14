# Plan Review — R2 Findings & Resolutions

Round 2 (3 agents, code-verified) verified the PR1 resolutions and found new coupling defects the resolutions introduced + residual determinism/display gaps. Resolutions below are AUTHORITATIVE (supersede PR1 where they conflict). Applied at Step 12 + plan-validation.

## High

**PR2-1 — too_many_failures guard must move INSIDE the orchestrator (qa/backend R2-F2).** Verified: in `_run_scan` the strict guard `if executor and all_results and not cancelled and not too_many_failures` (>50% symbols failed = money-safety gate, `scanner_service.py:1307-1309`) wraps ONLY execute_batch/fill/recheck (1312-1328); `cleanup_unused_rules`+`get_summaries` run under a LOOSER `if executor:` (1351). A single `run_post_scan_tail` under one call-site guard regresses one path. The manual path has NO too_many_failures guard today.
**Resolution (TASK-2.2):** `run_post_scan_tail` applies the guards INTERNALLY — gate execute_batch/fill/recheck on `(not cancelled and not too_many_failures and all_results)`; ALWAYS run cleanup/summaries when an executor is present. Pass `cancelled`/`too_many_failures`/`all_results` in. **The manual path now gains the too_many_failures gate** (a deliberate behavior alignment — document it). Add tests: `too_many_failures=True` → zero placements but summaries still emitted; manual-path parity for the same gate.

**PR2-2 — Register the 3 new kill-switches; the revert endpoint rejects them otherwise (qa R2-F1).** Verified: `admin.py:60` 422-rejects any `feature_name` not in `KILL_SWITCH_FEATURES` (`features.py:20-22` = regime-only `{__all__, f1, f2, f2_long}`); `test_features_registry.py:11` asserts EXACT frozenset equality. The PR1-5/DoD-§F#7 operator-revert path is INERT for the new switches.
**Resolution (TASK-0.6):** add `rate_gate_channel_fix`, `rate_gate_per_endpoint_limiter`, `post_scan_fanout_disabled` to `KILL_SWITCH_FEATURES` AND update `test_features_registry.py:11`. State this in TASK-0.6. (Small change; it IS the money-safety revert path.)

**PR2-3 — Single-renderer mount/suppress axes must be unified (frontend R2-F1, BLOCKER).** The PR1 resolutions contradict for the common case (viewing any finished auto-trade scan): the panel mounts on `auto_trade_config_count>0` (true for every historical auto-trade scan), but the active predicate is FALSE on a completed scan WITH summaries → WS never opens → 0 events → the "suppress legacy only after ≥1 WS event" gate never engages → legacy block AND panel both render (double-render / FF-2 violation).
**Resolution:** Suppress the legacy block on **data-presence, not WS-event-count**: render legacy `1190-1234` only when `!(panelMounted && (wsEventCount>0 || (scan.auto_trade_summaries?.length ?? 0)>0 || (scan.auto_trade_results?.length ?? 0)>0))`. The panel OWNS the live+terminal+cold render once mounted with data; the legacy block is the error-boundary fallback only. The Phase-1-alone-blank guard is driven off a **Phase-2-deployed build flag** (not per-scan events) — so shipping Phase 1 without Phase 2 keeps the legacy block; once Phase 2 ships, the panel owns it. Mount axis (`auto_trade_config_count`) and suppress axis now share the data-presence axis.

## Medium

**PR2-4 — RateGateBanAbort must be caught INSIDE each per-account task (backend R2-F1).** `gather(return_exceptions=True)` captures BaseException children too; merging from `self._state` (not gather returns) would discard the ban → no substatus emit, no skipped accounting.
**Resolution:** the `except RateGateBanAbort` lives INSIDE each per-account task body (before returning to gather): release the lock (the `finally` at 1693 already does), set `_AccountState` skipped + ban reason, `_emit_progress(substatus="ban", cooloff_until=…)`, return normally. Add a test asserting the ban substatus is emitted (not just lock released). Never catch it with bare `except:`/`except BaseException`.

**PR2-5 — Close-rule `reference_value` is a wall-clock timestamp → golden non-determinism (qa R2-F2).** Verified: close rules embed `reference_value = datetime.now(utc).isoformat()` (`auto_trade_service.py:689,707,1193,1212` + MR). PR1-2's normalized `(symbol, rule_type, params)` includes it → deterministic divergence parallel-vs-sequential.
**Resolution (TASK-2.10):** EXCLUDE `reference_value` and any `now`-derived field from the close-rule identity tuple (keep `threshold_value` which is config-derived); OR inject a frozen-clock seam so both runs stamp identical values. Prefer exclusion.

**PR2-6 — Fan-out kill must bypass the TTL cache (qa R2-F3).** PR1-3's between-accounts re-read vs TASK-0.6's "hot cache short TTL" → the mid-fan-out-kill test passes only by timing luck; prod emergency-stop has up-to-TTL latency.
**Resolution:** the fan-out kill (`post_scan_fanout_disabled`) is read with a **cache bypass** (TTL=0 / direct read) at the between-accounts safe-point; state max effect latency = one between-accounts gap. The PR1-13(b) test uses the direct read.

**PR2-7 — `acct_ordinal` needs ONE canonical derivation both sides (frontend R2-F2).** It's the only bridge between a salted-handle live row and its raw-`account_id` summary rows; if emit assigns by fan-out order and `get_summaries` by enumerate order, the terminal SUM mis-assigns counters.
**Resolution:** define ONE canonical ordinal = index into the **config-ordered distinct-`account_id` list** (or `sorted(account_id)`); BOTH the Phase-2 emit path and `get_summaries` compute it identically. State in TASK-1.1 + TASK-1.4. Test: emit-ordinal == summary-ordinal for the same account across a multi-account seed.

**PR2-8 — `dry_run` is per-account; the badge must be per-account-row (frontend R2-F3).** The feature's core is multi-account fan-out where account A can be dry_run while B is live. A single panel-level badge misleads.
**Resolution:** per-account-row DRY/LIVE badges (each row reads its own account's `dry_run` from `config.dry_run` at the emit site); any panel-level badge shows "mixed" explicitly when accounts disagree. Pin `dry_run` origin = `config.dry_run`.

## Low (folded into plan at Step 12)
- **PR2-9 (qa R2-F4):** decide+document whether the `__all__` master regime-kill ALSO reverts the post-scan rate-gate fixes (it does, via `is_killed`'s OR). Recommend: document that `__all__` reverts everything (fail-safe, widened blast radius noted in operator notes) rather than decoupling (which would lose fail-closed). Update `admin.py` docstring.
- **PR2-10 (backend R2-F4):** reconcile the 30s `place_trade` wait_for vs 15s `_SHUTDOWN_TIMEOUT`: during drain, cap the placement wait at the shutdown budget OR document that a 30s placement legitimately exceeds the 15s drain and relies on the reconciler. The timeout-mid-shield test asserts the `auto_trade_timeout_phantom_risk` log (`:1952`); the `orphan_order` record assertion is for the pool-timeout test only.
- **PR2-11 (backend R2-F3, frontend R2-F6):** rewrite TASK-2.3/2.4 phase text from "asyncio.Semaphore(width)" to the **chunked-launch model** (read width per launch, re-check between chunks) — drop the fixed-Semaphore phrasing; revert granularity = next chunk. Update TASK-1.1 emit sig + TASK-3.2 to `cooloff_until` (drop vestigial `cooloff_seconds`).
- **PR2-12 (frontend R2-F4):** the new WS endpoint does `await websocket.accept()` BEFORE the 1011 manager-None close (mirror ws_backtest's 4403 accept-then-close ordering, NOT its pre-accept 1011), so the close code reaches the browser and the allowlist's "1011 terminal" is reachable (else it surfaces as 1006 → reconnect storm).
- **PR2-13 (frontend R2-F5):** the hook sets `terminal=true` on ANY non-reconnect close code (1000/4403/4404/1011), so cold-load/replay of an unknown/GC'd scan converges promptly (not only via the time bound).
- **PR2-14 (frontend R2-F7):** the auto-switch suppression keeps `prevScanStatus.current = scan?.status` (line 510) UNCONDITIONAL; only gate the `setResultsTab("results")` call AND set `didAutoSwitch.current = true` when a tail is/was active so the edge is permanently consumed (no post-tail flicker).
- **PR2-15 (qa R2-F5):** state the golden runs the REAL gate at the `_request` boundary and seed peak-rate < the pinned 10006 threshold, so 10006 never fires asymmetrically in the golden (it's a benchmark/concurrency concern, not a golden-equality variable).

## Affirmed SOUND (R2 verified)
- PR1-1 shield span (set_leverage→place_market_order, inline TP/SL, DB write outside, inner to wait_for(30)) — correct.
- PR1-8 _fill_to_max — exactly 3 callers (834, 861, 1266) confirmed.
- PR1-10 RateGateBanAbort(BaseException) — sibling of CancelledError, doesn't break cancel semantics; no code catches it as Exception today (modulo PR2-4 placement).
- PR1-6 init_balances boundary split — correct (modulo PR2-1 guard).
- PR1-3 resizable limiter concept — sound (modulo PR2-11 phase-text rewrite).
- PR1-11 width-1 no-gather oracle + golden-master + width-N — sufficient.
- PR1-4 manual-tail drain — sound (implementer must add the set's own cancel+gather to `shutdown()`).
- PR1-5 polarity (no row=active, killed=true reverts, fail-closed=revert) — coherent (modulo PR2-2 registration + PR2-9 __all__ doc).
