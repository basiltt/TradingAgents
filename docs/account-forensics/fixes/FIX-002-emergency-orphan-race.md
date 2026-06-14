# FIX-002 — Emergency "close all losers" omits a still-open loser (WS buffer race)

**Status:** identified
**Severity:** Critical
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (any AI-managed account with `emergency_close` enabled)

## Symptom
At 02:58:05 the AI manager's deterministic emergency fired for `equity_drop_12.6pct`. The code
is meant to "close ALL losing positions", but the recorded decision closed **only TSTBSC +
FOLKS** and left **ESPORTS** — the single largest loser — open. ESPORTS then rode its short to
the full +12.3% stop-loss (~−$18.6).

## Root cause
`backend/services/ai_manager_task.py` → `_check_emergency_close()` (~line 1555):
```python
if trigger_reason.startswith("equity_drop"):
    for pos in positions:              # positions = self._ws_buffer["positions"]
        if _extract_upnl(pos) < 0:
            close_symbols.append(symbol)
```
The loser set is built from the **WebSocket positions buffer** at the trigger instant. At
02:58:05, TSTBSC and FOLKS were *simultaneously* closing on their own per-trade stop rules (both
`closed_at = 02:58:05`). The WS buffer mid-cascade did **not** contain the ESPORTS frame, so
ESPORTS was never added to `close_symbols`. The code comment at ~line 1609 even acknowledges the
hazard: *"WS events may remove positions from buffer during await."*

The recorded `state_snapshot.symbols = [TSTBSCUSDT, FOLKSUSDT]` confirms ESPORTS was absent.

## Why nothing recovered it
Compounded by FIX-003 (3% cap blocks the standard path) and FIX-004 (post-emergency cooldown +
circuit breaker disarm re-trigger), so once the emergency missed ESPORTS, nothing re-evaluated it.

## Fix approach (proposed)
1. On an equity-drop emergency, **do not trust the WS buffer alone** to enumerate positions.
   Fetch authoritative open positions from the exchange (or union the WS buffer with the DB
   `open` trades for the account) before computing `close_symbols`.
2. Guard against the mid-cascade race: when an equity-drop trigger fires, snapshot the open set
   once from a consistent source, and reconcile that any open loser not in `close_symbols` is
   either intentionally excluded (MR/locked) or gets closed.
3. Persist the emergency `execution_result` (currently NULL on this path) so the outcome is
   auditable — see also the audit gap noted in the report.

## Verification plan
- Repro test: simulate an equity-drop emergency while two positions close on the same tick;
  assert the third (still-open) loser is included in the close set.
- Integration: emergency close set == all open losers from the exchange snapshot, not the WS buffer.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §3 ("Why the EMERGENCY path EXCLUDED ESPORTS")
- Related: FIX-003, FIX-004
