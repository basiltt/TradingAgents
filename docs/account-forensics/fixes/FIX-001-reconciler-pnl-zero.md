# FIX-001 — Reconciler `external` close writes `net_pnl=0`, hiding real losses

**Status:** identified
**Severity:** High (data integrity — corrupts all PnL reporting)
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** Unni, Brother (same ESPORTS short); any trade ever closed via the
reconciler `external` path. System-wide for reporting.

## Symptom
A position that closed on the exchange (hit its stop-loss) was force-closed in the DB by the
position reconciler with:
```
close_reason = external,  exit_price = 0,  realized_pnl = 0,  net_pnl = 0,  fees = 0
```
The **real** loss (~$18.6 for Unni's ESPORTS) is correctly reflected in account equity, but the
trade ledger shows `$0`. Result: ledger sum (−$1.64) drastically under-counts the real equity
loss (−$21.3). "Brother" hit the identical bug on the same symbol.

## Root cause
`backend/services/position_reconciler.py` — when the reconciler detects "exchange has no
position but the DB row is still open", it marks the trade closed as stale/`external`, but on
that path it does **not** reconstruct realized PnL from the actual exit fill; it writes zeros.

The 5 other accounts that shorted ESPORTS closed via the per-trade stop rule
(`close_reason=rule_triggered`) and booked their losses correctly (−$2 to −$8). Only the
reconciler-`external` path zeroes PnL.

## Impact
- `/profitability-research` and every PnL dashboard **systematically under-count losses** by
  however much was lost on positions that exited via the `external` path.
- Historical numbers are optimistically biased. Account "true PnL" must currently be derived
  from equity (`high_freq_snapshots`), not the trade ledger.

## Fix approach (proposed — not yet implemented)
1. On an `external`/stale close, reconstruct realized PnL instead of writing 0:
   - Prefer Bybit's **closed-PnL endpoint** (`/v5/position/closed-pnl`) for the symbol/time window.
   - Fallback: derive from `(exit_or_mark − avg_fill) × filled_qty × side_sign − fees` using the
     last known mark/exit price.
2. Populate `exit_price`, `realized_pnl`, `net_pnl`, `fees` on the reconciled row.
3. **Backfill** historical `external`-closed rows with `net_pnl=0` so analytics become correct
   (one-off migration script; safe — read exchange closed-PnL, update DB).

## Verification plan
- Unit: reconciler close path produces non-zero `net_pnl` for a position that moved.
- Data: after backfill, for each account `sum(trades.net_pnl) ≈ equity_change` (gap < ~$1 fees).
- Spot-check: Unni ESPORTS row shows ≈ −$18.6, not $0; account ledger reconciles to ~−$21.

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §1, §3b
