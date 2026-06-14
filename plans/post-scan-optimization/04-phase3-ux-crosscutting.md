# Phase 3 — UX Polish + Cross-Cutting + Release Gate

**Goal:** Polish the live panel and Progress tab, surface rate-limit/ban state clearly, add the regression detectors + benchmarks, and assemble the Definition-of-Done release gate.

**Requirements:** FR-041, FR-042, FR-045, FR-046, FR-049 (operator docs), NFR-001, NFR-008, NFR-011, R79-R80, R82, R84, R88, R90, R195, R119, R163, R185, R186, R196, AC-FIX-4/6.
**Depends on:** Phases 0-2.

---

## Files
| File | Action | Purpose |
|---|---|---|
| `frontend/src/components/scanner/PostScanExecutionPanel.tsx` | Modify | Status colors, skip-reason transparency, DRY-RUN/LIVE badge, ban-cooloff state |
| `backend/routers/admin.py` | Modify | Operator-control trust boundary (TCP-peer loopback + token + XFF); audit principal |
| `backend/routers/ws.py` | Modify | (referenced) exact-origin note for the new endpoint already in Phase 1 |
| `backend/services/bybit_rate_gate.py` | Modify | Near-ban detector hook (emit `rate_wait`/ban substatus) |
| `backend/services/scan_progress_manager.py` | Modify | Carry `reason_code`/`cooloff_seconds`/ban substatus |
| `tests/backend/test_post_scan_benchmark.py` | Create | Speedup benchmark + zero-10006 + detectors |
| `tests/backend/test_rate_regression.py` | Create | Steady-state non-tail-flow regression |
| `plans/post-scan-optimization/TRACEABILITY.md` | Create | Req→Task→File→Test→AC matrix |

---

## Tasks

### TASK-3.1 — Panel polish (FR-041, FR-042, R79/R80/R84/R88/R90)
- **Notes:** Semantic status colors (green=placed/red=failed/amber=skipped/grey=pending/accent=running-waiting) consistent across stepper/badges/rows; every skip names its `reason_code` (via the frontend enum map); per-order side/symbol shown; DRY-RUN vs LIVE badge on the panel; distinct in-progress/completed/failed/cancelled headers. Reuse native primitives only.
- **TDD (component):** skip rows show reason; DRY/LIVE badge; color semantics.

### TASK-3.2 — Ban-cooloff vs throttle distinction (FR-042, R195, AC-FIX-5)
- **Notes:** A muted "Waiting on rate limit…" slow-pulse for a micro-throttle (neutral/accent), DISTINCT from a "Trading paused ~Nm — rate-limit cooloff" state with an `X-Bapi-Limit-Reset`/`cooloff_seconds` countdown for a confirmed ban (so a user doesn't force-kill a banned run and extend it). Driven by the gate's near-ban/ban substatus emitted through the progress event.
- **TDD:** throttle vs ban render distinctly; countdown ticks.

### TASK-3.3 — Operator-control trust boundary (FR-046, HR-5, D14, AC-FIX-4)
- **Notes:** `admin.py` (and the runtime concurrency-override + kill-switch endpoints): gate on **TCP peer = loopback** (independent of bind) + a shared token for the ban-inducing width-override; trust `X-Forwarded-For` only from an allow-listed proxy IP; principal is transport/token-derived (deprecate-but-accept body `updated_by`); audit + alert every flip; fail-closed if served on a public bind without the token. **Scope:** loopback-peer gate = MUST; the shared token MAY be SHOULD for first ship (default width=1 makes the override inert) — confirm in plan-validation.
- **TDD:** non-loopback peer without token rejected; loopback peer allowed; audit entry has transport principal not body.

### TASK-3.4 — Payload scrub + secrets (FR-045, FR-119, R119)
- **Notes:** Confirm the emitted event allow-list carries NO keys/secrets/headers/balances/raw-error-strings/labels (free-text omitted in Phase 1); the per-scan account handle is salted; any persisted reason/error rendered as TEXT not HTML.
- **TDD:** emitted payload scrub assertion; salted handle not stable cross-scan.

### TASK-3.5 — Regression detectors (NFR-008, R186)
- **Notes:** (a) duplicate-placement invariant monitor: alert when >1 order for the same `(account_id, symbol, cycle)` or placements exceed `max_trades` across the fan-out; (b) near-ban early-warning when `X-Bapi-Limit-Status` headroom < threshold, BEFORE a 10006. Structured per-account/per-stage timing logs keyed by `scan_id`+`account_id`.
- **TDD:** duplicate-placement monitor fires on a seeded dup; near-ban fires under synthetic saturation before any 10006.

### TASK-3.6 — Speedup benchmark + zero-10006 (NFR-001, NFR-002, R151, R196)
- **Notes:** With the TASK-2.1 mock + configurable latency + worst-case fill (7 polls): measure full-tail wall-clock at N=5/10/20, sequential (width=1) vs parallel (width=2). Assert **parallel < sequential at EACH N** (RTT-overlap), curve flattens past the private-cap plateau (NOT monotonic-in-N), and **zero `10006`** (the rate-aware mock would emit one if the gate under-throttled). Capture per-stage wall-clock to co-prove golden-equality unchanged.
- **TDD:** benchmark asserts speedup-vs-same-N + zero-10006.

### TASK-3.7 — Steady-state non-tail regression (NFR-010, R185, R163)
- **Notes:** Per-subsystem tests that after the channel fix + per-endpoint limiter, the accounts dashboard, `position_reconciler`, `close_rule_evaluator`, `trading_cycle_engine`, AI-manager, and the MCP lane each still charge the correct channel with no new throttle/latency/ban-risk; MCP lane neither starved by nor starving the order tail.
- **TDD:** each subsystem's gate usage unchanged-or-correct; MCP non-starvation.

### TASK-3.8 — Definition-of-Done gate + operator docs (R196, FR-049, R149-note)
- **Notes:** A documented checklist (the DoD in `00-plan-summary.md` §F) that MUST be green before flipping width>1 in prod: golden-equality, speedup benchmark + zero-10006, `=1` byte-identical, orphan-safety, both-call-sites, detectors live. Brief operator notes (not a full runbook — R149 deferred): how to flip kill-switches, tune width, read ban/throttle state.

### TASK-3.9 — Traceability matrix (Step 16 prep)
- **Notes:** `TRACEABILITY.md` mapping every MUST requirement → Task → Files → Test → AC → Verification.

---

## Verification (Phase 3)
1. `python -m pytest tests/backend/test_post_scan_benchmark.py tests/backend/test_rate_regression.py -x -q`.
2. `cd frontend && npx tsc --noEmit && npm run build`.
3. Manual: trigger a throttle (low width + many accounts) → "waiting" indicator; simulate a ban → distinct cooloff state; verify operator kill-switch flips at runtime.

## Completion criteria
- Panel polished + ban/throttle distinct; operator controls trust-bounded + audited; payloads scrubbed; detectors live; benchmark proves speedup + zero-10006; steady-state regression green; DoD gate assembled.

## Rollback
- Phase 3 is additive polish + tests; reverting the panel changes restores the Phase-1 panel. The DoD gate governs the width>1 flip (default stays width=1).
