"""Stage 1b: Resolve the ~$18 gap between closed-trade PnL (-1.64) and equity drop (-20).

Pull full high-freq equity trajectory, ESPORTS reconciliation state, wallet,
and cycle grouping. Read-only.
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, ACCT

def main():
    p("HIGH-FREQ EQUITY TRAJECTORY (every snapshot)")
    hf = run(prod_query("""
        select ts, round(equity::numeric,2) eq, round(unrealised_pnl::numeric,2) upnl,
               round(realised_pnl::numeric,2) rpnl, round(balance::numeric,2) bal,
               position_count pc
        from high_freq_snapshots where account_id=$1 order by ts asc
    """, ACCT))
    prev = None
    for r in hf:
        delta = ""
        if prev is not None:
            d = float(r['eq']) - float(prev)
            if abs(d) >= 1.0:
                delta = f"   <<< Δequity {d:+.2f}"
        print(f"{r['ts']}  eq={r['eq']:>7}  upnl={r['upnl']:>7}  rpnl={r['rpnl']:>7}  bal={r['bal']:>7}  pos={r['pc']}{delta}")
        prev = r['eq']

    p("ESPORTS TRADE — FULL ROW (is it reconciled?)")
    esp = run(prod_one("""
        select * from trades where account_id=$1 and symbol='ESPORTSUSDT'
    """, ACCT))
    print(json.dumps({k: str(v) for k,v in esp.items()}, indent=2) if esp else "none")

    p("TRADES GROUPED BY CYCLE (opened_at clustering)")
    rows = run(prod_query("""
        select symbol, side, status, round(net_pnl::numeric,3) net,
               opened_at, closed_at, close_reason, ai_closed
        from trades where account_id=$1 order by opened_at asc
    """, ACCT))
    for r in rows:
        print(f"{r['opened_at']}  {r['symbol']:<14} {r['side']:<5} {r['status']:<7} net={str(r['net']):>8} close={str(r['close_reason']):<16} ai={r['ai_closed']} closed={r['closed_at']}")

    p("WALLET-LEVEL: latest balances via daily + any account_snapshots")
    # daily_snapshots was empty; check what snapshot tables exist with rows for this acct
    for tbl in ["daily_snapshots", "account_snapshots", "high_freq_snapshots"]:
        try:
            c = run(prod_one(f"select count(*) c, max(ts::text) last from {tbl} where account_id=$1", ACCT))
            print(f"{tbl}: {c}")
        except Exception as e:
            try:
                c = run(prod_one(f"select count(*) c, max(snapshot_date::text) last from {tbl} where account_id=$1", ACCT))
                print(f"{tbl}: {c}")
            except Exception as e2:
                print(f"{tbl}: ERR {e2}")

    p("SUM CHECK: realized via trades vs equity drop")
    s = run(prod_one("""
        select round(sum(net_pnl)::numeric,3) closed_net,
               round(sum(case when status='closed' then net_pnl else 0 end)::numeric,3) only_closed
        from trades where account_id=$1
    """, ACCT))
    print(s)
    print("equity now ~79.59, started 100 (base trade #1 was 100.9) => drop ~ -20 to -21")

if __name__ == "__main__":
    main()
