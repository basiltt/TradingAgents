# Backtest Optimization — Findings & Decision-Ready Engineering Plan

**Date:** 2026-06-09
**Author:** Lead Engineer (synthesis of multi-agent diagnosis + web research + adversarial verification)
**Scope:** Why the crypto-futures backtester is slow (hours → target minutes) and re-downloads kline data every rerun, and how to make it TradingView-fast **without changing business logic** (<1% deviation from real trading).

**Files in scope:**
- `backend/services/backtest_engine.py` (pure simulation core — ZERO I/O)
- `backend/services/backtest_service.py` (orchestration, loaders, drill-down)
- `backend/services/kline_cache_service.py` (coverage detection + Bybit fetch + Postgres store)
- `backend/mcp/tools/optimizer/*` (sweep_tools, orchestrator, runner_pool) + `backend/mcp/repositories/sweep_repo.py`
- `backend/async_persistence.py` (kline_cache DDL)

---

## 1. Executive Summary

- **The slowness is NOT the per-candle math — it's the SETUP that scales with total candles per scan.** `_evaluate_candles_until` rebuilds a datetime-keyed window index by walking *every open symbol's entire kline list on every scan*, and re-seeds every carried position's mark by a linear prefix scan from index 0. Net engine complexity ≈ **O(scans × symbols × N_total)** with a **quadratic-in-time** seeding term, versus an achievable **O(total_candles × symbols)** single merge-walk. Fixing the data layout (structure-of-arrays + `searchsorted`/pointers) is the single biggest engine win and is **parity-neutral** (it changes *how* prices are located, not *which* decisions are made). **VERIFIED.**

- **The re-download bug is a false-positive coverage gap, not a missing cache.** `get_coverage_gaps` flags any day holding fewer than the theoretical-max candle count (288 for 5m) as a *perpetual* gap. Legitimately-short days (mid-day listing, halt/outage, the still-forming current day) store e.g. 144/288, refetch returns the same 144, the `GREATEST` upsert caps it at 144 < 288 forever, and `fetched_at` is never consulted (no TTL). Because `ensure_coverage` fetches one span `[min(gap_days) .. max(gap_days)+1d]`, a perpetual-gap day near the start (listing) plus one near the end (current/short day) **bracket the entire window and re-download the whole history on every rerun, independent of config changes.** **VERIFIED.**

- **There is a second, intentional re-download: Phase-B 1m drill-down.** `_build_fine_klines` calls `_fetch_klines_from_bybit` directly and deliberately does **not** persist it, so every rerun (and Phase B of every run) re-pulls all 1m drill-down candles over a contiguous `min→max` span that discards ~98% of fetched candles. **VERIFIED.**

- **A pure vectorbt-style rewrite is INFEASIBLE for the general config** — and adversarial review confirms it. The engine is a cross-sectional, shared-capital portfolio simulation with path-dependent latches (running wallet sizing, `cycle_start_equity` zeroing, `smart_drawdown_fired` one-shot, funding boundary dedupe, adaptive-blacklist-from-own-trades) and **portfolio-level close rules** (EQUITY_DROP/SMART/close_on_profit/EQUITY_RISE) that flatten the whole basket on a basket-equity threshold. The right architecture is **keep the sequential event loop, make it numba-fast over columnar numpy arrays**, with an optional vectorized barrier-exit fast-path for the narrow subset of configs where positions are provably independent.

- **Headline expected speedup: hours → seconds-to-minutes (≈100–1000× on the engine hot path; sweeps additionally parallelize across cores).** The dominant wins are (a) columnar SoA + `searchsorted`/merge-walk to kill the O(scans × N_total) setup and quadratic seeding, (b) `@njit` the per-candle kernel, (c) fix the coverage detector so closed days are fetched once ever, and (d) batch/parallelize the loaders and sweep execution. Storage moves to a Parquet/DuckDB read cache + in-process Arrow layer so reruns/sweeps slice from RAM. Parity is protected by a **golden-master diff** against the current engine before any optimization is trusted.

---

## 2. Root Causes (ranked)

Severity scale: **CRITICAL** (dominates runtime or causes the re-download) → **HIGH** → **MEDIUM** → **LOW**.
"VERIFIED" = independently confirmed by the adversarial verdicts in the bundle.

### RC-1 — Per-scan full re-scan to build the window index — **CRITICAL · VERIFIED (high confidence)**
- **What:** `_evaluate_candles_until` rebuilds `symbol_time_idx` + `all_timestamps` by walking the *entire* `klines.get(sym, [])` list for every open symbol on *every* scan, then sorts the timestamp set.
- **Why it's slow:** The window is bounded by `(start_time, end_time)` but the *scan over the data is not* — the inner loop uses `continue` (not `break`) on both bounds, so it touches all `N_total` candles to extract a window that is often a handful of candles. Setup scales with `N_total` per scan instead of with window size.
- **Evidence:** `backtest_engine.py:1186-1205` (build), call sites `273-274`, `295-298`. Lists are ascending (the seeding loop relies on it), so a bisect/slice is provably O(log N + W).
- **Verifier caveat (honest):** the outer loop iterates `open_symbols = {p.symbol for p in state.open_positions}` (bounded by `max_trades`, typically 2–10), **not** the full ~50-symbol universe. So "billions of iterations / ~50 symbols" is the worst case; the typical cost is tens-to-hundreds of millions of setup iterations. The **asymptotic claim (setup ∝ N_total per scan) and avoidability are unambiguously correct.**

### RC-2 — Quadratic-in-time mark-seeding (linear prefix scan from index 0) — **CRITICAL · VERIFIED (high confidence)**
- **What:** Each open position's mark is seeded by iterating `klines.get(p.symbol, [])` from the FIRST element until `open_time > start_time`. The same "scan-from-start-to-find-latest-price ≤ T" anti-pattern recurs in three places.
- **Why it's slow:** `start_time` advances monotonically every scan (`scan_order` sorted chronologically), so the prefix length grows toward `N_total` → **O(P × N_total) per scan → O(P × T²) over the run.** The `carried_upnl` variant at `978-986` is worse — it re-runs per *signal*, multiplying by signals-per-scan.
- **Evidence:** `backtest_engine.py:1215-1223` (seed), `978-986` (`_open_position` carried_upnl), `1143-1152` (`_open_scan_signals` carried_upnl). No bisect, no cached cutoff index, no pointer memoization anywhere.
- **Fix:** `np.searchsorted(open_time_epoch, T, side='right') - 1` → O(log N); with merge-walk pointers it's O(1).
- **Verifier caveat:** cost only accrues while positions are *carried across scans*; the dominant blow-up is N_total × S (quadratic in backtest length), not position count. Pure CPU waste — does **not** cause re-downloads.

### RC-3 — Coverage detector treats any short day as a perpetual gap — **CRITICAL · VERIFIED (high confidence) · THE RE-DOWNLOAD BUG (part 1)**
- **What:** `get_coverage_gaps` expects `per_day_full` (288 for 5m) for interior days and flags a day as a gap when `cached_count < expected`. Listing days, low-liquidity symbols, exchange outages, and the still-forming current day legitimately hold fewer candles.
- **Why it never heals:** Bybit returns the same smaller set on refetch; `_update_coverage` upserts `GREATEST(144,144)=144`; `fetched_at` is never read in gap detection (no TTL). So 144 < 288 stays a gap **forever** and refetches on every run.
- **Evidence:** `kline_cache_service.py:115-196` (esp. `156`, `158-176`, `192`), `286-318` (`GREATEST` at `313`).
- **Verifier caveat:** "low-liquidity symbol" is debatable (Bybit forward-fills zero-volume perp candles, so a quiet symbol may report a full 288). The **listing-day and current-day cases are unequivocal.** This is a refetch-waste/efficiency defect, not a data-correctness defect — the backtest still reads whatever is cached.

### RC-4 — `ensure_coverage` span collapses to the full range when gaps bracket the window — **CRITICAL · VERIFIED (high confidence) · THE RE-DOWNLOAD BUG (part 2)**
- **What:** `ensure_coverage` fetches one span `[min(gap_days) .. max(gap_days)+1d]`. A perpetual-gap listing day near the start + a short/most-recent day near the end make `min`/`max` bracket the **entire** window.
- **Why it's bad:** The whole history re-downloads on every rerun even when only a config parameter changed — gap detection keys only on `(symbols, interval, start, end)`, so it is config-independent.
- **Evidence:** `kline_cache_service.py:198-284` (`239-258`).
- **Verifier caveat (important nuance):** `_fetch_klines_from_bybit` is capped at `_MAX_PAGES(5) × _PAGE_SIZE(200) = 1000` candles/call. For spans > ~1000 5m candles (~3.47 days) each run re-downloads only the most recent ~1000 candles of the span — which makes the bug arguably **worse** (interior gaps beyond the tail never fill, so it *never converges*). The literal phrase "whole history in one shot" is exactly true only for ranges ≤ 1000 candles.

### RC-5 — `ensure_coverage` invoked every run with no warmed-guard and no cross-run memo — **HIGH · VERIFIED**
- **What:** `_run_backtest` always calls `ensure_coverage` before reading; `_load_klines` re-queries Postgres fresh each run. Nothing memoizes `(symbol, interval, range)` across runs in a session.
- **Why it's slow:** Even absent the detector bug, identical reruns redo coverage checks and Postgres round-trips; with the detector bug they redo Bybit fetches.
- **Evidence:** `backtest_service.py:726-748`, `964-977`.

### RC-6 — `_load_klines` does N sequential per-symbol DB round-trips (N+1) — **HIGH · VERIFIED**
- **What:** `for symbol in symbols: klines[symbol] = await get_klines(...)` — serial awaited round-trips, one per symbol, each a single `pool.fetch`.
- **Why it's slow:** Blocks the event loop on S sequential RTTs before the engine can start; runs on the critical path of every run and inside sweep `load_inputs`. Each `get_klines` also builds a Python dict per row with six `float()` casts — CPython-bound materialization of millions of rows.
- **Evidence:** `backtest_service.py:964-977`; `kline_cache_service.py:51-69`.
- **Fix:** Single `WHERE symbol = ANY($1) AND interval=$2 AND open_time BETWEEN $3 AND $4 ORDER BY symbol, open_time` (1 round-trip) and bucket in Python; read columnar (Polars/numpy), convert once.

### RC-7 — Phase-B 1m drill-down over-fetches a contiguous span, serial, never cached — **HIGH · VERIFIED · THE RE-DOWNLOAD BUG (part 3)**
- **What:** `_build_fine_klines` fetches a contiguous `min(epochs)→max(epochs)` 1m window per symbol for what is actually a *set* of ~15 discrete event bars, keeps only bars whose bucket key is in `epochs` (~98% discarded), awaits each symbol serially, and **deliberately does not store** the result.
- **Why it's slow:** Network cost paid in full on every run including byte-identical reruns; `drilldown_enabled` defaults True so it's on the default critical path; the 1000-candle pagination cap silently truncates symbols whose trades span > ~16.6h.
- **Evidence:** `backtest_service.py:983-1088` (`991-994`, `1064-1069`, `1082`); `kline_cache_service.py:348-432`.
- **Fix:** Fetch only the narrow per-bar windows (group adjacent epochs), bounded `asyncio.gather`, and add an in-process per-session 1m cache keyed by `(symbol, bar_epoch)`. **Must stay in-memory only** — never `store_klines` (would re-poison the 5m coverage table).

### RC-8 — Drill-down runs the full engine simulation TWICE — **MEDIUM · VERIFIED**
- **What:** With drill-down on, `engine.run` executes once as Phase A (to learn entry/exit bars) then again as Phase B with `fine_klines`. Phase A simulates the whole book at 5m just to discover bar indices.
- **Why it's slow:** Doubles engine CPU wall-time on the default path; holds an executor worker for the duration (only 3 workers).
- **Evidence:** `backtest_service.py:804-841`.
- **Fix:** Skip Phase A entirely for configs with **no portfolio-equity close rules** (exit bars are knowable per-trade from TP/SL without a global pass); otherwise emit the bar map as a cheap side-channel from a dry-run mode.

### RC-9 — Trailing-profit is O(P²) per candle (full book scan per symbol) — **HIGH · VERIFIED (medium confidence)**
- **What:** The caller loops `candles_at_time` symbols and calls `_evaluate_trailing_profit_for_symbol`, which loops ALL `state.open_positions` and `continue`s on non-matching symbols.
- **Why it's slow:** `|candles_at_time| == |open_positions| = P` (one-position-per-symbol rule), so it's **O(P²) per candle**, almost all iterations short-circuited. The efficient inverse pattern already exists 90 lines above in the TP/SL loop.
- **Evidence:** `backtest_engine.py:1354-1358`, `1788-1791`.
- **Verifier caveat:** magnitude is O(P²) where P = concurrent positions (bounded by `max_trades`), **not** O(scanned-universe × positions). Gated on `trailing_profit_pct` being set.

### RC-10 — Per-candle allocations, defensive copies, function-local imports — **HIGH · VERIFIED (medium confidence)**
- **What:** Each candle rebuilds `candles_at_time` (fresh dict), copies `open_symbols` via `list(...)`, copies the book via `list(state.open_positions)`, allocates a new `positions_to_close` list; `_eval_equity_core` runs function-local imports every call and (conditionally) makes two full passes over `open_positions`; `pos in state.open_positions` is O(P) membership on a list.
- **Evidence:** `backtest_engine.py:1235-1241`, `1266-1267`, `1347`; `1607-1612`, `1623-1634`, `1648-1661`; `1846`, `1907`.
- **Verifier caveats (honest, keeps this at medium):** (1) the "TWO full passes" is **conditional** on `max_drawdown_pct < 100.0`; the default is 100.0, so a default run makes **one** pass. (2) Local imports hit the `sys.modules` cache (cheap dict lookup, not re-execution). (3) "Dominate" is asserted, not profiled — the larger cost is the *multiple separate full passes* over `open_positions` across sub-evaluators (equity, trailing, time) each candle. Still a legitimate, real cleanup.

### RC-11 — Data layout (list[dict] keyed by datetime) blocks vectorization/JIT — **HIGH · VERIFIED (high confidence)**
- **What:** All kline access is dict-keyed (`k["open_time"]/["open"]/...`) on Python objects with **datetime** keys. Zero numpy/numba anywhere (grep confirms 0 matches). The numeric core (liq/SL/TP precedence, uPnL sums, MFE/MAE, funding) is pure float arithmetic, highly amenable to numpy columns + `@njit` once the layout is SoA with int64 epoch time.
- **Why it matters:** Forces interpreted per-element access in a triple-nested loop (timestamps × symbols × positions) and prevents JIT everywhere. The only true coupling is cross-symbol portfolio equity (sum across whole book) + cycle-wide termination — handled by a numba merge-walk over per-symbol pointer indices.
- **Evidence:** `backtest_engine.py:1190-1205`, `1550-1559` (datetime keys), numeric kernels `1255-1263`, `1276-1281`, `1308-1343`, `1623-1661`.
- **Verifier caveat:** an int-epoch path already exists in helpers (`_fine_window` at `760-762`, `_sim_bar_seconds` notes open_time may be datetime *or* epoch). The "@njit once SoA" portion is a sound forward-looking assessment, not code that exists yet; kernels call imported helpers that need njit reimplementation.

### RC-12 — Per-signal linear scans for entry-bar + price-drift — **MEDIUM · (from diagnosis)**
- **What:** `_open_position` finds the entry fill bar with a linear `for k in symbol_klines: if k["open_time"] >= current_time: break`, and `_apply_filter_chain` repeats the identical scan for the drift check.
- **Fix:** `np.searchsorted(..., side='left')` → O(log N); share the resolved next-bar index between drift check and open.
- **Evidence:** `backtest_engine.py:871-875`, `731-736`.

### RC-13 — Sweep `sweep_run` executes combos strictly SERIALLY — **HIGH · (from diagnosis)**
- **What:** `_execute_sweep` awaits each `run_one` to completion before starting the next; the 3-thread executor sits 2/3 idle. The fast `run_sweep_pooled` ProcessPool path is **not wired** into the persisted `sweep_run` tool (only `optimize_config` uses it).
- **Fix:** Semaphore-bounded `asyncio.gather` (raise `_MAX_CONCURRENT` toward cpu_count for sweeps), or route `sweep_run` through `run_sweep_pooled`. Keep per-combo `write_result` idempotency for crash-resume.
- **Evidence:** `sweep_tools.py:68-84`; `backtest_service.py:50,103,1321-1326`.
- **Windows note:** `supports_process_pool()` returns False on win32, so on this dev machine **both** paths are serial today — the async-gather fix is the portable win.

### RC-14 — Pooled path re-pickles the ENTIRE snapshot per combo — **HIGH · (from diagnosis)**
- **What:** `run_sweep_pooled` passes `signals`, `snapshot`, `instrument_info` as positional args to `run_in_executor`, so the spawn-context ProcessPool pickles + IPC-copies the whole dataset **once per combo** (O(N × snapshot_size)).
- **Fix:** Ship the snapshot to workers ONCE via the ProcessPool `initializer` (module globals); `_run_combo` takes only `cfg` + deadline. Or shared memory (Arrow / `multiprocessing.shared_memory`).
- **Evidence:** `orchestrator.py:160-180`; `runner_pool.py:46-93`.

### RC-15 — Per-combo double DB writes (result + rank re-write pass) — **MEDIUM · (from diagnosis)**
- **What:** `write_result` does a 2-statement txn per combo; then `_execute_sweep` calls `write_result` AGAIN for every ranked result just to stamp `result_rank` → 2N writes, 4N statements.
- **Fix:** Stamp ranks in a single set-based `UPDATE ... FROM (VALUES ...)`. Keep first-pass per-combo write for crash-resumability.
- **Evidence:** `sweep_repo.py:114-145`; `sweep_tools.py:85-92`.

### RC-16 — Adaptive blacklist rescans all closed trades per signal — **MEDIUM · (from diagnosis)**
- **What:** `_is_adaptive_blacklisted` linearly scans ALL `closed_trades` for every candidate signal when enabled → O(signals × closed_trades), grows with history.
- **Fix:** Maintain an incremental per-symbol win/total counter, updated on every close.
- **Evidence:** `backtest_engine.py:1083-1113`, `657-663`.

### RC-17 — `_load_klines` loads the full date range for every symbol — **MEDIUM · (from diagnosis)**
- **What:** A symbol appearing in a single scan on day 3 of a 90-day backtest still pulls all 90 days (~25,920 5m candles). Useful span is `[first signal entry, last possible exit]`.
- **Fix:** Bound each symbol's load to `[min(signal_time) − lookback, max(signal_time) + max_hold_window]`. Shrinks rows transferred + resident memory with no engine-semantic change.
- **Evidence:** `backtest_service.py:964-977`, `1385-1411`.

### RC-18 — kline_cache monthly partitioning is marginal; DEFAULT partition unbounded — **LOW · (from diagnosis)**
- **What:** Monthly RANGE partitions (now ±6 months) + an unbounded `kline_cache_default`. The composite PK `(symbol, interval, open_time)` already serves the hot query; partition pruning only avoids other months but adds a mild multi-partition btree fan-out. Windows older than ±6 months land in the unpruned DEFAULT partition.
- **Fix:** Keep Postgres as system-of-record; move the **bulk OHLCV read** to a columnar layer (see §4). If staying on Postgres, add a rolling partition-maintenance job.
- **Evidence:** `async_persistence.py:616-658`; `kline_cache_service.py:320-346`.

---

## 3. The Cache Re-Download Bug — Exact Mechanism + Exact Fix

> **Important:** `backtest_engine.py` is pure (ZERO I/O — "all data injected"). It contains **no** re-download path. The bug lives entirely in `backtest_service.py` + `kline_cache_service.py`. The engine's "scan-from-start" loops (RC-1/RC-2) are an *in-memory CPU* anti-pattern, **not** a cache miss.

### 3.1 The three distinct re-download behaviors

**(A) 5m false-positive coverage gap → re-fetch forever (the headline bug).**
The exact causal chain, every link verified:

1. `ensure_coverage` is called unconditionally on every run before the Postgres read — no warmed-guard (`backtest_service.py:726-748`, the call at `741-745`).
2. `get_coverage_gaps` computes `per_day_full = max(1, 1440 // interval_min)` = **288** for 5m (`kline_cache_service.py:156`), and `_expected_for` returns 288 for any full interior day (`158-176`).
3. A day is flagged a gap when `sym_counts.get(d, 0) < _expected_for(d)` (`:192`). Selected columns are `symbol, date, candle_count` only — **`fetched_at` is never read** → no TTL.
4. Legitimately-short days (mid-day listing, halt/outage, still-forming current day) hold e.g. **144/288**.
5. Refetch returns the same 144 candles; `store_klines` is `ON CONFLICT DO NOTHING`; `_update_coverage` upserts `GREATEST(existing, new)` = `GREATEST(144,144) = 144` (`:313`).
6. → `144 < 288` stays a gap **on every subsequent run, permanently.**

**(B) Span collapse → the whole window re-downloads.**
`ensure_coverage` fetches a single span `[min(gap_days) .. max(gap_days)+1d]` clipped to the window (`:254-258`). A perpetual-gap **listing day near the start** + a **short/most-recent day near the end** make `min`/`max` bracket the **entire** range. Gap detection keys only on `(symbols, interval, start, end)` → **config-independent**: changing only a TP% still triggers the full re-download.
- **Pagination nuance (makes it worse):** `_fetch_klines_from_bybit` caps at `_MAX_PAGES(5) × _PAGE_SIZE(200) = 1000` candles/call. For spans > ~3.47 days (1000 × 5m), each run only re-pulls the most recent ~1000 candles of the span — so interior gaps beyond the tail **never fill and the cache never converges.**

**(C) 1m drill-down is never cached (intentional, but pays per run).**
`_build_fine_klines` calls `_kline_cache._fetch_klines_from_bybit` **directly** and deliberately does **not** `store_klines` (`backtest_service.py:990-994`, `1069`). Every run (and Phase B of every run) re-pulls all 1m drill-down candles over a contiguous `min(epochs)→max(epochs)` span, discarding ~98%.

### 3.2 The exact fix

Replace the count-based completeness check with a **time-coverage manifest + explicit `sealed` flag gated by a completion frontier**, plus **negative caching** of confirmed absences. (Mirrors Freqtrade's proven rule: only the live-edge candle is ever treated as incomplete; detect it by *timestamp*, never by count.)

1. **Completion frontier (per interval):** `frontier = floor(now / T) * T`. Any candle with `open_time < frontier` is CLOSED and immutable → fetch-once-ever. Compute the frontier **per `(symbol, interval)`** — a 4h day seals later than a 5m day.

2. **Per-day `sealed` manifest:** add a row per `(symbol, interval, day_utc)` recording `sealed BOOL, first_open_ts, last_open_ts, candle_count (FACT, never a gate), gap_count, listing_snapped, delisted, content_sha256, fetched_at`. Plus a `symbol_lifecycle(symbol, listing_time, delist_time)` table.

3. **Seal rule:** a day is sealed when `day.end <= frontier` AND its exchange response has been fetched. Once sealed it is **never re-evaluated** regardless of `candle_count`. This is what kills the "144/288 → refetch forever" bug.

4. **Count-free refetch predicate:**
   `need_fetch = (not sealed) AND day_overlaps([listing_time, delist_time]) AND day.end > last_covered`.
   `candle_count` **never** enters the decision.

5. **Negative caching (RFC 2308 analogy):** persist `listing_time`/`delist_time` and re-verified intra-day gaps as "known empty", sealed permanently, so pre-listing/post-delist/structural-gap ranges stop being fetched. Give wrongly-recorded transient gaps a TTL so they can heal.

6. **Fetch per contiguous gap-run, not one `min..max` span** — so one stale day can't drag the whole range (`kline_cache_service.py:254-258`). Combined with sealing, closed days never enter the gap set at all.

7. **Process-level memo:** wrap `_load_klines` in an LRU keyed by `(symbol, interval, start, end)` and gate `ensure_coverage` behind a "range already complete" manifest check, so an identical rerun does **zero** Bybit/Postgres work. Memoize **sealed days only** — never the unsealed tail day.

8. **1m drill-down (behavior C):** add a per-session in-process cache keyed by `(symbol, bar_open_epoch)`; fetch only narrow per-bar windows via bounded `asyncio.gather`. Keep it **in-memory only** (never `store_klines`) so it can't re-poison the 5m coverage table.

9. **One-time migration:** backfill `sealed = true` for every day whose `end < current frontier` and that lies within `[listing, delist]`, so existing short-but-complete days stop refetching immediately.

**Parity guarantee for the cache fix:** closed candles are immutable (fetch-once-ever); only `date >= today-1` (the forming candle) may be refreshed; `store_klines` stays idempotent (`ON CONFLICT DO NOTHING`); `_update_coverage` stays monotonic (`GREATEST`); partial-day clipping for boundary days is preserved; any in-memory memo yields byte-identical klines vs the Postgres read and is invalidated for the forming day.

---

## 4. Target Architecture

### 4.1 Storage layer — Postgres stays write-of-record; reads move to columnar + RAM

**Decision: keep PostgreSQL for ingest/coverage/reconciliation; serve the backtest READ path from immutable Parquet (or a single local DuckDB file) + an in-process Arrow/Polars cache.**

Why columnar wins for *this* workload (working set is tiny — see sizing below):
- Backtests want a few columns over a date range; row-store Postgres reads every column of every row and serializes per-row over asyncpg. Columnar gives **projection + predicate + partition pushdown**, reading only the relevant files/columns.
- Candles are **immutable once closed** — a perfect fit for append-only columnar files.
- "Never re-fetch + repeated reads" is exactly what OS page cache + an in-process cache drive to near-zero cost.
- Postgres' own docs: partitioning is worthwhile mainly once a table exceeds RAM — which this never will.

**Working-set sizing (arithmetic):** 5m = 288 candles/day → ×90 days = 25,920 rows/symbol → ×50 symbols ≈ **1.3M rows ≈ 50–100 MB uncompressed**, far less as Parquet/Arrow. **The entire working set fits in RAM.** This single fact drives the design: optimize for repeated in-memory reads, not big-data disk scans.

**Three-layer cache:**
1. **Durable (write-once, immutable):** Parquet hive layout `symbol=<SYM>/year=<Y>/month=<M>/part.parquet`, sorted by `open_time` within each file (row-group min/max stats prune date ranges). Partition by **symbol → month** (not day — per-day = ~4,500 tiny files). *Or* collapse into a **single local DuckDB file** for ACID + SQL + one-file lifecycle. Pick loose Parquet for portability; pick DuckDB for SQL/ACID/no small-file sprawl.
2. **Read engine:** **DuckDB** (`read_parquet`, best if you want SQL/joins across symbols) **or Polars** (`scan_parquet`, best if the backtest math is already vectorized DataFrame/numpy). Both pushdown columns/predicates/partitions.
3. **Hot in-process layer:** a dict cache `{(symbol, interval, date-range): Arrow/Polars frame}` — first sweep iteration loads from disk, every subsequent rerun slices from RAM zero-copy. For instant *separate-process* reruns, back it with **mmap'd Feather V2** (on-disk == in-memory Arrow IPC, no deserialization; mmap pages in lazily via OS page cache).

**Coverage manifest** (the §3.2 sealed manifest) tells the loader the cache is complete so it never calls the exchange during a backtest; only the gap (max-ts → frontier) is ever fetched.

**Expected read speedup:** ~1–2 orders of magnitude on cold bulk scans (columnar pushdown vs row scan + wire serialization), effectively **instant (RAM slice) on warm sweep reruns**.

### 4.2 Engine hot loop — keep the sequential loop, make it numba-fast over columnar SoA

**Decision: custom `@njit` sequential engine. NOT vectorbt `from_signals`. NOT a framework rewrite.**

Both the diagnosis and the `vectorbt-vs-numba` research converge here. A pure vectorbt-style (column-independent) rewrite is **infeasible for the general config** because the engine is a **cross-sectional, shared-capital portfolio simulation**:
- **Portfolio-level close rules** (EQUITY_DROP / EQUITY_DROP_SMART / close_on_profit / EQUITY_RISE) act on basket equity = `wallet + Σ uPnL` across the whole open book and flatten the basket on a threshold. You cannot compute any symbol's exit in isolation.
- **Stateful latches:** `smart_drawdown_fired` one-shot, `cycle_start_equity` zeroing (cycle termination), funding boundary `(date,hour)` dedupe, adaptive-blacklist-from-own-trades.
- **Path-dependent sizing:** `qty` sized off running wallet + cross-book available balance.
- **Cycle gating:** `skip_if_positions_open`, per-scan `max_trades`, per-scan re-anchor.

vectorbt vectorizes each asset independently and has no shared-equity/liquidation concept; `cash_sharing` executes all group orders at the same tick (not a true sequential cross-symbol capital walk). It also lacks leverage/liquidation/funding entirely in OSS. Forcing it collapses into `from_order_func`/`@njit` callbacks — at which point you're writing numba anyway, with a foreign abstraction to re-prove parity through.

**The recommended core:**
- At load, convert each symbol to **structure-of-arrays**: `{open_time: int64[], open/high/low/close/volume: float64[]}`.
- Precompute a **global sorted-unique timeline** and drive the sim with **per-symbol advancing index pointers that never reset** (merge-walk) — this is the single fix that removes RC-1's O(scans × N_total) setup and RC-2's quadratic seeding in one stroke. Mark-seed becomes the value at the current pointer (O(1)); "last close ≤ T" / "first open ≥ T" become `searchsorted` (O(log N)).
- `@njit` the inner per-candle kernel: liquidation→SL→TP precedence, uPnL, equity sum, MFE/MAE, funding, trailing/time checks — operating on the column arrays + a compact position struct-of-arrays (numpy structured/record array or jitclass).
- Hold positions in a numpy structured array; index open positions by symbol (`dict[str, list[Position]]`) so trailing/TP-SL/equity/time loops touch only relevant positions (fixes RC-9).
- Hoist all function-local imports to module top (fixes RC-10).
- Keep the `fine_klines` drill-down on a separate, non-JIT path so the default fast path stays JIT-clean.

**numba engineering rules** (from research): numpy arrays only (no list[dict]); one dtype per array; structured array / jitclass for the position struct (NEVER a python list of dicts — reflected/nested containers can't cross the nopython boundary); `cache=True` to amortize compile; warm the function once before timing (first-call JIT compile is 1–10s); develop the loop in pure Python on a tiny dataset first for correctness, then add `@njit` and assert identical results; reserve `parallel=True`/`prange` for the **OUTER sweep over configs**, never the inherently-sequential inner bar loop.

**Optional vectorized barrier-exit FAST-PATH** — gated strictly on config: only when `max_drawdown_pct >= 100` AND not `close_on_profit` AND `target_goal_type != 'profit_pct'` AND not `trailing_profit_pct` AND no breakeven mutation. In that subset positions are provably independent → each exit is an independent cumulative-min/max + argmax over its bar slice (vectorbt-style first-touch). Everything else routes to the sequential kernel.

### 4.3 In-memory dataset reuse across reruns and sweeps

- **Single rerun:** the §4.1 hot layer means an identical rerun re-slices the same Arrow frames from RAM; the §3.2 manifest gate means `ensure_coverage` does zero exchange/DB work.
- **Sweeps already load once** (`load_inputs` loads signals+klines+instrument ONCE; `run_one` replays each combo against that in-memory snapshot — `run_one` is DB-less by contract, workers carry no credentials). **This is the one path that reuses klines well** and must be preserved.
- **Pooled path:** ship the snapshot to ProcessPool workers **once** via the `initializer` (module globals) instead of per-combo positional args (fixes RC-14). For the OHLCV arrays specifically, `multiprocessing.shared_memory` / Arrow gives zero-copy sharing across workers.
- **Convert-once:** cache the *converted* numpy SoA arrays alongside the Parquet so repeated sweeps skip both re-fetch and re-parse. The columnar engine + the SoA cache pair naturally.

### 4.4 How sweeps share one preloaded dataset (concrete)

```
load_inputs()  ── once ──►  (signals, snapshot_SoA, instrument_info)
                                      │
                 ┌────────────────────┼─────────────────────┐
   ProcessPool initializer sets module globals from snapshot_SoA  (one IPC copy total,
                 │                    │                     │      or shared_memory: zero-copy)
              worker_1             worker_2              worker_3
   run_combo(cfg) reads globals   ...                    ...
   → returns metrics dict only (no DB; parent persists)
```

- Parent process keeps ALL persistence (crash-resumable per-combo `write_result` ON CONFLICT `(sweep_id, config_hash)`); workers return only a metrics dict.
- Rank stamping becomes one set-based `UPDATE ... FROM (VALUES ...)` (fixes RC-15).
- Live-trading protection retained: both sweep paths yield to the live-SLI breaker (`_await_breaker_clear`).

---

## 5. Multi-Timeframe Drill-Down Verdict

**Question:** does "simulate on the big bar, drill into smaller candles only on big-bar events" work — is it faster, and does it risk accuracy (intrabar TP/SL ordering)?

**Verdict: YES, the idea works, is sound, and is a *smarter* version of TradingView's Bar Magnifier — fast AND accurate, IF the drill trigger is implemented correctly.** This is also exactly how the engine already gates drill-down today (`drilldown_enabled` + `simulation_interval`), so the recommendation hardens an existing design rather than replacing it.

### 5.1 Why it is correct (the conservative-bound guarantee)
An aggregated big bar satisfies `bigHigh = max(subHighs)` and `bigLow = min(subLows)`. Therefore **if the big bar's `[low, high]` range touches neither TP nor SL, no sub-bar inside it touched either level** — skip the drill and mark-to-market at the big bar's close with **zero accuracy loss**. This is provable, not heuristic, and covers ~80–95% of bars for typical TP/SL widths — that's where the speedup comes from. (Coarse-and-fine data must come from the same aggregation source so the max/min invariant holds exactly — true for Bybit/Binance aggregated klines.)

### 5.2 When drill-down is required vs avoidable
1. **AVOIDABLE (skip, exact):** big bar range touches neither TP nor SL and no pending entry sits inside it. No fill possible → carry, no drill.
2. **AVOIDABLE-but-precision-only:** big bar touches exactly ONE decision level. The outcome is already known (that level filled). You only need a drill for the exact intrabar fill *price* — and for stop/limit/TP/SL the fill price IS the order price (modulo slippage/gaps), so usually fill-at-level without drilling.
3. **MANDATORY (must drill):** the big bar contains **BOTH TP and SL** inside its range. Coarse OHLC cannot resolve which was hit first; the default open→high→low→close heuristic is a near-coin-flip and **biases results optimistically** (it can "choose" the favorable fill). You MUST drill to LTF sub-bars and replay them **in chronological order** to see which level was reached first. Same applies if an entry AND its stop both sit inside one bar.

### 5.3 Does it actually speed things up? (honest)
Yes, but **strategy-dependent.** With `p` = fraction of bars touching a level and `k` = sub-bars per big bar, work goes from `N·k` (always-drill) to `~N·(1 + p·k)`. For `p=0.10, k=12` that's ~5× fewer sub-bar ops **plus** you avoid loading most LTF candles (lazy load). **Caveat:** for very tight stops / scalping where `p → 1` you drill almost every bar and save little — the coarse pre-filter degenerates.

**The bigger, unconditional win for this scan-driven design is LAZY PER-SYMBOL LTF LOADING:** only fetch 1m candles for the handful of symbols that actually got a signal+position in a scan, never for the whole scanned universe. This is always safe and likely **dominates** the per-bar optimization. (It also directly fixes RC-7's over-fetch.)

### 5.4 Accuracy pitfalls to handle
- **Same-source aggregation** so `bigHigh == max(subHighs)` holds — satisfied by Bybit klines.
- **Recursion of ambiguity:** even after drilling to 5m/1m, if BOTH TP and SL still sit inside one sub-bar, order is again ambiguous. Mitigate by (i) choosing a drill TF fine enough that double-touch is rare, and (ii) a **conservative tie-break: assume SL fills first (worst case)** on residual ambiguity. This removes optimistic bias and keeps you on the safe side of the <1% target — *more* conservative than TradingView.
- **Bound the drill range** (TradingView caps LTF at 200,000 bars).
- **Stops fill at stop price or worse** (gaps/slippage) — model on the drill path.

### 5.5 Recommended hybrid (the design to build)
Three tiers, mapping 1:1 onto existing `simulation_interval` (coarse) + `drilldown_enabled` (toggle):
1. **Coarse pass** on `simulation_interval` bars; for each open position/pending order, test whether `[low, high]` touches TP, SL, or entry — **using High/Low, never close**.
2. Touches **nothing** → skip (exact). Touches exactly **one** level → fill at that level (drill only for market-on-touch realism).
3. **Both TP and SL inside one bar** → drill is MANDATORY: lazy-load **cached** LTF sub-bars for that bar only, replay open→…→close in time order, fill the first level reached; **conservative SL-first tie-break** on residual same-sub-bar ambiguity.
4. **Separately + unconditionally:** lazy-load LTF candles **only for symbols that traded in a scan** (per-symbol, per-bar), via the in-process 1m cache (§3.2 step 8) — never bulk, never the whole universe.

**Parity invariants the drill-down must preserve** (already in the engine — do NOT regress):
- Equity rules value uPnL off the **stable un-drilled 5m reference** (`equity_ref_entry`), so toggling drill-down NEVER changes which threshold fires → **identical trade selection** with or without drill-down.
- 1m **entry** drill-down is **price-only** (refines `entry_base_price`); the entry-bar lifecycle stays 5m; `equity_ref_base` preserved as the un-drilled 5m fill.
- Drill stays **fail-soft**: a symbol/window that returns no 1m candles falls back to 5m bar logic — never fabricate a fill.
- 1m equity fine-walk requires **full-book coverage** (every open symbol has a 1m window for the bar) else fall back to 5m.

**Validation:** before trusting the fast path, run an **always-LTF replay** on a sample window and diff trade-by-trade vs the conditional-drill engine to confirm <1% deviation.

---

## 6. New Libraries to Introduce

| Library | License | Role | Why |
|---|---|---|---|
| **numba** | BSD 2-Clause (free, OSS) | JIT the per-candle kernel + `prange` outer sweep | Only option that expresses ALL path-dependent rules natively while hitting seconds-to-minutes. Documented ~300× over pandas on a *structurally identical* path-dependent backtest; one-to-two orders of magnitude per numba's own docs. No license cost, no lock-in. |
| **numpy** | BSD-3-Clause (free, OSS) | Structure-of-arrays columns (int64 epoch + float64 OHLC), `searchsorted`, structured/record arrays for the position struct | Foundation for SoA layout, binary-search window location, and JIT-compatible data. Almost certainly already a transitive dep. |
| **pyarrow** | Apache-2.0 (free, OSS) | In-process hot cache + mmap'd Feather V2 | Zero-copy in-memory columnar standard; mmap reads ride the OS page cache for near-instant warm reruns; Feather V2 == Arrow IPC on disk (no deserialization tax). |
| **DuckDB** *(or Polars)* | MIT (free, OSS) | Columnar read engine over Parquet / single-file DB | Projection+predicate+partition pushdown; ~45ms date-filter vs 7.5s naive pandas; aggregates derived timeframes (`time_bucket`) in ms over the 1.3M-row set. Pick DuckDB for SQL/ACID/one-file; pick **Polars** (MIT) instead if the backtest core is already vectorized DataFrame/numpy. |
| **Parquet** (via pyarrow/duckdb) | Apache-2.0 (free, OSS) | Durable immutable on-disk OHLCV store | Columnar, compressed (3–5× smaller than rows), write-once — perfect fit for immutable closed candles. |

**Explicitly NOT adopting** (with reasons): **vectorbt OSS** (Apache-2.0 + Commons Clause; no leverage/liquidation/funding; path-dependent exits don't map) — but keep its columnar/numba *patterns* as reference and optionally use it downstream purely for metrics/plots fed by our trade records. **vectorbtpro** (commercial; still hand-write liquidation/funding as `@njit` callbacks → you're writing numba anyway). **backtesting.py** (AGPL-3.0 copyleft; single-instrument only — hard blocker). **bt** (daily rebalance paradigm, no intraday/leverage/futures). **zipline-reloaded** (US-equities only). **nautilus_trader** (LGPL-3.0; best research→live parity story and native Bybit perps + funding, BUT doesn't fully model liquidation, heavy event-driven engine, wants to own the whole stack) — **keep on the radar as an independent cross-validation oracle later, not a core replacement now.**

**Bulk data source (optional, for cold cache warming):** `https://public.bybit.com` — daily trade-tick dumps (`trading/{SYMBOL}/...csv.gz`, history from 2020-03-25) resampled locally to all timeframes in one pass; ~23 majors have pre-aggregated OHLC at `kline_for_metatrader4/`. **Zero-risk independent win:** the REST `/v5/market/kline` `limit` is `[1,1000]` (default 200) — bumping page size 200→1000 cuts incremental gap-fill request counts **5×** regardless of any other change.

---

## 7. Parity Guarantees — Invariants + Test Strategy

The refactor changes **how prices are located (searchsorted/pointers) and stored (columns)** — it must NOT change **which decisions are made**. The following invariants must stay **bit-for-bit identical**.

### 7.1 Invariants that must stay byte-identical
**Fill & sizing**
- Next-bar-open fill, no look-ahead: entry fills at the OPEN of the first candle whose `open_time >= current_time`; if none, `signals_no_kline++` and SKIP (never fabricate from stale close). `searchsorted(side='left')` must reproduce the exact `>=` boundary.
- Position sizing `qty = (sizing_capital · capital_pct/100 · leverage) / entry_base_price` (un-slipped mark), floor to `qty_step`, reject `< min_qty`, reject if margin > available_balance. **Path-dependent** (sizing_capital from running wallet + carried uPnL − Σ locked_margin, marked to last close ≤ current_time).

**Exit precedence & ordering (the parity-critical core)**
- Intrabar exit precedence **liquidation → SL → TP**, pessimistic: **SL wins** when SL and TP both hit in one bar; SL-wins-if-closer-than-liq; `>0` guards prevent fabricated ~100% PnL.
- Rule-evaluation ORDER within a candle is fixed: **funding (8h boundary) → per-position liq/TP/SL → equity rules → trailing profit → time rules.** Reordering changes which rule closes first → different PnL.
- Equity-rule precedence within a tick: **EQUITY_DROP(/SMART) → close_on_profit → EQUITY_RISE**, each with early return on cycle termination.
- 1m exit drill-down ONLY when ≥2 of {liq, sl, tp} fall in the 5m bar; walk 1m in order, return FIRST touched (pessimistic liq→sl→tp per 1m candle). Single-level bars exact at 5m.

**Portfolio-equity rules (the non-vectorizable core)**
- Equity rules value uPnL off the **stable `equity_ref_entry`** (un-drilled 5m fill), NOT the drilled entry → drill-down never changes selection.
- Intrabar-aware drawdown: each position valued at its OWN bar adverse extreme (high for shorts, low for longs); fire on `min(close_equity, intrabar_equity)`; exit at the adverse extreme on intrabar breach.
- EQUITY_DROP_PCT_SMART is **one-shot per scan** (`smart_drawdown_fired`), closes only intrabar-losing positions; conditional re-anchor; flag reset each non-skipped scan.
- Non-smart equity rules **zero `cycle_start_equity`** to terminate the cycle; re-anchored per non-skipped scan to `totalAvailableBalance`.

**Latches & accounting**
- Funding charged exactly once per 0/8/16h boundary via `(date, hour)` key regardless of granularity; longs pay, shorts receive.
- TRAILING_PROFIT state machine: clear peak when uPnL≤0; below activation continue WITHOUT triggering (preserve peak); peak from bar high(Buy)/low(Sell); trigger when `per_unit < peak×0.5`.
- Time rules order: MR `time_stop_minutes` → MAX_DURATION → BREAKEVEN_TIMEOUT (mutates TP to breakeven, skipped while trailing active).
- Wallet model: locked margin NEVER deducted at open (only entry fee); normal close adds `wallet_delta`; liquidation deducts locked_margin (separate branch, no exit slippage/fee).
- **Reconciliation invariant:** recorded `trade.pnl = pnl − exit_fee − entry_fee − funding_paid` (TradingView Net Profit) so **`Σ trade.pnl == final_equity − starting_capital`.**
- MFE/MAE updated every bar from that bar's high/low before exit checks.
- Force-close remaining positions at backtest end at each symbol's last close (reason `backtest_end`); equity-curve point on every close; terminal point matches `wallet_balance`.

**Admission gating**
- `skip_if_positions_open`: skip the scan's signals but STILL evaluate close rules; preserve the existing anchor (only preservation case).
- `max_trades` per-scan (`scan_entered`); `signals_entered` lifetime for `target_goal`; existing-symbol dedup; `abs(score)` ranking; 17-step filter chain order.
- **Known intentional divergence — DO NOT "fix":** `max_same_sector` is NOT enforced in the engine (live DOES enforce it); the service surfaces a `max_same_sector_not_enforced` warning.

**The golden no-op guarantee**
- The engine is **byte-identical to the 5m-only path** when `instrument_info`/`scan_contexts`/`fine_klines` are empty AND no regime feature is active — all drill/regime/instrument code short-circuits. The refactor MUST preserve this (gate all refinements behind presence-of-data checks exactly as today).

### 7.2 Test strategy — golden-master diff vs the current engine
1. **Freeze a golden-master oracle FIRST.** Before touching the engine, capture the *current* engine's full output (every trade: entry/exit time+price+qty+fees+funding+pnl+reason, the full equity curve, drawdown series, and all summary metrics) for a battery of fixtures. Serialize to disk as the immutable reference.
2. **Fixture battery** covering every parity-sensitive branch: default 5m-only no-drill/no-regime (the canonical golden path); drill-down (both-levels-in-one-bar); MR time-stop; EQUITY_DROP_PCT_SMART one-shot; non-smart EQUITY_DROP cycle termination; close_on_profit; EQUITY_RISE; TRAILING_PROFIT activation+retracement; funding boundary; BREAKEVEN_TIMEOUT TP mutation; `skip_if_positions_open`; adaptive blacklist; batch vs immediate mode; `fill_to_max_trades`; force-close at end.
3. **Bit-identical assertion on the canonical path:** the optimized engine must produce **byte-identical** trades + equity_curve to the oracle on the 5m-only no-drill config. This is the strongest, cheapest guard — run it in CI.
4. **<1% deviation assertion on drill/portfolio paths:** for the richer configs, assert per-trade and summary-metric deviation < 1% (allowing only the documented candle-resolution fidelity caveat). The conservative SL-first tie-break may legitimately make the new path *slightly* more pessimistic — assert deviation is within tolerance AND non-optimistic.
5. **Reconciliation test on every fixture:** assert `Σ recorded trade.pnl == final_equity − starting_capital` (catches any fee/funding/wallet drift).
6. **Develop-in-pure-Python-first discipline (numba):** implement each kernel in plain Python, assert it matches the oracle on a tiny dataset, THEN add `@njit` and assert identical results — isolates JIT bugs from logic bugs.
7. **Cache-fix parity:** assert the manifest/sealed loader returns **byte-identical klines** to the current Postgres read for any sealed range; assert a sealed closed day is fetched **exactly once** (mock the Bybit client, count calls across N reruns == 1); assert the forming day is still refreshed.

---

## 8. Phased Rollout (lowest-risk path to "minutes" first)

Ordered by **ROI ÷ risk**. Each phase is independently shippable and gated by the golden-master suite.

### Phase 0 — Golden-master harness (PREREQUISITE, do before any optimization)
Freeze the current engine's output as the immutable oracle; build the fixture battery (§7.2). **No behavior change.** Nothing downstream is trusted without this. **Risk: none.**

### Phase 1 — Stop the re-download (biggest correctness+latency win, lowest risk)
The cache fix (§3.2): sealed manifest + completion frontier + count-free refetch predicate + negative caching + per-contiguous-gap fetch + process-level LRU on `_load_klines` + 1m drill-down in-process cache. Bump REST `limit` 200→1000. **This alone turns "re-downloads everything every rerun" into "fetch once, ever."** Pure I/O/coverage logic — does not touch engine semantics, so parity risk is confined to the cache-parity tests (§7.2 step 7). **Risk: low.**

### Phase 2 — Quick-win loaders + sweep parallelism (no engine-semantic change)
- Batch `_load_klines` into one `ANY($1)` query (RC-6); batch MR mean-series (RC-16-adjacent).
- Hand `ensure_coverage`'s fetched candles to the engine instead of re-reading from Postgres (RC-5).
- Parallelize 1m drill-down fetches with bounded `asyncio.gather`; fetch only narrow per-bar windows (RC-7).
- Skip Phase A for configs with no portfolio-equity close rules (RC-8).
- Sweep: semaphore-bounded `asyncio.gather` (RC-13); set-based rank UPDATE (RC-15); ProcessPool `initializer` for the snapshot (RC-14).
- Bound per-symbol load to signal span + max-hold (RC-17).
**All semantics-preserving rearrangements** verified by the golden suite. **Risk: low.**

### Phase 3 — Columnar SoA engine layout (the dominant engine win)
Convert klines to per-symbol structure-of-arrays (int64 epoch + float64 OHLC) at load; replace the per-scan window rebuild (RC-1) and quadratic mark-seeding (RC-2) with `searchsorted` / merge-walk pointers; replace per-signal linear scans (RC-12); collapse equity passes (RC-10); index positions by symbol (RC-9); hoist imports (RC-10). **Engine still pure Python here** — assert bit-identical to the oracle at every step. This removes the O(scans × N_total) setup and the quadratic term — the single biggest engine speedup, *before* any JIT. **Risk: medium** (touches hot-path code; fully covered by golden diff).

### Phase 4 — `@njit` the per-candle kernel (turns seconds into milliseconds)
Move the inner kernel (liq/SL/TP precedence, uPnL, equity sum, MFE/MAE, funding, trailing/time) onto the SoA arrays under `@njit(cache=True)`, with a numpy structured-array position struct. Develop pure-Python-first, assert oracle-identical, then JIT. Keep the `fine_klines` drill-down on a separate non-JIT path. **Risk: medium-high** (numba constraints, type inference) — mitigated by the develop-in-Python-first discipline and bit-identical assertions.

### Phase 5 — Columnar storage read layer (Parquet/DuckDB + Arrow hot cache)
Move the bulk OHLCV READ off Postgres onto immutable Parquet (or single DuckDB file) + in-process Arrow/Polars cache + mmap'd Feather for cross-process reruns. Postgres stays write-of-record. Derive coarse timeframes from the sealed fine base via `time_bucket`/`group_by_dynamic` (store ONE base granularity, not per-TF). **Risk: medium** (new storage path; gated by byte-identical klines test).

### Phase 6 — Optional vectorized barrier fast-path + outer-loop `prange` sweeps
For the narrow independent-position config subset (§4.2), add the vectorized first-touch exit. Parallelize the OUTER sweep over configs with `prange`/ProcessPool (embarrassingly parallel; scales with cores). **Risk: medium** (correctness of the fast-path gate) — route anything ambiguous to the sequential kernel; validate against it.

### Phase 7 — (Optional, later) nautilus_trader cross-validation oracle
Stand up nautilus_trader independently as a second opinion to sanity-check the numba engine on a sample. **Not on the critical path.**

---

## 9. Expected Speedups (order-of-magnitude estimates)

| Change | Mechanism | Expected gain | Confidence |
|---|---|---|---|
| **Cache fix (Phase 1)** | Eliminates whole-history re-download every rerun; warm rerun does ~0 exchange/DB work | Re-download time → **~0** on warm reruns; cold warm bounded to true gaps. Removes the dominant *wall-clock* cost of reruns/sweeps | High |
| REST `limit` 200→1000 | 5× fewer paginated requests on gap-fills | **~5×** on incremental fetches | High (Bybit-documented) |
| Batch `_load_klines` (N+1 → 1 query) | Removes S−1 serial RTTs before engine start | Seconds → tens of ms of load latency; **~S×** on the load step | High |
| Parallelize/narrow 1m drill-down | Bounded gather + per-bar windows + in-process cache; stop discarding ~98% | **Several× to ~50×** on the drill-fetch step (over-fetch ratio); ~0 on rerun | Medium-High |
| Skip Phase A (no-equity configs) | Halves engine passes on those configs | **~2×** engine wall-time on that subset | High |
| **SoA + searchsorted/merge-walk (Phase 3)** | Kills O(scans × N_total) setup + quadratic seeding; O(log N)/O(1) lookups | **~10–100×** on the engine core (scales with backtest length × scans) — the single biggest engine win | High (asymptotic, verified) |
| **`@njit` kernel (Phase 4)** | Removes interpreter overhead on the per-candle math | **~10–100×** on the inner loop (numba docs: 1–2 orders of magnitude; ~300× cited on a path-dependent backtest) | Medium-High |
| Columnar read cache (Phase 5) | Columnar pushdown vs row scan + wire serialization; RAM slice on warm | **~1–2 orders of magnitude** cold; **~instant** warm | High (DuckDB-benchmarked) |
| Sweep parallelism (Phases 2+6) | Serial → cpu_count-wide; snapshot shipped once | **~`min(cpu_count, combos)`×** on sweeps; removes O(N×snapshot) pickling | High |

**Net:** Phase 1 alone fixes the "re-downloads every rerun" complaint and removes the biggest wall-clock cost. Phases 2–4 take a multi-hour engine run to **seconds-to-minutes**. Phases 5–6 make sweeps and warm reruns **near-instant**. The combined engine speedup is realistically **≈100–1000×** on long, scan-heavy backtests, with parity defended bit-for-bit by the golden-master suite at every step.

### Honest risks & open questions
- **Magnitudes are estimates, not profiled.** The ~300× and "1–2 orders of magnitude" figures come from analogous public benchmarks; actual numbers depend on backtest length, scan count, and concurrent-position count. Profile after Phase 3 to re-target Phase 4.
- **numba debugging is harder** (no pdb in nopython, first-call compile 1–10s). The pure-Python-first discipline is mandatory, not optional.
- **The "dominate" claims (RC-1/-2) are asymptotic + iteration-count-based, not profiled** — but the avoidability and the asymptotic improvement are verified-certain, so Phase 3 is safe to prioritize regardless.
- **Open question (decides Phase effort split):** how tight are typical stops in the scanned strategies? If `p → 1` (very tight stops), the per-bar drill pre-filter saves little and lazy per-symbol LTF loading is the dominant drill win; if moderate/wide, the conditional drill itself is a large win.

---

*End of findings. Build order: Phase 0 (golden harness) → Phase 1 (cache fix) → Phase 2 (loaders/sweep) → Phase 3 (SoA) → Phase 4 (njit) → Phase 5 (columnar storage) → Phase 6 (fast-path/prange). Never trust a phase without its golden-master diff.*
