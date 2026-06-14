# Traceability Matrix — Post-Scan Optimization

Maps the MUST requirements (effective spec AC > AB > AA > F-Z) to the implementing
tasks, files, and tests. Organized by phase. "AC" references the acceptance criteria
in `specs/post-scan-optimization-spec.md`.

Legend: ✅ implemented + tested · 🔁 runtime-revertable (kill-switch) · 📄 doc/gate

---

## Phase 0 — Rate-gate correctness + ban-breaker

| Req (FR/NFR/R) | Task | File(s) | Test(s) | Status |
|---|---|---|---|---|
| FR-001 public/private channel fix | 0.1-0.3 | `bybit_client.py`, `bybit_endpoints.py` | `test_bybit_client_channels.py`, `test_bybit_endpoints.py` | ✅🔁 |
| FR-002 per-(account,endpoint) sub-limiter | 0.4 | `bybit_rate_gate.py` | `test_bybit_rate_gate_v2.py` | ✅🔁 |
| FR-047 per-channel caps (400+100) | 0.4 | `bybit_rate_gate.py`, `main.py` | `test_bybit_rate_gate_v2.py` | ✅ |
| FR-006a ban-breaker (IP-ban only, not per-UID 10006) | 0.5 | `bybit_rate_gate.py`, `bybit_client.py` | `test_bybit_rate_gate_v2.py` (ban trip/clear/half-open) | ✅ |
| FR-048 background lanes wait out bans; order lane raises | 0.5 | `bybit_rate_gate.py` | `test_bybit_rate_gate_v2.py`, `test_bybit_client_channels.py` | ✅ |
| FR-049 revert kill-switches read own key | 0.6 | `post_scan_flags.py`, `features.py` | `test_post_scan_flags.py` | ✅🔁 |

## Phase 1 — Live WebSocket status

| Req | Task | File(s) | Test(s) | Status |
|---|---|---|---|---|
| FR-007 per-scan progress pub/sub | 1.1 | `scan_progress_manager.py` | `test_scan_progress_manager.py` | ✅ |
| FR-008 WS endpoint (strict origin + scan-existence) | 1.3 | `ws_scan_progress.py` | `test_ws_scan_progress.py` | ✅ |
| FR-045 wire allow-list (no account_id/label/secrets) | 1.3 | `ws_scan_progress.py` | `test_ws_scan_progress.py` (projection) | ✅ |
| FR-007 sink None-safe fail-open | 1.4 | `auto_trade_service.py` `_emit_progress` | `test_emit_progress_fail_open.py` | ✅ |
| CR-6 scan config-count for cold-load predicate | 1.5 | `scanner_service.py`, `client.ts` | `test_scan_config_count.py` | ✅ |
| PR2-7 canonical acct_ordinal | 1.6 | `auto_trade_service.py` `_acct_ordinal_map` | `test_acct_ordinal.py` | ✅ |
| FF-1..4 frontend poll-through-tail + single renderer | 1.7-1.8 | `ScannerPage.tsx`, `useScanAutoTradeProgressWS.ts`, `PostScanExecutionPanel.tsx` | `useScanAutoTradeProgressWS.test.tsx`, `PostScanExecutionPanel.test.tsx` | ✅ |

## Phase 2 — Bounded parallelism + data integrity

| Req | Task | File(s) | Test(s) | Status | AC |
|---|---|---|---|---|---|
| FR-025 orchestrator (single entry, both call sites) | 2.2 | `auto_trade_service.py` `run_post_scan_tail`, `scanner_service.py`, `routers/scanner.py` | `test_post_scan_orchestrator.py` | ✅ | AC-001 |
| FR-026/027 process-wide semaphore + single-flight | 2.3 | `post_scan_concurrency.py` | `test_post_scan_concurrency.py` | ✅🔁 | AC-002 |
| FR-028/029/030 per-account partition/merge | 2.4 | `auto_trade_service.py` `_fan_out_by_account` | `test_post_scan_golden.py` | ✅ | AC-003 |
| FR-034/035 merge from slots, not gather returns (cancel-safe) | 2.4 | `auto_trade_service.py` | `test_post_scan_golden.py` (ban-abort survival, stray-cancel) | ✅ | AC-003 |
| FR-004a/043 lock-order + shield order→stop | 2.5 | `accounts_service.py` `place_trade` | `test_place_trade_shield.py` | ✅ | AC-004 |
| FR-031/042 parallelize recheck/cleanup/summaries | 2.6 | `auto_trade_service.py` | `test_post_scan_golden.py` (recheck width), `test_auto_trade_service_unit.py` | ✅ | — |
| FR-036 replace-by-stage persist; commit-before-terminal | 2.7 | `auto_trade_service.py`, both call sites | `test_post_scan_orchestrator.py` (emit_complete defer) | ✅ | AC-009 |
| FR-038/AC-FIX-1 orphan log → reconciler (no auto-adopt) | 2.8 | `accounts_service.py` | `test_place_trade_shield.py` (orphan) | ✅ | AC-008 |
| FR-043/044 cancel + None-safety + backtest green | 2.9 | `auto_trade_service.py` | `test_post_scan_golden.py` (no-services, cancel) | ✅ | — |
| CR-5/NFR-003 golden-equality (the central net) | 2.10 | — | `test_post_scan_golden.py` | ✅ | AC-003 |
| SC-1/SC-2 default width=1; speedup is private-bound latency-hiding | — | `post_scan_concurrency.py` | `test_post_scan_benchmark.py` | ✅ | — |
| (R2 hardening) single-flight hard-gate + TOCTOU | rev | `routers/scanner.py`, `scanner_service.py` | `test_router_scanner.py` (409, claim-release) | ✅ | — |

## Phase 3 — UX polish + cross-cutting + release gate

| Req | Task | File(s) | Test(s) | Status |
|---|---|---|---|---|
| FR-041/042 panel polish + stage-key correctness | 3.1 | `PostScanExecutionPanel.tsx` | `PostScanExecutionPanel.test.tsx` (stage-key, placed→✓) | ✅ |
| FR-042/R195 ban cooloff banner (global, backend-wired) | 3.2 | `PostScanExecutionPanel.tsx` cooloff banner, `auto_trade_service.py` `_run_stage` ban emit (`cooloff_until`) | `test_post_scan_orchestrator.py::test_ban_emits_substatus_and_cooloff_for_panel`, `PostScanExecutionPanel.test.tsx` (cooloff) | ✅ |
| FR-045/R119 reason_code wire scrub (no free-text leak) | 3.4 | `auto_trade_service.py` `_wire_reason_code` | `test_post_scan_orchestrator.py::test_wire_reason_code_strips_free_text` | ✅ |
| NFR-008/R186 placement-integrity detectors (per-config) | 3.5 | `post_scan_detectors.py`, `auto_trade_service.py` self-check | `test_post_scan_detectors.py` (per-config breach, recheck no-false-positive) | ✅ |
| NFR-001/002/R196 speedup benchmark + zero-10006 + negative control | 3.6 | — | `test_post_scan_benchmark.py` (structural max_concurrency proof + global throttle + negative control) | ✅ |
| R196/FR-049 Definition-of-Done gate + operator notes | 3.8 | `DOD-GATE.md` | (the gate IS the test list) | ✅📄 |
| Step 16 traceability | 3.9 | `TRACEABILITY.md` | (this file) | ✅📄 |

---

## Deferred / scoped-out (tracked, not regressions)

| Item | Reason | Tracking |
|---|---|---|
| Durable crash-resume (deterministic orderLinkId) | Pre-existing risk (R108/109), not parallelization-caused; impossible vs current schema (SC-1, D15). Resume stays no-worse-than-today. | Spec §AB SC-1 |
| `init_balances` parallelization | One-time pre-scan state machine with 5 interdependent caches + force-close barrier; high bug risk, marginal gain. Tail (the user-visible cost) is parallelized. | Tracker D20 |
| Operator trust-boundary token (TASK-3.3) | Default width=1 makes the width-override inert; loopback-peer gate is the MUST, token is SHOULD for first ship. | Plan §3.3 |
| Steady-state non-tail regression sweep (TASK-3.7) | Phase 0 channel fix already covered by `test_bybit_*`; broader per-subsystem sweep is additive. | Plan §3.7 |
| Per-account `substatus` pills (rate_wait micro-throttle + per-account ban badge) | The near-ban `substatus="rate_wait"` gate-instrumentation hook (TASK-3.5) is unwired; the ban is emitted at STAGE level (global cooloff banner, which IS live). The per-account pills are UI-ready and light up the moment the backend emits a per-account substatus. | `PostScanExecutionPanel.tsx` (DEFERRED comments), DOD-GATE operator notes |
| Width-change-mid-flight semaphore split | Rare manual operator action; over-concurrency only (not double-placement); per-channel caps are the backstop. | `post_scan_concurrency.py` docstring |
| `acct_ordinal` cross-scan salting (R119) | The ordinal (1,2,3…) is stable cross-scan but carries NO identity — `account_id` never crosses the wire (stripped by the allow-list); single-tenant deployment. Consciously simplified to refresh-stable-per-scan; an observer cannot resolve `acct#N` to an account. | `auto_trade_service.py` `_acct_ordinal_map`, `ws_scan_progress.py` allow-list |
