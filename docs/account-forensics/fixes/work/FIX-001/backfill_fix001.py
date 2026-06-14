"""FIX-001 backfill (DRY-RUN by default).

Corrects the 2 trades zeroed by the closed-PnL window bug, writing EXACTLY what the
fixed reconciler would write. Verified against the live Bybit closed-PnL API:
totalEntryFee/totalExitFee are NULL for these demo records, so the reconciler's math
(`fees = entry_fee + exit_fee`; `net_pnl = closedPnl - fees`) yields fees=0 and
net_pnl = closedPnl. We therefore set net_pnl = realized_pnl = closedPnl, exit_price =
avgExitPrice, fees = 0 — mirroring reconcile_close on the real match path.

Run:  python backfill_fix001.py            # dry-run, prints planned updates
      python backfill_fix001.py --apply    # performs the UPDATE on prod
"""
import sys; sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, PROD_DSN
import asyncpg, asyncio

APPLY = "--apply" in sys.argv

async def fetch_targets():
    c = await asyncpg.connect(PROD_DSN)
    try:
        rows = await c.fetch("""
            select t.id, t.account_id, a.label, t.symbol, t.side,
                   t.entry_price::float8 entry, t.qty::float8 qty,
                   t.fees::float8 cur_fees, t.net_pnl::float8 cur_net, t.exit_price::float8 cur_exit,
                   t.stop_loss_price::float8 sl, t.take_profit_price::float8 tp,
                   cpr.avg_exit_price::float8 exit_px, cpr.closed_pnl::float8 raw_pnl
            from trades t
            join trading_accounts a on a.id = t.account_id
            join lateral (
                select avg_exit_price, closed_pnl
                from closed_pnl_records r
                where r.account_id = t.account_id and r.symbol = t.symbol
                order by r.created_time desc limit 1
            ) cpr on true
            where t.status='closed' and t.exit_price = 0 and t.close_reason='external'
        """)
        return [dict(r) for r in rows]
    finally:
        await c.close()

async def apply_updates(plans):
    c = await asyncpg.connect(PROD_DSN)
    try:
        async with c.transaction():
            for pl in plans:
                await c.execute("""
                    update trades set exit_price=$1, realized_pnl=$2, realized_pnl_pct=$3,
                           fees=$4, net_pnl=$5, close_reason=$6, updated_at=now()
                    where id=$7 and account_id=$8 and status='closed' and exit_price=0
                """, pl["exit_px"], pl["raw_pnl"], pl["pnl_pct"], pl["fees"],
                     pl["net_pnl"], pl["close_reason"], pl["id"], pl["account_id"])
        return True
    finally:
        await c.close()

def _infer_close_reason(exit_px, sl, tp):
    # mirror PositionReconciler._infer_close_reason for a market exit
    if tp and exit_px > 0 and abs(exit_px - tp) / tp < 0.005:
        return "take_profit"
    if sl and exit_px > 0 and abs(exit_px - sl) / sl < 0.005:
        return "stop_loss"
    return "external"

def main():
    targets = run(fetch_targets())
    p(f"FIX-001 BACKFILL — {len(targets)} target row(s)  [{'APPLY' if APPLY else 'DRY-RUN'}]")
    plans = []
    for t in targets:
        fees = 0.0  # Bybit reports null entry/exit fees for these records → reconciler fees=0
        net = t["raw_pnl"] - fees
        pnl_pct = round((t["raw_pnl"] / (t["entry"] * t["qty"]) * 100), 6) if t["entry"] and t["qty"] else 0.0
        close_reason = _infer_close_reason(t["exit_px"], t["sl"], t["tp"])
        plan = {**t, "fees": fees, "net_pnl": net, "pnl_pct": pnl_pct, "close_reason": close_reason}
        plans.append(plan)
        print(f"\n  {t['label']:<16} {t['symbol']} {t['side']}  trade_id={t['id']}")
        print(f"    BEFORE: exit_price={t['cur_exit']} net_pnl={t['cur_net']} fees={t['cur_fees']} close=external")
        print(f"    AFTER : exit_price={t['exit_px']} realized_pnl={t['raw_pnl']} fees={fees} "
              f"net_pnl={net} pnl_pct={pnl_pct}% close_reason={close_reason}")
        print(f"            (SL={t['sl']} exit={t['exit_px']} → {close_reason})")
    if not plans:
        print("  nothing to backfill (already healed?)")
        return
    if APPLY:
        ok = run(apply_updates(plans))
        print(f"\n  APPLIED: {ok}. Re-verifying...")
        after = run(fetch_targets())
        print(f"  remaining exit_price=0 external rows: {len(after)} (expect 0)")
    else:
        print("\n  DRY-RUN only. Re-run with --apply to write these to prod.")

if __name__ == "__main__":
    main()
