# Phase 0 — Rate-Gate Correctness + Ban Breaker (PREREQUISITE)

**Goal:** Make the centralized Bybit rate gate channel-correct, per-`account_id`/per-endpoint-aware, ban-safe, and runtime-revertible — BEFORE any parallelization raises request pressure. Default behavior unchanged when kill-switches are off.

**Requirements:** FR-001..009, FR-047, FR-006a, FR-049 (validation logic), R59-R78, R169, R171, AC-FIX-2/3/5.
**Depends on:** nothing. **Blocks:** Phase 2 (fan-out).

---

## Files
| File | Action | Purpose |
|---|---|---|
| `backend/services/bybit_rate_gate.py` | Modify | Per-`account_id`/endpoint sub-limiter; combined check; ban breaker + half-open admission; thread-safe `_wait_count`; endpoint registry |
| `backend/services/bybit_client.py` | Modify | Per-endpoint channel classification; route `_do_sync_time`; pass `endpoint_class` + `account_id`/uid-key + correct `lane` to the gate |
| `backend/services/feature_flags.py` or existing `features.py` | Modify | Runtime kill-switches for channel-fix + per-endpoint-limiter (revert to current behavior) |
| `backend/main.py` | Modify | Startup config validation (FR-049 logic) |
| `tests/backend/test_bybit_rate_gate.py` | Create | Gate unit tests |
| `tests/backend/test_bybit_client_channels.py` | Create | Channel classification + regression tests |

---

## Tasks

### TASK-0.1 — Endpoint→class→channel registry (FR-005, FR-001, FR-067)
- **Files:** `bybit_rate_gate.py` (add a module-level registry) or `bybit_client.py`.
- **Notes:** A single dict mapping each Bybit path → `(channel, endpoint_class)`:
  - `/v5/market/tickers`, `/v5/market/instruments-info`, `/v5/market/kline`, `/v5/market/time` → `("public", "market")`
  - `/v5/order/create` → `("private", "order_create")`
  - `/v5/order/cancel` → `("private", "order_cancel")`
  - `/v5/position/set-leverage` → `("private", "set_leverage")`
  - `/v5/position/trading-stop` → `("private", "set_trading_stop")`
  - `/v5/position/list` → `("private", "position_list")`
  - `/v5/account/wallet-balance` → `("private", "wallet")`
  - `/v5/order/history`, `/v5/order/realtime` → `("private", "order_query")`
- A lookup helper `classify(path) -> (channel, endpoint_class)`; **assert/raise** on an unmapped path used by `_request` (prevents silent mis-charging).
- **TDD:** test every known path maps; test an unmapped path raises.
- **AC:** AC-003 (public read → public channel).

### TASK-0.2 — Per-`account_id`/endpoint sub-limiter (FR-003, FR-004, FR-006a, R169)
- **Files:** `bybit_rate_gate.py`.
- **Notes:** Extend `BybitRateGate` with per-`(account_key, endpoint_class)` rolling-window deques (1s window) alongside the existing public/private 5s deques. `acquire_async(channel, *, lane, account_key=None, endpoint_class=None)`:
  - In ONE `with self._lock` critical section (await-free), prune + check ALL applicable dimensions: the channel 5s deque AND (if private + account_key/endpoint_class given) the per-(account_key,endpoint_class) 1s deque. **All-or-none:** append to every dimension only if ALL pass; else append to NONE and compute backoff = `max()` of the per-dimension waits; sleep OUTSIDE the lock (preserve the existing pattern at lines 92-108).
  - Caps (1s window, ~80% of Bybit floor): `order_create`/`order_cancel`=8, `set_leverage`=8, `set_trading_stop`=8, `position_list`=40, `wallet`=40, `order_query`=20.
  - `account_key` = the internal `account_id` (NOT a resolved UID — per D6/CR-2).
  - Keep public=400, private=100 (5s). Assert `public_max + private_max ≤ 500` (FR-006a). NO standalone 540 counter (SC-2c).
  - Mirror the same all-or-none logic into `acquire_sync`.
- **TDD:** test a single dimension throttles; test all-or-none (no IP token leaked on a per-endpoint miss); test backoff = max of dims; test concurrent acquirers never both pass `len < budget` (force interleave).
- **AC:** AC-004 (order-create >8/s throttles, no 10006).

### TASK-0.3 — Thread-safe `_wait_count` (FR-008, R171)
- **Files:** `bybit_rate_gate.py:90,110,116,130`.
- **Notes:** Move `self._wait_count += 1 / -= 1` INSIDE `self._lock` (or use an atomic). Used by the near-ban detector → safety-relevant, not just telemetry.
- **TDD:** test concurrent async+sync callers leave `_wait_count` consistent (no lost update).

### TASK-0.4 — Ban breaker + half-open admission (FR-047, R74, R186b, AC-FIX-5)
- **Files:** `bybit_rate_gate.py`.
- **Notes:** Add a process-wide breaker: on repeated `10006` (signaled from `bybit_client._request` after retries) within a short window, OPEN — set `_ban_until = now + ban_window`. `acquire_async` AND `acquire_sync` poll the breaker each wait iteration; while OPEN they raise a distinct `RateGateBanAbort` so the caller releases any held position-lock and re-queues (does NOT pin a lock across the pause). Recovery is HALF-OPEN via a shared admission counter: at `_ban_until`, admit K=1 for one full 5s window; on a successful probe ramp K→2→4 per subsequent window; a probe failure re-arms a fresh ban window. Parked waiters acquire an admission token (not a bool re-check) so 10·N tasks can't flood at recovery.
- **TDD:** test OPEN → `RateGateBanAbort` raised; test half-open admits K then ramps; test 10·N parked tasks at expiry keep post-recovery 5s egress ≤ caps; test probe-failure re-arms.
- **AC:** new AC (ban breaker releases lock + bounded recovery).

### TASK-0.5 — `bybit_client` channel routing + lane fixes (FR-001, FR-002, FR-007, FF-4)
- **Files:** `bybit_client.py`.
- **Notes:**
  - `_request` looks up `classify(path)` and passes `channel` + `endpoint_class` + `account_key` (the client's `account_id`) to `_wait_for_rate_limit`/the gate. Remove the hardcoded `channel="private"` (line 226).
  - `_do_sync_time` (line 72-88): route its `/v5/market/time` GET through the gate on the `public` channel via a dedicated high-priority/reserved path so a saturated public channel can't starve it (stale clock → 10002); run off the event loop if called sync.
  - `set_trading_stop` (line 554/573) and `_poll_order_fill` (line ~515) pass `lane="order"` (complete-an-open-position must not starve on the private channel).
  - On `10006` after retries, signal the gate breaker (TASK-0.4) and emit a HIGH-severity audit log (R72).
  - The client carries its `account_id` (passed at construction from `accounts_service._build_client`) for `account_key`.
- **TDD:** test each method routes to the correct channel/endpoint_class/lane; test `_do_sync_time` is gated; regression test that existing call shapes are unchanged when kill-switches are off.
- **AC:** AC-003.

### TASK-0.6 — Runtime kill-switches (FR-009, FR-040 partial, R180)
- **Files:** `features.py`/`feature_flags.py`, `bybit_client.py`, `bybit_rate_gate.py`.
- **Notes:** Two DB-backed `feature_kill_switches` flags: `rate_gate_channel_fix` and `rate_gate_per_endpoint_limiter`. When OFF, the gate/client fall back EXACTLY to current behavior (all-private, no per-endpoint dim). Read hot (cached with short TTL) at the gate boundary.
- **TDD:** test flag OFF → byte-identical to current channel="private" behavior; test flag ON → new behavior.

### TASK-0.7 — Startup config validation (FR-049, AC-FIX-2/3)
- **Files:** `main.py` lifespan (after services wired).
- **Notes:** Compute worst-case 5s load: private peak = `max(sustained ≈ W_accounts × ceil(5 ÷ min_placement_latency) × ~10 private-calls, burst 10·N)`; fail-closed/clamp the configured max concurrency if private >80/5s OR combined-IP >480/5s. ALSO scan account configs for **duplicate `api_key`/credential** (two account_ids → one real UID → per-UID 10006 risk) and WARN + clamp (sum their per-endpoint budgets under one key). Operator-only; documented safe ranges.
- **TDD:** test a config exceeding the budget is clamped/rejected; test duplicate-credential detection warns.

---

## Verification (Phase 0)
1. `python -m pytest tests/backend/test_bybit_rate_gate.py tests/backend/test_bybit_client_channels.py -x -q` — all pass.
2. Run the existing Bybit-touching tests (accounts/reconciler/AI-manager) — no regression (NFR-010, steady-state): each still charges the correct channel.
3. Manual: with kill-switches OFF, diff gate behavior against a recorded baseline — identical.

## Completion criteria
- Public reads charge the public channel; per-`account_id`/endpoint caps enforced; `_do_sync_time` gated; ban-breaker releases locks + half-open recovery; `_wait_count` thread-safe; startup validation clamps unsafe configs; kill-switches revert to current behavior; existing flows unregressed.

## Rollback
- Flip `rate_gate_channel_fix` / `rate_gate_per_endpoint_limiter` OFF → gate reverts to current all-private behavior at runtime, no redeploy.

## Risks
- **Steady-state regression** (channel fix moves market reads private→public system-wide): mitigated by per-subsystem regression tests + kill-switch.
- **Gate becomes a serialization point:** the critical section stays O(1)/await-free; sleep outside the lock (NFR-006, R160).
