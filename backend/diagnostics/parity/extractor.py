"""Build the live-selection oracle (ordered Cycles) from trade rows."""
from __future__ import annotations
from typing import Any, Mapping
from backend.diagnostics.parity.models import LiveTrade, Cycle


def build_cycles(trade_rows: list[Mapping[str, Any]]) -> list[Cycle]:
    """Group CLOSED trade rows into chronological Cycles keyed by scan_id.

    Open trades (status != 'closed' or closed_at is None) are excluded — parity is
    measured over fully-closed cycles only.
    """
    by_scan: dict[str, list[LiveTrade]] = {}
    meta: dict[str, tuple] = {}  # scan_id -> (signal_time, base_capital)
    for r in trade_rows:
        if r.get("status") != "closed" or r.get("closed_at") is None:
            continue
        sid = r["scan_id"]
        by_scan.setdefault(sid, []).append(LiveTrade(
            symbol=r["symbol"], side=r["side"],
            net_pnl=float(r["net_pnl"]) if r.get("net_pnl") is not None else 0.0,
            close_reason=r.get("close_reason") or "",
            entry_price=float(r["entry_price"]),
            exit_price=float(r["exit_price"]) if r.get("exit_price") is not None else None,
            scan_result_id=r.get("scan_result_id"),
            opened_at=r["opened_at"], closed_at=r["closed_at"],
        ))
        if sid not in meta:
            meta[sid] = (r["signal_time"], float(r["base_capital"]))

    cycles = [
        Cycle(scan_id=sid, signal_time=meta[sid][0], base_capital=meta[sid][1],
              live_trades=sorted(trades, key=lambda t: t.opened_at))
        for sid, trades in by_scan.items()
    ]
    cycles.sort(key=lambda c: c.signal_time)
    return cycles


def live_final_equity(cycles: list[Cycle]) -> float:
    """First cycle's base_capital + Σ net_pnl across all closed trades.

    base_capital compounds prior realized PnL, so this equals the last cycle's
    base_capital + its own net_pnl — computed additively for robustness.
    """
    if not cycles:
        return 0.0
    start = cycles[0].base_capital
    return start + sum(c.live_net_pnl for c in cycles)
