"""Per-symbol trailing TP/SL manager.

Handles the 30s fast-cycle tick loop for symbols where the LLM has decided
to trail TP/SL. Uses ATR-based SL computation and periodic mini-LLM checks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class TrailingParams:
    """Configuration for one symbol's trailing TP/SL loop (ATR multipliers, tick cadence, limits)."""

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
    max_duration_s: float = 3600.0
    max_api_failures: int = 5


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
        get_client_fn: Callable[[], Any],
        mini_llm_fn: Optional[Callable] = None,
        on_done: Optional[Callable[[str], None]] = None,
    ):
        self._params = params
        self._current_sl = initial_sl
        self._current_tp = initial_tp
        self._last_atr = initial_atr
        self._ws_buffer = ws_buffer
        self._get_indicators = get_indicators_fn
        self._get_client = get_client_fn
        self._mini_llm_fn = mini_llm_fn
        self._on_done = on_done

        self._tick_count = 0
        self._cancelled = False
        self._suspended = False
        self._mini_llm_failures = 0
        self._consecutive_api_failures = 0
        self._consecutive_stale_ticks = 0
        self._started_at = 0.0
        self._task: Optional[asyncio.Task] = None
        self._last_set_sl: Optional[float] = initial_sl
        self._last_set_tp: Optional[float] = initial_tp
        self._log = logging.getLogger(f"trailing.{params.symbol}")

    @property
    def symbol(self) -> str:
        """The symbol this trailing state manages."""
        return self._params.symbol

    @property
    def is_active(self) -> bool:
        """Return True if the trailing loop task is running and not cancelled."""
        return not self._cancelled and self._task is not None and not self._task.done()

    def start(self) -> None:
        """Launch the background trailing tick loop as an asyncio task."""
        self._task = asyncio.create_task(
            self._run_loop(), name=f"trailing-{self._params.symbol}"
        )

    def cancel(self) -> None:
        """Stop trailing and cancel the running loop task."""
        self._cancelled = True
        if self._task and not self._task.done():
            self._task.cancel()

    def suspend(self) -> None:
        """Pause SL/TP updates (e.g. while sweep-defense is active) without ending the loop."""
        self._suspended = True
        self._log.info("Suspended (sweep defense active)")

    def resume_from_sweep(self, current_exchange_sl: float) -> None:
        """Resume trailing after a suspend, re-syncing the SL to the exchange's current value."""
        self._suspended = False
        self._current_sl = current_exchange_sl
        self._log.info("Resumed from sweep, SL reset to %.6f", current_exchange_sl)

    async def _run_loop(self) -> None:
        self._started_at = time.monotonic()
        try:
            while not self._cancelled:
                await asyncio.sleep(self._params.tick_interval_s)
                if self._cancelled:
                    break
                if (time.monotonic() - self._started_at) > self._params.max_duration_s:
                    self._log.info("Max duration reached (%.0fs), exiting", self._params.max_duration_s)
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

        position = self._find_position()
        if position is None:
            self._log.info("Position closed, terminating trailing")
            self._cancelled = True
            return

        pos_updated_at = position.get("_ws_updated_at", 0.0)
        if pos_updated_at and (time.time() - pos_updated_at) > self._params.staleness_threshold_s:
            self._consecutive_stale_ticks += 1
            if self._consecutive_stale_ticks >= 3:
                self._log.error("3 consecutive stale ticks, cancelling trailing — handing back to rule evaluator")
                self._cancelled = True
                return
            self._log.warning("Stale WS data (%.0fs old), skipping tick (%d/3)", time.time() - pos_updated_at, self._consecutive_stale_ticks)
            return
        self._consecutive_stale_ticks = 0

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

        if adx is not None and adx < self._params.adx_exit_threshold:
            self._log.info("Momentum faded (ADX=%.1f < %.1f), exiting", adx, self._params.adx_exit_threshold)
            self._cancelled = True
            return

        new_sl = self._compute_new_sl(
            self._params.side, self._current_sl, price, atr, self._params.atr_multiplier
        )
        new_sl = self._enforce_breakeven_minimum(
            self._params.side, self._params.entry_price, new_sl
        )
        new_tp = self._compute_new_tp(
            self._params.side, price, new_sl, self._params.tp_extension_factor
        )
        # TP never moves backwards
        if self._params.side == "Buy":
            new_tp = max(self._current_tp, new_tp)
        else:
            new_tp = min(self._current_tp, new_tp)

        sl_changed = new_sl != self._last_set_sl
        tp_changed = new_tp != self._last_set_tp
        if sl_changed or tp_changed:
            try:
                client = await self._get_client()
                if not client:
                    self._consecutive_api_failures += 1
                    self._log.warning("No client available (%d/%d)", self._consecutive_api_failures, self._params.max_api_failures)
                else:
                    await client.set_trading_stop(
                        symbol=self._params.symbol,
                        stop_loss=str(new_sl) if sl_changed else None,
                        take_profit=str(new_tp) if tp_changed else None,
                        position_idx=self._params.position_idx,
                    )
                    self._current_sl = new_sl
                    self._current_tp = new_tp
                    self._last_set_sl = new_sl
                    self._last_set_tp = new_tp
                    self._consecutive_api_failures = 0
                    self._log.debug("Updated SL=%.6f TP=%.6f", new_sl, new_tp)
            except Exception:
                self._consecutive_api_failures += 1
                self._log.warning("set_trading_stop failed (%d/%d), will retry",
                                  self._consecutive_api_failures, self._params.max_api_failures)

            if self._consecutive_api_failures >= self._params.max_api_failures:
                self._log.error("Max API failures reached, cancelling trailing for %s", self._params.symbol)
                self._cancelled = True
                return

        # Mini-LLM check
        if (
            self._tick_count % self._params.mini_llm_every_n_ticks == 0
            and self._mini_llm_fn
            and self._mini_llm_failures < 3
        ):
            await self._run_mini_llm(price, atr, adx)

    async def _run_mini_llm(self, price: float, atr: float, adx: Optional[float]) -> None:
        if self._mini_llm_fn is None:
            return
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
