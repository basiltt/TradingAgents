# Implementation Plan: Backtest Performance Optimization

## A. Title & Metadata

| Field | Value |
|-------|-------|
| **Feature** | Backtest Performance Optimization (multi-hour → seconds-to-minutes, TradingView-class, parity-locked) |
| **Plan file** | `plans/backtest-performance/implementation-plan.md` |
| **Skill** | `/new-feature` (`~/.claude/skills/new-feature/SKILL.md`) — Step 6 (plan) + Step 7 (plan review) |
| **Created** | 2026-06-10 |
| **Status** | DRAFT — pending Step 7 plan review |
| **Spec** | `specs/backtest-optimization-spec.md` (A–Z; 52 FR + 24 NFR + 45+ AC; per-phase U.0–U.7) |
| **Architecture** | `specs/backtest-optimization-architecture.md` (ADR-001..005; components §3.1–3.12; coverage map) |
| **Requirements** | `specs/backtest-optimization-requirements.md` (517 REQ-`<CAT>`-NNN across 15 categories) |
| **Findings** | `specs/backtest-optimization-findings.md` (RC-1..RC-N; build order P0→P6) |
| **Discovery** | `specs/backtest-optimization-discovery.md` (parity landmines) |
| **Tracker** | `plans/backtest-performance/progress-tracker.md` (VERIFIED FACTS N1–N4) |
| **Phases** | P0 (golden-master, gates all) → P1 (cache) → P2 (loaders/sweep) → P3 (SoA engine) → P4 (numba) → P5 (Parquet/DuckDB) → P6 (fast-path) |
| **Hard parity gate** | Golden-master diff after EVERY phase; bit-identical discrete fields on canonical 5m no-drill; revert any phase that breaks parity |
| **Baseline (N2)** | `pytest tests/backend -k "backtest or kline"` → **342 passed, 3 skipped, ~11s**; golden+engine subset 53 passed. Any phase below this = parity break = REVERT |
| **Universal hard cap** | 120s in-process `threading.Timer` kill — NEVER raised |

### A.1 Conventions

- **`[NEW]`** = net-new module; **`[MOD]`** = existing file changed under semantic parity; **`[UNCHANGED-CONTRACT]`** = behavior frozen, internals re-pointed.
- **TDD throughout (RED→GREEN→REFACTOR):** every TASK names its test file + test names; the test is written and made to fail for the right reason BEFORE the implementation.
- **Parity vocabulary:** *DISCRETE fields* = {trade count, opened set, sides, symbols, entry/exit bar indices, `close_reason`, ordering}; *MONEY* = pnl/fees/equity within `continuous-money-epsilon` (Decimal-exact P0–P2, float64-refrozen P3+).
- **Money-parity tolerance (pinned numeric — single source of truth):** `continuous-money-epsilon` / `REL_TOL` = **abs `1e-9` on equity/wallet AND rel `1e-7` on per-trade pnl** (assert `abs(a−b) <= 1e-9 + 1e-7*abs(b)`). The P0–P2 lane is **Decimal-exact (`==`)**; the float64 epsilon applies ONLY across the P2→P3 era pivot (TASK-306 re-freeze) and the P4 float64-vs-Decimal differential (TASK-402). DISCRETE fields are ALWAYS bit-identical (no tolerance). Referenced by TASK-001/002, AC-020/041, §D.4, §M.2, §S.1.
- **Eval unit (single source of truth):** an *eval* = one HEAVY position-pass = `ticks × B` (`heavy_eval_count`); canonical `ticks≈25,920`, `B≈5` ⇒ `heavy_eval_count≈0.13M`. LIGHT term = `total_candles` advances (`≈1.296M`). Throughput floors are HEAVY-evals/sec.
- **Verified facts** (firsthand, do not contradict): **N1** numba GO (267×) but import-guarded + pure-Python fallback; **N2** baseline 342/3 green; **N3** 3 Postgres integration tests skip headless (need `BACKTEST_TEST_DATABASE_URL`), engine/golden parity runs WITHOUT Postgres; **N4** `_MIGRATIONS` @ `backend/async_persistence.py` ~L1494–1523, max v57, v58 MUST be a CALLABLE.

---

## B. Planning Summary

### B.1 What this delivers

Make the crypto-futures backtester **TradingView-fast (multi-hour → seconds-to-minutes)** while changing **zero business logic** (<1% deviation; bit-identical discrete fields on the canonical 5m no-drill path). Two headline defects are killed: (1) the **O(scans × symbols × N_total) engine setup** with a quadratic-in-time seeding term (RC-1/RC-2), and (2) the **re-download-every-rerun cache bug** (false-positive coverage gaps, RC-3) plus the un-persisted 1m drill re-fetch.

### B.2 Strategy in one paragraph

A 7-phase, dependency-ordered, golden-master-gated rollout. **P0** freezes the CURRENT engine output as a stored-snapshot oracle (replacing the brittle magic-number `test_backtest_golden.py`) with a fixture battery covering every close-rule branch and adds the missing three-way `Σ trade.pnl == net_profit == final_equity − start` reconciliation. **P0 changes no production logic** — it is pure test scaffolding that gates P1–P6. **P1** fixes the cache with a sealed-day manifest (v58 migration). **P2** batches loaders + parallelizes sweeps + fixes drill-down. **P3** rewrites the engine data layout to structure-of-arrays + merge-walk (PURE PYTHON, must hit "minutes" alone). **P4** JITs the per-candle kernel with numba (import-guarded, pure-Python fallback of record). **P5** adds an immutable Parquet/DuckDB read layer. **P6** adds a vectorized barrier fast-path for provably-independent configs. Every phase ends with: full golden parity + the 342-baseline green + a phase commit. Parity is the hard gate; any phase that breaks it and cannot be fixed is reverted.

### B.3 Core files (semantic parity required)

`backend/services/backtest_engine.py` (1938 L), `backend/services/backtest_service.py` (1664 L), `backend/services/kline_cache_service.py` (559 L), `backend/services/backtest_metrics.py` (825 L), `backend/services/trading_rules.py` (SSOT — UNTOUCHED), `backend/mcp/tools/optimizer/sweep_tools.py` (293 L), `backend/async_persistence.py` (v58 migration).

### B.4 Hard constraints (apply to ALL phases)

1. Golden-master bit-identical (discrete) on canonical 5m no-drill; <1% on drill/portfolio; non-optimistic.
2. `Σ trade.pnl == net_profit == final_equity − starting_capital` on EVERY fixture (Decimal-exact P0–P2; epsilon P3+).
3. Liquidation identity: `trade.pnl == −locked_margin − entry_fee − funding_paid`, `exit_fee==0`; THIS participates in Σ.
4. Sealed closed day fetched exactly once across N reruns (mock client, `call_count==1`).
5. `metrics.total_trades` NEVER disappears (present-and-0 on degenerate runs).
6. numba / pyarrow / duckdb **import-guarded** (`HAS_NUMBA`/`HAS_PYARROW`/`HAS_DUCKDB`), pure-Python fallback; declared in `[project.optional-dependencies].accel` ONLY (never base deps).
7. Do **NOT** "fix" the intentional `max_same_sector` non-enforcement in the backtest (documented parity caveat D6).
8. NO breaking API changes: the 9 real routes keep signatures; new fields optional+nullable; one additive route only (`GET /backtest-runtime/status`).
9. v58 migration is a CALLABLE, additive-only, idempotent, sub-second; `CREATE INDEX CONCURRENTLY` is OUT-OF-BAND (illegal in the txn-wrapped migration runner).

### B.5 Open-question dispositions (from spec §X, autonomous defaults — already resolved, no blockers)

- **Cadence (AC-004):** a P0 DIFFERENTIAL test decides once-per-tick vs per-symbol-candle and freezes whichever is bit-identical to legacy; HEAVY budgets re-derived if per-symbol-candle.
- **Open-book depth B (AC-004a):** measured at P0/early-P3; if B>5 the §Q.2 pre-computed B-contingency table (B≈10/B≈15) supplies re-derived budgets.
- **P0 capture ceiling:** 6h wall-clock on the pinned host; fallback = 30d×20sym representative fixture promoted to authoritative DISCRETE+MONEY fingerprint; full 90d×50sym downgraded to best-effort.
- **numba (D5/N1):** GO, but every U.4 AC is capability-waived when `HAS_NUMBA` false; P3 pure-Python must hit "minutes" alone.

---

## C. Spec Reference (FR / NFR / REQ → phase)

This plan implements the spec **exactly**. The authoritative mappings live in §R (Traceability). Headline anchors:

### C.1 Functional Requirements by phase

| Phase | FR (spec §H) | Theme |
|-------|--------------|-------|
| **P0** | FR-001..FR-014 (H.1 parity/correctness, frozen semantics) | Golden-master oracle freezes the legacy engine's decisions |
| **P1** | FR-019..FR-026 (H.3 sealed-day cache) + FR-050/051 (H.10 backfill/lifecycle) | Kill the re-download (RC-3); v58 sealed manifest |
| **P2** | FR-027..FR-032 (H.4 loaders/drill/sweeps) + FR-039/040 (H.6 admission) | Batched `ANY($1)` loads; lazy drill; parallel sweeps; PreflightEstimator |
| **P3** | FR-015..FR-018 (H.2 data-layout rewrite) | SoA + global timeline + merge-walk pointers (parity-neutral) |
| **P4** | FR-013/016/018 + FR-048/049 (H.9 deps) | `@njit` kernel + pure-Python fallback of record; import guards |
| **P5** | FR-033..FR-035 (H.5 storage tiers) | Parquet/DuckDB read layer + Arrow hot cache + derive-coarse |
| **P6** | FR-013 (fast-path clause) + FR-031/032 | Vectorized barrier first-touch + prange/ProcessPool sweep |
| **cross** | FR-036/037/038/052 (API + frontend contract), FR-041/044..047 (obs/rollback) | Contract preserved; flags; SAFE_MODE; shadow/dark |

### C.2 Non-Functional Requirements (the measurable bars)

| NFR | Bar | Gate phase |
|-----|-----|-----------|
| NFR-001 | Canonical drill-OFF ≤60s / drill-ON ≤90s; HEAVY/HEAVIEST ≤90s; all `<120s` | P3 (pure-Python), re-asserted P4–P6 |
| NFR-002 | ≥100× vs frozen P0 engine-CPU baseline (numba lane, windows-latest, `accel_waived=false`) | P4 |
| NFR-003 | ≥150k HEAVY-evals/s pure-Python; ≥5M HEAVY-evals/s warmed-numba (0.7×-calibrated floor) | P3 / P4 |
| NFR-004 | Symbol-doubling ≤2×; LIGHT per-advance ≤10,000 ns (≥100k LIGHT-advance/s) | P3 |
| NFR-005 | Sweep speedup ≥0.7×min(M,K,concurrency) **on the numba+ProcessPool lane**; 100-combo <60s / 500-combo <5min (numba+ProcessPool lane). **No-numba host:** sweeps run SEQUENTIAL (the P2 engine is GIL-bound pure Python; ThreadPool-over-nogil yields ~zero speedup until the P4 `nogil=True` kernel exists) — the ≥0.7× floor is WAIVED-by-capability there, documented expectation = sequential | P2 (parallelism, numba lane) / P3+P6 (absolute) |
| NFR-006 | Batched loads O(1) round-trips; metrics O(curve+trades) single-pass; progress O(100) | P2 |
| NFR-007 | Cross-engine byte/discrete parity (SoA, numba, columnar, fast-path) | P3/P4/P5/P6 |
| NFR-008 | <1% per-trade + summary on drill/portfolio; two-sided sandwich (non-optimistic) | P2/P3 |
| NFR-009 | Three-way Σ reconciliation on every fixture | P0/cross |
| NFR-010 | NO-OP guarantee: empty instrument_info/scan_contexts/fine_klines + no regime ⇒ byte-identical to 5m path | P0/cross |
| NFR-012 | `BT_RSS_BUDGET` symbol-scaled (CANONICAL tier 1GB; WIDE/HEAVY tier 1.75GB; HEAVIEST tier 2GB); klines SoA ≤150MB; timeline its own line; reject at `> tier_budget/2` pre-slot | P2/P3 |
| NFR-013 | `event_loop_lag_ms` p99 ≤250ms / ≤5× idle; live scanner fetch p95 ≤20% over baseline (TASK-313 GREEN owner) | P3/cross |
| NFR-014/015 | v58 catalog-only sub-second, expand-only (zero destructive DDL) | P1 |
| NFR-016 | Sampled row-count/sha backstop catches cross-tier drift | P5 |
| NFR-017..024 | Reliability, security, observability, admission determinism | cross |

### C.3 REQ categories (517 total — full enumeration in §R)

`REQ-PAR-*` (parity), `REQ-ENG-*` (engine), `REQ-CACHE-*` / `REQ-STORE-*` (cache/storage), `REQ-DRILL-*` (drill-down), `REQ-SWEEP-*` (sweeps), `REQ-PERF-*` (performance), `REQ-MIG-*` (migration), `REQ-ROLL-*` (rollback), `REQ-OBS-*` (observability), `REQ-SEC-*` (security, 7 controls), `REQ-DEP-*` (dependencies), `REQ-API-*`, `REQ-FE-*` (frontend), `REQ-TEST-*` (testing), `REQ-CFG-*` (config).

---

## D. Implementation Strategy

### D.1 Dependency order (P0 gates ALL)

```
P0 (golden-master harness)  ── gates ──┐
   │ freezes legacy decisions          │
   ▼                                    │
P1 (cache: sealed manifest, v58)        │
   │ parity-neutral, ships UNFLAGGED    │
   ▼                                    │  every phase
P2 (batched loaders + parallel sweeps)  │  diffs against
   │ + PreflightEstimator + drill       │  the P0 oracle
   ▼                                    │  BEFORE it is
P3 (SoA + merge-walk engine) ◀──────────┤  trusted
   │ PURE PYTHON; hits "minutes" alone  │
   │ ships UNFLAGGED (BT_ENGINE_SOA esc)│
   ▼                                    │
P4 (numba JIT) ── import-guarded, flag ─┤
   ▼                                    │
P5 (Parquet/DuckDB) ── flag ────────────┤
   ▼                                    │
P6 (vectorized fast-path) ── flag ──────┘
```

**P0 is the gate.** No phase advances without re-running the P0 golden-master diff and the 342-baseline. The build order is non-negotiable (findings §8): the cache fix (P1) removes the dominant wall-clock cost; the SoA rewrite (P3) is the single biggest engine win and must land before numba (P4) so P4 is re-targeted from real P3 profile numbers.

### D.2 TDD discipline (per CLAUDE.md — non-negotiable)

Every TASK follows **RED → GREEN → REFACTOR**:
1. **RED:** write the named test(s) first; run; confirm they FAIL for the right reason (not an import error masking a logic gap).
2. **GREEN:** write the simplest production code to pass — no speculative abstraction (YAGNI).
3. **REFACTOR:** clean up only after green; re-run the phase's full test set + the golden diff after every refactor.

Parity-bearing phases (P3/P4/P6) additionally **develop pure-Python-first, diff against the P0 oracle on every fixture, THEN optimize/JIT** — never JIT-first.

### D.3 Parity gate mechanics (the hard stop)

After each phase's implementation:
1. Run `pytest tests/backend/test_backtest_golden.py tests/backend/test_backtest_engine.py -q` → must be GREEN (the P0 snapshot + battery).
2. Run the canonical DISCRETE fingerprint assertion (`test_golden_fingerprint.py::test_discrete_fingerprint_stable`) → byte-identical to the P0 freeze.
3. Run `pytest tests/backend -k "backtest or kline" -q` → **≥342 passed, ≤3 skipped** (N2 floor; new tests only ADD).
4. If any of 1–3 fails and cannot be fixed within the **3-fix rule → REVERT the phase** (feature flag off for P4–P6; `git revert` the phase commit for P1–P3) and record in the tracker.

> **3-fix rule (definition):** at most **3 fix attempts** per distinct parity break. If the DISCRETE fingerprint (or the 342-baseline, or the golden battery) is still red after the 3rd attempt, STOP fixing → REVERT the phase (flag-off for P4–P6; `git revert <phase-commit>` for P1–P3) → record the break, the 3 attempts, and the root-cause hypothesis in the tracker → re-attempt as a fresh phase. This bounds time-on-a-single-break on a live trading system. (Same trigger referenced in §O.2 and §S.1.)

### D.4 Per-phase exit checklist (every phase)

- [ ] All phase TASKs complete (tests written first, green).
- [ ] Golden-master DISCRETE fingerprint byte-identical; MONEY within epsilon (Decimal-exact P0–P2).
- [ ] 342-baseline still green (only additions).
- [ ] `npx tsc --noEmit` + `npm run build` green IF the phase touched frontend (only P0 contract-freeze + any FE-visible change; engine phases do not).
- [ ] Consolidated 5-agent convergence review (correctness / parity / security / perf / maintainability) — fix every valid C/H/M; stop at 2 rounds no new findings.
- [ ] Phase commit (conventional: `feat(backtest):` / `perf(backtest):` / `test(backtest):`); tracker updated.

### D.5 Compressed-ceremony note (deliberate deviation, tracker-authorized)

Per the autonomous mandate: per-phase review is ONE consolidated convergence pass (5 agents) + full TDD, not 28 separate gates. Rigor is preserved (every valid C/H/M fixed, parity diffed every phase); ceremony is compressed to fit the implementation window. This is recorded as an explicit deviation.

---

## E. Phase Breakdown

> One block per phase. Each: **Goal · Scope · Files · Tasks · Tests · Verification · Completion criteria · Dependencies · Risks**. Task detail (signatures, impl notes) is in §F; file actions in §G.

### E.0 — Phase P0: Golden-master parity harness (gates ALL phases)

**Goal.** Freeze the CURRENT (pre-optimization) engine output as a **stored-snapshot oracle** that every later phase diffs against. Replace the brittle magic-number `test_backtest_golden.py` with snapshot fixtures covering EVERY close-rule branch, and add the three-way `Σ` reconciliation the existing `_assert_reconciles` lacks. **This phase changes NO production logic** — pure test scaffolding.

**Scope.**
- IN: `GoldenMasterOracle` harness; per-close-rule fixture battery; canonical fixture capture (with 6h ceiling + 30d×20sym fallback); DISCRETE + MONEY fingerprint split; three-way Σ reconciliation; cadence-evidence differential (AC-004); open-book depth B measurement (AC-004a); NO-OP byte-identity fixture; degenerate `total_trades=0` fixture; the uncovered-P0-latch fixtures (`skip_if_positions_open`, `fill_to_max_trades`, adaptive-blacklist window, funding granularity).
- OUT: any change to `backtest_engine.py` decision logic (frozen); any optimization.

**Files.** `tests/backend/golden/` (new fixture dir), `tests/backend/test_backtest_golden.py` [MOD — replace magic numbers], `tests/backend/test_golden_fingerprint.py` [NEW], `tests/backend/conftest.py` [MOD — fixture helpers], `tests/backend/golden/snapshots/*.json` [NEW artifacts], `tests/backend/golden/metrics_keys.json` / `trades_keys.json` / `summary_keys.json` [NEW frozen key sets]. No `backend/` production file changes.

**Tasks.** TASK-001..TASK-014 (§F).

**Tests (TDD — these ARE the deliverable).** T.1 (stored-snapshot oracle), T.2 (close-rule battery + source-derived enum completeness), T.2a (`skip_if_positions_open`), T.2b (`fill_to_max_trades`), T.3a (adaptive-blacklist window), T.3b (funding granularity), T.4c (entry-bar drill), T.5 (three-way Σ + degenerate + liquidation-with-fees + B&H-collision), T.9 (contract snapshot — frozen key sets).

**Verification.**
```bash
# RED first: each fixture fails before its snapshot is captured/asserted.
python -m pytest tests/backend/test_backtest_golden.py tests/backend/test_golden_fingerprint.py -x -q
# Capture the canonical fingerprint OFFLINE (120s Timer disabled) — AC-001:
python -m pytest tests/backend/test_golden_fingerprint.py::test_capture_canonical -q  # writes snapshot artifact
# Full baseline must remain green (only additions):
python -m pytest tests/backend -k "backtest or kline" -q   # ≥342 passed, ≤3 skipped (N2)
```

**Completion criteria.**
- AC-001 (canonical snapshot + DISCRETE/MONEY fingerprint + engine-CPU baseline, with the **pre-estimate-selected fixture (30d×20sym DEFAULT; 90d×50sym only if the pre-estimate clears the 6h ceiling)** + **pre-seeded-cache `bybit_kline_calls==0` precondition** recorded in manifest), AC-002 (three-way Σ + liquidation carve-out), AC-003 (source-derived enum union-coverage + completeness meta-test), AC-004 (cadence differential pass/fail), AC-004a (B measured + B-contingency table), AC-005 (NO-OP byte-identity), AC-006 (degenerate `total_trades=0`), AC-006a/b/c/d (latch fixtures) ALL green.
- The existing `_assert_reconciles` is replaced by explicit three-way Σ; a meta-test removing one term turns RED.
- 342-baseline green.

**Dependencies.** None (first phase). Gates P1–P6.

**Risks.** (1) The uncapped legacy capture could run for hours (RC-1/RC-2 super-linear) — **mitigated** by a fast engine-CPU pre-estimate that picks the fixture UPFRONT (30d×20sym DEFAULT, NOT gambling up to 6h of the overnight window on the slow 90d×50sym path; 6h ceiling is the backstop) + pre-seeded cache so capture does ZERO Bybit fetches (AC-001, TASK-004). (2) Magic-number brittleness in the existing test — **mitigated** by snapshot-as-oracle (discovery §7). (3) Cadence/B assumptions baked into budgets — **mitigated** by the AC-004/AC-004a evidence gates + the §Q.2 pre-computed cadence-contingency + B tables BEFORE P3 freezes budgets.

---

### E.1 — Phase P1: Cache re-download fix

**Goal.** Kill RC-3 (re-download every rerun) and the un-persisted 1m drill re-fetch's coverage side. Introduce a **sealed-day manifest** (provenance + immutability) with a **completion frontier** `floor(now/T)*T` so a closed day is fetched **exactly once ever**. Ship the v58 callable migration. Parity-neutral; ships UNFLAGGED (with `BT_CACHE_SEALED_MANIFEST` escape hatch).

**Scope.**
- IN: `SealedManifest` + completion-frontier; day-class taxonomy; negative caching + `gap_ranges`; reverify-pending one-shot; read-path lazy-seal-from-SOR; count-free refetch; per-gap-run fetch (not min→max bracket); REST `_PAGE_SIZE` 200→1000 + outer chunk loop; `content_sha256` canonical hash; v58 migration (callable, additive, idempotent); out-of-band CIC index builds; `SealBackfillRunner` (deferred); `SymbolLifecycleRefresher`; shared-breaker per-caller-class isolation; monotonic-frontier ratchet.
- OUT: SoA engine (P3); columnar storage (P5); the actual 1m drill loader rewrite (P2 — only the coverage side is P1).

**Files.** `backend/services/sealed_manifest.py` [NEW], `backend/services/kline_cache_service.py` [MOD], `backend/services/seal_backfill_runner.py` [NEW], `backend/services/symbol_lifecycle_refresher.py` [NEW], `backend/services/maintenance_admin.py` [NEW — `ensure_indexes()` + `validate_partition_tree()`], `backend/async_persistence.py` [MOD — v58 callable `_add_sealed_manifest_columns` (coverage) + v59 callable `_add_backtest_control_objects` (`backtest_runs` cols + status-CHECK widen + flag/lifecycle/generation tables)], `backend/mcp/core/breaker.py` [MOD — per-caller-class sub-state], `backend/services/backtest_service.py` [MOD — lifespan boot wiring: RunReaper + forming-day capture], `backend/services/run_reaper.py` [NEW — crash-orphan reclaimer], `backend/services/capability_resolver.py` [NEW — `BT_CACHE_SEALED_MANIFEST` escape-hatch flag, extended P3/P4], `backend/routers/backtest.py` [MOD — cache status/warmup manifest-aware + warmup future/inverted/oversized 422 guard (TASK-118, B1-F9)]. Tests: `tests/backend/test_sealed_manifest.py` [NEW], `tests/backend/test_kline_cache_sealed.py` [NEW], `tests/backend/test_v58_migration.py` [NEW], `tests/backend/test_seal_backfill.py` [NEW], `tests/backend/test_breaker_isolation.py` [NEW], `tests/backend/test_capability_resolver.py` [NEW].

**Tasks.** TASK-100..TASK-118 (§F) — incl. TASK-106 (v58 coverage cols) + TASK-106b (v59 `backtest_runs` cols + status-CHECK widen + `bt_flag_config`/`bt_flag_audit`/`symbol_lifecycle`/`sor_data_generation`) + **TASK-215 status→wire-map serializer (SEQUENCED INTO P1, B1-F3 — hard predecessor of TASK-114; RunReaper persists `interrupted_by_restart` in P1, so the wire-map MUST be GREEN on all read surfaces in the SAME deploy)** + TASK-119 (deploy-quiesce before the v59 status-CHECK swap).

**Tests.** T.6 (sealed-once `call_count==1` + tri-source-bi-leg sha + interior-hole + backward-clock-step), T.6a (forming-day snapshot coherency — concurrency), T.10 (v58 decouple + atomic-rollback + idempotent + fail-loud pre-checks + CREATE-before-INSERT + index planner-choice).

**Verification.**
```bash
python -m pytest tests/backend/test_sealed_manifest.py tests/backend/test_kline_cache_sealed.py tests/backend/test_v58_migration.py tests/backend/test_seal_backfill.py tests/backend/test_breaker_isolation.py -x -q
# Headless (N3): v58 callable + sealed logic validated via mocks (call_count==1); Postgres-integration sub-tests skip without BACKTEST_TEST_DATABASE_URL.
python -m pytest tests/backend -k "backtest or kline" -q   # ≥342 + new, ≤3 skipped
# Golden parity MUST hold (P1 is byte-neutral on klines):
python -m pytest tests/backend/test_golden_fingerprint.py -q
```

**Completion criteria.** AC-007 (sealed rerun `bybit_kline_calls==0`, per-day `call_count==1`), AC-007a (post-v58 pre-backfill lazy-seal), AC-007b (lazy-seal latency bound), AC-007c (SWEEP-level zero exchange work), AC-008 (klines byte-identical; schema 58 sub-second), AC-008a (v58 fail-loud pre-checks), AC-009 (sealed-short not perpetual gap), AC-009a (backward-clock-step ratchet), AC-010 (reverify one-shot), AC-011 (bi-source sha @ P1), AC-012 (v58 callable + idempotent + atomic + fresh-DB 0→58 equivalence), AC-013 (backfill mutates only coverage/manifest), AC-046 (breaker isolation), AC-048a (RunReaper orphan reclaim), AC-048f (forming-day coherency) green. **Status-wire-map phase-gate (B1-F3): `test_no_read_surface_emits_nonlegacy_status` GREEN — RunReaper persists `interrupted_by_restart` in P1, so TASK-215's serializer maps it (and any persisted literal) to a legacy-5 wire value on GET/LIST/MCP IN THIS phase; no read surface emits a non-legacy status literal.** Golden DISCRETE fingerprint unchanged.

**Dependencies.** P0 (oracle gates the parity diff). Migration claims the next free ints after v57 = **v58** (sealed-manifest coverage cols) + **v59** (`backtest_runs` control objects) (N4).

**Risks.** (1) v58 multi-statement DDL split on `;` → use a CALLABLE (N4, hard rule). (2) `CREATE INDEX CONCURRENTLY` illegal in the txn-wrapped runner → OUT-OF-BAND via `MaintenanceAdmin.ensure_indexes()` post-boot. (3) Postgres integration tests skip headless (N3) → validate via mocks; flag DB-only checks in the morning report. (4) Backward clock step could reopen RC-3 → monotonic `frontier = max(prev, computed)` ratchet (AC-009a).

---

### E.2 — Phase P2: Batched loaders + parallel sweeps + drill-down

**Goal.** Remove the N+1 load (1 batched `ANY($1)` query), parallelize sweeps (ProcessPool + `shared_memory`, capability-gated), and fix the 1m drill-down to be lazy + memoized + non-optimistic (no re-fetch on rerun). Add the `PreflightEstimator` admission gate (RSS term at P2). Parity-neutral.

**Scope.**
- IN: batched `_load_klines` (N+1→1, byte-identical buckets); batched `scan_source`/`ScanContext` load; `asyncio.gather` drill window prefetch; `DrilldownLoader` (lazy per-symbol 1m, per-bar fallback, in-process memo); `SweepRunner` (parallel combos, shipped-once shared inputs, `USE_PROCESS_POOL` predicate); `PreflightEstimator` + `AdmissionAccountant` (RSS + aggregate-RSS reject); `KlineStore` seam (Postgres-only tier at P2).
- OUT: the SoA compact snapshot (P3 — at P2 the pool shares legacy per-symbol kline lists); the wall-time reject term (P3); columnar tiers (P5).

**Files.** `backend/services/kline_store.py` [NEW — Postgres tier], `backend/services/drilldown_loader.py` [NEW], `backend/services/preflight_estimator.py` [NEW], `backend/mcp/tools/optimizer/sweep_runner.py` [NEW] + `sweep_tools.py` [MOD], `backend/services/backtest_service.py` [MOD — batched load + KlineStore seam + admission + `_build_fine_klines` drill PRODUCER (TASK-203) + `_downsample_equity` peak (TASK-216) + status→wire-map (TASK-215)], `backend/services/backtest_engine.py` [MOD — `_fine_klines` drill CONSUMER seam only, decisions frozen]. Tests: `tests/backend/test_batched_loaders.py` [NEW], `tests/backend/test_drilldown_loader.py` [NEW], `tests/backend/test_preflight_estimator.py` [NEW], `tests/backend/test_sweep_runner.py` [NEW].

**Tasks.** TASK-200..TASK-216 (§F) — incl. TASK-215 status→wire-map serializer (the GREEN owner for T.9) + TASK-216 `_downsample_equity` max-equity-peak force-include + **TASK-217 (partial-telemetry on 120s kill, AC-048l) + TASK-219 (`/backtest-runtime/status` route + privilege split) + TASK-220 (boundary symbol-charset gate; P5 path-containment) + TASK-220b (`bt_flag_config` write-surface lockdown)**.

**Tests.** T.3/T.7 (AC-014a batched byte-identity + duplicate-row parity), T.4 (differential float64-vs-Decimal + two-sided sandwich), T.4c (entry-bar drill), T.8 (sweep-combo==standalone parity row).

**Verification.**
```bash
python -m pytest tests/backend/test_batched_loaders.py tests/backend/test_drilldown_loader.py tests/backend/test_preflight_estimator.py tests/backend/test_sweep_runner.py -x -q
python -m pytest tests/backend/test_golden_fingerprint.py -q   # parity holds
python -m pytest tests/backend -k "backtest or kline" -q
```

**Completion criteria.** AC-014 (1 batched query, O(1) round-trips), AC-014a (byte-identical buckets + duplicate-row parity), AC-015 (drill on/off identical SELECTION, only fill PRICE differs — incl. full-book portfolio coverage, TASK-202/B4-F2), AC-015a (non-optimism + two-sided sandwich), AC-015b (drill rerun ZERO fetch + linear scaling), AC-015c (entry-bar drill), AC-016 (sweep speedup ≥0.7×min(M,K,concurrency)), AC-017 (sweep-combo==standalone, drill-off-coerced), AC-018-RSS (RSS reject gate at P2), AC-019 (host-capability predicate + Windows `shared_memory` cleanup), AC-048c (atomic persist — DB-lane; UNVALIDATED-headless per §I.5), AC-048d (aggregate-RSS), AC-048e (cross-process sweep cancel), AC-048l (partial-telemetry on 120s kill/cancel/degrade, TASK-217), AC-044 (`effective_max_concurrent` in manifest, TASK-212), AC-047 (`bt_flag_config` write-lockdown, TASK-220b), AC-048k (admission identity incl. proxied-distinct, TASK-214/219) green. **Status-wire-map phase-gate re-asserted (P2 first persists `queued`): no read surface emits a non-legacy status literal.** Golden parity holds.

**Dependencies.** P0 (oracle), P1 (sealed cache so sweeps do zero exchange work — AC-007c).

**Risks.** (1) ProcessPool semantics differ Windows/Linux → `USE_PROCESS_POOL = HAS_NUMBA AND shared_memory AND spawn`; Windows-11 prod = ProcessPool path (AC-019). (2) Drill double-charge funding on 1m → granularity-invariant `(date,hour)` dedupe (AC-006d/AC-015a). (3) `shared_memory` leak on Windows → `finally`-scoped release + terminal-path test (AC-019/AC-048e).

---

### E.3 — Phase P3: SoA + merge-walk engine (the dominant engine win)

**Goal.** Replace the `list[dict]` + per-scan full re-scan data layout with **structure-of-arrays** (`open_time:int64[]` epoch + OHLCV `float64[]`), a **global sorted-unique timeline**, and **per-symbol advancing merge-walk pointers that never reset** + `searchsorted` O(log N) anchor binding. This kills RC-1 (O(scans × N_total) setup) and RC-2 (O(P × T²) seeding). **PURE PYTHON, bit-identical to the P0 oracle.** This phase alone must hit "minutes" (NFR-001) and ≥150k HEAVY-evals/s (NFR-003). Ships UNFLAGGED with a `BT_ENGINE_SOA` escape hatch back to the legacy layout.

**Scope.**
- IN: `SoADatasetBuilder` (symbol→SoA, parse-each-candle-once, global timeline, vectorized scan-anchor binding, degenerate short-circuit <100ms); merge-walk pointer engine replacing `_evaluate_candles_until`'s window rebuild; `searchsorted` mark-seeding replacing the linear-prefix re-seed; the float64 fingerprint re-freeze; KlineStore `KlineColumns` SoA-ready output; window-aware adaptive-blacklist ring counter; precomputed funding-boundary bar indices; PreflightEstimator wall-time reject term (now the engine has a realized wall budget).
- OUT: numba JIT (P4 — P3 is pure-Python); columnar storage (P5); fast-path (P6).

**Files.** `backend/services/soa_dataset_builder.py` [NEW], `backend/services/backtest_engine.py` [MOD — data-layout re-point, decisions FROZEN], `backend/services/kline_store.py` [MOD — `KlineColumns` SoA output], `backend/services/preflight_estimator.py` [MOD — wall-time term]. Tests: `tests/backend/test_soa_builder.py` [NEW], `tests/backend/test_merge_walk_engine.py` [NEW], `tests/backend/test_soa_scaling.py` [NEW], `tests/backend/test_backtest_performance.py` [MOD — TASK-313 event-loop-lag].

**Tasks.** TASK-300..TASK-313 (§F) — incl. TASK-313 event-loop-lag / live-fetch budget (NFR-013 GREEN owner; the engine shares the live FastAPI process).

**Tests.** T.7 (SoA boundary-equivalence: empty/single-candle, signal-before-first/at-or-after-last, epoch-vs-datetime, 4×-history ±10% setup, per-lookup ≤log(N) microbench, LIGHT per-advance ns ceiling, symbol-scaling gate), T.3a/T.3b (latches re-asserted at P3), AC-020 fingerprint diff.

**Verification.**
```bash
python -m pytest tests/backend/test_soa_builder.py tests/backend/test_merge_walk_engine.py tests/backend/test_soa_scaling.py -x -q
# Diff vs P0 oracle on EVERY fixture (develop-behind-flag, diff-every-fixture discipline):
python -m pytest tests/backend/test_backtest_golden.py tests/backend/test_golden_fingerprint.py -q
# Throughput floor (pure-Python ≥150k HEAVY-evals/s) + ≤60s canonical:
python -m pytest tests/backend/test_backtest_performance.py -q
python -m pytest tests/backend -k "backtest or kline" -q
```

**Completion criteria.** AC-020 (DISCRETE bit-identical to frozen float64 master + MONEY within epsilon — MONEY fingerprint RE-FROZEN as float64 here), AC-021 (4×-history setup constant ±10% — RC-1 dead), AC-022 (boundary-bar exit fires same scan/bar as legacy window scan), AC-023 (carried-position mark-seeding bit-identical, no IndexError — RC-2 dead), AC-024 (≥150k HEAVY-evals/s + ≤60s drill-OFF / ≤90s drill-ON canonical pure-Python), AC-024a (HEAVY/HEAVIEST ≤90s + RSS ceilings), AC-024b (sweep absolute budget — numba lane only), AC-025 (symbol-doubling ≤2×), AC-018-wall (wall-time reject term now realizable), AC-006b/AC-006d re-asserted green. **AC-041: MONEY fingerprint re-frozen float64 at P3; DISCRETE byte-identical P0→P3.**

**Dependencies.** P0 (oracle — diff every fixture), P1 (cache), P2 (batched loaders + KlineStore seam feed the SoA builder).

**Risks.** (1) SoA rewrite silently perturbs a path-dependent latch → develop-behind-`BT_ENGINE_SOA`-flag, diff vs oracle on EVERY fixture before trusting; re-assert AC-006b (adaptive-blacklist) + AC-006d (funding) at P3. (2) epoch-vs-datetime `open_time` mismatch → AC-023 covers it explicitly. (3) misaligned-listing timeline blowup (~168MB) → its own `timeline_bytes` budget line (NFR-012). (4) per-symbol-candle cadence (if AC-004 proved it) re-derives the budgets BEFORE P3 merge.

---

### E.4 — Phase P4: numba JIT kernel (optional, import-guarded)

**Goal.** `@njit(cache=True, nogil=True)` the per-candle kernel (liquidation→SL→TP precedence, uPnL, once-per-tick basket equity, MFE/MAE, funding, trailing/time) over column arrays + a compact position SoA. **Developed PURE-PYTHON-FIRST then JIT'd**; a differential float64-vs-Decimal harness asserts identical DISCRETE decisions. Import-guarded (`HAS_NUMBA`) with the pure-Python lane as the **fallback of record**. numba is GO (N1) but the guard stays.

**Scope.**
- IN: `engine_kernel` (typed numpy arrays only across the nopython boundary; compact position SoA / jitclass; `boundscheck=False` timed path + CI `boundscheck=True` fuzz build; near-threshold guard-band routing to the Decimal-SoA oracle); pure-Python fallback of record; `BT_USE_NUMBA` flag + `HAS_NUMBA` capability; accel-health boot/warmup validation; Phase-A-kernel→orchestrator→Phase-B-drill handshake (drill stays non-JIT); pyproject `accel` extra declaration.
- OUT: columnar storage (P5); fast-path vectorization (P6 — though the kernel is shared).

**Files.** `backend/services/engine_kernel.py` [NEW — both lanes], `backend/services/backtest_engine.py` [MOD — dispatch to kernel], `backend/services/capability_resolver.py` [NEW — `HAS_NUMBA`/flags], `pyproject.toml` [MOD — `[project.optional-dependencies].accel`]. Tests: `tests/backend/test_engine_kernel.py` [NEW], `tests/backend/test_kernel_differential.py` [NEW], `tests/backend/test_numba_fallback.py` [NEW].

**Tasks.** TASK-400..TASK-410 (§F).

**Tests.** T.4 (differential float64-vs-Decimal), kernel fuzz/differential grid, near-threshold routing (AC-026), accel-failure fallback (AC-028/AC-028a), live-path no-import (AC-029), prebuilt-wheel CI (AC-030).

**Verification.**
```bash
python -m pytest tests/backend/test_engine_kernel.py tests/backend/test_kernel_differential.py tests/backend/test_numba_fallback.py -x -q
# Both lanes must be DISCRETE-identical outside the money guard-band:
python -m pytest tests/backend/test_golden_fingerprint.py -q
# numba-lane benchmark (windows-latest HAS_NUMBA lane, accel_waived=false): ≥100× + ≥5M HEAVY-evals/s + <10s
python -m pytest tests/backend/test_backtest_performance.py -k "numba" -q
# Pure-Python lane still green when numba absent (import-guarded):
BT_USE_NUMBA=0 python -m pytest tests/backend -k "backtest or kline" -q
```

**Completion criteria.** AC-026 (both lanes DISCRETE bit-identical outside guard-band; near-threshold routed to Decimal-SoA oracle; CI `boundscheck=True` no-OOB), AC-026a (near-threshold double-run <120s canonical; HEAVY in-flight abort), AC-027 (warmed ≥frozen-floor HEAVY-evals/s + <10s drill-OFF / <20s drill-ON / HEAVY <30s — when `HAS_NUMBA`), AC-028 (accel absent/ABI-broken still boots pure-Python), AC-028a (accel-failure fallback <120s + freed allocations), AC-029 (live path imports neither numba nor SoA kernel), AC-030 (prebuilt wheels resolve; windows-latest full golden green), NFR-002 (≥100×). **If `HAS_NUMBA` false: AC-026/027/030 + numba budgets WAIVED-by-capability (`accel_waived:true` in manifest); AC-024/024a pure-Python lane binds.**

**Dependencies.** P0, P1, P2, P3 (the kernel JITs the P3 pure-Python kernel; re-targeted from real P3 profile numbers per findings §8). The pure-Python lane IS the P3 engine.

**Risks.** (1) numba ABI break on py3.14.3/numpy2.4.4 → N1 verified GO, but every U.4 AC is capability-waived (D5 escape hatch); P3 alone hits minutes. (2) CPython-vs-LLVM 1-ULP money divergence → near-threshold guard-band routes to the Decimal-SoA oracle, NOT a blanket "always bit-identical" claim (AC-026). (3) Live scanner accidentally imports numba → AC-029 asserts the live order-execution path imports neither. (4) numba debugging harder → pure-Python-first discipline is mandatory.

---

### E.5 — Phase P5: Parquet/DuckDB read layer

**Goal.** Move the bulk OHLCV **READ** off Postgres onto immutable Parquet (symbol→month) + DuckDB read + Arrow hot cache + mmap'd Feather for cross-process reruns. **Postgres stays write-of-record.** Derive coarse TFs (15m/1h/4h) from the sealed 5m base. Only if P0–P4 green. Flag-gated (`BT_USE_COLUMNAR`/`BT_DERIVE_COARSE`).

**Scope.**
- IN: `KlineStore` columnar tiers (Arrow hot → Feather mmap → Parquet → Postgres); Parquet/Feather writer (sealed-only; forming day NEVER admitted to a hot tier); DuckDB/Polars reader (capability-locked, injection-safe); `content_sha256` Parquet-rebuild leg (tri-source); derive-coarse from sealed 5m base (with sealed-base precondition + native fallback); PITR read-time-compare invalidation; rotted-Parquet rebuild-from-SOR; junction-swap safety (Windows); NFR-016 sampled backstop; shadow/dark-compare mode.
- OUT: fast-path (P6).

**Files.** `backend/services/kline_store.py` [MOD — columnar tiers], `backend/services/columnar_writer.py` [NEW], `backend/services/columnar_reader.py` [NEW — DuckDB/Polars], `backend/services/derive_coarse.py` [NEW], `backend/async_persistence.py` [MOD — `materialized`/`data_generation` read-compare], `pyproject.toml` (accel extra already declared P4). Tests: `tests/backend/test_columnar_store.py` [NEW], `tests/backend/test_derive_coarse.py` [NEW], `tests/backend/test_columnar_security.py` [NEW], `tests/backend/test_shadow_compare.py` [NEW].

**Tasks.** TASK-500..TASK-512 (§F).

**Tests.** T.6 (tri-source sha — Parquet leg AC-011p), T.8 (per-tier read-latency micro-bench Arrow<Feather<Parquet<Postgres; cross-process warm-rerun <5s numba lane; cold-start gates), T.10 (junction-swap, DuckDB injection lockdown, shadow/dark, PITR).

**Verification.**
```bash
python -m pytest tests/backend/test_columnar_store.py tests/backend/test_derive_coarse.py tests/backend/test_columnar_security.py tests/backend/test_shadow_compare.py -x -q
# Columnar OFF == Postgres-identical; ON == cross-engine byte-parity:
BT_USE_COLUMNAR=0 python -m pytest tests/backend/test_golden_fingerprint.py -q
BT_USE_COLUMNAR=1 python -m pytest tests/backend/test_golden_fingerprint.py -q
python -m pytest tests/backend -k "backtest or kline" -q
```

**Completion criteria.** AC-031 (columnar off=Postgres-identical, on=cross-engine byte-parity), AC-031a (forming-day excluded from hot tiers, served from Postgres), AC-011p (Parquet tri-source sha leg), AC-032 (derive-coarse==native byte-identical + sealed-base-precondition native fallback), AC-033 (cross-process warm-rerun <5s numba lane / ≤60s pure-Python), AC-034 (rotted Parquet rebuilt from SOR), AC-035 (PITR self-invalidate O(1) singleton bump), AC-036 (junction-swap safe), AC-047a (shadow/dark-compare) green. Golden parity holds both flag states.

**Dependencies.** P0–P4 all green (spec gate: "only if P0–P4 green"). P1 (sealed manifest defines what is materializable).

**Risks.** (1) `kline_cache` OHLCV NUMERIC would break float64 byte-parity → VERIFIED `DOUBLE PRECISION` in prod (N.1a); NUMERIC = fail-closed boot guard, NOT migrate. (2) DuckDB external-access escape → capability lockdown + post-lockdown probe (AC-036/T.10). (3) Derive-coarse 12× cold-fetch amplification → engage ONLY with a sealed 5m base, else native fallback (AC-032). (4) Stale hot frame on frontier advance → forming day never admitted to a hot tier (AC-031a).

---

### E.6 — Phase P6: Vectorized fast-path + prange sweeps (optional)

**Goal.** For the narrow provably-independent-position config subset, add a **vectorized barrier first-touch** exit; parallelize the OUTER sweep loop with `prange`/ProcessPool. Only if P0–P5 green with time left; else defer with notes. Flag-gated (`BT_USE_FASTPATH`/`BT_PARALLEL_SWEEP`).

**Scope.**
- IN: fast-path eligibility predicate (7 clauses: max_dd≥100 AND no close_on_profit AND no profit target AND no trailing AND no breakeven AND no sequential-depletion/blacklist/skip coupling AND `fill_to_max_trades` OFF); vectorized barrier first-touch; route-ambiguous-to-sequential guard; `prange`/ProcessPool outer-loop sweep; largest-N sweep budget + reject (`MAX_SWEEP_COMBOS=2000`).
- OUT: nothing further (terminal phase).

**Files.** `backend/services/engine_kernel.py` [MOD — `fast_path_barrier_scan`], `backend/services/fastpath_gate.py` [NEW — eligibility predicate], `backend/mcp/tools/optimizer/sweep_runner.py` [MOD — prange outer loop]. Tests: `tests/backend/test_fastpath_gate.py` [NEW], `tests/backend/test_fastpath_parity.py` [NEW], `tests/backend/test_sweep_prange.py` [NEW].

**Tasks.** TASK-600..TASK-608 (§F).

**Tests.** T.4 (two-sided sandwich vs sequential oracle), eligibility classification (eligible↔ineligible per clause, AC-037), fast-path speedup (AC-037a), bounded-chunk streaming (AC-038), prange sweep budget (AC-039/AC-039a/AC-039b).

**Verification.**
```bash
python -m pytest tests/backend/test_fastpath_gate.py tests/backend/test_fastpath_parity.py tests/backend/test_sweep_prange.py -x -q
# Fast-path result == sequential oracle on eligible configs; ineligible routes to sequential:
python -m pytest tests/backend/test_golden_fingerprint.py -q
python -m pytest tests/backend -k "backtest or kline" -q
```

**Completion criteria.** AC-037 (fast-path == sequential oracle + 7-clause eligibility classification + ineligible routes sequential), AC-037a (≥10× speedup vs sequential, never net-slower — when `HAS_NUMBA`), AC-038 (bounded-chunk streaming, RSS in budget), AC-039 (500-combo prange <5min + live-breaker pauses sweep), AC-039a (largest-N=2000 budget + n=2001 reject), AC-039b (realistic canonical-class combo budget) green. Golden parity holds.

**Dependencies.** P0–P5 all green. The fast-path validates against the P3/P4 sequential kernel (its oracle).

**Risks.** (1) Fast-path runs on a coupled config → 7-clause predicate routes anything ambiguous to the sequential kernel (AC-037); each clause has an ineligible-classification test. (2) Fast-path byte-correct but no-faster → AC-037a asserts ≥10× AND never-net-slower. (3) Unbounded large-N sweep → `MAX_SWEEP_COMBOS=2000` + pre-slot reject (AC-039a). **If time-constrained: P6 is DEFERRED with notes — P0–P5 already meet the "minutes" goal.**

---

## F. Task Breakdown (TASK-NNN — REQ IDs · files · impl notes · test names)

> Every task is TDD: write the named test FIRST (RED), implement (GREEN), refactor. Signatures are exact; impl notes are mechanical.

### F.0 — Phase P0 tasks (golden-master harness; NO production logic change)

**TASK-001 — `GoldenMasterOracle` snapshot harness.** *(FR-001..014, REQ-TEST; AC-001)*
- File: `tests/backend/golden/oracle.py` [NEW].
- Impl: `class GoldenMasterOracle` with `def run_and_snapshot(self, config: dict, signals: list[dict], klines: dict[str, list[dict]], *, name: str) -> dict` — runs the CURRENT `BacktestEngine(...).run(...)` (engine is pure/sync, no DB — see `test_backtest_golden.py:19`), serializes ordered trades + ordered equity_curve + the frozen metrics key set to `tests/backend/golden/snapshots/{name}.json`; `def assert_matches(self, name, result)` re-runs and byte-compares DISCRETE fields, money within `REL_TOL`/epsilon. Capture runs with the 120s Timer DISABLED (offline; AC-001) — the oracle calls the engine directly, never `BacktestService`.
- Test: `tests/backend/test_golden_fingerprint.py::test_oracle_roundtrip_stable`, `::test_capture_canonical`.

**TASK-002 — Three-way Σ reconciliation (replaces `_assert_reconciles`).** *(FR-007/012, NFR-009; AC-002, AC-048g)*
- File: `tests/backend/golden/reconcile.py` [NEW].
- Impl: `def assert_reconciles(result: dict) -> None` asserting `Σ trade.pnl == net_profit == final_equity − starting_capital` (Decimal-exact on P0–P2 lane) AND per-trade `trade.pnl == gross − entry_fee − exit_fee − funding_paid` for non-liquidation, `trade.pnl == −locked_margin − entry_fee − funding_paid` with `exit_fee==0` for liquidation (FR-007 carve-out pinned to `backtest_engine.py:1400-1403`). A meta-test removing one term turns RED. **Two AC-048g/M.2 carve-out fixtures are OWNED here as NAMED tests (B3-F3/B5-F2 — previously prose-only in §M.2, no task owned them):** (1) **liquidation-with-fees-AND-funding** — a liquidation carrying NON-ZERO `entry_fee` AND a crossed 0/8/16h funding boundary (`funding_paid≠0`) asserts `trade.pnl == −locked_margin − entry_fee − funding_paid` PARTICIPATES in Σ (distinct from TASK-003's clean SL-omitted `liquidation` fixture); (2) **B&H-collision** — a run that TRADES BTC/USDT while the BTC Buy&Hold baseline is active asserts the B&H series is EXCLUDED from Σ while the real BTC/USDT trade is counted EXACTLY ONCE (the FR-012 double-count collision, spec AC-048g).
- Test: `tests/backend/test_backtest_golden.py::test_three_way_reconciliation`, `::test_meta_reconciliation_teeth`, `::test_liquidation_with_fees_and_funding_in_sigma` (B3-F3/B5-F2), `::test_bh_baseline_excluded_from_sigma` (AC-048g).

**TASK-003 — Close-rule fixture battery + source-derived enum.** *(REQ-TEST-007/008; AC-003, T.2)*
- File: `tests/backend/golden/fixtures.py` [NEW], `tests/backend/test_backtest_golden.py` [MOD].
- Impl: frozen fixtures for EVERY `close_reason`: clean `tp`, clean `sl`, `liquidation` (SL omitted/outside band), `equity_rise`/`close_on_profit` basket-flatten, `equity_drop`, `equity_drop_smart` (one-shot + re-arm), `breakeven` TP-mutation, `max_duration`, `trailing_profit` ratchet, `mr_time_stop`, `backtest_end` force-flush. `def source_close_reasons() -> set[str]` greps the engine-emitted literals (`backtest_engine.py:820-834,1714,1729,...,1930,315`) — tokens `tp,sl,liquidation,equity_drop,equity_drop_smart,close_on_profit,equity_rise,trailing_profit,mr_time_stop,max_duration,breakeven,backtest_end`. Completeness meta-test: `fixture_close_reasons == source_close_reason_enum`; teeth meta-test disabling one fixture turns the union gate RED. (`mr_target` NOT required — not an engine token yet.)
- Test: `::test_close_rule_union_coverage`, `::test_enum_completeness_meta`, `::test_enum_teeth_meta`.

**TASK-004 — Canonical fingerprint capture (DISCRETE/MONEY split + 6h ceiling + fallback).** *(REQ-PAR-042; AC-001, AC-041)*
- File: `tests/backend/test_golden_fingerprint.py` [NEW].
- Impl: capture the canonical fixture OFFLINE. **P0 data precondition (named step):** the canonical klines MUST be pre-seeded/warmed into the cache (or loaded from a committed fixture file) BEFORE capture, and the capture asserts `bybit_kline_calls == 0` — P0 runs BEFORE the P1 cache fix, so an unseeded capture would trigger the exact RC-3 live Bybit re-download the feature exists to kill, and would make the oracle non-reproducible offline (AC-001 "Timer disabled / offline" intent). **Fixture-selection is pre-estimated, NOT gambled:** run a fast engine-CPU pre-estimate to predict capture wall-time and pick the fixture UPFRONT — DEFAULT to the **30d×20sym** fixture as the authoritative oracle (it still exercises every `close_reason` + carried-position/cross-scan paths); promote 90d×50sym to authoritative ONLY if the pre-estimate predicts it completes well under the 6h ceiling, else keep 90d×50sym best-effort/offline (do NOT spend up to 6h of the overnight window on the slow legacy super-linear path before P1 starts). Freeze a **DISCRETE fingerprint** (sha over trade count/opened set/sides/symbols/entry-exit bar indices/close_reason/ordering — byte-identical P0–P6) and a **MONEY fingerprint** (Decimal-frozen P0–P2, re-frozen float64 at P3). Record host CPU model + clock + chosen fixture identity in the manifest. The chosen identity is version-tracked and is the SAME identity gated at every later phase.
- Test: `::test_discrete_fingerprint_stable`, `::test_money_fingerprint_stable`, `::test_fingerprint_fallback_recorded`, `::test_capture_zero_bybit_calls` (asserts pre-seeded cache, `bybit_kline_calls==0`).

**TASK-005 — Engine-CPU baseline (NFR-002 denominator).** *(NFR-002; AC-001, T.8)*
- File: `tests/backend/test_backtest_performance.py` [MOD].
- Impl: capture the authoritative uncapped engine-only-CPU baseline (the ≥100× denominator) on the SAME pre-estimate-selected fixture as TASK-004 (30d×20sym default; 90d×50sym only if the pre-estimate clears the 6h ceiling), recording fixture identity + basis + lane. The klines are pre-seeded (`bybit_kline_calls==0`, shared with TASK-004). The reduced-sub-fixture extrapolation is a documented cross-check ONLY. If the slow path is deferred, the ≥100× baseline is captured on the 30d×20sym fixture and the multiplier is asserted opportunistically/offline (`perf_baseline_waived` until the full baseline lands).
- Test: `::test_engine_cpu_baseline_captured`.

**TASK-006 — Cadence-evidence differential (once-per-tick vs per-symbol-candle).** *(FR-018, NFR-004; AC-004)*
- File: `tests/backend/test_golden_fingerprint.py` [MOD].
- Impl: read + cite the ACTUAL basket-equity recompute cadence in `_evaluate_candles_until`/`_eval_equity_core` (`backtest_engine.py:1177,1592`); a DIFFERENTIAL test runs BOTH candidate cadences on a multi-symbol fixture with an equity-threshold rule positioned to make them DIVERGE, asserting which is bit-identical to legacy (automated pass/fail). If per-symbol-candle: freeze that cadence, flag the cadence-contingent budgets for re-derivation before P3.
- Test: `::test_cadence_differential_decides`.

**TASK-007 — Open-book depth B measurement.** *(FR-018, NFR-003/004; AC-004a)*
- File: `tests/backend/test_golden_fingerprint.py` [MOD].
- Impl: measure ACTUAL peak + mean open-book B (concurrent positions per timeline tick) on the AC-001-resolved canonical fixture; confirm B≤5 OR re-derive `heavy_eval_count` + evals/s denominators + HEAVY latency budgets against measured B before the P3 merge gate (using the §Q.2 pre-computed B≈10/B≈15 table). Flag budgets 'B-contingent'.
- Test: `::test_open_book_depth_measured`.

**TASK-008 — NO-OP byte-identity fixture.** *(NFR-010; AC-005)*
- File: `tests/backend/test_backtest_golden.py` [MOD].
- Impl: empty instrument_info + empty scan_contexts + empty fine_klines + no regime → assert output byte-identical to the pure 5m path. Preserves the golden no-op guarantee.
- Test: `::test_noop_byte_identical`.

**TASK-009 — Degenerate / zero-trade fixture (`total_trades` invariant).** *(S.1, T.5; AC-006)*
- File: `tests/backend/test_backtest_golden.py` [MOD].
- Impl: zero-trade / degenerate-input fixture → `metrics.total_trades` present-and-0, renders as a real result, reconciliation holds trivially.
- Test: `::test_degenerate_total_trades_present_zero`.

**TASK-010 — `skip_if_positions_open` latch fixture.** *(FR-009, REQ-PAR-012; AC-006a, T.2a)*
- File: `tests/backend/golden/fixtures.py` [MOD].
- Impl: multi-scan (≥3) fixture, `skip_if_positions_open=true`, non-empty book at a scan START → bit-identical to legacy: new entries skipped that scan (latched at start), close rules still fire on carried positions, anchor preserved, `smart_drawdown` NOT re-armed; empty-book scan takes normal admit+re-arm+re-anchor.
- Test: `tests/backend/test_backtest_golden.py::test_skip_if_positions_open_latch`.

**TASK-011 — `fill_to_max_trades` relaxed-second-pass fixture.** *(FR-011, REQ-PAR-025; AC-006c, T.2b)*
- File: `tests/backend/golden/fixtures.py` [MOD].
- Impl: multi-scan multi-signal fixture, `fill_to_max_trades=true`, strict pass under-fills `max_trades`, leftover pool (some fail min_score/confidence, some stale, some already-open) → bit-identical in BOTH `execution_mode{batch,immediate}`: relaxed pass skips strict-rejected and continues, tops per-scan `scan_entered` to exactly `max_trades`, bypasses ONLY min_score/confidence, ranks leftovers by abs(score) desc. Also asserts fast-path-INELIGIBLE (FR-013 clause 7).
- Test: `::test_fill_to_max_trades_relaxed_pass[batch]`, `::test_fill_to_max_trades_relaxed_pass[immediate]`.

**TASK-012 — Adaptive-blacklist window-crossing fixture.** *(FR-011a, REQ-PAR-026, REQ-PERF-010; AC-006b, T.3a)*
- File: `tests/backend/golden/fixtures.py` [MOD].
- Impl: multi-scan fixture where a symbol is blacklisted by the run's OWN losing trades AND closes cross the 48h lookback boundary → O(1) incremental win/total counter EQUALS legacy full-history recompute at EVERY scan, including `≤T` vs `<T` boundary tie and the exact win/total `close_reason` feed. (Re-asserted at P3 + P4.)
- Test: `::test_adaptive_blacklist_window_equivalence`.

**TASK-013 — Funding granularity-invariance fixture.** *(FR-010, REQ-PAR-013; AC-006d, T.3b)*
- File: `tests/backend/golden/fixtures.py` [MOD].
- Impl: multi-scan multi-granularity fixture → bit-identical: (a) funding charged exactly once per `(date,hour)` boundary, identical count+timing across 5m AND drilled-1m (granularity-invariant), (b) negative `funding_rate_fixed_pct` inverts (longs receive/shorts pay), (c) equity cascade reads POST-funding wallet on a boundary bar. **GAPPED-funding-boundary fixture (B3-F2 — added to the P0 snapshot battery so TASK-304's P3 precompute is golden-DIFFED, not merely unit-asserted against its own inline oracle):** a deterministic multi-scan fixture where a 0/8/16h slot's ONLY stored bar lands at `minute ≥ 5` (gapped — legacy `backtest_engine.py:1262` charges NOTHING that slot) AND a SIBLING slot's first bar lands at `minute < 5` (charged), captured into the P0 stored snapshot. Because funding mutates `wallet_balance` which feeds the equity-cascade close rules, a spurious/missing charge can FLIP a discrete close — so this gapped case is part of the FROZEN P0 oracle that TASK-304 is diffed against every phase, not a P3-only inline assertion. (Mirror the same golden-snapshot treatment for any other P3-re-implemented edge branch: empty/single-candle, no-prior-candle mark seed.)
- Test: `::test_funding_granularity_invariance`, `::test_funding_negative_inversion`, `::test_funding_gapped_boundary_golden` (the gapped 0/8/16h slot charges ZERO and the sibling charges once — captured in the P0 snapshot).

**TASK-014 — Frozen contract key sets (metrics/trades/summary).** *(FR-037; AC-043, T.9)*
- File: `tests/backend/golden/metrics_keys.json` / `trades_keys.json` / `summary_keys.json` [NEW], `tests/backend/test_backtest_schemas.py` [MOD].
- Impl: freeze the exact `metrics_keys.json` set (names + types, nested expanded — not "~45"); `trades_keys.json` (19 `BacktestTrade` fields + `strategy_kind`); `summary_keys.json`. Asserted two-tier: `served ⊇ REQUIRED-core` AND `served ⊆ (REQUIRED ∪ OPTIONAL)`; numeric keys typed `number|null`, no string sentinels; cohort/MR/regime keys OPTIONAL+nullable. A dropped/renamed/retyped field fails CI.
- Test: `::test_metrics_keys_frozen`, `::test_trades_keys_frozen`, `::test_summary_keys_frozen`.

### F.1 — Phase P1 tasks (cache re-download fix; v58)

**TASK-100 — `SealedManifest` + completion-frontier.** *(FR-019..024; REQ-CACHE-*, REQ-STORE-001..011; AC-007/009/010)*
- File: `backend/services/sealed_manifest.py` [NEW].
- Impl: `class SealedManifest` with `def completion_frontier(self, now: datetime, interval: str) -> int` = `floor(now_ms/T)*T` with skew margin, persisted monotonic UTC ratchet `frontier = max(prev, computed)` (AC-009a); `def is_sealable(self, symbol, interval, date, stored_rows, lifecycle) -> tuple[bool, int]` returns (sealed, day_class) per the FR-019 predicate (day fully past frontier AND durably stored+validated); day-class enum `0..6` (N.1); `async def unsealed_days(self, symbol, interval, start, end) -> list` (fetch-eligible = `(NOT sealed) OR reverify_pending`); `def halt_seal_writes(self)` latch (SAFE_MODE). Runtime loader + `SealBackfillRunner` call the SAME frontier function.
- Test: `tests/backend/test_sealed_manifest.py::test_frontier_floor`, `::test_frontier_monotonic_ratchet`, `::test_sealable_predicate`, `::test_unsealed_days_fetch_eligible`.

**TASK-101 — Read-path lazy-seal-from-SOR.** *(FR-019, NFR-017; AC-007a/007b)*
- File: `backend/services/sealed_manifest.py` [MOD].
- Impl: `async def lazy_seal_from_sor(self, conn, symbol, interval, window) -> int` — BEFORE gap-compute, evaluate the FR-019 predicate against stored rows and seal complete past-frontier days in-place (0 Bybit), scoped to THIS run's symbols+window (not the corpus), batched set-based UPDATEs, records `lazy_seal_ms`; each lazy-sealed day carries a NON-NULL `content_sha256` = FR-025 canonical hash. Run still completes within ≤60s/≤90s WITH `lazy_seal_ms` included.
- Test: `tests/backend/test_kline_cache_sealed.py::test_lazy_seal_pre_backfill`, `::test_lazy_seal_latency_bounded`, `::test_lazy_seal_writes_sha`.

**TASK-102 — `content_sha256` canonical hash.** *(FR-025; AC-011)*
- File: `backend/services/sealed_manifest.py` [MOD].
- Impl: `def content_sha256(rows) -> bytes` — sorted by `open_time`; int64-ms epoch derived `floor(extract(epoch)*1000)` (N.1c — `open_time` STAYS TIMESTAMPTZ, unit DERIVED); IEEE-754 LE float64 OHLCV; fixed column order; `sha_version=0`. The canonical float64 derived ONCE from the Bybit-native string (single rounding) reused across sources (AC-011p). Boot/CI fail-closed guard: `kline_cache` OHLCV type IS `DOUBLE PRECISION` (N.1a) else REFUSE.
- Test: `tests/backend/test_kline_cache_sealed.py::test_content_sha256_canonical`, `::test_sha_double_precision_guard`, `::test_timestamptz_to_int64ms_derivation`.

**TASK-103 — `KlineCacheService` manifest-aware coverage.** *(FR-020/021/022; AC-007/009/010)*
- File: `backend/services/kline_cache_service.py` [MOD — `get_coverage_gaps:116`, `ensure_coverage:198`].
- Impl: replace the count-based perpetual-gap detector (any day < theoretical-max = gap) with the manifest predicate — a sealed-short day (mid-day listing/halt/forming, e.g. 144/288) is sealed-short NOT a perpetual gap and never re-probed. `ensure_coverage` fetches per-gap-run (not the `[min(gap)..max(gap)+1d]` bracket that re-downloads whole history). Negative caching via `gap_ranges`; reverify-pending one-shot post-frontier fetch then settle.
- Test: `tests/backend/test_kline_cache_sealed.py::test_sealed_short_not_perpetual_gap`, `::test_per_gap_run_fetch_no_bracket`, `::test_reverify_one_shot`.

**TASK-104 — REST `_PAGE_SIZE` 200→1000 + outer chunk loop.** *(NFR; AC-008)*
- File: `backend/services/kline_cache_service.py` [MOD — `_PAGE_SIZE:19`, `_fetch_klines_from_bybit:348/396`].
- Impl: `_PAGE_SIZE = 1000` (Bybit-documented max; 5× fewer paginated requests); wrap the fetch in an outer chunk loop so a >1000-candle gap paginates correctly. Klines produced BYTE-IDENTICAL to legacy (only request count changes).
- Test: `tests/backend/test_kline_cache_sealed.py::test_page_size_1000_byte_identical`, `::test_outer_chunk_loop_paginates`.

**TASK-105 — Sealed-once rerun guarantee (the headline).** *(FR-020, R.2; AC-007/007c)*
- File: `backend/services/kline_cache_service.py` [MOD].
- Impl: a fully-sealed range rerun issues `bybit_kline_calls == 0`; each sealed day's lifetime fetch `call_count == 1` (mock client). SWEEP-level: aggregate `bybit_kline_calls == 0` across ALL ProcessPool workers (cache-fill ONCE at warm-up, not per combo).
- Test: `tests/backend/test_kline_cache_sealed.py::test_sealed_rerun_zero_calls`, `::test_sealed_day_call_count_one`, `::test_sweep_aggregate_zero_calls`.

**TASK-106 — v58 callable migration `_add_sealed_manifest_columns`.** *(NFR-014/015, REQ-MIG-007/008/040; AC-008/008a/012)*
- File: `backend/async_persistence.py` [MOD — append `(58, _add_sealed_manifest_columns)` to `_MIGRATIONS` ~L1522].
- Impl: a CALLABLE (N4 — multi-stmt DDL strings get `;`-split) `async def _add_sealed_manifest_columns(conn)`. Step-0 fail-loud pre-checks: assert PK is exactly `(symbol, interval, date)` else RAISE naming expected PK; assert no pre-created manifest column of incompatible type (e.g. `first_open_ts INT4` where v58 wants `BIGINT`) else RAISE naming column+type — BEFORE any `ADD COLUMN`. Then `ADD COLUMN IF NOT EXISTS` for all N.1 columns, **every column pinned with explicit type + NOT NULL DEFAULT where it participates in predicate/flag/arithmetic logic (B2-F3 — these were under-specified inline; types are canonical in §I.1 and MUST match exactly):** `sealed BOOLEAN NOT NULL DEFAULT false`, `day_class SMALLINT NOT NULL DEFAULT 0`, `gap_count SMALLINT NOT NULL DEFAULT 0`, `gap_ranges JSONB`, `reverify_pending BOOLEAN NOT NULL DEFAULT false` (load-bearing in the TASK-107 partial-index predicate `WHERE NOT sealed OR reverify_pending` AND TASK-100 `unsealed_days` — a NULL would make the OR UNKNOWN and the planner may refuse the partial index unless query+index predicates match exactly), `listing_snapped BOOLEAN NOT NULL DEFAULT false`, `delisted BOOLEAN NOT NULL DEFAULT false`, `content_sha256 BYTEA`, `sha_version SMALLINT NOT NULL DEFAULT 0`, `manifest_semantics_version SMALLINT NOT NULL DEFAULT 1`, `fine_base_generation BIGINT` (nullable by design), `data_generation BIGINT NOT NULL DEFAULT 0`, `materialized BOOLEAN NOT NULL DEFAULT false` (flipped true↔false by TASK-501 — a NULL start breaks the flip), `first_open_ts`/`last_open_ts BIGINT`, `sealed_at TIMESTAMPTZ` — all catalog-only (PG11+), idempotent, on `kline_cache_coverage` EXCLUSIVELY (this table has NO `status` column — the `backtest_runs` status-CHECK widen + additive `backtest_runs` columns + control/lifecycle tables are a SEPARATE migration, TASK-106b/v59, since bundling a `backtest_runs` CHECK swap into the coverage callable is mis-targeted and would no-op). Zero data-dependent backfill inline. Mid-DDL failure leaves `schema_version=57`, nothing partial.
- Test: `tests/backend/test_v58_migration.py::test_v58_adds_columns_idempotent`, `::test_v58_column_types_and_defaults` (asserts NOT NULL + DEFAULT on the predicate/flag/arithmetic columns: `gap_count`/`reverify_pending`/`listing_snapped`/`delisted`/`sha_version`/`materialized`/`data_generation`), `::test_v58_wrong_pk_fail_loud`, `::test_v58_wrong_type_fail_loud`, `::test_fresh_db_0_to_58_equivalent`, `::test_v58_atomic_rollback_on_failure`. **All real-DDL tests carry the same `BACKTEST_TEST_DATABASE_URL` skip-guard as TASK-116 (N3): idempotency / atomic-rollback / fresh-DB-equivalence / column-types are NOT mock-validatable — a green headless P1 does NOT validate the migration; P1 exit note + morning report MUST record v58/v59 as UNVALIDATED until a Postgres lane runs.**

**TASK-106b — v59 callable migration `_add_backtest_control_objects` (the objects P1–P5 read/write).** *(NFR-014/015, REQ-MIG-007/008/040, FR-051/052; AC-008/012)*
- File: `backend/async_persistence.py` [MOD — append `(59, _add_backtest_control_objects)` to `_MIGRATIONS` immediately AFTER `(58, _add_sealed_manifest_columns)`]. **Sequenced BEFORE TASK-114/TASK-212/TASK-404/405/110 reference these objects** (RunReaper runs at boot AFTER `schema_version=59` confirmed). Verified gap (firsthand grep): `backtest_runs` (async_persistence.py:662-673) has a 5-value status CHECK `('pending','running','completed','failed','cancelled')` and NONE of `stage_timings`/`engine_fingerprint`/`terminal_reason`; `bt_flag_config`/`bt_flag_audit`/`symbol_lifecycle`/`sor_data_generation` have ZERO occurrences in `backend/`. Without this task TASK-114's CAS to `interrupted_by_restart` and TASK-212's `queued` VIOLATE the live CHECK and RunReaper crashes at every boot.
- Impl: a CALLABLE (N4) `async def _add_backtest_control_objects(conn)`, all idempotent + catalog-only:
  - (a) `ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS stage_timings JSONB`, `ADD COLUMN IF NOT EXISTS engine_fingerprint TEXT`, `ADD COLUMN IF NOT EXISTS terminal_reason TEXT` (constant/NULL defaults → no rewrite).
  - (b) **Status-CHECK widen on `backtest_runs` (the table that HAS a status column)**: PRE-CHECK `pg_get_constraintdef` by the resolved (anonymous @:665) constraint name via `pg_get_constraintdef`/`conname` — SKIP if already the 7-value superset; else DROP old by resolved name `IF EXISTS` → ADD the 7-value superset CHECK `('pending','running','completed','failed','cancelled','queued','interrupted_by_restart')` directly **VALID** (it is a pure widening superset — every existing row already satisfies it, so the validation scan is trivial and no dangling out-of-band VALIDATE step is left unowned). `failed_with_timeout` is NOT a persisted status literal — it is an in-memory terminal *reason* that maps to persisted `status='failed'` + `terminal_reason='timeout'` (J.1), so the 7-value superset is complete; a test asserts every persisted status literal satisfies the constraint. NOTE: this single DROP+ADD takes ACCESS EXCLUSIVE on `backtest_runs`; under `lock_timeout='30s'` (async_persistence.py:1599) an in-flight backtest writing the table can abort the swap → the whole v59 txn rolls back, `schema_version` stays 58, v59 retries on next boot (safe, nothing partial). Quiesce/cancel in-flight backtests at deploy.
  - (c) `CREATE TABLE IF NOT EXISTS bt_flag_config (flag TEXT PRIMARY KEY, value BOOLEAN NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_by TEXT)` + `CREATE TABLE IF NOT EXISTS bt_flag_audit (id BIGSERIAL PRIMARY KEY, flag TEXT NOT NULL, old_value BOOLEAN, new_value BOOLEAN, changed_at TIMESTAMPTZ NOT NULL DEFAULT now(), actor TEXT)` (DB-backed flag layer + detective audit, §L.4 write-surface lockdown grants; TASK-404 DB-read path depends on this).
  - (d) `CREATE TABLE IF NOT EXISTS symbol_lifecycle (symbol TEXT, interval TEXT, listing_ts BIGINT, delist_ts BIGINT, listing_snapped BOOLEAN NOT NULL DEFAULT false, delisted BOOLEAN NOT NULL DEFAULT false, day_class SMALLINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (symbol, interval))` (TASK-100 `is_sealable(...,lifecycle)` input + TASK-110 refresher backing store).
  - (e) `CREATE TABLE IF NOT EXISTS sor_data_generation (id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id=1), generation BIGINT NOT NULL DEFAULT 0)` + seed one row (`INSERT … ON CONFLICT DO NOTHING`) — the PITR singleton TASK-505 bumps O(1).
  - Mid-DDL failure leaves `schema_version=58`, nothing partial.
- Test: `tests/backend/test_v58_migration.py::test_v59_backtest_runs_additive_columns`, `::test_v59_status_check_widen_valid_by_resolved_name`, `::test_v59_creates_flag_and_lifecycle_tables`, `::test_v59_creates_sor_generation_singleton`, `::test_v59_idempotent_second_run`, `::test_v59_lock_timeout_abort_stays_58`, `::test_run_reaper_status_satisfies_widened_check`. (Real-DDL → same `BACKTEST_TEST_DATABASE_URL` skip-guard as TASK-116/N3.)

**TASK-107 — `MaintenanceAdmin.ensure_indexes()` (out-of-band CIC).** *(REQ-MIG-020/033/034, REQ-CACHE-010; AC-010/012, T.10)*
- File: `backend/services/maintenance_admin.py` [NEW].
- Impl: `class MaintenanceAdmin` with `async def ensure_indexes(self, conn)` — invoked from the lifespan boot hook AFTER `schema_version=59` confirmed (NOT `_MIGRATIONS`; CIC illegal in the txn-wrapped runner). `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_coverage_unsealed ON kline_cache_coverage (symbol, interval, date) WHERE NOT sealed OR reverify_pending` (matches the gap-query predicate). **Predicate-SWAP for `idx_backtest_runs_status` — NO-GAP ordering is MANDATORY (B1-F8/B2-F6), the build-temp-then-RENAME pattern is the PRIMARY path, NOT a parenthetical:** the base schema (async_persistence.py:676-678) already creates this index with the NARROW predicate `WHERE status IN ('pending','running')`, and `CREATE INDEX CONCURRENTLY IF NOT EXISTS <same name>` SKIPS when the name exists → the widened predicate would NEVER apply and `status='queued'` rows would be silently uncovered. A `DROP INDEX CONCURRENTLY` → `CREATE INDEX CONCURRENTLY` swap leaves a WINDOW (CIC can take seconds-to-minutes) where the hot admission/RunReaper/LIST status query has NO index → seq scans on a live host; and a crash between DROP and CREATE leaves the table PERMANENTLY un-indexed. So do the no-gap swap: `CREATE INDEX CONCURRENTLY idx_backtest_runs_status_v2 ON backtest_runs (status) WHERE status IN ('queued','pending','running')` → `DROP INDEX CONCURRENTLY IF EXISTS idx_backtest_runs_status` → `ALTER INDEX idx_backtest_runs_status_v2 RENAME TO idx_backtest_runs_status` — a covering index ALWAYS exists. `ensure_indexes` is idempotent against a MISSING target (re-CREATE the widened index if absent, not only DROP-if-invalid), so a crash-after-DROP self-heals on next boot. Idempotency = assert the LIVE `pg_get_indexdef` predicate equals the widened predicate (NOT mere existence), so a silent skip fails CI. On retry, detect+DROP leftover INVALID indexes (incl. a leftover `_v2`) (`SELECT … pg_index WHERE NOT indisvalid`); bounded `lock_timeout`; `cic_build_ms{index}` gauge. Double-ANALYZE `kline_cache_coverage` post-CIC + post-backfill. CLI-only boundary that may WRITE `bt_flag_config`.
- Test: `tests/backend/test_v58_migration.py::test_ensure_indexes_concurrent_idempotent`, `::test_index_planner_uses_idx_coverage_unsealed`, `::test_backtest_runs_status_index_predicate_widened` (asserts live `pg_get_indexdef` predicate includes `'queued'`, not just index existence), `::test_status_index_never_absent_during_swap` (temp-then-RENAME: a covering index exists at every step; DB lane), `::test_ensure_indexes_recreates_missing_status_index` (crash-after-DROP simulated → next boot restores the index), `::test_gap_query_latency_flat_as_manifest_scales`.

**TASK-108 — Partition-tree pre-flight validation.** *(REQ-MIG-035; AC — P1)*
- File: `backend/services/maintenance_admin.py` [MOD].
- Impl: `async def validate_partition_tree(self, conn)` — parent `kline_cache` exists; monthly RANGE scheme (migration-38) intact; no gaps/overlaps; default partition present → FAIL FAST on broken layout (so seal-backfill never seals rows stranded in `kline_cache_default`). Also detect+reconcile rows a legacy/rolling-deploy wrote into `kline_cache_default` back to their monthly partition.
- Test: `tests/backend/test_v58_migration.py::test_partition_gap_refusal`, `::test_default_partition_reconciliation`.

**TASK-109 — `SealBackfillRunner` (deferred, resumable).** *(FR-050, FR-025; AC-013)*
- File: `backend/services/seal_backfill_runner.py` [NEW].
- Impl: `class SealBackfillRunner` with `async def run(self)` — bounded/set-based chunked-commit UPDATE within a statement budget; idempotent + resumable from a checkpoint marker (enumerated states); mutates ONLY coverage/manifest + lifecycle rows, NEVER a `kline_cache` candle row (before/after content-hash diff proves candles byte-identical, row-count non-decreasing); computes `content_sha256` from the SOR rows it already reads in the same pass (non-NULL on backfilled seals); **TTL-exemption is keyed off `sealed = true`, NOT a NULL `fetched_at`** (B2-F1 firsthand: `kline_cache_coverage.fetched_at` is `TIMESTAMPTZ NOT NULL DEFAULT now()` @ async_persistence.py:655, so writing NULL would `NotNullViolation` — a sealed row keeps its non-NULL `fetched_at` and is exempted by the `sealed` flag; a later post-seal `fetched_at = now()` re-stamp is therefore HARMLESS and never removes the exemption); disjoint advisory-lock key on a DIRECT non-pooled session-pinned connection (REQ-MIG-028); paused/resumed by SAFE_MODE `drain()`/`quiesce()`. Off the boot path.
- Test: `tests/backend/test_seal_backfill.py::test_backfill_mutates_only_coverage`, `::test_backfill_resumable_idempotent`, `::test_backfill_writes_sha`, `::test_backfill_candles_byte_identical`.

**TASK-110 — `SymbolLifecycleRefresher`.** *(FR-051, REQ-MIG-005/015; AC-013)*
- File: `backend/services/symbol_lifecycle_refresher.py` [NEW].
- Impl: `class SymbolLifecycleRefresher` — populates/refreshes `symbol_lifecycle`; drives late reclassification of MUTABLE-post-seal columns (`listing_snapped`, `delisted`, `day_class`) WITHOUT un-seal/refetch/sha-change; disjoint advisory-lock on a DIRECT session-pinned connection; off the boot path.
- Test: `tests/backend/test_seal_backfill.py::test_lifecycle_refresh_no_unseal`, `::test_lifecycle_override_survives_refresh`.

**TASK-111 — Shared-breaker per-caller-class isolation.** *(O.4, FR-026, NFR-021; AC-046)*
- File: `backend/mcp/core/breaker.py` [MOD].
- Impl: split the single shared Bybit breaker into per-caller-class sub-states (backtest vs live scanner/auto-trade/reconciler) on the SAME breaker OBJECT — a backtest-origin 429/timeout storm opens the backtest sub-state ONLY; a concurrent live call still proceeds; only live-origin consecutive failures open the live sub-state.
- Test: `tests/backend/test_breaker_isolation.py::test_same_breaker_object`, `::test_backtest_open_does_not_gate_live`.

**TASK-112 — Forming-day snapshot coherency.** *(FR-012, REQ-PAR-045, REQ-STORE-030; AC-048f, T.6a)*
- File: `backend/services/backtest_service.py` [MOD — forming-day capture].
- Impl: a single SoA-build-time forming-day buffer is the only read for the engine main series + 3 aux series (B&H, btc_vol, MR-mean); an interleaved live-scanner forming-day upsert does NOT leak into any series; streamed/cursor multi-batch read internally coherent under `repeatable_read`; the forming-day capture transaction commits immediately (no long-held snapshot pinning `xmin` across the ≤120s run).
- Test: `tests/backend/test_kline_cache_sealed.py::test_forming_day_coherent_cross_read`, `::test_forming_day_no_xmin_pin`.

**TASK-113 — `_update_coverage` GREATEST upsert preserves v58 columns.** *(REQ-ROLL-009/010/011; AC-008)*
- File: `backend/services/kline_cache_service.py` [MOD — `_update_coverage:286`].
- Impl: the legacy `INSERT … ON CONFLICT` column-omitting upsert MUST NOT null/clobber additive v58 columns (column preservation); `candle_count` retains GREATEST max-observed semantics unchanged (verified upsert sets `candle_count`+`fetched_at` only @ :310-316). **`expected_bars(day)` is DAY-INTRINSIC (B2-F4):** define it as a pure function of `(interval, day_class, lifecycle)` = the full-day bar count (`1440/interval_min`) UNLESS listing/halt/forming truncates it — DISTINCT from `get_coverage_gaps`'s WINDOW-CLIPPED `_expected_for(d)` helper (`:158-176`, which depends on the request's start/end time-of-day and is NOT a day-intrinsic quantity). The manifest invariant `stored_row_count == expected_bars(day) − gap_count` uses the day-intrinsic `expected_bars`, never the window-clipped legacy helper. **`gap_count` live-path sync (B2-F5):** the live hot-path `_update_coverage` (which today touches only `candle_count`) does NOT maintain `gap_count` on an interior-gap fill; SCOPE the invariant to POST-BACKFILL state — live-written rows carry `gap_count` PROVISIONAL (recomputed by the TASK-109 backfill/seal pass, or derived in the same upsert CTE if cheap), and `test_interior_gap_invariant` exercises the invariant on the LIVE write path explicitly (asserting provisional-until-sealed semantics), not only the backfill path. **`fetched_at` re-stamp is safe (B2-F1):** a post-seal `_update_coverage` re-stamping `fetched_at = now()` does NOT remove TTL-exemption — exemption is keyed off `sealed`, not NULL `fetched_at` — so no `CASE WHEN sealed` guard is required for correctness (a sealed day survives a subsequent `_update_coverage`).
- Test: `tests/backend/test_kline_cache_sealed.py::test_upsert_preserves_v58_columns`, `::test_interior_gap_invariant` (LIVE write path; provisional-until-sealed), `::test_sealed_day_survives_update_coverage` (a sealed row re-stamped by `_update_coverage` keeps `sealed`+exemption).

**TASK-114 — Boot wiring: RunReaper + readiness contract.** *(FR-039/052, REQ-MIG-010; AC-048a)* **— PREDECESSOR: TASK-215 wire-map MUST be GREEN first (B1-F3).**
- File: `backend/services/backtest_service.py` [MOD — lifespan startup], `backend/services/run_reaper.py` [NEW].
- Impl: `class RunReaper` invoked from `BacktestService` lifespan startup AFTER `schema_version=59` confirmed (v59 widens the `backtest_runs` status CHECK + adds `terminal_reason`/`stage_timings`, TASK-106b — so the CAS below is legal; before admission re-opens): every `status IN ('queued','running')` orphan of a prior generation is CAS-transitioned to `interrupted_by_restart` (→ terminal wire `failed`, FR-052) so the FE stops polling, releasing the `_MAX_CONCURRENT` slot + `AdmissionAccountant` reservation exactly once, writing `terminal_reason` + partial `stage_timings`/fingerprint; idempotent. **Because RunReaper PERSISTS `interrupted_by_restart` in P1, TASK-215's wire-map serializer MUST already be GREEN on every read surface (GET/LIST/MCP) in the SAME P1 deploy (B1-F3 phase-gate) — otherwise the raw enum reaches the FE and stop-polls.**
- Test: `tests/backend/test_backtest_service.py::test_run_reaper_reclaims_orphans`, `::test_run_reaper_idempotent`.

**TASK-115 — `BT_CACHE_SEALED_MANIFEST` escape-hatch flag.** *(FR-046, REQ-ROLL; AC-040)*
- File: `backend/services/capability_resolver.py` [NEW — created here, extended P4].
- Impl: P1 ships UNFLAGGED but the per-path flag `BT_CACHE_SEALED_MANIFEST` (default on) gives the sealed-manifest path a runtime fallback to the legacy count-based coverage (for emergency revert without redeploy).
- Test: `tests/backend/test_capability_resolver.py::test_sealed_manifest_flag_fallback`.

**TASK-116 — Pre-deploy migration gates.** *(REQ-ROLL-007/028/029, REQ-MIG-041)*
- File: `tests/backend/test_v58_migration.py` [MOD].
- Impl: restored-prod-clone rehearsal asserting within-budget apply + second-run no-op; CD promotion guard blocking any binary whose max-supported `schema_version` < the live DB's; verified restore-point before v58. (Platform may be TBD; the gates are required + tested where headless-feasible per N3.)
- Test: `::test_promotion_guard_blocks_downgrade`, `::test_restored_clone_rehearsal` (skips without `BACKTEST_TEST_DATABASE_URL`, N3).

**TASK-117 — `get_coverage_gaps` headless mock test (N3).** *(FR-020; AC-007 — headless)*
- File: `tests/backend/test_kline_cache_sealed.py` [MOD].
- Impl: validate the sealed-once guarantee via a MOCK Bybit client (`call_count==1`) WITHOUT Postgres — the engine/cache parity gate runs headless (N3). Any DB-only validation that cannot run headless is flagged in the morning report.
- Test: `::test_sealed_once_mock_client_headless`.

**TASK-118 — `backtest-cache/status` + `warmup` manifest-aware.** *(FR-036; AC-007c, K.1)*
- File: `backend/routers/backtest.py` [MOD — `/backtest-cache/status:159`, `/backtest-cache/warmup:184`].
- Impl: `/backtest-cache/status` UNCHANGED shape, now computed from `SealedManifest` (MAY add optional `sealed_days`/`negative_days` counts); `/backtest-cache/warmup` manifest-aware, idempotent, 0-call on a sealed range, per-request scope ceiling + per-client rate limit reject over-scope pre-fetch. **Future/inverted/oversized-range guard (B1-F9): `/backtest-cache/warmup` is a SEPARATE route from POST `/backtest` and the verified `warmup_cache` (backtest.py:184-208) has NO future-date guard and NO range-magnitude bound (only `symbols max_length=200`). Apply TASK-213's future/inverted 422 guard IDENTICALLY here — {future-dated end, `start ≥ end`, wholly-future window} → structured 422, `bybit_kline_calls==0` (no future day probed) — PLUS a max-range-span ceiling (a decade-wide warmup is rejected), so a wholly-future or oversized warmup cannot bypass the RC-3 future-probe protection and trigger a live Bybit fetch storm.**
- Test: `tests/backend/test_backtest_router.py::test_cache_status_manifest_shape`, `::test_warmup_zero_call_sealed`, `::test_warmup_over_scope_rejected`, `::test_warmup_future_date_422`, `::test_warmup_oversized_range_rejected`.

**TASK-119 — Deploy-quiesce before the v59 status-CHECK swap (liveness guard).** *(NFR-014/015, REQ-MIG-010; AC-012 extended)* **— NEW (B1-F7/B3-F5).**
- File: `backend/services/backtest_service.py` [MOD — lifespan boot, admission gate], `backend/async_persistence.py` [MOD — v59 swap gated behind quiesce].
- Impl: the v59 `backtest_runs` status-CHECK DROP+ADD takes ACCESS EXCLUSIVE; under `lock_timeout='30s'` (`:1599`) an in-flight backtest writing `backtest_runs` aborts the swap → the whole v59 txn rolls back, schema stays at 58. On a live trading host with continuous backtests the lock can be PERPETUALLY contended so v59 NEVER applies, leaving every P1 feature gated on `schema_version=59` (RunReaper/TASK-114, ensure_indexes/TASK-107, admission re-open) permanently OFF and v58-only (coverage cols present, control tables absent) — silent indefinite degradation, NOT self-healing. So BEFORE the v59 swap: (a) BLOCK new backtest admission (admission gate closed) and (b) drain/cancel in-flight `backtest_runs` writers (cooperative cancel + bounded wait), THEN run the ACCESS-EXCLUSIVE CHECK-widen step; bounded retry/backoff. If v59 cannot apply within N attempts, emit a STRUCTURED OPERATOR ALERT (not a silent retry-next-boot). **Boot contract (explicit, tested): `schema_version < 59` → admission STAYS CLOSED with a structured operator alert** (NOT silent degradation where the API looks up but control objects are absent). Reconciles §I.2/§P.3's prose "Quiesce/cancel in-flight backtests at deploy" into an OWNED task with a runbook step.
- Test: `tests/backend/test_v58_migration.py::test_v59_blocked_until_quiesced` (in-flight writer present → swap deferred behind quiesce, not aborted-and-stuck), `::test_v59_alert_after_n_attempts` (v59 un-appliable → structured alert emitted), `tests/backend/test_backtest_service.py::test_admission_closed_below_v59` (boot contract: `schema_version<59` keeps admission closed + alert, not silent half-on). (Real-DDL lane → `BACKTEST_TEST_DATABASE_URL` skip-guard, N3.)

### F.2 — Phase P2 tasks (batched loaders + parallel sweeps + drill-down)

**TASK-200 — `KlineStore` Postgres-tier seam.** *(FR-027, REQ-STORE-012..016; AC-014)*
- File: `backend/services/kline_store.py` [NEW — Postgres tier only at P2].
- Impl: `class KlineStore` with `async def get_klines_batch(self, symbols: list[str], interval, start, end) -> dict[str, KlineColumns]` — at P2 routes everything to Postgres SOR (the tier precedence is added at P5); dense output (every requested symbol gets an entry, including zero-row negative-cached); `async def iter_klines_streamed(...)` server-side-cursor seam bounding build-time peak — **this cursor seam OWNS the asyncpg-Record lifetime (B3-F4): it releases each asyncpg Record as it is consumed into the `KlineColumns` numpy arrays, so the peak-RSS Record-release logic lives HERE, not in `SoADatasetBuilder` (which only ever sees the finished numpy SoA)**; routes any range `≥ frontier` exclusively to Postgres; owns `kline_tier_hits` provenance. `KlineColumns` = `@dataclass(frozen=True, slots=True)` defined ONCE here (`open_time: np.int64[]`, OHLCV `np.float64[]`, all same length, ascending+deduped). **At P2 `KlineColumns` is INTERNAL to `KlineStore` (B2-F8) — the `_load_klines`→engine seam stays legacy `dict[symbol, list[dict]]` until the P3 SoA swap.**
- Test: `tests/backend/test_batched_loaders.py::test_klinestore_dense_output`, `::test_klinestore_streamed_cursor` (asserts Records released as consumed — peak bounded), `::test_klinecolumns_shape_contract`.

**TASK-201 — Batched `_load_klines` (N+1 → 1).** *(FR-027, REQ-PAR-039, NFR-006; AC-014/014a)*
- File: `backend/services/backtest_service.py` [MOD — `_load_klines:968`].
- Impl: replace per-symbol queries with one batched `WHERE symbol = ANY($1) AND interval = $2 AND open_time BETWEEN $3 AND $4 ORDER BY symbol, open_time`; bucket into strictly-ascending per-symbol arrays BYTE-IDENTICAL to per-symbol `ORDER BY open_time`; per-run round-trip SUM O(1) in scan/candle count with fixed parameterized text. Batched `scan_source`/`ScanContext` load byte-identical to the legacy per-scan load; duplicate/overlapping scan rows → no double-anchor/no double re-arm. **Seam type at P2 (B2-F8 — disambiguate "arrays"): the `_load_klines`→engine contract STAYS legacy `dict[symbol, list[dict]]` at P2.** `KlineColumns` (frozen numpy SoA, TASK-200) remains INTERNAL to `KlineStore` and is surfaced to the engine ONLY at the P3 SoA swap (TASK-301/305, behind `BT_ENGINE_SOA`). The P2 engine is unmodified and consumes the legacy per-row `dict` shape (each row byte-identical to the legacy `get_klines` row); emitting `KlineColumns` to the unmodified P2 engine would break it. The "strictly-ascending per-symbol arrays" wording above means the bucketed `list[dict]` ordering, NOT numpy SoA, at P2.
- Test: `tests/backend/test_batched_loaders.py::test_single_batched_query`, `::test_batched_buckets_byte_identical`, `::test_duplicate_scan_rows_no_double_anchor`, `::test_load_klines_p2_returns_legacy_listdict` (B2-F8: the P2 `_load_klines`→engine seam returns `dict[symbol, list[dict]]`, not `KlineColumns`).

**TASK-202 — `DrilldownLoader` lazy per-symbol 1m.** *(FR-028/029/030, REQ-DRILL-013/020/023; AC-015/015a/015b)*
- File: `backend/services/drilldown_loader.py` [NEW].
- Impl: `class DrilldownLoader` with `async def fine_window(self, requests: list[tuple]) -> dict` — prefetch 1m windows for exactly the `(symbol, bar_open_epoch)` pairs derived from the completed Phase-A trade list (entry bar + forward neighbour + exit ±1) via `asyncio.gather`; in-process memo so a rerun issues ZERO LTF fetches; per-bar fetch failure falls back to 5m for THAT bar only (never aborts, never persists partial 1m, stays non-optimistic); no-1m-candles drill falls back to 5m and never fabricates a fill. No LTF fetch on bars touching neither/exactly-one level. **FULL-BOOK portfolio-equity coverage pass — MANDATORY (B4-F2, verified the pass EXISTS at backtest_service.py:1043-1061; omitting it diverges drill SELECTION):** the window set is NOT only "entry+neighbour+exit±1". The current `_build_fine_klines` adds a SECOND window source: for every PORTFOLIO-reason close (`equity_drop`,`equity_drop_smart`,`equity_rise`,`close_on_profit`) it adds the firing bar ±1 to EVERY OTHER position open across that firing instant — because the engine's 1m portfolio-equity walk only engages on a bar when EVERY open position has a 1m window (equity is a book-wide sum). Port this pass verbatim into the loader's window-derivation: for each portfolio-reason close, compute `open_from=_bar_open_epoch(entry)`/`open_until=_bar_open_epoch(exit)` for every trade and, if `open_from ≤ fire_epoch ≤ open_until`, add `{fire−bar_s, fire, fire+bar_s}` to that symbol. DROPPING this makes portfolio mass-closes lose 1m windows for co-open positions → drill on/off SELECTION diverges, breaking AC-015 ("drill on/off identical SELECTION"). (§K row §3.5 already claims the loader has "full-book-coverage" — this makes the buildable task match the component summary.)
- Test: `tests/backend/test_drilldown_loader.py::test_lazy_no_fetch_single_level`, `::test_rerun_zero_fetch_memo`, `::test_per_bar_fallback_non_optimistic`, `::test_drill_linear_scaling`, `::test_full_book_portfolio_coverage` (AC-015/015a: a co-open position receives the portfolio-close firing bar ±1; a regression that drops co-open coverage fails CI).

**TASK-203 — Drill seam: service producer + engine consumer (decisions frozen).** *(FR-029, NFR-008; AC-015)*
- File: `backend/services/backtest_service.py` [MOD — `_build_fine_klines:987` producer + call site `:833`, the DrilldownLoader swap target — this method is async/DB-bound (uses `_kline_cache`/`_fetch_klines_from_bybit`) and lives in the SERVICE, not the engine]; `backend/services/backtest_engine.py` [MOD — the engine's `self._fine_klines` consumption seam ONLY (`run()` param `:131`, consumed at `769`/`914`/`1496`), decisions FROZEN].
- Impl: replace the SERVICE `_build_fine_klines` producer with a `DrilldownLoader` call (TASK-202); the engine CONSUMES the produced `fine_klines` unchanged. Trade SELECTION identical drill on/off (same positions opened, same close rules same order) — ONLY intrabar fill PRICE may differ. **The handshake matches the ACTUAL two-`run()` structure (B4-F1 — verified `grep drill_request` over backtest_engine.py returns NOTHING; the engine does NOT emit drill requests):** the Phase-A `engine.run()` (`backtest_service.py:828`) returns the TRADE LIST (unchanged); `_build_fine_klines` (`:833`, signature `_build_fine_klines(self, config, trades)`) DERIVES the 1m windows from that completed trade list OFF-KERNEL (entry/exit datetimes + the full-book portfolio pass, TASK-202); the Phase-B `engine.run()` (`:838`) re-resolves ONLY flagged exit PRICES + reconciles the realized-wallet trajectory (the three-way Σ holds on the drill lane). The existing two-`run()` orchestration structure is PRESERVED — NO "Phase-A emits drill_requests" notion is introduced (there is no such engine seam).
- Test: `tests/backend/test_drilldown_loader.py::test_selection_identical_drill_on_off`, `::test_drill_three_way_reconciles`.

**TASK-204 — Entry-bar drill fixture path.** *(REQ-DRILL-022, FR-030; AC-015c, T.4c)*
- File: `backend/services/drilldown_loader.py` [MOD], `tests/backend/test_drilldown_loader.py` [MOD].
- Impl: when the entry-fill bar's own `[low,high]` spans a TP/SL/liq barrier, drill the ENTRY bar, replay 1m sub-bars chronologically, resolve entry FILL first then the first touched level with pessimistic liq→SL→TP, non-optimistic vs the always-LTF oracle. DISTINCT from same-bar exit-eligibility (5m) and mid-life both-levels cases.
- Test: `::test_entry_bar_spans_barrier_drill`.

**TASK-205 — Two-sided sandwich + non-optimism property test.** *(FR-030, NFR-008, REQ-DRILL-018; AC-015a, T.4)*
- File: `tests/backend/test_drilldown_loader.py` [MOD].
- Impl: randomized property test — for EVERY drilled trade: drilled PnL ≤ always-LTF oracle (non-optimistic) AND ≥ coarse pessimistic bound; entry slippage applied same direction/bps as the 5m path; the always-LTF reference self-validates to the exact coarse-5m result on no-ambiguity bars.
- Test: `::test_two_sided_sandwich_property`, `::test_always_ltf_reduces_to_coarse`.

**TASK-206 — `SweepRunner` parallel combos.** *(FR-031/032, NFR-005, REQ-SWEEP-002/003/006/008/009; AC-016/017/019)*
- File: `backend/mcp/tools/optimizer/sweep_runner.py` [NEW], `backend/mcp/tools/optimizer/sweep_tools.py` [MOD].
- Impl: `class SweepRunner` — parallel combo execution; host selection via `USE_PROCESS_POOL = HAS_NUMBA AND shared_memory-usable AND start_method=='spawn'` (Windows-11 prod → ProcessPool + `shared_memory`; else `ThreadPoolExecutor` over the `nogil=True` kernel; seq fallback); shipped-once shared inputs (at P2 shares legacy per-symbol kline lists; compact SoA lands P3); parent-side pool pre-warm; `finally`-scoped release of all `shared_memory` segments on every terminal path (Windows last-handle-close); live-breaker dispatch gate; coerces `drilldown_enabled=false` for the combo (PROPOSED config preserves the user's value). **Speedup floor ≥0.7×min(M,K,concurrency) binds ONLY on the numba+ProcessPool lane** (AC-016); on a no-numba host the ThreadPool-over-GIL-bound-pure-Python P2 engine yields ~zero real speedup (the `nogil=True` kernel does not exist until P4), so AC-016's floor is WAIVED-by-capability and the documented no-numba expectation is SEQUENTIAL sweeps — AC-016 is NOT asserted where it cannot hold. IPC/pickling bytes independent of combo count. **Worker env minimization (REQ-SEC-006, B1-F1/B5-F4 — owns §L.4's control, previously orphaned):** on the verified Windows `spawn` prod path a child INHERITS the full parent environment by default, so every sweep worker would carry `ACCOUNTS_ENCRYPTION_KEY`/`DATABASE_URL`. The pool is constructed with a child bootstrap (`ProcessPoolExecutor(initializer=_worker_env_bootstrap)` AND/OR `env=`-scrubbed spawn) that, BEFORE any user code runs, RESETS `os.environ` to a SUBSET of a CLOSED ALLOWLIST (only the keys the kernel needs: e.g. `PATH`, `SYSTEMROOT`, `NUMBA_CACHE_DIR`, `BT_*` non-secret accel flags, `TZ`). The forbidden-set `PG*`/`PGPASSWORD`/`PGSSLKEY`/`PGSERVICEFILE`/`DATABASE_URL`/`ACCOUNTS_ENCRYPTION_KEY`/secret-`BT_*` is ABSENT from the worker env even when the parent has them set.
- Test: `tests/backend/test_sweep_runner.py::test_process_pool_predicate`, `::test_speedup_floor`, `::test_ipc_independent_of_combo_count`, `::test_shared_memory_no_leak_terminal`, `::test_sweep_combo_equals_standalone`, `::test_worker_env_excludes_secrets` (REQ-SEC-006: a REAL spawned worker's `os.environ` has `ACCOUNTS_ENCRYPTION_KEY`/`DATABASE_URL`/`PG*`/`PGPASSWORD`/secret-`BT_*` ABSENT even when set in the parent; assert the env is a subset of the closed allowlist).

**TASK-207 — `PreflightEstimator` + `AdmissionAccountant` (RSS at P2).** *(FR-039/040/049, NFR-012/024, REQ-PERF-037/038/039; AC-018-RSS/048d)*
- File: `backend/services/preflight_estimator.py` [NEW].
- Impl: `class PreflightEstimator` with `def predict(self, config) -> Envelope` — `predicted_engine_work = a·light_advance_count(≈total_candles) + b·heavy_eval_count(≈ticks×B)` (NOT `candles×scans×B`), plus cold Bybit pages `ceil(missing/1000)`, drill fraction, cold-columnar term; `class AdmissionAccountant` reservation/queue. At P2: reject a WIDE run whose FINAL SoA exceeds the klines budget with the 4xx contract BEFORE a slot (`predicted_rss > tier_budget/2` where `tier_budget` is the symbol-scaled `BT_RSS_BUDGET` tier — CANONICAL 1GB / WIDE-HEAVY 1.75GB / HEAVIEST 2GB per §P.4/NFR-012, so a HEAVY/HEAVIEST run is judged against its OWN tier, not a flat 1GB; `under_estimate_margin=1.0`); aggregate-RSS rule (`Σ reserved per-run peak RSS + sweep-pool footprint ≤ BT_RSS_BUDGET` total host budget). The wall-time reject term moves to P3 (no realized wall budget at P2).
- Test: `tests/backend/test_preflight_estimator.py::test_wide_rss_reject`, `::test_aggregate_rss_reject`, `::test_in_budget_admits_no_false_reject`.

**TASK-208 — Cross-process sweep cancel under SAFE_MODE.** *(FR-044, FR-031, NFR-018; AC-048e)*
- File: `backend/mcp/tools/optimizer/sweep_runner.py` [MOD].
- Impl: abort reaches child PROCESSES via a cross-process mechanism (pool `terminate()` and/or a per-worker cancel flag in `shared_memory`) — NOT the parent's `threading.Event` (a child process cannot observe it); completes within a bounded wall-clock (not 120s/combo); no leaked `shared_memory` segments.
- Test: `tests/backend/test_sweep_runner.py::test_cross_process_cancel_bounded`, `::test_cancel_no_leaked_segments`.

**TASK-209 — `metrics` single-pass O(curve+trades).** *(NFR-006, REQ-PERF-032/017/020; AC-048i)*
- File: `backend/services/backtest_metrics.py` [MOD].
- Impl: metrics compute O(curve+trades) single-pass — NO O(n²) drawdown/run-up rescan; a curve-DOUBLING micro-gate stays ≤~2×. Preserves `metrics.total_trades` invariant.
- Test: `tests/backend/test_backtest_metrics.py::test_metrics_single_pass_no_quadratic`, `::test_total_trades_present`.

**TASK-210 — Progress emission + warmup collapse.** *(NFR-006, REQ-PERF-035; AC-048i)*
- File: `backend/services/backtest_service.py` [MOD — progress + `_WARMUP_BAND:57` (the constant + its progress-banding uses at `:740`/`:819`/`:826-836` are in the SERVICE, not the engine)].
- Impl: first progress signal <1s after run start (bounded, candle-count-independent); total progress writes O(100) regardless of candle count at <2% overhead; the P1 cache-fix collapses the `_WARMUP_BAND` (10%) stage to a bounded constant independent of pre-window history.
- Test: `tests/backend/test_backtest_performance.py::test_first_progress_under_1s`, `::test_progress_writes_flat`, `::test_warmup_band_collapsed`.

**TASK-211 — Atomic single-transaction persistence + torn-persist guard.** *(FR-038, NFR-009; AC-048c)*
- File: `backend/services/backtest_service.py` [MOD — persist path, `:1500-1538`].
- Impl: **CORRECTED to the VERIFIED real shape (B2-F2 — the prior "3-write COPY + separate equity_curve JSONB" was wrong on three counts):** the persist is ALREADY ONE `conn.transaction()` (`:1500`) containing, in order: (1) `INSERT INTO backtest_results … ON CONFLICT(run_id) DO UPDATE` where `equity_curve` is a COLUMN of that row (`:1503-1511`, NOT a separate write — re-persist is a SUPPORTED path via the upsert), (2) an idempotent `DELETE FROM backtest_trades WHERE run_id=$1` (`:1516`) FOLLOWED BY `executemany` INSERT of the trades (`:1518`), (3) the `UPDATE backtest_runs SET status='completed'` flip (`:1535`). The task PRESERVES this exact shape: a fault between any pair rolls back ALL of it (run NOT marked `completed`). **KEEP the idempotent `DELETE`-before-insert** — `backtest_trades.id` is `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` with NO natural unique key on `run_id`, so switching trades to `copy_records_to_table` WITHOUT the DELETE would DUPLICATE every trade on any re-persist; if an implementer adopts COPY for speed, the DELETE MUST stay. **The `status='completed'` flip STAYS INSIDE this transaction and is the JOIN POINT with TASK-212's terminal CAS** (the CAS coordinates with this in-txn flip; they are not independent writes). `GET /backtest/{id}` read-side guard returns the structured integrity error on a torn/duplicated/dropped/sign-flipped trade (`Σ(trade.pnl)≠net_profit` trips) — never a silently-wrong render or no-trades fallback.
- **Validation lane (B3-F7):** TASK-211 asserts Postgres TRANSACTION semantics (rollback). Like the P1 migration tests (N3), the rollback/torn-persist assertions need a real DB — carry the `BACKTEST_TEST_DATABASE_URL` skip-guard; AC-048c is recorded UNVALIDATED-headless in §I.5 + the morning report when the Postgres lane is absent (the integrity-error read-side guard IS mock-validatable; the in-txn rollback is NOT).
- Test: `tests/backend/test_backtest_service.py::test_atomic_persist_rollback` (fault mid-transaction rolls back results+trades+status; DB lane), `::test_persist_idempotent_no_duplicate_trades` (re-persist the SAME run_id → trade count UNCHANGED — catches a dropped DELETE, which `test_atomic_persist_rollback` cannot; DB lane), `::test_torn_persist_integrity_error` (read-side `Σ≠net_profit` guard; mock-validatable headless).

**TASK-212 — Terminal-state CAS + queue-drain.** *(FR-039, REQ-API-012/015; AC-042/048b/048h)*
- File: `backend/services/backtest_service.py` [MOD — admission/terminal, `create_backtest:191`, `_MAX_CONCURRENT:50`].
- Impl: concurrent timeout-kill + natural-finish + `POST /cancel` race → exactly one terminal state, no invalid transition, no double-start, no stuck `queued`, slot+reservation release exactly once; queue-drain promotes exactly one queued run (FIFO oldest `queued_at`) on slot release; `BT_QUEUE_MAX_DEPTH=16` reject + `BT_QUEUE_WAIT_TIMEOUT_MS=120000` `queued_timeout`. **EFFECTIVE `_MAX_CONCURRENT=1 on the no-numba lane is an ADMISSION-LEVEL gate, NOT a pool resize:** the `ThreadPoolExecutor` is constructed ONCE at `__init__` (`backtest_service.py:103`, `max_workers=_MAX_CONCURRENT=3`, module constant `:50`) and stays fixed-size; the CapabilityResolver-driven admission gate counts active no-numba runs and QUEUES/defers a 2nd concurrent no-numba run (effective cap=1) while the numba lane still allows 3 — the pool is never recreated. **The resolved slot count is RECORDED in the run manifest as `effective_max_concurrent` (B5-F6 — AC-044's falsifiable clause; a regression dropping it would otherwise pass since the prior P4 manifest fields were only `accel_waived`/`perf_baseline_waived`).** (AC-044/048b.)
- **Validation lane (B3-F7):** the terminal-CAS / queue-drain assertions exercise Postgres CAS semantics — carry the `BACKTEST_TEST_DATABASE_URL` skip-guard (N3); AC-042 is recorded UNVALIDATED-headless in §I.5 + the morning report where the Postgres lane is absent (the in-process state-machine arbitration is mock-validatable; the DB-side CAS atomicity is NOT).
- Test: `tests/backend/test_backtest_service.py::test_terminal_state_race_single_winner`, `::test_queue_drain_fifo_promote`, `::test_queue_depth_reject`, `::test_effective_max_concurrent_no_numba` (a 2nd concurrent no-numba run is queued/deferred while a numba lane admits 3; pool stays fixed-size at `__init__`), `::test_effective_max_concurrent_recorded_in_manifest` (B5-F6 — the resolved slot count is written to the run manifest).

**TASK-213 — Future/inverted date_range disposition.** *(S.15, FR-023, K.3; AC-048j)*
- File: `backend/routers/backtest.py` [MOD], `backend/mcp/tools/optimizer/sweep_tools.py` [MOD].
- Impl: {future-dated end, `start ≥ end`, wholly-future window} → structured 422 (K.3 reject contract, NOT a zero-trade row) IDENTICALLY on HTTP + MCP; no future day probed/sealed (`bybit_kline_calls==0`).
- Test: `tests/backend/test_backtest_router.py::test_future_date_422`, `::test_inverted_range_422`, `tests/backend/mcp/test_p3_backtest_debug.py::test_mcp_future_date_422`.

**TASK-214 — Non-spoofable admission identity.** *(FR-039, REQ-SEC-005, NFR-021; AC-048k)*
- File: `backend/routers/backtest.py` [MOD — `_client_id:46`].
- Impl: per-client rate limit + warmup scope ceiling + `BT_QUEUE_MAX_DEPTH` bind as ONE identity. **Two identity modes (B1-F10 — bare-peer is correct ONLY on a direct-exposure deploy):** (a) DIRECT-EXPOSURE deploy (no proxy) → identity = the kernel-peer key (`request.client.host`, the verified `_client_id:46`); rotating `X-Forwarded-For`/`X-Real-IP`/`Forwarded` cannot mint distinct clients. (b) PROXIED deploy (the documented environment runs a proxy at `localhost:4141`, and prod commonly fronts FastAPI with a reverse proxy) → EVERY request's peer is the proxy IP, so bare-peer COLLAPSES all clients into ONE bucket (a global single-bucket DoS: one abuser starves everyone, or forces a uselessly high limit). For any proxied deploy, the DEFAULT-configured identity is trusted-proxy XFF/`Forwarded` parsing WITH the operator allowlist: the last UNTRUSTED hop (the right-most address not in the trusted-proxy allowlist) is the identity. This is non-spoofable (a client cannot forge a hop the trusted proxy didn't append) AND discriminating (distinct real clients behind the proxy get distinct buckets). Document that bare-peer identity is correct ONLY on a direct-exposure deploy; the allowlist-XFF path is REQUIRED on a proxied deploy or the limiter is non-discriminating.
- Test: `tests/backend/test_backtest_router.py::test_header_rotation_one_identity` (direct-exposure: rotating XFF cannot mint clients), `::test_trusted_proxy_last_hop` (allowlist parsing picks the last untrusted hop), `::test_proxied_clients_distinct_identity` (B1-F10: two real clients behind a trusted proxy get DISTINCT buckets — the limiter does not collapse to one global bucket).

**TASK-215 — Status→wire-map serializer (the GREEN owner for T.9).** *(FR-052, REQ-API-012; AC-042, T.9)* **— SEQUENCED IN P1 (B1-F3), a HARD PREDECESSOR of TASK-114/TASK-212.**
- File: `backend/services/backtest_service.py` [MOD — `_build_results:476` + LIST route `:67`], `backend/mcp/tools/optimizer/*` [MOD — `backtest_get`/`scans_get` serializers].
- **Phase placement (B1-F3):** although listed here under F.2, this serializer SHIPS IN P1 and MUST be GREEN BEFORE any writer can persist a non-legacy status literal — TASK-114 (RunReaper, P1) CAS-transitions boot orphans to `interrupted_by_restart`, and TASK-212 (queue-drain, P2) persists `queued`. If the wire-map shipped only at P2, every read surface (GET/LIST/MCP) between the P1 and P2 deploys would serialize the raw `interrupted_by_restart` enum to the verified FE (`BacktestResultsPage.tsx`/`types.ts isPending`), which blanks/stop-polls on an unknown enum — the exact regression §J.1 warns against. **Phase-gate invariant (added to E.1 + every later phase): every PERSISTED status literal maps to a legacy-5 wire value on ALL read surfaces, asserted GREEN in the SAME phase that first writes the literal** (P1 for `interrupted_by_restart`, P2 for `queued`).
- Impl: the internal statuses `queued`/`interrupted_by_restart`/`failed_with_timeout` must be MAPPED to the legacy 5 wire values BEFORE serialization on EVERY read surface: `GET /backtest/{id}` (`_build_results:476`), the LIST endpoint (`:67`), AND MCP `backtest_get`/`scans_get` — `queued→pending`, `interrupted_by_restart→failed`, `failed_with_timeout→failed` (J.1). TASK-114/TASK-212 only perform DB-side CAS transitions INTO the new internal states; WITHOUT this serializer map the verified FE (`BacktestResultsPage.tsx`, `types.ts isPending`) receives an unknown enum and stop-polls (the exact regression J.1 warns against). This is the implementing task the T.9 status-wire-map test (M.7) binds to.
- Test: `tests/backend/test_backtest_schemas.py::test_status_wire_map_get`, `::test_status_wire_map_list`, `tests/backend/mcp/test_p3_backtest_debug.py::test_status_wire_map_mcp`, `tests/backend/test_backtest_schemas.py::test_no_read_surface_emits_nonlegacy_status` (phase-gate: scans GET/LIST/MCP serializers, asserts no non-legacy literal reaches the wire — runs at P1 and re-asserts every later phase).

**TASK-216 — `_downsample_equity` force-include global max-equity peak (NET-NEW, not a preserved invariant).** *(FR-052; AC — P2/cross)*
- File: `backend/services/backtest_service.py` [MOD — `_downsample_equity:491-521`].
- Impl: verified current code (`:491-521`) force-includes ONLY the global max-drawdown trough (min `drawdown_pct`); it does NOT force-include the global max-equity peak — so the peak-inclusion J.1 describes is NET-NEW behavior, not a preserved invariant. Modify the LTTB downsample to ALSO force-include the global max-equity-peak index (alongside first point, last point, max-DD trough) so the rendered GET-view curve cannot hide EITHER path-dependent extreme. The manifest still hashes the FULL pre-downsample JSONB (this changes only the GET view, not parity), so it does not touch the DISCRETE/MONEY fingerprint.
- Test: `tests/backend/test_backtest_service.py::test_downsample_includes_max_equity_peak` (a curve whose LTTB would otherwise DROP the peak asserts the peak index is force-kept), `::test_downsample_still_includes_trough_and_endpoints`.

**TASK-217 — Partial-telemetry persistence on the in-process 120s kill / cancel / degrade.** *(FR-041, NFR-009; AC-048l)* **— NEW (B5-F1, closes the orphaned AC-048l).**
- File: `backend/services/backtest_service.py` [MOD — the 120s `threading.Timer` kill path + `POST /cancel` + mid-run degrade terminal handler].
- Impl: AC-048a (RunReaper, TASK-114) writes partial `stage_timings`/fingerprint ONLY on the crash/restart-orphan path; AC-042 (TASK-212) arbitrates terminal state but NOT partial telemetry. The NORMAL in-process 120s `threading.Timer` kill, the `POST /cancel` path, and a mid-run degrade currently persist NO forensic telemetry — yet R.1/V-10 re-target P4 from exactly these `stage_timings`/`engine_fingerprint`. On EACH of {120s Timer kill, `POST /cancel`, mid-run degrade}, persist `backtest_runs.stage_timings` + `engine_fingerprint` + `terminal_reason` + an aborted-stage marker, with `Σ(exclusive stage timings) == elapsed ± tol`, and ensure the cache counters (`bybit_kline_calls`/`kline_tier_hits`) SURVIVE the kill (not reset). A regression dropping `stage_timings`/`engine_fingerprint` on a 120s kill MUST turn a test RED (the spec's stated gap — "would fail no test" — is closed).
- Test: `tests/backend/test_backtest_service.py::test_partial_telemetry_persisted_on_120s_kill` (Timer kill persists stage_timings+fingerprint+terminal_reason; Σ(exclusive)==elapsed±tol; counters survive), `::test_partial_telemetry_on_cancel`, `::test_telemetry_meta_drop_turns_red` (a meta-test removing the telemetry write turns RED — teeth).

**TASK-219 — `GET /backtest-runtime/status` route + privilege split.** *(REQ-SEC-005, NFR-021; AC-044/048k)* **— NEW (B1-F2, the implementing owner for §H.2/§G.1's route; previously attributed to non-implementing tasks).**
- File: `backend/routers/backtest.py` [MOD — add the route + `_status_privilege(request)` helper].
- Impl: implement the additive `GET /backtest-runtime/status` route (§H.2) — reads the `CapabilityResolver` snapshot. PUBLIC payload coarsened to capability booleans + active/degraded/off + breaker/seal-backfill/pitr state enums + `schema_ok: bool` (NO exact versions/git-SHA/integer `schema_version`/numeric resource config). `_status_privilege(request)` returns privileged ONLY when the auth token matches (constant-time compare) BY DEFAULT (`BT_STATUS_TRUST_PEER_LOOPBACK=false`); kernel-peer-loopback alone is sufficient ONLY when an operator sets `BT_STATUS_TRUST_PEER_LOOPBACK=true` on a verified no-proxy deploy. **A forwarding header (`X-Forwarded-For`/`Forwarded`) can NEVER promote a request to privileged** (the privilege decision uses the kernel-peer + token, never a forwarded header). Per-client rate limited (shares TASK-214 identity). Path PINNED to `/backtest-runtime/status` (distinct prefix; `/backtest/{run_id}` never shadows it).
- Test: `tests/backend/test_backtest_router.py::test_status_route_resolves`, `::test_status_route_coarsened_public` (public payload omits versions/git-SHA/numeric schema_version/resource numerics), `::test_status_route_forwarding_header_never_privileged` (a forged `X-Forwarded-For` loopback does NOT promote), `::test_status_route_token_constant_time`, `::test_status_route_run_id_status_not_shadowed`, `::test_status_route_rate_limited`.

**TASK-220 — Boundary symbol-charset validation + columnar canonical-path containment.** *(REQ-SEC-003/004; AC-036)* **— NEW (B1-F4, fail-closed before SQL/path code).**
- File: `backend/routers/backtest.py` [MOD — `/backtest:52` + `/backtest-cache/warmup:184`], `backend/mcp/tools/optimizer/sweep_tools.py` [MOD — MCP surfaces], `backend/services/columnar_writer.py` [MOD — P5], `backend/services/columnar_reader.py` [MOD — P5].
- Impl: symbols (`list[str]`, verified bounded only by `max_length` at backtest.py:187 — NO charset) flow into Parquet symbol→month partition PATHS (TASK-501) and DuckDB read PATHS (TASK-502); a symbol like `../../etc`, one containing path separators, a glob, or NUL enables traversal out of `BT_COLUMNAR_DIR`. **At the BOUNDARY (`/backtest`, `/backtest-cache/warmup`, MCP sweep surfaces): reject any symbol not matching a strict allowlist charset `^[A-Z0-9]+$` (the tradable-universe shape) with the K.3 4xx contract BEFORE it reaches SQL/path code.** In `columnar_writer`/`columnar_reader`, additionally assert the RESOLVED path `Path.resolve().is_relative_to(BT_COLUMNAR_DIR)` (canonical-containment / `os.path.commonpath`) and FAIL CLOSED — defence-in-depth even if a symbol slipped the charset gate. The charset gate is the P2 boundary half; the path-containment assertion lands with the P5 columnar writer/reader.
- Test: `tests/backend/test_backtest_router.py::test_symbol_charset_rejected` (a traversal/glob/NUL symbol is 4xx-rejected at `/backtest` + `/backtest-cache/warmup`), `tests/backend/mcp/test_p3_backtest_debug.py::test_symbol_charset_rejected_mcp`, `tests/backend/test_columnar_security.py::test_columnar_path_containment` (P5: a crafted traversal symbol cannot escape `BT_COLUMNAR_DIR` — resolved path containment fails closed).

**TASK-220b — `bt_flag_config` write-surface lockdown (preventive control).** *(REQ-SEC-006/007; AC-047)* **— NEW (B1-F6/B5-F3, the preventive control; the detective `bt_flag_audit` alone was unowned).**
- File: `backend/services/capability_resolver.py` [MOD — read-only handle], `backend/routers/backtest.py` [MOD — no write path], `backend/mcp/tools/optimizer/*` [MOD — no write path], `backend/services/maintenance_admin.py` [MOD — the ONLY write boundary].
- Impl: any public HTTP route or MCP tool attempting to WRITE `bt_flag_config` (INCLUDING setting SAFE_MODE off) is REJECTED; writes succeed ONLY from the operator boundary (`MaintenanceAdmin` CLI / loopback / authenticated-admin — the SAME gate as schema maintenance). The `CapabilityResolver` resolver path and the `GET /backtest-runtime/status` route hold READ-ONLY handles to `bt_flag_config` (no write method reachable from an HTTP/MCP request). Distinct from AC-047a (TASK-508 shadow/dark-compare).
- Test: `tests/backend/test_capability_resolver.py::test_flag_write_rejected_from_public_http` (incl. an attempt to disable SAFE_MODE), `::test_flag_write_rejected_from_mcp`, `::test_flag_write_allowed_from_operator_boundary`.

### F.3 — Phase P3 tasks (SoA + merge-walk engine; PURE PYTHON, bit-identical)

**TASK-300 — `SoADatasetBuilder` columnar dataset.** *(FR-015/017, NFR-003/012, REQ-ENG-001..007, REQ-PERF-006/007/008/044; AC-020/023)*
- File: `backend/services/soa_dataset_builder.py` [NEW].
- Impl: `class SoADatasetBuilder` with `def build(self, klines: dict[str, KlineColumns]) -> SoADataset` — each symbol already SoA from `KlineStore` (`open_time:int64[]`, OHLCV:`float64[]`); parse each candle ONCE (no per-row dict + six `float()` casts); `def global_timeline(self) -> np.int64[]` precomputes the sorted-unique union timeline (its OWN `timeline_bytes` budget line); vectorized scan-anchor `searchsorted` binding computed ONCE; degenerate-run short-circuit <100ms. **Memory ownership (B3-F4): the builder receives `KlineColumns` (already numpy SoA — `KlineStore` has ALREADY converted asyncpg Records to numpy), so it NEVER holds Records to release; the asyncpg-Record-release / server-side-cursor clause lives on `KlineStore.iter_klines_streamed` (TASK-200/305), NOT here. The builder only ASSERTS it never materializes a SECOND copy of the np arrays (it views/reuses the `KlineColumns` arrays, no duplicate allocation).**
- Test: `tests/backend/test_soa_builder.py::test_soa_parse_once`, `::test_global_timeline_sorted_unique`, `::test_scan_anchor_searchsorted`, `::test_degenerate_short_circuit_100ms`, `::test_builder_no_second_array_copy` (B3-F4: build does not duplicate the `KlineColumns` np arrays).

**TASK-301 — Merge-walk pointer engine (kills RC-1).** *(FR-015/016, REQ-ENG; AC-021/022)*
- File: `backend/services/backtest_engine.py` [MOD — replace `_evaluate_candles_until:1177` window rebuild].
- Impl: replace the per-scan full re-scan (`symbol_time_idx` + `all_timestamps` rebuilt by walking every open symbol's ENTIRE kline list with `continue` not `break`) with **per-symbol advancing index pointers that NEVER reset** + `searchsorted` O(log N) window bounds. **Pin the side exactly to the legacy EXCLUSIVE-both-ends window** (`backtest_engine.py:1205-1208` skips `kt <= start_time` and `kt >= end_time`): lower bound = `searchsorted(open_time, start_time, side='right')` (strict `> start`), upper bound = `searchsorted(open_time, end_time, side='left')` (strict `< end`) — this is the exact off-by-one that breaks boundary-bar parity (AC-022) if a side is wrong. Setup scales with window size, NOT `N_total`. Decisions FROZEN (this re-points HOW prices are located, not WHICH decisions are made). Boundary-bar exit fires EXACTLY the same scan/bar as the legacy window scan.
- Test: `tests/backend/test_merge_walk_engine.py::test_setup_constant_4x_history`, `::test_boundary_bar_same_scan`, `::test_merge_walk_pointers_never_reset`.

**TASK-302 — `searchsorted` mark-seeding (kills RC-2).** *(FR-017, S.8; AC-023)*
- File: `backend/services/backtest_engine.py` [MOD — replace the linear-prefix re-seed].
- Impl: replace the O(P×T²) carried-position mark re-seed (linear prefix scan from index 0 every scan) with `searchsorted` O(log N) lookup. Legacy (`backtest_engine.py:1227-1235`) initializes `mark = p.entry_price` and overwrites ONLY when a candle with `open_time <= start_time` exists. Pin the side exactly: `idx = searchsorted(open_time, start_time, side='right') - 1` for the inclusive `<= start` last-close; **idx==0 (no candle at/before start) MUST fall back to the initialized `entry_price` mark — NOT `klines[idx-1]==klines[-1]`, which is a silent negative-index wraparound that look-aheads to the LAST candle (a WRONG-VALUE bug, not an `IndexError`)**. Bit-identical to the linear-prefix oracle including the epoch-vs-datetime `open_time` case + empty/single-candle boundary arrays, with NO `IndexError` and NO negative-index wraparound.
- Test: `tests/backend/test_merge_walk_engine.py::test_mark_seeding_bit_identical`, `::test_mark_seeding_epoch_vs_datetime`, `::test_mark_seeding_empty_single_candle`, `::test_mark_seeding_no_prior_candle_uses_entry_price` (idx==0 falls back to `entry_price`, asserts no wraparound to `klines[-1]`).

**TASK-303 — Window-aware adaptive-blacklist ring counter.** *(REQ-PERF-010, REQ-PAR-026; AC-006b re-assert)*
- File: `backend/services/backtest_engine.py` [MOD — `_is_adaptively_blacklisted`].
- Impl: replace the per-position full history scan with a **time-bucketed ring of per-symbol `(wins,total)` counters** keyed to the lookback granularity, expiring buckets as simulated time advances (amortized O(1) per close + O(expired) per tick) — bit-identical to the legacy SLIDING-WINDOW win-rate over a fixture crossing the 48h boundary. Trades aging out drop from BOTH wins and total.
- Test: `tests/backend/test_merge_walk_engine.py::test_adaptive_blacklist_ring_equivalence`.

**TASK-304 — Precomputed funding-boundary bar indices.** *(REQ-PAR-013; AC-006d re-assert)*
- File: `backend/services/backtest_engine.py` [MOD — funding].
- Impl: precompute the funding-boundary bar indices from the int64 timeline BEFORE the loop (zero `datetime` in-kernel). **Pinned to legacy EXACTLY** (`backtest_engine.py:1262` gates on `hour in (0,8,16) AND candle_time.minute < 5`): for each uncharged funding slot {0,8,16}h, select the FIRST stored bar of that `(date,hour)` slot AND require that bar's `minute < 5`; if the slot's first stored bar is `minute ≥ 5` (gapped boundary — no bar landed in the first 5 min), charge NOTHING for that slot (match the legacy SKIP — do NOT charge the next available bar; epoch-modulo would wrongly charge it). This is decision-critical, not just money: funding mutates `wallet_balance` which feeds the equity-cascade close rules (TASK-013: cascade reads POST-funding wallet on a boundary bar), so a spurious charge can FLIP a discrete close. Bit-identical to the legacy `(date,hour)`+`minute<5` dedupe.
- Test: `tests/backend/test_merge_walk_engine.py::test_funding_boundary_precompute_gapped` (a slot whose ONLY stored bar is at minute ≥5 asserts ZERO funding charge — the SKIP, not a charge on the late bar), `::test_funding_staggered_listing`.

**TASK-305 — `KlineColumns` SoA-ready output from `KlineStore`.** *(REQ-STORE-018/040; AC-020)*
- File: `backend/services/kline_store.py` [MOD].
- Impl: `get_klines_batch` returns `KlineColumns` (int64-ms epoch derived, float64 OHLCV) directly consumable by `SoADatasetBuilder` — dense zero-row for negative-cached/unlisted symbols; strictly ascending, deduped, byte-identical to a pure-Postgres read at every seam.
- Test: `tests/backend/test_soa_builder.py::test_klinestore_soa_ready`, `::test_dense_zero_row_symbol`.

**TASK-306 — Float64 fingerprint re-freeze at P3.** *(REQ-PAR-042, NFR-007; AC-020/041)*
- File: `tests/backend/test_golden_fingerprint.py` [MOD].
- Impl: the DISCRETE fingerprint stays byte-identical P0→P3; the MONEY fingerprint is RE-FROZEN as float64 here (the P0–P2 Decimal lane pivots to float64) — cross-era money within `continuous-money-epsilon`. The SAME canonical identity (90d×50sym or 30d×20sym fallback) that AC-041 gates per phase.
- Test: `::test_discrete_fingerprint_stable_p3`, `::test_money_fingerprint_refrozen_float64`.

**TASK-307 — PreflightEstimator wall-time reject term.** *(FR-039/040, NFR-024; AC-018-wall)*
- File: `backend/services/preflight_estimator.py` [MOD].
- Impl: now the SoA engine has a realized wall budget, add the wall-time reject term: reject pre-slot when `predicted_wall_ms > resolved-lane budget/2` (numba-lane if `HAS_NUMBA`, else pure-Python lane); a no-numba WIDE whose LIGHT term alone (~21M advances at ~100k/s ≈ 210s) exceeds the budget is rejected with the 4xx contract, NOT admitted-then-killed. Drill term excluded from the reject threshold. No-numba HEAVY/HEAVIEST "parity-only" lane → reject threshold resolves to the universal 120s cap.
- Test: `tests/backend/test_preflight_estimator.py::test_wall_time_reject_no_numba_wide`, `::test_in_budget_drill_on_no_false_reject`.

**TASK-308 — Canonical pure-Python throughput floor + ≤60s.** *(NFR-001/003/004; AC-024)*
- File: `tests/backend/test_backtest_performance.py` [MOD].
- Impl: pure-Python SoA lane ≥150k HEAVY-evals/s single-core (`ticks×B` unit); canonical drill-OFF E2E ≤60s, drill-ON ≤90s (P3 reaches "minutes" without numba). Cadence-conditional: if AC-004 proved per-symbol-candle, the numeric gate is the re-derived budget.
- Test: `::test_pure_python_heavy_evals_floor`, `::test_canonical_drill_off_60s`, `::test_canonical_drill_on_90s`.

**TASK-309 — HEAVY/HEAVIEST lane budgets + RSS ceilings.** *(NFR-001/004/012; AC-024a)*
- File: `tests/backend/test_backtest_performance.py` [MOD].
- Impl: HEAVY (90d×100sym, B≈20) + HEAVIEST (90d×150sym, B≈40) pure-Python ≤90s each (still <120s) with peak RSS within OWN symbol-scaled ceilings (HEAVY ≤1.75GB, HEAVIEST ≤2GB WIDE tier). If profiling shows pure-Python HEAVIEST can't meet ≤90s → downgrade to numba-required (recorded in manifest) + AC-018 reject extended.
- Test: `::test_heavy_lane_90s_rss`, `::test_heaviest_lane_90s_rss`.

**TASK-310 — Symbol-scaling gate ≤2×.** *(NFR-004; AC-025)*
- File: `tests/backend/test_soa_scaling.py` [NEW].
- Impl: symbol-doubling at fixed candles → engine time grows ≤2× (LIGHT + HEAVY terms each gated; per-advance ns ceiling held ≤10,000 ns ⇔ ≥100k LIGHT-advance/s).
- Test: `::test_symbol_doubling_under_2x`, `::test_light_advance_ns_ceiling`.

**TASK-311 — SoA boundary-equivalence battery.** *(REQ-ENG-001..007, REQ-PERF-005; AC-023, T.7)*
- File: `tests/backend/test_soa_scaling.py` [MOD].
- Impl: empty/single-candle arrays; signal-before-first / at-or-after-last; epoch-vs-datetime `open_time`; per-lookup ≤log(N) microbench; non-monotonic-query microbench; 4×-history-at-fixed-W ±10% setup test.
- Test: `::test_soa_boundary_empty_single`, `::test_soa_signal_before_after`, `::test_soa_per_lookup_logn`, `::test_soa_4x_history_setup_flat`.

**TASK-312 — `BT_ENGINE_SOA` escape-hatch flag.** *(FR-046, REQ-ROLL; AC-040)*
- File: `backend/services/capability_resolver.py` [MOD].
- Impl: P3 ships UNFLAGGED but `BT_ENGINE_SOA` (default on) gives a runtime fallback to the legacy `list[dict]` layout for emergency revert without redeploy. Develop the SoA engine behind this flag, diff vs the P0 oracle on every fixture before flipping the default.
- Test: `tests/backend/test_capability_resolver.py::test_engine_soa_flag_fallback`.

**TASK-313 — Event-loop-lag + live-fetch budget under backtest/sweep (NFR-013 GREEN owner).** *(NFR-013, NFR-021; AC — cross, P3)*
- File: `tests/backend/test_backtest_performance.py` [MOD].
- Impl: NFR-013 (the engine SHARES the live FastAPI process — live auto-trade coroutines must not be starved) had NO task/test/AC (orphan). Add the gate: while a CANONICAL backtest AND a 100-combo sweep run, sample `event_loop_lag_ms` and a co-running mock live-scanner fetch latency — assert loop-lag **p99 ≤250ms AND ≤5× idle-baseline**, and live-fetch **p95 ≤20% over its standalone baseline**. Binds NFR-013 to a concrete AC and extends the §R.6 orphan-check to NFRs (not just FRs).
- Test: `::test_event_loop_lag_under_backtest`, `::test_live_fetch_p95_under_sweep`.

### F.4 — Phase P4 tasks (numba JIT kernel; import-guarded, pure-Python fallback of record)

**TASK-400 — `engine_kernel` pure-Python lane (fallback of record).** *(FR-013/016/018, NFR-003; AC-026/028)*
- File: `backend/services/engine_kernel.py` [NEW].
- Impl: `def run_kernel_pure(timeline, soa, book, config) -> Events` — the per-candle kernel (liquidation→SL→TP precedence, uPnL, once-per-tick basket equity, MFE/MAE, funding, trailing/time) in PURE PYTHON over column arrays + a compact position SoA. This IS the P3 engine extracted into a kernel shape; develop-pure-Python-FIRST. Materializes list/memoryview at chunk entry (no element-wise numpy indexing); meets ≥150k HEAVY-evals/s.
- Test: `tests/backend/test_engine_kernel.py::test_pure_kernel_matches_p3_oracle`.

**TASK-401 — `@njit` kernel (JIT the pure lane).** *(FR-013/016/018, REQ-DEP-019/020; AC-026/027)*
- File: `backend/services/engine_kernel.py` [MOD].
- Impl: `@njit(cache=True, nogil=True, boundscheck=False)` `def run_kernel_jit(...)` — receives ONLY typed numpy arrays/scalars across the nopython boundary (no reflected list/typed.Dict/Python object in the hot path); compact position SoA / jitclass (int-coded symbol, float64 fields, int8 flags, `Optional`→sentinel); any op that cannot lower stays OUTSIDE the kernel on the pure-Python path. CI `boundscheck=True` build proves no OOB; prod `boundscheck=False`. **Cooperative-cancel chunking (the 120s cap is cooperative, not force-kill — a Python thread / running `@njit` kernel cannot be force-killed and a nopython kernel does not poll `cancel_event`):** the kernel runs in BOUNDED chunks of at most `_KERNEL_CHUNK_CANDLES=4096` candles (≈`chunk×B` evals) per invocation, RETURNING control to the async orchestrator between chunks so the orchestrator checks `cancel_event` + the 120s `threading.Timer` deadline between bounded chunks (legacy checks every 100 candles at `backtest_engine.py:1244`; the JIT path inherits an equivalent bound). A deliberately long JIT/pure run is therefore actually interrupted within the cap + one-chunk margin.
- Test: `tests/backend/test_engine_kernel.py::test_jit_matches_pure[boundscheck]`, `::test_jit_no_oob_boundscheck_build`, `::test_jit_chunk_cancel_within_cap` (a long-running kernel is interrupted within 120s + one-chunk margin).

**TASK-402 — Differential float64-vs-Decimal harness.** *(NFR-007, M.4; AC-026, T.4)*
- File: `tests/backend/test_kernel_differential.py` [NEW].
- Impl: both lanes (numba + pure-Python) run the full fixture/fuzz/differential grid → outside the `continuous-money-epsilon` guard-band the two lanes are DISCRETE bit-identical (trade count, sides, symbols, entry/exit bar indices, ordering); within the guard-band EITHER they agree OR the config is detected near-threshold and ROUTED to the pure-Python oracle.
- Test: `::test_differential_discrete_identical`, `::test_differential_money_within_epsilon`.

**TASK-403 — Near-threshold guard-band routing.** *(NFR-007, FR-016; AC-026/026a)*
- File: `backend/services/engine_kernel.py` [MOD].
- Impl: a per-tick in-kernel guard-band (`gb=1e-4`) sets `near_threshold` when an open position's price passes within gb of a firing TP/SL/liq/equity threshold; on fire, the run is ROUTED to a whole-run Decimal-mode SoA merge-walk re-resolution (same `O(total_candles + ticks×B)` algorithm in Decimal, NOT the legacy super-linear oracle). The flag fires EARLY (first guard-band entry). CANONICAL near-threshold double-run (float attempt + Decimal re-resolution) <120s; HEAVY (or any class whose Decimal re-resolution can't fit the residual budget) ABORTS in-flight with the K.3 `near_threshold_decimal_infeasible` terminal error (NOT a 120s kill).
- Test: `::test_near_threshold_routes_to_decimal`, `::test_near_threshold_canonical_under_120s`, `::test_near_threshold_heavy_aborts`.

**TASK-404 — `CapabilityResolver` + `HAS_NUMBA` + flags.** *(FR-044/045/046, REQ-ROLL-001..004; AC-040/045)*
- File: `backend/services/capability_resolver.py` [MOD — created P1].
- Impl: `class CapabilityResolver` singleton — `effective = resolve(DB-override ?? ENV-default) AND HAS_<cap> AND boot_validation`, re-resolved PER RUN (not once per process); owns the 5 boolean accel gates (`BT_USE_NUMBA`, `BT_USE_COLUMNAR`, `BT_USE_FASTPATH`, `BT_PARALLEL_SWEEP`, `BT_DERIVE_COARSE`) + `BACKTEST_SAFE_MODE` master kill-switch (forces all effective-off in one op); DB-backed `bt_flag_config` layered above ENV (**this DB-read path DEPENDS ON TASK-106b/v59 having created `bt_flag_config`/`bt_flag_audit`** — until v59 is confirmed the resolver uses ENV-default only, never crashing on a missing table); ENV/file SAFE_MODE short-circuits with Postgres down; failed `bt_flag_config` read → last-known-good/ENV-default, NEVER more-permissive. `HAS_NUMBA = try: import numba; except: False`.
- Test: `tests/backend/test_capability_resolver.py::test_effective_resolution_per_run`, `::test_safe_mode_one_lever`, `::test_safe_mode_postgres_down`, `::test_failed_read_last_known_good`.

**TASK-405 — `SafeModeController` wiring.** *(FR-044, REQ-ROLL-001/002; AC-040/048e)*
- File: `backend/services/safe_mode_controller.py` [NEW], `backend/services/backtest_service.py` [MOD — lifespan inject].
- Impl: `class SafeModeController` injected at lifespan with handles to the in-flight run registry (`broadcast_cancel()`), `SealedManifest` (`halt_seal_writes()`), `SealBackfillRunner` (`drain()`/`quiesce()`). Pinned idempotent order: (a) flags-off → (b) broadcast-cancel → (c) halt seal writes → (d) drain backfill. `CapabilityResolver` owns (a) and SIGNALS the controller for (b)/(c)/(d).
- Test: `tests/backend/test_capability_resolver.py::test_safe_mode_cancels_live_sweep`, `::test_safe_mode_ordered_idempotent`.

**TASK-406 — Accel-health boot/warmup validation + fallback.** *(FR-014/048, REQ-PERF-042; AC-028/028a)*
- File: `backend/services/engine_kernel.py` [MOD], `backend/services/backtest_service.py` [MOD — boot].
- Impl: fail-fast accel-health validation trips at boot/warmup/first-combo (within first seconds, NOT after ~90s); accel absent/ABI-broken still imports + runs pure-Python; benign version mismatch warns, ABI-breaking disables JIT + falls back; on a mid-run accel failure the failed attempt's allocations are freed BEFORE the pure-Python fallback begins (no double-RSS peak); SUM (failed attempt + full pure-Python rerun) <120s.
- Test: `tests/backend/test_numba_fallback.py::test_accel_absent_boots_pure_python`, `::test_abi_break_disables_jit`, `::test_accel_failure_fallback_under_120s`, `::test_no_double_rss_peak`.

**TASK-407 — Live-path no-import assertion.** *(FR-049; AC-029)*
- File: `tests/backend/test_numba_fallback.py` [MOD].
- Impl: the live scanner/auto-trade order-execution path imports NEITHER numba NOR the SoA kernel, pays no JIT/warm cost, yields unchanged sizing/barrier values. (Asserts `sys.modules` after importing the live path.)
- Test: `::test_live_path_no_numba_import`, `::test_live_path_unchanged_sizing`.

**TASK-408 — pyproject `accel` extra + lockfile.** *(REQ-DEP-002/003; AC-030)*
- File: `pyproject.toml` [MOD].
- Impl: add `[project.optional-dependencies].accel = ["numba>=0.61,<0.67", "llvmlite>=0.44,<0.48", "pyarrow>=16,<21", "duckdb>=1.0,<2"]` — NOT in `[project].dependencies` (would brick a wheel-less install). A committed hash-pinned lockfile; CI asserts lockfile↔pyproject sync + numpy simultaneously satisfies numba's pin AND pandas' floor. `requires-python ≥ 3.10` for the extra. **N1: numba+llvmlite already installed in `.venv`; declare here, import-guarded.**
- Test: `tests/backend/test_numba_fallback.py::test_accel_extra_declared_not_base`.

**TASK-409 — Numba-lane benchmark CI gate (windows-latest).** *(NFR-002, REQ-PERF; AC-027/030)*
- File: `tests/backend/test_backtest_performance.py` [MOD].
- Impl: on the pinned `HAS_NUMBA`-true CI lane (windows-latest prebuilt-wheel), the numba-lane battery is a HARD merge gate (`accel_waived` MUST be `false`): warmed ≥frozen-floor HEAVY-evals/s (0.7×-calibrated ≈5M), canonical drill-OFF <10s / drill-ON <20s, HEAVY <30s, NFR-002 ≥100× vs the P0 engine-CPU baseline. Only non-numba lanes may waive. **Cadence/B-contingent (B3-F5 — these numeric thresholds are functions of `heavy_eval_count = ticks×B`, ~10× heavier if AC-004 proves per-symbol-candle): the ≥5M HEAVY-evals/s floor, <10s/<20s/<30s walls re-derive from the SAME `heavy_eval_count` basis FROZEN at P0 (mirror the TASK-308/309 cadence-contingency treatment, §Q.2). If the per-symbol-candle contingency binds at P0, these P4 thresholds are re-derived (not left as false-RED/ad-hoc-loosened) and the bound budgets recorded in the manifest.**
- Test: `::test_numba_100x_baseline`, `::test_numba_heavy_evals_floor`, `::test_numba_canonical_under_10s`.

**TASK-410 — Phase-A-kernel → orchestrator → Phase-B-drill handshake.** *(REQ-DRILL-011/012; AC-015 re-assert)*
- File: `backend/services/engine_kernel.py` [MOD], `backend/services/backtest_engine.py` [MOD].
- Impl: **the kernel returns the Phase-A TRADE RESULTS, NOT a `(K,2)` drill-request array (B4-F1 — corrected on two counts: there is no engine `drill_request` seam, AND a `(symbol_id, bar_open_epoch)` pair array is INSUFFICIENT because the full-book portfolio coverage pass needs each trade's `close_reason` + open-interval `[entry,exit]` overlap across the WHOLE book, which is absent from a (K,2) array).** The `@njit` kernel runs Phase A in nopython and returns the trade records as a TYPED nopython-friendly structure (parallel int64/float64 arrays: per-trade `symbol_id`, `entry_epoch`, `exit_epoch`, `close_reason_id`, pnl/fees) — a nopython kernel cannot return a Python `list[dict]` nor call the async `DrilldownLoader`. The async orchestrator maps that typed result back to the EXISTING two-`run()` SERVICE orchestration (no new engine "emit-then-resume" notion): Phase-A `engine.run()` (`backtest_service.py:828`) → the SERVICE's `_build_fine_klines`/`DrilldownLoader` (`:833`) derives 1m windows OFF-KERNEL from the full trade list (entry/exit + the full-book portfolio pass keyed on `close_reason_id` + open-interval overlap, TASK-202) → Phase-B `engine.run()` (`:838`) re-resolves ONLY flagged exit PRICES and emits `PRICE_CORRECTION` keyed to `position_id`, reconciled back into the kernel result (Σ holds on the drill lane); firing/selection/MFE-MAE/trailing stay coarse-5m.
- Test: `tests/backend/test_engine_kernel.py::test_phase_a_returns_typed_trade_results` (kernel returns the typed trade arrays incl. `close_reason_id`+open-intervals, not a (K,2) pair array), `::test_phase_b_price_correction_reconciles`, `::test_drill_selection_identical_kernel_vs_service` (window SELECTION derived off-kernel matches the pure-Python service path incl. full-book coverage).

### F.5 — Phase P5 tasks (Parquet/DuckDB read layer)

**TASK-500 — `KlineStore` columnar tier precedence.** *(FR-033/034, REQ-STORE-012..016/030; AC-031/031a)*
- File: `backend/services/kline_store.py` [MOD].
- Impl: add the tier precedence `in-process Arrow hot → mmap Feather V2 → Parquet → Postgres SOR`, short-circuit at first hit, record provenance; route any range including `≥ completion_frontier` exclusively to Postgres (forming day NEVER admitted to a hot tier — kills the frontier-advanced-evict race); `_ProcessLRU` (≤150MB klines), `_ArrowHotCache`, `_FeatherMmap`, `_DuckDBReader`/`_PolarsReader` (one long-lived connection, footers cached, warmed at boot).
- Test: `tests/backend/test_columnar_store.py::test_tier_precedence_short_circuit`, `::test_forming_day_postgres_only`, `::test_columnar_off_postgres_identical`, `::test_columnar_on_byte_parity`.

**TASK-501 — `ColumnarWriter` (Parquet/Feather, sealed-only).** *(FR-033, REQ-STORE-027/037/038; AC-031/034)*
- File: `backend/services/columnar_writer.py` [NEW].
- Impl: `class ColumnarWriter` — immutable Parquet symbol→month partition; `materialized` flips post-seal (`true→false` GC/quarantine atomically with delete, `false→true` rematerialize from SOR); fsync+rename; NEVER writes a forming day; bulk pre-materialization is bounded/resumable/throttled OR strictly lazy-on-first-touch (never an unbounded synchronous mass-build at deploy).
- Test: `tests/backend/test_columnar_store.py::test_parquet_sealed_only`, `::test_materialized_flip_content_unchanged`.

**TASK-502 — `ColumnarReader` (DuckDB/Polars, locked-down).** *(FR-033, REQ-SEC; AC-036, T.10)*
- File: `backend/services/columnar_reader.py` [NEW].
- Impl: `class ColumnarReader` — DuckDB `read_parquet` (or Polars `scan_parquet`) with capability lockdown (`SET enable_external_access=false`; post-lockdown `SET enable_external_access=true` rejected). **Injection mechanism PINNED (B1-F5):** the file path is passed via DuckDB PARAMETER BINDING (`read_parquet(?)`) — NO f-string/`%`/`.format` interpolation of a user symbol/interval into the SQL — and is DERIVED ONLY from a validated symbol allowlist (`^[A-Z0-9]+$`, TASK-220) + canonical root, never string-built. **Path containment (B1-F4):** assert the RESOLVED path `Path.resolve().is_relative_to(BT_COLUMNAR_DIR)` (fail-closed) before open. Windows junction-swap rejected between check and open (`NUMBA_CACHE_DIR` + `BT_COLUMNAR_DIR`).
- Test: `tests/backend/test_columnar_security.py::test_duckdb_injection_blocked` (a CONCRETE adversarial symbol with quotes/glob/path-escape reads ZERO rows / RAISES — not merely that a benign read works), `::test_duckdb_lockdown_enforced`, `::test_columnar_path_containment` (crafted traversal symbol cannot escape `BT_COLUMNAR_DIR`), `::test_junction_swap_rejected`.

**TASK-503 — Parquet-rebuild tri-source sha leg.** *(FR-025, N.1a/N.1c; AC-011p)*
- File: `backend/services/sealed_manifest.py` [MOD], `tests/backend/test_columnar_store.py` [MOD].
- Impl: `content_sha256` over one sealed day via Parquet-rebuild is bit-identical to BOTH Bybit-ingest and Postgres-read-rebuild (completing the tri-source equality); canonical float64 derived ONCE from the Bybit-native string (single rounding); the Postgres-read-rebuild leg runs on the `DOUBLE PRECISION` SOR (NUMERIC = fail-closed boot guard, NOT migrated).
- Test: `::test_tri_source_sha_identical`, `::test_numeric_table_fail_closed`.

**TASK-504 — `DeriveCoarse` from sealed 5m base.** *(FR-035, REQ-STORE-024; AC-032)*
- File: `backend/services/derive_coarse.py` [NEW].
- Impl: `class DeriveCoarse` — with `BT_DERIVE_COARSE` on, 15m/1h/4h derived from the sealed 5m base (`day_class=6`, carrying `fine_base_generation`); a regenerated fine base auto-invalidates stale coarse; engage ONLY when a sealed 5m base exists, else FALL BACK to the native per-interval fetch/load path (NOT a 12× 5m cold-fetch); flag-OFF native path is the documented rollback lever (byte-identical klines+trades). Derived ≤ native latency.
- Test: `tests/backend/test_derive_coarse.py::test_derived_equals_native_byte_identical`, `::test_no_sealed_base_native_fallback`, `::test_flag_off_native_1h_parity`.

**TASK-505 — PITR read-time-compare invalidation.** *(NFR-016, REQ-STORE; AC-035)*
- File: `backend/services/kline_store.py` [MOD], `backend/async_persistence.py` [MOD — `sor_data_generation` singleton].
- Impl: a PITR/restore that rewinds the SOR bumps ONLY the `sor_data_generation` singleton (O(1), no table-wide `kline_cache_coverage` re-stamp); invalidation is read-time token-compare (the row/artifact's embedded `data_generation` vs the singleton); every columnar/in-RAM tier self-invalidates + derived-coarse re-derives exactly once then stops. **Re-stamp-on-revalidate (B2-F7 — required for "exactly once then stops" to hold): when a row/artifact whose embedded `data_generation < singleton` is re-validated, UPDATE it (bounded, set-based) to the CURRENT singleton generation, so it STOPS re-invalidating; without the write-back re-stamp every read of an old (gen=0) row would re-invalidate FOREVER. The v58 `data_generation BIGINT NOT NULL DEFAULT 0` column is the re-stampable token.**
- Test: `tests/backend/test_columnar_store.py::test_pitr_o1_singleton_bump`, `::test_pitr_tiers_self_invalidate`, `::test_pitr_restamp_settles` (B2-F7: a SECOND read after PITR performs ZERO re-derivation — the first revalidation re-stamped the token).

**TASK-506 — Rotted-Parquet rebuild-from-SOR.** *(FR-034; AC-034)*
- File: `backend/services/kline_store.py` [MOD].
- Impl: a rotted Parquet file (sha256/row-count mismatch) is invalidated + rebuilt from the Postgres SOR (the seal never depended on the file); incompatible/unknown format stamp → rebuild from Postgres; columnar dir unwritable → degrade to Postgres + structured warning, never crash boot.
- Test: `tests/backend/test_columnar_store.py::test_rotted_parquet_rebuilt`, `::test_unwritable_dir_degrades`.

**TASK-507 — NFR-016 sampled backstop.** *(NFR-016; AC-035)*
- File: `backend/services/maintenance_admin.py` [MOD].
- Impl: a mandatory sampled row-count/`content_sha256` backstop that ALSO samples NULL-sha sealed days, so cross-tier byte drift / in-place mutation on a sealed-but-unhashed day is detected over time.
- Test: `tests/backend/test_columnar_store.py::test_sampled_backstop_detects_drift`.

**TASK-508 — Shadow / dark-compare mode.** *(FR-047, REQ-ROLL-016, REQ-OBS-046; AC-047a)*
- File: `backend/services/kline_store.py` [MOD], `backend/services/backtest_service.py` [MOD].
- Impl: read-path shadow logs an injected columnar byte-divergence AND returns authoritative Postgres (never serves the divergent byte); engine-shadow on a seeded-divergence config emits the size-capped localized divergence payload (trade-ordinal/symbol/field/magnitude) AND persists the optimized result (persistence-neutral); dark-mode (flags off) populates v58 fingerprint columns while staying oracle-identical. Disabling shadow removes all dual-execution cost.
- Test: `tests/backend/test_shadow_compare.py::test_read_shadow_returns_postgres`, `::test_engine_shadow_payload`, `::test_dark_mode_fingerprint_only`.

**TASK-509 — Per-tier read-latency micro-bench.** *(REQ-PERF-043; AC-033, T.8)*
- File: `tests/backend/test_backtest_performance.py` [MOD].
- Impl: per-tier read-latency ordering (Arrow < Feather < Parquet < Postgres); month-granular file-OPEN count ≤ `months_touched × symbols_touched` (never per-day); mmap major-page-fault bound; cross-process warm-rerun <5s (numba lane) / ≤60s (pure-Python); cold-start gates (cold JIT + empty LRU + cold files within 120s); GET-path downsample read-through cache (LTTB computed at most once per process per run).
- Test: `::test_tier_latency_ordering`, `::test_month_granular_open_count`, `::test_cross_process_warm_rerun`, `::test_cold_start_within_120s`.

**TASK-510 — `BT_USE_COLUMNAR`/`BT_DERIVE_COARSE` flag wiring.** *(FR-046, REQ-ROLL; AC-031/040)*
- File: `backend/services/capability_resolver.py` [MOD].
- Impl: wire `BT_USE_COLUMNAR` (+ `HAS_PYARROW`/`HAS_DUCKDB`) and `BT_DERIVE_COARSE` into the resolver; flag-off = Postgres-identical read / native-coarse fetch.
- Test: `tests/backend/test_capability_resolver.py::test_columnar_flag_capability_gated`.

**TASK-511 — Forming-day exclusion concurrency test.** *(REQ-STORE-030; AC-031a)*
- File: `tests/backend/test_columnar_store.py` [MOD].
- Impl: two reruns straddling a 5m frontier boundary both reflect FRESH forming-day rows from Postgres (`kline_tier_hits` shows forming day NEVER from arrow/feather/parquet); hot tiers contain only sealed data.
- Test: `::test_forming_day_never_hot_tier`.

**TASK-512 — `HAS_PYARROW`/`HAS_DUCKDB` import guards.** *(FR-048, REQ-DEP-004; AC-028)*
- File: `backend/services/columnar_reader.py` [MOD], `backend/services/columnar_writer.py` [MOD].
- Impl: `HAS_PYARROW`/`HAS_DUCKDB` import guards; absent → `BT_USE_COLUMNAR` effective-off → Postgres-identical read (the base pure-Python image stays lean, accel is a separable layer).
- Test: `tests/backend/test_columnar_security.py::test_pyarrow_absent_degrades_postgres`.

### F.6 — Phase P6 tasks (vectorized fast-path + prange sweeps; OPTIONAL)

**TASK-600 — `FastpathGate` 7-clause eligibility predicate.** *(FR-013, REQ-ENG-029/030; AC-037)*
- File: `backend/services/fastpath_gate.py` [NEW].
- Impl: `def is_fastpath_eligible(config) -> bool` — eligible iff ALL 7 clauses: (1) `max_drawdown_pct ≥ 100` (no armed equity-drop), (2) no `close_on_profit`, (3) no profit target (EQUITY_RISE), (4) no TRAILING_PROFIT, (5) no BREAKEVEN_TIMEOUT, (6) no sequential-depletion sizing / adaptive-blacklist-from-own-trades / `skip_if_positions_open` / live-book concentration coupling / drill-ON, (7) `fill_to_max_trades` OFF. Anything ambiguous routes to the sequential kernel.
- Test: `tests/backend/test_fastpath_gate.py::test_eligible_all_7_clauses`, `::test_ineligible_per_clause_routes_sequential[clause1..7]`.

**TASK-601 — Vectorized barrier first-touch.** *(FR-013, NFR-007/008; AC-037)*
- File: `backend/services/engine_kernel.py` [MOD — `fast_path_barrier_scan`].
- Impl: `def fast_path_barrier_scan(soa, positions, config) -> Events` — vectorized first-touch exit for provably-independent positions; result satisfies the two-sided sandwich vs the sequential-kernel oracle AND equals the sequential engine on eligible configs; sentinel "disable" values truly inert.
- Test: `tests/backend/test_fastpath_parity.py::test_fastpath_equals_sequential`, `::test_fastpath_two_sided_sandwich`.

**TASK-602 — Fast-path speedup + never-slower guard.** *(NFR-005, REQ-PERF-045; AC-037a)*
- File: `tests/backend/test_fastpath_parity.py` [MOD].
- Impl: on a provably-independent fixture with `HAS_NUMBA` true, the fast-path delivers ≥10× speedup vs the sequential kernel AND a guard asserts it is NEVER net-slower (else routes to sequential). Waived-by-capability if `HAS_NUMBA` false.
- Test: `::test_fastpath_10x_speedup`, `::test_fastpath_never_net_slower`.

**TASK-603 — Bounded-chunk barrier streaming.** *(NFR-012, M.4; AC-038)*
- File: `backend/services/engine_kernel.py` [MOD].
- Impl: the fast-path barrier scan streams in bounded chunks (no full-universe materialization); peak RSS stays within the klines budget.
- Test: `tests/backend/test_fastpath_parity.py::test_fastpath_bounded_chunks_rss`.

**TASK-604 — `prange`/ProcessPool outer-loop sweep.** *(NFR-005, FR-032; AC-039)*
- File: `backend/mcp/tools/optimizer/sweep_runner.py` [MOD].
- Impl: parallelize the OUTER sweep over configs with `prange`/ProcessPool (embarrassingly parallel); a 500-combo sweep finishes <5min, shared setup <15% of wall-time; the live-trading breaker pauses/sheds the sweep (own pool, not the 3 UI slots).
- Test: `tests/backend/test_sweep_prange.py::test_500_combo_under_5min`, `::test_shared_setup_under_15pct`, `::test_live_breaker_pauses_sweep`.

**TASK-605 — Largest-N sweep budget + reject (preflight wall, NOT a schema retype).** *(NFR-005, FR-031/032; AC-039a)*
- File: `backend/mcp/tools/optimizer/combos.py` [MOD — `MAX_SWEEP_COMBOS:16` + the `count > MAX_SWEEP_COMBOS` guards at `:71`/`:90`/`:136`], `backend/services/preflight_estimator.py` [MOD — wall-budget reject].
- Impl: distinguish the two DIFFERENT quantities (the existing plan conflated them): `n` (sweep_tools.py:40 `n: int = Field(default=100, ge=1, le=5000)`, mirrored in `optimize_config`) is the random-search SAMPLE count; `MAX_SWEEP_COMBOS` (combos.py:16, currently 5000, enforced at combos.py:71/90 + sweep_tools.py:136 + tools.py:103) gates the EXPANDED grid `count`. **⚠ DEVIATION FROM SPEC (B3-F1 — reconciled, not latent):** the spec (`backtest-optimization-spec.md` §S.3 / the "lower `n`'s `le` to 2000" line) instructs lowering `n`'s `le` 5000→2000. This plan INTENTIONALLY OVERRIDES that instruction because lowering `n`'s `le` would 422-REJECT previously-valid `n∈[2001,5000]` requests — a breaking retype violating B.4.8 ("NO breaking API changes") / §H.4 ("params stay 1:1"). Instead the 2000 wall-clock budget is enforced on the EXPANDED combo `count` via the `PreflightEstimator`. Net effect (≤2000-combo runs admitted, >2000 rejected) matches the spec's INTENT without the breaking schema lower. Cross-ref: spec "lower `le` to 2000" line is superseded by this row. **Do NOT lower `n`'s `le`.** A sweep whose `count > 2000` OR whose `predicted_sweep_wall_ms > budget(count)` is REJECTED pre-slot with the 4xx contract. Keep `n`'s public `le=5000`; the 2000 ceiling is an internal preflight/`count` wall, not a schema lower. Add a test pinning the chosen public `n` ceiling so schema + estimator + combos agree.
- Test: `tests/backend/test_sweep_prange.py::test_count_2000_admits`, `::test_count_over_2000_rejects`, `::test_n_le_5000_preserved_not_retyped`.

**TASK-606 — Realistic canonical-class sweep budget + 100-combo<60s absolute bar.** *(NFR-005, §D; AC-039b)*
- File: `tests/backend/test_sweep_prange.py` [MOD], `tests/backend/test_sweep_runner.py` [MOD — 100-combo gate lands at P2/P3 where parallelism first exists].
- Impl: a ≥10-combo sweep over the canonical run-class (90d×50sym, NOT the 14d×10sym toy) on the numba+ProcessPool lane finishes within `ceil(10/concurrency) × 4s` (canonical-per-combo numba wall ≤4s = engine-only ≈3s + IPC ≤1s, EXCLUDING the one-shot shared SoA setup). PROVISIONAL until the P4 profile lands. **Cadence/B-contingent (B3-F5): the ≤4s per-combo wall + the 100-combo<60s bar are functions of `heavy_eval_count`; if AC-004 proves per-symbol-candle (~10× heavier) they re-derive from the SAME P0-frozen basis (mirror TASK-308/309/§Q.2), recorded in the manifest — not left false-RED/ad-hoc-loosened.** **ALSO add the NFR-005 `100-combo <60s` absolute bar as a NAMED test gated at P2/P3 (where ProcessPool parallelism first lands) — NOT only at the deferrable P6** (the prior plan named only 500-combo<5min @ P6 + the 10-combo canonical budget, leaving 100-combo<60s ungated). On a no-numba host this bar is WAIVED-by-capability (sequential, per NFR-005).
- Test: `::test_realistic_canonical_sweep_budget`, `tests/backend/test_sweep_runner.py::test_100_combo_under_60s` (P2/P3 gate; waived no-numba).

**TASK-607 — `BT_USE_FASTPATH`/`BT_PARALLEL_SWEEP` flag wiring.** *(FR-046, REQ-ROLL; AC-040)*
- File: `backend/services/capability_resolver.py` [MOD].
- Impl: wire `BT_USE_FASTPATH` and `BT_PARALLEL_SWEEP` into the resolver; flag-off = sequential kernel / sequential sweep (each its own oracle).
- Test: `tests/backend/test_capability_resolver.py::test_fastpath_flag_fallback`.

**TASK-608 — Fast-path eligibility classification battery.** *(FR-013, NFR-008; AC-037)*
- File: `tests/backend/test_fastpath_gate.py` [MOD].
- Impl: exercise eligible↔ineligible classification — a config satisfying all 7 clauses runs the fast-path; a config violating EACH clause in turn (incl. a trailing-only and a breakeven-only config, each mirroring REQ-ENG-030) is classified ineligible AND provably ROUTES to the sequential kernel.
- Test: `::test_trailing_only_routes_sequential`, `::test_breakeven_only_routes_sequential`.

---

## G. File-Level Change Plan

> Action: NEW / MOD / UNCHANGED-CONTRACT. Every `backend/` change is semantic-parity-bound; `trading_rules.py` is the SSOT and is UNTOUCHED.

### G.1 Production code

| Path | Action | Purpose | Tasks | Phase |
|------|--------|---------|-------|-------|
| `backend/services/sealed_manifest.py` | NEW | Seal predicate, completion frontier, lazy-seal, `content_sha256` | TASK-100/101/102/503 | P1/P5 |
| `backend/services/kline_cache_service.py` | MOD | Manifest-aware coverage; `_PAGE_SIZE` 200→1000; upsert preserves v58 cols | TASK-103/104/105/113 | P1 |
| `backend/services/seal_backfill_runner.py` | NEW | Deferred resumable historical sealer | TASK-109 | P1 |
| `backend/services/symbol_lifecycle_refresher.py` | NEW | Populates/refreshes `symbol_lifecycle` | TASK-110 | P1 |
| `backend/services/maintenance_admin.py` | NEW | CLI-only: `ensure_indexes()` (CIC), partition validate, sampled backstop | TASK-107/108/507 | P1/P5 |
| `backend/async_persistence.py` | MOD | v58 callable `_add_sealed_manifest_columns` (coverage cols); v59 callable `_add_backtest_control_objects` (`backtest_runs` cols + status-CHECK widen + `bt_flag_config`/`bt_flag_audit`/`symbol_lifecycle`/`sor_data_generation`) | TASK-106/106b/505 | P1/P5 |
| `backend/mcp/core/breaker.py` | MOD | Per-caller-class breaker sub-state isolation | TASK-111 | P1 |
| `backend/services/run_reaper.py` | NEW | Boot-time crash-orphan reclaimer | TASK-114 | P1 |
| `backend/services/kline_store.py` | NEW→MOD | Layered READ (Postgres tier P2; columnar tiers P5); `KlineColumns` | TASK-200/305/500/505/506/508 | P2/P3/P5 |
| `backend/services/drilldown_loader.py` | NEW | Lazy per-symbol 1m loader, memo, fallback | TASK-202/204 | P2 |
| `backend/services/preflight_estimator.py` | NEW→MOD | Admission + envelope (RSS P2, wall-time P3) | TASK-207/307/605 | P2/P3/P6 |
| `backend/mcp/tools/optimizer/sweep_runner.py` | NEW | Parallel combo execution + cross-process cancel + prange | TASK-206/208/604 | P2/P6 |
| `backend/mcp/tools/optimizer/sweep_tools.py` | MOD | Wire SweepRunner; future-date 422 (`n` `le=5000` UNCHANGED — not retyped) | TASK-206/213 | P2 |
| `backend/mcp/tools/optimizer/combos.py` | MOD | `MAX_SWEEP_COMBOS` + expanded-`count` wall (2000 preflight budget, NOT an `n` schema lower) | TASK-605 | P6 |
| `backend/services/backtest_service.py` | MOD/UNCHANGED-CONTRACT | KlineStore seam, batched load, `_build_fine_klines` drill producer, atomic single-transaction persist (results+DELETE-then-trades+status flip), terminal CAS, status→wire-map, partial-telemetry on 120s kill, forming-day, SafeMode inject | TASK-201/203/210/211/212/215/217/112/114/405/406/508 | P1/P2/P4/P5 |
| `backend/services/backtest_engine.py` | MOD | Data-layout re-point (merge-walk, searchsorted, ring counter, funding precompute); decisions FROZEN; `_fine_klines` drill CONSUMPTION seam | TASK-203/301/302/303/304/410 | P2/P3/P4 |
| `backend/services/backtest_metrics.py` | MOD | Single-pass O(curve+trades); `total_trades` invariant | TASK-209 | P2 |
| `backend/services/soa_dataset_builder.py` | NEW | Symbol→SoA, global timeline, scan-anchor binding | TASK-300 | P3 |
| `backend/services/engine_kernel.py` | NEW→MOD | Pure-Python + `@njit` kernel; near-threshold routing; fast-path | TASK-400/401/403/406/410/601/603 | P4/P6 |
| `backend/services/capability_resolver.py` | NEW→MOD | Flag×capability resolution; `HAS_*`; SAFE_MODE | TASK-115/312/404/510/607 | P1/P3/P4/P5/P6 |
| `backend/services/safe_mode_controller.py` | NEW | SAFE_MODE actions (b)/(c)/(d) ordered idempotent | TASK-405 | P4 |
| `backend/services/columnar_writer.py` | NEW | Parquet/Feather writer (sealed-only) | TASK-501/512 | P5 |
| `backend/services/columnar_reader.py` | NEW | DuckDB/Polars reader (locked-down) | TASK-502/512 | P5 |
| `backend/services/derive_coarse.py` | NEW | Derive 15m/1h/4h from sealed 5m base | TASK-504 | P5 |
| `backend/services/fastpath_gate.py` | NEW | 7-clause eligibility predicate | TASK-600 | P6 |
| `backend/routers/backtest.py` | MOD | Cache-status/warmup manifest-aware + warmup future/inverted/oversized 422; admission identity; symbol-charset gate; **additive `/backtest-runtime/status` (TASK-219) with public/privileged split** | TASK-118/213/214/219/220 | P1/P2/cross |
| `pyproject.toml` | MOD | `[project.optional-dependencies].accel` (numba/llvmlite/pyarrow/duckdb) | TASK-408 | P4 |
| `backend/services/trading_rules.py` | **UNCHANGED** | SSOT — barrier/sizing math; NEVER touched | — | — |

### G.2 Test code (first-class deliverables)

| Path | Action | Covers | Phase |
|------|--------|--------|-------|
| `tests/backend/golden/oracle.py` | NEW | `GoldenMasterOracle` harness | P0 |
| `tests/backend/golden/reconcile.py` | NEW | Three-way Σ reconciliation | P0 |
| `tests/backend/golden/fixtures.py` | NEW | Close-rule battery + latch fixtures | P0 |
| `tests/backend/golden/snapshots/*.json` | NEW | Stored-snapshot oracle artifacts | P0 |
| `tests/backend/golden/{metrics,trades,summary}_keys.json` | NEW | Frozen contract key sets | P0 |
| `tests/backend/test_backtest_golden.py` | MOD | Replace magic numbers with snapshot oracle | P0 |
| `tests/backend/test_golden_fingerprint.py` | NEW | DISCRETE/MONEY fingerprint, cadence, B | P0/P3 |
| `tests/backend/test_sealed_manifest.py` | NEW | Frontier, ratchet, predicate | P1 |
| `tests/backend/test_kline_cache_sealed.py` | NEW | Sealed-once, lazy-seal, sha, forming-day | P1 |
| `tests/backend/test_v58_migration.py` | NEW | v58 callable, fail-loud, idempotent, index | P1 |
| `tests/backend/test_seal_backfill.py` | NEW | Backfill + lifecycle refresh | P1 |
| `tests/backend/test_breaker_isolation.py` | NEW | Per-caller-class breaker | P1 |
| `tests/backend/test_batched_loaders.py` | NEW | Batched `ANY($1)`, byte-identity | P2 |
| `tests/backend/test_drilldown_loader.py` | NEW | Lazy drill, memo, sandwich | P2 |
| `tests/backend/test_preflight_estimator.py` | NEW | RSS/wall-time reject | P2/P3 |
| `tests/backend/test_sweep_runner.py` | NEW | Parallel sweeps, cancel | P2 |
| `tests/backend/test_soa_builder.py` | NEW | SoA build, timeline | P3 |
| `tests/backend/test_merge_walk_engine.py` | NEW | Merge-walk, mark-seed, ring | P3 |
| `tests/backend/test_soa_scaling.py` | NEW | Boundary + scaling micro-gates | P3 |
| `tests/backend/test_engine_kernel.py` | NEW | Pure/JIT kernel, Phase A/B | P4 |
| `tests/backend/test_kernel_differential.py` | NEW | float64-vs-Decimal differential | P4 |
| `tests/backend/test_numba_fallback.py` | NEW | Accel absent/ABI, live no-import | P4 |
| `tests/backend/test_capability_resolver.py` | NEW | Flags, SAFE_MODE | P1/P3/P4/P5/P6 |
| `tests/backend/test_columnar_store.py` | NEW | Tiers, parity, PITR, forming | P5 |
| `tests/backend/test_columnar_security.py` | NEW | DuckDB lockdown, junction-swap | P5 |
| `tests/backend/test_derive_coarse.py` | NEW | Derived==native | P5 |
| `tests/backend/test_shadow_compare.py` | NEW | Shadow/dark-compare | P5 |
| `tests/backend/test_fastpath_gate.py` | NEW | 7-clause eligibility | P6 |
| `tests/backend/test_fastpath_parity.py` | NEW | Fast-path==sequential + speedup | P6 |
| `tests/backend/test_sweep_prange.py` | NEW | prange sweep budgets | P6 |
| `tests/backend/test_backtest_performance.py` | MOD | Benchmark-regression gates (all phases) | P0/P3/P4/P5 |
| `tests/backend/test_backtest_router.py` | MOD | Routes, status route, identity | P1/P2/cross |
| `tests/backend/test_backtest_schemas.py` | MOD | Frozen key sets, additive | P0/cross |

---

## H. API Change Plan (NO breaking changes)

**Hard rule.** Every existing endpoint signature, request schema, and response shape is a no-regress surface. Zero new required fields; rename/remove/retype nothing. New fields optional + nullable only. The 9 real routes (VERIFIED against `@router` decorators in `backend/routers/backtest.py`) keep identical signatures.

### H.1 Unchanged endpoints (the 9 real routes)

| Endpoint (line) | Method | No-regress note |
|-----------------|--------|-----------------|
| `/backtest` (`:52`) | POST 201 | Create+launch one step; reserves `_MAX_CONCURRENT=3` slot synchronously; `queued` verdict is NEW admission behavior on the SAME one-step boundary (today `503`s via `BacktestBusyError`); NO `/backtest/{id}/run` route exists |
| `/backtest` (`:67`) | GET | List; each row's `status` only emits the legacy 5 wire values |
| `/backtest/compare` (`:82`) | GET | `compare_backtests`; it is a GET (not POST); tolerates new close_reason/status |
| `/backtest/{run_id}` (`:100`) | GET | `_build_results` + torn-persist guard (FR-038); status wire-mapped |
| `/backtest/{run_id}/trades` (`:111`) | GET | REAL contract: `page`/`limit`/`sort_by`/`side`/`close_reason` OFFSET pagination (NOT cursor); unknown `close_reason` renders generic |
| `/backtest/{run_id}/cancel` (`:131`) | POST | Cooperative `threading.Event` cancel preserved |
| `/backtest/{run_id}` (`:145`) | DELETE 204 | — |
| `/backtest-cache/status` (`:159`) | GET | UNCHANGED shape, now from `SealedManifest`; MAY add optional `sealed_days`/`negative_days` |
| `/backtest-cache/warmup` (`:184`) | POST 202 | Manifest-aware, idempotent, 0-call on sealed range, scope ceiling + rate limit |

A **route-enumeration contract test** (T.9) asserts EXACTLY these 9 routes + methods (NO `/backtest/{id}/run`; `compare` only under GET) so route/method drift fails CI.

### H.2 The ONE additive route (non-breaking)

- **`GET /backtest-runtime/status`** [NEW] — read-only runtime optimization state. Path PINNED to `/backtest-runtime/status` (NOT `/backtest/status`, which `/backtest/{run_id}` would shadow in FastAPI declaration order). Public payload coarsened to capability booleans + active/degraded/off + breaker/seal-backfill/pitr state enums + `schema_ok: bool`. Exact versions/git-SHA/integer schema_version/numeric resource config ONLY on a kernel-peer-loopback/authenticated surface — a forwarding header can NEVER promote a request to privileged. Privileged grant requires the auth token BY DEFAULT (`BT_STATUS_TRUST_PEER_LOOPBACK=false`); kernel-peer-loopback is sufficient ONLY when an operator sets `BT_STATUS_TRUST_PEER_LOOPBACK=true` on a verified no-proxy deploy. Per-client rate limited. *(K.2; AC-044/048k; routing test asserts it resolves to the status handler and `run_id="status"` is never shadowed.)*
- File: `backend/routers/backtest.py` [MOD — add route BEFORE `/backtest/{run_id}` is irrelevant since the prefix differs, but declared with the distinct prefix]. Reads the `CapabilityResolver` snapshot. **Implemented by TASK-219 (B1-F2) — the public/privileged payload split, `BT_STATUS_TRUST_PEER_LOOPBACK` default-false logic, constant-time token compare, and the "forwarding header can NEVER promote to privileged" guarantee are owned there, NOT by TASK-118/213/214.**
- Test: `tests/backend/test_backtest_router.py::test_status_route_resolves`, `::test_status_route_coarsened_public`, `::test_status_route_forwarding_header_never_privileged`, `::test_status_route_run_id_status_not_shadowed`, `::test_status_route_rate_limited` (all owned by TASK-219).

### H.3 Error contracts (additive, distinct from result rows)

K.3 structured reject/queue contracts: `{status:'rejected', reason:'queue_full'|'wide_rss'|'wall_budget'|'near_threshold_decimal_infeasible'}` 4xx/503; `{status:'queued_timeout'}`; future/inverted/wholly-future date_range → structured 422. These are distinct from result rows (never a completed zero-trade row). MCP surfaces emit the same shapes additively.

### H.4 MCP tool output shapes (additive-only)

`backtest_run` params stay 1:1 with `BacktestCreateRequest`. `backtest_get`/`sweep_results`/`backtest_compare`/`scans_get` additive-only; `status` field wire-mapped to the legacy 5 values; the PROPOSED `AutoTradeConfig` from `optimize_config` omits the 6 infra/accel ENV knobs and `config_hash` is byte-identical pre/post-optimization (infra flags never enter the hash).

---

## I. Database / Migration Plan

### I.1 v58 sealed-manifest columns (table `kline_cache_coverage`, PK `(symbol, interval, date)`)

All `ADD COLUMN IF NOT EXISTS` with constant defaults → catalog-only, no table rewrite (PG11+), idempotent. Columns (N.1): `sealed BOOLEAN NOT NULL DEFAULT false`, `day_class SMALLINT NOT NULL DEFAULT 0`, `gap_count SMALLINT NOT NULL DEFAULT 0`, `gap_ranges JSONB`, `reverify_pending BOOLEAN NOT NULL DEFAULT false`, `listing_snapped BOOLEAN NOT NULL DEFAULT false`, `delisted BOOLEAN NOT NULL DEFAULT false`, `content_sha256 BYTEA`, `sha_version SMALLINT NOT NULL DEFAULT 0`, `manifest_semantics_version SMALLINT NOT NULL DEFAULT 1`, `fine_base_generation BIGINT`, `data_generation BIGINT NOT NULL DEFAULT 0`, `materialized BOOLEAN NOT NULL DEFAULT false`, `first_open_ts BIGINT`, `last_open_ts BIGINT`, `sealed_at TIMESTAMPTZ`. (`fetched_at` pre-exists at `:655` — NOT re-added.) **v58 is `kline_cache_coverage`-ONLY (it has no `status` column).** The `backtest_runs` additive columns (`stage_timings JSONB`, `engine_fingerprint TEXT`, `terminal_reason TEXT`), the `backtest_runs` status-CHECK widen (add `queued`/`interrupted_by_restart` → 7-value superset, applied **VALID** since it is a pure widening), and the new control/provenance/lifecycle tables (`bt_flag_config`, `bt_flag_audit`, `symbol_lifecycle`, `sor_data_generation` singleton) are a SEPARATE callable migration **v59 `_add_backtest_control_objects`** (TASK-106b) — they target a DIFFERENT table than coverage and MUST exist before TASK-114/212/404/405/110/505 reference them.

### I.2 Migration mechanics (per N4 — VERIFIED firsthand)

- **Location:** `_MIGRATIONS` list in `backend/async_persistence.py` (~L1494–1523), tuples `(version, sql_or_callable)`; current max = **v57** `(57, _backfill_open_trade_filled_qty)`. The runner wraps each migration in `conn.transaction()` (`:1629-1636`).
- **v58/v59 MUST be CALLABLES.** Append `(58, _add_sealed_manifest_columns)` then `(59, _add_backtest_control_objects)` — a single-stmt string `(56, "ALTER...")` is split on `;`, so the multi-statement sealed-manifest + control-object DDL MUST be callables (N4 hard rule). Define `async def _add_sealed_manifest_columns(conn)` (TASK-106, coverage cols) and `async def _add_backtest_control_objects(conn)` (TASK-106b, `backtest_runs` cols + status-CHECK widen + flag/lifecycle/generation tables).
- **Idempotent:** `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS`; second run is a no-op. The v59 `backtest_runs` status-CHECK widen uses a `pg_get_constraintdef` PRE-CHECK by RESOLVED (anonymous @:665) constraint name (SKIP if already the 7-value superset → ZERO DDL on second run) and is added **VALID** directly (pure widening superset — existing rows all satisfy it, trivial validation scan, no dangling out-of-band VALIDATE step left unowned).
- **Fail-loud step-0 pre-checks:** wrong PK or pre-created wrong-typed column → RAISE actionable diagnostic BEFORE any `ADD COLUMN`; `schema_version` stays at the prior version, nothing partial (AC-008a).
- **Sub-second + atomic:** each version reaches its number atomically so the global advisory lock is never held for a backfill; an injected mid-DDL failure leaves the prior version, the OLD status CHECK intact (AC-012). **Lock-contention caveat:** the v59 `backtest_runs` status-CHECK DROP+ADD takes ACCESS EXCLUSIVE; under `lock_timeout='30s'` (`:1599`) an in-flight backtest writing `backtest_runs` can abort the swap → the whole v59 txn rolls back, `schema_version` stays 58, v59 retries on next boot (safe, nothing partial). **On a live host with continuous backtests the lock can be PERPETUALLY contended so v59 NEVER applies → silent indefinite degradation (P1 features stay off). The remedy is OWNED by TASK-119 (deploy-quiesce, B1-F7/B3-F5): close admission + drain/cancel in-flight `backtest_runs` writers BEFORE the swap, bounded retry, structured operator alert if v59 cannot apply within N attempts, and the boot contract `schema_version<59 → admission stays CLOSED with an alert` (NOT silent half-on).** AC-012 extended with `test_v59_lock_timeout_abort_stays_58` + `test_v59_blocked_until_quiesced` + `test_admission_closed_below_v59` (DB-required lane).
- **Index plumbing is OUT-OF-BAND:** `CREATE INDEX CONCURRENTLY` is ILLEGAL in the txn-wrapped runner — it is built by `MaintenanceAdmin.ensure_indexes()` (TASK-107), a named post-migration async boot step invoked AFTER `schema_version=59` is confirmed (`idx_coverage_unsealed WHERE NOT sealed OR reverify_pending` + DROP-then-CREATE-swapped `idx_backtest_runs_status WHERE status IN ('queued','pending','running')` — a bare `IF NOT EXISTS` would silently keep the narrow predicate), with leftover-INVALID-index drop-on-retry + bounded `lock_timeout` + double-ANALYZE.
- **Advisory-lock topology (REQ-MIG-028):** the v58/v59 lock, the `SealBackfillRunner` election lock, and the `SymbolLifecycleRefresher` election lock are each on a dedicated DIRECT (non-pooled, session-pinned) asyncpg connection (defensive on the PRIMARY direct-asyncpg target; load-bearing under the [FLEET] transaction-mode pooler).
- **Partition pre-flight (REQ-MIG-035) is a HARD boot precondition, NOT CLI-optional:** `validate_partition_tree` (TASK-108) validates the `kline_cache` partition tree (parent exists, monthly RANGE intact, no gaps/overlaps, default present) → FAIL FAST on a broken layout; reconcile rows stranded in `kline_cache_default`. It MUST run in the boot sequence BEFORE `SealBackfillRunner` (so seal-backfill never seals rows stranded in `kline_cache_default`); it is fail-fast/guarded on the seal-backfill path, not an optional CLI step.

### I.3 Backfill (deferred, off the boot path)

`SealBackfillRunner` (TASK-109): bounded/set-based chunked-commit UPDATE within a statement budget; idempotent + resumable from a checkpoint marker; mutates ONLY coverage/manifest + lifecycle rows, NEVER a `kline_cache` candle row (before/after content-hash diff proves byte-identical); computes `content_sha256` from the SOR rows it already reads (non-NULL on backfilled seals); **TTL-exemption is keyed off `sealed = true`, NOT a NULL `fetched_at`** (B2-F1: `fetched_at` is `NOT NULL DEFAULT now()` @ :655 — a sealed row keeps its non-NULL `fetched_at`, exempted by the flag; a subsequent `fetched_at = now()` re-stamp on a sealed row is harmless and never removes the exemption); paused/resumed by SAFE_MODE.

### I.4 Rollback / rolling-deploy (expand-only)

- v58/v59 are **expand-only** at the DATA level (CI schema-diff guard asserts zero destructive DDL); additive columns/tables are ignored by older QUERIES.
- Legacy column-omitting upserts MUST NOT null/clobber additive v58 columns (`INSERT … ON CONFLICT` column preservation, TASK-113).
- Backtest endpoints MUST NOT read v58/v59 columns until `schema_version=59` is confirmed; the service reads the legacy path until then (no crash-loop on missing columns).
- No `SELECT *` against the backtest/coverage/manifest tables (every read enumerates columns).
- **BINARY rollback past v59 REQUIRES the pre-migration restore-point (DB downgrade) — it is NOT "runs without harm".** The migration runner RAISES `RuntimeError("Database schema v{current} is newer than this application supports (max v{max_version})")` whenever `current > max_version` (async_persistence.py:1616-1621). A rolled-back v57/v58 binary (lower `max_version`) therefore CRASHES on connect against a v59 DB. Operational binary revert past v59 = restore the verified pre-v59 restore-point, NOT merely redeploy the old binary. This is consistent with TASK-116's CD promotion guard, which BLOCKS promoting a binary whose max-supported `schema_version` < the live DB's (the two sections tell ONE story: forward-only unless you downgrade the DB).
- Pre-deploy gates: verified Postgres restore-point immediately before v58/v59; restored-prod-clone rehearsal (exact PG major + partitioning) asserting within-budget apply + second-run no-op; CD promotion guard blocking any binary whose max-supported `schema_version` < the live DB's (TASK-116).

### I.5 Headless validation (N3)

The v58/v59 callables + sealed logic are validated via mocks (`call_count==1`) for the call-shape; the 3 Postgres-integration tests (`test_backtest_integration.py`) skip without `BACKTEST_TEST_DATABASE_URL`. **Column-idempotency, atomic-rollback, fresh-DB 0→59 equivalence, status-CHECK widen, and the lock-timeout-abort path are NOT mock-validatable** — those real-DDL tests (TASK-106/106b) carry the SAME `BACKTEST_TEST_DATABASE_URL` skip-guard (N3), so a GREEN headless P1 does NOT validate the migration. The P1 exit note + morning report MUST record v58/v59 as **UNVALIDATED until a Postgres lane runs** them. Engine/golden parity (the business-logic gate) runs FULLY headless. Any DB-only validation that cannot run headless is flagged in the morning report.

### I.6 Rollback per migration

v58/v59 have no down-migration (additive columns/tables are harmless if unused); the operational revert is: (1) `BACKTEST_SAFE_MODE` flag for the accel layer, (2) `BT_CACHE_SEALED_MANIFEST=0` for the P1 cache path, (3) for the unflagged P1/P3 schema/engine, `git revert` + redeploy — and **if the rolled-back binary's `max_version` < the live DB's schema, ALSO restore the pre-v59 restore-point** (the runner hard-fails `current > max_version`, async_persistence.py:1616-1621 — a 57/58-binary does NOT boot against a 59-DB). The expand-only design keeps the DB usable by FORWARD binaries; it does NOT let an older binary run against a newer schema.

---

## J. Frontend Plan

**No functional frontend change.** The result/trade JSON contract is preserved; the React app renders unchanged. The constraints below are guardrails, not new features.

### J.1 Invariants to preserve

- **`metrics.total_trades` NEVER disappears** — present-and-correctly-typed on every run incl. degenerate `total_trades=0` (AC-006/043). A `null` degenerate-metric path renders without a formatting exception and never drops `total_trades`.
- **`status` wire values** — `GET /backtest/{id}` (and the LIST endpoint, and MCP `backtest_get`/`scans_get`) only ever emit the legacy 5 values (`pending|running|failed|cancelled|completed`). Internal `queued → pending`, `interrupted_by_restart → failed`, `failed_with_timeout → failed` are mapped BEFORE serialization (FR-052, TASK-215 owner) so the verified FE (`BacktestResultsPage.tsx` branches; `types.ts isPending`) never blanks or stop-polls on an unknown enum. `interrupted_by_restart` ALWAYS maps to terminal `failed` (a backtest is NOT resumable — W-1). **`failed_with_timeout` is NOT a persisted `backtest_runs.status` literal** — it is an in-memory terminal *reason* serialized as `status='failed'` + `terminal_reason='timeout'`; only `queued`/`interrupted_by_restart` are persisted status literals, which is why v59 widens the CHECK to the 7-value superset (5 legacy + those 2), NOT 8. The wire-map test (T.9) asserts every PERSISTED status literal satisfies the v59 CHECK.
- **Unknown `close_reason`** (`mr_target`) on `/backtest/{id}/trades` renders with a safe generic display, never dropped/blanked, no formatter throws (close_reason is rendered generically, never branched on).
- **Equity-curve downsampling** — `_downsample_equity` (LTTB) force-includes the first point, last point, AND global max-DD trough (PRESERVED invariant — current `:491-521` already does these). It is EXTENDED (NET-NEW, TASK-216 — not a preserved invariant) to ALSO force-include the global max-equity peak (FR-052) so the rendered curve cannot hide EITHER path-dependent extreme; the manifest still hashes the full pre-downsample JSONB (the added peak force-include affects only the GET view, not parity).
- **Bidirectional deploy-order compatibility** — a new FE rendering an old response and an old FE rendering a new response both render (surface `total_trades` + all shared ~45 keys).

### J.2 Frontend gates (run only when a phase touches FE-visible contract — P0 freeze + cross)

```bash
cd frontend && npx tsc --noEmit            # type check — must pass
cd frontend && npm run build               # production build — must pass
```

Engine phases (P1–P6) do NOT touch the frontend; these gates run at P0 (contract freeze) and at the final cross-phase validation. The frozen `metrics_keys.json`/`trades_keys.json`/`summary_keys.json` (TASK-014) are the CI tripwire — a dropped/renamed/retyped field fails the backend contract test before it reaches the FE.

### J.3 Frontend test (contract render)

- `tests/backend/test_backtest_schemas.py` covers the backend contract (frozen key sets, additive-only, status wire-map, unknown close_reason). The FE render-path assertions (degenerate-metric renders, unknown close_reason renders generic) are part of T.9 contract snapshot tests.

---

## K. Backend Plan (per-component → architecture §3.1–3.12)

> Each component maps to an architecture section. `trading_rules.py` (SSOT) is UNTOUCHED.

| Component (file) | Arch § | Responsibility | Phase | Tasks |
|------------------|--------|----------------|-------|-------|
| **`KlineStore`** (`kline_store.py`) | §3.1 | Layered READ (Postgres tier P2; Arrow→Feather→Parquet→PG P5); delegates WRITE to `KlineCacheService`; `KlineColumns`; `iter_klines_streamed` cursor seam; routes `≥frontier` to Postgres; `kline_tier_hits` | P2/P3/P5 | TASK-200/305/500/505/506/508 |
| **`SealedManifest`** (`sealed_manifest.py`) | §3.2 | Completion-frontier (monotonic ratchet), day-class taxonomy, negative cache, reverify gate, read-path lazy-seal, `content_sha256`, `unsealed_days`, `halt_seal_writes` | P1/P5 | TASK-100/101/102/503 |
| **`SoADatasetBuilder`** (`soa_dataset_builder.py`) | §3.3 | Symbol→SoA, global sorted-unique timeline, scan-anchor `searchsorted` binding, degenerate short-circuit, parse-once | P3 | TASK-300 |
| **`engine_kernel`** (`engine_kernel.py`) | §3.4 | `@njit` per-candle kernel + pure-Python fallback of record; near-threshold guard-band; Phase A/B drill handshake; fast-path | P4/P6 | TASK-400/401/403/410/601/603 |
| **`DrilldownLoader`** (`drilldown_loader.py`) | §3.5 | Lazy per-symbol 1m; per-bar fallback; in-process memo; full-book-coverage | P2 | TASK-202/204 |
| **`SweepRunner`** (`sweep_runner.py`) | §3.6 | Parallel combo execution; `USE_PROCESS_POOL` predicate; shipped-once shared inputs (SoA at P3); shared_memory cleanup; live-breaker gate; prange | P2/P6 | TASK-206/208/604 |
| **`GoldenMasterOracle`** (`tests/backend/golden/oracle.py`) | §3.7 | Stored-snapshot parity harness; three-way Σ; float64 re-freeze; NO-OP fixture; canonical fingerprint | P0 | TASK-001..014 |
| **`[MODIFIED]` core** (`backtest_engine.py`, `backtest_service.py`, `kline_cache_service.py`, `backtest_metrics.py`) | §3.8 | Data-layout re-point (decisions frozen); KlineStore seam + batched load + atomic single-transaction persist (results+DELETE-then-trades+status flip) + terminal CAS; manifest-aware coverage + `_PAGE_SIZE` 1000; single-pass metrics | P1/P2/P3 | TASK-103/104/201/203/209/301/302 |
| **`PreflightEstimator`** (`preflight_estimator.py`) | §3.9 | Admission + envelope predictor (`a·light + b·heavy`); RSS reject (P2) + wall-time reject (P3); `AdmissionAccountant` aggregate-RSS | P2/P3 | TASK-207/307/605 |
| **`SealBackfillRunner`** (`seal_backfill_runner.py`) | §3.10 | Deferred resumable throttled sealer; bounded chunked UPDATE; checkpoint marker | P1 | TASK-109 |
| **`SymbolLifecycleRefresher`** (`symbol_lifecycle_refresher.py`) | §3.11 | Populates/refreshes `symbol_lifecycle`; late reclassification without un-seal | P1 | TASK-110 |
| **`MaintenanceAdmin`** (`maintenance_admin.py`) | §3.12 | CLI-only: seal-reset, manifest-rebuild, `ensure_indexes()` (CIC), partition validate, DR, sampled backstop, `bt_flag_config` write | P1/P5 | TASK-107/108/507 |
| **`CapabilityResolver`/`SafeModeController`** (`capability_resolver.py`, `safe_mode_controller.py`) | §7.2 | Flag×capability resolution per run; SAFE_MODE one-lever; DB-backed `bt_flag_config` above ENV; fail-safe Postgres-down | P1/P3/P4/P5/P6 | TASK-115/312/404/405/510/607 |
| **`RunReaper`** (`run_reaper.py`) | M.14 | Boot-time crash-orphan reclaimer; CAS `running\|queued → interrupted_by_restart`; release slot+reservation once | P1 | TASK-114 |
| **`ColumnarWriter`/`ColumnarReader`/`DeriveCoarse`** (`columnar_*.py`, `derive_coarse.py`) | §3.1/§4.3 | Parquet/Feather (sealed-only); DuckDB/Polars (locked-down); derive 15m/1h/4h from sealed 5m | P5 | TASK-501/502/504/512 |
| **`FastpathGate`** (`fastpath_gate.py`) | §3.4/ADR-001 | 7-clause eligibility predicate; route-ambiguous-to-sequential | P6 | TASK-600/608 |

---

## L. Security Plan

> 7 `REQ-SEC` controls, all traceable. New-dependency CVE surface is the primary new risk; import guards keep it off the base image.

### L.1 New-dependency CVE surface (REQ-SEC-001/002, REQ-DEP)

- numba/llvmlite/pyarrow/duckdb live ONLY in `[project.optional-dependencies].accel` — the base pure-Python image never installs them (separable layer). A wheel-less target runs pure-Python; no source build (prebuilt wheels asserted per deploy target, AC-030).
- A committed hash-pinned lockfile; CI asserts lockfile↔pyproject sync. Version pins are bounded BOTH floor + ceiling (`numba>=0.61,<0.67`, `llvmlite>=0.44,<0.48`) to avoid an ABI break.
- CI module-absent + flag-combination matrices prove the backend imports + runs with the accel stack ABSENT (AC-028).

### L.2 Import guards (the containment boundary)

`HAS_NUMBA`/`HAS_PYARROW`/`HAS_DUCKDB` = `try: import X; except: False`. A flag whose capability is false resolves effective-off (`CapabilityResolver`). The live scanner/auto-trade path imports NEITHER numba NOR the SoA kernel (AC-029) — asserted against `sys.modules`.

### L.3 Parquet/DuckDB read-engine safety (REQ-SEC-003/004)

- **Parquet file-path safety:** no traversal; canonical `BT_COLUMNAR_DIR`-rooted paths; **boundary symbol-charset gate `^[A-Z0-9]+$` BEFORE any path/SQL construction (TASK-220, B1-F4)** + resolved-path `is_relative_to(BT_COLUMNAR_DIR)` canonical-containment fail-closed in `columnar_writer`/`columnar_reader`; Windows junction-swap rejected between check and open (`NUMBA_CACHE_DIR` + `BT_COLUMNAR_DIR`, TASK-502).
- **DuckDB capability lockdown + injection MECHANISM (REQ-SEC-004, B1-F5 — mechanism pinned, not just asserted):** `SET enable_external_access=false`; a post-lockdown `SET enable_external_access=true` is rejected (probe test). The read path uses DuckDB PARAMETER BINDING for the file path (`read_parquet(?)` bound parameter — NO f-string/`%`/`.format` interpolation of a user symbol/interval into the SQL), and the path is DERIVED ONLY from a validated symbol allowlist + canonical root (allowlist-derived, never string-built). `test_duckdb_injection_blocked` asserts a CONCRETE adversarial input (a symbol containing quotes/glob/path-escape) reads ZERO rows / RAISES — not merely that a benign read works.
- **Bulk-archive ingress (REQ-SEC-003):** the zip-bomb/bad-schema/checksum-mismatch archive guard runs ONLY when the default-OFF `public.bybit.com` bulk-archive feature is built behind its flag (out of scope by default — X-5/O.7/G.3); NOT a CI gate this feature.

### L.4 Control-surface lockdown (REQ-SEC-005/006/007)

- **`bt_flag_config` write-surface lockdown (OWNED by TASK-220b, B1-F6/B5-F3 — preventive control, previously unowned):** any public HTTP route or MCP tool attempting to WRITE `bt_flag_config` (incl. setting SAFE_MODE off) is REJECTED — writes succeed ONLY from the operator boundary (CLI/loopback/authenticated-admin, same as `MaintenanceAdmin`); the resolver + status route hold read-only handles; `bt_flag_audit` is detective-only (AC-047). Tested by `test_flag_write_rejected_from_public_http`/`_from_mcp` + `test_flag_write_allowed_from_operator_boundary`.
- **Status-route disclosure (REQ-SEC-005 — OWNED by TASK-219, B1-F2):** the public `/backtest-runtime/status` payload omits exact versions/git-SHA/resource numerics; a forwarding header can NEVER promote to the privileged payload; privileged grant requires the auth token by default (`BT_STATUS_TRUST_PEER_LOOPBACK=false`; co-located-proxy fail-open closure, K.2). Tested by `test_status_route_coarsened_public` + `test_status_route_forwarding_header_never_privileged`.
- **Spawn-worker secret minimization (REQ-SEC-006 — OWNED by TASK-206, B1-F1/B5-F4; no longer orphaned):** a sweep worker's `os.environ` is a SUBSET of a closed allowlist (not a denylist); `PG*`/`PGPASSWORD`/`PGSSLKEY`/`PGSERVICEFILE`/`DATABASE_URL`/`ACCOUNTS_ENCRYPTION_KEY`/secret-`BT_*` are ABSENT from the worker env even when the parent has them set. Implemented by TASK-206's `ProcessPoolExecutor(initializer=_worker_env_bootstrap)` child env reset (verified Windows `spawn` inherits the full parent env by default), tested by `test_worker_env_excludes_secrets` (T.10).

### L.5 Migration / wrong-DB safety

First-deploy wrong-DB refusal; missing-grant fail-closed; v58 fail-loud pre-checks (wrong PK / wrong-typed column); the `DOUBLE PRECISION` OHLCV boot guard fails closed on a legacy NUMERIC table (never a destructive rewrite). These are headless-testable via mocks where the live DB is absent (N3).

---

## M. Testing Plan

> Tests are FIRST-CLASS deliverables (TDD). The `GoldenMasterOracle` (P0) gates every later phase. Strict pytest-asyncio mode — async tests need `@pytest.mark.asyncio`. Per-test REQ/AC mapping in §R.

### M.1 Golden-master fixture battery (per close-rule branch — P0)

The CORNERSTONE. Replaces the brittle magic-number `test_backtest_golden.py` with a stored-snapshot oracle (discovery §7 flagged the existing magic-number brittleness). Frozen fixtures for EVERY engine-emitted `close_reason` token (derived from source, NOT a hand list):

| Fixture | `close_reason` | Branch exercised |
|---------|---------------|------------------|
| `test_clean_tp` | `tp` | Take-profit fill |
| `test_clean_sl` | `sl` | Stop-loss fill |
| `test_liquidation` | `liquidation` | SL omitted/outside band; `−locked_margin − entry_fee − funding_paid` carve-out |
| `test_equity_drop` | `equity_drop` | Basket equity drop cascade |
| `test_equity_drop_smart_oneshot` | `equity_drop_smart` | One-shot per scan + re-arm (FR-004 landmine) |
| `test_close_on_profit` | `close_on_profit` | Basket profit flatten |
| `test_equity_rise` | `equity_rise` | Basket rise flatten |
| `test_breakeven_tp_mutation` | `breakeven` | TP mutation only (SL/liq unchanged), skipped while trailing active |
| `test_max_duration` | `max_duration` | Age clock + boundary inclusivity |
| `test_trailing_activate_retrace` | `trailing_profit` | Activate + retrace ratchet (clear peak when uPnL≤0) |
| `test_mr_time_stop` | `mr_time_stop` | MR cohort time stop |
| `test_backtest_end_force_flush` | `backtest_end` | Cycle/end-of-run force-flush |
| `test_skip_if_positions_open` | (cycle latch) | T.2a — non-empty book at scan start |
| `test_fill_to_max_trades[batch\|immediate]` | (admission) | T.2b — relaxed second pass |
| `test_funding_boundary` | (funding) | T.3b — once-per-`(date,hour)` + negative inversion |
| `test_adaptive_blacklist_window` | (blacklist) | T.3a — 48h window crossing |
| `test_entry_bar_drill` | (drill) | T.4c — entry-fill bar spans barrier |
| `test_noop_byte_identical` | (NO-OP) | empty instrument_info/scan_contexts/fine_klines |
| `test_degenerate_zero_trade` | (degenerate) | `total_trades` present-and-0 |
| `test_skip_if_positions_open` + `test_force_close` + `test_liquidation_deliberate` | (cross) | batch-vs-immediate, force-close, deliberate liquidation |

**Union-coverage meta-test:** `fixture_close_reasons == source_close_reason_enum` (derived programmatically from `backtest_engine.py`); a newly-added enum value WITHOUT a fixture fails CI; a teeth meta-test disabling one fixture turns the union gate RED.

### M.2 Three-way Σ reconciliation (the `_assert_reconciles` upgrade — P0/cross)

Every fixture asserts `Σ trade.pnl == net_profit == final_equity − starting_capital` (Decimal-exact P0–P2; within `continuous-money-epsilon` P3+). Per-trade `trade.pnl == gross − entry_fee − exit_fee − funding_paid` (non-liquidation); `trade.pnl == −locked_margin − entry_fee − funding_paid`, `exit_fee==0` (liquidation — THIS participates in Σ). A meta-test removing one term turns RED. **Liquidation-with-fees-and-funding fixture (OWNED by TASK-002 as `test_liquidation_with_fees_and_funding_in_sigma`, B3-F3/B5-F2):** a liquidation WITH non-zero `entry_fee` AND a crossed 0/8/16h funding boundary (so `funding_paid≠0`) asserts the corrected per-trade identity participates in Σ. **B&H-collision fixture (OWNED by TASK-002 as `test_bh_baseline_excluded_from_sigma`, AC-048g):** a run that TRADES BTC/USDT while the BTC B&H baseline is active asserts the B&H series is EXCLUDED from Σ while the real BTC trade is included exactly once.

### M.3 Differential float64-vs-Decimal harness (P4)

A differential harness runs both lanes (numba + pure-Python) over the full fixture/fuzz/differential grid: outside the `continuous-money-epsilon` guard-band the lanes are DISCRETE bit-identical; within the guard-band EITHER they agree OR the config is detected near-threshold and ROUTED to the pure-Python Decimal-SoA oracle (asserts the mechanism FIRES, AC-026). A randomized property test asserts the drilled-trade two-sided sandwich (drilled PnL ≤ always-LTF AND ≥ coarse pessimistic) across the input space; the always-LTF reference self-validates to the exact coarse-5m result on no-ambiguity bars.

### M.4 Sealed-once mock-client tests (P1)

A mock Bybit client asserts a sealed day's lifetime fetch `call_count == 1` across N reruns and `bybit_kline_calls == 0` on a fully-sealed rerun (the headline RC-3 kill). SWEEP-level: aggregate `bybit_kline_calls == 0` across ALL ProcessPool workers (cache-fill ONCE at warm-up). Tri-source `content_sha256` hash-equality (Bybit-ingest vs Postgres-read-rebuild — bi-source at P1, Parquet-rebuild leg added at P5). Interior-hole / ambiguous-hole / empty-lifecycle / NULL-sha / sealed-TTL-exempt (sealed-flag-keyed, NOT NULL-`fetched_at`, B2-F1) / legacy-coarse-seal / backward-clock-step fixtures cover the manifest. **Runs headless (N3)** via mocks — no Postgres required.

### M.5 Benchmark regression gates (per-phase)

| Gate | Bar | Phase | Test |
|------|-----|-------|------|
| Engine-CPU baseline | frozen uncapped full-canonical (or 30d×20sym fallback) | P0 | `test_engine_cpu_baseline_captured` |
| Pure-Python HEAVY-evals/s | ≥150k single-core | P3 | `test_pure_python_heavy_evals_floor` |
| Canonical drill-OFF/ON | ≤60s / ≤90s | P3 | `test_canonical_drill_off_60s`/`_on_90s` |
| 4×-history setup | constant ±10% | P3 | `test_soa_4x_history_setup_flat` |
| Symbol-doubling | ≤2× | P3 | `test_symbol_doubling_under_2x` |
| numba ≥100× | vs P0 baseline (windows-latest, `accel_waived=false`) | P4 | `test_numba_100x_baseline` |
| numba HEAVY-evals/s | ≥frozen-floor (≈5M, 0.7×-calibrated) | P4 | `test_numba_heavy_evals_floor` |
| numba canonical | <10s drill-OFF / <20s drill-ON / HEAVY <30s | P4 | `test_numba_canonical_under_10s` |
| Per-tier read latency | Arrow<Feather<Parquet<Postgres | P5 | `test_tier_latency_ordering` |
| Cross-process warm-rerun | <5s (numba) / ≤60s (pure-Python) | P5 | `test_cross_process_warm_rerun` |
| Fast-path speedup | ≥10× vs sequential, never net-slower | P6 | `test_fastpath_10x_speedup` |
| 500-combo sweep | <5min, shared setup <15% | P6 | `test_500_combo_under_5min` |

**Anti-self-normalization:** floors derived from the run they gate cannot catch a regression — the ≥150k floor, the ≥5M numba tripwire, and the ≤4s per-combo wall are FROZEN constants (the numba floor is PROVISIONAL until the P4 profile lands, then re-derived from the measured warmed rate × 0.7 and frozen).

### M.6 Canonical fingerprint per-phase gate (AC-041)

After EVERY phase: the DISCRETE fingerprint is byte-identical across P0–P6; the MONEY fingerprint is byte-identical within P0–P2 (Decimal), re-frozen as float64 at P3, byte-identical P3–P6 (NOT a single byte-hash over money across the P2→P3 pivot). The fingerprint IDENTITY chosen at P0 (90d×50sym vs 30d×20sym fallback) is the SAME identity gated at every later phase, version-tracked in the manifest.

### M.7 Contract snapshot tests (T.9 — P0/cross)

Full `GET /backtest/{id}` envelope + frozen `metrics_keys.json` (two-tier `served ⊇ REQUIRED-core` AND `served ⊆ REQUIRED∪OPTIONAL`, numeric keys `number|null`) + `total_trades` invariant + `EquityPoint` + `page`/`limit`/`sort_by` OFFSET trades-pagination schema + frozen `trades_keys.json`/`summary_keys.json` + **status-wire-map (only the 5 legacy values on GET/LIST/MCP — TASK-215 is the implementing GREEN owner; the internal `queued`/`interrupted_by_restart`/`failed_with_timeout` must NOT reach the wire)** + unknown-`close_reason` generic render + route-enumeration (exactly 9 routes + methods) + bidirectional old↔new deploy-order + reject-shape + same-run_id double-submit + cancel-vs-slot-grant race + infra-flags-absent schema-snapshot (`config_hash` byte-identical pre/post-optimization).

### M.8 Security + migration + flag tests (T.10 — P1/P4/P5)

Windows junction-swap rejected; DuckDB injection cannot escape + post-lockdown probe; symbol-charset rejected at the boundary + columnar canonical-path containment (TASK-220); worker env subset-of-allowlist (negative secret-absence test, TASK-206/`test_worker_env_excludes_secrets`); v58/v59 decouple + atomic-rollback + idempotent-second-run + v58 column-types/defaults + expand-only schema-diff + `backtest_runs` status-CHECK widen (VALID by resolved name) + lock-timeout-abort-stays-58 + v59-blocked-until-quiesced (TASK-119) + fail-loud pre-checks + fresh-DB 0→59 equivalence + CREATE-before-INSERT ordering + `idx_backtest_runs_status` predicate-widen via temp-then-RENAME (live `pg_get_indexdef`, not mere existence; status-index-never-absent-during-swap); partition-gap refusal + default-reconciliation; advisory-lock session-pinned; post-backfill ANALYZE + EXPLAIN-uses-index; flag-write rejected from public HTTP + MCP, allowed from operator boundary (TASK-220b); SAFE_MODE one-lever + Postgres-down honorability + cancels-live-sweep + halts-seal; flag-flip-honored-next-run; shadow/dark-compare; per-caller-class breaker isolation; CI module-absent + flag-combination matrices. Headless via mocks where the live DB is absent (N3 — real-DDL idempotency/atomicity/lock-abort UNVALIDATED until a Postgres lane, §I.5).

### M.9 Coverage target

90%+ coverage on every NEW module (per `/new-feature` Step 12f). The per-phase comprehensive-testing convergence pass writes tests until 90%+ is reached on that phase's new code, with the golden battery + differential harness + contract snapshots as the backbone.

---

## N. Manual Verification Checklist

> Run after each phase (automated where possible; manual spot-checks for the items a test cannot fully assert). All commands assume the repo root and the project `.venv`.

### N.1 Per-phase (every phase)

- [ ] `python -m pytest tests/backend/test_backtest_golden.py tests/backend/test_golden_fingerprint.py -q` → GREEN (golden parity).
- [ ] `python -m pytest tests/backend -k "backtest or kline" -q` → **≥342 passed, ≤3 skipped** (N2 floor; new tests only ADD).
- [ ] DISCRETE fingerprint byte-identical to the P0 freeze; MONEY within epsilon (Decimal-exact P0–P2).
- [ ] Consolidated 5-agent convergence review applied (every valid C/H/M fixed; 2 rounds no-new-findings).
- [ ] Phase commit made (conventional message); tracker `Implementation Progress` row updated with commit SHA.

### N.2 Phase-specific

- **P0:** [ ] `test_backtest_golden.py` no longer contains hand-verified magic numbers (snapshot-as-oracle). [ ] Meta-test removing a Σ term turns RED. [ ] Canonical capture recorded host CPU + clock; if >6h, the 30d×20sym fallback is recorded as authoritative. [ ] Cadence differential decided (once-per-tick vs per-symbol-candle). [ ] B measured + recorded.
- **P1:** [ ] `python -m pytest tests/backend/test_v58_migration.py -q` GREEN. [ ] A fully-sealed rerun shows `bybit_kline_calls == 0` (mock). [ ] v58 (coverage cols) + v59 (`backtest_runs` cols + status-CHECK widen + flag/lifecycle/generation tables) applied → `schema_version=59` sub-second (or mock-validated headless for call-shape, N3 — column-idempotency/atomic-rollback UNVALIDATED until a Postgres lane, §I.5). [ ] `MaintenanceAdmin.ensure_indexes()` builds `idx_coverage_unsealed` CONCURRENTLY + SWAPS `idx_backtest_runs_status` to the widened predicate (out-of-band). [ ] `validate_partition_tree` runs as a hard precondition BEFORE seal-backfill. [ ] Klines byte-identical to legacy.
- **P2:** [ ] `_load_klines` issues 1 batched query (assert via query log/mock). [ ] Drill on/off SELECTION identical. [ ] A drilled rerun issues ZERO LTF fetches. [ ] Sweep speedup ≥0.7×min(M,K,concurrency) on the canonical SWEEP fixture. [ ] WIDE run rejected pre-slot (RSS).
- **P3:** [ ] Pure-Python canonical drill-OFF ≤60s (the "minutes alone" milestone — D5). [ ] ≥150k HEAVY-evals/s. [ ] 4×-history setup constant ±10% (RC-1 dead). [ ] Carried-position mark-seeding bit-identical (RC-2 dead). [ ] MONEY fingerprint re-frozen float64.
- **P4:** [ ] `HAS_NUMBA` resolved; if true → windows-latest lane ≥100× + <10s + ≥5M HEAVY-evals/s (`accel_waived=false`). [ ] `BT_USE_NUMBA=0` run still green (import-guarded fallback). [ ] Live path imports neither numba nor SoA kernel. [ ] If `HAS_NUMBA` false → U.4 ACs waived, pure-Python ≤60s binds (record `accel_waived:true`).
- **P5:** [ ] `BT_USE_COLUMNAR=0` → Postgres-identical; `=1` → cross-engine byte-parity. [ ] Forming day NEVER served from a hot tier. [ ] DuckDB lockdown probe rejects post-lockdown external access. [ ] Derived-coarse == native byte-identical.
- **P6:** [ ] 7-clause eligibility classifies each violating clause as ineligible + routes sequential. [ ] Fast-path == sequential oracle on eligible configs. [ ] ≥10× speedup + never net-slower. [ ] `n=2001` sweep rejected.

### N.3 Final (cross-phase)

- [ ] `python -m pytest tests/backend -q` (full backend suite) GREEN.
- [ ] `cd frontend && npx tsc --noEmit && npm run build` GREEN.
- [ ] v58 migration applies cleanly on a restored-prod-clone (or mock-validated, N3) + second-run no-op.
- [ ] All 45+ ACs satisfied or capability-waived-and-recorded (numba ACs on a no-numba host).
- [ ] Morning report lists any DB-only validation that could not run headless.

---

## O. Rollback Plan (feature-flag-per-optimization)

### O.1 Per-optimization flags (independent revert without redeploy)

| Flag | Default | Reverts | Phase |
|------|---------|---------|-------|
| `BT_CACHE_SEALED_MANIFEST` | on | P1 sealed manifest → legacy count-based coverage | P1 |
| `BT_ENGINE_SOA` | on | P3 SoA layout → legacy `list[dict]` engine | P3 |
| `BT_USE_NUMBA` (+`HAS_NUMBA`) | on-if-capable | P4 JIT → pure-Python kernel (oracle of record) | P4 |
| `BT_USE_COLUMNAR` (+`HAS_PYARROW`/`HAS_DUCKDB`) | off | P5 Parquet/Feather → Postgres read | P5 |
| `BT_DERIVE_COARSE` | off | P5 derive-coarse → native per-interval fetch | P5 |
| `BT_USE_FASTPATH` | off | P6 fast-path → sequential kernel | P6 |
| `BT_PARALLEL_SWEEP` | on-if-capable | P2/P6 ProcessPool → ThreadPool-over-nogil / sequential | P2/P6 |
| `BACKTEST_SAFE_MODE` | off | MASTER kill-switch → all 5 accel flags effective-off in one op + abort in-flight + halt seals + drain backfill | cross |

`BACKTEST_SAFE_MODE` reproduces the golden master via the P3 pure-Python SoA + Postgres-read + sequential + native-coarse path (byte-identical). It is honorable WITHOUT a DB read (ENV/file short-circuit) so it works with Postgres down. A failed `bt_flag_config` read resolves to last-known-good/ENV-default, NEVER more-permissive.

### O.2 Per-phase revert

- **P4–P6** (flagged): flip the flag off — no redeploy, next run honors it.
- **P1/P3** (unflagged schema/engine): the per-path escape flags (`BT_CACHE_SEALED_MANIFEST`/`BT_ENGINE_SOA`) give runtime fallback; a full revert is `git revert <phase-commit>` + redeploy — and if the reverted binary's `max_version` < the live DB schema, ALSO restore the pre-v59 restore-point (the runner hard-fails `current > max_version`; a 57/58-binary does NOT boot against a 59-DB — see §I.4/§I.6).
- **P2 (unflagged loaders/metrics/persistence/admission) is REDEPLOY-ONLY revert — accepted bounded risk:** P2's batched `_load_klines` (TASK-201), the `_build_fine_klines`→`DrilldownLoader` drill seam (TASK-203, decisions FROZEN but the code path changes), single-pass metrics (TASK-209), atomic single-transaction persist (TASK-211 — results upsert + DELETE-then-trades + in-txn status flip), and terminal CAS (TASK-212) ship UNFLAGGED with NO per-path runtime lever (unlike P1's `BT_CACHE_SEALED_MANIFEST` / P3's `BT_ENGINE_SOA`). A P2 parity break (batched-bucket byte mismatch AC-014a, or drill non-optimism AC-015a) reverts via `git revert <P2-commit>` + redeploy only. Rationale for accepting this: batched buckets are asserted BYTE-IDENTICAL to per-symbol `ORDER BY open_time` (AC-014a) and the drill seam keeps decisions frozen (AC-015), so the parity risk is bounded and golden-diffed every phase. (A future `BT_BATCHED_LOADERS`/`BT_DRILL_LAZY` default-on flag mirroring P1/P3 would add a no-redeploy lever if a P2 regression ever demands one.)
- **Parity-break revert:** if a phase breaks the golden DISCRETE fingerprint and cannot be fixed within the 3-fix rule (§D.3 — at most 3 fix attempts per parity break before mandatory revert) → revert the phase commit, record the break + root-cause in the tracker, and re-attempt with the fix.

### O.3 numba / Parquet fallback (the capability fallback)

- numba absent/ABI-broken → `HAS_NUMBA` false → pure-Python lane (the fallback of record); U.4 ACs waived (`accel_waived:true`). The accel-health validation trips at boot/warmup/first-combo (not after 90s); a mid-run accel failure frees the failed attempt's allocations before the pure-Python rerun (no double-RSS); SUM <120s.
- pyarrow/duckdb absent → `BT_USE_COLUMNAR` effective-off → Postgres-identical read.
- A rotted Parquet file → invalidated + rebuilt from the Postgres SOR (the seal never depended on the file).

---

## P. Deployment Plan

### P.1 Dependencies (import-guarded, separable layer)

`pyproject.toml` `[project.optional-dependencies].accel = ["numba>=0.61,<0.67", "llvmlite>=0.44,<0.48", "pyarrow>=16,<21", "duckdb>=1.0,<2"]` — NOT in base `[project].dependencies`. The base pure-Python image stays lean; the accel stack is a separable image layer. A committed hash-pinned lockfile; CI asserts lockfile↔pyproject sync + numpy simultaneously satisfies numba's pin AND pandas' floor + prebuilt wheels resolve on every deploy target (generic, prod base libc, windows-latest). **N1: numba+llvmlite already installed in `.venv`.**

### P.2 Incremental phase deploy

Each phase is an independent, individually-revertable deploy gated by its golden-master diff. P0 (harness) ships first + stays green through P6. Phases 1–3 ship UNFLAGGED (parity-neutral pure-Python; must hit "minutes" alone). Flags gate only accel-dependent P4–P6. P5 is the only phase touching the deploy-volume contract (`BT_COLUMNAR_DIR` persistent → <5s warm-rerun; ephemeral → cold-build budget, 0 Bybit).

### P.3 Boot / readiness contract

v58 then v59 apply in `_MIGRATIONS` at startup; **TASK-119 (deploy-quiesce, B1-F7) closes admission + drains in-flight `backtest_runs` writers BEFORE the v59 ACCESS-EXCLUSIVE status-CHECK swap so it cannot be perpetually lock-aborted; if v59 cannot apply within N attempts a structured operator alert fires and admission STAYS CLOSED (`schema_version<59` boot contract — not silent half-on).** AFTER `schema_version=59` is confirmed: `MaintenanceAdmin.ensure_indexes()` (out-of-band CIC) + `MaintenanceAdmin.validate_partition_tree()` (hard precondition — FAIL FAST on a broken `kline_cache` partition tree) + `RunReaper` (crash-orphan reclamation) run before admission re-opens; `SealBackfillRunner` (which MUST run AFTER `validate_partition_tree` so it never seals rows stranded in `kline_cache_default`) + `SymbolLifecycleRefresher` run off the boot path. The CD promotion guard blocks any binary whose max-supported `schema_version` < the live DB's; a verified restore-point precedes v58/v59.

### P.4 Resource budgets (the engine shares the live FastAPI process)

Process RSS budget is **symbol-scaled `BT_RSS_BUDGET`, NOT a flat 1GB** (reconciling the prior "≤1GB total" with TASK-309's 1.75/2GB tier ceilings): CANONICAL tier budget = 1GB, WIDE/HEAVY tier = 1.75GB, HEAVIEST tier = 2GB; klines SoA ≤150MB; global timeline its OWN `timeline_bytes` line (up to ~168MB misaligned worst case) ADDED to the klines budget. The `PreflightEstimator` reject term (TASK-207) fires at `predicted_rss > tier_budget/2` (so a HEAVY/HEAVIEST run is judged against its OWN 1.75/2GB tier budget, NOT 1GB/2=0.5GB — otherwise every HEAVY/HEAVIEST run would be rejected pre-slot and TASK-309's ≤90s tier tests could never run admitted); a runtime RSS watchdog is the backstop. **The HEAVIEST 2GB tier is admissible only on a host whose live co-tenancy headroom allows it; on the PRIMARY single-worker target the watchdog caps the admissible tier below any ceiling that would breach live-process safety.** On the PRIMARY single-worker target the watchdog budget is per-process == whole-host; `event_loop_lag_ms` p99 ≤250ms / ≤5× idle (live auto-trade coroutines not starved); on the no-numba lane concurrent backtests are capped to 1 (`_MAX_CONCURRENT` effective=1) to bound GIL contention.

---

## Q. Dependency & Sequencing

### Q.1 Critical path

```
P0 ──▶ P1 ──▶ P2 ──▶ P3 ──▶ P4 ──▶ P5 ──▶ P6
(gate)                (minutes    (≥100×)  (warm)  (fast-path)
                       alone)
```

**P0 is first and gates everything** — no phase advances without re-running the P0 golden diff. P3 is the dominant engine win and must land BEFORE P4 so P4 is re-targeted from real P3 profile numbers (findings §8). P5 requires P0–P4 green ("only if P0–P4 green"). P6 is optional/last (P0–P5 already meet the goal; defer with notes if time-constrained).

### Q.2 Intra-phase dependencies

- P1 depends on the v58 migration claiming the next free int after v57 (=58, N4).
- P2's `SweepRunner` shares legacy per-symbol kline lists at P2; the compact shared SoA lands at P3 (the SoA does not exist until then).
- P2's `PreflightEstimator` gets the RSS reject at P2; the wall-time reject term moves to P3 (no realized wall budget until the SoA engine exists).
- P3's `engine_kernel` pure-Python lane IS the thing P4 JITs (develop-pure-first).
- P5's columnar tiers extend the P2 `KlineStore` seam; P5's `DeriveCoarse` requires P1's sealed 5m base.
- P6's fast-path validates against the P3/P4 sequential kernel (its oracle).

**Pre-computed cadence-contingency table (so AC-004's pass/fail does not stall P3 mid-implementation — mirrors the §Q.2 B≈10/B≈15 table for open-book depth):** if TASK-006/AC-004 resolves the basket-equity recompute cadence to **per-symbol-candle** (instead of once-per-tick), the HEAVY term re-bases from `ticks×B` to `Σ_symbol candles_symbol` and the budgets re-derive to the pre-staged numbers below; freeze the proven cadence and bind these BEFORE the P3 merge gate.

| Cadence outcome | HEAVY eval basis | Re-derived throughput floor | Re-derived wall budget (drill-OFF / drill-ON) |
|-----------------|------------------|------------------------------|-----------------------------------------------|
| once-per-tick (assumed default) | `ticks×B` (`heavy_eval_count≈0.13M`) | ≥150k HEAVY-evals/s pure-Python | ≤60s / ≤90s (TASK-308 baseline) |
| per-symbol-candle (contingency) | `Σ_symbol candles_symbol` (≈`total_candles`≈1.296M, ~10× heavier) | ≥150k evals/s held; per-advance ≤10,000 ns (NFR-004) | ≤90s / ≤120s (still <120s cap; re-bind TASK-308/309 numeric gates) |

If the contingency binds, TASK-308's `::test_canonical_drill_off_60s`/`::test_canonical_drill_on_90s` numeric thresholds are replaced by the re-derived ≤90s/≤120s gates and recorded in the manifest.

### Q.3 Capability-conditional sequencing

- If `HAS_NUMBA` false (D5/V-1): U.4 ACs waived; P3 pure-Python ≤60s is the binding bar; P6 fast-path speedup waived. The plan still completes P0–P3 + P5 (columnar is numba-independent for the read path) with the pure-Python lane.
- If the 6h P0 capture ceiling trips: the 30d×20sym fallback fixture becomes the authoritative DISCRETE+MONEY fingerprint AND the ≥100× baseline AND the B-measurement basis (the SAME resolved identity AC-041 gates per phase).

---

## R. Traceability Matrix (REQ → TASK → files → test → AC)

> Every requirement category is traceable from REQ → TASK → file → named test → AC. Phase column shows where it gates.
>
> **Scope note:** §R lists the REPRESENTATIVE per-phase anchors; the EXHAUSTIVE task→test→AC mapping is §F (every TASK-NNN carries its own REQ IDs + named tests + AC inline). Tasks added/edited in review (TASK-106b status/control migration, TASK-119 deploy-quiesce, TASK-203 drill seam producer+consumer, TASK-215 status-wire-map [now P1-sequenced], TASK-216 equity-peak, TASK-217 partial-telemetry, TASK-219 status route, TASK-220 symbol-charset/path-containment, TASK-220b flag-write lockdown, TASK-305 KlineColumns SoA output, TASK-313 event-loop-lag, TASK-410 typed-result handshake, TASK-605/606 sweep budgets) are traced in §F; the orphan-check (§R.6) covers FRs AND measurable NFRs AND the 7 REQ-SEC controls. The matrix rows below are anchors, not the full set.

### R.1 Phase P0 (golden-master — gates all)

| REQ / FR | TASK | File | Test | AC |
|----------|------|------|------|-----|
| REQ-PAR-001..014, FR-001..006 | TASK-001/003 | `golden/oracle.py`, `golden/fixtures.py` | `test_oracle_roundtrip_stable`, `test_close_rule_union_coverage` | AC-001/003 |
| REQ-PAR-009, FR-007, NFR-009 | TASK-002 | `golden/reconcile.py` | `test_three_way_reconciliation`, `test_meta_reconciliation_teeth` | AC-002 |
| REQ-PAR-042 | TASK-004 | `test_golden_fingerprint.py` | `test_discrete_fingerprint_stable`, `test_money_fingerprint_stable` | AC-001/041 |
| NFR-002 | TASK-005 | `test_backtest_performance.py` | `test_engine_cpu_baseline_captured` | AC-001 |
| FR-018, NFR-004 | TASK-006 | `test_golden_fingerprint.py` | `test_cadence_differential_decides` | AC-004 |
| FR-018, NFR-003/004 | TASK-007 | `test_golden_fingerprint.py` | `test_open_book_depth_measured` | AC-004a |
| NFR-010 | TASK-008 | `test_backtest_golden.py` | `test_noop_byte_identical` | AC-005 |
| S.1, T.5 | TASK-009 | `test_backtest_golden.py` | `test_degenerate_total_trades_present_zero` | AC-006 |
| FR-009, REQ-PAR-012 | TASK-010 | `golden/fixtures.py` | `test_skip_if_positions_open_latch` | AC-006a |
| FR-011, REQ-PAR-025 | TASK-011 | `golden/fixtures.py` | `test_fill_to_max_trades_relaxed_pass` | AC-006c |
| FR-011a, REQ-PAR-026, REQ-PERF-010 | TASK-012 | `golden/fixtures.py` | `test_adaptive_blacklist_window_equivalence` | AC-006b |
| FR-010, REQ-PAR-013 | TASK-013 | `golden/fixtures.py` | `test_funding_granularity_invariance` | AC-006d |
| FR-037, REQ-FE-009/010 | TASK-014 | `golden/*_keys.json`, `test_backtest_schemas.py` | `test_metrics_keys_frozen` | AC-043 |

### R.2 Phase P1 (cache)

| REQ / FR | TASK | File | Test | AC |
|----------|------|------|------|-----|
| FR-019..024, REQ-CACHE-*, REQ-STORE-001..011 | TASK-100 | `sealed_manifest.py` | `test_frontier_floor`, `test_frontier_monotonic_ratchet` | AC-007/009/009a/010 |
| FR-019, NFR-017 | TASK-101 | `sealed_manifest.py` | `test_lazy_seal_pre_backfill`, `test_lazy_seal_latency_bounded` | AC-007a/007b |
| FR-025, N.1a/N.1c | TASK-102/503 | `sealed_manifest.py` | `test_content_sha256_canonical`, `test_tri_source_sha_identical` | AC-011/011p |
| FR-020/021/022 | TASK-103/105 | `kline_cache_service.py` | `test_sealed_rerun_zero_calls`, `test_sealed_short_not_perpetual_gap` | AC-007/007c/009 |
| NFR (REST) | TASK-104 | `kline_cache_service.py` | `test_page_size_1000_byte_identical` | AC-008 |
| NFR-014/015, REQ-MIG-007/008/040 | TASK-106 | `async_persistence.py` | `test_v58_adds_columns_idempotent`, `test_v58_wrong_pk_fail_loud`, `test_fresh_db_0_to_58_equivalent` | AC-008a/012 |
| NFR-014/015, FR-051/052, REQ-MIG-007/008 | TASK-106b | `async_persistence.py` (v59) | `test_v59_backtest_runs_additive_columns`, `test_v59_status_check_widen_valid_by_resolved_name`, `test_v59_creates_flag_and_lifecycle_tables`, `test_v59_creates_sor_generation_singleton`, `test_run_reaper_status_satisfies_widened_check` | AC-008/012 |
| REQ-MIG-020/033/034, REQ-CACHE-010 | TASK-107 | `maintenance_admin.py` | `test_ensure_indexes_concurrent_idempotent`, `test_index_planner_uses_idx_coverage_unsealed` | AC-010/012 |
| REQ-MIG-035 | TASK-108 | `maintenance_admin.py` | `test_partition_gap_refusal` | P1 |
| FR-050, FR-025 | TASK-109 | `seal_backfill_runner.py` | `test_backfill_mutates_only_coverage`, `test_backfill_writes_sha` | AC-013 |
| FR-051, REQ-MIG-005/015 | TASK-110 | `symbol_lifecycle_refresher.py` | `test_lifecycle_refresh_no_unseal` | AC-013 |
| O.4, FR-026, NFR-021 | TASK-111 | `breaker.py` | `test_backtest_open_does_not_gate_live` | AC-046 |
| FR-012, REQ-PAR-045, REQ-STORE-030 | TASK-112 | `backtest_service.py` | `test_forming_day_coherent_cross_read` | AC-048f |
| REQ-ROLL-009/010/011 | TASK-113 | `kline_cache_service.py` | `test_upsert_preserves_v58_columns` | AC-008 |
| FR-039/052, REQ-MIG-010 | TASK-114 | `run_reaper.py` | `test_run_reaper_reclaims_orphans` | AC-048a |
| NFR-014/015, REQ-MIG-010 (deploy-quiesce) | TASK-119 | `backtest_service.py`, `async_persistence.py` | `test_v59_blocked_until_quiesced`, `test_admission_closed_below_v59` | AC-012 |
| FR-052, REQ-API-012 (P1 wire-map, B1-F3) | TASK-215 | `backtest_service.py`, MCP | `test_no_read_surface_emits_nonlegacy_status` | AC-042 |
| REQ-ROLL-007/028/029, REQ-MIG-041 | TASK-116 | `test_v58_migration.py` | `test_promotion_guard_blocks_downgrade` | P1 |

### R.3 Phase P2 (loaders/sweep/drill)

| REQ / FR | TASK | File | Test | AC |
|----------|------|------|------|-----|
| FR-027, REQ-STORE-012..016 | TASK-200 | `kline_store.py` | `test_klinestore_dense_output`, `test_klinecolumns_shape_contract` | AC-014 |
| FR-027, REQ-PAR-039, NFR-006 | TASK-201 | `backtest_service.py` | `test_single_batched_query`, `test_batched_buckets_byte_identical` | AC-014/014a |
| FR-028/029/030, REQ-DRILL-013/020/023 | TASK-202 | `drilldown_loader.py` | `test_lazy_no_fetch_single_level`, `test_rerun_zero_fetch_memo` | AC-015/015b |
| REQ-DRILL-022, FR-030 | TASK-204 | `drilldown_loader.py` | `test_entry_bar_spans_barrier_drill` | AC-015c |
| FR-030, NFR-008, REQ-DRILL-018 | TASK-205 | `drilldown_loader.py` | `test_two_sided_sandwich_property` | AC-015a |
| FR-031/032, NFR-005, REQ-SWEEP-* | TASK-206 | `sweep_runner.py` | `test_process_pool_predicate`, `test_sweep_combo_equals_standalone` | AC-016/017/019 |
| FR-039/040/049, NFR-012/024, REQ-PERF-037/038/039 | TASK-207 | `preflight_estimator.py` | `test_wide_rss_reject`, `test_aggregate_rss_reject` | AC-018-RSS/048d |
| FR-044, FR-031, NFR-018 | TASK-208 | `sweep_runner.py` | `test_cross_process_cancel_bounded` | AC-048e |
| NFR-006, REQ-PERF-032/017/020 | TASK-209 | `backtest_metrics.py` | `test_metrics_single_pass_no_quadratic` | AC-048i |
| NFR-006, REQ-PERF-035 | TASK-210 | `backtest_service.py` | `test_first_progress_under_1s`, `test_warmup_band_collapsed` | AC-048i |
| FR-038, NFR-009 | TASK-211 | `backtest_service.py` | `test_atomic_persist_rollback`, `test_persist_idempotent_no_duplicate_trades`, `test_torn_persist_integrity_error` | AC-048c |
| FR-039, REQ-API-012/015 | TASK-212 | `backtest_service.py` | `test_terminal_state_race_single_winner`, `test_queue_drain_fifo_promote` | AC-042/048b/048h |
| S.15, FR-023, K.3 | TASK-213 | `routers/backtest.py` | `test_future_date_422` | AC-048j |
| FR-039, REQ-SEC-005, NFR-021 | TASK-214 | `routers/backtest.py` | `test_header_rotation_one_identity` | AC-048k |
| FR-029, NFR-008 | TASK-203 | `backtest_service.py` (`_build_fine_klines:987` producer), `backtest_engine.py` (`_fine_klines` consumer) | `test_selection_identical_drill_on_off`, `test_drill_three_way_reconciles` | AC-015 |
| FR-052, REQ-API-012 | TASK-215 | `backtest_service.py` (`_build_results:476`, list `:67`), MCP `backtest_get`/`scans_get` | `test_status_wire_map_get`, `test_status_wire_map_list`, `test_status_wire_map_mcp` | AC-042 |
| FR-052 | TASK-216 | `backtest_service.py` (`_downsample_equity:491`) | `test_downsample_includes_max_equity_peak`, `test_downsample_still_includes_trough_and_endpoints` | P2/cross |
| FR-041, NFR-009 | TASK-217 | `backtest_service.py` (120s kill path) | `test_partial_telemetry_persisted_on_120s_kill`, `test_telemetry_meta_drop_turns_red` | AC-048l |
| FR-044, REQ-SEC-005, NFR-021 | TASK-219 | `routers/backtest.py` (`/backtest-runtime/status`) | `test_status_route_coarsened_public`, `test_status_route_forwarding_header_never_privileged` | AC-044/048k |
| REQ-SEC-003/004 | TASK-220 | `routers/backtest.py`, `sweep_tools.py`, `columnar_*.py` | `test_symbol_charset_rejected`, `test_columnar_path_containment` | AC-036 |
| REQ-SEC-006/007, FR-051 | TASK-220b | `capability_resolver.py`, `routers/backtest.py`, MCP, `maintenance_admin.py` | `test_flag_write_rejected_from_public_http`, `test_flag_write_rejected_from_mcp`, `test_flag_write_allowed_from_operator_boundary` | AC-047 |
| REQ-SEC-006 (spawn-worker secret minimization) | TASK-206 | `sweep_runner.py` | `test_worker_env_excludes_secrets` | T.10 |
| FR-039, REQ-API-012/015 (effective_max_concurrent manifest) | TASK-212 | `backtest_service.py` | `test_effective_max_concurrent_recorded_in_manifest` | AC-044 |

### R.4 Phase P3 (SoA engine)

| REQ / FR | TASK | File | Test | AC |
|----------|------|------|------|-----|
| FR-015/017, REQ-ENG-001..007, REQ-PERF-006/007/008/044 | TASK-300 | `soa_dataset_builder.py` | `test_soa_parse_once`, `test_global_timeline_sorted_unique` | AC-020/023 |
| REQ-STORE-018/040 | TASK-305 | `kline_store.py` | `test_klinestore_soa_ready`, `test_dense_zero_row_symbol` | AC-020 |
| NFR-013, NFR-021 | TASK-313 | `test_backtest_performance.py` | `test_event_loop_lag_under_backtest`, `test_live_fetch_p95_under_sweep` | P3/cross |
| FR-015/016 | TASK-301 | `backtest_engine.py` | `test_setup_constant_4x_history`, `test_boundary_bar_same_scan` | AC-021/022 |
| FR-017, S.8 | TASK-302 | `backtest_engine.py` | `test_mark_seeding_bit_identical`, `test_mark_seeding_epoch_vs_datetime` | AC-023 |
| REQ-PERF-010, REQ-PAR-026 | TASK-303 | `backtest_engine.py` | `test_adaptive_blacklist_ring_equivalence` | AC-006b |
| REQ-PAR-013 | TASK-304 | `backtest_engine.py` | `test_funding_boundary_precompute_gapped` | AC-006d |
| REQ-PAR-042, NFR-007 | TASK-306 | `test_golden_fingerprint.py` | `test_money_fingerprint_refrozen_float64` | AC-020/041 |
| FR-039/040, NFR-024 | TASK-307 | `preflight_estimator.py` | `test_wall_time_reject_no_numba_wide` | AC-018-wall |
| NFR-001/003/004 | TASK-308 | `test_backtest_performance.py` | `test_pure_python_heavy_evals_floor`, `test_canonical_drill_off_60s` | AC-024 |
| NFR-001/004/012 | TASK-309 | `test_backtest_performance.py` | `test_heavy_lane_90s_rss` | AC-024a |
| NFR-004 | TASK-310/311 | `test_soa_scaling.py` | `test_symbol_doubling_under_2x`, `test_soa_4x_history_setup_flat` | AC-025 |

### R.5 Phases P4/P5/P6

| REQ / FR | TASK | File | Test | AC |
|----------|------|------|------|-----|
| FR-013/016/018, REQ-DEP-019/020 | TASK-400/401 | `engine_kernel.py` | `test_pure_kernel_matches_p3_oracle`, `test_jit_matches_pure` | AC-026/027 |
| NFR-007, M.4 | TASK-402/403 | `engine_kernel.py`, `test_kernel_differential.py` | `test_differential_discrete_identical`, `test_near_threshold_routes_to_decimal` | AC-026/026a |
| FR-044/045/046, REQ-ROLL-001..004 | TASK-404/405 | `capability_resolver.py`, `safe_mode_controller.py` | `test_safe_mode_one_lever`, `test_safe_mode_cancels_live_sweep` | AC-040/045 |
| FR-014/048, REQ-PERF-042 | TASK-406 | `engine_kernel.py` | `test_accel_absent_boots_pure_python`, `test_accel_failure_fallback_under_120s` | AC-028/028a |
| FR-049 | TASK-407 | `test_numba_fallback.py` | `test_live_path_no_numba_import` | AC-029 |
| REQ-DEP-002/003 | TASK-408 | `pyproject.toml` | `test_accel_extra_declared_not_base` | AC-030 |
| NFR-002, REQ-PERF | TASK-409 | `test_backtest_performance.py` | `test_numba_100x_baseline`, `test_numba_heavy_evals_floor` | AC-027/030 |
| FR-033/034, REQ-STORE-012..016/030 | TASK-500 | `kline_store.py` | `test_tier_precedence_short_circuit`, `test_forming_day_postgres_only` | AC-031/031a |
| FR-033, REQ-STORE-027/037/038 | TASK-501 | `columnar_writer.py` | `test_parquet_sealed_only` | AC-031/034 |
| FR-033, REQ-SEC | TASK-502 | `columnar_reader.py` | `test_duckdb_injection_blocked`, `test_junction_swap_rejected` | AC-036 |
| FR-035, REQ-STORE-024 | TASK-504 | `derive_coarse.py` | `test_derived_equals_native_byte_identical`, `test_no_sealed_base_native_fallback` | AC-032 |
| NFR-016 | TASK-505/507 | `kline_store.py`, `maintenance_admin.py` | `test_pitr_o1_singleton_bump`, `test_sampled_backstop_detects_drift` | AC-035 |
| FR-034 | TASK-506 | `kline_store.py` | `test_rotted_parquet_rebuilt` | AC-034 |
| FR-047, REQ-ROLL-016, REQ-OBS-046 | TASK-508 | `kline_store.py` | `test_read_shadow_returns_postgres`, `test_dark_mode_fingerprint_only` | AC-047a |
| FR-013, REQ-ENG-029/030 | TASK-600/608 | `fastpath_gate.py` | `test_eligible_all_7_clauses`, `test_trailing_only_routes_sequential` | AC-037 |
| FR-013, NFR-007/008 | TASK-601 | `engine_kernel.py` | `test_fastpath_equals_sequential`, `test_fastpath_two_sided_sandwich` | AC-037 |
| NFR-005, REQ-PERF-045 | TASK-602 | `test_fastpath_parity.py` | `test_fastpath_10x_speedup`, `test_fastpath_never_net_slower` | AC-037a |
| NFR-005, FR-032 | TASK-604/605/606 | `sweep_runner.py`, `combos.py`, `preflight_estimator.py` | `test_500_combo_under_5min`, `test_count_over_2000_rejects`, `test_100_combo_under_60s` | AC-039/039a/039b |

### R.6 Cross-cutting orphan-check

Every FR maps to ≥1 TASK + ≥1 test + ≥1 AC (Z-3 orphan-check). The notable previously-orphaned items now explicitly covered: FR-009 (TASK-010/AC-006a), FR-011 (TASK-011/AC-006c), FR-011a (TASK-012/303/AC-006b), FR-010 (TASK-013/304/AC-006d), FR-012 (TASK-112/AC-048f), FR-047 (TASK-508/AC-047a), FR-052 (TASK-215 status→wire-map serializer — the GREEN owner for T.9), REQ-DRILL-022 (TASK-204/AC-015c), REQ-CACHE-010 (TASK-107/AC-010 index planner-choice), REQ-MIG-028 (TASK-109/110 session-pinned lock). **R2-review newly-owned (were prose-only / orphaned): AC-048l partial-telemetry on the 120s in-process kill (TASK-217), AC-048g B&H-collision + liquidation-with-fees-and-funding Σ carve-outs (TASK-002), AC-044 `effective_max_concurrent` manifest write (TASK-212), AC-047 `bt_flag_config` write-surface lockdown — preventive, distinct from AC-047a (TASK-220b), REQ-SEC-005 status-route privilege split (TASK-219), REQ-SEC-006 spawn-worker secret minimization (TASK-206/`test_worker_env_excludes_secrets`), REQ-SEC-003/004 boundary symbol-charset + columnar path-containment + DuckDB parameter-bound path (TASK-220/502), the v59 deploy-quiesce liveness guard (TASK-119), and the B1-F3 status-wire phase-gate (TASK-215 in P1).** The orphan-check also covers measurable NFRs: NFR-013 (TASK-313 event-loop-lag/live-fetch — previously orphaned, now bound). `max_same_sector` no-op is DELIBERATELY preserved (D6 — NOT fixed), pinned by the T.3 intentional-no-op branch fixture.

---

## S. Definition of Done

### S.1 Per-phase DoD (every phase P0–P6)

A phase is DONE when ALL hold:
1. **All phase TASKs complete** — each test written FIRST (RED), implementation GREEN, refactored.
2. **Golden parity** — DISCRETE fingerprint byte-identical to the P0 freeze; MONEY within `continuous-money-epsilon` (Decimal-exact P0–P2, float64 P3+); `Σ trade.pnl == net_profit == final_equity − start` on every fixture.
3. **Baseline green** — `pytest tests/backend -k "backtest or kline"` → ≥342 passed, ≤3 skipped (N2; new tests only ADD).
4. **Phase ACs satisfied** — every AC in the phase's U-section green OR capability-waived-and-recorded (`accel_waived`/`perf_baseline_waived` in the manifest on a no-numba/ceiling-tripped host).
5. **Consolidated review converged** — 5-agent pass (correctness/parity/security/perf/maintainability), every valid C/H/M fixed, 2 rounds no-new-findings.
6. **Frontend gates** (only if the phase touched FE-visible contract — P0 + cross) — `npx tsc --noEmit` + `npm run build` green.
7. **Phase commit** — conventional message; tracker `Implementation Progress` row updated with the commit SHA + AC status.

### S.2 Feature-level DoD (the whole feature)

The feature is DONE when:
1. **All 7 phases** meet their per-phase DoD (or P5/P6 deferred-with-notes per the autonomous mandate, with P0–P3 fully done — P0–P3 alone meet the "minutes" goal). **The `100-combo <60s` sweep bar (NFR-005) now gates at P2/P3** (TASK-606 — where ProcessPool parallelism first lands; waived-by-capability on a no-numba host). **If P6 is deferred:** only the `500-combo <5min` sweep ABSOLUTE bar lands at P6 — the morning report MUST record it as UNMET-because-deferred (the parallelism floor AC-016 + the canonical-class budget + the 100-combo<60s bar still gate at P2/P3).
2. **Goal met** — the canonical backtest runs in seconds-to-minutes (≤60s pure-Python canonical drill-OFF; ≥100× vs the P0 engine-CPU baseline on the numba lane when `HAS_NUMBA`), with <1% deviation from real trading (bit-identical DISCRETE on the canonical 5m no-drill path).
3. **Re-download dead** — a fully-sealed rerun issues `bybit_kline_calls == 0`; each sealed day's lifetime fetch `call_count == 1`; sweeps do zero redundant exchange work.
4. **No contract regression** — the 9 routes keep signatures; `metrics.total_trades` never disappears; only the additive `/backtest-runtime/status` route is new; the frozen key sets pass.
5. **Full suite green** — `pytest tests/backend` GREEN; `npx tsc --noEmit` + `npm run build` GREEN.
6. **Migration safe** — v58 (coverage cols) + v59 (`backtest_runs` cols + status-CHECK widen + flag/lifecycle/generation tables) apply sub-second + idempotent (mock-validated headless for call-shape, N3; column-idempotency/atomic-rollback/fresh-DB/status-CHECK/lock-abort restored-clone-validated where the live DB is available — UNVALIDATED headless per §I.5); expand-only; no destructive DDL.
7. **All ACs** (AC-001..AC-048l) satisfied or capability-waived-and-recorded.
8. **Traceability complete** — every REQ → TASK → file → test → AC (§R); no orphans.
9. **Reviews complete** — Step 13 (cross-phase) + Step 14 (general hardening) converged.
10. **Merge gate** — MERGE to main + push ONLY if ALL green (pytest + tsc + npm build + golden parity + migration apply). Else push the feature branch + leave a precise report. NEVER poison main on a live trading system (tracker mandate).

### S.3 Explicitly NOT done / out of scope (deferred, per spec §G.3)

- AI Manager feature (excluded from backtest, deferred).
- The `public.bybit.com` bulk-archive ingest (default-OFF, behind its own flag; its zip-bomb guard is not a CI gate this feature).
- nautilus_trader cross-validation oracle (findings Phase 7 — not on the critical path).
- Keyset-cursor trades pagination (the REAL contract is `page`/`limit`/`sort_by` OFFSET; a cursor would be a deliberate CONTRACT CHANGE, not this feature).
- The `max_same_sector` non-enforcement is DELIBERATELY left as-is (D6).

### S.4 Evidence-before-completion (per CLAUDE.md)

No phase or the feature is claimed done without RUNNING the validation command, READING the full output, and VERIFYING the actual result (PASS/FAIL/NOT-RUN with evidence). Capability-waived ACs are recorded with the reason. The morning report (autonomous mandate) lists: phases completed, parity status per phase, any DB-only validation that could not run headless (N3), `accel_waived` status (N1/D5), and the merge disposition (merged-to-main vs feature-branch-pushed).

---

*End of implementation plan. Build order: P0 (golden harness, gates all) → P1 (cache) → P2 (loaders/sweep/drill) → P3 (SoA, minutes-alone) → P4 (numba) → P5 (Parquet/DuckDB) → P6 (fast-path). Never trust a phase without its golden-master diff. Revert any phase that breaks parity and cannot be fixed.*
