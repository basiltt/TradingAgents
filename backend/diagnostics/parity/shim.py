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
    first_open_by_scan: dict[str, Any] = {}
    for c in cycles:
        pinned_by_scan.setdefault(c.scan_id, set()).update(c.pinned_set)
        opens = [t.opened_at for t in c.live_trades if t.opened_at is not None]
        if opens:
            first_open_by_scan[c.scan_id] = min(opens)

    out: list[Mapping[str, Any]] = []
    matched: set[tuple[str, str, str]] = set()
    for s in signals:
        sid = s.get("scan_id")
        pins = pinned_by_scan.get(sid)
        if not pins:
            continue
        key = (s.get("ticker"), str(s.get("direction", "")).lower())
        if key in pins:
            rec = dict(s)
            # In selective replay, membership is pinned from live trades. The decision
            # instant should therefore be the account's actual order-placement cycle,
            # not the scan completion timestamp, which can precede live entry by
            # several minutes and produce stale fills on fast-moving symbols.
            if sid in first_open_by_scan:
                rec["signal_time"] = first_open_by_scan[sid]
            out.append(rec)
            matched.add((sid, key[0], key[1]))

    if not return_missing:
        return out

    missing: set[tuple[str, str, str]] = set()
    for sid, pins in pinned_by_scan.items():
        for sym, side in pins:
            if (sid, sym, side) not in matched:
                missing.add((sid, sym, side))
    return out, missing
