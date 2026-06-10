# Backtest Optimization — Discovery Summary (Step 1)

**Date:** 2026-06-09
**Source:** 6-agent discovery workflow + firsthand reads. Grounding for spec/plan.
**Companion:** `specs/backtest-optimization-findings.md` (root-cause investigation).

This doc captures the codebase surface the optimization must respect. It is INPUT to the
requirements brainstorm + spec. Everything here is evidence from the actual code.

---

## 1. Repository / Stack

- Backend: FastAPI (Python 3.14.3), asyncio + asyncpg (PostgreSQL). numpy 2.4.4 present
  (transitive via pandas); engine currently **pure-Python (math/Decimal), zero heavy deps**.
- Frontend: React + TS + Vite (TanStack Query/Router). Backtest UI under
  `frontend/src/components/backtest/`, API client `frontend/src/api/client.ts`.
- Tests: pytest + pytest-asyncio (**strict mode** — async tests missing `@pytest.mark.asyncio`
  silently error/skip). Markers: unit/integration/smoke/slow.
- Migrations: `_MIGRATIONS` list in `backend/async_persistence.py` (positional version ints,
  single `schema_version` row). Current latest = **v57**; next free = **v58**.

## 2. Core Files (semantic parity required — must not change behavior)

| File | Role |
|------|------|
| `backend/services/backtest_engine.py` (~1910 L) | Pure sync sim loop. Reads every config via `config.get(field, default)`; defaults MIRROR schema. |
| `backend/services/backtest_service.py` (~1660 L) | Async orchestration: load signals/klines, warm cache, 2-phase drilldown, threadpool, persist. |
| `backend/services/kline_cache_service.py` (~560 L) | Kline fetch/store/coverage. Bybit REST. `get_coverage_gaps` = the re-download bug site. |
| `backend/services/trading_rules.py` | SSOT for sizing, TP/SL, slippage, liq, fees, trailing, breakeven. Shared live+backtest. |
| `backend/mcp/tools/optimizer/sweep_tools.py` + `sweep_repo.py` | Param sweep — calls pure engine directly (bypasses drilldown). |
| `backend/services/backtest_metrics.py` | `compute_all_metrics(trades, equity_curve, config)` @ L607 → ~45-key metrics dict. |

## 3. Config Surface (the requirements surface — must keep honoring identically)

Flow: `BacktestCreateRequest.model_dump()` → dict → engine `config.get(...)`. **MCP `backtest_run`
params are 1:1 identical.** `starting_capital` + `date_range_*` + `scan_source` are required
(engine reads `config['starting_capital']` by subscript @ L177). Groups:

- **Execution (backtest-only):** starting_capital, simulation_interval(5m/15m/1h/4h),
  fee_rate_pct(0.055), slippage_bps(2), funding_rate_model+funding_rate_fixed_pct,
  drilldown_enabled(True), direction(straight/reverse), execution_mode(immediate/batch),
  fill_to_max_trades, leverage(20), capital_pct(5).
- **Trade-decision (AutoTradeConfig parity):** take_profit_pct(150), stop_loss_pct(100),
  17-step filter chain (blacklist/whitelist/existing-pos/[regime]/signal-age/hold-skip/
  max_same_direction/sector NO-OP/adaptive_blacklist/signal_sides/min_score/confidence/
  max_trades/target_goal/balance/price_drift), symbol_blacklist/whitelist(≤200),
  max_signal_age_minutes, max_price_drift_pct(signed, direction-aware).
- **Close rules:** max_drawdown_pct(100), smart_drawdown_close(EQUITY_DROP_PCT_SMART one-shot/scan),
  breakeven_timeout_hours, max_trade_duration_hours, trailing_profit_pct, close_on_profit_pct
  (requires target_goal_value), target_goal_type(trade_count LIFETIME early-stop | profit_pct).
- **Adaptive blacklist:** enabled, min_trades(5), max_win_rate(30), lookback_hours(48) —
  computed from the backtest's OWN trade history.
- **F1 regime/session:** regime_filter_enabled, session_filter (allowed/blocked hours, mutually
  exclusive), btc_vol_filter (min/max thresholds, interval, lookback), regime classifier tuning
  (staleness/volatile_atr/trend_ema_dist).
- **F2 mean-reversion:** mean_reversion_enabled, mr_short/long_enabled, mr_long_ack (BYPASSED in
  backtest), mr_mean_period/interval, mr_target_capture_pct, mr_tight_stop_pct, mr_time_stop_minutes,
  mr_min_edge_pct, mr_extreme_min_abs_score, mr_capital_pct, mr_leverage, mr_max_trades.
- **F3 cohort:** strategy_cohort(trend|mean_reversion|None→trend in backtest).

Cross-validations in schema: stop_loss_pct/leverage < 100; close_on_profit_pct requires
target_goal_value; session allowed/blocked mutually exclusive; btc_vol min<max.

## 4. API + Lifecycle (must not regress)

- Endpoints (`backend/routers/backtest.py`): POST `/backtest` (create), POST `/backtest/{id}/run`,
  POST `/backtest/{id}/cancel`, GET `/backtest` (list), GET `/backtest/{id}`, DELETE `/backtest/{id}`,
  GET `/backtest/{id}/trades` (paginated), POST `/backtest/compare`, GET `/backtest-cache/status`,
  POST `/backtest-cache/warmup`.
- Run states: pending → running → completed/failed/cancelled. Cooperative cancel via
  `threading.Event` (engine checks every 100 candles). Concurrency `_MAX_CONCURRENT=3` (slot counter).
  **`_TIMEOUT_SECONDS=120` is a HARD wall-clock cap** — a slow run is killed at 120s. This is BOTH
  the symptom (runs time out) AND a constraint (optimized run must finish well under it; may be raised).
- Progress: engine `on_progress` → throttled DB `progress_pct`. Warm-up owns first `_WARMUP_BAND=10%`.
- Per-client create rate limit (sliding window).

## 5. Result/Trade JSON Contract (frontend depends on — BACKWARD COMPAT REQUIRED)

- `BacktestResults{metrics, equity_curve, summary, warnings}`; `BacktestMetrics` ~45 keys
  (net_profit, net_profit_pct, win_rate, profit_factor, max_dd_pct, final_equity, buy_hold_final_value,
  total_trades, Sharpe, Sortino…); `EquityPoint{ts, equity, drawdown_pct?}`;
  `BacktestTrade` 19 fields + strategy_kind; `CacheStatusResponse{symbols_total, symbols_cached,
  symbols_with_gaps, ready}`.
- **BREAKING-CHANGE TRAP:** if `metrics.total_trades` is absent/renamed, the UI routes completed runs
  to the "no trades simulated" fallback (`BacktestResultsPage.tsx:255`) — looks like data loss.
  **Only ADD optional nullable keys; never rename/retype/remove existing keys.**
- `equity_curve` is LTTB-downsampled on GET. A manifest hashing the curve must hash the FULL stored
  JSONB, not the downsampled API view.
- Persistence idempotency: results upsert ON CONFLICT(run_id); trades delete-before-insert; kline
  INSERT ON CONFLICT DO NOTHING; coverage GREATEST upsert. NUMERIC cols need Decimal coercion +
  finite-guard (`_num` @ backtest_service.py:1449) or one Inf/NaN aborts `_persist_results`.

## 6. Metrics (numerical oracle-parity surface)

`compute_all_metrics(trades, equity_curve, config)` @ backtest_metrics.py:607. ~45 metrics: Sharpe,
Sortino, max drawdown (path-dependent on equity_curve ORDER), win rate, profit factor, expectancy,
buy&hold baseline, equity-curve LTTB downsample. All must match the oracle within tolerance; the
path-dependent ones require equity_curve ordering to be preserved exactly.

## 7. Existing Golden/Parity Test Infrastructure (Phase 0 builds on this)

- `tests/backend/test_backtest_golden.py` exists — but uses **inline hand-verified magic numbers**
  (38.9725, -510.725, 959.0, -878.4, 77.941103). Brittle: any legit fee/slippage/sizing change forces
  manual re-derivation. **Phase 0 should prefer a STORED-SNAPSHOT oracle** (run current engine, freeze
  output) over more magic numbers.
- `_assert_reconciles` only ties `metrics['net_profit']` to `final_equity - start` — it does NOT
  independently assert `Σ trade['pnl']`. **Phase 0 must add the explicit per-trade-sum cross-check.**
- Cheap fast seam = the **pure engine layer** (sync, no DB) for fixtures; reserve async mock_db for
  service-layer parity.
- Branch builders (`_config`/`_signal`/`_klines`) are duplicated across golden/engine/regime tests with
  DIFFERENT defaults — do NOT consolidate naively (shifts frozen golden values); extend in place.
- Unrelated decoys: `tests/golden_diff_async.py`, `tests/test_cache_parity_eval.py` are LLM-graph
  harnesses, NOT backtest parity — do not touch.

## 8. Tricky Parity Landmines (verified)

- `close_reason 'liquidation'` is effectively UNREACHABLE in normal configs (SL-clamp pulls SL inside
  the liq band) — a liquidation fixture must deliberately omit SL or set it outside the band.
- `equity_drop_smart` is ONE-SHOT per scan (re-arm @ engine L1139) — fixture must test the re-arm.
- `max_same_sector` is an INTENTIONAL no-op in the engine (needs IO sector service) — **do NOT "fix" it**;
  service emits `max_same_sector_not_enforced` warning.
- Golden NO-OP guarantee: empty instrument_info/scan_contexts/fine_klines + no regime ⇒ engine output
  byte-identical to the pure 5m path. Must hold after every phase.
- `regime_staleness_minutes` is live-only (backtest builds fresh ScanContext per scan_time) — N/A in
  backtest, accepted for parity.

## 9. Storage DDL + Migration Constraints

- Tables (migration 38): `kline_cache` (PK symbol,interval,open_time; PARTITION BY RANGE(open_time),
  monthly ±6mo from migration time + DEFAULT catch-all), `kline_cache_coverage`
  (PK symbol,interval,date; candle_count SMALLINT), `backtest_runs`, `backtest_results`, `backtest_trades`.
- Sealed-manifest columns are NET-NEW. Add as **migration v58** (next free int after v57), `ADD COLUMN
  IF NOT EXISTS` with constant default, idempotent. Likely on `kline_cache_coverage` (sealed flag /
  provenance) and/or `backtest_runs`.
- **Migration hazards:** (a) version-int collisions have happened twice before (parallel branches) —
  claim next free int + coordinate; (b) multi-statement DDL as a string is split on inner `;`
  incorrectly — **use a callable migration** for multi-statement DDL; (c) partition set only spans
  ±6mo from migration time (store_klines auto-creates on write, but a >6mo-old sealed range may live in
  `kline_cache_default`).

## 10. New Dependencies (Phase 4/5) — IMPORT-GUARD REQUIRED

numba, pyarrow, duckdb are ALL net-new. Declare in `pyproject.toml [project].dependencies` (`>=` floor,
requires-python ≥3.10). **The backend is currently pure-Python with zero heavy deps — new deps MUST be
import-guarded with a pure-Python fallback path, or a missing wheel makes the ENTIRE backend fail to
import.** numba in particular: strict numpy/Python pins, slow first-call JIT. Project tracks transitive
CVEs (pip-audit floors) — new deps widen that surface. **D5 risk:** Python 3.14.3 + numpy 2.4.4 is
bleeding-edge for numba 0.65.1/llvmlite 0.47.0; Phase 3 must hit "minutes" so numba is optional.

## 11. Discovery Output Summary

- **Key constraint:** every config field, endpoint, metric key, and result-JSON shape above is a
  no-regress surface. The optimization changes HOW data is loaded/looped/stored, never WHAT the
  business rules decide.
- **Biggest risks:** (1) frontend breaking-change via metrics keys; (2) migration version collision +
  multi-statement split; (3) new-dep import crash; (4) golden brittleness / missing per-trade-sum check;
  (5) numba on bleeding-edge Python.
- **Areas needing extra care:** the 17-step filter chain ordering, equity_curve ordering (path-dependent
  metrics), the one-shot smart-drawdown re-arm, the drilldown full-book equity coverage rule.
