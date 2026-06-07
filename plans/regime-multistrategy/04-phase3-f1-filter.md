# Phase 3 — F1 Session/Regime Entry Filter

**Entry criteria:** Phase 2 complete (routing backbone, cohort, reconciler; golden snapshot green).
**Exit criteria:** F1 suppresses entries in blocked UTC hours (placement-time) and outside the BTC-vol band; fail-open on data failure; `f1_active` tagged on allowed trends; one-time override works; all-off + F1-off golden snapshot byte-identical.

**Goal:** add the F1 gates into the canonical pipeline (Phase 2's market-condition slot). F1 is strictly subtractive.

---

## Cross-phase context (self-contained)
- F1 umbrella (FR-009): `regime_filter_enabled` gates BOTH session + vol sub-modes.
- Session gate evaluates trade-PLACEMENT UTC time (tz-aware), re-checked each phase (FR-010); blocked hours default [1,6,7,8,9,10,11,12].
- Vol gate (FR-012): suppress when `ctx.get_btc(...).vol_value` outside `[min,max]` (atr_ratio units); boundary allow-at-equality.
- F1 applies to BOTH trend and MR entries (market-condition); fail-open (FR-013/014).

---

## TASK-3.1 — Session gate (`gate_session`, placement-time UTC)
- **Requirements:** FR-009, FR-010, FR-011, FR-013, EC-01, T-11.
- **Files:** modify `strategy_router.py` (`gate_session`), `auto_trade_service.py` (wire into pipeline market-condition slot).
- **Implementation:**
  ```python
  def gate_session(cfg, now_utc: datetime) -> SkipDecision | None:
      if not (cfg.get("regime_filter_enabled") and cfg.get("session_filter_enabled")): return None
      hour = now_utc.astimezone(timezone.utc).hour
      blocked = set(cfg.get("session_blocked_hours_utc") or [])
      allowed = cfg.get("session_allowed_hours_utc")
      if allowed is not None: blocked = set(range(24)) - set(allowed)
      return SkipDecision(SESSION_FILTER) if hour in blocked else None
  ```
  - `now_utc` is injected (the clock) so placement time governs and tests are deterministic; re-evaluated in each phase (immediate/batch/fill/recheck).
- **Tests:** `test_session_blocks_in_window()`; `test_session_allows_outside()`; `test_session_boundary_HH00_and_HH59()` (EC-01); `test_session_uses_placement_utc_not_naive_local()` (T-11 — a +02 local 03:30 evaluates as UTC 01:30); `test_session_applies_to_both_strategies()`; `test_session_off_when_umbrella_off()`.
- **Verification:** golden snapshot green (F1 off); `pytest tests/backend/test_regime_filter.py -k session -x -q`.
- **AC:** AC-002. **Rollback:** remove gate from pipeline.

## TASK-3.2 — BTC-vol gate (`gate_btc_vol`, fail-open)
- **Requirements:** FR-012, FR-014, EC-03, EC-10.
- **Files:** modify `strategy_router.py` (`gate_btc_vol`).
- **Implementation:**
  ```python
  def gate_btc_vol(cfg, ctx) -> SkipDecision | None:
      if not (cfg.get("regime_filter_enabled") and cfg.get("btc_vol_filter_enabled")): return None
      btc = ctx.get_btc(cfg["btc_vol_interval"], cfg["btc_vol_lookback_candles"])  # PD8: metric is constant atr_ratio
      if btc is None or btc["unavailable"]:
          return None  # FAIL-OPEN: emit vol_unavailable trace but do not suppress
      v = btc["vol_value"]
      lo, hi = cfg.get("btc_vol_min_threshold"), cfg.get("btc_vol_max_threshold")
      if (lo is not None and v < lo) or (hi is not None and v > hi):
          return SkipDecision(BTC_VOL_FILTER)
      return None
  ```
  - On unavailable: emit a `vol_unavailable` trace (observability) but PROCEED (fail-open).
- **Tests:** `test_vol_suppresses_outside_band()` (AC-013); `test_vol_allows_inside_band()`; `test_vol_boundary_equality_allows()`; `test_vol_unavailable_fails_open()` (EC-03/EC-10 — proceeds + trace).
- **Verification:** `pytest tests/backend/test_regime_filter.py -k vol -x -q`.
- **AC:** AC-003, AC-013. **Rollback:** remove gate.

## TASK-3.3 — `f1_active` tagging on allowed trend entries
- **Requirements:** FR-015, R5-G3.
- **Files:** modify `auto_trade_service.py` placement (pass `f1_active=` to `create_trade`).
- **Implementation:** when F1 is enabled for the account AND the entry is allowed (passed session+vol), set `f1_active=true` on the trade row; session-hour is derived later from `created_at` UTC (no column).
- **Tests:** `test_f1_active_tagged_when_filter_on_and_allowed()`; `test_f1_active_false_when_filter_off()`.
- **Verification:** `pytest tests/backend/test_regime_filter.py -k f1_active -x -q`.
- **AC:** AC-009. **Rollback:** default f1_active false.

## TASK-3.4 — One-time session-filter override (FR-066)
- **Requirements:** FR-066, SD20, AC-017, T-23.
- **Files:** modify `scanner_service.py` (accept a per-run `ignore_session_filter` flag from the manual-scan API), `auto_trade_service.py` (honor it for one scan).
- **Implementation:** a manual scan may pass `ignore_session_filter=true` (confirmation-gated in UI); when set, `gate_session` + `gate_btc_vol` are skipped for THAT scan only (non-persistent, auto-reverts), the override is audit-logged, and entries placed under override are tagged so they are EXCLUDED from `f1_active` before/after stats.
- **Tests:** `test_override_bypasses_session_for_one_scan()`; `test_override_does_not_persist()` (next scan re-applies F1); `test_override_entries_excluded_from_efficacy()` (T-23).
- **Verification:** `pytest tests/backend/test_regime_filter.py -k override -x -q`.
- **AC:** AC-017. **Rollback:** remove flag handling.

---

## Phase 3 Validation (exit gate)
```
python -m pytest tests/backend/test_regime_filter.py tests/backend/test_regime_golden_snapshot.py -x -q
```
Session+vol suppress correctly + placement-UTC + fail-open + override + golden snapshot green → Phase 3 complete. Commit: `feat(regime): phase 3 — F1 session + BTC-vol entry filter (placement-UTC, fail-open, f1_active tagging, one-time override)`.

## Phase 3 → traceability
FR-009/010/011/013/EC-01/T-11→T-3.1; FR-012/014/EC-03/EC-10→T-3.2; FR-015/R5-G3→T-3.3; FR-066/SD20→T-3.4.
