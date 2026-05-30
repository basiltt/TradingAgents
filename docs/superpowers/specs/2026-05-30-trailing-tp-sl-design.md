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
  LLM returns ADJUST_TP_SL → _execute_action() creates TrailingState
  → TrailingState runs independently at 30s intervals
  → Main eval loop excludes trailing symbols from LLM evaluation
  → On exit: TrailingState removes itself, symbol returns to normal monitoring
```

### High-Level Flow

```
Normal eval cycle (LLM):
  Position profitable + strong momentum detected
    → LLM returns action: ADJUST_TP_SL
    → AIManagerTask creates TrailingState for that symbol
    → TrailingState takes over fast monitoring

Fast cycle (deterministic, every 30s):
  1. Read mark price from WS buffer (no API call)
  2. Get ATR(14) from cached kline data
  3. Compute candidate_sl:
       Long:  max(current_sl, price - atr_multiplier × ATR)
       Short: min(current_sl, price + atr_multiplier × ATR)
  4. Compute candidate_tp:
       Long:  price + (price - candidate_sl) × tp_extension_factor
       Short: price - (candidate_sl - price) × tp_extension_factor
  5. If SL improved: call set_trading_stop()
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

### When the LLM Should Recommend ADJUST_TP_SL (prompt guidance)

- Position is already profitable (unrealized PnL > 0)
- Momentum is strong: ADX > 25, price moving in position's favor
- Volume supports the move (not a thin spike)
- NOT when approaching known resistance/support

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
| Mark price | WS buffer (`_ws_buffer["positions"]`) | Zero — already streaming |
| ATR(14) | Kline endpoint, cached, refreshed every 5 min | 1 API call per 5 min per symbol |
| ADX | Computed from same kline data | Zero — derived |
| Position info | WS buffer | Zero — already streaming |

## Safety Rules

| Rule | Implementation |
|------|---------------|
| SL never moves backwards | `max(current_sl, computed)` for longs, `min()` for shorts |
| Minimum SL = breakeven + fees | First tick ensures SL ≥ entry_price × 1.001 |
| TP must exceed current price | Reject TP behind mark price |
| Max one `set_trading_stop` per tick | Skip if SL/TP unchanged from last call |
| Position closed externally | Symbol disappears from WS → self-terminate |
| Emergency close overrides | `_check_emergency_close()` cancels trailing before closing |
| Budget accounting | ADJUST_TP_SL = 1 action; trailing ticks are free |
| Token budget for mini-LLM | Small fixed cap (~500 output tokens); counts toward daily budget |
| Max concurrent trailing | Configurable limit (default 3) per account |
| One trailing per symbol | Reject ADJUST_TP_SL if symbol already trailing |

## Conflict Prevention

- Symbols in `_active_trailing` are excluded from the position list sent to the main LLM graph
- If user manually closes position on Bybit, WS update triggers trailing termination
- Only ONE `TrailingState` per symbol at a time
- Emergency close path cancels all active trailing states before closing

## Risk Validation Gate

The existing `risk_validation` node in the LangGraph rejects `ADJUST_TP_SL` if:
- Position is not profitable (unrealized PnL ≤ 0)
- `trailing_enabled` is False in config
- Max concurrent trailing limit reached
- Symbol already has an active trailing state
- Position unrealized profit < `trailing_min_profit_pct`

## Configuration

New fields in `AIManagerConfig`:

```python
trailing_enabled: bool = False
trailing_tick_interval_s: float = 30.0
trailing_mini_llm_every_n_ticks: int = 3
trailing_default_atr_multiplier: float = 2.0
trailing_default_tp_extension_factor: float = 1.5
trailing_adx_exit_threshold: float = 20.0
trailing_min_profit_pct: float = 1.0
trailing_max_concurrent: int = 3
trailing_atr_period: int = 14
trailing_kline_refresh_s: float = 300.0
```

## Database Changes

None. Trailing state is ephemeral (in-memory). If the service restarts, trailing states are lost and symbols return to normal monitoring. The last-set SL/TP remains on Bybit's exchange side, so positions remain protected.

## Files to Create/Modify

| File | Action |
|------|--------|
| `backend/services/ai_manager_trailing.py` | **Create** — TrailingState class |
| `backend/services/ai_manager_task.py` | Modify — add ADJUST_TP_SL to allowed actions, integrate TrailingState lifecycle |
| `backend/ai_manager_schemas.py` | Modify — add trailing config fields |
| `backend/services/ai_manager_graph.py` | Modify — allow ADJUST_TP_SL through action generation |
| `backend/services/ai_manager_prompts.py` | Modify — add ADJUST_TP_SL to LLM prompt instructions |
| `backend/services/bybit_client.py` | No change — `set_trading_stop()` already exists |
| `tests/backend/test_ai_manager_trailing.py` | **Create** — unit tests for trailing logic |

## Out of Scope

- Position size adjustments (scaling in/out)
- Modifying entry orders
- Trailing on positions opened by the AI Manager itself (applies to all open positions equally)
- Persistent trailing state across restarts
