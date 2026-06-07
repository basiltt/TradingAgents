# Phase 5 — Frontend + Full Test Suite + Hardening

**Entry criteria:** Phases 0–4 complete (all backend behavior + golden snapshot green).
**Exit criteria:** all toggles render/persist/round-trip on each surface; StrategyChip + per-strategy PnL view + fleet/bulk + preset shipped; full test suite (E2E, characterization, fixtures, perf, parity, ack-negative) green; 90%+ coverage on new modules; alerting + auto-disable wired; all ACs pass.

**Goal:** the user-facing surfaces, the exhaustive test layer, and operability (alerts, auto-disable). The literal original ask — "enable-able from both forms" — is satisfied by the shared `AutoTradeSection.tsx`.

---

## Cross-phase context (self-contained)
- `AutoTradeSection.tsx` is mounted by BOTH `ScannerPage` (manual) and `ScheduledScansPage` (scheduled). Patterns: `ToggleRow`, `DEFAULT_CONFIG`, `onChange({field})`, localStorage `STORAGE_KEY`, `Notice`, neumorphism.
- 28 config fields (SD10's 26 + 2 classifier-tuning) already in backend + `client.ts` (Phase 0). DEFAULT_CONFIG must add them.

---

## TASK-5.1 — Per-feature sub-components + DEFAULT_CONFIG
- **Requirements:** FR-060, FR-061, R2-36, AC-012.
- **Files:** create `RegimeFilterFields.tsx`, `MeanReversionFields.tsx`, `CohortField.tsx` under `frontend/src/components/scanner/`; modify `AutoTradeSection.tsx` (mount them + extend `DEFAULT_CONFIG`).
- **Implementation:** group under a "Market Regime & Strategy" section; F1 24-cell UTC hour grid + presets + local-time hover + "blocks X%/day" preview; F2 fields + persistent danger Notice on long-enable + acknowledgement checkbox → `POST /accounts/{id}/f2-long-ack`; `CohortField` 2-way selector showing inherited account value. All conditional sub-fields reveal on parent toggle.
- **Tests:** `AutoTradeSection.test.tsx` — `renders all toggles default off`; `each toggle set→save→reload round-trips` (T-13, AC-012) on ALL THREE surfaces — manual scan, scheduled scan, AND per-account config (PR1-16: AC-012 names three; if per-account shares the exact `AutoTradeSection` mount, assert that explicitly); `long-enable shows danger Notice + gates ack`.
- **Verification:** `cd frontend && npx tsc --noEmit && npm run build`; component tests green.
- **AC:** AC-012. **Rollback:** revert AutoTradeSection.

## TASK-5.2 — StrategyChip + per-strategy PnL view
- **Requirements:** FR-062, R3-21, R3-22, AC-016.
- **Files:** create `StrategyChip.tsx`; modify trades/positions tables + account-detail page (new PnL tab); modify `/trades/stats` consumer for `by_strategy`.
- **Implementation:** `<StrategyChip kind={trend|mean_reversion}/>` on trade rows/position cards; account-detail "Strategy" tab rendering strategy × direction × {PnL, win-rate, count, avg-hold} from `GET /trades/stats?...` `by_strategy` key.
- **Tests:** `StrategyChip.test.tsx`; `test_pnl_split_renders_strategy_x_direction()` (AC-016).
- **Verification:** `npx tsc --noEmit && npm run build`.
- **AC:** AC-016. **Rollback:** remove chip/tab.

## TASK-5.3 — Fleet roster (bulk cohort) + recommended-defaults preset + concentration warning
- **Requirements:** FR-063, FR-067, SD21, AC-014.
- **Files:** create `FleetCohortView.tsx`; add preset button to `AutoTradeSection`.
- **Implementation:** multi-select roster with "apply cohort to selected" + preview/confirm + partial-failure handling; concentration warning when a cohort > `cohort_concentration_pct` (70%) of the fleet; one-click "Apply research-recommended preset" (F1 hours 1,6–12 + vol band + conservative F2 sizing) with diff/confirm + post-apply feedback.
- **Tests:** `test_bulk_assign_preview_confirm()`; `test_concentration_warning_fires()` (AC-014); `test_preset_applies_recommended()`.
- **Verification:** `npx tsc --noEmit && npm run build`.
- **AC:** AC-014. **Rollback:** remove view.

## TASK-5.4 — Backend test suite: E2E + characterization + fixtures
- **Requirements:** T-02, T-03, T-04, R4-14, R4-15, R4-16.
- **Files:** create `tests/backend/test_regime_e2e.py`, `test_regime_characterization.py`, `tests/backend/fixtures/regime/` (BTC klines, per-symbol klines, overbought+oversold extreme scan_results, fixed clock).
- **Implementation:** E2E runs ONE full scan all-3-on → assert manifest of placed trades (correct strategy_kind) + skips (correct reason codes); characterization snapshots per-feature-ENABLED expected decisions; fixture corpus shared across unit/E2E/snapshot.
- **Tests:** `test_all_on_full_scan_manifest()` (T-03); `test_f1_enabled_characterization()`, `test_f2_enabled_characterization()`, `test_f3_enabled_characterization()` (T-02); `test_degraded_scan_f1_open_f2_closed()` (R3-F2/AD1: ONE degraded `ScanContext.empty(degraded=True)` scan simultaneously places a trend/F1 entry AND excludes F2 — the original HIGH bug, asserted as one scenario).
- **Verification:** `pytest tests/backend/test_regime_e2e.py tests/backend/test_regime_characterization.py -x -q`.
- **AC:** AC-002,004,005. **Rollback:** delete tests.

## TASK-5.5 — Perf + parity + alerting/auto-disable
- **Requirements:** T-10, T-18, T-19, FR-065, NFR-001, SD22.
- **Files:** create `tests/backend/test_regime_perf.py`; modify metrics/alerting (`observability.py`), auto-disable hook.
- **Implementation:**
  - Perf test: assert BTC fetch count ≤ distinct tuples, mean once/symbol, all-on scan latency within budget (≤+30s cold/+2s warm vs baseline). WORST-CASE fixture (R3-F1 perf): max fraction of extreme-score signals (max qualifying MR symbols) + heterogeneous (interval,lookback)/(period,interval) across the 50-account cohort (so dedup doesn't trivially collapse fetch_count) + the mandatory per-scan mark-price fetches (uncacheable across scans, so they hit the warm path too). Assert the analytical `ceil(fetch_count/concurrency) × per_fetch_latency ≤ budget` model AND one empirical wall-clock smoke check.
  - Auto-disable (constants SD22): F2-long → trip kill-switch when rolling drawdown over last 20 trades < −15%; F1 alert when suppression_rate > 95% over 8 scans. Min-sample guard (EC-14): a new/low-history account (< 20 trades) must NOT trip the breaker.
- **Tests:** `test_fetch_count_bounds()` (T-10); `test_scan_latency_within_budget()` (PR1-F4: inject per-fetch latency, assert `ceil(fetch_count/concurrency) × per_fetch_latency ≤ budget` over a 570×21 AND 570×50 corpus; warm-cache pass proves +2s); `test_f2_long_auto_disable_trips_kill_switch()` (T-18); `test_auto_disable_no_trip_below_min_sample()` (PR1-17/EC-14); `test_f1_suppression_alert()`.
- **Verification:** `pytest tests/backend/test_regime_perf.py -x -q`.
- **AC:** (ops). **Rollback:** remove hooks.

## TASK-5.6 — Coverage gate + final invariants
- **Requirements:** T-14, FR-064, T-24, NFR-010.
- **Files:** coverage config; `test_regime_invariants.py`.
- **Implementation:** 90%+ line AND branch on `market_data.py`, `market_data_fetch.py`, `strategy_router.py`, `scan_context.py`, `kill_switch.py`, `pending_intents.py`, `f2_long_ack.py`, and the gate predicates (PR1-12 — full new-module set, not just two); `test_feature_toggle_new_entries_only()` (T-24 — toggling does not re-manage open positions); trace-volume sampling assertion (NFR-010).
- **Tests (R2-F4 — per-module, not aggregate):** run coverage per new module so a weak module can't hide behind strong ones; assert each of `market_data.py`, `market_data_fetch.py`, `strategy_router.py`, `scan_context.py`, `kill_switch.py`, `pending_intents.py`, `f2_long_ack.py` ≥ 90% line AND branch (a small `test_coverage_per_module.py` that parses `coverage json` per file, or per-file pytest invocations with `--cov-fail-under=90`). Aggregate `--cov-branch --cov-fail-under=90` runs in CI as a backstop.
- **Verification:** coverage ≥ 90%; all invariants green.
- **AC:** all. **Rollback:** n/a.

---

## Phase 5 Validation (exit gate)
```
python -m pytest tests/backend/ -x -q
cd frontend && npx tsc --noEmit && npm run build && npm test
```
Full suite green + 90% coverage + all ACs → Phase 5 complete. Commit: `feat(regime): phase 5 — frontend (sub-components, StrategyChip, PnL, fleet, preset) + full test suite + alerting`.

## Phase 5 → traceability
FR-060/061→T-5.1; FR-062→T-5.2; FR-063/067→T-5.3; T-02/03/04→T-5.4; T-10/18/FR-065→T-5.5; T-14/FR-064/24→T-5.6.
