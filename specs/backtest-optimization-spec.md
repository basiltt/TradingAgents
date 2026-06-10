# Specification: Backtest Performance Optimization

> **Template:** `/new-feature` Step 4 spec (sections A–Z).
> **Status:** DRAFT → Spec Review (Step 5) gate next.
> **This document is the authoritative requirements contract.** It translates the 517 curated
> requirements into a testable FR/NFR set, pins explicit per-phase acceptance criteria (P0–P6),
> and is written to survive adversarial spec review. Every FR/NFR is testable and traces to a
> REQ category + rollout phase + a named test (§Y Traceability Matrix).

---

## A. Title & Metadata

| Field | Value |
|-------|-------|
| **Feature** | Backtest Performance Optimization (hours → seconds-to-minutes, TradingView-class) |
| **Slug** | `backtest-optimization` |
| **Author** | Lead Engineer (autonomous `/new-feature` pipeline) |
| **Created** | 2026-06-10 |
| **Skill** | `/new-feature` (Step 4 — Specification) |
| **Type** | Performance + storage refactor under a HARD zero-business-logic-change constraint |
| **Rollout** | 7 phases — **P0** golden-master harness → **P1** cache fix → **P2** loaders/sweep → **P3** SoA engine → **P4** numba JIT → **P5** Parquet/DuckDB → **P6** vectorized fast-path |
| **Grounding** | `specs/backtest-optimization-architecture.md` (1644 L, ADR-001..005, components §3.1–3.12), `specs/backtest-optimization-requirements.md` (517 REQ across 15 categories), `specs/backtest-optimization-findings.md` (root causes RC-1..RC-11), `specs/backtest-optimization-discovery.md` (codebase surface) |
| **Core files (semantic parity required)** | `backend/services/backtest_engine.py` (~1910 L), `backtest_service.py` (~1660 L), `kline_cache_service.py` (~560 L), `trading_rules.py`, `backtest_metrics.py`, `backend/mcp/tools/optimizer/sweep_tools.py` + `sweep_repo.py` |
| **Migration** | **v58** (next free int after current latest v57) — `_MIGRATIONS` in `backend/async_persistence.py` |
| **New deps (optional, import-guarded)** | `numba`, `llvmlite`, `pyarrow`, `duckdb` — `[project.optional-dependencies].accel`, never base |
| **Stack** | FastAPI / Python 3.14.3, asyncpg/PostgreSQL, numpy 2.4.4; React + TS + Vite frontend |
| **Hard wall** | `_TIMEOUT_SECONDS = 120` (`backtest_service.py:770`) — both the symptom and a constraint |

### A.1 Document conventions

- **REQ-IDs** reference `specs/backtest-optimization-requirements.md` (e.g. `REQ-PAR-001`). FR/NFR text
  groups requirement categories rather than enumerating all 517; the must-have anchors are cited inline.
  **Exception — REQ-SEC-001..007** originate in **architecture §8.7**, NOT in `requirements.md` (a grep of
  requirements.md returns none); they are carried as a named-but-externally-sourced category and counted as the
  separate "+7 SEC" total (§Y), never folded into the 517. **REQ-PERF-046** (numba/pure-Python lane split + committed
  pure-Python budget, §I.0a) **has now been backported into `backtest-optimization-requirements.md` (R2-F5-batch3)** as
  a `must, cross` item counted separately from the 45-item PERF baseline (mirroring the REQ-SEC external-source
  convention); this spec and the requirements baseline now agree on it.
- **Phase tags** `P0`–`P6` map to the rollout above; `cross` = cross-cutting (delivered/asserted across phases).
- **Lane** terminology: the **canonical 5m no-drill path** is the bit-identity lane; **drill / portfolio /
  fast-path lanes** carry genuine intrabar/coarse-resolution ambiguity and are governed by the non-optimistic
  (one-sided float ≤ Decimal) invariant.
- **Parity representation pivot at P3:** through P2 the engine still computes in `Decimal`; the golden master is
  **byte-identical to the string→Decimal oracle**. From P3 on, float64 SoA math lands and the golden master is
  **re-frozen AS the float64 representation** — the gate becomes **discrete fields bit-identical** (trade count,
  sides, symbols, entry/exit bar indices, ordering) **AND money fields within a pinned two-sided
  `continuous-money-epsilon`** vs the Decimal oracle (Prime Directive table; REQ-STORE-040 corrected, REQ-TEST-005).

---

## B. Discovery Summary

**The slowness is NOT the per-candle math — it is the SETUP that scales with total candles per scan, plus a
false-positive cache miss that re-downloads the whole history every rerun.** Two verified root-cause clusters:

1. **Engine setup is super-linear (RC-1, RC-2 — CRITICAL/VERIFIED).** `_evaluate_candles_until`
   (`backtest_engine.py`) rebuilds a datetime-keyed window index by walking *every open symbol's entire kline
   list on every scan* (inner loop `continue`s, never `break`s, on both bounds), and re-seeds every carried
   position's mark by a linear prefix scan from index 0. Net ≈ **O(scans × symbols × N_total)** with a
   quadratic-in-time seeding term, vs an achievable **O(total_candles × symbols)** single merge-walk. Fixing the
   data layout (structure-of-arrays + `searchsorted`/non-resetting pointers) is the single biggest engine win and
   is **parity-neutral** — it changes *how* prices are located, not *which* decisions are made.

2. **Re-download is a false-positive coverage gap (RC-3 — CRITICAL/VERIFIED).** `get_coverage_gaps`
   (`kline_cache_service.py`) flags any day holding fewer than the theoretical-max candle count (288 for 5m) as a
   *perpetual* gap. Legitimately-short days (mid-day listing, halt, the still-forming current day) store e.g.
   144/288, refetch returns the same 144, the `GREATEST` upsert caps it at 144 < 288 **forever**, `fetched_at` is
   never consulted (no TTL). Because `ensure_coverage` fetches one span `[min(gap_days) .. max(gap_days)+1d]`, a
   perpetual-gap day near the start (listing) plus one near the end (forming) **bracket the whole window and
   re-download the entire history on every rerun**, independent of config. A second intentional re-download is
   Phase-B 1m drill-down (`_build_fine_klines`), which fetches over a contiguous min→max span and discards ~98%.

**A pure vectorbt-style rewrite is INFEASIBLE for the general config (ADR-001, adversarially verified).** The
engine is a cross-sectional, shared-capital portfolio simulation with path-dependent latches (running-wallet
sizing, `cycle_start_equity` zeroing, `smart_drawdown_fired` one-shot, funding `(date,hour)` dedupe,
adaptive-blacklist-from-own-trades) and **portfolio-level close rules** (EQUITY_DROP/SMART/close_on_profit/
EQUITY_RISE) that flatten the whole basket on a basket-equity threshold. The right architecture is **keep the
sequential event loop, make it numba-fast over columnar numpy arrays**, with an optional vectorized barrier-exit
fast-path for the narrow config subset where positions are provably independent.

**No-regress surfaces (the contract the optimization must hold identically):**

- **Config surface:** `BacktestCreateRequest.model_dump()` → `config.get(...)`; **MCP `backtest_run` params are
  1:1 identical**. ~60 fields across Execution / Trade-decision / Close-rules / Adaptive-blacklist / F1-regime /
  F2-mean-reversion / F3-cohort groups (discovery §3).
- **API:** **9 endpoints** in `backend/routers/backtest.py` (VERIFIED against code — `@router` decorators:
  `POST /backtest` create+launch, `GET /backtest` list, `GET /backtest/compare`, `GET /backtest/{run_id}`,
  `GET /backtest/{run_id}/trades`, `POST /backtest/{run_id}/cancel`, `DELETE /backtest/{run_id}`,
  `GET /backtest-cache/status`, `POST /backtest-cache/warmup`). **There is NO `POST /backtest/{id}/run` route** —
  `POST /backtest` is a **single-step create-AND-launch** (`create_backtest` reserves a `_MAX_CONCURRENT=3` slot
  synchronously and calls `_launch_background` in the same request; it raises `BacktestBusyError`→`503` when full,
  it does NOT today enqueue). **`compare` is `GET /backtest/compare`, NOT `POST`.** run states `pending → running →
  completed/failed/cancelled`; cooperative `threading.Event` cancel; `_MAX_CONCURRENT=3`; 120s hard cap.
- **Result/Trade JSON:** `BacktestResults{metrics, equity_curve, summary, warnings}`; ~45-key `BacktestMetrics`;
  `EquityPoint{ts, equity, drawdown_pct?}`; 19-field `BacktestTrade` + `strategy_kind`. **BREAKING-CHANGE TRAP:
  if `metrics.total_trades` is absent/renamed, the UI routes completed runs to the "no trades simulated" fallback
  (`frontend/src/components/backtest/BacktestResultsPage.tsx:255` — VERIFIED full path, R3-F2-batch6; the sibling
  `types.ts:31` `isPending` + `BacktestListPage.tsx` per-row status used by FR-052/L.5 share the same
  `frontend/src/components/backtest/` directory. Every later bare `BacktestResultsPage.tsx` reference in this spec
  resolves to that path — NOT `src/pages/`).** Only ADD optional nullable keys.
- **Metrics:** `compute_all_metrics` (`backtest_metrics.py:607`); path-dependent Sharpe/Sortino/max-DD/run-up
  depend on `equity_curve` ORDER — ordering must be preserved exactly.
- **Storage/migration:** `kline_cache` (partitioned), `kline_cache_coverage` (PK symbol,interval,date),
  `backtest_runs/_results/_trades`; sealed-manifest columns are net-new (v58, `ADD COLUMN IF NOT EXISTS`);
  multi-statement DDL must be a **callable** migration (the `;`-split bug); version-int collisions have happened
  twice (claim next free + coordinate).
- **Parity landmines (verified):** `close_reason 'liquidation'` effectively unreachable in normal configs
  (SL-clamp); `equity_drop_smart` one-shot per scan with re-arm; **`max_same_sector` is an INTENTIONAL no-op — do
  NOT "fix" it**; golden NO-OP guarantee (empty instrument_info/scan_contexts/fine_klines + no regime ⇒
  byte-identical to the pure 5m path); `regime_staleness_minutes` is live-only (N/A in backtest).
- **New deps:** backend is currently pure-Python with zero heavy deps — a missing wheel must NOT crash backend
  import; numba on Python 3.14.3 + numpy 2.4.4 is bleeding-edge (**D5 risk**), so P3 alone must hit "minutes".

---

## C. Feature Overview

Re-architect the crypto-futures backtesting system so a backtest that today runs for **multiple hours (and
frequently hits the 120s kill)** completes in **seconds-to-minutes** with **TradingView-class** result fidelity,
**without changing a single business-logic decision**. The optimization changes *how* kline data is
**loaded, located, looped, and stored** — never *what* the trading rules decide.

Five mechanisms, layered as 7 independently-revertable phases, each gated by a golden-master parity diff:

| # | Mechanism | Phase | Parity posture |
|---|-----------|-------|----------------|
| 1 | **Sealed-day manifest** — closed days fetched exactly once ever; only the forming-edge gap is re-read (kills the false-positive re-download) | P1 | Byte-identical klines; rerun `bybit_kline_calls == 0` on sealed range |
| 2 | **Batched loaders + lazy/parallel drill-down + parallel sweeps** — N+1 → 1 query; bounded 1m fetch with in-process cache; ProcessPool fan-out with shipped-once shared inputs | P2 | NO-OP guarantee; drill-on/off SELECTION identical |
| 3 | **Structure-of-Arrays + global timeline + merge-walk pointers** — kills RC-1 O(scans×N_total) setup + RC-2 quadratic seeding; `searchsorted`/O(1) lookups | P3 | Bit-identical discrete + money within `continuous-money-epsilon` (float64 re-freeze) |
| 4 | **numba `@njit` per-candle kernel** (optional, import-guarded) — removes interpreter overhead on the hot loop; pure-Python fallback of record | P4 | Pure-Python vs JIT bit-identical |
| 5 | **Parquet/DuckDB read tier + Arrow hot cache** + **vectorized barrier fast-path** for independent-position configs | P5/P6 | Columnar-off → Postgres-identical; fast-path two-sided sandwich vs sequential kernel |

**Parity is defended bit-for-bit by a golden-master suite (P0) that gates every later phase.** No phase is
trusted without its golden-master diff. The 120s hard cap stays a **safety net, never a target** — every
**CANONICAL-class** benchmarked run must finish at ≤ 50% of the cap (≤ 60s); HEAVY/HEAVIEST classes carry a documented `≤90s`
budget exception (still `< 120s` — the 120s hard kill is universal and never raised); **WIDE carries a numba-lane
latency budget only — on pure-Python it is RSS/stream/preflight-governed with no latency commitment and is rejected
pre-slot if infeasible (R2-F1-batch4)** (§I.0a/NFR-001/Q.1).

**Out-of-the-box this is a pure-Python win:** Phases 1–3 ship **effective-on-by-default** and must hit "minutes"
alone (D5), so the bleeding-edge numba stack (Phases 4–6) is strictly optional acceleration behind import guards +
feature flags. A missing/broken accel wheel degrades to the verified pure-Python/Postgres path, never crashes. **P1
(sealed manifest) and P3 (SoA engine) are nonetheless independently revertable AT RUNTIME** via the added
`BT_CACHE_SEALED_MANIFEST` / `BT_ENGINE_SOA` flags (FR-046) — so the kill-switch reaches them too, not only the accel
layer. (The master `SAFE_MODE` lever alone reproduces the **accel-off P3 pure-Python** oracle; full pre-feature
reproduction is the documented multi-flag combination.)

---

## D. Business Goal

| Goal | Why it matters | Measured by |
|------|----------------|-------------|
| **Backtests finish in seconds-to-minutes** | Today runs take hours or hit the 120s kill — the feature is effectively unusable for iteration; users cannot tune strategy params in a feedback loop | Canonical 90d×50sym×5m: drill-off **<10s (numba lane only)** / **≤60s (pure-Python lane — the binding bar when `HAS_NUMBA` is false, REQ-PERF-046)**; ≥100× vs frozen P0 **engine-CPU** baseline on the **numba lane** (pure-Python carries the absolute ≤60s budget, not the multiplier) (REQ-PERF-001/003/046) |
| **Reruns/sweeps do ZERO redundant exchange work** | The re-download bug re-pulls the entire history every rerun — the dominant wall-clock cost and a Bybit rate-limit/Cost liability | `bybit_kline_calls == 0` on a fully-sealed rerun; sealed day fetched exactly once across N reruns (REQ-CACHE, Prime Directive) |
| **<1% deviation from the legacy backtest oracle** | The refactor must not change results: a fast-but-wrong engine is worse than a slow one. **(R6-F3-batch4 — relabeled from "<1% deviation from real trading": the "Measured by" column is parity to the LEGACY ENGINE (golden-master bit-identity + Σ reconciliation), NOT to live fills; bit-identity to legacy proves the zero-business-logic-change refactor preserves legacy behavior, it does NOT prove <1%-vs-live, and no AC validates against recorded live fills — so the headline must name its real, testable scope)** | Golden-master bit-identity (5m no-drill) + <1% per-trade/summary on drill/portfolio lanes + three-way Σ reconciliation (Prime Directive). **Real-trading-vs-backtest accuracy is INHERITED from the existing engine (the refactor changes no trading logic) and is OUT OF SCOPE for this performance feature — see §W assumption** |
| **TradingView-class result fidelity** | Equity curve, drawdown, ~45 standard metrics must render correctly and completely | Result-JSON contract test (all ~45 keys present/typed); path-dependent metric ordering preserved (REQ-FE-009, discovery §6) |
| **Parameter sweeps become interactive** | `optimize_config` / `sweep_run` drive the agent's propose-config workflow; serial sweeps over the slow engine are infeasible | 100-combo warm sweep **<60s**, 500-combo **<5min** (numba+ProcessPool lane, fast engine); measured **speedup ≥0.7×min(M,K,concurrency)** (REQ-SWEEP-005/006) |
| **Zero production risk during rollout** | A migration crash-loop, a frontend break, or a new-dep import failure would take down live trading (shared FastAPI process) | Master kill-switch reproduces oracle in one lever; v58 expand-only + sub-second; new deps import-guarded; `metrics.total_trades` contract-tested (REQ-ROLL/MIG/DEP/FE) |

**Non-goal:** changing any trading decision, adding the AI-Manager backtest feature (deferred), or rewriting onto
a third-party backtest framework (ADR-001 rejects vectorbt/nautilus on the critical path).

---

## E. Current System Behavior

**Run lifecycle (today).** `POST /backtest` (`create_backtest:191`, reserves a `_MAX_CONCURRENT=3` slot,
per-client rate limit) → `_launch_background:665` → `_execute_backtest:671`: cache warm-up owns `[0,
_WARMUP_BAND=10%]`, then `load_inputs:1254` → Phase A coarse engine pass → optional Phase B drill-down
(`_build_fine_klines:983`) → `compute_all_metrics` → `_persist_results:1435` → `_attach_buy_hold:1331`. A
`threading.Timer(_TIMEOUT_SECONDS=120):770` cooperatively cancels via `threading.Event` (engine checks every 100
candles, `backtest_engine.py:1232`).

**Engine (today).** Pure sync sim loop, Decimal/`math` arithmetic, **zero heavy deps**. Reads every config field
via `config.get(field, default)` mirroring schema defaults. `_evaluate_candles_until` rebuilds the window index
per scan by walking every open symbol's full kline list (the RC-1 super-linear setup); carried positions are
re-seeded by a linear prefix scan from index 0 (the RC-2 quadratic seeding). `trading_rules.py` is the shared
SSOT for sizing, TP/SL, slippage, liq, fees, trailing, breakeven (live + backtest).

**Cache (today).** `KlineCacheService` fetches from Bybit v5 (`_BYBIT_KLINE_URL:18`, `category=linear`,
`_PAGE_SIZE=200`, `_MAX_PAGES=5`, `_MAX_RETRIES=3`). `get_coverage_gaps` uses count-vs-expected as the coverage
primitive — the RC-3 false-positive: a short-but-complete day is a perpetual gap, `_update_coverage:303` `GREATEST`
upsert caps it forever, `fetched_at` is never consulted. `ensure_coverage` fetches one bracketing span, so two
perpetual-gap days re-download the whole window. Phase-B 1m drill is fetched and deliberately not persisted.

**Storage (today).** Migration 38: `kline_cache` (PK symbol,interval,open_time; PARTITION BY RANGE monthly ±6mo +
DEFAULT), `kline_cache_coverage` (PK symbol,interval,date; `candle_count SMALLINT`, `fetched_at` already present),
`backtest_runs/_results/_trades`. Migrations are positional ints in `_MIGRATIONS`; current latest **v57**.

**Result/persistence (today).** `_build_results:476`; `equity_curve` LTTB-downsampled on GET
(`_downsample_equity:491`). Persistence idempotency: results upsert `ON CONFLICT(run_id)`; trades
delete-before-insert; kline `INSERT ON CONFLICT DO NOTHING`; coverage `GREATEST` upsert. NUMERIC cols need Decimal
coercion + finite-guard (`_num:1449`) or one Inf/NaN aborts `_persist_results`. The weak `_assert_reconciles`
only ties `metrics['net_profit']` to `final_equity − start` — it does NOT independently assert `Σ trade['pnl']`.

**Sweep (today).** MCP `sweep_tools.py` / `optimize_config` call the pure engine directly (bypassing drill-down);
serial execution over the slow engine.

**Net symptom:** a real 90d×50sym run re-downloads its whole history, then runs the super-linear engine, and
**hits the 120s kill** — the feature is unusable for its purpose.

---

## F. Expected New Behavior

**Same decisions, same JSON, dramatically faster — and provably so.**

1. **Engine.** The sequential cross-sectional event loop is preserved, but driven over **structure-of-arrays**
   columnar data with a **global sorted-unique timeline** and **per-symbol advancing pointers that never reset**
   (merge-walk). Mark-seed becomes O(1) at the current pointer; "last close ≤ T" / "first open ≥ T" become
   `searchsorted` (O(log N)). The per-candle kernel (liquidation→SL→TP precedence, uPnL, basket equity, MFE/MAE,
   funding, trailing/time) is `@njit`-compiled when the accel stack is present, with a **pure-Python fallback of
   record** that is the parity oracle. The basket-equity recompute fires **once per timeline tick** over the open
   book (the pinned parity cadence). **No business decision changes** — proven byte-identical on the 5m no-drill
   path and within `continuous-money-epsilon` on the float64 lanes.

2. **Cache.** A **sealed-day manifest** (net-new v58 columns on `kline_cache_coverage`) replaces count-based
   coverage. A day **seals** once it is fully past the completion frontier `floor((now − skew)/T)*T` AND its
   candles are durably stored + OHLC-validated. A sealed day is **immutable, fetched exactly once ever**; only the
   `(max_stored_ts → frontier)` gap is ever fetched. A negative-cache class records pre-listing/post-delist/
   known-gap days so they are never re-probed. **Reruns over sealed ranges issue 0 Bybit calls.**

3. **Loaders + drill-down + sweeps.** `_load_klines` batches N+1 → 1 query (`symbol=ANY($1)` + `BETWEEN`). The 1m
   drill-down is **lazy per-symbol, bounded per-bar, in-process cached** — no more discarding ~98%, no more
   re-pull on rerun. Sweeps fan out across cores (`spawn` ProcessPool + `shared_memory`) with the SoA snapshot
   **shipped once**, falling back to a bounded `ThreadPoolExecutor` over the `nogil=True` kernel (win32 dev/CI) or
   sequential.

4. **Storage tiers.** Sealed days are materialized to an immutable **Parquet/Feather** columnar read cache with an
   **Arrow hot frame** (≤150MB LRU) — warm sweep reruns slice from RAM. **The forming UTC day never enters a hot
   tier**; it is served exclusively from Postgres primary. Materialization is best-effort and independent of
   sealing (Postgres stays the system-of-record).

5. **Result contract — unchanged.** Every endpoint signature, request schema, and response shape is identical.
   `metrics.total_trades` and all ~45 keys are always present and correctly typed. New fields are **optional +
   nullable only** (`metrics.engine_path`, `metrics.cache_provenance`, `summary.jit_warm_ms`, `warnings[]`
   additions). A degenerate/zero-trade run still returns `total_trades=0` present (never the frontend trap). One
   **additive non-breaking** `GET /backtest-runtime/status` route (pinned non-colliding prefix — see K.2) exposes
   runtime optimization state.

6. **Safety.** A master `BACKTEST_SAFE_MODE` kill-switch forces all optimization flags effective-off in one
   operation (reproducing the golden master), aborts in-flight accel runs, halts seal writes, and drains the
   backfill — **honorable even with Postgres down** (ENV/file short-circuit). Per-optimization feature flags allow
   independent rollback. A runtime RSS watchdog + pre-flight estimator prevent OOM of the shared live process.

**Observable proof at every step:** per-stage timers, cache tier-hit/miss/refetch counters (`bybit_kline_calls`,
`sealed_day_fetched_once`), an always-on event-loop-lag SLI, JIT timing, and redacted parity-diff logging make
the speedup and the parity measurable, not asserted.

---

## G. Scope

### G.1 In scope

- **Engine internals** (`backtest_engine.py`): SoA dataset, global timeline, merge-walk pointers, numba kernel +
  pure-Python fallback, vectorized barrier fast-path — all **semantics-frozen** (P3/P4/P6).
- **Cache subsystem** (`kline_cache_service.py` [MOD] + new `SealedManifest`): completion frontier, day-class
  taxonomy, negative cache, REST `_PAGE_SIZE` 200→1000, outer chunked cold-fill loop, shared circuit breaker
  reuse (P1).
- **Loaders/orchestration** (`backtest_service.py` [UNCHANGED-CONTRACT]): new `KlineStore` read seam,
  `DrilldownLoader`, batched signal/kline/trade SQL, `executemany`/`COPY` persist, atomic 3-write transaction +
  read-side torn-persist guard, terminal-state CAS arbitration, **boot-time `RunReaper` crash-orphan reclaimer (M.14
  — CAS-writes `interrupted_by_restart` on `running`/`queued` rows left by a dead process generation, releasing slot +
  reservation), FIFO queue-drain promotion, and aggregate-RSS admission** (P2/cross).
- **Sweep** (`sweep_tools.py`/`sweep_repo.py` + new `SweepRunner`): parallel fan-out, shipped-once inputs, batched
  array-bound persist (P2/P6).
- **Storage** (new `KlineStore` tiers + Parquet/Feather layout): Arrow hot cache, mmap Feather, DuckDB read engine,
  derive-coarse-from-fine (P5).
- **Database**: **v58 migration** — sealed-manifest columns on `kline_cache_coverage`, `bt_flag_config` control
  table, `sor_data_generation`/`sor_identity` singletons, seal-backfill marker, additive fingerprint/stage-timing
  columns on `backtest_runs`/`_results`/`sweep_results` — additive/expand-only, callable, idempotent, +
  deferred `SealBackfillRunner` (P1).
- **Dependencies**: `accel` optional extra (numba/llvmlite/pyarrow/duckdb), import guards, lockfile, pip-audit (P4/P5).
- **Observability**: per-stage timers, cache counters, loop-lag SLI, parity diagnostics, status route (cross).
- **Rollback**: master kill-switch, per-optimization flags, `CapabilityResolver`/`SafeModeController`,
  shadow/dark-compare mode, CD promotion guard + restore-point (cross).
- **Test harness**: `GoldenMasterOracle` stored-snapshot oracle, golden battery per close-rule branch,
  differential float64-vs-Decimal, two-sided sandwich, property tests, benchmark regression gates, contract
  snapshots (P0, gates all).
- **Admin/maintenance**: `MaintenanceAdmin` CLI-only surface (seal-reset / manifest-rebuild / DR /
  provenance-enumeration), `SymbolLifecycleRefresher` (P1, off the boot path).
- **Frontend**: **no functional change** — only the LTTB downsampler is amended to force-include the global
  max-drawdown trough point (REQ-FE-004); the result contract is preserved and contract-tested.

### G.2 Out of scope

- **Any business-logic change.** TP/SL/sizing/filter-chain/close-rule decisions are frozen. `max_same_sector`
  stays an intentional engine no-op (do NOT "fix" it — D6).
- **AI-Manager backtest feature** (explicitly deferred — CLAUDE.md).
- **Third-party backtest framework** (vectorbt / nautilus_trader on the critical path — ADR-001 rejects;
  nautilus may be a later offline cross-validation oracle only, not on the critical path).
- **Live trading / order-execution path.** The numba/SoA reimplementation is **confined to the backtest engine**;
  the live scanner/auto-trade path keeps calling pure-Python `trading_rules.py` with no numba import (REQ-DEP-025).
- **New required API fields, renamed/removed/retyped keys, schema-contractions in v58** (deferred to a later
  expand-then-contract migration after all pre-v58 pods drain — REQ-ROLL-005).
- **`regime_staleness_minutes` semantics in backtest** (live-only; backtest builds fresh ScanContext per scan —
  accepted N/A for parity).

### G.3 Future (explicitly deferred, not this feature)

- `nautilus_trader` independent cross-validation oracle (off critical path).
- Bulk `public.bybit.com` daily-archive ingest as default (ships behind a flag with untrusted-ingress guards, or
  stays out of scope — default REST only).
- Schema-contraction migration (drop/rename of any deprecated column) — a separate later migration.
- AI-Manager-in-backtest simulation.

---

## H. Functional Requirements

> FRs are **grouped by functional area**, not enumerated 1:1 against the 517 requirements. Each FR is testable,
> names its owning component, cites its anchor REQ-IDs, and carries a phase tag. The full category→FR→phase→test
> mapping is in §Y. **Every FR is subordinate to the Prime Directive: it changes HOW, never WHAT.**

### H.1 Parity & correctness (frozen semantics) — owner: `GoldenMasterOracle` (§3.7) + frozen `engine_kernel` (§3.4)

- **FR-001 — Intrabar exit precedence is frozen.** The optimized engine MUST resolve within-candle exits in the
  exact legacy order **liquidation → SL → TP**, pessimistically: on a dual SL+TP touch SL wins; SL fires only if
  closer than the liq price; the existing `>0` PnL-fabrication guards are retained. *(REQ-PAR-001; P0/cross)*
- **FR-002 — Within-candle rule order is frozen.** The fixed order **funding → per-position liq/TP/SL → equity
  cascade → trailing → time** MUST hold; ALL per-position exits resolve before the basket cascade; a position's
  own liq/TP/SL beats a same-bar basket flatten (records TP/SL/liquidation, not equity_*). *(REQ-PAR-002; P0)*
- **FR-003 — Equity cascade order + cycle re-anchor are frozen.** EQUITY_DROP(/SMART) → close_on_profit →
  EQUITY_RISE with early-return on cycle termination; non-smart rules zero `cycle_start_equity` and re-anchor the
  next non-skipped scan to the pinned wallet quantity. The basket equity `E = wallet + Σ open-uPnL` thresholds
  WITHOUT subtracting Σ locked_margin and reads the POST-funding wallet on a boundary bar. *(REQ-PAR-003/005/006; P0/cross)*
- **FR-004 — `EQUITY_DROP_PCT_SMART` one-shot semantics are frozen.** One-shot per scan (`smart_drawdown_fired`),
  closes ONLY intrabar-losing positions, conditional re-anchor, re-arms each non-skipped scan, with the pinned
  cascade fall-through to survivors when a SMART fire does not terminate the cycle. A fixture MUST exercise the
  re-arm. *(REQ-PAR-004; P0; landmine — discovery §8)*
- **FR-005 — `TRAILING_PROFIT` state machine is frozen.** Clear peak when uPnL≤0; below activation preserve peak
  without triggering; peak from bar high(Buy)/low(Sell); trigger when per_unit < peak×0.5; activation derives from
  `trailing_profit_pct` on the same ROI-on-margin-at-leverage basis as TP/SL. *(REQ-PAR-007; P0)*
- **FR-006 — Time-rule order + BREAKEVEN mutation are frozen.** Order **MR `time_stop_minutes` → MAX_DURATION →
  BREAKEVEN_TIMEOUT**; each rule's age-clock reference + boundary inclusivity pinned; BREAKEVEN mutates ONLY TP,
  leaves SL and liq price unchanged, is skipped while trailing is active, with pinned same-bar re-eligibility when
  trailing deactivates. *(REQ-PAR-008; P0)*
- **FR-007 — Wallet accounting is frozen.** `locked_margin` is NEVER deducted at open (only `entry_fee`); a normal
  close adds `wallet_delta`; liquidation deducts `locked_margin` via a separate branch with NO exit fee and NO
  slippage. **Liquidation recorded-PnL identity PINNED to the engine SSOT (R4-F1-batch4 — `backtest_engine.py:1400-1403`
  computes `recorded_pnl = compute_liquidation_pnl(locked_margin, entry_fee) − funding_paid` and
  `trading_rules.compute_liquidation_pnl` returns `−(initial_margin + entry_fee)`, so the recorded PnL is
  `−locked_margin − entry_fee − funding_paid` — NOT the bare `−locked_margin` a prior carve-out asserted, which omits
  the open-time `entry_fee` (deducted at `:1051`) and the lifecycle `funding_paid` (`:1272/1275`) the wallet actually
  loses):** a liquidation trade's `trade.pnl == −locked_margin − entry_fee − funding_paid` with `exit_fee == 0` and no
  exit slippage, and **THIS value is what participates in `Σ trade.pnl`** so the three-way `Σ trade.pnl ==
  net_profit == final_equity − starting_capital` reconciles on any run containing a liquidation (the bare `−locked_margin`
  would break it). *(REQ-PAR-009, NFR-009; P0; R4-F1-batch4)*
- **FR-008 — Sizing math is bit-identical to the Decimal oracle.** `qty = (sizing_capital · capital_pct/100 ·
  leverage) / entry_base_price` floored to `qty_step`; reject `qty < min_qty` and `required_margin > available`
  but ADMIT at exact equality; the floored-to-exactly-0 disposition is pinned; flooring/rounding bit-identical to
  the Decimal oracle. `sizing_capital = running wallet + carried uPnL − Σ locked_margin` marked at last-close ≤
  scan_time, immediate-mode sequential depletion in abs(score) rank order, batch-mode no depletion, legacy
  insertion order preserved. *(REQ-PAR-010/011; P0/cross)*
- **FR-009 — Cycle-gating latches are frozen.** `skip_if_positions_open` skips iff the open book is non-empty at
  scan START (latched at entry), still evaluates close rules, preserves the anchor, does NOT re-arm
  smart_drawdown; empty/zero-admitted/zero-signal scans take the normal admit + re-arm + re-anchor path. *(REQ-PAR-012; P0)*
- **FR-010 — Funding is charged exactly once per boundary.** Once per 0/8/16h boundary via the `(date,hour)`
  dedupe regardless of candle granularity; longs pay / shorts receive (inverted for negative
  `funding_rate_fixed_pct`); applied on the POST-funding wallet the equity cascade reads. *(REQ-PAR-013; cross)*
- **FR-011 — The 17-step filter chain order + the `max_same_sector` no-op + the `fill_to_max_trades` relaxed second
  pass are frozen.** Each of the 17 steps fires
  in the exact legacy order with identical admit/reject outcomes; the **`max_same_sector` step stays an intentional
  no-op** (service emits `max_same_sector_not_enforced`) — it MUST NOT be "fixed". **`fill_to_max_trades` second
  admission pass FROZEN (R4-F1-batch4 — it is a MUST/P0 parity item REQ-PAR-025 ("skip-rejected-and-continue vs
  stop-at-attempts") and a real path-dependent SECOND admission pass in the engine (`backtest_engine.py:422-434`
  batch / `:460-474` immediate, whose own comment notes it would otherwise "diverge from real trading"), but it
  appeared ZERO times in the spec and defaults `false` so the canonical golden master AC-001 never exercises it — the
  identical uncovered-P0-frozen-path gap class that earned `skip_if_positions_open` its AC-006a/T.2a fixture):** when
  `fill_to_max_trades=true` AND the strict pass admitted fewer than `max_trades` this scan, a **relaxed second pass**
  re-evaluates the leftover signals (those whose symbol is not already open), ranked by `abs(score)` descending,
  bypassing ONLY `min_score`/`confidence` (NOT freshness/`max_signal_age_minutes`, NOT `max_trades`), topping the
  per-scan `scan_entered` counter up to `max_trades` — frozen bit-identical to legacy: the **per-scan (not lifetime)
  counter coupling**, the **skip-rejected-and-continue** semantics, the **exact filters bypassed vs retained** in the
  relaxed pass, and the **leftover-ranking + already-open exclusion**. *(REQ-CFG-*, REQ-PAR-025, discovery §3/§8; P0/cross; R4-F1-batch4)*
- **FR-011a — Adaptive-blacklist-from-own-trades semantics are frozen bit-identically across SoA/numba.** The
  adaptive blacklist is a **path-dependent, cross-sectional state latch** (admission decisions derived from the
  run's OWN closed-trade win-rate, keyed by symbol over a lookback) — the kind of "HOW changes WHAT" risk a columnar/
  JIT rewrite can silently break (REQ-PERF-010 even pins an O(1) incremental counter update). Frozen as bit-identical
  to legacy: the **lookback window** (`adaptive_blacklist_lookback_hours`, default 48h sliding), the **min-trades
  threshold**, the **max-win-rate threshold**, the **symbol keying**, exactly **which `close_reason`s count as
  win vs total**, the **`≤T` vs `<T` boundary tie**, and **the point in the scan loop the blacklist is evaluated**.
  **Incremental-vs-recompute equivalence (REQ-PAR-026):** the O(1) incremental win/total counter MUST EQUAL the
  legacy full-history recompute over the sliding window at every scan — proven by a dedicated golden fixture: a
  multi-scan path where a symbol is blacklisted by the run's OWN losing trades AND where closes cross the 48h window
  boundary (entering/leaving the lookback), exercising the tie and the win/total feed. *(REQ-CFG-*, REQ-PAR-026,
  REQ-PERF-010; P0 freeze / P3 parity)*
- **FR-012 — Buy&Hold + auxiliary series are isolated and reconciliation-excluded.** The B&H BTC baseline is
  reproduced on a fully isolated legacy first-vs-last-close path and EXCLUDED from the `Σ trade.pnl` reconciliation
  even when BTC/USDT is itself traded; auxiliary series (B&H, btc_vol, MR-mean) are valued off the SAME forming-day
  snapshot the engine consumed; degenerate/malformed scan_source fields are dispositioned byte-identically without
  raising; an open position on a symbol whose klines end mid-window is force-closed per legacy. **Forming-day
  snapshot-coherency MECHANISM pinned (R4-F1-batch5 — the "same forming-day snapshot" requirement was an OUTCOME with
  no mechanism: the engine main load + the 3 aux reads (B&H, btc_vol, MR-mean) are SEPARATE `get_klines_batch`/
  `get_klines` calls (arch lines 265/267/487, REQ-PAR-045/REQ-STORE-030), so a live-scanner forming-day upsert landing
  BETWEEN them yields a torn cross-read that silently violates parity on any to-present window; under asyncpg default
  READ COMMITTED the multi-batch server-side cursor read (`iter_klines_streamed`) reintroduces the same hazard across
  FETCH batches):** the run **captures forming-day bars for EVERY needed symbol (engine main + B&H + btc_vol + MR-mean)
  ONCE into a single in-process forming-day buffer at SoA-build time**, via a **single SHORT read transaction that
  commits IMMEDIATELY** (NOT a `repeatable_read` snapshot held across the ≤120s run — that pins `xmin` and is the
  pool-exhaustion/xmin-horizon hazard the arch fails-fast on, R5-F3-batch5); ALL consumers (engine + every aux series)
  read forming-day values from THAT buffer, never re-query. The streamed/cursor multi-batch read is pinned to a
  `repeatable_read` snapshot for its own duration so its FETCH batches are mutually coherent. *(REQ-PAR-045,
  REQ-STORE-030; cross; R4-F1-batch5)*
- **FR-013 — Sentinel "disable" config values are truly inert.** `max_drawdown_pct==100` never fires EQUITY_DROP;
  off-sentinel stop_loss/take_profit/trailing never fire — byte-identical to a config omitting them; any vectorized
  fast-path is provably gated to configs where it equals the sequential engine. **Fast-path eligibility predicate
  ENUMERATED (R3-F7-batch1 — it was previously described only narratively/circularly, so the "is this config
  fast-path-eligible" classification test could not be written):** a config is **fast-path-eligible IFF ALL of the
  following hold** (the explicit conjunction under which positions are provably independent, so the vectorized
  per-position barrier scan provably equals the sequential kernel):
  **(1)** NO portfolio-level / cross-position close rule is armed — `EQUITY_DROP_PCT`, `EQUITY_DROP_PCT_SMART`,
  `EQUITY_RISE_PCT`, `close_on_profit_pct`, and any basket-equity-triggered rule are all off/sentinel (these couple
  positions through shared equity, the §B/§C "independent-position" violation);
  **(2)** NO shared-wallet sequential-depletion coupling — sizing does not depend on running wallet balance such that
  one position's fill changes another's size (e.g. fixed notional / independent per-signal sizing, not
  percent-of-remaining-equity that depletes sequentially);
  **(3)** NO adaptive-blacklist-from-own-trades feedback active (FR-011a) — a symbol's eligibility must not depend on
  THIS run's own prior closes (which serializes the timeline);
  **(4)** NO `skip_if_positions_open` cycle-gating latch (FR-009) and no `max_same_direction`/sector concentration
  cap that reads the live open book (path-dependent admission);
  **(5)** drill-OFF (intrabar coupling is the sequential lane);
  **(6)** every active close rule is a **STATIC per-position first-touch barrier evaluable from that position's own
  price path alone — TP / SL / liq / `MAX_DURATION` (a fixed-age barrier)**. **`TRAILING_PROFIT` and
  `BREAKEVEN_TIMEOUT` are EXPLICITLY INELIGIBLE → route to the sequential kernel (R5-F1-batch4 — the prior clause
  listed them as eligible, DIRECTLY CONTRADICTING the controlling REQ-ENG-029 ("gated EXACTLY on max_drawdown_pct≥100
  AND not close_on_profit AND target_goal_type!='profit_pct' AND NOT trailing_profit_pct AND NO breakeven mutation")
  and REQ-ENG-030 ("any config with ... trailing_profit, breakeven mutation ... is ROUTED to the sequential
  kernel"): TRAILING_PROFIT is a ratcheting peak whose exit barrier MOVES within the position's own life (trigger =
  per_unit < peak×0.5), and BREAKEVEN_TIMEOUT MUTATES the TP barrier after an age threshold — both are
  MOVING/MUTATING within-position barriers, so the vectorized first-touch STATIC-barrier sandwich (REQ-PERF-045)
  provably CANNOT reproduce them; a `BT_USE_FASTPATH` run with only TRAILING_PROFIT (or only BREAKEVEN_TIMEOUT) armed
  would otherwise route to the vectorized scan and silently diverge from the sequential kernel on the P6 lane)**;
  **(7)** `fill_to_max_trades` is OFF (R4-F1-batch4 — the relaxed second pass is a path-dependent per-scan
  `scan_entered`-counter coupling that re-admits previously-rejected signals up to `max_trades`, i.e. exactly the
  cross-sectional "live admission count" coupling clause (4) guards against; a `BT_USE_FASTPATH` run with
  `fill_to_max_trades=true` would otherwise route to the vectorized independent-position scan and silently diverge —
  so a config with `fill_to_max_trades=true` is path-dependent ⇒ INELIGIBLE ⇒ routes to the sequential kernel).
  A config failing ANY clause is **ineligible and MUST route to the sequential kernel**. **This conjunction is
  RECONCILED with the eligibility SSOT REQ-ENG-029/030 (R5-F1-batch4): clauses (1)/(6)'s no-portfolio-rule +
  no-trailing + no-breakeven exactly mirror REQ-ENG-029's `max_drawdown_pct≥100 AND not close_on_profit AND
  target_goal_type!='profit_pct' AND not trailing_profit_pct AND no breakeven mutation`, and "anything ambiguous
  routes sequential and is validated against it" is REQ-ENG-030's property.** *(REQ-PAR-040, REQ-ENG-029/030; P6; R5-F1-batch4)*
- **FR-014 — Accelerated-path failure restarts the whole run clean.** A mid-run failure of numba/DuckDB/Parquet
  restarts the WHOLE run on the pure-Python/Postgres path (never continue-from-failure splicing two engines'
  partial state); the recovered result is byte-identical to the oracle. **Combined-time budget (REQ-PERF-042):** the
  SUM of (failed accel attempt + full pure-Python fallback rerun) MUST fit the 120s cap. This is enforced by
  **fail-fast accel health validation at boot/warmup/first-combo** (so an accel failure is detected within the first
  seconds, NOT after ~90s of a HEAVY run) AND by **freeing the failed attempt's allocations before the fallback**
  (no double-RSS). A **deps-absent fallback-lane regression gate** carries its own frozen baseline so the
  pure-Python recovery path cannot silently regress. *(REQ-PAR-041, REQ-ROLL-012, REQ-PERF-042; cross)*

### H.2 Engine data-layout rewrite (parity-neutral) — owner: `SoADatasetBuilder` (§3.3) + `engine_kernel` (§3.4)

- **FR-015 — Per-scan window setup scales with window size W, not N_total.** Replace the `continue`-on-both-bounds
  full-list walk in `_evaluate_candles_until` with a `searchsorted`/slice so a test that 4×-es the pre-window
  history at fixed W leaves per-scan setup time constant within ±10%. *(REQ-ENG-001; P3)*
- **FR-016 — The merge-walk evaluates EXACTLY the legacy bar set.** The replacement evaluates exactly the same
  half-open `[current_time, next_scan_time)` bars as the legacy window scan (same first/last bar, same
  inclusive/exclusive boundary) — no rule fires one bar early/late; proven by a boundary-bar fixture. *(REQ-ENG-002; P3)*
- **FR-017 — Price location is O(log N)/amortized-O(1), bit-identical.** "last close ≤ T" / "first open ≥ T" use
  `np.searchsorted(side='right')-1` / non-resetting merge-walk pointers reproducing the linear-prefix mark-seed
  BIT-IDENTICALLY (RC-1/RC-2); an out-of-order intra-scan query falls back to `searchsorted` O(log N) — never
  rescans O(N) or resets the pointer. Boundary fixtures cover empty/single-candle arrays, signal before first /
  at-or-after last candle, the epoch-vs-datetime `open_time` case — no path raises `IndexError`. *(REQ-ENG-003/004/005/006/007; P3)*
- **FR-018 — Basket-equity recompute cadence is once-per-tick (verified before frozen).** A **P0 verification
  step** reads the legacy `_evaluate_candles_until`/`_eval_equity_core` code and records the ACTUAL recompute
  cadence relative to the symbol loop as cited evidence BEFORE the once-per-tick oracle is frozen. The optimized
  engine recomputes `E = wallet + Σ open-uPnL` and fires equity rules **once per timeline tick over the open
  book** (NOT once per symbol-candle) — the frozen parity oracle. If legacy proves per-symbol-candle, that is
  surfaced as a parity-relevant finding and resolved before P3. *(REQ-ENG-032, REQ-PAR-006, REQ-PERF-032; P0→P3)*

### H.3 Sealed-day cache manifest (kills the re-download) — owner: `SealedManifest` (§3.2) + `KlineCacheService` [MOD] (§3.8)

- **FR-019 — Gap detection becomes "unsealed days in `[start, frontier]`".** Coverage is decided by the seal flag,
  NOT count-vs-expected. A day seals once `day_end_utc ≤ frontier(now)` AND it is within `[listing_time,
  delist_time]` AND all stored candles are OHLC-valid AND durably committed. The `get_coverage_gaps` count-vs-max
  primitive (the RC-3 bug) is removed. **Read-path lazy-seal-from-SOR — REQUIRED to close the post-v58/pre-backfill
  window (R2-F2-batch2 — `sealed BOOLEAN NOT NULL DEFAULT false` instantly stamps EVERY pre-existing coverage row
  unsealed, so the first run after v58 would see the ENTIRE history as a gap and `ensure_coverage` would re-download
  it — RC-3, the headline bug this feature kills, re-opened for the whole window between v58 apply and
  `SealBackfillRunner` completion, which is deferred + throttled and therefore long):** the runtime READ/gap-detection
  path, BEFORE computing any Bybit fetch span, evaluates the seal predicate against the ALREADY-STORED `kline_cache`
  rows and **lazily seals complete past-frontier days IN-PLACE from the SOR (0 Bybit calls)** — so the gap-fill
  targets ONLY genuinely-missing bars, not already-complete-but-not-yet-backfilled days. The pinned ordering is
  **lazy-seal-from-SOR → gap-compute → fetch** (the seal-upsert failure path is the same next-run lazy-seal of
  NFR-017/S.11, generalized to the cold-start window). This makes the seal flag self-healing on read regardless of how
  far `SealBackfillRunner` has progressed. **Read-path lazy-seal write-amplification bound (R3-F5-batch3 — the first
  canonical run over a complete-but-unsealed window is ≈4,500 (90d×50sym) per-day seal evaluations + in-place
  coverage UPDATEs on the latency-critical path inside the 120s run, previously unbudgeted):** the read-path
  lazy-seal is **scoped to ONLY the days the run actually READS** (the `[start, frontier]` window for this run's
  symbols — NOT the whole corpus) and is **batched** (a single set-based UPDATE per symbol-month chunk, not a
  per-day round-trip); bulk sealing of days OUTSIDE the run's window stays the deferred `SealBackfillRunner`'s job.
  The lazy-seal term is **folded into the run latency model** (a `lazy_seal_ms` stage timer, R.1) and is included in
  the ≤60s/≤90s budget rather than treated as free. **Sha disposition (R3-F5-batch3):** a lazy-sealed day **computes
  and stores its `content_sha256`** (the FR-025 canonical hash) from the SOR rows it reads in the same pass — it does
  NOT leave a NULL-sha row (consistent with FR-050's `SealBackfillRunner`); residual NULL-sha days remain covered by
  the NFR-016 sampled backstop. *(REQ-CACHE-*, REQ-STORE-001..011, R2-F2-batch2, R3-F5-batch3; P1 — gated by AC-007b)*
- **FR-020 — A sealed day is immutable and fetched exactly once ever.** Reruns over a fully-sealed range issue **0
  Bybit calls**; a sealed day's lifetime fetch count is **exactly 1** across N reruns (mock-client `call_count==1`
  test). Only the `(max_stored_ts → frontier)` gap is ever fetched. *(REQ-CACHE, Prime Directive; P1)*
- **FR-021 — Day-class taxonomy + negative cache.** The manifest encodes a mutually-distinguishable day-class enum
  (`0=unsealed, 1=sealed-full, 2=sealed-short-listing, 3=sealed-interior-structural-gap, 4=sealed-empty-negative,
  5=sealed-delist-snapped, 6=derived-coarse`). Negative-cache classes (pre-listing/post-delist/known-gap) are
  never re-probed. *(REQ-STORE-009; P1)*
- **FR-022 — Ambiguous interior holes get a one-shot post-frontier reverify.** An interior hole that may be a
  legacy-bug artifact seals as `day_class=3` with `gap_count`/`gap_ranges` AND `reverify_pending=true` (held WARM,
  never permanent negative-cache) until exactly one post-frontier re-fetch settles it — clear to confirmed gap, or
  re-seal class 1/2 if filled. Prevents the false-permanent-cache failure the seal model exists to kill. **Fetch-
  eligibility predicate reconciliation (R2-F3-batch2 — a `sealed=true, reverify_pending=true` row would be EXCLUDED
  by a bare `NOT sealed` gap predicate AND by a `WHERE NOT sealed` index, so the mandated one-shot reverify fetch
  would have NO trigger path and the V-7 false-negative-cache mitigation would be non-functional):** the fetch-
  eligible set is **`(NOT sealed) OR reverify_pending`**, NOT bare `NOT sealed`; the supporting partial index
  `idx_coverage_unsealed` is `… WHERE NOT sealed OR reverify_pending` (N.4) so a class-3 reverify-pending day is
  index-covered and selected for exactly one post-frontier fetch, after which it clears `reverify_pending` (confirmed
  gap) or re-seals class 1/2 (filled). *(REQ-MIG-014, R2-F3-batch2; P1)*
- **FR-023 — Completion frontier is a monotonic UTC ratchet with skew margin.** `frontier(now) = floor((now_ms −
  skew_margin_ms)/(T*1000))*(T*1000)`, persisted as `max(prev, computed)` — a backward clock step NEVER un-seals.
  `skew_margin` is a documented range-validated config (default 1×T). The runtime loader and `SealBackfillRunner`
  call the **same** frontier function. All bucketing/frontier/lifecycle/Parquet-path math is **UTC-only** (zero
  naive-local/DST leakage on the Windows host). *(REQ-CACHE-006, REQ-MIG-012, REQ-STORE-010; P1)*
- **FR-024 — Lifecycle bound: NULL lifecycle ⇒ fetch-everything, never auto-seal-empty.** The `[listing_time,
  delist_time]` clause comes from `symbol_lifecycle`; an absent/NULL row means fetch-everything (never "out of life
  ⇒ seal known-empty"), so a wrong/empty lifecycle can never permanently negative-cache real data. *(REQ-MIG-011; P1)*
- **FR-025 — `content_sha256` canonical hash reconciles all three physical representations.** Rows sorted ascending
  by `open_time`; time as int64-ms epoch (`floor(extract(epoch)*1000)`, asserted exact on the 5m/1m grid); OHLCV as
  IEEE-754 raw 8-byte little-endian float64 (`struct.pack('<d')`); fixed column order. A tri-source hash-equality CI
  test (fresh Bybit ingest vs Postgres-read-rebuild vs Parquet-rebuild over one sealed day) is the gate. A NULL sha
  reads as "no comparable hash" (no check, no refetch, no raise), NOT a mismatch. *(REQ-STORE-003/004; P1/P5)*
- **FR-026 — Failed/429/timeout responses never seal.** A day seals only on durable valid rows past the frontier;
  a Bybit failure/429/timeout can never produce a false negative-cache. The shared circuit breaker
  (`backend/mcp/core/breaker.py` instance — reused, not reimplemented) coordinates backoff across kline + instrument
  + drill fetch paths; a priority/quota layer in front keeps backtest cold-fill below live-trading Bybit access.
  *(REQ-CACHE-007/028, REQ-OBS-029; P1)*

### H.4 Loaders, drill-down & sweeps — owner: `KlineStore` (§3.1), `DrilldownLoader` (§3.5), `SweepRunner` (§3.6)

- **FR-027 — Batched signal/kline/instrument loads (N+1 → 1).** `_load_klines` and signal/instrument fan-out use
  one batched query (`symbol=ANY($1)` + `BETWEEN`), removing S−1 serial round-trips; per-run Postgres round-trip
  SUM is O(1) in scan/candle count; every batched SQL uses FIXED parameterized text (no string-interpolated
  `IN`-lists) so asyncpg's prepared-statement cache stays bounded across a sweep. *(REQ-PERF-016/017/018/020; P2)*
- **FR-028 — 1m drill-down is lazy, bounded, in-process cached, and persists nothing.** Drill replays only bars
  whose coarse High/Low actually span a barrier (the pre-filter); per-symbol LTF is lazy-loaded; an in-process
  memo prevents re-pull on rerun. Drill cost scales LINEARLY with drilled-bar count; non-drilled bars stay O(1).
  *(REQ-DRILL-020, REQ-PERF; P2/P3)*
- **FR-029 — Drill never changes trade SELECTION; only intrabar fill PRICE may differ.** Toggling
  `drilldown_enabled` yields identical positions opened and identical close rules firing in the same order — ONLY
  intrabar fill price may differ (drill-on vs drill-off diff fixture). The 1m fine-walk requires full-book
  coverage; if ANY open symbol lacks a 1m window the engine falls back to 5m (fail-soft) and NEVER fabricates a
  fill. MFE/MAE, trailing peak, and BREAKEVEN activation stay on coarse (5m) extremes even on the drilled path.
  *(REQ-DRILL-011/012/013/016/019; P0/P2/P3)*
- **FR-030 — Drilled fills are non-optimistic + two-sided bracketed.** A property test over synthetic (coarse-bar,
  1m-sub-bar) configs asserts a two-sided sandwich for every drilled trade: drilled PnL ≤ always-LTF oracle
  (non-optimistic) AND ≥ the coarse pessimistic-resolution bound. Entry slippage is applied with the same
  direction/bps as the 5m path, neither dropped nor double-applied. A 1m drill FETCH FAILURE on an individual bar
  falls back to 5m for THAT bar only — never aborts, never persists partial 1m, stays non-optimistic. *(REQ-DRILL-017/018/022/023; P0/P2)*
- **FR-031 — Sweeps fan out across cores with shipped-once shared inputs.** `SweepRunner` parallelizes combos via
  the **capability predicate `USE_PROCESS_POOL = shared_memory-usable AND start_method=='spawn'` (DECOUPLED from
  `HAS_NUMBA` — R4-F3-batch5: gating multiprocessing on `HAS_NUMBA` was a performance defect that stranded the
  no-numba (D5-binding) host — pure-Python combos parallelize across PROCESSES fine (no shared GIL), and that host
  needs process-level parallelism MOST since it is the one host where the GIL serializes a ThreadPool; the prior
  `HAS_NUMBA AND …` predicate gave a no-numba host neither ProcessPool nor a working nogil ThreadPool (the nogil
  kernel itself requires numba) and dropped it to sequential)**
  — resolves identically on dev + prod for a given host; the Windows-11 PRIMARY prod host satisfies it → ProcessPool +
  `shared_memory` (with numba present, the per-combo engine is ALSO the fast numba lane). A host failing the predicate
  (no usable `shared_memory` / no `spawn`) falls back to a bounded `ThreadPoolExecutor` over the `nogil=True` kernel
  **when `HAS_NUMBA` is true** (the nogil kernel releases the GIL); final fallback sequential —
  `BT_PARALLEL_SWEEP`, never `asyncio.gather` over sync CPU. **`concurrency` is DEFINED for BOTH pool types
  (R4-F3-batch5):** for ProcessPool it is the resolved worker-process count; for the ThreadPool-over-nogil path it is
  the effective worker count — recorded as a concrete integer per host in the run manifest either way (NFR-005).
  **Phase-staging of the shared-SoA
  guarantee (CORRECTED — the compact SoA and `SoADatasetBuilder` do NOT exist until P3, so the "ship the SoA snapshot
  once / IPC + RSS independent of combo count" guarantee is RE-TAGGED to P3/P6, NOT P2):** at **P2** the parallel
  fan-out shares only the **legacy per-symbol kline lists** (parallelism + IPC-independence-of-combo-count + breaker
  semantics are gated on a SMALL fixture — AC-016 — but NOT the compact-RSS guarantee, since legacy lists are not
  compact). From **P3 on**, the **compact SoA snapshot ships once**: aggregate IPC bytes independent of combo count;
  process-tree RSS ≈ `base_snapshot + C×small-per-combo-working-set`, NOT `C×full-kline-bytes`. **Windows
  `shared_memory` cleanup contract:** each segment is released when the creating process's last handle closes (no
  POSIX `resource_tracker`); a terminal-path test asserts no leaked segments. *(REQ-SWEEP-002/003/006/008; P2
  parallelism / P3 shared-SoA RSS-IPC / P6)*
- **FR-032 — Sweep parity: each combo equals a standalone backtest of that exact config.** A single sweep combo's
  persisted result equals a standalone `backtest_run` of that config; `optimize_config`'s PROPOSED config
  reproduces the per-combo metrics it was ranked on; the batched ranking persist uses UNNEST array binding +
  `executemany` + `COPY` (no inline `VALUES`). **Drill scoping (R2-F2-batch4 — the sweep runs the pure engine that
  bypasses drilldown (J.2/§E), so for a `drilldown_enabled=true` config the standalone drill-ON run applies 1m
  intrabar fills the combo did not, diverging within <1% but NOT equal; an unscoped "equals a standalone run" claim
  would break the optimize/propose workflow):** the equality is scoped to **drill-OFF** — sweeps coerce
  `drilldown_enabled=false`, the "equals a standalone `backtest_run`" claim is asserted against the **drill-OFF**
  standalone. **PROPOSED-config drill disposition (R3-F11-batch3 — the prior "the PROPOSED config carries the
  drill-off coercion" would LEAK a backtest-internal performance artifact into the LIVE `AutoTradeConfig` a human
  applies, silently flipping `drilldown_enabled` — a genuine BUSINESS config field, NOT one of the 6 INFRA flags
  REQ-CFG-013 guards — to a value the user never chose):** the sweep ranks combos on the drill-OFF result
  INTERNALLY, but the **PROPOSED config PRESERVES the user-supplied `drilldown_enabled` value** (it is NOT coerced to
  false in the proposal); the ranked metric is **annotated as drill-off-derived** (e.g. a `ranked_drill_off: true`
  provenance flag on the proposal) so the human knows the ranking used drill-off and that a drill-ON re-run may
  differ within <1%. Thus a human re-running the proposal reproduces the ranked metrics ONLY when they also run
  drill-OFF, and that caveat is surfaced rather than hidden by a silent field flip (AC-017)
  (REQ-CFG-013 covers the 6 infra flags; `drilldown_enabled` is now explicitly covered as a business field that the
  proposal must NOT silently alter). The live-trading breaker stays a parent-side dispatch gate — a
  sweep pauses/sheds under an open breaker and runs in its own pool (not the 3 live UI slots). *(REQ-PAR-043, REQ-SWEEP-009, R2-F2-batch4; P2/P6)*

### H.5 Storage tiers & columnar layout — owner: `KlineStore` tiers (§3.1) + Parquet/Feather layout (§4.3)

- **FR-033 — Layered read with sealed-only hot tiers; forming day is Postgres-only.** `KlineStore` routes any
  range including `≥ completion_frontier` **exclusively to Postgres primary**; Arrow hot frames (≤150MB LRU), mmap
  Feather, and Parquet hold **sealed data only**. The forming UTC day never enters a hot tier (removes the
  frontier-advanced-evict race). Two reruns straddling a 5m boundary both reflect fresh forming-day rows. *(REQ-STORE-030; P2/P5)*
- **FR-034 — Sealing is independent of materialization; Postgres is the SOR.** `sealed` depends only on the
  Postgres SOR; `materialized` (Parquet fsync'd+renamed) is best-effort and a distinct column. A Parquet file that
  rots (sha256 + row-count mismatch) is invalidated and rebuilt from the Postgres SOR; seal never depended on the
  file. Bulk pre-materialization is a bounded/resumable/throttled background job OR strictly lazy-on-first-touch —
  never an unbounded synchronous mass-build at P5 deploy. *(REQ-STORE-026/027/028/037; P5)*
- **FR-035 — Derived-coarse equals legacy native-coarse.** With `BT_DERIVE_COARSE` on, 15m/1h/4h bars are derived
  from the sealed 5m base (`day_class=6`, carrying `fine_base_generation`); a regenerated fine base auto-invalidates
  stale coarse. The flag-OFF fallback is the legacy NATIVE per-interval fetch/load path (byte-identical
  klines+trades) — the documented rollback lever. A flag-OFF native-1h byte-identical parity test gates it.
  **Sealed-5m-base precondition (R2-F6-batch4 — without it, a coarse-interval backtest requested over an uncached
  window with `BT_DERIVE_COARSE` on would force a 5m cold-fetch ≈12× the candle volume of the requested 1h range to
  derive the coarse bars, regressing the very cold-fill cost it claims to optimize and unbounded vs the flag-OFF
  native path AC-032 compares against):** derive-coarse **engages ONLY when a sealed 5m base for the window already
  exists**; if no sealed 5m base is present, it **falls back to the native per-interval fetch/load path** (the
  documented flag-OFF lever) rather than triggering a 12× 5m cold-fetch. (Pre-materializing the 5m base is a separate
  explicit warmup decision, never an implicit side effect of a coarse backtest request.) *(REQ-STORE-024, REQ-ROLL-015, REQ-TEST-030, R2-F6-batch4; P5)*

### H.6 API lifecycle & result contract — owner: `BacktestService` [UNCHANGED-CONTRACT] (§3.8) + routers

- **FR-036 — Every existing endpoint signature, request schema, and response shape is unchanged.** The **9**
  endpoints in `backend/routers/backtest.py` (the real route set — §B/K.1, R3-F1-batch6, NOT "10") keep identical
  signatures; MCP `backtest_run` params stay 1:1; the
  refactor adds zero new required fields and renames/removes/retypes nothing. New fields are optional + nullable
  only. **`GET /backtest/{id}/trades` REAL contract pinned (R4-F2-batch4 — the prior "index-backed cursor/limit-
  paginated with latency flat as rows grow" mis-stated the live API: `routers/backtest.py:111-128` is `page` (ge=1) +
  `limit` (ge=1,le=500) + `sort_by` + `side`/`close_reason` filters, i.e. OFFSET pagination, and the only index is
  the single-column `idx_backtest_trades_run ON backtest_trades(run_id)` (async_persistence.py:722); OFFSET is
  O(offset) NOT flat-as-rows-grow, and `sort_by` on any non-`run_id` column forces a full Postgres sort with no
  covering index — so freezing a "cursor schema" was itself a regression risk because the live contract is
  page/limit/sort_by):** the FROZEN no-regress contract is the REAL `page`/`limit`/`sort_by`/`side`/`close_reason`
  OFFSET pagination; the "latency flat as rows grow" guarantee is **WITHDRAWN** (OFFSET is O(offset) by construction).
  IF flat keyset latency is later desired it is a deliberate CONTRACT CHANGE (keyset cursor + a composite
  `(run_id, <sort_col>, id)` index as an explicit additive v58 index with its own AC), NOT covered by this "unchanged"
  FR. The default `sort_by` (`entry_time`) and the `run_id` prefix are the only index-assisted access today.
  *(REQ-API-*, REQ-FE-009; cross; R4-F2-batch4)*
- **FR-037 — `metrics.total_trades` (and the FROZEN canonical metric-key set) are always present + correctly
  typed.** **P0 deliverable — freeze the EXACT key set (not "~45"):** P0 ships a version-tracked snapshot artifact
  `tests/golden/metrics_keys.json` enumerating the EXACT canonical `BacktestMetrics` key set with each key's name +
  type, **including nested per-side / sub-objects** (the real dict is ~62 quoted keys once nested objects are
  expanded; "~45" was an approximate top-level count and is NOT assertable). **Snapshot semantics — REQUIRED-core vs
  OPTIONAL (R3-F9-batch3 — a blanket set-EQUALITY gate fails on legitimately run-conditional keys: drill-only fields,
  mean-reversion/cohort-only metrics, regime-only fields exist only on some run-classes, so strict equality is either
  over-strict (false CI failures) or under-defined):** `metrics_keys.json` declares **two tiers** — a **REQUIRED-core
  set** (incl. `total_trades`) that MUST be present + correctly typed on **EVERY** run regardless of class, and an
  **OPTIONAL set** (drill-only / MR / cohort / regime-conditional keys) allowed to be absent per run-class. The CI
  contract test asserts **`served_keys ⊇ REQUIRED-core` AND `served_keys ⊆ (REQUIRED ∪ OPTIONAL)`** (NOT blanket
  set-equality), with types checked for every present key. Additive evolution only: a new key is added to the
  snapshot (required or optional) in the same change, and a new required key must also be optional+nullable on the
  wire. **Single-typed keys / NO string sentinels (R3-F9-batch2 — see L.4): every numeric metric key is typed
  `number|null` (nullable-number); a degenerate metric (e.g. `profit_factor` on an all-wins run) serializes as JSON
  `null`, NEVER a string sentinel** (a key that is a number on normal runs and a string on degenerate runs is a union
  the single-type snapshot cannot express AND would throw an existing FE `toFixed` formatter — the total_trades trap
  class). The test also pins the `EquityPoint` schema, the
  `page`/`limit`/`sort_by` OFFSET trades-pagination param schema (R4-F2-batch4 — the REAL contract, NOT a cursor
  schema; the prior "cursor schema" mis-stated the live `page`/`limit`/`sort_by` OFFSET API), and the GET envelope shape as additive-only. **`trades_keys.json` +
  `summary_keys.json` (R3-F5-batch5 — the frozen snapshot covered metrics + EquityPoint + cursor + envelope but NOT
  the 19-field `BacktestTrade` RECORD nor the summary-object keys, both named no-regress surfaces in L.1; a
  dropped/renamed/retyped trade field consumed by `GET /backtest/{id}/trades` + the trades-table UI + MCP
  `backtest_get`, or a removed summary key, would escape CI):** P0 ALSO ships `tests/golden/trades_keys.json` (the 19
  `BacktestTrade` fields + `strategy_kind`, names+types) and `tests/golden/summary_keys.json` (the existing
  summary-object keys), asserted **additive-only in the SAME T.9 contract test** so a trade/summary field regression
  fails CI exactly like a dropped metrics key. **Two-tier REQUIRED-core/OPTIONAL model PROPAGATED to
  trades_keys/summary_keys (R6-F4-batch5 — the REQUIRED-core vs OPTIONAL two-tier typing R3-F9-batch3 introduced for
  `metrics_keys.json` (because run-conditional drill/MR/cohort/regime-only keys make blanket set-equality either
  over-strict or under-defined) was NOT propagated to trades_keys/summary_keys, frozen only as "names+types,
  additive-only"; but `strategy_kind` (the 20th trade field) is the MR/cohort marker and is itself run-conditional —
  on a non-cohort/non-MR run it may be absent or null, exactly the class that broke blanket metrics set-equality — so
  a T.9 snapshot asserting `served_trade_keys == frozen_set` would FALSE-FAIL on a non-MR run missing `strategy_kind`,
  while a bare superset leaves REQUIRED-vs-OPTIONAL undefined and lets a genuinely-dropped core field (the V-2
  frontend-trap class for the trades table + MCP `backtest_get`) escape CI):** `trades_keys.json` and
  `summary_keys.json` ALSO declare two tiers — the contract test asserts **`served_keys ⊇ REQUIRED-core` AND
  `served_keys ⊆ (REQUIRED ∪ OPTIONAL)`** (NOT blanket set-equality), types checked per PRESENT key, single-typed
  nullable per L.4. **REQUIRED-core trade fields** = the trade-record fields the trades-table render path consumes on
  every run (`symbol`, `side`, `entry_price`, `exit_price`, `entry_time`, `exit_time`, `pnl`, `close_reason`,
  `qty`/size, `leverage`, fees — the core 19 the table + MCP `backtest_get` render); **`strategy_kind` and any
  cohort/MR/regime-only trade fields are OPTIONAL + nullable** (absent/null on non-cohort/non-MR runs, never
  false-failing the snapshot). A degenerate/zero-trade run returns
  `total_trades=0` present — never the `BacktestResultsPage.tsx:255` "no trades simulated" fallback. Everywhere this
  spec says "~45 keys" it means "the frozen `metrics_keys.json` set". *(REQ-FE-009/008, REQ-API; P0/cross; R3-F9-batch2/F9-batch3/F5-batch5, R6-F4-batch5)*
- **FR-038 — Three result writes commit atomically + a read-side torn-persist guard.** `backtest_results`,
  `backtest_trades`, and the `equity_curve` JSONB commit inside ONE `conn.transaction()`; a crash between them
  rolls back all three and the run is NOT marked `completed`. The GET path reconciles a completed run before
  render — if **the DISCRETE checks fail (trades/curve missing or length-mismatched, trade COUNT off, or a
  duplicated/dropped trade — caught structurally, tolerance-free)** OR `Σ(trade.pnl) != net_profit` (within the
  `continuous-money-epsilon` from P3 on), it returns an explicit integrity error, never a silently-wrong render. The
  structural discrete checks catch a dropped/duplicated/sign-flipped trade even when its money delta is under the
  continuous epsilon (NFR-009 false-negative closure). **The persisted-path `Σ(trade.pnl)` is read back from
  `NUMERIC(20,8)` as Decimal; the guard's tolerance basis is the `trade_count`-scaled epsilon shown to DOMINATE
  worst-case NUMERIC(20,8) quantization (`T×0.5e-8 ≤ T×abs_tol`), not only float64 representation rounding — so the
  guard is reconciled against the PERSISTED Decimal sum, not just the in-memory float64 sum (NFR-009 / R2-F9-batch2).**
  The `_num` finite/Decimal guard runs over every trade record
  BEFORE the `COPY`/`executemany` buffer is built. **Gated by AC-048c (R3-F6-batch3/F4-batch5/F6-batch5 — the
  write-side atomic-3-write rollback and the GET-side torn-persist integrity-error path previously had prose + a §T
  mention but no Given/When/Then gate): a fault injected between each pair of writes rolls back all three and the run
  is NOT `completed`; a deliberately torn/duplicated/dropped/sign-flipped persisted trade trips the structured
  integrity error.** *(REQ-API-007, REQ-PAR-018, R2-F9-batch2, R3-F6-batch3/F4-batch5/F6-batch5; cross — gated by AC-048c)*
- **FR-039 — Exactly-one terminal state under concurrent timeout/finish/cancel; same-run_id single-flight.** The
  transition `running → {completed|failed_with_timeout|cancelled|interrupted_by_restart}` is a guarded atomic
  CAS on `backtest_runs.status` (first writer wins; losers no-op). **`failed_with_timeout` disposition (R2-F2-batch3
  — it appeared as a terminal in this list + the J.1 flow but was NOT in the N.2 stored-enum list, the FR-052 wire
  map, or the CHECK constraint, making it an orphaned persisted status that would either violate the widened CHECK
  or leak unmapped to an old FE):** `failed_with_timeout` is an **INTERNAL/logical label, NOT a distinct STORED
  `status` value** — the 120s-timeout terminal CAS writes the stored status **`failed`** (a legacy-valid value)
  carrying the timeout disposition in a SEPARATE field (`terminal_reason='timeout'` / the aborted-stage marker in
  `stage_timings`), so it is neither added to the `backtest_runs.status` CHECK list (N.2) nor ever emitted as a
  novel wire value. The `queued→running` (slot grant) and
  `queued→cancelled` transitions are ALSO CAS-arbitrated (no double-start, no stuck queued row, reservation
  released exactly once). **Single-flight KEY defined (R4-F3-batch4 — the prior "duplicate `POST /backtest` for an
  already-in-flight run_id (or a single-flight key collision)" was incoherent + untestable: `run_id` is
  server-MINTED as a fresh UUID on every create (`backtest_service.py:199/239`), so two POSTs can NEVER collide on the
  same run_id, and no client idempotency key / config-hash dedupe field exists in the request schema, so the
  described scenario cannot occur):** the single-flight key is an **OPTIONAL client-supplied `Idempotency-Key`
  request header**; when present, a second `POST /backtest` bearing a key matching a still-in-flight (non-terminal)
  run **coalesces to that run's id (returns the same run) or rejects-retriable (`409`)** — never a
  second concurrent execution. When the header is ABSENT, every create mints a fresh run_id and there is NO
  same-run_id collision to guard (the unreachable same-run_id clause is DELETED). **Admission boundary (R3-F1-batch6 — re-modeled onto the REAL one-step create):**
  there is NO `POST /backtest/{id}/run` route; `POST /backtest` reserves the slot synchronously and launches in the
  same request. Today a slot-full create raises `BacktestBusyError`→`503`; the `queued` verdict + `queued→running`
  slot-grant CAS is the NEW admission behavior introduced ON this existing create boundary (no new route), and the
  `AdmissionAccountant` promotes a queued create when a slot frees (FR-039 queue-drain). **Queue-drain trigger +
  ordering PINNED (R3-F5-batch3 — the lifecycle admits queued runs and says the terminal writer releases the slot
  "exactly once", but nothing specified the TRIGGER that PROMOTES a waiting queued run when a slot frees, nor the
  ordering; without it a queued run starves until the next external POST happens to re-evaluate admission):** the
  winning terminal writer's slot-release path (in its `finally`) — or the `AdmissionAccountant` it calls — is the
  trigger that **promotes the next eligible queued run to `running` under a pinned FIFO ordering (oldest `queued_at`
  first)**; promotion is itself CAS-arbitrated so two concurrently-freeing terminals promote two DISTINCT runs (no
  double-promote) and no queued run starves. The `_MAX_CONCURRENT` slot
  + `AdmissionAccountant` reservation release exactly once
  via the winning terminal writer's `finally`. **Queue bound + wait-timeout PINNED (R4-F8-batch3 — the admission queue
  was underspecified on two axes: `queued_timeout` was referenced as an error contract (K.3/FR-040) with no DURATION/
  trigger/test so a run could sit `queued` forever if slots never free; and AC-048b's FIFO promotion had NO MAX QUEUE
  DEPTH, so across clients (the per-client rate limit bounds only one client) the queue is unbounded in memory +
  DB-row growth + FE polling):** a **`BT_QUEUE_MAX_DEPTH`** caps the queue — a `POST /backtest` that would exceed it
  is REJECTED pre-slot with the K.3 `{status:'rejected', reason:'queue_full'}` 4xx/503 capacity contract (no row
  admitted); and a **`BT_QUEUE_WAIT_TIMEOUT_MS`** bounds the wait — a still-`queued` run exceeding it transitions to a
  terminal/timeout disposition returning the `{status:'queued_timeout'}` contract, **releasing its reservation**, and
  the terminal status maps to a legacy wire value per FR-052 (so the FE stops polling). **Concrete range-validated
  defaults PINNED (R5-F6-batch1 — these are security-relevant DoS bounds and must be falsifiable to the same standard
  as `skew_margin`/`T`; an unpinned `BT_QUEUE_MAX_DEPTH` lets a build set it effectively-infinite and pass AC-048h's
  reject test while leaving the cross-client queue-memory/DB-row/FE-poll DoS surface open):** `BT_QUEUE_MAX_DEPTH`
  default **16** (cross-client total, keyed by the W-12 non-spoofable identity so header-rotation cannot evade it),
  `BT_QUEUE_WAIT_TIMEOUT_MS` default **120000** ms; both range-validated and recorded in the run manifest. AC-048h
  gates against THESE pinned values — a `POST /backtest` that would make queue depth `BT_QUEUE_MAX_DEPTH+1` rejects
  `queue_full`; a depth at the limit admits; a run `queued` past `BT_QUEUE_WAIT_TIMEOUT_MS` returns `queued_timeout`. *(REQ-API-012/015, R2-F2-batch3, R3-F5-batch3, R4-F3-batch4, R4-F8-batch3; cross — gated by AC-048b/AC-048h)*
- **FR-040 — Additive runtime status route.** A new non-breaking `GET /backtest-runtime/status` (path PINNED to the
  non-colliding `/backtest-runtime/` prefix — see K.2; a literal `/backtest/status` would be shadowed by
  `/backtest/{run_id}` and 404) reports per-optimization active-vs-degraded state, seal-backfill progress, shared
  breaker state, and `pitr_primary_detector` state. The **public payload is coarsened** — capability booleans +
  active/degraded states only, NO exact version strings, NO full git-SHA, NO integer schema_version, NO numeric
  resource config (those go to a loopback/CLI surface). A reject/queue-timeout disposition returns a distinct
  structured 4xx/503 error contract (`{status:'rejected'|'queued_timeout', reason, pred_ms, pred_rss_bytes}`), NOT a
  completed/zero-trade result row. **MCP reject representation (the MCP `backtest_run` tool has no HTTP status):** the
  same reject/queue-timeout disposition surfaces to the MCP consumer as a **structured tool ERROR / raised exception
  carrying `{status:'rejected'|'queued_timeout', reason, pred_ms, pred_rss_bytes}` — explicitly NOT a completed-shape
  result object** (bolting `status:'rejected'` onto a normal result would itself be the kind of shape change K.4
  forbids). This MCP reject error shape is added to the K.4 MCP schema-snapshot so the reject path is contract-covered
  on BOTH the HTTP and MCP surfaces. *(REQ-OBS-029/035/039/040/043, REQ-API, REQ-SEC-005; cross)*

### H.7 Observability — owner: structured-log counters/timers + parity-diff + invariant checks (§9)

- **FR-041 — Per-stage timers, exclusive-vs-overlap-aware, survive timeout/cancel/degrade.** Per-run (not
  per-candle) timers (`warmup_ms`, `load_klines_ms`, `soa_build_ms`, `timeline_build_ms`, `phase_a_engine_ms`,
  `phase_b_drill_ms`, `metrics_ms`, `persist_ms`, `jit_warm_ms`, `accel_wasted_ms`). Stages are recorded as spans
  reduced to exclusive occupancy so `Σ(exclusive) == wall_ms ± tol`, with `overlap_ms` capturing concurrency
  savings. On a 120s kill/cancel/degrade, partial timings + counters + flag/SHA fingerprint are still emitted +
  persisted with the terminal reason + aborted stage. *(REQ-OBS-011/012/013; cross)*
- **FR-042 — Cache hit/miss/refetch counters prove the re-download is dead.** Registered metrics:
  `kline_tier_hits{arrow,feather,parquet,postgres}`, `bybit_kline_calls` (0 on a fully-sealed rerun),
  `sealed_day_fetched_once` (==1 across N reruns), `unsealed_days_fetched`, `negative_cache_skips`,
  `postgres_kline_selects` (0 on a warm fully-sealed rerun; == forming-day-only on a forming-tail rerun). *(REQ-STORE-012, REQ-CACHE; cross)*
- **FR-043 — Always-on event-loop-lag SLI + parity diagnostics with redaction discipline.** An `event_loop_lag_ms`
  gauge is bounded for the ENTIRE duration of a backtest AND a sweep (the canary against starving live auto-trade
  coroutines) **— bound PINNED: p99 ≤ 250 ms / ≤5× idle baseline (R.5/R2-F4-batch4)**. `live_scanner_fetch_latency_p95` is measured vs baseline during the v58 DDL, the `SealBackfillRunner`
  window, AND the out-of-band `CREATE INDEX CONCURRENTLY` window **— allowed regression ≤ 20 % over baseline**. Parity-diff + invariant-check logs emit
  ratios/deltas/bucketed values by default (raw absolute money only under an off-in-prod debug flag), honoring the
  platform's `financial_detail=false` redaction. The three-way `Σ trade.pnl == final_equity − starting_capital ==
  net_profit` reconciliation (O(trades), always on) is logged as a boolean pass + bucketed magnitude. *(REQ-PERF-029/030/031/036, REQ-OBS-046; cross)*

### H.8 Rollback, safety & flags — owner: `CapabilityResolver`/`SafeModeController` (§7.2) + `bt_flag_config`

- **FR-044 — Master `BACKTEST_SAFE_MODE` kill-switch, honorable with Postgres down.** One lever forces ALL
  optimization flags effective-off (reproducing the golden master byte-for-byte on the canonical 5m no-drill path),
  cooperatively aborts in-flight accel runs/sweeps (bounded, not waiting out 120s), halts new seal writes, and
  drains the deferred backfill — in the pinned idempotent order (a)flags-off → (b)broadcast-cancel → (c)halt-seal
  → (d)drain-backfill via the injected `SafeModeController`. **Cross-process sweep abort (R3-F6-batch3):** a sweep
  running combos in a `spawn` ProcessPool cannot be aborted by the parent's `threading.Event` (a child process does
  not share it); SAFE_MODE step (b) therefore aborts an in-flight sweep via a **cross-process mechanism (pool
  `terminate()` and/or a per-worker cancel flag in `shared_memory`)** that yields the bounded-wall-clock guarantee
  AND leaves no leaked `shared_memory` segments on forced terminate (gated by AC-048e, tied to AC-019 cleanup). An ENV/file `BACKTEST_SAFE_MODE` short-circuits to
  all-off independent of `bt_flag_config`, so the kill-switch works with the DB unreachable; a failed
  `bt_flag_config` read resolves to last-known-good/ENV-default, NEVER to a more-permissive state. *(REQ-ROLL-001/002, R5-F7/F9-batch; cross)*
- **FR-045 — Flags are DB-backed durable, read-your-writes, re-resolved per run.** A `bt_flag_config` control table
  is the source of truth layered above ENV defaults (precedence ENV-default `<` DB-override); `CapabilityResolver`
  re-resolves `effective = resolve(DB-override ?? ENV-default) AND HAS_<cap> AND boot_validation` per run (not once
  per process), so a flip takes effect on the next run on every instance without redeploy. Re-enabling a flag
  re-runs the per-tier health self-check before serving. The §5.4 status route reports exactly this resolver's
  snapshot (contract-tested equal). **Write-surface + authorization (R2-F1 — pins WHO may WRITE `bt_flag_config`,
  through what surface; the table is the DB-backed source of truth for the boolean accel flags (the 5 accel gates +
  the 2 per-path fallback flags, FR-046/R5-F4-batch4) AND can carry the
  `BACKTEST_SAFE_MODE` master-kill-switch row, so its write integrity is the kill-switch's integrity):** ALL writes
  to `bt_flag_config` (flag flips AND a SAFE_MODE row) are confined to the SAME operator boundary as
  `MaintenanceAdmin` (FR-051 — **CLI / loopback / authenticated-admin only, never bound to the public port**).
  **NO public HTTP route and NO MCP tool may write `bt_flag_config`** — the read-path (`CapabilityResolver`) and the
  §K.2 status route are read-only over it. Disarming SAFE_MODE uses the SAME operator surface as the ENV/file lever
  (FR-044) — a non-operator surface attempting to set SAFE_MODE off is REJECTED. `bt_flag_audit` (N.2) is the
  detective record of each resolved snapshot and is explicitly NOT a control surface (a write to the audit log can
  never change effective state). A test asserts (a) no public HTTP path and no MCP tool can write `bt_flag_config`,
  (b) a write attempt to set SAFE_MODE off from a non-operator surface is rejected, (c) the resolver/status route
  hold a read-only handle. *(REQ-ROLL-003/004, REQ-SEC-007, R2-F1-batch1; cross)*
- **FR-046 — Per-optimization independent rollback + within-run degrade.** **FIVE BOOLEAN accel gates
  (`BT_USE_NUMBA`, `BT_USE_COLUMNAR`, `BT_USE_FASTPATH`, `BT_PARALLEL_SWEEP`, `BT_DERIVE_COARSE`) each gate one
  optimization with a verified fallback (R5-F4-batch4 — the prior "six accel flags ... BT_COLUMNAR_DIR" mis-counted:
  `BT_COLUMNAR_DIR` is a DIRECTORY PATH, NOT a boolean gate — you cannot set a path to "effective-off", and columnar
  enablement is ALREADY gated by the boolean `BT_USE_COLUMNAR`, so `BT_COLUMNAR_DIR` is configuration, not a rollback
  gate)**; a runtime failure in numba/DuckDB/Parquet degrades to the pure-Python/
  Postgres path WITHIN the same run with oracle-identical results. **`BT_COLUMNAR_DIR` is CONFIGURATION (the columnar
  storage path), not a gating flag.** **Plus TWO added per-path runtime-rollback flags
  so the kill-switch genuinely reaches the unflagged phases (closes the P1/P3-have-no-runtime-lever gap):**
  **`BT_CACHE_SEALED_MANIFEST`** (default ON) — OFF falls the cache back to the LEGACY count-based coverage path (a
  behavioral coverage/seal change that V-7 shows can strand data, so it gets its own lever rather than redeploy);
  and **`BT_ENGINE_SOA`** (default ON) — OFF falls the engine back to the LEGACY per-window loop (the P3
  re-architecture's runtime escape hatch). Both fallbacks are parity-asserted to the pre-feature path. **So the
  KILL-SWITCH GATING set is SEVEN BOOLEANS: the 5 accel gates + `BT_CACHE_SEALED_MANIFEST` + `BT_ENGINE_SOA`
  (R5-F4-batch4); `BT_COLUMNAR_DIR` is NOT in it.** **Scope of the
  "one lever reproduces the golden master" claim (CORRECTED):** with all 5 accel flags off, `SAFE_MODE` reproduces
  the **P3 pure-Python SoA** golden master; with `BT_ENGINE_SOA` + `BT_CACHE_SEALED_MANIFEST` ALSO off it reproduces
  **pre-feature (legacy loop + count-coverage)** behavior — i.e. full pre-feature reproduction is a documented
  multi-flag combination, and the master `SAFE_MODE` lever alone targets the accel-off P3 oracle (not pre-feature).
  Phases 1–3 ship effective-on-by-default but ARE now independently revertable at runtime via these flags. A CI
  matrix runs the canonical fixture under every CI-exercised flag combination asserting byte/discrete-identity to the
  canonical baseline AND that `BT_ENGINE_SOA=off` / `BT_CACHE_SEALED_MANIFEST=off` reproduce the legacy path.
  *(REQ-ROLL-012/013, R2-F7-batch5, R5-F4-batch4; cross)*
- **FR-047 — Shadow / dark-compare mode, persistence-neutral + size-capped.** (a) Read-path shadow reads both
  Postgres and columnar, logs byte-divergence, returns authoritative Postgres. (b) Engine shadow samples runs
  through both engines, persists the optimized result, emits a localized divergence payload (trade ordinal/symbol +
  field + magnitude) — bounded to small synthetic configs (the legacy engine cannot finish a real 90d×50sym run
  under 120s) OR an offline replay with its own budget. Both sampling-bounded, off by default in prod; disabling
  removes all dual-execution cost. Dark-mode runs (flags off) still populate v58 fingerprint columns while staying
  oracle-identical. *(REQ-ROLL-016, REQ-OBS-046, REQ-FE-012; P5/cross)*

### H.9 Dependencies (import-guarded optional accel) — owner: `HAS_NUMBA/PYARROW/DUCKDB` guards + `accel` extra

- **FR-048 — New deps are an optional extra; a missing wheel never crashes backend import.** `numba`/`llvmlite`/
  `pyarrow`/`duckdb` live in `[project.optional-dependencies].accel` (floors + ceilings), NEVER base deps. **The
  `duckdb` floor is `>=1.1` and is documented as a SECURITY floor (not just perf) because the §P.3/NFR-020 injection
  lockdown primitives (`allowed_directories`, `lock_configuration`) require it (R2-F5); a boot/CI probe verifies the
  resolved build enforces them or the columnar path fails closed.** Import
  is guarded (`HAS_*` capability flags); a missing/broken wheel degrades to the pure-Python/Postgres path. A
  committed hash-pinned lockfile + CI assert lockfile↔pyproject sync and that numpy simultaneously satisfies
  numba's pin AND pandas' floor; CI verifies PREBUILT wheels install on every deploy target (generic, prod base
  libc, win32) and the windows-latest lane runs the full golden suite green; the dep checks re-run at each phase
  merge touching pyproject/lockfile; pip-audit covers the accel extra. *(REQ-DEP-002/003/026/027/028/029; P4/P5)*
- **FR-049 — Accel is confined to the backtest path; live execution never pays for it.** The numba/SoA kernel is
  CONFINED to the backtest engine; the live scanner/auto-trade ORDER-EXECUTION path keeps calling pure-Python
  `trading_rules.py` with NO numba import, NO JIT warm, NO SoA/columnar dependency — unchanged sizing/barrier
  values, unaffected if the accel stack is absent/broken. All thread pools (`NUMBA_NUM_THREADS`, BLAS/OpenMP,
  DuckDB, Polars) + the numba threading layer are explicitly pinned, derived from the **resolved CPU budget
  (cgroup CPU quota on Linux/[FLEET], OR the explicit `BT_CPU_BUDGET` config / Windows Job Object on the primary
  Windows 11 host — NEVER `os.cpu_count()`/host RAM, per NFR-013/REQ-DEP-022)**. **CPU-budget partitioning across the
  shared host (closes the `_MAX_CONCURRENT=3` + sweep oversubscription hole):** the resolved compute-thread budget is
  partitioned by a **global compute-thread semaphore** so that the SUM of threads across all active backtest slots
  (up to `_MAX_CONCURRENT=3`) PLUS the sweep pool never exceeds the budget — concretely, per-slot thread cap =
  `max(1, floor(CPU_BUDGET / active_compute_slots))` recomputed as slots/sweeps enter and leave, with the live
  auto-trade loop reserved a non-preemptible share. Nested parallelism (numba prange × ProcessPool × per-run BLAS)
  therefore never exceeds the budget even under the worst case of 3 concurrent runs + a sweep. Pools are applied
  scoped so they do not regress live-path indicator-compute latency. *(REQ-DEP-020/021/022/023/024/025; P4/cross)*

### H.10 Admin / maintenance & lifecycle — owner: `MaintenanceAdmin` (§3.12), `SymbolLifecycleRefresher` (§3.11), `SealBackfillRunner` (§3.10)

- **FR-050 — Deferred, resumable, throttled seal backfill off the boot path.** Sealing historical days runs in a
  separate `SealBackfillRunner` (NOT inline in the v58 migration): bounded/set-based chunked-commit UPDATE within a
  statement budget, idempotent, resumable from its own checkpoint marker (enumerated states
  not_started/in_progress/complete), mutating ONLY coverage/manifest + `symbol_lifecycle` rows — NEVER a
  `kline_cache` candle row (before/after content-hash diff proves every candle byte-identical). **It computes
  `content_sha256` (the FR-025 canonical hash) from the SOR candle rows it reads while sealing, so a backfilled day
  is hashed + verifiable, NOT NULL-sha (R2-F7).** It throttles to not
  regress live-scanner fetch latency, uses disjoint advisory-lock keys, and is paused/resumed by SAFE_MODE. *(REQ-MIG-018/019/021, REQ-STORE-003; P1)*
- **FR-051 — Lifecycle reclassification + maintenance admin are non-destructive + guarded.** `SymbolLifecycleRefresher`
  may UPDATE the MUTABLE-post-seal columns (`listing_snapped`, `delisted`, `day_class`) when lifecycle data arrives
  late WITHOUT un-sealing, refetching, or changing `content_sha256`. `MaintenanceAdmin` (seal-reset /
  manifest-rebuild / DR / provenance-enumeration) is **CLI-only — not bound to the public port** — and DB-identity
  guarded; the in-place manifest rebuild-from-SOR seals closed days from existing rows+lifecycle with 0 Bybit
  refetch, interruptible/resumable/idempotent. *(REQ-MIG-015, REQ-ROLL-024/025/030/032/033, REQ-CACHE-049, REQ-SEC-007; P1/cross)*

### H.11 Frontend compatibility — owner: result/trade JSON contract (§5.2)

- **FR-052 — No functional frontend change; the LTTB downsampler force-includes BOTH path-dependent extremes.**
  `_downsample_equity` is amended to always include the first point, the last point, the global max-drawdown
  trough point, **AND the global max-equity (peak / max-run-up) point (R6-F4-batch4 — the trough fix prevented the
  rendered curve hiding the max-DD extreme, but max RUN-UP is an equally path-dependent rendered metric (§L.3 lists
  "run-up" alongside max-DD as order-dependent) and standard LTTB can drop a single-bucket peak the same way it drops
  a single-bucket trough; for the §D "TradingView-class result fidelity" deliverable, hiding the peak on the GET view
  is the symmetric defect the trough fix exists to prevent)** — so the rendered curve cannot hide EITHER the max-DD
  trough OR the max-equity peak, with its golden oracle re-frozen against the
  amended output AND a downsample-preservation fixture asserting BOTH extremes survive downsampling; the manifest still hashes the full pre-downsample JSONB (the trough+peak change affects only the GET
  view, never the hash basis). Old↔new bidirectional deploy-order compatibility is proven (a new FE rendering an
  old response and an old FE rendering a new response both render, surfacing `total_trades` + all shared ~45 keys).
  **New-status-enum safety (CORRECTED — the prior "an old FE encountering a new status enum degrades gracefully"
  claim is FALSE against code: `BacktestResultsPage.tsx` only branches `pending|running|failed|cancelled|completed`,
  so a `queued`/`interrupted_by_restart` value matches NO branch → BLANK body; and `types.ts` `isPending =
  status==='pending'||'running'` treats `queued` as terminal → polling STOPS → permanently blank page).** The
  adopted fix is **option (a): the new internal lifecycle states `queued` and `interrupted_by_restart` are NOT
  surfaced on the public `GET /backtest/{id}` wire — they are MAPPED to existing wire values before serialization
  (`queued → pending`, `interrupted_by_restart → failed`), consistent with the
  additive-only response rule**. **Resumability predicate PINNED (R2-F2-batch4/R2-F5-batch4 — the prior
  `interrupted_by_restart → running if it will resume else failed` left "if it will resume" undefined, and if it
  ever mapped to `running` the FE `isPending` would poll forever for a run that never completes):** a backtest
  persists NO mid-run state and is **NOT resumable** (W-1), so the "will it resume" predicate is **constant FALSE**
  and `interrupted_by_restart` ALWAYS maps to the **terminal** wire value `failed` (polling stops). There is no
  branch that maps it to `running`. Only the additive `GET /backtest-runtime/status` route exposes the granular internal
  states (to clients that opt in). A contract test asserts the GET-result `status` field only ever emits the legacy
  five values, **AND that an `interrupted_by_restart` run reaches a TERMINAL wire status (`failed`) so the FE stops
  polling**, so no existing FE can blank or stop-polling on a non-terminal unknown. (`close_reason` additions like `mr_target` remain
  display-only strings the FE renders generically and never branches on — unaffected.) No path issues `SELECT *`
  against the backtest/coverage tables. *(REQ-FE-003/004/010/013/014/015/016; P0/P5/cross)*

---

## I. Non-Functional Requirements

> NFRs are the measurable quality bars. Each is testable with a pinned threshold + a named gate. Budgets are gated
> on the **canonical fixture: 90 days × 50 symbols × 5m ≈ 1.296M candles over ≈2160 scans** (REQ-PERF-001).
> **Normative definition of "candle-eval" (single source of truth, used by every evals/sec floor — RECONCILED to
> architecture §11.2, R3-F1/F2-batch2):** an *eval* is one **HEAVY position-pass** — the `ticks × B` term
> (`heavy_eval_count`), where `ticks` = distinct timeline timestamps (canonical ≈25,920) and `B` = open-book depth.
> Canonical `heavy_eval_count ≈ ticks × B ≈ 0.13M` (`B≈5`). This is NOT the `candles × B` product (≈6.48M — the
> REQ-OBS-007 meter's *internal-consistency cross-check only* and the "inflated single product" rejected for
> budgeting, see §Q), and it is NOT the LIGHT-blended 1.43M total. **The LIGHT term `O(total_candles)` ≈ 1.296M
> pointer/mark advances (`light_advance_count`) is NEVER folded into `evals/s`** (matching architecture §11.2); it is
> gated SEPARATELY as a per-advance ns micro-gate (NFR-004). **Floor + wall are DIFFERENT scopes (R3-F2-batch2
> correction):** the evals/s floor measures the *engine-only* HEAVY hot loop; the ≤60s budget is the *E2E* wall
> (load+build+engine+metrics+persist). One does NOT imply the other — the earlier "`100k/s × 60s = 6M ≥ 1.43M` so
> the floor is strictly stronger than the wall" worked check is **withdrawn** (it conflated a blended engine count
> with an E2E wall). Each gate is asserted independently: the pure-Python **≥150k HEAVY-evals/s** floor (architecture
> §11.1 hard gate) is the engine regression tripwire; the ≤60s E2E wall is the separate hard latency gate. The
> precise pure-Python floor value is **re-pinned from a profiled P0/early-P3 engine slice** (X-2 estimate ↔ floor
> reconciliation, R3-F2/F3-batch2) rather than asserted from an unprofiled constant.

### I.0a Performance-requirement amendment (REQ-PERF-046) + capability-conditional acceptance

> This block pins two requirement-level decisions the spec relies on. **REQ-PERF-046 has now been backported into
> `backtest-optimization-requirements.md` (R2-F5-batch3), so the binding pure-Python lane budget has a real baseline
> anchor; the capability-conditional acceptance below remains a spec-level elaboration.** REQ-PERF-046 is the ID every
> numba/pure-Python lane budget cites (replacing the non-existent "REQ-PERF-001 lane-split
> amendment" and the mis-applied REQ-PERF-039 latency citation).

- **REQ-PERF-046 — numba/pure-Python lane split + committed pure-Python budget (amends REQ-PERF-001).** The single
  flat "drill-OFF E2E <10s / drill-ON <20s, no lane qualifier" budget of REQ-PERF-001 is formally split into two
  lanes: (a) the **numba lane** carries `<10s` drill-OFF / `<20s` drill-ON as MUST budgets; (b) the **pure-Python
  lane** (numba absent/broken/flag-off) carries a committed `≤60s` canonical / `≤90s` HEAVY-HEAVIEST budget, all
  `< 120s` (the **120s `_TIMEOUT_SECONDS` hard kill is universal and never raised**). The `≤60s` figure is a
  *safety-net TARGET* (≤50% of the 120s cap) scoped to the CANONICAL run-class; the HEAVY/HEAVIEST classes carry
  their `≤90s` committed budget as the documented exception (still `< 120s`), NOT a ≤60s target. **WIDE is NOT in the
  committed pure-Python latency budget (R2-F1-batch4): WIDE latency is a NUMBA-LANE budget (capability-waived when
  `HAS_NUMBA` false); on the pure-Python lane WIDE is RSS/stream/preflight-governed with NO latency commitment and an
  infeasible pure-Python WIDE is REJECTED pre-slot (predicted-wall-time reject term, AC-018), not killed at 120s.**
  This makes the
  pure-Python "minutes alone" deliverable (D5) the binding bar when numba is unavailable, and the numba budgets
  stretch goals gated only when the accel stack loads.
- **Capability-conditional acceptance (binds AC-026/027/030, the P4–P6 ACs, and the D/NFR-001/003 numba-lane
  budgets).** **IF `HAS_NUMBA` is false on the deploy target** (no wheel / ABI break on Py3.14.3 + numpy2.4.4, per
  task #71 / risk V-1), **THEN every numba-lane MUST (bit-identity vs JIT, ≥5M evals/s, `<10s` drill-OFF `<20s`
  drill-ON, the P4–P6 fast-path/columnar-warm budgets) is WAIVED-by-capability**, and the **pure-Python `≤60s`
  canonical / `≤90s` HEAVY lane (REQ-PERF-046) is the binding acceptance bar** for those phases. The waiver is
  recorded in the run/CI manifest (`engine_path`, `accel_waived: true`) so a green merge under waiver is auditable
  and never silently masks a regression on a host that DOES have numba. **No run-class left budget-less AND
  un-rejected (R4-F1-batch6):** the pure-Python `≤90s` is the BINDING gate for HEAVY/HEAVIEST whenever `HAS_NUMBA` is
  false, EXCEPT where AC-024a option (b) downgrades HEAVIEST to numba-required after profiling — in that single case,
  on a no-numba host the pure-Python HEAVIEST lane is parity-only with no latency commitment AND **AC-018's
  predicted-wall-time pre-slot reject is extended to reject the infeasible no-numba HEAVIEST** (resolved threshold =
  the 120s cap with the under-estimate margin), so it is rejected pre-slot rather than admitted-then-killed. The
  per-symbol-candle contingency (Q.2) is handled identically — a "parity-only / no-latency-budget" HEAVY/HEAVIEST
  lane resolves AC-018's reject threshold to the universal 120s cap (R4-F7-batch4).

### I.1 Performance & throughput

- **NFR-001 — Canonical single-run latency.** Warm canonical run: drill-OFF **<10s** (numba lane, stretch 5s) /
  drill-ON **<20s** (numba lane); the **pure-Python lane** ≤60s canonical (≤90s for the HEAVY/HEAVIEST class) so a
  flag-off/degraded run is still bounded. The **120s `_TIMEOUT_SECONDS` stays the UNIVERSAL hard kill for EVERY
  run-class** (the hard constraint — never raised). The separate **≤ 50% of the 120s cap (≤60s)** rule is a
  *safety-net TARGET* scoped to the **CANONICAL run-class** (canonical numba + canonical pure-Python + the drill
  lanes); the **HEAVY/HEAVIEST classes are the documented exception** — their committed `≤90s` pure-Python
  budget is the binding latency bar for those classes, still comfortably under the universal 120s hard kill (`90 <
  120`), even though it exceeds the canonical ≤60s target. **WIDE class latency disposition (R2-F1-batch4 —
  CORRECTED: the prior text listed WIDE in the pure-Python ≤90s commitment, but WIDE (200sym×365d ≈ 21M 5m candles)
  is physically infeasible on the pure-Python lane — at a ~100k LIGHT-advance/s pure-Python rate the LIGHT term alone (≈21M
  advances) is ≈210s, exceeding both ≤90s AND the 120s hard kill; WIDE is feasible only on the numba lane ≈4s):**
  **WIDE latency is a NUMBA-LANE budget, capability-waived (like the P4–P6 ACs) when `HAS_NUMBA` is false.** On the
  **pure-Python lane WIDE carries NO latency commitment** — it is **RSS/stream/preflight-governed** (NFR-004/NFR-012,
  §I.3 WIDE resolution, §S.6): a pure-Python WIDE run that the preflight predicts cannot finish under the resolved-
  lane budget is **rejected pre-slot with the 4xx contract (AC-018), NOT admitted and killed at 120s**. No run of
  any class exceeds the 120s hard cap. *(REQ-PERF-001/039/046; cross.
  **Note:** the numba/pure-Python lane split and the committed pure-Python `≤60s`/`≤90s` budgets are introduced by
  **REQ-PERF-046** (defined in §I.0a below) — a spec-level amendment to be backported into the requirements
  baseline; they are NOT derived from REQ-PERF-039, which governs only WIDE-run OOM streaming/rejection.)*
- **NFR-002 — ≥100× vs the frozen P0 baseline (engine-CPU basis, numba lane).** **Baseline-capture protocol
  (pins what "frozen P0 baseline" means given the 120s cap):** the legacy engine *cannot complete* the canonical
  90d×50sym fixture under the 120s service Timer (§B/§E/§H.8: it hits the kill), so the baseline is NOT a wall-clock
  E2E time on the canonical fixture. Instead P0 captures, in a dedicated `slow`-marked offline harness with the
  `BacktestService` 120s Timer **disabled**, the **legacy engine-only CPU time**. **Baseline basis PINNED to the
  uncapped full-canonical measurement (R3-F3-batch2/F8-batch2/F3-batch2 — the two bases are NOT equivalent for this
  engine: §B/RC-1/RC-2 prove legacy is SUPER-LINEAR in symbols×scans×N_total with a quadratic-in-time seeding term,
  so a LINEAR per-candle × candle-count extrapolation from a small sub-fixture SYSTEMATICALLY UNDER-estimates true
  canonical legacy CPU, deflating the ≥100× ratio and letting a slower-than-intended engine pass the headline gate):**
  the authoritative baseline is **(b) one uncapped full-canonical engine-CPU measurement** — the legacy engine run
  to true completion ONCE on the full canonical 90d×50sym fixture in a one-shot offline job, recording engine-only
  CPU seconds directly. **(a) the reduced-sub-fixture × candle-count extrapolation is permitted ONLY as a documented
  cross-check, and ONLY if it fits a SUPER-LINEAR (`scans×symbols×N`) cost model (NOT a flat per-candle constant)
  carrying an explicit super-linearity correction factor** — it is never the authoritative denominator for the
  ≥100× gate. **SOLE EXCEPTION — the AC-001 6h-fallback case (R6-F4-batch2/R6-F6-batch5):** when AC-001's uncapped
  full-canonical capture exceeds its 6h ceiling, basis (b) is by definition unobtainable; in THAT documented case
  ONLY, the baseline is captured on the resolved 30d×20sym fallback fixture (with the super-linear correction note)
  and the ≥100× multiplier is asserted opportunistically/offline + capability-waived (`perf_baseline_waived`) while
  the absolute ≤60s/≤90s REQ-PERF-046 budgets bind — per AC-001's redefinition clause. Outside that fallback, basis
  (b) on the full canonical fixture remains the only authoritative denominator. The ≥100× gate is asserted **engine-only CPU time, numba lane** (the
  pure-Python lane carries the absolute `≤60s`/`≤90s` REQ-PERF-046 budget instead of a multiplier, since 100× vs an
  uncapped multi-hour legacy baseline is not its binding constraint). The headline scaling test self-normalizes for
  CI-host variance (engine-only CPU / in-process re-measured ratio, NOT dev-frozen wall-seconds); a `slow`-marked
  deterministic regression test asserts a warm rerun does ZERO exchange/DB kline work and fails if runtime regresses
  past a threshold; every cold-timed region resets + asserts-empty all caches. The baseline fixture identity, the
  basis (pinned (b), with any (a) cross-check + its correction factor), and the lane are all version-tracked
  alongside the frozen fingerprint. *(REQ-PERF-003/004; P0/cross; R3-F3-batch2/F8-batch2/F3-batch2)*
- **NFR-003 — Engine candle-eval throughput floors.** "Eval" is the §I-preamble normative unit **= one HEAVY
  position-pass (`ticks × B`, `heavy_eval_count`; canonical ≈ 0.13M), RECONCILED to architecture §11.2** — NOT
  `candles × B`, and NOT the LIGHT-blended 1.43M. The LIGHT term (`light_advance_count` ≈ 1.296M) is gated
  separately as a per-advance ns micro-gate (NFR-004), never folded into evals/s. Post-P3 (SoA, pure-Python)
  **≥150k HEAVY-evals/sec single-core**. **150k disposition RESOLVED to ONE coherent meaning (R6-F2-batch5 —
  the prior label "FIXED PRE-PROFILING HARD GATE" contradicted the very next clause "captured ONCE from an early
  profiled P0/early-P3 slice and FROZEN": a value cannot be both set with NO profiling AND captured from a profiled
  slice):** the ≥150k floor is a **MUST-MEET hard gate (architecture §11.1) whose THRESHOLD VALUE is calibrated ONCE
  from an EARLY profiled P0/early-P3 engine slice and then FROZEN as an absolute constant** used to gate ALL LATER
  phases. "Fixed before the runs it gates" means frozen ahead of the later/final P3–P6 runs — NOT "set with zero
  profiling" (the R3-rejected magic constant) and NOT "a per-run fraction of the gated run's own rate" (the
  R4-rejected self-referential calibration). **Consequence if unmet (R6-F2-batch5 — a must-meet gate must say what
  happens on failure):** IF the early-profiled engine slice itself cannot reach ≥150k HEAVY-evals/s, that is a P3
  ENGINE-DESIGN finding surfaced BEFORE the P3 merge (re-architect/optimize the hot loop, or re-derive the floor with
  a named owner+gate) — it is NEVER silently lowered to whatever the slice measured, and the frozen value, once set,
  is the regression tripwire for every later phase. 5M is a POST-P3-CALIBRATED
  TRIPWIRE (R4-F2-batch5 — reconciled to architecture §11.1/§11.2, which scopes the "fraction-of-measured-rate"
  calibration protocol to the 5M numba tripwire ONLY; applying it to the 150k gate made the primary P3 pure-Python
  regression tripwire SELF-REFERENTIAL — a floor derived from the very run it gates cannot catch a regression in that
  run): the **≥150k** floor is captured ONCE from an early
  profiled P0/early-P3 slice and FROZEN as a constant tripwire for ALL later phases, NOT re-measured/re-derived
  per-run (it is "profiled-once-then-fixed", which is distinct from both "unprofiled magic constant" R3 rejected AND
  "self-referential fraction of the gated run's own rate" R4 rejects). Post-P4 (`@njit` warmed, excluding first-call
  compile) **≥5M HEAVY-evals/sec single-core** is the **post-P3-calibrated tripwire = a fraction (pinned 0.7×) of the
  measured warmed-numba rate captured ONCE and frozen**, NOT a literal pre-profiling absolute; the AC-027/AC-030 merge
  gate is "measured warmed-numba rate ≥ the frozen 0.7×-calibrated floor", not a bare ≥5M literal. **The engine
  evals/s floor and the ≤60s E2E wall are
  DIFFERENT scopes (engine-only hot loop vs full load→persist round-trip); neither implies the other** — the prior
  "≥100k/s is strictly stronger than the ≤60s wall" claim is withdrawn (R3-F2-batch2). Both floors gated on BOTH the
  canonical and HEAVY paths; the evals/s floor is the regression tripwire, the wall budget is the
  separate hard gate. **REQ-PERF-005 backport (R4-F6-batch4 — REQ-PERF-005 in requirements.md previously read "≥100k
  evals/sec single-core" with NO unit qualifier (generic evals), conflicting with this NFR's re-pinned "≥150k
  HEAVY-evals/s (ticks×B unit)" in BOTH value (100k→150k) AND unit (generic→HEAVY-evals); the REQ-PERF-046 lane-split
  was backported but this floor re-pin was not):** REQ-PERF-005 has now been **updated in requirements.md** to "≥150k
  HEAVY-evals/sec (ticks×B / heavy_eval_count unit), re-pinned from a profiled P0/early-P3 slice" with the ≥5M
  recast as the post-P3-calibrated 0.7× tripwire — cross-referencing architecture §11.1/§11.2 and this §I-preamble
  unit definition; the prior "100k generic evals" is superseded. *(REQ-PERF-005; P3/P4; R4-F2-batch5, R4-F6-batch4)*
- **NFR-004 — Linear/sub-linear scaling across the surface.** Setup scales with `Σ(actual per-symbol bounded
  spans)` NOT `N_symbols × full_window` (a 25-dense/25-short fixture shows setup ∝ actual candle volume); per-scan
  context build is O(1)-amortized (doubling scans grows context-build ≤~2×); engine wall-time scales ≤ linearly
  with turnover (10×-ing closes grows engine time ≤~linearly, no O(closes²) rescan); symbol-doubling grows the
  engine ≤2× (LIGHT term `ticks×symbols` and HEAVY term `ticks×B` each gated separately with a per-advance ns
  ceiling). **LIGHT per-advance ns ceiling PINNED (R6-F1-batch2 — the wall-DOMINANT term had NO numeric threshold:
  §I-preamble/NFR-004/T.7 all referenced "a per-advance ns micro-gate" without a value, the SAME unfalsifiable-gate
  defect the spec closed for the ≥150k HEAVY floor / MAX_SWEEP_COMBOS=2000 / under_estimate_margin=1.0; and the
  canonical ≤60s budget is explicitly dominated by the ~1.296M LIGHT advances — 10× the 0.13M HEAVY count — so the
  single largest latency contributor was gated by a test-author-chosen threshold, letting a high-constant per-advance
  regression (e.g. a per-symbol dict/attr lookup) pass silently):** the LIGHT micro-gate is **≥100k LIGHT-advance/s
  single-core ⇔ ≤10,000 ns/advance (≈10 µs)** — captured ONCE from the early-P3 profiled engine slice and **FROZEN as
  an absolute constant tripwire for ALL later phases**, exactly mirroring the ≥150k HEAVY "profiled-once-then-fixed"
  protocol (NFR-003). This SINGLE pinned figure is the one referenced by §I-preamble, NFR-001/NFR-003, Q.2, T.7, and
  the AC-018 WIDE/per-class predicted-wall reject term (so the WIDE LIGHT-term reject point and the canonical
  load/build headroom are all re-derived from ONE rate, not three). It is PROVISIONAL until the P0/early-P3 profile
  lands (like the ≥150k HEAVY floor); the named re-derivation owner+gate is the AC-004/AC-004a measurement path.
  Additional fixture points each carry their **own committed latency+RSS budget** (not "TBD"): **4h-coarse
  canonical** ≤ the same-window native-5m latency (FR-035 derived-coarse must never be slower) at ≤ the canonical
  RSS; **WIDE 200sym×365d** governed by §S.6/NFR-012 (own WIDE total-RSS line, pre-flight/stream path per the §I.3
  WIDE resolution); **HEAVIEST-config** pure-Python ≤90s / numba <30s (Q.1) with peak RSS ≤ its OWN ≤2GB ceiling.
  **HEAVY/HEAVIEST fixture dimensions PINNED (R2-F3-batch4 — they were cited by AC-024a/027/037a but never
  dimensioned, leaving the deep-book worst case with no concrete budget; the canonical's `B≈5` cannot supply a deep
  book, so "derive-by-formula from canonical" could not size B):** **HEAVY = 90 days × 100 symbols × 5m, drill-ON,
  every close rule armed + regime + mean-reversion, peak open-book `B≈20`, high turnover** — committed **≤90s
  pure-Python / <30s numba, peak RSS ≤ its OWN symbol-scaled ceiling (≤1.75GB, NFR-012/Q.3/R3-F4-batch1 — NOT the
  canonical 1.5GB)**; **HEAVIEST = 90 days × 150 symbols × 5m, drill-ON,
  all rules + regime + MR, peak open-book `B≈40` (deep concurrent book), high turnover** — committed **≤90s
  pure-Python / <30s numba, peak RSS ≤ its OWN ceiling (≤2GB, pinned under the WIDE tier — R3-F1-batch4/F4-batch6)**. The HEAVY-term `O(ticks×B)` deep-book worst case is
  thereby budgeted against a concrete `B`. **Worst-case trade count T PINNED per fixture (R4-F6-batch5 — R2-F3-batch4
  pinned book depth B and R3-F4-batch1 pinned per-class RSS, but the "persist <3s trade-heavy" budget (NFR-006/Q.3)
  and the `trade_count`-scaled continuous-money-epsilon for the Σ reconciliation / torn-persist guard (NFR-009/FR-038)
  BOTH scale with total trade count T, and T was left undimensioned ("high turnover" is qualitative), so the <3s
  persist gate was not falsifiable (the test author picks T) and the worst-case accumulated epsilon `T×abs_tol` was
  unbounded):** the worst-case total trade count is pinned **CANONICAL T ≈ 5,000; HEAVY T ≈ 12,000; HEAVIEST T ≈
  20,000** (derived from peak turnover × scans per class — recorded in the fixture manifest), and the persist <3s gate
  AND the `trade_count`-scaled epsilon (`T×abs_tol` worst-case accumulation) are gated against THAT T per class. **WIDE
  T PINNED (R6-F3-batch2 — WIDE (200sym×365d) is the LARGEST class and plausibly the largest T, but was OMITTED from
  the pin; WIDE persists trades and runs the three-way Σ reconciliation whenever it COMPLETES (numba lane ≈<30s, or
  BT_WIDE_STREAM), so for WIDE both the persist-<3s gate (NFR-006/Q.3) and the T-scaled continuous-money-epsilon
  accumulation (NFR-009) are undimensioned — the identical falsifiability + unbounded-epsilon hole the pin closed for
  the other three classes):** **WIDE T ≈ 80,000** (derived from WIDE peak turnover × scans — 200sym × 365d), recorded
  in the fixture manifest; WIDE's persist-<3s and Σ-epsilon are gated against THAT T whenever WIDE completes on the
  numba/stream lane. (On the pure-Python reject lane WIDE never reaches persist — AC-018 rejects it pre-slot — so the
  pin binds only the lane where WIDE actually persists.) The
  dimensioned T is added to NFR-004's fixture table so persist + reconciliation budgets have a concrete pass/fail.
  Any other point lacking a pinned number is derived-by-formula from the
  canonical (stated scaling formula + tolerance) so
  a concrete pass/fail always exists. **Cadence contingency (load-bearing):** this entire HEAVY-term O(ticks×B) cost
  model and the symbol-doubling ≤2× bound assume the once-per-tick basket cadence frozen by FR-018/AC-004. **IF the
  P0 cadence-evidence step (AC-004) proves legacy is per-symbol-candle**, THEN the HEAVY term becomes O(candles×B)
  (~50× larger), and this NFR-004 bound, the NFR-003 evals/s floor, and the §Q latency budgets are **re-derived and
  re-frozen before P3** (named owner + gate per AC-004); these budgets are flagged **cadence-contingent** so the
  dependency is visible to planning. *(REQ-PERF-002/007/008/009/010/011, REQ-ENG-032; P3)*
- **NFR-005 — Sweep budgets + parallel speedup.** Warm 100-combo **<60s**, 500-combo **<5min** — these are
  **numba + ProcessPool-lane MUST budgets** gated at the phase where the engine is actually fast (P3 pure-Python SoA
  or P4 numba), NOT at P2 (see AC-016/AC-039 phase re-tag). The **degraded/sequential lane** (win32 no-numba
  ThreadPool-over-pure-Python, or the final sequential fallback) carries a **documented relaxed ceiling** of
  `Σ(per-combo pure-Python wall) / effective-parallelism` and is asserted only for *parallel efficiency + IPC
  independence on a small fixture* at P2, never the <60s/<5min absolute. Measured **speedup ≥ 0.7 × min(M, K,
  concurrency)** vs serial (this is SPEEDUP per REQ-SWEEP-006, bounded by min(M,K) — NOT dimensionless efficiency,
  which would be the unsatisfiable ≥1.4); equivalently parallel **efficiency ≥ 0.7** (dimensionless). **`concurrency`
  PINNED (R3-F7-batch2 — it was previously an unresolved third term, making `min()` indeterminate / trivially
  satisfiable if it resolved to 1):** `concurrency` = the **resolved parallel-pool worker count for whichever pool
  the host selected** — the `USE_PROCESS_POOL` worker-process count (ProcessPool, now numba-INDEPENDENT per
  FR-031/R4-F3-batch5) OR the effective ThreadPool-over-nogil worker count
  (derived from the resolved CPU budget per FR-049/NFR-013), recorded as a **concrete integer per benchmark host in
  the run manifest**, so `min(M, K, concurrency)` evaluates to a fixed number for every AC run (AC-016/024b/039); on a
  sequential-only fallback host (no parallel mechanism) the speedup gate is capability-waived (AC-016).
  Inherently-
  serial shared setup <15% of total sweep wall-time; aggregate IPC/pickling bytes independent of combo count;
  process-tree RSS ≈ `base_snapshot + C×small-per-combo-working-set`. **`optimize_config` E2E (baseline+sweep+rank)
  wall budget = `sweep_wall(N) + rank_overhead`**, with `rank_overhead ≤ 0.25 × sweep_wall(N)` and the batched
  array-bound persist included — i.e. ≤1.25× the sweep budget for its N (a concrete, testable threshold).
  **Sweep-level wall-time + RSS reject for the full N range (R4-F6-batch4 — the MCP `sweep_run`/`optimize_config` tool
  admits `n: Field(default=100, ge=1, le=5000)` (sweep_tools.py:40), but every sweep budget only gates 100-combo
  (<60s) and 500-combo (<5min); the entire 1000–5000-combo range has NO latency budget, NO RSS budget, and NO
  sweep-level wall-time reject — linearly extrapolating the 500→5min point, a 5000-combo sweep ≈50min with no
  admission gate, and AC-048d bounds peak RSS but not total sweep wall-time):** **`MAX_SWEEP_COMBOS` is PINNED to a
  concrete integer `2000` (R5-F5-batch5 — the prior "(≤ the largest BUDGETED N)" was internally inconsistent: the only
  budgeted N values are 100/500, so "≤ largest budgeted N" implies ≤500, unconditionally rejecting everything in
  501–5000, while the SAME sentence's PreflightEstimator reject term ADMITS N>500 when the predicted wall fits — a
  direct contradiction; and the "lower `le` OR add a reject term" was left an unresolved OR). The "≤ largest budgeted
  N" phrasing is DROPPED (it conflicts with admitting N>500). RESOLUTION (pick ONE, not both):** the
  `PreflightEstimator` **dynamically admits up to a wall-time-derived ceiling** — it admits an `n` IFF
  `predicted_sweep_wall_ms ≤ budget(n)` (formula `sweep_wall(n) ≈ ceil(n/concurrency) × per-combo_wall`) **AND**
  `n ≤ MAX_SWEEP_COMBOS=2000` (the absolute hard ceiling, decoupled from the 100/500 latency-gate points). The MCP
  tool's `le=5000` is **lowered to `le=2000`** so the schema and the estimator agree on the hard ceiling (the dynamic
  wall-time term rejects WITHIN [1,2000] when the host is too slow to fit budget). `predicted_sweep_wall_ms >
  budget(n)` ⇒ structured 4xx (like AC-018). An AC gates the largest ADMITTED N (`MAX_SWEEP_COMBOS=2000`) and a
  just-over-ceiling reject (`n=2001` rejects; a `n≤2000` whose predicted wall exceeds budget also rejects).
  *(REQ-SWEEP-005/006/007/008/009; P3/P4/P6; R4-F6-batch4, R5-F5-batch5)*
- **NFR-006 — Persist budget + holistic round-trip O(1).** Persist **<3s** on a trade-heavy run via
  `executemany`/`COPY` (O(1) insert round-trips, not O(T)); doubling the trade count keeps the insert round-trip
  count flat. The per-run Postgres round-trip SUM is O(1) in scan/candle count; the prepared-statement cache stays
  bounded across a multi-K sweep (statement text invariant to K). Metrics compute is O(curve+trades) single-pass
  (no O(n²) drawdown rescan). Progress writes are O(100) regardless of candle count, overhead <2%, first signal
  <1s after run start. *(REQ-PERF-017/020/032/033/035/036; cross)*

### I.2 Parity & fidelity (the correctness quality bar)

- **NFR-007 — Bit-identity on the canonical 5m no-drill path.** Through P2 (Decimal engine math): byte-identical
  to the string→Decimal oracle. From P3 on (float64): the golden master is re-frozen AS the float64
  representation; the gate is **discrete fields bit-identical** (trade count, sides, symbols, entry/exit bar
  indices, ordering) **AND money fields within a pinned two-sided `continuous-money-epsilon`** vs the Decimal
  oracle (symmetric representation-rounding only — NOT one-sided pessimism on this lane). **`continuous-money-epsilon`
  is pinned to ONE concrete value (single source of truth, referenced by NFR-007/008, NFR-009, AC-020/031/037, and
  the `GoldenMasterOracle` interface):** `epsilon(value) = max(abs_tol, rel_tol × |value|)` with **`abs_tol = 1e-6`
  quote-currency units** and **`rel_tol = 1e-9`** (≈ float64 machine-eps ×~4.5, sized for the canonical op-count so
  representation rounding never trips it, while a real 1-cent error always does), PLUS a **guard-band half-width
  `gb = 1e-4` quote units around every firing threshold** (TP/SL/liq/equity-rule price levels): a config whose money
  delta to a threshold is `< gb` is "near-threshold", detected and routed to the pure-Python oracle rather than
  allowed a silent cross-lane discrete divergence (per the arch money-epsilon guard-band resolution). **Detection
  MECHANISM restated in-spec (R3-F8-batch1 — the prior text deferred to "the arch resolution" without saying
  WHEN/HOW near-threshold is detected, leaving AC-026 not standalone-testable):** near-threshold is detected by a
  **per-tick IN-KERNEL guard-band check** — on each timeline tick, as the float kernel evaluates each open position
  against its armed thresholds (TP/SL/liq/equity-rule levels it already computes), it also computes `|price −
  threshold|` for each and, if ANY open position is within `gb` of a firing threshold on that tick, it **sets a
  run-level `near_threshold` flag** that marks the run for **pure-Python re-resolution** (the float result is
  discarded and the whole run is re-executed on the Decimal oracle, FR-014-style whole-run clean restart — never a
  spliced per-tick mix). This is an in-kernel per-tick distance compare (cheap, reuses the threshold values already
  in registers), NOT a separate full float pre-pass. **Near-threshold double-run COMBINED-budget (R4-F4-batch4 — the
  near-threshold guard-band routes the WHOLE run to a pure-Python Decimal re-execution ("the float result is
  discarded and the whole run is re-executed on the Decimal oracle"), i.e. TWO full executions (float attempt +
  Decimal rerun); the structurally-identical accel-failure fallback (FR-014) got a committed combined-time budget +
  AC-028a (failed-attempt + fallback < 120s), but the near-threshold double-run had NO combined-latency budget and NO
  AC — a canonical near-threshold run can exceed ≤60s, and on the numba lane it triggers a full pure-Python rerun ON
  TOP of the JIT attempt, with no falsifiable gate):** the SUM `(float attempt + pure-Python Decimal re-resolution)
  MUST fit the universal 120s cap` for canonical/HEAVY, and near-threshold detection MUST fire EARLY (the per-tick
  `near_threshold` flag is set as soon as any open position enters the guard-band, so the discard happens before deep
  work where possible). **The Decimal re-resolution ENGINE is PINNED (R5-F1-batch5 — the prior text named no engine
  for the "pure-Python Decimal re-resolution", and the ONLY Decimal path otherwise in the spec is the
  `GoldenMasterOracle` (M.7), a STORED SNAPSHOT of the legacy SUPER-LINEAR engine that AC-001 says takes up to 6
  HOURS on canonical — so a literal reading made AC-026a both UNTESTABLE (no engine named) and UNSATISFIABLE (the
  legacy oracle can't meet <120s)):** near-threshold re-resolution runs on a **Decimal-mode variant of the SAME SoA
  merge-walk engine (M.4)** — identical `O(total_candles + ticks×B)` algorithm, `Decimal` dtype instead of float64 —
  NOT the legacy `GoldenMasterOracle` engine. Its cost basis is added to §Q: Decimal arithmetic is ~50–100×/op
  slower than float64, so on canonical (`heavy_eval_count ≈ 0.13M` + `light_advance_count ≈ 1.296M`) the Decimal
  re-resolution is ≈ (0.13M HEAVY + 1.296M LIGHT) × ~Decimal-per-op cost, which is shown to fit the residual budget
  under 120s after the discarded float attempt (the early-fire discard keeps the float attempt small). AC-026a cites
  THIS engine + throughput basis so the budget is falsifiable. **HEAVY near-threshold is NOT in the <120s
  combined-budget claim — in-flight ABORT disposition (R6-F1-batch1 — the prior "falls back to AC-018's pre-slot
  reject" is UNREACHABLE for a property that manifests MID-RUN: AC-018 runs BEFORE the slot is granted (PreflightEstimator)
  and has NO near-threshold signal, so it can never reject a config whose near-threshold property only appears
  post-admission, after the slot is taken; AND on the §Q Decimal cost basis a near-threshold HEAVY (90d×100sym, B≈20 →
  `heavy_eval_count ≈ ticks×B ≈ 0.52M`) Decimal re-resolution is ≈0.52M/150k × (50–100×) ≈ 175–350s — far over 120s —
  so the prior "(float attempt + Decimal-SoA) completes <120s for canonical/HEAVY" was unsatisfiable for HEAVY and
  would admit-then-die-at-120s, the exact regression this feature removes):** the <120s combined-budget claim is
  SCOPED TO CANONICAL ONLY (where 0.13M HEAVY + 1.296M LIGHT Decimal fits the residual budget). When `near_threshold`
  fires MID-RUN **on a HEAVY (or any larger) class** AND the resolved Decimal re-resolution cannot fit the residual
  budget, the run is **ABORTED in-flight with the §K.3 structured terminal error (a DISTINCT terminal reason —
  `near_threshold_decimal_infeasible` — NOT a completed/zero-trade row and NOT a 120s kill)**, never continuing into a
  Decimal pass that the 120s Timer would kill. (A conservative pre-slot near-threshold-RISK classifier — a static
  config/threshold-proximity heuristic — MAY additionally let AC-018 reject the highest-risk HEAVY configs before the
  slot; but the BINDING guarantee is the in-flight abort, because near-threshold is fundamentally a mid-run property.)
  Gated by AC-026a.** Enforced by the
  golden-master CI guard at EVERY phase. *(Prime Directive, REQ-STORE-040, REQ-TEST-005, R3-F8-batch1, R4-F4-batch4; cross)*
- **NFR-008 — <1% deviation + non-optimistic on drill/portfolio/fast-path lanes.** <1% per-trade + summary
  deviation, AND non-optimistic (one-sided float ≤ Decimal — these lanes have genuine intrabar/coarse-resolution
  ambiguity) verified by the differential float64-vs-Decimal harness + the two-sided sandwich (REQ-DRILL-018).
  **Result fingerprint is SPLIT into two parts (R2-F1-batch5 — a single content hash over money-bearing fields
  CANNOT be byte-identical across the P2→P3 Decimal→float64 representation pivot (§A.1/NFR-007), so the prior
  "byte-identical across Phases 0–6" fingerprint claim was a CI gate that necessarily fails or is bypassed at P3;
  inherited verbatim from REQ-PAR-042 which predates the P3 float64 decision):** (a) a **representation-invariant
  DISCRETE fingerprint** (trade count, sides, symbols, entry/exit bar INDICES, ordering, `close_reason`s) asserted
  **byte-identical across P0–P6** (no phase ever changes a discrete decision); and (b) a **MONEY fingerprint** (the
  content hash over ordered-trade money fields + ordered `equity_curve` + the frozen-key metrics) asserted
  **byte-identical within the Decimal era (P0–P2)**, **RE-FROZEN AS the float64 representation at P3**, and
  byte-identical **P3–P6** — with cross-era money compared within the `continuous-money-epsilon` (NFR-007), never as
  a raw byte hash across the P2→P3 boundary. The full-scale **authoritative canonical drill-OFF benchmark (90d×50sym,
  OR the AC-001 30d×20sym fallback fixture when the 6h capture ceiling trips — R5-F3-batch5; the same identity AC-041
  gates per phase)** carries both fingerprints.
  *(Prime Directive, REQ-PAR-042 [backport note: "discrete fingerprint byte-identical P0–P6; money fingerprint
  re-frozen at P3", NOT a single byte-identical-0–6 claim], R2-F1-batch5; cross)*
- **NFR-009 — Three-way reconciliation holds on every fixture.** `Σ trade.pnl == final_equity − starting_capital
  == net_profit` AND per-trade `trade.pnl == gross_price_pnl − entry_fee − exit_fee − funding_paid` **(non-
  liquidation closes only)**. **Liquidation has its own pinned identity (NOT a Σ-exclusion — the B&H baseline IS
  Σ-excluded but a liquidation trade is INCLUDED in the Σ; corrected to the engine SSOT, R4-F1-batch4):** a
  liquidation trade satisfies `trade.pnl == −locked_margin − entry_fee − funding_paid` with `exit_fee == 0` and no
  slippage (FR-007 margin-wipeout branch — `compute_liquidation_pnl` returns `−(locked_margin+entry_fee)` and the
  engine subtracts `funding_paid`), so it is excluded from the gross-minus-fees formula but
  STILL included in the `Σ trade.pnl` total (and the bare `−locked_margin` would BREAK the Σ on any
  liquidation-bearing run). **The DISCRETE identities stay EXACT and tolerance-free at every phase**
  (trade COUNT, the opened-position set, each `close_reason`, and the exit-bar index per REQ-PAR-018) — a dropped,
  duplicated, or misattributed trade is caught **structurally**, independent of any money tolerance. Only the
  *continuous* money sums use tolerance: EXACT on the P0–P2 Decimal lane; from P3 on the `continuous-money-epsilon`
  of NFR-007 (scaled per-run by `trade_count` for the Σ aggregate) applies to BOTH the invariant check AND the
  GET-path torn-persist guard. **Persisted-path reconciliation basis PINNED (R2-F9-batch2 — the GET-path guard
  reconciles PERSISTED values: `backtest_trades.pnl` is `NUMERIC(20,8)` (`async_persistence.py:708`) read back as
  Decimal and summed vs `net_profit` stored as float in `metrics` JSONB, so the error source on the persisted
  comparison is NUMERIC(20,8) QUANTIZATION (granularity `1e-8`/trade, accumulating with trade_count), NOT the float64
  REPRESENTATION rounding the `continuous-money-epsilon` was derived for — the two are different error bases):** the
  persisted-path guard asserts (a) each trade's `NUMERIC(20,8)` round-trip is within the per-trade `abs_tol`
  (`abs_tol = 1e-6 ≫ 0.5e-8` quantization half-ULP, so a single quantization never trips it), AND (b) the
  trade_count-scaled aggregate epsilon DOMINATES the worst-case accumulated quantization: `T × 0.5e-8 ≤ T × abs_tol`
  (holds with ~200× margin), so the `trade_count`-scaled `continuous-money-epsilon` absorbs NUMERIC quantization as
  well as float64 rounding. A **high-trade-count fixture reconciles the PERSISTED (NUMERIC-read-back Decimal) sum**,
  not only the in-memory float64 sum. A high-trade-count fixture asserts the guard does NOT false-POSITIVE; **a fault-
  injection fixture asserts the guard/structural check DETECTS a single dropped / duplicated / sign-flipped trade
  even when its money delta is below the continuous epsilon** (closing the false-NEGATIVE hole on large-capital/
  high-count runs — caught by the exact discrete identities, not the money band). The B&H BTC baseline is excluded
  from this reconciliation. *(Prime Directive, REQ-PAR-018/045, REQ-TEST-014, R2-F9-batch2; P0/cross)*
- **NFR-010 — Golden NO-OP guarantee preserved every phase.** Empty `instrument_info`/`scan_contexts`/`fine_klines`
  + no regime ⇒ engine output byte-identical to the pure 5m path, asserted by a per-phase NO-OP fixture. The
  derived-coarse `15m/1h/4h` path equals legacy native-coarse for any coarse-interval config. *(discovery §8, REQ-TEST-030; cross)*
- **NFR-011 — Fingerprint & persistence stability.** `content_sha256` is a pure function of the canonical candle
  bytes, independent of engine git-SHA or optimization-flag generation (concurrent rolling-deploy versions
  converge to one hash, no spurious refetch); the equity_curve manifest hash and sweep config_hash are invariant
  to net-new sibling columns; every recorded numeric value survives the float→NUMERIC/JSONB round-trip losslessly.
  *(REQ-PAR-044, REQ-FE-003/015; P5/cross)*

### I.3 Resource & memory

- **NFR-012 — Bounded RSS on the shared live process.** Peak process RSS for the canonical drill-OFF run ≤ **1 GB**
  total (re-derived to include book/curve/interpreter/live headroom); resident kline bytes ≤ **150 MB** (≤2×
  theoretical SoA); the global timeline gets its OWN `timeline_bytes` budget line ADDED to (not carved from) the
  150 MB (the ~168 MB misaligned worst case alone exceeds 150 MB). **The drill-ON run carries its own concrete
  ceiling (R2-F4-batch4/batch5 — was "its own ceiling" with no number, leaving AC-024a's RSS clause undecidable):
  `drill-ON ceiling = canonical 1 GB + committed 1m-drill-cache budget (≤ 256 MB) + fine-SoA budget (≤ 256 MB) =
  ≤ 1.5 GB total`** (the 1m drill cache + fine SoA on top of the 5m working set; still < the 2 GB WIDE budget). This
  single number is the **CANONICAL (50-sym) drill-ON** ceiling referenced by NFR-004, AC-027, AC-037a, and §Q.3.
  **HEAVY/HEAVIEST get their OWN symbol-scaled ceilings (R3-F1-batch4/F4-batch1/F4-batch6 — the 1.5 GB number is
  canonical-derived and was NOT re-derived for 2–3× the symbols + deeper book; resident klines, position book, and
  fine-SoA all scale with symbol count, so reusing it under-budgets the heavy classes and makes AC-024a's RSS clause
  unsatisfiable):** **HEAVY (100sym) ceiling ≤ 1.75 GB** (`base_non_kline ~0.85GB + resident_klines(100sym) ~0.3GB +
  1m-drill-cache ≤256MB + fine-SoA ≤256MB + timeline`); **HEAVIEST (150sym) ceiling ≤ 2 GB** (pinned under the WIDE
  tier: `resident_klines(150sym) ~0.45GB` + deeper book `B≈40` + drill cache + fine-SoA + `timeline_bytes` ~168MB).
  AC-024a asserts each class against ITS OWN ceiling, NOT the canonical 1.5 GB. **AGGREGATE-RSS admission (R3-F7-batch3
  — per-run ceilings bound a SINGLE run, but on the single shared host (W-3) 3 concurrent runs + a sweep pool can SUM
  past the host budget; only the watchdog backstopped it):** the `AdmissionAccountant` enforces `Σ(reserved per-run
  predicted peak RSS) + sweep-pool footprint ≤ BT_RSS_BUDGET` at admission (queue/reject pre-slot otherwise), so the
  watchdog is a backstop not the primary control (AC-048d). **WIDE-run path (RESOLVED — reconciles the NFR-012 "rejects/
  streams" / S.6 "not newly rejected" / REQ-PERF-039 tension):** a WIDE run (e.g. 200sym×365d, whose SoA ≈1GB alone
  meets/exceeds the canonical ceiling) is handled in **two tiers**: (1) the `PreflightEstimator` admits it if its
  predicted peak RSS (open-book SoA + timeline + drill headroom) fits the **WIDE total-RSS budget = 2 GB** within the
  universal 120s hard cap (and its committed ≤90s-class latency budget); (2) if it would exceed that budget it is either **pre-flight REJECTED** (default) or, when
  `BT_WIDE_STREAM` is enabled, executed via a **history-streaming path that streams only the CLOSED/inactive symbol
  history (released before the next batch) while keeping the ENTIRE OPEN BOOK resident** — because the cross-sectional
  shared-capital basket-equity invariant (H.2) requires every open position resident to compute `E = wallet + Σ open-
  uPnL` once per tick, a symbol contributing to basket equity is NEVER evicted. The streaming path must prove parity
  vs the all-resident oracle on a WIDE fixture. S.6's "not newly rejected" applies only when the WIDE run fits tier-1;
  otherwise the reject/stream disposition governs. A runtime RSS watchdog cooperatively aborts before OOM.
  *(REQ-PERF-012/014/037/039; P3/cross)*
- **NFR-013 — Allocation + build-time peak bounded; ceilings budget-derived (cgroup OR explicit config).** Total
  Python allocations (tracemalloc peak) scale with `(trades + symbols + curve_length)` NOT candle count (candle-
  doubling at fixed trades stays ±10%); the Postgres-fallback raw-row→SoA conversion releases rows incrementally so
  transient build-time peak RSS ≤ ~1.5× final SoA. **Per-process + aggregate ceilings AND all thread-pool caps derive
  from an explicit CPU/RSS budget, resolved platform-specifically (REQ-DEP-022 "cgroup OR explicit config"):** on the
  **PRIMARY single-host Windows 11 target** (W-3/X-6, no cgroups — a Linux-only kernel feature) the budget is read
  from explicit config envs **`BT_CPU_BUDGET` / `BT_RSS_BUDGET`** (defaulting, if unset, to a Windows Job Object query
  / `GetPhysicallyInstalledSystemMemory` with a documented safety fraction), NEVER `os.cpu_count()`/host RAM; on a
  **[FLEET]/Linux-container** deploy the budget is the **cgroup CPU quota / cgroup memory limit**. **`BT_RSS_BUDGET`
  default safety fraction PINNED (R6-F5-batch1 — the aggregate-RSS admission gate (AC-048d) and Q.3's
  "Σ(reserved per-run peak RSS)+sweep-pool ≤ BT_RSS_BUDGET" DEPEND on this bound, but the unset default deferred to "a
  documented safety fraction" that was NEVER documented (it appears once, undefined); R5 deliberately pinned concrete
  defaults for skew_margin (1×T), under_estimate_margin (1.0), BT_QUEUE_MAX_DEPTH (16), and BT_QUEUE_WAIT_TIMEOUT_MS
  (120000) PRECISELY because an unpinned safety bound "lets a build set it effectively-infinite and pass the reject
  test while leaving the DoS surface open" — and BT_RSS_BUDGET on the shared single-host live process (3 concurrent
  runs up to 2GB each + a sweep pool) is the same class):** when unset, the resolved budget is
  **`BT_RSS_BUDGET = min(BT_RSS_BUDGET_env_if_set, 0.6 × physically-installed RAM)`** on the W-3 single-host target
  (a 0.6 safety fraction reserving 40% for the OS + the shared FastAPI/live-trading process), **range-validated**
  (reject a non-positive or >installed-RAM value) and **recorded in the run manifest**. AC-048d asserts against THIS
  pinned default (admit at the limit, reject one run over), not an operator-supplied number only. On a Linux-container
  deploy the cgroup memory limit supersedes the 0.6×installed-RAM derivation. A multi-worker
  deploy either keeps `Σ(workers × per-process cache) ≤ budget` OR uses mmap/shared-memory-backed hot tiers so adding
  a worker does not N-multiply resident kline bytes. Every terminal path (complete/timeout-kill/cancel) releases SoA
  arrays, position book, 1m memo, mmap/shm segments, per-tier conns in a `finally`; a soak over heterogeneous runs
  asserts flat RSS + FD/mmap/shm/conn return to baseline. *(REQ-PERF-013/014/041, REQ-DEP-021/022; cross)*

### I.4 Migration safety

- **NFR-014 — v58 is callable, additive/expand-only, idempotent, sub-second.** v58 is a **callable** migration (no
  `;`-split bug), ships **DDL ONLY** (`ADD COLUMN IF NOT EXISTS` with constant defaults → catalog-only, no table
  rewrite; lifecycle table) with **zero data-dependent seal backfill inline**, advancing
  `schema_version` to 58 atomically + sub-second so the global migration advisory lock is never held for a long
  backfill. An injected mid-DDL failure leaves `schema_version` at 57 with nothing partially applied. **Fail-loud
  step-0 pre-checks BEFORE any `ADD COLUMN` (REQ-MIG-007/008 — R5-F2-batch3: these two must-controls had NO spec
  anchor (no FR, no §U AC, absent from the T.10 enumeration) even though architecture §4.4 designs them; without them
  a P1 merge can go green while v58 silently builds the manifest on a wrong-typed `first_open_ts INT4` (epoch-ms
  overflow, REQ-MIG-006) or a mismatched PK, defeating the sealed-manifest integrity model):** v58 FIRST (a)
  **validates the live `kline_cache_coverage` PK is exactly `(symbol, interval, date)`** and **FAILS FAST with an
  actionable key-mismatch diagnostic (zero schema change, `schema_version` stays 57)** if it differs (REQ-MIG-007);
  and (b) **detects a pre-existing target manifest column already present with an INCOMPATIBLE type/width** (which
  `ADD COLUMN IF NOT EXISTS` would SILENTLY SKIP) and **FAILS LOUD** with an actionable message rather than proceed on
  the wrong type (REQ-MIG-008). Both pre-checks run BEFORE any `ADD COLUMN`, so a wrong-PK or wrong-typed-column DB
  never gets a half-built manifest. Gated by a P1 AC (AC-008a) + a T.10 sub-test wired to the ACTUAL callable. **The
  `backtest_runs.status` CHECK-constraint widen (N.2 / R2-F1) is NOT a catalog-only `ADD COLUMN` — it is a
  DROP+ADD CONSTRAINT; to keep boot sub-second it adds the new CHECK `NOT VALID` in v58 and runs `VALIDATE
  CONSTRAINT` OUT-OF-BAND (the bare `ADD ... CHECK` would re-validate the whole table under ACCESS EXCLUSIVE). This
  carve-out is the ONLY non-`ADD COLUMN` schema change in v58; `backtest_runs` is small so its validation scan is
  bounded regardless.** The partial
  index `idx_coverage_unsealed` is built out-of-band via `CREATE INDEX CONCURRENTLY` (NOT inside the in-transaction
  callable migration — CIC is illegal in a transaction; see N.4 CIC-owner, R2-F3-batch3). It claims the next free int
  (collision-coordinated) with a bounded `lock_timeout` + in-boot retry + submission-quiesce DRAIN window so the
  `ADD COLUMN` ACCESS EXCLUSIVE never races the live scanner's `_update_coverage` upserts. **The migration/election
  advisory locks (v58 apply, `SealBackfillRunner`, `SymbolLifecycleRefresher`) are acquired on a dedicated DIRECT
  (non-pooled, session-pinned) asyncpg connection (REQ-MIG-028, N.4) — defensive on the standalone-primary PRIMARY
  target, load-bearing under the [FLEET] transaction-mode-pooler variant — so a session-level `pg_advisory_lock` is
  never silently re-bound to a different pooled backend.** *(REQ-MIG-007/008/018/020/021/028/033, R1-F1/F2, R2-F1-batch3, R5-F2-batch3, R5-F4-batch3; P1)*
- **NFR-015 — Expand-only + rolling-deploy column preservation + downgrade-blocked.** v58 contains ZERO destructive
  DDL (CI schema-diff guard); any contraction is deferred to a later migration after all pre-v58 pods drain.
  **The `backtest_runs.status` CHECK-constraint DROP+ADD (N.2 / R2-F1) is EXPAND-ONLY (the new IN-list is a strict
  superset of the old) and is explicitly WHITELISTED in the destructive-DDL schema-diff guard as an expand-only
  constraint widening — a naive guard would flag the `DROP CONSTRAINT` as destructive, so the whitelist entry pins
  it as the one allowed constraint replacement and asserts the new list ⊇ the old.**
  Pre-optimization code runs correctly against v58 (additive columns ignored); legacy column-omitting upserts MUST
  NOT null/clobber additive v58 columns on existing rows. Binary downgrade below v58 is FORBIDDEN (the runner
  RAISES when stored `schema_version` > app max) — the supported rollback is the kill-switch; a CD promotion guard
  BLOCKS deploying any binary whose max-supported `schema_version` < the live DB's. A verified restore-point is
  taken + verified immediately before v58; v58 is rehearsed on a restored prod clone (exact PG major + partitioning)
  asserting within-budget apply + second-run no-op. *(REQ-ROLL-005/006/007/009, REQ-MIG-041, R2-F1-batch3; P1/cross)*
- **NFR-016 — PITR/restore self-invalidation is detected, not assumed.** A SOR-wide monotonic `sor_data_generation`
  token is stamped (at write time) on every fine coverage row + embedded in every derived artifact (Parquet/Feather,
  Arrow/LRU, 1m-drill memo, SoA memo, derived-coarse). **Invalidation is READ-TIME COMPARE of the embedded token vs
  the `sor_data_generation` singleton — NOT a per-row mass re-stamp UPDATE (R2-F8-batch2), so a PITR bump touches
  ONLY the singleton (O(1)), never `kline_cache_coverage` table-wide.** **Which token GATES read-time invalidation
  (R5-F6-batch2 — resolves the tension between "coverage-row token frozen post-seal / DEFAULT 0 for pre-v58 rows" and
  "READ-TIME COMPARE of the embedded token": a coverage ROW is the SOR manifest itself — there is nothing to
  "rebuild" from it and re-stamping is forbidden, so a read-time compare of the ROW token against a bumped singleton
  would mismatch on EVERY read after any PITR bump yet have no valid rebuild action):** ONLY the **derived-artifact**
  embedded tokens (Parquet/Feather/Arrow/LRU/1m-drill memo/SoA memo/derived-coarse) gate read-time invalidation —
  a mismatch there invalidates + **rebuilds that artifact** (the artifact IS re-derivable from the SOR). The
  **coverage-row `data_generation` is PROVENANCE-ONLY** (it records the generation under which the row was sealed); it
  is **NOT a read-time invalidation trigger** and is advanced SOLELY via the documented un-seal → re-verify → re-seal
  path, never by a read-time compare. So a sealed coverage row carrying a stale `data_generation` (or DEFAULT 0)
  after a singleton bump does NOT itself trigger refetch/re-seal on read — only its DERIVED artifacts rebuild once.
  A boot DB-identity comparison
  (`system_identifier`, `timeline_id`, control-file digest) bumps the singleton on any PITR/restore/failover; a
  MANDATORY sampled row-count/`content_sha256`
  backstop independently bumps it on detected drift (so a rewind evading the boot hook still invalidates). **The
  sampled backstop ALSO samples sealed days carrying NULL `content_sha256` (residual pre-R2-F7 backfilled rows) so a
  sealed-but-unhashed day's cross-tier drift / in-place mutation is still caught — `SealBackfillRunner` now hashes
  backfilled days (FR-050), so NULL-sha is the residual, not the norm.** A
  restore test that does NOT manually bump asserts the backstop triggers invalidation; a PITR test asserts
  derived-coarse re-derives exactly once then stops (the FROZEN content set byte-unchanged across the re-stamp);
  **a test asserts a sealed coverage row with a STALE `data_generation` does NOT trigger refetch/re-seal on read
  after a singleton bump (only its derived artifacts rebuild once — R5-F6-batch2).** *(REQ-CACHE-043/044, REQ-ROLL-023; cross; R5-F6-batch2)*

### I.5 Reliability & resilience

- **NFR-017 — Fail-soft everywhere; no run-abort on a recoverable fault.** A numba/DuckDB/Parquet runtime failure
  degrades to pure-Python/Postgres within the run; a 1m drill fetch failure falls back to 5m for that bar only; a
  Bybit 429/timeout never seals + trips the shared breaker for coordinated backoff; a Postgres write failure
  during cold `store_klines` leaves the day unsealed/refetchable with no torn manifest row (fail-loud or documented
  partial-data warning), and a seal-upsert failure after rows are durable is non-fatal (run completes
  oracle-identical, day stays unsealed for next-run lazy-seal). A strict-offline/cache-only mode fails loud with an
  actionable miss message (no silent fetch). *(REQ-ROLL-012, REQ-DRILL-023, REQ-CACHE-007/047/050; cross)*
- **NFR-018 — Cooperative cancel + bounded termination.** The 120s `threading.Timer` cancel, natural finish, and
  `POST /cancel` are CAS-arbitrated to exactly one terminal state; SAFE_MODE aborts in-flight accel runs/sweeps
  within a bounded wall-clock (not waiting out 120s/combo) and pauses/resumes the backfill idempotently from
  checkpoint. *(REQ-API-012, REQ-ROLL-002; cross)*

### I.6 Security

- **NFR-019 — Path-traversal/TOCTOU rejection (Windows-primary + POSIX lane).** Parquet hive paths use a
  reversible `SAN(SYM)` encoding (percent/hex-encode every non-`[A-Za-z0-9._-]` char) + an asserted within-
  `BT_COLUMNAR_DIR` absolute-path check; `interval` validated against the closed enum. Windows (primary): reject
  reparse points/junctions on the path + every parent, validate dir ownership + ACL via win32 security APIs,
  canonicalize-then-re-stat BY HANDLE (a junction-swap test is rejected). POSIX (CI lane): `O_NOFOLLOW` +
  `realpath`-then-`fstat` + non-world-writable mode. **The SAME ownership/ACL/reparse-reject validation covers the
  numba `NUMBA_CACHE_DIR` (an integrity-critical local-code-execution path) at P4 — or it lives inside the guarded
  `BT_COLUMNAR_DIR`; on failure the on-disk JIT cache is disabled, not loaded (P.2 / R2-F6).** *(REQ-SEC-001,
  REQ-STORE-021/034; P4 numba-cache-dir / P5 Parquet-dir)*
- **NFR-020 — DuckDB capability lockdown.** Keep `enable_external_access=true` but constrain
  `allowed_directories=[BT_COLUMNAR_DIR]`, `lock_configuration=true` (a successful injection cannot re-widen
  access), `autoinstall/autoload_known_extensions=false`, `access_mode='READ_ONLY'`. The scanned Parquet PATH is
  string-built (SAN + within-allowed_directories the defense); real predicates use `$n` binding. An injection test
  asserts a crafted symbol cannot escape `allowed_directories` AND cannot mutate config. **`duckdb>=1.1` is a pinned
  SECURITY floor (the lockdown primitives require it — arch §8.3); a boot/CI probe asserts the loaded build exposes
  AND enforces `allowed_directories` + `lock_configuration` (a post-lockdown `SET enable_external_access=true` is
  rejected), else the columnar path fails closed to Postgres (P.3 / R2-F5).** *(REQ-SEC-002; P5)*
- **NFR-021 — New-dep CVE surface bounded; spawn-worker secret minimization; coarsened public surface; wrong-DB
  fail-closed.** Accel deps are hash-pinned + pip-audited + floor/ceiling-bound + optional. Spawn workers launch
  with an ALLOWLIST (deny-by-default) env carrying only non-secret kernel vars — NEVER `ACCOUNTS_ENCRYPTION_KEY`,
  `DATABASE_URL`, `COINGECKO_API_KEY`, or LLM keys; core dumps disabled; **the allowlist is a CLOSED set (P.4) and
  the worker-env test asserts `set(os.environ) ⊆ allowlist` (subset/exact-membership, NOT a 4-name denylist) so a
  future-added secret fails CI (R2-F4)**. The public `/backtest-runtime/status` payload
  omits exact versions / git-SHA / numeric resource config. The expected DB-identity is OPERATOR-PROVISIONED (not
  self-seeded) so a first-deploy wrong-`DATABASE_URL` is caught on first boot; a missing `pg_control_*` grant FAILS
  CLOSED (refuses destructive seal writes). `MaintenanceAdmin` destructive ops are CLI-only, not bound to the
  public port. *(REQ-SEC-003/004/005/006/007, REQ-DEP-028; cross)*

### I.7 Observability & maintainability

- **NFR-022 — Instrumentation overhead ≤2%, counters O(trades+signals).** All counters/timers add ≤2% overhead and
  scale O(trades+signals), never per-candle; partial telemetry survives timeout/cancel/degrade; a per-tier
  read-latency micro-benchmark asserts Arrow hot < Feather mmap < Parquet < Postgres so a tier regression is
  caught. *(REQ-PERF-036, REQ-OBS-012/013, REQ-PERF-043; cross)*
- **NFR-023 — Core files stay semantically identical.** `backtest_engine.py`, `backtest_service.py`,
  `kline_cache_service.py`, `trading_rules.py`, `sweep_tools.py` change only in HOW (data layout, batching,
  tiering) — never in WHAT they decide; the golden-master suite is the enforcement point. *(Prime Directive; cross)*
- **NFR-024 — Pre-flight estimator accuracy.** The estimator brackets actual within ±50% on the deterministic
  compute+network+cold-build terms on the canonical + wide fixtures (host-aware); the drill term is a bounded
  worst-case excluded from the ±50% gate. **Estimator basis reconciled to §I-preamble (R4-F4-batch5):** the compute
  term is `a·light_advance_count (≈total_candles) + b·heavy_eval_count (≈ticks×B)` (M.9/R.4), NOT `candles×scans×B`; a
  **calibration test asserts the ±50% bracket holds as SCANS (not just symbols) scale** (the spurious `scans` factor
  is removed, so the estimate must not drift super-linearly in scan count). **WIDE-lane accuracy scoping (R4-F2-batch4
  — the ±50% gate is UNTESTABLE on the pure-Python WIDE lane it names: a pure-Python WIDE run is REJECTED pre-slot
  (NFR-001/AC-018) and therefore never produces an "actual" wall/RSS to bracket):** the WIDE ±50% accuracy assertion
  is scoped to a lane where WIDE actually COMPLETES — the **numba lane** (WIDE ≈<30s) OR a dedicated offline/uncapped
  harness that runs the rejected pure-Python WIDE to completion solely to ground-truth the estimate; for the
  pure-Python WIDE REJECT path, the ±50% accuracy gate is REPLACED by the AC-018 conservative-under-estimate-margin
  assertion (never admit a true over-budget run). State per-fixture/per-lane which accuracy clause applies.
  **`under_estimate_margin` PINNED to the concrete ratio (R4-F4-batch4 — the prior "`≥` the estimator's worst-case
  under-prediction" was numerically unpinned and the natural reading unsafe: the ±50% bracket means actual ∈
  [0.5×pred, 1.5×pred] so worst-case actual = 2×predicted, which requires `1+margin = 2` i.e. margin = 1.0 to
  guarantee a true over-budget run is never admitted; reading "worst-case under-prediction" as the ±50% percentage
  gives margin = 0.5 ⇒ `budget/1.5` ⇒ admits up to ~1.33×budget):** `under_estimate_margin` is DEFINED as
  `max(actual/predicted) − 1 = 1.0` (the ±50% bracket's worst case), so the AC-018 reject thresholds are `predicted_rss
  > budget/2` and `predicted_wall_ms > budget/2` — NOT `budget/1.5`. **Drill-term bound direction (R4-F8-batch4 — the
  drill term is "a bounded worst-case excluded from the ±50% gate", but if it is a conservative UPPER bound fed into
  the reject decision, a near-budget HEAVY/HEAVIEST drill-ON run (both classes are drill-ON) can be FALSE-REJECTED,
  contradicting AC-018's no-false-reject ADMIT path):** the drill term is **EXCLUDED from the AC-018 reject threshold**
  (drill-ON overruns are governed by the runtime watchdog + the ≤90s class budget), OR given a separate looser
  two-sided bound used in the reject decision — so a near-budget in-budget drill-ON heavy run is NOT false-rejected.
  *(REQ-PERF-037/038; P2/cross; R4-F4-batch4/F4-batch5, R4-F2-batch4, R4-F8-batch4)*

---

## J. User Flows

### J.1 Single backtest run (the primary lifecycle)

```
User/MCP → POST /backtest (create AND launch — ONE step, no separate /run route)  [BacktestCreateRequest.model_dump() → config]
   │  reserves a _MAX_CONCURRENT=3 slot OR enqueues (queued); per-client rate limit
   │     (today, slot-full → 503 BacktestBusyError; the `queued` verdict is NEW admission behavior on this SAME create boundary)
   │  PreflightEstimator predicts compute+network+RSS:
   │     ├─ verdict=run      → proceed
   │     ├─ verdict=queue    → queued (CAS-arbitrated); 120s clock arms at queued→running
   │     └─ verdict=reject   → 4xx {status:'rejected', reason, pred_ms, pred_rss_bytes}  ← NOT a result row
   ▼
(same request) _launch_background → _execute_backtest
   │  ① warm-up: SealedManifest.unsealed_days in [start, frontier] → bounded Bybit gap-fill ONLY
   │     (fully-sealed range ⇒ bybit_kline_calls == 0; forming day served from Postgres primary)
   │  ② load_inputs: batched signals + klines (ANY($1)+BETWEEN, 1 query); KlineStore tier-routes
   │     (Arrow hot → Feather mmap → Parquet → Postgres; forming day → Postgres only)
   │  ③ SoADatasetBuilder: columnar arrays + global timeline + scan-anchor searchsorted (once)
   │  ④ Phase A engine pass (numba kernel if BT_USE_NUMBA effective, else pure-Python oracle):
   │     per-tick funding → per-position liq/TP/SL → equity cascade → trailing → time
   │  ⑤ optional Phase B drill: lazy per-symbol 1m, bounded per-bar, in-process memo (drilldown_enabled)
   │  ⑥ compute_all_metrics (~45 keys, path-dependent ordering preserved)
   │  ⑦ _persist_results: 3 writes (results + trades COPY + equity_curve JSONB) in ONE transaction
   │  ⑧ _attach_buy_hold (isolated path, reconciliation-excluded)
   │  terminal-state CAS: running → {completed|failed_with_timeout|cancelled|interrupted_by_restart}
   │    (failed_with_timeout is an INTERNAL label → stored status 'failed' + terminal_reason='timeout', R2-F2-batch3)
   │  (120s Timer kill / natural finish / POST /cancel all arbitrate; first writer wins; slot released once)
   ▼
GET /backtest/{id} → _build_results → torn-persist guard reconciles → BacktestResults JSON
   (equity_curve LTTB-downsampled, trough-preserving; metrics.total_trades always present)
   ▼
React BacktestResultsPage / MCP backtest_get
```

**Warm-rerun flow (the headline win):** an identical rerun over a fully-sealed window does ② entirely from the
Arrow hot frame / Feather mmap (warm) — `bybit_kline_calls == 0`, `postgres_kline_selects == 0` (forming-tail:
== forming-day-only) — and the SoA build slices from RAM. The run completes in seconds.

### J.2 Sweep / optimize lifecycle

```
MCP sweep_run / optimize_config (space, base, scan_source, date_range)
   │  PreflightEstimator sizes the combo grid; SoADatasetBuilder builds the shared read-only SoA ONCE
   ▼
SweepRunner fan-out  [prod: spawn ProcessPool + shared_memory | win32 dev/CI: ThreadPool over nogil kernel | seq]
   │  snapshot shipped ONCE (IPC bytes independent of combo count)
   │  each combo → pure engine (bypasses drilldown; combo is drill-OFF-coerced — R2-F2-batch4) → metrics
   │  live-trading breaker = parent dispatch gate; sweep pauses/sheds under open breaker, own pool (not 3 UI slots)
   ▼
batched persist (UNNEST id+rank arrays, executemany, COPY — fixed parameterized text, no inline VALUES)
   ▼
sweep_results (re-rankable by alternate objective server-side, no re-run) / optimize_config PROPOSES a config
   (a human approves it in the app UI — the agent cannot apply it)
```

**Parity tie:** a single sweep combo's persisted result == a standalone **drill-OFF** `backtest_run` of that exact
config (sweeps coerce `drilldown_enabled=false`; the equality is scoped to drill-off because the pure engine bypasses
drilldown — R2-F2-batch4); the
PROPOSED config reproduces the per-combo metrics it was ranked on (REQ-PAR-043, REQ-SWEEP-009; AC-017).

### J.3 Cache warm-up flow

```
POST /backtest-cache/warmup (symbols, start, end, interval)
   │  per-client rate limit + AdmissionAccountant (same admission boundary as POST /backtest); a request whose
   │     scope exceeds the warmup ceiling is REJECTED with the structured 4xx contract BEFORE any Bybit call
   │     (bybit_kline_calls == 0 on the reject path) — see scope ceiling below
   │  SealedManifest.unsealed_days(range) → only unsealed days in [start, frontier]
   │  ensure_coverage: outer per-symbol-month chunk loop (bounded by the per-request ceiling), semaphore-bounded
   │     concurrent fan-out, _PAGE_SIZE=1000, shared breaker (priority below live), incremental seal of completed days
   │  re-warming a sealed range ⇒ 0 Bybit calls; single-flight-safe alongside backtests; populates lifecycle
   ▼
GET /backtest-cache/status → CacheStatusResponse{symbols_total, symbols_cached, symbols_with_gaps, ready
                                                  (+ optional sealed_days/negative_days)}
   ready=true when every CLOSED/sealed day is present and ONLY the forming-edge day is incomplete
```

**Warmup scope ceiling (R2-F3 — bounds the Bybit-cost + storage DoS-amplification surface).** `POST
/backtest-cache/warmup`'s reach is otherwise unbounded (J.3's outer per-symbol-month chunk loop has unbounded reach;
the PreflightEstimator reject path and RSS/slot admission govern RUNS, not warmup cold-fetch scope). A single
request with many symbols × `interval=1m` × a multi-year start would drive unbounded TOTAL Bybit calls + disk
(rate-bounded by the semaphore/breaker, but unbounded in total work/cost/storage). Mitigation: a **per-request scope
ceiling = `symbol_count × span × interval-multiplier`** (concretely a max-symbols cap, a max-span cap, AND a
fine-interval restriction so `1m` carries a much smaller max-span than `5m`), evaluated against the structured 4xx
contract (`{status:'rejected', reason, pred_ms, pred_rss_bytes}` / `pred_bybit_calls`) **before any Bybit call**.
**Concrete range-validated defaults PINNED (R5-F6-batch1 — the reject AC is only falsifiable if the caps are pinned,
to the same precision standard as `skew_margin`/`T`; an unpinned cap lets a build set it to effectively-infinite and
pass the reject test while leaving the DoS surface open):** `BT_WARMUP_MAX_SYMBOLS` default **50**,
`BT_WARMUP_MAX_SPAN_DAYS_5M` default **400** days, `BT_WARMUP_MAX_SPAN_DAYS_1M` default **90** days (the reduced
fine-interval span); all three are range-validated config and **recorded in the run/fixture manifest**. The reject
AC gates against THESE pinned values — a request at `limit+1` (51 symbols, or a 5m span of 401d, or a 1m span of 91d)
**rejects** pre-fetch with `bybit_kline_calls == 0`; a request **at** the limit **admits**.
warmup is ALSO subject to the same per-client rate limit + `AdmissionAccountant` as `POST /backtest` create. **The
"per-client" key for the rate limit AND this scope ceiling is the W-12 non-spoofable identity (authenticated
principal/API-key, else kernel peer address — NEVER a raw `X-Forwarded-For`), so a header-rotating attacker cannot
mint unlimited distinct "clients" to bypass the ceiling (R5-F2-batch1).** A test
asserts an over-scope warmup request is rejected pre-fetch (`bybit_kline_calls == 0`).

### J.4 Kill-switch / degrade flow

```
Operator sets BACKTEST_SAFE_MODE (ENV/file OR bt_flag_config row)
   ▼  SafeModeController (injected at lifespan), pinned idempotent order:
   (a) CapabilityResolver forces all 6 flags effective-off (reproduces golden master)
   (b) broadcast_cancel() → every in-flight run's threading.Event (bounded abort, not 120s wait);
       for an in-flight ProcessPool SWEEP, the abort is CROSS-PROCESS (pool.terminate() / per-worker
       shared_memory cancel flag) since a child process cannot observe the parent's threading.Event (AC-048e)
   (c) SealedManifest.halt_seal_writes()
   (d) SealBackfillRunner.drain()/quiesce()
   ▼  honorable even with Postgres DOWN (ENV/file short-circuits; failed bt_flag_config read → last-known-good/ENV)
   next run on every instance serves the pure-Python/Postgres oracle path
```

---

## K. API Requirements

**Hard rule: every existing endpoint, request schema, and response shape is a no-regress surface. Zero new
required fields; rename/remove/retype nothing. New fields are optional + nullable only.**

### K.1 Endpoints — UNCHANGED signatures (`backend/routers/backtest.py` — **9 real routes**, VERIFIED against `@router` decorators)

| Endpoint | Status | Note |
|----------|--------|------|
| `POST /backtest` (create **+ launch**, one step) | **UNCHANGED** | `BacktestCreateRequest.model_dump()` → `config.get(...)`; reserves a `_MAX_CONCURRENT=3` slot **synchronously** and calls `_launch_background` in the SAME request — there is **NO separate `/backtest/{id}/run` route**; today it `503`s (`BacktestBusyError`) when full; same-run_id single-flight (FR-039); MCP `backtest_run` 1:1 |
| `POST /backtest/{id}/cancel` | **UNCHANGED** | Cooperative `threading.Event` cancel preserved |
| `GET /backtest` / `GET /backtest/{id}` | **UNCHANGED** | `_build_results:476` + torn-persist guard (FR-038) |
| `DELETE /backtest/{id}` | **UNCHANGED** | — |
| `GET /backtest/{id}/trades` (paginated) | **UNCHANGED** | Real contract: `page`/`limit`/`sort_by`/`side`/`close_reason` OFFSET pagination (R4-F2-batch4 — NOT cursor; latency is O(offset), NOT flat-as-rows-grow; only `idx_backtest_trades_run` exists) |
| `GET /backtest/compare` | **UNCHANGED** | `compare_backtests:357` (it is a **GET**, not POST); tolerates new close_reason/status enums |
| `GET /backtest-cache/status` | **UNCHANGED shape** | Now computed from `SealedManifest`; MAY add optional `sealed_days`/`negative_days` counts |
| `POST /backtest-cache/warmup` | **UNCHANGED** | Manifest-aware, idempotent, 0-call on a sealed range; per-request scope ceiling + per-client rate limit (J.3 / R2-F3) reject over-scope pre-fetch |

> **Routing/contract test (R3-F1-batch6 — the prior table listed a phantom `POST /backtest/{id}/run` and a wrong-method `POST /backtest/compare`, and §B said "10 endpoints"; corrected to the real 9):** the T.9 endpoint-contract test **enumerates exactly these 9 routes + their HTTP methods** (asserting NO `/backtest/{id}/run` exists and that `compare` resolves only under `GET`), so a future drift in route set or method fails CI. **`queued`-state admission disposition (FR-039) is re-modeled onto the REAL one-step `create_backtest` boundary:** the slot is reserved synchronously at `POST /backtest`; introducing a `queued` verdict is therefore **NEW admission behavior on the existing one-step create** (today the same condition `503`s via `BacktestBusyError`), NOT a transition gated by a non-existent `/run` boundary — the `queued→running` CAS (FR-039/J.1) fires when the `AdmissionAccountant` promotes a waiting create, and **no new route is added** (the only additive route remains `GET /backtest-runtime/status`, K.2).

### K.2 New additive route (non-breaking)

- **`GET /backtest-runtime/status`** — read-only runtime optimization state. **Path PINNED to `/backtest-runtime/
  status` (decided, not "or") to avoid the verified collision** with the existing `GET /backtest/{run_id}` (K.1):
  FastAPI matches in declaration order, so a literal `/backtest/status` registered AFTER `/backtest/{run_id}` is
  shadowed — `run_id="status"` would hit `_validate_run_id`/`get_backtest` and 404, silently killing the additive
  route. The distinct `/backtest-runtime/` prefix cannot be captured as a `{run_id}`. (Belt-and-suspenders: if a
  future maintainer re-adds `/backtest/status`, it MUST be declared BEFORE `/backtest/{run_id}`.) A **routing
  contract test** asserts `GET /backtest-runtime/status` resolves to the status handler AND that `run_id="status"`
  is never shadowed by the status route. Does NOT alter any existing endpoint. **Public payload coarsened** to
  capability booleans + active/degraded/off states + breaker/seal-backfill/pitr-detector state enums +
  `schema_ok: bool`. Exact version strings / full git-SHA / integer schema_version / numeric resource config are
  exposed ONLY on a loopback/CLI (or authenticated) surface. A contract test pins the public payload shape AND
  asserts it OMITS exact versions/git-SHA/resource numerics. **Privileged-surface determination + rate limit
  (R2-F8 — the "loopback/privileged" boundary and the public route's rate posture were unspecified; if "loopback"
  were derived from a proxy-supplied header like `X-Forwarded-For`, the disclosure control would be trivially
  spoofable behind the reverse proxy):** "loopback/privileged" is determined SOLELY from the **kernel peer socket
  address** (the actual TCP/UDS peer the server accepted — `request.client`/`transport.get_extra_info('peername')`
  / UDS peer-cred), or an explicit **auth token**. A **forwarding header (`X-Forwarded-For`/`X-Real-IP`/
  `Forwarded`) can NEVER promote a request to the privileged (uncoarsened) payload** — header-derived loopback is
  explicitly rejected. The **public `GET /backtest-runtime/status` carries a per-client rate limit** (it performs
  per-request flag/breaker/PITR resolution, so it is a cost surface like `POST /backtest`). A contract test asserts
  (a) a request bearing a spoofed `X-Forwarded-For: 127.0.0.1` from a NON-loopback peer gets ONLY the coarsened
  payload, (b) the precise payload is served only to the real kernel-peer-loopback/authenticated surface, (c) the
  route is rate-limited. **Co-located-proxy fail-open closure (R5-F1-batch1 — kernel-peer-loopback is the
  RIGHT anti-spoof signal but it fails OPEN under the PRIMARY topology W-3 describes: a single-host Windows 11
  box very commonly fronts the FastAPI app with a SAME-HOST reverse proxy (nginx/IIS/Caddy on loopback), so the
  kernel peer of EVERY forwarded external request IS `127.0.0.1` — every unauthenticated internet client would
  then be classified loopback-privileged and receive the uncoarsened exact-version/git-SHA/schema_version/
  resource payload, fully defeating REQ-SEC-005 in production):** the privileged grant therefore **requires the
  explicit auth token by DEFAULT** (the safe posture that assumes a loopback-terminating proxy MAY be present);
  **kernel-peer-loopback is accepted as sufficient ONLY under an explicitly operator-configured
  `BT_STATUS_TRUST_PEER_LOOPBACK=true`** (default false) that an operator sets ONLY on a verified no-proxy (or
  non-loopback-terminating-proxy) deployment. With `BT_STATUS_TRUST_PEER_LOOPBACK` unset/false (default), a
  kernel-peer-loopback request WITHOUT the auth token gets only the COARSENED payload. The contract test adds:
  (d) GIVEN a co-located proxy forwarding an EXTERNAL client (kernel peer `127.0.0.1`) with
  `BT_STATUS_TRUST_PEER_LOOPBACK` unset/false, WHEN it requests `/backtest-runtime/status`, THEN it receives
  ONLY the coarsened payload unless it presents the auth token; (e) the precise payload is served on
  peer-loopback WITHOUT a token ONLY when `BT_STATUS_TRUST_PEER_LOOPBACK=true`. See §W-11 for the proxy-topology
  assumption + authoritative trust signal. *(REQ-OBS-029/035/039/040/043, REQ-SEC-005, NFR-021, R2-F8-batch1, R5-F1-batch1)*

### K.3 Error contracts (additive, distinct from result rows)

- A `PreflightEstimator` `reject` or queue-wait-timeout returns a **structured 4xx/503** (`422` for reject with
  `reason`; `503`/retriable for capacity, including `reason:'queue_full'` when `BT_QUEUE_MAX_DEPTH` is exceeded —
  R4-F8-batch3) with body `{status:'rejected'|'queued_timeout', reason, pred_ms,
  pred_rss_bytes}` — **NOT** a `completed` result row and **NOT** a zero-trade `BacktestResult` (so it can never hit
  the frontend no-trades trap). A reject-shape contract test asserts (a) the 4xx contract, (b) the FE renders
  "rejected/queued", (c) `metrics.total_trades` is not consulted on the reject path; **(d) a queue-full create is
  rejected pre-slot and a wait-timeout `queued` run returns `queued_timeout` then releases its reservation (AC-048h).**
  *(REQ-API, R5-F13-batch3, R4-F8-batch3)*

### K.4 MCP tool output shapes (additive-only)

- `backtest_get`, `sweep_results`, `backtest_compare`, `scans_get` output shapes are pinned additive-only by a
  schema-snapshot test — no field dropped/renamed/retyped, `total_trades` + the ~45 metric keys always present —
  so MCP agent consumers driving optimize/propose workflows do not silently break. **The MCP `backtest_get`/`scans_get`
  `status` field is also held to the legacy-five wire-value contract (queued/interrupted_by_restart/failed_with_timeout
  mapped per FR-052) — same as the HTTP GET + LIST surfaces (R2-F6-batch5).** *(REQ-FE-011)*

---

## L. UI / UX

**No functional frontend change. The result contract is preserved and contract-tested; the only code change is a
parity-preserving amendment to the equity-curve downsampler.**

- **L.1 — Result contract preserved (the frontend trap).** `BacktestResults{metrics, equity_curve, summary,
  warnings}`; `BacktestMetrics` ~45 keys; `EquityPoint{ts, equity, drawdown_pct?}`; `BacktestTrade` 19 fields +
  `strategy_kind`. **`metrics.total_trades` MUST always be present + correctly typed** — if absent/renamed the UI
  routes completed runs to the "no trades simulated" fallback (`BacktestResultsPage.tsx:255`), which looks like
  data loss. Only ADD optional nullable keys (`metrics.engine_path`, `metrics.cache_provenance`,
  `summary.jit_warm_ms`, `warnings[]` entries like `max_same_sector_not_enforced`/`columnar_degraded`) — none read
  by the existing render path. *(REQ-FE-009, discovery §5)*
- **L.2 — Equity-curve LTTB downsampler amended to keep the max-DD trough.** Standard LTTB can drop a deep
  single-bucket trough; `_downsample_equity` is amended to always include the first point, last point, AND the
  global max-drawdown trough point. Its golden oracle is re-frozen against the amended output. A
  trough-preservation fixture asserts the trough survives downsampling. The **manifest still hashes the full
  pre-downsample JSONB**, so the trough change affects only the GET view, never the hash basis. *(REQ-FE-004/003)*
- **L.3 — Path-dependent metrics render correctly.** Sharpe/Sortino/max-DD/run-up depend on `equity_curve` ORDER;
  the SoA/numba rewrite preserves curve ordering exactly so the rendered charts match the oracle. *(discovery §6)*
- **L.4 — Inf/NaN metrics coerced to JSON `null` (NEVER a string sentinel — R3-F9-batch2).** `profit_factor` on an
  all-wins run, edge-case Sharpe/expectancy → a documented oracle-frozen **JSON `null`** that survives JSONB write →
  GET read → render without a serialization error and without dropping `total_trades`. **String sentinels are
  FORBIDDEN in numeric metric keys (the prior "null OR a fixed string" was a frontend-contract conflict: FR-037/T.9
  freeze each key's single type, so a key that is a `number` on normal runs and a `string` sentinel on degenerate
  runs is a union the single-type snapshot cannot express, AND an existing FE numeric formatter like `toFixed`
  applied to a string throws at render — the total_trades-trap class).** All degenerate numeric metrics standardize
  to `null`, keeping every numeric key single-typed `number|null`; `metrics_keys.json` declares the nullable-number
  type; an FE render test asserts the `null` path renders without a formatting exception and never drops
  `total_trades`. *(REQ-FE-008; R3-F9-batch2)*
- **L.5 — Bidirectional deploy-order compatibility.** A NEW frontend rendering an OLD backend response (missing the
  new optional keys) AND an OLD frontend rendering a NEW backend response (carrying additive keys) both render and
  surface `total_trades` + all shared ~45 keys. **The GET-result `status` field is wire-stable: the new internal
  states `queued`/`interrupted_by_restart` are mapped to legacy wire values (`queued→pending`,
  `interrupted_by_restart→failed` — TERMINAL, since backtests are not resumable, W-1) BEFORE serialization (FR-052),
  so an OLD FE never receives an unknown
  non-terminal status — it cannot blank the body or stop polling.** A new `close_reason` (e.g. `mr_target`) is a
  display-only string the FE renders generically (never branched-on) and degrades to a safe generic display — never
  crashes/blanks/drops the row. **Unknown-`close_reason` render claim is CODE-VERIFIED + TEST-GATED (R5-F6-batch5 —
  this claim is structurally IDENTICAL to the original "old FE degrades gracefully on a new status enum" claim that
  was FALSE on code inspection (`BacktestResultsPage.tsx` branches; `types.ts` `isPending`) and had to be corrected
  with a code citation + paired test; `mr_target` MAY appear in `BacktestTrade.close_reason` once regime-multistrategy
  lands (R6-F2-batch4 — it is NOT a current engine token; today the engine emits no `mr_target`, so the unknown-token
  forward-compat path is what is gated, not a present value)
  on the `GET /trades` wire + the trades-table UI, so if any FE switch/badge/icon map is keyed on `close_reason` it
  falls through unverified):** the spec MUST either (a) CITE the actual FE code path proving `close_reason` is
  rendered generically and never branched-on (the trades-table cell that renders it as a raw string / via a default
  fallback in any badge map), mirroring the `BacktestResultsPage.tsx:255` / `types.ts:31` citations used for
  `status`, OR (b) add a dedicated **T.9 FE-render contract test**: GIVEN a `GET /backtest/{id}/trades` response
  carrying an UNKNOWN `close_reason` (`mr_target`), WHEN the trades table renders, THEN the row renders with a safe
  generic display and is **never dropped/blanked** and no formatter throws. This is gated under AC-043. Proven by paired old→new / new→old contract tests across GET result,
  **the GET `/backtest` LIST endpoint (per-row status), the MCP `backtest_get`/`scans_get` status field
  (R2-F6-batch5),** `/backtest-cache/status`, and `/backtest/compare`, INCLUDING an explicit old-FE-vs-new-status-value test asserting
  the mapped wire status keeps polling alive. *(REQ-FE-010/014/016)*
- **L.6 — Status surface (optional UI consumption).** The additive `GET /backtest-runtime/status` route's coarsened public
  payload (capability booleans + degrade states) is available for an optional ops panel; not required by the
  existing pages. *(REQ-OBS, §K.2)*

---

## M. Backend Requirements (per-component → architecture §3.1–3.12)

> Convention: **[NEW]** net-new module; **[MODIFIED]** existing file changed under semantic-parity;
> **[UNCHANGED-CONTRACT]** behavior frozen, internals may be re-pointed.

- **M.1 — `KlineStore` [NEW]** (`backend/services/kline_store.py`, §3.1; P2 seam, P5 tiers). Layered READ
  abstraction; delegates ALL WRITE to `KlineCacheService` (unchanged SOR). Tier-routes Arrow hot → Feather mmap →
  Parquet → Postgres; routes any range including `≥ frontier` exclusively to Postgres; `iter_klines_streamed`
  server-side-cursor streaming seam bounds build-time peak; generation-token snapshot contract for stitched
  columnar+PG reads. Owns `kline_tier_hits` provenance. *(FR-027/033/034, NFR-012/013; REQ-STORE-012..016/030)*
- **M.2 — `SealedManifest` + completion-frontier [NEW]** (§3.2; P1 logic, P5 materialized-state). Owns the seal
  predicate (`completion_frontier`, monotonic UTC ratchet + skew margin), day-class taxonomy, negative cache,
  reverify-pending gate, **read-path lazy-seal-from-SOR (seals complete past-frontier stored days in-place, 0 Bybit,
  BEFORE gap-compute — closes the post-v58/pre-backfill RC-3 window, R2-F2-batch2)**, `unsealed_days(range)`,
  `halt_seal_writes()` latch. Runtime loader + `SealBackfillRunner`
  call the SAME frontier function. *(FR-019..024/026; REQ-CACHE-*, REQ-STORE-001..011)*
- **M.3 — `SoADatasetBuilder` [NEW]** (§3.3; P3). Converts each symbol to structure-of-arrays
  (`open_time:int64[]`, OHLCV:`float64[]`); precomputes the global sorted-unique timeline + vectorized
  scan-anchor `searchsorted` binding (once); degenerate-run short-circuit <100ms; releases Records as consumed.
  Parses each candle ONCE (no per-row dict + six `float()` casts). *(FR-015/017, NFR-003/004/012; REQ-ENG-001..007, REQ-PERF-006/007/008/044)*
- **M.4 — `engine_kernel` [NEW]** (§3.4; P4 numba + pure-Python fallback of record). `@njit` per-candle kernel
  (liquidation→SL→TP, uPnL, once-per-tick basket equity, MFE/MAE, funding, trailing/time) over column arrays + a
  compact position SoA; receives ONLY typed numpy arrays/scalars across the nopython boundary (no reflected
  list/typed.Dict/Python object in the hot path); compiles `boundscheck=False` for the timed path with a CI
  `boundscheck=True` fuzz/differential build proving no OOB; the vectorized first-touch fast-path streams its
  barrier scan in bounded chunks. The pure-Python lane materializes list/memoryview at chunk entry (no element-wise
  numpy indexing) and meets the **≥150k HEAVY-evals/s floor** (`ticks×B` unit, NFR-003 reconciled to architecture §11.2 — R3-F1/F2-batch2). *(FR-013/016/018, NFR-003; REQ-DEP-019/020, REQ-ENG-*, REQ-PERF-005/011/045)*
- **M.5 — `DrilldownLoader` [NEW]** (§3.5; P2 fix, P5 cache). Lazy per-symbol 1m loader; per-bar fetch failure
  falls back to 5m for that bar only (never aborts, never persists partial 1m); no-1m-candles drill falls back to
  5m and never fabricates a fill; full-book-coverage rule. *(FR-028/029/030; REQ-DRILL-013/020/023)*
- **M.6 — `SweepRunner` [NEW]** (§3.6; **P2 parallelism + P3 shared-SoA + P6**). Parallel combo execution; the
  **shipped-once shared SoA lands at P3** (the compact SoA does not exist until then — at P2 the pool shares legacy
  per-symbol kline lists and is gated only for parallelism + IPC-independence on a small fixture, NOT compact-RSS).
  Host selection via the capability predicate (`USE_PROCESS_POOL = HAS_NUMBA AND shared_memory-usable AND
  spawn`; prod Windows-11 → ProcessPool + `shared_memory`; else `ThreadPoolExecutor` over the `nogil=True` kernel;
  seq fallback); parent-side pool pre-warm + budget-derived caps (cgroup OR `BT_CPU_BUDGET` config — NFR-013); the
  global compute-thread semaphore coordinates with the `_MAX_CONCURRENT=3` slots so nested parallelism never
  oversubscribes (FR-049); persist-then-release + GC tune; `finally`-scoped release of all segments on every terminal
  path (Windows last-handle-close semantics); live-breaker dispatch gate. *(FR-031/032, NFR-005/013;
  REQ-SWEEP-002/003/006/008/009, REQ-PERF-021/026/027/041)*
- **M.7 — `GoldenMasterOracle` [NEW]** (§3.7; P0, gates ALL phases). Stored-snapshot parity harness (run current
  engine, freeze output) — NOT inline magic numbers; adds the explicit per-trade-sum three-way reconciliation the
  weak `_assert_reconciles` lacks; the float64 re-freeze at P3; per-phase NO-OP fixture; the canonical 90d×50sym
  frozen result fingerprint. *(FR-001..014, NFR-007..010; REQ-PAR-*, REQ-TEST-*)*
- **M.8 — `[MODIFIED]` core services (semantic parity required).** `backtest_engine.py` (data-layout re-point,
  decisions frozen); `backtest_service.py` [UNCHANGED-CONTRACT] (KlineStore seam, batched load + COPY persist,
  atomic 3-write txn, terminal-state CAS, B&H concurrent reroute); `kline_cache_service.py` (manifest-aware
  coverage, `_PAGE_SIZE` 200→1000 + outer chunk loop, shared breaker reuse); `trading_rules.py` SSOT UNTOUCHED;
  `backtest_metrics.py` single-pass O(curve+trades). *(FR-027/036/038/039, NFR-006/023)*
- **M.9 — `PreflightEstimator` [NEW]** (§3.9; P2 gate, cross). Admission + envelope predictor. **Compute term
  re-expressed in the PINNED eval basis (R4-F4-batch5 — the prior `candles×scans×B` formula carried a SPURIOUS extra
  `scans` factor and used total-candles instead of ticks, over-counting by orders of magnitude and scaling
  super-linearly in scan count while the real engine HEAVY term is O(ticks×B) and LIGHT is O(total_candles)
  INDEPENDENT of scan count; the §I-preamble explicitly rejects `candles×scans×B`):** `predicted_engine_work =
  a·light_advance_count (≈ total_candles) + b·heavy_eval_count (≈ ticks×B)` with `a,b` host-calibrated — NOT
  `candles×scans×B`. (`Σ_scans(window candles) ≈ total_candles`, so a per-scan-window formulation must reduce to
  `total_candles`, not multiply by scan count.) Plus cold Bybit pages `ceil(missing/1000)`, drill fraction,
  cold-columnar-build term; `AdmissionAccountant`
  reservation/queue; rejects a WIDE run whose FINAL SoA exceeds the klines budget before it takes a slot **AND
  rejects pre-slot when `predicted_wall_ms > the resolved-lane budget` (numba vs pure-Python) so an infeasible
  no-numba WIDE is rejected with the 4xx contract rather than admitted-then-killed at 120s — R2-F1-batch4**; brackets
  actual within ±50% on deterministic terms (the ±50% bracket must hold as SCANS, not just symbols, scale —
  R4-F4-batch5). **AGGREGATE-RSS admission (R3-F7-batch3 — the per-run gate rejects a
  SINGLE run over budget (AC-018) but 3 concurrent canonical runs (≤1GB each) + a sweep pool holding the shared SoA
  can SUM past the single-host budget, with only the runtime watchdog as backstop — the V-6 OOM risk):** the
  `AdmissionAccountant` ALSO enforces a SUM rule — admit a new run/sweep only when `Σ(reserved per-run predicted peak
  RSS) + sweep-pool footprint ≤ BT_RSS_BUDGET`; otherwise it QUEUES or rejects PRE-slot (the watchdog is the
  backstop, not the primary control). *(FR-039/040/049, NFR-012/024; REQ-PERF-037/038/039; R3-F7-batch3 — gated by AC-048d)*
- **M.10 — `SealBackfillRunner` [NEW]** (§3.10; P1, off the boot path). Deferred, resumable, throttled historical
  sealer; bounded chunked-commit UPDATE; mutates ONLY coverage/manifest + lifecycle (never a candle row);
  checkpoint marker (enumerated states) is the SOLE gate for "cache-complete"; disjoint advisory-lock keys;
  paused/resumed by SAFE_MODE; cold-fetches a never-seen range via `ensure_coverage`/`warmup` only. *(FR-050; REQ-MIG-018/019/021)*
- **M.11 — `SymbolLifecycleRefresher` [NEW]** (§3.11; P1, off the boot path). Populates/refreshes
  `symbol_lifecycle`; drives the late-lifecycle reclassification of MUTABLE-post-seal columns without
  un-seal/refetch/sha-change. *(FR-051; REQ-MIG-005/015)*
- **M.12 — `MaintenanceAdmin` [NEW]** (§3.12; cross). CLI-only (not bound to the public port) DB-identity-guarded
  surface: seal-reset, manifest-rebuild-from-SOR (0 Bybit refetch, interruptible/resumable/idempotent), DR,
  provenance-enumeration. **Also OWNS the out-of-band index builds via `ensure_indexes()` (post-migration async boot
  step, invoked AFTER `schema_version=58` is confirmed — NOT `_MIGRATIONS`, since CIC is illegal in a transaction):
  `CREATE INDEX CONCURRENTLY IF NOT EXISTS` for `idx_coverage_unsealed` (`WHERE NOT sealed OR reverify_pending`) +
  the widened `idx_backtest_runs_status`, with leftover-INVALID-index drop-on-retry + bounded `lock_timeout` +
  idempotent re-run (N.4 / R2-F3-batch3).** Is the operator boundary that may WRITE `bt_flag_config` (P.9).
  *(FR-051, NFR-021; REQ-ROLL-024/025/030/032/033, REQ-CACHE-049, REQ-SEC-007)*
- **M.13 — `CapabilityResolver` / `SafeModeController` [NEW]** (§7.2). One resolver computes `effective = resolve(
  DB-override ?? ENV-default) AND HAS_<cap> AND boot_validation` per run; `SafeModeController` (injected at
  lifespan) performs SAFE_MODE actions (b)/(c)/(d) in pinned idempotent order; ENV/file SAFE_MODE short-circuits
  with Postgres down. *(FR-044/045/046; REQ-ROLL-001/002/003/004)*
- **M.14 — `RunReaper` [NEW] (boot-time crash-orphan reclaimer — R3-F1-batch1/R3-F4-batch3).** Closes the gap that
  the terminal state `interrupted_by_restart` had a wire-map (FR-052 → `failed`) and a CHECK-list slot (N.2) but
  **NO writer/owner**: backtests run in a `ThreadPoolExecutor` inside the shared FastAPI process, so on a
  restart/crash the in-memory `threading.Timer`/`Event` are gone but the `backtest_runs` row stays `running` (or
  `queued`) forever — and the verified FE (`isPending = status==='pending'||'running'`, `types.ts:31`) would then
  **poll that orphan forever**. `RunReaper` is invoked from the **`BacktestService` lifespan startup hook, AFTER
  `schema_version=58` is confirmed** (and before admission re-opens). On the single-worker PRIMARY target (W-3),
  EVERY `status IN ('queued','running')` row at boot is by definition an orphan of a prior process generation; on a
  multi-instance/[FLEET] deploy it scans for `running`/`queued` rows whose owning process/thread is provably gone
  (`instance_id`/heartbeat mismatch vs the current generation). It **CAS-transitions** each such orphan
  `running|queued → interrupted_by_restart` (first-writer-wins, same guarded CAS as FR-039, so it cannot race a
  live terminal writer), which maps to the terminal wire value `failed` (FR-052) so the FE stops polling, and it
  releases the `_MAX_CONCURRENT` slot + the `AdmissionAccountant` reservation **exactly once** per reclaimed row.
  It writes `terminal_reason='interrupted_by_restart'` + the partial `stage_timings`/fingerprint (FR-041) and is
  idempotent (a second boot finds no orphans). *(FR-039/FR-052, REQ-API-012/015, REQ-OBS-009/016; cross — gated by AC-048a)*

---

## N. Database / Data

### N.1 v58 sealed-manifest columns (table `kline_cache_coverage`, PK `(symbol, interval, date)`)

All `ADD COLUMN IF NOT EXISTS` with constant defaults → catalog-only, no table rewrite (PG11+), idempotent. The
seal grain is per-symbol-day, which is exactly the coverage grain (so NOT on `backtest_runs`).

| Column | Type | Default | Meaning |
|--------|------|---------|---------|
| `sealed` | `BOOLEAN NOT NULL` | `false` | Day fully past frontier AND durably stored + validated. Immutable-once-true (content columns). Gap/fetch-eligibility = `(NOT sealed) OR reverify_pending` in `[start, frontier]` (R2-F3-batch2 — a reverify-pending class-3 day stays fetch-eligible). |
| `day_class` | `SMALLINT NOT NULL` | `0` | Enum `0=unsealed,1=sealed-full,2=sealed-short-listing,3=sealed-interior-structural-gap,4=sealed-empty-negative,5=sealed-delist-snapped,6=derived-coarse`. |
| `gap_count` | `SMALLINT NOT NULL` | `0` | Known-missing bar count. **Invariant reconciliation (R2-F6-batch2):** the legacy `candle_count` is written by the `_update_coverage` GREATEST upsert (max-OBSERVED count, §B/§E), NOT expected-bars-for-day, so `row_count == candle_count − gap_count` does NOT hold on an interior-gap day. The pinned invariant is therefore `stored_row_count == expected_bars(day) − gap_count`, where `expected_bars(day)` is DERIVED from interval + UTC day length, snapped to `[listing_time, delist_time]` (listing/delist truncation), NOT from `candle_count`. `candle_count` retains its GREATEST max-observed meaning unchanged (v58 does NOT alter its write semantics); `gap_count` + `expected_bars` are the manifest-grade fields. A `day_class=3` interior-gap fixture asserts `stored_row_count == expected_bars − gap_count`. |
| `gap_ranges` | `JSONB NULL` | `NULL` | Queryable known-gap boundaries `[{first_open_ts,last_open_ts}]` so the loader skips exactly the negative-cached sub-windows. |
| `reverify_pending` | `BOOLEAN NOT NULL` | `false` | One-shot post-frontier reverify gate for an ambiguous interior hole (WARM/refetchable until settled). Folded into the fetch-eligible predicate `(NOT sealed) OR reverify_pending` + indexed by `idx_coverage_unsealed`'s `WHERE NOT sealed OR reverify_pending` (R2-F3-batch2). |
| `listing_snapped` | `BOOLEAN NOT NULL` | `false` | Day's first bar snapped to `symbol_lifecycle.listing_time`. Persisted as a column (not folded into `day_class`). |
| `delisted` | `BOOLEAN NOT NULL` | `false` | Day past `symbol_lifecycle.delist_time`. |
| `content_sha256` | `BYTEA NULL` | `NULL` | Canonical hash (sorted by `open_time`; int64-ms epoch; IEEE-754 LE float64 OHLCV; fixed column order). NULL = no comparable hash (no check, no refetch). |
| `sha_version` | `SMALLINT NOT NULL` | `0` | Canonicalization-scheme version; an older-scheme sha reads as "no comparable hash". |
| `manifest_semantics_version` | `SMALLINT NOT NULL` | `1` | Versions the seal-logic/day-class semantics (DISTINCT from `sha_version`). |
| `fine_base_generation` | `BIGINT NULL` | `NULL` | For `day_class=6`: generation of the sealed fine base it derived from (auto-invalidates stale coarse). |
| `data_generation` | `BIGINT NOT NULL` | `0` | SOR-wide data-generation token snapshot stamped at row-WRITE time from the `sor_data_generation` singleton. **PITR invalidation is READ-TIME COMPARE, not a mass re-stamp (R2-F8-batch2 — resolves the contradiction between "MUTABLE-post-seal via PITR re-stamp" and an unbudgeted table-wide UPDATE): invalidation compares the artifact's/row's embedded token against the global `sor_data_generation` singleton at READ time; a mismatch invalidates + rebuilds that artifact. NO per-row UPDATE of `kline_cache_coverage` is performed on a PITR bump (the bump touches only the singleton), so there is no table-wide write/bloat/lock.** Mutable only via this read-compare semantics, not an in-place re-stamp scan. |
| `materialized` | `BOOLEAN NOT NULL` | `false` | Parquet partition fsync'd+renamed. DISTINCT from `sealed`. |
| `first_open_ts` / `last_open_ts` | `BIGINT NULL` | `NULL` | int64-ms epoch bounds of stored rows. |
| `sealed_at` | `TIMESTAMPTZ NULL` | `NULL` | Seal provenance (UTC). |
| `fetched_at` | `TIMESTAMPTZ` | *(pre-existing)* | Already present (`:655`); referenced by TTL-exempt logic, NOT re-added by v58. |

**Post-seal mutability contract.** FROZEN once `sealed=true` (never silently UPDATEd; a change requires an explicit
un-seal → re-verify → re-seal + sha recompute): `sealed`, `content_sha256`, `sha_version`, `first_open_ts`,
`last_open_ts`, `candle_count`, **`gap_count`, `gap_ranges` (frozen-WITH-content — the known-gap geometry is part of
the hashed content basis; changing it requires the same un-seal→re-verify→re-seal path, R5-F5-batch2)**, `sealed_at`.
MUTABLE via documented paths: `listing_snapped`/`delisted`/`day_class`
(lifecycle reclassification — bytes unchanged), `reverify_pending` (one-shot reverify), **`materialized` and
`fine_base_generation` (materialization-state + derived-coarse provenance — R5-F5-batch2: REQ-STORE-027 explicitly
REQUIRES `materialized` to flip post-seal — `true→false` on GC/quarantine "clears the flag ATOMICALLY with delete"
and `false→true` on rematerialize "rebuild-from-SOR sets the flag" — so an implementer enforcing "frozen unless
listed mutable" on a sealed row would WRONGLY freeze `materialized` and break GC/rematerialize self-healing; the
rule is "content/seal columns frozen; materialization-state + derived-coarse-provenance columns may change
post-seal").** `data_generation` is **NOT
re-stamped in place** — PITR invalidation is a READ-TIME compare of the row/artifact token vs the
`sor_data_generation` singleton (R2-F8-batch2), so it never participates in a post-seal mass UPDATE. **Every manifest
column thus has a STATED post-seal disposition (no column omitted from both lists — R5-F5-batch2).** A test asserts a
sealed day's `materialized` can transition `true→false→true` (GC then rematerialize) with ALL content columns
(`content_sha256`/`first_open_ts`/`last_open_ts`/`candle_count`/`gap_count`/`gap_ranges`) **byte-unchanged**.
*(REQ-MIG-015, REQ-CACHE-043, REQ-STORE-027; R5-F5-batch2)*

**N.1a — `kline_cache` OHLCV column type is PINNED for lossless float64 round-trip (REQ-STORE-040).** The
tri-source `content_sha256` gate (AC-011) and the columnar==Postgres byte-parity gate (AC-031) BOTH hash a
**Postgres-read-rebuild** source, so the stored OHLCV type MUST round-trip the Bybit-string → stored → IEEE-754
float64 path **bit-identically**. The existing `kline_cache` OHLCV columns are therefore pinned to **`DOUBLE
PRECISION` (IEEE-754 binary64)** — NOT `NUMERIC`/`DECIMAL` (whose base-10 value generally does NOT equal the float64
the columnar tier stores, and which forces a `Decimal` coercion `_num:1449` that can diverge at the ULP). **VERIFIED:
production `kline_cache` OHLCV is already `DOUBLE PRECISION` (`async_persistence.py:624-628`), so the NUMERIC branch
is DEAD in production.** **NUMERIC handling reconciled to fail-closed-block, NOT migrate (R6-F3-batch1 — a full table
rewrite of the partitioned `kline_cache` SOR is FORBIDDEN by NFR-014 catalog-only-v58 / NFR-015 expand-only per N.1c,
and "assert `float64(numeric)==columnar_float64`" contradicts the single-rounding rule that the hash never relies on a
double-rounding `float64(numeric)` re-derivation):** a deployed table using `NUMERIC` for OHLCV is an UNSUPPORTED
legacy configuration — v58 records the invariant and a boot/CI **fail-closed guard** asserts the OHLCV type is
`DOUBLE PRECISION`; a NUMERIC table causes the columnar/hash path to **REFUSE to run (fail loud)** rather than being
migrated (no rewrite) and rather than hashing re-derived `float64(numeric)` bytes. A test asserts the
Postgres-read-rebuild source of the tri-source hash converts
bit-identically to the Bybit-ingest and Parquet-rebuild sources **on the `DOUBLE PRECISION` SOR**. *(REQ-STORE-040, REQ-TEST-005; N, NFR-007, NFR-014/015, N.1c; R6-F3-batch1)*

**N.1b — ONE symbol + ONE interval canonicalization across ALL keying surfaces (REQ-CACHE-045).** A single
documented `canonical_symbol()` and `canonical_interval()` pair is applied UNIFORMLY across: signal/scan symbols,
the `kline_cache` PK, the `kline_cache_coverage` manifest PK, lifecycle rows, the Bybit fetch ticker (`category=
linear` + interval mapping), the Parquet/Feather partition path, all in-process cache keys, AND **the
symbol→int-code map the numba kernel needs across the nopython boundary (M.4)**. Alternate symbol forms (e.g.
`BTCUSDT` vs `BTC/USDT:USDT`) MUST resolve to ONE key; an unsupported interval is REJECTED (not silently mapped). A
test asserts (a) alternate symbol spellings collapse to one cache key + one int-code, (b) an unsupported interval
raises, (c) the Parquet partition, Postgres PK, Arrow key, and int-code map agree on the identical canonical form
(a mismatch would silently split the cache or break cross-tier byte-identity). *(REQ-CACHE-045; N, M.3/M.4, N.3)*

**N.1c — `open_time` STAYS `TIMESTAMPTZ`; the int64-ms canonical unit is DERIVED, NOT stored (REQ-STORE-040
epoch-unit clause — R5-F1-batch2).** N.1a pinned the OHLCV float64 round-trip but did NOT address REQ-STORE-040's
SECOND clause ("a single int64-millisecond unit for `open_time` across kline_cache, manifest first/last_open_ts,
Parquet/Feather, the Arrow hot frame, and the int64 SoA arrays"), leaving it orphaned and **factually false against
the live schema**: `kline_cache.open_time` is **`TIMESTAMPTZ`**, PK `(symbol, interval, open_time)`
(`async_persistence.py:623`), NOT a stored `BIGINT`-ms column. This is reconciled — NOT by retyping the column:
- **`kline_cache.open_time` REMAINS `TIMESTAMPTZ`.** Retyping it to `BIGINT` would be a **full table rewrite** of the
  partitioned SOR, violating NFR-014 (catalog-only / sub-second v58) and NFR-015 (expand-only). **v58 MUST NOT retype
  `open_time`; an implementer reading REQ-STORE-040 literally must NOT attempt it.**
- **The canonical int64-ms unit is DERIVED at hash/load time**, exactly as FR-025 already does
  (`floor(extract(epoch FROM open_time) * 1000)`), which is well-defined precisely BECAUSE the column is a
  timestamp. REQ-STORE-040's "across kline_cache" is restated to mean **the DERIVED canonical unit** every tier
  agrees on (the int64-ms value the SoA arrays, manifest `first/last_open_ts` BIGINT columns, Parquet/Feather, and
  the Arrow frame all carry), NOT the stored column TYPE of `kline_cache`. The manifest `first_open_ts`/`last_open_ts`
  ARE stored `BIGINT`-ms (N.1); `kline_cache` is the one tier that stores a timestamp and derives.
- **T.6 derivation test (R5-F1-batch2):** the `TIMESTAMPTZ → int64-ms` derivation is asserted **bit-exact** and
  EQUAL to the Bybit-native ms on the 5m and 1m grids — INCLUDING a stored bar carrying **nonzero sub-second
  microseconds** (asserting `floor` truncates correctly, never rounds up) — so the **Postgres-read-rebuild leg of
  AC-011 (tri-source sha) and AC-031 (columnar==Postgres)** has a well-defined int64-ms time basis and cannot diverge
  from the Bybit-ingest/Parquet legs on the hash's time field. *(REQ-STORE-040, REQ-TEST-005, FR-025; N, NFR-014/015, AC-011/031; R5-F1-batch2)*

### N.2 New control/provenance tables + additive run columns (v58)

- **`bt_flag_config`** — DB-backed flag control table (source of truth layered above ENV defaults); read with
  read-your-writes/staleness-guard semantics; per-run re-resolution. **WRITE surface is operator-only** (CLI/loopback/
  authenticated-admin, same boundary as `MaintenanceAdmin`); no public HTTP route and no MCP tool may write it; the
  resolver and §K.2 status route are READ-ONLY over it (FR-045 / P.9). It MAY carry the `BACKTEST_SAFE_MODE` master
  kill-switch row, so its write integrity IS the kill-switch's integrity. *(REQ-ROLL-003, REQ-SEC-007)*
- **`sor_data_generation(value BIGINT)`** singleton — monotonic SOR data-epoch counter, bumped on any
  PITR/restore/failover or detected drift. **`sor_identity`** row — last-seen `{system_identifier, timeline_id,
  control_digest}` for PITR-rewind detection; the EXPECTED identity is **operator-provisioned**
  (`BT_EXPECTED_PG_SYSTEM_IDENTIFIER`), NOT self-seeded. **Single-row enforcement + atomic bump (R2-F7-batch2 — a
  duplicated or racily-written singleton makes "the" generation ambiguous and silently corrupts the entire PITR
  self-invalidation scheme since `data_generation` is embedded in every derived artifact):** BOTH tables enforce
  exactly-one-row via the `id boolean PRIMARY KEY DEFAULT true CHECK(id)` pattern (a second insert violates the PK).
  The bump is **atomic + monotonic-non-decreasing**: `UPDATE sor_data_generation SET value = GREATEST(value, $new)
  WHERE id RETURNING value` (or an advisory-locked `value = value + 1` increment), so concurrent bumps can never
  lose an increment or move the counter backward. A concurrency test asserts exactly one row survives concurrent
  inserts AND the value is monotonic non-decreasing under concurrent bumps. *(REQ-CACHE-043, REQ-SEC-006, R2-F7-batch2)*
- **Seal-backfill completion marker** — persisted object created by the v58 DDL; enumerated states
  (`not_started/in_progress/complete`) + progress counters; survives restart; the SOLE gate for any
  "cache-complete/fully-optimized" status (`schema_version=58` does NOT imply backfill complete). *(REQ-MIG-021)*
- **`symbol_lifecycle` — net-new v58 table (R5-F3-batch2 — it was MISSING from this N.2 enumeration even though
  NFR-014 lists v58 as shipping "(lifecycle table)" and FR-024 + the day-class logic depend on it, so the
  REQ-MIG-037 migration-completeness meta-test would not draw it from the inventory; its DDL was also under-specified
  vs REQ-MIG-009/010):** explicit DDL `symbol_lifecycle(symbol TEXT PRIMARY KEY, listing_time TIMESTAMPTZ NULL,
  delist_time TIMESTAMPTZ NULL, source TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`, created
  `CREATE TABLE IF NOT EXISTS` (idempotent, in the v58 callable set). The **`PRIMARY KEY (symbol)`** on the
  N.1b-canonical symbol is the conflict target REQ-MIG-010's idempotent refresh upsert needs (without it the table
  could hold duplicate per-symbol rows that break point-lookup seal logic); the **`source` provenance column** is how
  REQ-MIG-010's refresh implements **manual-override precedence** — an `ON CONFLICT (symbol) DO UPDATE` COALESCE/skips
  rows whose `source` marks an operator correction, so a background refresh MUST NOT clobber operator-corrected
  listing/delist values. `listing_time`/`delist_time` are **`TIMESTAMPTZ`** (consistent with the R5-F1-batch2
  decision that lifecycle/time columns stay timestamps and any int64-ms unit is derived, not stored). An absent/NULL
  row means `listing=-inf/delist=+inf` (fetch-everything, NEVER "out of life ⇒ seal-known-empty" — REQ-MIG-009
  invariant). Enumerated in the REQ-MIG-037 completeness meta-test by real catalog name and in the v58
  `CREATE TABLE IF NOT EXISTS` set. *(REQ-MIG-009/010, NFR-014, FR-024; R5-F3-batch2)*
- **`bt_flag_audit`** — durable record of each resolved flag snapshot (audit log, not a control surface). *(REQ-MIG-037)*
- **Migration-completeness meta-test inventory (REQ-MIG-037 — R5-F6-batch3 + R5-F2/F3-batch2): the meta-test asserts
  NOT ONLY that additive COLUMNS are present, but that EVERY net-new v58 TABLE exists resolved BY REAL CATALOG NAME
  + CREATE-before-INSERT statement ordering.** The net-new-table inventory the meta-test enumerates by real name is:
  `sor_data_generation`, `sor_identity`, `seal_backfill_marker`, `bt_flag_config`, `bt_flag_audit`,
  **`symbol_lifecycle`** (R5-F3-batch2), and the schema-migration log; and the additive-column targets on the REAL
  tables `backtest_runs`, `backtest_results`, **`mcp_sweep_results`** + **`mcp_sweeps`** (NOT a nonexistent
  `sweep_results` — R5-F2-batch2). It ALSO asserts **CREATE-before-INSERT ordering** (every control table is CREATEd
  before any statement INSERTs into it — the `bt_flag_config` deferred-marker INSERT must not precede its CREATE; arch
  line 1017/1018) so the fresh-DB `0→58` apply (AC-012, REQ-MIG-040) cannot boot-crash-loop on a missing relation.
  *(REQ-MIG-037/040, R5-F2-batch2, R5-F3-batch2, R5-F6-batch3)*
- **Additive nullable columns** on `backtest_runs` (`stage_timings`, `engine_fingerprint`, `peak_open_positions`,
  `turnover`, `seal_backfill_marker` ref), `backtest_results` (`equity_curve_manifest_hash`,
  `manifest_hash_version`, optional JSONB metric keys), and the **per-combo `mcp_sweep_results` + run-state
  `mcp_sweeps` tables (fingerprint/provenance) — these are the REAL persisted sweep tables (`async_persistence.py:
  897`/`:865`); there is NO table named `sweep_results` (that is the name of an MCP TOOL, `sweep_tools.py:246`, NOT a
  relation — R5-F2-batch2; an `ADD COLUMN` on `sweep_results` would raise `relation "sweep_results" does not exist`,
  abort the v58 txn, strand `schema_version` at 57, and crash-loop boot under the held advisory lock). §K's
  `sweep_results` MCP-tool references are unchanged (tool name, not table).** — all enumerated
  in the migration-completeness meta-test (by REAL catalog name) + OBS schema-snapshot. New `backtest_runs.status` enum values: `queued`,
  `interrupted_by_restart` (alongside existing `cancelled`) — these are **INTERNAL persistence states; they are NOT
  emitted on the `GET /backtest/{id}` wire** (mapped to legacy values before serialization per FR-052 — `queued→
  pending`, `interrupted_by_restart→failed` (terminal — backtests are not resumable, W-1/R2-F2-batch4)), so no existing frontend sees an unknown status. **`mcp_sweeps` run-state reconciliation (REQ-ROLL-017/018 — R5-F2-batch2): the
  real `mcp_sweeps.status` CHECK enum is `('queued','running','completed','cancelled','failed','interrupted')`
  (`async_persistence.py:865`), so a sweep row killed mid-run is reconciled to the EXISTING `'interrupted'` state
  (NOT a new `'interrupted_by_restart'`, and NOT `'pending'` which is not in the enum — `'queued'` is); `backtest_runs`
  reuses its OWN new `interrupted_by_restart` for consistency with its wire-map, while `mcp_sweeps` keeps its existing
  `'interrupted'`.** *(REQ-OBS-009/016, REQ-FE-003/015, REQ-ROLL-017/018; R5-F2-batch2)*
- **`backtest_runs.status` CHECK-constraint widen — REQUIRED v58 DDL sub-step (R2-F1/R2-F1-batch3 — the live column
  is `status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed','cancelled'))`
  at `async_persistence.py:664-665`, a CHECK-constrained TEXT, NOT free text; the new states CANNOT be introduced by
  `ADD COLUMN IF NOT EXISTS` and the first CAS write of `status='queued'` would raise a CHECK violation, so the run
  could never be enqueued — this is the identical defect class as the prior v22 incident at lines 1511-1516):** v58
  carries an **explicit, ordered constraint-swap sub-step** with an **execution-idempotency guard (R5-F4-batch2 ≡
  R5-F1-batch3 — Postgres has NO `ADD CONSTRAINT IF NOT EXISTS` for CHECK constraints, so the unconditional
  DROP→ADD→VALIDATE shown previously is RESULT-idempotent but NOT EXECUTION-idempotent: a direct second run re-resolves
  the now-WIDENED constraint via `LIKE '%status%'`, DROPs it, re-ADDs `NOT VALID`, re-VALIDATEs — taking ACCESS
  EXCLUSIVE and transiently leaving `backtest_runs` with NO status CHECK each run — contradicting REQ-ROLL-027's
  "zero DDL re-execution via IF NOT EXISTS" / REQ-MIG-004 "second-run no-op" and the architecture §4.4 `DROP
  CONSTRAINT IF EXISTS` form at line 932):** (0) **PRE-CHECK** — read
  `pg_get_constraintdef(oid)` for the resolved status CHECK and, **IF the existing definition ALREADY permits the
  target 7-value superset IN-list, SKIP the entire DROP+ADD+VALIDATE (a true no-op — issue ZERO DDL, take NO ACCESS
  EXCLUSIVE lock)**; only proceed to the swap when the current CHECK is the legacy 5-value list. (1) Resolve the REAL constraint name from
  `pg_constraint` (do NOT assume `backtest_runs_status_check` — read it: `SELECT conname FROM pg_constraint WHERE
  conrelid='backtest_runs'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%status%'`). (2)
  `ALTER TABLE backtest_runs DROP CONSTRAINT IF EXISTS <resolved_name>` (the `IF EXISTS` form, aligned with
  architecture §4.4 line 932). (3) `ALTER TABLE backtest_runs ADD CONSTRAINT
  backtest_runs_status_check CHECK(status IN ('pending','running','completed','failed','cancelled','queued',
  'interrupted_by_restart'))` — **added `NOT VALID` then `VALIDATE CONSTRAINT` OUT-OF-BAND** so the boot DDL stays
  sub-second (the bare `ADD CONSTRAINT` re-validates the whole table under ACCESS EXCLUSIVE; `NOT VALID` skips the
  scan, `VALIDATE` later takes only `SHARE UPDATE EXCLUSIVE`). `backtest_runs` is small (one row per run) so even an
  in-line validation scan is bounded, but the `NOT VALID`+`VALIDATE` split is the pinned default. This swap is an
  **EXPAND-ONLY widening (the new list is a strict superset)** and is **whitelisted in the NFR-015 destructive-DDL
  schema-diff guard** as expand-only (a naive `DROP CONSTRAINT` would otherwise trip it). `failed_with_timeout` is
  NOT added to the stored CHECK list — it is an INTERNAL-only label mapped to stored `failed` (see FR-052 / R2-F2).
  A test (under U.1/T.10) asserts the new states `queued`/`interrupted_by_restart` are INSERTABLE post-v58, the swap
  is callable + atomic-rollback-safe (mid-DDL failure leaves `schema_version` at 57 and the OLD constraint intact),
  **the swap is NEVER momentarily absent during a fresh apply**, and **the second DIRECT invocation issues ZERO DDL
  (no DROP/ADD/VALIDATE) and acquires NO ACCESS EXCLUSIVE lock** — i.e. the pre-check makes it execution-idempotent,
  not merely result-idempotent (R5-F4-batch2 ≡ R5-F1-batch3). *(REQ-MIG-001/004/020, REQ-ROLL-027, REQ-OBS-016, R2-F1-batch2/batch3, R5-F4-batch2)*

### N.3 Parquet/Feather columnar layout (Phase 5)

- **Hive partition path** built from `SAN(symbol)` + `interval` + UTC `year/month`; `SAN()` percent/hex-encodes
  every non-`[A-Za-z0-9._-]` char; resolved absolute path asserted within `BT_COLUMNAR_DIR`. Sealed months only.
- **Tiers:** Arrow hot frame (`{(symbol,interval,date-range): pa.Table}`, ≤150MB in-process LRU, sealed-only,
  forming day NEVER admitted) → mmap'd Feather V2 (on-disk == in-memory Arrow IPC, format-version + sha verified on
  map) → Parquet (immutable sealed months, no TTL, invalidate only on sha-mismatch rebuild) → Postgres SOR (all
  rows + forming edge, point-in-time snapshot).
- **Generation token** embedded in every part-file `_manifest.json` + every in-process artifact; validated on read,
  invalidate+rebuild on mismatch (PITR self-invalidation). *(REQ-STORE-021/024/028/034/038, REQ-CACHE-044)*

### N.4 v58 migration strategy (idempotent, callable, deferred-backfill-safe)

- **Callable migration** (not a `;`-split string) for the multi-statement DDL; claims the next free int after v57
  (collision-coordinated); **additive DDL ONLY** — columns + control/provenance tables + the **expand-only
  `backtest_runs.status` CHECK widen (N.2 / R2-F1: PRE-CHECK `pg_get_constraintdef` — SKIP if already the 7-value
  superset — else DROP old constraint by resolved `pg_constraint` name with `IF EXISTS` → ADD new
  superset CHECK `NOT VALID`, with `VALIDATE` out-of-band; the pre-check makes the second run issue ZERO DDL,
  R5-F4-batch2)**; **zero data-dependent seal backfill inline**. **Index
  plumbing is NOT in the in-transaction callable migration (CORRECTED — R2-F3-batch3): the migration runner wraps
  every migration in `conn.transaction()` (`async_persistence.py:1629-1636`) and `CREATE INDEX CONCURRENTLY` is
  ILLEGAL inside a transaction, so putting the index in `_MIGRATIONS` would crash the migration and strand
  `schema_version` at 57. The partial index is therefore built OUT-OF-BAND (see lock-discipline bullet) and is
  explicitly excluded from the v58 in-transaction DDL inventory.** `schema_version` reaches 58 atomically + sub-second
  so the global advisory lock is never held for a backfill. An injected mid-DDL failure leaves `schema_version` at
  57, the OLD status CHECK intact, nothing partial.
- **Lock discipline:** each `ADD COLUMN` takes a momentary catalog `ACCESS EXCLUSIVE` (no table rewrite) — bounded
  `lock_timeout` + in-boot retry + a submission-quiesce DRAIN window so it never races the live scanner's
  continuous `_update_coverage` upserts. **Advisory-lock connection topology (REQ-MIG-028 — R5-F4-batch3: a
  session-level `pg_advisory_lock` MUST run on a dedicated DIRECT, non-pooled, session-pinned connection, because
  under pgBouncer TRANSACTION-mode the lock can be acquired on one backend while later work runs on another, silently
  breaking the exactly-one-v58-apply + exactly-one-backfill-runner + exactly-one-lifecycle-refresher guarantees the
  whole migration rests on; the prior I.4/N.4 text covered disjoint lock KEYS but never this session-pinned-connection
  hazard):** the **v58 migration lock, the `SealBackfillRunner` election lock, and the `SymbolLifecycleRefresher`
  election lock are each acquired on a dedicated DIRECT (non-pooled, session-pinned) asyncpg connection**, with a
  **pooling-mode test** asserting the lock is held on a session-pinned backend (not released/re-bound across pooled
  transactions). **Scoping:** the PRIMARY target is a standalone primary / direct asyncpg, so this is **defensive /
  forward-compatible HERE; it becomes LOAD-BEARING under the [FLEET] secondary-fleet variant** (transaction-mode
  pooler) — the decision is recorded so it is visible in the contract whichever topology ships. **Out-of-band index builds (CIC OWNER PINNED — R2-F3-batch3):** the
  out-of-band indexes are owned by a **named post-migration async boot step** (`MaintenanceAdmin.ensure_indexes()`
  invoked from the lifespan boot hook AFTER `schema_version=58` is confirmed — NOT `_MIGRATIONS`, which is
  transaction-wrapped). Each is built `CREATE INDEX CONCURRENTLY IF NOT EXISTS`; on retry the owner first DETECTS +
  `DROP`s any leftover `INVALID` index from a prior failed CIC (`SELECT … FROM pg_index WHERE NOT indisvalid`),
  uses a bounded `lock_timeout`, and is idempotent re-run-safe. Its build window is measured by `cic_build_ms{index}`
  + a stall gauge. **Post-backfill planner stats (REQ-MIG-034 — R5-F5-batch3: after the bulk seal-backfill UPDATE +
  index build, stale planner stats from the mass column-add + the ~100%→~0% `NOT sealed` distribution flip can
  degrade the seal-check/unsealed-days query to a Seq Scan, silently regressing the P1 "sealed rerun is fast"
  Prime-Directive benefit; absent from the prior spec):** after the seal-backfill UPDATE and CIC build, the owner runs
  **`ANALYZE` (and a bounded `VACUUM`) on `kline_cache_coverage`** — a **double-ANALYZE** (once post-CIC-build, AGAIN
  after the backfill marker flips to `complete`, so the planner sees the final mostly-sealed distribution). A P1
  AC/T.10 sub-test asserts an **`EXPLAIN`-uses-index** plan for the gap/unsealed query against the **post-backfill
  mostly-sealed row distribution** (NOT a freshly-built empty table), so a post-backfill stats regression to Seq Scan
  fails CI (REQ-MIG-034).
  - **`idx_coverage_unsealed` (DDL PINNED — R2-F5-batch2 + reconciled with the reverify predicate R2-F3-batch2):**
    `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_coverage_unsealed ON kline_cache_coverage (symbol, interval, date)
    WHERE NOT sealed OR reverify_pending`. The column list `(symbol, interval, date)` matches the gap-detection query
    (`symbol = $1 AND interval = $2 AND date BETWEEN $3 AND $4 AND (NOT sealed OR reverify_pending)`); the partial
    predicate is **`WHERE NOT sealed OR reverify_pending`** (NOT bare `WHERE NOT sealed`) so a `day_class=3 /
    reverify_pending=true` row — which is `sealed=true` — is STILL index-covered and STILL selected by the
    fetch-eligible set (resolves R2-F3-batch2: the one-shot reverify fetch now has a trigger path + supporting index).
    **Planner-choice + size-independence test (REQ-CACHE-010 — R5-F7-batch2: REQ-CACHE-010 requires seal-state
    resolution "index-backed so latency is O(range days), independent of manifest size," but N.4's "not a seq scan"
    was prose only — no §U AC / §T test asserted the planner actually picks an Index/Bitmap scan or that gap-query
    latency stays flat as manifest rows scale; a predicate-implication break, a stats/cardinality shift, or a
    non-sargable rewrite would silently regress to a Seq Scan undetected because a small-manifest microbench runs
    fast either way):** a P1 §T/§U test runs `EXPLAIN (ANALYZE)` on the gap-detection query against a
    REALISTICALLY-sized manifest (≥100k rows across many symbols/intervals) and asserts the plan node is an
    **Index Scan / Bitmap Index Scan on `idx_coverage_unsealed` (NOT a Seq Scan)**, PLUS a **scaling assertion** that
    gap-query latency for a FIXED range stays flat as total manifest rows grow 10× (O(range days), independent of
    manifest size). Wired into the P1 AC set so a predicate-implication break (query WHERE no longer implying the
    partial-index predicate) fails CI. *(REQ-CACHE-010; P1; R5-F7-batch2)*
  - **`idx_backtest_runs_status` widen (R2-F4-batch2):** the existing partial index `idx_backtest_runs_status ON
    backtest_runs(status) WHERE status IN ('pending','running')` (`async_persistence.py:676-677`) is recreated with
    `WHERE status IN ('queued','pending','running')` so the FR-039 `queued→running`/`queued→cancelled` admission-cycle
    arbitration + queued-row cleanup queries are index-backed (not a seq scan). Predicate change only (index-only, no
    table rewrite); built via the same out-of-band CIC owner (drop-old + CIC-new, or a dedicated partial index on
    `queued`). Added to the migration-completeness meta-test. *(REQ-MIG-020/033, R2-F3-batch2/batch3, R2-F4-batch2, R2-F5-batch2)*
- **Partition hazard — pre-flight validation + default-reconciliation, with tests (REQ-MIG-035 — R5-F7-batch3
  replaces the prior "handled, not assumed" prose, which named NO mechanism and NO test, an untestable assertion).**
  The existing `kline_cache` partition set spans only ±6mo from migration time, so a >6mo-old sealed range may live
  in `kline_cache_default` (`store_klines` auto-creates on write). v58 (or its boot sibling) therefore **pre-flight
  validates the partition tree** — parent table exists; the migration-38 monthly RANGE scheme is intact; no
  gaps/overlaps; the default partition is present — and **FAILS FAST on a broken layout** (so the seal-backfill never
  seals coverage rows whose candles are stranded in an unpruned default partition, which would silently break the
  cross-tier read path). It ALSO **detects + reconciles** rows a legacy/rolling-deploy instance wrote into
  `kline_cache_default` back to their proper monthly partition (restoring the default-empty invariant). Tests:
  a **partition-gap/broken-layout REFUSAL** test and a **default→proper-partition reconciliation** test, both gated by
  a P1 AC. *(REQ-MIG-035; P1; R5-F7-batch3)*
- **Backfill (separate, deferred — `SealBackfillRunner`):** bounded/set-based chunked-commit UPDATE within a
  statement budget; idempotent + resumable from its checkpoint marker; mutates ONLY coverage/manifest + lifecycle
  rows, NEVER a `kline_cache` candle row (before/after content-hash diff proves every candle byte-identical,
  coverage row-count non-decreasing, no `candle_count` reduced/high-water-mark regressed); legacy
  coarse-interval rows sealed as immutable facts by their existing PK (no orphan, no refetch). **`content_sha256`
  on backfilled seals (R2-F7 — closes the "entire deferred-backfilled historical corpus is sealed-immutable yet has
  NO integrity hash" gap; a NULL sha means the tri-source gate (AC-011) and any ongoing drift check are blind to that
  day):** because `SealBackfillRunner` ALREADY READS the Postgres SOR candle rows while sealing, it **computes
  `content_sha256` from those rows in the same pass** (the §FR-025 canonical hash — sorted by `open_time`, int64-ms
  epoch, IEEE-754 LE float64 OHLCV, fixed column order) and writes it on the seal, so a backfilled day is **hashed +
  TTL-exempt-but-verifiable**, not NULL-sha. `fetched_at` stays NULL on a backfilled seal (it was not freshly Bybit-
  fetched; TTL-exempt). **Residual-risk backstop:** for any day that STILL carries NULL `content_sha256` (e.g. a
  pre-R2-F7 backfilled row, or a row the runner could not hash), the NFR-016 mandatory sampled row-count/`content_sha256`
  backstop ALSO samples NULL-sha sealed days so cross-tier byte drift / in-place mutation on a sealed-but-unhashed day
  is still detected over time. A test asserts (a) a `SealBackfillRunner`-sealed day carries a NON-NULL
  `content_sha256` equal to the FR-025 canonical hash of its SOR rows, and (b) the sampled backstop covers residual
  NULL-sha sealed days. *(REQ-MIG-014/015/016/017/018/019, REQ-STORE-003, R2-F7-batch1)*
- **Rollback / rolling-deploy:** v58 is **expand-only** (CI schema-diff guard asserts zero destructive DDL); pre-v58
  code runs correctly against v58 (additive columns ignored); legacy column-omitting upserts MUST NOT
  null/clobber additive v58 columns (`INSERT … ON CONFLICT` column preservation); legacy count-based instances that
  refetch sealed-short days during the overlap window leave the manifest intact (store_klines `ON CONFLICT DO
  NOTHING`) and new-code re-seals idempotently with zero net change. Backtest endpoints MUST NOT read v58 columns
  until `schema_version=58` is confirmed; if v58 rolled back to 57 the service still boots + serves the legacy path
  (no crash-loop on missing columns). No `SELECT *` against the backtest/coverage/manifest tables (every read
  enumerates columns). *(REQ-ROLL-005/006/008/009/010/011, REQ-FE-013)*
- **Pre-deploy gates:** a verified Postgres restore-point immediately before v58; a restored-prod-clone rehearsal
  (exact PG major + partitioning) asserting within-budget apply + second-run no-op; a CD promotion guard blocking
  any binary whose max-supported `schema_version` < the live DB's. *(REQ-ROLL-007/028/029, REQ-MIG-041)*

### N.5 Write-side growth, bloat & retention (REQ-STORE-042/043 — R5-F8-batch2)

> REQ-STORE-042 ("Postgres write-side growth/bloat MUST be bounded": manifest row-count bound + retention/archival for
> permanently-delisted symbols + autovacuum/HOT/fillfactor-friendly high-churn coverage/seal GREATEST-upserts) and
> REQ-STORE-043 (equity_curve JSONB documented size budget + write-time guard) previously had NO home in §N — yet v58
> MATERIALLY WORSENS the exact bloat vector they target: it widens `kline_cache_coverage` (a table the live scanner
> continuously GREATEST-upserts) with ~15 new columns including a JSONB (`gap_ranges`), increasing row width,
> dead-tuple churn, and TOAST pressure. This subsection gives both should-requirements a home.

- **N.5a — Manifest row-count bound + delisted retention/archival (REQ-STORE-042).** `kline_cache_coverage` (keyed
  `symbol,interval,date`) carries a **documented row-count bound** and a **retention/archival path for
  permanently-delisted symbols** (their coverage/seal rows are archivable + re-derivable from the SOR, so they need
  not accumulate forever on the hot manifest). The archival path NEVER deletes a `kline_cache` candle row (SOR is
  authoritative); it prunes/relocates only the derivable manifest rows.
- **N.5b — High-churn upsert HOT/fillfactor/autovacuum tuning (REQ-STORE-042).** The continuously-upserted
  `kline_cache_coverage` GREATEST-upsert path and the `backtest_trades`/`equity_curve` delete-before-insert rerun path
  are specified **HOT-update-friendly** — a tuned `fillfactor` (leaving page free space so a GREATEST-upsert can do a
  HOT update without a new index tuple) + an autovacuum policy sized for the churn rate (or an explicit assertion of
  HOT-friendliness for the upserted columns, none of which are the indexed `(symbol,interval,date)` key). The widened
  row (incl. the `gap_ranges` JSONB, which TOASTs only when large) MUST NOT push the common upsert off the HOT path.
- **N.5c — `equity_curve` JSONB size budget + write-time guard (REQ-STORE-043).** The stored FULL `equity_curve`
  JSONB carries a **documented byte budget** and a **write-time guard for pathological high-turnover runs**, bounding
  stored-row bytes + serialize cost. **Hash/snapshot/metrics basis RECONCILED — store-capping FORBIDDEN on
  golden/parity fixtures + byte budget PINNED (R6-F3-batch5 — the prior "cap on stored points with a
  downsample-before-store policy" created a THIRD equity-curve representation (engine-emitted full curve →
  store-capped JSONB → GET-time LTTB view) that CONTRADICTS the long-standing hash-basis contract: L.2/FR-052/AC-043
  state the manifest hashes the FULL pre-downsample JSONB and discovery §5 says hash the FULL stored JSONB; but after
  store-capping the stored ordered curve is NOT full, so either the hash is over the engine curve (not recomputable
  from stored rows — breaking the AC-011 tri-source rebuild + FR-038 read-side recompute) or over the store-capped
  curve (then "full pre-downsample JSONB" is a misnomer AND the T.1 golden snapshot + the path-dependent
  Sharpe/Sortino/max-DD computed from `equity_curve` order must reconcile to the SAME capped curve, which the spec
  never stated); and the "byte budget"/"cap on stored points" carried NO number, making the N.5d guard test
  non-falsifiable):** ONE canonical curve is pinned as SIMULTANEOUSLY the FR-052 hash basis, the T.1 golden-snapshot
  basis, and the `compute_all_metrics` input. **Store-capping is FORBIDDEN on golden/parity fixtures** (the canonical
  90d×50sym / 30d×20sym fixtures, every T.2 close-rule fixture, and any run feeding AC-011/AC-041/T.1) — for those the
  stored JSONB IS the full engine curve, so the hash basis, the golden snapshot, and the metrics input are all the
  same full ordered curve, byte-for-byte. The write-time guard applies ONLY to non-parity production runs whose curve
  exceeds the budget, and when it fires it records `equity_curve_store_capped: true` in the manifest so a capped run is
  never mistaken for a parity basis. **Byte budget PINNED: stored `equity_curve` JSONB ≤ 8 MB and ≤ 50,000 stored
  points** (range-validated, recorded in the manifest); a run exceeding it on the non-parity path downsamples
  BEFORE store with a policy that STILL preserves BOTH the max-DD trough AND the max-equity peak (R6-F4-batch4). **The
  manifest STILL hashes the full ordered curve** on the parity path (the §L.2/FR-052 basis is
  the pre-API-downsample curve); GET still returns the bounded LTTB view. *(REQ-STORE-043; R5-F8-batch2, R6-F3-batch5, R6-F4-batch4)*
- **N.5d — Sustained-churn test.** A test drives sustained GREATEST-upsert churn on `kline_cache_coverage` (and
  rerun delete-before-insert on `backtest_trades`/`equity_curve`) and asserts **no monotonic latency degradation**
  (HOT-update ratio stays healthy; dead-tuple footprint bounded by autovacuum) and that the `equity_curve` write-time
  guard rejects/bounds a pathological-turnover curve **against the PINNED ≤8 MB / ≤50,000-point budget (N.5c,
  R6-F3-batch5 — a falsifiable threshold: a curve at the cap stores, one point/byte over triggers
  downsample-before-store on the non-parity path; golden/parity fixtures are never store-capped)**. *(REQ-STORE-042/043; cross; R5-F8-batch2, R6-F3-batch5)*

---

## O. Integration — Bybit REST (the only external integration; fail-soft)

Bybit v5 public is the ONLY external integration, hit ONLY for cold gap-fill. Sealed days never call it (rerun
`call_count == 0` for fully-sealed ranges).

- **O.1 — Kline fetch (`KlineCacheService._fetch_klines_from_bybit`).** `_BYBIT_KLINE_URL:18`, `category=linear`.
  **Page size 200 → 1000** (`_PAGE_SIZE:19` raised to Bybit's documented max → ~5× fewer paginated requests).
  **`_MAX_PAGES` is interval-aware and pinned `≥ ceil(candles_per_month(interval) / 1000)`** so one outer chunk's
  worth of candles always fits within the page cap WITHOUT truncating the tail — the math does NOT hold uniformly
  with a fixed small cap: one month of 5m ≈ 8640 candles ≈ 9 pages, but 1m ≈ 44640 candles ≈ 45 pages, so a fixed
  `_MAX_PAGES=5` would truncate a month of 1m. EITHER `_MAX_PAGES` is set per-interval to that ceiling, OR the OUTER
  chunk granularity is itself interval-aware (sub-month — e.g. ~weekly — for 1m) so each inner fetch stays within
  `_MAX_PAGES` while fully covering its chunk. Cold gap-fill for a long unsealed history is driven by an **OUTER
  chunked loop (per-symbol-month, owned by `SealBackfillRunner`/`ensure_coverage`)** so total reach is
  unbounded-by-design while each call stays page-bounded — the cap can never truncate the tail of a long gap.
  Interval mapping `5m/15m/1h/4h/1m → 5/15/60/240/1`. A test seals a >5000-candle cold range and asserts full
  coverage + 0 refetch on rerun, **including a 1m cold range exceeding one month** (the fine-interval case that a
  fixed cap would silently truncate). *(REQ-CACHE, REQ-MIG-035, REQ-STORE-008)*
- **O.2 — Cold-fetch concurrency budgeted + named.** The cold kline-fetch path (`ensure_coverage`/`warmup` + the
  outer chunk loop) uses an explicit **semaphore-bounded concurrent fan-out across symbols** with a committed
  throughput budget (`wall ≈ ceil(N/cap) × per-fetch`), governed by the shared Bybit circuit breaker so a 429 storm
  backs off coordinately. `ensure_coverage` is THE component that cold-fetches a never-seen range (the
  "reject-then-warm" target) — `SealBackfillRunner` only SEALS rows already in the Postgres SOR. **Warmup carries a
  per-request scope ceiling (symbol-count × span × interval-multiplier) + per-client rate limit + `AdmissionAccountant`
  admission (J.3 / R2-F3); an over-scope request is rejected with the structured 4xx BEFORE any Bybit call.** A test
  asserts fan-out ≤ cap, RSS-flat, breaker-gated, AND that an over-scope warmup is rejected pre-fetch
  (`bybit_kline_calls == 0`). *(REQ-PERF-018/037, REQ-CACHE, NFR-021)*
- **O.3 — Retry / fail-soft / per-symbol isolation.** `_MAX_RETRIES=3` preserved; one symbol's network/parse
  failure does NOT abort the batch (counted `failed`, gap retained, `still_missing`). **Failed/429/timeout responses
  NEVER seal a day** (a day seals only on durable valid rows past the frontier), so the breaker can never cause a
  false negative-cache. *(REQ-CACHE-007/028)*
- **O.4 — Shared circuit breaker (reuse, not reimplement) + priority layer + per-caller-class OPEN-state partition.**
  The Bybit breaker IS the existing `backend/mcp/core/breaker.py` instance (`closed`/`open`/`half-open` +
  consecutive-failure count + next-probe); kline + instrument + drill fetch paths wrap that ONE shared breaker for
  coordinated backoff. A priority/quota layer sits in front so backtest cold-fill is rate-prioritized BELOW live
  scanner/auto-trade/reconciler Bybit access (a backtest 429 storm must not cut off live access). **Isolation
  mechanism (R2-F2 — resolves the "shared breaker yet a backtest storm must not cut off live" tension concretely):**
  OPEN-state is **partitioned by caller class**. Every Bybit call is tagged `caller_class ∈ {live, backtest}`. The
  breaker keeps **per-caller-class failure counters and per-class OPEN/half-open state** (a backtest-only sub-breaker
  layered on the shared object — same instance/id, class-partitioned state): a run of consecutive **backtest-origin**
  failures backs off / opens the **backtest** sub-state ONLY and does NOT open the live sub-state; the **live**
  sub-state opens only on **live-origin** consecutive failures. The priority/quota layer is the front gate; the
  class-partitioned OPEN-state is the guarantee that backtest-induced failures can never gate live calls. (If a
  single global OPEN must ever be asserted — e.g. a hard exchange outage observed by BOTH classes — it is reached
  only by live-origin failures, never by backtest-origin alone.) A test asserts (a) the kline path + the MCP path
  share one breaker OBJECT (same id), AND (b) **GIVEN a backtest-triggered breaker-OPEN (backtest sub-state open),
  WHEN a live Bybit call is made, THEN it still proceeds** — the live path is not gated by a backtest-induced open.
  State (both class sub-states) is exposed on the §K.2 status route. *(REQ-OBS-029, REQ-CACHE-007/028/040, NFR-021,
  R2-F2-batch1)*
- **O.5 — Instrument info (`InstrumentInfoCache.refresh:516`).** `_BYBIT_INSTRUMENTS_URL:480`, `limit=1000`
  already — unchanged. `_DEFAULT_INSTRUMENT_INFO:487` NO-OP defaults (`tick_size=0`, `max_leverage=0`) preserved (an
  unknown symbol behaves as if no instrument info supplied — parity-critical for the golden NO-OP guarantee). *(discovery §8)*
- **O.6 — Drilldown fetch fallback.** A 1m per-bar fetch failure falls back to 5m for that bar only, never aborts
  the run, never persists partial 1m data, stays non-optimistic; a no-1m-candles drill falls back to 5m and never
  fabricates a fill. *(REQ-DRILL-013/023)*
- **O.7 — Optional bulk archive (untrusted ingress, default OFF).** A `public.bybit.com` daily-archive accelerator
  for large cold ranges is OPTIONAL behind a flag; default stays REST. If enabled it is treated as untrusted
  (decompressed-size + compression-ratio ceiling, schema/symbol/interval/time-range validation, published-checksum
  verification, quarantine + validate-then-atomic-rename, raw bytes hashed pre-parse); on any guard failure it
  falls back to REST. If the guards are not built, the bulk path is OUT OF SCOPE. *(REQ-SEC-003, §8.4)*

---

## P. Security

- **P.1 — New-dependency CVE surface.** numba/llvmlite/pyarrow/duckdb widen the transitive CVE surface (already
  pip-audit-tracked). Mitigations: hash-pinned lockfile, pip-audit over the accel extra in CI, floors+ceilings
  bound the resolvable set, the extra is optional (base deploy carries none). pyarrow deserialization CVEs are
  mitigated by reading **only files this process wrote** (no untrusted Arrow/Parquet ingress except the
  explicitly-guarded bulk-archive path) + the format/schema-version stamp + sha verification. **`content_sha256`
  is integrity-of-content, NOT a parser-CVE mitigation** (verifying it requires first parsing with pyarrow — the
  control against a hostile file is process-ownership + dir-mode, §P.2). *(REQ-DEP-002/028, REQ-SEC; §8.1)*
- **P.2 — Parquet file-path safety (Windows-primary + POSIX lane).** Hive path from `symbol`+`interval`+UTC
  `year/month` → path-traversal risk. Mitigation: reversible `SAN(SYM)` encoding + asserted within-
  `BT_COLUMNAR_DIR` absolute path; `interval` validated against the closed enum. **Windows (primary):** reject
  reparse points/junctions on the path + every parent up to `BT_COLUMNAR_DIR`; validate dir ownership + ACL via
  win32 security APIs (owner SID == process SID, no write ACE for non-owner/`Everyone`/`Authenticated Users`);
  canonicalize then re-stat BY HANDLE (close TOCTOU) — a junction-swap test is rejected. **POSIX (CI/Linux lane):**
  `O_NOFOLLOW` + `realpath`-then-`fstat` + non-world-writable mode + ownership. **Numba on-disk compile-cache dir
  (R2-F6 — extends the same guard to the JIT cache, an integrity-critical path introduced at P4; numba writes
  compiled machine code there and loads it back at runtime, so a writable/poisoned compile cache is a local
  code-execution vector, and the §P.2/NFR-019 controls were previously scoped only to the Parquet `BT_COLUMNAR_DIR`
  at P5):** the `NUMBA_CACHE_DIR` is subjected to the **SAME boot-time ownership/ACL/reparse-reject validation** as
  `BT_COLUMNAR_DIR` (process-owned; no write ACE for non-owner / `Everyone` / `Authenticated Users`; no reparse
  point/junction on the dir or any parent; POSIX non-world-writable + ownership), **OR** it is required to live
  INSIDE the already-guarded `BT_COLUMNAR_DIR`. If the cache dir FAILS validation, the **JIT on-disk cache is
  DISABLED and the engine falls back** (re-compile in-process, or pure-Python) rather than loading from an
  untrusted cache. This validation is added to the **path-safety test matrix at P4** (alongside the P5 Parquet-dir
  matrix). *(REQ-SEC-001, REQ-STORE-021/034, R2-F6-batch1)*
- **P.3 — DuckDB read-engine lockdown.** Keep `enable_external_access=true` (Parquet reads need it) but constrain
  `allowed_directories=[BT_COLUMNAR_DIR]`; `lock_configuration=true` (a successful injection cannot re-widen
  access); `autoinstall/autoload_known_extensions=false`; `access_mode='READ_ONLY'`. The Parquet PATH is
  string-built (defense = SAN + within-allowed_directories); predicates use `$n` binding; `interval` validated
  against the enum. An injection test asserts a crafted symbol cannot escape `allowed_directories` AND cannot mutate
  config. **Security version floor + enforcement probe (R2-F5 — `allowed_directories`/`lock_configuration` are the
  lockdown primitives and require DuckDB ≥1.1 per architecture §8.3; a resolution below 1.1, or a build lacking the
  settings, would silently no-op the lockdown while a permissive/mocked injection test still passes):** `duckdb>=1.1`
  is pinned as a **SECURITY floor** (not merely a perf floor) in the `accel` extra (FR-048). A **boot/CI probe**
  asserts the loaded `duckdb` (a) exposes AND (b) ENFORCES `allowed_directories` + `lock_configuration` — concretely,
  after applying the lockdown, a runtime `SET enable_external_access=true` (or any config mutation) is REJECTED, and a
  read of a path OUTSIDE `allowed_directories` is rejected. If the primitives are absent or unenforced, the columnar
  path **FAILS CLOSED / refuses to engage** (degrades to the Postgres path, `columnar_degraded` warning) rather than
  running an unprotected DuckDB. *(REQ-SEC-002, NFR-020, R2-F5-batch1)*
- **P.4 — Spawn-worker secret minimization.** Worker env is an ALLOWLIST, deny-by-default — only non-secret kernel
  vars; NEVER `ACCOUNTS_ENCRYPTION_KEY`, `DATABASE_URL`, `COINGECKO_API_KEY`, or LLM keys; core dumps disabled; no
  forked asyncpg pool handed to a child. **Pinned allowlist (the CLOSED set — R2-F4):** the worker `os.environ` is
  exactly `{thread-cap vars (NUMBA_NUM_THREADS, OMP_NUM_THREADS, OPENBLAS_NUM_THREADS, MKL_NUM_THREADS,
  POLARS_MAX_THREADS, DUCKDB threads), BT_COLUMNAR_DIR, the numba cache dir var (NUMBA_CACHE_DIR), NUMBA_THREADING_LAYER}`
  plus the OS-mandatory process bootstrap vars **enumerated as an EXPLICIT closed literal per-OS set, NOT an
  open-ended "TEMP-class" pattern (R5-F5-batch1 — a subset assertion is only sound if the RHS is a CLOSED enumerated
  set; a loose "TEMP-class" CLASS can admit credential-bearing vars that happen to match the bootstrap pattern, e.g.
  libpq reads `PGPASSWORD`/`PGSSLKEY`/`PGSERVICEFILE`/`PGPASSFILE` from the environment, so a forked/spawned worker
  matching a loose pattern could leak Postgres creds to a CPU worker that needs no DB access — silently
  reintroducing the R2-F4 denylist weakness via an open RHS):** **Windows** bootstrap set =
  `{SystemRoot, Path, PATHEXT, TEMP, TMP, NUMBER_OF_PROCESSORS, PROCESSOR_ARCHITECTURE, COMSPEC, WINDIR,
  SystemDrive, ComSpec, USERPROFILE, LOCALAPPDATA}`; **POSIX** bootstrap set = `{PATH, TMPDIR, HOME, LANG, LC_ALL,
  LC_CTYPE, TZ}` — both CLOSED literal sets — and NOTHING else. **Verification is a
  SUBSET assertion, not a 4-name denylist (R2-F4 — a denylist passes even when a future secret env var, e.g. a new
  LLM key name or a credential-bearing `BT_*` var, leaks):** the test asserts `set(worker.os.environ) ⊆ allowlist`
  (exact membership against the closed set above), so ANY non-allowlisted variable — including a future-added secret —
  FAILS CI. **A dedicated NEGATIVE test (R5-F5-batch1) asserts `PGPASSWORD`, `PGSSLKEY`, `PGSERVICEFILE`, `PGPASSFILE`,
  any other `PG*`, `DATABASE_URL`, `ACCOUNTS_ENCRYPTION_KEY`, and any secret-bearing `BT_*` are NOT in the worker env
  EVEN WHEN the parent process has them all set** (the subset RHS is the closed literal set above, which contains no
  `PG*`/secret name). The backtester places no real orders; trading credentials are untouched. *(REQ-SEC-004, R2-F4-batch1, R5-F5-batch1)*
- **P.5 — Migration / wrong-DB safety.** v58 ships DDL only (no destructive backfill); the destructive-capable path
  is the deferred `SealBackfillRunner`, guarded by a required **operator-provisioned** DB-identity row checked
  before any seal write (a first-deploy wrong-`DATABASE_URL` is caught on first boot, NOT self-seeded); a READ-ONLY/
  standby connection SKIPs/DEFERs rather than crash-loops; a missing `pg_control_*` grant **FAILS CLOSED** (refuses
  destructive seal writes, surfaced as `degraded`); advisory-lock keys are disjoint (migration `8675309`,
  backfill-election, live-scanner — never collide). *(REQ-SEC-006, REQ-MIG-027/043)*
- **P.6 — Unauthenticated-surface disclosure limits.** The public `GET /backtest-runtime/status` payload is coarsened
  (capability booleans + active/degraded states only) — no exact version strings, no full git-SHA, no integer
  schema_version, no numeric resource config (those go to a loopback/CLI/authenticated surface). **The privileged
  surface is keyed to the KERNEL PEER socket address or an explicit auth token — a forwarding header
  (`X-Forwarded-For`/`Forwarded`) can NEVER obtain the precise payload (R2-F8) — and the public route is per-client
  rate-limited.** A contract test asserts the omission AND that a spoofed forwarding header gets only the coarsened
  payload. *(REQ-SEC-005, NFR-021)*
- **P.7 — Log-redaction discipline.** Parity-diff + invariant-check logs emit ratios/deltas/bucketed values by
  default (honoring the platform's `financial_detail=false` redaction); raw absolute P&L/equity only under an
  explicit debug flag that is OFF in prod. *(REQ-OBS, §9.3)*
- **P.8 — REQ-SEC traceability.** **Seven REQ-SEC controls (REQ-SEC-001..007) are wired into the Requirements
  Coverage Map with named tests so a dropped §8 control fails CI exactly like a dropped functional requirement
  (R5-F3-batch1 — the prior text collapsed the homes into "P.2–P.6, the public-payload limit, CLI-only maintenance
  ops", omitting REQ-SEC-003 entirely and under-citing the per-control ACs; the SEC row in §Y is expanded to one line
  per control):** REQ-SEC-001→P.2/NFR-019/AC-T.10-junction; REQ-SEC-002→P.3/NFR-020/AC-T.10-injection;
  **REQ-SEC-003→DEFERRED with the bulk-archive feature (see below + R5-F4-batch1)**; REQ-SEC-004→P.4/NFR-021/AC-T.10
  worker-env-subset (+ the R5-F5 negative-secret test); REQ-SEC-005→K.2/P.6/AC-T.9 spoofed-XFF + AC-048k identity;
  REQ-SEC-006→P.5/NFR-021/AC-T.10 wrong-DB + missing-grant; REQ-SEC-007→P.9/FR-051/AC-047 flag-write-lockdown.
  **REQ-SEC-003 conditionality RESOLVED (R5-F4-batch1 — the control protects ONLY the `public.bybit.com` bulk-archive
  accelerator, which is DEFAULT-OFF and "OUT OF SCOPE if the guards are not built" per X-5/O.7/G.3; a CI-gating
  archive security test for code paths that may not exist this feature is contradictory — it would either fail (no
  code to exercise) or pass vacuously (skipped, no record)):** REQ-SEC-003 (zip-bomb/decompression-ratio ceiling,
  schema/symbol/interval/time-range validation, published-checksum verify, quarantine-then-atomic-rename) is
  **DEFERRED alongside the bulk-archive feature** — marked deferred in §Y like the other G.3 items, and **REMOVED from
  the T.10 CI gate until the bulk-archive feature lands**. IF the archive feature is later built behind its flag,
  REQ-SEC-003's zip-bomb/bad-schema/checksum tests ship WITH it and become a hard gate THEN (and the §Y SEC row
  flips REQ-SEC-003 from deferred to P.1/O.7/T.10-archive). So this feature ships and CI-gates **six** in-scope SEC
  controls; REQ-SEC-003 is the seventh, deferred-with-feature. *(REQ-SEC-001..002/004..007 in-scope; REQ-SEC-003
  deferred; R5-F3-batch1, R5-F4-batch1)*
- **P.9 — `bt_flag_config` write-surface lockdown (the kill-switch's integrity boundary) (R2-F1).** `bt_flag_config`
  is the DB-backed source of truth for the boolean accel flags (the 5 accel gates + the 2 per-path fallback flags,
  FR-046/R5-F4-batch4) and can carry the `BACKTEST_SAFE_MODE` master kill-switch
  row, so an actor able to WRITE a row could disarm SAFE_MODE, flip an accel flag to an operator-gated state, or
  enable the §P.7 raw-money debug-logging flag. Mitigation: writes are confined to the SAME operator boundary as
  `MaintenanceAdmin` (CLI / loopback / authenticated-admin only, never the public port); NO public HTTP route and NO
  MCP tool may write the table; `CapabilityResolver` and the §K.2 status route hold READ-ONLY handles; disarming
  SAFE_MODE uses the same operator surface as the ENV/file lever (FR-044). `bt_flag_audit` is detective-only (not a
  control surface). A test asserts (a) no public HTTP path and no MCP tool can write `bt_flag_config`, (b) a
  non-operator surface attempting to set SAFE_MODE off is rejected, (c) the resolver/status handles are read-only.
  *(REQ-SEC-007, REQ-ROLL-003, FR-044/045/051)*

---

## Q. Performance

**Canonical fixture: 90 days × 50 symbols × 5m ≈ 1.296M candles over ≈2160 scans** (REQ-PERF-001). **"Candle-eval"
is the §I normative unit = one HEAVY position-pass (`ticks × B`, `heavy_eval_count`), RECONCILED to architecture
§11.2** — NOT the `candles × B` product (that is the REQ-OBS-007 meter's internal cross-check only, the "inflated
single product" rejected for budgeting), and NOT the LIGHT-blended 1.43M total. The basket-equity recompute fires
**once per timeline tick** (the pinned cadence), giving the two-term cost model: LIGHT `O(total_candles)` ≈ 1.296M
cheap pointer/mark advances (`light_advance_count`, gated separately per NFR-004, **never folded into evals/s**) +
HEAVY `O(ticks × B)` ≈ **0.13M** position-passes (`B≈5`) = **the eval basis**. **The engine evals/s floor and the
≤60s E2E wall are different scopes; neither implies the other — the prior "`100k/s×60s=6M ≥ 1.43M`, floor strictly
stronger than the wall" check is withdrawn (R3-F2-batch2).** The pure-Python floor is **≥150k HEAVY-evals/s**
(architecture §11.1), re-pinned from a profiled engine slice.

### Q.1 Single-run latency budgets

| Lane | Budget | Gate |
|------|--------|------|
| Canonical drill-OFF (numba) | **<10s** (stretch 5s) | §12.3 Performance row; ≤50% of 120s cap |
| Canonical drill-ON (numba) | **<20s** | §12.3 Performance row |
| Canonical pure-Python lane (drill-OFF) | **≤60s** | own benchmark gate (a flag-off/degraded run stays bounded); ≤50% of 120s cap |
| Canonical pure-Python (drill-ON) | **≤90s** (R3-F2-batch1 — was un-gated; drill ~doubles latency, plausibly >60s; still `<120s`) | AC-024 drill-ON clause |
| HEAVY/HEAVIEST pure-Python | **≤90s** (documented exception, still `< 120s`; numba HEAVY `<30s`; contingent — AC-024a option (b) downgrades to numba-required if profiled >90s) | §12.3 HEAVIEST fixture both lanes (AC-024a) |
| Every **CANONICAL-class** benchmarked run | **≤ 60s (≤50% of the 120s cap)** | the cap stays a safety net, never a target |
| HEAVY/HEAVIEST classes | **≤90s latency budget** (NOT the ≤60s canonical target) | still `< 120s` — the 120s hard kill is universal |
| WIDE (200sym×365d) | **numba-lane latency only** (≈<30s numba); **pure-Python = NO latency commitment**, RSS/stream/preflight-governed, infeasible run rejected pre-slot (R2-F1-batch4) | §I.3 WIDE / NFR-004 / AC-018 reject (pred_ms) |

> **Reconciliation note (resolves the prior ≤60s-vs-≤90s self-contradiction):** the **120s `_TIMEOUT_SECONDS` hard
> kill is UNIVERSAL and never raised** (the hard constraint). The "≤60s / ≤50% of the 120s cap" is a *safety-net
> target* scoped to the **CANONICAL run-class only**. HEAVY/HEAVIEST carry a committed `≤90s` latency budget as
> a documented exception — still `< 120s`, so it never breaches the universal hard cap, and it does not collide with
> the canonical ≤60s target because the two bind different run-classes. **WIDE carries NO pure-Python latency
> commitment (R2-F1-batch4): its latency is numba-lane only; on pure-Python it is RSS/stream/preflight-governed and an
> infeasible WIDE is rejected pre-slot by the predicted-wall-time reject term, never killed at 120s.** (See §I.0a / NFR-001.)

### Q.2 Throughput floors + scaling

- **≥150k HEAVY-evals/sec single-core** post-P3 (SoA, pure-Python; `ticks×B` / `heavy_eval_count` unit, architecture
  §11.1 hard gate, re-pinned from a profiled engine slice — R3-F2/F3-batch2) — P3 must reach "minutes" before any JIT.
- **≥5M HEAVY-evals/sec single-core** post-P4 (`@njit` warmed, excl. first-call compile). The evals/s floor is a
  post-P3-calibrated regression tripwire; the wall budget is the separate hard gate (different scope — engine-only
  vs E2E — neither implies the other). The LIGHT `light_advance_count` is a separate per-advance ns micro-gate, never
  folded into evals/s.
- **Decimal-mode SoA re-resolution throughput basis (R5-F1-batch5 — for the NFR-007 near-threshold whole-run
  re-resolution + AC-026a's <120s combined budget).** The near-threshold re-resolution runs the **SAME SoA
  merge-walk algorithm in `Decimal` dtype** (`O(total_candles + ticks×B)`, M.4), NOT the legacy super-linear oracle.
  Decimal arithmetic is **~50–100×/op slower than float64**; on canonical (`heavy_eval_count ≈ 0.13M` HEAVY +
  `light_advance_count ≈ 1.296M` LIGHT) this re-resolution is the dominant term but, because the early-fire discard
  keeps the failed float attempt small, the SUM `(float attempt + Decimal-SoA re-resolution)` fits the **120s** cap
  for **CANONICAL** (the basis AC-026a gates against). **HEAVY arithmetic shown explicitly (R6-F1-batch1):** a HEAVY
  near-threshold Decimal re-resolution (e.g. 90d×100sym, B≈20 → `heavy_eval_count ≈ ticks×B ≈ 0.52M`) costs
  ≈ 0.52M/150k × (50–100×) ≈ **175–350s** — far over the 120s cap — so HEAVY does NOT fit the combined budget and is
  NOT covered by the <120s claim. For HEAVY (or any class whose Decimal re-resolution exceeds the residual budget),
  near-threshold firing mid-run triggers the **in-flight §K.3 ABORT (`near_threshold_decimal_infeasible`)** per NFR-007,
  NOT a pre-slot AC-018 reject (which cannot see a mid-run property) and NOT an admit-then-kill-at-120s.
- **≥100× engine-CPU** vs the frozen P0 baseline (NFR-002 protocol: the authoritative baseline is the **uncapped
  full-canonical engine-CPU** measurement; the reduced-sub-fixture extrapolation is a cross-check ONLY and must fit a
  super-linear cost model — R3-F3-batch2/F8-batch2) on the **numba lane** (the pure-Python lane
  carries the absolute ≤60s/≤90s budget, not the multiplier — 100× vs an uncapped multi-hour legacy baseline is not
  its binding constraint).
- **Scaling:** setup ∝ `Σ(actual per-symbol bounded spans)`; symbol-doubling ≤2× (LIGHT + HEAVY terms gated
  separately, per-advance ns ceiling); turnover 10× ≤~linear; scan-doubling context-build ≤~2×. **Cadence-contingent
  (AC-004):** if legacy proves per-symbol-candle, the HEAVY term + these scaling budgets are re-derived before P3.
- **Cadence-contingency budget table (PRE-COMPUTED — R3-F5-batch2: almost the entire P3–P6 budget set is silently
  conditional on the unverified P0 cadence finding (AC-004); previously NO fallback set was pre-computed, so an
  AC-004 finding of per-symbol-candle could invalidate the downstream contract with no ready numbers and stall P3.
  Owner: the AC-004 gate owner; these numbers are pre-authorized via the REQ-ENG-032 linear-symbol-scaling
  amendment path so a finding has a deterministic, already-reviewed resolution):** IF AC-004 proves
  **per-symbol-candle** cadence, the HEAVY term becomes `O(candles×B)` ≈ **6.48M HEAVY-evals** (≈50× the once-per-tick
  0.13M), and the budgets re-freeze to this contingency table:

  | Run-class | once-per-tick (default) pure-Python / numba | **per-symbol-candle CONTINGENCY** pure-Python / numba |
  |-----------|---------------------------------------------|------------------------------------------------------|
  | CANONICAL drill-OFF | ≤60s / <10s | **≤90s / <20s** (still `<120s`; pure-Python re-derived at ≥150k HEAVY-evals/s over 6.48M ≈ 43s engine + load/build/persist) |
  | HEAVY (100sym) | ≤90s / <30s | **numba-required (<45s numba); pure-Python parity-only** (6.48M×2 HEAVY-evals breaches ≤90s pure-Python — invoke AC-024a option (b)) |
  | HEAVIEST (150sym) | ≤90s / <30s | **numba-required (<60s numba, still `<120s`); pure-Python parity-only** |

  The numba lane stays within `<120s` in every contingency cell; the pure-Python lane is preserved for CANONICAL and
  drops to parity-only for HEAVY/HEAVIEST (the same AC-024a option (b) downgrade), so an AC-004 finding never leaves
  a run-class budget-less. The evals/s FLOORS are unchanged (they are per-eval rates); only the eval COUNT and the
  wall budgets re-derive. **No-numba reject on the parity-only cells (R4-F7-batch4):** a "numba-required; pure-Python
  parity-only / no-latency-budget" HEAVY/HEAVIEST cell on a no-numba host has NO pure-Python latency budget for AC-018
  to compare against — so AC-018's predicted-wall-time reject threshold resolves to the **universal 120s cap (with the
  under-estimate margin)** and an infeasible no-numba HEAVY/HEAVIEST run is REJECTED pre-slot (4xx, bybit/slot
  untouched), NOT admitted-then-killed at 120s. *(REQ-PERF, REQ-ENG-032, AC-004, AC-018; R3-F5-batch2, R4-F7-batch4)*
- **Open-book-depth (B) contingency budget table (PRE-COMPUTED — R5-F4-batch5: AC-004a flags the canonical HEAVY
  budgets 'B-contingent' "with a pre-computed fallback row for the measured-B case", explicitly mirroring how cadence
  is 'cadence-contingent' — but UNLIKE the cadence case (which got the full pre-computed Q.2 cadence-contingency
  table), NO B-contingency table existed anywhere, so a measured B>5 finding (plausible at B=10–15 per AC-004a) would
  leave every canonical HEAVY budget with no deterministic resolution and STALL P3 — the exact gap the cadence
  pre-computation closed). Owner: the AC-004a measurement gate; pre-authorized via the same REQ-ENG-032
  linear-symbol-scaling amendment path so a B>5 finding has a deterministic, already-reviewed resolution.** The
  canonical HEAVY `heavy_eval_count ≈ ticks × B` (canonical `ticks ≈ 25,920`); the default budgets assume `B≈5`
  (`heavy_eval_count ≈ 0.13M`). IF AC-004a measures a larger B, the canonical HEAVY budgets re-freeze to:

  | Measured B | re-derived `heavy_eval_count` (ticks×B) | pure-Python ≤Xs (at ≥150k HEAVY-evals/s) | numba budget | owner / gate |
  |-----------|------------------------------------------|------------------------------------------|--------------|--------------|
  | **B≈5 (default)** | ≈0.13M | ≤60s canonical (engine ≈0.9s + load/build/persist) | <10s | AC-004a (a) confirms — budgets stand |
  | **B≈10** | ≈0.26M | ≤60s canonical still holds (engine ≈1.7s; LIGHT + load/build/persist dominate the wall, not the 0.26M HEAVY) | <12s | AC-004a (b) re-freeze before P3 merge |
  | **B≈15** | ≈0.39M | ≤90s canonical (engine ≈2.6s; HEAVY class re-tagged to the ≤90s exception lane, still `<120s`) | <15s | AC-004a (b) re-freeze before P3 merge |

  Because the canonical wall is dominated by the ≈1.296M LIGHT advances + load/build/persist (NOT the sub-0.4M HEAVY
  evals), even B≈15 keeps canonical pure-Python within ≤90s and numba well under the 120s cap; only the
  `heavy_eval_count` denominator and the evals/s-budget arithmetic re-derive (the per-eval FLOORS are unchanged). The
  HEAVY-class (100sym) and HEAVIEST-class (150sym) budgets scale their own B identically. AC-004a/NFR-003/004 cite
  THIS table so a measured B>5 has an already-reviewed resolution and never stalls P3. *(AC-004a, NFR-003/004, REQ-ENG-032; P0/P3; R5-F4-batch5)*
- **JOINT cadence×B contingency cell (PRE-COMPUTED — R6-F1-batch5: the cadence table varies cadence at B≈5 and the
  B-table varies B at once-per-tick, but cadence (AC-004) and open-book depth B (AC-004a) are ORTHOGONAL axes BOTH
  measured at P0; the joint worst case — per-symbol-candle AND B≈15 — is `candles×B = 1.296M×15 ≈ 19.44M HEAVY-evals`
  (3× the cadence table's 6.48M worst cell, 50× the B-table's 0.39M), which at the ≥150k HEAVY-evals/s floor is
  ≈ 19.44M/150k ≈ **130s engine-only**, BREACHING the universal 120s hard cap for the CANONICAL pure-Python lane —
  and neither single-axis table has a 19.44M cell, so a simultaneous cadence+B finding had NO pre-computed resolution
  and would stall P3, defeating the tables' purpose; worse, canonical is normally a committed-budget lane (not a
  pre-slot-reject lane), so a no-numba host in the joint world would ADMIT a canonical run that then dies at 120s —
  the exact admitted-then-killed antipattern AC-018 exists to prevent):** IF AC-004 proves per-symbol-candle AND
  AC-004a measures B≥~12 (joint `candles×B` ⇒ pure-Python wall > 120s), the CANONICAL lane is re-tagged to the SAME
  disposition the cadence table already applies to HEAVY/HEAVIEST: **canonical becomes numba-required; the pure-Python
  canonical lane is parity-only with NO latency commitment, and AC-018's predicted-wall-time pre-slot reject is
  EXTENDED to the canonical lane** — a no-numba canonical run in the joint world is REJECTED pre-slot (4xx,
  bybit/slot untouched), NOT admitted-then-killed at 120s.

  | Joint axis | `heavy_eval_count` | pure-Python disposition | numba budget | owner / gate |
  |-----------|--------------------|--------------------------|--------------|--------------|
  | per-symbol-candle × B≈10 | ≈12.96M | ≈86s engine — re-tag canonical to ≤90s exception lane (still `<120s`) | <30s | AC-004+AC-004a joint re-freeze before P3 |
  | per-symbol-candle × B≈15 | ≈19.44M | **>120s — canonical numba-required; pure-Python parity-only; no-numba canonical REJECTED pre-slot (AC-018 extended to canonical)** | <40s | AC-004+AC-004a joint re-freeze; AC-018 canonical reject |

  This makes the two axes' interaction explicit (they are NOT independent for the wall budget) and removes the last
  admitted-then-killed hole. *(AC-004, AC-004a, AC-018, NFR-003/004, REQ-ENG-032; P0/P3; R6-F1-batch5)*
- **All contingency-table walls are PROVISIONAL until the profiled HEAVY rate lands (R6-F2-batch5 — every pure-Python
  wall in BOTH single-axis tables AND the joint table is computed using ≥150k HEAVY-evals/s as a GIVEN (e.g. "6.48M ÷
  150k ≈ 43s", "19.44M ÷ 150k ≈ 130s"), but NFR-003 states 150k is captured ONCE from an early profiled slice and
  FROZEN — i.e. the real rate is NOT known at spec-authoring time, and X-2 admits a blended rate as low as ~24–33k/s;
  if the profiled HEAVY rate lands below 150k every pre-computed wall is invalid, reopening the P3 stall the
  pre-computation was meant to foreclose):** every wall number in §Q.2's cadence, B, and joint contingency tables is
  flagged **PROVISIONAL — re-derive from the actual P0/early-P3 profiled HEAVY-evals/s the moment it is captured**,
  with the SAME named re-derivation owner+gate as AC-004/AC-004a (the cadence/B measurement owners). A sub-150k
  profiled rate has a deterministic resolution (re-derive every wall, re-apply the >120s ⇒ numba-required/pre-slot-
  reject disposition) rather than re-stalling P3. The per-eval FLOORS (≥150k itself) are the frozen tripwire per
  NFR-003; only the derived WALL arithmetic is provisional. *(NFR-003, X-2, AC-004/AC-004a; P0/P3; R6-F2-batch5)*

### Q.3 Sweep + persist + memory budgets

- Warm 100-combo **<60s**, 500-combo **<5min** — **on the fast (P3 pure-Python SoA / P4 numba) engine, numba +
  ProcessPool lane** (NOT gated at P2's legacy loop, AC-024b); measured **speedup ≥ 0.7×min(M,K,concurrency)** vs
  serial (speedup, not the >1 "efficiency" mis-statement — equivalently efficiency ≥0.7); serial shared setup <15% of
  sweep wall-time; IPC bytes independent of combo count. The degraded/sequential lane carries the NFR-005 relaxed
  ceiling, not these absolutes.
- **`optimize_config` E2E wall = `sweep_wall(N) + rank_overhead`**, with `rank_overhead ≤ 0.25 × sweep_wall(N)` (≤1.25×
  the sweep budget for its N) — a concrete testable threshold (was "documented wall" with no number).
- Persist **<3s** trade-heavy (O(1) insert round-trips); metrics O(curve+trades) single-pass; progress writes
  O(100), overhead <2%, first signal <1s.
- RSS ≤**1GB** total (canonical); **canonical drill-ON ceiling ≤1.5GB** (= canonical 1GB + 1m-drill-cache ≤256MB + fine-SoA
  ≤256MB, R2-F4-batch4); **HEAVY (100sym) ≤1.75GB**, **HEAVIEST (150sym) ≤2GB** (symbol-scaled per-class ceilings, NOT
  the canonical 1.5GB — R3-F1-batch4/F4-batch1/F4-batch6); **WIDE class ≤2GB** under its raised cap; klines ≤**150MB**
  (canonical; ~0.3GB HEAVY / ~0.45GB HEAVIEST resident); `timeline_bytes` its
  own added line; load-transient ≤1.5× final SoA; allocations ∝ (trades+symbols+curve_length) not candle count.
  **Aggregate admission: `Σ(reserved per-run peak RSS) + sweep-pool ≤ BT_RSS_BUDGET` (R3-F7-batch3, AC-048d).**
- **Warm cross-process rerun <5s** when `BT_COLUMNAR_DIR` is a persistent volume **AND `HAS_NUMBA` true** (mmap
  Feather survives a deploy; the engine is fast enough that columnar read dominates); on the **pure-Python lane the
  warm rerun is bounded by the ≤60s/≤90s engine budget**, not <5s (columnar read removes only the IO term); if the
  dir is ephemeral, the cold-build budget (rebuild from Postgres, 0 Bybit) governs.
- *(REQ-PERF-001..045, REQ-SWEEP-005/006/007, REQ-STORE-038)*

---

## R. Observability

- **R.1 — Per-stage timers (per-run, not per-candle).** `warmup_ms`, `load_klines_ms`, `soa_build_ms`,
  `timeline_build_ms`, `phase_a_engine_ms`, `phase_b_drill_ms`, `metrics_ms`, `persist_ms`, `jit_warm_ms`,
  `accel_wasted_ms`, `cic_build_ms{index}`. Exclusive-vs-overlap-aware: stages recorded as `(start,end)` spans
  reduced to exclusive occupancy so `Σ(exclusive) == wall_ms ± tol`, with `overlap_ms` capturing concurrency
  savings. On a 120s kill/cancel/degrade, partial timings + counters + flag/SHA fingerprint are still
  emitted + persisted (`backtest_runs.stage_timings`/`engine_fingerprint`) with the terminal reason + aborted
  stage, reconciling to elapsed-until-failure. Lets us profile after P3 to re-target P4. *(REQ-OBS-011/012/013)*
- **R.2 — Cache hit/miss + refetch counters (proves the re-download is dead).**

  | Metric | What it proves | Req |
  |--------|----------------|-----|
  | `kline_tier_hits{arrow,feather,parquet,postgres}` | Read-tier provenance; warm rerun = all-arrow | REQ-STORE-012 |
  | `bybit_kline_calls` | **0 on a fully-sealed rerun** (the headline counter) | REQ-CACHE |
  | `sealed_day_fetched_once` | A sealed day's lifetime fetch count **== 1** across N reruns | Prime Directive |
  | `unsealed_days_fetched` / `negative_cache_skips` | Gap-fill scope = unsealed-only; negative days never re-probed | REQ-STORE-009 |
  | `postgres_kline_selects` | **0** on a warm fully-sealed rerun; **== forming-day-only** on a forming-tail rerun | REQ-STORE-012 |
  | `peak_open_positions` / `turnover` | Calibrate the PreflightEstimator `B`; diagnose deep-book vs high-turnover | REQ-OBS-009 |

  A dedicated "sealed day fetched once" counter is asserted in a mock-client test (`call_count == 1` across reruns).
- **R.3 — JIT + parity diagnostics (redaction discipline).** `jit_compile_ms` per kernel; `engine_path` label
  (`sequential`/`fastpath`/`pure_python`). Parity-diff + the three-way invariant-check (`Σ trade.pnl ==
  final_equity − starting_capital == net_profit`, O(trades), always on) emit ratios/deltas/bucketed values by
  default; raw absolute money only under an off-in-prod debug flag. Two-tier shadow/dark-compare: (a) read-path
  shadow (log byte-divergence, return Postgres) and (b) size-capped engine shadow (localized divergence payload),
  both sampling-bounded, off by default. *(REQ-OBS-046, REQ-PERF-036)*
- **R.4 — Pre-flight estimator telemetry.** Logs predicted vs actual (compute term **`a·light_advance_count
  (≈total_candles) + b·heavy_eval_count (≈ticks×B)`** — the PINNED eval basis, NOT `candles×scans×B` which carries a
  spurious `scans` factor, R4-F4-batch5; cold pages
  `ceil(missing/1000)`, drill fraction, cold-columnar-build term) so calibration drift is visible; brackets actual
  within ±50% on the deterministic terms (drill term excluded), and the bracket holds as scans (not only symbols) scale. *(REQ-PERF-037/038)*
- **R.5 — Always-on event-loop-lag SLI.** `event_loop_lag_ms` periodic `loop.time()` drift sampler, bounded for the
  ENTIRE duration of a backtest AND a sweep (the canary against starving live auto-trade coroutines);
  `live_scanner_fetch_latency_p95` vs baseline during the v58 DDL window, the backfill window, AND the distinct
  `CREATE INDEX CONCURRENTLY` build window. On breach it alerts/breaks. **Concrete bounds PINNED (R2-F4-batch4 —
  these were "its documented bound"/"vs baseline" with no number, leaving AC-044 untestable and the Critical V-6
  "sweep starves live order placement" SLI ungated):** `event_loop_lag_ms` p99 ceiling = **250 ms** (absolute) during
  any backtest/sweep window — equivalently ≤ 5× the idle-baseline p99 sampled at boot, whichever is the LOOSER bound
  documented per host; and `live_scanner_fetch_latency_p95` may regress **≤ 20 % above its pre-window rolling
  baseline** during the v58 DDL, `SealBackfillRunner`, and CIC windows. A breach of either alerts and (for the
  backfill/sweep) throttles/sheds. *(REQ-PERF-029/030/031, R2-F4-batch4)*
- **R.6 — Runtime status surface + breaker state.** The §K.2 route exposes the shared breaker state + seal-backfill
  progress + flag effective-states + pitr-detector state; migration/deploy + storage-health alerting (schema
  mismatch, sha-mismatch rebuild, columnar degrade). *(REQ-OBS-029/031/032/033/034/041/042/047)*

---

## S. Edge Cases

- **S.1 — Zero-trade / degenerate inputs.** All-filtered scan, zero-symbol window, no-kline symbol, single-candle
  window → `metrics.total_trades` present-and-0 (NEVER absent — the UI fallback trap), the run renders as a real
  result, reconciliation holds trivially, short-circuit <100ms. *(REQ-TEST-012, REQ-PERF-044)*
- **S.2 — Degenerate metrics.** Zero-variance / n=1 equity → defined (not NaN/Inf/raise) Sharpe/Sortino; all-wins →
  `profit_factor` coerced to **JSON `null`** (NOT a string sentinel — L.4/R3-F9-batch2); all-losses → 0; a `pnl==0`
  trade in each of the 4 side×outcome quadrants
  exercises the near-zero floor comparator — each persists without aborting `_persist_results`. *(REQ-TEST-013, REQ-FE-008)*
- **S.3 — `close_reason 'liquidation'` is effectively unreachable in normal configs** (SL-clamp pulls SL inside the
  liq band) — a liquidation fixture must deliberately omit SL or set it outside the band. *(discovery §8)*
- **S.4 — Smart-drawdown one-shot re-arm.** `equity_drop_smart` is one-shot per scan (re-arm @ engine L1139) — a
  fixture must test the re-arm. *(discovery §8, REQ-PAR-004)*
- **S.5 — Forming-edge day.** A range ending on the current forming day MUST report `ready=true` (the forming day's
  expected incompleteness is NOT a gap), served from Postgres primary; two reruns straddling a 5m boundary both
  reflect fresh forming-day rows. *(REQ-FE-007, REQ-STORE-030)*
- **S.6 — Misaligned / sparse universe.** A 25-dense/25-short fixture (alts listing mid-window) shows setup ∝
  actual candle volume; a 200sym×365d misaligned-listing WIDE run is **NOT newly rejected ONLY WHEN it fits the
  tier-1 WIDE total-RSS budget (≤2GB, NFR-012)** — the ~168MB timeline worst case has its own budget line; above the
  WIDE budget it is reject-pre-flight (default) or `BT_WIDE_STREAM` history-streaming (open book stays resident per
  the basket-equity invariant). *(REQ-PERF-008, REQ-ENG-014, REQ-PERF-039)*
- **S.7 — Boundary-bar exit.** An exit level touched on the boundary bar between two adjacent scans fires in
  EXACTLY the same scan as legacy (half-open `[current, next)` interval). *(REQ-ENG-002)*
- **S.8 — `open_time` may be datetime OR epoch.** The searchsorted/merge-walk handles both representations
  bit-identically; empty/single-candle arrays + signal-before-first / at-or-after-last raise no `IndexError`. *(REQ-ENG-005/006)*
- **S.9 — Symbol whose klines end mid-window.** An open position is force-closed at the legacy point (backtest_end),
  reconciliation-consistent. *(REQ-PAR-045)*
- **S.10 — Partial 1m sub-bar coverage on a drilled bar.** A frozen fixture pins the chosen rule (proceed on
  available sub-bars OR fall back to 5m per the full-book rule), oracle-frozen + non-optimistic. *(REQ-DRILL-015)*
- **S.11 — Postgres write failure mid-cold-store / seal-upsert failure.** A `store_klines` write failure leaves the
  day unsealed/refetchable, no torn manifest row; a seal-upsert failure after rows are durable is non-fatal (run
  completes oracle-identical, day stays unsealed for next-run lazy-seal). *(REQ-CACHE-050)*
- **S.12 — Rolling-deploy overlap.** Legacy count-based instances refetching sealed-short days leave the manifest
  intact + new-code re-seals idempotently with zero net change. *(REQ-ROLL-011)*
- **S.13 — PITR/restore that does NOT route through the boot hook.** The mandatory sampled-integrity backstop
  independently bumps the generation; derived-coarse re-derives exactly once then stops. *(REQ-CACHE-043)*
- **S.14 — Accel module absent / ABI-broken / first-deploy wrong-DB / missing pg_control grant.** Backend still
  imports; canonical runs pure-Python; ABI-breaking version mismatch disables JIT/columnar + falls back; wrong-DB
  refuses to seal on first boot; missing grant fails closed. *(REQ-DEP-029, REQ-SEC-006)*
- **S.15 — Future-dated / inverted / wholly-future `date_range`.** The disposition is PINNED (was unspecified): the
  engine **clamps `date_range_*` to `≤` the completion frontier `floor((now − skew)/T)*T` BEFORE window-bounding**
  (per W-9), so `unsealed_days(range)` never tries to seal nonexistent future days. A **`start ≥ end`** (inverted or
  zero-width) range and a range **wholly beyond the frontier** (after clamping yields an empty window) return a
  **structured `422`** (same error contract as a preflight reject — NOT a completed zero-trade row, never the FE
  no-trades trap). **Disposition PINNED to the 422 (R4-F5-batch5 — the prior text left it an unresolved OR ("return a
  structured 422 ... OR, where product prefers, an explicit empty-oracle result with total_trades=0") and promised
  "the chosen disposition is frozen by an AC", but NO such AC existed in §U, so the behavior was unpinned and could
  diverge HTTP-vs-MCP):** the disposition is the **structured 422** (consistent with the K.3 reject contract so it can
  never hit the FE no-trades trap) — the empty-oracle alternative is DROPPED. A test submits each of {future-dated
  end, start>end, wholly-future window} and asserts the **422 on BOTH HTTP and MCP** + that no future day is probed/
  sealed; gated by AC-048j. *(REQ-STORE-030, W-9; FR-023; R4-F5-batch5)*
- **S.16 — Drill fallback precedence (the three triggers reconciled).** FR-029 (no-1m-window-for-a-symbol ⇒
  WHOLE-BOOK 5m fallback, because one symbol's missing window changes every symbol's drilled fill via the full-book
  coverage rule) and FR-030/O.6 (transient per-bar 1m FETCH failure ⇒ 5m for THAT BAR only) are TWO different
  triggers; S.10 is a THIRD (partial sub-bar coverage). The PINNED precedence decision tree when they co-occur: (1)
  if ANY open symbol has NO 1m window for the drilled span → **whole-book 5m for that span** (FR-029 wins, highest
  precedence — it is a structural book-level condition); else (2) for a bar with a transient 1m fetch failure →
  **5m for that bar only** (FR-030); else (3) partial sub-bar coverage on a bar → the S.10 frozen rule (proceed on
  available sub-bars OR per-bar 5m). An **oracle-frozen COMBINED-trigger fixture** exercises "one symbol has no 1m
  window while others do, simultaneously with a per-bar fetch failure on a different symbol," asserting whole-book
  fallback dominates and the result is non-optimistic + bit-stable. *(FR-029/030, O.6, REQ-DRILL-013/015/020)*

---

## T. Testing Requirements

> Tests are FIRST-CLASS deliverables (TDD per CLAUDE.md). The `GoldenMasterOracle` (P0) gates every later phase.
> No phase advances without its golden-master diff. Strict pytest-asyncio mode — async tests need `@pytest.mark.asyncio`.

- **T.1 — Stored-snapshot golden oracle (P0, replaces magic numbers).** Run the current engine, freeze the output
  (ordered trades + ordered equity_curve + ~45 metrics) as the snapshot oracle — NOT inline hand-verified magic
  numbers (the existing `test_backtest_golden.py` is brittle). The existing `_assert_reconciles` is replaced by the
  explicit three-way `Σ trade.pnl == net_profit == final_equity − start` cross-check. *(REQ-TEST, discovery §7)*
- **T.2 — Golden-master fixture battery per close-rule branch.** Frozen fixtures for EVERY close path: clean
  take_profit, clean stop_loss, liquidation (SL omitted/outside band), EQUITY_RISE/close_on_profit basket-flatten,
  EQUITY_DROP, EQUITY_DROP_SMART one-shot-per-scan with re-arm, BREAKEVEN_TIMEOUT TP-mutation, MAX_DURATION,
  TRAILING_PROFIT ratchet, cycle/end-of-run force-flush, target_goal_type trade_count + profit_pct early-stop —
  each reconciling. A union-coverage assertion exercises every `close_reason` enum **derived from the engine source
  (not this hand list)** — the ACTUAL engine tokens `tp`, `sl`, liquidation, equity_drop, equity_drop_smart,
  close_on_profit, equity_rise, trailing_profit, max_duration, mr_time_stop, `breakeven`, backtest_end (R6-F1-batch4 —
  NOT the long aliases `take_profit`/`stop_loss`/`breakeven_timeout`, which the engine never emits;
  `mr_target` is NOT yet an engine token, lands only with regime-multistrategy — R6-F2-batch4); **a completeness meta-test asserts `fixture_close_reasons ==
  source_close_reason_enum`** so a newly-added enum value without a fixture fails CI; a teeth meta-test disabling one
  fixture turns the union gate RED. *(REQ-TEST-007/008)*
- **T.2a — `skip_if_positions_open` cycle-gating latch fixture (R3-F2-batch5 — FR-009 is a P0-frozen, path-dependent
  cycle-level latch ("HOW changes WHAT" class) but had NO dedicated fixture: T.2's close-rule battery + T.3's
  17-filter-step fixtures do not exercise it (it is a cycle-level gate, not a per-signal filter), and the canonical
  golden master AC-001 runs the default `skip_if_positions_open=false`, so the latch was never exercised by the
  snapshot oracle either — a P0-frozen latch effectively untested).** A dedicated **multi-scan** golden fixture runs
  `skip_if_positions_open=true` across ≥3 scans where the open book is **non-empty at a scan START**, asserting
  bit-identical to the legacy oracle that: (a) new entries are **skipped** on that scan (latched at scan start), (b)
  **close rules still fire** on the carried positions during the skipped scan, (c) the **anchor is preserved**, and
  (d) `smart_drawdown` is **NOT re-armed** on the skipped scan; an empty-book scan takes the normal admit + re-arm +
  re-anchor path. Mirrors the FR-004 smart-drawdown re-arm fixture pattern; gated by a P0 AC (AC-006a). *(FR-009, REQ-PAR-012; P0; R3-F2-batch5)*
- **T.2b — `fill_to_max_trades` relaxed-second-pass fixture (R4-F1-batch4 — FR-011/REQ-PAR-025 freeze the relaxed
  second admission pass as a P0 path-dependent step, but T.2's close-rule battery + T.3's single per-filter-step
  admit/reject fixtures do not exercise it (it is a per-scan multi-signal top-up, not a single-signal filter), and the
  canonical golden master AC-001 runs the default `fill_to_max_trades=false`, so the second pass was never exercised
  by the snapshot oracle — the identical uncovered-P0-frozen-path gap class as `skip_if_positions_open`).** A dedicated
  **multi-scan, multi-signal** golden fixture runs `fill_to_max_trades=true` with a strict pass that admits FEWER than
  `max_trades` and a pool of leftover signals (some that fail `min_score`/`confidence`, some stale past
  `max_signal_age_minutes`, some whose symbol is already open), asserting **bit-identical to the legacy oracle** in
  BOTH `execution_mode{batch,immediate}` that: (a) the relaxed pass **skips the rejected-by-strict and continues**
  (does not stop at first attempt), (b) it tops the **per-scan `scan_entered` counter** (not lifetime) up to exactly
  `max_trades` and no further, (c) it bypasses ONLY `min_score`/`confidence` and STILL rejects stale + already-open +
  over-`max_trades` signals, and (d) leftover ranking is `abs(score)` descending. Gated by a P0 AC (AC-006c). *(FR-011,
  REQ-PAR-025; P0; R4-F1-batch4)*
- **T.3 — Per-filter-step + mean-reversion + interaction-matrix fixtures.** Paired admit/reject fixtures pinning
  each of the 17 filter steps (including the intentional `max_same_sector` no-op branch); a mean-reversion cohort
  fixture (mr_short/long, tight_stop, time_stop, mean_period/interval, capital/leverage) with the backtest-only
  `mr_long_ack` bypass frozen; a strategy-mode interaction matrix freezing `execution_mode{immediate,batch} ×
  direction{straight,reverse} × drilldown{on,off} × cohort{trend,mean_reversion} × funding_rate_model{none,fixed_8h}
  × fill_to_max_trades{off,on}`
  each against its own oracle. **`fill_to_max_trades` axis added (R4-F1-batch4 — the relaxed second admission pass is
  a frozen P0 path-dependent step (FR-011/REQ-PAR-025) but was absent from this matrix; it is path-dependent in BOTH
  `execution_mode` lanes (batch `_process_batch_signals` and immediate `_process_immediate_signals`), so the matrix
  spans it in each mode):** the `fill_to_max_trades=on` cells assert the relaxed-pass skip-rejected-and-continue
  ordering, the per-scan-counter cap, and the bypassed-vs-retained filter set bit-identical to the oracle in both
  modes. **Regime-ACTIVE parity axes (added — regime-OFF alone (NFR-010) under-covered the
  F1 path, REQ-PAR-030):** the matrix additionally spans `regime{off,active} × session{off,active} ×
  btc_vol{off,active}` (or a dedicated F1 fixture set) so the **regime classifier label computation**
  (`regime_volatile_atr`, `regime_trend_ema_dist_pct` over the per-scan `ScanContext`) AND the **F1 gates that
  consume it** (`gate_session` blocked/allowed hours, `gate_btc_vol` min/max) are pinned bit-identical to the oracle
  when ACTIVE — not only proven inert when OFF. *(REQ-TEST-009/010/011, REQ-PAR-030)*
- **T.3a — Adaptive-blacklist incremental==full-recompute, 48h-window-crossing fixture (R3-F3-batch5/F3-batch6 —
  FR-011a self-identifies the adaptive-blacklist-from-own-trades incremental==recompute equivalence (REQ-PAR-026 /
  REQ-PERF-010 O(1) counter) as exactly the "HOW changes WHAT" risk a columnar/JIT rewrite can silently break and
  says it is "proven by a dedicated golden fixture", but that fixture had NO §T number and NO gating AC: T.3's
  single admit/reject per-filter-step fixtures are a DIFFERENT assertion than incremental-vs-full-recompute
  equivalence across a sliding-window boundary, and §Y mapped FR-011a only to the generic battery).** A dedicated
  multi-scan fixture where a symbol is blacklisted by the run's OWN losing trades AND closes cross the **48h lookback
  window boundary** (entering/leaving the window), asserting the **O(1) incremental win/total counter EQUALS the
  legacy full-history recompute over the sliding window at EVERY scan**, including the `≤T` vs `<T` boundary tie and
  the exact win/total `close_reason` feed. Gated by a P0/P3 AC (AC-006b) and cited from the §Y PAR row instead of the
  generic battery. *(FR-011a, REQ-PAR-026, REQ-PERF-010; P0 freeze / P3 parity; R3-F3-batch5/F3-batch6)*
- **T.3b — Funding granularity-invariance + negative-rate-inversion fixture (R4-F3-batch5 — FR-010 (funding charged
  exactly once per 0/8/16h boundary via `(date,hour)` dedupe regardless of candle granularity; longs pay / shorts
  receive, inverted for negative `funding_rate_fixed_pct`; applied to the POST-funding wallet the equity cascade
  reads) is a frozen, path-dependent cross-cutting invariant feeding the equity cascade — the same "HOW changes WHAT"
  class FR-004/FR-009/FR-011a each got a DEDICATED fixture+AC for — but T.3 only TOGGLES `funding_rate_model{none,
  fixed_8h}` in the interaction matrix; nothing pins the granularity-invariant once-per-boundary dedupe or the
  negative-rate inversion).** A dedicated **multi-scan, multi-granularity** fixture asserts bit-identical to the legacy
  oracle that: (a) funding is charged **exactly once per `(date,hour)` boundary across a 5m run AND a drilled-1m run**
  (identical charge COUNT + timing — granularity-invariant dedupe), (b) the **negative-`funding_rate_fixed_pct`
  inversion** (longs RECEIVE / shorts PAY), and (c) the equity cascade reads the **POST-funding wallet** on a boundary
  bar. Gated by AC-006d; cited from the §Y PAR row. *(FR-010, REQ-PAR-013; P0/cross; R4-F3-batch5)*
- **T.4 — Differential float64-vs-Decimal + two-sided sandwich.** A differential harness asserts the float64 lane
  is non-optimistic (≤ Decimal) on drill/portfolio paths; a randomized property test asserts the drilled-trade
  two-sided sandwich (drilled PnL ≤ always-LTF oracle AND ≥ coarse pessimistic bound) across the input space; the
  always-LTF reference is self-validated to reduce to the exact coarse-5m result on no-ambiguity bars. *(REQ-TEST-005/006, REQ-DRILL-018)*
- **T.4c — ENTRY-BAR drill fixture (entry-fill bar spans a barrier — R6-F2-batch1, REQ-DRILL-022).** A dedicated
  fixture pins the case where the ENTRY-fill bar's own `[low, high]` spans a TP/SL/liquidation barrier: the engine
  drills the entry bar, replays 1m sub-bars chronologically resolving the entry FILL then the first touched level with
  pessimistic **liq→SL→TP** precedence, and is non-optimistic vs the always-LTF oracle. Explicitly DISTINCT from the
  same-bar exit-eligibility (5m) case and the mid-life both-levels case (which T.4/AC-015a already cover). Gated by
  AC-015c. *(REQ-DRILL-022, FR-030, NFR-008; P0/P2/P3; R6-F2-batch1)*
- **T.5 — Three-way reconciliation on EVERY fixture + degenerate metrics.** `Σ trade.pnl == net_profit ==
  final_equity − start` AND per-trade `trade.pnl == gross_price_pnl − entry_fee − exit_fee − funding_paid` (a
  **liquidation** trade instead satisfies `trade.pnl == −locked_margin − entry_fee − funding_paid`, exit_fee==0 —
  FR-007/AC-002, R4-F1-batch4); a meta
  test removing one term turns it red. Zero-trade + degenerate-metric fixtures assert `total_trades` present-and-0
  and persist without aborting. **B&H-collision fixture (R4-F4-batch5):** one fixture **TRADES BTC/USDT while the BTC
  B&H baseline is active**, asserting the B&H series is EXCLUDED from Σ while the real BTC trade is included exactly
  once (gated by AC-048g). **Liquidation-with-fees-and-funding fixture (R4-F1-batch4):** one fixture liquidates a
  position carrying a non-zero `entry_fee` AND a crossed funding boundary, asserting the corrected liquidation
  per-trade identity participates in Σ (gated by AC-002). *(REQ-TEST-012/013/014)*
- **T.6 — Sealed-once + cache-parity tests.** A mock-client test asserts a sealed day's `call_count == 1` across N
  reruns and `bybit_kline_calls == 0` on a fully-sealed rerun; a tri-source hash-equality test (Bybit ingest vs
  Postgres-read-rebuild vs Parquet-rebuild) gates `content_sha256`; interior-hole / ambiguous-hole / empty-lifecycle
  / NULL-sha / TTL-exempt / legacy-coarse-seal **/ backward-clock-step (R4-F3-batch6)** tests cover the manifest.
  **Backward-clock-step fixture (R4-F3-batch6 — FR-023's monotonic-ratchet `frontier = max(prev, computed)` is
  anti-RC-3 safety-critical (an un-seal from clock skew/NTP step would re-mark sealed days as gaps and reopen the
  headline re-download bug this feature exists to kill) but had NO test: T.6's enumerated fixtures omit a
  backward-clock-step case, and the arch states the property without naming a test owner — by contrast FR-024's
  NULL-lifecycle IS covered by the empty-lifecycle fixture):** GIVEN a sealed day and an injected BACKWARD wall-clock
  step (now goes backward by > T), WHEN the frontier is recomputed and gap-detection runs, THEN `frontier(persisted)`
  is UNCHANGED (`max(prev, computed)` holds), the day STAYS sealed, and the rerun issues `bybit_kline_calls == 0`
  (RC-3 not reopened). *(REQ-CACHE, REQ-STORE-003, REQ-MIG-014/015/016/017, REQ-CACHE-006/REQ-STORE-010; R4-F3-batch6)*
- **T.6a — Forming-day snapshot-coherency concurrency test (R4-F1-batch5 — the entire §T battery is single-threaded
  golden fixtures, so a torn cross-read between the engine main load and the 3 aux reads (B&H/btc_vol/MR-mean) is
  INVISIBLE to the golden master; FR-012's "same forming-day snapshot" needs an interleaving test the single-threaded
  oracle cannot provide).** A concurrency test runs a to-present window that needs the forming day and **interleaves a
  live-scanner forming-day `kline_cache` upsert BETWEEN the engine main load and EACH aux load**, asserting (a) all
  consumers read **identical forming-bar OHLCV** for every symbol (the single SoA-build forming-day buffer was the only
  read; the interleaved upsert does NOT leak into any series), (b) on the streamed/cursor path the multi-batch read is
  internally coherent under its `repeatable_read` snapshot, and (c) an **xmin-horizon / pool-exhaustion assertion** —
  the forming-day capture transaction commits immediately (NO long-held `repeatable_read` across the ≤120s run, so the
  connection returns to the pool and the DB `xmin` horizon does not advance-pin). *(FR-012, REQ-PAR-045, REQ-STORE-030; cross; R4-F1-batch5)*
- **T.7 — SoA boundary-equivalence + scaling micro-benchmarks.** Empty/single-candle arrays, signal-before-first /
  at-or-after-last, epoch-vs-datetime `open_time`; a 4×-history-at-fixed-W ±10% setup test; per-lookup ≤log(N)
  microbench; a non-monotonic-query microbench; the LIGHT per-advance ns ceiling **(asserted against the PINNED
  ≥100k LIGHT-advance/s ⇔ ≤10,000 ns/advance frozen constant — NFR-004/R6-F1-batch2, the wall-dominant term's
  falsifiable tripwire, NOT a test-author-chosen value)** + symbol-scaling micro-gate. *(REQ-ENG-001..007, REQ-PERF-005)*
- **T.8 — Benchmark regression gates.** ≥100× vs frozen P0 baseline (engine-CPU basis, numba lane, host-normalized —
  per NFR-002, **uncapped-full-canonical baseline, R3-F3-batch2/F8-batch2**); **≥150k/≥5M HEAVY-evals/s floors**
  (`ticks×B` unit, architecture §11.2 basis — NOT the blended 1.43M, R3-F1/F2-batch2); **the canonical DISCRETE fingerprint asserted byte-identical across P0–P6
  AND the MONEY fingerprint byte-identical P0–P2 (Decimal), re-frozen as float64 at P3, byte-identical P3–P6 (NOT a
  single money byte-hash across the P2→P3 pivot — R2-F1-batch5) — over the AUTHORITATIVE canonical fingerprint AS
  RESOLVED BY AC-001 (90d×50sym, or the 30d×20sym fallback when the 6h ceiling trips), the SAME identity AC-041 gates
  per phase (R5-F3-batch5)**;
  per-tier read-latency micro-bench (Arrow < Feather < Parquet < Postgres). **REQ-PERF-043 sub-gates (restored — the
  spec previously kept only tier-ordering and dropped three):** (a) **month-granular file-OPEN count** — Parquet/
  Feather opens ≤ `months_touched × symbols_touched`, NEVER per-day; (b) **mmap major-page-fault / thrash bound** when
  the working set exceeds the page cache; (c) **derived-coarse ≤ native latency** — a `BT_DERIVE_COARSE` 4h run is
  **never slower than the same-window native 5m run** (FR-035's resample step must not regress), with the one-time
  fine→coarse resample budgeted `O(fine_candles)`. **Cold-start gates (REQ-PERF-040 — was WARM-only):** a
  **cold-start worst-case** (cold JIT compile + empty in-process LRU/hot + cold columnar files) completes within the
  120s cap AND asserts boot-time JIT warm is actually invoked; a **COLD-COMPUTE** budget (empty caches, JIT
  pre-warmed, IO mocked) `<30s`; a **cold drill-ON** budget. **GET-path downsample cache (REQ-PERF-034):** a test
  asserts repeated/concurrent GETs of a COMPLETED run do NOT re-parse + re-LTTB the full JSONB each time (served from
  an **in-process read-through cache keyed by `run_id`**; the trough-preserving LTTB + the FR-052 global-max-DD
  search are **computed at most once per process per run** — NOT necessarily at persist-time, since N.2 adds NO
  persisted downsampled-curve column (R3-F8-batch5 — the prior "run ONCE at persist, materialized" wording implied a
  storage column that does not exist; the storage design is the read-through cache, computed on first GET and cached,
  so a cold process recomputes once then serves from cache); the manifest still hashes the full pre-downsample JSONB). Persist-<3s
  round-trip-flat; a no-leak soak over heterogeneous (incl. killed+cancelled) runs asserting flat RSS +
  FD/mmap/shm/conn baseline. **Engine perf-regression micro-gates (REQ-ENG-011/013 — were orphaned):**
  trailing-profit is **O(P) per candle not O(P²)** (a P-doubling test asserts ≤~2×); TP/SL/liq barrier prices are
  **derived ONCE per opened position** (a counter test asserts once-not-per-candle). **Progress/warmup/metrics micro-gates
  (REQ-PERF-035/032 — R4-F3-batch4/R4-F5-batch5, gated by AC-048i):** first progress signal **<1s after run start**;
  progress-write statement count **O(100) flat as candle count doubles** at **<2% overhead**; the P1 `_WARMUP_BAND`
  stage **collapsed to a bounded constant** (flat as pre-window history lengthens); metrics compute **O(curve+trades)
  single-pass** (a curve-doubling test stays ≤~2×, no O(n²) drawdown/run-up rescan). **Sweep-combo==standalone parity
  row (AC-017 — R2-F3-batch5): a single sweep combo's persisted result is discrete-identical + money-within-epsilon to
  a standalone DRILL-OFF `backtest_run` of that exact config, and `optimize_config`'s PROPOSED (drill-off-coerced)
  config reproduces the per-combo metrics it was ranked on.** *(REQ-PERF-003/004/005/034/040/043,
  REQ-ENG-011/013, REQ-PAR-042, REQ-PAR-043/REQ-SWEEP-009)*
- **T.9 — Contract snapshot tests.** Full GET `/backtest/{id}` envelope + the **frozen `metrics_keys.json` exact
  key set** (names + types, nested objects expanded — not "~45"), **asserted as REQUIRED-core ⊆ served ⊆
  (REQUIRED ∪ OPTIONAL), NOT blanket set-equality (R3-F9-batch3 — run-conditional drill/MR/cohort/regime keys), with
  every numeric metric key typed `number|null` and NO string sentinels (R3-F9-batch2)** + `total_trades` invariant +
  `EquityPoint`/
  the **`page`/`limit`/`sort_by` OFFSET trades-pagination param schema (R4-F2-batch4 — the REAL contract, NOT a
  cursor schema)** + **the frozen `trades_keys.json` (19 `BacktestTrade` fields + `strategy_kind`) and
  `summary_keys.json` (summary-object keys), additive-only **AND two-tier REQUIRED-core/OPTIONAL like
  `metrics_keys.json` — `served ⊇ REQUIRED-core` AND `served ⊆ (REQUIRED ∪ OPTIONAL)`, `strategy_kind` +
  cohort/MR/regime trade fields classified OPTIONAL+nullable so a non-MR run missing them does NOT false-fail
  (R6-F4-batch5)**, so a dropped/renamed/retyped trade or summary field
  fails CI exactly like a dropped metrics key (R3-F5-batch5)** + **an FE render test that the `null` degenerate-metric
  path renders without a formatting exception and never drops `total_trades` (R3-F9-batch2)** + **an
  unknown-`close_reason` FE-render contract test (R5-F6-batch5): GIVEN a `GET /backtest/{id}/trades` response carrying
  an UNKNOWN `close_reason` (`mr_target`), WHEN the trades table renders, THEN the row renders with a safe generic
  display and is NEVER dropped/blanked and no formatter throws (paired with a code citation that `close_reason` is
  rendered generically / never branched-on, mirroring the `BacktestResultsPage.tsx:255`/`types.ts:31` status
  citations)**;
  **GET-result `status` only emits the legacy five wire values** (queued/interrupted_by_restart
  mapped per FR-052) so an old FE keeps polling; **the status-wire-map assertion ALSO covers the GET `/backtest`
  LIST endpoint (each returned run row's `status`) AND the MCP `backtest_get`/`scans_get` `status` field
  (R2-F6-batch5 — these were uncovered; a leaked `queued`/`interrupted_by_restart` on the list/MCP surface
  reproduces the exact FE blank/stop-poll trap FR-052 closes), enumerating EVERY internal→wire mapping (queued→
  pending, interrupted_by_restart→failed, failed_with_timeout→failed) and asserting ONLY the legacy five ever
  appear**; MCP `backtest_get`/`sweep_results`/`backtest_compare`/`scans_get`
  additive-only **AND the MCP reject/queued error shape** (FR-040); the public `/backtest-runtime/status` payload
  omits exact versions/git-SHA/resource numerics **AND a spoofed `X-Forwarded-For` from a non-loopback peer gets only
  the coarsened payload (R2-F8)**; **a routing test that `GET /backtest-runtime/status` resolves to
  the status handler and `run_id="status"` is never shadowed**; **a route-enumeration test that the backtest router
  exposes EXACTLY the real 9 routes + their HTTP methods (`POST /backtest`, `GET /backtest`, `GET /backtest/compare`,
  `GET /backtest/{id}`, `GET /backtest/{id}/trades`, `POST /backtest/{id}/cancel`, `DELETE /backtest/{id}`,
  `GET /backtest-cache/status`, `POST /backtest-cache/warmup`) — asserting NO `POST /backtest/{id}/run` exists and
  `compare` resolves only under GET (R3-F1-batch6)**; bidirectional old↔new deploy-order; reject-shape
  error contract; the near-simultaneous terminal-state race; same-run_id double-submit; cancel-vs-slot-grant race.
  **Infra-flags-absent schema-snapshot (REQ-CFG-013 — was orphaned):** a snapshot of `BacktestCreateRequest` + the
  MCP `backtest_run`/`sweep_run`/`optimize_config` param schemas asserts NONE of the **6 infra/accel ENV knobs (the 5
  boolean accel gates + the `BT_COLUMNAR_DIR` PATH; T.9 enumerates the env-knob NAMES, not a boolean-gate count — the
  ROLLBACK gating set is 7 booleans per FR-046/R5-F4-batch4, a distinct list)** appear;
  the optimizer's PROPOSED `AutoTradeConfig` omits them; and `config_hash` is **byte-identical pre/post-optimization**
  (the infra flags never enter the hash inputs). *(REQ-FE-009/010/011, REQ-API-007/012/015, REQ-CFG-013, REQ-SEC-005, R2-F6-batch5/R2-F8-batch1)*
- **T.10 — Security + migration + flag tests.** Windows junction-swap rejected (Parquet dir AND numba
  `NUMBA_CACHE_DIR`, R2-F6-batch1); DuckDB injection cannot escape/mutate AND the `duckdb>=1.1` lockdown-enforcement
  probe (post-lockdown `SET enable_external_access=true` rejected, R2-F5-batch1); **worker `os.environ` is a SUBSET of
  the closed allowlist (not a 4-name denylist, R2-F4-batch1) AND a NEGATIVE test asserts `PG*`/`PGPASSWORD`/
  `PGSSLKEY`/`PGSERVICEFILE`/`DATABASE_URL`/`ACCOUNTS_ENCRYPTION_KEY`/secret-`BT_*` are ABSENT from the worker env
  even when the parent has them set (R5-F5-batch1)**; zip-bomb/bad-schema/checksum-mismatch archive **(REQ-SEC-003,
  DEFERRED — runs ONLY when the default-OFF `public.bybit.com` bulk-archive feature is built behind its flag; NOT a
  CI gate this feature, since the protected path is out of scope by default per X-5/O.7/G.3 — R5-F4-batch1)**;
  first-deploy wrong-DB refusal; missing-grant fail-closed; **`bt_flag_config` write-lockdown (no public HTTP/MCP
  write; non-operator SAFE_MODE-off rejected, R2-F1-batch1); per-caller-class breaker isolation (backtest-OPEN does
  not gate a live call, R2-F2-batch1); over-scope warmup rejected pre-fetch with `bybit_kline_calls==0` (R2-F3-batch1);
  spoofed `X-Forwarded-For` from a non-loopback peer gets only the coarsened status payload (R2-F8-batch1)**;
  v58 decouple + atomic-rollback + idempotent-second-run +
  expand-only schema-diff + **`backtest_runs.status` CHECK widen (queued/interrupted_by_restart insertable post-v58;
  swap callable + atomic-rollback-safe; whitelisted expand-only in the schema-diff guard, R2-F1-batch3; PRE-CHECK
  pre-check makes the second direct run issue ZERO status-CHECK DDL / no ACCESS EXCLUSIVE, R5-F4-batch2)** +
  legacy-upsert-column-preservation + restored-prod-clone rehearsal;
  **NAMED MIG sub-tests (R5-F3-batch3): wrong-PK + pre-created-wrong-typed-column fail-loud BEFORE any ADD COLUMN
  (REQ-MIG-007/008, AC-008a); fresh-DB `0→58` schema-byte-identical-to-57→58 + seal-backfill-no-op-on-empty +
  CREATE-before-INSERT ordering (seeding an index-less `mcp_sweep_results` so the `bt_flag_config` deferred-marker
  INSERT fires) (REQ-MIG-040, AC-012); symbol_lifecycle override-survives-refresh + readiness-before-population
  (REQ-MIG-010); pooling-mode session-pinned advisory-lock on a DIRECT non-pooled connection (REQ-MIG-028);
  post-backfill ANALYZE + EXPLAIN-uses-index on the mostly-sealed distribution (REQ-MIG-034); partition-tree-gap
  REFUSAL + default→proper-partition reconciliation (REQ-MIG-035); gate-before-relax (REQ-MIG-038); in-place-edit
  checksum (REQ-MIG-002)**;
  SAFE_MODE one-lever + Postgres-down honorability + cancels-live-sweep + halts-seal; flag-flip-honored-next-run;
  **shadow/dark-compare (R5-F2-batch5): read-path shadow logs an injected columnar byte-divergence AND returns
  authoritative Postgres; engine-shadow on a small synthetic seeded-divergence config emits the size-capped localized
  divergence payload (trade-ordinal/symbol/field/magnitude) AND persists the optimized result; dark-mode (flags off)
  populates v58 fingerprint columns while staying oracle-identical (AC-047a)**; CI
  module-absent + flag-combination matrices. *(REQ-SEC-001..002/004..007, REQ-MIG-002/007/008/010/018/020/028/034/035/038/040/041, REQ-ROLL-001/002/003/005/009/027,
  R2-F1/F2/F3/F4/F5/F6/F8-batch1, R2-F1-batch3, R5-F2/F3/F4/F5/F6/F7-batch3)*

---

## U. Acceptance Criteria

> Given/When/Then, measurable. **Every phase P0–P6 has explicit acceptance criteria** that gate its merge.
> A phase is DONE only when ALL its ACs pass AND the golden-master diff is green.

### U.0 — Phase P0: Golden-master parity harness (gates ALL phases)

- **AC-001** — GIVEN the current (pre-optimization) engine run **OFFLINE via the `GoldenMasterOracle` harness with
  the `BacktestService` 120s Timer DISABLED** (the legacy engine cannot finish the canonical 90d×50sym fixture under
  the cap — §B/§E — so the baseline is captured uncapped, NOT as a 120s-censored E2E time), WHEN it runs the
  canonical fixture + the per-close-rule battery, THEN it freezes (a) a stored snapshot (ordered trades + ordered
  equity_curve + the frozen `metrics_keys.json` set), (b) the **full-scale 90d×50sym frozen result fingerprint —
  SPLIT into a DISCRETE fingerprint (byte-identical P0–P6) and a MONEY fingerprint (Decimal-frozen P0–P2, re-frozen
  as float64 at P3 per R2-F1-batch5)** (REQ-PAR-042), and (c) the **engine-only-CPU baseline per the NFR-002 protocol** — the **authoritative uncapped
  full-canonical engine-CPU measurement** (the reduced-sub-fixture extrapolation is a documented super-linear-fit
  cross-check ONLY, never the headline denominator — R3-F3-batch2/F8-batch2) — recording the
  baseline fixture identity, basis, and lane. All version-tracked. The canonical golden snapshot is captured on the
  full 90d×50sym fixture offline (the harness has no service timeout). **P0 capture wall-clock CEILING + fallback
  PINNED (R4-F6-batch4 — §B/RC-1/RC-2 prove the uncapped legacy engine is SUPER-LINEAR in scans×symbols×N_total with a
  quadratic-in-time seeding term over ≈1.296M candles × ≈2160 scans, so the one-shot uncapped capture — which GATES
  ALL 7 phases — is an unbounded prerequisite that could run to tens of hours / practically non-terminate in a CI/dev
  window, an unquantified feasibility/schedule risk):** the uncapped legacy run carries a **concrete wall-clock
  ceiling of 6 hours on the pinned capture host (recorded in the manifest: host CPU model + clock)**. IF the uncapped
  full-90d×50sym capture EXCEEDS that ceiling, the documented FALLBACK is a **smaller-but-representative canonical
  golden fixture (e.g. 30d×20sym) that STILL exercises every `close_reason` and the carried-position/cross-scan
  paths**, promoted to the authoritative DISCRETE+MONEY fingerprint, with the full-90d×50sym fingerprint DOWNGRADED to
  a best-effort/offline artifact (captured opportunistically, not a merge prerequisite). This ceiling + fallback is an
  explicit AC clause so P0 can never block indefinitely. **The fallback ALSO redefines the coupled NFR-002 ≥100×
  baseline AND propagates to every section that hard-codes 90d×50sym (R6-F8-batch1/R6-F4-batch2/R6-F6-batch5 — the
  fingerprint had a fallback but the coupled perf/B/budget basis did not: NFR-002 pins the ≥100× authoritative
  denominator to "(b) one uncapped full-canonical engine-CPU measurement" and FORBIDS the reduced-sub-fixture
  extrapolation as the denominator — but the 6h ceiling trips PRECISELY BECAUSE that uncapped full-canonical run will
  not finish, so when the fallback fires the ≥100× hard merge gate (AC-027/AC-030, `accel_waived` MUST be false on
  windows-latest) has NO valid baseline AND its only alternative (the 30d×20sym sub-fixture) is the very thing NFR-002
  forbids; likewise AC-004a's B-measurement, the §Q.2/Q.3 budget calibration, and the `ticks≈25,920`=90d×5m
  arithmetic all stay pinned to the now-demoted 90d×50sym artifact, violating AC-041's "the fingerprint identity
  CHOSEN at P0 is the SAME identity gated at EVERY later phase"):** when the 6h ceiling trips, ADOPT option (a) —
  **the ≥100× engine-CPU baseline is captured on the SAME 30d×20sym fallback fixture** (recording the documented
  super-linear-fit correction note, since a 30d×20sym legacy CPU number is a weaker basis), and the **≥100× multiplier
  is ASSERTED OPPORTUNISTICALLY/OFFLINE against the full-canonical baseline if/when it ever lands — capability-waived
  (like the numba ACs) until then — with the absolute `≤60s`/`≤90s` REQ-PERF-046 budgets binding as the sole P-gate in
  the interim** (recorded in the run manifest as `baseline_fixture: 30d×20sym`, `accel_waived` semantics extended to
  `perf_baseline_waived`). This keeps the windows-latest ≥100× hard gate always-defined: it gates against the resolved
  fallback fixture's baseline, never a forbidden extrapolation, and never an absent denominator. **Propagation (same
  conditional applied everywhere AC-041 was reconciled):** AC-004a measures B on whichever fixture AC-001 makes
  authoritative; NFR-002's baseline is on the resolved fixture; the §Q.2/Q.3 budget + B-table fixture identity
  (`ticks` count re-derived for the resolved fixture — 30d×20sym ⇒ `ticks≈8,640`, NOT 25,920) re-derive together, so
  B-measurement, the ≥100× baseline, and the budget calibration follow the SAME resolved identity the merge gate uses.
  *(NFR-002, T.1, AC-004a, AC-027/AC-030, §Q.2/Q.3; R4-F6-batch4, R6-F8-batch1, R6-F4-batch2, R6-F6-batch5)*
- **AC-002** — GIVEN any fixture, WHEN the three-way reconciliation runs, THEN the EXACT discrete identities hold
  (trade count, opened set, `close_reason`, exit-bar index) AND `Σ trade.pnl == net_profit == final_equity −
  starting_capital` (EXACT on the Decimal lane, within `continuous-money-epsilon` from P3) AND per-trade `trade.pnl
  == gross − entry_fee − exit_fee − funding_paid` **for non-liquidation closes**, while a **liquidation** trade
  instead satisfies `trade.pnl == −locked_margin − entry_fee − funding_paid` with `exit_fee == 0` and no exit
  slippage (FR-007 carve-out, pinned to the engine SSOT per R4-F1-batch4 — the bare `−locked_margin` is WRONG and
  would break the Σ on any liquidation-bearing run); THIS liquidation value participates in the Σ. A meta-test
  removing one term turns it RED. **Liquidation reconciliation fixture (R4-F1-batch4 — the prior carve-out's
  `−locked_margin` was untested against a non-zero entry_fee + a crossed funding boundary, the exact terms it
  omitted):** a P0 fixture exercises a liquidation **WITH a non-zero `entry_fee` AND a 0/8/16h funding boundary
  crossed BEFORE the liquidation** (so `funding_paid ≠ 0`), asserting BOTH the corrected per-trade identity
  `trade.pnl == −locked_margin − entry_fee − funding_paid` AND the three-way Σ over a run that includes that
  liquidation. *(NFR-009, T.5, FR-007; R4-F1-batch4)*
- **AC-003** — GIVEN the close-rule battery, WHEN union-coverage runs, THEN every `close_reason` enum value is
  exercised AND a teeth meta-test disabling one fixture turns the union gate RED. **The authoritative enum is DERIVED
  FROM THE ENGINE SOURCE (not a hand-maintained list)** and a completeness meta-test asserts `fixture_close_reasons
  == source_close_reason_enum` — so a newly-added enum value WITHOUT a fixture fails CI. **The enum tokens are the
  ACTUAL engine-emitted literals, NOT prose aliases (R6-F1-batch4 — VERIFIED against `backtest_engine.py`: the engine
  emits the ABBREVIATED tokens `tp` (lines 825/834/1345/1352) and `sl` (820/823/829/832/1322/1328/1343/1350) and
  `breakeven` (line 1930) — NEVER `take_profit`/`stop_loss`/`breakeven_timeout`; a fixture/contract test asserting the
  long aliases would make this very `fixture_close_reasons == source_close_reason_enum` meta-test RED because the
  source never produces them):** the authoritative source-of-record enum is the set actually returned/appended in
  `backtest_engine.py` — `tp`, `sl`, `liquidation`, `equity_drop`, `equity_drop_smart`, `close_on_profit`,
  `equity_rise`, `trailing_profit`, `mr_time_stop`, `max_duration`, `breakeven`, `backtest_end` (cite
  `backtest_engine.py:820-834` + `:1714/1729/1749/1767/1859/1898/1903/1930` + `:315`). This prose list is
  ILLUSTRATIVE-ONLY / non-normative — the snapshot artifact is generated PROGRAMMATICALLY from the engine source, so
  the meta-test compares fixtures to the real tokens, never to a hand-maintained alias list. **`mr_target` is NOT a
  current engine token — undeclared cross-feature dependency RESOLVED (R6-F2-batch4 — grep confirms `mr_target` exists
  ONLY as the config field `mr_target_capture_pct` and the helper `mr_target_price` (mean_reversion_math.py); the
  backtest engine NEVER emits `close_reason=='mr_target'`; it appears as a close_reason ONLY in the separate, unmerged
  `regime-multistrategy-spec.md`, so a literal "the enum MUST include `mr_target`" clause is unsatisfiable against the
  source-derived enum and would force a hand-add that violates "derived from source"):** the `mr_target` 'MUST include'
  requirement is REMOVED. The completeness gate relies SOLELY on the source-derived enum; a future `mr_target` lands
  automatically when regime-multistrategy merges (an explicit assumption — regime-multistrategy is NOT a hard P0
  prerequisite of this feature), and the FE-render forward-compat path (AC-043/T.9) already handles any unknown
  `close_reason` generically, so no P0 hard-requirement depends on a token the engine does not yet emit. *(T.2; R6-F1-batch4, R6-F2-batch4)*
- **AC-004** — GIVEN the legacy `_evaluate_candles_until`/`_eval_equity_core` code, WHEN the P0 cadence-evidence
  step runs, THEN the ACTUAL basket-equity recompute cadence relative to the symbol loop is read + recorded as
  cited evidence AND **a DIFFERENTIAL test runs BOTH candidate cadences (once-per-tick vs per-symbol-candle) on a
  multi-symbol fixture with an equity-threshold rule positioned to make them DIVERGE, asserting which cadence is
  bit-identical to legacy** (an automated pass/fail, not only a human read). **Branch AC:** IF the differential
  proves legacy is per-symbol-candle, THEN (a) the parity oracle freezes per-symbol-candle cadence, (b) the HEAVY
  cost term O(candles×B), the NFR-003 evals/s floor, and the §Q/NFR-004 latency+symbol-scaling budgets are
  re-derived + re-frozen with a named owner BEFORE P3 proceeds, (c) the cadence-contingent budgets are flagged. The
  once-per-tick oracle is frozen only if the differential confirms it. *(FR-018, NFR-004)*
- **AC-004a (canonical open-book depth B MEASURED before freezing the HEAVY budgets — R4-F5-batch4: the entire
  HEAVY-term budget basis (`heavy_eval_count ≈ ticks × B ≈ 0.13M`, the ≥150k/≥5M HEAVY-evals/s floors, the ≤60s
  canonical wall) is load-bearing on canonical peak-open-book depth `B≈5`, but unlike the cadence assumption (which
  got the AC-004 evidence-gate BEFORE freezing), `B≈5` is ASSERTED, never measured-and-gated pre-freeze (R.2 only
  calibrates `peak_open_positions` POST-hoc); if the canonical fixture actually averages B=10–15 concurrent positions,
  every canonical HEAVY budget is 2–3× optimistic and silently passes/fails on the wrong basis)** — GIVEN the frozen
  canonical fixture **AS RESOLVED BY AC-001 (90d×50sym, OR the 30d×20sym fallback when the 6h capture ceiling trips —
  R6-F6-batch5: B MUST be measured on whichever fixture AC-001 makes authoritative, with `ticks` re-derived
  accordingly — 30d×20sym ⇒ `ticks≈8,640`, not 25,920 — so the B-measurement, the ≥100× baseline, and the budget
  calibration all follow the SAME resolved identity AC-041 gates per phase)**, WHEN the P0/early-P3 measurement runs, THEN the ACTUAL **peak and mean open-book B**
  (concurrent open positions per timeline tick) is measured and recorded, AND either (a) confirms `B ≤ 5` (the
  budgets stand) OR (b) the canonical `heavy_eval_count`, the NFR-003 evals/s denominators, and the §Q/NFR-004
  canonical HEAVY latency budgets are **re-derived and re-frozen against the measured B BEFORE the P3 merge gate**.
  The canonical HEAVY budgets are flagged **'B-contingent'** (the same way cadence budgets are 'cadence-contingent'),
  with a pre-computed fallback row for the measured-B case **— the §Q.2 B-contingency table (PRE-COMPUTED for
  B≈10 / B≈15, R5-F4-batch5) supplies the re-derived `heavy_eval_count`, pure-Python/numba budgets, and owner/gate, so
  a measured B>5 has a deterministic already-reviewed resolution and never stalls P3**. *(FR-018, NFR-003/004, R.2, Q.2; P0/P3; R4-F5-batch4, R5-F4-batch5)*
- **AC-005** — GIVEN the NO-OP inputs (empty instrument_info/scan_contexts/fine_klines + no regime), WHEN the
  engine runs, THEN output is byte-identical to the pure 5m path. *(NFR-010)*
- **AC-006** — GIVEN a zero-trade / degenerate-input fixture, WHEN it runs, THEN `metrics.total_trades` is
  present-and-0, the run renders as a real result, and reconciliation holds trivially. *(S.1, T.5)*
- **AC-006a (`skip_if_positions_open` cycle-gating latch — R3-F2-batch5: the P0-frozen FR-009 latch had no fixture
  or AC and the canonical master runs the default `false`)** — GIVEN the T.2a multi-scan fixture with
  `skip_if_positions_open=true` and a non-empty open book at a scan START, WHEN the engine runs (at P0 and re-checked
  at each later phase), THEN it is bit-identical to the legacy oracle: new entries are skipped that scan, close rules
  still fire on carried positions, the anchor is preserved, and `smart_drawdown` is NOT re-armed on the skipped scan;
  an empty-book scan takes the normal admit+re-arm+re-anchor path. *(FR-009, T.2a; P0; R3-F2-batch5)*
- **AC-006b (adaptive-blacklist incremental==full-recompute — R3-F3-batch5/F3-batch6: FR-011a's self-identified
  high-risk parity path (REQ-PAR-026/REQ-PERF-010 O(1) counter) had a fixture promised in prose but no §T number and
  no gating AC)** — GIVEN the T.3a multi-scan fixture where a symbol is blacklisted by the run's OWN losing trades
  AND closes cross the 48h lookback boundary, WHEN the engine runs (P0 freeze, **re-asserted at P3 AND P4** — the SoA
  and numba rewrites are where this latch can be silently perturbed, R5-F2-batch4), THEN the O(1)
  incremental win/total counter EQUALS the legacy full-history recompute over the sliding window at EVERY scan —
  including the `≤T` vs `<T` boundary tie and the exact win/total `close_reason` feed. *(FR-011a, T.3a; P0/P3/P4; R3-F3-batch5/F3-batch6, R5-F2-batch4)*
- **AC-006c (`fill_to_max_trades` relaxed second pass — R4-F1-batch4: the P0-frozen FR-011/REQ-PAR-025 relaxed
  admission pass had no fixture or AC, and the canonical master runs the default `false`)** — GIVEN the T.2b multi-scan
  multi-signal fixture with `fill_to_max_trades=true` and a strict pass that under-fills `max_trades`, WHEN the engine
  runs (at P0 and re-checked at each later phase) in BOTH `execution_mode{batch,immediate}`, THEN it is bit-identical
  to the legacy oracle: the relaxed pass skips strict-rejected signals and continues, tops the per-scan `scan_entered`
  counter up to exactly `max_trades`, bypasses ONLY `min_score`/`confidence` (still rejecting stale/already-open/
  over-`max_trades`), and ranks leftovers by `abs(score)` descending. A `fill_to_max_trades=true` config is ALSO
  asserted fast-path-INELIGIBLE (FR-013 clause 7) — it routes to the sequential kernel. *(FR-011, FR-013, T.2b; P0; R4-F1-batch4)*
- **AC-006d (funding granularity-invariance + negative-rate inversion — R4-F3-batch5: FR-010 is a frozen
  path-dependent cross-cutting invariant feeding the equity cascade but had no dedicated fixture/AC, only a
  `funding_rate_model{none,fixed_8h}` toggle in T.3)** — GIVEN the T.3b multi-scan multi-granularity fixture, WHEN the
  engine runs (P0 freeze, re-checked at later phases), THEN it is bit-identical to the legacy oracle: (a) funding is
  charged exactly once per `(date,hour)` boundary with an IDENTICAL charge count + timing across a 5m run AND a
  drilled-1m run (granularity-invariant dedupe — drill does NOT double-charge), (b) a negative `funding_rate_fixed_pct`
  INVERTS direction (longs receive / shorts pay), and (c) the equity cascade reads the POST-funding wallet on a
  boundary bar. *(FR-010, REQ-PAR-013, T.3b; P0/cross; R4-F3-batch5)*

### U.1 — Phase P1: Cache re-download fix

- **AC-007** — GIVEN a fully-sealed range, WHEN a backtest reruns N times, THEN `bybit_kline_calls == 0` AND each
  sealed day's lifetime fetch `call_count == 1` (mock-client test). *(FR-020, R.2)*
- **AC-007a (post-v58 pre-backfill lazy-seal — R2-F2-batch2)** — GIVEN `schema_version=58` applied but
  `SealBackfillRunner` NOT yet run (so every coverage row carries the `sealed=false` default) WHILE the
  `kline_cache` candle rows for a past-frontier window are ALREADY present + complete, WHEN a backtest runs over
  that window, THEN the read-path lazy-seal evaluates the FR-019 predicate against the stored rows and seals the
  complete days in-place FIRST, so `bybit_kline_calls == 0` for those already-complete days (RC-3 is NOT re-opened
  during the post-v58/pre-backfill window) — gap-fill targets only genuinely-missing bars. *(FR-019, NFR-017)*
- **AC-007b (lazy-seal latency bound — R3-F5-batch3)** — GIVEN the FIRST post-v58 canonical run over a
  complete-but-unsealed `[start, frontier]` window (≈4,500 day-rows would otherwise be evaluated/UPDATEd inline),
  WHEN it runs, THEN (a) the read-path lazy-seal touches ONLY the days THIS run reads (scoped to its symbols+window,
  not the whole corpus), (b) the seals are applied as batched set-based UPDATEs (a `lazy_seal_ms` timer is recorded),
  (c) each lazy-sealed day carries a NON-NULL `content_sha256` = the FR-025 canonical hash of its SOR rows, and (d)
  the run still completes **within its ≤60s/≤90s latency budget WITH `lazy_seal_ms` included** — the lazy-seal cost
  does not blow the run budget, and bulk sealing of out-of-window days stays the deferred `SealBackfillRunner`'s job.
  *(FR-019, FR-025, NFR-001; R3-F5-batch3)*
- **AC-007c (SWEEP-level zero-exchange work over a sealed range — R6-F5-batch4: §D's goal names BOTH "Reruns AND
  sweeps do ZERO redundant exchange work", but the only gating AC (AC-007) covers the single-run RERUN path; no AC
  asserted `bybit_kline_calls == 0` for a multi-combo SWEEP over a sealed range — sweeps fan combos across a spawn
  ProcessPool (J.2), so a per-worker/per-process cache-fill miss is a plausible regression that passes every existing
  cache AC while re-pulling history, the exact Bybit rate-limit/cost liability the goal targets; the SoA is shared
  once but the per-combo warm-up/coverage path was not AC-gated)** — GIVEN a ≥100-combo sweep over a FULLY-SEALED
  range on the ProcessPool lane, WHEN the sweep runs, THEN **aggregate `bybit_kline_calls == 0` across ALL workers**
  (cache-fill happens ONCE at warm-up, NOT per combo / per process) AND per-run `postgres_kline_selects` stay bounded
  (no per-combo Postgres re-read storm) — a mock-client test sums the counter across the pool. Wired into the §Y
  CACHE + SWEEP rows. *(FR-020, FR-042, J.2, §D; cross; R6-F5-batch4)*
- **AC-008** — GIVEN the canonical klines, WHEN P1 ships, THEN the produced klines are byte-identical to legacy
  (the seal model changed coverage detection, not bytes) AND `schema_version` reaches 58 sub-second with the
  backfill running separately. *(FR-019, NFR-014)*
- **AC-008a (v58 fail-loud step-0 pre-checks — R5-F2-batch3: REQ-MIG-007/008 had ZERO spec/AC/T.10 anchor, so a P1
  merge could go green while v58 built the manifest on a wrong PK or a wrong-typed column)** — GIVEN a DB seeded with
  (i) a `kline_cache_coverage` PK that is NOT exactly `(symbol, interval, date)`, OR (ii) a pre-created manifest
  column of an INCOMPATIBLE type/width (e.g. `first_open_ts INT4` where v58 wants `BIGINT`), WHEN the v58 callable
  runs, THEN it **RAISES an actionable diagnostic BEFORE any `ADD COLUMN`** (the key-mismatch message names the
  expected PK; the wrong-type message names the column + expected type) and **`schema_version` stays 57** with
  nothing partially applied — `ADD COLUMN IF NOT EXISTS`'s silent-skip on a wrong-typed column is converted to a
  fail-loud. A T.10 sub-test is wired to the ACTUAL callable (not a mock). *(REQ-MIG-007/008, NFR-014; P1; R5-F2-batch3)*
- **AC-009** — GIVEN a mid-day-listing / halt / forming day storing e.g. 144/288, WHEN coverage is evaluated,
  THEN it is sealed-short (or forming) — NOT a perpetual gap — and is never re-probed (the RC-3 bug is dead). *(FR-021, S.5)*
- **AC-009a (monotonic-frontier backward-clock-step — R4-F3-batch6)** — GIVEN a sealed day and an INJECTED BACKWARD
  wall-clock step (now moves backward by > T, e.g. NTP correction / clock skew), WHEN the completion frontier is
  recomputed and gap-detection runs, THEN `frontier(persisted) == max(prev, computed)` is UNCHANGED (the ratchet never
  regresses), the previously-sealed day STAYS sealed (is NOT re-marked a gap / NOT un-sealed), and the rerun issues
  `bybit_kline_calls == 0` — so a clock step can never reopen RC-3 (the headline re-download bug). *(FR-023,
  REQ-CACHE-006, REQ-STORE-010, T.6; P1; R4-F3-batch6)*
- **AC-010** — GIVEN an ambiguous interior hole, WHEN it seals, THEN it carries `gap_count`/`gap_ranges` +
  `reverify_pending=true` (held WARM) and gets exactly one post-frontier re-fetch before any permanent
  negative-cache. **The fetch-eligible predicate `(NOT sealed) OR reverify_pending` + the
  `idx_coverage_unsealed WHERE NOT sealed OR reverify_pending` index give it a real trigger path (R2-F3-batch2): a
  `day_class=3 / reverify_pending=true` day (which is `sealed=true`) IS selected for exactly one fetch and then
  settles — clearing `reverify_pending` (confirmed gap) or re-sealing class 1/2 (filled) — never an infinite refetch.** *(FR-022)*
- **AC-011 (P1 bi-source leg — R3-F3-batch1: the tri-source gate was unsatisfiable at P1 because the Parquet tier
  does not exist until P5)** — GIVEN a **bi-source** comparison (**Bybit ingest vs Postgres-read-rebuild**) over one
  sealed day **at P1**, WHEN `content_sha256` is computed, THEN both are bit-identical. The **Parquet-rebuild leg is
  deferred to its own P5 AC (AC-011p)** — at P1 only the two sources that physically exist are gated. *(FR-025, T.6)*
- **AC-012** — GIVEN v58, WHEN applied, THEN it contains zero destructive DDL (schema-diff guard), is a callable
  migration (no `;`-split), is a post-apply no-op on second run, and an injected mid-DDL failure leaves
  `schema_version` at 57 with nothing partial. **Status-CHECK execution-idempotency (R5-F1-batch3/R5-F4-batch2):** the
  test runs the v58 callable TWICE directly and asserts the second invocation issues **ZERO status-CHECK DDL** (the
  `pg_get_constraintdef` pre-check SKIPs the DROP/ADD/VALIDATE because the 7-value superset already holds), acquires
  **NO ACCESS EXCLUSIVE lock**, and the status constraint is **never momentarily absent**. **Fresh-DB `0→58`
  equivalence + statement-ordering (REQ-MIG-040 — R5-F6-batch3: applying the FULL `_MIGRATIONS` list from an EMPTY DB
  must yield a schema byte-identical to an in-place 57→58 upgrade, with the seal-backfill a clean no-op on empty
  tables; AND the architecture's CREATE-before-INSERT boot-crash-loop guard must hold):** a fresh-DB test applies
  `0→58` from empty and asserts (a) the resulting schema is **byte-identical to an in-place 57→58 upgrade**, (b) the
  data-dependent seal-backfill is a **clean no-op on empty tables**, and (c) **CREATE-before-INSERT statement
  ordering** holds — `bt_flag_config` (and every control table) is CREATEd BEFORE any statement INSERTs into it
  (the test seeds an **index-less `mcp_sweep_results`** so the deferred-`uq_mcp_sweep_results_sweepcfg` marker INSERT
  into `bt_flag_config` actually fires, proving the table exists before the INSERT — arch line 1017/1018). *(NFR-014/015, REQ-MIG-040; P1; R5-F1-batch3, R5-F4-batch2, R5-F6-batch3)*
- **AC-013** — GIVEN the deferred `SealBackfillRunner`, WHEN it runs, THEN it mutates ONLY coverage/manifest +
  lifecycle rows (a before/after content-hash diff proves every `kline_cache` candle byte-identical) and resumes
  idempotently from its checkpoint. **AND each backfilled seal carries a NON-NULL `content_sha256` equal to the
  FR-025 canonical hash of its SOR rows (R2-F7) — so the backfilled historical corpus is hashed + verifiable, not
  sealed-immutable-yet-unhashed; residual NULL-sha days are covered by the NFR-016 sampled backstop.** *(FR-050, FR-025)*

### U.2 — Phase P2: Batched loaders + parallel sweeps + drill-down

- **AC-014** — GIVEN the load path, WHEN a run loads S symbols, THEN it issues 1 batched query (not N+1) and the
  per-run Postgres round-trip SUM is O(1) in scan/candle count with fixed parameterized text. *(FR-027, NFR-006)*
- **AC-014a (P2 batched-load BYTE-IDENTITY + duplicate-row parity — R3-F7-batch6: REQ-PAR-039 (must, P2) requires the
  batched `ANY($1)` kline load to bucket into strictly-ascending per-symbol arrays BYTE-IDENTICAL to a per-symbol
  `ORDER BY` read, the batched `scan_source`/`ScanContext` load byte-identical to the legacy per-scan load, AND
  duplicate/overlapping scan rows handled per legacy — but the only P2 load AC (AC-014) asserted PERFORMANCE (1
  batched query, O(1) round-trips), not byte-identity, and AC-041's discrete fingerprint runs on the CLEAN canonical
  fixture which never exercises duplicate/overlapping rows)** — GIVEN the batched `ANY($1)` loader and a fixture with
  **duplicate/overlapping scan rows + a sparse/misaligned universe** (some symbols short, some absent for some
  scans), WHEN inputs load, THEN (a) each symbol's per-symbol kline bucket is **byte-identical** to the per-symbol
  `ORDER BY open_time` read (strictly-ascending, same dedup), (b) the batched `scan_source`/`ScanContext` grouping is
  **byte-identical** to the legacy per-scan load, and (c) duplicate/overlapping scan rows produce **no double-anchor /
  no double re-arm** — identical anchoring/grouping to legacy. Named test added to T.3/T.7; cited from the §Y
  PAR/CFG rows. *(FR-027, REQ-PAR-039; P2; R3-F7-batch6)*
- **AC-015** — GIVEN `drilldown_enabled` toggled on vs off, WHEN a fixture runs, THEN trade SELECTION is identical
  (same positions opened, same close rules in the same order) — ONLY intrabar fill PRICE may differ — AND no LTF
  fetch occurs on bars touching neither/exactly-one level. *(FR-029, NFR-008)*
- **AC-015a (FR-030 drill non-optimism + two-sided sandwich — dedicated phase gate, was only a T.4 reference with no
  gating AC — R2-F10-batch2)** — GIVEN synthetic (coarse-bar, 1m-sub-bar) configs, WHEN a drilled trade fills, THEN
  a property test asserts the **two-sided sandwich for EVERY drilled trade**: drilled PnL ≤ always-LTF oracle
  (non-optimistic) AND ≥ the coarse pessimistic-resolution bound; entry slippage is applied with the same
  direction/bps as the 5m path (neither dropped nor double-applied); a per-bar 1m FETCH FAILURE falls back to 5m for
  THAT bar only (never aborts, never persists partial 1m, stays non-optimistic). *(FR-030, NFR-008, T.4)*
- **AC-015b (FR-028 drill rerun-memo + linear scaling — the central anti-re-download benefit had no AC at the phase
  that delivers it — R2-F5-batch5)** — GIVEN a drilled run then an identical drilled RERUN, WHEN the second run
  executes, THEN it issues **ZERO LTF fetches** (in-process memo hit-count == 0 second run) — no re-pull on rerun;
  AND GIVEN a fixture that DOUBLES the drilled-bar count, WHEN drill wall-time is measured, THEN it grows ≤~linearly
  in drilled-bar count while NON-drilled-bar cost stays flat O(1) (drill cost scales linearly, not super-linearly).
  *(FR-028, NFR-008)*
- **AC-015c (ENTRY-BAR drill — the entry-fill bar's own [low,high] spans a barrier — R6-F2-batch1: REQ-DRILL-022
  _(should, P0)_ explicitly demands a DEDICATED fixture for the case where the entry-fill bar itself spans a TP/SL/liq
  barrier, calling itself DISTINCT from same-bar exit-eligibility (5m) and mid-life both-levels cases; a spec-wide grep
  for the requirement returned ZERO hits and the §Y DRILL row mapped DRILL only to FR-028/029/030 + O.6 + S.16 — none
  of which is the entry-bar-spans-barrier case — so this fixture-bearing must-have was orphaned, the same gap-class
  that earned `skip_if_positions_open` its AC-006a/T.2a and `fill_to_max_trades` its AC-006c/T.2b; the Z-3
  orphan-check passed spuriously because DRILL was mapped at the category level)** — GIVEN an entry-fill bar whose own
  `[low, high]` spans a TP/SL/liquidation barrier (the "entry + its-stop-both-inside-the-same-bar" trigger), WHEN the
  bar is drilled, THEN the engine drills the ENTRY bar and replays 1m sub-bars chronologically, resolving the entry
  FILL first and THEN the first touched level with pessimistic **liq→SL→TP** precedence, and the result is
  **non-optimistic vs the always-LTF oracle** (drilled PnL ≤ always-LTF). This is asserted as a fixture DISTINCT from
  the same-bar exit-eligibility (5m) case and the mid-life both-levels case (T.4c). *(REQ-DRILL-022, FR-030, NFR-008, T.4c; P0/P2/P3; R6-F2-batch1)*
- **AC-016 (P2 — parallelism only, NOT the absolute sweep budget)** — GIVEN a sweep on M cores over the **canonical
  SWEEP combo fixture (PINNED: each combo = 14 days × 10 symbols × 5m ≈ 40k candles × ≈336 scans — a small fixture
  the P2 legacy-loop engine CAN run quickly)**, WHEN it runs, THEN measured **speedup ≥ 0.7×min(M,K,concurrency)** vs
  serial (NOT efficiency ≥ a >1 value), aggregate IPC/pickling bytes are independent of combo count, and process-tree
  RSS ≈ base + C×small-working-set. **Capability disposition (R4-F3-batch5 — with `USE_PROCESS_POOL` decoupled from
  `HAS_NUMBA` (FR-031), a no-numba host DOES get ProcessPool, so the speedup gate applies there too; but a host with
  NO real parallelism mechanism (no usable `shared_memory`/`spawn` AND no numba for the nogil ThreadPool ⇒ sequential
  lane, speedup ≈ 1×, `concurrency` would be undefined) cannot satisfy `≥0.7×min(M,K,concurrency)`):** on a host with
  ProcessPool OR the nogil ThreadPool, `concurrency` = that pool's resolved worker count (NFR-005) and the
  ≥0.7×min(M,K,concurrency) gate binds; on the **sequential-only fallback host the speedup gate is WAIVED-by-capability**
  (recorded in the manifest, exactly as the U.4 numba ACs are waived) since no parallelism mechanism exists. **The
  absolute 100-combo `<60s` / 500-combo `<5min` wall budgets are NOT gated at
  P2** (the engine is still the legacy super-linear loop until P3 SoA / P4 numba — 100 canonical-class combos cannot
  finish in 60s at P2 even fully parallel); they are gated at AC-024b/AC-039 on the fast engine. *(FR-031, NFR-005)*
- **AC-017 (RESTORED — sweep-combo == standalone parity, the FR-032 must-level gate; was dropped, leaving the §Y
  `P2 {AC-014..019}` range non-contiguous and REQ-PAR-043/REQ-SWEEP-009 unverified — R2-F2-batch5/R2-F3-batch5/
  R2-F10-batch2)** — GIVEN a single sweep combo C and a standalone `backtest_run` of C's EXACT config, WHEN both
  run, THEN the persisted results are **discrete-field identical** (trade count, opened set, sides, symbols,
  entry/exit bar indices, `close_reason`, ordering) AND **money within `continuous-money-epsilon`** (Decimal-exact on
  the P0–P2 lane); AND `optimize_config`'s PROPOSED config, re-run standalone, reproduces the per-combo metrics it
  was ranked on. **Drill disposition PINNED (resolves R2-F2-batch4 — the sweep runs the pure engine that bypasses
  drilldown, so a `drilldown_enabled=true` standalone would apply 1m intrabar fills the combo did not, diverging
  within <1% but NOT equal):** sweeps **coerce `drilldown_enabled=false`** for the combo, and the "== a standalone
  `backtest_run`" equality is asserted against the **drill-OFF standalone** of that config. **PROPOSED-config
  preserves the user's `drilldown_enabled` (R3-F11-batch3 — do NOT leak the internal drill-off coercion into the live
  proposed config):** the PROPOSED `AutoTradeConfig` carries the **user-supplied `drilldown_enabled` value
  unchanged** (not coerced false), with the ranked metric annotated drill-off-derived; a sub-assertion checks the
  proposed config's `drilldown_enabled` equals the user's input and is never silently flipped. (A drill-ON
  standalone of the same config is the separate <1% drill lane, NOT the equality target.) Named test: T.8 sweep-parity
  row (extends the benchmark-regression battery). *(FR-030/FR-032, REQ-PAR-043, REQ-SWEEP-009; R2-F2-batch4/F2-batch5/F3-batch5, R3-F11-batch3)*
- **AC-018** — GIVEN the `PreflightEstimator`, WHEN it evaluates runs, THEN **(reject path)** a WIDE run whose
  predicted peak RSS exceeds the WIDE total-RSS budget is rejected with the 4xx structured error contract before it
  takes a slot (NOT a completed/zero-trade row); **(predicted-wall-time reject term — added, R2-F1-batch4: the gate
  must NOT be RSS-ONLY, else a no-numba host ADMITS a WIDE run that FITS ≤2GB and then dies at the 120s kill — the
  exact failure this feature removes)** the gate ALSO rejects pre-slot when **`predicted_wall_ms > the resolved-lane
  budget`** (numba-lane budget if `HAS_NUMBA`, else the pure-Python lane budget) — concretely a no-numba WIDE whose
  LIGHT term alone (~21M advances at a ~100k LIGHT-advance/s pure-Python rate ≈ 210s) exceeds the budget is rejected with the 4xx contract, NOT
  admitted; **(ADMIT path)** the canonical, HEAVY, and HEAVIEST
  in-budget fixtures all return **verdict=run (NO false reject)** — queue/reject trigger ONLY above the documented
  slot/RSS/wall-time envelope. Determinism of the reject gate does NOT rely on the symmetric ±50% accuracy: both the
  RSS and the wall-time reject thresholds carry a **conservative under-estimate margin** — reject when `predicted_rss >
  budget / (1 + under_estimate_margin)` (and `predicted_wall_ms > budget / (1 + under_estimate_margin)`) with
  **`under_estimate_margin = max(actual/predicted) − 1 = 1.0` (PINNED to the ±50%-bracket worst case — R4-F4-batch4 —
  so the thresholds are `predicted_rss > budget/2` and `predicted_wall_ms > budget/2`, NOT `budget/1.5`; the natural
  "0.5" reading would admit up to ~1.33×budget and break the determinism claim AC-048d leans on)** (so a true
  over-budget run is never admitted
  by an optimistic estimate); the runtime RSS watchdog is the backstop, not the gate. **No-numba HEAVY/HEAVIEST
  contingency reject (R4-F7-batch4 + R4-F1-batch6 — under the Q.2 cadence-contingency the per-symbol-candle HEAVY/
  HEAVIEST lane resolves to "numba-required; pure-Python parity-only / no-latency-budget"; if AC-004 proves
  per-symbol-candle AND `HAS_NUMBA` is false there is NO pure-Python HEAVY/HEAVIEST budget for this gate to compare
  against, so the run would be admitted-then-killed at 120s — re-introducing the exact regression this feature
  removes; the same hole exists for HEAVIEST when AC-024a option (b) downgrades it to numba-required on a no-numba
  host, §I.0a):** for a "parity-only / no-latency-budget" lane (no-numba HEAVY or HEAVIEST under the per-symbol-candle
  contingency, OR a numba-required-downgraded HEAVIEST on a no-numba host), the AC-018 reject threshold resolves to the
  **universal 120s cap** (with the margin: reject when `predicted_wall_ms > 120s/2 = 60s`), so an infeasible no-numba
  HEAVY/HEAVIEST run is REJECTED pre-slot with the 4xx contract (bybit/slot untouched), NOT admitted-then-killed — the
  reject term is extended beyond WIDE to ALSO cover HEAVY and HEAVIEST whenever their resolved lane has no latency
  commitment. **Drill term excluded from the reject threshold (R4-F8-batch4):** the drill term is NOT added into
  `predicted_wall_ms` for the reject decision (drill-ON overruns governed by the watchdog + ≤90s budget), so a
  near-budget in-budget drill-ON HEAVY/HEAVIEST run is NOT false-rejected. **ADMIT-path tests use NEAR-budget drill-ON
  fixtures (R4-F8-batch4 — not only comfortably-in-budget):** the canonical, HEAVY, and HEAVIEST ADMIT assertions
  include a NEAR-budget drill-ON HEAVY/HEAVIEST fixture returning verdict=run (no false reject), AND a separate
  no-numba HEAVY/HEAVIEST contingency fixture returning the 4xx reject (bybit/slot untouched, not a 120s kill). The
  estimator still brackets
  actual within ±50% on deterministic terms (drill term excluded). **PHASE-SPLIT (R6-F4-batch1 — the §Y map puts
  AC-018 in P2 {AC-014..019}, but the wall-time reject term + the canonical/HEAVY/HEAVIEST "verdict=run, no false
  reject" ADMIT assertions compare against the resolved-lane WALL budget, and the pure-Python ≤60s/≤90s lane budgets
  are a P3 SoA-engine deliverable — at P2 the engine is still the legacy super-linear loop that AC-016/AC-024b say
  "cannot finish in 60s even fully parallel," so at P2 the estimator either has no realized wall budget to compare
  against or, using the P3 ≤60s target, would predict EVERY canonical run over-budget and FALSE-REJECT it, breaking
  AC-018's own ADMIT assertion; the RSS reject term IS P2-realizable, the wall-time term is not):** the **RSS /
  aggregate-RSS reject path (AC-048d) is gated at P2**; the **predicted-wall-time reject term AND the
  canonical/HEAVY/HEAVIEST "verdict=run / no-false-reject" wall ADMIT assertions move to P3**, where the resolved-lane
  wall budgets first exist. A P2 merge requires only the RSS gate; the wall-time gate is asserted from P3 on. The §Y
  per-phase map is updated accordingly (AC-018-RSS at P2, AC-018-wall at P3). *(FR-039/040,
  NFR-024, NFR-012, R2-F1-batch4, R4-F4-batch4, R4-F7-batch4, R4-F1-batch6, R4-F8-batch4, R6-F4-batch1)*
- **AC-019** — GIVEN the parallel-execution host-capability predicate **`USE_PROCESS_POOL = shared_memory-usable AND
  start_method=='spawn'`** (DECOUPLED from `HAS_NUMBA` per R4-F3-batch5 — pure-Python combos parallelize across
  processes fine; a capability check that resolves identically on dev and prod for a given host — NOT a "win32 vs
  prod" dichotomy, since spawn is available on ALL Windows incl. the Windows-11 PRIMARY
  prod target), WHEN a sweep runs, THEN a host satisfying the predicate selects **ProcessPool + `shared_memory`**
  (independent of numba — a no-numba host STILL gets ProcessPool, running pure-Python combos per process) and a host
  failing it selects the **ThreadPool-over-nogil** path (when `HAS_NUMBA`) or the final sequential fallback — pinned,
  not silently auto-degraded, and the
  Windows-11 prod path is explicitly the ProcessPool path. The **Windows `shared_memory` cleanup contract** is
  documented + tested: each segment is released when the creating process's last handle closes (no POSIX
  `resource_tracker`), and a terminal-path test asserts no leaked segments after complete/cancel/kill. *(FR-031, W-3; R4-F3-batch5)*

### U.3 — Phase P3: SoA + merge-walk engine

- **AC-020** — GIVEN the SoA/merge-walk engine, WHEN it runs the canonical 5m no-drill fixture, THEN the result is
  **discrete-fields bit-identical** to the frozen float64 master AND money within `continuous-money-epsilon` vs the
  Decimal oracle. *(NFR-007)*
- **AC-021** — GIVEN a test that 4×-es the pre-window history at fixed window size W, WHEN per-scan setup is timed,
  THEN setup time stays constant within ±10% (the RC-1 super-linear setup is dead). *(FR-015)*
- **AC-022** — GIVEN an exit level touched on the boundary bar between two adjacent scans, WHEN the merge-walk
  evaluates, THEN it fires in EXACTLY the same scan/bar as the legacy window scan. *(FR-016, S.7)*
- **AC-023** — GIVEN carried positions across multi-scan timelines (incl. the epoch-vs-datetime `open_time` case +
  empty/single-candle boundary arrays), WHEN mark-seeding runs, THEN it is bit-identical to the linear-prefix
  oracle with no `IndexError`. *(FR-017, S.8)*
- **AC-024** — GIVEN the pure-Python SoA lane, WHEN the canonical fixture runs, THEN throughput ≥150k
  **HEAVY-evals/sec** single-core (`ticks×B` unit, §I-preamble/architecture §11.1) AND the canonical **drill-OFF**
  pure-Python E2E ≤60s (P3 reaches "minutes" without numba). **Canonical drill-ON pure-Python budget (R3-F2-batch1 —
  the canonical 50-sym drill-ON pure-Python lane previously fell in NO latency gate: ≤60s was drill-OFF-only and the
  ≤90s exception was HEAVY/HEAVIEST-only):** the canonical **drill-ON** pure-Python run carries a committed **≤90s**
  budget (the drill roughly doubles latency per the numba-lane <10s→<20s evidence, so canonical drill-ON pure-Python
  plausibly exceeds ≤60s), still `< 120s`, gated here under U.3 as its own clause. **Cadence-conditional gate
  (R3-F1-batch5/F1-batch3 — the ≤60s/≤90s figures are cadence-contingent per NFR-004/AC-004):** the ≤60s drill-OFF /
  ≤90s drill-ON numbers are the **once-per-tick acceptance bars**; IF the P0 cadence-evidence step (AC-004) proves
  legacy basket-equity recompute is **per-symbol-candle**, THEN this AC's numeric gate is one of the budgets
  **re-derived and re-frozen before P3** (SAME owner/gate as NFR-004 — the P3 merge gate then tracks the re-derived
  budget, not a stale ≤60s). *(NFR-001/003/004; AC-004)*
- **AC-024a (HEAVY/HEAVIEST lane — was un-gated)** — GIVEN the **HEAVY (90d×100sym×5m, drill-ON, B≈20) and HEAVIEST
  (90d×150sym×5m, drill-ON, deep book B≈40) fixtures (dimensions pinned per NFR-004/R2-F3-batch4)**, WHEN they
  run on the pure-Python SoA lane, THEN each finishes **≤90s** (the documented HEAVY/HEAVIEST latency budget, still
  `< 120s` — the universal hard cap is never raised)
  with **peak RSS within its OWN symbol-scaled drill-ON ceiling (R3-F4-batch1/F4-batch6/F1-batch4 — the canonical-
  derived ≤1.5GB was NOT re-derived for 2–3× the symbols + deeper book; resident klines, position book, and fine-SoA
  all scale with symbol count, so reusing the 50-sym number under-budgets the heavy classes):** **HEAVY ceiling ≤
  1.75GB** (`base_non_kline ~0.85GB + resident_klines(100sym)~0.3GB + 1m-drill-cache ≤256MB + fine-SoA ≤256MB +
  timeline`) and **HEAVIEST ceiling ≤ 2GB** (pinned under the **WIDE ≤2GB tier**, NFR-012: `resident_klines(150sym)
  ~0.45GB` + deeper book(B≈40) + drill cache + fine-SoA + `timeline_bytes` ~168MB worst case). AC-024a asserts each
  class against ITS OWN ceiling, not the canonical 1.5GB. On the numba lane (when present) each finishes **<30s**.
  **Pure-Python ≤90s contingency (R3-F6-batch3 — carries architecture §11.1 option (b)):** the pure-Python ≤90s is
  the default-but-contingent target; IF post-P3 profiling shows pure-Python HEAVIEST cannot meet ≤90s, THEN HEAVIEST
  is **downgraded to numba-required** (pure-Python HEAVY lane marked **parity-only, NOT latency-bound**) and the
  merge gate becomes **numba <30s**, recorded in the run/CI manifest — so the gate stays falsifiable rather than a
  dead-end P3 block. **No-numba HEAVIEST resolution (R4-F1-batch6 — the contradiction: §I.0a/REQ-PERF-046 commits
  pure-Python HEAVY/HEAVIEST to a binding ≤90s bar when `HAS_NUMBA` false, but option (b) downgrades HEAVIEST to
  "numba-required" with the pure-Python lane "parity-only / NOT latency-bound"; on a no-numba host BOTH cannot hold —
  "numba-required" is unsatisfiable, so a downgraded HEAVIEST would have NO satisfiable latency commitment AND
  (since AC-018's reject was WIDE-only) would be admitted-then-killed at 120s):** the resolution is **option (b)
  extended to AC-018** — when HEAVIEST is downgraded to numba-required AND `HAS_NUMBA` is false, the pure-Python
  HEAVIEST lane is parity-only with NO latency commitment, and **AC-018's predicted-wall-time pre-slot reject is
  EXTENDED to reject such a HEAVIEST run** (resolved threshold = the universal 120s cap with the under-estimate
  margin) — so a no-numba HEAVIEST that profiling shows cannot meet ≤90s is REJECTED with the 4xx contract pre-slot,
  NOT admitted-then-killed. No run-class is left both budget-less AND un-rejected on a supported host. This gates the
  committed HEAVY/HEAVIEST cap so a phase cannot merge green while the heavy lane is unverified (mirrored at P4/P6).
  *(NFR-001/004/012, Q.1/Q.3, AC-018; R3-F4-batch1/F4-batch6/F1-batch4/F6-batch3, R4-F1-batch6)*
- **AC-024b (sweep absolute budget — re-tagged here from P2)** — GIVEN a **100-combo warm sweep** over the canonical
  SWEEP combo fixture, WHEN it runs on M cores **with `USE_PROCESS_POOL` satisfied (`HAS_NUMBA AND shared_memory AND
  spawn` — AC-019/FR-031)**, THEN it
  finishes **<60s** and a **500-combo** sweep finishes **<5min**. **Lane-ownership reconciliation (R3-F6-batch2/
  F8-batch6 — the prior text listed "P3 pure-Python SoA" as owing the absolute, but those absolutes are reachable
  ONLY via ProcessPool parallelism, which is gated on `HAS_NUMBA`; a no-numba host runs sweeps on the GIL-bound
  ThreadPool and CANNOT meet <60s):** the absolute `<60s`/`<5min` budgets **bind ONLY when the ProcessPool lane is
  selected (`HAS_NUMBA` true)**. On a **no-numba-wheel host** the P3 pure-Python SoA sweep runs on the degraded
  ThreadPool/sequential lane and is governed by the **NFR-005 relaxed ceiling** (`Σ(per-combo pure-Python wall) /
  effective-parallelism`), **NOT** the absolute — so "P3 pure-Python SoA" is removed from the absolute-budget list
  and made capability-conditional like the U.4 numba ACs. *(FR-031, NFR-005; R3-F6-batch2/F8-batch6)*
- **AC-025** — GIVEN symbol-doubling at fixed candles, WHEN engine time is measured, THEN it grows ≤2× (LIGHT +
  HEAVY terms each gated, per-advance ns ceiling held). *(NFR-004)*

### U.4 — Phase P4: numba JIT kernel (optional, import-guarded)

> **Capability gate (binds all of U.4):** every AC below is a MUST **only when `HAS_NUMBA` is true** on the target.
> If `HAS_NUMBA` is false (no wheel / ABI break on Py3.14.3+numpy2.4.4, task #71 / V-1), AC-026/027/030 and the
> numba-lane budgets are **WAIVED-by-capability** (recorded `accel_waived:true` in the manifest) and the pure-Python
> ≤60s canonical / ≤90s HEAVY lane (AC-024/AC-024a) is the binding bar — see §I.0a.

- **AC-026** — GIVEN the `@njit` kernel and the pure-Python fallback of record, WHEN both run the full
  fixture/fuzz/differential grid, THEN **outside the pinned `continuous-money-epsilon` money guard-band the two lanes
  are DISCRETE-field bit-identical (trade count, sides, symbols, entry/exit bar indices, ordering); WITHIN the
  guard-band EITHER they agree OR the config is detected near-threshold and ROUTED to the pure-Python oracle — never
  a silent cross-lane discrete divergence** (this matches the architecture's CPython-vs-LLVM 1-ULP resolution; a
  blanket "always bit-identical" is unsatisfiable on near-threshold configs and is NOT claimed). A CI
  `boundscheck=True` build proves no out-of-bounds (prod sets `boundscheck=False`). **Near-threshold routing gate
  (R3-F8-batch1 — exercises the NFR-007 per-tick in-kernel guard-band):** GIVEN a config deliberately constructed so
  an open position's price passes WITHIN `gb=1e-4` of a firing TP/SL/liq/equity threshold on at least one tick, WHEN
  it runs, THEN the per-tick in-kernel guard-band sets the `near_threshold` flag and the run is **actually ROUTED to
  the pure-Python oracle** (whole-run re-resolution), proving the mechanism fires rather than silently accepting a
  possibly-divergent float result. *(FR-016, M.4, NFR-007; R3-F8-batch1)*
- **AC-026a (near-threshold double-run combined budget — R4-F4-batch4: the whole-run pure-Python re-resolution is two
  full executions but had no combined-latency budget or AC, unlike the structurally-identical AC-028a accel-failure
  fallback)** — GIVEN a near-threshold canonical (and HEAVY) config that trips the per-tick guard-band and is routed
  to whole-run **Decimal-mode SoA merge-walk re-resolution (the engine PINNED in NFR-007/R5-F1-batch5 — same
  `O(total_candles + ticks×B)` algorithm as M.4 in `Decimal` dtype, NOT the legacy `GoldenMasterOracle` super-linear
  engine)**, WHEN it runs, THEN (1) the `near_threshold` flag fires EARLY (as
  soon as the first open position enters the guard-band, so the float attempt is discarded before deep work where
  possible) and (2) the SUM `(float attempt + Decimal-SoA re-resolution)` completes **< 120s** for
  **CANONICAL** (mirrors AC-028a), **measured against the §Q Decimal-throughput basis (~50–100×/op vs float64) so
  the budget is FALSIFIABLE with a named engine and rate (R5-F1-batch5)** — the doubled-execution wall stays within
  the resolved-lane budget. **HEAVY (and larger) near-threshold disposition CORRECTED to in-flight ABORT (R6-F1-batch1
  — the prior "< 120s for canonical/HEAVY" was UNSATISFIABLE for HEAVY: a near-threshold HEAVY Decimal re-resolution is
  ≈175–350s on the §Q cost basis, and the "rejected pre-slot via AC-018" escape is UNREACHABLE because near-threshold
  is a MID-RUN property the pre-slot PreflightEstimator cannot see):** for HEAVY (or any class whose resolved Decimal
  re-resolution cannot fit the residual budget), when `near_threshold` fires mid-run the run is **ABORTED in-flight
  with the §K.3 structured terminal error (`near_threshold_decimal_infeasible` — a distinct terminal reason, NOT a
  completed/zero-trade row, NOT a 120s kill)**, never continuing into a Decimal pass that the 120s Timer kills. The
  HEAVY <120s assertion is DROPPED from this AC; AC-026a's wall assertion is CANONICAL-only. An OPTIONAL static
  near-threshold-RISK classifier MAY pre-reject the highest-risk HEAVY configs at AC-018, but the binding HEAVY
  guarantee is the in-flight abort. *(NFR-007,
  FR-014, AC-018, K.3; P4/cross; R4-F4-batch4, R5-F1-batch5, R6-F1-batch1)*
- **AC-027** — GIVEN the warmed `@njit` kernel (excl. first-call compile) **AND `HAS_NUMBA` true**, WHEN the
  canonical fixture runs, THEN throughput **≥ the frozen 0.7×-calibrated numba floor (R4-F2-batch5 — the merge gate is
  "measured warmed-numba rate ≥ frozen floor", NOT a literal pre-profiling ≥5M absolute; per architecture §11.2 the
  ≥5M figure is the post-P3-calibrated tripwire = 0.7× of the warmed-numba rate captured once and frozen, ≈5M HEAVY-
  evals/s)** single-core (`ticks×B` unit) AND the canonical
  drill-OFF E2E <10s (drill-ON
  <20s) on the numba lane; HEAVY <30s. **If `HAS_NUMBA` is false this AC is waived-by-capability** (AC-024/024a bind
  instead). **Numba-lane benchmark CI gating (R3-F5-batch6 — the headline numba budgets are MUSTs only when
  `HAS_NUMBA` true, but nothing forced at least one CI lane to actually measure them; if the slow benchmark ran only
  on a no-numba host the entire P4–P6 value prop could merge green never measured):** the numba-lane benchmark
  battery (this AC's ≥frozen-floor HEAVY-evals/s + <10s, AND NFR-002 ≥100×) **MUST run on the pinned `HAS_NUMBA`-true CI lane
  (the windows-latest prebuilt-wheel lane, AC-030) where it is a HARD merge gate** (`accel_waived` MUST be `false`
  there); only NON-numba lanes may waive. *(NFR-001/002/003/004; §I.0a; R3-F5-batch6, R4-F2-batch5)*
- **AC-028** — GIVEN the accel module is ABSENT or ABI-broken, WHEN the backend boots, THEN it still imports, the
  canonical backtest runs pure-Python, and a benign version mismatch warns while an ABI-breaking mismatch disables
  JIT + falls back. *(FR-048, S.14)*
- **AC-028a (combined accel-failure + fallback time budget — R3-F3-batch4: REQ-PERF-042 was asserted in FR-014 but
  had NO gating AC; AC-028 covers only BOOT-time absence, not a mid-run failure at the worst-case LATE detection
  point — the exact admit-then-die-at-120s regression this feature removes)** — GIVEN an accel failure INJECTED at
  the pinned worst-case detection point on the HEAVY fixture (e.g. ~80–90s into a HEAVY run), WHEN the run falls back,
  THEN (1) the **fail-fast accel-health validation actually trips at boot/warmup/first-combo — within the first
  seconds, NOT after ~90s** (so the worst-case late injection is itself prevented by health validation where
  possible), (2) the failed attempt's allocations are **freed before the pure-Python fallback begins** (no double-RSS
  peak), and (3) the **SUM (failed accel attempt + full pure-Python fallback rerun) completes < 120s**. Added to the
  §Y PERF anchor tests. *(FR-014, REQ-PERF-042; P4/cross; R3-F3-batch4)*
- **AC-029** — GIVEN the live scanner/auto-trade order-execution path, WHEN it runs, THEN it imports neither numba
  nor the SoA kernel, pays no JIT/warm cost, and yields unchanged sizing/barrier values. *(FR-049)*
- **AC-030** — GIVEN PREBUILT wheels for numba/llvmlite/pyarrow/duckdb, WHEN CI installs on every deploy target
  (generic, prod base libc, windows-latest), THEN all resolve to prebuilt wheels (no source build) and the
  windows-latest lane runs the full golden suite green; the dep checks re-run at each phase merge. **The
  windows-latest lane is ALSO the pinned `HAS_NUMBA`-true benchmark lane (R3-F5-batch6): the NFR-002 ≥100× +
  AC-027 ≥5M HEAVY-evals/s + <10s numba budgets are HARD merge gates on THIS lane (`accel_waived` MUST be `false`
  here), so the numba-lane value proposition is always measured pre-merge on at least one lane** — only non-numba
  lanes may record `accel_waived:true`. *(FR-048; NFR-002, AC-027; R3-F5-batch6)*

### U.5 — Phase P5: Parquet/DuckDB read layer

- **AC-031** — GIVEN `BT_USE_COLUMNAR` OFF, WHEN a run executes, THEN the result is Postgres-identical; GIVEN it
  ON, the columnar tier produces a cross-engine byte-parity result. *(FR-033, NFR-007)*
- **AC-031a (forming-day excluded from hot tiers; served from Postgres — R4-F3-batch5: FR-033/N.3 decided the
  correctness-critical invariant "KlineStore routes any range including ≥ completion_frontier exclusively to Postgres
  primary; Arrow/Feather/Parquet hold sealed-only; the forming day is NEVER admitted to a hot tier" (arch §11.1
  R1-F10/REQ-STORE-030 — it removes the unowned frontier-advanced-evict race and a stale-hot-frame serving wrong
  recent-backtest data), but it was asserted only in prose with a named ARCH test and NO §U AC gated it: AC-031..036
  cover columnar on/off byte-parity, tri-source sha, warm-rerun, rotted-Parquet, PITR, junction-swap — none assert the
  forming day is excluded from hot tiers / served from Postgres)** — GIVEN a range whose end is the forming UTC day,
  WHEN two reruns straddle a 5m frontier boundary, THEN both reflect **FRESH forming-day rows served from Postgres
  primary** (`kline_tier_hits` shows the forming day NEVER from arrow/feather/parquet; `postgres_kline_selects` ==
  forming-day-only on the warm rerun) AND the Arrow/Feather/Parquet tiers contain **only sealed data** (the forming
  day is never admitted to a hot tier, so the frontier-advanced-evict race cannot serve a stale hot frame). *(FR-033,
  REQ-STORE-030; P5/P2 seam; R4-F3-batch5)*
- **AC-011p (P5 Parquet leg of the tri-source `content_sha256` gate — R3-F3-batch1: split out from AC-011 because
  Parquet does not exist until P5)** — GIVEN the now-existing Parquet tier, WHEN `content_sha256` is computed over
  one sealed day via **Parquet-rebuild**, THEN it is bit-identical to BOTH the Bybit-ingest and Postgres-read-rebuild
  sources (completing the full tri-source equality that AC-011 asserts bi-source at P1). **Single-rounding canonical
  float64 (R3-F10-batch3 — closes the NUMERIC double-rounding hazard: a `NUMERIC`-typed column makes Postgres-rebuild
  `Bybit-string→Decimal→float64` (double rounding) while Bybit-ingest is `Bybit-string→float64` (single rounding),
  which can differ at the ULP and FAIL bit-identity):** the canonical float64 used for hashing is derived **ONCE from
  the Bybit-native string (single rounding) and reused across all three sources**. **NUMERIC disposition CORRECTED to
  the verified production fact (R6-F3-batch1 — the prior text was internally contradictory and proposed a forbidden
  remedy: (a) it both mandated the gate "never relies on a `float64(numeric)` re-derivation that double-rounds" AND in
  the next sentence required a test that "asserts the Postgres-read-rebuild float64 equals the Bybit-ingest float64
  bitwise even on a (legacy) NUMERIC table" — i.e. it forbade float64(numeric) then tested exactly float64(numeric);
  (b) the "migrate to `DOUBLE PRECISION`" remedy is a full table rewrite of the partitioned `kline_cache` SOR, which
  N.1c explicitly FORBIDS for that table under NFR-014 (catalog-only/sub-second v58) and NFR-015 (expand-only), so an
  implementer following it literally could attempt a destructive rewrite):** the VERIFIED fact is that production
  `kline_cache` OHLCV columns are **`DOUBLE PRECISION`** (cite `async_persistence.py:624-628`), so the NUMERIC branch
  is DEAD in production and the tri-source hash basis is well-defined with NO migration. NUMERIC is therefore treated
  as an **UNSUPPORTED legacy configuration that is BLOCKED at boot (fail-loud), NOT migrated** — a table rewrite is
  forbidden by NFR-014/NFR-015 (N.1c). The "migrate" option and the contradictory "assert float64(numeric) bitwise on
  a legacy NUMERIC table" test are DELETED. In their place: a boot/CI **fail-closed guard** asserts the `kline_cache`
  OHLCV column type IS `DOUBLE PRECISION`, and a NUMERIC-typed table causes the columnar/hash path to **REFUSE to run
  (fail closed)** rather than hashing re-derived `float64(numeric)` bytes. The retained bitwise test asserts
  Postgres-read-rebuild float64 == Bybit-ingest float64 on the **DOUBLE PRECISION** SOR (the production type), not on a
  legacy NUMERIC table. *(FR-025, N.1a, N.1c, NFR-014/015, T.6; R3-F3-batch1/R3-F10-batch3, R6-F3-batch1)*
- **AC-032** — GIVEN `BT_DERIVE_COARSE` ON, WHEN a 15m/1h/4h config runs, THEN derived-coarse == legacy
  native-coarse (byte-identical klines+trades); GIVEN it OFF, the legacy native-fetch path is the documented
  rollback lever (flag-OFF native-1h byte-identical parity test). **AND GIVEN `BT_DERIVE_COARSE` ON but NO sealed 5m
  base for the window, WHEN the coarse config runs, THEN it FALLS BACK to native per-interval fetch (NOT a 12× 5m
  cold-fetch) within the native cold-fill budget (R2-F6-batch4) — derive-coarse never silently amplifies cold-fetch
  cost.** *(FR-035)*
- **AC-033** — GIVEN a persistent `BT_COLUMNAR_DIR`, WHEN a cross-process warm rerun runs over a sealed window,
  THEN **on the numba lane (`HAS_NUMBA` true)** it finishes **<5s** (mmap Feather survives the deploy; the engine
  itself is fast enough that columnar read dominates); **on the pure-Python lane (`HAS_NUMBA` false)** the `<5s`
  precondition does NOT hold — the engine still executes ≤60s — so the pure-Python warm-rerun budget is its own
  **`≤60s` canonical / `≤90s` HEAVY** gate (the columnar read merely removes the IO term, not the engine term). An
  ephemeral dir waives even those to the cold-build budget (rebuild from Postgres, 0 Bybit). *(NFR-001, Q.3; §I.0a)*
- **AC-034** — GIVEN a rotted Parquet file (sha256/row-count mismatch), WHEN read, THEN it is invalidated + rebuilt
  from the Postgres SOR (seal never depended on the file). *(FR-034)*
- **AC-035** — GIVEN a PITR/restore that rewinds the SOR, WHEN the boot-identity hook OR the sampled backstop
  fires, THEN every columnar/in-RAM tier self-invalidates and derived-coarse re-derives exactly once then stops
  (frozen content set byte-unchanged across the re-stamp). **AND the PITR bump is O(1) — it updates ONLY the
  `sor_data_generation` singleton; invalidation is read-time token-compare, so NO table-wide `kline_cache_coverage`
  re-stamp UPDATE occurs (R2-F8-batch2) — a meta-assertion bounds the bump cost to the singleton write.** *(NFR-016, S.13)*
- **AC-036** — GIVEN a Windows `BT_COLUMNAR_DIR` junction-swap between check and open, WHEN a file is opened,
  THEN it is rejected (handle-based TOCTOU close); a DuckDB injection cannot escape `allowed_directories` or mutate
  config. **AND** GIVEN the loaded `duckdb` build, WHEN the boot/CI lockdown probe runs, THEN it asserts the build
  EXPOSES + ENFORCES `allowed_directories` + `lock_configuration` (`duckdb>=1.1`; a post-lockdown `SET
  enable_external_access=true` is rejected) — else the columnar path fails closed to Postgres (R2-F5). *(NFR-019/020,
  P.2/P.3)*

### U.6 — Phase P6: Vectorized fast-path + prange sweeps

- **AC-037** — GIVEN `BT_USE_FASTPATH` ON for a config with provably-independent positions, WHEN it runs, THEN the
  fast-path result satisfies the two-sided sandwich vs the sequential-kernel oracle AND the fast-path is provably
  gated to configs where it equals the sequential engine; sentinel "disable" values are truly inert. **Eligibility
  classification gate (R3-F7-batch1 — the predicate is now enumerated in FR-013):** a test exercises the
  FR-013 eligibility predicate's **eligible ↔ ineligible** classification — GIVEN a config that satisfies all **7
  clauses** (the 6 original + clause 7 `fill_to_max_trades` OFF, R4-F1-batch4) it is classified eligible and runs the
  fast-path; GIVEN a config violating EACH clause in turn (one armed
  portfolio close rule; sequential-depletion sizing; adaptive-blacklist-from-own-trades; `skip_if_positions_open`/
  live-book concentration cap; drill-ON; **a TRAILING_PROFIT-only config; a BREAKEVEN_TIMEOUT-only config (both
  moving/mutating within-position barriers — R5-F1-batch4)**; **`fill_to_max_trades`=true**) it is classified **ineligible AND provably
  ROUTES to the sequential kernel** (never silently runs the fast-path on a coupled config). **The trailing-only and
  breakeven-only cases each mirror REQ-ENG-030's property test (any config with trailing_profit or breakeven mutation
  routes sequential — R5-F1-batch4).** *(FR-013, NFR-008, REQ-ENG-029/030; R3-F7-batch1, R4-F1-batch4, R5-F1-batch4)*
- **AC-037a (P6 fast-path SPEEDUP — was missing; P6 had no speed gate)** — GIVEN `BT_USE_FASTPATH` ON on a
  provably-independent fixture **with `HAS_NUMBA` true**, WHEN it runs, THEN the vectorized barrier fast-path
  delivers **≥10× speedup vs the sequential kernel** (REQ-PERF-045) AND a guard asserts the fast-path is **never
  net-slower** than the sequential path for the configs it claims (else it routes to sequential). Without this AC a
  byte-correct-but-no-faster fast-path would pass every other P6 gate. **If `HAS_NUMBA` is false the speedup MUST is
  waived-by-capability** (the fast-path is a numba-lane optimization). *(FR-013, NFR-005; REQ-PERF-045; §I.0a)*
- **AC-038** — GIVEN the fast-path barrier scan, WHEN it runs, THEN it streams in bounded chunks (no full-universe
  materialization) and peak RSS stays within the klines budget. *(NFR-012, M.4)*
- **AC-039** — GIVEN a 500-combo `prange`/ProcessPool sweep, WHEN it runs, THEN it finishes <5min, shared setup
  <15% of wall-time, and the live-trading breaker pauses/sheds the sweep (own pool, not the 3 UI slots). *(NFR-005, FR-032)*
- **AC-039a (largest-N sweep budget + reject — R4-F6-batch4: the tool admits `n` up to 5000 but only 100/500 were
  budgeted; the 1000–5000 range had no latency/RSS budget and no sweep-level reject)** — GIVEN a sweep at the largest
  ADMITTED N (`MAX_SWEEP_COMBOS` **pinned = 2000**, R5-F5-batch5), WHEN it runs on the numba+ProcessPool lane, THEN it finishes within
  `sweep_wall(N) ≈ ceil(N/concurrency) × per-combo_wall`; AND GIVEN a requested `n` whose `predicted_sweep_wall_ms >
  budget(N)` **OR `n > MAX_SWEEP_COMBOS` (e.g. `n=2001`)**, WHEN preflight evaluates it, THEN it is REJECTED pre-slot with the structured
  4xx contract (like AC-018) — NOT admitted and left to run ~50min unbounded. **The tool's `le` is lowered to 2000 so
  schema + estimator agree on the hard ceiling; the test asserts `n=2000` admits (when the host fits budget) and
  `n=2001` rejects (R5-F5-batch5).** *(NFR-005, FR-031/032; P6; R4-F6-batch4, R5-F5-batch5)*
- **AC-039b (interactive sweep on REALISTIC canonical-class combos — R4-F7-batch5: AC-016/024b/039 all benchmark the
  toy 14d×10sym≈40k-candle SWEEP combo fixture, but §D's "parameter sweeps become interactive" deliverable describes
  the real optimize_config/propose workflow that sweeps real AutoTradeConfigs over the canonical run-class
  (90d×50sym≈1.296M candles) — ~32× heavier per combo; a sweep "interactive" on 40k-candle combos but minutes-per-combo
  on real ones passes every gate while failing the deliverable)** — GIVEN a small-but-REALISTIC sweep (≥10 combos over
  the **canonical run-class 90d×50sym**, NOT the 14d×10sym toy fixture), WHEN it runs on the **numba + ProcessPool
  lane**, THEN it finishes within a concrete wall budget (`ceil(10/concurrency) × canonical-per-combo numba wall`);
  AND the **no-numba lane** carries the explicit relaxed-ceiling expectation for the same combo size (the "interactive"
  claim is gated against realistically-sized combos, not only the toy fixture). **canonical-per-combo numba wall
  PINNED (R6-F5-batch2 — the per-combo wall was never pinned anywhere (grep confirms only formula usages), so
  the budget self-normalized to whatever was measured at test time — the exact anti-pattern the spec rejects for the
  150k floor ("a floor derived from the very run it gates cannot catch a regression"); the standalone canonical numba
  E2E is <10s (Q.1) but a sweep combo REUSES the shipped-once SoA snapshot and SKIPS per-combo load/build/persist, so
  the standalone <10s is NOT the per-combo wall):** the canonical-per-combo numba wall is pinned to
  **≤4s = engine-only HEAVY+LIGHT time (canonical numba ≈3s) + per-combo IPC overhead (≤~1s), EXCLUDING the one-shot
  shared SoA setup** (which NFR-005 already caps at <15% of sweep wall-time), captured from the P4 profiled slice and
  FROZEN; AC-039b evaluates `ceil(10/concurrency) × 4s` as a fixed pass/fail threshold so a per-combo regression is
  catchable. PROVISIONAL until the P4 profile lands (like the ≥5M numba tripwire), re-derived from the measured
  per-combo wall then. *(NFR-005, FR-031/032, §D; P6; R4-F7-batch5, R6-F5-batch2)*

### U.7 — Cross-cutting (all phases)

- **AC-040** — GIVEN `BACKTEST_SAFE_MODE` set (ENV/file OR `bt_flag_config`), WHEN engaged — even with Postgres
  DOWN — THEN **the FIVE BOOLEAN accel gates (`BT_USE_NUMBA`, `BT_USE_COLUMNAR`, `BT_USE_FASTPATH`,
  `BT_PARALLEL_SWEEP`, `BT_DERIVE_COARSE`) resolve effective-off in one op (R5-F4-batch4 — the prior "all 6 accel
  flags effective-off" was semantically undefined: `BT_COLUMNAR_DIR` is a PATH, not a boolean gate, so it has no
  "effective-off" state; the kill-switch's gating set is the 5 boolean accel flags, and `BT_COLUMNAR_DIR` is
  configuration)**, in-flight accel runs/sweeps abort within a
  bounded wall-clock, new seal writes halt, and the backfill drains; a failed `bt_flag_config` read resolves to
  last-known-good/ENV-default, NEVER more-permissive. **Kill-switch reproduction scope (CORRECTED):** "the
  kill-switch reproduces the golden master in one lever" is TRUE for the **accel layer** — `SAFE_MODE` ⇒ the **P3
  pure-Python SoA engine + Postgres-read + sequential + native-coarse** path, which equals the golden master
  byte-for-byte. It is NOT a runtime lever back to *pre-feature* behavior: **P1 (sealed manifest) and P3 (SoA
  re-architecture) ship UNFLAGGED**, so reverting THOSE is redeploy + restore-point, not a flag — EXCEPT that the two
  added per-path flags (`BT_CACHE_SEALED_MANIFEST`/`BT_ENGINE_SOA`) give P1/P3 their own runtime fallback. *(FR-044/046, U-cross; R5-F4-batch4)*
- **AC-041** — GIVEN **the authoritative canonical drill-OFF frozen fingerprint AS RESOLVED BY AC-001 (the
  90d×50sym fixture, OR the 30d×20sym representative fallback fixture when AC-001's 6h capture ceiling trips —
  R5-F3-batch4/R5-F3-batch5: AC-041 must NOT hard-code 90d×50sym, because AC-001's R4-F6-batch4 fallback explicitly
  DOWNGRADES the 90d×50sym fingerprint to a best-effort/offline artifact "NOT a merge prerequisite" and PROMOTES the
  30d×20sym fixture to the authoritative DISCRETE+MONEY fingerprint; a per-phase merge gate hard-coded to the demoted
  artifact would be contradictory/unsatisfiable when the fallback fires)**, WHEN measured at each phase P0–P6, THEN
  **the DISCRETE fingerprint is byte-identical across P0–P6, and the MONEY fingerprint is byte-identical within
  P0–P2 (Decimal), re-frozen as float64 at P3, and byte-identical P3–P6 (cross-era money within
  `continuous-money-epsilon`) — NOT a single byte-hash over money across the P2→P3 pivot (R2-F1-batch5)** (no phase
  buys a speedup by changing results) AND the run finishes within its budget: **the
  CANONICAL class meets the ≤60s (≤50% of the 120s cap) target; HEAVY/HEAVIEST meet their ≤90s latency budget; WIDE
  meets its numba-lane latency only (pure-Python WIDE is RSS/stream/preflight-governed with no latency commitment and
  is rejected pre-slot if infeasible — R2-F1-batch4) — and EVERY class stays under the universal 120s hard kill**
  (never raised). The ≤60s target binds only the
  canonical class, never the HEAVY pure-Python ≤90s lane. **The fingerprint identity CHOSEN at P0 (full 90d×50sym vs
  the 30d×20sym fallback) is the SAME identity gated at EVERY later phase, version-tracked in the manifest
  (R5-F3-batch4).** *(NFR-008, Q.1, AC-001; §I.0a; R5-F3-batch4/F3-batch5)*
- **AC-042** — GIVEN concurrent timeout-kill + natural-finish + `POST /cancel` (and `queued→running` vs
  `queued→cancelled`), WHEN they race, THEN exactly one terminal state is written, no invalid transition, no
  double-start, no stuck `queued` row, and the slot + reservation release exactly once. **(Scope: this AC covers the
  LIVE in-process race only; the CRASH/RESTART-orphan path — a `running`/`queued` row left by a dead process
  generation — is NOT covered here and is gated by AC-048a, R3-F1-batch1/R3-F4-batch3.)** *(FR-039)*
- **AC-043** — GIVEN the GET result contract, WHEN any phase ships, THEN `metrics.total_trades` + **the full frozen
  `metrics_keys.json` set (exact names + types, nested objects expanded — not "~45")** are present + correctly typed,
  the equity-curve manifest hashes the full pre-downsample JSONB while the GET view preserves the max-DD trough, the
  GET-result `status` only ever emits the legacy five wire values (queued/interrupted_by_restart mapped per FR-052),
  **an UNKNOWN `close_reason` (`mr_target`) on `GET /backtest/{id}/trades` renders with a safe generic display and is
  never dropped/blanked / never throws a formatter (R5-F6-batch5)**,
  and old↔new bidirectional deploy-order both render. *(FR-037/052, L.1/L.2/L.5; R5-F6-batch5)*
- **AC-044** — GIVEN the always-on `event_loop_lag_ms` SLI, WHEN the **worst-case shared-host load runs**, THEN the
  gauge stays under
  **its pinned bound (`event_loop_lag_ms` p99 ≤ 250 ms / ≤5× idle baseline; `live_scanner_fetch_latency_p95` ≤ 20 %
  over baseline during the DDL/backfill/CIC windows — R.5/R2-F4-batch4)** (live auto-trade coroutines are not starved).
  **LANE-EXPLICIT worst case (R4-F1-batch5 — W-3 runs backtests in a ThreadPoolExecutor INSIDE the shared FastAPI
  process; a pure-Python engine pass HOLDS THE GIL, so 3 concurrent pure-Python backtest threads + the asyncio event
  loop all contend for ONE GIL, and the cited FR-049 global compute-thread semaphore only caps NATIVE pools
  (NUMBA_NUM_THREADS/BLAS/OMP/DuckDB) + numba `prange` — it does NOTHING for GIL contention in Python bytecode; the
  numba lane is fine because the FR-031/M.4 `nogil=True` kernel releases the GIL, but the no-numba host (V-1/D5) is
  exactly where this AC's 3-concurrent worst case would starve live order placement, V-6):** the **3-concurrent +
  sweep worst case is CAPABILITY-GATED to the nogil/numba lane** (where the kernel releases the GIL). On the
  **pure-Python lane (`HAS_NUMBA` false)**, concurrent backtests are **capped to 1** in the shared event-loop process
  (OR pure-Python backtests run in a SEPARATE process, not the shared event-loop process) — **this cap is the
  EFFECTIVE `_MAX_CONCURRENT` resolution pinned in AC-048b (R6-F6-batch4): on the no-numba shared-process host
  `_MAX_CONCURRENT` resolves to 1 and queue-drain promotes at most 1, so the admission model (default `=3`) and this
  GIL cap no longer collide**; a dedicated AC clause
  measures `event_loop_lag_ms` p99 under that pure-Python cap. The semaphore (FR-049)
  partitions the CPU budget across all active slots + the sweep so nested NATIVE parallelism never oversubscribes
  the host, but the GIL bound is enforced by the lane-explicit concurrency cap, NOT the native-pool semaphore.
  AC-044's pass condition is thus falsifiable on the D5 no-numba host. *(NFR-013, FR-049, R.5; R4-F1-batch5)*
- **AC-045** — GIVEN a flag flipped in `bt_flag_config`, WHEN the next run executes on a second (simulated)
  instance, THEN it honors the flip WITHOUT restart, and re-enabling a flag re-runs the per-tier health self-check
  before serving. *(FR-045)*
- **AC-046 (shared-breaker per-caller-class isolation — R2-F2-batch1)** — GIVEN the single shared Bybit breaker
  (`backend/mcp/core/breaker.py`) wrapped by both the backtest cold-fill path and the live scanner/auto-trade/
  reconciler path, WHEN a backtest-origin 429/timeout storm drives the **backtest** sub-state to OPEN, THEN a
  concurrent **live** Bybit call STILL PROCEEDS (the live sub-state is not opened by backtest-origin failures) — and,
  conversely, only live-origin consecutive failures open the live sub-state. A test asserts (a) the kline path + the
  MCP path share one breaker OBJECT (same id) AND (b) a backtest-triggered OPEN does not gate a live call. *(O.4, FR-026, NFR-021)*
- **AC-047 (`bt_flag_config` write-surface lockdown — R2-F1-batch1)** — GIVEN the DB-backed flag/SAFE_MODE control
  table, WHEN any public HTTP route or MCP tool attempts to WRITE `bt_flag_config` (including setting SAFE_MODE off),
  THEN it is REJECTED — writes succeed ONLY from the operator boundary (CLI/loopback/authenticated-admin, same as
  `MaintenanceAdmin`); the resolver + §K.2 status route hold read-only handles; `bt_flag_audit` is detective-only.
  *(FR-044/045, P.9, REQ-SEC-007)*
- **AC-047a (shadow / dark-compare mode — R5-F2-batch5: FR-047 had NO gating AC and no dedicated named test — the §Y
  ROLL row bundled it as "FR-044/045/046/047 → AC-040/045" but AC-040 is the SAFE-MODE kill-switch and AC-045 is
  flag-flip-honored-next-run, NEITHER exercises any shadow/dark-compare behavior, and T.10 never mentions shadow mode,
  so FR-047 was an orphaned FR mapped to a phase via a bundling artifact that does not cover it, violating Z-1/Z-3)**
  — GIVEN read-path shadow enabled, WHEN a deliberately-divergent columnar byte is injected, THEN the divergence is
  LOGGED **and authoritative Postgres is returned** (read-path never serves the divergent columnar byte); AND GIVEN
  engine-shadow on a small synthetic config with a SEEDED divergence, WHEN both engines run, THEN the **localized
  divergence payload (trade-ordinal / symbol / field / magnitude, size-capped)** is emitted AND the **optimized
  result is persisted** (shadow is persistence-neutral — it does not change what is stored); AND GIVEN dark-mode
  (flags off), WHEN a run completes, THEN the **v58 fingerprint columns populate** while the run stays
  **oracle-identical** (dark-mode adds provenance without changing results). Disabling shadow removes all
  dual-execution cost. A dedicated named test is added to T.10 and cited from the §Y ROLL/OBS rows so FR-047 is no
  longer bundled-but-uncovered. *(FR-047, REQ-ROLL-016, REQ-OBS-046, REQ-FE-012; P5/cross; R5-F2-batch5)*
- **AC-048a (boot-time crash-orphan reclamation — R3-F1-batch1/R3-F4-batch3, the `interrupted_by_restart` writer)** —
  GIVEN a `backtest_runs` row left `status='running'` (or `'queued'`) by a prior process generation that crashed/
  restarted (in-memory `Timer`/`Event` gone, DB row stale), WHEN `RunReaper` (M.14) runs at `BacktestService`
  lifespan startup AFTER `schema_version=58` is confirmed, THEN every such orphan is CAS-transitioned to
  `interrupted_by_restart` (→ terminal wire `failed`, FR-052) so the verified FE (`isPending`) **stops polling**,
  the `_MAX_CONCURRENT` slot + `AdmissionAccountant` reservation are released exactly once per row, and a second boot
  is a no-op (idempotent). On the single-worker target every boot-time `running`/`queued` row is reclaimed; on
  [FLEET] only provably-dead-generation rows are. *(FR-039/FR-052, M.14; cross)*
- **AC-048b (queue-drain promotion on slot release — R3-F5-batch3)** — GIVEN `_MAX_CONCURRENT=3` slots full and N
  `queued` creates waiting, WHEN one in-flight run reaches any terminal state and releases its slot, THEN the
  terminal writer's release path (or `AdmissionAccountant`) **promotes exactly one** queued run to `running` under a
  **pinned FIFO ordering** (oldest `queued_at` first) — no starvation (a waiting run is eventually promoted without
  a new external `POST`), no double-promote (two terminals freeing concurrently promote two distinct runs, never the
  same one twice), and the `queued→running` CAS arms the 120s clock. **EFFECTIVE slot count on the pure-Python lane
  PINNED (R6-F6-batch4 — unreconciled concurrency on the PRIMARY target: AC-044 caps concurrent backtests to 1 on the
  `HAS_NUMBA`-false lane to bound GIL-induced `event_loop_lag`, but the admission model keeps `_MAX_CONCURRENT=3` and
  promotes queued runs up to 3 slots; on the W-3 single-host Windows 11 deployment — also the host most likely to lack
  a numba wheel per V-1 — these collide: does the slot count drop to 1, or do 3 slots admit-then-serialize on the
  GIL?):** the EFFECTIVE concurrency RESOLVES on `HAS_NUMBA` — when `HAS_NUMBA` is **false** AND pure-Python backtests
  run IN the shared event-loop process, **`_MAX_CONCURRENT` resolves to 1** and AC-048b's queue-drain promotes **at
  most 1** (the other slots stay closed); when pure-Python backtests are dispatched to a **separate process** (the
  alternative AC-044 permits), the 3-slot model holds because the GIL is not shared with the event loop. The resolved
  effective slot count is recorded in the run manifest (`effective_max_concurrent`), and a falsifiable clause asserts
  that on a no-numba shared-process host a 2nd concurrent admission is QUEUED (not promoted) until the 1 slot frees.
  *(FR-039, J.1, AC-044, V-1; cross; R6-F6-batch4)*
- **AC-048c (atomic 3-write persistence rollback + GET torn-persist guard — R3-F6-batch3/R3-F4-batch5/R3-F6-batch5)** —
  GIVEN the three result writes (results + trades `COPY` + equity_curve JSONB) commit in ONE `conn.transaction()`,
  WHEN a fault is injected between each pair of writes, THEN **all three roll back**, the run is **NOT** marked
  `completed`, and a re-run is clean (no partial row served); AND GIVEN a deliberately torn/duplicated/dropped/
  sign-flipped persisted trade, WHEN `GET /backtest/{id}` runs the read-side guard, THEN it returns the **structured
  integrity error** (the structural discrete check catches the dropped/duplicated/sign-flipped trade even when its
  money delta is under the `continuous-money-epsilon`; `Σ(trade.pnl)≠net_profit` also trips) — never a silently-wrong
  render and never the no-trades fallback. *(FR-038, NFR-009, L.1; cross)*
- **AC-048d (aggregate-RSS admission, not just per-run — R3-F7-batch3)** — GIVEN the single shared host (W-3) and the
  per-run preflight that rejects a SINGLE run exceeding the klines budget (AC-018), WHEN admitting a new run or sweep
  would make `Σ(reserved per-run predicted peak RSS) + sweep-pool footprint > BT_RSS_BUDGET`, THEN
  `AdmissionAccountant` **queues or rejects it pre-slot** (the 4xx/queue contract), so 3 concurrent canonical runs +
  a sweep never collectively breach `BT_RSS_BUDGET` **by admission** — the runtime RSS watchdog (NFR-012) is the
  backstop, NOT the primary control. *(NFR-012/013, FR-049, V-6; cross)*
- **AC-048e (cross-process sweep cancel under SAFE_MODE / POST-cancel — R3-F6-batch3)** — GIVEN an in-flight sweep
  running combos in a `spawn` ProcessPool (prod Windows-11 path), WHEN SAFE_MODE engages or the sweep is cancelled,
  THEN the abort reaches the child PROCESSES via a **cross-process mechanism (pool `terminate()` and/or a per-worker
  cancel flag in `shared_memory`) — NOT the parent's `threading.Event`, which a child process cannot observe** —
  completing within the bounded wall-clock (NOT waiting out 120s/combo) AND leaving **no leaked `shared_memory`
  segments** (Windows last-handle-close cleanup on forced terminate, tied to the AC-019 terminal-path cleanup
  contract). *(FR-044, FR-031, NFR-018, AC-019; cross)*
- **AC-048f (forming-day snapshot coherency — R4-F1-batch5)** — GIVEN a to-present window that needs the forming UTC
  day across the engine main series + the 3 aux series (B&H, btc_vol, MR-mean), WHEN a live-scanner forming-day
  `kline_cache` upsert is interleaved BETWEEN the engine load and EACH aux load (T.6a), THEN every consumer reads
  IDENTICAL forming-bar OHLCV from the single SoA-build-time forming-day buffer (no torn cross-read), the streamed/
  cursor multi-batch read is internally coherent under `repeatable_read`, and the forming-day capture transaction
  commits immediately (no long-held snapshot pinning `xmin` across the ≤120s run, no pool exhaustion). *(FR-012, T.6a; cross; R4-F1-batch5)*
- **AC-048g (B&H BTC baseline excluded from Σ even when BTC/USDT is traded — R4-F4-batch5: T.5 runs three-way
  reconciliation on every fixture, but if NO fixture both TRADES BTC/USDT AND computes the BTC B&H baseline, the exact
  double-count collision FR-012 calls out is never exercised)** — GIVEN a fixture that **TRADES BTC/USDT while the BTC
  B&H baseline is active**, WHEN the three-way reconciliation runs, THEN `Σ trade.pnl == net_profit == final_equity −
  starting_capital` holds with the **B&H BTC series EXCLUDED** from the Σ AND the real BTC/USDT trade(s) **included
  exactly once** (the B&H series neither leaks into Σ nor double-counts the real BTC trade). *(FR-012, NFR-009, T.5; cross; R4-F4-batch5)*
- **AC-048h (queue depth bound + wait-timeout — R4-F8-batch3)** — GIVEN `_MAX_CONCURRENT` slots full and the
  admission queue, WHEN a `POST /backtest` arrives that would push queue depth past `BT_QUEUE_MAX_DEPTH` (pinned
  default **16**, R5-F6-batch1), THEN it is
  REJECTED pre-slot with the K.3 `{status:'rejected', reason:'queue_full'}` 4xx/503 contract (no row admitted, no slot
  taken); AND GIVEN a run sitting `queued` past `BT_QUEUE_WAIT_TIMEOUT_MS` (pinned default **120000** ms) while no slot frees, WHEN the wait timeout
  fires, THEN the run transitions to a terminal `queued_timeout` disposition (returning the `{status:'queued_timeout'}`
  contract), its `AdmissionAccountant` reservation is released exactly once, and its terminal status maps to a legacy
  wire value (FR-052) so the FE stops polling. **The threshold is falsifiable against the pinned default (a request at
  depth `limit+1` rejects, at the limit admits — R5-F6-batch1).** *(FR-039, FR-040, FR-052, K.3; cross; R4-F8-batch3, R5-F6-batch1)*
- **AC-048k (non-spoofable rate-limit/admission identity under header rotation — R5-F2-batch1)** — GIVEN one
  untrusted kernel peer (no trusted-proxy allowlist configured) that floods `POST /backtest-cache/warmup` and
  `POST /backtest` while ROTATING `X-Forwarded-For`/`X-Real-IP`/`Forwarded` values to mint distinct apparent clients,
  WHEN the per-client rate limit + warmup scope ceiling + `BT_QUEUE_MAX_DEPTH` evaluate the requests, THEN all three
  bounds STILL BIND as ONE identity (the W-12 kernel-peer key, header ignored), so `bybit_kline_calls` stays bounded
  and `event_loop_lag_ms` stays under its NFR-013/R.5 bound; AND GIVEN an operator-configured trusted-proxy allowlist,
  the LAST untrusted hop is used as the identity. *(FR-039, J.3, W-12, REQ-SEC-005, NFR-021; cross; R5-F2-batch1)*
- **AC-048i (progress-emission + warmup-collapse + metrics single-pass — R4-F3-batch4 (REQ-PERF-035 is a MUST,
  user-facing: live progress bar / responsiveness) + R4-F5-batch5 (NFR-006 sub-claims had NO Given/When/Then AC and
  the §Y PERF row mapped only to T.8/AC-024/024a/027, none of which exercise first-signal latency, progress-write
  count vs candle count, the P1 `_WARMUP_BAND` collapse, or the metrics single-pass property — a must-level
  product-visible requirement untestable as written, and a regression to O(n²) drawdown rescan or per-candle progress
  writes would fail no AC))** — GIVEN a backtest run, THEN: **(a)** the FIRST progress signal fires **<1s after run
  start** (bounded wall-time, independent of candle count); **(b)** total progress writes stay **O(100) regardless of
  candle count** (a candle-count-doubling test keeps the progress-write statement count flat) at **<2% overhead**;
  **(c)** the P1 cache-fix collapses the **`_WARMUP_BAND` (10%) stage to a small bounded constant** independent of
  pre-window history (a history-lengthening test keeps the warmup stage flat, no longer history-proportional); **(d)**
  metrics compute is **O(curve+trades) single-pass** — a curve-DOUBLING micro-gate stays ≤~2× (NO O(n²) drawdown/
  run-up rescan). Named tests added to T.8 (PERF anchor) and wired into the §Y PERF/OBS row. *(NFR-006, REQ-PERF-035/032/017/020; cross; R4-F3-batch4, R4-F5-batch5)*
- **AC-048j (future-dated / inverted / wholly-future date_range disposition — R4-F5-batch5: S.15's disposition was an
  unresolved OR and promised a gating AC that did not exist)** — GIVEN each of {future-dated end, `start ≥ end`,
  wholly-future window (empty after frontier-clamp)}, WHEN submitted, THEN the PINNED disposition is a **structured
  422** (the K.3 reject contract, NOT a completed zero-trade row / FE no-trades trap) returned **identically on BOTH
  the HTTP and MCP surfaces**, AND **no future day is probed or sealed** (`bybit_kline_calls == 0` for future days).
  The empty-oracle `total_trades=0` alternative is NOT used. *(S.15, FR-023, K.3; cross; R4-F5-batch5)*
- **AC-048l (partial-telemetry persistence on the in-process 120s kill / cancel / degrade — R6-F2-batch3: FR-041
  mandates that "on a 120s kill/cancel/degrade, partial timings + counters + flag/SHA fingerprint are still emitted +
  persisted with the terminal reason + aborted stage" (also R.1), but NO §U AC exercised it — AC-048a (RunReaper)
  writes partial `stage_timings`/fingerprint only on the CRASH/restart-orphan path, NOT the normal in-process 120s
  Timer kill; AC-042 asserts exactly-one terminal-state arbitration but NOT partial-telemetry persistence; the §Y OBS
  row mapped FR-041 only to "R.2 counters, R.5 loop-lag, T.9, AC-044/047a", none of which injects a timeout-kill and
  asserts the partial persist — so a regression dropping `stage_timings`/`engine_fingerprint` on a 120s kill (losing
  the post-kill forensics R.1/V-10 rely on to re-target P4) would fail no test; the same uncovered-MUST class that
  earned AC-048a/AC-048c/AC-048i their dedicated gates)** — GIVEN a run hard-killed at the 120s `threading.Timer` (AND
  separately a `POST /backtest/{id}/cancel`, AND a mid-run degrade), WHEN it terminates, THEN `backtest_runs.stage_timings`
  + `engine_fingerprint` (flag/SHA) + `terminal_reason` + the aborted-stage marker are **persisted** with
  `Σ(exclusive) == elapsed-until-failure ± tol`, AND the cache counters (`bybit_kline_calls`, `kline_tier_hits`, …)
  emitted so far **survive** (not reset to zero); a meta-test that drops `stage_timings`/`engine_fingerprint` on the
  kill path turns RED. *(FR-041, R.1, R.2; cross; R6-F2-batch3)*

---

## V. Risks

| ID | Risk | Likelihood / Impact | Mitigation |
|----|------|---------------------|------------|
| **V-1 (D5)** | **numba on Python 3.14.3 + numpy 2.4.4 is bleeding-edge** — numba 0.65.1/llvmlite 0.47.0 may not have wheels / may ABI-break | Med / High | numba is OPTIONAL (P4–P6 flagged); **P3 alone must hit "minutes" pure-Python**; import-guarded with pure-Python fallback of record; floors+ceilings; CI prebuilt-wheel matrix on every target incl. windows-latest; ABI-mismatch disables JIT + falls back *(REQ-DEP, S.14)* |
| **V-2** | **A frontend breaking-change via a dropped/renamed metrics key** routes completed runs to the "no trades simulated" fallback | Med / High | `metrics.total_trades` + ~45-key contract test; additive-nullable-only rule; degenerate run returns `total_trades=0`; bidirectional deploy-order tests *(FR-037, L.1)* |
| **V-3** | **Migration version-int collision** (happened twice on parallel branches) or multi-statement `;`-split | Med / High | Claim next free int + coordinate; **callable** migration (no `;`-split); CI migration-version re-verification per merge; restored-prod-clone rehearsal *(NFR-014)* |
| **V-4** | **New-dep import crash takes down the shared live FastAPI process** | Low / Critical | Deps in the optional `accel` extra (NEVER base); `HAS_*` import guards; missing wheel degrades, never crashes; live path imports no accel *(FR-048/049)* |
| **V-5** | **A parity-silent change** (e.g. once-per-tick basket recompute when legacy was per-symbol-candle, LTTB dropping the trough, float ULP false-positive on the reconciliation guard) | Med / High | P0 cadence-evidence step BEFORE freezing the oracle; trough-preservation fixture; lane-dependent reconciliation tolerance + high-trade-count false-positive test; golden-master diff gates every phase *(FR-018/052, NFR-009)* |
| **V-6** | **A sweep OOMs or starves live order placement** on the shared process | Low / High | Pre-flight rejects a WIDE run before a slot; runtime RSS watchdog aborts before OOM; live breaker = parent dispatch gate (sweep pauses/sheds, own pool, cgroup caps); always-on loop-lag SLI *(NFR-012, FR-032)* |
| **V-7** | **A false negative-cache permanently strands real data** (legacy-bug interior hole sealed-empty forever; wrong/empty lifecycle) | Low / High | Ambiguous-hole one-shot post-frontier reverify (WARM until settled); NULL lifecycle ⇒ fetch-everything (never auto-seal-empty); failed/429/timeout never seals *(FR-022/024/026)* |
| **V-8** | **A PITR/restore serves stale derived bytes** against a rewound SOR | Low / High | SOR-wide generation token embedded in every artifact; boot DB-identity hook + MANDATORY sampled-integrity backstop; PITR re-stamp re-derives coarse exactly once *(NFR-016)* |
| **V-9** | **Cold-fetch of a never-seen long range exceeds the 120s cap** (the reject-then-warm UX gap) | Med / Med | `ensure_coverage`/`warmup` named as the cold-fetch surface with semaphore-bounded fan-out + committed throughput budget; PreflightEstimator reject-then-warm; outer per-symbol-month chunk loop *(O.1/O.2, FR-039)* |
| **V-10** | **Magnitudes are estimates, not profiled** (~300×, "1–2 orders of magnitude" from analogous benchmarks) | Med / Med | Per-stage timers profile after P3 to re-target P4; wall-clock budgets are the hard gate, evals/s a post-P3-calibrated tripwire; ≥100× asserted vs the actual frozen P0 baseline *(R.1, NFR-002/003)* |
| **V-11** | **A win32 dev/CI host lacks `spawn` ProcessPool** while prod uses it | Low / Low | Pinned (not auto-degraded) fallback: ThreadPool-over-nogil on win32 dev/CI, ProcessPool+shared_memory on prod; a test asserts the correct selection per host *(FR-031, AC-019)* |
| **V-12** | **A v58 `ADD COLUMN` ACCESS EXCLUSIVE races the live scanner's continuous `_update_coverage`** | Low / Med | Bounded `lock_timeout` + in-boot retry + submission-quiesce DRAIN window; `CREATE INDEX CONCURRENTLY` out-of-band; sub-second DDL *(NFR-014)* |

---

## W. Assumptions

- **W-1** — Stored `scan_results` (Postgres) are the immutable signal source of record; the engine never
  re-analyzes. A reproduce/retry that finds pruned scan_source signals reports "unavailable" rather than silently
  diverging. *(§2 actors, REQ-PAR-045)*
- **W-2** — `trading_rules.py` is the SSOT for sizing/TP/SL/slippage/liq/fees/trailing/breakeven and is **not
  changed** by this feature; the numba kernel re-implements its math identically (proven by the differential
  harness), confined to the backtest path. *(NFR-023, FR-049)*
- **W-3** — The PRIMARY deployment target is a **single-host Windows 11** process running the live FastAPI app +
  the backtest engine in a threadpool (single-worker constraint for the backtest-bearing process). A [FLEET]
  multi-worker variant, if deployed, uses mmap/shared-memory hot tiers + cgroup-aggregate RSS evaluation. *(§2.0, FR via §7.3/§7.4)*
- **W-4** — The 120s `_TIMEOUT_SECONDS` cap MAY be raised but is NEVER relied upon as a target; every benchmarked
  run finishes at ≤50% of it. *(Q.1)*
- **W-5** — Postgres is the system-of-record for all kline + result rows; Parquet/Feather/Arrow are never the SOR
  (sealing depends only on the PG SOR; materialization is best-effort). *(FR-034)*
- **W-6** — `numpy 2.4.4` is present (transitive via pandas); the SoA build uses it. The accel stack
  (`numba/llvmlite/pyarrow/duckdb`) is the only net-new dependency set and is optional. *(discovery §10)*
- **W-7** — The shared Bybit circuit breaker `backend/mcp/core/breaker.py` exists and is reused (not
  reimplemented); a priority/quota layer keeps backtest cold-fill below live access. *(O.4)*
- **W-8** — The existing per-`(symbol,interval,date)` `kline_cache_coverage` table (with a pre-existing
  `fetched_at`) is the correct seal grain; v58 adds columns there, not on `backtest_runs`. *(N.1)*
- **W-9** — UTC-only time handling is correct on the Windows host (zero naive-local/DST leakage); API/MCP
  `date_range_*` are normalized to UTC before window-bounding. *(FR-023)*
- **W-10** — `regime_staleness_minutes` is live-only and N/A in backtest (backtest builds a fresh ScanContext per
  scan_time) — accepted for parity. *(discovery §8)*
- **W-10a — Real-trading-vs-backtest accuracy is INHERITED, not validated by this feature (R6-F3-batch4).** This is a
  performance + storage refactor under a HARD zero-business-logic-change constraint (§A): it changes NO trading
  decision, sizing, barrier, fee, or fill rule. Therefore the "<1% deviation" goal (§D) is scoped to parity with the
  **legacy backtest oracle** (golden-master bit-identity + three-way Σ reconciliation), and the accuracy of the
  backtest engine RELATIVE TO REAL/LIVE FILLS is INHERITED unchanged from the pre-feature engine and is OUT OF SCOPE
  here. No AC validates backtested trades against recorded live fills; if such validation is ever desired it is a
  SEPARATE feature (a sample reconciliation of backtested trades vs recorded live fills). *(§D, §A; R6-F3-batch4)*
- **W-11 — Reverse-proxy topology + authoritative trust signal (R5-F1-batch1).** The PRIMARY single-host W-3
  deployment MAY front the FastAPI app with a **co-located (same-host) reverse proxy** (nginx/IIS/Caddy on
  loopback) terminating external traffic — a common Windows-11 posture. Because such a proxy makes the kernel
  peer of EVERY forwarded request `127.0.0.1`, kernel-peer-loopback ALONE is NOT a trustworthy
  privilege signal under this topology. The **authoritative trust signal for the privileged
  `/backtest-runtime/status` payload is therefore the explicit auth token by default**; kernel-peer-loopback is
  honored as sufficient ONLY when an operator has affirmatively set `BT_STATUS_TRUST_PEER_LOOPBACK=true` on a
  deployment they have verified has NO loopback-terminating proxy in front (e.g. the app binds the public port
  directly). The same per-client rate-limit/admission identity (§K.1/K.3, W-12) is likewise NOT derived from a
  forwarding header unless an operator-configured trusted-proxy allowlist is present. *(K.2, P.6, REQ-SEC-005)*
- **W-12 — Rate-limit / admission client-identity key (R5-F2-batch1).** The client-identity key used by every
  per-client DoS bound this feature introduces (the `POST /backtest`, `POST /backtest-cache/warmup`, and
  `GET /backtest-runtime/status` rate limits; the warmup scope ceiling; and `BT_QUEUE_MAX_DEPTH`'s
  cross-client queue bound) is pinned to a **non-spoofable signal**: the authenticated principal/API-key when
  present, ELSE the **kernel peer socket address** — NEVER a raw forwarding header. A forwarding header
  (`X-Forwarded-For`/`X-Real-IP`/`Forwarded`) is honored as the identity ONLY behind an operator-configured
  **trusted-proxy allowlist** (validate the proxy hop, take the LAST untrusted hop); absent that allowlist the
  header is ignored for identity. *(K.1, K.3, J.3, FR-039)*

---

## X. Open Questions (resolved with recommended defaults — autonomous mode)

> This is an autonomous pipeline; each open question is resolved here with a default + rationale so the plan can
> proceed. A reviewer may override any resolution at the Step 5 gate.

- **X-1 — Basket-equity recompute cadence (the parity-critical unknown).** **RESOLVED:** freeze **once-per-tick
  over the open book** as the oracle, BUT gated by the P0 cadence-evidence step (AC-004) that reads the legacy code
  and cites the proving line FIRST. If legacy proves per-symbol-candle, resolve before P3 (do not silently rewrite).
  *Rationale: the headline symbol-scaling speedup + REQ-ENG-032 rest on this; verify, don't assume.* *(FR-018)*
- **X-2 — `<10s` drill-off budget feasibility on pure-Python.** **RESOLVED:** lane-split — `<10s` drill-off /
  `<20s` drill-on are **numba-lane** MUST budgets; the pure-Python lane is `≤60s` canonical / `≤90s`
  HEAVY/HEAVIEST. *Rationale: pure-Python is ~43–60s; the lane-split makes the MUST achievable + D5 numba-optional
  intact.* **Estimate↔floor reconciliation (R3-F2/F3-batch2 — the "~43–60s" pure-Python estimate, the 1.43M blended
  eval count, and an unprofiled ≥100k/s floor cannot all hold; if 43–60s is real the BLENDED rate is ~24–33k/s, below
  100k/s):** the floor is restated as a **≥150k HEAVY-evals/s** rate on the `ticks×B` denominator (architecture
  §11.1) — a HEAVY-only basis is consistent with a 43–60s E2E wall that is dominated by the ~1.296M LIGHT advances +
  load/build/persist, NOT the 0.13M HEAVY evals. **LIGHT-advance/s reconciled to ONE pinned figure (R6-F2-batch2 — the
  prior text let §I.0a's "~43–60s dominated by LIGHT" be misread as a ~27–33k/s LIGHT rate (1.296M ÷ ~45s) while
  NFR-001/AC-018 computed the WIDE reject term at ~100k LIGHT-advance/s — a ~3–4× discrepancy that swings the AC-018
  WIDE reject point from ~210s to ~780s and the canonical load/build headroom from ~12s to comfortable):** the ~45s
  wall is NOT LIGHT-only — it is `LIGHT + load + SoA-build + HEAVY + metrics + persist`. At the pinned **≥100k
  LIGHT-advance/s (≤10 µs/advance, NFR-004/R6-F1-batch2)** the LIGHT term alone is ~1.296M ÷ 100k ≈ **~13s**, and the
  remaining ~30–47s is load/build/HEAVY/persist; "dominated by LIGHT" means LIGHT is the **largest single engine term**
  (10× the HEAVY count), NOT that the whole wall is LIGHT. So ≥100k LIGHT-advance/s and a 43–60s E2E wall are
  CONSISTENT, and the AC-018 WIDE reject term (~21M ÷ 100k ≈ 210s) and the canonical headroom are both re-derived from
  this ONE pinned rate. The exact pure-Python floor value is **re-pinned from a profiled
  P0/early-P3 engine slice** (the architecture's post-P3 fraction-of-measured-rate protocol), and the "engine floor
  is strictly stronger than the E2E wall" claim is corrected (different scopes — §I-preamble/NFR-003).**
  The lane split + committed pure-Python budgets are pinned by the spec-introduced `REQ-PERF-046`
  (§I.0a, amends REQ-PERF-001) — NOT a non-existent "REQ-PERF-001 lane-split amendment", and NOT REQ-PERF-039
  (which governs only WIDE-run OOM streaming/rejection). The 120s `_TIMEOUT_SECONDS` hard kill is universal and
  never raised; `≤90s` HEAVY is a documented latency-budget exception still `< 120s`.** *(NFR-001, Q.1, REQ-PERF-046; §I.0a)*
- **X-3 — How tight are typical strategy stops (decides P-effort split, drill `p→1`)?** **RESOLVED (default):**
  assume **moderate** stops → the conditional drill pre-filter is a large win + lazy per-symbol LTF loading is the
  dominant drill cost; PROFILE after P3 (the per-stage timers) to confirm + re-target. If `p→1` (very tight), the
  per-bar pre-filter saves little and lazy LTF dominates — handled by the linear-in-drilled-bars budget. *(FR-028, V-10)*
- **X-4 — `BT_COLUMNAR_DIR` persistence (warm-rerun <5s vs cold-build).** **RESOLVED:** on the PRIMARY single-host
  target it is a **persistent local volume** (the <5s cross-process warm budget is in force); an ephemeral/[FLEET]
  deploy waives <5s to the cold-build budget — stated per deploy. *(AC-033, Q.3)*
- **X-5 — Bulk `public.bybit.com` archive ingest.** **RESOLVED:** **OUT OF SCOPE by default** (REST only); ships
  only behind a flag WITH the full untrusted-ingress guard set, else not built. *(O.7, G.3)*
- **X-6 — Multi-worker uvicorn for the backtest process.** **RESOLVED:** **single-worker** (option a) on the
  PRIMARY target (RSS watchdog is per-process == whole-host); [FLEET] multi-worker requires mmap/shared-memory hot
  tiers + cgroup-aggregate RSS. *(W-3, §7.3)*
- **X-7 — `pg_control_*` grant absent under least-privilege Postgres.** **RESOLVED:** default **fail-loud (a)** —
  refuse + name the missing privilege (`BT_PITR_DETECTOR=require`); `backstop_only` is an explicit opt-in that
  falls back observably to the sampled backstop + flags `pitr_primary_detector=degraded`; a degraded detector may
  serve READS but NEVER authorizes a destructive seal. *(P.5, NFR-016)*
- **X-8 — Status-route auth.** **RESOLVED:** the public route stays **unauthenticated but coarsened** (booleans +
  states only) **and per-client rate-limited**; precise values go to loopback/CLI, where "loopback/privileged" is
  determined SOLELY by the **kernel peer socket address or an explicit auth token — NEVER a forwarding header**
  (`X-Forwarded-For` cannot promote to the precise payload), so the disclosure control is not spoofable behind the
  reverse proxy (R2-F8). If an auth substrate is later introduced for `MaintenanceAdmin`,
  the route MAY become auth-gated + serve the precise payload. *(K.2, P.6, R2-F8)*
- **X-9 — DuckDB vs Polars as the columnar reader.** **RESOLVED:** **DuckDB** is the primary read engine (locked
  down per P.3); the flag-combination support matrix enumerates the CI-exercised reader; the all-supported-equal
  baseline (pure-Python + Postgres + sequential + native-coarse) is the equality target. *(FR-046, P.3)*
- **X-10 — `nautilus_trader` cross-validation oracle.** **RESOLVED:** **deferred / off critical path** — a later
  optional second-opinion oracle on a sample, never gating a phase. *(G.3)*

---

## Y. Traceability Matrix (REQ category → FR/NFR → phase → test)

| REQ category | Count | FR / NFR | Phase | Anchor test (§T) |
|--------------|-------|----------|-------|-------------------|
| **PAR** — Parity-Correctness | 45 | FR-001..014, **FR-007 (liquidation pnl identity = −locked_margin−entry_fee−funding_paid→AC-002, R4-F1-batch4)**, **FR-009 (skip_if_positions_open latch→T.2a/AC-006a, R3-F2-batch5)**, **FR-010 (funding granularity-invariance + neg-rate inversion→T.3b/AC-006d, R4-F3-batch5)**, **FR-011 (fill_to_max_trades relaxed pass→T.2b/AC-006c, R4-F1-batch4)**, **FR-011a (REQ-PAR-026 adaptive-blacklist incremental==recompute→T.3a/AC-006b, R3-F3-batch5/6; REQ-PAR-030 regime-active)**, **FR-012 (forming-day snapshot coherency→T.6a/AC-048f; B&H-BTC-traded Σ exclusion→AC-048g, R4-F1-batch5/F4-batch5)**, **REQ-PAR-039 batched-load byte-identity→AC-014a (R3-F7-batch6)**, NFR-007/008/009/010/011 | P0 (gates all) | T.1/T.2/**T.2a**/**T.2b**/T.3/**T.3a**/**T.3b**/T.4/T.5/**T.6a**/T.8, AC-002/006a/006b/006c/006d/014a/048f/048g |
| **CACHE** — Cache | 50 | FR-019..026, **FR-023 (monotonic frontier ratchet backward-clock-step→AC-009a/T.6, R4-F3-batch6)**, **N.1b (REQ-CACHE-045 symbol+interval canonicalization across all keying surfaces incl. int-code map)**, **REQ-CACHE-010 (idx_coverage_unsealed EXPLAIN-uses-index + size-independence→N.4, R5-F7-batch2)**, **sweep-level zero-exchange→AC-007c (R6-F5-batch4)**, O.1..O.4 | P1 | T.6 (sealed-once, tri-source sha, **backward-clock-step**), N.1b canonicalization test, **N.4 EXPLAIN/scaling test (REQ-CACHE-010)**, AC-009a, **AC-007c (sweep `bybit_kline_calls==0`)** |
| **ENG** — Engine | 34 | FR-015..018, NFR-003/004, **T.8 micro-gates (REQ-ENG-011 trailing O(P); REQ-ENG-013 barrier-derived-once)** | P3/P4 | T.7 (boundary-equiv, scaling microbench), T.8 (ENG micro-gates) |
| **STORE** — Storage | 45 | FR-025/033 (**forming-day excluded from hot tiers→AC-031a, R4-F3-batch5**)/034/035, N.1/**N.1a (REQ-STORE-040 OHLCV float64 round-trip)**/**N.1c (REQ-STORE-040 open_time TIMESTAMPTZ→int64-ms DERIVED, R5-F1-batch2)**/N.3/**N.5 (REQ-STORE-042/043 write-side growth/bloat/retention + equity_curve budget, R5-F8-batch2)**, **REQ-STORE-027 (materialized flips post-seal→post-seal-mutability contract, R5-F5-batch2)**, NFR-011/019 | P1/P2/P3/P5 | T.6/T.8 (tier-latency), **T.6 TIMESTAMPTZ→int64-ms derivation (R5-F1)**, **N.5d sustained-churn (R5-F8)**, AC-031/**031a**..034 |
| **DRILL** — Drilldown | 23 | FR-028/029/030, O.6, **S.16 (fallback precedence)**, **REQ-DRILL-022 entry-bar-spans-barrier→AC-015c/T.4c (R6-F2-batch1)** | P0/P2/P3 | T.4 (two-sided sandwich), **T.4c (entry-bar drill)**, AC-015/015a (FR-030 sandwich) / AC-015b (FR-028 memo+linear) / **AC-015c (REQ-DRILL-022 entry-bar)** |
| **SWEEP** — Sweep | 19 | FR-031 (**ProcessPool decoupled from HAS_NUMBA, R4-F3-batch5**)/032, NFR-005 (**largest-N reject + canonical-class budget, R4-F6/F7-batch4/5**), **sweep-level zero-exchange→AC-007c (R6-F5-batch4)** | P2 (parallelism) / P3-P4 (abs budget) / P6 | AC-016 (P2 parallelism + capability waiver), AC-017 (combo==standalone parity), AC-024b/039/**039a/039b** (abs budget + largest-N + canonical-class), **AC-007c (aggregate `bybit_kline_calls==0`)** |
| **PERF** — Performance | 45 (+REQ-PERF-046 backported, counted separately) | NFR-001..006/012/013/024, **NFR-003 (150k fixed pre-profiling / 5M calibrated tripwire, REQ-PERF-005 backport R4-F2/F6-batch4/5)**, **NFR-006 progress/warmup/single-pass→AC-048i (R4-F3/F5-batch4/5)**, **NFR-024 estimator basis + margin=1.0 + WIDE/drill scoping (R4-F4-batch4/5, R4-F2/F8-batch4)**, **REQ-PERF-046 (§I.0a lane split — now backported into requirements.md per R2-F5-batch3)**, Q.* | cross / P3-P6 | T.8 (benchmark + cold-start + REQ-PERF-043 sub-gates + GET-cache + **progress/warmup/single-pass micro-gates**), AC-018/024/024a/027/**048i** |
| **MIG** — Migration | 43 | FR-050/051, N.2/N.4, NFR-014/015/016, **REQ-MIG-007/008 (PK + wrong-type fail-loud pre-checks→AC-008a, R5-F2-batch3)**, **REQ-MIG-009/010 (symbol_lifecycle DDL + override-precedence→N.2, R5-F3-batch2)**, **REQ-MIG-028 (advisory-lock direct/non-pooled session-pinned conn→N.4, R5-F4-batch3)**, **REQ-MIG-034 (post-backfill ANALYZE/EXPLAIN-uses-index→N.4, R5-F5-batch3)**, **REQ-MIG-035 (partition pre-flight + default-reconcile→N.4, R5-F7-batch3)**, **REQ-MIG-040 (fresh-DB 0→58 equivalence + CREATE-before-INSERT→AC-012, R5-F6-batch3)** | P1 | T.10 sub-tests (NAMED, R5-F3-batch3): **AC-008a** wrong-PK + wrong-typed-column refusal; **AC-012** decouple/atomic-rollback/idempotent-ZERO-DDL-second-run + fresh-DB 0→58 + CREATE-before-INSERT ordering; override-survives-refresh + readiness-before-population (REQ-MIG-010); pooling-mode session-pinned lock (REQ-MIG-028); post-backfill EXPLAIN-uses-index (REQ-MIG-034); partition-gap-refusal + default-reconciliation (REQ-MIG-035); gate-before-relax (REQ-MIG-038); in-place-edit checksum (REQ-MIG-002); restored-prod-clone rehearsal |
| **DEP** — Dependencies | 32 | FR-048/049, P.1 | P4/P5 | T.10 (module-absent, wheel matrix), AC-028..030 |
| **ROLL** — Rollback | 34 | FR-044/045/046 (**+P1 `BT_CACHE_SEALED_MANIFEST` / P3 `BT_ENGINE_SOA` flags; 7-boolean gating set, BT_COLUMNAR_DIR is config not a gate, R5-F4-batch4**)/**047 (shadow/dark-compare→AC-047a, R5-F2-batch5)**, M.13 | cross | T.10 (SAFE_MODE, flag-flip, **shadow/dark-compare**), AC-040/045/**047a** |
| **OBS** — Observability | 49 | FR-040/**041 (partial-telemetry persist on 120s kill→AC-048l, R6-F2-batch3)**/042/043, **FR-047 shadow/dark-compare→AC-047a (R5-F2-batch5)**, **AC-044 lane-explicit GIL bound (pure-Python concurrency cap, R4-F1-batch5)**, R.* | cross | R.2 counters, R.5 loop-lag, T.9, **T.10 shadow/dark-compare**, AC-044/**047a**/**048l (kill-path partial telemetry)** |
| **TEST** — Testing | 44 | T.1..T.10 (all), M.7 | P0 (gates all) | the suite itself + teeth meta-tests |
| **API** — API-Lifecycle | 24 | FR-036 (**9 real routes, R3-F1-batch6; REAL page/limit/sort_by OFFSET trades contract, R4-F2-batch4**)/038 (**atomic-3-write→AC-048c**)/039 (**queue-drain→AC-048b; crash-orphan reclaim→M.14/AC-048a; Idempotency-Key single-flight + queue depth/timeout→AC-048h, R4-F3/F8-batch4/3**)/040 (**+MCP reject shape; +queue_full/queued_timeout**), K.* | cross | T.9 (envelope, race, reject-shape, status-route, **9-route enum, OFFSET pagination schema**), AC-042/048a/048b/048c/**048h/048j** |
| **CFG** — Config-Surface | 14 | FR-011/**FR-011a**, **REQ-CFG-013 (infra-flags-absent + config_hash byte-identity)**, **FR-032 PROPOSED-config preserves user `drilldown_enabled` (R3-F11-batch3)**, §E config surface | cross | T.3 (per-filter-step, no-op branch), T.9 (infra-flags-absent snapshot), AC-017 (proposed-drill preserved) |
| **FE** — Frontend-Compat | 16 | FR-037 (**required-core/optional keys + null-only sentinels + trades_keys/summary_keys two-tier, R3-F9-batch2/3, R3-F5-batch5, R6-F4-batch5**)/052 (**LTTB trough+peak, R6-F4-batch4**), L.1/L.4 (**null-only**)/L.5 | cross | T.9 (contract, frozen-key-set, **trades/summary keys two-tier**, status-wire-map, bidirectional, **trough+peak**, null-render) |
| **SEC** — Security (**originate in architecture §8.7, NOT requirements.md — see §A.1**) | 7 (6 in-scope + 1 deferred) | **SEC-001→P.2/NFR-019; SEC-002→P.3/NFR-020; SEC-003→DEFERRED-with-bulk-archive (R5-F4); SEC-004→P.4/NFR-021; SEC-005→K.2/P.6/NFR-021; SEC-006→P.5/NFR-021; SEC-007→P.9/FR-051** | cross / P5 (SEC-003: deferred) | **per-control:** SEC-001→T.10-junction; SEC-002→T.10-injection; **SEC-003→T.10-archive (DEFERRED, runs only when the bulk-archive flag feature lands, R5-F4)**; SEC-004→T.10 worker-env-subset + R5-F5 negative-secret; SEC-005→T.9 spoofed-XFF + AC-048k identity; SEC-006→T.10 wrong-DB + missing-grant; SEC-007→AC-047 flag-write-lockdown |
| **TOTAL** | **517 + 7 SEC** | FR-001..052 (+FR-011a), NFR-001..024 | **P0–P6** | §T battery |

**Orphan check:** all 15 requirement categories (PAR 45, CACHE 50, ENG 34, STORE 45, DRILL 23, SWEEP 19, PERF 45,
MIG 43, DEP 32, ROLL 34, OBS 49, TEST 44, API 24, CFG 14, FE 16 = **517**) plus the 7 REQ-SEC controls map to
at least one FR/NFR with a named test + a phase. **REQ-SEC-001..007 originate in architecture §8.7 (NOT
`backtest-optimization-requirements.md`) — they are carried here as a named-but-externally-sourced category per
§A.1; the "+7 SEC" total is kept distinct from the 517 for exactly this reason.** **SEC per-control mapping is now
ONE ROW PER CONTROL to its REAL section + specific test (R5-F3-batch1 — the prior single collapsed `T.10 (junction,
injection, fail-closed)` cell mis-homed REQ-SEC-003 (O.7/P.1, OUTSIDE P.2..P.6) and REQ-SEC-007 (P.9/FR-051,
gated by AC-047) and omitted the per-control AC anchors, so the Z-3 orphan-check passed spuriously for SEC): the
Z-3 meta-test asserts all 7 SEC controls trace to a section IN THEIR REAL RANGE plus a SPECIFIC named test/AC — NOT
a single collapsed T.10 cell — and that REQ-SEC-003 is explicitly recorded DEFERRED-with-bulk-archive (so a
deferred control is auditable as deferred, not silently dropped).** The previously-orphaned must-items
now have concrete anchors: REQ-CACHE-045→N.1b, REQ-STORE-040→N.1a, REQ-PAR-026→FR-011a, REQ-PAR-030→T.3 regime-axes,
REQ-CFG-013→T.9 infra-flags snapshot, REQ-ENG-011/013→T.8 micro-gates, REQ-PERF-034/040/043→T.8. Cross-cutting
categories are owned by named FRs/NFRs, not left implicit. **Per-phase coverage (R4-F2-batch4 — P0 was previously
enumerated TWICE with conflicting members ("P0 {AC-001..006}" AND "P0 {AC-001..006 + AC-006a/006b}"), making the
authoritative map self-contradictory for the traceability meta-test (Z-2); the incomplete first entry is DELETED so
each phase appears EXACTLY ONCE with its complete AC set):** P0 {AC-001..006 + AC-004a + AC-006a/006b/006c/006d}, P1
{AC-007..013 + AC-007a/007b/**007c** + AC-008a + AC-009a}, P2 {AC-014,014a,015,015a,015b,015c,016,017,**018-RSS** (RSS/aggregate-RSS reject only — AC-048d),019}, P3 {AC-020..025 + AC-024a/024b + **018-wall** (predicted-wall-time reject + canonical/HEAVY/HEAVIEST no-false-reject ADMIT assertions, R6-F4-batch1) + AC-006a/006b/006c/006d (path-dependent latch battery RE-RUN against the float64 master)}, P4 {AC-026..030 + AC-026a + AC-028a + AC-006a/006b/006c/006d (latch battery re-run against the numba kernel)}, P5 {AC-031..036 + AC-031a + AC-011p}, P6
{AC-037..039 + AC-037a + AC-039a/039b}, cross {AC-040..047 + AC-047a + AC-048a/048b/048c/048d/048e/048f/048g/048h/048i/048j/048k/048l}. **A meta-test asserts NO
phase key is enumerated more than once in this map (R4-F2-batch4), in addition to the Z-2 membership assertion.**
**Path-dependent latch battery re-gated at the rewrite phases (R5-F2-batch4 — the highest-risk "HOW changes WHAT"
fixtures (T.2a skip_if_positions_open, T.2b fill_to_max_trades, T.3a adaptive-blacklist, T.3b funding-granularity)
were tagged P0-only, but the P3 SoA pointer/`searchsorted`/once-per-tick rewrite and the P4 numba merge are exactly
where a path-dependent latch can be silently perturbed; the P3 merge gate AC-020 + the AC-041 canonical fingerprint
both use the DEFAULT config with these latches OFF, so no enumerated P3/P4 AC re-ran the latch battery): AC-006a/006b/006c/006d
are now members of BOTH the P3 and P4 phase-sets, so the SoA and numba merge gates re-assert the latch fixtures
against the float64/numba master rather than only the default-config canonical fingerprint. AC-006b's prior `P0/P3`
self-tag is now RECONCILED with its phase-set membership (it appears in P0, P3, AND P4).** **"Golden-master diff gates
every later phase" CLARIFIED (R5-F2-batch4): T.1's per-phase gate means the WHOLE fixture battery (the T.2/T.2a/T.2b/
T.3/T.3a/T.3b close-rule + latch fixtures, not only the canonical discrete+money fingerprint) RE-RUNS at each phase
P3–P6 against that phase's re-frozen master; the canonical fingerprint (AC-041) is the ADDITIONAL full-scale gate,
not a substitute for the battery.**
**(AC-017 RESTORED — sweep-combo==standalone parity gate, R2-F2-batch5/
R2-F3-batch5; AC-015a/015b added for FR-030/FR-028 gates, R2-F10-batch2/R2-F5-batch5; AC-007a for post-v58 lazy-seal,
R2-F2-batch2; AC-046 breaker isolation, R2-F2-batch1; AC-047 flag-config write lockdown, R2-F1-batch1. R3 batch6 ADDED:
AC-006a skip_if_positions_open (R3-F2-batch5), AC-006b adaptive-blacklist incremental==recompute (R3-F3-batch5/6),
AC-007b lazy-seal latency bound (R3-F5-batch3), AC-011p P5 Parquet sha leg (R3-F3-batch1), AC-014a batched-load
byte-identity (R3-F7-batch6), AC-028a accel-failure+fallback<120s (R3-F3-batch4), AC-048a crash-orphan reclaim
(R3-F1-batch1/F4-batch3), AC-048b queue-drain promotion (R3-F5-batch3), AC-048c atomic-3-write rollback
(R3-F6-batch3/F4-batch5/F6-batch5), AC-048d aggregate-RSS admission (R3-F7-batch3), AC-048e cross-process sweep
cancel (R3-F6-batch3).)**

---

## Z. Definition of Ready

This spec is READY for Step 5 (Spec Review) and onward to planning when ALL hold:

- [x] **Z-1** — Every FR/NFR is testable, names an owning component, cites anchor REQ-IDs, and carries a phase tag.
- [x] **Z-2** — Every phase P0–P6 has explicit Given/When/Then acceptance criteria (§U) that gate its merge. **AC
  numbering is non-contiguous-but-complete (sub-lettered AC-006a/006b/007a/007b/011p/014a/015a/015b/024a/024b/028a/037a
  + restored AC-017 + cross AC-046/047/048a/048b/048c/048d/048e); the §Y per-phase map enumerates the actual set per
  phase, so the traceability meta-test asserts
  membership of the enumerated set, NOT a contiguous integer range.**
- [x] **Z-3** — All 15 requirement categories (517) + 7 REQ-SEC controls **+ the backported REQ-PERF-046 amendment**
  trace to an FR/NFR + a named test + a
  phase (§Y orphan check passes).
- [x] **Z-4** — The Prime Directive invariants (5m no-drill bit-identity, <1% drill/portfolio + non-optimistic,
  three-way Σ reconciliation, sealed-once, NO-OP guarantee, `total_trades` present, core-file semantic parity, 120s
  cap, `max_same_sector` no-op, derived-coarse == native-coarse, `Σtrade.pnl == final_equity − starting_capital`)
  are each pinned to an enforcement point (FR/NFR/AC).
- [x] **Z-5** — All hard constraints are addressed: 7-phase rollout (G/§U), <1% parity / golden bit-identical on
  5m no-drill (NFR-007), 120s cap (Q.1), `metrics.total_trades` never disappears (FR-037), v58
  callable+idempotent (NFR-014), numba/pyarrow/duckdb import-guarded with pure-Python fallback (FR-048), do NOT fix
  `max_same_sector` (FR-011), `Σtrade.pnl == final_equity − starting_capital` (NFR-009).
- [x] **Z-6** — Real files / config fields / line-refs referenced throughout (core files, `_TIMEOUT_SECONDS:770`,
  `BacktestResultsPage.tsx:255`, `_PAGE_SIZE:19`, `_evaluate_candles_until`, v58 / `_MIGRATIONS`, etc.).
- [x] **Z-7** — Open questions (§X) are resolved with recommended defaults (autonomous mode); a reviewer may
  override at the Step 5 gate.
- [x] **Z-8** — Risks (§V) incl. the numba-on-Py3.14 D5 risk (V-1) each carry a mitigation.
- [ ] **Z-9** — Spec Review (Step 5) gate: minimum 10 adversarial rounds × 5 agents (or 2 consecutive clean rounds
  early) — **PENDING** (next step).

---

*End of specification. Next: Step 5 (Spec Review gate) per `/new-feature` — 5 agents × ≥10 rounds, then Step 6
(implementation plan). This document is the requirements contract; the plan elaborates per-phase build order +
TDD task breakdown against the FR/NFR/AC IDs above.*
