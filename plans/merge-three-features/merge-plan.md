# Merge Plan — Three Critical Features into `main`

**Date:** 2026-06-06
**Author:** Senior lead merge (Claude)
**Risk level:** HIGH (money-handling trading system, multiple DB migrations, 3 independent feature branches)

## Features being merged

| # | Branch | Worktree | Scope |
|---|--------|----------|-------|
| 1 | `worktree-backtesting-system` | `.claude/worktrees/backtesting-system` | Full backtesting engine: kline cache, simulation engine, metrics (TradingView parity), API, React dashboard. ~20.7k LOC. |
| 2 | `worktree-debug-tracing` | `.claude/worktrees/debug-tracing` | Always-on forensic debug tracing for AutoTradeExecutor: recorder, repository, `/api/v1/debug` router, `debug_*` tables. ~2.2k LOC. |
| 3 | `worktree-prompt-caching` | `.claude/worktrees/prompt-caching` | Anthropic prompt caching: cacheable prompt splitting, `cache_control` injection, per-run toggle, cache metrics. ~2.7k LOC. |

## Branch topology (all bases are ancestors of main)

```
... ─ f2491db6 (backtesting base) ─ ... ─ ed11dfe8 (prompt-caching base) ─ ... ─ 2f9974b (main HEAD == debug-tracing base)
```

- backtesting branched earliest; debug-tracing branched from current main HEAD.
- main already contains the **debug + caching + backtest DOC/spec files** (committed in d8121a2 `feat(debug): implement...` and the caching doc commits) but **NOT the actual code** for debug or backtest.

## CRITICAL FINDING #1 — Migration version collision (v38)

Both branches append migrations after main's max (v37):

- **backtesting** adds: `(38, _create_backtest_tables)`, `(39 analysis_price)`, `(40 widen cols)`, `(41 indexes)`
- **debug-tracing** adds: `(38, _SCHEMA_DEBUG_V38)`

The migration loop (`_apply_migrations`) applies `version > current` and stores a single max in `schema_version`. **Two `(38, ...)` entries = one set of tables silently never created.** Git auto-merges both as adjacent list items WITHOUT a conflict marker — a silent, catastrophic schema bug.

Migration version integers are **positional only** (never referenced elsewhere; code references table/column NAMES). Renumbering the integers is therefore safe.

## CRITICAL FINDING #2 — Live dev DB is already at v41 (backtest applied)

`postgresql://...localhost:5432/tradingagents` is at **schema_version = 41** with `backtest_runs/results/trades` tables and `scan_results.analysis_price` present; **no debug tables**.

The developer ran the backtesting worktree against the shared local DB. Consequences:
- **Backtest MUST keep v38–v41** to stay consistent with the already-migrated DB. Renumbering backtest would orphan the existing tables and re-run nothing.
- **Debug's v38 MUST be renumbered to v42** (next free slot). If debug kept v38, `38 ≤ 41` → debug tables would NEVER be created on this DB.

## Merge order & strategy

**Order: (1) backtesting → (2) debug-tracing → (3) prompt-caching.**

Rationale: backtest defines the v38–v41 migrations that match the live DB; merging it first anchors the migration list. Debug then appends as v42. Caching is last (zero code conflicts, pure feature-flag additions).

### Step A — Merge backtesting (`worktree-backtesting-system`)
- Code conflicts vs main: **NONE** (main didn't touch backtest's code files since its base).
- Doc conflicts (add/add): `specs/backtesting-system-spec.md`, `specs/backtesting-system-requirements.md`, `plans/backtesting-system/implementation-plan.md`, `plans/backtesting-system/progress-tracker.md`.
  - **Resolution:** take the **backtest branch** version (it is the final, more complete state: spec 420→579, tracker 67→150).
- `backend/main.py`, `backend/async_persistence.py`: auto-merge clean (main unchanged there since base).
- After merge: migrations end at v41. Verify list is contiguous 1..41 with no dup.

### Step B — Merge debug-tracing (`worktree-debug-tracing`)
- `backend/main.py`: **conflict expected** (both backtest+debug edit the lifespan startup, shutdown, and router-include regions). Resolve by **keeping BOTH** feature blocks.
- `backend/async_persistence.py`: **v38 collision**. Resolve by **renumbering debug `(38, _SCHEMA_DEBUG_V38)` → `(42, _SCHEMA_DEBUG_V42)`** and placing it AFTER backtest's `(41, ...)`. Rename the constant for clarity.
- `backend/services/scanner_service.py`: backtest (lines ~1105–1130) vs debug (320, 421–605, 894+) are non-overlapping → auto-merge clean. Verify.
- After merge: migrations contiguous 1..42; v42 = debug.

### Step C — Merge prompt-caching (`worktree-prompt-caching`)
- merge-tree vs main: **fully clean**. But after A+B, recheck:
  - `backend/services/scanner_service.py`: pc adds 1 line at ~901 (`prompt_cache_enabled` in config dict) — non-overlapping with debug/backtest regions.
  - `frontend/src/api/client.ts`: pc edits interfaces (192/289); backtest adds imports+appends end → clean.
  - `frontend/src/components/scanner/ScheduledScansPage.tsx`: pc edits 732–1322; backtest edits 1–666 → clean.
- `pyproject.toml`: pc tightens dependency upper bounds (`litellm>=1.83.7,<2`, `langchain-community>=0.4.1,<0.5`, `langchain-anthropic>=1.4.2,<2`, `langchain-core ...,<2`). Keep pc version. **uv.lock NOT regenerated by pc** (documented as un-installable in their env). Flag for follow-up but does not block (deps already satisfied in `.venv`).

## Verification after EACH step
1. `git status` clean, no leftover conflict markers (`grep -rn '<<<<<<<\|=======\|>>>>>>>' backend/ frontend/src/`).
2. Migration list contiguous & unique: assert no duplicate version ints.
3. Backend import smoke: `python -c "import backend.main"`.
4. Run impacted backend tests against the live DB.

## Final verification (after all 3)
1. Migration dry-run / idempotency check on live DB (already v41 → only v42 debug applies). Confirm debug tables created, `schema_version=42`.
2. Full backend suite: `pytest tests/backend/ -q` against live DB.
3. Targeted feature suites: backtest, debug, caching.
4. Frontend: `npx tsc --noEmit` + `npm run build` + `npm test` (vitest) for backtest components.
5. App startup smoke (lifespan builds all services without error).
6. Grep for conflict markers across whole tree.

## Rollback
- Each feature merged as its own merge commit on `main`. If a step fails verification irrecoverably, `git merge --abort` (during) or `git reset --hard ORIG_HEAD` (after, before pushing). Nothing is pushed to origin until all green.
- Live DB: v42 debug migration is additive (CREATE TABLE IF NOT EXISTS) and reversible by dropping `debug_*` tables + resetting `schema_version` if needed.

## Out of scope / follow-ups
- Regenerating `uv.lock` for pinned dep ranges (pc documented this as environment-limited).
- The other ~11 worktrees (UI redesigns, etc.) are NOT part of this merge.
