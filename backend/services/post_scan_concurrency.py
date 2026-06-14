"""Process-wide account-concurrency primitive for the post-scan tail (TASK-2.3).

Phase 2 fans the per-account post-scan work out under a SINGLE process-wide
``asyncio.Semaphore`` so that an auto tail, a manual re-run, and a scheduled scan
that overlap in time share one concurrency budget against Bybit's private channel
(they hit the same IP). The default width is **1** — the executor's parallel path
is byte-identical to the old sequential path at width 1 (proven by the Phase-2
golden-equality test), so shipping at 1 is a no-op until an operator opts in.

Two facilities:
  * ``get_account_semaphore()`` — the shared limiter. Width comes from
    ``configure_account_concurrency`` (FR-049-clamped) and is forced to 1 whenever
    the ``post_scan_fanout_disabled`` revert kill-switch is on.
  * a ``scan_id``-keyed single-flight registry (``try_begin_tail`` / ``end_tail``)
    so an auto tail and a manual re-run for the SAME scan cannot run concurrently
    (they would double-place). This complements the router's ``_in_flight_auto_trades``
    (which guards only the manual path) by covering BOTH entry points centrally.

Loop-binding note: an ``asyncio.Semaphore`` binds to the loop that is running when
it is first awaited. The backend runs one long-lived loop, but pytest-asyncio
creates a fresh loop per test, so a naive module-singleton would raise
"bound to a different event loop". We therefore stamp the semaphore with the loop
that created it and recreate it transparently when the running loop changes (or the
width changes). This is safe in production (one loop => created once) and correct
under tests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Set

from backend.services import post_scan_flags

logger = logging.getLogger(__name__)

# FR-049 bounds. Width is an operator knob; clamp hard so a fat-fingered config
# can neither stall the tail (0) nor blow past a sane private-channel ceiling.
MIN_WIDTH = 1
MAX_WIDTH = 16
DEFAULT_WIDTH = 1

_configured_width: int = DEFAULT_WIDTH

_semaphore: Optional[asyncio.Semaphore] = None
_semaphore_loop: Optional[asyncio.AbstractEventLoop] = None
_semaphore_width: Optional[int] = None

# scan_id-keyed single-flight set. Plain set guarded by the GIL on sync ops; the
# begin/end calls are synchronous and never await, so no async lock is needed.
_in_flight_tails: Set[str] = set()


def configure_account_concurrency(width: object) -> int:
    """Set the desired account-concurrency width, clamped to [MIN_WIDTH, MAX_WIDTH].

    Returns the effective configured width. Never raises — a non-numeric value
    falls back to DEFAULT_WIDTH (1) so a bad config degrades to the safe sequential
    path rather than aborting startup.
    """
    global _configured_width
    try:
        w = int(width)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        w = DEFAULT_WIDTH
    if w < MIN_WIDTH:
        w = MIN_WIDTH
    elif w > MAX_WIDTH:
        w = MAX_WIDTH
    _configured_width = w
    return w


def configured_width() -> int:
    """The configured width, ignoring the kill-switch (for observability)."""
    return _configured_width


def effective_width() -> int:
    """The width actually used right now: the configured width, forced to 1 when
    the ``post_scan_fanout_disabled`` revert kill-switch is on."""
    if post_scan_flags.fanout_disabled():
        return 1
    return _configured_width


def get_account_semaphore() -> asyncio.Semaphore:
    """Return the shared account-concurrency semaphore for the running loop.

    Recreates the semaphore when (a) the running event loop differs from the one it
    was bound to, or (b) the effective width changed. Both are O(1) checks on the
    hot path's cold edge (once per fan-out, not per acquire).

    KNOWN LIMITATION (accepted, low risk): if an operator changes the width (or flips
    the fanout_disabled kill-switch) WHILE two tails for DIFFERENT scans are already
    fanning out, the in-flight tails keep their captured semaphore object while the
    next call here creates a new one at the new width — so transiently up to
    old_width + new_width placements can be in flight against the one Bybit IP. This
    is NOT a double-placement risk (each placement is still per-(account,symbol)
    locked); it is a brief over-concurrency that can only nudge the IP-bound rate.
    A single fan-out captures the semaphore ONCE (see _fan_out_by_account) so within
    one tail the bound is exact. Mitigation deferred — width changes are a rare manual
    operator action; the per-channel rate-gate caps remain the hard backstop."""
    global _semaphore, _semaphore_loop, _semaphore_width
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    width = effective_width()
    if _semaphore is None or _semaphore_loop is not loop or _semaphore_width != width:
        _semaphore = asyncio.Semaphore(width)
        _semaphore_loop = loop
        _semaphore_width = width
    return _semaphore


def try_begin_tail(scan_id: str) -> bool:
    """Claim the single-flight slot for ``scan_id``'s post-scan tail.

    Returns True if the caller now owns the tail for this scan; False if a tail for
    the same scan is already running (the caller must NOT run the tail). Pair every
    True with exactly one ``end_tail`` in a finally.
    """
    if not scan_id:
        # No scan id (shouldn't happen on the tail path) — don't gate; let it run.
        return True
    if scan_id in _in_flight_tails:
        logger.info("post_scan_tail_single_flight_block", extra={"scan_id": scan_id})
        return False
    _in_flight_tails.add(scan_id)
    return True


def end_tail(scan_id: str) -> None:
    """Release the single-flight slot for ``scan_id``. Idempotent."""
    _in_flight_tails.discard(scan_id)


def is_tail_in_flight(scan_id: str) -> bool:
    return scan_id in _in_flight_tails


def reset_for_tests() -> None:
    """Reset all module state (width, semaphore, single-flight set). Test helper."""
    global _configured_width, _semaphore, _semaphore_loop, _semaphore_width
    _configured_width = DEFAULT_WIDTH
    _semaphore = None
    _semaphore_loop = None
    _semaphore_width = None
    _in_flight_tails.clear()
