# Phase 0 — Foundation

**Entry criteria:** baseline `python -m pytest tests/backend/ -x -q` passes; worktree created.
**Exit criteria:** all-off golden snapshot byte-identical to pre-change; migrations 43–48 apply (idempotent + enum-parity, ASYNC-ONLY per PD2 — NO sync/async parity test); `ReasonCode` enum + 28 config fields land with validators; gate-chain extracted with zero behavior change.

**Goal:** lay the schema, config, enum, and code-structure foundation WITHOUT changing any runtime behavior. This phase is guarded end-to-end by a golden snapshot proving `_try_trade` decisions are byte-identical.

---

## Cross-phase context (self-contained)
- `_try_trade` is at `backend/services/auto_trade_service.py:1001` — a sequential skip-gate chain; each gate calls `self._emit_decision(account_id, phase, symbol, "skipped", reason, result, **kw)`.
- `AutoTradeConfig` at `backend/schemas/__init__.py:426` — Pydantic v2, `extra="forbid"`, optional fields + `@model_validator`.
- `_MIGRATIONS` registry: `async_persistence.py:776` (latest 42), sync twin `persistence.py:677`. Runner splits SQL on `;`, wraps each in a txn, bumps `schema_version`.
- Migration set: 43,44,46,47,48 catalog-only on boot; 45 index out-of-band.

---

## TASK-0.1 — Golden snapshot harness (TDD foundation, write FIRST)
- **Requirements:** FR-001, T-01.
- **Files:** create `tests/backend/test_regime_golden_snapshot.py`; create fixture `tests/backend/fixtures/regime/recorded_scan.json` (a recorded scan_results set + account configs + expected `_try_trade` decisions).
- **Implementation:**
  - Build a deterministic harness that runs the executor's `_try_trade` over the recorded scan with all-features-off configs and captures the ordered list of `(account_id, symbol, decision, reason, side, qty_basis, tp, sl, leverage)` tuples.
  - **Stub seam (PR1-4):** patch `accounts_service.place_trade` to record its call args (symbol, side, take_profit_pct, stop_loss_pct, leverage, capital_pct, strategy_kind) and return a synthetic fill (so no Bybit call); intercept `self._emit_decision` to capture skip tuples `(account_id, symbol, "skipped", reason)`. tp/sl/qty are captured at the `place_trade` boundary (they are computed inside it for trend, but the harness records the inputs passed to it).
  - Assert the captured manifest equals a stored golden file. On first run, generate the golden from current `main` behavior (commit it).
  - Use a fixed injectable clock (pass `now` into the harness) for determinism.
- **Tests:** `test_all_off_decisions_byte_identical()` — runs harness, asserts equality with golden.
- **Verification:** `python -m pytest tests/backend/test_regime_golden_snapshot.py -x -q` → green against current behavior.
- **AC:** AC-001. **Rollback:** delete test file.

## TASK-0.2 — `ReasonCode` enum (single source of truth)
- **Requirements:** FR-006, NFR-008.
- **Files:** create `backend/services/strategy_reason_codes.py`; modify `auto_trade_service.py` to import + use it in `_emit_decision` calls.
- **Implementation:**
  ```python
  from enum import Enum
  class ReasonCode(str, Enum):
      # existing (migrated from string literals)
      BLACKLIST = "blacklist"; WHITELIST = "whitelist"; ALREADY_HELD = "already_held"
      MAX_SIGNAL_AGE = "max_signal_age"; HOLD_SIGNAL = "hold_signal"
      MAX_SAME_DIRECTION = "max_same_direction"; MAX_SAME_SECTOR = "max_same_sector"
      ADAPTIVE_BLACKLIST = "adaptive_blacklist"; SIGNAL_SIDES = "signal_sides"
      MIN_SCORE = "min_score"; CONFIDENCE_FILTER = "confidence_filter"
      MAX_TRADES = "max_trades"; TARGET_GOAL_REACHED = "target_goal_reached"
      PRICE_DRIFT = "price_drift"; NO_BALANCE = "no_balance"
      # new (F1/F2/F3)
      SESSION_FILTER = "session_filter"; BTC_VOL_FILTER = "btc_vol_filter"
      VOL_UNAVAILABLE = "vol_unavailable"; COHORT_MISMATCH = "cohort_mismatch"
      MR_REGIME_EXCLUDED = "mr_regime_excluded"; MR_LONG_DISABLED = "mr_long_disabled"
      MR_LONG_UNACKNOWLEDGED = "mr_long_unacknowledged"; MR_NO_EDGE = "mr_no_edge"
      MR_DEGENERATE_TARGET = "mr_degenerate_target"; MR_MEAN_UNAVAILABLE = "mr_mean_unavailable"
      MR_INSUFFICIENT_HISTORY = "mr_insufficient_history"
      MR_FEE_FLOOR = "mr_fee_floor"; MR_SL_LIQUIDATION = "mr_sl_liquidation"   # PD10
      MR_INVERTED_GEOMETRY = "mr_inverted_geometry"                            # PD10
      FEATURE_KILLED = "feature_killed"                                        # PR1-1 (kill-switch gate)
      MR_REGIME_STALE = "mr_regime_stale"; MR_PRICE_UNAVAILABLE = "mr_price_unavailable"  # R2-F5
  ```
  - `_emit_decision` (real signature `auto_trade_service.py:66` uses `**detail`, not `**kw` — functionally identical) accepts `ReasonCode | str`; existing string call sites keep working (enum value == old string, so trace output is unchanged — critical for golden snapshot).
- **Tests:** `test_reason_code_values_match_legacy_strings()` — assert each enum `.value` equals the prior literal (guarantees golden snapshot unaffected).
- **Verification:** golden snapshot (TASK-0.1) still green after migration.
- **AC:** FR-006. **Rollback:** revert enum import, restore literals.

## TASK-0.3 — Config schema: new `AutoTradeConfig` fields + validators
- **Requirements:** FR-009..012, FR-020..028, FR-040, SD10 table, NFR-004.
- **Files:** modify `backend/schemas/__init__.py` (AutoTradeConfig); modify `frontend/src/api/client.ts` (TS interface mirror).
- **NOTE (PD8):** `btc_vol_metric` was cut in D9c (atr_ratio-only) — it is NOT a field; the metric is the constant `"atr_ratio"`. Total new fields = 28 (the SD10 table's 26 user-facing + `regime_volatile_atr` + `regime_trend_ema_dist_pct` classifier-tuning).
- **Implementation:** add all 28 optional fields per the SD10 table with exact types/defaults/bounds, e.g.:
  ```python
  regime_filter_enabled: bool = False
  session_filter_enabled: bool = False
  session_blocked_hours_utc: Optional[List[int]] = None   # each 0-23
  session_allowed_hours_utc: Optional[List[int]] = None
  btc_vol_filter_enabled: bool = False
  btc_vol_min_threshold: Optional[float] = Field(None, ge=0)
  btc_vol_max_threshold: Optional[float] = Field(None, ge=0)
  btc_vol_interval: Literal["15m","1h","4h"] = "1h"
  btc_vol_lookback_candles: int = Field(default=14, ge=2, le=200)
  mean_reversion_enabled: bool = False
  mr_short_enabled: bool = True
  mr_long_enabled: bool = False
  mr_long_ack_requested: bool = False
  mr_regime: Literal["ranging"] = "ranging"
  mr_mean_period: int = Field(default=20, ge=2, le=200)
  mr_mean_interval: Literal["15m","1h","4h"] = "1h"
  mr_target_capture_pct: float = Field(default=60, gt=0, le=100)
  mr_tight_stop_pct: Optional[float] = Field(None, gt=0, le=1000)
  mr_time_stop_minutes: int = Field(default=120, ge=5, le=1440)
  mr_min_edge_pct: float = Field(default=1.0, ge=0, le=100)
  mr_extreme_min_abs_score: float = Field(default=5.0, ge=0, le=10)
  mr_capital_pct: float = Field(default=2.0, gt=0, le=100)
  mr_leverage: int = Field(default=10, ge=1, le=125)
  mr_max_trades: int = Field(default=2, ge=1, le=999)
  strategy_cohort: Literal["trend","mean_reversion"] = "trend"
  regime_staleness_minutes: int = Field(default=30, ge=5, le=240)
  regime_volatile_atr: float = Field(default=2.0, gt=0, le=10)
  regime_trend_ema_dist_pct: float = Field(default=1.0, ge=0, le=50)
  ```
  - Validators (per-feature helpers): `validate_session_exclusive` (reject both blocked+allowed); `validate_vol_band` (min<max when both set); `validate_mr_direction` (≥1 of short/long when mean_reversion_enabled); `validate_hours_range` (0-23, dedup).
- **Tests:** `test_config_defaults_all_off()`; `test_session_blocklist_allowlist_mutual_exclusion()`; `test_vol_min_lt_max()`; `test_mr_requires_a_direction()`; `test_old_config_without_new_fields_loads()` (EC-12); `test_field_bounds_reject_out_of_range()`; `test_extra_keys_ignored_on_lenient_load()` (PR1-18/AD7: old v42 code re-validating new-written JSONB must tolerate extra keys — use a lenient model for persisted-config re-validation, or confirm the AD20 strip step).
- **Verification:** `pytest tests/backend/test_*schema* -x -q`; `cd frontend && npx tsc --noEmit`.
- **AC:** AC-011, AC-012. **Rollback:** remove fields.

## TASK-0.4 — `ScanContext` frozen dataclass scaffold
- **Requirements:** FR-003, AD5/AD15.
- **Files:** create `backend/services/scan_context.py`.
- **Implementation:** the frozen dataclass + `BtcRegime` TypedDict (PR1-3: btc keyed by `(interval, lookback)` — metric dropped per PD8):
  ```python
  @dataclass(frozen=True)
  class ScanContext:
      btc: dict[tuple[str,int], BtcRegime]    # (interval, lookback) -> BtcRegime
      means: dict[tuple[str,int,str], float]  # (symbol, period, interval) -> EMA
      prices: dict[str, float]                # symbol -> mark price (PR1-9, account-independent)
      computed_at: datetime
      degraded: bool
      kill: dict[str, bool]                   # feature_name -> killed
  ```
  - Helpers: `get_btc(interval, lookback) -> BtcRegime|None`; `routing_regime(interval, lookback) -> str` (returns `btc[(interval,lookback)]["regime"]` or `"unknown"` if absent/degraded — PR1-3/PD9); `get_mean(symbol, period, interval) -> float|None`; `get_price(symbol) -> float|None`; `is_killed(feature) -> bool` (`kill.get("__all__") or kill.get(feature, False)`); `is_stale(now, ttl_minutes) -> bool` (returns True immediately if `degraded`; else `(now - computed_at).total_seconds()/60 > ttl_minutes` — R2-F5); `ScanContext.empty(degraded=True, kill=None)` factory sets `computed_at = datetime(1970,1,1,tzinfo=utc)` (epoch → always stale → F2 fail-closed cleanly, no `now - None` crash), empty btc/means/prices, and carries the passed `kill` dict (R3-F1: so master/f1 kill is enforced even with no precompute; defaults to `{}` only if not provided).
- **Tests:** `test_scan_context_empty_degraded()`; `test_is_stale_boundary()` (EC-04 boundary); `test_routing_regime_unknown_when_absent()`; `test_is_killed_master_and_per_feature()`.
- **Verification:** `pytest tests/backend/test_scan_context.py -x -q`.
- **AC:** — **Rollback:** delete file.

## TASK-0.5 — Migrations 43,44,46,47,48 (boot, ASYNC-ONLY)
- **Requirements:** FR-040, FR-050, FR-007, FR-027, FR-051, NFR-009, T-09.
- **Files:** modify `async_persistence.py` (`_MIGRATIONS` at :776, latest v42); create `tests/backend/test_migration_apply.py`.
- **CODEBASE NOTE (PD2):** The sync `persistence.py` `_MIGRATIONS` (at :211) is DEAD — it ends at v35 (36–42 already missing) and `AnalysisDB` is imported nowhere; only `AsyncAnalysisDB` is wired (main.py:187, migrate.py:21). Therefore migrations are added to `async_persistence.py` ONLY, and the sync/async byte-parity test is DROPPED (it would fail on the pre-existing 36–42 gap and guards dead code). NFR-009's parity clause is void; if sync is ever revived, backport 36–48 first.
- **Implementation:** append to async `_MIGRATIONS` (after v42):
  - `(43, "ALTER TABLE trading_accounts ADD COLUMN IF NOT EXISTS strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK (strategy_cohort IN ('trend','mean_reversion'))")`
  - `(44, "ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_kind TEXT NOT NULL DEFAULT 'trend' CHECK (strategy_kind IN ('trend','mean_reversion')), ADD COLUMN IF NOT EXISTS strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK (strategy_cohort IN ('trend','mean_reversion')), ADD COLUMN IF NOT EXISTS f1_active BOOLEAN NOT NULL DEFAULT false")` (one statement, no inner `;`)
  - `(46, "CREATE TABLE IF NOT EXISTS f2_long_ack (account_id TEXT PRIMARY KEY, acked_at TIMESTAMPTZ NOT NULL, acked_leverage INT NOT NULL, acked_capital_pct REAL NOT NULL, acked_max_trades INT NOT NULL)")`
  - `(47, "CREATE TABLE IF NOT EXISTS pending_trade_intents (account_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, strategy_kind TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (account_id, symbol, side))")` (PD5: keyed by (account,symbol,side) — the tuple the reconciler already matches orphans by; NOT order_link_id, which is never sent to the exchange)
  - `(48, "CREATE TABLE IF NOT EXISTS feature_kill_switches (feature_name TEXT PRIMARY KEY, killed BOOLEAN NOT NULL DEFAULT false, updated_by TEXT, updated_at TIMESTAMPTZ)")` (R2-F2: column is `killed` — self-documenting, DEFAULT false = safe/not-killed; the `kill` dict value == the `killed` column verbatim)
  - Migration 45 (index) registered but NOT inline — see TASK-0.6.
- **Tests:** `test_migrations_apply_idempotent()` (run twice, IF NOT EXISTS); `test_check_enum_matches_pydantic_literal()` (R5-G6: CHECK enum == `Literal["trend","mean_reversion"]` for cohort + strategy_kind).
- **Verification:** start app against test DB → migrations apply clean; idempotent + enum-parity tests green.
- **AC:** AC-010, AC-011. **Rollback:** forward-only — runbook (NFR-012); for dev, drop columns/tables.
- **Planning confirmations:** verify `trading_accounts`/`trades` PK types; confirm PG≥11.

## TASK-0.6 — Migration 45 (out-of-band index) registration + startup healthcheck
- **Requirements:** NFR-009, NFR-012, AD18.
- **Files:** modify `async_persistence.py` (migration runner — add a "deferred/non-transactional" flag); modify `backend/main.py` (startup healthcheck warn).
- **Implementation:**
  - Register `(45, _DEFERRED_INDEX)` where the runner records the version but does NOT build inline; a background task (or documented ops step) runs `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_account_strategy_kind ON trades(account_id, strategy_kind, status)` outside any txn, under the existing advisory lock, with INVALID-index DROP+retry.
  - Startup healthcheck: if the index is absent or INVALID, `logger.warning("idx_trades_account_strategy_kind missing/invalid — per-strategy queries will seq-scan")` (warn, never crash).
- **Tests:** `test_index_healthcheck_warns_when_absent()` (mock catalog query); `test_index_build_lock_window_on_prod_snapshot()` (PR1-19/T-09/RV-03: assert the CONCURRENTLY build holds no blocking lock on a production-sized `trades` snapshot — or document as an ops-step check if not unit-testable).
- **Verification:** app starts clean with index absent (warn logged, no crash).
- **AC:** — **Rollback:** drop the deferred entry.

## TASK-0.7 — Gate-chain extraction to `strategy_router.py` (behavior-preserving)
- **Requirements:** NFR-008, R2-30, R4-3.
- **Files:** create `backend/services/strategy_router.py` (gate predicate stubs); modify `auto_trade_service.py` `_try_trade` to call the extracted predicates.
- **Implementation:** extract each existing gate into a module-level pure function `gate_<name>(ctx) -> SkipDecision | None` where `ctx` bundles config + signal + state + scan_context + clock. Initially these wrap the EXACT existing logic (no new gates yet). `_try_trade` becomes a thin loop over the gate list. The golden snapshot (TASK-0.1) is the proof of zero behavior change.
- **Tests:** golden snapshot must remain green after extraction; `test_gate_functions_pure()` (no I/O, deterministic).
- **Verification:** `pytest tests/backend/test_regime_golden_snapshot.py -x -q` green.
- **AC:** AC-001. **Rollback:** revert `_try_trade` to inline.

---

## Phase 0 Validation (exit gate)
```
python -m pytest tests/backend/test_regime_golden_snapshot.py tests/backend/test_migration_apply.py tests/backend/test_scan_context.py -x -q
cd frontend && npx tsc --noEmit
```
All green + golden snapshot byte-identical → Phase 0 complete. (PR1-5: migration test is `test_migration_apply.py`, NOT a parity test — sync registry is dead per PD2; arch AD14/NFR-009 parity clause is VOID.) Commit: `feat(regime): phase 0 foundation — migrations, config schema, ReasonCode enum, gate extraction (default-off, golden-snapshot guarded)`.

## Phase 0 → traceability
FR-001→T-0.1; FR-006→T-0.2; FR-009..028/040→T-0.3; FR-003→T-0.4; FR-007/027/040/050/051→T-0.5; NFR-009→T-0.5; NFR-012/AD18→T-0.6; NFR-008→T-0.7.
