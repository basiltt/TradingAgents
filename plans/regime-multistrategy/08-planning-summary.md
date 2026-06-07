# Planning Phase Summary — Regime Multi-Strategy (3 Optional Features)

**Date:** 2026-06-07
**Skill:** `/new-feature` (Steps 1–8 complete; Part 2 implementation is Steps 9–19)
**Status:** ✅ Planning complete — all artifacts converged, zero unresolved Critical/High findings.

---

## What was planned

Three OPTIONAL, default-off, per-account features driven by the 2026-06-07 profitability research, each enable-able from BOTH the Scheduled Market Scan Form and the per-account Auto Trade Form (the same shared `AutoTradeSection.tsx`):

- **F1 — Regime/Session Entry Filter:** suppress trend entries during the proven money-losing Asian/low-vol session (UTC 01, 06–12) + optional BTC realized-vol/ATR band.
- **F2 — Mean-Reversion Strategy:** a second strategy active only in "ranging" regime; fades extremes to a mean-target with fast/tight exits; both directions (long behind a server-side acknowledgement — your decision D21b).
- **F3 — Strategy-Cohort Accounts:** route each account to a `trend` or `mean_reversion` cohort to decorrelate the 21-account fleet.

## Artifacts produced

| Artifact | File | Review |
|----------|------|--------|
| Requirements | `specs/regime-multistrategy-requirements.md` | 10 rounds, 2 consecutive clean (~235 reqs) |
| Architecture | `specs/regime-multistrategy-architecture.md` | 5 rounds, 2 consecutive clean (16 sections) |
| Specification | `specs/regime-multistrategy-spec.md` | 4 rounds, 2 consecutive clean (FR-001..067, NFR, AC-001..017) |
| Implementation Plan | `plans/regime-multistrategy/00-plan-summary.md` + `01..06` phase files | 4 rounds, 2 consecutive clean + codebase-alignment validation |
| Progress Tracker | `plans/regime-multistrategy/progress-tracker.md` | live |

**Total: 23 multi-agent review rounds across planning.**

## Key decisions you made

- **D21a:** all 3 features in v1 (together).
- **D21b / D6:** F2 trades BOTH directions live (long behind default-off + opt-in + server-side acknowledgement). ⚠️ Standing risk RF1: longs have negative expectancy in your data — mitigated by ack gate, kill-switch, per-strategy PnL visibility, auto-disable, persistent UI warning.
- **D21c:** backtest integration deferred to v2 (you chose live-immediately).

## Scope cuts to v2 (made during review to keep v1 shippable)

`both`-cohort (intra-account dual-strategy), signal-breadth gate, backtest replay/parity, F2 range-break exit, full auto circuit-breaker, session-aware EXIT rule, VWAP/BB-mid means, score_gate F1 mode.

## What the build touches

- **New modules:** `backend/services/market_data.py`, `strategy_router.py`, `scan_context.py`.
- **Migrations:** 43–48 (async-only — sync registry confirmed dead), 45 index out-of-band.
- **Modified:** `scanner_service`, `auto_trade_service`, `close_rule_evaluator`, `position_reconciler`, `trade_repository`, `ai_account_manager_service`, `accounts_service` (new `place_trade` `strategy_kind` param), `schemas/__init__.py`, frontend `AutoTradeSection` + new sub-components + `client.ts`.

## Codebase truths the plan-validation caught (and the plan now reflects)

- `place_trade` has no strategy param → one is added (defaults "trend", golden-snapshot-safe).
- Method is `create_child_trade`, not `create_partial_close_child`.
- Sync `persistence.py` is dead (stuck at v35, unused) → migrations are async-only; the sync/async parity test was dropped.
- `close_rules.threshold_value` is `NUMERIC(20,8)` → holds float-minute time-stops; no contingency migration needed.
- `order_link_id` is never sent to Bybit → pending-intent is keyed by `(account, symbol, side)` (what the reconciler already matches on), with quarantine-first as the always-safe fallback.

## Build order (acyclic, architecture-ratified)

Phase 0 Foundation (migrations, config, ReasonCode, gate extraction — golden-snapshot guarded) → Phase 1 Shared compute (market_data + precompute + kill-switch) → Phase 2 Routing (route_strategy, cohort, reconciler) → Phase 3 F1 filter → Phase 4 F2 strategy → Phase 5 Frontend + full test suite + hardening.

Each phase exits only when the all-off golden snapshot is byte-identical (guaranteeing zero behavior change until a feature is explicitly enabled).

## Readiness

- ✅ All FRs map to a task + test + acceptance criterion.
- ✅ Two HIGH plan-review findings resolved (kill-switch now enforced + read unconditionally; staleness wired into MR placement).
- ✅ Zero unresolved Critical/High findings.
- ✅ Plan is codebase-aligned and executable.

**Ready for Part 2 (Steps 9–19): worktree → per-phase TDD implementation → cross-phase validation → final hardening → merge.**
