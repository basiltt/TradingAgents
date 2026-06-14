"""Process-level mirror of the post-scan-optimization revert kill-switches.

The Bybit rate gate and client run on hot, partly-synchronous paths and cannot
do a per-request DB read. This module holds a lightweight in-process snapshot of
the three revert flags, refreshed periodically from feature_kill_switches by a
background task (see main.py). Reads are lock-free and O(1).

Polarity (PR2-2): a flag is "active" (the corrected behavior) UNLESS reverted.
- channel_fix_reverted: True  => charge every call to the private channel (old behavior)
- per_endpoint_limiter_reverted: True => skip the per-account/endpoint sub-limiter
- fanout_disabled: True => force the post-scan tail to run sequentially (width=1)

Default (no refresh yet / fresh process): all reverts False => corrected behavior
active. A DB read failure during refresh fails CLOSED to the safe state, which for
these correctness fixes is "keep them active" (do NOT revert on a transient blip) —
the gate's own per-channel caps remain a hard backstop regardless.
"""

from __future__ import annotations

from typing import Any

from backend.services import features as _feat

# Module-level snapshot. Plain bools => lock-free reads.
_channel_fix_reverted = False
_per_endpoint_limiter_reverted = False
_fanout_disabled = False


def channel_fix_active() -> bool:
    """True when the public/private channel classification is in effect."""
    return not _channel_fix_reverted


def per_endpoint_limiter_active() -> bool:
    """True when the per-account/endpoint sub-limiter is in effect."""
    return not _per_endpoint_limiter_reverted


def fanout_disabled() -> bool:
    """True when the post-scan tail must run sequentially (revert switch on)."""
    return _fanout_disabled


def apply_snapshot(kill: dict[str, bool]) -> None:
    """Update the process snapshot from a feature_kill_switches dict.

    Called by the periodic refresher with the result of read_kill_switches().
    These revert flags read their OWN key ONLY — they are deliberately NOT coupled
    to the master "__all__" kill (which governs the regime features). Reverting an
    infra-level correctness fix is an explicit, separate operator action; a master
    regime-kill must not silently disable the channel fix / sub-limiter.
    """
    global _channel_fix_reverted, _per_endpoint_limiter_reverted, _fanout_disabled
    _channel_fix_reverted = bool(kill.get(_feat.FEATURE_RATE_GATE_CHANNEL_FIX, False))
    _per_endpoint_limiter_reverted = bool(kill.get(_feat.FEATURE_RATE_GATE_PER_ENDPOINT_LIMITER, False))
    _fanout_disabled = bool(kill.get(_feat.FEATURE_POST_SCAN_FANOUT_DISABLED, False))


async def refresh_from_db(db: Any) -> None:
    """Read feature_kill_switches once and apply the snapshot. Never raises.

    A transient DB error makes read_kill_switches() return the fail-closed sentinel
    ``{"__all__": True}``; because the revert flags read their own keys (not
    "__all__"), that sentinel leaves the corrected behavior ACTIVE — i.e. a DB blip
    does NOT silently revert the fixes (the gate's per-channel caps remain the hard
    backstop regardless). Only an explicit ``<flag>=true`` row reverts.
    """
    try:
        from backend.services.kill_switch import read_kill_switches
        kill = await read_kill_switches(db)
        apply_snapshot(kill)
    except Exception:  # pragma: no cover - defensive
        pass


def reset_for_tests() -> None:
    """Reset all reverts to inactive (corrected behavior). Test helper."""
    global _channel_fix_reverted, _per_endpoint_limiter_reverted, _fanout_disabled
    _channel_fix_reverted = False
    _per_endpoint_limiter_reverted = False
    _fanout_disabled = False
