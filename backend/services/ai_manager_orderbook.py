"""AI Manager Order Book Monitor + Sweep Detection.

Connects to Bybit public WebSocket for real-time orderbook and trade data.
Detects liquidity manipulation (fake sweeps, stop hunts, spoofing).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

_WS_PUBLIC_LINEAR = "wss://stream.bybit.com/v5/public/linear"
_RECONNECT_BASE = 2.0
_RECONNECT_MAX = 30.0
_TRADE_TAPE_SIZE = 1000
_VOLUME_WINDOW_S = 30.0


class SweepDetector:
    """Detects fake sweep / stop hunt patterns from trade tape."""

    def __init__(self, confidence_threshold: float = 0.5):
        self._threshold = confidence_threshold
        self._trades: deque = deque(maxlen=_TRADE_TAPE_SIZE)
        self._avg_volume_30s: float = 0.0
        self._last_update: float = 0.0

    def update_trade(self, trade: Dict[str, Any]) -> None:
        self._trades.append(trade)
        self._update_avg_volume()

    def _update_avg_volume(self) -> None:
        now = time.monotonic()
        if now - self._last_update < 5.0 and self._avg_volume_30s > 0:
            return
        self._last_update = now
        if not self._trades:
            return
        latest_ts = self._trades[-1].get("time", 0)
        cutoff_ms = latest_ts - int(_VOLUME_WINDOW_S * 1000)
        recent = [t for t in self._trades if t.get("time", 0) > cutoff_ms]
        if recent:
            self._avg_volume_30s = sum(float(t.get("size", 0)) for t in recent) / max(1, len(recent))

    def check_sweep(
        self, my_sl: Optional[float], my_side: str, current_price: float
    ) -> Optional[Dict[str, Any]]:
        if not self._trades or self._avg_volume_30s == 0 or my_sl is None:
            return None

        now_ms = self._trades[-1].get("time", 0) if self._trades else 0
        recent = [t for t in self._trades if now_ms - t.get("time", 0) < 10000]
        if len(recent) < 5:
            return None

        burst_volume = sum(float(t.get("size", 0)) for t in recent)
        volume_ratio = burst_volume / max(0.001, self._avg_volume_30s * len(recent))

        if my_side == "Buy":
            approaching = current_price < my_sl * 1.005
            direction = "long_hunt"
        else:
            approaching = current_price > my_sl * 0.995
            direction = "short_hunt"

        if not approaching:
            return None

        confidence = min(1.0, (volume_ratio - 1.0) / 2.0)
        if confidence < self._threshold:
            return None

        return {
            "confidence": round(confidence, 3),
            "direction": direction,
            "swept_level": my_sl,
            "current_price": current_price,
            "recovery_started": False,
            "targets_my_position": True,
            "volume_anomaly_ratio": round(volume_ratio, 2),
        }


class OrderBookMonitor:
    """Per-symbol order book state + sweep detection."""

    def __init__(self, symbol: str, confidence_threshold: float = 0.5):
        self._symbol = symbol
        self._bids: List[Tuple[float, float]] = []
        self._asks: List[Tuple[float, float]] = []
        self._sweep_detector = SweepDetector(confidence_threshold)
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._fallback_task: Optional[asyncio.Task] = None
        self._running = False

    def update_orderbook(self, bids: List, asks: List) -> None:
        self._bids = [(float(b[0]), float(b[1])) for b in bids[:50]]
        self._asks = [(float(a[0]), float(a[1])) for a in asks[:50]]

    def update_trade(self, trade: Dict[str, Any]) -> None:
        self._sweep_detector.update_trade(trade)

    def get_snapshot(
        self, my_sl: Optional[float], my_side: str, current_price: float
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        imbalance = self._compute_imbalance(10)
        spread = self._compute_spread()
        bid_clusters = self._find_clusters("bid")
        ask_clusters = self._find_clusters("ask")
        depth_ratio = self._compute_depth_ratio(25)

        if my_sl:
            for c in bid_clusters + ask_clusters:
                c["near_my_sl"] = abs(c["price"] - my_sl) / max(my_sl, 1) < 0.003

        sweep = self._sweep_detector.check_sweep(my_sl, my_side, current_price)

        return {
            "bid_clusters": bid_clusters,
            "ask_clusters": ask_clusters,
            "imbalance_ratio": round(imbalance, 3),
            "spread_bps": round(spread, 2),
            "depth_ratio": round(depth_ratio, 3),
            "spoofing_flags": [],
        }, sweep

    def _compute_imbalance(self, levels: int = 10) -> float:
        bid_vol = sum(s for _, s in self._bids[:levels]) if self._bids else 0
        ask_vol = sum(s for _, s in self._asks[:levels]) if self._asks else 0
        if ask_vol == 0:
            return 1.0
        return bid_vol / ask_vol

    def _compute_spread(self) -> float:
        if not self._bids or not self._asks:
            return 0.0
        best_bid = self._bids[0][0]
        best_ask = self._asks[0][0]
        mid = (best_bid + best_ask) / 2
        if mid == 0:
            return 0.0
        return (best_ask - best_bid) / mid * 10000

    def _compute_depth_ratio(self, levels: int = 25) -> float:
        bid_vol = sum(s for _, s in self._bids[:levels]) if self._bids else 0
        ask_vol = sum(s for _, s in self._asks[:levels]) if self._asks else 0
        if ask_vol == 0:
            return 1.0
        return bid_vol / ask_vol

    def _find_clusters(self, side: str, threshold_multiplier: float = 3.0) -> List[Dict[str, Any]]:
        levels = self._bids if side == "bid" else self._asks
        if not levels:
            return []
        sizes = sorted(s for _, s in levels)
        # Use lower half average so outliers don't inflate the threshold
        half = max(1, len(sizes) // 2)
        baseline_avg = sum(sizes[:half]) / half
        threshold = baseline_avg * threshold_multiplier
        clusters = []
        for price, size in levels:
            if size > threshold:
                clusters.append({"price": price, "volume": size, "side": side})
        return clusters[:5]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._ws_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._fallback_task and not self._fallback_task.done():
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except asyncio.CancelledError:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ws_loop(self) -> None:
        delay = _RECONNECT_BASE
        while self._running:
            try:
                from backend.services.bybit_rate_gate import get_rate_gate
                await get_rate_gate().acquire_async(channel="ws_connect")
                await self._connect_and_listen()
                delay = _RECONNECT_BASE
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("OrderBook WS error for %s: %s", self._symbol, e)
            if not self._running:
                break
            if self._fallback_task and not self._fallback_task.done():
                self._fallback_task.cancel()
            self._fallback_task = asyncio.create_task(self._rest_fallback_once())
            jitter = random.uniform(0, 5.0)
            await asyncio.sleep(delay + jitter)
            delay = min(delay * 2, _RECONNECT_MAX)

    async def _rest_fallback_once(self) -> None:
        try:
            from backend.services.bybit_rate_gate import get_rate_gate
            await get_rate_gate().acquire_async(channel="public")
            if not self._session or self._session.closed:
                self._session = aiohttp.ClientSession()
            async with self._session.get(
                f"https://api.bybit.com/v5/market/orderbook?category=linear&symbol={self._symbol}&limit=50",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    data = body.get("result", {})
                    self.update_orderbook(data.get("b", []), data.get("a", []))
                    logger.debug("REST fallback orderbook updated for %s", self._symbol)
        except Exception:
            logger.debug("REST fallback failed for %s", self._symbol)

    async def _connect_and_listen(self) -> None:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        self._ws = await asyncio.wait_for(
            self._session.ws_connect(_WS_PUBLIC_LINEAR, heartbeat=20),
            timeout=15,
        )
        await self._ws.send_json({
            "op": "subscribe",
            "args": [f"orderbook.50.{self._symbol}", f"publicTrade.{self._symbol}"],
        })
        async for msg in self._ws:
            if not self._running:
                break
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                topic = data.get("topic", "")
                if "orderbook" in topic:
                    ob_data = data.get("data", {})
                    self.update_orderbook(ob_data.get("b", []), ob_data.get("a", []))
                elif "publicTrade" in topic:
                    for trade in data.get("data", []):
                        self.update_trade({
                            "price": float(trade.get("p", 0)),
                            "size": float(trade.get("v", 0)),
                            "side": trade.get("S", ""),
                            "time": int(trade.get("T", 0)),
                        })
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break
