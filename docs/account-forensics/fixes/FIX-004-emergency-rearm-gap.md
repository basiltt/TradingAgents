# FIX-004 — Post-emergency disarm leaves a large loser unprotected

**Status:** fixed (2026-06-14) — ref-equity reseed floored by open losses (+ FIX-003 backstop)
**Severity:** High
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (AI-managed accounts)

## Symptom
After the 02:58:05 emergency partially fired (closing TSTBSC+FOLKS but missing ESPORTS — see
FIX-002), the protection machinery **disarmed itself** while ESPORTS was still open and bleeding,
so nothing re-triggered before ESPORTS hit its stop ~17 minutes later.

## Root cause
Three mechanisms combined, confirmed in `ai_manager_state` after the event:
1. `emergency_cooldown_until = 02:58:35` — a 30 s suppression of equity-drop re-triggers.
2. `emergency_ref_equity` is **cleared** post-close and re-seeds from the *next* equity reading —
   the **lowered** post-close equity (~$84). The ongoing ESPORTS loss is then measured against
   that lowered baseline, so $84→$79 reads as ~6% (< 10%) and never re-triggers.
3. `circuit_breaker_active = true, count = 3` — the LLM eval path was tripped for 1 h.

## What FIX-003 already covers
FIX-003's per-position hard-loss force-close runs inside `_check_emergency_close` — **before**
the circuit breaker (which only gates the LLM `_evaluate` path) and uses an **absolute** loss
ratio (not the drawdown reference). ESPORTS was *not* in `emergency_closed_symbols`, so it was
not cooldown-blocked either. So once deployed, FIX-003 force-closes any loser past the hard cap
(8%) regardless of breaker/cooldown/ref state — the orphaned-loser case is covered.

**Residual gap (this fix):** a loser in the **3–8% band** after an emergency — the equity-drop
trigger desensitized by the ref reset, the LLM path breaker-blocked, and below the hard cap. It
would bleed unprotected until it crossed 8% (then FIX-003 catches it) or recovered.

## Fix (implemented)
`backend/services/ai_manager_task.py` → `_check_emergency_close`, reference (re)seed
(was `_emergency_ref_equity = equity_val`):
```python
open_loss = sum(-_extract_upnl(p) for p in positions if _extract_upnl(p) < 0)
seed = equity_val + open_loss        # floor by still-open unrealized losses
self._ws_buffer["_emergency_ref_equity"] = seed
```
The reference now reflects the high-water the open losers are actually drawing down from, so a
still-open loser keeps counting as a drawdown after the reset. Restores **relative** drawdown
protection in the 3–8% band; FIX-003 remains the **absolute** backstop above it.

Safe by construction: a fresh position with a tiny unrealized loss seeds a reference only a
fraction of a percent above equity (no spurious trigger); the upward ratchet (high-water mark)
is unchanged.

## Verification — done
- ✅ Unit: post-close seed = equity + |open loss| (ESPORTS: 84 + 14 = 98, not 84).
- ✅ Re-trigger: open loser bleeding 84→79 against the floored ref reads ~19% ≥ 10% → fires
  (old: 6% from a reset 84 ref → never fired).
- ✅ No-loss seed unchanged; ratchet-up unaffected. 126 adjacent AI-manager/emergency tests pass.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §3 ("Why it was never retried")
- Related: FIX-002 (emergency race), FIX-003 (hard-loss backstop)
- Forensic scripts: `fix004_probe.py`
