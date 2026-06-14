"""Post-scan placement-integrity detectors (TASK-3.5, NFR-008, R186).

Money-safety invariant monitors that run over the executor's recorded state AFTER the
parallelized tail, independent of the placement path. They are the regression net for
the highest-risk failure of the fan-out: a duplicate or over-cap placement that the
per-account partition is supposed to make impossible.

Two checks:
  * `find_duplicate_placements(executor)` — any (account_id, symbol) that appears more
    than once in an account's successful executions. Under the per-account partition
    this must be empty (the `traded` set + per-(account,symbol) lock prevent it).
  * `find_over_cap_accounts(executor)` — any account whose successful placements exceed
    its config's `max_trades`. The hard `max_trades` backstop in `_try_trade` must hold
    across the fan-out.

These return structured findings (never raise) so a caller can log a HIGH-severity
alert. `assert_placement_integrity(executor)` raises AssertionError with the findings —
used by tests + an optional post-tail self-check.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def find_duplicate_placements(executor: Any) -> List[Tuple[str, str, int]]:
    """Return [(account_id, symbol, count)] for any (account, symbol) placed >1 time
    successfully across ALL of an account's configs/states. Empty == healthy."""
    counts: Dict[Tuple[str, str], int] = {}
    for state in executor._state.values():
        aid = state.config.get("account_id", "")
        for e in state.executions:
            if e.status == "success":
                key = (aid, e.symbol)
                counts[key] = counts.get(key, 0) + 1
    return [(aid, sym, c) for (aid, sym), c in counts.items() if c > 1]


def find_over_cap_accounts(executor: Any) -> List[Tuple[str, int, int]]:
    """Return [(account_id, executed, max_trades)] for any CONFIG whose SUCCESSFUL
    placements exceed ITS OWN configured max_trades. Empty == healthy.

    Checks PER-CONFIG (per-state), not per-account-sum: the executor enforces the cap
    per state (``state.trades_executed >= cfg.max_trades`` in ``_try_trade``), so the
    detector must match that granularity — an account with cfgA(max=3) placing 5 and
    cfgB(max=3) placing 1 is a cfgA breach that a per-account sum (6 <= 6) would MASK.
    The returned account_id may repeat (one row per breaching config)."""
    findings: List[Tuple[str, int, int]] = []
    for state in executor._state.values():
        aid = state.config.get("account_id", "")
        if not aid:
            continue
        executed = sum(1 for e in state.executions if e.status == "success")
        cap = int(state.config.get("max_trades", 999))
        if executed > cap:
            findings.append((aid, executed, cap))
    return findings


def assert_placement_integrity(executor: Any) -> None:
    """Raise AssertionError if any duplicate or over-cap placement is found. A cheap
    post-tail self-check (money-safety regression detector)."""
    dups = find_duplicate_placements(executor)
    over = find_over_cap_accounts(executor)
    assert not dups, f"duplicate placements detected: {dups}"
    assert not over, f"over-cap placements detected: {over}"
