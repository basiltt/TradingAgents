# Phase 4 — F2 Mean-Reversion Strategy

**Entry criteria:** Phase 3 complete (F1 gates, routing, cohort, reconciler; golden snapshot green).
**Exit criteria:** MR fades extreme signals to a mean-target in ranging regime, both directions (long gated by server ack); margin-% TP correct (oracle test); per-position tight-SL + time-stop fire; all F2 guards fire (incl. under relaxed); MR excluded from AI manager; fail-closed on missing data; all-off golden snapshot green.

**Goal:** the chop strategy. Reuses `place_trade` with a server-derived `strategy_kind="mean_reversion"`, pre-inverts the side via `resolve_final_side(mr_fade=True)`.

---

## Cross-phase context (self-contained)
- `route_strategy` (Phase 2) selects "mean_reversion" when cohort=mean_reversion AND `ctx.regime`==mr_regime. `resolve_final_side(signal_dir, reverse, mr_fade=True)` gives the fade side.
- TP formula (FR-022): `margin_tp_pct = (mr_target_capture_pct/100) × (|entry−mean|/entry) × mr_leverage × 100`, clamp `min(exchange_max_tp_pct, distance_implied_max)`.
- Exits (FR-023): tight-SL via `mr_tight_stop_pct`→`stop_loss_pct`; time-stop via `mr_time_stop_minutes`→`max_trade_duration_hours=min/60` (FLOAT) written on the per-position `close_rules` row.
- Long-ack (FR-027): `f2_long_ack` table is the sole gate; `mr_long_ack_requested` config ignored.

---

## TASK-4.0 — Add `strategy_kind` param to `place_trade` (PD4 — prerequisite)
- **Requirements:** FR-024, FR-050.
- **Files:** modify `backend/services/accounts_service.py` (`place_trade` at :199), `backend/services/trade_repository.py` (`create_trade` INSERT — done in Phase 2 TASK-2.5).
- **CODEBASE NOTE (PD4):** `place_trade` currently has NO strategy param, and `source` is validated to `{manual,cycle,scanner}` — so strategy_kind is a NEW separate param (do NOT fold into `source`).
- **Implementation:** add `strategy_kind: str = "trend"` to `place_trade(...)`; thread it into the `create_trade(...)` call it makes. Trend trades default "trend" (unchanged behavior — golden snapshot proves it).
- **Tests:** `test_place_trade_defaults_trend()` (golden parity); `test_place_trade_passes_strategy_kind()`.
- **Verification:** golden snapshot green.
- **AC:** AC-004. **Rollback:** remove param.

## TASK-4.1 — MR entry selection + side + TP/SL computation
- **Requirements:** FR-020, FR-021, FR-022, FR-024, SD9.
- **Files:** modify `auto_trade_service.py` (MR placement branch in `_try_trade`), use `market_data.compute_ema_mean` result from `ctx.means`.
- **Implementation:**
  - Eligible when route=="mean_reversion" AND `abs(score) >= mr_extreme_min_abs_score`.
  - **Staleness gate (PR1-2, fail-closed):** if `ctx.is_stale(now, cfg["regime_staleness_minutes"])` → skip `mr_regime_stale` (R2-F5: distinct reason, not conflated with `mr_regime_excluded`; the 4-phase cycle spans minutes–hours so this is reachable in-scan; a degraded ScanContext is always stale).
  - mean = `ctx.get_mean(symbol, mr_mean_period, mr_mean_interval)`; if None → skip `mr_mean_unavailable`/`mr_insufficient_history` (fail-closed).
  - entry = `ctx.get_price(symbol)` (PR1-9: precomputed per-symbol mark price, account-independent — NOT a per-account `get_mark_price` call on the hot path); if None → skip `mr_price_unavailable` (R2-F5, fail-closed).
  - fade side = `resolve_final_side(direction, cfg.reverse, mr_fade=True)`.
  - `margin_tp_pct` per formula, clamped; tight-SL = `mr_tight_stop_pct or default`.
  - Call `place_trade(..., take_profit_pct=margin_tp_pct, stop_loss_pct=tight_sl, leverage=mr_leverage, capital_pct=mr_capital_pct, strategy_kind="mean_reversion", trade_direction="straight")` (pre-inverted side; never reuse `reverse` knob).
- **Tests:** `test_mr_short_fade_overbought()`; `test_mr_long_fade_oversold_with_ack()` (T-05 both directions); `test_mr_tp_oracle()` (T-06 hand-computed exchange-correct TP for known entry/leverage/distance); `test_mr_mean_unavailable_fails_closed()`; `test_mr_skips_when_context_stale_beyond_ttl()` (PR1-2) + `test_mr_proceeds_within_ttl()`.
- **Verification:** `pytest tests/backend/test_mean_reversion.py -k "entry or tp" -x -q`.
- **AC:** AC-004. **Rollback:** remove MR branch.

## TASK-4.2 — F2 safety guards (all fire under relaxed)
- **Requirements:** FR-025, FR-026, EC-06, T-17.
- **Files:** modify `auto_trade_service.py` MR branch.
- **Implementation (each → skip + distinct reason, BEFORE place_trade, fire even when relaxed=True):**
  1. degenerate target: TP on wrong side of entry → `mr_degenerate_target`.
  2. inverted geometry: tight-SL distance > TP distance → skip/clamp (no SL/TP cross).
  3. no edge: `|entry−mean|/entry × 100 < mr_min_edge_pct` → `mr_no_edge`.
  4. fee-band: TP% ≤ round-trip fee+slippage estimate → skip.
  5. liquidation: SL beyond leverage-implied liquidation price → skip/clamp.
- **Tests:** `test_degenerate_target_skips()`; `test_inverted_geometry_skips()`; `test_no_edge_skips()`; `test_fee_floor_skips()` (T-17); `test_sl_inside_liquidation()` (T-17); `test_guards_fire_under_relaxed()` (EC-15).
- **Verification:** `pytest tests/backend/test_mean_reversion.py -k guard -x -q`.
- **AC:** AC-004. **Rollback:** remove guards (only if F2 disabled).

## TASK-4.3 — Per-position exit registration (tight-SL + time-stop, float)
- **Requirements:** FR-023, FR-053, EC-08, SD2, T-20.
- **Files:** modify `auto_trade_service.py` (register close rule after successful place), `close_rule_evaluator.py` (read per-position params).
- **CODEBASE NOTE (PD6 — GOOD NEWS):** `close_rules.threshold_value` is `NUMERIC(20,8)` (async_persistence:944), already read as `float(rule["threshold_value"])` (close_rule_evaluator:456) / `Decimal` (:361). So `0.083h` stores with full precision — **NO migration 49 needed; the contingency is DROPPED.**
- **Implementation:**
  - After `place_trade` success, register a `MAX_DURATION` close rule with `threshold_value = mr_time_stop_minutes/60.0` (FLOAT hours — `NUMERIC(20,8)` holds it; no truncation). Store on the per-position `close_rules` row (existing columns).
  - `post_scan_recheck` recreate sources from the rule row (or excludes open MR positions).
- **Tests:** `test_time_stop_float_no_truncation()` (EC-08, 5min→0.083h not 0); `test_recheck_preserves_mr_params()` (T-20, 5-min stop survives recheck); `test_both_account_trend_duration_not_clobbered()`.
- **Verification:** `pytest tests/backend/test_mean_reversion.py -k exit -x -q`.
- **AC:** AC-004. **Rollback:** revert to account-config duration.

## TASK-4.4 — Pre-submit pending-intent write (keyed by account/symbol/side)
- **Requirements:** FR-051, R6-1.
- **Files:** modify `auto_trade_service.py` (call `pending_intents.write_intent` BEFORE `place_trade`), delete after `create_trade` success.
- **Implementation (PD5):** `write_intent(account_id, symbol, side, "mean_reversion")` before submit; `delete_intent(account_id, symbol, side)` after `create_trade`. Reconciler (Phase 2) matches by `(account_id, symbol, side)` — NOT order_link_id (never sent to exchange).
- **Tests:** `test_intent_written_before_submit()`; `test_intent_deleted_after_create_trade()`.
- **Verification:** `pytest tests/backend/test_mean_reversion.py -k intent -x -q`.
- **AC:** AC-008. **Rollback:** remove intent write.

## TASK-4.5 — F2-long acknowledgement (table + endpoints + gate)
- **Requirements:** FR-027, SD28, AC-006, AC-007, T-07, PR1-7, PR1-8.
- **Files:** create `backend/routers/` handlers `POST /accounts/{id}/f2-long-ack` AND `POST /admin/kill-switch`; create `backend/services/f2_long_ack.py`; modify MR branch (long-fade gate).
- **Implementation:**
  - Ack endpoint: authed (owner/admin ownership assertion); snapshots CURRENT server-side persisted config exposure (mr_leverage/mr_capital_pct/mr_max_trades) — does NOT trust client body (SD28); writes `f2_long_ack` row.
  - **Admin kill-switch endpoint (PR1-7):** `POST /admin/kill-switch {feature_name, killed}` — admin-only authz, upserts `feature_kill_switches` (sets the `killed` column), populates `updated_by`/`updated_at` (audit). The manual blast-radius control complementing the auto-disable.
  - Long-fade gate (fires even under `relaxed=True` — PR1-8): when route=mean_reversion AND fade side=long → also `if ctx.is_killed("f2_long"): skip FEATURE_KILLED`; require a fresh ack row where `acked_leverage>=cfg.mr_leverage AND acked_capital_pct>=cfg.mr_capital_pct AND acked_max_trades>=cfg.mr_max_trades`; else skip `mr_long_unacknowledged`. If `mr_long_enabled` false → `mr_long_disabled`.
  - `mr_long_ack_requested` config field is IGNORED server-side.
- **Tests:** `test_long_rejected_without_ack()` (AC-006); `test_long_rejected_when_ack_stale_after_escalation()` (AC-007, T-07); `test_long_allowed_with_fresh_ack()`; `test_ack_snapshots_server_config_not_client_body()` (SD28); `test_cross_account_ack_403()` (NFR-005); `test_long_ack_required_under_relaxed()` (PR1-8 — ack gate not bypassed by fill-to-max); `test_admin_kill_switch_requires_admin_403()` + `test_admin_kill_switch_audits_updated_by()` (PR1-7).
- **Verification:** `pytest tests/backend/test_mean_reversion.py -k ack -x -q`.
- **AC:** AC-006, AC-007, AC-010. **Rollback:** disable long side (default).

## TASK-4.6 — MR counter + AI-manager exclusion + signal_performance split
- **Requirements:** FR-028, FR-029, FR-030, FR-052, T-15, T-16, T-19.
- **Files:** modify `auto_trade_service.py` (`_AccountState.mr_trades_executed` at :1260; AI auto-enable at :1196), `ai_account_manager_service.py` (position filter), `scanner_service._compute_adaptive_blacklist` (strategy-scoped).
- **Implementation:**
  - `_AccountState.mr_trades_executed` enforces `mr_max_trades` as a per-scan cap across all 4 phases; rehydrated on resume.
  - One-symbol-one-strategy: MR placement adds to the same `existing_symbols`/`traded` sets (FR-029).
  - AI manager exclusion (PD3 — two distinct sites): (a) the AUTO-ENABLE trigger at `auto_trade_service.py:1196` (`if cfg.get("ai_manager_enabled")... enable()`) must SKIP when the just-placed trade is MR (don't auto-enable AI off an MR fill); (b) the POSITION FILTER in `ai_account_manager_service.py` excludes `strategy_kind='mean_reversion'` positions from AI management (FR-052).
  - adaptive_blacklist computed strategy-scoped (MR losses don't poison trend blacklist).
- **Tests:** `test_mr_counter_per_scan_cap_across_phases()` (T-19); `test_mr_counter_rehydrates_on_resume()`; `test_one_symbol_one_strategy()` (T-16); `test_mr_success_does_not_auto_enable_ai()` (T-15a, at :1196); `test_ai_manager_filters_mr_positions()` (T-15b); `test_mr_loss_not_in_trend_blacklist()`.
- **Verification:** `pytest tests/backend/test_mean_reversion.py -k "counter or ai or blacklist" -x -q`.
- **AC:** AC-004, AC-015. **Rollback:** revert state/AI changes.

---

## Phase 4 Validation (exit gate)
```
python -m pytest tests/backend/test_mean_reversion.py tests/backend/test_regime_golden_snapshot.py -x -q
```
MR both directions (long ack-gated) + TP oracle + guards + exits + AI exclusion + fail-closed + golden snapshot green → Phase 4 complete. Commit: `feat(regime): phase 4 — F2 mean-reversion (margin-% TP, per-position exits, long-ack, AI exclusion, fail-closed)`.

## Phase 4 → traceability
FR-020/021/022/024/SD9→T-4.1; FR-025/026/EC-06/T-17→T-4.2; FR-023/053/EC-08/T-20→T-4.3; FR-051→T-4.4; FR-027/SD28/T-07→T-4.5; FR-028/029/030/052/T-15/16/19→T-4.6.
