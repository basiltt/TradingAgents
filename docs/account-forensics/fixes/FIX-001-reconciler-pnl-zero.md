# FIX-001 — Reconciler `external` close writes `net_pnl=0`, hiding real losses

**Status:** fixed (2026-06-14) — code patched + tested, 2 live rows backfilled
**Severity:** High (data integrity — corrupts all PnL reporting)
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** Unni, Brother (both ESPORTS short). System-wide for reporting.

## Symptom
A position that closed on the exchange (hit its stop-loss) was force-closed in the DB by the
position reconciler with:
```
close_reason = external,  exit_price = 0,  realized_pnl = 0,  net_pnl = 0,  fees = 0
```
The **real** loss (−$19.08 for Unni's ESPORTS) is correctly reflected in account equity, but the
trade ledger showed `$0`. Result: ledger sum (−$1.64) drastically under-counted the real equity
loss (−$21.3). "Brother" hit the identical bug on the same symbol.

## Root cause (proven, not assumed)
The reconciler's close path is correct *when it finds the closed-PnL record* — it reconstructs
`exit_price`/`realized_pnl`/`net_pnl` properly. The bug is that **it could never find the
record**, so it fell through to the zero-fallback on every retry forever.

`_reconcile_trade` built the closed-PnL lookup window as `start_ms = trade.opened_at`,
`end_ms = now()`. But **Bybit timestamps a closed-PnL record's `createdTime` at POSITION-OPEN
time, which can be a few seconds BEFORE our DB's `opened_at`** (clock skew between Bybit's
position-create and our fill-record write). Bybit's `/v5/position/closed-pnl` filters by
`createdTime ∈ [startTime, endTime]`, so a window starting exactly at `opened_at` **excludes the
very record it needs**.

Proven live against prod: Unni's ESPORTS closed-PnL record has
`createdTime = 1781400691946`, which is **7.65 s before** the trade's `opened_at`
(`1781400699596`). Querying with `startTime = opened_at` → **0 records**; widening the window
start by a few minutes → the record appears and matches exactly (`closedPnl = -19.07806468`,
`avgExitPrice = 0.07486`, `side = Buy`). The backfill loop (running every ~70 s) was finding
"1 backfill trade" for Unni and Brother and failing the match **on every single cycle**.

## Impact
- `/profitability-research` and every PnL dashboard **under-counted losses** by whatever was
  lost on positions whose closed-PnL `createdTime` happened to precede `opened_at`.
- Until fixed, account "true PnL" had to be derived from equity (`high_freq_snapshots`).

## Fix (implemented)
`backend/services/position_reconciler.py`:
- Added `_CLOSED_PNL_WINDOW_PAD_MS = 10 * 60 * 1000` and pad the lookup window start backward:
  `start_ms = opened_at_ms − _CLOSED_PNL_WINDOW_PAD_MS`. 10 min comfortably covers the observed
  ~8 s skew without risking a mismatch — a different close of the same `(symbol, side)` is still
  disambiguated by the newest-`updatedTime` pick in `_fetch_closed_pnl_match`.
- This single change fixes BOTH the live stale-close path and the 24 h backfill retry (they share
  `_reconcile_trade`).

Test: `tests/backend/test_position_reconciler_unit.py::test_reconcile_window_includes_record_created_before_opened_at`
(red→green; asserts the padded window finds a record whose `createdTime` predates `opened_at`
and that the trade is reconciled with the real `net_pnl`, not zeroed). Full suite 5/5; adjacent
close-positions suites 60/60.

## Backfill (applied)
`debug_forensics/fix001/backfill_fix001.py --apply` corrected the 2 zeroed live rows from
`closed_pnl_records` (verified the values equal what the fixed reconciler would write — Bybit
reports `totalEntryFee/totalExitFee = null` for these demo records, so `net_pnl = closedPnl`):

| Account | net_pnl | exit_price | close_reason |
|---------|---------|-----------|--------------|
| Unni - Demo | −19.07806468 | 0.07486 | stop_loss |
| Brother - Demo | −18.75644255 | 0.0716 | stop_loss |

Post-backfill: **0** `external`/`exit_price=0` rows remain system-wide; Unni ledger
(−$20.72) now reconciles with the equity change instead of showing −$1.64.

## Verification — done
- ✅ Unit: padded window finds the pre-`opened_at` record; trade reconciled with real PnL.
- ✅ Data: Unni ledger ≈ equity change (gap closed from ~$19 to ~fees noise).
- ✅ Spot-check: Unni ESPORTS row = −19.078 / stop_loss; 0 zeroed rows remain.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §1, §3b
- Forensic scripts: `debug_forensics/fix001/` (probes + backfill)
