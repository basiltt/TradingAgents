# FIX-002 — Emergency "close all losers" omits a still-open loser (WS buffer race)

**Status:** fixed (2026-06-14) — exchange-snapshot union + execution_result persisted
**Severity:** Critical
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (any AI-managed account with `emergency_close` enabled)

## Symptom
At 02:58:05 the AI manager's deterministic emergency fired for `equity_drop_12.6pct`. It is
meant to "close ALL losing positions", but it closed **only TSTBSC + FOLKS** and left
**ESPORTS** — the single largest loser — open. ESPORTS rode its short to the +12.3% stop (−$19).

## Root cause (proven with ms-precision)
The close set was built from `self._ws_buffer["positions"]`, the **event-sourced, eventually-
consistent** WebSocket position buffer (updated per-symbol as `position_update` events arrive).
At the trigger instant the buffer was momentarily inconsistent with the exchange:

```
02:58:05.800  FOLKS closes  (rule_triggered — its own per-trade SL)
02:58:05.828  TSTBSC closes (rule_triggered — its own per-trade SL)
02:58:05.864  emergency records symbols = [TSTBSC, FOLKS]   ← already-closed pair
              ESPORTS (genuinely open, losing) is ABSENT from the buffer
```
So the emergency "closed" the two positions that had **already closed 36–63 ms earlier** and
**missed the one that was actually open**. `execution_result = NULL` confirms the batch-close was
a no-op (both targets already gone). The code comment at the batch-close even admitted the
hazard: *"WS events may remove positions from buffer during await."*

## Fix (implemented)
`backend/services/ai_manager_task.py` → `_check_emergency_close`, equity-drop branch:
- Enumerate losers from the **authoritative exchange snapshot** (`accounts_service.get_positions`,
  the same source the close service uses) **UNIONed** with the WS-buffer losers. The union
  guarantees we never close FEWER losers than before — only ever catch ones the buffer dropped.
- **Fail-safe:** if the exchange fetch raises, fall back to the WS-buffer losers alone (never
  abort the emergency, never shrink the set). The fetch is on the rare *confirmed*-emergency
  path only, not every tick, and `get_positions` is 15 s-cached so it adds negligible latency.
- MR/locked/excluded still spared (unchanged filter).

Also fixed the **audit gap** (`_execute_emergency_batch_close`): the emergency path called
`insert_decision` but never `update_decision_outcome`, leaving `execution_result` NULL. It now
mirrors the standard path and persists the close outcome (closed count, symbols, realized PnL),
so the forensic trail is complete.

Tests: `tests/backend/test_ai_manager_emergency_position_source.py` (6 cases: closes a loser
missing from the buffer; unions WS+exchange; falls back to WS on fetch error; spares MR/locked;
closes only losers not winners; persists execution_result). 6/6 green; 122 adjacent
AI-manager/emergency tests pass. Replaying the real 02:58 snapshot now closes ESPORTS.

## Why nothing recovered it (then)
Compounded by FIX-003 (3% cap blocked the standard path) and FIX-004 (post-emergency cooldown +
circuit breaker). FIX-003 is now also fixed (hard-loss force-close), so even if a future race
slipped a loser past this, the hard cap would catch it — defense in depth.

## Verification — done
- ✅ Unit: a loser absent from the WS buffer but present on the exchange IS closed.
- ✅ Union: WS-only and exchange-only losers both closed; fetch-error falls back to WS.
- ✅ Audit: `update_decision_outcome` called with the real closed count/symbols/pnl.
- ✅ Real-snapshot replay: 02:58 emergency now closes ESPORTS (was missed).

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §3 ("Why the EMERGENCY path EXCLUDED ESPORTS")
- Related: FIX-003 (loss-cap dead-zone), FIX-004 (post-emergency disarm)
- Forensic scripts: `fix002_probe.py`
