# Profitability Research History

This document tracks all profitability research sessions, findings, recommendations, and their outcomes over time. Each research run appends to this file so future analyses can compare trends.

---

## 2026-06-04 — Initial Baseline Research

**Timestamp:** 2026-06-04 ~10:00 UTC  
**Total System PnL:** $1,370.92 across 4,858 closed trades  
**System Win Rate:** 50.3%  
**Avg PnL/Trade:** $0.33  
**Active Period:** ~2 weeks (May 20 – Jun 4, 2026)  
**Accounts:** 21 demo accounts, $100 starting capital each

### Configuration at Time of Research
- Scan interval: Every 3 hours (180 min)
- Coins scanned: ~570 per run
- Min score: 6
- Leverage: 5x–20x depending on account
- TP: 150% of margin (7.5% at 20x)
- SL: 100% of margin (5% at 20x)
- Drawdown limit: 10–12%
- Profit goal: 12–14%
- AI Manager: Enabled on 10 accounts

### Key Findings
1. **Score 7-8 signals dramatically outperform score 6** — $0.86 avg vs $0.32, 52.3% vs 45.7% win rate
2. **Scan duration (57-149 min) causes signal staleness** — early-analyzed coins are stale by execution
3. **Batch wipeouts from EQUITY_DROP_PCT rule** — one bad position closes all 5
4. **AI Manager execution pipeline is broken** — all 181 decisions have null execution_result
5. **5 toxic symbols cost -$418** (BIGTIMEUSDT, PLAYSOUTUSDT, SOXLUSDT, SPXUSDT, POWERUSDT)
6. **93% short bias** — system only works in bearish/ranging markets
7. **10x leverage has best risk-adjusted returns** — 52.8% win rate, $0.66 avg
8. **Manual close_all (profit lock) has best avg PnL** — $1.04 per trade

### Recommendations Made
| # | Recommendation | Priority | Status |
|---|---------------|----------|--------|
| 1 | Post-scan signal validation (price drift check) | HIGH | PENDING |
| 2 | Raise min_score from 6 to 7 | HIGH | PENDING |
| 3 | Per-position SL instead of batch EQUITY_DROP | HIGH | PENDING |
| 4 | Fix AI Manager execution pipeline | HIGH | PENDING |
| 5 | Symbol blacklist for toxic symbols | MEDIUM | PENDING |
| 6 | Reduce max_trades from 5 to 3 | MEDIUM | PENDING |
| 7 | Time-based signal weighting | MEDIUM | PENDING |
| 8 | Trailing stop after +2% profit | MEDIUM | PENDING |
| 9 | Lower EQUITY_RISE_PCT from 14% to 8% | LOW-MED | PENDING |
| 10 | AI Manager prevent-new-trades capability | LOW-MED | PENDING |

### Account Standings (sorted by PnL)
| Account | PnL | Trades | Win Rate |
|---------|-----|--------|----------|
| Autotrader | +$176.57 | 192 | 50.5% |
| Appu | +$172.20 | 85 | 68.2% |
| Jeffin | +$166.63 | 263 | 49.8% |
| Joyel | +$157.83 | 235 | 52.3% |
| Preethy | +$111.25 | 254 | 52.8% |
| Unni | +$92.47 | 90 | 52.2% |
| Brother | -$6.94 | 400 | 41.3% |
| Jerin | -$12.00 | 260 | 39.6% |
| Princy | -$19.44 | 257 | 42.8% |

### Notes
- Unni account grew from $93 to $219 (+136%) in 5 days
- Preethy peaked at $248 but AI Manager couldn't properly lock profits
- Appu has best PnL/trade ratio ($2.03) with fewest trades — evidence that quality > quantity
- 12 liquidations occurred ($129.68 lost) — these should be zero with proper SL

---

## 2026-06-04 — Implementation Session (Post-Research Fixes)

**Timestamp:** 2026-06-04 ~11:00–23:00 UTC  
**Type:** Code implementation (no new data analysis)  
**Trigger:** Implementing all recommendations from the 2026-06-04 initial baseline research

### Root Cause Fix: 93% Sell Signal Bias

The most critical discovery: the **Crypto Portfolio Manager** (`tradingagents/agents/crypto_analysts.py`) had NO rating scale definition in its prompt. The LLM filled the `PortfolioDecision.rating` field using training priors where "Sell" meant "avoid/exit" rather than "go short." This caused 93% of all PM decisions to output "Sell" regardless of the underlying analysis.

**Fix applied:**
- Added explicit 5-tier rating scale to the crypto PM prompt (Buy/Overweight/Hold/Underweight/Sell) with clear directional semantics for futures trading
- Clarified that "Sell = strong conviction to go SHORT" and "Buy = strong conviction to go LONG"
- Fixed `_rating_to_direction()` mapping: Underweight now correctly maps to "sell" (was mapping to "hold")

**Files changed:** `tradingagents/agents/crypto_analysts.py`, `backend/services/scanner_service.py`

### Code Implementations from Report Recommendations

| # | Recommendation | Implementation | Files |
|---|---------------|---------------|-------|
| 1 | Post-scan signal validation | `max_price_drift_pct` config + drift check in `_try_trade` comparing `analysis_price` (from trader's entry_price) vs current mark price. Skips trade if price already moved >X% in signal direction. | `auto_trade_service.py`, `scanner_service.py`, `accounts_service.py`, `schemas/__init__.py` |
| 4 | Fix AI Manager execution pipeline | (a) ADJUST_TP_SL decisions now record immediate `{"status": "trailing_started"}` outcome. (b) Added `dry_run` gate before CLOSE execution — was missing, meaning dry_run=True still executed real closes. (c) Fixed test mocks that were masking the real test failures. | `ai_manager_task.py`, `test_ai_manager_task.py`, `test_ai_manager_sweep_defense.py` |
| 5 | Adaptive blacklist | `adaptive_blacklist_enabled` config + `_compute_adaptive_blacklist()` queries `signal_performance` table for symbols with <30% win rate over configurable lookback. Pre-injected into executor configs at scan start. | `scanner_service.py`, `auto_trade_service.py`, `schemas/__init__.py` |
| 7 | Time-based signal weighting | `execute_batch` sort key changed to `(abs(score), completed_at)` descending — at equal score, fresher signals are prioritized over staler ones. | `auto_trade_service.py` |
| New | Sector concentration limit | `max_same_sector` config limits how many positions can be in the same crypto sector (l1, l2, defi, meme, ai, gaming, infra, exchange). | `auto_trade_service.py`, `sector_map.py` (new), `schemas/__init__.py` |
| New | Dynamic sector classification | `SectorService` class: CoinGecko categories + LLM fallback + PostgreSQL DB cache (7-day TTL). Hot path is sync dict lookup (zero I/O). Symbols classified at scan start, capped at 50/batch to avoid rate limit delays. | `sector_service.py` (new), `sector_map.py` (new), `coingecko_data.py`, `scanner_service.py`, `main.py`, `persistence.py`, `async_persistence.py` |
| New | Orphan position alerting | Position reconciler now broadcasts WebSocket alert when exchange has positions with no matching DB trade record. | `position_reconciler.py` |

### Pre-Existing Features Verified Working (No Code Change Needed)

| Feature | Location | Notes |
|---------|----------|-------|
| Static blacklist/whitelist | `auto_trade_service.py:925-931` | `symbol_blacklist` and `symbol_whitelist` in AutoTradeConfig |
| Per-position trailing stop | close_rule_evaluator `_evaluate_trailing_profit` | `trailing_profit_pct` config creates `TRAILING_PROFIT` rule |
| AI pause-new-trades | `ai_manager_task.py:838-855` | `PAUSE_TRADING` action creates rule checked by auto-trade executor |
| max_same_direction limit | `auto_trade_service.py:952-960` | Prevents all positions being same direction |
| min_profit_to_close_ratio | `ai_manager_task.py:914-936` | Default 0.3 = AI won't close if profit < 30% of TP target |
| Per-trade TP/SL at order time | `accounts_service.py:286-301` | SL/TP prices set on Bybit at `place_market_order` |

### Items Requiring Config Changes Only (No Code Needed)

| Change | Config Field | Current | Recommended |
|--------|-------------|---------|-------------|
| Raise minimum score | `min_score` | 6 | 7 |
| Reduce positions per cycle | `max_trades` | 5 | 3 |
| Increase capital per trade | `capital_pct` | 9-15% | 18-20% |
| Relax drawdown threshold | `max_drawdown_pct` | 10-12% | 18-20% |
| Lower profit lock threshold | `target_goal_value` | 12-14% | 8% |

### New Config Fields Added

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_price_drift_pct` | float (0-50) | None (disabled) | Skip trade if price moved >X% in signal direction since analysis |
| `max_same_sector` | int (1-10) | None (disabled) | Max positions in same crypto sector |
| `adaptive_blacklist_enabled` | bool | false | Enable automatic symbol exclusion based on win rate |
| `adaptive_blacklist_min_trades` | int (2-50) | 5 | Min trades before symbol can be blacklisted |
| `adaptive_blacklist_max_win_rate` | float (0-100) | 30.0 | Win rate threshold below which symbol is excluded |
| `adaptive_blacklist_lookback_hours` | int (1-720) | 48 | How far back to look at trade history |

### Database Migrations Added

| Version | Table | Purpose |
|---------|-------|---------|
| v34 (sync) / v36 (async) | `symbol_sectors` | Caches sector classifications (symbol PK, sector, source, coingecko_categories, classified_at) |

### Tests Added/Fixed

| File | Tests | Notes |
|------|-------|-------|
| `tests/backend/test_sector_service.py` | 24 new tests | CG mapping, LLM fallback, cache behavior, ensure_classified |
| `tests/backend/test_ai_manager_task.py` | 49 tests (3 fixed) | Added `_llm_logger` AsyncMock, `_model_name` to fixture |
| `tests/backend/test_ai_manager_sweep_defense.py` | 4 tests (1 fixed) | Added `_ws_buffer` with positions to fixture |
| `tests/test_scanner_signal_structured.py` | Updated | `test_underweight_uses_sell` — asserts "sell" not "hold" |

### Safety Bugs Fixed

1. **`dry_run` mode was NOT preventing CLOSE actions** — only ADJUST_TP_SL had the dry_run gate. Fixed: added dry_run check before close execution path.
2. **Sweep defense test passing falsely** — `_ws_buffer` mock was wrong, causing `_handle_sweep_resolved` to silently skip SL restoration.
3. **Sector map had fictitious tokens** — JABORAUSDT, GABORAUSDT, ABORAUSDT were non-existent tokens in the static dict. Removed.
4. **DOGEUSDT duplicated** in sector map. IMXUSDT had conflicting sector assignments. Cleaned.

### Final Test Results

- **Total:** 423 passed, 0 failed (all previously failing tests now pass)
- **Previously failing:** `test_evaluate_close_executes`, `test_execution_exception_records_dead_letter`, `test_transition_to_resolved` — all now pass

### Recommendation Status Update

| # | Recommendation | Previous Status | New Status |
|---|---------------|----------------|------------|
| 1 | Post-scan signal validation (price drift) | PENDING | **IMPLEMENTED** (code) |
| 2 | Raise min_score from 6 to 7 | PENDING | READY (config change only) |
| 3 | Per-position SL / relax batch close | PENDING | PARTIALLY READY (trailing exists; config change for drawdown threshold) |
| 4 | Fix AI Manager execution pipeline | PENDING | **IMPLEMENTED** (code) |
| 5 | Symbol blacklist (adaptive) | PENDING | **IMPLEMENTED** (code) |
| 6 | Reduce max_trades from 5 to 3 | PENDING | READY (config change only) |
| 7 | Time-based signal weighting | PENDING | **IMPLEMENTED** (code) |
| 8 | Trailing stop after +2% profit | PENDING | ALREADY EXISTS (feature pre-dates report) |
| 9 | Lower EQUITY_RISE_PCT from 14% to 8% | PENDING | READY (config change only) |
| 10 | AI Manager prevent-new-trades | PENDING | ALREADY EXISTS (PAUSE_TRADING action) |
| New | Sector concentration limit | — | **IMPLEMENTED** (code) |
| New | Dynamic sector classification | — | **IMPLEMENTED** (code) |
| New | Orphan position alerting | — | **IMPLEMENTED** (code) |

---

## 2026-06-06 — Three-Feature Integration (Backtesting + Debug Tracing + Prompt Caching)

**Timestamp:** 2026-06-06 ~22:00 UTC
**Type:** Multi-feature merge to `main` (3 independent feature branches merged by a senior-lead merge process)
**Trigger:** Three critical features were developed in parallel in separate git worktrees and needed to land on `main` together — cleanly, with correct database-migration ordering, and with every feature verified working end-to-end.

### Why this matters for profitability research

These three features are **research-enablement infrastructure**, not new trading logic. Up to now, profitability analysis (see the 2026-06-04 entries) has been *retrospective* — we could only learn from trades the live system had already taken with real (demo) capital. That is slow and expensive: validating a single config idea (e.g. "raise min_score to 7") meant waiting days for the live system to accumulate enough trades. The three features close that loop:

- **Backtesting** lets us test config changes against *historical* scan data in seconds instead of waiting days for live trades.
- **Debug tracing** gives us per-decision forensics, so when a backtest (or live run) does something surprising we can see exactly *why* each symbol was traded, skipped, or closed.
- **Prompt caching** cuts the LLM cost of running scans/analyses, which makes large research sweeps (and re-scanning for backtests) economically viable.

Together they turn profitability research from "wait and observe" into "hypothesize, simulate, inspect, repeat."

---

### Feature 1 — Backtesting System

**Problem it solves:**
Every recommendation in the 2026-06-04 research (raise min_score, reduce max_trades, change drawdown thresholds, sector limits, etc.) could only be validated by deploying it live and waiting for enough closed trades to reach significance. There was **no way to ask "what would this config have done?"** against history. That made the recommendation table (`READY (config change only)`) a list of *untested guesses*.

**What was built:**
A full simulation engine that replays the **real auto-trade cycle** (scan results → signal filtering → trade placement → close-rule evaluation → position closure) against historical scan data already stored in the DB. It reuses the *same* parameters as the Scheduled Market Scanner (all `AutoTradeConfig` fields), enforces the same cycle rules (no new trades while a previous cycle is running), and evaluates all the same close rules (`EQUITY_RISE_PCT`, `EQUITY_DROP_PCT`, `BREAKEVEN_TIMEOUT`, `MAX_DURATION`, `TRAILING_PROFIT`). It runs in seconds using cached kline data and produces TradingView-quality output: equity curve, drawdown chart, and the full standard metric set (Sharpe, Sortino, profit factor, max drawdown, win rate, expectancy, etc.).

**Key components:**
| Component | File | Role |
|-----------|------|------|
| Simulation engine | `backend/services/backtest_engine.py` | Candle-by-candle replay; 17-step filter chain; wick-based TP/SL; unified close-rule timeline; look-ahead-bias guards |
| Trading rules | `backend/services/trading_rules.py` | Pure functions for liquidation, fees, funding, sizing — shared parity with live trading |
| Metrics | `backend/services/backtest_metrics.py` | TradingView-parity metric computation from the trade ledger + equity curve |
| Kline cache | `backend/services/kline_cache_service.py` | Local OHLCV cache (Bybit fetcher + gap detection + instrument-info cache) so re-runs are instant |
| Service/orchestration | `backend/services/backtest_service.py` | Run lifecycle, signal loading from scan history, stale-run recovery on restart, result persistence |
| API | `backend/routers/backtest.py` | `POST/GET/DELETE /api/v1/backtest`, `/backtest/{id}/trades`, `/backtest/compare`, `/backtest/{id}/cancel`, `/backtest-cache/status`, `/backtest-cache/warmup` |
| Frontend | `frontend/src/components/backtest/*` | Results dashboard: equity curve, drawdown, metrics grid, trade list, multi-run comparison basket |

**Important:** the backtest uses real scan results from the DB as its signal source (it does **not** re-analyze with the LLM), and the user supplies fresh capital / TP / SL / leverage rather than reusing account configs. The **AI Manager** is intentionally excluded from the backtest (deferred). Target fidelity: <1% deviation from real trading results.

---

### Feature 2 — Auto-Trade Debug Tracing

**Problem it solves:**
The 2026-06-04 research repeatedly hit a wall: when the system did something wrong (93% sell bias, batch wipeouts, the AI Manager's 181 null execution results), we could only infer *what* happened from the trades table — we could not see *why* each decision was made. There was no forensic record of "for scan X, account Y, symbol Z: the signal scored 7, passed the drift check, failed the sector-concentration limit, and was therefore skipped." Diagnosing a profitability regression meant guessing from outcomes.

**What was built:**
Always-on, performance-safe forensic tracing for the entire `AutoTradeExecutor` path. Every scheduled or manual auto-trade run now records a reconstructable decision tree: the run lifecycle, per-account traces (capital, equity, gate that stopped execution, recheck-rescue status), per-symbol decisions (scan score/confidence/direction, the decision + reason code, resulting order id), lifecycle events, and exchange snapshots at each gate. This is the missing instrument that lets future research answer "why" instead of just "what."

**Design constraints (money-critical hot path):**
- **Fail-open:** a recorder failure can never break a live trade. Emit is wrapped so tracing exceptions are swallowed.
- **Non-blocking:** synchronous emit into a bounded in-memory buffer with drop-on-pressure; a background drainer does the actual DB writes via bulk `COPY`.
- **Kill-switch:** runtime-toggleable (`debug_config.tracing_enabled`) so it can be turned off instantly with near-zero overhead.
- **Retention:** 60-day default retention with a background cleanup loop; secrets are stripped from `config_snapshot` at the persistence boundary.

**Key components:**
| Component | File | Role |
|-----------|------|------|
| Recorder | `backend/services/debug_trace_recorder.py` | Fail-open emit, bounded buffer, drainer, retention loop, run lifecycle/context |
| Repository | `backend/services/debug_trace_repository.py` | Bulk `COPY` insert, lifecycle SQL, aggregate-tree + sub-route read queries with narrative |
| API | `backend/routers/debug.py` | `GET /api/v1/debug/scan/{scan_id}`, `/scan/{scan_id}/account/{account_id}`, `/runs`, `/account/{account_id}/timeline`, `/symbol/{symbol}`, `/config` |
| Wiring | `backend/main.py`, `backend/services/scanner_service.py`, `backend/services/auto_trade_service.py` | Recorder instantiated in lifespan; threaded into the executor; per-symbol decisions + account summaries emitted; debug run closed in `finally` |

**Bonus safety fix carried on this branch:** `close_positions_service.py` — an explicit *empty* symbols list must close **nothing**, not fall through to close-all (`if symbols:` → `if symbols is not None:`). An empty scoping list closing every position would be catastrophic; a regression test now guards it.

---

### Feature 3 — Anthropic Prompt Caching

**Problem it solves:**
Each scan analyzes ~570 coins, and every analyst (market, fundamentals, crypto-technical) sends a large, mostly-static system prompt to the LLM on every single call. With Anthropic models, that static prefix was billed at full input-token price every time. The cost of running scans — and therefore the cost of *research* (large sweeps, re-scans for backtests, parameter exploration) — was dominated by re-sending identical prompt prefixes. Expensive research is research you don't do.

**What was built:**
Prompt-prefix caching for `anthropic/*` models. The static portion of each analyst prompt is split into a cacheable prefix and injected with `cache_control` at the litellm chokepoint, so Anthropic bills the repeated prefix at the (much cheaper) cache-read rate. The feature is **off by default** and controllable three ways: an environment variable (`TRADINGAGENTS_PROMPT_CACHE_ENABLED`), an admin/global resolved-config value, and a per-run request flag (`prompt_cache_enabled`) exposed in the Analysis and Scanner UI forms. Normalized cache/token metrics (cache-creation vs cache-read vs uncached tokens) are logged from the invoke chokepoint so the savings are measurable.

**Key components:**
| Component | File | Role |
|-----------|------|------|
| Prompt-split helper | `tradingagents/agents/utils/prompt_cache.py` | `split_cacheable_prompt` (Pattern A) + message-shaping helper |
| Cacheable analysts | `tradingagents/agents/analysts/market_analyst.py`, `analysts/fundamentals_analyst.py`, `agents/crypto_analysts.py` | Static prompt split into cacheable prefix |
| litellm injection | `tradingagents/llm_clients/litellm_client.py`, `llm_clients/model_families.py` | `cache_control` injected on the system message for `anthropic/*`; cache metrics logged |
| Config plumbing | `tradingagents/default_config.py`, `graph/trading_graph.py`, `backend/services/scanner_service.py`, `analysis_service.py`, `schemas/__init__.py` | `prompt_cache_enabled` threaded request → graph config (relay preserves the resolved/admin value when the request omits it) |
| Frontend toggle | `frontend/src/components/analysis/ConfigForm.tsx`, `scanner/ScannerPage.tsx`, `scanner/ScheduledScansPage.tsx`, `api/client.ts` | Per-run caching toggle in the 3 LLM-settings forms |

**Operational caveats (recorded so future research doesn't trip on them):**
- Caching is a **cost** optimization, not a behavior change — a behavioral-parity eval harness (`scripts/cache_parity_eval.py`) was built to confirm decisions are unchanged with caching on vs off.
- OpenAI/Gemini paths are unaffected (no-op); only `anthropic/*` benefits.
- `pyproject.toml` dependency upper bounds were tightened for the tested caching path (`litellm>=1.83.7,<2`, `langchain-community>=0.4.1,<0.5`, `langchain-anthropic>=1.4.2,<2`, `langchain-core<2`). **Follow-up:** `uv.lock` was not regenerated (the branch documented it as un-installable in that environment) — regenerate before a clean-room deploy.

---

### Merge mechanics — how the three branches were integrated safely

All three branches had **different merge-bases** but all were ancestors of `main`. Merge order chosen: **backtesting → debug-tracing → prompt-caching**.

**Critical issue #1 — database migration version collision (v38).**
Both the backtesting and debug-tracing branches independently branched off `main` and each appended a migration numbered **v38**. The migration applier (`_apply_migrations`) only runs versions `> current` and stores a single max version, so two `(38, …)` entries would mean **one feature's tables silently never get created** — and git auto-merges adjacent list entries with *no conflict marker*, so this would have shipped invisibly. Resolution:
- Backtesting keeps **v38–v41** (kline cache + backtest tables, `analysis_price` column, widened numeric columns, trade indexes).
- Debug-tracing's v38 was **renumbered to v42** (constant renamed `_SCHEMA_DEBUG_V38` → `_SCHEMA_DEBUG_V42`).
- Migration version integers are positional-only (code references table/column *names*, never the number), so renumbering is safe. Final list is contiguous **1..42, no duplicates**.

**Critical issue #2 — the live dev DB was already at schema v41.**
The backtesting worktree had been run against the shared local Postgres, so it was already migrated to v41 with backtest tables present (but no debug tables). This *dictated* the renumber direction: if debug had kept v38, `38 ≤ 41` would skip it forever and debug tables would never be created on that DB. Renumbering debug to v42 means it layers cleanly on top. Confirmed post-merge: live DB advanced to **v42**, all 6 `debug_*` tables created, backtest v38–v41 tables intact.

**Conflicts resolved:**
| File | Branches | Resolution |
|------|----------|------------|
| `backend/async_persistence.py` | backtest ∩ debug | Kept both migration helpers; renumbered debug v38→v42 |
| `specs/…`, `plans/backtesting-system/…` (4 docs) | backtest ∩ main | Took the backtest branch's final, more complete versions |
| `backend/main.py` | backtest ∩ debug | Auto-merged clean — both feature blocks coexist (service wiring + router includes) |
| `backend/services/scanner_service.py` | all three | Auto-merged clean — `analysis_price` (×5), `_debug_recorder` (×13), `prompt_cache_enabled` (×1) coexist |
| `frontend/src/api/client.ts`, `scanner/ScheduledScansPage.tsx` | backtest ∩ caching | Auto-merged clean — non-colliding regions |

### Database migrations added (this session)

| Version | Owner | Tables / Change |
|---------|-------|-----------------|
| v38 | Backtesting | `kline_cache` (+ monthly partitions), `kline_cache_coverage`, `backtest_runs`, `backtest_results`, `backtest_trades` |
| v39 | Backtesting | `scan_results.analysis_price` column (entry-price anchor for drift + backtest fill) |
| v40 | Backtesting | Widen `backtest_trades` pnl_pct/mfe_pct/mae_pct → NUMERIC(12,4), qty → NUMERIC(30,8) (overflow guards) |
| v41 | Backtesting | Composite indexes on `backtest_trades(run_id, entry_time)` and `(run_id, pnl)` |
| **v42** | Debug Tracing | `debug_runs`, `debug_account_traces`, `debug_lifecycle_events`, `debug_symbol_decisions`, `debug_exchange_snapshots`, `debug_config` (**renumbered from the branch's v38**) |

### Verification performed (money-critical — no room for error)

- **Backend feature suites:** 557 tests pass across all three features (backtest engine/metrics/service/router/rules/close-rules/filter-chain, kline cache, debug recorder/repository/router/e2e/performance, caching helper/injection/metrics/analyst-prompts).
- **Full app lifespan:** the complete FastAPI app starts (`app_ready: all services initialised`) and shuts down cleanly with all three features' services wired together; `GET /api/v1/backtest` and `/api/v1/debug/runs` both return 200; 146 routes registered.
- **Live DB migration:** applied v42 to the real dev DB → `schema_version=42`, all feature tables present.
- **Frontend:** `tsc --noEmit` clean; production build (`tsc -b && vite build`) succeeds; **644 frontend tests pass** (59 files).
- **Build-blocking bug fixed:** the backtesting branch shipped a Zod **v3** API call (`invalid_type_error`) while the project ships Zod **v4** — `tsc --noEmit` and vitest both tolerated it, but the production build rejected it. Fixed to the v4 `error` field (1 line, behavior-preserving).

### Pre-existing issues found (NOT caused by this merge — flagged for follow-up)

1. **`tests/backend/test_close_positions_service_unit.py` — 9 failures.** Stale mocks return `{"orderId": …}` without `cumExecQty`, so they fail the fill-confirmation safety check in `_close_single_position`. **Proven pre-existing** by running them against the pre-merge `main` snapshot (identical 9 failures). Money-critical test-quality gap — the mocks should be updated to include `cumExecQty`.
2. **`tests/backend/test_analysis_service.py` — 21 failures, environmental.** `validate_backend_url` blocks `localhost` because this host resolves it to IPv6 `::1`; this hits **every** `_build_config` test (caching and non-caching alike). `validators.py` is untouched by any merged branch. The caching config logic itself was proven correct by exercising `_build_config` directly with the URL validator patched.

### Recommendation status update (from the 2026-06-04 research)

| # | Recommendation | Previous Status | New Status |
|---|---------------|----------------|------------|
| 2 | Raise min_score from 6 to 7 | READY (config) | **NOW TESTABLE** via backtesting before committing live |
| 3 | Per-position SL / relax batch close | PARTIALLY READY | **NOW TESTABLE** — backtest evaluates all close rules incl. drawdown |
| 6 | Reduce max_trades from 5 to 3 | READY (config) | **NOW TESTABLE** via backtesting |
| 9 | Lower EQUITY_RISE_PCT 14%→8% | READY (config) | **NOW TESTABLE** via backtesting |
| New | Backtesting system | — | **IMPLEMENTED** (code) |
| New | Auto-trade debug tracing | — | **IMPLEMENTED** (code) |
| New | Anthropic prompt caching | — | **IMPLEMENTED** (code, default OFF) |

### Next steps for profitability research

1. Use the backtesting system to validate the still-`READY (config change only)` recommendations (#2, #3, #6, #9) against historical scan data **before** changing live config.
2. Enable debug tracing on a live scan and use the forensic tree to confirm the 2026-06-04 fixes (sell-bias, drift check, sector limit) behave as intended per-symbol.
3. Run the cache-parity eval, then enable prompt caching to lower the cost of large research sweeps.
4. Resolve the two pre-existing test issues above before the next production deploy.

---

## 2026-06-06 — Post-Merge Senior Review & Hardening

**Timestamp:** 2026-06-06 ~22:45 UTC
**Type:** Code review + targeted fixes (no new data analysis)
**Trigger:** Money-critical review of the just-merged 3-feature integration — hunt for gaps, breakage, inconsistencies, and internal conflicts before relying on the features.

### Method

Dispatched adversarial reviewers across each feature (backtest correctness, debug reliability, caching parity) plus a cross-cutting integration review. **Every flagged "CRITICAL/HIGH" was independently verified before any code change** — most turned out to be false positives or pre-existing, documented design decisions. Three were confirmed real and fixed.

### Problem #1 (HIGH, fixed) — Backtest price-drift filter silently disabled

**The problem:** The backtesting feature added `scan_results.analysis_price` (migration v39), the scanner extracts it into the result dict, and the backtest signal loader `SELECT`s it — but the **shared, auto-merged** `insert_scan_result()` in `async_persistence.py` was never updated to actually WRITE the column. So `analysis_price` was always NULL in the DB. This is the classic auto-merge hazard: the column + the read path + the extraction all landed, but the write path in a file touched by another feature did not.

**Why it matters for profitability research:** The backtest's `max_price_drift_pct` filter (which skips a signal whose price has already moved too far since analysis — one of the 2026-06-04 fixes) reads `analysis_price`. With it always NULL, the filter **silently no-ops in backtests**, so a backtest would admit trades that live trading rejects → results diverge from reality, defeating the <1% fidelity goal. Any profitability conclusion drawn from a drift-filtered config would have been wrong.

**The fix:** Persist `analysis_price` in the INSERT + `ON CONFLICT` (with `COALESCE` so a price-less re-insert can't wipe an existing value) + defensive coercion (only a positive finite number is stored, else NULL). Verified round-tripping through the live DB. Note: live trading was unaffected — it reads `analysis_price` from the in-memory result dict, not the DB; only backtests read it from the DB.

### Problem #2 (HIGH, fixed) — Optional forensics could abort trading startup

**The problem:** `DebugTraceRecorder` init + `start()` ran **unguarded** in the app lifespan, before the trading services. The debug router (returns 503 when the recorder is absent) and the scanner (`if recorder is not None`) are both explicitly designed to tolerate a *missing* recorder — but startup made it mandatory. A throw during debug init would propagate out of lifespan and **halt the entire trading app to protect a forensics feature.**

**The fix:** Wrap construction + `start()` in try/except; on failure log and degrade to `None` (every consumer already handles None), mirroring the sibling `backtest_service.recover_stale_runs()` pattern.

### Problem #3 (reliability, fixed) — Debug `open_run` could stall trade placement

**The problem:** `open_run` (which writes a debug run row) is awaited on the scan/trade-leading path. Its `create_run` DB call had no timeout, so a saturated shared connection pool could block trade placement while waiting to acquire a connection — violating "tracing must never slow a live trade."

**The fix:** `asyncio.wait_for(create_run, timeout=5s)`; on timeout, fail open (run untraced, trading proceeds) rather than block.

### Adversarially REFUTED (NOT changed — changing them would have introduced bugs)

- **"Backtest equity-rule basis mismatch."** A reviewer claimed the EQUITY_DROP reference (which subtracts locked margin) is inconsistent with the measured equity (which doesn't). Verified against production: production's reference IS `totalAvailableBalance` (subtracts margin) while the measured value IS `totalEquity` (doesn't) — the backtest faithfully mirrors this asymmetry, and an existing regression test (`test_equity_drop_reference_excludes_carried_locked_margin`) locks it in. The proposed "fix" would have **re-introduced a prior real bug (R6/R9).**
- **"Caching makes 4 crypto analysts more expensive."** Refuted against Anthropic's billing docs: a sub-min-length prefix is a silent no-op (no write premium), and these are multi-call tool-using agents that read the cache back **within** a scan → net cheaper, not more expensive. Real (minor) issue is only a missed cross-scan optimization, not a cost regression.
- **Realized-only equity curve / drawdown granularity.** Already disclosed as "known approximation #14" in the backtest spec — a deliberate, documented design choice, not a defect.

### Verification

Added `tests/backend/test_merge_hardening.py` (6 regression tests, all green). Async-path test sweep across all touched areas: **115+ pass**. Full app lifespan starts/stops clean with all 3 features; `analysis_price` round-trips through the live DB. The pre-existing `close_positions` mock failures and sync-persistence(v35)-vs-live-DB(v42) version-guard errors are unrelated and were proven pre-existing (documented in the prior entry).

### Takeaway for future merges

The one real bug that would have corrupted profitability research (`analysis_price` not persisted) was a **silent auto-merge gap in a shared file** — exactly the failure mode to watch when several features edit the same module. Auto-merge being "textually clean" does not mean it is "semantically complete." Always trace each new column/field end-to-end: migration → write → read.

---

## 2026-06-07 — Regime-Focused Research (Choppy-Market Profitability)

**Timestamp:** 2026-06-07 01:26 UTC
**Total System PnL:** $2,065.28 across 4,924 closed trades (was $1,370.92 / 4,858 on 06-04 → **+$694**)
**System Win Rate:** 51.0% (was 50.3%)
**Avg PnL/Trade:** $0.42 (was $0.33)
**Trigger:** Operator question — profitability drops in choppy markets; considering "multiple strategies on multiple markets."
**Report:** `docs/research/reports/2026-06-07_01-26-profitability-report.md`

### Trend
**IMPROVING overall** — best 48h window in the dataset (+$990, $1.80/tr, 59.5% WR). Prior fixes (min_score 7, max_trades 3, drift filter, blacklist, trailing profit) all validated and working. BUT a large, localized choppy-market leak remains.

### Top 3 Findings
1. **Session-of-day is the dominant profit factor.** US/EU session (UTC 13–22) is strongly profitable; **Asian/low-vol session (UTC 01, 06–12) bleeds ~−$1,335 over the last 5 days** (win rates 0–31%). The trend-short engine gets chopped in ranging Asian tape. (New — prior research never bucketed by hour.)
2. **One edge, not two.** Shorts +$2,149 / Longs −$106. Longs show 55% WR but **negative expectancy** (fat left tail) — no long edge exists; the 93%-bias *bug* fix did not create a long *strategy*.
3. **"21 accounts" = correlation, not diversification.** All accounts trade identical signals simultaneously → 21× correlated drawdowns (e.g. 06-06 13:00: 12–13 accounts in same 3 losers). The operator's "multiple strategies" instinct is correct but must come *before* more capital replication.

### Supporting discoveries
- **1–3h holds win (+$1,532); 3–6h holds lose (−$97)** — sharp chop-grind cliff at ~3h.
- **Blacklist leaks via ticker churn** — new toxic names (BABY, PARTI, TA, HOME −$114 to −$208 each, 0–16% WR). **Blacklist enforcement AUDITED & CONFIRMED working** — BIGTIME/SOXL/PLAYSOUT last traded 06-03, zero since blacklist deploy; earlier "reappeared" flag was a 7-day-window artifact that swept up the pre-blacklist 06-03 blowup (~−$344 in one day across 16–23 accounts each). Static blacklist is reactive (bans *after* the correlated loss); structural liquidity filter needed to catch the next toxic coin pre-blowup.
- **AI manager is break-even noise** (+$0.03/tr over 1,118 closes).
- **13 liquidations −$167** at 20× in volatile/illiquid names.

### Recommendation Status Updates (from 06-04)
| Rec | Status |
|---|---|
| Raise min_score 6→7 | ✅ IMPLEMENTED — validated (score 7 = +$1,268) |
| Reduce max_trades 5→3 | ✅ IMPLEMENTED |
| Post-scan drift filter | ✅ IMPLEMENTED (drift 3%, age 120m) |
| Symbol blacklist | ✅ IMPLEMENTED & AUDITED WORKING — but reactive; needs structural filter for new tickers |
| Trailing stop +2% | ✅ IMPLEMENTED |
| Lower profit goal 14→8% | ✅ IMPLEMENTED |
| Fix AI Manager pipeline | 🔶 PARTIAL — runs but adds ~$0 edge |
| 93% sell-bias fix | ✅ IMPLEMENTED — bug gone, but no long edge created |

### New Recommendations (this run)
1. **[VERY HIGH]** Session/regime entry filter — suppress/score-gate UTC 01,06–12 (~$200–300/day).
2. **[HIGH]** Structural symbol filter (24h vol, listing age, spread) vs static blacklist.
3. **[MED]** Cut long side to zero until a long strategy is backtested.
4. **[MED]** Chop exit — cut trades not resolved in ~3h during detected chop.
5. **[HIGH/long-term]** Backtest a regime-segmented mean-reversion strategy for the chop window (use the in-flight Backtesting System; must report per-session metrics).
6. **[RESOLVED]** ~~Audit blacklist enforcement~~ — audited, blacklist holds (zero trades since 06-03); no gap.
7. **[HIGH/long-term]** Strategy-cohort the accounts (A=trend US-session, B=mean-rev Asian-session) for real diversification.
8. **[MED]** Drop chop-cohort leverage 20×→10×.

### Note for Backtesting System (in-flight feature)
The backtester is the right vehicle to validate the mean-reversion strategy and account-cohort ideas **before funding**. It MUST be regime-segmented (per-session / per-volatility-bucket metrics) or it will average the Asian-session leak into US-session profit and hide the exact effect isolated here.

---

## 2026-06-07 — Two-Feature Integration (Regime Multi-Strategy + MCP Optimizer)

**Timestamp:** 2026-06-07 ~21:40 UTC
**Type:** Multi-feature merge to `main` (2 large independent feature branches) + comprehensive post-merge review
**Trigger:** The Regime Multi-Strategy and MCP Server features were completed in separate worktrees and needed to land on `main` together, cleanly, with correct migration ordering and no money-path regressions.

### Why this matters for profitability research

These two features directly operationalize the recommendations from the 2026-06-04 and 2026-06-07 research entries:

- **Regime Multi-Strategy** is the *implementation* of the "strategy-cohort the accounts" and "regime-segmented mean-reversion" recommendations (rec #5/#7 in the 06-07 entry). It adds a BTC-regime filter (F1), a mean-reversion strategy cohort (F2), and session filtering (F3) — so an account can be routed to trend OR mean-reversion based on detected market regime, instead of running one strategy blind into a chop window. This is the mechanism that lets us stop "averaging the Asian-session leak into US-session profit."
- **MCP Optimizer** lets an LLM agent run parameter sweeps over the *real* backtest engine and propose better configs — turning the backtester from a manual tool into an automated parameter-search loop, behind a human-approval gate before anything touches live trading.

Together with the backtesting + scheduled-scan data already imported, the research loop is now: detect regime → route the right strategy → sweep its params on history → human-approve → deploy.

### Feature 1 — Regime Multi-Strategy (F1/F2/F3)

**Problem it solves:** The 93%-sell-bias era and the chop-window losses both came from running ONE strategy (trend-following) regardless of market regime. In a ranging/choppy market, trend signals are noise; the data showed 3-6h holds losing in chop. There was no way to say "in this regime, fade the extremes instead of chasing the trend," and no way to run different strategies on different accounts.

**What was built:**
- **F1 — BTC regime filter:** classifies the market (trend / ranging / volatile) from BTC volatility and EMA distance; gates whether trend entries are allowed.
- **F2 — Mean-reversion cohort:** a full second strategy. When an account's `strategy_cohort = mean_reversion`, signals are *faded* (price-vs-mean) rather than followed, with their own leverage/capital/TP/SL, a fast time-stop (MR holds are 1-3h winners, 3-6h losers), and a drawdown breaker. MR positions are excluded from the AI Manager (they have their own fast exits).
- **F3 — Session filter:** block/allow specific UTC hours (isolates the Asian-session leak).
- **Strategy routing + cohort resolution**, kill-switches (`feature_kill_switches`), pending-trade-intents (so an orphaned MR fill is reconciled as MR, not mislabeled trend), and per-strategy backtest replay + per-trade strategy tagging.

**Key components:** `regime_filter.py`, `mean_reversion_math.py`, `strategy_router.py`, `kill_switch.py`, `pending_intents.py`, `scan_context.py`, `safety_monitors.py`, `market_data.py`. Migrations v43–v51 (strategy_cohort/strategy_kind columns, f2_long_ack, pending_trade_intents, feature_kill_switches, backtest_trades.strategy_kind).

### Feature 2 — MCP Server + Parameter Optimizer

**Problem it solves:** Backtesting validates a *single* config a human picked. But the config space (leverage × capital × TP × SL × min_score × close rules × …) is huge — manual exploration finds local optima at best. There was no automated way to search it, and no safe path from "the optimizer found a better config" to "live trading uses it."

**What was built:** A FastMCP streamable-HTTP server that exposes read tools + a parameter optimizer to an LLM agent. The optimizer runs sweeps over the **real** backtest engine, scores configs, and produces ranked proposals. The ONLY route from a swept config to live trading is a 3-gate apply pipeline (allow-list sanitize → absolute sanity ceiling → full cross-field validation) behind **explicit human approval** in the control plane. Includes token-budget UI (so enabling all tools doesn't blow the model's context), live-trading protection, audit log, and one-time data-egress consent.

**Key components:** `backend/mcp/` (61 modules — core/auth/netguard/breaker/budget, tools/optimizer/apply, repositories, transport). Migrations v52–v55 (renumbered from the branch's v43–v46 during the merge; 6 mcp_ tables + backtest_runs sweep tagging + money-column precision widening).

### Merge mechanics & money-safety (no room for error)

**Migration collision:** both branches branched at v42 and both started numbering at v43. The live dev DB had already applied regime's v43–v51, so regime KEEPS v43–v51 and MCP was RENUMBERED to v52–v55. Final list contiguous 1..55. Live DB migrated to v55, all tables present.

**Money-path composition (the hard part):** both features refactored the SAME trade-placement function (`auto_trade_service._try_trade`) differently — regime added F2 mean-reversion param computation + pending-intent lifecycle; MCP wrapped placement in a per-(account,symbol) position lock + live re-check, extracting a `_do_place` helper. These were COMPOSED by hand: `_try_trade` computes guards + routes (mr_fade), then calls `_do_place` under the lock; `_do_place` computes MR params (so the intent write AND order submission are both lock-protected) and executes. The composition introduced and caught one NameError (`cohort`) during the merge, and a post-merge review caught one dropped regime semantic (MR position-direction on the ambiguous-error branch) — both fixed.

**Cross-feature money-safety finding:** regime added 28 new fields to `AutoTradeConfig` (mr_leverage up to 125, mr_capital_pct, regime toggles, …). The MCP optimizer's fail-closed allow-list security guard correctly flagged them as unclassified. **All 28 were DENIED from optimizer sweeping** — the optimizer has no model of MR/regime interactions and must not auto-tune money-critical MR knobs. Additionally the absolute sanity ceiling was extended to bound `mr_leverage`/`mr_capital_pct` (defense-in-depth on the revert path).

### Review & verification

Comprehensive multi-aspect review (a correctness reviewer on the hand-composed money path; a security reviewer on the optimizer→live-config apply path), every finding adversarially verified before fixing. Security verdict: the apply pipeline is genuinely fail-closed — the 28 regime fields are unreachable by any agent/apply path (allow-list + double-sanitize + drift-guarded atomic write under FOR UPDATE).

- Backend: regime suite (281) + mcp suite (273) + money-path/MR/backtest suites all pass; full broad sweep 557 pass.
- Frontend: tsc clean, production build OK, 691 tests pass.
- Live DB at v55; full app lifespan (regime + mcp + all existing services) starts/stops clean; 21 mcp routes registered.
- Pre-existing `test_close_positions_service_unit.py` failures (stale `cumExecQty` mocks) proven present on the pre-merge tag — unrelated to this merge.

### Next steps for profitability research

1. Use the MCP optimizer to sweep **trend** params on the imported scheduled-scan history (the 28 MR fields stay deny-from-sweep until manually validated).
2. Backtest the F2 mean-reversion cohort regime-segmented (per-session metrics) before funding an MR account — exactly the 06-07 recommendation #5.
3. Validate F3 session filtering against the Asian-session leak isolated in the 06-07 research.

---

## 2026-06-07 — End-to-End Application Review (money-safety + reliability hardening)

**Timestamp:** 2026-06-07 ~22:30 UTC
**Type:** Full-application review + fixes (no new data analysis)
**Trigger:** End-to-end review of the whole app (money path, concurrency, data integrity, cross-feature integration) after 5 features were merged in.

### Method
Fanned out specialized reviewers (money-correctness, concurrency/reliability, data-integrity, cross-feature integration), then **adversarially verified every finding before fixing** — a verification pass refuted several reviewer claims and corrected severities. Only confirmed issues were changed.

### The most important finding (money-critical, production-proven)
**The default stop-loss sat AT/BEYOND the liquidation price, so losing trades rode to liquidation instead of stopping out.** With the default config (`stop_loss_pct=100`, `leverage=20`), the SL fires at a 5% adverse price move but Bybit liquidation happens at ~4.5% — so the protective stop never triggered. Confirmed at *every* leverage (10×/20×/50×). This directly explains the liquidations recorded in earlier research ("12 liquidations… should be zero with proper SL"; "13 liquidations −$167 at 20× in volatile names"). The mean-reversion path already had the correct guard (`MR_SL_LIQUIDATION`); the trend path had none.

**Fix:** a `clamp_sl_move_to_liquidation()` helper now caps the SL price-move to 0.9× the liquidation distance in `place_trade`, so the stop always fires before liquidation. Clamp (not reject) keeps existing default-config trades placing — now with a stop that actually protects. **Profitability impact: this should eliminate the liquidation losses and convert them into controlled stop-outs (a smaller, bounded loss per trade).**

### Other confirmed fixes
- **Position-lock force-release (concurrency):** `cleanup_account(force=True)` could release a lock held by another coroutine (asyncio locks have no owner) → two coroutines believing they own the same position → double place/close. Now never force-releases a held lock.
- **Shutdown ordering:** the scanner was torn down after accounts/AI-manager, so an in-flight scan could place an untracked trade through a closed client during shutdown. Now drains the scanner first + a `_shutting_down` guard refuses new clients during teardown.
- **MR aggregate-capital guard:** `mr_capital_pct × mr_max_trades` could commit >100% of base capital (over-allocation/liquidation risk) with no validator. Now capped at 100%, matching the trend guard.
- **Config coherence:** `session_filter_enabled` / `btc_vol_filter_enabled` were silent no-ops without `regime_filter_enabled` — now rejected loudly so a "blocked session" config can't silently trade through every hour.
- **WS reconnect rate-gate** + **migration `lock_timeout`** (deploy-safety): smaller reliability hardening.

### Deferred (noted, not fixed — lower severity / needs product decision)
- **Trailing-profit disarm:** once armed, if price retraces below `activation_pct` (still profitable) the trailing close stops being evaluated until uPnL≤0, so a winner can decay toward breakeven. Changing trailing-stop semantics needs a deliberate product call.
- **Trend partial-fill orphan:** if a trend order fills but the DB write fails, there's no pending-intent (the MR path writes one); the reconciler's symbol/size matching is the only backstop. Worth adding trend-path parity later.
- **Optimizer on MR-cohort accounts:** the MCP optimizer can sweep trend risk fields (capital_pct/leverage) that are inert on an MR-cohort account, producing misleading "best config" results. The dangerous case (auto-applying MR knobs) is already prevented (deny-from-sweep); making the optimizer MR-aware is an enhancement.

### Verification
Each fix has regression tests (SL clamp ×4, lock force-release ×1, MR aggregate + coherence validators ×6). App lifespan starts/stops clean with the reordered shutdown; frontend tsc + build pass. The ~42 pre-existing baseline failures (close_positions `cumExecQty` mocks, api-key env tests, sync-persistence-v35-vs-live-DB) are unrelated and predate this review.

---

<!-- NEXT RESEARCH ENTRY GOES BELOW THIS LINE -->







