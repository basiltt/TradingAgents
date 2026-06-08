# Production-Ready Backend — Progress Tracker

**Active Skill:** `/production-ready` (`~/.claude/skills/production-ready/SKILL.md`)
**Started:** 2026-06-09
**Worktree:** `.claude/worktrees/production-ready-backend-hardening` (branch `worktree-production-ready-backend-hardening`)
**Worktree base:** local HEAD `7ca17c9` (main, 18 commits ahead of origin/main — backtest work included)

## CRITICAL RECOVERY NOTE
After any context compaction: read THIS tracker, then re-read `~/.claude/skills/production-ready/SKILL.md`, then resume from the last IN_PROGRESS / next PENDING step. Do NOT restart or skip phases. Review rounds spawn **3 agents in parallel per round** via direct Agent tool calls (NOT TeamCreate). Each phase exits on **2 consecutive clean rounds** or its round budget. Global hard stop at round 250.

## Target Scope
- **Target:** `backend/` (entire FastAPI backend)
- **Files:** 172 Python files, ~47,652 LOC
  - `backend/services/`: 66 files, 27,882 LOC (bulk — trading engine, AI manager, backtest)
  - `backend/mcp/`: 61 files, 6,294 LOC (external MCP API surface — high risk)
  - `backend/routers/`: 24 files, 3,863 LOC (HTTP surface — high risk)
  - `backend/schemas/`: 4 files, 1,782 LOC
  - top-level: 17 files, 7,831 LOC
- **Tests:** 2,634 collected (186 backend test files)
- **Python:** 3.14.3 | venv at main repo `.venv` (PYTHONPATH=. picks up worktree backend/)
- **Run tests with:** `PYTHONPATH=. <main-repo>/.venv/Scripts/python.exe -m pytest tests/backend -o addopts=""`

## Baseline (Step 0)
| Metric | Value |
|---|---|
| Backend tests collected | 2,634 (2,300 excl mcp) |
| **Authoritative baseline (single-proc, excl mcp)** | **2262 passed, 35 failed, 3 skipped (982s/16min)** |
| — all 35 failures PRE-EXISTING (0 code changes by me) | 14 validators (order-dep isolation) + 21 stale/investigate |
| mcp/ tests | 29 require real Postgres — excluded from code baseline |
| Coverage | DEFERRED — full suite 16min; measure per-module in Phase 4 |
| Ruff lint errors (default rules) | 36 (15 F401, 11 E702, 5 F821 REAL BUGS, 3 F841, 2 E741) |
| Ruff (strict-pragmatic ruleset) | 324 high-value (76 B904, 51 I001, 30 SIM102, 28 PERF203, 5 F821, …) |
| Type checker | mypy not installed; ruff used for static checks |
| Dependency vulns | 14 in 8 pkgs (pip-audit) |

### Regression-detection strategy (given 16-min full suite + order-dependent tests)
- **Per-fix gate:** run the specific changed test file(s) IN ISOLATION single-proc; a regression = a test green-in-isolation that my change turns red.
- **Phase-boundary gate:** run TARGETED test batches (per changed-module) single-proc. NOTE: the FULL single-proc suite is BRITTLE — aborts on interpreter-teardown lock races (ThreadPoolExecutor `_global_shutdown_lock`) under pytest-timeout, producing a no-summary timeout. Use targeted batches of ~6 files instead (fast + reliable). Reserve a full run only for the final Step 8 gate, in small chunks.
- NEVER use xdist `-n` as a gate (false failures from order-dependence). xdist only for quick non-isolation-sensitive scans.
- Baseline failed-set snapshot: plans/production-ready-backend/baseline-failures.txt

### Dependency vulnerabilities (address in Phase 6 — careful, large codebase)
| Package | Cur | Fix | IDs |
|---|---|---|---|
| starlette | 1.0.0 | 1.0.1 | PYSEC-2026-161 (FastAPI core — most relevant) |
| aiohttp | 3.13.5 | 3.14.0 | CVE-2026-34993, CVE-2026-47265 |
| urllib3 | 2.6.3 | 2.7.0 | PYSEC-2026-142, PYSEC-2026-141 |
| idna | 3.13 | 3.15 | CVE-2026-45409 |
| python-dotenv | 1.0.1 | 1.2.2 | CVE-2026-28684 |
| langchain-core | 1.3.2 | 1.3.3 | CVE-2026-44843 |
| litellm | 1.83.7 | 1.83.10 | CVE-2026-40217 |
| pip | 25.3 | 26.1 | (tooling, not runtime dep) |

### Baseline REAL BUGS found (fix in Phase 1/5)
1. `backend/services/ai_manager_task.py:2021` — `logger` undefined (should be `self._log`) — NameError if cleanup fails
2. `backend/services/ai_manager_task.py:2118` — `logger` undefined — NameError if commentary fails
3. `backend/services/ai_manager_task.py:2252` — `logger` undefined — NameError in daily cleanup
4. `backend/services/ai_manager_task.py:2255` — `logger` undefined — NameError in daily cleanup
5. `backend/services/backtest_service.py:1060` — `ScanContext` forward-ref undefined-name (verify import scope)

## Tooling Setup
- [x] Worktree created (branched from local HEAD with baseRef=head)
- [x] ruff 0.15.16 installed
- [x] pytest-timeout 2.4.0 + pytest-xdist 3.8.0 installed (baseline hung w/o timeout — DB-dependent MCP tests)
- [~] Baseline tests recorded (re-running with --timeout=60 -n4 after first run hung)
- [ ] Baseline coverage recorded
- [x] pip-audit run (14 vulns / 8 pkgs)
- [ ] Strict ruff config added to pyproject.toml (planned below)

### Planned Phase 1 ruff config (strict-but-pragmatic, FastAPI-aware) — apply in P1 R1
- line-length = 120 (235 E501 remain vs 2411 @ 88; most code targets ~120)
- select = E, F, W, B, SIM, UP, I, C4, PIE, RET, PERF, ASYNC
- ignore (cosmetic/false-positive at scale): E501 (handled separately/gradually), UP045/UP006/UP007/UP035/UP037 (annotation churn — defer), SIM105, RET504, RET505, B008 (FastAPI Query/Depends idiom)
- → yields ~324 high-value findings (76 B904 exc-chaining, 51 I001 imports, 30 SIM102, 28 PERF203, 5 F821 REAL BUGS, etc.)
- Note: confirm whether to keep E501 in or gradually fix the 235 over-120 lines; lean to fixing in P1.

### Test infra note (BLOCKER resolved)
First baseline run (`pytest tests/backend`, no timeout, single-proc) HUNG at ~30% — pytest proc flat CPU 94s, no progress. Root cause: DB-dependent MCP tests (tests/backend/mcp/*) using real asyncpg/DATABASE_URL with no DB available block indefinitely. Fix: run with `--timeout=60 --timeout-method=thread -n 4`.

### CRITICAL TEST-STRATEGY FINDING (xdist unsafe)
- xdist `-n 4` run: **2563 passed, 37 failed, 29 errors, 5 skipped** (314s)
- BUT `test_validators.py`: 25/25 PASS single-proc, 14 FAIL under `-n4` → **xdist causes false failures** (test-isolation/shared-state/network-resolution races). xdist is UNSAFE as a baseline/regression gate for this suite.
- 29 errors all in `tests/backend/mcp/*` = require real Postgres (no DB present) → environmental, excluded from code baseline.
- **Authoritative test command (single-process):**
  `PYTHONPATH=. <venv>/Scripts/python.exe -m pytest tests/backend --ignore=tests/backend/mcp --timeout=120 --timeout-method=thread -o addopts=""`
- For targeted fast re-runs during phases, run the specific changed test files single-process.

### REAL pre-existing failures (NOT xdist artifacts — reproduce single-proc) — 19 total
Confirmed by single-proc reruns. All are STALE TESTS referencing old internal APIs/behaviors after prod refactors (prod code evolved, tests didn't). Per skill, these must pass by end of process (fix in Phase 4/5).

1. `test_close_positions_service_unit.py` — 9 fail. TEST DRIFT: prod `_close_single_position` now requires `cumExecQty > 0` fill-confirmation (line ~202); mock `place_market_close_order` returns no `cumExecQty` → service returns closed=0, tests assert closed=1. Prod is the safer version. FIX: add `cumExecQty` to mocks.
2. `test_bybit_rate_limiting.py` — 3 fail. TEST DRIFT: `AttributeError: 'BybitClient' object has no attribute '_request_timestamps'` — rate-limit internals were refactored/renamed; tests reference removed attr. FIX: update tests to new rate-limit API.
3. `test_engine_filter_chain.py` — 4 fail (TestImmediateModeFillToMaxTrades x2, TestInstrumentInfo x2). Investigate in Phase 4/5.
4. `test_persistence.py::test_schema_migration_higher_version_refused` — 1 fail (the other persistence xdist failure was an artifact). Investigate.
5. `test_close_rule_evaluator_ws.py::test_debounce_allows_after_interval` — 1 fail (timing/debounce). Investigate.
6. `test_security.py::test_start_analysis_backend_url_private_ip_rejected` — 1 fail. Investigate (SSRF guard test).

### xdist-ONLY artifacts (pass single-proc — NOT real failures)
- `test_validators.py` — 14 fail under -n4, 25/25 PASS single-proc. Cause: `_allow_local()` reads `ALLOW_LOCAL_LLM_BACKEND` env; monkeypatch.setenv races across xdist workers + getaddrinfo. Pure isolation issue.
- `test_persistence.py::test_concurrent_writes` — xdist artifact (module skips if no PostgreSQL).
- 29 `mcp/*` ERRORS — require real Postgres; excluded from code baseline via --ignore=tests/backend/mcp.

### Authoritative single-proc baseline (excl mcp): RUNNING (bp6fixz8k) — at 81%

## Phase Status
| Phase | Name | Budget | Status | Rounds | Findings |
|---|---|---|---|---|---|
| 0 | Discovery & Baseline | — | DONE | — | 5 baseline bugs |
| 1 | Type Safety & Linting | 24 | DONE (gate met) | 3 | 14 real bugs + 76 B904; ruff 325→0, mypy 94→0 |
| 2 | Clean Code & Patterns | 28 | IN_PROGRESS | 0 | — |
| 2.5 | Documentation | 22 | PENDING | 0 | — |
| 2.75 | Maintainability | 20 | PENDING | 0 | — |
| 3 | Logging | 20 | PENDING | 0 | — |
| 4 | Testing | 36 | PENDING | 0 | — |
| 5 | Bug Detection & Robustness | 36 | PENDING | 0 | — |
| 5.5 | Future-Proofing | 14 | PENDING | 0 | — |
| 5.75 | Performance | 16 | PENDING | 0 | — |
| 6 | Config & Security | 14 | PENDING | 0 | — |
| 7 | Final Holistic | 30 | PENDING | 0 | — |

## State
- current_round: 0
- current_phase: 0
- clean_streak: 0
- total_findings: 0
- findings_by_severity: {critical: 0, high: 0, medium: 0, low: 0, info: 0}

## Decided Log (Debate Resolution Protocol)
_(entries added as findings are resolved; check before applying any contradicting fix)_
- DECIDED-1 (R1): `ai_manager_task.py` exception handlers use `self._log` (per-account logger), NOT bare `logger`. Evidence: class defines `self._log = logging.getLogger(...)` at __init__; module has no `logger`. Status: FINAL.
- DECIDED-2 (R1): `backtest_service.py` resolves `ScanContext` annotation via a `TYPE_CHECKING` import; runtime import stays lazy inside `_build_scan_contexts()` to avoid the scan_context→services→backtest_service cycle. Status: FINAL.
- DECIDED-3 (R1): `trade_service._broadcast` uses `is not None` (not truthiness) for `realized_pnl`/`net_pnl` so a breakeven 0.0 PnL is broadcast as 0.0, not null. Status: FINAL.
- DECIDED-4 (R1): `close_rule_evaluator._check_time_elapsed` guards `reference_value` for None/empty before `.replace()` (a None value with key present escaped the except tuple as AttributeError). Status: FINAL.
- DECIDED-5 (R1): `accounts.close_trade` body uses `Body(default_factory=TradeCloseRequest)` not a shared mutable `TradeCloseRequest()` default. Status: FINAL.
- DECIDED-6 (R1): `accounts_service.create_account` raises RuntimeError if post-insert `get_account` returns None (removed bare `# type: ignore` that hid the Optional mismatch). Status: FINAL.
- DECIDED-7 (R1): B904 exception chaining — convention: `except ... as <var>:` → `raise ... from <var>`; `except SomeError:` (no var, user-facing replacement msg) → `raise ... from None`. Applied to all 76 sites. Status: FINAL.
- DECIDED-8 (R3): mypy run non-strict (`--ignore-missing-imports --follow-imports=silent`). 94 errors → 0. 5 REAL null-safety bugs fixed with guards (see below). Scoped `# type: ignore[code] # reason` only (never bare). Status: FINAL.
- DECIDED-9 (R3): `ai_manager_orderbook` connect path captures `_ensure_session()` return into a local `session` (typed non-None) instead of touching `self._session`/`self._ws` (Optional) — fixes union-attr crash if session not yet created. Status: FINAL.
- DECIDED-10 (R3): `mcp/mount.MCPManager` attrs given `Optional[...]` types (TYPE_CHECKING imports); `enable()`/`disable()` raise RuntimeError if `config_repo is None` (not-booted) instead of cryptic AttributeError. Status: FINAL.
- DECIDED-11 (R3): `ai_manager_llm_provider` `x or os.getenv("K","")` → `x or os.getenv("K") or ""` for mypy str-narrowing; behavior identical except an explicitly-empty env var now falls back to the default (more correct, empty model/provider was invalid anyway). Status: FINAL.

## Phase 1 REAL BUGS fixed (total 9 + 76 B904)
F821 (5): 4× undefined `logger` in ai_manager_task.py; ScanContext forward-ref.
Correctness (4): trade_service 0.0-PnL-as-null; close_rule_evaluator None.replace AttributeError; accounts mutable Body default; accounts_service type:ignore-masked Optional.
mypy null-safety (5): orderbook None-session ws crash; scanner None-scan .get; mcp/mount None-config_repo enable/disable; trades/read None-rows iteration; trailing None mini_llm_fn.
Plus 76 B904 exception-chain losses.

## Test-quality findings (for Phase 4)
- TQ-1: `tests/backend/test_validators.py` + `test_security.py` leak global env state (`ALLOW_LOCAL_LLM_BACKEND`) without cleanup → order-dependent failures (validators 25/25 alone, 14 fail when co-run after security). Fix in Phase 4: monkeypatch.delenv or autouse cleanup fixture. This is THE cause of the "14 validator failures" seen under xdist and batched runs — NOT a code bug.

## Activity Log
- 2026-06-09: Step 0 started. Worktree created from local HEAD (verified 17 backtest commits present). ruff installed. Baseline lint = 36 errors incl. 5 F821 real bugs. Backend test baseline running in bg.
