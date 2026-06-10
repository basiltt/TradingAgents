# Consolidated Requirements — Cache (REQ-CACHE)

**Category:** Cache
**Prefix:** CACHE
**Source slice:** 158 raw `category=="Cache"` items (incl. tags CACHE/NEGCACHE/LRU/PARITY/FRONTIER/SEAL/TTL/LISTING/GAPRUN/GUARD/SSOT/CONCURRENCY/COMPAT/LIVE-EDGE/LIFECYCLE/PERF)
**Consolidated to:** 44 requirements (merged 114 near-duplicates)
**Grounding:** specs/backtest-optimization-findings.md (RC-3 perpetual-gap, RC-4 span-collapse, RC-6 N+1 loader, RC-17 full-range load), specs/backtest-optimization-discovery.md

Phase legend: **P0** golden-master · **P1** cache · **P2** loaders/sweep · **P3** SoA engine · **P5** Parquet/DuckDB · **cross** spans phases.
The lone `category=="Parity"` item is owned by the Parity-Correctness agent and is intentionally NOT folded here.

---

## A. Headline behavioral contracts (warm / cold)

### REQ-CACHE-001 — Warm identical rerun does zero data work (must, P1)
A warm identical rerun (same config, same process session) MUST complete in < 2 s and issue **0 Bybit HTTP calls, 0 kline-table SELECTs, and 0 Postgres writes** (0 `store_klines`, 0 manifest seal upserts, 0 `GREATEST` coverage upserts) — served entirely from the process LRU / sealed manifest. Verified by separate read-counter and write-counter assertions on a fully-sealed config.
_Merged: 000, 022, 099. Rationale: directly tests the headline "re-downloads every rerun" fix (RC-3/4/5)._

### REQ-CACHE-002 — Cold run is network-bound, not history-bound (must, P1)
A cold run (empty cache) MUST bound Bybit kline requests to ≤ `ceil(true_missing_candles / 1000)` and MUST never re-fetch a sealed day; total cold wall-time scales with genuinely-missing candles, not total history.
_Merged: 001. Rationale: fixes RC-4 span-collapse (whole-history re-download) + RC-3 perpetual-gap with the 1000-page bump._

### REQ-CACHE-003 — Cold-vs-warm byte-identical results (must, cross)
A COLD run and a subsequent WARM run of the same config MUST produce byte-identical trades, ordered `equity_curve`, and ALL metrics — proving the cache changes WHERE data comes from, never WHAT the engine decides. This holds across cold→warm, LRU-served, and columnar-served reads.
_Merged: 049, 353 (+ drill analog 116). Rationale: the parity contract the golden-master suite enforces at every step; guards the `metrics.total_trades` trap._

### REQ-CACHE-004 — Param-tweak and symbol-delta reruns stay warm on data (must, P1)
Because the kline/data cache key EXCLUDES strategy params, a "tweak a param and rerun" over the same (symbols, interval, window) MUST issue 0 Bybit calls and 0 kline SELECTs (only the engine re-runs); and a rerun that ADDS/REMOVES symbols MUST load only the delta symbols, serving every unchanged symbol from the warm cache (0 data I/O for them).
_Merged: 075, 504, 097. Rationale: the common iterate-on-config workflow must not re-pay data cost._

---

## B. Completion frontier & sealing core semantics

### REQ-CACHE-005 — Per-(symbol,interval) frontier, recomputed each run, stable within a run (must, P1)
The completion frontier MUST be `floor(now_utc / T) * T` computed **per (symbol, interval)** (4h seals later than 5m for the same wall-clock day); any candle with `open_time < frontier` is CLOSED/immutable. It MUST be recomputed at read time on every run (a forming day auto-seals on a later run with no manual reseal) yet held STABLE for all seal/forming/clip/lazy-seal decisions within a single run (a mid-run UTC-midnight rollover cannot flip a day's class). Boundary is exact: `open_time == frontier−T` is sealed, `open_time == frontier` is forming.
_Merged: 008, 009, 047, 089/424. Rationale: §3.2(1); per-(sym,interval) frontier is the basis of fetch-once-ever; within-run stability prevents internally-inconsistent results._

### REQ-CACHE-006 — Frontier clock safety: skew lag, monotonic ratchet, single clock source (should, P1)
The frontier MUST apply an explicit safety lag (`floor((now_utc − skew_margin)/T)*T`) so a fast/skewed host clock never prematurely seals the forming day; sealing MUST be a monotonic ratchet (a backward clock step — NTP/VM/manual — never un-seals a sealed day); and `now_utc` MUST derive from a single coordinated authoritative source (e.g. Postgres `NOW()` / NTP reference) so multiple instances agree on the boundary day's class.
_Merged: 040/249, 055/390, 120/922. Rationale: protects the live-edge candle and guarantees cross-instance seal agreement._

### REQ-CACHE-007 — Seal only after a post-frontier success confirms terminal candles (must, P1)
A day MUST be sealed **iff** `day.end <= frontier` AND a fetch performed at/after that frontier returned a SUCCESSFUL (HTTP-200, non-throttled) response confirming its terminal candle (`last_open_ts == day_end − T`, or the listing/structural-gap exception). A pre-frontier fetch, or any failed/partial/timeout/429 response, MUST NOT seal the day (leave unsealed for retry, store partial rows idempotently, bounded backoff, actionable symbol+range error).
_Merged: 011(partial), 038, 056/391, 758. Rationale: prevents freezing a still-forming or partially-fetched day as immutable._

### REQ-CACHE-008 — Count-free refetch predicate (kills the 144/288 loop) (must, P1)
The refetch decision MUST be exactly `need_fetch = (not sealed) AND day_overlaps([listing_time, delist_time]) AND day.end > last_covered`, with **no candle-count term**; the live edge is detected by timestamp only. A legitimately-short sealed day (e.g. a 144/288 listing/halt day) MUST never be refetched, while the forming/current day (date ≥ today−1) IS still refreshed.
_Merged: 012, 015, 027, 028, 011(predicate). Rationale: RC-3 root cause — `candle_count < 288` must never enter the fetch decision._

---

## C. Sealed manifest: schema, gate, source-of-truth, compatibility

### REQ-CACHE-009 — Per-day manifest schema (must, P1)
A per-day manifest row keyed `(symbol, interval, day_utc)` MUST persist: `sealed BOOL, first_open_ts, last_open_ts, candle_count, gap_count, listing_snapped, delisted, content_sha256, fetched_at`. Once a row is sealed it MUST never be re-evaluated or refetched regardless of `candle_count`.
_Merged: 010, 011(immutability). Rationale: the durable structure that replaces the false-positive coverage detector._

### REQ-CACHE-010 — Manifest is the single source of truth + index-backed complete-range gate (must, P1)
`ensure_coverage` MUST be gated behind a manifest "range already complete" check that consults the manifest (never a live `COUNT(*)`); a fully-sealed requested range MUST perform 0 exchange calls and 0 coverage scans. Seal-state for ALL requested symbols MUST resolve in **1 batched** `WHERE symbol = ANY($1) AND interval=$2 AND day_utc BETWEEN …` query (bucketed in Python), index-backed so latency is O(range days) and independent of total manifest size.
_Merged: 020, 021, 068, 076. Rationale: SSOT + O(1)-query gate; the seal-check must not reintroduce the O(N) fan-out the kline `ANY($1)` loader eliminated._

### REQ-CACHE-011 — Single batched kline loader, bounded read concurrency (must, P1)
`_load_klines` MUST issue exactly **1 Postgres query per interval** for all symbols via `WHERE symbol = ANY($1)` (bucketed in Python), independent of symbol count (`assert query_count == 1` for an N-symbol load).
_Merged: 002. Rationale: RC-6 — current N+1 serial per-symbol round-trips block the event loop before the engine starts and recur inside every sweep `load_inputs`._

### REQ-CACHE-012 — Manifest ↔ legacy coverage consistency + NULL-sealed (v58) compatibility (must, cross)
The per-day manifest and the legacy `GREATEST`-monotonic coverage high-water-mark (`_update_coverage`/`last_covered`) MUST stay mutually consistent (no day `sealed=true` while the HWM reports it uncovered; both classify any range identically). A `kline_cache_coverage` row whose v58 `sealed` column IS NULL (written by old code in the DDL→backfill window, or after a rollback to legacy code) MUST be treated as UNSEALED/refetchable — never `sealed=true`, never an error.
_Merged: 065, 123. Rationale: keeps both coverage mechanisms live and asserts they agree; v58 migration safety on rolling deploy/rollback._

### REQ-CACHE-013 — Lazy-seal existing closed-day rows without refetch (must, P1)
A CLOSED day (`day.end < frontier`, within `[listing,delist]`) that already has `kline_cache` rows but carries NO manifest seal (`sealed IS NULL`) MUST be LAZILY SEALED from the existing Postgres rows with **0 Bybit refetch** (the runtime equivalent of the v58 backfill), so a missing manifest row can never force re-downloading data already present in Postgres.
_Merged: 082. Rationale: bridges the DDL→backfill gap and manifest-write-failure recovery without re-paying network cost._

### REQ-CACHE-014 — Batched, tier-durable, idempotent seal/gap-range writes (should, P1)
Runtime sealing of newly-closed days MUST batch manifest seal upserts into O(1) (or O(symbols)) round-trips (single `executemany`/`INSERT…ON CONFLICT` over all `(symbol,interval,day)` tuples), and a day MUST enter the batch only after its rows are durably stored in ALL required tiers. Both seal-row writes and known-empty/gap-range writes MUST be race-safe idempotent upserts (`ON CONFLICT`) so ≥3 concurrent writers under `_MAX_CONCURRENT` converge to one consistent row.
_Merged: 081, 090, 041/252, 150. Rationale: a cold 90d×50sym run issues ~4,500 day-seals — must not be one round-trip per day; concurrent sweep combos must not corrupt the manifest._

---

## D. Gap-run fetching, pagination, ingest hygiene

### REQ-CACHE-015 — Page size 200→1000 (must, P1)
REST page size MUST be raised 200→1000 (Bybit-documented cap) so gap-fill request count for a fixed missing span is ~5× lower (assert request-count ratio ≈ 5×) and per-call coverage widens so spans >3.47 days stop truncating to the most-recent 1000.
_Merged: 004. Rationale: RC bump; fewer round-trips and avoids pagination truncation._

### REQ-CACHE-016 — One request span per contiguous gap-run, paginated to FULL coverage (must, P1)
The fetcher MUST issue one request span **per contiguous gap-run**, never a single `min(gap_days)..max(gap_days)` span (so one stale interior day cannot drag the whole window into re-download). Within each gap-run it MUST paginate to FULL coverage in a single `ensure_coverage` invocation — the `_MAX_PAGES=5` cap MUST be raised/removed or the loop MUST continue until `last_fetched_open_time >= gap_run_end` — so a span larger than `_MAX_PAGES×page_size` does not leave interior candles perpetually missing.
_Merged: 019, 029, 072, 501. Rationale: RC-4 span-collapse + the `_MAX_PAGES` truncation that fills only the recent ~1000 tail._

### REQ-CACHE-017 — Boundary-exact, ascending, dedup, seam-invariant pagination + deterministic seal (must, P1)
The ingest path MUST normalize Bybit v5 newest-first (descending) pages to strictly-ascending order before `store_klines` and before `content_sha256`; the page-cursor loop MUST walk descending pages and stitch seams so each interval-grid slot is fetched **exactly once** (no drop, no duplicate across page seams or adjacent gap-run spans), honoring Bybit inclusive/exclusive endpoint semantics. `content_sha256` MUST be invariant to seam placement, and two independent cold runs over the same range MUST seal an identical set of `(symbol,interval,day)` with identical day-class and sha.
_Merged: 088, 131, 144/965. Rationale: correctness of the merge-walk store + deterministic sealed bytes across processes/fetch-orderings._

### REQ-CACHE-018 — Clip ingested candles to the in-life window; overwrite stale forming rows before seal (must, P1)
Before `store_klines`/`content_sha256`, returned candles MUST be CLIPPED to the requested in-life window — discard rows with `open_time <` requested start, `open_time >= frontier` (forming), or outside confirmed `[listing,delist]` — so an over-returning page can't inflate a sealed day, leak a forming candle, or seal an adjacent day's candles. Before sealing, any pre-existing stale forming row (e.g. left by a legacy instance lacking the forming-clip, under `store_klines ON CONFLICT DO NOTHING`) MUST be overwritten so DO-NOTHING staleness is never frozen into an immutable sealed day.
_Merged: 149, 129/435. Rationale: keeps the canonical sha clean and prevents stale-forming poisoning of sealed days._

### REQ-CACHE-019 — Day-granular partial-failure sealing + cancel/120s deadline between pages (must, cross)
A multi-day gap-run that FAILS partway MUST seal (day-granular, count-free, post-frontier-confirmed) every fully-covered closed day already stored, leaving only the unfetched remainder unsealed (a retry fetches just the remainder). The pagination loop MUST check the cooperative cancel (`threading.Event`) and the **120s** run deadline BETWEEN pages, aborting cleanly — persisting fetched candles idempotently, sealing completed days, leaving the rest retryable — rather than running the full multi-page fetch past the cap.
_Merged: 110/789, 119. Rationale: a flaky exchange must not re-download sealed-capable history; honors the 120s cap mid-fetch._

---

## E. Bounded loads, symbol set, auxiliary & derived series

### REQ-CACHE-020 — Bounded per-symbol span covering every lookback, snapped to whole days, parity-proven (must, P1)
Each symbol's kline load MUST be bounded to `[min(signal_time) − lookback, max(signal_time) + max_hold_window]` where `lookback` includes EVERY indicator window in effect (adaptive_blacklist `lookback_hours=48`, `mr_mean_period×mr_mean_interval`, btc_vol lookback, regime EMA-distance window). For manifest/coverage/seal lookups the span MUST be snapped OUTWARD to whole UTC-day boundaries (whole-day seal model) while the engine consumes only the precise window. A test MUST assert bounded-span results are byte-identical to a full-range oracle (identical `signals_no_kline` AND identical opened-trade set — every signal's entry-fill bar and full close-rule window included; no truncated-warmup divergence).
_Merged: 005, 036, 050, 070. Rationale: RC-17 — full-range load wastes rows+RAM; the bound must never drop a trade or truncate indicator warm-up._

### REQ-CACHE-021 — Loaded symbol set = distinct signals ∪ auxiliary symbols, exactly (must, P2)
The set of symbols loaded MUST equal `distinct(scan_source signal symbols) ∪ {required auxiliary symbols}` (BTC/USDT for Buy&Hold and btc_vol; MR-mean reference) — no signaled symbol omitted (which would silently become `signals_no_kline`) and no extraneous symbol loaded. A test asserts the load set tracks signal add/remove with byte-identical engine output.
_Merged: 138. Rationale: prevents both silent signal loss and wasted fetch/RAM._

### REQ-CACHE-022 — All auxiliary kline paths route through the cache (must, P1)
Every auxiliary kline path — Buy&Hold BTC (`_attach_buy_hold`, a SEPARATE loader path), btc_vol BTC, and MR mean-reference at `mr_mean_interval` — MUST route through the sealed-manifest/LRU cache so a warm rerun issues **0 Bybit calls across ALL of them**, not just the symbol loaders. Buy&Hold MUST keep `buy_hold_return_pct`/`buy_hold_final_value`/`excess_return` within the <1% oracle tolerance and MUST null those keys (never abort `_persist_results`) on fetch failure.
_Merged: 035, 051. Rationale: the separate B&H path is the easiest place to silently break the warm-rerun 0-call guarantee._

### REQ-CACHE-023 — Derive coarse/aux series from the fine 5m sealed base (no separate coarse fetch) (should, P2)
Coarse-interval runs and auxiliary reference series (coarse `simulation_interval`, B&H BTC, btc_vol BTC, MR-mean) MUST be DERIVED from the fine (5m) sealed base via resample, not a separate coarse-interval fetch: warm 5m→1h on the same symbols+window issues 0 Bybit + 0 kline SELECTs; even COLD, a coarse run fetches only the fine base once (no extra coarse pages).
_Merged: 115. Rationale: avoids redundant coarse fetches; one fine base serves all coarse derivations._

### REQ-CACHE-024 — Derive-once memos: resample, indicator/feature series, signals/contexts (should, P2)
Within a session/sweep: the fine→coarse resample for `(symbol, coarse_interval, range)` MUST be memoized (derived once, not per combo); indicator/feature series (trend-EMA, ATR, btc_vol series, MR reference-mean) MUST be computed ONCE per `(symbol/BTC, interval, range)` and reused across combos/reruns (only the per-combo THRESHOLD comparison varies); and `scan_source` signals + per-scan `ScanContext`s MUST be memoizable keyed on `(scan_source identity, interval, window)` EXCLUDING strategy config, so a param-tweak rerun issues 0 signal-table and 0 ScanContext-build queries. All such memos are bounded/evictable and byte-identical to a fresh build.
_Merged: 062, 127, 130. Rationale: a regime/MR/param sweep must not re-derive shared inputs per combo._

### REQ-CACHE-025 — Exchange-metadata (instrument_info + lifecycle) cached for full 0-call warm rerun (should, P1)
`instrument_info` (`qty_step, min_qty, tick_size`) and `symbol_lifecycle` exchange lookups MUST be cached with a TTL/sealed snapshot so a warm rerun's total Bybit `call_count == 0` across the FULL run — kline + instrument_info + lifecycle paths — not just the kline loaders.
_Merged: 058. Rationale: closes the warm-rerun 0-call guarantee over auxiliary metadata fetches._

---

## F. Symbol lifecycle & negative caching

### REQ-CACHE-026 — Lifecycle table consulted before fetch; discover, persist, deterministic (must, P1)
A `symbol_lifecycle(symbol, listing_time, delist_time)` table MUST be persisted, refreshed from exchange instrument info, and consulted before any fetch to exclude out-of-life ranges. On UNKNOWN/NULL lifecycle the loader MUST fetch-and-discover (treat the range as potentially live, never auto-skip as pre-listing) and MUST PERSIST the discovered `listing_time` (earliest candle) and confirmed `delist_time` back, so subsequent runs negative-cache pre-listing/post-delist days. Discovery MUST be deterministic across processes (two cold runs converge to identical lifecycle bounds and negative-cache day sets).
_Merged: 013, 042/259, 126/941, 134. Rationale: lifecycle is the gate that makes pre-listing/post-delist negative caching safe and cross-process stable._

### REQ-CACHE-027 — Negative cache served with zero I/O; precise gap-ranges queryable (must, P1)
Pre-listing, post-delist, confirmed-interior-structural-gap, and genuine in-life-empty day ranges MUST be recorded known-empty, sealed, and served from the manifest with **0 Bybit calls AND 0 kline SELECTs** (no rows to read; no Parquet/partition opened for an all-empty month), returning an empty set the engine handles as `signals_no_kline` (never raising). The PRECISE boundaries of every known-empty sub-range MUST be persisted in a queryable structure (gap-ranges, NOT merely `gap_count`) so the count-free predicate skips exactly those holes while still serving any genuinely-missing in-life sub-range.
_Merged: 014, 016, 071, 087, 091, 100. Rationale: negative caching is what stops pre-listing/post-delist/outage days from being perpetual refetch candidates._

### REQ-CACHE-028 — Known-empty only on genuine in-life 200-empty; transient gaps get one-shot reverify TTL (should, P1)
A day is recorded known-empty ONLY on a SUCCESSFUL HTTP-200 genuinely returning zero candles for an IN-LIFE range. A non-200/timeout/429, or an empty result outside confirmed `[listing,delist]`, MUST NOT create a known-empty seal. A genuine in-life 200-empty (possible later exchange backfill) MUST first be a TTL-bearing transient gap, re-verified **exactly once** at/after the frontier before permanent known-empty sealing — never immediate seal-forever — so a real day later backfilled is not frozen empty. Extended multi-day in-life empty stretches (outage / ultra-low-volume contract) ARE sealable per-day known-empty (distinct from pre-listing/post-delist).
_Merged: 039, 104, 113, 140/797. Rationale: separates transient exchange gaps from permanent out-of-life emptiness; prevents both perpetual refetch and false freezing._

### REQ-CACHE-029 — Negative-cache TTL durable & coordinated-clock; never on sealed days (should, P1)
The negative-cache/transient-gap TTL MUST apply ONLY to unsealed/transient gap days (never sealed days), MUST be DURABLE (persisted in the manifest, surviving process restart so it neither refetches every restart nor heals only in-process), and its expiry MUST be evaluated against the SAME coordinated UTC clock as the frontier (never local host wall clock), healing/re-verifying exactly once at the coordinated expiry.
_Merged: 017, 151. Rationale: an in-process-only or local-clock TTL re-fetches on every restart or heals inconsistently across skewed instances._

### REQ-CACHE-030 — Lifecycle transitions: delist→seal-tail, relist→reopen, mid-session & durable invalidation (should, cross)
On a delist transition the background lifecycle refresh MUST set `delisted/delist_time` and seal the now-complete in-life tail (delisted symbols incur **0 ongoing live-edge refresh** on later runs — a dead symbol has no forming candle). On a re-list (same symbol string, new contract, or unexpected candles appearing in a known-empty range) it MUST reopen/extend `delist_time` and re-discover rather than serve empty. Any lifecycle correction (operator override, background refresh, relist) MUST invalidate the in-process negative-cache memo (re-evaluated next access within the long-lived process) AND the DURABLE manifest-level negative-cache (so a fresh-process/post-restart run re-discovers the now-in-life day), while genuinely out-of-life days stay zero-fetch. A symbol that does not exist on the exchange MUST be negatively cached at the SYMBOL level after a bounded discovery attempt (queried at most once across reruns).
_Merged: 057/392, 060, 064/411, 121/583, 137/1034, 145/779. Rationale: lifecycle is dynamic; stale negative caches must heal on correction without un-sealing valid in-life days._

### REQ-CACHE-031 — Mid-window delist: post-last-candle days negative-cached; late signals → signals_no_kline (should, P2)
A symbol whose candles STOP mid-window (mid-backtest delist / ceases trading before `date_range_end`) MUST have its post-last-candle days negative-cached so reruns issue 0 fetches for them, and signals after its last candle MUST resolve to `signals_no_kline` — never a fabricated fill from the stale final close — identically to the legacy engine.
_Merged: 094. Rationale: prevents both perpetual refetch of dead-tail days and fabricated trades on stale prices._

---

## G. In-process caches: LRU, hot SoA, 1m drill, memory budget

### REQ-CACHE-032 — Bounded process LRU: sealed-only, forming-excluded-per-access, byte-identical (must, P1)
`_load_klines` MUST be wrapped in a process-level LRU keyed `(symbol, interval, start, end)`, bounded by entry-count and/or byte budget with eviction, returning klines byte-identical to a fresh Postgres read and not growing RSS across reruns. It MUST memoize **sealed days only**; the unsealed tail/forming day MUST never be memoized and always re-read fresh — and that forming-day exclusion MUST be re-evaluated against the live frontier on EACH access (not frozen at insert) so a day that crosses the frontier mid-session (UTC-midnight rollover) flips from always-fresh to memoizable with no restart.
_Merged: 006, 022/388, 023, 024, 030, 061. Rationale: §3.2 step 7 — memoize sealed days only; an unbounded or forming-frozen memo leaks or serves stale live data._

### REQ-CACHE-033 — Range-containment & partial-overlap hits via sub-linear index (should, P1)
The hot/LRU cache MUST serve a sub-range request from an already-cached SUPER-range as a zero-copy slice (0 Bybit + 0 kline SELECTs, byte-identical) — covering the differing per-run bounded spans of REQ-CACHE-020. A PARTIAL overlap MUST return byte-identical klines for the overlap with no torn/duplicated/misordered boundary candle (at minimum a correct miss-reload; the chosen reload-vs-merge strategy documented). Containment/overlap lookup MUST be backed by a sub-linear index (per-(symbol,interval) interval tree / sorted-range map), staying O(log E) as cached-range count E grows.
_Merged: 074/503, 086/598, 093. Rationale: bounded spans vary per run — without containment hits each run re-reads; without an index, lookup degrades over a long sweep._

### REQ-CACHE-034 — Eviction correctness: whole-entry, working-set-aware, view-safe, oversized-bypass (should, P1)
Eviction MUST be whole-`(symbol,interval,range)`-entry granular and working-set-aware (retain the active combo's frames, evict LRU whole entries — never partial slices), degrading to bounded sub-linear re-loads under a budget smaller than the working set (no per-combo full reload, no thrash). An evicted entry MUST reload byte-identical on re-request (eviction degrades to a correct MISS, never cached-empty/stale). Eviction MUST NOT free a buffer still borrowed by a zero-copy view (refcount keeps it alive — no use-after-free). A single entry larger than the entire byte budget MUST be served by bypass (or serve-then-evict) without thrashing or evicting the whole cache.
_Merged: 052, 054, 080, 156. Rationale: graceful degradation + memory-safety for the zero-copy SoA design._

### REQ-CACHE-035 — Arrow/SoA hot cache retains the working set; unified 3-tier memory budget (should, P3)
The in-process Arrow/SoA hot cache MUST retain the canonical fits-in-RAM working set so WITHIN one sweep no `(symbol,range)` is re-loaded or re-converted after first touch (per-combo kline-load count == 0 and SoA-conversion count == 0 for combos 2..K). The three in-process tiers (5m `_load_klines` LRU, 1m drill cache, Arrow/SoA hot cache) MUST be governed by a SINGLE unified process-wide memory budget with coordinated eviction so they cannot each grow to their own ceiling and collectively breach the process RSS ceiling.
_Merged: 032, 078. Rationale: the SoA conversion is expensive; a sweep must convert once, and the tiers must not independently OOM the process._

### REQ-CACHE-036 — 1m drill cache: in-memory-only, own ceiling, forming-excluded, cancel-safe, parity, cross-process reconciled (should, cross)
The 1m drill-down cache MUST be in-memory ONLY (after a drill, `kline_cache`/`kline_cache_coverage` are unchanged — 1m data can never re-poison 5m coverage), with its OWN explicit byte/entry ceiling + eviction separate from the 5m LRU, and MUST EXCLUDE the still-forming 1m sub-bar(s) (`open_time >= 1m frontier`) so a drilled forming 5m bar re-fetches its forming sub-bars while sealed sub-bars stay memoized. A cancel/120s timeout mid-drill-fetch MUST release the drill semaphore, leave no torn/partial bar, and persist no 1m data. Cold-vs-warm drill MUST be byte-identical (warm in-process rerun = 0 Bybit 1m calls). The cross-process warm-rerun 0-call guarantee MUST be explicitly reconciled with the in-memory-only 1m cache: either (a) document 1m drill fetches as an accepted divergence, OR (b) persist sealed 1m sub-bars to a SEPARATE durable drill store (own frontier/seal/clip semantics, never touching 5m coverage) — and strict-offline mode (REQ-CACHE-041) MUST fail-loud on a fresh-process drill miss rather than silently fetch or silently skip drilling.
_Merged: 031, 033/228, 077, 079/588, 116, 124, 125, 112(drill-portion), 154(gate-portion). Rationale: the 1m drill is the second intentional re-download (findings §RC); it must stay isolated from 5m coverage and have an explicit cross-process contract._

---

## H. Concurrency, rate-limiting, pool isolation, live coexistence

### REQ-CACHE-037 — Single-flight coalescing for identical & overlapping cold loads (should, P2)
Concurrent cold loads of the same `(symbol,interval,range)` MUST coalesce into a single in-flight fetch (≥4 concurrent loads of one uncached range ⇒ Bybit `call_count == 1`); and concurrent loads of OVERLAPPING (not merely identical) spans MUST coordinate so each interval-grid slot in the overlap is fetched exactly once (range-aware in-flight merge).
_Merged: 037/246, 135. Rationale: a K-combo parallel cold sweep on a shared range must issue 1 fetch, not K._

### REQ-CACHE-038 — Shared Bybit rate-limit semaphore, circuit breaker, keep-alive, positive concurrency (should, P2)
Cold gap-fill, parallel 1m-drill, and one-shot reverify fetches MUST share a rate-limit-aware concurrency semaphore (in-flight ≤ cap, bounded backoff) AND a process-level circuit breaker shared across runs/combos (open on sustained 429/5xx, half-open probe, close on success) so a degraded exchange is hit with fleet-bounded aggregate load. The Bybit HTTP client MUST reuse a bounded keep-alive connection pool (TCP count ≤ cap, not ~N) so handshake cost is amortized. The cold path MUST positively ACHIEVE concurrency via semaphore-bounded `asyncio.gather` (wall-time ≈ `ceil(N/cap)×t`, sub-linear in N), not merely stay under the cap by fetching serially.
_Merged: 034/229, 073, 096, 102/756, 117. Rationale: cold cost must parallelize without tripping rate limits or re-handshaking per request._

### REQ-CACHE-039 — DB-pool protection: release connection across HTTP await; bounded read concurrency (should, P2)
The cold gap-fill path MUST NOT hold a pooled asyncpg connection across the (slow, network-bound) Bybit HTTP await — release before the fetch, re-acquire only to store rows — so a slow/backing-off exchange can't pin a connection. Parallel cold Postgres reads MUST be bounded to a configured fraction of the pool (a DB-pool semaphore distinct from the Bybit rate-limit semaphore and from request-coalescing) so a wide cold sweep can't exhaust the pool and starve the live trading path's DB access.
_Merged: 053, 085. Rationale: the cache is shared with live trading; cold sweeps must not starve live DB/connections._

### REQ-CACHE-040 — Live-path coexistence: shared manifest, no live-set eviction, independent toggle, rate priority, forked-worker isolation (must, cross)
Because `kline_cache_service` is shared, the sealed-manifest gate MUST: (a) be independently toggleable for the backtest path vs the live path (two flags) and preserve the LIVE path's current-day freshness/coverage byte-identically — verified across scanner/auto-trade AND the AI Manager (`ai_manager_task`) and `position_reconciler` read paths; (b) write closed-day seals into the ONE shared manifest from BOTH live and backtest fetchers using identical frontier/seal logic, so a day fetched by either is served to the other with 0 refetch; (c) priority-weight/pin the live path's hot working set so a cache-thrashing backtest never evicts it (live fetches stay warm); (d) rate-PRIORITIZE backtest cold-fill strictly below the live path on the shared semaphore/breaker (live holds a reserved share, never throttled). Forked ProcessPool sweep workers MUST treat inherited COW dict caches as empty and access shared kline/SoA data only via explicit shared-memory arrays (no COW-balloon RSS, no serving a parent-only entry).
_Merged: 043, 066, 103, 109, 122, 132, 133. Rationale: the cache is shared infrastructure — the optimization must be invisible and non-disruptive to live trading._

---

## I. Integrity, content-hash, correction & invalidation

### REQ-CACHE-041 — content_sha256 integrity escape hatch: warm = no hash, mismatch = refetch, empty = sentinel (should, P1)
Warm reads of a sealed day MUST NOT recompute `content_sha256` by default (trust the stored sha; hashing runs only on the explicit integrity/escape-hatch or manual force-reverify path — a warm read pays 0 hashing cost). The escape hatch MUST work both ways: a sealed day whose recomputed hash no longer matches IS refetched and re-sealed; a matching hash is NEVER refetched (`call_count==0`). A zero-row (fully known-empty) day MUST hash to a canonical sentinel so empty days compare deterministically on the integrity path. There MUST be a documented, tested admin/operational force-reverify path (explicit/manual, never on `candle_count`) that recomputes the hash, conditionally refetches, and re-seals with the corrected hash — for exchange-backfill/historical-restatement.
_Merged: 045, 098, 101, 059/397. Rationale: seal-forever needs a controlled, cheap-when-warm correction path for genuine upstream restatements._

### REQ-CACHE-042 — Manifest↔store integrity guards (both directions) + internal consistency (should, P1)
The loader MUST fail-loud or trigger one-shot reverify+reseal (never silently backtest on wrong data) when: (a) a `sealed` day returns FEWER rows than its stored `candle_count` (rows deleted, partition dropped, store/manifest skew) — never proceed on truncated klines; (b) the INVERSE — a `sealed`-known-empty/negative-cached day has kline rows PRESENT (stale negative cache racing a real backfill, relist, legacy-instance store) — never silently drop real candles into `signals_no_kline`; (c) manifest internal accounting fails to reconcile: `Σ(gap-range slots) == gap_count` and `candle_count + gap_count + boundary-clip(listing/delist/forming) == interval-derived expected in-life slots`. Legacy rows predating the turnover/quote-volume column (NULL turnover/volume) MUST be handled by ONE documented policy on read, in fine→coarse aggregation, and in the hash/count-shortfall checks — no raise, no NULL-poisoned coarse bar, no spurious refetch.
_Merged: 044/295, 147, 153, 142. Rationale: a sealed manifest is only as trustworthy as its agreement with the actual stored rows._

### REQ-CACHE-043 — SOR-drift detection beyond the generation token (could, P1)
The system MUST detect Postgres-SOR content drift the `#755` data-generation token can't catch on its own (in-place `delete+reinsert`, out-of-band restatement, or a PITR rewinding the token below later-built artifacts) via a sampled/triggered integrity check (sealed-day row-count vs `candle_count`, or recomputed vs stored `content_sha256`), then bump the generation, invalidate dependent columnar/in-process artifacts, and emit an alertable signal — rather than assuming every SOR change carries a correct token bump.
_Merged: 148. Rationale: the generation token assumes disciplined writers; un-tokened restatements must still self-heal._

### REQ-CACHE-044 — Correction invalidation is total; in-flight runs are snapshot-isolated; mid-seal reads consistent; flag-keyed memos; accel-fallback reuse (should, cross)
A content-changing sealed-day correction (sha-mismatch refetch or manual force-reverify) MUST invalidate EVERY overlapping in-process artifact — `_load_klines` LRU, Arrow/Polars hot frame, mmap'd Feather slice, derived-coarse memo, raw→SoA conversion memo, AND the global-timeline/scan-anchor memo — so a long-lived process never serves pre-correction data from any tier. But an IN-FLIGHT run MUST consume a point-in-time snapshot fixed at SoA-build: a concurrent correction of its days MUST NOT mutate its already-materialized read-only arrays (observed only by the NEXT run), and the run MUST record the data-generation it consumed; likewise a backtest reading a day CONCURRENTLY with a deferred-backfill/lazy-seal MUST observe one coherent classification (fully-unsealed or fully-sealed, never torn mid-seal). Any in-process memo whose CONTENTS depend on a data-path flag (derive-coarse-from-fine, columnar-vs-Postgres, manifest-gate) MUST incorporate the resolved flag generation into its key or be invalidated when the flag changes between runs (within-run flag freeze still holds). After an accelerated-path mid-run fault triggers a clean fallback rerun, the fallback MUST reuse the warm LRU/immutable-SoA data already loaded (0 Bybit refetch, 0 kline SELECTs on restart — re-execute only the engine).
_Merged: 069/436, 111/755, 114, 143, 152, 118. Rationale: corrections must be total for the NEXT run yet never corrupt an already-running run or splice mixed-generation data._

---

## J. Cross-cutting: canonicalization, warmup, offline, intraday, rebuild, store-failure

### REQ-CACHE-045 — Canonical symbol & interval keys + pinned category/interval fetch mapping (must, cross)
A single documented SYMBOL canonicalization (case/separator/contract-suffix, e.g. `BTC/USDT` vs `BTCUSDT` vs `BTCUSDT.P`) AND a single documented INTERVAL canonicalization (internal `1m/5m/15m/1h/4h`) MUST be applied uniformly across scan_source signals, `kline_cache` PK, the sealed-manifest PK, `symbol_lifecycle`, the Bybit fetch ticker, the Parquet hive partition value, the in-process LRU/hot/1m-drill keys, and the symbol→int-code map — any alternate form resolves to ONE key (never split into two coverage/manifest rows or cache entries, never silently demoted to `signals_no_kline`); an unsupported interval is rejected at the cache boundary with an actionable error. The Bybit fetch path MUST pin instrument `category=linear` (USDT-perpetual) and the interval mapping (`5m/15m/1h/4h/1m → 5/15/60/240/1`) so a futures fetch can never silently retrieve spot/wrong-category/wrong-interval data.
_Merged: 141/1063, 146/1039, 139/1039. Rationale: one logical symbol/interval must key identically everywhere or coverage silently splits and parity breaks._

### REQ-CACHE-046 — Manifest-aware idempotent warmup endpoint (sealing, shared seal code) (should, P2)
`POST /backtest-cache/warmup` MUST be manifest-aware and idempotent: it incrementally SEALS the v58 manifest for completed days it fetches (not merely fill `kline_cache` rows), re-warming an already-sealed range issues 0 Bybit calls, it is single-flight-safe to run concurrently with backtests, populates `symbol_lifecycle`, reports PER-SYMBOL success/failure (not all-or-nothing), and its response contract stays additive-only. It MUST execute the IDENTICAL frontier seal gate, forming-clip, and seal-only-after-post-frontier-terminal-candle rule as the backtest cold-fetch path via SHARED code (a near-midnight warmup can't seal a forming day or persist a forming candle the backtest path would have clipped).
_Merged: 063, 067, 083. Rationale: an operator pre-warm before a big sweep must produce sealed days, byte-identical to what a cold backtest would seal._

### REQ-CACHE-047 — Strict-offline / cache-only run mode (fail-loud on any miss, incl. 1m & aux) (should, cross)
A STRICT-OFFLINE / cache-only mode (config/env flag) MUST serve only from manifest/Postgres/columnar tiers and FAIL LOUD with an actionable miss message on ANY cache miss instead of issuing a Bybit fetch — enabling deterministic incident-replay and a hermetic CI lane. It MUST cover the in-memory-only 1m drill cache and all auxiliary series (B&H BTC, btc_vol BTC, MR-mean): a fresh-process drill/aux miss FAILS LOUD (clear error, 0 Bybit calls) rather than silently fetching (violates offline) or silently skipping the drill/aux computation (corrupts results).
_Merged: 106, 112, 095. Rationale: a hermetic warm lane proves the warm-rerun 0-call guarantee and gives deterministic replay._

### REQ-CACHE-048 — Intraday/forming-day-only & future-window clamp & replica-lag tolerance (should, P1)
A backtest whose window lies ENTIRELY within the current forming/live-edge UTC day MUST run correctly served from Postgres with 0 sealed days, 0 columnar artifacts, 0 negative-cache entries, while still producing a real result with `metrics.total_trades` present, byte-identical to legacy. A window extending to/beyond `now` MUST CLAMP to the forming edge: genuinely-future days (`open_time >= now`) incur 0 fetch / 0 SELECT, are NOT classified as coverage gaps, and are NOT sealed/negative-cached. The manifest read/seal path MUST tolerate Postgres read-replica lag: a day sealed on the primary but not yet visible on a lagging replica is classified UNSEALED/refetchable (count-free, safe-but-slower), never raised as an integrity error (no read-your-writes assumption across primary/replica).
_Merged: 105, 084, 107. Rationale: the `metrics.total_trades` trap + future/forming edges + replica lag must degrade safely, never error or seal wrongly._

### REQ-CACHE-049 — In-place manifest rebuild-from-SOR: interruptible, idempotent, preserves known-empty; wired into copy-prod-scans (could, cross)
The admin in-place manifest REBUILD-from-SOR path MUST seal closed days from existing `kline_cache` rows + `symbol_lifecycle` with **0 Bybit refetch**, be interruptible/resumable from its OWN persisted checkpoint and idempotent (a killed+restarted rebuild resumes without re-scanning rebuilt chunks and never leaves a half-rebuilt manifest; final result byte-identical modulo NULL sha to an uninterrupted rebuild). It MUST preserve every known-empty/negative-cache record NOT re-derivable from rows+lifecycle alone (confirmed interior structural gaps, genuine in-life 200-empty days) — either persist them durably across rebuild OR re-verify each ambiguous in-life empty day exactly ONCE before re-sealing (never perpetual refetch). The `copy-prod-scans` workflow MUST invoke this rebuild in the TARGET environment so a fresh manifest-less env seeded with copied klines seals from the SOR with 0 Bybit calls.
_Merged: 157/675/777, 128, 108. Rationale: restated/copied data needs a manifest rebuild that can't be defeated by interruption or re-introduce perpetual refetch of ambiguous empties._

### REQ-CACHE-050 — Store/seal write-failure is non-fatal and leaves the day unsealed (must, P1)
A Postgres WRITE failure during cold gap-fill `store_klines` (disk-full, statement_timeout, constraint violation, mid-batch connection loss) MUST leave the affected day UNSEALED/refetchable, write no torn/partial manifest seal row, and either fail the run loud with an actionable symbol+range message or surface a documented explicit partial-data warning — NEVER seal a day whose rows failed to persist, never let the engine proceed on a truncated set. Symmetrically, a manifest seal-upsert/coverage-write failure occurring AFTER the klines are durably stored MUST be non-fatal (run/warmup completes oracle-identical, day stays unsealed for next-run lazy-seal, no torn manifest row).
_Merged: 048, 155, 136. Rationale: a half-written cache must always degrade to "unsealed, retry next run," never to a corrupt sealed state or a silent truncated backtest._

---

## Coverage map (raw → consolidated)

- **A** warm/cold contracts: 000,001,022,049,075,097,099,353,504,116(parity) → 001–004
- **B** frontier/seal: 008,009,011,012,015,027,028,038,040,047,055,056,089,120,249,390,391,424,758,922 → 005–008
- **C** manifest/loader/v58: 002,010,020,021,041,065,068,076,081,082,090,123,150,252 → 009–014
- **D** gap-run/pagination/ingest: 004,019,029,072,088,110,119,129,131,144,149,435,501,789,965 → 015–019
- **E** bounded/symbol-set/aux/derived: 005,035,036,050,051,058,062,070,115,127,130,138,238,355,404,405 → 020–025
- **F** lifecycle/negcache: 013,014,016,017,039,042,057,060,064,071,087,091,094,100,104,113,121,126,134,137,140,145,151,259,392,411,583,779,797,941,1034 → 026–031
- **G** in-proc caches: 006,023,024,030,031,032,033,052,054,061,074,077,078,079,080,086,093,112(drill),124,125,156,228,388,503,588,598 → 032–036
- **H** concurrency/live: 034,037,043,053,066,073,085,096,102,103,109,117,122,132,133,135,229,246,756 → 037–040
- **I** integrity/correction: 044,045,059,069,098,101,111,114,118,142,143,147,148,152,153,295,397,436,755 → 041–044
- **J** cross-cutting: 084,095,105,106,107,108,128,136,139,141,146,148,155,157,675,777,1039,1063 → 045–050

**Distinct ideas preserved: 50 consolidated requirements from 158 raw items (108 merged as near-duplicates, 50 kept).**

