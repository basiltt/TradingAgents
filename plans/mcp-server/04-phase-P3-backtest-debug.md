# Phase P3 — Backtest + Debug Tools

**Goal:** Expose the backtesting subsystem and the debug forensics routes as MCP tools, and make the additive `BacktestService` changes the optimizer (P4) depends on: the `run_one` Protocol path + `source/sweep_id` tagging + a shared concurrency gate, plus the `bybit_rate_gate` subordinate lane.

**Entry:** P2 exit met.
**Exit:** backtest schema-equivalence test green; debug `allow_debug` gate test green; `run_one` parity test (metrics match the UI path incl. buy-hold); rate-gate default-lane equivalence test; BacktestService UI-slot equivalence test.

**Requirements:** FR-014/038/037, AC-016/018; §14.4/§15.6; R-10..13/235/242/243.

---

## K. Backend Implementation Plan

### Backtest tools (`backend/mcp/tools/backtest/`)
- TASK-P3-01: `backtest_run` — `@tool(group=BACKTEST, safety_class=BACKTEST, mutating=True)`; input schema **generated from `BacktestCreateRequest`** (import from `backend.schemas.backtest_schemas`, `model_json_schema()`); handler calls `ctx.services.backtest_service.create_backtest(body, client_id="mcp:<principal>")` (via `ctx.services`, never `app.state` directly — §F contract) → returns `run_id`. Money floats coerced `Decimal(str(x))` at persist.
- TASK-P3-02: `backtest_get` (status→result, fire-and-poll), `backtest_list`, `backtest_compare` (2..N runs, standard metrics).
- TASK-P3-03: `cache_status` / `cache_warmup` — kline cache coverage/warm via existing endpoints' service methods; writes the SAME store/keys as BacktestService (shared), with a coexistence quota protecting the live path.

### Debug tools (`backend/mcp/tools/debug/`)
- TASK-P3-04: `debug_scan_trace` / `debug_account_timeline` / `debug_symbol_decisions` / `debug_config_get` — `@tool(group=DEBUG, safety_class=READ_ONLY)`; gated behind `safe_mode_flags.allow_debug` (default OFF) — if off, the tool is not in `tools/list` AND denied at dispatch. Reuse `debug_trace_repository` reads; credential-shaped keys stripped; depth/size-capped.

### BacktestService additive changes (`backend/services/backtest_service.py`)
- TASK-P3-05: add `async def run_one(self, config, signals, snapshot, instrument_info, *, deadline) -> dict[str, Any]` — runs the engine against a PRE-LOADED snapshot (bypasses `_load_klines`/`_resolve_instrument_info`/buy-hold-fetch); replicates `_attach_buy_hold` from `snapshot["BTCUSDT"]` (None-on-missing) so metrics match the UI path — **the snapshot builder (P4 TASK-P4-03) MUST always include BTCUSDT even when no signal references it** (codebase note C-F18: real `_attach_buy_hold` fetches BTCUSDT via the kline cache). `BacktestService` is declared to satisfy the `BacktestRunner` Protocol in **`backend/mcp/core/runner.py`** (P0-owned); `FakeBacktestRunner` (conftest) implements it. Engine call maps `snapshot→klines` in the existing `engine.run(config, signals, klines, cancel_event, on_progress, instrument_info)` (verified `backtest_service.py:731`); `deadline` drives `cancel_event`.
- TASK-P3-06: add a SEPARATE asyncio sub-cap for sweep combos WITHOUT changing the UI admission race. **Keep `create_backtest`'s synchronous `_active_slots` int reservation exactly as-is** (the class comment `backtest_service.py:88-97` documents that a Semaphore acquired in the background task reopens a TOCTOU race — do NOT move admission to `await gate.acquire()`). The shared cap = the existing `_MAX_CONCURRENT` int admission; the sweep path additionally holds an `asyncio.Semaphore(sweep_sub_cap)` where `sweep_sub_cap < _MAX_CONCURRENT` so UI keeps reserved slots. **Burst test (backend-R1-F4):** N concurrent `create_backtest` calls in ONE loop tick never exceed `_MAX_CONCURRENT` (not just a steady-state count check).
- TASK-P3-07: `create_backtest` gains optional `source: str='ui'`, `sweep_id: UUID|None=None` params → tagged into the `backtest_runs` row (v44 columns). UI list/retention queries exclude `source='mcp_sweep'`. (Sweep combos do NOT create rows by default — P4; this is for the optional persist mode.)

### bybit_rate_gate additive lane (`backend/services/bybit_rate_gate.py`)
- TASK-P3-08: `acquire_async(channel, *, lane: str='live')` — new `lane` param **defaults to 'live'** (existing callers unchanged); MCP/sweep pass `lane='mcp'` (subordinate, reserved live floor); a 429/ban breaker halts the `mcp` lane first. Also add `lane='live'` to `acquire_sync` (`bybit_rate_gate.py:82`) IF any exchange-facing/order path uses it — confirm the live order/leverage path is async-only; add a test asserting the order path cannot acquire on `lane='mcp'` (backend-R1-F9). **Signature-compat test:** every existing caller (scanner/reconciler/order-placement) behavior-unchanged.

## L. Security (P3)
- `backtest_run`/`backtest_*` are `safety_class=BACKTEST` (require BACKTEST tier); debug gated by `allow_debug`; debug output redaction (credential strip + size cap); deny-list call-graph still holds (no tool reaches `update_scheduled_scan`/exchange order methods).

## M. Testing Plan (P3)
- Schema-equivalence (AC-016): `backtest_run` advertised schema == `BacktestCreateRequest.model_json_schema()`.
- `test_backtest_get` (AC-016, QA-R1-F7): created→running→completed status transition, fire-and-poll; `test_backtest_compare`: 2..N runs → full standard metric set.
- `run_one` parity: same config via the worker `_run_combo`/`run_one(snapshot)` and via `create_backtest` (UI path) → identical metrics (incl. buy-hold/excess-return); deterministic on seeded klines.
- Debug gate (AC-018): `allow_debug=false` → tool absent+denied; `=true` → redacted trace, depth-capped.
- Rate-gate default-lane equivalence (+ order-path-cannot-use-mcp-lane assertion); BacktestService UI-slot burst-equivalence (N concurrent create_backtest in one tick never exceed `_MAX_CONCURRENT`).
- Money: `Decimal(str(x))` round-trip lossless.

## N. Manual Verification (P3)
1. BACKTEST tier + `backtest_run` → run_id → `backtest_get` polls to result.
2. `backtest_compare` two runs → metric table.
3. Enable `allow_debug` → `debug_scan_trace` returns redacted forensics; disable → denied.

## O. Completion Criteria (P3)
All P3 tests green; existing backtest/debug suites unchanged; UI-slot + rate-gate equivalence green. Commit `feat(mcp): P3 backtest + debug tools, run_one, source tagging, rate-gate lane`.
