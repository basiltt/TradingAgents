# FIX-004 — Post-emergency disarm leaves a large loser unprotected

**Status:** identified
**Severity:** High
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (AI-managed accounts)

## Symptom
After the 02:58:05 emergency partially fired (closing TSTBSC+FOLKS but missing ESPORTS — see
FIX-002), the protection machinery **disarmed itself** while ESPORTS was still open and bleeding,
so nothing re-triggered before ESPORTS hit its stop ~17 minutes later.

## Root cause
Three mechanisms combined, visible in `ai_manager_state` after the event:
1. `emergency_cooldown_until = 02:58:35` — a 30s suppression of equity-drop re-triggers.
2. `emergency_ref_equity` is **cleared** post-close and re-initializes from the *next* WS wallet
   update — which reflects the **lower** post-close equity (~$84). The drawdown reference
   effectively "resets" to the new lower baseline, so the ongoing ESPORTS loss no longer reads as
   a large drop from the (now-lowered) reference.
3. `circuit_breaker_active = true, circuit_breaker_count = 3` — the LLM eval path was tripped.

Net effect: standard path blocked (FIX-003), emergency reference reset, breaker tripped →
**no path re-evaluated the still-open ESPORTS loser.**

`ai_manager_task.py`: `_check_emergency_close()` ref-equity ratchet/reset (~line 1495–1511,
1594–1599) and circuit-breaker gating (~line 649–651).

## Fix approach (proposed)
1. **Don't reset the drawdown reference below a floor while large unrealized losses remain open.**
   When re-initializing `emergency_ref_equity` post-close, account for still-open positions'
   unrealized PnL (e.g. reference = max(new_equity, equity_at_day_start) or include open-loss),
   so an orphaned loser still counts against the drawdown trigger.
2. **Let the circuit breaker half-open immediately for a hard loss.** If any open position
   exceeds a hard per-position loss threshold, bypass the breaker/cooldown for a forced close
   (capital preservation overrides rate-limiting).
3. Pair with FIX-002 so the emergency doesn't orphan a loser in the first place.

## Verification plan
- Unit: after an emergency that leaves an open loser, a subsequent tick still triggers a close
  for that loser (reference did not reset away the drawdown).
- Scenario replay: Unni 02:58–03:15 window results in ESPORTS being closed, not riding to SL.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §3 ("Why it was never retried")
- Related: FIX-002, FIX-003
