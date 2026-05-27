"""Process-wide Bybit IP-level rate gate.

All Bybit HTTP requests (private or public, async or sync) MUST acquire
a token from this gate before hitting the network. Prevents combined load
from exceeding Bybit's 600/5s IP limit (10-minute ban on violation).
"""

from __future__ import annotations

import asyncio
import collections
import threading
import time
from typing import Optional

_WINDOW_SECONDS = 5.0
_PUBLIC_BUDGET = 400
_PRIVATE_BUDGET = 100
_WS_CONNECT_BUDGET = 450  # Bybit allows 500 new WS connections/5min — leave headroom


class BybitRateGate:
    """Cross-system IP-level rate gate. Singleton per process."""

    def __init__(
        self,
        public_budget: int = _PUBLIC_BUDGET,
        private_budget: int = _PRIVATE_BUDGET,
        ws_connect_budget: int = _WS_CONNECT_BUDGET,
        window: float = _WINDOW_SECONDS,
    ):
        self._public_max = public_budget
        self._private_max = private_budget
        self._ws_connect_max = ws_connect_budget
        self._window = window
        # WS connect uses 5-minute window (Bybit limit is 500/5min)
        self._ws_window = 300.0
        self._public_timestamps: collections.deque = collections.deque(maxlen=public_budget + 50)
        self._private_timestamps: collections.deque = collections.deque(maxlen=private_budget + 50)
        self._ws_connect_timestamps: collections.deque = collections.deque(maxlen=ws_connect_budget + 50)
        self._lock = threading.Lock()
        self._wait_count = 0

    @property
    def current_usage(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "public": sum(1 for t in self._public_timestamps if t > now - self._window),
                "private": sum(1 for t in self._private_timestamps if t > now - self._window),
                "ws_connect": sum(1 for t in self._ws_connect_timestamps if t > now - self._ws_window),
            }

    @property
    def wait_count(self) -> int:
        return self._wait_count

    def _get_channel(self, channel: str):
        if channel == "private":
            return self._private_timestamps, self._private_max, self._window
        if channel == "ws_connect":
            return self._ws_connect_timestamps, self._ws_connect_max, self._ws_window
        return self._public_timestamps, self._public_max, self._window

    async def acquire_async(self, channel: str = "public") -> None:
        timestamps, max_budget, window = self._get_channel(channel)
        self._wait_count += 1
        try:
            while True:
                with self._lock:
                    now = time.monotonic()
                    while timestamps and timestamps[0] < now - window:
                        timestamps.popleft()
                    if len(timestamps) < max_budget:
                        timestamps.append(now)
                        return
                    sleep_time = timestamps[0] - (now - window) + 0.05
                await asyncio.sleep(max(0.05, min(sleep_time, window)))
        finally:
            self._wait_count -= 1

    def acquire_sync(self, channel: str = "public", timeout: float = 10.0) -> bool:
        timestamps, max_budget, window = self._get_channel(channel)
        deadline = time.monotonic() + timeout
        self._wait_count += 1
        try:
            while time.monotonic() < deadline:
                with self._lock:
                    now = time.monotonic()
                    while timestamps and timestamps[0] < now - window:
                        timestamps.popleft()
                    if len(timestamps) < max_budget:
                        timestamps.append(now)
                        return True
                    sleep_time = timestamps[0] - (now - window) + 0.05
                time.sleep(max(0.05, min(sleep_time, window)))
            return False
        finally:
            self._wait_count -= 1


_gate: Optional[BybitRateGate] = None
_gate_init_lock = threading.Lock()


def get_rate_gate() -> BybitRateGate:
    global _gate
    if _gate is None:
        with _gate_init_lock:
            if _gate is None:
                _gate = BybitRateGate()
    return _gate
