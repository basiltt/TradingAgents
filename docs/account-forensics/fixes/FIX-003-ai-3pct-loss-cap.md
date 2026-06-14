# FIX-003 — `max_single_decision_loss_pct=3%` blocks closing the biggest losers

**Status:** identified
**Severity:** Critical
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (every AI-managed account using this config default)

## Symptom
The AI manager's standard evaluation path **never closed ESPORTS**, even though it was the
account's deepest loser. It happily closed smaller losers (HMSTR, GWEI, NOKIA, B3) but the one
position that most needed closing grew unchecked until it hit its stop.

## Root cause
`backend/services/ai_manager_task.py` (~line 1001), in the standard (non-urgent) decision path:
```python
if not _is_urgent and self._config.max_single_decision_loss_pct:
    loss_pct = abs(upnl) / equity * 100
    if loss_pct > self._config.max_single_decision_loss_pct:   # 3.0
        return   # SKIP — refuse to close, "loss too big for one decision"
```
ESPORTS' unrealized loss was **5%–15% of equity** the whole time. Every standard evaluation saw
`loss_pct > 3%` and `return`ed without closing. The gate — intended to stop the AI from realizing
a large loss in one action — instead **guarantees the largest loser can only ever grow**, because
the standard path becomes structurally incapable of exiting it. Its only possible exit was the
emergency path, which missed it (FIX-002).

## The perverse incentive
This is the core design flaw: *a position already losing >3% is exactly the one that most needs
closing.* Capping the **exit** by loss size is backwards — the cap belongs on **entry sizing**,
not on the decision to cut a loss.

## Fix approach (proposed)
1. **Remove the loss cap from the exit/close decision.** The cap should bound position size at
   entry (risk-per-trade), not block exits.
2. If a "don't realize a huge loss in one click" guard is still desired, route positions
   exceeding the threshold to the **emergency/forced-close path** instead of skipping them — so
   large losers are closed *more* aggressively, not ignored.
3. Add an explicit "stale large-loser" sweep: any position whose unrealized loss exceeds the
   account stop should be force-closed regardless of the standard-path gates.

## Verification plan
- Unit: a position losing 8% of equity in the standard path results in a CLOSE action (or is
  routed to forced close), not a skip.
- Backtest/replay: re-run the Unni 02:xx window; ESPORTS should be closed by the standard or
  forced path well before the +12% stop.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §3 ("Why the standard path NEVER closed ESPORTS")
- Related: FIX-002, FIX-004
