# Dynamic Trailing TP/SL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the AI Manager to dynamically adjust TP/SL on profitable positions with strong momentum, using ATR-based trailing with per-symbol fast monitoring cycles.

**Architecture:** New `TrailingState` class in a separate module handles the 30s tick loop. `AIManagerTask` branches execution for `ADJUST_TP_SL` actions, creating trailing instances. The LangGraph risk validation gate enforces profitability and concurrency checks. Close rules yield to trailing; sweep defense suspends it.

**Tech Stack:** Python 3.11+, asyncio, Pydantic, Bybit REST API (`set_trading_stop`), existing MarketDataAggregator for ATR/ADX.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/services/ai_manager_trailing.py` | TrailingState class — tick loop, ATR SL computation, mini-LLM checks, sweep suspension |
| `backend/ai_manager_schemas.py` | Config fields + schema literal update |
| `backend/services/ai_manager_prompts.py` | LLM prompt: 4th action option |
| `backend/services/ai_manager_graph.py` | Risk validation: trailing-specific rejections |
| `backend/services/ai_manager_task.py` | Integration: execution branching, lifecycle, trigger suppression, pause/kill cleanup |
| `backend/services/close_rule_evaluator.py` | Suppress TP/SL mods on trailing symbols |
| `tests/backend/test_ai_manager_trailing.py` | Unit tests for TrailingState |

---

### Task 1: Schema Updates

**Files:**
- Modify: `backend/ai_manager_schemas.py:12-59` (AIManagerConfig), `backend/ai_manager_schemas.py:70-77` (AIManagerAction)

- [ ] **Step 1: Add trailing config fields to AIManagerConfig**

Add after line 59 (`event_rapid_cycle_debounce_s`):

```python
    # Trailing TP/SL (dynamic trailing for profitable positions)
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

- [ ] **Step 2: Add ADJUST_TP_SL to AIManagerAction.action_type Literal**

Change line 71-73 from:
```python
    action_type: Literal[
        "HOLD", "FULL_CLOSE", "PARTIAL_CLOSE", "ADJUST_TP", "ADJUST_SL"
    ]
```
To:
```python
    action_type: Literal[
        "HOLD", "FULL_CLOSE", "PARTIAL_CLOSE", "ADJUST_TP", "ADJUST_SL", "ADJUST_TP_SL"
    ]
```

- [ ] **Step 3: Add trailing fields to AIManagerConfigUpdate**

Find the `AIManagerConfigUpdate` class and add corresponding Optional fields:
```python
    trailing_enabled: Optional[bool] = None
    trailing_tick_interval_s: Optional[float] = Field(default=None, ge=10.0, le=120.0)
    trailing_mini_llm_every_n_ticks: Optional[int] = Field(default=None, ge=2, le=10)
    trailing_default_atr_multiplier: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    trailing_default_tp_extension_factor: Optional[float] = Field(default=None, ge=1.0, le=3.0)
    trailing_adx_exit_threshold: Optional[float] = Field(default=None, ge=10.0, le=35.0)
    trailing_min_profit_pct: Optional[float] = Field(default=None, ge=0.5, le=10.0)
    trailing_max_concurrent: Optional[int] = Field(default=None, ge=1, le=10)
    trailing_atr_period: Optional[int] = Field(default=None, ge=7, le=21)
    trailing_kline_refresh_s: Optional[float] = Field(default=None, ge=60.0, le=600.0)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/backend/test_ai_manager_router.py -v -x`
Expected: PASS (no breaking changes — new fields have defaults)

- [ ] **Step 5: Commit**

```bash
git add backend/ai_manager_schemas.py
git commit -m "feat(trailing): add ADJUST_TP_SL schema and config fields"
```

---

### Task 2: LLM Prompt Changes

**Files:**
- Modify: `backend/services/ai_manager_prompts.py:81-147`

- [ ] **Step 1: Add ADJUST_TP_SL to the decision framework**

In `build_system_prompt()`, change line 93 from:
```python
        "Evaluate each open position and decide: HOLD, FULL_CLOSE, or PARTIAL_CLOSE.\n\n"
```
To:
```python
        "Evaluate each open position and decide: HOLD, FULL_CLOSE, PARTIAL_CLOSE, or ADJUST_TP_SL.\n\n"
```

- [ ] **Step 2: Add "When to ADJUST_TP_SL" section**

Insert before the `"## Key Principles:"` section (before line 110):
```python
        "## When to ADJUST_TP_SL (trail take-profit and tighten stop-loss):\n"
        "- Position is already profitable (unrealized PnL > 0, at least 1% of entry)\n"
        "- Momentum is strong: ADX > 25, price moving decisively in position's favor\n"
        "- Volume supports the move (not a low-volume spike)\n"
        "- Do NOT use when price is approaching known resistance (longs) or support (shorts)\n"
        "- This EXTENDS TP and TIGHTENS SL simultaneously — letting profits run while locking gains\n"
        "- Include optional params: atr_multiplier (1.0-3.0), tp_extension_factor (1.0-2.0)\n\n"
```

- [ ] **Step 3: Update the response format JSON**

Change lines 140-144 from:
```python
        "\nRespond ONLY with valid JSON:\n"
        '{"action": "HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE", '
        '"symbol": "<symbol or empty for HOLD>", '
        '"confidence": <0.0-1.0>, '
        '"reason": "<brief explanation>"}\n'
```
To:
```python
        "\nRespond ONLY with valid JSON:\n"
        '{"action": "HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE"|"ADJUST_TP_SL", '
        '"symbol": "<symbol or empty for HOLD>", '
        '"confidence": <0.0-1.0>, '
        '"reason": "<brief explanation>", '
        '"params": {"atr_multiplier": <1.0-3.0>, "tp_extension_factor": <1.0-2.0>}}\n'
        "(params field is optional, only for ADJUST_TP_SL)\n"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/backend/ -k "prompt" -v -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_manager_prompts.py
git commit -m "feat(trailing): add ADJUST_TP_SL to LLM prompt options"
```

---

### Task 3: Risk Validation Gate

**Files:**
- Modify: `backend/services/ai_manager_graph.py:326-381`

- [ ] **Step 1: Add trailing-specific validation in risk_validation_node**

Insert after the sweep block check (after line 372, before the correlation check at line 374):

```python
    # Trailing-specific validation
    action = state.get("action", "HOLD")
    if action == "ADJUST_TP_SL":
        trailing_config = state.get("trailing_config") or {}
        if not trailing_config.get("enabled"):
            state["_risk_rejected"] = True
            state["action"] = "HOLD"
            state["reason"] = "trailing_disabled"
            return state

        trailing_symbols = state.get("trailing_symbols") or set()
        if symbol in trailing_symbols:
            state["_risk_rejected"] = True
            state["action"] = "HOLD"
            state["reason"] = f"already_trailing: {symbol}"
            return state

        trailing_count = state.get("trailing_count", 0)
        max_concurrent = trailing_config.get("max_concurrent", 3)
        if trailing_count >= max_concurrent:
            state["_risk_rejected"] = True
            state["action"] = "HOLD"
            state["reason"] = "trailing_max_concurrent_reached"
            return state

        # Profitability check
        min_profit_pct = trailing_config.get("min_profit_pct", 1.0)
        target_pos = next((p for p in positions if p.get("symbol") == symbol), None)
        if target_pos:
            try:
                upnl = float(target_pos.get("unrealisedPnl", target_pos.get("unrealized_pnl", 0)))
                entry = float(target_pos.get("avgPrice", target_pos.get("entryPrice", 0)))
                size = float(target_pos.get("size", 0))
                position_value = entry * size if entry and size else 0
                profit_pct = (upnl / position_value * 100) if position_value > 0 else 0
                if profit_pct < min_profit_pct:
                    state["_risk_rejected"] = True
                    state["action"] = "HOLD"
                    state["reason"] = f"insufficient_profit: {profit_pct:.1f}% < {min_profit_pct}%"
                    return state
            except (TypeError, ValueError):
                state["_risk_rejected"] = True
                state["action"] = "HOLD"
                state["reason"] = "trailing_profit_check_failed"
                return state
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/backend/ -k "graph" -v -x`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_manager_graph.py
git commit -m "feat(trailing): add risk validation checks for ADJUST_TP_SL"
```

---

### Task 4: TrailingState Module (Core)

**Files:**
- Create: `backend/services/ai_manager_trailing.py`
- Create: `tests/backend/test_ai_manager_trailing.py`

- [ ] **Step 1: Write failing tests for TrailingState core logic**

Create `tests/backend/test_ai_manager_trailing.py`:

```python
"""Unit tests for TrailingState."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.ai_manager_trailing import TrailingState, TrailingParams


class TestTrailingParams:
    def test_defaults(self):
        p = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0)
        assert p.atr_multiplier == 2.0
        assert p.tp_extension_factor == 1.5
        assert p.adx_exit_threshold == 20.0


class TestSLComputation:
    def test_long_sl_never_moves_backwards(self):
        state = TrailingState._compute_new_sl(
            side="Buy", current_sl=105.0, price=110.0, atr=2.0, atr_multiplier=2.0
        )
        # price - 2*2 = 106. 106 > 105 → moves up
        assert state == 106.0

    def test_long_sl_stays_when_price_drops(self):
        state = TrailingState._compute_new_sl(
            side="Buy", current_sl=106.0, price=107.0, atr=2.0, atr_multiplier=2.0
        )
        # price - 2*2 = 103. 103 < 106 → stays at 106
        assert state == 106.0

    def test_short_sl_never_moves_backwards(self):
        state = TrailingState._compute_new_sl(
            side="Sell", current_sl=95.0, price=90.0, atr=2.0, atr_multiplier=2.0
        )
        # price + 2*2 = 94. 94 < 95 → moves down
        assert state == 94.0

    def test_short_sl_stays_when_price_rises(self):
        state = TrailingState._compute_new_sl(
            side="Sell", current_sl=94.0, price=93.0, atr=2.0, atr_multiplier=2.0
        )
        # price + 2*2 = 97. 97 > 94 → stays at 94
        assert state == 94.0


class TestTPComputation:
    def test_long_tp_extends(self):
        tp = TrailingState._compute_new_tp(
            side="Buy", price=110.0, sl=106.0, tp_extension_factor=1.5
        )
        # price + (price - sl) * factor = 110 + 4*1.5 = 116
        assert tp == 116.0

    def test_short_tp_extends(self):
        tp = TrailingState._compute_new_tp(
            side="Sell", price=90.0, sl=94.0, tp_extension_factor=1.5
        )
        # price - (sl - price) * factor = 90 - 4*1.5 = 84
        assert tp == 84.0


class TestBreakevenGuard:
    def test_long_sl_minimum_is_breakeven(self):
        sl = TrailingState._enforce_breakeven_minimum(
            side="Buy", entry_price=100.0, candidate_sl=99.0
        )
        # Must be at least entry * 1.001 = 100.1
        assert sl == 100.1

    def test_short_sl_minimum_is_breakeven(self):
        sl = TrailingState._enforce_breakeven_minimum(
            side="Sell", entry_price=100.0, candidate_sl=101.0
        )
        # Must be at most entry * 0.999 = 99.9
        assert sl == 99.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/backend/test_ai_manager_trailing.py -v -x`
Expected: FAIL (module not found)

- [ ] **Step 3: Create TrailingState module**

Create `backend/services/ai_manager_trailing.py`:

```python
"""Per-symbol trailing TP/SL manager.

Handles the 30s fast-cycle tick loop for symbols where the LLM has decided
to trail TP/SL. Uses ATR-based SL computation and periodic mini-LLM checks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    from backend.services.bybit_client import BybitClient

logger = logging.getLogger(__name__)


@dataclass
class TrailingParams:
    symbol: str
    side: str  # "Buy" or "Sell"
    entry_price: float
    position_idx: int = 0
    atr_multiplier: float = 2.0
    tp_extension_factor: float = 1.5
    adx_exit_threshold: float = 20.0
    tick_interval_s: float = 30.0
    mini_llm_every_n_ticks: int = 3
    staleness_threshold_s: float = 90.0


class TrailingState:
    """Manages trailing TP/SL for a single symbol."""

    def __init__(
        self,
        params: TrailingParams,
        initial_sl: float,
        initial_tp: float,
        initial_atr: float,
        ws_buffer: Dict[str, Any],
        get_indicators_fn: Callable[[str], Dict[str, Any]],
        bybit_client: "BybitClient",
        mini_llm_fn: Optional[Callable] = None,
        on_done: Optional[Callable[[str], None]] = None,
    ):
        self._params = params
        self._current_sl = initial_sl
        self._current_tp = initial_tp
        self._last_atr = initial_atr
        self._ws_buffer = ws_buffer
        self._get_indicators = get_indicators_fn
        self._client = bybit_client
        self._mini_llm_fn = mini_llm_fn
        self._on_done = on_done

        self._tick_count = 0
        self._cancelled = False
        self._suspended = False  # sweep defense suspension
        self._mini_llm_failures = 0
        self._task: Optional[asyncio.Task] = None
        self._last_set_sl: Optional[float] = None
        self._last_set_tp: Optional[float] = None
        self._log = logging.getLogger(f"trailing.{params.symbol}")

    @property
    def symbol(self) -> str:
        return self._params.symbol

    @property
    def is_active(self) -> bool:
        return not self._cancelled and self._task is not None and not self._task.done()

    def start(self) -> None:
        self._task = asyncio.create_task(
            self._run_loop(), name=f"trailing-{self._params.symbol}"
        )

    def cancel(self) -> None:
        self._cancelled = True
        if self._task and not self._task.done():
            self._task.cancel()

    def suspend(self) -> None:
        self._suspended = True
        self._log.info("Suspended (sweep defense active)")

    def resume_from_sweep(self, current_exchange_sl: float) -> None:
        self._suspended = False
        self._current_sl = current_exchange_sl
        self._log.info("Resumed from sweep, SL reset to %.6f", current_exchange_sl)

    async def _run_loop(self) -> None:
        try:
            while not self._cancelled:
                await asyncio.sleep(self._params.tick_interval_s)
                if self._cancelled:
                    break
                await self._tick()
        except asyncio.CancelledError:
            pass
        except Exception:
            self._log.exception("Trailing loop crashed")
        finally:
            if self._on_done:
                self._on_done(self._params.symbol)

    async def _tick(self) -> None:
        if self._suspended:
            return

        self._tick_count += 1

        # Check position still exists
        position = self._find_position()
        if position is None:
            self._log.info("Position closed, terminating trailing")
            self._cancelled = True
            return

        # Staleness check
        pos_updated_at = position.get("_ws_updated_at", 0.0)
        if pos_updated_at and (time.time() - pos_updated_at) > self._params.staleness_threshold_s:
            self._log.warning("Stale WS data (%.0fs old), skipping tick", time.time() - pos_updated_at)
            return

        # Get current price and ATR
        price = self._get_mark_price(position)
        if price is None or price <= 0:
            return

        indicators = self._get_indicators(self._params.symbol)
        atr = indicators.get("atr_14")
        adx = indicators.get("adx_14")

        if atr is None or atr <= 0:
            self._log.debug("ATR unavailable, skipping tick")
            return
        self._last_atr = atr

        # Check ADX exit condition
        if adx is not None and adx < self._params.adx_exit_threshold:
            self._log.info("Momentum faded (ADX=%.1f < %.1f), exiting", adx, self._params.adx_exit_threshold)
            self._cancelled = True
            return

        # Compute new SL/TP
        new_sl = self._compute_new_sl(
            self._params.side, self._current_sl, price, atr, self._params.atr_multiplier
        )
        new_sl = self._enforce_breakeven_minimum(
            self._params.side, self._params.entry_price, new_sl
        )
        new_tp = self._compute_new_tp(
            self._params.side, price, new_sl, self._params.tp_extension_factor
        )

        # Only call API if values changed
        sl_changed = new_sl != self._last_set_sl
        tp_changed = new_tp != self._last_set_tp
        if sl_changed or tp_changed:
            try:
                await self._client.set_trading_stop(
                    symbol=self._params.symbol,
                    stop_loss=str(new_sl) if sl_changed else None,
                    take_profit=str(new_tp) if tp_changed else None,
                    position_idx=self._params.position_idx,
                )
                self._current_sl = new_sl
                self._current_tp = new_tp
                self._last_set_sl = new_sl
                self._last_set_tp = new_tp
                self._log.debug("Updated SL=%.6f TP=%.6f", new_sl, new_tp)
            except Exception:
                self._log.warning("set_trading_stop failed, will retry next tick")

        # Mini-LLM check
        if (
            self._tick_count % self._params.mini_llm_every_n_ticks == 0
            and self._mini_llm_fn
            and self._mini_llm_failures < 3
        ):
            await self._run_mini_llm(price, atr, adx)

    async def _run_mini_llm(self, price: float, atr: float, adx: Optional[float]) -> None:
        try:
            decision = await asyncio.wait_for(
                self._mini_llm_fn(
                    symbol=self._params.symbol,
                    side=self._params.side,
                    entry=self._params.entry_price,
                    price=price,
                    sl=self._current_sl,
                    tp=self._current_tp,
                    atr=atr,
                    adx=adx or 0.0,
                    tick=self._tick_count,
                ),
                timeout=15.0,
            )
            decision = (decision or "").strip().upper()
            if decision.startswith("EXIT"):
                self._log.info("Mini-LLM says EXIT")
                self._cancelled = True
            elif decision.startswith("TIGHTEN"):
                self._params.atr_multiplier = max(1.0, self._params.atr_multiplier * 0.75)
                self._log.info("Mini-LLM says TIGHTEN, multiplier=%.2f", self._params.atr_multiplier)
            # KEEP = do nothing
            self._mini_llm_failures = 0
        except (asyncio.TimeoutError, Exception):
            self._mini_llm_failures += 1
            self._log.debug("Mini-LLM failed (%d/3)", self._mini_llm_failures)

    def _find_position(self) -> Optional[Dict[str, Any]]:
        positions = self._ws_buffer.get("positions") or []
        for p in positions:
            if p.get("symbol") == self._params.symbol:
                return p
        return None

    def _get_mark_price(self, position: Dict[str, Any]) -> Optional[float]:
        try:
            return float(position.get("markPrice", position.get("mark_price", 0)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _compute_new_sl(side: str, current_sl: float, price: float, atr: float, atr_multiplier: float) -> float:
        if side == "Buy":
            candidate = price - (atr_multiplier * atr)
            return max(current_sl, candidate)
        else:
            candidate = price + (atr_multiplier * atr)
            return min(current_sl, candidate)

    @staticmethod
    def _compute_new_tp(side: str, price: float, sl: float, tp_extension_factor: float) -> float:
        if side == "Buy":
            distance = price - sl
            return price + (distance * tp_extension_factor)
        else:
            distance = sl - price
            return price - (distance * tp_extension_factor)

    @staticmethod
    def _enforce_breakeven_minimum(side: str, entry_price: float, candidate_sl: float) -> float:
        if side == "Buy":
            minimum = entry_price * 1.001
            return max(candidate_sl, minimum)
        else:
            maximum = entry_price * 0.999
            return min(candidate_sl, maximum)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/backend/test_ai_manager_trailing.py -v -x`
Expected: PASS

- [ ] **Step 5: Add lifecycle tests**

Append to `tests/backend/test_ai_manager_trailing.py`:

```python
class TestTrailingLifecycle:
    @pytest.mark.asyncio
    async def test_cancel_stops_loop(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0, tick_interval_s=0.1)
        done_called = []
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "105"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            bybit_client=AsyncMock(),
            on_done=lambda s: done_called.append(s),
        )
        ts.start()
        await asyncio.sleep(0.05)
        ts.cancel()
        await asyncio.sleep(0.2)
        assert not ts.is_active
        assert done_called == ["BTCUSDT"]

    @pytest.mark.asyncio
    async def test_position_gone_terminates(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0, tick_interval_s=0.1)
        ws = {"positions": []}  # no position
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer=ws,
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            bybit_client=AsyncMock(),
        )
        ts.start()
        await asyncio.sleep(0.25)
        assert not ts.is_active

    @pytest.mark.asyncio
    async def test_suspend_skips_ticks(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0, tick_interval_s=0.1)
        client = AsyncMock()
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "115"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 30.0},
            bybit_client=client,
        )
        ts.start()
        ts.suspend()
        await asyncio.sleep(0.25)
        client.set_trading_stop.assert_not_called()
        ts.cancel()

    @pytest.mark.asyncio
    async def test_adx_below_threshold_exits(self):
        params = TrailingParams(symbol="BTCUSDT", side="Buy", entry_price=100.0, position_idx=0,
                               tick_interval_s=0.1, adx_exit_threshold=20.0)
        ts = TrailingState(
            params=params, initial_sl=99.0, initial_tp=110.0, initial_atr=2.0,
            ws_buffer={"positions": [{"symbol": "BTCUSDT", "markPrice": "105"}]},
            get_indicators_fn=lambda s: {"atr_14": 2.0, "adx_14": 15.0},  # below threshold
            bybit_client=AsyncMock(),
        )
        ts.start()
        await asyncio.sleep(0.25)
        assert not ts.is_active
```

- [ ] **Step 6: Run all trailing tests**

Run: `python -m pytest tests/backend/test_ai_manager_trailing.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/services/ai_manager_trailing.py tests/backend/test_ai_manager_trailing.py
git commit -m "feat(trailing): implement TrailingState module with tests"
```

---

### Task 5: AIManagerTask Integration

**Files:**
- Modify: `backend/services/ai_manager_task.py`

- [ ] **Step 1: Add ADJUST_TP_SL to _ALLOWED_ACTIONS and add imports**

At line 7, add import:
```python
from backend.services.ai_manager_trailing import TrailingState, TrailingParams
```

At line 44, change:
```python
_ALLOWED_ACTIONS = frozenset({"CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL", "FULL_CLOSE", "PARTIAL_CLOSE", "REDUCE"})
```
To:
```python
_ALLOWED_ACTIONS = frozenset({"CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL", "FULL_CLOSE", "PARTIAL_CLOSE", "REDUCE", "ADJUST_TP_SL"})
```

- [ ] **Step 2: Add _active_trailing dict in __init__**

After `self._sweep_blocked_symbols: set = set()` (around line 105), add:
```python
        self._active_trailing: Dict[str, TrailingState] = {}
```

- [ ] **Step 3: Add trailing cleanup to pause() and set_killed()**

Replace `pause()` method (line 204-208):
```python
    def pause(self) -> None:
        """Transition to PAUSED state; the run loop blocks until resume()."""
        self._cancel_all_trailing()
        self.transition_to(PAUSED)
        self._pause_event.set()
        self._wake_event.set()
```

Replace `set_killed()` method (line 225-229):
```python
    def set_killed(self) -> None:
        """Activate kill switch — transitions to ERROR and signals cancellation."""
        self._cancel_all_trailing()
        self._killed = True
        self.transition_to(ERROR)
        self._cancel_event.set()
```

Add helper method:
```python
    def _cancel_all_trailing(self) -> None:
        """Cancel all active trailing states."""
        for ts in list(self._active_trailing.values()):
            ts.cancel()
        self._active_trailing.clear()
```

- [ ] **Step 4: Add _start_trailing method**

Add after `_cancel_all_trailing`:
```python
    async def _start_trailing(self, symbol: str, result: dict) -> None:
        """Create and start a TrailingState for a symbol."""
        position = next(
            (p for p in (self._ws_buffer.get("positions") or []) if p.get("symbol") == symbol),
            None,
        )
        if not position:
            self._log.warning("Cannot start trailing for %s: position not found", symbol)
            return

        # Get ATR from MarketDataCache (correct attribute name: _market_data_cache)
        cache = self._service._market_data_cache
        indicators = cache.get_indicators(symbol) if cache else {}
        atr = indicators.get("atr_14")
        if atr is None or atr <= 0:
            # Ensure symbol is tracked, wait for next refresh cycle won't work here
            # Try get_all_indicators in case symbol data exists under different key
            if cache:
                cache.track_symbols({symbol})
                all_ind = cache.get_all_indicators()
                indicators = all_ind.get(symbol, {})
                atr = indicators.get("atr_14")
            if atr is None or atr <= 0:
                self._log.warning("Cannot start trailing for %s: ATR unavailable", symbol)
                return

        side = position.get("side", "Buy")
        entry_price = float(position.get("avgPrice", position.get("entryPrice", 0)))
        position_idx = int(position.get("positionIdx", 0))
        mark_price = float(position.get("markPrice", position.get("mark_price", 0)))

        params_from_llm = result.get("params") or {}
        atr_mult = float(params_from_llm.get("atr_multiplier", self._config.trailing_default_atr_multiplier))
        tp_ext = float(params_from_llm.get("tp_extension_factor", self._config.trailing_default_tp_extension_factor))

        # Compute initial SL/TP
        if side == "Buy":
            initial_sl = max(entry_price * 1.001, mark_price - atr_mult * atr)
        else:
            initial_sl = min(entry_price * 0.999, mark_price + atr_mult * atr)

        initial_tp = TrailingState._compute_new_tp(side, mark_price, initial_sl, tp_ext)

        params = TrailingParams(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            position_idx=position_idx,
            atr_multiplier=atr_mult,
            tp_extension_factor=tp_ext,
            adx_exit_threshold=self._config.trailing_adx_exit_threshold,
            tick_interval_s=self._config.trailing_tick_interval_s,
            mini_llm_every_n_ticks=self._config.trailing_mini_llm_every_n_ticks,
        )

        def _on_trailing_done(sym: str) -> None:
            self._active_trailing.pop(sym, None)
            self._log.info("Trailing ended for %s", sym)

        # Get Bybit client (per-account, obtained dynamically)
        client = await self._service._accounts_service.get_client(self._account_id)
        if not client:
            self._log.warning("Cannot start trailing for %s: no Bybit client", symbol)
            return

        ts = TrailingState(
            params=params,
            initial_sl=initial_sl,
            initial_tp=initial_tp,
            initial_atr=atr,
            ws_buffer=self._ws_buffer,
            get_indicators_fn=lambda s: (self._service._market_data_cache.get_indicators(s) if self._service._market_data_cache else {}),
            bybit_client=client,
            mini_llm_fn=None,  # Task 8 wires this up
            on_done=_on_trailing_done,
        )

        # Set initial TP/SL on exchange
        try:
            await client.set_trading_stop(
                symbol=symbol,
                take_profit=str(initial_tp),
                stop_loss=str(initial_sl),
                position_idx=position_idx,
            )
        except Exception:
            self._log.exception("Failed to set initial trailing TP/SL for %s", symbol)
            return

        self._active_trailing[symbol] = ts
        ts.start()
        self._log.info("Started trailing for %s: SL=%.6f TP=%.6f ATR=%.6f", symbol, initial_sl, initial_tp, atr)
```

- [ ] **Step 5: Bifurcate _execute_action for ADJUST_TP_SL**

In `_execute_action()`, the bifurcation must happen AFTER the lock is acquired and budget is consumed (around line 898, after `budget_ok` check). This ensures ADJUST_TP_SL respects per-symbol cooldown, position locking, kill-switch recheck, and action budget — same safety as closes. Insert BEFORE the decision recording and close logic:

```python
        if action_type == "ADJUST_TP_SL":
            # Record decision (same as close path)
            now_utc = datetime.now(timezone.utc)
            decision_data = {
                "timestamp": now_utc,
                "action_type": action_type,
                "evaluation_type": "standard",
                "urgency": self._get_urgency(),
                "state_snapshot": copy.deepcopy(self._ws_buffer),
                "action_taken": {"action": action_type, "symbol": symbol},
                "reasoning": result.get("reason", "")[:_MAX_REASONING_CHARS],
                "confidence": result.get("confidence", 0.0),
                "graph_path": result.get("graph_path"),
                "strategy_version": self._config.strategy_version,
                "chain_key_version": _CHAIN_KEY_VERSION,
            }
            await self._service._repo.insert_decision(
                self._account_id, decision_data, self._service._hmac_key
            )
            await self._start_trailing(symbol, result)
            return  # Skip close logic below
```

**Important:** This must be INSIDE the `try:` block that holds the lock, so the `finally:` clause at the end releases the lock properly.

- [ ] **Step 6: Pass trailing state into graph evaluation**

In the `_evaluate()` method, the graph state dict is built at lines 1094-1116 as a dict literal returned from a helper. Add these entries to that dict (after the `"_sweep_blocked_symbols"` entry at line 1112):
```python
            "trailing_count": len(self._active_trailing),
            "trailing_symbols": set(self._active_trailing.keys()),
            "trailing_config": {
                "enabled": self._config.trailing_enabled,
                "max_concurrent": self._config.trailing_max_concurrent,
                "min_profit_pct": self._config.trailing_min_profit_pct,
            },
```

Also, filter trailing symbols out of the positions passed to the LLM. In `_get_market_data()` (line 1124) or more precisely in the graph state's `"ws_snapshot"`, the positions list should exclude trailing symbols. Add filtering where `ws_snapshot` is built:
```python
            # Filter trailing symbols from LLM evaluation
            ws_copy = copy.deepcopy(self._ws_buffer)
            ws_copy["positions"] = [
                p for p in (ws_copy.get("positions") or [])
                if p.get("symbol") not in self._active_trailing
            ]
```
Use `ws_copy` instead of `copy.deepcopy(self._ws_buffer)` for the `"ws_snapshot"` value.

- [ ] **Step 7: Suppress event triggers for trailing symbols**

The `EventTriggerDetector` is fed position data via `_handle_ws_event` callbacks, NOT via a `check_triggers()` call in `_monitoring_cycle`. The trigger fires by setting `_event_trigger_fired` asyncio.Event.

The correct approach: in the event trigger's evaluation (inside `_handle_ws_event` or where `_event_trigger.update()` is called), skip symbols in `_active_trailing`. Find where `_event_trigger` processes position data and add:
```python
        # Skip trigger evaluation for actively trailing symbols
        if symbol in self._active_trailing:
            return
```

Alternatively, in the `EventTriggerDetector.check()` method's position loop, pass an exclusion set:
```python
        self._event_trigger.set_excluded_symbols(set(self._active_trailing.keys()))
```

The exact insertion point depends on where `_event_trigger` processes position updates — grep for `_event_trigger` usage and add the exclusion at that call site.

- [ ] **Step 8: Cancel trailing on emergency close**

In `_check_emergency_close()`, before closing positions, add:
```python
        # Cancel any trailing for symbols about to be emergency-closed
        for sym in symbols_to_close:
            if sym in self._active_trailing:
                self._active_trailing[sym].cancel()
                self._active_trailing.pop(sym, None)
```

- [ ] **Step 9: Handle sweep interactions with trailing**

In `_process_sweep_lifecycle()` (or wherever sweep detection fires), when a sweep is detected for a symbol:
```python
        if symbol in self._active_trailing:
            self._active_trailing[symbol].suspend()
```

When sweep resolves for a symbol:
```python
        if symbol in self._active_trailing:
            # Get current SL from position data
            pos = next((p for p in self._ws_buffer.get("positions", []) if p.get("symbol") == symbol), None)
            current_sl = float(pos.get("stopLoss", 0)) if pos else 0
            if current_sl > 0:
                self._active_trailing[symbol].resume_from_sweep(current_sl)
            else:
                self._active_trailing[symbol].cancel()
                self._active_trailing.pop(symbol, None)
```

- [ ] **Step 10: Run tests**

Run: `python -m pytest tests/backend/test_ai_manager_task.py -v -x`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add backend/services/ai_manager_task.py
git commit -m "feat(trailing): integrate TrailingState into AIManagerTask lifecycle"
```

---

### Task 6: Close Rule Evaluator Integration

**Files:**
- Modify: `backend/services/close_rule_evaluator.py`

- [ ] **Step 1: Add trailing awareness to close rule evaluator**

The `CloseRuleEvaluator` needs a reference to the active trailing set. Add a method to accept it:

In the class `__init__`, add a parameter:
```python
        self._get_active_trailing: Callable[[], set] = lambda: set()
```

Add a setter:
```python
    def set_trailing_checker(self, fn: Callable[[], set]) -> None:
        self._get_active_trailing = fn
```

- [ ] **Step 2: Guard BREAKEVEN_TIMEOUT against trailing symbols**

In the evaluation loop (around line 228-238), before handling `BREAKEVEN_TIMEOUT`:
```python
                    # BREAKEVEN_TIMEOUT: skip if symbol is actively trailing
                    if rule["trigger_type"] == "BREAKEVEN_TIMEOUT":
                        rule_symbols = rule.get("symbols", [])
                        trailing_symbols = self._get_active_trailing()
                        if any(s in trailing_symbols for s in rule_symbols):
                            logger.info(
                                "Skipping BREAKEVEN_TIMEOUT rule %s — symbol(s) actively trailing",
                                rule["id"],
                            )
                            continue
```

- [ ] **Step 3: Wire up in main.py (where CloseRuleEvaluator is instantiated)**

The `CloseRuleEvaluator` is instantiated in `backend/main.py` (around line 283), NOT in `ai_account_manager_service.py`. The wiring must aggregate trailing symbols across ALL active tasks (multi-account):

In `backend/main.py`, after the evaluator is created:
```python
        # Wire trailing awareness into close rule evaluator
        def _get_all_trailing_symbols() -> set:
            """Aggregate trailing symbols across all account tasks."""
            trailing = set()
            ai_service = app.state.ai_manager_service
            if ai_service and hasattr(ai_service, '_tasks'):
                for task in ai_service._tasks.values():
                    trailing.update(task._active_trailing.keys())
            return trailing

        app.state.rule_evaluator.set_trailing_checker(_get_all_trailing_symbols)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/backend/test_ai_manager_task.py -v -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/close_rule_evaluator.py backend/main.py
git commit -m "feat(trailing): suppress close rule TP/SL mods on trailing symbols"
```

---

### Task 7: Exchange-Side SL Execution Tracking

**Files:**
- Modify: `backend/services/ai_manager_task.py`

- [ ] **Step 1: Detect trailing position closure in WS handler**

In `_handle_ws_event` (line 292-308), the position update handler at line 296 filters out the position via list comprehension BEFORE checking if it closed. The `data` variable from the WS event contains the update (with size=0). We must capture the OLD position data BEFORE the filter removes it.

Modify the position_update handler. Before line 296 (`positions = [p for p in positions if p.get("symbol") != symbol]`), add:

```python
            # Capture old position before removal (for trailing PnL tracking)
            old_position = next((p for p in positions if p.get("symbol") == symbol), None)
```

Then in the `else` branch (line 301, where size == 0), add:
```python
                    # Track exchange-side execution for trailing symbols
                    if symbol in self._active_trailing and old_position:
                        try:
                            entry = float(old_position.get("avgPrice", old_position.get("entryPrice", 0)))
                            last_mark = float(old_position.get("markPrice", 0))
                            size = float(old_position.get("size", 0))
                            pos_side = old_position.get("side", "Buy")
                            if pos_side == "Buy":
                                estimated_pnl = (last_mark - entry) * size
                            else:
                                estimated_pnl = (entry - last_mark) * size
                            if estimated_pnl < 0:
                                asyncio.create_task(self._enforce_daily_limits(estimated_pnl))
                                self._log.info(
                                    "Exchange-side SL execution for trailing %s, est PnL: $%.2f",
                                    symbol, estimated_pnl,
                                )
                        except (TypeError, ValueError):
                            self._log.warning("Could not compute PnL for exchange-closed trailing %s", symbol)
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/backend/test_ai_manager_task.py -v -x`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_manager_task.py
git commit -m "feat(trailing): track exchange-side SL execution for daily loss enforcement"
```

---

### Task 8: Mini-LLM Wiring

**Files:**
- Modify: `backend/services/ai_manager_task.py`

- [ ] **Step 1: Create mini-LLM callable**

Add a method to `AIManagerTask`. **Important:** The `_llm_callable` signature is `(system_prompt: str, context_prompt: str) -> str` (two positional string args, no max_tokens). The mini-LLM must use this same interface:

```python
    async def _trailing_mini_llm(self, symbol: str, side: str, entry: float, price: float,
                                  sl: float, tp: float, atr: float, adx: float, tick: int) -> str:
        """Lightweight LLM check for trailing continuation."""
        upnl = (price - entry) if side == "Buy" else (entry - price)

        system_prompt = (
            "You are a trailing stop-loss monitor. Given position state, decide: "
            "KEEP (continue trailing), TIGHTEN (reduce ATR multiplier), or EXIT (stop trailing). "
            "Reply with one word followed by a 10-word reason."
        )
        context_prompt = (
            f"Symbol: {symbol} | Side: {side} | Entry: ${entry:.4f} | Current: ${price:.4f}\n"
            f"SL: ${sl:.4f} | TP: ${tp:.4f} | ATR: ${atr:.4f} | ADX: {adx:.1f} | Tick: {tick}\n"
            f"Unrealized PnL: ${upnl:.4f}\n\n"
            "Decision: KEEP | TIGHTEN | EXIT"
        )

        llm = self._llm_callable or (self._service._llm_callable if self._service else None)
        if not llm:
            return "KEEP"
        response = await llm(system_prompt, context_prompt)
        return response.strip().split()[0] if response else "KEEP"
```

- [ ] **Step 2: Pass mini_llm_fn when creating TrailingState**

In `_start_trailing`, change `mini_llm_fn=None` to:
```python
            mini_llm_fn=self._trailing_mini_llm,
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/backend/test_ai_manager_trailing.py tests/backend/test_ai_manager_task.py -v -x`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/ai_manager_task.py
git commit -m "feat(trailing): wire up mini-LLM for periodic trailing re-assessment"
```

---

### Task 9: Full Integration Test

**Files:**
- Modify: `tests/backend/test_ai_manager_trailing.py`

- [ ] **Step 1: Add integration-style test**

```python
class TestFullIntegration:
    @pytest.mark.asyncio
    async def test_trailing_full_cycle(self):
        """End-to-end: start trailing → SL moves up → ADX fades → exits."""
        tick = 0
        adx_values = [30, 30, 30, 15]  # fades on 4th tick

        def fake_indicators(symbol):
            nonlocal tick
            idx = min(tick, len(adx_values) - 1)
            return {"atr_14": 2.0, "adx_14": adx_values[idx]}

        client = AsyncMock()
        client.set_trading_stop = AsyncMock(return_value={})

        params = TrailingParams(
            symbol="BTCUSDT", side="Buy", entry_price=100.0,
            position_idx=0, tick_interval_s=0.1, adx_exit_threshold=20.0,
        )
        # Price rising each tick
        prices = [105, 108, 112, 112]
        price_idx = [0]

        ws = {"positions": [{"symbol": "BTCUSDT", "markPrice": "105", "_ws_updated_at": time.time()}]}

        def update_price():
            price_idx[0] = min(price_idx[0] + 1, len(prices) - 1)
            ws["positions"][0]["markPrice"] = str(prices[price_idx[0]])
            ws["positions"][0]["_ws_updated_at"] = time.time()

        orig_tick = TrailingState._tick
        async def patched_tick(self_ts):
            nonlocal tick
            update_price()
            tick += 1
            await orig_tick(self_ts)

        done_events = []
        ts = TrailingState(
            params=params, initial_sl=96.0, initial_tp=114.0, initial_atr=2.0,
            ws_buffer=ws,
            get_indicators_fn=fake_indicators,
            bybit_client=client,
            on_done=lambda s: done_events.append(s),
        )

        with patch.object(TrailingState, '_tick', patched_tick):
            ts.start()
            await asyncio.sleep(0.8)

        assert not ts.is_active
        assert done_events == ["BTCUSDT"]
        # SL should have moved up from initial 96
        assert client.set_trading_stop.call_count >= 1
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/backend/test_ai_manager_trailing.py -v`
Expected: PASS

- [ ] **Step 3: Run full backend test suite**

Run: `python -m pytest tests/backend/ -v --timeout=60`
Expected: PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add tests/backend/test_ai_manager_trailing.py
git commit -m "test(trailing): add full integration test for trailing lifecycle"
```

---
