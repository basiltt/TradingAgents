"""Reproduce the LIVE sweep_run call EXACTLY: NO base, just space + starting_capital
arg + window. This matches the MCP call that keeps failing, to find the real cause
that the full-base repro (repro_execute_sweep) masked."""
from __future__ import annotations

import asyncio
import traceback

from scripts.squeeze_research.harness import BASE_CONFIG, build_service


async def main() -> None:
    svc, db = await build_service()
    try:
        from backend.mcp.tools.optimizer.combos import generate_combos

        load_cfg = {
            **BASE_CONFIG,
            "scan_source": {"mode": "schedule",
                            "schedule_id": "d9c5f14f-a71f-4907-9449-dab3b75a52cb"},
        }
        signals, snapshot, instrument_info = await svc.load_inputs(load_cfg)
        print(f"load_inputs OK: {len(signals)} signals, {len(snapshot)} symbols")

        # EXACTLY what sweep_run builds when no `base` is passed:
        #   base_cfg = dict(args.base or {})  -> {}
        #   combos = generate_combos(space, base={}, ...)
        space = {"capital_pct": [22], "leverage": [7, 8], "max_trades": [3, 4]}
        base_cfg = {}  # <-- live call passed no base
        combos = generate_combos(space, strategy="grid", base=base_cfg, n=100, seed=0)
        print(f"generated {len(combos)} combos; first combo keys = {sorted(combos[0].keys())}")

        cfg = combos[0]
        print("running run_one on combo:", cfg)
        try:
            metrics = await svc.run_one(cfg, signals, snapshot, instrument_info, deadline=None)
            print("run_one OK -> trades:", metrics.get("total_trades"),
                  "net%:", metrics.get("net_profit_pct"))
        except Exception:
            print("RUN_ONE RAISED (this is the live failure):")
            traceback.print_exc()

        # Candidate fix A: seed ONLY starting_capital (like optimize_config's setdefault).
        print("\n=== FIX-A: base_cfg gets starting_capital only ===")
        base_a = {"starting_capital": 234.0}
        combos_a = generate_combos(space, strategy="grid", base=base_a, n=100, seed=0)
        cfg_a = combos_a[0]
        print("combo keys:", sorted(cfg_a.keys()))
        try:
            m = await svc.run_one(cfg_a, signals, snapshot, instrument_info, deadline=None)
            print(f"  run_one OK -> trades={m.get('total_trades')} "
                  f"net%={m.get('net_profit_pct')} dd%={m.get('max_dd_pct')} "
                  f"sharpe={m.get('sharpe')}")
        except Exception:
            traceback.print_exc()

        # Reference: full BASE_CONFIG overlaid (what a complete config produces).
        print("\n=== REF: full BASE_CONFIG base ===")
        base_full = {k: v for k, v in BASE_CONFIG.items()
                     if k not in ("date_range_start", "date_range_end", "scan_source")}
        combos_full = generate_combos(space, strategy="grid", base=base_full, n=100, seed=0)
        cfg_full = combos_full[0]
        try:
            m = await svc.run_one(cfg_full, signals, snapshot, instrument_info, deadline=None)
            print(f"  run_one OK -> trades={m.get('total_trades')} "
                  f"net%={m.get('net_profit_pct')} dd%={m.get('max_dd_pct')} "
                  f"sharpe={m.get('sharpe')}")
        except Exception:
            traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
