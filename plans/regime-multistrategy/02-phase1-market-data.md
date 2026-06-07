# Phase 1 — Shared Compute (`market_data.py` + scan-time precompute)

**Entry criteria:** Phase 0 complete (migrations, config, ScanContext scaffold, gate extraction, golden snapshot green).
**Exit criteria:** BTC regime/vol + per-symbol means computed once per scan into `ScanContext`; F1 fail-open / F2 fail-closed verified; precompute failure degrades globally (trend proceeds, scan never aborts); kill-switch read once/scan; perf within budget (fetch counts bounded, single-flight dedup).

**Goal:** build the market-data computation layer and wire it into `start_scan` following the `_compute_adaptive_blacklist` injection pattern — WITHOUT yet using the results in any gate (gates come in Phases 3–4). With all features off, the precompute is skipped entirely (golden snapshot stays green).

---

## Cross-phase context (self-contained)
- Pattern to mirror: `scanner_service._compute_adaptive_blacklist` (`scanner_service.py:339`) → injected before executor at `start_scan` (`:407–437`).
- `ScanContext` (from Phase 0, `scan_context.py`): `btc: dict[(interval,lookback)->BtcRegime]`, `means: dict[(symbol,period,interval)->float]`, `prices: dict[symbol->float]` (PR1-9 per-symbol mark price), `computed_at`, `degraded`, `kill: dict[str,bool]`.
- Precompute-enable predicate (FR-009/FR-003): `any(cfg has (regime_filter_enabled ∧ btc_vol_filter_enabled) ∨ mean_reversion_enabled ∨ strategy_cohort=='mean_reversion' for cfg in auto_configs)`. Session-only F1 does NOT trigger BTC precompute.
- Kline source: existing `KlineCacheService`/equivalent via `bybit_rate_gate` (confirm exact API in planning — A-002).

---

## TASK-1.1 — `market_data.classify_regime` (pure, TDD)
- **Requirements:** SD1, SD1a, FR-012, T-22.
- **Files:** create `backend/services/market_data.py`.
- **NOTE (PD8):** metric is the constant `"atr_ratio"` (D9c cut `btc_vol_metric`); `ScanContext.btc` is keyed by `(interval, lookback)` only. `ScanContext.routing_regime(interval, lookback)` (PD9) returns `btc[(interval,lookback)].regime` or `"unknown"` if absent/degraded — used by `route_strategy`/F2.
- **Implementation (write test first):**
  ```python
  def compute_atr_ratio(klines: list[Kline], n: int) -> float | None:
      """ATR(n)/SMA(ATR(n) over n). Needs >= 2n+1 candles; else None."""
  def compute_ema_distance_pct(klines: list[Kline], n: int) -> float | None:
      """(close - EMA(n))/EMA(n) * 100. Needs >= n candles; else None."""
  def classify_regime(klines: list[Kline], *, lookback: int,
                      volatile_atr: float = 2.0, trend_ema_dist_pct: float = 1.0) -> BtcRegime:
      """First-match: unknown if candles < 2*lookback+1; volatile if atr_ratio>=volatile_atr;
         trending if abs(ema_dist)>=trend_ema_dist_pct; else ranging."""
  ```
  - ATR uses Wilder's true range. Required depth = `2*lookback + 1` (else `unknown`, `unavailable=True`).
- **Tests (`test_market_data.py`):** truth table — `test_classify_volatile()` (atr_ratio≥2.0), `test_classify_trending_up/down()` (|ema_dist|≥1.0), `test_classify_ranging()`, `test_classify_unknown_insufficient_candles()` (candles<2n+1), `test_atr_ratio_not_degenerate_to_one()` (with exactly 2n+1 candles, ratio computable ≠ trivially 1.0), `test_boundary_at_exact_threshold()` (atr_ratio==2.0 → volatile; ema_dist==1.0 → trending).
- **Verification:** `pytest tests/backend/test_market_data.py -x -q`.
- **AC:** AC-002, AC-013. **Rollback:** delete module.

## TASK-1.2 — `market_data.compute_ema_mean` (per-symbol, pure)
- **Requirements:** FR-022, NFR-002.
- **Files:** modify `market_data.py`.
- **Implementation:** `def compute_ema_mean(klines: list[Kline], period: int) -> float | None` — EMA over `period` closes; `None` if candles < period (→ `mr_insufficient_history`).
- **Tests:** `test_ema_mean_known_value()` (hand-computed EMA for a fixed series); `test_ema_mean_insufficient()` (candles<period → None).
- **Verification:** part of `test_market_data.py`.
- **AC:** AC-004. **Rollback:** remove function.

## TASK-1.3 — Kline fetch with 2×lookback depth + single-flight + bounded cache
- **Requirements:** SD1a, NFR-002, NFR-003, NFR-007, R3-17.
- **Files:** create `backend/services/market_data_fetch.py` (or a class in `market_data.py`); reuse existing kline cache.
- **Implementation:**
  - `async def fetch_klines(symbol, interval, depth) -> list[Kline]` — cache-first (key `(symbol, interval, lookback-bucket)`), via `bybit_rate_gate`, subordinate to order placement; depth ≥ `2*lookback+1` for BTC.
  - Single-flight (PR1-11): the in-flight `dict[key, asyncio.Future]` lives at the GLOBAL fetch/cache layer (process-lifetime), keyed same as the LRU — so two CONCURRENT cold scans hitting the same cold key coalesce (the in-scan benefit is already covered by tuple-dedup, so in-scan single-flight alone would be dead code). Alternatively, document that concurrent cold scans may double-fetch (bounded 2×) and drop it.
  - Bounded LRU (entry cap + documented memory estimate); cache key `(symbol, interval, lookback-bucket)` where lookback-bucket = the max-needed depth per `(symbol, interval)` (shorter requests tail-slice the cached longer series); no intra-scan eviction (capacity ≥ working set).
- **Tests:** `test_single_flight_dedup()` (N concurrent same-symbol → 1 fetch); `test_single_flight_rejection_no_negative_cache()` (failed fetch → next phase retries); `test_cache_keyed_by_interval_bucket()`.
- **Verification:** `pytest tests/backend/test_market_data_fetch.py -x -q`.
- **AC:** — **Rollback:** delete module.

## TASK-1.4 — `build_scan_context` (precompute orchestration)
- **Requirements:** FR-003, NFR-001, NFR-002, NFR-006, R4-7.
- **Files:** modify `market_data.py` (add `async def build_scan_context(auto_configs, scan_results, *, now, kill, fetcher) -> ScanContext`). NOTE (R3-F1): `kill` is passed IN (read unconditionally in start_scan), NOT read here.
- **Implementation:**
  - If precompute-enable predicate is False → return `ScanContext.empty(degraded=False, kill=kill)` (no fetches — golden snapshot path, but carries the kill dict).
  - Else, wrap the whole block in `try/except` with a bounded total time budget (`asyncio.wait_for`), using **bounded-concurrency `asyncio.gather` (PR1-10:** a semaphore-capped fan-out, subordinate to `bybit_rate_gate`; cap = e.g. 8) over the deduped tuple-sets:
    1. (kill already read in start_scan and passed in).
    2. BTC tuples: collect distinct `(interval, lookback)` from configs that need a regime — i.e. configs with `(regime_filter_enabled ∧ btc_vol_filter_enabled)` OR `mean_reversion_enabled` OR `strategy_cohort=='mean_reversion'` (PR1-6: MR-cohort/MR-enabled configs contribute their `(btc_vol_interval, btc_vol_lookback_candles)` tuple EVEN WHEN `btc_vol_filter_enabled` is false — else `routing_regime`→"unknown"→route "none"→MR never fires). For each → fetch + `classify_regime` → `btc[tuple]`.
    3. Qualifying MR symbols = `{r.symbol for r in scan_results if abs(r.score) >= min(mr_extreme_min_abs_score over MR-enabled accounts)}`; for each distinct `(symbol, period, interval)` → fetch + `compute_ema_mean` → `means[tuple]`; ALSO fetch the per-symbol mark price → `prices[symbol]` (PR1-9: account-independent, precomputed so the MR hot path does a dict lookup, not a per-account `get_mark_price`).
    4. Return `ScanContext(btc, means, prices, computed_at=now, degraded=False, kill=kill)`.
  - On ANY exception/timeout → log warning + return `ScanContext.empty(degraded=True, kill=kill)` (F1 will fail-open, F2 fail-closed; trend proceeds).
- **Tests:** `test_precompute_skipped_when_all_off()` (no fetch calls); `test_precompute_memoized_btc_by_tuple()` (≤ distinct tuples); `test_precompute_mean_scoped_to_qualifying_symbols()` (not all 570); `test_mr_cohort_with_vol_filter_off_still_classifies_regime()` (PR1-6); `test_precompute_failure_degrades_globally()` (fetcher raises → degraded ScanContext, no exception out); `test_precompute_within_budget()` (timeout → degrade); `test_precompute_concurrency_capped()` (PR1-10, ≤ cap in-flight).
- **Verification:** `pytest tests/backend/test_market_data.py -k precompute -x -q`.
- **AC:** AC-003. **Rollback:** remove function.

## TASK-1.5 — Wire precompute into `scanner_service.start_scan`
- **Requirements:** FR-003, R2-11, R4-4.
- **Files:** modify `backend/services/scanner_service.py` (`start_scan`, near the adaptive-blacklist injection at :407).
- **Implementation:**
  - After adaptive-blacklist injection: ALWAYS read the kill-switch (`kill = await read_kill_switches(db)`, R3-F1 — unconditional). If precompute-enabled: `scan_context = await market_data.build_scan_context(auto_configs, results_so_far_or_signals, now=datetime.now(timezone.utc), kill=kill, fetcher=self._kline_fetcher)`; else `scan_context = ScanContext.empty(degraded=False, kill=kill)`. Pass `scan_context` to the `AutoTradeExecutor` (new constructor kwarg `scan_context=`), NOT injected per-config. (Both paths carry the kill dict so the master/f1 kill works even with no precompute.)
  - Persist scan-global regime to `regime_snapshots` (SD6 columns) and suppressed/allowed counts to the run/config snapshot. PR1-20: batch the per-config writes into ONE write (not N awaited INSERTs); `regime_snapshots` gets a retention/rollup sweep (mirror debug_trace) to bound growth.
  - `_computed_*` per-config injection remains ONLY for adaptive_blacklist.
- **Tests:** `test_start_scan_builds_context_when_enabled()`; `test_start_scan_no_context_when_all_off()` (executor gets empty context, golden path).
- **Verification:** golden snapshot still green (all-off → no context built/used).
- **AC:** AC-002. **Rollback:** revert start_scan.

## TASK-1.6 — Kill-switch reader (read UNCONDITIONALLY in start_scan)
- **Requirements:** FR-007, AD2, AD19, R3-F1.
- **Files:** create `backend/services/kill_switch.py`; wire into `start_scan` (TASK-1.5).
- **CRITICAL (R3-F1):** the kill-switch is read UNCONDITIONALLY in `start_scan` — NOT inside `build_scan_context` (which only runs when the precompute predicate is true). Otherwise the master emergency-stop `__all__` and the `f1` kill are no-ops for session-only-F1 or trend-only fleets (exactly when an operator wants to halt trend trades). The `kill` dict is injected into BOTH the real `ScanContext` AND `ScanContext.empty(...)` (so `empty()` carries the kill dict, not `{}`).
- **Implementation:** `async def read_kill_switches(db) -> dict[str,bool]` — SELECT `feature_name, killed` from `feature_kill_switches`; the `kill` dict value IS the `killed` column verbatim (R2-F2). The admin endpoint sets `killed=true` to kill a feature. NO row = not killed. On exception → return `{"__all__": True}` (fail-closed). `is_killed(kill, feature)` = `kill.get("__all__") or kill.get(feature, False)`. `start_scan` calls it once and threads the dict into whichever ScanContext it builds (real or empty).
- **Tests:** `test_kill_switch_master_disables_all()`; `test_kill_switch_read_failure_fails_closed()`; `test_kill_switch_no_row_not_killed()` (T-21); `test_kill_switch_column_to_dict_direction()` (R2-F2/R3-F3: insert the kill row via a direct DB/repo write here — the admin endpoint is built in Phase 4; this Phase-1 test uses a direct write, the endpoint-level test lives in Phase 4); `test_kill_read_when_precompute_skipped()` (R3-F1: kill enforced even when no account triggers precompute — `empty()` context still carries the kill dict).
- **Verification:** `pytest tests/backend/test_kill_switch.py -x -q`.
- **AC:** AC-010. **Rollback:** delete file.

---

## Phase 1 Validation (exit gate)
```
python -m pytest tests/backend/test_market_data.py tests/backend/test_market_data_fetch.py tests/backend/test_kill_switch.py tests/backend/test_regime_golden_snapshot.py -x -q
```
Golden snapshot green (all-off unaffected) + new compute tests green + fail-open/closed/degrade verified → Phase 1 complete. Commit: `feat(regime): phase 1 — market_data classify_regime + EMA mean + scan-time precompute + kill-switch (unused by gates yet)`.

## Phase 1 → traceability
SD1/SD1a→T-1.1; FR-022→T-1.2; NFR-002/003/007/R3-17→T-1.3; FR-003/NFR-006/R4-7→T-1.4; FR-003→T-1.5; FR-007→T-1.6.
