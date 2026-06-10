"""Selection shim: pin the engine's input signals to live's actual trades."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import Cycle


def pin_signals(
    signals: list[Mapping[str, Any]],
    cycles: list[Cycle],
    return_missing: bool = False,
):
    """Filter `signals` to only those matching a pinned (scan_id, ticker, side).

    `signals` items are engine signal dicts (keys: scan_id, ticker, direction,
    score, signal_time, ...). `cycles` carries the pinned (symbol, lower-side) per
    scan. Matching normalizes side/direction to lowercase. Signals for scans with
    no cycle are dropped. If return_missing, also returns the set of pinned keys
    that had no matching signal (a data-integrity surface, never silent).
    """
    pinned_by_scan: dict[str, set[tuple[str, str]]] = {}
    for c in cycles:
        pinned_by_scan.setdefault(c.scan_id, set()).update(c.pinned_set)

    out: list[Mapping[str, Any]] = []
    matched: set[tuple[str, str, str]] = set()
    for s in signals:
        sid = s.get("scan_id")
        pins = pinned_by_scan.get(sid)
        if not pins:
            continue
        key = (s.get("ticker"), str(s.get("direction", "")).lower())
        if key in pins:
            out.append(s)
            matched.add((sid, key[0], key[1]))

    if not return_missing:
        return out

    missing: set[tuple[str, str, str]] = set()
    for sid, pins in pinned_by_scan.items():
        for sym, side in pins:
            if (sid, sym, side) not in matched:
                missing.add((sid, sym, side))
    return out, missing
