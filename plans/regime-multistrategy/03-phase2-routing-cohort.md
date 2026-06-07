# Phase 2 — F3 Routing, Cohort, Reconciler

**Entry criteria:** Phase 1 complete (ScanContext populated, kill-switch, golden snapshot green).
**Exit criteria:** `route_strategy` + `resolve_final_side` pass their truth tables; cohort field persists + resolves with correct precedence; the canonical gate pipeline orders cohort→route→strategy-scoped→trend-only→side; reconciler is strategy-aware via pending-intent (never silent-trend); all-off golden snapshot still green.

**Goal:** build the routing backbone — the heart of F2/F3 — so a signal is routed to exactly one strategy per account, and orphaned positions recover their strategy tag. With cohort defaulting to "trend" and MR disabled, behavior is unchanged.

---

## Cross-phase context (self-contained)
- `route_strategy(cohort, regime) -> Literal["trend","mean_reversion","none"]`; `resolve_final_side(signal_dir, reverse, mr_fade) -> Literal["long","short"]` (pure, in `strategy_router.py`).
- Cohort precedence (FR-040): per-scan config `strategy_cohort` > stored `trading_accounts.strategy_cohort` > "trend".
- Gate taxonomy (SD12): trend-only = {min_score, confidence_filter, price_drift}; strategy-scoped = {adaptive_blacklist}; rest agnostic. `route_strategy` output drives which gates run.
- Reconciler: `position_reconciler.py`; pending-intent table `pending_trade_intents` keyed by `(account_id, symbol, side)` (PR1-14: NOT order_link_id — Bybit position reconciliation returns no orderLinkId, so orphans are matched by symbol/side, which the reconciler already does).

---

## TASK-2.1 — `route_strategy` (pure, TDD)
- **Requirements:** FR-004, FR-041, EC-05.
- **Files:** modify `backend/services/strategy_router.py`.
- **Implementation:**
  ```python
  def route_strategy(cohort: str, regime: str, *, mr_regime: str = "ranging") -> Literal["trend","mean_reversion","none"]:
      if cohort == "trend": return "trend"          # trend-cohort runs trend in ALL regimes
      if cohort == "mean_reversion":
          return "mean_reversion" if regime == mr_regime else "none"  # MR only in mr_regime
      return "trend"   # unknown cohort → safe default
  ```
- **Tests:** `test_route_trend_cohort_all_regimes()` (trend in ranging/trending/volatile/unknown); `test_route_mr_cohort_ranging()` → mean_reversion; `test_route_mr_cohort_trending()` → none; `test_route_mr_cohort_unknown_regime()` → none (fail-closed); `test_route_unknown_cohort_defaults_trend()`.
- **Verification:** `pytest tests/backend/test_strategy_router.py -k route -x -q`.
- **AC:** AC-005. **Rollback:** remove function.

## TASK-2.2 — `resolve_final_side` (pure, exhaustive truth table)
- **Requirements:** FR-005, R2-33, T-08.
- **Files:** modify `strategy_router.py`.
- **Implementation:**
  ```python
  def resolve_final_side(signal_dir: str, reverse: bool, mr_fade: bool) -> Literal["long","short"]:
      # base direction from signal
      base = "long" if signal_dir in ("buy","long") else "short"
      # apply exactly one composition; reverse XOR mr_fade flips; reverse AND mr_fade = identity
      flip = reverse ^ mr_fade
      return ("short" if base == "long" else "long") if flip else base
  ```
- **Tests:** exhaustive parametrized truth table over {signal_dir∈(buy,sell)} × {reverse∈(T,F)} × {mr_fade∈(T,F)} = 8 cases, each asserting the exact expected side; explicitly pin `reverse=True ∧ mr_fade=True ⇒ identity (no double-invert)`.
- **Verification:** `pytest tests/backend/test_strategy_router.py -k resolve_final_side -x -q`.
- **AC:** AC-004. **Rollback:** remove function.

## TASK-2.3 — Cohort resolution + canonical gate pipeline order
- **Requirements:** FR-040, FR-041, FR-042, FR-043, SD12, R4-5.
- **Files:** modify `auto_trade_service.py` (`_try_trade`), `strategy_router.py` (`GateChain`).
- **Implementation:**
  - Resolve cohort once per (account, scan): config override > account field > "trend"; inject as `state.cohort`.
  - Pipeline order in `_try_trade`: (0) **master kill-switch (PR1-1/R2-F4):** `if ctx.is_killed("__all__"): emit FEATURE_KILLED + skip` (only `__all__` is knowable before routing) → (1) resolve cohort → (1b) **per-feature kill:** `if ctx.is_killed(feature_for(cohort)): skip FEATURE_KILLED` (cohort is now known: mean_reversion-cohort→"f2", trend-cohort→"f1") → (2) `route_strategy(cohort, ctx.routing_regime(cfg["btc_vol_interval"], cfg["btc_vol_lookback_candles"]), mr_regime=cfg["mr_regime"])` → if "none" emit `cohort_mismatch`/`mr_regime_excluded` and skip → (3) strategy-scoped gates (adaptive_blacklist, MR-scoped variant) → (4) market-condition gates (F1 — Phase 3, no-op here) → (5) trend-only gates (min_score/confidence/price_drift) SKIPPED when strategy=="mean_reversion" → (6) `resolve_final_side` → place. (PD9: `ScanContext.routing_regime(interval, lookback)` returns `btc[(interval,lookback)].regime`, or "unknown" if absent/degraded.)
  - Kill-switch feature key: "f1" for trend-cohort, "f2" for mean_reversion-cohort; "f2_long" additionally checked for long-fade (Phase 4). With all features off, `kill` is empty → no-op (golden parity).
  - For strategy=="trend" the chain is IDENTICAL to today (golden snapshot proves it).
- **Tests:** `test_cohort_precedence_config_over_account()`; `test_cohort_unknown_rejected()`; `test_trend_cohort_runs_all_trend_gates()` (golden parity); `test_mr_strategy_skips_trend_only_gates()` (min_score/price_drift not applied); `test_first_config_wins_on_conflict()` (FR-043); `test_killed_feature_suppresses_placement()` (PR1-1/AC-010 — a flipped kill row blocks a would-be trade); `test_kill_master_key_suppresses_all()`.
- **Verification:** golden snapshot green; `pytest tests/backend/test_strategy_cohort.py -x -q`.
- **AC:** AC-005. **Rollback:** revert pipeline to inline.

## TASK-2.4 — Cohort persistence wiring (account column + read-back)
- **Requirements:** FR-040, R2-24.
- **Files:** modify `accounts_service.py` (read/write `strategy_cohort`), account response schema, `frontend/src/api/client.ts`.
- **Implementation:** `trading_accounts.strategy_cohort` (migration 43, Phase 0) read on account fetch + write on `PATCH /accounts/{id}`; default "trend" for legacy rows; expose in account response.
- **Tests:** `test_account_cohort_roundtrip()`; `test_legacy_account_defaults_trend()`.
- **Verification:** `pytest tests/backend/test_accounts*.py -k cohort -x -q`; `cd frontend && npx tsc --noEmit`.
- **AC:** AC-005. **Rollback:** remove field from serializer.

## TASK-2.5 — Strategy-kind tagging at `create_trade` (both INSERT paths)
- **Requirements:** FR-050, R2-19, R3-16.
- **Files:** modify `backend/services/trade_repository.py` (`create_trade` at :109, `create_child_trade` at :658 — NOTE PD1: the method is `create_child_trade`, NOT `create_partial_close_child`; `UPDATABLE_COLUMNS` at :51).
- **Implementation:**
  - `create_trade(... , strategy_kind: str = "trend", strategy_cohort: str = "trend")` → write both columns + `f1_active` (default false; set by Phase 3). PD4: the explicit `INSERT INTO trades (...)` column list (:136, ~22 columns + `$N` placeholders) MUST be extended with the 3 new columns + placeholders.
  - `create_child_trade` (:658) inherits `parent["strategy_kind"]` AND `parent["strategy_cohort"]` (NOT current account value). PR1-13: the `create_child_trade` INSERT (:669) has its OWN explicit column list that must ALSO add `strategy_kind`/`strategy_cohort`/`f1_active` (+ `$N` placeholders) — else child rows take the migration-44 DEFAULT 'trend' and mislabel MR partial-close PnL.
  - Add `strategy_kind`, `strategy_cohort`, `f1_active` to `UPDATABLE_COLUMNS` (:51) if mutated.
  - `strategy_kind` is server-derived — NEVER read from a request payload. (NOTE PD4: `place_trade` itself also needs a new `strategy_kind` param — see Phase 4 TASK-4.0.)
- **Tests:** `test_create_trade_tags_strategy()`; `test_child_trade_inherits_parent_strategy()` (R3-16); `test_strategy_kind_not_client_settable()`.
- **Verification:** round-trip through the async persistence path (T-09 partial).
- **AC:** AC-004, AC-008. **Rollback:** default columns to 'trend'.

## TASK-2.6 — Reconciler strategy-awareness + pending-intent (keyed by account/symbol/side)
- **Requirements:** FR-051, R5-G1, R6-1, EC-11, T-12.
- **Files:** modify `position_reconciler.py` (orphan path at :144–161); create `backend/services/pending_intents.py` (write/read/GC).
- **CODEBASE NOTE (PD5):** `order_link_id` is generated INSIDE `create_trade` AFTER the exchange call and is NEVER sent to Bybit as `orderLinkId` (`place_market_order:325` omits it) — so an orphan cannot be joined by order_link_id. The reconciler ALREADY matches orphans by `(symbol, side)` and has `get_open_trades_by_symbol_side` (:719). Therefore `pending_trade_intents` is keyed by `(account_id, symbol, side)` (migration 47, PD5).
- **Implementation:**
  - `write_intent(account_id, symbol, side, strategy_kind)` — called BEFORE order submit (Phase 4 calls it).
  - On reconciliation, an orphaned position → match `pending_trade_intents` by `(account_id, symbol, side)` → adopt with recovered `strategy_kind`; if no intent row → quarantine/flag (the reconciler's EXISTING `ORPHAN_POSITION_DETECTED` + WS alert path — NOT silent 'trend').
  - `delete_intent(account_id, symbol, side)` after successful `create_trade`; background GC sweep removes intents older than TTL (mirror debug_trace retention).
- **Tests:** `test_reconciler_recovers_strategy_from_intent()`; `test_reconciler_no_intent_quarantines_not_trend()` (T-12, the safety-critical path); `test_intent_gc_sweep_removes_stale()`.
- **Verification:** `pytest tests/backend/test_position_reconciler.py -k strategy -x -q`.
- **AC:** AC-008. **Rollback:** revert reconciler to existing orphan-quarantine (already safe).

---

## Phase 2 Validation (exit gate)
```
python -m pytest tests/backend/test_strategy_router.py tests/backend/test_strategy_cohort.py tests/backend/test_position_reconciler.py tests/backend/test_regime_golden_snapshot.py -x -q
```
Truth tables green + cohort routing correct + reconciler never-silent-trend + golden snapshot green → Phase 2 complete. Commit: `feat(regime): phase 2 — route_strategy + resolve_final_side + cohort routing + strategy-aware reconciler`.

## Phase 2 → traceability
FR-004/041/EC-05→T-2.1; FR-005/T-08→T-2.2; FR-040..043/SD12→T-2.3; FR-040/R2-24→T-2.4; FR-050→T-2.5; FR-051/T-12→T-2.6.
