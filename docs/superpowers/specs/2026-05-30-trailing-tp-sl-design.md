# Dynamic Trailing TP/SL with Per-Symbol Fast Monitoring

**Date**: 2026-05-30
**Status**: Draft
**Feature Flag**: `trailing_enabled` (default: False)

## Problem

The AI Manager can only close or hold positions. When market conditions are strongly favorable, it cannot extend take-profit to let profits run, nor can it tighten stop-loss to protect unrealized gains. Positions either hit their original TP/SL (set at entry) or get manually closed by the AI Manager.

## Solution

A hybrid approach:
1. **LLM decides WHEN** to start trailing (during normal eval cycle)
2. **Deterministic rules compute HOW** (ATR-based SL trailing, factor-based TP extension)
3. **Per-symbol fast monitoring** (30s ticks) manages the trailing until momentum fades
4. **Periodic mini-LLM check** (every ~90s) re-assesses whether to keep/tighten/exit

## Architecture

### New Module: `backend/services/ai_manager_trailing.py`

A `TrailingState` class manages trailing for a single symbol. Each instance:
- Owns a 30s asyncio tick loop
- Computes SL/TP updates deterministically (ATR-based)
- Calls `bybit_client.set_trading_stop()` when values improve
- Runs a mini-LLM check every 3rd tick
- Self-terminates on momentum fade (ADX < threshold)

### Integration with AIManagerTask

```
AIManagerTask._active_trailing: Dict[str, TrailingState]

Flow:
  LLM returns ADJUST_TP_SL → _execute_action() branches to trailing path
  → Creates TrailingState (does NOT call close_positions_service)
  → TrailingState runs independently at 30s intervals
  → Main eval loop excludes trailing symbols from LLM evaluation
  → EventTriggerDetector suppresses triggers for trailing symbols
  → On exit: TrailingState removes itself, symbol returns to normal monitoring
```

### Execution Path Branching

Currently `_execute_action()` unconditionally calls `close_positions_service.close_all_for_rule()`.
The method must be bifurcated:

```python
async def _execute_action(self, result: dict) -> None:
    action_type = result.get("action", "HOLD")
    symbol = result.get("symbol", "")

    if action_type == "ADJUST_TP_SL":
        await self._start_trailing(symbol, result)
        return

    # Existing close logic (unchanged)
    ...
```

The `_start_trailing` method:
1. Records the decision (same as close path — insert_decision with HMAC)
2. Reads current position data from _ws_buffer
3. Gets ATR from MarketDataAggregator via `get_indicators(symbol)`
4. Creates TrailingState instance with all required params
5. Spawns its asyncio task and registers in `_active_trailing`

Budget: counts as 1 action (same as a close). Subsequent trailing ticks are free.

### High-Level Flow

```
Normal eval cycle (LLM):
  Position profitable + strong momentum detected
    → LLM returns action: ADJUST_TP_SL
    → AIManagerTask creates TrailingState for that symbol
    → TrailingState takes over fast monitoring

Fast cycle (deterministic, every 30s):
  1. Read mark price from position's `markPrice` field in WS buffer
  2. Get ATR(14) from MarketDataAggregator.get_indicators(symbol)
  3. Compute candidate_sl:
       Long:  max(current_sl, price - atr_multiplier × ATR)
       Short: min(current_sl, price + atr_multiplier × ATR)
  4. Compute candidate_tp:
       Long:  price + (price - candidate_sl) × tp_extension_factor
       Short: price - (candidate_sl - price) × tp_extension_factor
  5. If SL improved: call set_trading_stop(symbol, tp, sl, position_idx)
  6. Check ADX — if below threshold, exit fast-cycle

Mini-LLM check (every 3rd tick, ~90s):
  → Compact prompt with symbol state
  → Response: KEEP | TIGHTEN | EXIT
  → Can adjust ATR multiplier or signal termination

Exit condition:
  → ADX drops below threshold (default 20) → momentum faded
  → TrailingState self-terminates, symbol returns to normal monitoring
```

## New Action: ADJUST_TP_SL

### Alignment with Existing Schema

The `AIManagerAction` schema already defines:
```python
action_type: Literal["HOLD", "FULL_CLOSE", "PARTIAL_CLOSE", "ADJUST_TP", "ADJUST_SL"]
```

And `PositionAction` already has `new_tp`/`new_sl` fields.

We use `ADJUST_TP_SL` as the **combined** action in the runtime `_ALLOWED_ACTIONS` set (which is separate from the schema's Literal type). The schema's `AIManagerAction.action_type` Literal must be updated to include `"ADJUST_TP_SL"` as a new variant. The existing `ADJUST_TP`/`ADJUST_SL` remain for potential future single-adjustment use but are NOT used by this feature.

### Allowed Actions (updated)

```python
_ALLOWED_ACTIONS = frozenset({
    "CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL",
    "FULL_CLOSE", "PARTIAL_CLOSE", "REDUCE",
    "ADJUST_TP_SL"
})
```

### LLM Output Schema

```json
{
  "action": "ADJUST_TP_SL",
  "symbol": "BTCUSDT",
  "reason": "Strong bullish momentum with rising ADX and volume...",
  "confidence": 0.82,
  "params": {
    "atr_multiplier": 2.0,
    "tp_extension_factor": 1.5
  }
}
```

`params` is optional — defaults apply if omitted.

### LLM Prompt Changes

The current prompt (in `ai_manager_prompts.py` line 93) tells the LLM to choose between:
```
"HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE"
```

This must be updated to:
```
"HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE"|"ADJUST_TP_SL"
```

And the response format (line 141) updated from:
```
{"action": "HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE", "symbol": "...", ...}
```
To:
```
{"action": "HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE"|"ADJUST_TP_SL", "symbol": "...", ...}
```

A new section must be added to the system prompt explaining when to use ADJUST_TP_SL:

```
## When to ADJUST_TP_SL (trail take-profit and tighten stop-loss):
- Position is already profitable (unrealized PnL > 0)
- Momentum is strong: ADX > 25, price moving decisively in position's favor
- Volume supports the move (not a low-volume spike)
- Do NOT use when price is approaching known resistance (longs) or support (shorts)
- Do NOT use on positions with < 1% unrealized profit
- Include optional "params" with "atr_multiplier" (1.0-3.0) and "tp_extension_factor" (1.0-2.0)
```

### Mini-LLM Prompt Template

```
Symbol: {symbol} | Side: {side} | Entry: ${entry} | Current: ${price}
SL: ${sl} | TP: ${tp} | ATR: ${atr} | ADX: {adx} | Tick: {n}
Unrealized PnL: ${upnl}

Decision: KEEP (continue trailing) | TIGHTEN (reduce ATR multiplier to 1.5) | EXIT (stop trailing)
Reply with one word and a 10-word reason.
```

## Data Sources

| Data | Source | Cost |
|------|--------|------|
| Mark price | `pos.get("markPrice")` from WS buffer positions | Zero — already streaming |
| ATR(14) | `MarketDataAggregator.get_indicators(symbol)["atr_14"]` | Zero — already computed in existing 5-min kline refresh loop |
| ADX | Computed from same kline data in MarketDataAggregator | Zero — already derived |
| Position info | WS buffer `_ws_buffer["positions"]` | Zero — already streaming |
| Position side | `pos.get("side")` — "Buy" or "Sell" | Zero — in WS data |
| Position idx | `pos.get("positionIdx", 0)` — for hedge mode support | Zero — in WS data |

**No new API calls needed for the fast cycle.** The existing `MarketDataAggregator` fetches klines every 60s and computes ATR. The trailing module reads from the same cached data.

**Cold-start handling**: If `get_indicators(symbol)` returns no ATR (kline data not yet fetched for a newly-tracked symbol), `_start_trailing()` must do a synchronous kline fetch before spawning the trailing task. If this fetch fails, reject the ADJUST_TP_SL action and log a warning. On subsequent ticks, if ATR becomes None (cache evicted), skip that tick's SL/TP update and retry next tick.

## Hedge Mode Support

Bybit's `set_trading_stop` requires `position_idx`:
- `0` = one-way mode (default, most accounts)
- `1` = Buy side in hedge mode
- `2` = Sell side in hedge mode

`TrailingState` must store the `position_idx` from the position's WS data (`pos.get("positionIdx", 0)`) and pass it through to every `set_trading_stop` call. The `AIManagerTask` already tracks `self._is_hedge_mode` — this flag determines which `positionIdx` values to expect.

## Event Trigger Suppression

The `EventTriggerDetector.check_triggers()` evaluates ALL positions and can fire triggers for price moves, drawdowns, and PnL velocity. If a symbol is actively trailing:
- Its price movements are expected (trailing means price is moving)
- Firing triggers would cause the main eval loop to try evaluating a symbol that's excluded from LLM input — wasted computation

**Fix**: Before calling `check_triggers()`, filter out positions whose symbol is in `_active_trailing.keys()`. This is a one-line change in the monitoring cycle:

```python
positions_for_triggers = [
    p for p in positions
    if p.get("symbol") not in self._active_trailing
]
self._event_trigger.check_triggers(positions_for_triggers, ...)
```

## Safety Rules

| Rule | Implementation |
|------|---------------|
| SL never moves backwards | `max(current_sl, computed)` for longs, `min()` for shorts |
| Minimum SL = breakeven + fees | First tick ensures SL ≥ entry_price × 1.001 |
| TP must exceed current price | Reject TP behind mark price |
| Max one `set_trading_stop` per tick | Skip if SL/TP unchanged from last call |
| Position closed externally | Symbol disappears from WS → self-terminate |
| Position size reduced | Partial close does NOT terminate trailing (position still open, same SL/TP apply) |
| Emergency close overrides | `_check_emergency_close()` cancels all trailing before closing |
| Budget accounting | ADJUST_TP_SL = 1 action; trailing ticks are free |
| Token budget for mini-LLM | Small fixed cap (~500 output tokens); counts toward daily budget |
| Max concurrent trailing | Configurable limit (default 3) per account |
| One trailing per symbol | Reject ADJUST_TP_SL if symbol already trailing |
| Hedge mode safe | Pass `position_idx` from WS position data to all `set_trading_stop` calls |
| Stale data protection | If last WS position update for symbol is >90s old, skip tick (don't update SL/TP with stale prices) |
| ATR unavailable | If ATR is None on any tick, skip that tick's SL/TP computation |

## Conflict Prevention

- Symbols in `_active_trailing` are excluded from the position list sent to the main LLM graph
- Symbols in `_active_trailing` are excluded from `EventTriggerDetector.check_triggers()` input
- If user manually closes position on Bybit, WS update triggers trailing termination
- Only ONE `TrailingState` per symbol at a time
- Emergency close path cancels all active trailing states before closing
- Daily loss enforcement still runs on the account level — if daily loss cap is breached while trailing, the task pauses and all trailing states terminate

## Sweep Defense Interaction

The sweep defense system widens SL when a liquidity sweep is detected. This conflicts with trailing's "SL never moves backwards" invariant.

**Rules:**
1. **Risk validation rejects ADJUST_TP_SL if symbol is in `_sweep_blocked_symbols`** — explicit check, not relying on the generic sweep block (which only blocks closes). Log the rejection clearly.
2. **If a sweep is detected on a symbol that's already trailing**: The trailing state must yield — it pauses SL updates (skips `set_trading_stop` calls) and lets sweep defense take over. The trailing state enters a `suspended` sub-state.
3. **When sweep resolves on a suspended trailing state**: Trailing resumes, but resets `current_sl` to the CURRENT exchange SL value (query from the position's WS data or the last known `set_trading_stop` result). It does NOT restore a pre-sweep SL.
4. **If sweep defense actively widens SL**: This is allowed because the trailing state is suspended — it won't overwrite the widened SL.

**TrailingState sub-states:**
```
ACTIVE → normal trailing (computing + setting SL/TP)
SUSPENDED → sweep detected, paused SL updates, awaiting sweep resolution
```

## Close Rule Evaluator Interaction

The `CloseRuleEvaluator` is an independent background service that can close positions or modify TP/SL (e.g., BREAKEVEN_TIMEOUT rule). It operates without awareness of trailing state.

**Rules:**
1. **If a close rule fully closes a trailing symbol**: The WS position_update (size=0) triggers trailing termination. The ~1-30s gap between close and WS update is acceptable — `set_trading_stop` on a closed position returns an error which the trailing tick handles gracefully (log warning, self-terminate).
2. **If a close rule modifies TP/SL (e.g., BREAKEVEN_TIMEOUT)**: This creates a race. Resolution: **when trailing is active for a symbol, close rules that modify TP/SL are suppressed for that symbol**. Close rules that CLOSE the position still fire (safety takes priority).
3. **Implementation**: The `CloseRuleEvaluator` must check `_active_trailing` (via a shared reference or callback) before calling `set_trading_stop`. If symbol is trailing, skip the TP/SL modification rule and log it.

**Why close rules that close the position still fire**: A close rule represents a hard user-defined boundary (e.g., "close if loss > $50"). Trailing is advisory; user rules are authoritative.

## Exchange-Side SL Execution and Daily Loss Tracking

When a trailing SL is executed by Bybit's engine (not by the AI Manager), the position disappears from WS with a realized PnL. The current `_enforce_daily_limits()` is only called when the AI Manager initiates a close — exchange-side executions bypass it entirely.

**Fix — required for correctness:**
1. The WS position_update handler already detects when a position disappears (size goes to 0).
2. When a position disappears AND it was in `_active_trailing`, compute the approximate realized PnL: `last_known_mark_price - entry_price` × `position_size` (adjusted for side).
3. Feed this into `_enforce_daily_limits()` to update `realized_loss_today`.
4. If the loss breaches the daily cap, the task pauses (same as AI-initiated close path).

**Note**: This is an existing gap for ALL exchange-side SL executions, not just trailing. However, trailing makes it far more likely (the system is actively setting SLs that are closer to price). This feature MUST fix it for trailing symbols. Fixing it for all positions is recommended but can be a follow-up.

## Pause/Kill Trailing Cleanup

When `pause()` or `set_killed()` is called on the AIManagerTask:

1. **All entries in `_active_trailing` must be explicitly cancelled** — call `trailing_state.cancel()` for each.
2. `TrailingState.cancel()` sets an internal flag, the tick loop exits on next iteration, the asyncio task completes.
3. The `pause()` and `set_killed()` methods must be updated to include this cleanup BEFORE changing state.

**Implementation in `pause()`:**
```python
def pause(self) -> None:
    for ts in list(self._active_trailing.values()):
        ts.cancel()
    self._active_trailing.clear()
    self._state = PAUSED
    self._pause_event.set()
```

Similarly for `set_killed()`.

**TrailingState must check `_cancelled` flag at the start of each tick:**
```python
async def _tick(self):
    if self._cancelled:
        return  # exit loop
    ...
```

## Mini-LLM Failure Handling

The mini-LLM check runs every 3rd tick (~90s). Failure modes and responses:

| Failure | Response |
|---------|----------|
| Timeout (>15s) | Default to KEEP — continue trailing with current params |
| Parse failure (not KEEP/TIGHTEN/EXIT) | Default to KEEP |
| LLM service degraded (degradation tier ≥ 3) | Skip mini-LLM entirely, run purely deterministic (ADX exit only) |
| 3 consecutive failures | Disable mini-LLM for this trailing instance permanently, log warning |

**Mini-LLM timeout**: 15s (not 90s like main eval). Uses `asyncio.wait_for` with short timeout.

**Token budget**: Mini-LLM calls count toward daily token budget. If budget is exhausted, skip mini-LLM (same as degradation tier ≥ 3 behavior).

## Threading Model

`TrailingState` runs as an asyncio task in the **same event loop** as `AIManagerTask`. It reads `_ws_buffer` directly (shared reference).

**Safety guarantee**: In CPython asyncio, single-threaded execution means no true data races as long as no `await` interrupts a read-modify-write sequence. The WS handler's position update block has no awaits between read and write — verified safe.

**Rules for implementation:**
1. `TrailingState` MUST run in the same event loop (never `loop.run_in_executor`)
2. `TrailingState` reads `_ws_buffer.get("positions", [])` — list lookup is atomic in CPython
3. No locking needed, but add a comment documenting this invariant
4. If the WS handler is ever refactored to add awaits in the position update block, this must be revisited

## Risk Validation Gate

The existing `risk_validation` node currently checks: locked positions, symbol existence, cold-start confidence, sweep block, and correlation heat. It does NOT currently check profitability.

New checks to add for `ADJUST_TP_SL`:
- Position is not profitable (unrealized PnL ≤ 0) → **reject**
- `trailing_enabled` is False in config → **reject**
- Max concurrent trailing limit reached → **reject** (requires passing `active_trailing_count` into graph state)
- Symbol already has an active trailing state → **reject** (requires passing `active_trailing_symbols` into graph state)
- Symbol is in `_sweep_blocked_symbols` → **reject** (trailing and sweep defense conflict)
- Symbol has active close rules that modify TP/SL → **reject** (avoid race condition)
- Position unrealized profit < `trailing_min_profit_pct` → **reject**

**Implementation detail**: The graph state dict must be extended to include:
```python
state["trailing_count"] = len(self._active_trailing)
state["trailing_symbols"] = set(self._active_trailing.keys())
state["sweep_blocked_symbols"] = self._sweep_blocked_symbols
state["trailing_config"] = {
    "enabled": self._config.trailing_enabled,
    "max_concurrent": self._config.trailing_max_concurrent,
    "min_profit_pct": self._config.trailing_min_profit_pct,
}
```

This is injected at graph invocation time in `_evaluate()`, alongside the existing position/wallet data.

## Configuration

New fields in `AIManagerConfig`:

```python
trailing_enabled: bool = False
trailing_tick_interval_s: float = Field(default=30.0, ge=10.0, le=120.0)
trailing_mini_llm_every_n_ticks: int = Field(default=3, ge=2, le=10)
trailing_default_atr_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
trailing_default_tp_extension_factor: float = Field(default=1.5, ge=1.0, le=3.0)
trailing_adx_exit_threshold: float = Field(default=20.0, ge=10.0, le=35.0)
trailing_min_profit_pct: float = Field(default=1.0, ge=0.5, le=10.0)
trailing_max_concurrent: int = Field(default=3, ge=1, le=10)
trailing_atr_period: int = Field(default=14, ge=7, le=21)
trailing_kline_refresh_s: float = Field(default=300.0, ge=60.0, le=600.0)
```

Corresponding optional fields in `AIManagerConfigUpdate` (same types, all Optional with default None).

## Database Changes

None. Trailing state is ephemeral (in-memory). If the service restarts, trailing states are lost and symbols return to normal monitoring. The last-set SL/TP remains on Bybit's exchange side, so positions remain protected.

## Files to Create/Modify

| File | Action |
|------|--------|
| `backend/services/ai_manager_trailing.py` | **Create** — TrailingState class with tick loop, ATR computation, mini-LLM check, sweep suspension, cancel support, staleness detection |
| `backend/services/ai_manager_task.py` | Modify — add `ADJUST_TP_SL` to `_ALLOWED_ACTIONS`, bifurcate `_execute_action()`, add `_active_trailing` dict, add `_start_trailing()` method, filter trailing symbols from trigger checks, cancel trailing on emergency/pause/kill, pass trailing state into graph, handle exchange-side SL execution for trailing symbols in WS handler |
| `backend/ai_manager_schemas.py` | Modify — add `"ADJUST_TP_SL"` to `AIManagerAction.action_type` Literal, add trailing config fields to both `AIManagerConfig` and `AIManagerConfigUpdate` |
| `backend/services/ai_manager_graph.py` | Modify — add trailing-specific checks in `risk_validation` node, accept `trailing_count`/`trailing_symbols`/`sweep_blocked_symbols`/`trailing_config` in graph state |
| `backend/services/ai_manager_prompts.py` | Modify — add `ADJUST_TP_SL` as 4th action option, add "When to ADJUST_TP_SL" section, update response format |
| `backend/services/close_rule_evaluator.py` | Modify — check active trailing before calling `set_trading_stop` for TP/SL modification rules; suppress TP/SL mods on trailing symbols (close rules still fire) |
| `backend/services/bybit_client.py` | No change — `set_trading_stop()` already exists and supports `position_idx` |
| `tests/backend/test_ai_manager_trailing.py` | **Create** — unit tests for TrailingState (tick logic, SL-never-backwards, momentum fade exit, hedge mode position_idx, emergency cancel, sweep suspension/resume, staleness skip, mini-LLM failure defaults, pause cleanup) |

## Out of Scope

- Position size adjustments (scaling in/out)
- Modifying entry orders
- Trailing on positions opened by the AI Manager itself (applies to all open positions equally)
- Persistent trailing state across restarts
- Using `ADJUST_TP` or `ADJUST_SL` as separate single-field actions (future work)
