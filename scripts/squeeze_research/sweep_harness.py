"""Broad config sweep via the offline harness (drives the REAL engine).

The MCP sweep_run failed on a date-coercion bug in load_inputs; this runs the same
864-combo grid directly through BacktestService, which we've proven reproduces the
baseline bit-exact. Ranks by total return AND by a DD-constrained objective.

Runs sequentially (the service caps concurrency); ~each backtest is ~10-15s so we
keep the grid focused. Writes a CSV + prints the top configs.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

from scripts.squeeze_research.harness import BASE_CONFIG, build_service, run_one, summarize

# Focused grid: the knobs my research showed actually move results. take_profit
# (120 vs 150) and trailing (2 vs 3) barely mattered, so fix them and spend the
# budget on the high-impact axes. 4*3*2*3*3 = 216 combos.
SPACE = {
    "leverage": [5, 6, 7, 8],
    "capital_pct": [15, 18, 22],
    "max_trades": [3, 4],
    "max_drawdown_pct": [10, 12, 100],
    "target_goal_value": [12, 15, 18],
}

_CONCURRENCY = 3  # matches BacktestService _MAX_CONCURRENT


def combos(space):
    keys = list(space.keys())
    for vals in itertools.product(*[space[k] for k in keys]):
        yield dict(zip(keys, vals))


async def main():
    svc, db = await build_service()
    rows = []
    try:
        grid = list(combos(SPACE))
        print(f"running {len(grid)} combos through the REAL engine ({_CONCURRENCY}-way)...")
        # baseline reference
        base = summarize(await run_one(svc, BASE_CONFIG, None), "baseline")
        print(f"baseline: net={base['net_profit']:.2f} dd={base['max_dd_pct']:.2f}% "
              f"sharpe={base['sharpe']:.2f}")

        sem = asyncio.Semaphore(_CONCURRENCY)
        done_count = {"n": 0}

        async def one(i, ov):
            async with sem:
                cfg = dict(BASE_CONFIG); cfg.update(ov)
                try:
                    s = summarize(await run_one(svc, cfg, None), json.dumps(ov))
                    s["overrides"] = ov
                    rows.append(s)
                except Exception as exc:  # noqa: BLE001
                    print(f"  combo {i} failed: {exc}")
                done_count["n"] += 1
                if done_count["n"] % 25 == 0:
                    print(f"  ...{done_count['n']}/{len(grid)} done")

        await asyncio.gather(*[one(i, ov) for i, ov in enumerate(grid)])
        # write csv
        import csv
        out = "scripts/squeeze_research/sweep_results.csv"
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["net_profit", "net_pct", "max_dd_pct", "win_rate", "sharpe",
                        "profit_factor", "trades", "largest_loss"] + list(SPACE.keys()))
            for r in rows:
                w.writerow([r["net_profit"], r["net_profit_pct"], r["max_dd_pct"],
                            r["win_rate"], r["sharpe"], r["profit_factor"],
                            r["total_trades"], r["largest_loss"]]
                           + [r["overrides"][k] for k in SPACE.keys()])
        print(f"\nwrote {out} ({len(rows)} rows)\n")

        def top(metric, n=8, dd_cap=None, reverse=True):
            pool = [r for r in rows if r["net_profit"] is not None]
            if dd_cap is not None:
                pool = [r for r in pool if (r["max_dd_pct"] or 999) <= dd_cap]
            return sorted(pool, key=lambda r: r.get(metric) or -1e9, reverse=reverse)[:n]

        def show(title, items):
            print(f"=== {title} ===")
            print(f"  {'net$':>9}{'net%':>9}{'DD%':>8}{'win%':>7}{'shrp':>7}{'PF':>6}{'tr':>4}  config")
            for r in items:
                print(f"  {r['net_profit']:>9.1f}{r['net_profit_pct']:>9.1f}{r['max_dd_pct']:>8.2f}"
                      f"{r['win_rate']:>7.1f}{r['sharpe']:>7.1f}{r['profit_factor']:>6.2f}"
                      f"{r['total_trades']:>4}  {json.dumps(r['overrides'])}")
            print()

        show("TOP by NET PROFIT (any DD)", top("net_profit"))
        show("TOP by NET PROFIT, DD <= 18%", top("net_profit", dd_cap=18.0))
        show("TOP by SHARPE", top("sharpe"))
        print(f"baseline for reference: net={base['net_profit']:.1f} ({base['net_profit_pct']:.1f}%) "
              f"dd={base['max_dd_pct']:.2f}% sharpe={base['sharpe']:.2f}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
