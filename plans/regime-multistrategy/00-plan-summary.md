# Implementation Plan Summary: Regime Multi-Strategy (3 Optional Features)

## A. Metadata
- **Plan:** Regime Multi-Strategy v1 — F1 Session/Regime Filter, F2 Mean-Reversion, F3 Strategy-Cohort
- **Date:** 2026-06-07
- **Author:** `/new-feature` Step 6
- **Status:** Draft
- **Spec:** `specs/regime-multistrategy-spec.md` (v1.0, converged 4 rounds)
- **Architecture:** `specs/regime-multistrategy-architecture.md` (converged 5 rounds)
- **Version:** 1.0

## B. Planning Summary
Three optional, default-off auto-trade features that adapt trading to market regime, driven by the 2026-06-07 profitability research (Asian-session bleed + 21-account correlation). Built on the existing `_try_trade` gate-chain pattern with two new pure modules (`market_data.py`, `strategy_router.py`), a frozen `ScanContext`, and migrations 43–48. F2 trades both directions (long behind a server-side ack — per user decision D21b). Every feature is byte-identical to current behavior when off (golden-snapshot enforced).

**Key files:** `backend/services/market_data.py` (new), `strategy_router.py` (new), `scan_context.py` (new), `scanner_service.py`, `auto_trade_service.py`, `close_rule_evaluator.py`, `position_reconciler.py`, `trade_repository.py`, `ai_account_manager_service.py`, `schemas/__init__.py`, `async_persistence.py`+`persistence.py`, `frontend/src/components/scanner/AutoTradeSection.tsx` + new sub-components, `frontend/src/api/client.ts`.

**Key risks:** RV-01 F2-long negative expectancy (mitigated: default-off, ack, kill-switch, per-strategy PnL); RV-05 price_drift inverted for MR (mitigated: gate taxonomy skip); RV-06 reconciler mislabel (mitigated: pending-intent + quarantine); RV-07 precompute failure regresses trend (mitigated: global degrade).

**Key assumptions:** auth layer exists for endpoints (A-001); kline cache available (A-002); v42 tolerates extra JSONB keys (A-003); `regime_snapshots` exists (A-004); PG≥11 (A-005).

## C. Phase List & Build Order (acyclic, architecture-ratified)

| Phase | File | Scope | Entry | Exit |
|-------|------|-------|-------|------|
| **0 — Foundation** | `01-phase0-foundation.md` | Migrations 43–48 (async-only), `ReasonCode` enum, config schema (28 fields + validators), `scan_context.py` scaffold, gate-chain extraction under golden snapshot | baseline tests pass | all-off golden snapshot byte-identical; migrations apply (idempotent + enum-parity); no sync/async parity test (PD2) |
| **1 — Shared Compute** | `02-phase1-market-data.md` | `market_data.py` (classify_regime + EMA mean + 2×lookback fetch), scan-time precompute in `start_scan` + global degrade + kill-switch read + single-flight + bounded cache | Phase 0 done | regime/vol/mean computed once/scan, fail-open/closed correct, perf within budget |
| **2 — F3 Routing** | `03-phase2-routing-cohort.md` | `route_strategy()`, `resolve_final_side()`, cohort field+migration+resolution, canonical gate pipeline order, reconciler strategy-awareness, pending-intent | Phase 1 done | cohort routes correctly; resolve_final_side truth table green; reconciler never silent-trend |
| **3 — F1 Filter** | `04-phase3-f1-filter.md` | Session gate (placement-UTC), BTC-vol gate, F1 umbrella toggle, f1_active tagging, suppression, override (FR-066) | Phase 2 done | F1 suppresses in blocked hours/vol band; fail-open; default-off parity |
| **4 — F2 Strategy** | `05-phase4-f2-meanrev.md` | MR placement (margin-% TP, strategy_kind, pending-intent write), per-position exits, guards, long-ack table+endpoint, MR counter, AI-mgr exclusion, signal_performance split | Phase 3 done | MR fades in ranging regime both directions (long gated by ack); fail-closed; exits fire |
| **5 — Frontend + Tests + Hardening** | `06-phase5-frontend-tests.md` | Sub-components, StrategyChip, PnL view, fleet/bulk, preset; client.ts types; E2E, characterization, fixtures, TP oracle, perf, parity, ack-negative, coverage; alerting/auto-disable | Phase 4 done | all FRs tested; 90% coverage; all ACs pass |

## D. Cross-Phase Dependencies & Shared Interfaces

- **`ScanContext`** (frozen dataclass, `scan_context.py`) — produced in Phase 1 (`scanner_service.start_scan`), consumed in Phases 2–4 (`_try_trade` via `strategy_router`). Contract (Phase 0 scaffolds the dataclass shape; Phase 1 populates):
  ```python
  @dataclass(frozen=True)
  class ScanContext:
      btc: dict[tuple[str,int], BtcRegime]    # (interval, lookback) -> BtcRegime  (metric dropped per PD8)
      means: dict[tuple[str,int,str], float]   # (symbol, period, interval) -> EMA
      prices: dict[str, float]                 # symbol -> mark price (PR1-9, account-independent precompute)
      computed_at: datetime                    # epoch when degraded (so is_stale → True, fail-closed)
      degraded: bool
      kill: dict[str, bool]                    # feature_name -> killed  (value == feature_kill_switches.killed column; killed=true means suppressed)
  # BtcRegime = {regime: Literal["ranging","trending","volatile","unknown"], vol_value: float|None, unavailable: bool}
  # helpers: get_btc(interval,lookback), routing_regime(interval,lookback), get_mean(symbol,period,interval),
  #          get_price(symbol), is_killed(feature), is_stale(now, ttl_minutes)
  ```
- **`route_strategy(cohort, regime, *, mr_regime="ranging") -> Literal["trend","mean_reversion","none"]`** — Phase 2; called first in `_try_trade`; Phases 3–4 gate on its output. Regime is read via `ScanContext.routing_regime(interval, lookback)`.
- **`resolve_final_side(signal_dir, reverse, mr_fade) -> Literal["long","short"]`** — Phase 2; used by Phase 4 placement.
- **`ReasonCode` enum** — Phase 0; extended/consumed by Phases 1–4 `_emit_decision` (real signature uses `**detail`).
- **Migrations 43–48 (ASYNC-ONLY)** — Phase 0 (43 cohort col, 44 trades tags, 46 ack, 47 intent keyed by (account,symbol,side), 48 kill-switch all on boot; 45 index out-of-band). **PD2: the sync `persistence.py` registry is DEAD (stuck at v35, `AnalysisDB` unused) — migrations go to `async_persistence.py` only; the sync/async parity test is DROPPED.** No migration 49/50 (PD6: `close_rules.threshold_value` is already NUMERIC(20,8), holds float hours).
- **`place_trade` gains a new `strategy_kind` param** (Phase 4 TASK-4.0) — it has none today and `source` is enum-restricted. `create_trade` INSERT column list extended (+3 cols).
- **`strategy_kind` write-site checklist** — Phase 0 defines; Phases 2 (`create_trade`/`create_child_trade`, reconciler) + 4 (`place_trade`, child inherits parent) wire all sites.

## E. Global Constants & Key Decisions
- Project root: `c:\Users\ttbasil\Desktop\Projects\PublicProjects\TradingAgents`
- Backend tests: `python -m pytest tests/backend/ -x -q`; typecheck FE: `cd frontend && npx tsc --noEmit`; build FE: `npm run build`
- New modules: `backend/services/{market_data,strategy_router,scan_context}.py`
- Migration set: 43,44,46,47,48 (boot, catalog-only, ASYNC-ONLY — sync registry is dead), 45 (out-of-band index). No 49/50 (close_rules already NUMERIC).
- Naming: `trades.strategy_kind` (NOT `strategy` — collision with /strategies); `strategy_cohort` (account + trade); both `TEXT` + CHECK
- Config: 28 new `AutoTradeConfig` fields (SD10's 26 + 2 classifier-tuning); `btc_vol_metric` NOT a field (atr_ratio constant per D9c)
- Fail policy: F1 OPEN, F2 CLOSED, precompute-failure global degrade
- Default-off = byte-identical (golden snapshot is the gate on Phase 0)

## F. Section-Index Map
- Migrations + schema + enum + extraction → `01-phase0-foundation.md`
- BTC classifier + EMA mean + precompute + cache → `02-phase1-market-data.md`
- route_strategy + cohort + reconciler + pending-intent → `03-phase2-routing-cohort.md`
- session/vol gates + f1_active + override → `04-phase3-f1-filter.md`
- MR placement + exits + ack + AI exclusion → `05-phase4-f2-meanrev.md`
- frontend + full test suite + alerting → `06-phase5-frontend-tests.md`

## G. Definition of Done (plan-level)
Each phase file is self-contained, has entry/exit criteria, exact file paths + signatures, per-task tests with input→output, validation commands, and rollback. Every spec FR maps to a task (traceability in each phase + consolidated in this summary at Step 16).
