# Specification: Regime Multi-Strategy (3 Optional Features)

## A. Title and Metadata

- **Feature:** Regime Multi-Strategy — 3 optional, default-off auto-trade features
- **Date:** 2026-06-07
- **Author:** `/new-feature` skill (Step 4)
- **Status:** Draft
- **Related user request:** "Profitability reduces in choppy markets — run multiple strategies on multiple markets. Build 3 optional features enable-able from the Scheduled Market Scan Form and the per-account Auto Trade Form."
- **Source docs:** `specs/regime-multistrategy-requirements.md` (10 rounds, converged), `specs/regime-multistrategy-architecture.md` (5 rounds, converged), `docs/research/reports/2026-06-07_01-26-profitability-report.md`
- **Related modules:** `scanner_service`, `auto_trade_service`, `close_rule_evaluator`, `position_reconciler`, `accounts_service`, `ai_account_manager_service`, `trade_repository`, `async_persistence`/`persistence`, frontend `AutoTradeSection`
- **New modules:** `backend/services/market_data.py`, `backend/services/strategy_router.py`, `backend/services/scan_context.py`
- **Version:** 1.0 (v1; backtest integration + `both` cohort + signal-breadth gate deferred to v2)

## B. Discovery Summary

- **`AutoTradeConfig`** (`backend/schemas/__init__.py:426`) — Pydantic v2, `extra="forbid"`, ~37 optional fields with defaults + paired `@model_validator`. The single home for all new per-account config.
- **`_try_trade`** (`backend/services/auto_trade_service.py:1001`) — a sequential "skip-if-filter-fails" gate chain; each gate calls `_emit_decision(account_id, phase, symbol, "skipped", reason, ...)`. New gates slot in here.
- **`_compute_adaptive_blacklist`** (`scanner_service.py:339,407`) — pre-computes a value and injects it into configs before the executor runs. The model for scan-time regime/vol/mean precompute.
- **`ai_manager_regime.compute_regime()`** (`ai_manager_regime.py:12`) — existing per-symbol classifier (trending_up/down/ranging/volatile/compression). Kept separate; new `market_data.py` is market-scoped (BTC).
- **`close_rule_evaluator.py`** — existing TRAILING_PROFIT / MAX_DURATION / BREAKEVEN_TIMEOUT / EQUITY_* triggers. F2 fast-exits reuse MAX_DURATION + stop_loss_pct.
- **`AutoTradeSection.tsx`** — shared by BOTH `ScannerPage` (manual scan) and `ScheduledScansPage` (scheduled scan). Editing it satisfies the "both forms" requirement. Patterns: `ToggleRow`, `DEFAULT_CONFIG`, `onChange({field})`, localStorage, `Notice`, neumorphism design system.
- **Migrations** — `_MIGRATIONS` registry in `async_persistence.py:776` (+ sync twin `persistence.py:677`), latest version 42, auto-apply on startup; runner splits SQL on `;` and wraps each migration in a transaction.
- **`trades` table** — has `source ∈ (manual,cycle,scanner)`, no `strategy` column; two INSERT paths (`create_trade` + `create_partial_close_child`).
- **Constraint:** money hot-path must stay fast and fail-open on optional-feature failure (existing price-drift gate at line 1146 uses bare `except: pass`).

## C. Feature Overview

Three OPTIONAL, default-off, per-account toggles that adapt trading to market regime — built because profitability research found the system bleeds in the choppy Asian/low-vol session (UTC 01, 06–12: ~−$1,335 over 5 days at 0–31% win rate) while the US/EU session prints 57–86% win rates, and that all 21 accounts clone identical signals (21× correlated drawdowns, not diversification).

- **F1 — Regime/Session Entry Filter:** suppress new trend entries during detected chop (UTC session-hour windows + optional BTC realized-vol/ATR threshold).
- **F2 — Mean-Reversion Strategy:** a second strategy active only in "ranging" regime; reuses LLM `scan_results`, fades range extremes, targets the mean, fast/tight exits; trades both directions (long behind a server-side acknowledgement).
- **F3 — Strategy-Cohort Accounts:** assign each account to a `trend` or `mean_reversion` cohort so the fleet decorrelates.

**Users:** the operator configuring scans (manual + scheduled) per trading account.

## D. Business Goal

- **Objective:** stop the choppy-market profit leak and convert the 21 cloned accounts into a decorrelated portfolio.
- **User value:** a one-toggle session filter expected to save ~$200–300/day; an optional chop strategy that earns where the trend engine bleeds; cohort routing that smooths the equity curve.
- **Operational value:** every feature default-off and byte-identical to today until enabled; per-account rollout (canary on one account first); kill-switch for instant blast-radius control.
- **Success:** F1 measurably reduces blocked-hour bleed (before/after on `f1_active`-tagged trends); F2 trades only in ranging regime with positive per-strategy PnL visibility; cohorts demonstrably reduce correlated drawdowns. Zero regression when all off.

## E. Current System Behavior

- Scheduled scan every 3h across ~570 coins → `scan_results` with direction/confidence/score → `AutoTradeExecutor` filters signals per `AutoTradeConfig` and places trades on Bybit across up to 21 accounts.
- `_try_trade` applies gates (blacklist, whitelist, already-held, signal-age, max-same-direction, sector, adaptive-blacklist, signal-sides, min-score, confidence, max-trades, target-goal, price-drift) then `place_trade(...)`.
- All accounts consume the SAME signals in the same cycle — no strategy differentiation, no regime awareness, no session filter.
- Close rules (TP/SL via place_trade; MAX_DURATION/BREAKEVEN/TRAILING/EQUITY via `close_rule_evaluator`) registered per account.
- **Limitations:** trend-short engine only; loses in ranging/Asian-session tape; 21× correlated exposure; no way to suppress entries by market condition.

## F. Expected New Behavior

- **Config:** `AutoTradeConfig` gains ~23 optional fields (F1 session/vol, F2 mean-reversion, F3 cohort) — all default-off; absent/old config behaves exactly as today.
- **Scan-time:** when any consumer is enabled, `start_scan` precomputes BTC market regime/vol (per param-tuple) and per-symbol EMA means (for qualifying MR symbols only), builds a frozen `ScanContext`, and reads the kill-switch once.
- **Entry:** `_try_trade` calls `route_strategy(cohort, regime)` → runs strategy-scoped then market-condition then trend-only/agnostic gates → `resolve_final_side()` → `place_trade(strategy_kind=...)`.
- **F1:** suppresses trend (and, for session+vol, MR) entries during chop; emits distinct skip reasons; tags allowed trends with `f1_active` + session-hour.
- **F2:** in ranging regime, fades extreme signals to a mean-target TP (converted to margin-%) with tight-SL + time-stop exits; long side requires a fresh server-side ack.
- **F3:** routes each account to its cohort's strategy; trades tagged with `strategy_kind` + point-in-time `strategy_cohort`.
- **Backend:** new `market_data`/`strategy_router`/`scan_context` modules; reconciler strategy-aware via pending-intent; AI manager excludes MR positions.
- **Data:** migrations 43–48 (cohort col, trades tags, index, ack table, pending-intent table, kill-switch table).
- **Validation:** all new fields server-validated/bounded; long-fade rejected without ack.
- **Errors:** F1 fail-open, F2 fail-closed, precompute failure → global degrade (trend proceeds), scan never aborts.

## G. Scope

### In Scope (v1)
- F1 session-hour + BTC-vol entry filter (default-off, per-account, both scan forms).
- F2 mean-reversion strategy (both directions; long behind server-side ack; ranging-regime-gated; reuses scan_results; EMA mean; margin-% TP; tight-SL + time-stop exits).
- F3 `trend`|`mean_reversion` cohort (per-account config field + persisted account column).
- New modules `market_data.py`, `strategy_router.py`, `scan_context.py`.
- Migrations 43–48; sync/async parity; `trades.strategy_kind`/`strategy_cohort`/`f1_active`.
- Reconciler pending-intent; AI-manager MR exclusion; kill-switch; per-strategy PnL view; StrategyChip; recommended-defaults preset; bulk cohort assignment.
- Full test suite (golden snapshot, E2E all-on, characterization, fixtures, TP oracle, perf, parity, ack negative-path).

### Out of Scope (deferred to v2)
- `both` cohort (intra-account dual-strategy); signal-breadth gate; backtest integration + <1% parity; F2 range-break exit; F2 auto circuit-breaker (a minimal safety auto-off to kill-switch IS in scope); VWAP/BB-mid mean bases; score_gate F1 mode; realized_vol metric option; session-aware EXIT rule (F1 is entry-only).

### Future Scope
- Shadow/observe mode, canary automation, before/after dashboard, A/B framework, what-if preview, periodic digest, proactive nudge.

## H. Functional Requirements

### Common / Framework
- FR-001: All new config fields default to off/none; with every feature disabled, `_try_trade` produces byte-identical decisions to current `main` (golden-snapshot enforced).
- FR-002: Each feature is configurable per-account from the shared `AutoTradeSection.tsx`, which is mounted in BOTH the manual Market Scan form and the Scheduled Market Scan form.
- FR-003: Regime/vol/mean are precomputed once per scan in `start_scan` (gated by "any consumer enabled" = F1 ∨ F2 ∨ MR-cohort) and exposed to the executor via a frozen `ScanContext`; the trade hot path performs no new network I/O except the already-cached `get_mark_price`.
- FR-004: `route_strategy(cohort, regime) → {"trend","mean_reversion","none"}` selects the strategy per (account, signal) and runs BEFORE all strategy-scoped gates.
- FR-005: `resolve_final_side(signal_dir, reverse, mr_fade) → "long"|"short"` computes the exchange side exactly once; the trend `reverse` knob and MR fade never double-invert.
- FR-006: New skip reasons are a `ReasonCode` enum (no magic strings): `session_filter`, `btc_vol_filter`, `vol_unavailable`, `cohort_mismatch`, `mr_regime_excluded`, `mr_long_disabled`, `mr_long_unacknowledged`, `mr_no_edge`, `mr_degenerate_target`, `mr_mean_unavailable`, `mr_insufficient_history`.
- FR-007: A per-feature kill switch (table `feature_kill_switches`, read once per scan at precompute) suppresses a feature when its row says `enabled=false`; a master key disables all; read failure fails closed; no row = not killed.

### F1 — Regime/Session Entry Filter
- FR-009: `regime_filter_enabled` is the F1 UMBRELLA master toggle; BOTH the session sub-mode (`session_filter_enabled`) and the BTC-vol sub-mode (`btc_vol_filter_enabled`) require it to be on. Session-only F1 needs NO BTC precompute (session is evaluated purely on placement-time UTC).
- FR-010: When `regime_filter_enabled` + `session_filter_enabled`, suppress new entries opened during any UTC hour in `session_blocked_hours_utc` (default [1,6,7,8,9,10,11,12]); evaluated against the trade-PLACEMENT UTC time (tz-aware), re-checked each phase.
- FR-011: Allowlist mode (`session_allowed_hours_utc`) is mutually exclusive with the blocklist; a validator rejects setting both.
- FR-012: When `regime_filter_enabled` + `btc_vol_filter_enabled`, suppress new entries when the scan-time BTC `atr_ratio` (from `market_data.classify_regime`) is outside `[btc_vol_min_threshold, btc_vol_max_threshold]`. Boundary is `<`/`>` (allow at exact equality).
- FR-013: F1 session + BTC-vol gates apply to BOTH trend and MR entries (market-condition gating); F1 is strictly subtractive — it may only skip entries, never create/upsize/up-leverage.
- FR-014: On BTC data failure, F1 fails OPEN (no suppression; emit `vol_unavailable`); F1 suppression still applies under `relaxed`/fill-to-max mode.
- FR-015: Each suppressed entry emits a distinct reason; allowed trend entries persist `f1_active=true` + the session-hour for before/after efficacy measurement.
- FR-016: A scan-level summary records suppressed/allowed counts, detected regime + inputs, and current UTC hour.

### F2 — Mean-Reversion Strategy
- FR-020: When `mean_reversion_enabled` and `route_strategy` selects `mean_reversion` (account cohort = mean_reversion AND scan-global BTC `market_data` regime = `mr_regime`, default "ranging"), F2 fades qualifying `scan_results` extremes (`abs(score) >= mr_extreme_min_abs_score`).
- FR-021: A strong overbought signal → SHORT-to-mean; a strong oversold signal → LONG-to-mean. `mr_short_enabled` default true; `mr_long_enabled` default false.
- FR-022: F2 computes the EMA mean over `mr_mean_period` klines at `mr_mean_interval`. TP percent-of-margin = `(mr_target_capture_pct/100) × (|entry−mean|/entry) × mr_leverage × 100`, clamped to `min(exchange_max_tp_pct, distance_implied_max)` where `distance_implied_max = (|entry−mean|/entry) × mr_leverage × 100` (capture=100%). The BTC market regime that gates F2 is the scan-global `market_data` regime (one `regime_snapshots` row/scan), NOT the per-symbol `ai_manager_regime` classifier.
- FR-023: F2 exits reuse existing machinery: tight-SL via `mr_tight_stop_pct` (→ `stop_loss_pct`), time-stop via `mr_time_stop_minutes` (→ `max_trade_duration_hours = minutes/60`, FLOAT, must not truncate 0.083h to 0). Both are captured PER-POSITION on the `close_rules` row at registration (existing per-position columns: `threshold_value`/`reference_value`/`cycle_id`), never re-read from shared account config at close-eval. If the existing MAX_DURATION column cannot hold minute-precision float hours, a per-rule minutes field is added (contingency migration 49, confirmed in planning).
- FR-024: F2 calls existing `place_trade(...)` with a server-derived `strategy_kind="mean_reversion"`; it pre-inverts the side and passes `trade_direction="straight"` (never reuses the `reverse` knob).
- FR-025: F2 guards (all fire under `relaxed`): skip `mr_degenerate_target` if TP on wrong side of entry; skip/clamp if tight-SL wider than TP (no SL/TP cross); skip `mr_no_edge` if distance-to-mean < `mr_min_edge_pct`; SL must sit inside leverage-implied liquidation; TP must clear round-trip fee+slippage.
- FR-026: F2 fails CLOSED — missing/stale regime or per-symbol mean (or candles < `mr_mean_period`) → no entry (`mr_mean_unavailable`/`mr_insufficient_history`); regime != `mr_regime` → `mr_regime_excluded`.
- FR-027: Long-fade entries require a fresh server-side acknowledgement (table `f2_long_ack`); the config `mr_long_ack_requested` is non-authoritative UI intent and is ignored server-side. Absent/stale ack → `mr_long_unacknowledged`. Ack goes stale when `mr_leverage`/`mr_capital_pct`/`mr_max_trades` escalate above the acked values.
- FR-028: F2 uses separate `mr_capital_pct`/`mr_leverage`/`mr_max_trades` (conservative defaults); `_AccountState.mr_trades_executed` enforces `mr_max_trades` as a per-scan cap across all phases, rehydrated on resume.
- FR-029: A symbol is never taken by both strategies in one cycle; MR placements add to the same `existing_symbols`/`position_directions`/`traded` structures as trend.
- FR-030: MR losses feed a strategy-scoped adaptive blacklist (not the trend blacklist); existing filters (max_same_direction, signal_sides post-fade, blacklist, sector) apply to the combined book.

### F3 — Strategy-Cohort Accounts
- FR-040: `AutoTradeConfig.strategy_cohort: Literal["trend","mean_reversion"]` (default "trend") + a persisted `trading_accounts.strategy_cohort` column; resolution precedence = per-scan config override > stored account field > "trend".
- FR-041: `trend`-cohort accounts ignore MR signals and run trend in ALL regimes; `mean_reversion`-cohort accounts ignore trend entries and run MR only in `mr_regime`. Cohort mismatch emits `cohort_mismatch`.
- FR-042: Cohort validates against a closed server-side enum; unknown values rejected. Cohort lookup failure resolves to "trend".
- FR-043: A scheduled/shared scan must not override a per-account safety toggle; if one account appears in multiple configs with differing cohorts, first-config-wins (documented).

### Strategy tagging, reconciler, AI manager
- FR-050: Every trade is tagged at `create_trade` with `strategy_kind` (server-derived, never client-settable) and denormalized point-in-time `strategy_cohort`; the partial-close child inherits BOTH from its parent.
- FR-051: Before submitting an MR order, a `pending_trade_intents` row (keyed by the order's UUID `order_link_id`) records `strategy_kind`; `position_reconciler` joins orphaned exchange positions to it to recover the tag; if unrecoverable, quarantine/flag — NEVER silent `trend`.
- FR-052: MR positions are excluded from the AI manager: an MR `_try_trade` success must not trigger AI auto-enable, and the AI manager filters out `strategy_kind='mean_reversion'` positions.
- FR-053: `post_scan_recheck` rule recreate sources MR per-position params from the per-trade persisted record (or excludes open MR positions) — tight-SL/time-stop survive a recheck.

### Frontend & operability
- FR-060: `AutoTradeSection.tsx` splits into `RegimeFilterFields`, `MeanReversionFields`, `CohortField` sub-components; each toggle renders + persists + round-trips (set→save→reload) on each surface {manual scan, scheduled scan, per-account config}.
- FR-061: F2-long enable surfaces a persistent danger Notice (negative-expectancy) + an acknowledgement that drives the server ack write; the cohort field shows the inherited account value and flags overrides.
- FR-062: A `<StrategyChip>` (TREND vs MEAN_REVERSION) renders on trades/positions surfaces; a per-strategy × per-direction PnL view (account-detail tab) shows {PnL, win-rate, count, avg-hold} — the manual-disable safety net.
- FR-063: A one-click "Apply research-recommended preset" sets F1 blocked hours (1,6–12) + vol band + conservative F2 sizing; a fleet roster allows bulk cohort assignment with preview/confirm.
- FR-064: Enabling/disabling a feature or changing cohort affects ONLY new entries; open positions keep their original management (surfaced via a "managed under previous config" indicator). Enabling writes a marker to research-history for longitudinal measurement.
- FR-065: A safety auto-disable trips the kill switch for F2-long if rolling drawdown breaches a threshold; alerts fire on F1 suppression_rate > 95% over N scans.

## I. Non-Functional Requirements

- NFR-001 (Perf): The trade hot path adds zero new network calls for F1/F3; all-on scan latency ≤ +30s cold-cache / ≤ +2s warm vs the default-off baseline.
- NFR-002 (Perf): BTC vol/regime memoized by distinct (metric, interval, lookback) tuple (≤21, typically 1–2 fetches/scan); MR mean fetched once per (symbol, lookback-bucket, interval) for qualifying symbols ∩ MR-enabled accounts only (not all 570); per-symbol reads single-flight-deduped across accounts.
- NFR-003 (Perf/Mem): Kline cache keyed (symbol, interval, lookback-bucket), capacity ≥ max per-scan working set + headroom (no intra-scan eviction), explicit entry cap + memory estimate; `ScanContext` shared by immutable reference (not deep-copied per config).
- NFR-004 (Security): All risk-bearing fields (leverage, capital_pct, cohort, strategy_kind, toggles) server-authoritative and re-validated; client/localStorage untrusted; JSONB keys whitelisted; `strategy_kind` server-derived only.
- NFR-005 (Security): F2-long ack unbypassable — the `f2_long_ack` table is the sole gate; ack/cohort/kill-switch writes require account-owner/admin authz (ownership assertion; cross-account → 403).
- NFR-006 (Reliability): F1 fails-open, F2 fails-closed; precompute orchestration failure → global degrade (trend proceeds), scan never aborts; single-flight rejected future → per-consumer policy (F1 open, F2 closed), fresh attempt next phase.
- NFR-007 (Reliability): BTC kline fetches route through `bybit_rate_gate`, strictly subordinate to order placement (never delay an order); kline cache TTL ≥ min manual-scan interval.
- NFR-008 (Maintainability): Gate predicates, `route_strategy`, `resolve_final_side` are module-level pure functions in `strategy_router.py` (no executor coupling), unit-testable in isolation; flat config fields with feature-prefix naming; per-feature validator helpers + a cross-field-invariant table.
- NFR-009 (Data integrity): Migrations forward-only, IF NOT EXISTS, no embedded semicolons, catalog-only on boot (43/44/46/47/48), index 45 out-of-band/background; sync+async `_MIGRATIONS` DDL-byte parity (CI test); CHECK enums == Pydantic Literals (CI test).
- NFR-010 (Observability): Every regime decision, session skip, MR entry, fail-open/closed activation, ack, and kill-switch flip logged to `debug_trace`; per-decision skips at debug level + per-scan aggregate at info; per-scan emission cap/sampling scaled by (symbols × accounts).
- NFR-011 (Compatibility): All API/response changes additive; old clients ignore unknown keys; persisted scheduled-scan configs re-validated with a LENIENT (ignore-extra) model distinct from the strict request-ingress model; `/trades/stats` retains top-level aggregates and adds a `by_strategy` key.
- NFR-012 (Deployability): Default-off enables dark deploy; per-account toggle = canary; rollback runbook sequences kill-switch-off → close MR positions → `UPDATE schema_version=42` (BEFORE code rollback) → deploy v42; pre-merge verify v42 config-load tolerates extra JSONB keys.
- NFR-013 (Scalability): Design holds to 50 accounts — per-symbol costs are account-independent via memoization + single-flight; `(mr_mean_interval, btc_vol_interval)` are Literal enums and `mr_mean_period` quantized to lookback-buckets so memo cardinality stays bounded.

## J. User Flows

**Primary — enable F1 on one account:** operator opens the scan form → expands "Market Regime & Strategy" → toggles Regime/Session Filter on → default blocked hours (UTC 1,6–12) pre-filled → saves → next scan suppresses entries in those hours (visible in scan summary) → allowed trends tagged `f1_active`.

**Primary — enable F2 (short) on a mean_reversion-cohort account:** operator sets cohort = Mean-Reversion → enables Mean-Reversion strategy → saves → in ranging regime, qualifying extremes fade to mean with tight exits; in trending regime, MR is suppressed (`mr_regime_excluded`) and the account places nothing (trend ignored by cohort).

**Alternate — enable F2 long side:** operator toggles "Enable long side" → persistent danger Notice appears → operator confirms acknowledgement → server writes `f2_long_ack` → long fades now permitted. If operator later raises `mr_leverage`, ack goes stale → long fades rejected (`mr_long_unacknowledged`) until re-acknowledged.

**Failure — BTC data unavailable:** precompute can't fetch BTC klines → F1 fails open (trend proceeds, scan summary shows "Regime: unknown — filter skipped") → F2 fails closed (MR skipped, "MR skipped: regime data unavailable").

**Edge — cohort change with open positions:** operator switches an account trend→mean_reversion → only NEW entries route to MR; existing trend positions keep trend management; a banner shows "N open positions managed under previous config".

**Permission-denied:** a non-owner POSTs to `/accounts/{id}/f2-long-ack` → 403.

## K. API Requirements

- **`POST /scanner/scan`, `POST/PUT /scheduled-scans`** — accept the new `AutoTradeConfig` fields (Pydantic, `extra="forbid"` — all declared/optional). Backward compatible (omitted → defaults). Existing routers: `backend/routers/scanner.py`, `scheduled_scans.py`.
- **`POST /accounts/{id}/f2-long-ack`** (new) — body `{leverage, capital_pct, max_trades}` (the acked exposure snapshot); writes `f2_long_ack`. Auth: account-owner/admin (ownership assertion). 200 on success, 403 unauthorized, 422 invalid.
- **`PATCH /accounts/{id}`** — accept/return `strategy_cohort`. Auth: owner/admin.
- **`POST /admin/kill-switch`** (new, admin-only) — `{feature_name, enabled}` → upsert `feature_kill_switches`, audit-logged.
- **`GET /accounts/{id}`** — returns `strategy_cohort` (additive).
- **`GET /trades`** — `strategy_kind` field on each row + optional `?strategy_kind=` filter (additive).
- **`GET /trades/stats`** — retains existing top-level aggregate keys; adds `by_strategy` object (additive — old clients unaffected).
- **`POST /backtest`** — `BacktestCreateRequest` keeps `extra="forbid"`: a request carrying any F1/F2/F3 field fails loud (422 "backtest does not yet simulate these features"). No new backtest fields in v1.

## L. UI/UX Requirements

- **Screens:** Manual Scan (`ScannerPage`), Scheduled Scan (`ScheduledScansPage`) — both mount `AutoTradeSection`; Account-detail (per-strategy PnL tab, cohort editor); a Fleet roster (bulk cohort assignment).
- **Components:** new `RegimeFilterFields`, `MeanReversionFields`, `CohortField` sub-components; shared `<StrategyChip>`; reuse `ToggleRow`, `Notice`, segmented controls, neumorphism tokens.
- **States:** loading skeletons while configs hydrate; regime-unknown state in scan results ("Regime: unknown — filter skipped (fail-open)" vs "MR skipped: regime data unavailable"); empty/disabled states; "blocks nothing" warning when F1 on but no hours/vol configured; "blocks all 24h" warning.
- **F1 picker:** 24-cell UTC hour grid with local-time hover, presets ("Recommended chop hours", session presets), live "blocks UTC X (≈Y%/day)" preview.
- **F2-long:** persistent danger Notice (icon + text, not color-only) citing negative expectancy; acknowledgement checkbox gating the server ack.
- **Validation messages:** inline min/max clamps; mutual-exclusion (blocklist vs allowlist); cohort-vs-strategy mismatch warning with "Sync" fix.
- **A11y:** hour grid cells focusable with `aria-pressed`; cohort selector `role="radiogroup"`; danger conveyed by icon+text; live-region for previews/warnings.
- **Responsive:** hour grid reflows; fleet roster + PnL tables scoped for small screens; touch targets ≥44px. Dark/light via design tokens.

## M. Backend Requirements

- **New modules:** `market_data.py` (BTC regime/vol per param-tuple + per-symbol EMA mean; fetch failure → `unavailable` sentinel), `strategy_router.py` (`route_strategy`, `resolve_final_side`, gate predicate fns, `GateChain` — all pure), `scan_context.py` (frozen `ScanContext` dataclass).
- **`scanner_service.start_scan`:** add precompute block (gated by any-consumer-enabled) building `ScanContext` + kill-switch read; global try/except + bounded budget → degrade; inject scan-context to the executor (NOT per-config for scan-global data).
- **`auto_trade_service`:** `_try_trade` extracted into named gate predicates (under golden-snapshot guard) calling `route_strategy` first; F2 placement path (margin-% TP conversion, `strategy_kind`, pending-intent write, MR counter); AI-enable skip for MR; session gate reads placement-time UTC each phase.
- **`close_rule_evaluator`:** MR per-position time-stop/tight-SL sourced from the per-trade persisted record; recheck preserves them.
- **`position_reconciler`:** strategy-aware orphan adoption via `pending_trade_intents`; quarantine fallback.
- **`trade_repository`:** `strategy_kind`/`strategy_cohort`/`f1_active` into both INSERT paths (child inherits parent); add to `UPDATABLE_COLUMNS` audit.
- **`ai_account_manager_service`:** filter `strategy_kind='mean_reversion'`.
- **`schemas/__init__.py`:** ~23 new `AutoTradeConfig` fields + validators (mutual-exclusion, min<max, ≥1 direction when MR enabled); per-feature validator helpers.
- **Existing patterns:** follow `_compute_adaptive_blacklist` injection, `_emit_decision` tracing, `place_trade` contract, `bybit_rate_gate`.

## N. Database/Data Requirements

- **Migration 43:** `trading_accounts.strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK (strategy_cohort IN ('trend','mean_reversion'))`.
- **Migration 44 (one multi-clause statement):** `trades` ADD `strategy_kind VARCHAR(15) NOT NULL DEFAULT 'trend' CHECK (strategy_kind IN ('trend','mean_reversion'))`, `strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK (... IN ('trend','mean_reversion'))`, `f1_active BOOLEAN NOT NULL DEFAULT false`.
- **Migration 45 (out-of-band/background):** `CREATE INDEX [CONCURRENTLY] IF NOT EXISTS idx_trades_account_strategy_kind ON trades(account_id, strategy_kind, status)` — built post-deploy, NOT on boot; startup healthcheck warns if absent/INVALID.
- **Migration 46:** `f2_long_ack (account_id TEXT PK, acked_at TIMESTAMPTZ NOT NULL, acked_leverage INT NOT NULL, acked_capital_pct REAL NOT NULL, acked_max_trades INT NOT NULL)`.
- **Migration 47:** `pending_trade_intents (order_link_id UUID PK, account_id TEXT NOT NULL, strategy_kind VARCHAR(15) NOT NULL, created_at TIMESTAMPTZ NOT NULL)`.
- **Migration 48:** `feature_kill_switches (feature_name TEXT PK, enabled BOOLEAN NOT NULL DEFAULT true, updated_by TEXT, updated_at TIMESTAMPTZ)`.
- **Parity:** all 6 mirrored byte-identically into sync `persistence.py`; CI asserts version-list + DDL-byte parity. Single shared advisory-lock key for the index across runners.
- **Backfill:** existing rows → `'trend'` / `f1_active=false` (semantically correct — only trend existed before). Constant-default single-statement (catalog-only on PG11+, no rewrite).
- **Config fields:** ride `auto_trade_configs` JSONB (no migration). `regime_snapshots` (existing) holds scan-global BTC regime/vol (one row/scan).
- **Rollback:** forward-only; runbook per NFR-012.

## O. Integration Requirements

- **Bybit klines:** BTC + per-symbol klines via `KlineCacheService` + `bybit_rate_gate` (cache-first, rate-limited, subordinate to orders). Fail-open(F1)/fail-closed(F2) at the boundary; single-flight dedup; rejected future → per-consumer policy.
- **Bybit orders:** `place_trade` unchanged except server-derived `strategy_kind` + pre-submit intent write; `order_link_id` stays a 36-char UUID (no strategy encoding).
- **Idempotency:** pending-intent keyed by UUID; precompute deterministic for a scan/cache state.

## P. Security Requirements

- Server re-validates all config; risk fields server-authoritative; `strategy_kind` never read from a request payload.
- F2-long ack: `f2_long_ack` table is the sole gate; `mr_long_ack_requested` (config) ignored; staleness on exposure escalation.
- Authz: ownership assertion on ack/cohort/kill-switch endpoints (cross-account → 403); kill-switch admin-only, audit-logged; confirm the concrete identity model against the codebase during planning (if single-operator, document + drop role language).
- Input validation: every new numeric field Pydantic-bounded; enum reason codes prevent log injection; JSONB key whitelist.
- Kill-switch store not client-influenceable; read-fail → fail-closed.

## Q. Performance Requirements

- Hot path network-free (F1/F3); ≤ +30s cold / +2s warm budget (perf regression test threshold).
- Memoization + single-flight per NFR-002/003; MR mean scoped to qualifying symbols ∩ MR-enabled accounts.
- Trace volume capped/sampled (NFR-010); cohort gate O(1) in-memory (no per-symbol DB lookup).
- Scales to 50 accounts (NFR-013).

## R. Logging, Monitoring, and Observability

- Log every regime decision, skip (with structured detail: regime, vol value vs threshold), MR entry, ack, fail-open/closed, kill-switch flip to `debug_trace`.
- Metrics: per-gate fire counts; F1 suppression rate; per-strategy PnL/win-rate; fetch counts.
- Alerts: F1 suppression_rate > 95% over N scans; F2-long rolling drawdown → auto-disable to kill switch.
- Scan summary persisted into the run/config snapshot for replay; `f1_active` on trades for before/after analysis.

## S. Edge Cases

- EC-01 Session hour exactly HH:00:00.000 / HH:59:59.999; midnight-crossing windows wrap; DST-invariant (UTC continuous); naive-local-time leak is a defect (test guards).
- EC-02 BTC vol exactly at threshold (define `<`/`≤`); empty scan_results (no div-by-zero); malformed/duplicate/out-of-range hours rejected; blocking all 24h warns.
- EC-03 BTC fetch returns NaN/Inf/negative/zero/stale → treated as unavailable per fail policy (never compared as a valid number).
- EC-04 Regime flips ranging→trending between scan-time compute and placement → decision pinned to scan-time snapshot; stale beyond TTL → F2 skips.
- EC-05 Regime ∈ {volatile, compression, unknown} → MR not eligible (`mr_regime_excluded`); trend-cohort still runs trend.
- EC-06 MR TP computes to wrong side of entry → `mr_degenerate_target`; tight-SL wider than TP → skip/clamp; distance < edge → `mr_no_edge`.
- EC-07 Long enabled but ack absent/stale → `mr_long_unacknowledged` (not an error, no fallthrough to short, no long placed).
- EC-08 `mr_time_stop_minutes` = 5 → 0.083h must NOT truncate to 0 ("disabled"); float duration; per-trade captured.
- EC-09 Partial-close child created after account re-cohorted → inherits parent's strategy_kind + strategy_cohort (not current account value).
- EC-10 Single-flight fetch fails → all awaiters see an `unavailable` sentinel; EACH applies its own policy (F1 fail-OPEN/proceed, F2 fail-CLOSED/skip) — never a blanket fail-closed. Fresh attempt next phase (no negative caching across phases).
- EC-11 Order fills but `create_trade` write fails → reconciler recovers strategy_kind from pending-intent; else quarantine (never silent trend).
- EC-12 Old DB JSONB / old localStorage config lacking new keys → loads default-off, no error; re-save doesn't corrupt unrelated fields.
- EC-13 Account in multiple configs with differing cohorts → first-config-wins (documented).
- EC-14 New zero-history account with F2 enabled → no false circuit-breaker, no misleading win-rate (min-sample guard).
- EC-15 `relaxed`/fill-to-max mode → F1 suppression + all F2 safety guards + cohort_mismatch still fire.
- EC-16 Rollback past v42 → boot-guard avoided via schema_version downgrade BEFORE code rollback; old code tolerates additive columns (lenient re-validation).

## T. Testing Requirements

- T-01 Golden snapshot: all-3-off → byte-identical `_try_trade` decisions vs current main (FR-001).
- T-02 Per-feature ENABLED characterization snapshots (each produces EXPECTED decisions, not just "different from off").
- T-03 E2E: one full scan all-3-on → asserted manifest of placed trades (correct `strategy_kind`) + skips (correct reason codes).
- T-04 Fixture corpus: BTC kline fixtures, per-symbol kline fixtures, scan_results with overbought AND oversold extremes, fixed injectable clock — shared by unit/E2E/snapshot.
- T-05 Direction coverage: BOTH short-fade (overbought) AND long-fade (oversold, ack'd) with direction-specific geometry assertions.
- T-06 TP-conversion oracle: hand-computed exchange-correct TP% for known (entry, leverage, distance) + clamp on extreme inputs.
- T-07 Ack negative paths: reject when absent, reject when stale, re-ack required on leverage/capital/max_trades escalation.
- T-08 `resolve_final_side` exhaustive truth table (incl. reverse ∧ fade ⇒ identity).
- T-09 Migration: sync/async DDL-byte parity; CHECK == Literal (CI); migration-45 lock window vs production-sized snapshot; behavioral round-trip through both persistence paths.
- T-10 Perf: fetch-count bounds (BTC ≤ tuples, mean once/symbol) + all-on latency within budget.
- T-11 Timezone: placement-time UTC governs; DST-invariant; naive-local-time leak fails a test.
- T-12 Reconciler: orphan with failed create_trade → recovered from pending-intent; unrecoverable → quarantine not trend.
- T-13 Frontend: each toggle renders+persists+round-trips on each surface; F2-long acknowledgement gates server write.
- T-14 90%+ line/branch coverage on `market_data.py`, `strategy_router.py`, gate predicates, `resolve_final_side`, `route_strategy`.

## U. Acceptance Criteria

- AC-001: Given all features off, when a scan runs, then placed trades/skips are byte-identical to current main (T-01).
- AC-002: Given F1 enabled with default blocked hours, when a trade would open at UTC 09:00, then it is suppressed with `session_filter` and counted in the scan summary (FR-010/016).
- AC-003: Given F1 enabled and BTC klines unavailable, when the scan runs, then trend entries proceed (fail-open) and the summary shows regime unknown (FR-014).
- AC-004: Given a mean_reversion-cohort account in ranging regime, when a strong overbought signal arrives, then a SHORT-to-mean trade is placed with tagged `strategy_kind='mean_reversion'`, a tight SL, and a time-stop (FR-020/022/023/050).
- AC-005: Given the same account in trending regime, when any signal arrives, then no MR trade is placed (`mr_regime_excluded`) and no trend trade is placed (cohort) (FR-026/041).
- AC-006: Given `mr_long_enabled` true but no fresh ack, when an oversold signal arrives, then the long fade is rejected with `mr_long_unacknowledged` (FR-027).
- AC-007: Given a valid ack at leverage 5, when leverage is raised to 10, then subsequent long fades are rejected until re-acknowledged (FR-027, T-07).
- AC-008: Given an MR order that fills but whose trade-row write fails, when reconciliation runs, then the position is tagged mean_reversion from the pending-intent (or quarantined) — never silently 'trend' (FR-051, T-12).
- AC-009: Given a trade placed under F1-active in a blocked hour's neighbor, when queried, then `f1_active` + session-hour are recorded for before/after analysis (FR-015).
- AC-010: Given the kill switch row `feature_name='mean_reversion', enabled=false`, when the next scan runs, then no MR entries are placed (FR-007).
- AC-011: Given an old saved config without the new fields, when loaded, then all features are off and behavior is unchanged (EC-12).
- AC-012: Given each feature toggle, when set→saved→reloaded on the manual scan, scheduled scan, and per-account surfaces, then the value round-trips (FR-060, T-13).

## V. Risks

- RV-01 | F2-long negative expectancy | High severity / High likelihood | the user opted into live longs; data shows −$0.57/trade. Mitigation: default-off, opt-in, server ack, regime-gated, per-direction PnL visibility, auto-disable to kill-switch, persistent UI warning. (Standing flag RF1.)
- RV-02 | Unvalidated strategy live (backtest deferred) | High / Medium | F2 ships live without backtest validation. Mitigation: conservative defaults, default-off, kill-switch, per-strategy PnL, fail-closed.
- RV-03 | Migration-45 index lock at deploy | Medium / Medium | out-of-band/background build + prod-snapshot test + startup warn.
- RV-04 | Rollback boot-guard crash | Medium / Low | runbook sequences schema_version downgrade before code rollback; pre-merge v42 lenient-config check.
- RV-05 | price_drift gate inverted for MR | Medium / Medium (latent) | gate classified strategy-agnostic vs trend-only; router skips trend-only gates for MR; explicit fade test.
- RV-06 | Reconciler mislabels orphan MR as trend | High / Low | pending-intent join + quarantine fallback; never silent trend.
- RV-07 | Precompute failure regresses trend trading | High / Low | global try/except + degrade; scan never aborts.
- RV-08 | Trace buffer saturation | Low / Medium | debug-level per-decision + sampling + per-scan cap.
- RV-09 | Auto-merge gap (column added to read but not write path) | Medium / Medium | write-site checklist binds each column → {migration×2, both INSERTs, UPDATABLE_COLUMNS, serializer, Pydantic, TS}.

## W. Assumptions

- A-001 | The codebase has an identity/auth layer to enforce account-owner/admin on the new endpoints | Risk: Medium | Reason: existing account endpoints imply it | Impact if wrong: authz must be added or features documented single-operator (AD9, planning verifies).
- A-002 | `KlineCacheService`/equivalent exposes BTC + per-symbol klines via `bybit_rate_gate` | Risk: Low | Reason: discovery found kline caching on the trade path | Impact if wrong: a thin fetch helper is added in `market_data.py`.
- A-003 | Deployed v42 `AutoTradeConfig` load path tolerates extra JSONB keys (or can be made to before merge) | Risk: Medium | Reason: needed for safe rollback | Impact if wrong: rollback needs a config-key-strip step (AD20).
- A-004 | `regime_snapshots` table exists and can hold scan-global BTC regime/vol | Risk: Low | Reason: referenced in research schema | Impact if wrong: a small table is added.
- A-005 | The PG server is ≥11 (catalog-only ADD COLUMN with constant default) | Risk: Low | Reason: standard | Impact if wrong: migration strategy revisited.

## X. Open Questions

- Q-001 | Exact identity/ownership mechanism for authz | Why: secures the ack/cohort/kill-switch endpoints | Recommended default: reuse the existing account-access check; if none, document single-operator and drop role language | Impact if unanswered: planning must inspect auth before implementing endpoints (non-blocking for design).
- Q-002 | Migration-45 build path (CONCURRENTLY background vs bounded-lock) | Why: deploy safety | Recommended default: deferred background migration with startup warn | Impact: plan picks based on prod `trades` size (pre-constrained safe either way).
- Q-003 | Final migration numbers (43–48 may shift vs the in-flight backtesting feature) | Why: collision avoidance | Recommended default: reserve a contiguous block at merge; last-to-land renumbers | Impact: mechanical renumber + CI parity check.

## Y. Traceability Matrix

| Requirement | Spec § | Component / File | Test | AC |
|-------------|--------|------------------|------|-----|
| FR-001 default-off | F/H | golden snapshot | T-01 | AC-001 |
| FR-003 scan-context precompute | F/M | `scan_context.py`, `scanner_service` | T-03,T-10 | AC-002 |
| FR-004 route_strategy | F/M | `strategy_router.py` | T-02,T-03 | AC-004,005 |
| FR-005 resolve_final_side | F/M | `strategy_router.py` | T-08 | AC-004 |
| FR-007 kill-switch | H/N | `feature_kill_switches`, scanner | T-03 | AC-010 |
| FR-010..016 F1 | F1 H | `strategy_router` gates, `market_data` | T-02,T-11 | AC-002,003,009 |
| FR-020..030 F2 | F2 H | `strategy_router`, `market_data`, executor, close_rule_evaluator | T-04,05,06 | AC-004,005,006 |
| FR-027 F2-long ack | F2 H | `f2_long_ack`, ack endpoint | T-07 | AC-006,007 |
| FR-040..043 F3 | F3 H | `strategy_cohort` col+config, `route_strategy` | T-02 | AC-005 |
| FR-050..053 tagging/reconciler/AI | H | `trade_repository`, `position_reconciler`, `ai_account_manager` | T-12 | AC-008 |
| FR-060..065 frontend/ops | H/L | `AutoTradeSection` + sub-components | T-13 | AC-012 |
| NFR-001..003 perf | I/Q | precompute, cache | T-10 | AC-002 |
| NFR-009 migrations | I/N | `async_persistence`+`persistence` | T-09 | AC-011 |
| EC-12 backward compat | S | config load | T-13 | AC-011 |
| FR-066 session override | AA/AB | manual scan path | T-23 | AC-017 |
| FR-067 concentration warn | AA/AB | fleet view | T-16-adj | AC-014 |
| FR-052 AI-mgr MR exclusion | H | `ai_account_manager` | T-15 | AC-015 |
| FR-029 one-symbol-one-strategy | H | executor state | T-16 | AC-004 |
| FR-025 fee/liquidation guards | H | F2 placement | T-17 | AC-004 |
| FR-065 auto-disable + alert | H | kill-switch, metrics | T-18 | (ops) |
| FR-028 MR counter cross-phase | H | `_AccountState` | T-19 | AC-004 |
| FR-053 recheck preserves MR | H | `close_rule_evaluator` | T-20 | AC-004 |
| FR-007 kill-switch master/fail | H/N | `feature_kill_switches` | T-21 | AC-010 |
| SD1 BTC classifier | AA | `market_data` | T-22 | AC-002,013 |
| FR-062 per-strategy PnL | H/L | account-detail tab | T-13 | AC-016 |
| RV-10 F1 entry-only caveat | AA | (measurement) | — | (A-006) |

> Note: canonical §H/§T/§U/§V lists run through their last numbered item (FR-067, T-24, AC-017, RV-10); items added during spec review live in §AA (SD1–SD18) and §AB (SD19–SD27), folded into this matrix above.

(Full requirement→task mapping completed in the implementation plan, Step 6.)

## Z. Definition of Ready

- [x] Scope clear (v1 vs v2 boundary explicit)
- [x] Requirements testable (FR/NFR with IDs)
- [x] Edge cases documented (EC-01..16)
- [x] Codebase impact understood (discovery + architecture)
- [x] Dependencies identified (kline cache, auth, regime_snapshots)
- [x] Risks documented (RV-01..09 with mitigations)
- [x] Acceptance criteria measurable (AC-001..012)
- [x] No unresolved Critical/High findings (10 req rounds + 5 arch rounds converged; open questions are non-blocking, planning-phase)

**Status: Draft → ready for Step 5 spec review.**

---

## AA. Spec Review R1 Resolutions (SD1–SD18)

### SD1 — BTC regime classifier (was High; `market_data.classify_regime`)
Inputs from BTC klines at `btc_vol_interval`/`btc_vol_lookback_candles`: `atr_ratio = ATR(n)/SMA(ATR,n)`, `ema_distance_pct = (close − EMA(n))/EMA(n) × 100`. Rules (first match):
- `volatile` if `atr_ratio ≥ regime_volatile_atr` (default 2.0)
- `trending` if `|ema_distance_pct| ≥ regime_trend_ema_dist_pct` (default 1.0)
- `ranging` otherwise
- `unknown` if available candles < required depth (→ F1 fail-open, F2 fail-closed)
Thresholds are bounded config fields. Market-scoped (BTC only, no MTF) — deliberately simpler than `ai_manager_regime`. Truth-table test (T-22).

**SD1a [R2-F1 — fetch depth, money-path]:** `atr_ratio = ATR(n)/SMA(ATR(n) over n)` requires ~`2×n` candles (an n-wide SMA over the ATR series). BTC fetch depth MUST be `≥ btc_vol_lookback_candles × 2 + 1`; `unknown` is returned when available candles < that required depth (NOT merely < lookback) — otherwise `atr_ratio` degenerates to 1.0 and `volatile` never fires while failing OPEN with wrong data. The denominator is the SMA over `n` consecutive ATR(n) values; ATR uses Wilder's true-range. Pinned, not left implicit.
**Unit note:** `btc_vol_min_threshold`/`btc_vol_max_threshold` and `regime_volatile_atr` are in **atr_ratio units** (~0.5–2.0), NOT percent.

### SD2 — MR per-position exit persistence (was High)
MR tight-SL + time-stop are written on the per-position `close_rules` row at registration (existing per-position columns), not read from account config at eval. `post_scan_recheck` recreate sources from that row, or excludes open MR positions. The MAX_DURATION value must hold minute-precision float hours — if the existing column is INT-hours, add a per-rule minutes field (contingency migration 49, confirmed in planning). EC-08 asserts no truncation-to-0.

### SD3/SD4/SD5 — applied inline (EC-10 reworded; FR-009 F1 umbrella; f1_active session-hour derived from `created_at` UTC, no column).

### SD6 — regime_snapshots vs run-snapshot
Scan-global BTC regime → `regime_snapshots` (cols: scan_id, ts, btc_regime, atr_ratio, ema_distance_pct, computed_at; confirm existing table in planning, else contingency migration). Per-scan suppressed/allowed COUNTS → run/config snapshot JSONB. Two distinct sinks.

### SD7 — pending_trade_intents lifecycle
Delete after successful `create_trade`; a background GC sweep removes unadopted intents (rejected/never-filled) older than a TTL (mirrors debug_trace retention). Reconciler obtains `order_link_id` via the existing position→order-history path (confirm in planning).

### SD8 — staleness TTL
`regime_staleness_minutes` bounded config (default 30). F2 skips if `now − ScanContext.computed_at > TTL`. EC-04 boundary test.

### SD10 — Canonical config-field table (26 fields incl. 2 classifier-tuning; all optional, default-off)

| Field | Type | Default | Bounds | Feature |
|-------|------|---------|--------|---------|
| regime_filter_enabled | bool | false | — | F1 |
| session_filter_enabled | bool | false | — | F1 |
| session_blocked_hours_utc | list[int]\|null | null | each 0–23 | F1 |
| session_allowed_hours_utc | list[int]\|null | null | each 0–23, excl. w/ blocked | F1 |
| btc_vol_filter_enabled | bool | false | — | F1 |
| btc_vol_min_threshold | float\|null | null | ≥0, < max | F1 |
| btc_vol_max_threshold | float\|null | null | ≥0, > min | F1 |
| btc_vol_interval | Literal | "1h" | {15m,1h,4h} | F1 |
| btc_vol_lookback_candles | int | 14 | 2–200 | F1 |
| mean_reversion_enabled | bool | false | — | F2 |
| mr_short_enabled | bool | true | — | F2 |
| mr_long_enabled | bool | false | — | F2 |
| mr_long_ack_requested | bool | false | UI-intent only (ignored server-side) | F2 |
| mr_regime | Literal | "ranging" | {ranging} v1 | F2 |
| mr_mean_period | int | 20 | 2–200 (bucketed) | F2 |
| mr_mean_interval | Literal | "1h" | {15m,1h,4h} | F2 |
| mr_target_capture_pct | float | 60 | >0–100 | F2 |
| mr_tight_stop_pct | float\|null | null | >0–1000 | F2 |
| mr_time_stop_minutes | int | 120 | 5–1440 | F2 |
| mr_min_edge_pct | float | 1.0 | 0–100 | F2 |
| mr_extreme_min_abs_score | float | 5.0 | 0–10 | F2 |
| mr_capital_pct | float | (conservative) | >0–100 | F2 |
| mr_leverage | int | (conservative) | 1–125 | F2 |
| mr_max_trades | int | (conservative) | 1–999 | F2 |
| strategy_cohort | Literal | "trend" | {trend,mean_reversion} | F3 |
| regime_staleness_minutes | int | 30 | 5–240 | common |

(F1=9, F2=15, F3=1, common=1; the few "sub-fields" the architecture enumerated separately are folded here. `regime_volatile_atr`, `regime_trend_ema_dist_pct` are classifier-tuning fields with defaults 2.0/1.0.)

### SD11 — `strategy_kind` and `strategy_cohort` both `TEXT` with CHECK (drop VARCHAR(15)).

### SD12 — Gate taxonomy (the 13 existing `_try_trade` gates)
| Gate | Class | Applies to MR? |
|------|-------|----------------|
| blacklist, whitelist, already_held | agnostic | yes |
| max_signal_age | agnostic | yes |
| max_same_direction, max_same_sector | agnostic | yes (combined book) |
| adaptive_blacklist | strategy-scoped | yes (MR-scoped variant) |
| signal_sides | agnostic (post-fade side) | yes |
| min_score, confidence_filter | trend-only | NO (MR uses `mr_extreme_min_abs_score`) |
| price_drift | trend-only — SKIPPED for MR | NO (skipped for MR) |
| max_trades / target_goal | agnostic (MR uses `mr_max_trades`) | yes |
Resolves RV-05: `route_strategy` output drives the pipeline to skip trend-only gates for MR.

### SD13 — New acceptance criteria
- AC-013: Given F1 vol-gate on and BTC atr_ratio outside the band, when a signal arrives, then the entry is suppressed with `btc_vol_filter` (FR-012).
- AC-014: Given a cohort assignment that places > threshold of accounts in one cohort, when applied on the fleet view, then a concentration warning fires; assignments persist (FR-067, F3 decorrelation).
- AC-015: Given an MR position, when the AI manager evaluates, then it excludes `strategy_kind='mean_reversion'` and MR success did not auto-enable AI (FR-052).
- AC-016: Given trades of both strategies/directions, when the per-strategy PnL view renders, then it shows strategy × direction × {PnL, win-rate, count, avg-hold} (FR-062).

### SD14 — New tests: T-15 AI-mgr MR exclusion; T-16 one-symbol-one-strategy (FR-029); T-17 fee-floor + liquidation-distance guards (FR-025); T-18 auto-disable + suppression alert (FR-065); T-19 MR counter cross-phase + resume (FR-028); T-20 recheck preserves MR params (FR-053); T-21 kill-switch master-key + read-fail-closed (FR-007); T-22 regime-classifier truth table (SD1).

### SD16 — New FRs
- FR-066: Manual scan offers a one-time "run anyway — ignore session filter this scan" override behind a confirmation (F1 escape hatch).
- FR-067: The fleet view surfaces a concentration warning when too many accounts land in one cohort (reintroduces correlated drawdown risk).

### SD15 — New risk/assumption
- RV-10 | F1 entry-only may underdeliver | Medium / Medium | if the Asian-session bleed is dominated by positions HELD-THROUGH the session (not entered during it), F1 (entry-only) reduces but doesn't fix it. Mitigation: measure via `f1_active` before/after; a session-aware EXIT rule is the v2 remedy (noted in §G).
- A-006 | The historical bleed is materially driven by entries made DURING the bad session (not only hold-through) | Risk: Medium | Reason: F1's value rests on it | Impact: if wrong, prioritize the v2 session-exit rule.

### SD17 — NFR-002 memo bound expressed as "≤ account count" (not literal 21), consistent with the 50-account target (NFR-013).

### SD18 — §J gains a primary "bulk cohort assignment" flow; §W A-001/A-003 inline the AD9 (authz: reuse account-access check or document single-operator) and AD20 (pre-merge verify v42 tolerates extra JSONB keys) one-liners. Field-count counters reconciled to 23 (SD10 table authoritative). Migration set 43–48 (+49 contingency) is authoritative; requirements-doc "43–47" is stale (kill-switch table concretized during architecture).

## Rounds: Spec-R1 done (not clean) → SD1-SD18 applied. Next: Spec-R2.

---

## AB. Spec Review R2 Resolutions (SD19–SD27)

- **SD19 [R2-F1 money-path, applied to SD1a]** BTC classifier fetch depth pinned to `≥ 2×lookback+1`; `unknown` triggers on insufficient depth (prevents silent degenerate atr_ratio=1.0). Threshold units = atr_ratio (documented).
- **SD20 [FR-066 override hardening]** The manual session-filter override: confirmation-gated, applies to EXACTLY one scan, does NOT persist (auto-reverts next scan), is audit-logged, and overridden entries are tagged so they are EXCLUDED from `f1_active` before/after efficacy stats (preserves FR-015). It bypasses BOTH F1 sub-modes (session + vol) for that one manual scan. → AC-017, T-23.
- **SD21 [concentration threshold]** FR-067 fires when a single cohort holds `> cohort_concentration_pct` of the fleet (named constant, default 70%) OR all-but-one accounts in one cohort. AC-014 asserts against this value. (Display-only warning; not a hard block.)
- **SD22 [FR-064 invariant + FR-065 thresholds]** FR-064 "new-entries-only" invariant gets T-24 (toggling a feature/cohort does NOT re-manage existing open positions). FR-065 thresholds pinned as named CONSTANTS (not user config, like SD21's `cohort_concentration_pct`): auto-disable F2-long when rolling drawdown over the last `f2_long_breaker_trades` (default 20) trades < `f2_long_breaker_drawdown_pct` (default −15%); F1 suppression alert when suppression_rate > 95% over `f1_alert_scans` (default 8) scans. These four (`cohort_concentration_pct`, `f2_long_breaker_trades`, `f2_long_breaker_drawdown_pct`, `f1_alert_scans`) are server-side constants, NOT part of the 23-field `AutoTradeConfig` table. T-18 asserts exact trip points.
- **SD23 [migration numbering]** Reserve 49 = MR float-minutes contingency (if MAX_DURATION column is INT-hours), 50 = regime_snapshots contingency (if table absent). Both confirmed/dropped in planning.
- **SD24 [gate taxonomy wording]** price_drift row = "trend-only — SKIPPED for MR" (drop the confusing "INVERTED" hint; the decision is skip). `resolve_final_side` runs BEFORE all direction gates (signal_sides AND max_same_direction operate on the post-fade side).
- **SD25 [TP clamp note]** `distance_implied_max` is a redundant-but-harmless upper bound (always ≥ output when capture ≤ 100%); `exchange_max_tp_pct` is the binding clamp. Informational.
- **SD26 [traceability fold-back]** §Y traceability matrix extended with rows for FR-066, FR-067, T-15..T-24, AC-013..AC-017, RV-10. The canonical §H/§T/§U/§V lists are authoritative through their last item; §AA/§AB appendices are the source for items beyond (a "see §AA/§AB" pointer is added at the end of each canonical list during the final spec consolidation before planning).
- **SD27 [new ACs/tests from R2]** AC-017 (one-time override: confirmation-gated, single-scan, non-persistent, audited, excluded from efficacy); T-23 (override auto-reverts next scan); T-24 (feature/cohort toggle is new-entries-only).
- **SD28 [R3 security Low — ack snapshot server-derived]** The `/accounts/{id}/f2-long-ack` endpoint MUST snapshot the CURRENT server-side persisted config exposure (mr_leverage/mr_capital_pct/mr_max_trades) at ack time — it must NOT trust client-supplied exposure values in the body (else a client acks once at {125,100,999} and permanently defeats escalation-staleness). Either derive the snapshot server-side or 422 if the body ≠ persisted config. (NFR-005 reinforcement.)
- **SD29 [R3 fold-back, applied]** §AA SD12 price_drift row → "SKIPPED for MR" (applied); §Y matrix extended with FR-066/067, T-15..24, AC-013..017, RV-10 rows + canonical-vs-appendix pointer (applied); SD22 breaker/alert thresholds declared server-side constants, not config (applied).

## Rounds: Spec-R2 done → SD19-SD27 applied. Next: Spec-R3 (verify + security re-run; seek 2 consecutive clean).





