# Parity Baseline — Hydration Note

**Date:** 2026-06-10
**Account:** Dad - Demo (`75aecaa7-0f10-400b-a562-1ddd7ae6cf94`), `ai_manager_enabled=false`
**Window:** 2026-06-04 22:00 UTC → 2026-06-10 06:00 UTC (= 2026-06-05 00:00 .. 2026-06-10 08:00 in prod-local UTC+02)

## Hydration result (local DB)

- **Scans + scan_results:** copied via `copy-prod-scans` skill (`--since 2026-06-04`). 46 scans, 26,661 scan_results. Continuity OK.
- **trades (oracle):** copied via `_copy_oracle.py` (copy-prod-scans skips trades). **52 rows = 51 closed + 1 open** (MEGAUSDT, opened 2026-06-09, excluded from parity).
- **trading_accounts:** Dad-Demo account row copied (trades FK dependency).
- **analysis_runs:** 10,430 rows copied (tiebreaker source for `_load_signals` LEFT JOIN).
- **auto_trade_results:** present on the copied `scans` rows.

## Ground-truth invariants (verified local)

- Closed trades: **51**; distinct symbols: **49** (HNTUSDT×2, MYXUSDT×2).
- First cycle base_capital: **200.43428197**.
- 17 in-window trading cycles (3 trades each) + 1 boundary cycle from the first scan.

## Kline coverage (5m)

- **49/49 traded symbols have 5m candles** in-window. **0 zero-coverage symbols.**
- Density ~1400 candles/symbol (full window ≈1530; minor gaps normal, acceptable).

## Notes

- Timezone correction: the user's "from 5 June" is prod-local (UTC+02). The first
  cycle opens 2026-06-05 01:28 +02 = 2026-06-04 23:28 UTC, so the UTC window starts
  at 2026-06-04 22:00 to capture exactly the 51 closed trades.
- `psql` is not installed locally on this Windows host; all local DB checks use
  asyncpg directly (the app's driver).
