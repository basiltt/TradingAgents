# Merge Plan — MCP Server + Regime Multi-Strategy into `main`

**Date:** 2026-06-07
**Risk:** HIGH (money-handling trading system, 2 large features, 9 shared files, migration collision)
**Backup tag:** `pre-merge-2feat-backup-2026-06-07` @ 3c7718b

## Features

| Branch | Commits | Scope |
|--------|---------|-------|
| `worktree-regime-multistrategy` | 28 | BTC regime filter + mean-reversion strategy cohort, strategy routing, kill-switches, pending-intents, per-strategy backtest replay. ~11.2k LOC. |
| `worktree-mcp-server` | 25 | FastMCP streamable-HTTP server, read tools, optimizer/sweep engine over the REAL backtest engine, human-approval proposal loop, token budget UI. ~17.2k LOC. |

Both share merge-base `95cc27d7` (ancestor of main). Main moved forward since (only `accounts_service.py` + its test changed in code).

## CRITICAL #1 — Migration version collision (both start at v43)

- **regime** adds v43–v51 (9): `strategy_cohort`, `strategy_kind`, indexes, `f2_long_ack`, `pending_trade_intents`, `feature_kill_switches`, `backtest_trades.strategy_kind`.
- **mcp** adds v43–v46 (4): `_migrate_mcp_v43` (6 mcp_ tables), `backtest_runs.source/sweep_id`, `mcp_config.egress_consent_at`, money-column widening.
- They COLLIDE on v43, v44. Git auto-merges both list entries with NO conflict marker → silent schema breakage.

## CRITICAL #2 — Live local DB already at v50 (regime applied)

Live DB = v50 with `f2_long_ack`, `feature_kill_switches`, `pending_trade_intents`, `trading_accounts.strategy_cohort` present; NO mcp_ tables. The developer ran regime against the local DB.

**Decision:** regime KEEPS v43–v51 (matches live DB; only v51 remains to apply). mcp RENUMBERS v43→v52, v44→v53, v45→v54, v46→v55 (append after regime's v51). Migration ints are positional-only → safe. mcp's internal dependency order preserved (v52 creates mcp_config, v54 alters it).

## Merge order: regime FIRST, then mcp

Regime anchors the migration sequence (live DB committed to it) and updates the backtest engine with strategy logic; mcp's optimizer wraps that same engine, so it should layer on top.

## Shared files (9) & conflict expectation

| File | Expectation | Resolution |
|------|-------------|------------|
| `async_persistence.py` | v43/v44 collision | Keep both helper defs; renumber mcp → v52–55 after regime v51 |
| `main.py` | CONFLICT ~256 (both insert after BacktestService) + ~596 | Keep BOTH feature blocks |
| `scanner_service.py` | CONFLICT ~428 (both extend AutoTradeExecutor construction) | Keep BOTH params/blocks |
| `auto_trade_service.py` | CONFLICT ~1145 | Keep both |
| `schemas/__init__.py` | hunks far apart (470 vs 394–691) | Likely clean |
| `accounts_service.py` | far apart (275/287 vs 194–425); main also touched it | Verify clean |
| `backtest_service.py` | far apart (873 vs 695–1146) | Likely clean |
| `position_reconciler.py` | far apart (128 vs 77/147) | Likely clean |
| `frontend/src/api/client.ts` | far apart (19/1577 vs 278–1343) | Likely clean |

Doc/spec/plan files: add/add — take each branch's own version.

## Per-step verification
1. No conflict markers (`grep -rn '<<<<<<<'`).
2. Migration list contiguous & unique (regime 43–51, mcp 52–55, max 55).
3. Backend import smoke + syntax.
4. Run impacted feature suites against live DB.

## Final verification (after both)
1. Migration dry-run on live DB (v50 → apply v51 regime + v52–55 mcp). Confirm all tables, schema_version=55.
2. Full backend suite; targeted regime + mcp + backtest suites.
3. Frontend tsc --noEmit + build + vitest.
4. Full app lifespan start/stop (all services incl. MCP server + regime wiring).
5. Conflict-marker sweep whole tree.

## Then: comprehensive multi-aspect review
Dispatch parallel reviewers (correctness, reliability, integration, security, money-critical for both features + cross-feature). Adversarially verify EVERY finding before fixing. Fix confirmed issues + regression tests. Re-verify.

## Rollback
Each feature = own merge commit. `git merge --abort` (during) / `git reset --hard pre-merge-2feat-backup-2026-06-07` (after, pre-push). Nothing pushed until all green. Live DB additive migrations reversible.
