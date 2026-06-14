# FIX-003 — Big-but-calm losers are never closed (loss-cap dead-zone)

**Status:** fixed (2026-06-14) — code + tests; hard-loss force-close added
**Severity:** Critical
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (every AI-managed account)

## Symptom
The AI manager **never closed ESPORTS**, the account's deepest loser. It closed smaller losers
(HMSTR, GWEI, NOKIA, B3) but the one position that most needed closing grew unchecked from −3%
to −19% of equity until it hit its stop.

## Root cause (proven with prod data)
Two facts from `ai_manager_logs` + `ai_manager_llm_calls` (DB-persisted, survive log rotation):
between 02:25 and 03:13, Unni's AI manager ran **47 evaluation cycles but made only 1 LLM call**
(the 02:25 B3 close). So for **46 cycles ESPORTS was dropped *before* the LLM** — it was never
even evaluated.

Two gates produced the dead-zone, both *before* the LLM:
1. **The soft loss cap** (`ai_manager_task.py` ~line 1001): the standard path's
   `max_single_decision_loss_pct = 3%` did `return` for any position losing more than 3% of
   equity. ESPORTS was 5–17% the whole time → skipped every cycle. The gate intended to stop the
   AI realizing a big loss *in one careless decision* instead **guaranteed the biggest loser
   could only grow** — capping the *exit* by loss size is backwards.
2. **The circuit breaker** (`_evaluate` ~line 651): after 3 closes it tripped
   (`circuit_breaker_active=true, count=3`), aborting most evals before the LLM (this overlaps
   with FIX-004).

Net: nothing ever force-closed a big, *calm* loser (no velocity spike, no account-wide equity
crash) — it fell through every gate and bled out.

## Fix (implemented)
Added a deterministic **per-position hard-loss force-close** as a new condition in
`_check_emergency_close` (`ai_manager_task.py`), which runs **before** the LLM, the circuit
breaker, and the token-budget gate:

- New config `max_position_loss_pct` (schema default **8%**, range 1–50, `None` disables) — the
  HARD cap, sitting above the 3% soft cap.
- Condition 3 `position_hard_loss`: any position whose unrealized loss ≥ `max_position_loss_pct`
  of equity is force-closed via the existing emergency batch-close, sparing MR/locked/excluded
  (same filter as the equity-drop and velocity branches) and honoring the 30 s per-symbol
  cooldown.

Two-tier model now: the **soft cap** still governs whether the LLM may *casually* realize a loss;
the **hard cap** is the capital-preservation backstop that cuts a big loser regardless of
velocity/urgency/breaker state. ESPORTS at −17.5% would have been force-closed (verified by
replaying the real snapshot) — in practice caught the first cycle it crossed 8% (~−$8), not −$19.

Tests: `tests/backend/test_ai_manager_hard_loss_close.py` (5 cases: fires on big calm loser;
ignores sub-cap; closes only over-cap; spares MR/locked; disabled when `None`). 5/5 green; 162
adjacent AI-manager/emergency/schema/router tests pass.

## Why not just remove the soft cap
The soft cap has a legitimate purpose (don't let the LLM nonchalantly dump a large loss in one
routine decision). Removing it would lose that guard. The hard cap is the right complement: it
*adds* an aggressive backstop rather than weakening the existing one.

## Verification — done
- ✅ Unit: position at −12%/−15%/−17% of equity → force-closed; −2% → left for the LLM.
- ✅ Real-snapshot replay: ESPORTS (−17.5% of equity, no velocity, ref==equity) → `position_hard_loss` close.
- ✅ No regressions across AI-manager/emergency/schema/router suites.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §3 ("Why the standard path NEVER closed ESPORTS")
- Related: FIX-002 (emergency race), FIX-004 (post-emergency disarm / circuit breaker)
- Forensic scripts: `../accounts/unni/runs/2026-06-14/` + `fix003_*` probes
