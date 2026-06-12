# Implementation Plan: Cool Off Time

## A. Metadata
- **Plan:** Cool Off Time implementation
- **Date:** 2026-06-11
- **Status:** Draft → Plan Review (Step 7)
- **Spec:** specs/cool-off-time-spec.md (70 FR/NFR/AC, converged)
- **Architecture:** specs/cool-off-time-architecture.md (converged R6)
- **Decided Log:** plans/cool-off-time/progress-tracker.md (D1-D54, DS1-DS31)
- **Version:** 1.0

## B. Planning Summary
Implement an account-specific, optional cool-off pause for scanner auto-trade, in live + backtest.
Core = a pure shared `cooloff_core` (classify + streak state machine), a persisted
`account_cooloff_state` table (migration v61), a deferred `CooloffClassifier` (own txn, three
drivers, never in a close txn), a live gate in `AutoTradeExecutor`, a status+clear API, backtest
enforcement+reporting, and frontend config+badge. Default OFF everywhere; close path untouched;
backtest OFF byte-identical.

**Key files:**
- NEW: `backend/services/cooloff_core.py`, `backend/services/cooloff_repository.py`, `backend/services/cooloff_classifier.py`, `backend/services/cooloff_sweep.py`, `frontend/src/components/scanner/CoolOffFields.tsx`, `frontend/src/components/scanner/CoolOffBadge.tsx`
- MODIFY: `backend/schemas/__init__.py`, `backend/schemas/backtest_schemas.py`, `backend/async_persistence.py`, `backend/services/auto_trade_service.py`, `backend/services/trade_service.py`, `backend/services/backtest_engine.py`, `backend/services/backtest_service.py`, `backend/services/scanner_service.py`, `backend/routers/scanner.py`, `backend/routers/accounts.py`, `backend/main.py`, `frontend/src/api/client.ts`, `frontend/src/components/scanner/AutoTradeSection.tsx`, `frontend/src/components/backtest/*` (results)

## C. Implementation Strategy
- Bottom-up, dependency-ordered: pure core + schemas (no I/O) → DB/repo → live classifier+gate+wiring
  → API → backtest → frontend. Each phase is independently testable.
- Strict TDD per task: RED (failing test for the right reason) → GREEN (simplest pass) → REFACTOR.
- Reuse existing patterns: `_is_account_paused` gate shape, `PositionReconciler` loop, migration
  `_MIGRATIONS` entry, `RegimeStrategyFields` UI block, `clampNumberOrNull` inputs.
- The close path (`trade_repository.close_trade`/`reconcile_close`, the close transactions) is
  NOT modified. The only close-side change is a post-commit trigger line in `trade_service`.
- Feature is default-OFF; the OFF code path must remain byte-identical (backtest golden test).

## D. Phase Overview

| Phase | Goal | Key deliverables | Depends on |
|-------|------|------------------|------------|
| P1 | Pure core + config schemas | cooloff_core.py; 8 fields on AutoTradeConfig + BacktestCreateRequest + validators; TS type; pure unit tests | — |
| P2 | DB + repository | migration v61 (account_cooloff_state); CooloffRepository (read/arm/clear/settings-upsert); repo tests | P1 |
| P3 | Live classifier + gate + wiring | CooloffClassifier.maybe_classify; 60s sweep; AutoTradeExecutor._account_in_cooloff + settings pre-pass; trade_service post-commit trigger; main.py DI | P2 |
| P4 | Live API | GET /accounts/{id}/cooloff + POST .../cooloff/clear (authz + audit); MCP fields | P2,P3 |
| P5 | Backtest | cooloff_enabled state; ARM hook in _close_position; 3 gate sites; funding_paid persist; bands+skipped stats; results schema; OFF golden + determinism tests | P1 |
| P6 | Frontend | CoolOffFields (shared); validation; CoolOffBadge + Resume-now; backtest results stat+bands; TS type+DEFAULT_CONFIG | P1,P4,P5 |

Dependency note: P3 and P5 both depend on P1 (shared core) and are otherwise independent (live vs sim).
P4 can proceed after P2/P3. P6 after P4 (badge needs status API) + P5 (backtest UI).

## E. Cross-Cutting Rules (apply to every phase)
- CR-1: Default OFF; absent config fields → all-OFF. Never change behavior when no tier is enabled.
- CR-2: Cool-off NEVER opens/closes a position or modifies a close rule (NFR-001/009). Verify with a
  regression test that close-rule evaluation is identical regardless of cool-off state.
- CR-3: All new timestamps tz-aware UTC (live) / sim time (backtest). Store cooloff_until as timestamptz.
- CR-4: Fail-open everywhere on the cool-off path; log WARNING (transient) / ERROR (corruption, staleness escape).
- CR-5: One shared `cooloff_core` for live + backtest; `now` injected; pure, deterministic.
- CR-6: STALE_MIN = 1560 minutes (26h). CLAMP_MAX = 31 days. DOUBLE_THRESHOLD = 2. STREAK_CLAMP = 2.
  Define as module constants in cooloff_core.

---

## PHASE 1 — Pure Core + Config Schemas

**Goal:** the deterministic decision engine + the 8 config fields, all I/O-free and unit-tested.
**Completion criteria:** cooloff_core unit tests pass; AutoTradeConfig + BacktestCreateRequest accept/validate the 8 fields; TS type updated; backend `pytest tests/backend/test_cooloff_core.py` + `npx tsc --noEmit` green.

### TASK-P1-1: cooloff_core.py (pure module)
- File: CREATE backend/services/cooloff_core.py
- Requirements: FR-005, FR-006, FR-007 (decision part), CR-5, CR-6
- TDD: write tests/backend/test_cooloff_core.py FIRST (RED).
- Module constants: STALE_MIN_MINUTES = 1560; CLAMP_MAX_DAYS = 31; DOUBLE_THRESHOLD = 2; STREAK_CLAMP = 2.
- Enums/dataclasses (frozen):
  - Outcome = Literal["success","failure","neutral"]
  - CooloffReason = Literal["success","failure","double_success","double_failure"]
  - @dataclass(frozen=True) CooloffSettings: success_enabled:bool; success_minutes:int|None; failure_enabled:bool; failure_minutes:int|None; double_success_enabled:bool; double_success_minutes:int|None; double_failure_enabled:bool; double_failure_minutes:int|None
  - @dataclass(frozen=True) StreakState: consecutive_wins:int; consecutive_losses:int
  - @dataclass(frozen=True) ArmDecision: streaks:StreakState; arm:bool; duration_minutes:int|None; reason:CooloffReason|None
- Functions (pure, no I/O, no datetime.now/time):
  - classify_outcome(net_pnl: float|None) -> Outcome: None or not math.isfinite -> "neutral"; >0 "success"; <0 "failure"; ==0 "neutral".
  - any_tier_enabled(s: CooloffSettings) -> bool
  - decide(state: StreakState, outcome: Outcome, settings: CooloffSettings) -> ArmDecision:
    - neutral: return ArmDecision(state, arm=False, None, None)  # unchanged
    - success: new_wins=min(state.consecutive_wins+1, STREAK_CLAMP); new=StreakState(new_wins,0)
      - if new_wins>=DOUBLE_THRESHOLD and settings.double_success_enabled: reset wins->0 -> ArmDecision(StreakState(0,0), True, double_success_minutes, "double_success")
      - elif settings.success_enabled: ArmDecision(new, True, success_minutes, "success")
      - else: ArmDecision(new, False, None, None)
    - failure: symmetric (losses; double_failure / failure)
  - Note: when both single+double enabled and double fires, the double branch wins (double overrides single). When the just-incremented side is exactly at clamp (2) and double DISABLED but single enabled, single arms every time (streak stays clamped at 2).
- Tests (>=20 cases): each outcome; first-cycle (0->1); opposite resets other side to 0/new-side 1; double fires at exactly 2 then resets that side to 0; double-overrides-single (both enabled -> reason=double, dur=double); single-only at clamp keeps arming single; neutral transparent; clamp never exceeds 2; classify None/NaN/Inf/0/+/-; settings with enabled-but-None-minutes is NOT this module's concern (schema rejects it) but decide must not crash if minutes is None when arm would be True -> assert it only returns arm=True with a non-None duration (guard: if chosen minutes is None, arm=False — defensive).
- NOTE: cooloff_until computation (now + minutes, max-rearm) is done by the CALLER (classifier/backtest), not decide(), because `now` differs (UTC vs sim). decide() returns only duration+reason.

### TASK-P1-2: AutoTradeConfig 8 fields + validator
- File: MODIFY backend/schemas/__init__.py (class AutoTradeConfig @ L444, extra="forbid")
- Requirements: FR-001, FR-002, CO-CFG-1..4
- Add fields (after ai_pause_cycles ~L481, before the Regime block):
  - cooloff_on_success_enabled: bool = False
  - cooloff_on_success_minutes: Optional[int] = Field(None, ge=1, le=43200)
  - cooloff_on_failure_enabled: bool = False
  - cooloff_on_failure_minutes: Optional[int] = Field(None, ge=1, le=43200)
  - cooloff_on_double_success_enabled: bool = False
  - cooloff_on_double_success_minutes: Optional[int] = Field(None, ge=1, le=43200)
  - cooloff_on_double_failure_enabled: bool = False
  - cooloff_on_double_failure_minutes: Optional[int] = Field(None, ge=1, le=43200)
- Add @model_validator(mode="after") validate_cooloff: for each of the 4 tiers, if *_enabled is True then *_minutes must be not None (raise ValueError "cooloff_on_X_minutes required when cooloff_on_X_enabled"). Mirror style of validate_target_goal (L544).
- TDD: tests/backend/test_cooloff_schema.py — enabled-without-minutes rejects (422/ValueError); minutes 0/43201/-1/NaN reject; 1 and 43200 accept; extra field rejected (extra=forbid); absent fields default OFF; all-OFF default valid.

### TASK-P1-3: BacktestCreateRequest 8 fields + validator
- File: MODIFY backend/schemas/backtest_schemas.py (class BacktestCreateRequest @ L40)
- Requirements: FR-001 (mirror), CO-CFG-2
- Add the IDENTICAL 8 fields + the same validate_cooloff model_validator (mirror AutoTradeConfig exactly, per the file's existing mirror convention).
- TDD: extend test_cooloff_schema.py with the backtest model — same accept/reject matrix.

### TASK-P1-4: TS AutoTradeConfig type + DEFAULT_CONFIG
- File: MODIFY frontend/src/api/client.ts (interface AutoTradeConfig @ L326)
- Requirements: FR-023, CO-FE-6
- Add 8 optional fields: cooloff_on_success_enabled?: boolean; cooloff_on_success_minutes?: number | null; (and the other 3 pairs).
- File: MODIFY frontend/src/components/scanner/AutoTradeSection.tsx DEFAULT_CONFIG (@ L18): add all 8 = false/null.
- TDD: `npx tsc --noEmit` green; a small component test asserting DEFAULT_CONFIG has the 8 keys OFF/null.

### Phase 1 Validation
- python -m pytest tests/backend/test_cooloff_core.py tests/backend/test_cooloff_schema.py -x -q
- cd frontend && npx tsc --noEmit
- All green before P1 commit.

---

## PHASE 2 — Database + Repository

**Goal:** the account_cooloff_state table (migration v61) + CooloffRepository with column-scoped settings upsert, episode query, arm, clear, and status read. No business logic (that is cooloff_core).
**Completion criteria:** migration applies on a fresh DB; repo CRUD tests pass against a test DB.

### TASK-P2-1: Migration v61
- File: MODIFY backend/async_persistence.py (_MIGRATIONS list, append after current v60 @ ~L1573)
- Requirements: FR-001(storage), CO-MIG-1..4, arch §8
- Add entry (61, _SCHEMA_V61_COOLOFF) where _SCHEMA_V61_COOLOFF is the exact DDL from arch §8 (CREATE TABLE IF NOT EXISTS account_cooloff_state with: account_id TEXT PK REFERENCES trading_accounts(id); cooloff_until TIMESTAMPTZ; cooloff_reason TEXT CHECK enum; consecutive_wins/losses SMALLINT NOT NULL DEFAULT 0 CHECK >=0; last_processed_close_at TIMESTAMPTZ; last_processed_close_id UUID; the 8 settings cols (bools default FALSE; *_minutes INT CHECK NULL OR BETWEEN 1 AND 43200); updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(); CONSTRAINT chk_cooloff_pair CHECK ((cooloff_until IS NULL)=(cooloff_reason IS NULL))). Single statement, no inner semicolons, idempotent IF NOT EXISTS. NO trades-table change.
- Verify idx_trades_account_status_created (async_persistence L101) serves the open COUNT; idx_trades_account_closed (L104) serves the windowed SELECT. NO new trades index.
- TDD: tests/backend/test_cooloff_migration.py — apply migrations on a fresh test pool; assert table + constraints exist; chk_cooloff_pair rejects (until set, reason null); *_minutes CHECK rejects 0/43201.

### TASK-P2-2: CooloffRepository
- File: CREATE backend/services/cooloff_repository.py
- Requirements: FR-008/011/013/014, arch §3/§4/§8/§10/§11, D26/D38/D42/D46/DS29
- class CooloffRepository: def __init__(self, db). Holds `db` and resolves `db.pool` per call (match TradeRepository convention; do NOT snapshot a raw _pool — DP16/PBR-F4). Module const CLASSID for the advisory lock (e.g. 786433).
- Methods (parameterized SQL; reads are plain SELECT, NEVER FOR UPDATE — D42):
  - async get_state(account_id) -> dict|None
  - async upsert_settings(account_id, settings: dict) -> None: column-scoped INSERT ... ON CONFLICT (account_id) DO UPDATE SET (8 settings cols + updated_at=NOW()) ONLY — never touches state cols. Inline the full statement in the task body (DP16).
  - async read_status(account_id, *, now=None) -> dict: {cooloff_until, cooloff_reason, consecutive_wins, consecutive_losses, cooloff_remaining_seconds, cooling}; known-account-no-row -> defaults (until=null, streaks=0, cooling=false); remaining = max(0, until-now); cooling = until IS NOT NULL AND now<until (FR-029/DS29). CORRUPTION CLAMP (DP7/CR-4): if cooloff_until > now + CLAMP_MAX_DAYS(31), treat as corrupt -> cooling=False + log ERROR + best-effort guarded reset (NULL until/reason).
  - async clear(account_id, reset_streak=False) -> bool: guarded UPDATE NULLing until/reason (+ streaks=0 if reset_streak). Idempotent.
  - async count_open_scanner(conn, account_id) -> int: COUNT FROM trades WHERE account_id AND source='scanner' AND status IN ('pending','open','partially_filled','closing','partially_closed').
  - async fetch_unprocessed_closed(conn, account_id, mark_at, mark_id) -> list[dict]: SELECT id, opened_at, closed_at, net_pnl, exit_price, status FROM trades WHERE account_id AND source='scanner' AND status='closed' AND (closed_at,id) > (COALESCE(mark_at,'-infinity'), COALESCE(mark_id, all-zero uuid)) ORDER BY closed_at, id. NO LIMIT (DP1 — match arch; the open==0 flat-gate guarantees these are complete episodes; a bound would risk classifying a truncated partial run). If a defensive cap is ever added it MUST loop/re-fetch and never classify an incomplete run.
  - async try_lock(conn, account_id) -> bool: SELECT pg_try_advisory_xact_lock(CLASSID, hashtext(account_id)).
  - async apply_classification(conn, account_id, *, new_wins, new_losses, mark_at, mark_id, cooloff_until, cooloff_reason) -> None: ONE UPDATE of streak + high-water. When arming: cooloff_until = GREATEST(existing, LEAST(new, now()+CLAMP_MAX_DAYS)) (max-rearm + corruption clamp on write, DP7); cooloff_reason follows the chosen until (CASE WHEN new_until > existing THEN new_reason ELSE keep existing reason END — DP16/PBR-F3, keeps the (until,reason) pair coherent). Never touches settings cols.
- TDD: tests/backend/test_cooloff_repository.py — upsert_settings does not clobber state; read_status no-row defaults + remaining math + cooling boundary (now==until -> not cooling); clear idempotent w/ + w/o reset_streak; fetch composite-key ordering + NULL mark from-beginning + equal-closed_at tiebreak by id; count_open_scanner includes pending, excludes terminal/manual/cycle.

### Phase 2 Validation
- python -m pytest tests/backend/test_cooloff_migration.py tests/backend/test_cooloff_repository.py -x -q (test DB; skip-guard if DATABASE_URL absent, per existing repo-test convention).

---

## PHASE 3 — Live Classifier + Gate + Wiring (money-critical)

**Goal:** the deferred classifier, the 60s sweep, the executor gate + settings pre-pass, the post-commit trigger, and main.py DI.
**Completion criteria:** classifier + gate tests pass; close-path-untouched regression passes; server starts and sweep runs.

### TASK-P3-1: CooloffClassifier.maybe_classify
- File: CREATE backend/services/cooloff_classifier.py
- Requirements: FR-008/009, arch §3/§4/§10, D16/D17/D22/D31/D32/D38/D43/D51, CR-4
- class CooloffClassifier: __init__(self, db, repo, *, now_fn=lambda: datetime.now(timezone.utc)) — holds db, resolves db.pool per call (consistent with CooloffRepository; do NOT take a raw pool — PBR-R2-F1).
- async maybe_classify(account_id) -> None — own connection+transaction; ENTIRE body wrapped try/except -> log + swallow (fail-open; NEVER raises). Steps exactly per arch §3:
  1. state=get_state; if None or not any_tier_enabled(settings): return.
  2. async with self.db.pool.acquire() as conn, conn.transaction(): if not try_lock(conn): return.
  3. loop: if count_open_scanner(conn)>0: return. candidates=fetch_unprocessed_closed(...). if empty: return.
  4. episode=_earliest_episode(candidates) (pure helper, see below).
  5. settlement guard: if any episode trade NOT settled (status='closed' AND (exit_price<>0 OR net_pnl<>0)): if episode.max_closed_at < now()-timedelta(minutes=STALE_MIN_MINUTES): apply_classification advancing mark past episode as NEUTRAL (no arm) + log ERROR (staleness escape) + continue; else return.
  6. net=sum(net_pnl over episode). outcome=classify_outcome(net). decision=decide(StreakState(state.wins,state.losses), outcome, settings).
  7. cooloff_until = decision.arm ? episode.max_closed_at + timedelta(minutes=decision.duration_minutes) : None. apply_classification(conn, new_wins/losses=decision.streaks, mark=episode.max(closed_at,id), until/reason via GREATEST). log.
  8. continue to next episode (mark strictly advances -> terminates).
- _earliest_episode(rows) -> Episode (pure; unit-tested in isolation; lives in cooloff_classifier or cooloff_core): rows ordered by (closed_at,id); reconstruct flatness by interleaving opened_at(+1)/closed_at(-1) with closes-before-opens on equal timestamps (D39/D45); the earliest episode = the maximal run from the start until the running open-count first returns to 0. Returns the episode trade set + max_closed_at + max_id + the "all settled?" flag + net sum.
- TDD: tests/backend/test_cooloff_classifier.py (seeded pool or fakes): single losing episode -> failure arm; settlement defer then settle -> arm; staleness escape (>26h unsettled -> neutral advance + ERROR); idempotency (twice -> one arm, monotonic mark); two episodes between sweeps -> two in order; lock-not-acquired -> no-op; exception -> swallowed; equal-timestamp boundary split (D45) parity fixture.

### TASK-P3-2: 60s sweep
- File: CREATE backend/services/cooloff_sweep.py
- Requirements: FR-008(b), arch §3(b)/§11, modeled on PositionReconciler (L30-97)
- class CooloffSweep: __init__(self, db, classifier, accounts_service); start()/shutdown() (asyncio task; _INITIAL_DELAY ~30s; interval env COOLOFF_SWEEP_INTERVAL_S default 60). _loop: list active accounts; for each await classifier.maybe_classify(account_id).
- TDD: test_cooloff_sweep.py — calls maybe_classify per active account; one account error does not stop others; shutdown cancels cleanly.

### TASK-P3-3: AutoTradeExecutor gate + settings pre-pass
- File: MODIFY backend/services/auto_trade_service.py
- Requirements: FR-010/012/013/029, NFR-009, arch §11, D46/D50/DS19
- __init__ (L77): add cooloff_repo=None, cooloff_classifier=None; store None-guarded.
- Add async _account_in_cooloff(account_id) -> bool (sibling to _is_account_paused @ L346): if not self._cooloff_repo: return False. try: if self._cooloff_classifier: await self._cooloff_classifier.maybe_classify(account_id) (gate-time sync, FR-008c — separate acquisition, not nested in a held txn, D50). state=await self._cooloff_repo.read_status(account_id). return bool(state['cooling']). except Exception: log WARNING; return False (fail-open).
- Call the gate at init_balances (~L483, with _is_account_paused): set state.stopped=True, state.stopped_reason="cooloff_active". And post_scan_recheck (~L1006) BEFORE the state-reset block (~L1022). At the post_scan_recheck site the action MUST mirror the PAUSE block (L1008-1012) EXACTLY (DP2): `for state in states: state.stopped=True; state.stopped_reason="cooloff_active"` then `continue` — iterate ALL states under the lock and continue, or the L1022 reset block clears stopped and defeats the gate.
- Settings pre-pass (FR-013/DS19): in init_balances BEFORE the L461 stopped loop (mirror the close_on_profit pre-pass at L400-457): per distinct account, build CooloffSettings from state.config; if any_tier_enabled: try: await self._cooloff_repo.upsert_settings(account_id, dict) except Exception: log WARNING + continue (DP6 — fail-open, NEVER abort the scan, NFR-001). DO NOT upsert when no tier enabled (clobber guard).
- TDD: test_auto_trade_cooloff_gate.py — blocks at both sites (recheck loops all states + continue, runs before reset); fail-open on repo error; stopped_reason distinct; pre-pass upserts only when a tier enabled (all-OFF manual config does NOT overwrite enabled scheduled row); pre-pass upsert error is swallowed (scan not aborted); PAUSE + cooloff compose.
- TDD (CARDINAL — DP3, CR-2/AC-012/NFR-009): test_auto_trade_cooloff_closes_unaffected.py — (a) close_rule_evaluator output byte-identical with cooling ON vs OFF for the same positions; (b) the close_on_profit pre-pass still force-closes for a cooling account (cool-off must not suppress a close); (c) a cooling account with an open scanner position hitting TP/SL still closes on schedule.

### TASK-P3-4: trade_service post-commit trigger
- File: MODIFY backend/services/trade_service.py
- Requirements: FR-008(a), NFR-001/002, D37/D40
- __init__: self._bg_tasks: set = set(); self._cooloff_classifier=None.
- set_cooloff_classifier(self, classifier) deferred setter.
- _fire_cooloff(self, account_id): if not self._cooloff_classifier: return; try: t=asyncio.create_task(self._cooloff_classifier.maybe_classify(account_id)); self._bg_tasks.add(t); t.add_done_callback(self._bg_tasks.discard) except Exception: log. (Wraps SCHEDULING so it can never raise out of a committed close.)
- Call self._fire_cooloff(account_id) STRICTLY AFTER the `async with conn.transaction()` block exits in: _close_full (after L295), reconcile_close (after L97), close_trade_record_only (after L221), and the _handle_close_failure record-closed branch (after L454). NEVER inside the txn.
- TDD: test_trade_service_cooloff_trigger.py — trigger after commit not inside txn; classifier raising does NOT roll back / propagate; task ref retained.

### TASK-P3-5: main.py DI + scanner build sites
- File: MODIFY backend/main.py (~L463-489)
- Requirements: D37/D48/D54
- Build cooloff_repo=CooloffRepository(db); cooloff_classifier=CooloffClassifier(db, cooloff_repo) (PBR-R2-F1 — pass the db object, NOT db._pool; the repo resolves db.pool per call per DP16). stash on app.state. trade_service.set_cooloff_classifier(cooloff_classifier). Stamp app.state.scanner_service._cooloff_classifier/_cooloff_repo (mirror L449 _ai_manager_service). Start CooloffSweep; shutdown it in the shutdown block (mirror position_reconciler L638). NOTE: CooloffClassifier.__init__ takes (db, repo) and resolves db.pool per call (consistent with the repo; do not pass a raw pool).
- File: MODIFY backend/services/scanner_service.py (builds L564/L894): pass cooloff_repo=getattr(self,'_cooloff_repo',None) or CooloffRepository(self._db), cooloff_classifier=getattr(self,'_cooloff_classifier',None) or CooloffClassifier(self._db, that_repo) (PBR-R2-F1/F2 — pass self._db not self._db._pool; construct the classifier fallback too so the gate-time sync path is never silently dropped).
- File: MODIFY backend/routers/scanner.py (/auto-trade build): pass from request.app.state.
- TDD: test_main_cooloff_wiring.py (light) — app builds with cooloff on app.state; scanner_service receives them; sweep start/stop.

### Phase 3 Validation
- python -m pytest tests/backend/test_cooloff_classifier.py tests/backend/test_cooloff_sweep.py tests/backend/test_auto_trade_cooloff_gate.py tests/backend/test_trade_service_cooloff_trigger.py -x -q
- Regression (close path unchanged): python -m pytest tests/backend/ -k "close_rule or reconcil or trade_service or auto_trade" -x -q

---

## PHASE 4 — Live API (status + clear)

**Goal:** GET cool-off status + POST clear, behind per-account authz, audited; MCP fields.
**Completion criteria:** endpoint tests pass (200/403/404, audit, idempotent).

### TASK-P4-1: Status + clear endpoints
- File: MODIFY backend/routers/accounts.py
- Requirements: FR-014/015, NFR-012, K3, CO-API-1/2, D28/DS29
- GET /accounts/{account_id}/cooloff -> calls request.app.state.cooloff_repo.read_status(account_id). Known account, no row -> 200 defaults (DS29). Unknown account -> 404. Behind the SAME per-account ownership dependency the other accounts routes use (find it in accounts.py — likely a get_account/ownership check; name it in the task once located). Response model: CooloffStatusResponse {cooloff_until, cooloff_reason, consecutive_wins, consecutive_losses, cooloff_remaining_seconds, cooling}.
- POST /accounts/{account_id}/cooloff/clear?reset_streak=false -> repo.clear(account_id, reset_streak). 200 {cleared, cooloff_until:null}. 403 non-owner; 404 unknown. Idempotent. Audit: log structured (actor, account_id, reset_streak, before/after cooloff_until + streaks) at INFO; if a durable audit table/log exists in the app, write there (locate; else structured log per NFR-008).
- Add response schemas to backend/schemas (CooloffStatusResponse, CooloffClearResponse).
- AUTHZ NOTE (verified in accounts.py): routes use `_get_service(request)` + `_validate_id(account_id)` over a request-scoped service; the app is a single-operator localhost tool with NO per-user ownership layer. So "per-account ownership" = the same `_get_service`/`_validate_id`/account-exists(404) guard the sibling routes use; there is no 403-non-owner path to add (the spec NFR-012 threat-model note covers this). AC-017's 403 sub-clause is N/A for this deployment — assert the inherited dependency + 404-unknown instead.
- TDD: tests/backend/test_cooloff_api.py — 200 + shape; no-row defaults; 404 unknown; 403 non-owner (if authz exists; else assert the inherited dependency is applied); clear idempotent + does not reset streak unless flag; audit emitted.

### TASK-P4-2: MCP fields exposure
- File: MODIFY the MCP accounts/config payload builder (locate via mcp core; CO-API-3)
- Requirements: FR-030, CO-API-3
- Include the 8 cool-off settings + status fields in accounts_get / config payloads; no money-redaction (timestamps/counters/bools only).
- TDD: extend MCP payload test (if present) or add a targeted assertion that the fields appear.

### TASK-P4-3: Scheduled-scan config-save settings upsert (FR-013 writer-1, PPR-R2-F1)
- File: MODIFY backend/services/scan_scheduler_service.py (create/update — the POST/PATCH /scheduled-scans save path) + backend/routers/scheduled_scans.py if the upsert is wired at the router.
- Requirements: FR-013 (writer-1, authoritative), D46, CO-CFG-7
- On saving a scheduled scan, for each auto_trade_config with >=1 cool-off tier enabled, call cooloff_repo.upsert_settings(account_id, settings) (SAME column-scoped clobber guard as the executor pre-pass — only when a tier enabled; never overwrite an enabled account row with an all-OFF config). This persists settings immediately for a saved-but-not-yet-run schedule. Needs cooloff_repo available to the scheduler service (inject via main.py stamp like scanner_service, or app.state).
- TDD: tests/backend/test_scheduled_cooloff_settings.py — saving a scheduled scan with cool-off enabled persists the account_cooloff_state settings row immediately (before any run); all-OFF config does not clobber an enabled row.

### Phase 4 Validation
- python -m pytest tests/backend/test_cooloff_api.py tests/backend/test_scheduled_cooloff_settings.py -x -q

---

## PHASE 5 — Backtest enforcement + reporting

**Goal:** sim-time cool-off (ARM hook + 3 gate sites), funding-excluded net, bands + skipped stats, results schema; OFF byte-identical + determinism.
**Completion criteria:** backtest cool-off tests pass; OFF golden byte-identical; determinism (run twice identical); live-vs-backtest sign parity test passes.

### TASK-P5-1: SimulationState fields + cooloff_enabled
- File: MODIFY backend/services/backtest_engine.py (SimulationState @ L165)
- Requirements: FR-020, D52, CR-1
- Add: cooloff_enabled: bool=False; cooloff_until: datetime|None=None; cooloff_reason: str|None=None; consecutive_wins:int=0; consecutive_losses:int=0; cooloff_last_flat_idx:int=0; cooloff_bands: list=field(default_factory=list); signals_skipped_cooloff:int=0; cooloff_skipped_by_reason: dict=field(default_factory=dict).
- In run() (@ L221), set state.cooloff_enabled = any of the 4 tiers enabled in config (computed once). Also build self._cooloff_settings = CooloffSettings(...from the 8 config fields) ONCE in run() (DP8) — the ARM hook reads self._cooloff_settings (since _close_position has no config arg). ALL cool-off code below is gated on state.cooloff_enabled.

### TASK-P5-2: ARM hook in _close_position
- File: MODIFY backend/services/backtest_engine.py (_close_position @ L1954, after open_positions.remove @ L2049)
- Requirements: FR-016/018, CO-BT-15/16, D33/D44/D45, CR-1
- Persist funding_paid on the trade_record ONLY when state.cooloff_enabled: trade_record["funding_paid"]=position.funding_paid (D44 — keep absent when OFF for byte-identical golden).
- After the remove, guarded by state.cooloff_enabled and close_reason != "backtest_end" (D25) and not state.open_positions:
  cohort = state.closed_trades[state.cooloff_last_flat_idx:]; net = sum(t["pnl"] + t["funding_paid"] for t in cohort) (D33 funding-excluded); outcome=classify_outcome(net); dec=cooloff_core.decide(StreakState(wins,losses), outcome, self._cooloff_settings) (DP8 — read the run()-built settings, not a missing config arg); update wins/losses; state.cooloff_last_flat_idx=len(state.closed_trades) (advance on EVERY flat incl neutral); if dec.arm: until=exit_time+timedelta(minutes=dec.duration_minutes); state.cooloff_until=max(state.cooloff_until or until, until); state.cooloff_reason=dec.reason; append band {start:exit_time, end:until, reason}.

### TASK-P5-3: Three gate sites
- File: MODIFY backend/services/backtest_engine.py (run loop L395; selection branch L479, post_recheck branch L467, live_selection branch — gate at L426 AFTER the L425 _force_close_for_live_selection, before _open_scan_signals)
- Requirements: FR-017, CO-BT-17, D24/D39, CR-1
- Before each of the 3 _open_scan_signals calls, guarded by state.cooloff_enabled: if state.cooloff_until and open_instant < state.cooloff_until: state.signals_skipped_cooloff += len(scan_signals); bump per-reason; if state.open_positions: _evaluate_window over the SAME window the non-cooled branch uses for THIS branch (post_recheck branch -> [post_recheck_time,next], NOT [scan_started_at,...] which already ran L454-455); continue (do NOT touch cycle_start_equity/rule clocks).
- open_instant per branch (DP9): selection branch AND live_selection branch both open at selection_time; post_scan_recheck branch opens at post_recheck_time. (There is NO "live_selection instant" — _scan_live_selection returns a list; the branch opens at selection_time.)
- live_selection gate MUST sit AFTER L425 _force_close_for_live_selection (DP9/arch §7) so a live_selection flat still ARMs via the L2049 hook — only the open is skipped.
- Gate ordering: cool-off check BEFORE skip_if_positions_open so skipped signals land in the cool-off bucket (CO-BT-9).

### TASK-P5-4: Bands/stats emission (into result.filter_stats, NO schema field change)
- File: MODIFY backend/services/backtest_engine.py — at the SimulationResult construction site in run() (~L588-600), write cool-off bands + signals_skipped_cooloff (by reason) INTO result.filter_stats, guarded by state.cooloff_enabled (PQR-R2-F1 — state IS in scope here; backtest_service L2806 already copies result.filter_stats wholesale into the DB summary, so NO backtest_service change is needed and asdict(result) exposes the keys for the golden/determinism test). Do NOT add a typed field to SimulationResult/BacktestResultsResponse (DP12 — filter_stats is an open dict).
- Requirements: FR-019, CO-BT-10/19, D25, CR-1
- Absent when OFF (state.cooloff_enabled False -> no keys added -> filter_stats == the original 5 keys == golden). Bands clamped to [report_start, report_end]; overlapping/abutting bands merged (deterministic: sort by start, merge, surviving reason = the arming/later reason); drop degenerate (start>=end) or fully-out-of-window bands.
- Terminal force-close (close_reason=="backtest_end") does NOT arm (already excluded in P5-2).

### TASK-P5-5: Backtest config -> settings + cooloff_core wiring
- File: MODIFY backend/services/backtest_engine.py (run()) — build self._cooloff_settings = CooloffSettings(from the 8 BacktestCreateRequest fields) ONCE in run() (DP8); reuse cooloff_core.decide + classify_outcome (CR-5). Stored as an engine attr read by the P5-2 hook.

### Phase 5 PRE-STEP (DP10 — do FIRST, on master): capture the OFF golden
- On the current master (BEFORE any P5 code exists), commit BOTH (a) a deterministic INPUT fixture (the fixed scans + klines + config, or an inline synthetic builder — PQR-R2-F2) at tests/backend/fixtures/cooloff_golden_input.* AND (b) the serialized OFF SimulationResult at tests/backend/fixtures/cooloff_golden.json. The golden test rebuilds the IDENTICAL input from (a), so the compare is reproducible + non-circular. All P5 code lands AFTER both fixtures exist.

### Phase 5 Validation + critical tests
- tests/backend/test_backtest_cooloff.py: enforcement skips entries in the sim window; skipped scan opens nothing + no streak move; ARM at flat with funding-excluded net; bands emitted+clamped+merged; skipped-by-reason counts; a carried open position closes on schedule INSIDE a cool-off band identically to OFF (DP3/PSR-F4).
- tests/backend/test_backtest_cooloff_golden.py: OFF run == the checked-in master golden via json.dumps(dataclasses.asdict(result), sort_keys=True, default=str) (DP11 — SimulationResult is a dataclass with datetimes), zero float tolerance (AC-005). Determinism: run twice ON -> identical full result incl bands+skipped (AC-006).
- tests/backend/test_cooloff_parity.py: same synthetic episode -> live episode net == backtest cohort net EXACTLY (not just sign), incl negative funding (DP13/AC-007/AC-019); equal-timestamp boundary SPLIT exercised in BOTH the live _earliest_episode grouping AND the backtest cohort with an explicit close@T/open@T fixture (AC-015).
- python -m pytest tests/backend/test_backtest_cooloff*.py tests/backend/test_cooloff_parity.py -x -q

---

## PHASE 6 — Frontend

**Goal:** CoolOffFields (shared config), validation, CoolOffBadge + Resume-now, backtest results stat+bands.
**Completion criteria:** tsc + component tests pass; renders in both scan surfaces + backtest form.

### TASK-P6-1: CoolOffFields component
- File: CREATE frontend/src/components/scanner/CoolOffFields.tsx (mirror RegimeStrategyFields.tsx)
- Requirements: FR-021, CO-FE-1..6, DS24
- Grouped inset sub-card "Cool Off Time": "Single trade" (Success, Failure) + "Win/Loss streak" (Double-success, Double-failure). Per setting: NeuSwitch + (when ON) numeric Input + Min/Hr segmented unit selector. Defaults on enable (30/60/60/120m); preserve last value on disable (local state). Minutes stored; Hr entry -> Math.round(value*60); STICKY unit (default Min, or Hr if stored %60==0 and >=60 on first load only); full-precision Hr display, never re-round canonical minutes (DS24). Props: { config slice, onChange(partial) }. Mount inside AutoTradeSection AutoTradeCard (covers ScannerPage + ScheduledScansPage).
- File: MODIFY frontend/src/components/scanner/AutoTradeSection.tsx — mount CoolOffFields in AutoTradeCard (after RegimeStrategyFields, ~L827).
- BACKTEST FORM (DP4/PFR-F1): CoolOffFields ({config,onChange}) CANNOT drop into BacktestConfigForm.tsx (it is react-hook-form: CheckField control={control} name=... + ToggleNumberField/NumberField bound to BacktestCreateRequest). Add a SEPARATE small RHF block in BacktestConfigForm.tsx using the existing CheckField+ToggleNumberField widgets for the 8 fields (mirror how regime_filter_enabled etc. are rendered ~L1009-1035). Do NOT claim single-component reuse. (Shared validateCooloff helper — DP15 — is reused by both.)
- TDD: CoolOffFields.test.tsx — renders 4 tiers; toggle reveals input+unit; defaults on enable; Min<->Hr conversion + sticky + full-precision; bound to onChange; per-account independence. + BacktestConfigForm RHF block renders the 8 fields.

### TASK-P6-2: Validation (block save/launch)
- Requirements: FR-025, CO-FE-7, DS15
- Shared helper validateCooloff(config) -> {valid, errors per tier} in a frontend util (e.g. frontend/src/components/scanner/cooloffValidation.ts), mirroring backend validate_cooloff (enabled tier requires duration in unit-aware bounds). Consumed by BOTH the CoolOffFields inline error AND the host-page disable gates; runs over the account_id-filtered config set.
- Host pages (exact refs, DP15): components/scanner/ScannerPage.tsx handleStart (~L497; launch button disabled ~L1057); components/scanner/ScheduledScansPage.tsx handleSubmit (~L1009; save button disabled ~L1464). Block while any enabled tier invalid; identify offending account+tier inline.
- TDD: assert Save/Launch disabled + inline error shown for an enabled-blank tier; shared helper unit test.

### TASK-P6-3: CoolOffBadge + Resume-now + status query
- File: CREATE frontend/src/components/scanner/CoolOffBadge.tsx; MODIFY client.ts (add CooloffStatus interface + accountsApi.getCooloffStatus, clearCooloff)
- Requirements: FR-022/027, CO-FE-8/9/10/11, DS25, DP14
- DP14: define `export interface CooloffStatus { cooloff_until: string | null; cooloff_reason: "success"|"failure"|"double_success"|"double_failure"|null; consecutive_wins: number; consecutive_losses: number; cooloff_remaining_seconds: number; cooling: boolean }` in client.ts (matches K3/DS29). accountsApi.getCooloffStatus(id) -> CooloffStatus; accountsApi.clearCooloff(id, reset_streak?) -> mutation.
- Badge renders only when account_id present (NOT in CoolOffFields/backtest); reason + countdown (server remaining_seconds anchor, client ticks) + resume time tooltip; distinct from AI PAUSE. Resume-now button: confirm dialog, server-confirmed; invalidate cooloff-status + ["accounts"] + dashboard. Polling: baseline 30-60s + window-focus refetch while >=1 account has tiers ENABLED; faster ~15s while cooling; invalidate on scan-complete/scheduled settle; countdown->0 refetch. Mount on account card + ScannerPage selector + ScheduledScansPage row (per-account iteration within a schedule row, 0..N accounts — DP-PFR-F8). Render loading/error/empty/404 + resume in-flight states. Surface cooloff_active stopped_reason in scan/lifecycle UI (FR-027).
- ScannerPage handleStart pre-launch warn/confirm if a selected account is cooling (FR-026).
- TDD: CoolOffBadge.test.tsx — shows reason+countdown from status; Resume-now calls clear + invalidates; not rendered without account_id; pre-launch warn; cooloff_active scan reason renders distinct from ai_paused_trading (AC-023).

### TASK-P6-4: Backtest results stat + bands
- Files: MODIFY frontend/src/components/backtest/types.ts (add cool-off fields), MetricsGrid.tsx, EquityCurveChart.tsx, BacktestResultsPage.tsx
- Requirements: FR-024, CO-FE-13, DS1, DP5/DP14
- DP14: add cool-off fields to the results type in types.ts — signals_skipped_cooloff (number) + by-reason breakdown + cooloff bands [{start,end,reason}] (sourced from run.results.summary). Decide MetricsGrid data source: pass the results.summary cool-off slice into MetricsGrid (extend its props) OR add the skipped stat to BacktestMetrics — pin: extend MetricsGrid props with an optional cooloff summary, rendered only when present.
- MetricsGrid: "Signals skipped (cool-off): N" (by trigger) when present.
- EquityCurveChart (DP5/PFR-F2/F5/PFR-R2-F1): the X-axis is CATEGORICAL (dataKey="label", lossy formatTsLabel) so recharts ReferenceArea x1/x2 with arbitrary timestamps will NOT position, AND ReferenceArea-by-label is also unsafe (duplicate/lossy labels). PINNED approach: compute a per-row boolean `cooloff` membership flag in prepareEquitySeries/EquityChartDatum (in ./equityCurveData — it owns the raw EquityPoint.ts; the charted row's lossy label cannot recover ts for band membership), where a row is in-band if its ts falls within any band; render a background <Area> keyed off that flag (NOT ReferenceArea-by-label). RENDER DETAIL (PFR-R3-F1): a boolean flag as an Area dataKey fills only to height 1 (invisible against equity values); map the flag to a plottable extent — per-row band value = y-axis MAX when in-band else null (null breaks the band into gaps), OR a hidden secondary yAxisId with domain [0,1]. Make the new `bands` param to prepareEquitySeries OPTIONAL so existing equity-chart callers are unaffected. Bands data sourced from results.summary cool-off slice -> passed to equityCurveData to set the flag. Legend entry + show/hide toggle (default ON). Absent when OFF. (The ReferenceArea import is only needed if a number-axis refactor is chosen; the pinned Area-by-flag approach uses the existing Area import.)
- TDD: assert stat + bands render when results.summary carries them; absent for an OFF run.

### TASK-P6-5: accessibility + responsive
- Requirements: NFR-010/011, CO-FE-14/15
- Switch roles/aria-checked; Min/Hr keyboard radiogroup; aria-describedby errors; aria-live throttled countdown; prefers-reduced-motion; reason+time text-not-color; responsive reflow + >=44px targets + dark/light parity.

### Phase 6 Validation
- cd frontend && npx tsc --noEmit && npm run build
- cd frontend && npm test -- CoolOff (component tests)

---

## R. Traceability Matrix (FR -> Task -> Test -> AC)

| FR | Phase/Task | Test | AC |
|----|-----------|------|-----|
| FR-001/002 | P1-2,P1-3 | test_cooloff_schema | (validation) |
| FR-003/004 | P3-1 (live), P5-2/3 (bt) | test_cooloff_classifier, test_backtest_cooloff | AC-001/010/024 |
| FR-005/006/007 | P1-1 | test_cooloff_core | AC-002/003/014 |
| FR-008 | P3-1/4/5 | test_cooloff_classifier, test_trade_service_cooloff_trigger | AC-013 |
| FR-009 | P3-1 | test_cooloff_classifier | AC-018 |
| FR-010/012/029 | P3-3 | test_auto_trade_cooloff_gate | AC-001/012/016 |
| FR-011 | P2-2,P3-3 | test_cooloff_repository | AC-016 |
| FR-013 | P2-2,P3-3 (writer-2),P4-3 (writer-1) | test_auto_trade_cooloff_gate, test_scheduled_cooloff_settings | AC-020/026 |
| FR-014/015 | P4-1 | test_cooloff_api | AC-008/017 |
| FR-016..020 | P5-1..5 | test_backtest_cooloff*, golden, parity | AC-005/006/007/015/019 |
| FR-021..027 | P6-1..5 | CoolOff*.test.tsx | AC-009/011/021/022/023 |
| FR-028 | P3-1,P5-2 | test_cooloff_classifier | AC-024 |
| FR-030 | P4-2 | mcp payload test | AC-025 |
| NFR-001/002/009 | P3-3/4 | test_trade_service_cooloff_trigger, regression | AC-004/012/013 |
| NFR-005 | P5 | test_cooloff_parity | AC-007/019 |

## O. Rollback & Recovery
- Feature default-OFF: a deploy with no enabled tiers changes nothing. Rollback = redeploy prior build; migration v61 (extra table) is inert to the old code; no trades-table change to reverse. No data migration. To hard-disable at runtime: clear settings rows / no tier enabled -> classifier early-returns, gate no-ops.

## N. Manual Verification Checklist
- Start backend; confirm migration v61 applied (schema_version=61) and CooloffSweep started.
- Configure a failure cool-off (e.g. 5m) on a paper account in the manual scan UI; run a scan that loses; confirm: trade closes normally, account shows "cooling off" badge with countdown, next scan is skipped (stopped_reason=cooloff_active), badge clears at expiry.
- Resume-now clears the pause; streak unchanged.
- Run a backtest with cool-off ON: confirm skipped-signals stat + equity-curve bands; run with OFF: confirm identical to a pre-feature run.
- Confirm an open position still closes (TP/SL) while the account is cooling off.

## S. Definition of Done
- All 6 phases complete; every FR mapped to a passing test + AC; close-path regression green; backtest OFF golden byte-identical; live+backtest parity test green; tsc + build green; no unresolved Critical/High; tracker updated.

## R2. Traceability — NFR rows + additional test obligations (DP18)

| NFR | Phase/Task | Test |
|-----|-----------|------|
| NFR-001 (no close rollback/delay; fail-open) | P3-1/3-3/3-4 | test_trade_service_cooloff_trigger, test_auto_trade_cooloff_closes_unaffected |
| NFR-002 (close txn unmodified; trigger post-commit) | P3-4 | test_trade_service_cooloff_trigger |
| NFR-003 (migration additive/idempotent/no-backfill) | P2-1 | test_cooloff_migration |
| NFR-004 (plain reads, try-lock, no pool starvation) | P2-2/P3-1/P3-3 | test_cooloff_repository, test_cooloff_classifier |
| NFR-005 (live==backtest sign/value parity) | P5 | test_cooloff_parity |
| NFR-006 (hot-path index coverage) | P2-1/P2-2 | test_cooloff_repository (query plan/coverage assert) |
| NFR-007 (UTC/DST; timestamptz) | P2-2/P3-1 | test_cooloff_repository (tz-aware), test_cooloff_classifier (DST-spanning window) |
| NFR-008 (transition logging WARNING/ERROR) | P3-1/P3-3 | test_cooloff_logging (assert cooloff_armed/blocked/expired/cleared + ERROR on corruption-reset + staleness-escape; WARNING on transient fail-open) |
| NFR-009 (only gates entries; closes unaffected) | P3-3 | test_auto_trade_cooloff_closes_unaffected |
| NFR-010 (a11y) | P6-5 | CoolOff a11y test (roles/aria-checked, radiogroup keyboard, aria-live throttle) |
| NFR-011 (responsive/dark-light) | P6-5 | CoolOff responsive/theme test (>=44px, reflow, dark/light render) |
| NFR-012 (API authz inherited; 404; audit) | P4-1 | test_cooloff_api |

### Additional enumerated test obligations (DP18 — fold into the named test files)
- AC-010 (P3-1 test_cooloff_classifier): partial-close child + parent both closed -> episode net = child + parent (sign can flip win->loss); proves no parent_trade_id IS NULL filter.
- AC-016 (P5 test_backtest_cooloff): backtest gate boundary — open at exactly cooloff_until proceeds; cooloff_until-1s blocked; identical to the live repo `cooling` boundary (P2-2).
- AC-020 (P3-3 test_auto_trade_cooloff_gate): the settings pre-pass upsert runs BEFORE the stopped-check for an already-cooling account (assert order — snapshot refreshed even while gated).
- AC-023 (P6-3 CoolOffBadge.test): a cooloff_active scan result renders the cooling reason, distinct from ai_paused_trading.
- AC-024 (P3-1 test_cooloff_classifier): seed ONLY cancelled scanner rows -> maybe_classify arms nothing, streaks + high-water untouched.
- AC-009 (P6-1 CoolOffFields.test): shared AutoTradeSection renders the same per-account cool-off config in both ScannerPage + ScheduledScansPage surfaces.
- FR-023 (P1-4): hydrating a localStorage AutoTradeConfig missing the 8 cool-off keys yields all-OFF (merge guard).

### FR-013 writer-1 (scheduled config-save) — DP18 decision
- ADD: wire upsert_settings into the scheduled-scan save path (POST/PATCH /scheduled-scans handler, scan_scheduler_service.create/update) with the SAME clobber guard (only when a tier enabled), so a saved-but-not-yet-run schedule has a fresh settings row. Task: TASK-P4-3 (scheduled config-save settings upsert). Test: test_cooloff_api / test_scheduled_cooloff_settings — saving a scheduled scan with cool-off enabled persists the account_cooloff_state settings row immediately.

### P3-4 note (DP17)
- _close_partial is intentionally NOT a trigger site: a partial close leaves the account non-flat (count_open_scanner>0) so the classifier no-ops; the flat-making close always routes through _close_full/reconcile_close/close_trade_record_only; sweep + gate-time sync are the backstop.

### P3-5 note (DP16)
- scanner_service fallback constructs BOTH `repo = getattr(self,'_cooloff_repo',None) or CooloffRepository(self._db)` and `CooloffClassifier(self._db, repo)` when app.state did not stamp them (pass the db OBJECT, not self._db.pool — PR3-F1), so the gate-time sync classify path is never silently dropped.
