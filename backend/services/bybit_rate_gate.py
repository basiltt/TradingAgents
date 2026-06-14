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

# Per-account, per-endpoint-class caps (1-second window), ≈80% of Bybit's
# non-VIP floor. None => IP-bounded only (no per-UID sub-limit). Imported from
# the endpoint registry so it stays the single source of truth.
try:
    from backend.services.bybit_endpoints import ENDPOINT_PER_SECOND_CAP as _DEFAULT_ENDPOINT_CAPS
except Exception:  # pragma: no cover - registry import is the canonical path
    _DEFAULT_ENDPOINT_CAPS = {}


class RateGateBanAbort(BaseException):
    """Raised by the gate while a confirmed Bybit IP ban is in effect.

    Subclasses BaseException (NOT Exception) on purpose: the order-placement
    path wraps work in a broad ``except Exception`` that turns failures into a
    "failed" execution. A ban must NOT be silently swallowed there — the caller
    must catch RateGateBanAbort explicitly, release any held position-lock, and
    re-queue / record a ban substatus (FR-047). It is a sibling of
    asyncio.CancelledError, so it does not interfere with cancellation.
    """

    def __init__(self, cooloff_until: Optional[float] = None):
        super().__init__("Bybit rate-gate ban in effect")
        self.cooloff_until = cooloff_until


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
        # Per-(account_key, endpoint_class) rolling-window deques (1s window by
        # default). Created lazily; bounded by the configured account count.
        self._endpoint_caps: dict[str, int] = {
            k: v for k, v in dict(_DEFAULT_ENDPOINT_CAPS).items() if v is not None
        }
        self._endpoint_window = 1.0
        self._endpoint_ts: dict[tuple[str, str], collections.deque] = {}
        # Ban breaker: monotonic deadline past which the breaker re-opens (None =
        # not banned). cooloff_until is the wall-clock epoch surfaced to the UI.
        self._ban_until_monotonic: Optional[float] = None
        self._ban_cooloff_until: Optional[float] = None
        # Monotonic generation counter bumped on every trip_ban. A success that
        # clears the breaker must pass the generation it observed when it started,
        # so a slow request whose ban was superseded by a FRESH ban cannot wipe the
        # new ban (ABA guard).
        self._ban_generation: int = 0
        # Half-open recovery: after the cooloff deadline, admit exactly ONE probe
        # and hold everyone else, rather than releasing the whole backlog at once
        # (which would instantly re-trip a still-active Bybit ban). The probe is
        # given a short window; if the prober never reports back (success ->
        # clear_ban, failure -> trip_ban re-arms) the window expires and the next
        # caller becomes the new probe (so a lost probe can't deadlock the gate).
        self._half_open_probe_until: Optional[float] = None

    # Probe window: how long a single half-open probe holds the "armed" state
    # before another caller is allowed to re-probe (seconds). Must be >= the max
    # request wall-time (aiohttp total=10s × retries) so a slow probe's window
    # cannot expire while its request is still in flight (which would admit a
    # second overlapping probe).
    _HALF_OPEN_PROBE_WINDOW = 30.0
    # How long a background (non-raise_on_ban) caller sleeps between ban re-checks.
    _BAN_POLL_INTERVAL = 0.5

    def set_endpoint_caps(self, caps: dict[str, int], *, per_window: float = 1.0) -> None:
        """Override the per-account/endpoint caps and window (used by tests/config)."""
        with self._lock:
            self._endpoint_caps = dict(caps)
            self._endpoint_window = per_window
            self._endpoint_ts.clear()

    @property
    def ban_generation(self) -> int:
        """Monotonic counter of ban trips; capture it before a probe request and
        pass it to clear_ban() so a stale success can't wipe a fresher ban."""
        return self._ban_generation

    def trip_ban(self, *, cooloff_seconds: float) -> None:
        """Open the ban breaker for ``cooloff_seconds`` (called on a confirmed
        IP-level ban — NOT a per-UID throttle).

        While open, an acquire either raises RateGateBanAbort (order/scan callers
        that pass raise_on_ban=True) or waits out the ban (background callers), so
        nothing keeps hammering an already-banned IP.
        """
        with self._lock:
            self._ban_until_monotonic = time.monotonic() + cooloff_seconds
            self._ban_cooloff_until = time.time() + cooloff_seconds
            self._half_open_probe_until = None
            self._ban_generation += 1

    @property
    def is_banned(self) -> bool:
        """True while the ban breaker is OPEN (before the cooloff deadline)."""
        deadline = self._ban_until_monotonic
        return deadline is not None and time.monotonic() < deadline

    def _ban_state(self) -> str:
        """Classify the current ban state for an acquiring caller. Returns:
        - "clear": no ban (or this caller is admitted as the half-open probe).
        - "banned": breaker open OR a probe is already in flight — caller must
          wait/abort.
        Admission of a single probe happens HERE under the lock so it is atomic.
        """
        deadline = self._ban_until_monotonic
        if deadline is None:
            return "clear"
        now = time.monotonic()
        with self._lock:
            deadline = self._ban_until_monotonic
            if deadline is None:
                return "clear"
            if now < deadline:
                return "banned"
            # Past the cooloff deadline — half-open.
            probe_until = self._half_open_probe_until
            if probe_until is not None and now < probe_until:
                return "banned"  # a probe is in flight; hold others
            # Admit THIS caller as the probe; arm the probe window. The breaker
            # stays "set" (deadline non-None) so concurrent callers are held until
            # the prober reports (clear_ban on success / trip_ban on fresh ban) or
            # the window expires.
            self._half_open_probe_until = now + self._HALF_OPEN_PROBE_WINDOW
            return "clear"

    @property
    def ban_cooloff_until(self) -> Optional[float]:
        """Wall-clock epoch the current ban clears at, or None."""
        return self._ban_cooloff_until

    def clear_ban(self, expected_generation: Optional[int] = None) -> bool:
        """Clear an active ban (called by a successful half-open probe, by an
        operator override, or for test isolation). Returns True if it cleared.

        If ``expected_generation`` is given, only clears when it matches the
        current ban generation — so a slow probe whose ban was superseded by a
        FRESH ``trip_ban`` cannot wipe the new ban (ABA guard)."""
        with self._lock:
            if expected_generation is not None and expected_generation != self._ban_generation:
                return False
            self._ban_until_monotonic = None
            self._ban_cooloff_until = None
            self._half_open_probe_until = None
            return True

    @property
    def current_usage(self) -> dict:
        """Current per-channel request counts within their rolling windows."""
        now = time.monotonic()
        with self._lock:
            return {
                "public": sum(1 for t in self._public_timestamps if t > now - self._window),
                "private": sum(1 for t in self._private_timestamps if t > now - self._window),
                "ws_connect": sum(1 for t in self._ws_connect_timestamps if t > now - self._ws_window),
            }

    @property
    def wait_count(self) -> int:
        """Number of callers currently waiting on the rate gate."""
        return self._wait_count

    def _get_channel(self, channel: str):
        if channel == "private":
            return self._private_timestamps, self._private_max, self._window
        if channel == "ws_connect":
            return self._ws_connect_timestamps, self._ws_connect_max, self._ws_window
        return self._public_timestamps, self._public_max, self._window

    async def acquire_async(
        self,
        channel: str = "public",
        *,
        lane: str = "live",
        account_key: Optional[str] = None,
        endpoint_class: Optional[str] = None,
        raise_on_ban: bool = False,
    ) -> None:
        """Acquire a rate-gate slot.

        Ban handling: if a process-wide IP ban is in effect, callers with
        ``raise_on_ban=True`` (the order/scan placement path) get a fast
        RateGateBanAbort so they can release locks and record a ban substatus.
        Background callers (default ``raise_on_ban=False`` — reconciler, AI
        manager, WS feeds, market data) instead WAIT OUT the ban (polling the
        breaker), so an IP ban gracefully PAUSES those loops rather than crashing
        them with a BaseException. The half-open probe admits exactly one of the
        waiters when the cooloff elapses.

        `lane` selects priority on the private channel:
        - 'order' — order placement / leverage. Highest priority: uses the FULL
          budget and the shortest backoff, so a real-money order is never delayed
          behind background traffic.
        - 'live' (default) — scanner/reconciler/AI-manager. Reserves a small
          headroom so it cannot consume the entire budget and starve 'order'.
        - 'mcp' — subordinate (reserves ~25% for live); MCP/sweep traffic.

        When `account_key` + `endpoint_class` are given AND the endpoint has a
        configured per-second cap, a SECOND per-account dimension is enforced in
        the SAME critical section as the channel dimension (all-or-none commit):
        a slot is taken only if BOTH dimensions have room; otherwise neither is
        charged and the caller backs off.
        """
        timestamps, max_budget, window = self._get_channel(channel)
        effective_budget = max_budget
        if lane == "mcp":
            # subordinate lane: leave headroom for live (reserve ~25%, >=1).
            effective_budget = max(1, int(max_budget * 0.75))
        elif lane == "live" and channel == "private" and max_budget > 4:
            # background live traffic leaves a SMALL fixed headroom (1 slot when
            # the budget is large enough) so order placement — which uses the full
            # budget — always has room ahead of it, without materially shrinking
            # the existing live budget.
            effective_budget = max_budget - 1
        # 'order' uses the full budget (no reservation against it).
        ep_cap = self._endpoint_caps.get(endpoint_class) if (account_key and endpoint_class) else None
        with self._lock:
            self._wait_count += 1
        try:
            while True:
                if self._ban_state() == "banned":
                    if raise_on_ban:
                        raise RateGateBanAbort(cooloff_until=self._ban_cooloff_until)
                    # Background caller: pause until the ban clears (or a probe slot
                    # opens) rather than crashing the loop. Bounded poll so a never-
                    # clearing ban can't hang forever silently — the caller's own
                    # loop will re-enter on the next tick.
                    await asyncio.sleep(min(1.0, self._BAN_POLL_INTERVAL))
                    continue
                with self._lock:
                    now = time.monotonic()
                    while timestamps and timestamps[0] < now - window:
                        timestamps.popleft()
                    channel_ok = len(timestamps) < effective_budget
                    ep_dq = None
                    ep_ok = True
                    ep_wait = 0.0
                    if ep_cap is not None:
                        ep_dq = self._endpoint_ts.get((account_key, endpoint_class))
                        if ep_dq is None:
                            ep_dq = collections.deque(maxlen=ep_cap + 50)
                            self._endpoint_ts[(account_key, endpoint_class)] = ep_dq
                        while ep_dq and ep_dq[0] < now - self._endpoint_window:
                            ep_dq.popleft()
                        ep_ok = len(ep_dq) < ep_cap
                        if not ep_ok:
                            ep_wait = ep_dq[0] - (now - self._endpoint_window) + 0.02
                    if channel_ok and ep_ok:
                        # all-or-none: commit to BOTH deques, or neither.
                        timestamps.append(now)
                        if ep_dq is not None:
                            ep_dq.append(now)
                        return
                    # compute backoff = max of the contended dimensions' waits
                    channel_wait = 0.0
                    if not channel_ok:
                        channel_wait = timestamps[0] - (now - window) + 0.05
                    sleep_time = max(channel_wait, ep_wait)
                # order lane backs off the least; mcp the most — so orders win.
                if lane == "order":
                    extra = 0.0
                elif lane == "mcp":
                    extra = 0.05
                else:
                    extra = 0.02
                await asyncio.sleep(max(0.02 if lane == "order" else 0.05, min(sleep_time, window)) + extra)
        finally:
            with self._lock:
                self._wait_count -= 1

    def acquire_sync(self, channel: str = "public", timeout: float = 10.0) -> bool:
        """Blocking variant of acquire for sync callers; returns False if it times out.

        Sync callers do not pass the per-account dimension (only async order/scan
        traffic does); this remains channel-only for backward compatibility.

        Ban handling: sync callers keep their bool contract — while the breaker is
        OPEN this returns ``False`` (treat as "couldn't acquire / skip") rather than
        raising, so the threaded data-fetch path degrades gracefully instead of
        throwing a BaseException out of a sync stack.
        """
        timestamps, max_budget, window = self._get_channel(channel)
        deadline = time.monotonic() + timeout
        with self._lock:
            self._wait_count += 1
        try:
            while time.monotonic() < deadline:
                if self._ban_state() == "banned":
                    time.sleep(min(0.5, self._BAN_POLL_INTERVAL))
                    continue
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
            with self._lock:
                self._wait_count -= 1


_gate: Optional[BybitRateGate] = None
_gate_init_lock = threading.Lock()


def get_rate_gate() -> BybitRateGate:
    """Return the process-wide BybitRateGate singleton, creating it on first use."""
    global _gate
    if _gate is None:
        with _gate_init_lock:
            if _gate is None:
                _gate = BybitRateGate()
    return _gate
