# Requirements: Regime Multi-Strategy (3 Optional Features)

**Source:** 2026-06-07 profitability research (`docs/research/reports/2026-06-07_01-26-profitability-report.md`)
**Skill:** `/new-feature` Step 2
**Status:** Round 1 complete — compiling

## Feature Description

Three OPTIONAL, default-off, toggleable features, each configurable from the shared `AutoTradeSection.tsx`
component (mounted by BOTH the manual Market Scan form `ScannerPage.tsx` and the Scheduled Market Scan
form `ScheduledScansPage.tsx`), per trading account:

- **F1 — Regime/Session Entry Filter:** suppress or score-gate new trend entries during detected chop.
  Detection = UTC session-hour windows + optional BTC realized-vol/ATR threshold (scan-time) + optional
  signal-breadth gate.
- **F2 — Mean-Reversion Strategy:** a second strategy active only in "ranging" regime; reuses LLM
  `scan_results`; fades range extremes; targets the mean; fast/tight exits; trades both directions live
  (long side default-off, opt-in, regime-gated).
- **F3 — Strategy-Cohort Accounts:** per-account `strategy_cohort` field routing accounts to trend vs
  mean-reversion vs both, decorrelating the 21-account cloning problem.

## User Scope Decisions (Step 1)

| ID | Decision | Note |
|----|----------|------|
| D4 | F2 signal source = reuse LLM `scan_results` | No new TA pipeline; entries gated to scan cadence |
| D5 | All 3 features live-enabled immediately | Override of research "backtest-first"; MUST stay default-off |
| D6 | F2 = BOTH directions live | ⚠️ Override of "no long trading"; long side default-off/opt-in/regime-gated |
| D7 | F3 cohort = field on `AutoTradeConfig` + account | Consistent with per-account pattern |

## Critical Architectural Findings (Round 1)

- **AF1:** `scan_results` carry NO price — F2 needs trade-time mark price + kline-derived mean for TP.
- **AF2:** F1 fails-OPEN (subtractive filter); F2 fails-CLOSED (never enter on stale/missing regime data).
- **AF3:** Session filter evaluates **trade-placement UTC time**; regime/vol computed once at scan-time.
- **AF4:** F3 cohort = migration 43 on `trading_accounts` + per-scan config override; default `"trend"`.
- **AF5:** Reuse `_computed_*` underscore-key injection pattern (bypasses `extra="forbid"`).
- **AF6:** F2-long requires explicit acknowledgement + persistent danger notice; server re-validates.

---

## F1 — Regime/Session Entry Filter

### Core [CORE]
- F1-1 Master toggle `regime_filter_enabled`, default OFF, on manual scan + scheduled scan + per-account.
- F1-2 UTC session-hour suppression of new trend entries; default blocked window = UTC 01, 06–12.
- F1-3 Optional BTC realized-vol / ATR% gate computed at scan time; suppress when outside configured band.
- F1-4 Optional signal-breadth gate: suppress entries when scan yields fewer than N qualifying signals.
- F1-5 When disabled: NO regime computed, NO entries blocked, NO BTC fetch — byte-identical to today.
- F1-6 Filter is strictly SUBTRACTIVE — may only skip/down-score entries, never create/upsize/up-leverage.

### Config [CONFIG]
- F1-7 `regime_filter_mode: Literal["suppress","score_gate"]` default `"suppress"` (hard block vs raise min_score).
- F1-8 `regime_filter_score_penalty: float` default 2.0, range 0–10 — min_score bump under score_gate mode.
- F1-9 `session_filter_enabled: bool` + `session_blocked_hours_utc: List[int]` (each 0–23).
- F1-10 Mutually-exclusive `session_allowed_hours_utc` (allowlist mode); validator rejects setting both.
- F1-11 `btc_vol_filter_enabled: bool`; `btc_vol_metric: Literal["realized_vol","atr_ratio"]` default `atr_ratio`.
- F1-12 `btc_vol_min_threshold` / `btc_vol_max_threshold` (Optional float ≥0); validator requires min<max when both set.
- F1-13 `btc_vol_interval: Literal["15m","1h","4h"]` default `1h`; `btc_vol_lookback_candles: int` default 14, 2–200.
- F1-14 `signal_breadth_gate_enabled: bool`; `signal_breadth_min_count: int` default 3 (1–50) and/or min avg score.
- F1-15 `regime_filter_fail_open: bool` default True (mirror existing price-drift fail-open).
- F1-16 Combine-logic for the 3 sub-gates (session/vol/breadth) is OR by default (any chop signal suppresses); documented.

### Observability [OBSERVABILITY]
- F1-17 Distinct queryable skip reasons: `session_filter`, `btc_vol_filter`, `signal_breadth`, `vol_unavailable`.
- F1-18 Per-suppressed-signal reason string with detail (e.g. "blocked: UTC 07 losing window", "ATR% 0.4<0.8").
- F1-19 Scan-level summary: X suppressed / Y allowed, current UTC hour, current vol value, breadth count.
- F1-20 Detected-regime + computed inputs emitted into the run/config snapshot (`open_run` config_snapshot) for replay.
- F1-21 Allow-path attribution: when enabled-but-passed, record gates evaluated+passed (distinguish from default-off).

### Safety [SAFETY]
- F1-22 Manual-scan one-time override ("run anyway, ignore session filter this scan") behind confirmation.
- F1-23 Warn if user blocks all 24 hours (no trades ever) — surface, don't silently halt.
- F1-24 Warn if F1 enabled but configured to block nothing (no-effect config).

---

## F2 — Mean-Reversion Strategy

### Core [CORE]
- F2-1 Master toggle `mean_reversion_enabled`, default OFF, per-account opt-in.
- F2-2 Activates ONLY when scan-time regime ∈ `mr_allowed_regimes` (default `["ranging"]`); explicit UI dependency.
- F2-3 Reuses existing LLM `scan_results` as signal source — no new TA/re-analysis pipeline.
- F2-4 Fades range extremes: a strong overbought signal → SHORT-to-mean; strong oversold → LONG-to-mean.
- F2-5 Targets the mean (mid-range/EMA/VWAP), NOT the trend strategy's 150%-of-margin TP.
- F2-6 Fast/tight exits tuned to the 1–3h winning band (data: 3–6h holds lose).
- F2-7 When disabled: only the trend strategy runs, exactly as today.

### Config [CONFIG]
- F2-8 `mr_short_enabled: bool` default True; `mr_long_enabled: bool` default False (negative-expectancy guardrail).
- F2-9 `mr_allowed_regimes: List[str]` default `["ranging"]`; validator restricts to compute_regime vocabulary.
- F2-10 `mr_mean_basis: Literal["ema","vwap","bb_mid"]` default `ema`; `mr_mean_period: int` default 20 (2–200).
- F2-11 `mr_target_capture_pct: float` default 60 (>0–100) — fraction of distance-to-mean captured as TP.
- F2-12 `mr_tight_stop_pct: Optional[float]` (>0–1000) overriding `stop_loss_pct` for MR trades (tighter default).
- F2-13 `mr_time_stop_minutes: int` default 120 (5–1440) — fast time-based exit.
- F2-14 `mr_min_edge_pct: float` default 1.0 (0–100) — skip if distance-to-mean too small to fade.
- F2-15 `mr_extreme_min_abs_score: float` default 5.0 (0–10) — only fade signals marking an extreme.
- F2-16 Separate `mr_capital_pct`, `mr_leverage`, `mr_max_trades` so MR doesn't inherit trend sizing (conservative defaults).
- F2-17 `@model_validator` requires ≥1 of short/long enabled when `mean_reversion_enabled`.

### Conflict & Mutual Exclusion [CONFLICT]
- F2-18 Regime router: when regime ∈ mr_allowed_regimes → trend suppressed (F1) + MR enabled; else MR suppressed, trend runs.
- F2-19 A symbol is never taken by BOTH strategies in one cycle (one-position-per-symbol dedupe).
- F2-20 Existing filters (max_same_direction, signal_sides, blacklist, adaptive_blacklist, sector) apply to combined book.
- F2-21 MR inversion must NOT double-invert with the existing `direction:"reverse"` config knob; final side computed once + asserted.

### Safety & Exits [SAFETY]
- F2-22 Long side regime-gated AND behind explicit acknowledgement surfacing the negative-expectancy warning.
- F2-23 F2 fails-CLOSED: missing/stale/errored regime or vol data → do NOT enter MR (esp. long).
- F2-24 Degenerate target guard: skip if computed TP ≤ entry (long) or ≥ entry (short) — "degenerate_target".
- F2-25 Inverted-geometry guard: skip/clamp if tight-SL wider than mean-target TP (reward<risk); never cross SL/TP.
- F2-26 `mr_min_edge_pct` guard: skip "mr_no_edge" when distance-to-mean below threshold.
- F2-27 Range-break exit: close/flag when price exits the detected band (distinct from TP/SL hit).
- F2-28 SL must sit inside leverage-implied liquidation price; reject meaningless SL.
- F2-29 TP must clear round-trip fee+slippage band (no net-negative "win").
- F2-30 Optional circuit breaker: auto-disable MR long side if realized expectancy stays negative over N trades.

### Observability [OBSERVABILITY]
- F2-31 Every MR position/trade tagged with originating strategy (TREND vs MEAN_REVERSION) in trades + UI.
- F2-32 Per-account PnL/win-rate split by strategy AND direction (so long negative-expectancy is visible early).
- F2-33 Distinct skip reasons: `mr_regime_excluded`, `mr_long_disabled`, `mr_no_edge`, `mr_degenerate_target`.

---

## F3 — Strategy-Cohort Accounts

### Core [CORE]
- F3-1 New `strategy_cohort: Literal["trend","mean_reversion","both"]` on `AutoTradeConfig`, default `"trend"`.
- F3-2 Persisted account-level `strategy_cohort` column (migration 43 on `trading_accounts`, default `'trend'`).
- F3-3 Cohort routes which strategy each account runs; breaks the 21-accounts-clone-identical-signals problem.
- F3-4 Resolution precedence: per-scan config override > stored account field > default `"trend"`.
- F3-5 Default cohort `"trend"` → account behaves exactly as today (trend only, no session restriction unless F1 on).

### Routing & Conflict [CONFLICT]
- F3-6 `trend` cohort accounts ignore MR signals; `mean_reversion` accounts ignore trend entries; `both` runs the regime router.
- F3-7 Cohort gate runs FIRST in `_try_trade` strategy branch, then existing side/score filters compose after.
- F3-8 Cohort mismatch emits distinct skip `cohort_mismatch` / `no_cohort` with `state.trades_skipped += 1`.
- F3-9 `both` cohort uses regime router (trend in trending, MR in ranging) — never both on one symbol/cycle.

### Safety [SAFETY]
- F3-10 Cohort must validate against closed server-side enum; reject unknown/typo strings (don't silently route to none).
- F3-11 Cohort lookup failure resolves to safe default (trend), never random/last-cached strategy.
- F3-12 Concentration warning if too many accounts land in one cohort (reintroduces correlated drawdown).
- F3-13 A scheduled/shared scan MUST NOT override a per-account safety setting (per-account config wins for safety toggles).

### Observability [OBSERVABILITY]
- F3-14 Account dashboard shows each account's cohort, active strategy, current session-eligibility.
- F3-15 Per-cohort aggregated performance reporting to compare cohort strategies over time.
- F3-16 Trades tagged with cohort attribution for later per-cohort performance grouping.

---

## Cross-Cutting

### Backtest [BACKTEST]
- X-1 Extend regime-segmented backtester to compute the same BTC scan-time regime/vol per historical scan timestamp.
- X-2 F2 represented as a regime-conditional strategy in the backtester (invert eligible signals, simulate mean-target+tight-SL+time-stop).
- X-3 F3 `strategy_cohort` as a backtest run parameter routing the simulated account; <1% deviation via shared helpers (not reimplemented math).
- X-4 F1 suppression replayable in backtester; trade-count/PnL impact measurable per session.

### Data & Performance [DATA/PERF]
- X-5 BTC volatility sourced from existing kline cache/Bybit via `bybit_rate_gate`; cache-first; shared by live + backtest.
- X-6 Hot trade path stays network-free for F1/F3 — all BTC fetch/regime/breadth computed once in `start_scan`, injected per-config.
- X-7 F2's one unavoidable trade-time price read reuses cached `get_mark_price`/kline calls under existing `asyncio.wait_for` timeouts.
- X-8 Idempotent scan-time pre-compute (deterministic for scan window/cache state); safe to recompute in batch/relaxed phases.
- X-9 Shared vol/regime helper used by both live and backtest to avoid math drift.

### Default-Off Integrity & Compat [DEFAULT/COMPAT]
- X-10 Golden/snapshot regression: all 3 off → `_try_trade` byte-identical decisions to current main on a recorded scan fixture.
- X-11 Each feature toggled off independently restores its code path; no shared mutable state leaks a gate decision when flag off.
- X-12 Present-but-disabled == absent: config with new fields + `enabled=false` behaves identically to config lacking the fields.
- X-13 Old DB JSONB + old localStorage configs lacking new keys load to default-off without error; re-save doesn't corrupt unrelated fields.
- X-14 Migration 43 additive + nullable-with-default; no backfill that flips behavior; mirror into sync `persistence.py` twin.
- X-15 Frontend TS `AutoTradeConfig` mirrors every new backend field; all new fields optional/defaulted (no `extra="forbid"` break).

### Timezone & Boundaries [TIMEZONE/BOUNDARY]
- X-16 Session filter evaluates trade-placement UTC time, tz-aware; naive-local-time leak is a defect (test guards it).
- X-17 Block-hour inclusivity [HH:00:00.000, HH:59:59.999]; midnight-crossing windows wrap correctly; DST-invariant (UTC continuous).
- X-18 Boundary tests: vol exactly at threshold (define >/≥); breadth exactly N; empty scan_results (no div-by-zero); malformed hours rejected.
- X-19 Regime label normalized (case/whitespace) so typo never silently disables the gate.

### Security & Audit [INTEGRITY/AUDIT/KILL_SWITCH]
- X-20 Server re-validates ALL config server-side; client/localStorage untrusted; whitelist JSONB keys; enum/type at API boundary.
- X-21 Risk-bearing fields (leverage, size, cohort, toggles) server-authoritative; client cannot escalate.
- X-22 Every regime decision, session skip, MR entry, and fail-open/closed activation logged to debug_trace for post-hoc analysis.
- X-23 F2-long enable requires explicit acknowledgement persisted server-side before honoring.
- X-24 Per-feature kill switch readable on hot-path without redeploy; separate F2-long kill; killing F2 is fail-closed.
- X-25 Stale-data TTL: regime/vol computed at scan-time but trade placed later — if older than TTL, F2 re-checks or skips; stale flagged in trace.

## Total Requirements Count: ~95 (R1)
## Rounds Completed: 1

---

# Round 2 Additions (+85 requirements, gaps & decisions)

## R2 Decisions Applied (scope control)

**Contradiction fix (D8):** Regime/vol pre-compute is gated by **ANY consumer enabled** (F1 ∨ F2 ∨ `both`-cohort ∨ backtest), NOT by F1 alone. F1-5 reworded accordingly.

**YAGNI cuts (D9):** EMA-only mean (drop vwap/bb_mid) · suppress-only F1 (drop score_gate) · atr_ratio-only vol (drop realized_vol) · scalar `mr_regime` (drop list). Range-break exit deferred to v2.

## F2 Trade-Creation Mechanics (was the biggest gap)

- R2-1 [F2-PLACE] F2 reuses existing `place_trade()` — converts its price-distance-to-mean target into percent-of-margin TP given leverage; passes existing `take_profit_pct`/`stop_loss_pct` params plus a new `strategy="mean_reversion"` arg. NO parallel place path. (D10a)
- R2-2 [F2-PLACE] F2 fade-side mapping: F2 pre-inverts the signal and passes `trade_direction="straight"` with the resolved side; MUST NOT reuse the `"reverse"` knob (avoid double-invert). Final side computed once + asserted.
- R2-3 [F2-EXIT] F2 fast exits reuse EXISTING close machinery: tight-SL via `stop_loss_pct`; time-stop via `max_trade_duration_hours = mr_time_stop_minutes/60` (reuses `MAX_DURATION`). Range-break exit DEFERRED to v2. (D10b)
- R2-4 [F2-DATA] MR mean (EMA over `mr_mean_period` klines) precomputed at scan-time per distinct (symbol, period); only `get_mark_price` stays on trade-time hot path. (D10e)
- R2-5 [F2-DEGENERATE] Degenerate/inverted-geometry/no-edge/fee-band/SL-vs-liquidation guards (F2-24..29) all fire under `relaxed=True` too (F2 fails-closed regardless of fill mode).

## Per-Phase Integration & State

- R2-6 [PHASE] F1/F2/F3 gates apply in ALL phases routing through `_try_trade`: `evaluate_result` (immediate), `execute_batch` strict, fill pass, AND `post_scan_recheck`. Confirm recheck routes through `_try_trade` or replicate gates.
- R2-7 [PHASE] F1 session gate re-evaluates trade-placement UTC at EACH phase (post_scan_recheck runs 2h+ later — a symbol allowed at scan start may now be in a blocked window).
- R2-8 [RELAXED] Define per-gate relaxed-mode behavior: F2 safety guards + F3 cohort_mismatch ALWAYS fire under relaxed; F1 suppression under relaxed = explicitly chosen (recommend: still suppress — it's a market-condition gate, not a quality filter).
- R2-9 [STATE] `_AccountState` gains MR-specific counters (`mr_trades_executed`) so `mr_max_trades` is enforced independently of trend `max_trades` for `both`-cohort accounts.
- R2-10 [STATE] MR placements add to the SAME `existing_symbols`/`position_directions`/`traded` structures so trend+MR can't both take one symbol; contested-symbol precedence defined (trend-first in trending, MR-first in ranging per regime router).
- R2-11 [ORDER] Resolved cohort + regime/vol/mean injected as `_computed_*` keys in `start_scan` BEFORE `executor.init_configs()` (mirror adaptive_blacklist ordering at scanner_service:409-437).
- R2-12 [ORDER] Define interaction of F2 fade with the `direction=="hold"` early-return and `signal_sides` filter: `signal_sides` applies to the POST-fade trade side for MR; document + test composition with `mr_short_enabled`/`mr_long_enabled`.

## Migrations & Data Integrity (D10c/d)

- R2-13 [MIGRATION] Migration 43: `trading_accounts.strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK(strategy_cohort IN ('trend','mean_reversion','both'))`.
- R2-14 [MIGRATION] Migration 44: `trades.strategy VARCHAR(15) NOT NULL DEFAULT 'trend' CHECK(strategy IN ('trend','mean_reversion'))` — note enum has NO 'both' (a trade has one origin). Plus denormalized `trades.strategy_cohort` (point-in-time capture at placement).
- R2-15 [MIGRATION] Migration 45: `CREATE INDEX IF NOT EXISTS idx_trades_account_strategy ON trades(account_id, strategy, status)` for per-strategy/cohort analytics (F2-32, F3-15).
- R2-16 [MIGRATION] Lock-safety: single-statement `ADD COLUMN ... NOT NULL DEFAULT '<constant>' CHECK(...)` (catalog-only on PG11+, no rewrite). Forbid nullable-then-SET-NOT-NULL form. No embedded semicolons (runner splits on ';'). IF NOT EXISTS for idempotency. Forward-only (no down-migrations).
- R2-17 [MIGRATION] Version-collision coordination: backtesting feature owns some 38-41 range; allocate a reserved contiguous block at merge; last-to-land renumbers; merge checklist verifies `_MIGRATIONS[-1][0]` sequential with no gaps/dupes.
- R2-18 [PARITY] All 3 migrations mirrored byte-identically into sync `persistence.py` `_MIGRATIONS`; add a regression test asserting the two `_MIGRATIONS` version lists are identical (prevents the documented async/sync drift bug class).
- R2-19 [WRITE-PATH] `trades.strategy` wired into BOTH insert paths: `create_trade` AND `create_partial_close_child` (child inherits `parent["strategy"]` — else MR partial closes mis-tag as trend). Add to UPDATABLE_COLUMNS audit. Checklist binds each new column → {migration ×2, INSERT sites, UPDATABLE_COLUMNS, serializer, Pydantic, TS}.
- R2-20 [DATA] `signal_performance` gains strategy attribution so MR (fade) losses don't poison the trend adaptive_blacklist (which aggregates win-rate by symbol). Per-strategy blacklist computation.
- R2-21 [DATA] Backfill semantics: existing rows → `'trend'` (semantically correct — only trend existed before). No NULL/legacy sentinel. Document rationale.
- R2-22 [READ-SAFETY] All backend reads of new config keys use `.get(key, default)`; audit `cycle_repository`, `auto_trade_service`, `scanner_service`, `scan_scheduler_service`, scheduled-scan account-removal walker for unguarded `config["..."]` access.
- R2-23 [AUDIT] `_sanitize_config` must explicitly allow `_computed_regime`/`_computed_btc_vol`/`_computed_mean` keys into `config_snapshot` (test asserts they appear); reconcile with existing `regime_snapshots` table (decide JSONB-only vs that table); confirm no size cap exceeded.
- R2-24 [READ-BACK] Trade + account response schemas + TS types extended for read-back columns (`trades.strategy`, `trades.strategy_cohort`, `trading_accounts.strategy_cohort`) — distinct from config-field mirroring (X-15).

## AI Manager & Existing-Feature Interop (D10f, D11)

- R2-25 [AI-MGR] MR positions excluded from AI Manager: MR `_try_trade` success must NOT trigger the AI auto-enable block (auto_trade_service:1196-1214); AI manager filters out `strategy='mean_reversion'` positions. (research excludes MR from AI mgmt)
- R2-26 [INTEROP] `trailing_profit` × MR exit precedence defined: MR's tight-SL/time-stop are the intended fast exits; document which wins (recommend MR time-stop/tight-SL not overridden by trailing_profit on MR positions).
- R2-27 [INTEROP] adaptive_blacklist write-back: MR losses feed a strategy-scoped blacklist (per R2-20), not the shared trend blacklist.
- R2-28 [LIFECYCLE] Enabling F1/F2 or switching cohort affects ONLY new entries; already-open positions keep their original management (no force-migrate). Surfaced in UI.

## Code Organization / Maintainability (D10g)

- R2-29 [MAINT] Config structure decision: keep FLAT fields (consistent with existing 37-field pattern + `_computed_*` injection + JSONB shape), with strict feature-prefix naming. Documented rationale (nesting would break JSONB/localStorage shape X-13).
- R2-30 [MAINT] Extract `_try_trade` gate chain into named predicate helpers (`_gate_session`, `_gate_btc_vol`, `_gate_breadth`, `_gate_cohort`, etc.) as a pre-refactor under the X-10 golden-snapshot guard (provably behavior-preserving).
- R2-31 [MAINT] All skip-reason codes defined as a `ReasonCode` enum/Final constants (single source of truth); `_emit_decision` accepts it; existing codes migrated to avoid two conventions.
- R2-32 [MAINT] New module `backend/services/market_regime.py` owns BTC realized-vol/ATR + regime classification, consumed by live + backtest (and optionally ai_manager). State whether `ai_manager_regime.py` calls it or stays separate. Single shared math (X-3 <1% deviation depends on it).
- R2-33 [MAINT] Single pure `resolve_final_side(signal_dir, reverse, mr_fade)` function replacing the 3 duplicated inline invert copies; exhaustive parametrized truth-table test pinning the double-invert (reverse ∧ fade ⇒ identity) case.
- R2-34 [MAINT] Typed `_computed_*` payload (TypedDict/dataclass) shared by producer (`scanner_service`) and consumer (`_try_trade`) so the contract can't drift.
- R2-35 [MAINT] Test organization: `test_regime_filter.py`, `test_mean_reversion.py`, `test_strategy_cohort.py`, `test_market_regime.py`, plus dedicated golden-snapshot + resolve-final-side truth-table files.
- R2-36 [MAINT] Frontend: split the absorbing `AutoTradeSection.tsx` into per-feature sub-components (`RegimeFilterFields`, `MeanReversionFields`, `CohortField`) isolating the F2-long acknowledgement UI.
- R2-37 [MAINT] Document each new field's default, range, and empirical basis (blocked hours UTC 01,06-12 ← losing-window; time-stop 120m ← 1-3h winning band) in spec + a feature doc.

## Performance (scan fan-out: 570 results × 21 configs)

- R2-38 [PERF] BTC vol/regime memoized by distinct (metric, interval, lookback) tuple across the 21 configs (≤21, typically 1-2 fetches), not a single global value (configs may differ) nor 21× recompute.
- R2-39 [PERF] MR mean memoized once per (symbol, period) per scan (not per account×trade ≈ 63×); single-flight dedup of per-symbol mark-price/kline reads across accounts (no thundering herd).
- R2-40 [PERF] Signal-breadth via ONE aggregation pass over 570 results at scan-time; per-config min answered O(1)/O(log n), not 570×21 rescans.
- R2-41 [PERF/LAZY] Skip BTC vol fetch when no config enables vol gate; skip regime build when no consumer needs it (granular, beyond the master toggle).
- R2-42 [PERF/MEM] `_computed_*` blob shared by immutable reference across configs (not deep-copied 21×); bounded/LRU scan-scoped kline cache (byte ceiling + eviction) so 570 symbols can't grow unbounded.
- R2-43 [PERF] Cohort resolved once in-memory at scan start; `_try_trade` cohort gate is O(1) field compare with ZERO per-symbol DB lookup.
- R2-44 [BACKTEST/PERF] Regime/vol/mean timeline batch-precomputed once per backtest keyed (timestamp, param-tuple); replay does O(1) lookups (not O(trades×accounts) builds). Windowed/streaming evictable kline load for replay.

## Backtest Replayability

- R2-45 [BACKTEST] Session-time source injectable (clock param), not hardcoded `datetime.now(timezone.utc)` — live uses now(), backtest injects historical scan timestamp (else F1 replay impossible).
- R2-46 [STALE] X-25 stale-regime resolution in late phases: stale → skip MR (fail-closed, NO late network fetch) rather than re-fetch on the recheck path; TTL check lives at gate entry; stale flagged in trace.
- R2-47 [RESUME] Resumed scans (`resume_incomplete_scans`/`restore_state`) carry forward scan-time regime values flagged stale, OR recompute — decision documented; stale MR skips (fail-closed).

## Product / Adoption (v1 subset — D11)

- R2-48 [DEFAULTS] One-click "Apply research-recommended preset" sets F1 blocked hours (01,06-12) + vol band + F2 conservative sizing in a single action.
- R2-49 [MARKER] Enabling/disabling a feature writes a marker (timestamp, account, feature, config snapshot) to research-history store so the next research run can measure effect.
- R2-50 [WORKFLOW] Bulk cohort/feature assignment across selected accounts (the 21-account pain point this feature exists to solve).
- R2-51 [DISCOVERABILITY] Each feature's UI links its source research finding/report; warns at config time that default-off means the documented bleed persists until enabled.
- R2-52 [COHORT-EDGE] Multiple configs for one account with differing cohorts: first-config-wins (or reject) — documented so decorrelation isn't defeated. `both`-cohort fill-to-max candidate selection governed by regime router.
- R2-53 [COLD-START] New zero-history account with F2 enabled must not false-trigger circuit breaker or show misleading win-rate; minimum-sample guard.

## Deferred to v2 / Future Enhancements (explicitly OUT of v1 scope)

- DEF-1 F2 range-break exit (new trigger_type + constraint migration) — time-stop + tight-SL + mean-TP suffice for v1.
- DEF-2 Shadow/observe-only mode; canary automation; before/after dashboard; A/B control framework; what-if preview; proactive nudge; periodic digest. (v1 ships mechanism; measurement via debug_trace + per-strategy PnL split.)
- DEF-3 F2 circuit-breaker auto-disable (F2-30) — optional; v1 relies on per-strategy PnL visibility + manual disable.
- DEF-4 VWAP/BB-mid mean bases; score_gate F1 mode; realized_vol metric; multi-regime MR list.

## Total Requirements Count: ~180 (R1+R2)
## Rounds Completed: 2

---

# Round 3 Additions (+28 requirements; 2 CRITICAL deploy gaps)

## Deployment & Migration Safety (CRITICAL — D12, D13)

- R3-1 [DEPLOY-CRITICAL] Migration 45 `CREATE INDEX` (non-concurrent) takes a SHARE lock blocking ALL `trades` writes for the build duration at startup. `CREATE INDEX CONCURRENTLY` is STRUCTURALLY IMPOSSIBLE in the current runner (wraps every migration in `conn.transaction()`; PG rejects CONCURRENTLY in a txn). Plan MUST choose: (a) add a non-transactional migration path running CONCURRENTLY under the existing advisory lock but outside `conn.transaction()`, with INVALID-index recovery (DROP + retry, since `IF NOT EXISTS` won't rebuild an invalid index); OR (b) accept + bound the lock window, validated by R3-3.
- R3-2 [ROLLBACK-CRITICAL] Runner boot-guard raises RuntimeError when `schema_version > max_version` → rolling app code back past v42 BRICKS startup. Mandate a rollback runbook: (a) manual `UPDATE schema_version SET version=42`, (b) a test confirming v42 code tolerates the 3 additive columns (trades row→model read path must not reject-extra). Forward-only is the substitute for down-migrations.
- R3-3 [DEPLOY-TEST] Test migration 45 against a production-sized `trades` snapshot; record observed lock/build window; gate ship decision on it.
- R3-4 [VERSION-SKEW] Migrations only ever append strictly above the global max in EVERY shared env (dev/staging/canary); pre-merge check that no environment already applied a to-be-renumbered version (runner's integer `version <= current` gate silently skips renumbered migrations forever otherwise).
- R3-5 [DEPLOY-ORDER] Confirm trade/account response additions (R2-24) are forward-compatible for an unmodified old client (no strict/reject-extra parsing on trade/account read path) so backend can deploy ahead of frontend.

## Backtest API Contract (D14)

- R3-6 [BACKTEST-API] `BacktestCreateRequest` (backtest_schemas.py:35) is a hand-copied flat mirror with `extra="ignore"` — new F1/F2/F3 fields are silently DROPPED (backtest runs as if features off, defeating X-3 <1% deviation with no error). Must add every new field explicitly AND set `extra="forbid"` so unknown params fail loudly.
- R3-7 [BACKTEST-API] `BacktestTradeResponse` gains a `strategy` field; `/backtest/{id}/trades` gains a `strategy=` filter; backtest metrics support per-strategy + per-direction split (enables the F2-32 measurement that DEF-2 keeps in v1).

## Naming Collision (D15)

- R3-8 [NAMING] Pre-existing `/strategies` router + `strategies` table + `strategy_id` FK + `VALID_STRATEGY_CATEGORIES` already own the word "strategy". New `trades.strategy` / `place_trade(strategy=)` overloads it. Decision: keep column name `strategy` BUT document explicitly "no relation to the strategies table / strategy_id" in schema + code comments; TS type named to avoid ambiguity. (Plan may instead choose `strategy_kind` — ratify one.)

## F2 Data & Conversion Edge Cases (D16, D18)

- R3-9 [F2-CONFIG] Add `mr_mean_interval: Literal["15m","1h","4h"]` default `"1h"` — `mr_mean_period` is a candle COUNT with no timeframe today (asymmetric vs `btc_vol_interval`). Precompute key = (symbol, period, interval).
- R3-10 [F2-FAILCLOSED] Per-symbol mean/kline precompute failure is OUTSIDE the regime/vol fail-closed contract (mean is per-symbol, distinct from BTC-level regime/vol). Add fail-closed skip reasons `mr_mean_unavailable` + `mr_insufficient_history`; min-candle guard (`available_candles >= mr_mean_period`); test qualifying-signal-but-no-klines race.
- R3-11 [F2-CLAMP] Converted TP (price-distance→margin-% given leverage, R2-1) needs an UPPER clamp (≤ exchange ceiling, ≤ distance-implied max) — high leverage × wide distance yields an unfillable absurd TP. Test extreme-leverage/far-mean inputs.
- R3-12 [F2-EXIT] `mr_time_stop_minutes`→`max_trade_duration_hours` conversion: floor 5min = 0.083h — forbid the int-truncation-to-0 ("0 = disabled") collision; require float duration (or store minutes); MR duration captured per-trade at placement (not read from shared account config at close-eval, which would clobber a `both` account's trend setting).
- R3-13 [F2-EXIT] Close-evaluator polling cadence (hours-sized for trend) must bound MR time-stop error (5-min floor) — special-case minute-granularity MR stops or document the max lateness; test a 5-min stop against the actual evaluator tick.

## Regime Router Totality & State (D17, D19)

- R3-14 [F3-ROUTER] `both`-cohort regime→strategy mapping must be TOTAL over the compute_regime vocabulary (trending_up/down → trend; ranging → MR; volatile/compression/unknown → define explicit default, recommend: no new entries / trend-only documented). Pin the classifier trending↔ranging boundary tie-break (>/≥). Test volatile/compression/exact-boundary for a `both` account.
- R3-15 [STATE] `both`-account combined-exposure ceiling: total open trades ≤ account max; `capital_pct + mr_capital_pct ≤ 100` (reject/warn). F3-12 concentration is cross-account; this is within-account. Test one-limit-hit-other-not.
- R3-16 [WRITE-PATH] Partial-close child inherits BOTH `parent["strategy"]` AND `parent["strategy_cohort"]` (child created at close time; account may have been reassigned since open — R2-28 keeps open positions on original management). Test partial-close-after-reassignment attribution.
- R3-17 [CONCURRENCY] Single-flight rejected-future policy: on shared kline/mark-price fetch failure, all awaiters fail-closed THIS phase but NO negative caching across phases (fresh attempt next phase — execute_batch/post_scan_recheck). Test one-fetch-fails-many-awaiters.
- R3-18 [MARKER] Research-history marker (R2-49) written in same transaction as the config change (or derived from config audit log); bulk writes (R2-50) idempotent + ordered. Test concurrent enable/disable on one account.

## New Money-Field Bounds & Validation (security follow-through)

- R3-19 [VALIDATION] New Round-2 money fields get explicit bounds: `mr_max_trades` (1–999), `mr_leverage` (1–125), `mr_capital_pct` (>0–100), `mr_mean_period` (2–200), `mr_time_stop_minutes` (5–1440), `mr_target_capture_pct` (>0–100). All server-validated via Pydantic before persistence.
- R3-20 [SECURITY] `strategy="mean_reversion"` arg to `place_trade` must be server-DERIVED from the executor's strategy decision, NOT client-settable — a crafted request must not mislabel a trend trade as MR (to dodge the trend adaptive_blacklist) or vice-versa. F2-long acknowledgement enforced server-side via an explicit persisted field, not just the UI checkbox.

## Frontend New Surfaces (D20)

- R3-21 [UI] Shared `<StrategyChip>` (TREND vs MEAN_REVERSION) rendered consistently across open-positions cards, closed-trades table, trade-detail, notifications; trades table gains strategy filter/group-by.
- R3-22 [UI] Per-strategy × per-direction PnL split (F2-32) has a defined IA home (recommend: tab on account detail) — load-bearing as the manual-disable safety net (DEF-2); table shape = strategy × direction × {PnL, win-rate, count, avg-hold}. Per-cohort aggregate (F3-15) relationship defined.
- R3-23 [UI] Account-level cohort editor surface exists (migration-43 column needs a UI home — account settings page); `CohortField` in scan form shows inherited account value + flags when overriding + clear-override affordance.
- R3-24 [UI] Bulk cohort/feature assignment (R2-50) lives on a fleet/roster multi-select view (new surface): checkboxes + apply-to-selected action bar + preview/confirm before mutating N accounts + partial-failure handling. Combines with R2-48 preset ("apply preset to selected").
- R3-25 [UI] Recommended-defaults preset (R2-48): confirmation/diff when overwriting customized values + undo/revert + post-apply feedback + dirty-state-save interaction defined.
- R3-26 [UI] Regime fail/unknown/loading states: scan-results panel shows "Regime: unknown — filter skipped (fail-open)" vs "MR skipped: regime data unavailable" (fail-closed); distinguish gate-passed vs gate-couldn't-evaluate; loading state while scan-time BTC-vol/regime fetches run.
- R3-27 [UI] Grandfathered-position indicator: account switched strategy/cohort shows "N open positions managed under previous config" banner; resolves the visual collision where a grandfathered position shows a TREND chip under an MR-cohort account.
- R3-28 [UI] Cross-scan cohort conflict (R2-52 first-config-wins) surfaces a config-time warning when one account carries conflicting cohorts across scheduled scans; F3-12 concentration warning has a stated home (fleet view).

## Total Requirements Count: ~208 (R1+R2+R3)
## Rounds Completed: 3

---

# Round 4 Additions (+25 requirements; scope locked; critical arch bug)

## FINAL SCOPE (D21 — user decision)
- v1 = ALL 3 features. F2 = BOTH directions live (long: default-off, opt-in, server-enforced ack, regime-gated). Backtest DEFERRED to v2.
- Dropped from v1: X-1..X-4, R3-6, R3-7, R2-44 (backtest replay/parity), QA <1%-deviation test. KEPT: `market_regime.py` shared module (live).

## Architecture — Reuse Seams (ARCH#1-5)

- R4-1 [ARCH-BUG CRITICAL] The existing `price_drift` gate (auto_trade_service.py:1128-1146) is INVERTED for MR: trend skips when price already moved in signal direction (move consumed); MR FADES and WANTS a deeper extreme. Blindly reusing `_try_trade` systematically skips MR's best setups + admits its worst. Golden snapshot (all-off) can't catch it. Gate extraction MUST classify each gate strategy-agnostic vs trend-only; the router skips/inverts trend-only gates (price_drift, and min_score/confidence vs F2-15's `mr_extreme_min_abs_score`) for MR. Explicit price-drift-under-fade test required.
- R4-2 [ARCH] `market_regime.py` is MARKET-scoped (BTC scalar/scan) vs `ai_manager_regime.compute_regime` PER-SYMBOL. MR fade is per-symbol but gated by BTC regime — document MR eligibility explicitly as a market-PROXY gate (not per-symbol regime). Keep the two classifiers separate (different scope/inputs); share the concept, not the math. R3-14 references the MARKET label set.
- R4-3 [ARCH] R2-30 gate extraction targets MODULE-LEVEL PURE functions (or a stateless `GateChain` parameterized by config + computed payload + injected clock + counters), not executor-private methods — so the same gate logic is unit-testable in isolation and reusable (also serves QA-G2 enabled-path characterization). The testable seam is the stated purpose.
- R4-4 [ARCH] Scan-GLOBAL computed data (regime/vol/mean — identical across 21 configs) routes through a scan-level context object passed to the executor, NOT injected per-config. Reserve per-config `_computed_*` for genuinely per-config data (adaptive_blacklist). If any computed data stays in-config, strip `_computed_*` before the `_json.dumps(config)` scans-table insert (scanner_service:449) to avoid per-scan JSONB bloat over ~570 symbols.
- R4-5 [ARCH] Define `route_strategy(cohort, regime) -> {"trend","mean_reversion","none"}` as a single pure component owning totality (R3-14) + contested-symbol precedence (R2-10). It MUST run BEFORE all strategy-scoped gates. Canonical chain order: `cohort → route_strategy → strategy-scoped gates (incl. strategy-scoped adaptive_blacklist) → trend-only/agnostic gates → resolve_final_side`. (Fixes the unsequenced dependency where strategy-scoped adaptive_blacklist at line 1070 runs before strategy is known for `both`.)

## Backend — Service Boundaries (BACKEND#1-5)

- R4-6 [RECONCILER CRITICAL] `position_reconciler.py` must be strategy-aware. MR placement is 3 sub-steps (order submit → `create_trade` strategy write → per-trade close-rule register); define the partial-failure contract so an order that fills but whose row/rule write fails is NOT re-adopted as default `'trend'` (which would: skip MR exits, break AI-mgr exclusion, poison trend blacklist). Reconciler reconstructs/honors strategy tag.
- R4-7 [RESILIENCE] `start_scan` precompute block (≤21 BTC fetches + regime build + 570-symbol mean/breadth assembly + injection) wrapped in global try/except with a bounded time budget; on failure/timeout, degrade globally (F1 → no suppression, F2 → no MR, trend proceeds) — an enabled-feature precompute crash must NEVER abort the scan and regress core trend trading.
- R4-8 [OBSERVABILITY] Trace-volume control: ~570×21×~10 new skip reasons must not saturate the bounded drop-on-pressure debug buffer (evicting load-bearing placement/error/fail-closed traces). Per-decision skips emit at debug level + per-scan aggregate at info; per-scan emission cap / sampling for high-cardinality suppression traces.
- R4-9 [STATE] Pin `_AccountState` MR-counter (`mr_trades_executed`) reset-vs-carry across all 4 phases (evaluate_result → execute_batch → fill → post_scan_recheck) so `mr_max_trades` is a per-scan cap (not overshooting N×4); resume/`restore_state` (R2-47) rehydrates it.
- R4-10 [PIPELINE] One canonical cross-feature gate order defined as a single pipeline (per R4-5) with deterministic skip-reason precedence on multi-gate failure. Explicitly resolve: on a `both`-cohort account in ranging regime (router → MR), do F1 session/vol gates ALSO gate the MR entry, or only trend? DECISION: F1 session + BTC-vol gates are market-condition gates that apply to BOTH strategies; breadth gate applies to trend only (MR intentionally wants few signals). Documented + tested.

## Security (SEC-R4)

- R4-11 [KILL-SWITCH-SEC] The per-feature kill switch has its OWN secure design: stored server-side in a store NOT influenced by client/per-account JSONB config; writable only via an authenticated admin path; audit-logged with actor; read synchronously on the hot path (cached flag, no per-symbol DB hit). The safety mechanism must not itself be client-injectable.
- R4-12 [AUDIT-INJECTION] New free-text/string fields (cohort, reason details, marker payloads) are sanitized/enum-constrained before entering logs/audit to prevent log-injection; reason codes are enum (R2-31), not free strings.
- R4-13 [RATE-LIMIT] New BTC kline fetches route through the existing `bybit_rate_gate` so a rapid manual-scan loop can't hammer Bybit into a ban; cache-first (R2-38) bounds fetch frequency.

## Testing Strategy (QA-G2..G7; G1 dropped per backtest deferral)

- R4-14 [TEST-E2E] An end-to-end integration test runs ONE full scan with all 3 features enabled and asserts the full manifest of placed trades (correct `strategy` tags) AND skips (correct reason codes) over a realistic scan_results set — gate composition, not just per-gate units.
- R4-15 [TEST-CHARACTERIZATION] Alongside the all-off golden snapshot (X-10), a per-feature ENABLED characterization snapshot proves each feature produces the EXPECTED decisions (not merely "different from off").
- R4-16 [TEST-FIXTURES] A versioned deterministic fixture corpus: BTC kline fixtures (regime/vol), per-symbol kline fixtures (MR mean), scan_results fixtures with extreme-marking scores, and a fixed injectable clock — shared by unit, E2E, and snapshot tests (load-bearing for R4-14/15, R3-10/14/16).
- R4-17 [TEST-ORACLE] The margin-% TP conversion (R2-1) tested against a table of independently hand-computed exchange-correct TP values for known (entry, leverage, distance-to-mean) — correctness oracle, not just clamp-on-garbage + self-consistency.
- R4-18 [TEST-PERF] A fan-out regression test asserts fetch-count bounds (BTC ≤ distinct tuples R2-38; mean once per symbol R2-39) AND all-on scan latency stays within budget vs the default-off baseline.
- R4-19 [TEST-PARITY] Sync/async parity tested behaviorally: write a trade carrying `strategy`/`strategy_cohort` through BOTH the sync and async persistence paths and assert identical persisted + read-back results (beyond R2-18's migration-list equality).
- R4-20 [TEST-COVERAGE] 90%+ line/branch coverage target for new modules (`market_regime.py`, gate predicates, `resolve_final_side`, route_strategy) stated as an acceptance gate.

## Product — Core-Value Analysis (Product-R4)

- R4-21 [ANALYSIS] Before sizing F1 as THE bleed fix, attribute the historical Asian-session bleed to entry-time-in-session vs positions-held-through-session. If hold-through dominates, F1 (entry-only) underdelivers and a session-aware exit/no-hold rule is needed (currently out of scope — flag for v2). Document the finding in the spec.
- R4-22 [PRODUCT] Out-of-the-box every account defaults to cohort `"trend"` → ZERO decorrelation until the operator re-cohorts. v1 ships the MECHANISM + bulk-assign affordance (R2-50); decorrelation is an explicit one-time operator setup task, stated (not assumed). F3-12 concentration warning surfaces if everyone lands in one cohort.

## Open Items Carried to Spec
- The `both`-cohort adds real complexity (R3-14/15, R4-5/10). Retained per D21a, but spec marks it the highest-complexity surface; plan may sequence it last within F3 so trend/mean_reversion cohorts ship first.

## Total Requirements Count: ~233 (R1-R4); ~8 backtest items deferred to v2
## Rounds Completed: 4

---

# Round 5 Resolutions (D22) — convergence; cuts + ratifications

These supersede earlier text where noted. The SPEC (next step) is authored from THIS resolved state.

## Scope cuts (v1 → v2)
- D22a [CUT] `both` strategy_cohort → v2. v1 enum = `Literal["trend","mean_reversion"]`. Decorrelation comes from cross-account diversity; no single account needs both. Removes within-account exposure ceiling (R3-15), most `both`-router hard cases (R4-5/R4-10), dual-counter complexity (R2-9 simplified), contested-symbol precedence (R2-10/R2-52). NOTE: does NOT violate D21a (that lock = F2 long+short direction, not the F3 `both` cohort).
- D22b [CUT] Signal-breadth gate (F1-4, F1-14, `signal_breadth` reason) → v2. Only chop gate with no empirical basis; weakest proxy; trend-only; worsens trace volume. F1 ships with session + BTC-vol (both empirically grounded).

## Ratifications
- D22c [NAMING] `trades.strategy_kind` (NOT `strategy`) everywhere — avoids collision with `/strategies` router + `strategies` table + `strategy_id` FK. `place_trade(strategy_kind=)`, `route_strategy()->kind`, index `idx_trades_account_strategy_kind`. `strategy_cohort` unchanged.
- D22d [MODULE] New `backend/services/strategy_router.py` owns `route_strategy()`, `resolve_final_side()`, gate predicate functions, and the `GateChain`. `auto_trade_service` imports FROM it (no cycle). `market_regime.py` is separate (BTC compute).
- D22e [PERSIST] Scan-global regime/vol/mean persist to the existing `regime_snapshots` table, NOT config JSONB. Resolves the R2-23↔R4-4 contradiction: strip `_computed_*` before the config insert; F1-20 replay reads `regime_snapshots`. `_computed_*` in config reserved for adaptive_blacklist only.
- D22f [F2-LONG ACK] Concrete: `mr_long_ack: bool` field (default false) + a server-side ack record table (account_id, acked_at, acked_leverage, acked_capital_pct); authenticated write path; re-ack required when `mr_leverage`/`mr_capital_pct` escalate. Server rejects long-fade entry when ack absent/stale → skip reason `mr_long_unacknowledged`.
- D22g [BACKTEST-SAFETY] `BacktestCreateRequest` keeps `extra="forbid"` so a backtest request carrying any F1/F2/F3 field FAILS LOUDLY ("backtest does not yet simulate these features") — no silent trend-only results.
- D22h [MIGRATION] Migration 44 is ONE multi-clause statement (comma-separated `ADD COLUMN`, single trailing semicolon) adding both `trades.strategy_kind` + `trades.strategy_cohort` (catalog-only, one brief lock, no embedded `;`).

## New gaps resolved (R5)
- R5-G1 [RECONCILER] Encode `strategy_kind` in the exchange `orderLinkId` at submit so the reconciler reads it back when adopting an orphan; pre-submit pending-intent record as fallback; NEVER silent auto-`trend` (quarantine/flag-for-manual). Reconciler adoption INSERT added to the strategy_kind write-site checklist (R2-19).
- R5-G2 [RECHECK] `post_scan_recheck` close-rule recreate sources MR per-position params from the per-trade persisted record OR excludes already-open MR positions. Test: a 5-min MR time-stop survives a full recheck cycle without reverting to trend duration.
- R5-G3 [F1-EFFICACY] Persist `f1_active` + session-hour on allowed trend trades so trend PnL is sliceable before/after enabling F1 (F1 effect measurable in v1 despite backtest deferral). This is the minimal "did it work" surface.
- R5-G4 [TEST-DIRECTION] Fixture corpus + E2E + characterization + TP-oracle each exercise BOTH an overbought-extreme (short fade) AND an oversold-extreme (long fade, ack'd) with direction-specific geometry assertions. Long-fade path cannot ship green-with-zero-coverage.
- R5-G5 [ACCEPTANCE] Minimal testable criterion: each toggle renders + persists + round-trips (set→save→reload) on EACH surface {manual scan, scheduled scan, per-account settings}. Resolve F1/F2 per-account home: cohort gets an account-settings editor (R3-23); F1/F2 toggles are scan-config (per `AutoTradeConfig`) — "per-account" = the per-account AutoTradeConfig in the scan forms (the literal original ask). Documented.
- R5-G6 [CI-TEST] A CI-gated test asserts DB CHECK enum == Pydantic `Literal` set-equality across all enum domains (`trading_accounts.strategy_cohort`, `trades.strategy_cohort`, `trades.strategy_kind`); verify `route_strategy`'s `"none"` never reaches `create_trade(strategy_kind=)`.
- R5-G7 [VALIDATORS] Per-feature validator helpers + a single cross-field-invariant table in the spec (keep fields flat per R2-29; group the validators).
- R5-G8 [ACK-ESCALATION] Re-trigger `mr_long_ack` (or audit-log actor+timestamp) when `mr_leverage`/`mr_capital_pct` escalate while long enabled (folded into D22f).

## Supersessions (apply in SPEC; listed so nothing is implemented from stale text)
- F2-18: remove "(F1)" attribution + global "ranging ⇒ trend suppressed" framing — routing lives in `route_strategy`; a `trend`-cohort account runs trend in ALL regimes.
- F1-2 / F1-5 / F1-6 / F1 feature desc: F1 session + BTC-vol gates apply to BOTH strategies (market-condition gating); F1 disabled ⇒ no gate; regime computed when ANY consumer enabled (D8).
- D9 cuts now final: no `regime_filter_mode`/`score_penalty` (F1-7/8), no `realized_vol` option (F1-11 → atr_ratio only), no `mr_allowed_regimes` list (F2-9 → scalar `mr_regime`), no multi-basis (F2-10 → EMA only).
- AF5 / R2-11 / X-6 / R2-34 / R2-42: regime/vol/mean flow via the scan-context object (D22e), not per-config `_computed_*`.
- R2-45 clock rationale = test determinism (not backtest). X-9 folds into R2-32. R2-17 (backtest version coord) moot.

## Clean build phase order (architecture-ratified, acyclic)
Phase 0 Foundation (under all-off golden snapshot): migrations 43/44/45 + sync/async parity, ReasonCode enum, gate extraction to pure functions in `strategy_router.py`, scan-context scaffolding.
Phase 1 Shared compute: `market_regime.py`, `start_scan` precompute + global try/except degrade + budget, fan-out memoization, injectable clock.
Phase 2 F3 routing backbone: `route_strategy()`, cohort field/resolution/migration, canonical pipeline order, reconciler strategy-awareness.
Phase 3 F1: session/vol gates (strategy-agnostic vs trend-only classification).
Phase 4 F2 (MR): resolve_final_side, mean precompute, place_trade(strategy_kind=) + TP conversion/clamps, exits, guards, long-ack/security.
Phase 5 Hardening + UI + tests: trace-volume control, kill-switch security, frontend sub-components, E2E/characterization/fixtures/oracle/perf/parity.

## Total Requirements Count: ~233 active (+ R5 resolutions); `both`-cohort + breadth + ~8 backtest items deferred to v2
## Rounds Completed: 5

---

# Round 6 Resolutions — convergence (architecture declared converged)

R6: architecture agent → "Converged, only mechanical text cleanup." Security + QA each found ONE substantive item; both resolved below. Remaining work = mechanical find/replace the spec author performs (the supersession + rename + cut cleanups enumerated in R5/R6).

- R6-1 [RECONCILER, supersedes R5-G1 mechanism] The exchange `orderLinkId` encoding is INFEASIBLE: existing path uses a 36-char UUID v4 with a UNIQUE index + idempotency guard (FR-004), and Bybit V5 `orderLinkId` max = 36 chars — a `mr-<uuid>` prefix overflows, truncation breaks the UUID/idempotency contract. RESOLUTION: the **pre-submit pending-intent record** (a DB row keyed by the SAME order_link_id UUID, carrying `strategy_kind` directly) is the PRIMARY reconciler join; quarantine/flag-for-manual is the terminal fallback; NEVER silent auto-`trend`. Drop the orderLinkId-encoding clause. (This is simpler than R5-G1's original two-mechanism proposal.)
- R6-2 [TEST, R5-G9] Negative-path ack tests are required (the most safety-relevant new gate): assert (a) long-fade entry REJECTED when ack absent → `mr_long_unacknowledged`; (b) REJECTED when ack stale; (c) re-ack required when `mr_leverage`/`mr_capital_pct` escalate while long enabled (stateful: ack@L1 → escalate L2 → reject until re-ack). Adds to the R4 testing set.
- R6-3 [CLARIFY] `regime_snapshots` holds only the scan-global BTC regime/vol scalar (one row/scan), NOT the ~570 per-(symbol,period) MR means. MR means live in the scan-context object in memory + are captured per-trade at placement (R3-12/R5-G2); they are not persisted to regime_snapshots. (Corrects D22e wording that grouped "regime/vol/mean".)
- R6-4 [MECHANICAL — for spec author] Apply the enumerated cleanups: remove `both` from F3-1/F3-6/F3-9/R2-13/R2-14 CHECK/R3-14/feature-desc/Open-Items; remove breadth from F1-16/F1-17/F1-19/R2-40/R4-10/X-18/R2-30 helper; rename `strategy`→`strategy_kind` in R2-1/R2-14/R2-15(index)/R2-19/R2-24/R2-25/R3-16/R3-20/R4-14/R4-19. (R5-G6 CI test catches any missed CHECK-enum drift.)

## Total Requirements Count: ~233 active; cuts applied (`both`, breadth → v2); R6 = 1 reconciler simplification + 1 test add + clarifications
## Rounds Completed: 6

---

# Round 7-8 Resolutions — convergence confirmed

R7 (3 agents): ALL "CONVERGED — ready for spec", zero findings → first clean round.
R8 (2 agents): one inventory correction below; otherwise "CONFIRMED CONVERGED".

- R8-1 [MIGRATION INVENTORY] Two new CREATE TABLE migrations were not inventoried (the 43/44/45 list covered only cohort/kind columns + index). Both are routine EMPTY-table creates (no backfill, no lock risk, catalog-only, IF NOT EXISTS) that ride the existing forward-only + sync/async-parity (R2-18) + write-site-checklist (R2-19) rails:
  - **Migration 46:** `f2_long_ack` record table (account_id, acked_at, acked_leverage, acked_capital_pct) — the server-authoritative anchor for the F2-long acknowledgement (D22f). MUST be a separate table (not JSONB) so a crafted config request cannot forge the ack (X-20/R3-20); enables the stateful re-ack-on-escalation test (R6-2).
  - **Migration 47:** `pending_trade_intents` table (order_link_id UUID PK, account_id, strategy_kind, created_at) — the pre-submit intent record the reconciler joins on (R6-1).
  - Both thread through R2-17 reserved-block reservation, R3-4 version-skew coordination, R2-18 parity, and the migration-version-collision merge checklist. Final v1 migration set: 43, 44, 45, 46, 47 (numbers finalized at merge per R2-17).

## FINAL Total: ~235 active requirements; v2-deferred: `both` cohort, signal-breadth gate, backtest integration, range-break exit, circuit-breaker
## Rounds Completed: 8 (R7 clean; R8 one inventory fix)

---

# Round 9-10 — final convergence (2 consecutive clean rounds achieved)

R9 (2 agents): both "CONVERGED" with one sub-blocker nit (folded below). R10 (confirmation): clean.

- R9-1 [REFINEMENT] The F2-long re-ack escalation trigger (D22f/R5-G8) extends to `mr_max_trades` as well as `mr_leverage`/`mr_capital_pct` — all three scale aggregate negative-EV long-fade exposure, so any escalation of them while long is enabled invalidates a prior ack. Trigger set = {mr_leverage↑, mr_capital_pct↑, mr_max_trades↑}. The `f2_long_ack` table (migration 46) therefore carries `acked_leverage`, `acked_capital_pct`, AND `acked_max_trades`.
- R2-18 wording note: "all 3 migrations" → now 5 (43-47); the final set declared in R8-1 governs.

## CONVERGENCE REACHED — requirements complete after 10 rounds (R7, R9, R10 clean; 2 consecutive clean at R9→R10). Ready for Step 4 (Spec authoring).
## Rounds Completed: 10







