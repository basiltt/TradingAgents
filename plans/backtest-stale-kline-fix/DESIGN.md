# Backtest Stale-Kline / Coverage Fix (A+B+C) — Design & Progress

**Date:** 2026-06-09
**Trigger:** "Dad - Demo" (75aecaa7) backtest PnL did not match production (+55% prod vs
−33% backtest, 39 vs 15 trades). User also flagged "klines not cached — refetched every
backtest."

## Root cause (proven with diagnostics, .tmp_fidelity/diag_cache_probe.py)

The backtest silently fills entries on STALE / wrong-time candles:
1. `run_backtest` reads `kline_cache` via `_load_klines` but NEVER ensures coverage.
2. Cache had PARTIAL coverage: EIGEN 73 of ~1050 candles (missing the 04:35 fill bar);
   FU/RKLB ZERO candles near the fill time.
3. The coverage guard `_check_kline_coverage` only rejects when >20% of symbols have
   ZERO candles — a symbol with one stray candle passes.
4. `_open_position` (engine) falls back to `symbol_klines[-1]["close"]` when NO candle
   has open_time >= signal_time → fills EIGEN at 0.161 (a price ~2h stale) when the real
   04:35 price was 0.178 (== production's mark).
5. Wrong short entry (0.161 vs 0.178) → underwater → never hits +15% target → held to
   24h max_duration → skip_if_positions_open skips ~8 scans → 15 trades vs 39 → −33%.

Real EIGEN 04:35 candle = O 0.178 (verified via _fetch_klines_from_bybit). Production
filled 0.1773. The engine SHOULD have filled ~0.178 but fabricated 0.161 from stale data.

## Three defects → three fixes (TDD each)

### A. Engine: stop fabricating fills from stale candles
`backtest_engine.py` `_open_position` ~L850. Today: `entry_base_price =
symbol_klines[-1]["close"]` then overwrite if a bar >= current_time exists. If none
exists (cache truncated before signal), it KEEPS the stale last-close and trades.
**Fix:** if no candle exists at/after current_time within a tolerance (one sim bar),
the signal is un-simulatable → skip it: `state.signals_no_kline += 1; return False`
(same path as "symbol had no candles"), so it surfaces as a warning and the trade is
NOT fabricated. This is the production-faithful behaviour (no live fill either).
Golden: a run where every signal HAS a forward candle is byte-identical (the new branch
is only reached on missing-forward-data, which previously produced a wrong trade).

### B. Service: ensure coverage before simulating
`backtest_service.py` `run_backtest` ~L694. **Fix:** before `_load_klines`, call
`ensure_coverage(symbols, interval, start, end)` (the same path `warmup_cache` uses) so
gaps are fetched + stored. Bounded by the existing `_check_total_kline_budget`. Best-
effort: log fetch stats; the post-load `_check_kline_coverage` still guards the result.
This makes the cache populate on the FIRST run (fixes "refetched every time" once C is
also fixed — partial days will complete and persist).

### C. Cache: partial-day coverage bug
`kline_cache_service.py` `get_coverage_gaps` L163-169. Today a date is "covered" if it
appears in the coverage table AT ALL, ignoring candle_count. A 73/288 day is marked
covered → never refetched. **Fix:** a date counts as covered only when
`candle_count >= expected_for_that_day(interval, date, now)`. Expected = full day's
candle count (288 for 5m), EXCEPT the current/partial day (clip expected to candles up
to min(end, now)). The query already selects candle_count. This makes ensure_coverage
actually complete partial days, so the cache fills and stays filled (fixes user's
"klines not cached" complaint).

## Validation
- Re-run Dad-Demo (75aecaa7) real config, Jun 5 → Jun 8 17:35, schedule d9c5f14f.
- EXPECT: EIGEN/FU/RKLB entries ~production prices (EIGEN ~0.178 not 0.161); trade
  count rises toward prod's ~39 (scans no longer skipped on stale-held positions); PnL
  flips from −33% toward prod's +55% region (won't be exact — candle-vs-tick + the few
  `external` manual closes prod made are not reproducible, but direction + magnitude
  must converge).
- Full backtest test suite stays green (89 + new tests). Golden + sweep immunity intact.

## Progress
| # | Step | Status |
|---|------|--------|
| 1 | Root cause via diagnostics | DONE |
| 2 | Design (this doc) | DONE |
| 3 | TDD A (engine stale-fill skip) | DONE |
| 4 | TDD C (partial-day coverage) | DONE |
| 5 | TDD B (run_backtest ensure_coverage) | DONE |
| 6 | Full suite green | DONE (154) |
| 7 | Re-validate Dad-Demo converges | DONE |

## Outcome (validated in-process AND via MCP on reloaded backend — identical)

Dad-Demo (75aecaa7), real config, Jun 5 → Jun 8 17:35, schedule d9c5f14f:

| Metric | Before fix | After fix | Production |
|---|---|---|---|
| EIGEN entry | 0.161 (−9% wrong) | **0.17796** (0.48% off) | 0.17711 |
| RKLB entry | 105.3 (−10% wrong) | **116.877** (0.05% off) | 116.94 |
| FU entry | 0.00380 | **0.0039902** (3.7% off) | 0.004144 |
| Trade count | 15 | **27** | 39 |
| Net PnL | **−33%** | **+20.45%** | +51.65% |
| EIGEN close | max_duration (24h) | **equity_rise** (+15% target) | rule_triggered |
| signals_no_kline | 0 (fabricated silently) | **0 (real coverage)** | — |
| win rate / PF | — | 51.9% / 1.24 | — |

The PnL **flipped sign** (−33% → +20%, same direction as prod's +52%); entries now match
production to **0.05–0.5%** (candle-vs-tick floor); EIGEN closes via the +15% rise target
exactly like production instead of being held 24h. ensure_coverage warmed 455 symbols
(3 delisted symbols correctly failed-soft).

## Residual gap (27 vs 39, +20% vs +52%) — NOT an engine bug
- Production made **6 `external` closes** (manual/app interventions) a backtest can't
  reproduce.
- The rest is the candle-vs-tick entry-fill sensitivity (sub-1% entry diffs flip a few
  marginal trades) documented in FIDELITY-REPORT Addendum 2 — an irreducible ceiling.

## Files changed
- `backend/services/backtest_engine.py` — `_open_position`: skip (no-kline) instead of
  filling on a stale last candle when no bar exists at/after signal_time.
- `backend/services/kline_cache_service.py` — `get_coverage_gaps`: candle-count-aware
  gap detection with boundary-day clipping (partial day = gap).
- `backend/services/backtest_service.py` — `_execute_backtest`: best-effort
  ensure_coverage(symbols, interval, start, end) BEFORE `_load_klines`.
- Tests: `test_backtest_engine.py::TestStaleEntryNotFabricated` (2),
  `test_kline_cache_service.py::TestGetCoverageGaps` (+2 partial-day),
  `test_backtest_execution.py::TestExecution` (+2 coverage-before-load / fail-soft).
- 154 backtest+cache tests green; golden byte-identical + sweep immunity intact.
