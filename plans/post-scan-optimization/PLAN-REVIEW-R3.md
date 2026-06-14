# Plan Review — R3 Findings & Resolutions (CONVERGED)

Round 3 (2 agents, code-verified). Backend verdict: **PLAN-READY** (3 minor pin-at-Step-12 items). Frontend: one substantive cross-layer fix (R3-F1) + prose tightening. Resolutions below are AUTHORITATIVE and complete the plan. Plan review CONVERGES here.

## The one substantive fix

**PR3-1 — Auto-tail WS `active` predicate must cover the RUNNING window (frontend R3-F1).** Verified against code: the post-scan tail's placement steps (`execute_batch`/`fill`/`recheck`, `scanner_service.py:1300-1328`) run **BEFORE** the in-memory `scan["status"]` is set to `"completed"` (that happens at `:1330-1348`, AFTER placement). So a predicate keyed on `status==="completed" && summaries-absent` is FALSE during the actual live trade placement → the WS never opens during the window the user most wants to watch, defeating FR-010..024 on the auto path.
**Resolution (TASK-1.8, FR-019):** the auto-tail `active`/WS-open predicate is:
`auto_trade_config_count>0 && (scan.auto_trade_summaries?.length ?? 0)===0 && !wsTerminalReceived && (status==="running" || status==="completed") && withinUpperTimeBound`.
I.e., open the WS whenever the scan has auto-trade configs, no summaries yet, no terminal event received, and the scan is running-or-just-completed — with the upper time bound (FF-1) closing it if no terminal arrives. During the early symbol-analysis phase the WS opens and simply shows pending steps (fail-open, no events yet) — acceptable. This makes the live placement window observable. The manual-rerun leg is unchanged (trigger→terminal). PR2-14's `tailActiveOrWas` latch is driven by THIS predicate (so it latches true during the running tail and correctly suppresses the auto-switch).

## Backend pin-at-Step-12 (non-blocking, resolvable from existing code)

**PR3-2 — `scan_error` in the orchestrator guard (backend R3-F1).** PR2-1's internal placement gate must include `scan_error`: gate execute_batch/fill/recheck on `(not scan_error and not cancelled and not too_many_failures and bool(results))`; invoke `run_post_scan_tail` on BOTH branches so cleanup/summaries always run when an executor exists (matching today's looser `if executor:` at 1351). Pass `scan_error` in alongside `cancelled`/`too_many_failures`/`all_results`. Add a `scan_error=True → zero placements, cleanup+summaries still emitted` test.

**PR3-3 — Manual `too_many_failures` data source (backend R3-F2).** TASK-2.2: the manual path loads `failed_count`/`total` from the persisted scan row (`async_persistence.py:1309`) to compute `too_many_failures` before calling `run_post_scan_tail`. (If an implementer instead passes `False`, that is today's behavior = safe — but then drop the "gains the gate" claim. Prefer loading the counts for true alignment.)

**PR3-4 — TASK-0.6 cache wording (backend R3-F3).** `kill_switch.read_kill_switches` is currently un-cached (direct `db.pool.fetch`). TASK-0.6's "hot cache, short TTL" is NEW caching for the gate-boundary reads ONLY; the between-accounts fan-out kill (`post_scan_fanout_disabled`) calls the direct un-cached reader (max latency = one between-accounts gap; fail-closed `{"__all__":True}` already forces sequential = safe).

## Frontend prose tightening (R3-F2/F3/F4)
- Unify the single-renderer under ONE boolean `showPanel = PHASE2_DEPLOYED && auto_trade_config_count>0 && dataPresent` (where `dataPresent = wsEventCount>0 || (auto_trade_summaries?.length ?? 0)>0 || (auto_trade_results?.length ?? 0)>0`); update TASK-1.7's literal "mount only when config>0" to this. The legacy block `1190-1234` renders only when `!showPanel`.
- Define `wsEventCount` in TASK-1.6 = `steps.length + accounts.length + orders.length > 0` (or an explicit counter).
- Enumerate the panel's persisted-data props for cold-load (`auto_trade_summaries`, `auto_trade_results`, `config` for cold-load dry_run + ordinal join) so cold-load/Phase-1-alone renders content, not blank.

## Affirmed SOUND (R3 verified)
- Backend money-path: the strict auto-path placement gate (no placement on >50% fail / cancel / scan_error) is preserved exactly; per-account partition/merge-from-state, shield span, golden tuple all unambiguous.
- PR2-2 (register 3 kill-switches) — exactly 2 consumers (`admin.py:27`, `test_features_registry.py:11`), side-effect-free.
- PR2-4 (RateGateBanAbort caught inside the task) — coherent with merge-from-state.
- PR2-5 (exclude reference_value) — still catches wrong-type/threshold/missing-rule regressions.
- PR2-6 (fan-out kill direct read) — coherent; fail-closed = sequential = safe.
- No PR2-vs-PR2 contradiction; PR2-3 correctly supersedes the PR1 "≥1 WS event" low.
- PR2-7/8/12/13/14 coherent (PR2-14 latch driven by the PR3-1 predicate).

## VERDICT: PLAN-READY — CONVERGED
3 rounds complete (LITE directive). All blockers resolved; remaining items are Step-12 implementation pins resolvable from existing code. The money-critical auto-path gate is intact and unambiguous; the frontend live-stream path is now reachable (PR3-1). Plan is executable end-to-end.

**Effective plan = phase files + PLAN-REVIEW-R1 (PR1) + PLAN-REVIEW-R2 (PR2 supersedes PR1) + PLAN-REVIEW-R3 (PR3 final). Implementation (Step 12) applies all three resolution layers.**
