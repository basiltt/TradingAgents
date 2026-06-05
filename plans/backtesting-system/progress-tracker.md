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
| Step 12: Per-Phase Implementation | IN_PROGRESS | P1-P5 ALL GATES PASSED. P4 committed b7cd140. P5 (Backend Service + API) ALL 4 GATES: 12c Phase Review (7r/2clean — async/data/API bugs), 12d Plan-Compliance (4r/2clean — buy&hold+excess_return wired, per_trade stripped from JSONB, coverage guard, warmup endpoint), 12e Production Hardening (5r/2clean APPROVED — OOM budget, UUID validation, error sanitization, observability, atomic completion invariant, persist retry), 12f Testing (4r/2clean mutation-resistant). 96 service tests, 383 backtest tests. NEXT: P5 12g commit, then P6 Frontend. |
| Step 13: Cross-Phase Validation | PENDING | 10-15 rounds |
| Step 14: Final Review | PENDING | 20-25 rounds |
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

---

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
