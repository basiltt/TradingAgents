"""Reproduce the FULL MCP _execute_sweep background path offline, with the real
SweepRepository + real BacktestService runner, and surface the exception that
_execute_sweep swallows into a bare 'failed' status (no traceback server-side)."""
from __future__ import annotations

import asyncio
import traceback

from scripts.squeeze_research.harness import BASE_CONFIG, build_service


async def main() -> None:
    svc, db = await build_service()
    try:
        from backend.mcp.repositories.sweep_repo import SweepRepository
        from backend.mcp.tools.optimizer.sweep_tools import SweepRunIn, _execute_sweep

        repo = SweepRepository(db.pool)

        # 1) load inputs exactly like sweep_run's foreground does (coerced dates)
        load_cfg = {
            **BASE_CONFIG,
            "scan_source": {"mode": "schedule",
                            "schedule_id": "d9c5f14f-a71f-4907-9449-dab3b75a52cb"},
        }
        signals, snapshot, instrument_info = await svc.load_inputs(load_cfg)
        print(f"load_inputs OK: {len(signals)} signals, {len(snapshot)} symbols")

        # 2) create a real job row
        space = {"capital_pct": [22], "leverage": [7, 8], "max_trades": [3, 4]}
        sweep_id = await repo.create_job(
            strategy="grid", param_space=space, objective_metric="sharpe",
            total_combos=4,
        )
        print("created sweep job:", sweep_id)

        # 3) drive the EXACT background body. Wrap so we see any raised error AND
        #    then read back the job status the body recorded.
        args = SweepRunIn(
            space=space, objective="sharpe", strategy="grid",
            base=dict(BASE_CONFIG),
            date_range_start="2026-06-04T18:30:00Z",
            date_range_end="2026-06-13T03:00:00Z",
            scan_source=load_cfg["scan_source"], starting_capital=234.0,
        )
        print("running _execute_sweep ...")
        try:
            await _execute_sweep(
                sweep_id=sweep_id, repo=repo, runner=svc, args=args,
                signals=signals, snapshot=snapshot, instrument_info=instrument_info,
                manager=None,
            )
        except Exception:
            print("_execute_sweep RAISED (unexpected — it usually swallows):")
            traceback.print_exc()

        job = await repo.get_job(sweep_id)
        print("FINAL JOB STATUS:", job.get("status"),
              "completed:", job.get("completed_combos"), "/", job.get("total_combos"))

        # If it failed, re-run the loop body INLINE with NO swallowing to expose
        # the real exception the production code hides.
        if job.get("status") == "failed":
            print("\n=== INLINE re-run of the combo loop (no swallow) ===")
            from backend.mcp.tools.optimizer.combos import config_hash, generate_combos
            from backend.mcp.tools.optimizer.ranker import _objective_value

            sweep_id2 = await repo.create_job(
                strategy="grid", param_space=space, objective_metric="sharpe",
                total_combos=4,
            )
            combos = generate_combos(space, strategy="grid", base=dict(BASE_CONFIG),
                                     n=100, seed=0)
            print(f"generated {len(combos)} combos")
            for i, cfg in enumerate(combos):
                h = config_hash(cfg)
                print(f"  combo {i}: hash={h[:10]} lev={cfg.get('leverage')} "
                      f"cap={cfg.get('capital_pct')} mt={cfg.get('max_trades')}")
                metrics = await svc.run_one(cfg, signals, snapshot, instrument_info,
                                            deadline=None)
                print(f"    run_one -> sharpe={metrics.get('sharpe')} "
                      f"net%={metrics.get('net_profit_pct')} trades={metrics.get('total_trades')}")
                obj = _objective_value(metrics, "sharpe")
                print(f"    objective_value={obj!r}")
                await repo.write_result(
                    sweep_id=sweep_id2, config=cfg, config_hash=h,
                    metrics=metrics, objective_value=obj,
                )
                print("    write_result OK")
            print("INLINE LOOP COMPLETED — all 4 combos persisted")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
