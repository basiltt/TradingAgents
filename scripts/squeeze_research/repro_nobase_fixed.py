"""Verify the FIXED sweep path: NO base passed, just space + starting_capital +
window. Drives the real _execute_sweep with base_cfg seeded (as sweep_run now
does) and confirms it completes 4/4 instead of KeyError->failed."""
from __future__ import annotations

import asyncio

from scripts.squeeze_research.harness import BASE_CONFIG, build_service


async def main() -> None:
    svc, db = await build_service()
    try:
        from backend.mcp.repositories.sweep_repo import SweepRepository
        from backend.mcp.tools.optimizer.sweep_tools import SweepRunIn, _execute_sweep

        repo = SweepRepository(db.pool)
        load_cfg = {
            **BASE_CONFIG,
            "scan_source": {"mode": "schedule",
                            "schedule_id": "d9c5f14f-a71f-4907-9449-dab3b75a52cb"},
        }
        signals, snapshot, instrument_info = await svc.load_inputs(load_cfg)
        print(f"load_inputs OK: {len(signals)} signals")

        space = {"capital_pct": [22], "leverage": [7, 8], "max_trades": [3, 4]}
        # EXACT live no-base call: args.base is None
        args = SweepRunIn(
            space=space, objective="sharpe", strategy="grid", base=None,
            date_range_start="2026-06-04T18:30:00Z",
            date_range_end="2026-06-13T03:00:00Z",
            scan_source=load_cfg["scan_source"], starting_capital=234.0,
        )
        # sweep_run seeds this before launching the bg task:
        base_cfg = dict(args.base or {})
        base_cfg.setdefault("starting_capital", args.starting_capital)
        print("resolved base_cfg:", base_cfg)

        sweep_id = await repo.create_job(
            strategy="grid", param_space=space, objective_metric="sharpe", total_combos=4,
        )
        await _execute_sweep(
            sweep_id=sweep_id, repo=repo, runner=svc, args=args,
            signals=signals, snapshot=snapshot, instrument_info=instrument_info,
            manager=None, base_cfg=base_cfg,
        )
        job = await repo.get_job(sweep_id)
        print("FINAL STATUS:", job.get("status"),
              "completed:", job.get("completed_combos"), "/", job.get("total_combos"))
        print("error_message:", job.get("error_message"))
        rows = await repo.results(sweep_id, limit=10)
        print(f"stored results: {len(rows)}")
        for r in sorted(rows, key=lambda x: (x.get("result_rank") or 99)):
            m = r.get("metrics") or {}
            c = r.get("config") or {}
            print(f"  rank={r.get('result_rank')} lev={c.get('leverage')} "
                  f"mt={c.get('max_trades')} sc={c.get('starting_capital')} "
                  f"sharpe={m.get('sharpe')} net%={m.get('net_profit_pct')} "
                  f"trades={m.get('total_trades')}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
