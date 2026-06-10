"""Golden-master parity harness for the backtest engine (Phase P0).

The optimization phases (P1-P6) change HOW the backtester loads data, loops, and
stores klines — never WHAT the business rules decide. This module freezes the
CURRENT engine's output as a *stored-snapshot oracle*: a deterministic fingerprint
of `SimulationResult` that every later phase diffs against.

Two-part fingerprint (the parity contract):
  * DISCRETE fields (opened set, side, close_reason, exit-bar index, total_trades,
    selection order) must be **bit-identical** across every phase — these encode
    WHICH trades happened and WHY. A float refactor must never flip them.
  * MONEY fields (pnl, fees, equity curve) may differ only within a tight relative
    epsilon (float reassociation under numpy/numba), and must stay non-optimistic.

Also provides the three-way Σ reconciliation the legacy `_assert_reconciles`
lacked: Σ trade.pnl == metrics.net_profit == final_equity − starting_capital,
accumulated over recorded values, so a bug that corrupts one term but not the
others turns RED.

Pure + synchronous: no DB, no network. Mirrors `BacktestEngine.run`'s contract.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

# Money rounding for the MONEY fingerprint. 1e-6 absolute is far under the <1%
# parity budget and absorbs only float reassociation, not real divergence.
MONEY_DECIMALS = 6
# Relative tolerance when comparing MONEY fields across phases.
MONEY_REL_TOL = 1e-6
MONEY_ABS_FLOOR = 1e-6  # absolute floor for near-zero oracle values (avoid div-by-0 in rel)

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")


# --------------------------------------------------------------------------- #
# Canonicalization helpers
# --------------------------------------------------------------------------- #

def _canon_ts(v: Any) -> Any:
    """Datetimes → epoch-int (stable across tz-aware repr); pass through others."""
    if isinstance(v, datetime):
        return int(v.timestamp())
    return v


def _round_money(v: Any) -> Any:
    """Round a float money value; normalize -0.0 → 0.0; leave non-floats alone."""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return str(v)  # surface NaN/Inf explicitly instead of silently comparing
        r = round(v, MONEY_DECIMALS)
        return 0.0 if r == 0.0 else r  # kill signed zero
    return v


# Trade fields that are DISCRETE (must be bit-identical) vs MONEY (epsilon-tolerant).
# Derived from the engine's recorded trade dict (see _close_position / _trade_row_to_dict).
_DISCRETE_TRADE_FIELDS = (
    "symbol", "side", "close_reason", "leverage", "scan_id",
    "signal_score", "signal_confidence", "strategy_kind",
)
_MONEY_TRADE_FIELDS = (
    "entry_price", "exit_price", "qty", "pnl", "pnl_pct", "fees_paid",
    "mfe_pct", "mae_pct", "funding_paid",
)
_TIME_TRADE_FIELDS = ("entry_time", "exit_time")


def trade_fingerprint(trade: dict[str, Any]) -> dict[str, Any]:
    """Split a single trade into {discrete, money, time} fingerprint parts."""
    discrete = {k: trade.get(k) for k in _DISCRETE_TRADE_FIELDS}
    money = {k: _round_money(trade.get(k)) for k in _MONEY_TRADE_FIELDS}
    time = {k: _canon_ts(trade.get(k)) for k in _TIME_TRADE_FIELDS}
    return {"discrete": discrete, "money": money, "time": time}


# Metric keys that are DISCRETE (counts) vs MONEY. total_trades is the frontend
# trap (BacktestResultsPage routes to "no trades" if absent) — always present.
# Key names verified against live engine output (winners/losers, not *_trades).
_DISCRETE_METRIC_FIELDS = (
    "total_trades", "winners", "losers",
    "max_consecutive_wins", "max_consecutive_losses",
)
_MONEY_METRIC_FIELDS = (
    "net_profit", "net_profit_pct", "final_equity", "win_rate",
    "gross_profit", "gross_loss", "total_commission",
    "avg_win", "avg_trade", "expectancy", "max_dd_pct", "max_run_up_pct",
)


def fingerprint(result: Any) -> dict[str, Any]:
    """Build the full deterministic fingerprint of a SimulationResult.

    Shape:
      {
        "trades": [ {discrete, money, time}, ... ],   # ORDER-SENSITIVE (selection)
        "metrics": {"discrete": {...}, "money": {...}},
        "equity_curve": {"len": int, "money": [rounded equity points]},
        "n_trades": int,
      }
    """
    trades = list(getattr(result, "trades", []) or [])
    metrics = dict(getattr(result, "metrics", {}) or {})
    curve = list(getattr(result, "equity_curve", []) or [])

    md = {k: metrics.get(k) for k in _DISCRETE_METRIC_FIELDS}
    mm = {k: _round_money(metrics.get(k)) for k in _MONEY_METRIC_FIELDS}

    return {
        "n_trades": len(trades),
        "trades": [trade_fingerprint(t) for t in trades],
        "metrics": {"discrete": md, "money": mm},
        "equity_curve": {
            "len": len(curve),
            "money": [_round_money(p.get("equity")) for p in curve],
        },
    }


# --------------------------------------------------------------------------- #
# Comparison: DISCRETE bit-identical, MONEY within epsilon
# --------------------------------------------------------------------------- #

@dataclass
class DiffResult:
    ok: bool
    discrete_mismatches: list[str]
    money_mismatches: list[str]

    def __bool__(self) -> bool:
        return self.ok

    def summary(self) -> str:
        parts = []
        if self.discrete_mismatches:
            parts.append("DISCRETE: " + "; ".join(self.discrete_mismatches[:20]))
        if self.money_mismatches:
            parts.append("MONEY: " + "; ".join(self.money_mismatches[:20]))
        return " | ".join(parts) if parts else "identical"


def _money_close(a: Any, b: Any) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return a == b  # NaN/Inf sentinels compared literally
    if a is None or b is None:
        return a == b
    return abs(a - b) <= max(MONEY_ABS_FLOOR, MONEY_REL_TOL * max(abs(a), abs(b)))


def diff_fingerprints(expected: dict[str, Any], actual: dict[str, Any]) -> DiffResult:
    """Compare two fingerprints. DISCRETE must match exactly; MONEY within epsilon."""
    disc: list[str] = []
    money: list[str] = []

    if expected.get("n_trades") != actual.get("n_trades"):
        disc.append(f"n_trades {expected.get('n_trades')} != {actual.get('n_trades')}")

    et, at = expected.get("trades", []), actual.get("trades", [])
    for i in range(max(len(et), len(at))):
        if i >= len(et) or i >= len(at):
            disc.append(f"trade[{i}] presence mismatch")
            continue
        e, a = et[i], at[i]
        if e["discrete"] != a["discrete"]:
            disc.append(f"trade[{i}].discrete {e['discrete']} != {a['discrete']}")
        if e["time"] != a["time"]:
            disc.append(f"trade[{i}].time {e['time']} != {a['time']}")
        for k in e["money"]:
            if not _money_close(e["money"][k], a["money"].get(k)):
                money.append(f"trade[{i}].{k} {e['money'][k]} != {a['money'].get(k)}")

    em, am = expected.get("metrics", {}), actual.get("metrics", {})
    if em.get("discrete") != am.get("discrete"):
        disc.append(f"metrics.discrete {em.get('discrete')} != {am.get('discrete')}")
    for k in em.get("money", {}):
        if not _money_close(em["money"][k], am.get("money", {}).get(k)):
            money.append(f"metrics.{k} {em['money'][k]} != {am.get('money', {}).get(k)}")

    ec, ac = expected.get("equity_curve", {}), actual.get("equity_curve", {})
    if ec.get("len") != ac.get("len"):
        disc.append(f"equity_curve.len {ec.get('len')} != {ac.get('len')}")
    else:
        for i, (ev, av) in enumerate(zip(ec.get("money", []), ac.get("money", []))):
            if not _money_close(ev, av):
                money.append(f"equity_curve[{i}] {ev} != {av}")

    return DiffResult(ok=(not disc and not money), discrete_mismatches=disc, money_mismatches=money)


# --------------------------------------------------------------------------- #
# Snapshot persistence (stored-snapshot oracle, replaces magic numbers)
# --------------------------------------------------------------------------- #

def snapshot_path(name: str) -> str:
    return os.path.join(SNAPSHOT_DIR, f"{name}.json")


def save_snapshot(name: str, fp: dict[str, Any]) -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    with open(snapshot_path(name), "w", encoding="utf-8") as fh:
        json.dump(fp, fh, indent=2, sort_keys=True, default=str)


def load_snapshot(name: str) -> Optional[dict[str, Any]]:
    p = snapshot_path(name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def assert_matches_snapshot(name: str, result: Any) -> None:
    """Assert a result matches its stored snapshot. If absent, capture it (first run).

    On capture the assert is a no-op for that run — CI must run twice OR the
    snapshot must be committed (we commit snapshots, so capture happens once in
    the authoring session and the file is the oracle thereafter).
    """
    fp = fingerprint(result)
    expected = load_snapshot(name)
    if expected is None:
        save_snapshot(name, fp)
        return
    diff = diff_fingerprints(expected, fp)
    assert diff.ok, f"golden snapshot '{name}' diverged: {diff.summary()}"


# --------------------------------------------------------------------------- #
# Three-way Σ reconciliation (the term the legacy _assert_reconciles lacked)
# --------------------------------------------------------------------------- #

def assert_reconciles(result: Any, starting_capital: float, *, abs_tol: float = 1e-6) -> None:
    """Three-way invariant on EVERY fixture:

        Σ trade.pnl  ==  metrics.net_profit  ==  final_equity − starting_capital

    The legacy harness only checked the 2nd == 3rd. Adding the per-trade sum (1st)
    catches a bug that corrupts net_profit AND final_equity together but leaves the
    recorded trade pnls correct (or vice-versa). Holds under liquidation, negative
    funding, force-close, and basket-flatten terms combined.
    """
    metrics = result.metrics
    trades = result.trades or []
    net_profit = float(metrics["net_profit"])
    final_equity = float(metrics["final_equity"])
    sum_pnl = sum(float(t.get("pnl", 0.0)) for t in trades)

    # 2nd == 3rd (legacy invariant)
    assert abs(net_profit - (final_equity - starting_capital)) <= abs_tol, (
        f"net_profit {net_profit} != final_equity-start "
        f"{final_equity - starting_capital}"
    )
    # 1st == 2nd (the added per-trade-sum cross-check)
    assert abs(sum_pnl - net_profit) <= max(abs_tol, MONEY_REL_TOL * max(1.0, abs(net_profit))), (
        f"Σ trade.pnl {sum_pnl} != net_profit {net_profit} "
        f"(per-trade-sum reconciliation — the term legacy _assert_reconciles lacked)"
    )
