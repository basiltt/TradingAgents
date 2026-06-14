"""Reproduce the EXACT MCP sweep execution path offline to capture the real error.

The MCP sweep does:  load_inputs(window)  ->  run_one(combo, signals, snapshot, instr)
NOT _execute_backtest. So this isolates whatever the sweep combos hit.
"""
from __future__ import annotations

import asyncio
import traceback

from scripts.squeeze_research.harness import BASE_CONFIG, build_service


async def main() -> None:
    svc, db = await build_service()
    try:
        # 1) load_inputs exactly like sweep_run/optimize_config now do (datetimes)
        load_cfg = {
            **{k: v for k, v in BASE_CONFIG.items()},
            "scan_source": {"mode": "schedule",
                            "schedule_id": "d9c5f14f-a71f-4907-9449-dab3b75a52cb"},
        }
        print("calling load_inputs ...")
        try:
            signals, snapshot, instrument_info = await svc.load_inputs(load_cfg)
        except Exception:
            print("LOAD_INPUTS RAISED:")
            traceback.print_exc()
            return
        print(f"load_inputs OK: {len(signals)} signals, "
              f"{len(snapshot)} symbols in snapshot, "
              f"{len(instrument_info)} instrument entries")

        if not signals:
            print("!! zero signals -> sweep would have nothing to run")
            return

        # 2) run ONE combo exactly like the sweep runner does
        combo = {**BASE_CONFIG, "leverage": 7, "capital_pct": 22.0, "max_trades": 4}
        print("calling run_one (combo lev7/cap22/mt4) ...")
        try:
            metrics = await svc.run_one(combo, signals, snapshot, instrument_info,
                                        deadline=None)
            print("run_one OK. metrics keys:", sorted(metrics.keys())[:12])
            print("  net_profit:", metrics.get("net_profit"),
                  " net%:", metrics.get("net_profit_pct"),
                  " dd%:", metrics.get("max_dd_pct"),
                  " trades:", metrics.get("total_trades"),
                  " sharpe:", metrics.get("sharpe"))
        except Exception:
            print("RUN_ONE RAISED:")
            traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
