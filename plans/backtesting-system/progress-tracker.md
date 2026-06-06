# Backtesting System — Progress Tracker

## Active Skill: `/new-feature`
## Feature: Comprehensive Backtesting System
## Started: 2026-06-05

---

## Status Overview

| Phase | Status | Notes |
|-------|--------|-------|
| Step 1: Discovery | COMPLETED | 5 discovery agents, full summary written |
| Step 2: Requirements Brainstorm | COMPLETED | 5 rounds, 22 agents, 305 requirements |
| Step 3: Architecture Document | COMPLETED | Created + reviewed (1 round), all Critical/High fixed |
| Step 4: Specification | COMPLETED | spec.md created |
| Step 5: Spec Review | COMPLETED | 7 rounds × 5 agents. All C/H fixed. R7: unanimously CLEAN |
| Step 6: Implementation Plan | COMPLETED | 7 phases, ~40 tasks, all reviews passed |
| Step 7: Plan Review | COMPLETED | 3 rounds + traceability audit + 5-agent codebase consistency audit. ALL critical/high fixed. |
| Step 8: Planning Summary | COMPLETED | |
| Step 9: Create Worktree | COMPLETED | worktree-backtesting-system |
| Step 10: Validate Plan | COMPLETED | Migration 37, all files exist, trading_rules.py done |
| Step 11: Implementation Tracker | COMPLETED | |
| Step 12: Per-Phase Implementation | IN_PROGRESS | P1-P5 ALL GATES PASSED. P4 committed b7cd140. P5 committed 7cbd9e5. **P6 Frontend ALL 4 GATES PASSED** — 12a/12b impl+validate (Tasks 6.1-6.8 + 6.5b, 210 tests), 12c-12f review cycle ran 12 rounds across correctness/a11y/contract/security/testing/plan-compliance/adversarial lenses, **2 consecutive clean rounds (R11+R12) → CONVERGED ship-ready**. tsc+build clean. NEXT: P6 12g commit, then P7 Integration. |
| Step 13: Cross-Phase Validation | COMPLETED | 6 rounds; found+fixed 8 cross-phase bugs (drawdown flat-zero, NUMERIC overflow x2+migration40, cancel race, equity/summary json-safe, empty-signals UX, downsample trough). 2 clean rounds. |
| Step 14: Final Review | IN_PROGRESS | 20-25 rounds (2 clean exit) |
| Step 15: Final Validation | PENDING | |
| Step 16: Traceability | PENDING | |
| Step 17: Readiness Check | PENDING | |
| Step 18: Merge/PR | PENDING | |
| Step 19: Summary | PENDING | |

---

## Activity Log

| Timestamp | Step | Activity | Result |
|-----------|------|----------|--------|
| 2026-06-05 | 1 | Started /new-feature skill | Created tracker |
| 2026-06-05 | 1 | Codebase discovery | COMPLETED — discovery-summary.md written |
| 2026-06-05 | 2 | Requirements brainstorm | COMPLETED — 5 rounds, 305 reqs, near-clean R5 |
| 2026-06-05 | 3 | Architecture document | COMPLETED — reviewed, all critical fixes applied |
| 2026-06-05 | 4 | Specification | IN_PROGRESS |
| 2026-06-06 | 12 | P6 Frontend 12a impl (Tasks 6.1-6.8) | COMPLETED — 16 backtest source files, 12 test files, 102 tests |
| 2026-06-06 | 12 | P6 Frontend 12b validate | COMPLETED — 102 tests pass, tsc clean, build clean |
| 2026-06-06 | 12 | P6 Frontend 12c-12f review (12 rounds) | COMPLETED — 2 consecutive clean (R11+R12). 210 tests, tsc+build clean |
| 2026-06-06 | 12 | P6 Frontend 12g commit | COMPLETED — ee5f62d |
| 2026-06-06 | 12 | P7 Integration 12a/12b (Tasks 7.1-7.4) | COMPLETED — scanner "Backtest These Settings" buttons (ScanDetail + ScheduledScans) + scanSeed util (6 tests); golden-set (6 tests); performance <1.5s (2 tests); nav (done P6); carry-forward integration (3 DB-gated). 216 FE + 208 BE backtest tests, tsc+build clean |
| 2026-06-06 | 12 | P7 Integration 12c-12f review | IN_PROGRESS — R1-R3 fixed entry-fee/price-drift/funding/equity-curve-points. R4 (3 agents): equity-curve fix VERIFIED + adversarial found follow-on HIGH — curve started at first trade's CLOSE not the starting-capital anchor (single-trade run → degenerate drawdown); + MED non-chronological force-close tail. FIXED: seed (start, starting_capital) anchor before scan loop; stable-sort equity curve by ts before metrics; removed dead wallet_delta. Single losing trade now shows max_dd 5.11%. 214 BE backtest tests. NEXT: R5 verify.

---

| 2026-06-06 | 13 | Cross-Phase Validation R1 (5 agents) | Found 3 cross-phase bugs: (1) HIGH engine wrote drawdown_pct=0.0 placeholder → frontend drawdown chart flat-zero (fixed: backfill real drawdown-from-peak); (2) MED-HIGH mfe_pct/pnl_pct NUMERIC(8,4) overflow at high leverage → persist crash (fixed: migration 40 widen to NUMERIC(12,4)); (3) MED cancel→complete race (fixed: eager-cancel NOT EXISTS results guard). Architecture coherent, all suites green (215 BE/199 FE). |

## Key Decisions

- No AI Manager in backtesting (deferred)
- Uses real scan results from DB as signal source
- User provides fresh capital/TP/SL/leverage (no account configs)
- Must be <1% deviation from real trading
- Super fast execution (seconds, not minutes)
- TradingView-quality metrics and charts

---

## Files Created

| File | Step | Purpose |
|------|------|---------|
| plans/backtesting-system/progress-tracker.md | 1 | This file |
| plans/backtesting-system/discovery-summary.md | 1 | Codebase discovery findings |
| specs/backtesting-system-requirements.md | 2 | 305 requirements (all rounds) |
| specs/backtesting-system-architecture.md | 3 | Architecture + review fixes |
| specs/backtesting-system-spec.md | 4-5 | Full specification (reviewed + clean) |
| plans/backtesting-system/implementation-plan.md | 6-7 | Implementation plan (reviewed + clean) |

---

## Phase 5 Carry-Forward (raised during P4 reviews — MUST address when wiring service)

### Phase 6 Task 6.3 Carry-Forward (deferred UX polish — non-blocking)
- Quick/Advanced mode toggle, preset save/load (localStorage import/export JSON), and dirty-form
  navigation guard (useBlocker / beforeunload) from plan Task 6.3 are NOT implemented. All config
  fields ARE reachable via the collapsible Section UI (functional parity), so this is UX polish, not
  a correctness/feature gap. Product reviewer (R5) judged it defer-able. Track as a follow-up; the
  form already accepts a `seed` prop so presets can be layered on later without refactor.
- Equity chart crosshair/zoom (recharts Brush) from Task 6.5 also deferred (nice-to-have); Buy & Hold
  line IS now implemented.

### Phase 7 Integration-Test Carry-Forward (raised during P5 12f testing review)
- The Phase 5 unit suite (~96 tests) mocks `db.pool` and `_wire_transaction` (codebase norm). It does
  NOT exercise real asyncpg SQL/rollback/concurrency. Phase 7 integration should add ~4 Postgres-backed
  tests: (1) persist round-trip read-back, (2) transaction rollback on trade-insert failure leaves no
  orphan results, (3) genuinely concurrent runs respecting the 3-slot cap, (4) the cross-thread
  _on_progress → call_soon_threadsafe DB-write hop. Not a Phase 5 blocker (unit gate uses mocks).

1. **excess_return + Buy & Hold wiring** — `compute_buy_hold_return(btc_klines, capital)` exists and is
   correct, but `compute_all_metrics(trades, equity, config)` takes no `btc_klines`, so it is NOT wired.
   Spec FR-006 "Comparison" row requires Buy & Hold return AND `excess_return` (= net_profit_pct −
   buy_hold.return_pct). Phase 5 service must: fetch BTCUSDT klines for the window, call
   `compute_buy_hold_return`, and add both `buy_hold_return_pct` and `excess_return` to the results
   payload. excess_return has ZERO implementation today — do not silently drop it.

2. **per_trade persistence — avoid JSONB duplication** — `compute_all_metrics` output now includes a
   `per_trade` list (one entry per closed trade) for the cumulative-PnL chart. Its fields are a near-exact
   subset of the `backtest_trades` TABLE columns. Do NOT persist the 50k-entry `per_trade` array into the
   `backtest_results.metrics` JSONB cell (multi-MB, TOASTed, shipped whole on every fetch). Instead:
   persist per-trade rows to `backtest_trades`, and serve the cumulative-PnL series from that table
   (compute `cumulative_pnl` on read, ordered by exit_time). Keep `metrics` JSONB to scalar aggregates.
   Consider capping/downsampling `per_trade` in the API response like the equity curve (LTTB).
