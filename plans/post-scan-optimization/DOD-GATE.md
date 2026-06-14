# Definition-of-Done Gate — Post-Scan Optimization (width>1 release)

**Status:** Phase 0-3 implemented. This gate governs flipping account-concurrency
**width>1** in production. The feature SHIPS at **width=1** (byte-identical to the old
sequential tail) regardless — every item below must be green before an operator raises
`POST_SCAN_ACCOUNT_CONCURRENCY` above 1.

---

## Gate checklist (ALL must be green before width>1)

| # | Criterion | Proof | Status |
|---|-----------|-------|--------|
| G1 | **Golden-equality**: parallel (width=2) places the byte-identical per-account ordered tuple stream + close rules + counters as sequential (width=1). | `tests/backend/test_post_scan_golden.py` (per_account_tuples, created/deleted-rule fingerprint, summary counters, recheck width-invariance) | ✅ |
| G2 | **width=1 is byte-identical** to the pre-change sequential path. | Full pre-existing auto-trade suite green (`test_auto_trade_service_unit.py` etc., 37 tests) + golden width=1 leg | ✅ |
| G3 | **Speedup**: parallel < sequential wall-clock at the SAME N (RTT-overlap), N=5/10/20; advantage plateaus, capped at the width (latency-hiding, not throughput). | `tests/backend/test_post_scan_benchmark.py::test_parallel_faster_than_sequential_same_n`, `::test_speedup_is_latency_hiding_capped_at_width` | ✅ |
| G4 | **Zero 10006 + negative control**: under the concurrency bound the GLOBAL rate-aware throttle never trips; a deliberately-too-low bound MUST trip (falsifiability). | `test_post_scan_benchmark.py::test_zero_10006_under_concurrency_bound`, `::test_negative_control_10006_fires_when_bound_exceeded` | ✅ |
| G5 | **No double-placement / over-cap**: the placement-integrity detector finds zero duplicates and zero over-cap accounts after a parallel tail. | `tests/backend/test_post_scan_detectors.py` + the inline `run_post_scan_tail` self-check (logs HIGH on violation) | ✅ |
| G6 | **Failure isolation**: one account's failure/ban/cancel does not drop another account's placed orders from `auto_trade_results`. | `test_post_scan_golden.py::test_placed_orders_survive_midaccount_ban_abort`, `::test_stray_child_cancel_does_not_tear_down_healthy_tail`, `::test_one_account_failure_isolated_from_others` | ✅ |
| G7 | **Orphan-safety**: an order that hits the exchange but fails its DB write (or is cancelled mid-submission) is protected by inline TP/SL and surfaces a structured `orphan_order` alert for the reconciler. | `tests/backend/test_place_trade_shield.py` + the cancel-during-submission orphan log | ✅ |
| G8 | **Both call sites unified**: scheduled tail, manual re-run, and resume all route through `run_post_scan_tail`; single-flight prevents an auto+manual same-scan double-run. | `test_post_scan_orchestrator.py`, `test_router_scanner.py` (409 + claim-release), `test_post_scan_concurrency.py` | ✅ |
| G9 | **Backtest / no-services path green** at width>1. | `test_post_scan_golden.py::test_full_parallel_tail_green_in_no_services_mode` | ✅ |
| G10 | **Rate-gate channel correctness** (Phase 0) is live: public reads on the public channel, per-account/endpoint sub-limiter, ban-breaker. | `test_bybit_rate_gate_v2.py`, `test_bybit_endpoints.py`, `test_bybit_client_channels.py` | ✅ |
| G11 | **Frontend converges**: live stepper stage keys match the backend emit keys; throttle vs ban distinct; cold-load shows persisted view. | `frontend/.../PostScanExecutionPanel.test.tsx`, `useScanAutoTradeProgressWS.test.tsx`; `tsc --noEmit` clean | ✅ |

---

## How to verify the gate locally

```bash
# Backend gate suite
python -m pytest \
  tests/backend/test_post_scan_golden.py \
  tests/backend/test_post_scan_benchmark.py \
  tests/backend/test_post_scan_detectors.py \
  tests/backend/test_post_scan_orchestrator.py \
  tests/backend/test_post_scan_concurrency.py \
  tests/backend/test_place_trade_shield.py \
  tests/backend/test_router_scanner.py \
  -x -q

# Frontend
cd frontend && npx tsc --noEmit && \
  npx vitest run src/components/scanner/__tests__/PostScanExecutionPanel.test.tsx \
                 src/hooks/__tests__/useScanAutoTradeProgressWS.test.tsx
```

---

## Operator notes (brief — not a full runbook)

### Concurrency width
- **Env:** `POST_SCAN_ACCOUNT_CONCURRENCY` (default `1`). Clamped to `[1, 16]`; a bad value
  degrades to `1` (never aborts startup).
- **Default `1`** runs the exact sequential path. Raise to `2` first, observe, then step up.
  The speedup is **latency-hiding** — it overlaps per-account network RTTs up to the
  private-channel cap, then plateaus. Past ~the cap there is little additional gain;
  do NOT expect linear scaling with width.

### Revert kill-switches (DB-backed `feature_kill_switches`, refreshed ~15s)
- `post_scan_fanout_disabled = true` → forces effective width **1** (sequential) at runtime,
  regardless of the env width. Use this to instantly revert the parallel path.
- `rate_gate_channel_fix = true` → reverts the public/private channel classification.
- `rate_gate_per_endpoint_limiter = true` → disables the per-account/endpoint sub-limiter.
- Each reads its OWN key only — they are NOT coupled to the regime `__all__` master kill.
  A transient DB blip does NOT revert them (fails closed to "keep the fix active").

### Reading ban / throttle state
- **Confirmed ban cooloff** (the "Trading paused ~Nm — rate-limit cooloff" BANNER): a
  RateGateBanAbort during the tail emits `cooloff_until`, and the panel shows a global
  countdown banner. An IP ban is active; the tail waits it out. Force-killing a banned
  run can EXTEND the ban — let it drain. **This is the live signal that works today.**
- **Micro-throttle pill** ("rate limit" pulse) and the **per-account "paused" badge**:
  the panel renders these off a per-account `substatus`, but the current backend only
  emits the ban as a STAGE-level event (global banner), not a per-account row. So these
  two per-account indicators are **wired in the UI but not yet driven by a backend emit**
  (the near-ban `substatus="rate_wait"` hook is the deferred TASK-3.5 gate instrumentation).
  Treat the cooloff banner as the authoritative ban signal until that hook lands.
- A `post_scan_placement_integrity_violation` or `orphan_order` log at `severity=high` is
  an operator alert — investigate via the scan id / account id in the record.
