# P4 Gap-Closure Plan (post-traceability)

**Trigger:** Step-16 traceability audit + independent verification found the optimizer
shipped as a synchronous, test-only composite. This closes the MVP-scoped gaps G0–G5.

**Source of truth for "done":** `plans/mcp-server/TRACEABILITY.md` flips to SATISFIED.

---

## G0 — Real optimizer execution (FOUNDATIONAL; FR-016/017/019)
The shipped `optimize_config` calls `run_sweep_inproc(signals=[], snapshot={}, instrument_info={})`
— hollow. `BacktestService.run_one` (the BacktestRunner adapter) was never built; `app.state.mcp_backtest_runner` never wired.

**Tasks:**
- G0-1: `BacktestService.run_one(config, signals, snapshot, instrument_info, *, deadline)` —
  reuse `BacktestEngine().run(...)` synchronously in the executor, NO DB persist, return a
  metrics dict (extract from `BacktestResult`). Satisfies the `BacktestRunner` Protocol.
- G0-2: wire `app.state.mcp_backtest_runner = backtest_service` (it already satisfies the
  protocol once run_one exists) in main.py near backtest_service init.
- G0-3: the optimizer composite must LOAD real inputs once (baseline signals/klines/instrument
  for the date range) and pass the shared snapshot to every combo (in-sample, one load).
- G0-4: tests — run_one against a tiny real-shaped klines fixture returns finite metrics;
  optimize_config with the real runner (small grid) produces a winner with provenance.

## G2 — Live-trading protection (FR-034/035/036, NFR-002/AC-011) — highest real-money risk
**Tasks:**
- G2-1: `core/dbfloor.py` — compute a reserved live-floor; cap MCP/sweep pool acquisitions
  below `pool_max - floor`. Preflight `db_budget_ok` computes it for real (not a stub bool).
- G2-2: `tools/optimizer/runner_pool.py` — `ProcessPoolExecutor(spawn, max_workers≤cores-1,
  initializer=_worker_init)`; `_worker_init` scrubs secrets from os.environ + POSIX-guarded
  `os.nice`/`oom_score_adj`. Worker = module-level sync entrypoint `_run_combo(...)`, DB-LESS,
  returns metrics. Parent collects futures.
- G2-3: shared-memory columnar snapshot for klines (build off-loop; SIGBUS/ENOSPC preflight
  shm gate); Windows guard → fall back to in-process.
- G2-4: `core/breaker.py` — live-SLI breaker (event-loop lag / reconciler / order p95 / pool-wait)
  suspends MCP with hysteresis; out-of-band kill path. Fail-closed if SLIs absent.
- G2-5: leader guard (FR-034) — advisory-lock on a dedicated never-pooled connection when
  WEB_CONCURRENCY>1; non-leaders degrade.
- G2-6: `conftest.synthetic_order_reconciler` fixture (drives REAL order+reconciler paths vs
  fakes, records per-cycle latency; idle = baseline). `test_live_protection.py` (Linux-only
  marker): max sweep → live-order p95 ≤ 1.15× AND p99 ≤ 1.3× AND max-cycle < bound, N≥500.
- G2-7: `test_worker_scrub.py` — worker env has no secret canary (AC-010).

## G1 — Async sweep persistence (FR-021/040, AC-023/025) — TASK-P4-12b/13
**Tasks:**
- G1-1: `repositories/sweep_repo.py::SweepRepository` — all SQL for `mcp_sweep_jobs` /
  `mcp_sweep_results` (create job, write-result own-txn, claim-running boot-recovery,
  list/get, re-rank stored results by alternate objective). No asyncpg outside the repo.
- G1-2: tools `sweep_run(space,objective,constraints,strategy)→sweep_id`, `sweep_status`,
  `sweep_results(sweep_id,objective?)`, `sweep_cancel`. `optimize_config` persists via the repo.
- G1-3: control-plane `GET /sweeps` (keyset), `GET /sweeps/{id}`, `GET /sweeps/{id}/results?objective=`
  (server-side re-rank — FR-040), `POST /sweeps/{id}/cancel`.
- G1-4: boot-recovery — claim-running sweeps marked `interrupted` then resumed by completed
  config-hash set (AC-023). Hook into mcp_boot.
- G1-5: tests — persist+re-rank (AC-025), crash-recovery (AC-023), cancel persists partial.

## G3 — Approval depth + dedicated UI (FR-024, AC-009) — TASK-P4-J1/J2
**Tasks:**
- G3-1: `/mcp/proposals/$proposalId` route + `McpProposalReview.tsx` — server risk verdict,
  segregated "agent-generated, unverified" rationale panel, field-level diff with high-risk
  flags, per-high-risk-field ack checkbox + typed-confirm input, applied-config version
  history with one-click revert.
- G3-2: `OptimizerSection` / sweep browser in `/mcp` (list sweeps, open results, re-rank).
- G3-3: high-risk-field classifier (leverage↑, capital↑, SL removed) drives the ack gate.
- G3-4: vitest — typed-confirm blocks until exact match; ack required per high-risk field.

## G4 — Egress consent (FR-033, AC-022)
- G4-1: `mcp_config.egress_consent_at` column (v45 additive); set once on first enable.
- G4-2: enable flow records consent; control-plane exposes it; `/mcp` shows a persistent notice.
- G4-3: test — consent recorded exactly once; re-enable doesn't duplicate.

## G5 — Misc (FR-003/014, AC-019)
- G5-1: preflight real dry-connect self-test (in-process loopback initialize).
- G5-2: kline cache MCP tools `cache_status` / `cache_warmup` (wrap existing service methods).
- G5-3: `test_kill_switch_under_load.py` — out-of-band disable under a saturated loop cancels
  in-flight sweeps (Linux-friendly; uses the breaker path).

## Sequence
G0 → G2 → G1 → G3 → G4 → G5 → re-run traceability → readiness → merge.
(G0 first: everything real depends on a working engine adapter. G2 before G1: the pool/floor
the sweep persistence runs on must exist + be safe before we let agents launch async sweeps.)
