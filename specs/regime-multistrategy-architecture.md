# Architecture: Regime Multi-Strategy (3 Optional Features)

**Source requirements:** `specs/regime-multistrategy-requirements.md` (10 rounds, converged)
**Skill:** `/new-feature` Step 3
**Status:** Draft for review

> Most architectural decisions here were ratified during the 10 requirements rounds (D1–D22, AF1–AF6, ARCH#1–5).
> This document consolidates them into a single coherent architecture and binds every requirement to a component.

---

## 1. Architecture Decision Record (ADR)

### ADR-1: Reuse the `_try_trade` gate-chain pattern; extract gates to a pure-function module
- **Decision:** Add Features 1 & 3 as new gates in the existing `_try_trade` sequence, but FIRST extract the gate chain into module-level pure functions in a new `backend/services/strategy_router.py`. F2 (mean-reversion) is a strategy *branch* selected by a `route_strategy()` function, not a parallel executor.
- **Context:** `_try_trade` (auto_trade_service.py:1001) is already a clean "skip-if-filter-fails" chain emitting decision traces. Inlining 3 more features would create a ~400-line unreviewable method (R2-30).
- **Alternatives rejected:** (a) A parallel MR executor — duplicates state/close-rule/AI-manager wiring. (b) Inline everything — unmaintainable, untestable. (c) Strategy plugin framework — YAGNI for 2 strategies.
- **Consequences:** Gates become independently unit-testable; the executor imports from `strategy_router` (one-way, no cycle); a golden-snapshot guard (X-10) proves the extraction is behavior-preserving.

### ADR-2: Two regime classifiers kept separate by scope
- **Decision:** New `backend/services/market_data.py` (renamed from the originally-proposed `market_regime.py` per AD4) computes a MARKET-scoped regime (BTC realized-vol/ATR, per BTC-param-tuple) and the per-symbol EMA mean. The existing `ai_manager_regime.compute_regime()` (per-symbol) is left untouched.
- **Context:** They operate at incompatible scopes with different inputs (ARCH#1). Forcing reuse would couple unrelated subsystems.
- **Alternatives rejected:** Unify into one classifier — scope mismatch (market vs per-symbol) makes a shared signature leaky.
- **Consequences:** MR eligibility is explicitly a market-PROXY gate (BTC ranging ⇒ MR eligible), documented as such. The two share the *concept* of regime, not the math.

### ADR-3: Scan-time precompute + scan-level context object
- **Decision:** Compute regime/vol once per scan in `start_scan` (like `_compute_adaptive_blacklist`); pass scan-global results via a scan-level context object to the executor. Per-symbol MR means precomputed per distinct (symbol, period, interval). Reserve per-config `_computed_*` injection for genuinely per-config data (adaptive_blacklist).
- **Context:** Hot trade path must stay network-free (X-6); scan-global data injected per-config would duplicate one value 21× and bloat the serialized scans-table config (ARCH#4).
- **Consequences:** Only `get_mark_price` remains a trade-time read. Regime/vol persist to `regime_snapshots` for replay; stripped from config before insert.

### ADR-4: F2 reuses `place_trade`; price-target converted to margin-%
- **Decision:** F2 calls the existing `place_trade()` with a new server-derived `strategy_kind="mean_reversion"` arg, converting its price-distance-to-mean target into percent-of-margin given leverage (with upper clamp + guards). No parallel placement path. Fast exits reuse `MAX_DURATION` (time-stop) + `stop_loss_pct` (tight-SL).
- **Context:** `place_trade` takes percent-of-margin TP/SL; F2 thinks in price distance (AF1, R2-1).
- **Consequences:** One placement path, one close-rule machinery. Range-break exit deferred to v2.

### ADR-5: Default-off, byte-identical preservation
- **Decision:** Every feature defaults off; a golden-snapshot regression proves all-off `_try_trade` decisions are byte-identical to current `main`.
- **Consequences:** Zero behavior change until explicitly opted in; safe to ship live (D21).

### ADR-6: F2-long acknowledgement as a server-authoritative record
- **Decision:** The long-fade safety gate is anchored by a separate server-side table `f2_long_ack` (not config JSONB). Long-fade entries are rejected unless a fresh ack exists; ack goes stale when `mr_leverage`/`mr_capital_pct`/`mr_max_trades` escalate.
- **Context:** Config is client-round-tripped/untrusted (X-20); a JSONB ack could be forged. Longs have negative expectancy (the user opted in deliberately — D6/D21b).
- **Consequences:** A crafted request cannot unlock long trading; the ack is auditable; re-ack required on exposure escalation.

### ADR-7: Reconciler pending-intent record (not orderLinkId encoding)
- **Decision:** Before submitting an MR order, write a `pending_trade_intents` row keyed by the same `order_link_id` UUID carrying `strategy_kind`. The reconciler joins orphaned exchange positions to this row to recover the strategy tag; quarantine/flag is the terminal fallback.
- **Context:** Encoding strategy in `orderLinkId` overflows Bybit's 36-char limit and breaks the UUID idempotency contract (R6-1). A position whose `create_trade` write failed has no other strategy source.
- **Consequences:** MR positions are never silently mislabeled `trend` (which would skip MR exits, break AI-manager exclusion, poison the trend blacklist).

---

## 2. System Context

```
                    ┌─────────────────────────────────────────────┐
   Operator ──────► │  Frontend (React/TS)                        │
   (scan forms)     │  AutoTradeSection → RegimeFilterFields /     │
                    │  MeanReversionFields / CohortField          │
                    └───────────────┬─────────────────────────────┘
                                    │ auto_trade_configs (JSON)
                                    ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  Backend (FastAPI)                                              │
   │                                                                │
   │  scanner_service.start_scan ──┐                                │
   │    (scan-time precompute)     │ builds ScanContext             │
   │       │                       ▼                                │
   │       │   market_data.py ◄──── KlineCacheService ◄── Bybit   │
   │       │   (BTC vol/regime +      (BTC + per-symbol klines;    │
   │       │    per-symbol EMA mean)   mean computed AFTER          │
   │       │                          extreme-score signal filter) │
   │       │                                                        │
   │       ▼                                                        │
   │  AutoTradeExecutor._try_trade                                  │
   │       │  imports                                               │
   │       ▼                                                        │
   │  strategy_router.py: route_strategy() → GateChain →            │
   │       resolve_final_side()                                     │
   │       │                                                        │
   │       ▼                                                        │
   │  place_trade(strategy_kind=…) ──► Bybit (live order)           │
   │       │                                                        │
   │       ├─► pending_trade_intents (pre-submit)                   │
   │       ├─► trades (strategy_kind, strategy_cohort, f1_active)   │
   │       ├─► close_rule_evaluator (time-stop / tight-SL)          │
   │       └─► debug_trace (decision reasons)                       │
   │                                                                │
   │  position_reconciler ◄── joins orphans via pending_trade_intents│
   │  ai_account_manager ◄── excludes strategy_kind='mean_reversion'│
   └────────────────────────────────────────────────────────────────┘
```

- **External systems:** Bybit (klines for regime/mean + live order placement) — all via existing `accounts_service` + `bybit_rate_gate`.
- **Access pattern:** operator configures per-account via two scan forms (shared component); scheduled scans run unattended every 3h.

---

## 3. Component Architecture

### New components

| Component | File | Responsibility | Inputs | Outputs | Errors |
|-----------|------|----------------|--------|---------|--------|
| Market data | `backend/services/market_data.py` | Compute BTC market-scoped regime + realized-vol/ATR AND per-symbol EMA mean from klines (AD4) | BTC klines + per-symbol klines, config (metric/interval/lookback/period) | `BtcRegime` per param-tuple + `means` map | fetch failure → `unavailable` sentinel, caller fail-policy |
| Strategy router | `backend/services/strategy_router.py` | `route_strategy(cohort, regime)`, `resolve_final_side()`, gate predicate fns, `GateChain` | config, scan-context, signal, clock | strategy kind, final side, skip-decision | pure fns; no I/O |
| Scan context | `backend/services/scan_context.py` (AD5/AD15) | Frozen dataclass carrying scan-global computed data (BTC regime/vol by param-tuple, per-symbol means, computed_at, degraded) | built in `start_scan` | typed read-only payload | — |

### Modified components

| Component | File | Change |
|-----------|------|--------|
| Scanner service | `scanner_service.py` | `start_scan` precompute block (regime/vol/means) + build ScanContext + global try/except degrade + bounded budget |
| Auto-trade executor | `auto_trade_service.py` | `_try_trade` calls `route_strategy` + GateChain; F2 placement w/ `strategy_kind`; MR counter in `_AccountState`; pending-intent write; AI-enable skip for MR |
| Close-rule evaluator | `close_rule_evaluator.py` | MR per-position time-stop/tight-SL sourced from per-trade persisted params; recheck preserves them |
| Position reconciler | `position_reconciler.py` | Strategy-aware orphan adoption via `pending_trade_intents`; quarantine fallback |
| Trade repository | `trade_repository.py` | `strategy_kind`/`strategy_cohort`/`f1_active` in both INSERT paths; child inherits parent; UPDATABLE_COLUMNS |
| Schemas | `schemas/__init__.py` | ~22 new `AutoTradeConfig` fields + validators |
| Persistence (×2) | `async_persistence.py` + `persistence.py` | Migrations 43–48 (mirrored, DDL-byte parity test) |
| Frontend | `AutoTradeSection.tsx` + new sub-components | RegimeFilterFields, MeanReversionFields, CohortField; StrategyChip; per-strategy PnL view |

### Dependency direction (acyclic)
```
market_data.py    ─┐
                   ├─► scanner_service ─► auto_trade_service ─► strategy_router
strategy_router ◄──┘         (start_scan)      (_try_trade imports router)
                          (builds ScanContext from scan_context.py — a leaf dataclass)
```
`auto_trade_service` imports FROM `strategy_router` (one-way). `market_data` and `scan_context` are leaves. No cycles (ratified R5/R7/Arch-R2).

---

## 4. Data Architecture

### Migrations (final set: 43–48; numbers finalized at merge per R2-17)

| # | DDL | Lock profile |
|---|-----|--------------|
| 43 | `ALTER TABLE trading_accounts ADD COLUMN IF NOT EXISTS strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK (strategy_cohort IN ('trend','mean_reversion'))` | catalog-only (PG11+) |
| 44 | `ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_kind VARCHAR(15) NOT NULL DEFAULT 'trend' CHECK (strategy_kind IN ('trend','mean_reversion')), ADD COLUMN IF NOT EXISTS strategy_cohort TEXT NOT NULL DEFAULT 'trend' CHECK (strategy_cohort IN ('trend','mean_reversion')), ADD COLUMN IF NOT EXISTS f1_active BOOLEAN NOT NULL DEFAULT false` (ONE multi-clause statement) | catalog-only |
| 45 | `CREATE INDEX [CONCURRENTLY?] IF NOT EXISTS idx_trades_account_strategy_kind ON trades(account_id, strategy_kind, status)` | ⚠ see §10 — non-txn path OR bounded lock |
| 46 | `CREATE TABLE IF NOT EXISTS f2_long_ack (account_id TEXT PRIMARY KEY, acked_at TIMESTAMPTZ NOT NULL, acked_leverage INT NOT NULL, acked_capital_pct REAL NOT NULL, acked_max_trades INT NOT NULL)` | empty table |
| 47 | `CREATE TABLE IF NOT EXISTS pending_trade_intents (order_link_id UUID PRIMARY KEY, account_id TEXT NOT NULL, strategy_kind VARCHAR(15) NOT NULL, created_at TIMESTAMPTZ NOT NULL)` | empty table |
| 48 | `CREATE TABLE IF NOT EXISTS feature_kill_switches (feature_name TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT true, updated_by TEXT, updated_at TIMESTAMPTZ)` | empty table |

- **Parity:** all 6 mirrored byte-identically into sync `persistence.py`; regression test asserts the two `_MIGRATIONS` version lists match (R2-18) and DDL-byte parity (AD14).
- **CHECK == Literal:** CI test asserts each DB CHECK enum equals its Pydantic `Literal` (R5-G6). `f1_active` carries the session-context flag for F1 efficacy measurement (R5-G3).
- **Config fields (no migration — ride `auto_trade_configs` JSONB):** ~22 new `AutoTradeConfig` fields (F1: `regime_filter_enabled`, `session_filter_enabled`, `session_blocked_hours_utc`, `session_allowed_hours_utc`, `btc_vol_filter_enabled`, `btc_vol_min_threshold`, `btc_vol_max_threshold`, `btc_vol_interval`, `btc_vol_lookback_candles`, `regime_filter_fail_open`; F2: `mean_reversion_enabled`, `mr_short_enabled`, `mr_long_enabled`, `mr_long_ack_requested`, `mr_regime`, `mr_mean_period`, `mr_mean_interval`, `mr_target_capture_pct`, `mr_tight_stop_pct`, `mr_time_stop_minutes`, `mr_min_edge_pct`, `mr_extreme_min_abs_score`, `mr_capital_pct`, `mr_leverage`, `mr_max_trades`; F3: `strategy_cohort`). All optional/defaulted (default-off).

### Entity relationships
- `trading_accounts (1) ── (N) trades` — trade carries denormalized point-in-time `strategy_cohort` (immutable history, survives account re-cohorting).
- `trading_accounts (1) ── (0..1) f2_long_ack` — one ack per account.
- `pending_trade_intents (1) ── (0..1) trades` — joined by `order_link_id`; intent is transient (reconciled/cleaned).
- `regime_snapshots` — scan-global BTC regime/vol, one row per scan (existing table; reused).

### Data lifecycle
- **Config:** created/edited in form → persisted in scan's `auto_trade_configs` JSONB → server re-validates → read default-safe via `.get()`.
- **Intent:** written pre-submit → joined by reconciler → cleaned after successful `create_trade` (or on quarantine resolution).
- **Trade tag:** `strategy_kind`/`strategy_cohort`/`f1_active` written at `create_trade`; child partial-close inherits parent; immutable thereafter.
- **Ack:** written via authed endpoint → checked at long-fade entry → invalidated on exposure escalation.

---

## 5. API Architecture

| Endpoint | Change |
|----------|--------|
| `POST /scanner/scan`, `/scheduled-scans` | Accept new `AutoTradeConfig` fields (Pydantic auto, `extra="forbid"` — fields declared) |
| `GET` scan/account config endpoints | Return new fields (additive; old clients ignore unknown keys — R3-5) |
| `POST /accounts/{id}/f2-long-ack` (new) | Authenticated write of the ack record (account, leverage, capital_pct, max_trades snapshot) |
| `GET /accounts/{id}` | Returns `strategy_cohort` (read-back, R2-24) |
| `GET /trades` + `/trades/stats` | `strategy_kind` field + optional `strategy_kind=` filter; per-strategy split |
| `POST /backtest` | `BacktestCreateRequest` keeps `extra="forbid"` → fails loud if F1/F2/F3 fields sent (v2 not yet supported) |

- **Versioning:** all additive; no breaking changes for existing consumers.
- **Authz:** ack endpoint + cohort changes require account-owner/admin; a scheduled scan cannot override a per-account safety toggle (X-21, R3-13).
- **Error contract:** follows existing FastAPI validation (422 on bad config; 403 on unauthorized ack).

---

## 6. Integration Architecture

- **Bybit klines (new usage):** BTC klines for regime/vol + per-symbol klines for MR mean, via existing `KlineCacheService` + `bybit_rate_gate` (cache-first; rate-limited so a rapid scan loop can't trigger a ban — R4-13).
- **Bybit orders (existing):** `place_trade` unchanged except the new server-derived `strategy_kind` arg + pre-submit intent write.
- **Communication:** synchronous within a scan; precompute is one batched phase.
- **Fallback:** F1 fails-OPEN (data missing ⇒ no suppression, trend proceeds); F2 fails-CLOSED (data missing/stale ⇒ no MR entry). On a rejected shared BTC fetch, the future resolves to an `unavailable` sentinel and the policy is applied PER-CONSUMER after settle (never a blanket fail-closed — see §10 / §14 AD1). Precompute orchestration failure ⇒ global degrade (F1 off, F2 off, trend runs) — never aborts the scan (R4-7).
- **Single-flight:** per-symbol kline/mark-price reads coalesced across the 21 accounts in a scan; rejected future fails-closed for that phase, fresh attempt next phase (R3-17).

---

## 7. Infrastructure & Deployment

- **No new infra** — reuses Postgres, the existing kline cache, Bybit, the FastAPI app. No queues/caches/services added.
- **Migrations auto-apply on startup** (existing mechanism). Migration 45 (index) is the one deploy-risk surface — see §10.
- **Rollout:** all features default-off; safe to deploy dark, then enable per-account. Operator may enable on one account first (per-account toggle is the canary affordance).
- **Kill switch:** per-feature global kill in the `feature_kill_switches` table (NOT client JSONB), authed admin write, audit-logged. Evaluated ONCE per scan at precompute (read-fail → fail-closed/assume-killed; no-row → not-killed) — keeps the hot path network-free (§11, §14 AD2/AD19). The blast-radius control for "all live immediately"; a mid-scan kill takes effect at the next scan (acceptable window).
- **Rollback:** forward-only migrations. Rolling code back past v42 trips the boot-guard (`schema_version > max_version` → RuntimeError) — documented runbook: manual `UPDATE schema_version SET version=42` + confirm old code tolerates the additive columns (R3-2).

---

## 8. Security Architecture

- **Server-authoritative risk fields:** leverage, capital_pct, cohort, strategy_kind, all toggles re-validated server-side; client/localStorage untrusted; JSONB keys whitelisted (X-20/21).
- **`strategy_kind` server-derived:** never client-settable — prevents mislabeling a trend trade as MR (to dodge the trend blacklist) or vice-versa (R3-20).
- **F2-long ack:** the `f2_long_ack` table is the authoritative gate (ADR-6); a forged config bool cannot unlock long trading; ack staleness on exposure escalation forces re-consent.
- **Bounds:** every new numeric field Pydantic-bounded (session hours 0–23, leverage 1–125, capital >0–100, etc.) — fat-finger cannot create a catastrophic order.
- **Audit:** every regime decision, session skip, MR entry, fail-open/closed activation, ack, and kill-switch flip logged to `debug_trace` with actor where applicable; reason codes are an enum (no log injection via free strings).
- **Attack surface:** the new ack + cohort endpoints require account-owner/admin authz; the kill switch is admin-only.

---

## 9. Observability Architecture

- **Decision traces:** new skip reasons as a `ReasonCode` enum: `session_filter`, `btc_vol_filter`, `vol_unavailable`, `cohort_mismatch`, `mr_regime_excluded`, `mr_long_disabled`, `mr_long_unacknowledged`, `mr_no_edge`, `mr_degenerate_target`, `mr_mean_unavailable`, `mr_insufficient_history`.
- **Trace volume control:** ~570×21×~10 reasons could saturate the bounded drop-on-pressure buffer — per-decision skips at debug level, per-scan aggregate at info, with a per-scan emission cap/sampling (R4-8).
- **Scan-level summary:** suppressed/allowed counts, detected regime + inputs, current UTC hour (F1-19); persisted into the run/config snapshot for replay.
- **F1 efficacy:** `f1_active` + session-hour persisted on allowed trend trades so trend PnL is sliceable before/after enabling F1 (R5-G3) — the v1 "did it work" surface (backtest deferred).
- **Per-strategy split:** trades tagged with `strategy_kind` + `strategy_cohort` enable per-strategy × per-direction PnL/win-rate views (the manual-disable safety net for F2-long).
- **Metrics:** per-gate fire counts; fetch-count bounds asserted by a perf test.

---

## 10. Resilience & Failure Modes

| Failure | Behavior |
|---------|----------|
| BTC kline fetch fails/times out | F1: fail-OPEN (no suppression). F2: fail-CLOSED (no MR entry). Distinct `vol_unavailable` reason. |
| Per-symbol mean unavailable / candles < period | F2 fail-CLOSED: `mr_mean_unavailable` / `mr_insufficient_history` skip. |
| `start_scan` precompute throws/hangs | Global try/except + bounded budget → degrade (F1 off, F2 off, trend proceeds). Scan never aborts. |
| Regime flips ranging→trending between compute and place | Decision pinned to scan-time snapshot; stale beyond TTL ⇒ F2 skips (fail-closed). |
| Order fills but `create_trade` write fails | Reconciler joins orphan via `pending_trade_intents` → recovers `strategy_kind`; else quarantine/flag — never silent `trend`. |
| `post_scan_recheck` recreates close rules | MR per-position params sourced from per-trade persisted record (or open MR positions excluded) — tight-SL/time-stop preserved. |
| Single-flight shared fetch rejected | **Per data type:** a rejected BTC-kline future resolves to an `unavailable` sentinel → per-consumer policy applied after settle (F1 fail-OPEN/no-suppress, F2 fail-CLOSED/no-entry); a rejected per-symbol-kline or mark-price future is a placement prerequisite → fail-closed for both strategies. NEVER a blanket phase-level fail-closed. Fresh attempt next phase (no negative caching). |
| Index migration lock (mig 45) | EITHER non-transactional `CREATE INDEX CONCURRENTLY` under the advisory lock outside `conn.transaction()` with INVALID-index DROP+retry recovery, OR a plain build whose lock window is measured against a production-sized `trades` snapshot and gated on an SLO. Plan picks; both paths are pre-constrained safe (R3-1/R3-3). |
| Rollback past v42 | Documented runbook (manual schema_version downgrade + additive-column tolerance check). |

- **Idempotency:** scan-time precompute deterministic for a scan/cache state; `pending_trade_intents` keyed by UUID; migrations `IF NOT EXISTS`.
- **Consistency:** `strategy_kind`/`strategy_cohort` denormalized point-in-time on the trade (strong, immutable history).

---

## 11. Performance Architecture

- **Hot path network-free for F1/F3:** all BTC fetch/regime/mean computed once in `start_scan`; the kill-switch is read once per scan at precompute (§14 AD19); `_try_trade` reads in-memory scan-context + O(1) cohort compare. Only `get_mark_price` (already cached) is a trade-time read.
- **Memoization:** BTC vol/regime by distinct (metric, interval, lookback) tuple across 21 configs (≤21, typically 1–2 fetches); MR mean memoized once per (symbol, lookback-bucket, interval) per scan (AD16); single-flight dedup across accounts.
- **Aggregation:** signal counts (if any future breadth use) and means computed in one pass over 570 results, not 570×21.
- **Memory:** scan-context shared by immutable reference (not deep-copied 21×); bounded/LRU kline cache for ~570 symbols.
- **Budget:** all-on scan latency must stay within a stated budget vs the default-off baseline (perf regression test, R4-18).

---

## 12. Technology Decisions

- **Language/framework:** Python 3.12 / FastAPI / asyncpg (backend), React 18 + TS + Vite (frontend) — all existing, no new stack.
- **New modules:** `market_data.py` (BTC regime/vol + per-symbol EMA mean), `strategy_router.py` (route/resolve/gates), `scan_context.py` (frozen dataclass) — pure-function + dataclass, no new deps.
- **Indicators:** EMA/ATR/realized-vol computed in-process from cached klines (no TA library dependency added — EMA-only mean per D9a).
- **Testing:** pytest + pytest-asyncio (backend), existing frontend test setup; new files `test_market_data.py`, `test_strategy_router.py` (route + resolve_final_side truth table), `test_regime_filter.py`, `test_mean_reversion.py`, `test_strategy_cohort.py`, golden-snapshot + fixtures corpus (BTC klines, per-symbol klines, extreme-score scan_results, fixed clock). 90% coverage gate on new modules.

---

## 13. Requirement → Component Coverage (no orphans)

| Requirement group | Architectural home |
|-------------------|--------------------|
| F1 session/vol gates | `strategy_router` gate fns; `market_data` (vol); `scanner_service` precompute |
| F1 efficacy measurement | `trades.f1_active` column; per-strategy PnL view |
| F2 strategy selection | `route_strategy()` |
| F2 fade side + double-invert | `resolve_final_side()` |
| F2 mean/TP conversion | `market_data`/scan-context (mean) + executor (margin-% conversion) |
| F2 exits | `close_rule_evaluator` (time-stop/tight-SL) |
| F2-long ack | `f2_long_ack` table + ack endpoint + gate fn |
| F3 cohort routing | `strategy_cohort` (config + account col) + `route_strategy` |
| Strategy tagging | `trades.strategy_kind/strategy_cohort`; both INSERT paths |
| Reconciler safety | `pending_trade_intents` + `position_reconciler` |
| Persistence/migrations | `async_persistence` + `persistence` (43–48) |
| Feature kill-switch | `feature_kill_switches` table (mig 48) + admin endpoint + precompute-time read (once/scan, read-fail→closed) |
| Observability | `debug_trace` + `ReasonCode` enum + scan summary |
| Frontend | `AutoTradeSection` + sub-components + StrategyChip + PnL view |
| AI-manager exclusion | `ai_account_manager` filter on `strategy_kind` |
| Backtest (X-1..X-4) | v2-deferred; guarded by `BacktestCreateRequest extra="forbid"` loud-fail (R3-6) — not orphaned |

Every Step-2 requirement maps to a component; no requirement is orphaned.

---

## 14. Architecture Review R1 Resolutions

R1 (5 reviewers) found ~20 items; the substantive resolutions (AD1–AD14):

### Critical correctness
- **AD1 [single-flight × fail-open, was the High bug]** A rejected shared BTC-fetch future resolves to an `unavailable` **sentinel**; the fail policy is applied **per-consumer after the fetch settles** — F1 → fail-OPEN (no suppression), F2 → fail-CLOSED (no MR entry). NEVER a blanket phase-level fail-closed (that would wrongly suppress trend whenever F1 is on). Mark-price single-flight is a placement prerequisite (fail-closed for both strategies — distinct from a regime filter). Updates §6 + §10.

### Component boundaries & contracts
- **AD4 [MR-mean home + scope]** Rename `market_regime.py` → **`market_data.py`**, owning BOTH the BTC market regime/vol AND the per-symbol EMA-mean helper. MR mean is precomputed AFTER extreme-score signal filtering, scoped to `{symbols with qualifying MR signals} ∩ {mean_reversion-enabled accounts}` — NOT all 570. The §2 diagram pins this ordering.
- **AD5 [ScanContext frozen]** New `backend/services/scan_context.py` defines the producer→consumer contract:
  ```python
  @dataclass(frozen=True)
  class ScanContext:
      btc_regime: Literal["ranging","trending","volatile","unknown"]
      btc_vol_value: float | None
      vol_unavailable: bool
      means: dict[tuple[str,int,str], float]   # (symbol, period, interval) -> EMA
      computed_at: datetime                      # for trade-time staleness TTL
      degraded: bool                             # explicit, not absence
  ```
  `route_strategy`/`GateChain` are unit-tested against this fixed shape.

### Security
- **AD3 [ack single source of truth]** The config field is renamed `mr_long_ack_requested` (NON-authoritative UI intent). The `f2_long_ack` TABLE is the SOLE gate; any inbound config bool is ignored. Precedence stated in §8/ADR-6.
- **AD2 [kill-switch store]** New migration 48 `feature_kill_switches (feature_name TEXT PK, enabled BOOLEAN NOT NULL DEFAULT true, updated_by TEXT, updated_at TIMESTAMPTZ)`. Read cadence: once per scan at precompute (refined by AD19 — supersedes the originally-proposed ≤30s TTL hot-path cache); **read failure FAILS CLOSED** (assume killed). Shared across replicas via DB. A master "disable-all-new-features" key + per-feature keys. Admin-only authed write, audit-logged. Added to §2 path + §13 row.
- **AD9 [authz]** Ownership assertion (authenticated principal owns `{account_id}`) on the ack, cohort, and kill-switch endpoints; cross-account negative test (→403). Confirm the concrete identity model against the codebase during planning; if genuinely single-operator, document that and drop role language.

### Performance & deploy
- **AD6 [index out-of-band]** Migration 45 (index) builds OUT-OF-BAND / post-deploy (ops step or deferred background migration), NOT on startup boot — avoids readiness-probe crashloop + multi-instance advisory-lock stall + repeated INVALID-index cycles. Startup runs only catalog-only DDL (43/44/46/47/48). Documented: default-off ≠ migration-free.
- **AD8 [cache bound + budget]** Kline cache keyed `(symbol, interval, lookback-bucket)`; capacity ≥ max per-scan working set + headroom (no intra-scan eviction); state entry cap + memory estimate (candles × OHLCV × entries). Latency budget: all-on adds ≤ +30s cold-cache / ≤ +2s warm vs default-off baseline (the R4-18 perf-test threshold). MR-mean memo cardinality bounded by constraining `(period, interval)` to a small enumerated set.
- **AD7 [persisted-config rollback]** A LENIENT (ignore-extra) model RE-VALIDATES persisted scheduled-scan configs (old code reading new-written JSONB must not 422), distinct from the strict `extra="forbid"` request-ingress model. Added to the rollback runbook.
- **AD12 [rate-gate + TTL]** Kline cache TTL ≥ minimum manual-scan interval (bursts coalesce); kline fetches strictly subordinate to order placement on `bybit_rate_gate` (never delay an order) or partitioned budgets.
- **AD14 [DDL parity]** CI asserts DDL-BYTE parity across sync/async `_MIGRATIONS` (not just version lists); single shared advisory-lock key for the index across both runners.

### Operability
- **AD10 [alerting + auto-off]** Alert thresholds: F1 suppression_rate > 95% over N scans; F2-long rolling drawdown. Name the metrics sink. A safety auto-disable for F2-long trips the kill switch automatically (a minimal breaker, distinct from the full v2 circuit-breaker DEF-3).
- **AD11 [/trades/stats additive]** Retain existing top-level aggregate keys; ADD the per-strategy breakdown under a new `by_strategy` key.
- **AD13 [rollback sequencing]** Runbook order: (1) kill-switch off → (2) close/reconcile open MR positions → (3) roll back code → (4) `UPDATE schema_version` with a post-condition check. Verify v42 reconciler/close-rule behavior on pre-existing MR positions (per-trade persisted params suggest safe — confirm during planning).

**Migration set updated: 43–48** (48 = `feature_kill_switches`). Index (45) is the only out-of-band one.

## Rounds: Arch-R1 done (not clean) → resolutions AD1-AD14 applied. Next: Arch-R2.

---

## 15. Architecture Review R2 Resolutions

R2 verified AD1–AD14. Most findings were **propagation gaps** (AD-cards edited §14 but not the body) — now fixed inline: §10 single-flight row (AD1 bug re-exposed — FIXED), §6 fallback, §13 kill-switch row + "43–48". The module rename (`market_regime.py`→`market_data.py`), field rename (`mr_long_ack`→`mr_long_ack_requested`), and `scan_context.py` addition are applied as global text updates. Genuinely new substantive items (AD15–AD19):

- **AD15 [ScanContext BTC contract — was a real gap]** `btc_vol_interval`/`btc_vol_lookback_candles` are per-config (§4), so BTC vol is NOT a single scalar when accounts differ. ScanContext therefore carries BTC regime/vol as a **tuple-keyed dict** mirroring `means`:
  ```python
  @dataclass(frozen=True)
  class ScanContext:
      btc: dict[tuple[str,str,int], BtcRegime]   # (metric, interval, lookback) -> {regime, vol_value, unavailable}
      means: dict[tuple[str,int,str], float]      # (symbol, period, interval) -> EMA
      computed_at: datetime
      degraded: bool
  ```
  Each config reads `ctx.btc[(its metric, interval, lookback)]`. ADR-2's "one per scan" → "one per distinct BTC-param tuple (≤21, typically 1–2)".

- **AD16 [period/interval enumeration ENFORCED — perf hinge]** The cardinality bound that makes AD8's latency budget + 50-account scaling real must be enforced in the schema, not by convention: `mr_mean_interval: Literal["15m","1h","4h"]` and `btc_vol_interval` likewise; `mr_mean_period` quantized into the same lookback-buckets used as the cache key. CHECK==Literal CI test (R5-G6) covers them. The MR-mean memo key aligns to `(symbol, lookback-bucket, interval)` (matches the cache key).

- **AD17 [rollback boot-guard ordering — real bug]** AD13's sequence crashes: after rolling code back to v42 (step 3), the app reboots and the boot-guard (`schema_version=48 > max_version=42`) raises RuntimeError BEFORE step 4's `UPDATE schema_version` can run. CORRECTED sequence: (1) kill-switch off → (2) close/reconcile open MR positions → (3) **`UPDATE schema_version SET version=42` while new code still running** → (4) THEN deploy v42 code (boots cleanly, additive columns tolerated via AD7 lenient model). The schema_version downgrade must precede the code rollback.

- **AD18 [out-of-band index registration + verification]** Prefer the **deferred-background-migration** variant (self-healing, no manual ops) over a manual ops step. Migration 45 is registered in `_MIGRATIONS` but flagged non-transactional/background so the boot runner records its version WITHOUT building inline (no version-counter gap). A startup healthcheck WARNS (does not crash) if `idx_trades_account_strategy_kind` is absent/INVALID, so the missing-index silent-seq-scan (R2-F2) is detected.

- **AD19 [kill-switch read cadence + no-row semantics]** Kill-switch evaluated ONCE per scan at precompute (not per-trade) — keeps the hot path network-free (§11 amended to list it as a precompute-time read). Semantics: NO row = "not killed" (feature governed by its own config toggle, which is default-off anyway); an explicit row with `enabled=false` = killed; a read FAILURE (exception/timeout) = fail-closed (assume killed). "No row" (empty result) is distinct from "read failed". Master key + per-feature key: killed if EITHER says killed.

- **AD20 [v42 lenient-config pre-check]** Before merge, VERIFY the currently-deployed v42 `AutoTradeConfig` load path tolerates extra JSONB keys (if v42 is strict `extra="forbid"`, a rollback would 422 on new-written scheduled-scan configs). If v42 is strict, the rollback runbook must include a config-key-strip step. This is a pre-merge verification, not a runtime feature. (AD7 makes FORWARD code lenient; AD20 confirms the BACKWARD target.)

**Migration set: 43–48** (45 = out-of-band/background index; 43/44/46/47/48 = catalog-only on boot).

## Rounds: Arch-R2 done → AD15-AD20 applied. Next: Arch-R3 (verify, seek 2 consecutive clean).

---

## 16. Architecture Review R3 Resolutions

R3 verified AD15–AD20; findings were the same propagation class (AD-cards claimed body edits not fully applied) — now actually applied inline: §7 + §13 kill-switch cadence → "precompute-time read (once/scan)"; §11 lists the kill-switch read + means memo key → `(symbol, lookback-bucket, interval)`; §13 two `market_regime`→`market_data` refs; §4 "5"→"6" migrations. Plus:

- **AD21 [means two-level key — resolves AD15/AD16/R3-9 ambiguity]** `mr_mean_period` stays a free int (2–200, R3-9) for EMA accuracy, BUT kline FETCH/CACHE is keyed by `(symbol, interval, lookback-bucket)` (coarse, dedups fetches) while the computed `means` EMA dict is keyed by the EXACT `(symbol, period, interval)`. Two-level: bucket bounds fetch cardinality (perf), exact period preserves EMA correctness. A bucket fetch returns enough candles to compute any period within it. So AD15's `means` key (exact period) and AD16's cache key (bucket) are both correct at their own layer — not a contradiction.
- **AD22 [§13 backtest row]** Add to the coverage table: `Backtest (X-1..X-4) → v2-deferred, guarded by BacktestCreateRequest extra="forbid" loud-fail (R3-6)` — so the "no orphan" claim is honest (backtest is deliberately deferred, not unhomed).
- Note: requirements doc's "43–47 (5 migrations)" is now stale vs architecture's "43–48 (6)" — the kill-switch store (R4-11) was concretized as table 48 during Arch-R1. Architecture is authoritative for the migration set; flag for R2-17 version reservation at merge.

## Rounds: Arch-R3 done → AD21-AD22 + propagation applied. Next: Arch-R4 (confirm clean).






