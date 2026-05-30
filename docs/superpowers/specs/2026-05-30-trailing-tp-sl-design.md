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

**No new API calls needed for the fast cycle.** The existing `MarketDataAggregator` already fetches klines and computes ATR on a 5-min refresh. The trailing module reads from the same cached data.

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
| Emergency close overrides | `_check_emergency_close()` cancels all trailing before closing |
| Budget accounting | ADJUST_TP_SL = 1 action; trailing ticks are free |
| Token budget for mini-LLM | Small fixed cap (~500 output tokens); counts toward daily budget |
| Max concurrent trailing | Configurable limit (default 3) per account |
| One trailing per symbol | Reject ADJUST_TP_SL if symbol already trailing |
| Hedge mode safe | Pass `position_idx` from WS position data to all `set_trading_stop` calls |

## Conflict Prevention

- Symbols in `_active_trailing` are excluded from the position list sent to the main LLM graph
- Symbols in `_active_trailing` are excluded from `EventTriggerDetector.check_triggers()` input
- If user manually closes position on Bybit, WS update triggers trailing termination
- Only ONE `TrailingState` per symbol at a time
- Emergency close path cancels all active trailing states before closing
- Daily loss enforcement still runs on the account level — if daily loss cap is breached while trailing, the task pauses and all trailing states terminate

## Risk Validation Gate

The existing `risk_validation` node currently checks: locked positions, symbol existence, cold-start confidence, sweep block, and correlation heat. It does NOT currently check profitability.

New checks to add for `ADJUST_TP_SL`:
- Position is not profitable (unrealized PnL ≤ 0) → **reject**
- `trailing_enabled` is False in config → **reject**
- Max concurrent trailing limit reached → **reject** (requires passing `active_trailing_count` into graph state)
- Symbol already has an active trailing state → **reject** (requires passing `active_trailing_symbols` into graph state)
- Position unrealized profit < `trailing_min_profit_pct` → **reject**

**Implementation detail**: The graph state dict must be extended to include:
```python
state["trailing_count"] = len(self._active_trailing)
state["trailing_symbols"] = set(self._active_trailing.keys())
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
| `backend/services/ai_manager_trailing.py` | **Create** — TrailingState class with tick loop, ATR computation, mini-LLM check |
| `backend/services/ai_manager_task.py` | Modify — add `ADJUST_TP_SL` to `_ALLOWED_ACTIONS`, bifurcate `_execute_action()`, add `_active_trailing` dict, add `_start_trailing()` method, filter trailing symbols from trigger checks, cancel trailing on emergency close, pass trailing state into graph |
| `backend/ai_manager_schemas.py` | Modify — add `"ADJUST_TP_SL"` to `AIManagerAction.action_type` Literal, add trailing config fields to both `AIManagerConfig` and `AIManagerConfigUpdate` |
| `backend/services/ai_manager_graph.py` | Modify — add trailing-specific checks in `risk_validation` node, accept `trailing_count`/`trailing_symbols`/`trailing_config` in graph state |
| `backend/services/ai_manager_prompts.py` | Modify — add `ADJUST_TP_SL` as 4th action option, add "When to ADJUST_TP_SL" section, update response format |
| `backend/services/bybit_client.py` | No change — `set_trading_stop()` already exists and supports `position_idx` |
| `tests/backend/test_ai_manager_trailing.py` | **Create** — unit tests for TrailingState (tick logic, SL-never-backwards, momentum fade exit, hedge mode position_idx, emergency cancel) |

## Out of Scope

- Position size adjustments (scaling in/out)
- Modifying entry orders
- Trailing on positions opened by the AI Manager itself (applies to all open positions equally)
- Persistent trailing state across restarts
- Using `ADJUST_TP` or `ADJUST_SL` as separate single-field actions (future work)
