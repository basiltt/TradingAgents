# MCP Server — Requirements Traceability Matrix

**Generated:** Step 16 (post-implementation audit, pre-merge)
**Method:** each FR/AC mapped to implementing code + proving test by reading the actual codebase.
**Verdicts:** SATISFIED · PARTIAL · UNMET · DEFERRED(P5/P6, intentional)

---

## Functional Requirements

| FR | Verdict | Code | Test |
|----|---------|------|------|
| FR-001 default OFF fresh DB | SATISFIED | config_repo.repair_to_failsafe / migrations v43 | test_off_path, test_migrations |
| FR-002 OFF→no transport, /mcp/rpc 503 | SATISFIED | mount._Indirection/_gate_503 | test_off_path, test_control_plane |
| FR-003 enable preflight + dry-connect | PARTIAL | core/preflight.run_preflight | test_preflight (shm/SLI invariants stubbed; no live dry-connect self-test) |
| FR-004 kill-switch drops sessions/cancels sweeps | PARTIAL | mount.disable(kill=True)/bump_kill_epoch | (transport teardown tested; no out-of-band-under-saturated-loop test; no in-flight-sweep cancel — no async sweeps exist) |
| FR-005 init failure degrades, never aborts startup | SATISFIED | mount.mcp_boot try/except; main.py seam | test_off_path (boot-failure), e2e |
| FR-006 hot enable/disable ref-swap | SATISFIED | mount enable/disable + indirection | test_control_plane |
| FR-007 advertise only enabled; disabled→-32601 | SATISFIED | registry.resolve_enabled; server.call_tool | test_registry, test_dispatch |
| FR-008 groups+individual toggle, most-restrictive | SATISFIED | registry.resolve_enabled | test_registry |
| FR-009 presets predicates; Minimal zero-mutating | SATISFIED | registry.PRESETS + _minimal | test_registry, test_preset_hardening |
| FR-010 UI N-count + token meter ±10% | SATISFIED | core/budget + /mcp/registry + TokenMeter | test_budget, test_registry_endpoint |
| FR-011 read tools (all 9 rows) | SATISFIED | tools/{scans,accounts,positions,trades,portfolio,analytics,scheduled,symbols}/read | test_p1_read_tools, test_p1_completion |
| FR-012 resources + static prompts | SATISFIED | resources/catalog | test_resources_prompts |
| FR-013 summary/detail + keyset pagination + bounded | SATISFIED | core/shape; tools use project/paginate | test_shape, test_p1_completion |
| FR-014 backtest_run + get/list/compare + cache | PARTIAL | tools/backtest/read | test_p3_backtest_debug (schema-equiv ✓; kline cache_status/warmup tools NOT built) |
| FR-015 sweep_estimate combo/feasibility, >5000 refuse | SATISFIED | tools/optimizer/tools.sweep_estimate | test_optimizer_tools |
| FR-016 grid/random, dedup config-hash, ranked top-N | SATISFIED | combos + ranker + orchestrator | test_combos, test_ranker, test_orchestrator |
| FR-017 baseline current + uplift | SATISFIED | orchestrator + ranker.compute_uplift | test_ranker, test_golden_sweep |
| FR-018 keep-current robustness bar | SATISFIED | ranker.robustly_beats + orchestrator | test_ranker, test_golden_sweep |
| FR-019 provenance (config-hash/range/seed) | PARTIAL | orchestrator result carries config_hash | test_golden_sweep (seed/range provenance not persisted — no sweep store) |
| FR-020 fidelity caveat + robustness verdict | SATISFIED | ranker.robustness_verdict; orchestrator fidelity_caveat | test_ranker, test_golden_sweep |
| FR-021 sweep_id fire-and-poll + sweep_cancel | **UNMET** | — | — (only sync optimize_config; no sweep_run/status/results/cancel, no SweepRepository, no mcp_sweep_* persistence) |
| FR-022 winner→pending proposal + target schedule/index | SATISFIED | optimize_config→create_proposal_from_winner; proposal_repo | test_apply_loop (create→approve→revert) |
| FR-023 human-apply: sanitize→ceiling→validate→atomic drift-guard | SATISFIED | apply.py + proposal_service + apply_auto_trade_config_atomic | test_apply_pipeline, test_apply_loop, test_final_hardening |
| FR-024 approval screen ack+typed-confirm+rationale+history | PARTIAL | MCPProposals.tsx (diff + approve-confirm) | (per-field ack, typed-confirm, segregated rationale panel, version history NOT built) |
| FR-025 proposal TTL expiry coerce-or-reject | SATISFIED | proposal_service expiry; repo | test_apply_loop (expired) |
| FR-026 bearer constant-time, fail-closed 401 | SATISFIED | core/auth.BearerAuthenticator; transport guard | test_auth, test_transport |
| FR-027 Host loopback + non-loopback Origin reject | SATISFIED | core/netguard; transport _AuthHostGuard | test_netguard, test_transport |
| FR-028 capability tier ceiling, re-read per call | SATISFIED | registry.tier_allows; dispatch tier-gate | test_dispatch, test_registry |
| FR-029 deny-list + call-graph (no money sink) | SATISFIED | registry._DENY_METHODS | test_architecture |
| FR-030 no secret leak (outputs/audit/logs) | SATISFIED | redact.strip_secret_keys; dispatch backstop | test_redact, test_dispatch (worker-env scrub N/A — no ProcessPool) |
| FR-031 balances/abs-P&L redacted by default | SATISFIED | redact.redact_record + money markers | test_redact, test_p1_completion |
| FR-032 audit hash-chain single writer | SATISFIED | core/audit.AuditWriter | test_audit, test_audit_repo |
| FR-033 one-time egress consent + persistent notice | **UNMET** | — | — (no consent record, no /mcp notice) |
| FR-034 single-worker / advisory-lock leader | PARTIAL | config_repo (kill_epoch); single-worker assumed | (no multi-worker advisory-lock leader guard built) |
| FR-035 DB-pool floor reserved for trading loop | **UNMET** | — | — (no reserved-floor cap on MCP acquisitions) |
| FR-036 ProcessPool/spawn/shm sweep execution | DEFERRED | in-process orchestrator (run_sweep_inproc) | (perf layer; pure core shipped) |
| FR-037 bybit_rate_gate subordinate lane | SATISFIED | bybit_rate_gate acquire_async(lane='mcp') | test_rate_gate_lane |
| FR-038 debug tools allow_debug-gated, redacted | SATISFIED | tools/debug/read | test_p3_backtest_debug |
| FR-039 optimizer constraints exclude + objective enum | SATISFIED | ranker constraints + OBJECTIVE_METRICS | test_ranker, test_optimizer_tools |
| FR-040 re-rank stored sweep by alt objective | **UNMET** | — | — (no sweep store; no /sweeps/{id}/results?objective=) |

## Acceptance Criteria

| AC | Verdict | Note |
|----|---------|------|
| AC-001 fresh DB OFF + 503 + no bg task | SATISFIED | test_off_path |
| AC-002 enable preflight failure names invariant | SATISFIED | router.enable 422 + test_preflight |
| AC-003 Minimal preset zero-mutating + -32601 | SATISFIED | test_registry/test_preset_hardening |
| AC-004 token meter ±10% client-side | SATISFIED | test_budget + TokenMeter |
| AC-005 optimize_config baseline+combos+top-N | SATISFIED | test_golden_sweep |
| AC-006 keep-current when nothing beats | SATISFIED | test_golden_sweep null-result |
| AC-007 golden sweep == known winner-hash + full bar | SATISFIED | test_golden_sweep |
| AC-008 winner→pending proposal, agent can't apply | SATISFIED | test_apply_loop |
| AC-009 high-risk field ack+typed-confirm+revert | PARTIAL | revert ✓; per-field ack + typed-confirm NOT built |
| AC-010 CI fails on money-sink/secret-canary | PARTIAL | deny-list test ✓; no worker-secret-canary (no ProcessPool) |
| AC-011 live-order p95≤1.15x under max sweep | **UNMET** | no synthetic fixture / live-SLI gate (TASK-P4-12c) |
| AC-012 init raise → startup ok mcp_server=None | SATISFIED | test_off_path boot-failure |
| AC-013 bad token/forged Host rejected fail-closed | SATISFIED | test_transport |
| AC-014 WEB_CONCURRENCY>1 leader + DB floor | UNMET | no leader guard / floor (FR-034/035) |
| AC-015 OFF suite unchanged + <50ms overhead | SATISFIED | host-app regression green; OFF-path |
| AC-016 backtest schema-equivalence | SATISFIED | test_p3_backtest_debug |
| AC-017 scans_get no re-run + redacted balances | SATISFIED | test_p1_read_tools/test_p1_completion |
| AC-018 debug allow_debug gate | SATISFIED | test_p3_backtest_debug |
| AC-019 kill-switch under saturated loop cancels sweeps | PARTIAL | disable tested; no saturated-loop/sweep-cancel test |
| AC-020 proposal expiry + stale-schema coerce-or-reject | SATISFIED | test_apply_loop |
| AC-021 audit tamper detected + single-writer no-fork | SATISFIED | test_audit, test_audit_repo |
| AC-022 egress consent once + notice | **UNMET** | FR-033 not built |
| AC-023 backend killed mid-sweep → resume not stuck | **UNMET** | no sweep persistence/recovery |
| AC-024 constraint-exclude + unsupported-objective error | SATISFIED | test_ranker, test_optimizer_tools |
| AC-025 re-rank stored sweep by objective | **UNMET** | FR-040 not built |
| AC-026 apply drift-guard + no lost update | SATISFIED | test_apply_loop drift |

---

## Summary

**SATISFIED:** 28/40 FR · 17/26 AC — the entire OFF-path/security/auth/audit/read-tool/redaction/optimize→propose→approve→apply money path is built, tested, and reviewed.

> **UPDATE (gap-closure pass — see `06-gap-closure.md`):** all 5 gap clusters below
> were subsequently CLOSED. Net result now **38/40 FR · 25/26 AC SATISFIED**;
> the only remaining DEFERRED items are genuine P5/P6 future scope (advanced
> optimizer validation, shadow/paper, remote bind, mcp_tokens). The Linux-only
> live-order-p95 gate (AC-011) is built + asserted in Linux CI (skip-marked on
> Windows dev). See the per-cluster closure notes appended below.

**Gaps grouped:**

### G1 — Async sweep persistence (FR-021, FR-040, FR-019 partial, AC-023, AC-025) — P4 TASK-P4-12b/13
The synchronous `optimize_config` works end-to-end, but the **`sweep_id` fire-and-poll** model is absent: no `sweep_run`/`sweep_status`/`sweep_results`/`sweep_cancel` tools, no `SweepRepository`, no `mcp_sweep_jobs`/`mcp_sweep_results` tables used, no re-rank endpoint, no crash-recovery. Impact: an agent cannot disconnect/reattach to a long sweep, and sweeps aren't persisted for later compare/re-rank.

### G2 — Live-trading protection (FR-035, FR-036, FR-034, NFR-002/AC-011, AC-014) — P4 TASK-P4-12/12c
The headline RISK mitigation in the architecture. **Not built:** ProcessPool/shm sweep isolation, reserved DB-pool floor, multi-worker leader guard, the synthetic order/reconciler fixture, and the **live-order-p95 gate** (the spec's "gating assertion"). The in-process orchestrator runs sweeps on the event loop — acceptable for small/fast FakeRunner sweeps, but the spec's guarantee that a max sweep won't degrade live trading is unproven.

### G3 — Approval-screen depth (FR-024, AC-009)
Per-field acknowledgment, typed-confirm, segregated agent-rationale panel, and applied-config version history are not built. Basic diff + approve-confirm dialog exists.

### G4 — Egress consent (FR-033, AC-022)
One-time data-egress consent record + persistent `/mcp` notice not built.

### G5 — Smaller (FR-003 dry-connect, FR-014 kline cache tools, FR-004/AC-019 saturated-loop cancel test)

**Intentional DEFERRED (not gaps):** FR-036 ProcessPool is partially in G2; P5/P6 (advanced optimizer, shadow/paper, remote bind, mcp_tokens) per spec §"Future Scope".

---

## Gap-closure verification (post-implementation)

| Cluster | Was | Now | Evidence |
|---------|-----|-----|----------|
| G0 hollow optimizer exec | (masked) | CLOSED | BacktestService.run_one + load_inputs; metric-alias fix; test_run_one_adapter, test_optimizer_tools real-data path |
| G1 FR-021/040, AC-023/025 | UNMET | CLOSED | SweepRepository + sweep_run/status/results/cancel + /sweeps endpoints + recover_interrupted; test_sweep_repo, test_sweep_tools |
| G2 FR-034/035/036, NFR-002/AC-011/014 | UNMET | CLOSED | dbfloor + runner_pool(spawn+scrub) + breaker + leader + live-protection gate (Linux); test_dbfloor/breaker/leader/runner_pool/live_protection |
| G3 FR-024, AC-009 | PARTIAL | CLOSED | McpProposalReview (/mcp/proposals/$id): server verdict + segregated rationale + per-field ack + typed-confirm + version history; MCPSweepBrowser; vitest McpProposalReview |
| G4 FR-033, AC-022 | UNMET | CLOSED | v45 egress_consent_at + record_egress_consent (idempotent) + /mcp EgressNotice; test_config_repo consent |
| G5 FR-003/014, AC-019 | UNMET/PARTIAL | CLOSED | cache_status/cache_warmup tools + server.self_test dry-connect + saturated-loop kill test; test_g5_misc |

**Remaining DEFERRED (genuine P5/P6, per spec "Future Scope"):** advanced optimizer
(walk-forward/OOS, Pareto, Monte Carlo, sensitivity), shadow/paper probation,
staged capital rollout, champion-config memory, generated PDF reports,
resources/subscribe + live notifications, remote-bind transport, mcp_tokens
multi-token table. None are MVP.

---

## NFR verification (final pass)

| NFR | Verdict | Evidence |
|-----|---------|----------|
| NFR-001 read-tool p95<200ms | SATISFIED | test_nfr_gates::test_nfr001 (50-sample in-proc dispatch p95) |
| NFR-002 live-order gate under sweep | SATISFIED (Linux CI) | test_live_protection (N=600, p95≤1.15×, p99≤1.3×baseline_p99, max<bound); skip on Windows |
| NFR-003 audit write <5ms | SATISFIED | test_nfr003 (100-sample enqueue p95<5ms, non-blocking queue) |
| NFR-004 preset budgets ≤2k/8k/20k + per-tool cap | SATISFIED | budget.PRESET_TOKEN_CEILINGS + test_nfr004 |
| NFR-005 5000-combo <60s FakeRunner | SATISFIED | test_nfr005 (timed orchestration) |
| NFR-006 default OFF / READ_ONLY / fail-closed | SATISFIED | preflight + config_repo failsafe + test_off_path |
| NFR-007 never crash live process | SATISFIED | mount degrade-to-None + spawn pool isolation; test_off_path boot-failure |
| NFR-008 restart mid-sweep recovers | SATISFIED | sweep_repo.recover_interrupted + mount boot + test_sweep_repo |
| NFR-009 one-way dep, import-linter enforced | SATISFIED | .importlinter contract 'mcp-one-way-dependency' KEPT (services/routers/tradingagents ↛ mcp) |
| NFR-010 health mcp sub-status (degraded≠503) | SATISFIED | main._mcp_health_substatus in /api/v1/health + test_nfr010 |
| NFR-011 OFF <50ms startup overhead | SATISFIED | test_nfr011 (register_mcp timed) |
| NFR-012 NaN/Inf→NULL at persist, per-combo committed | SATISFIED | sweep_repo._nan_to_null/_safe_objective + own-txn write; test_nfr012 |
| NFR-013 /mcp a11y (roles/labels/keyboard) | SATISFIED | a11y.test.tsx (progressbar ARIA, native controls, no positive tabindex) |
| NFR-014 Linux CI MCP job (POSIX gate) | SATISFIED | .github/workflows/ci.yml mcp-tests job (Postgres service + full suite + import-linter) |

**Phase exits now met:** P2 (budget ceilings + a11y test present), P4 (live-order gate N≥500 + max bound + p99-vs-p99).

**All 14 NFRs SATISFIED.** Combined with 38/40 FR + 25/26 AC (the 2 remaining are P5/P6
future scope), the feature meets its MVP spec. Note: NFR-002's protection gate is
*asserted* only in Linux CI (POSIX ProcessPool) — on Windows dev it skip-marks.
