"""Stage 3b: Does alphabetical position correlate with account performance?
If 'U = low priority' caused losses, late-alphabet accounts should underperform.
Compare per-account realized PnL + equity vs alphabetical rank. Read-only.
"""
from __future__ import annotations
import sys, datetime as dt
sys.path.insert(0, ".")
from _prod import prod_query, run, p

EPOCH = dt.datetime(2026,6,13,17,0,0,tzinfo=dt.timezone.utc)

def main():
    accts = run(prod_query("select id,label from trading_accounts where is_active=1 and label like '%Demo%' order by label"))
    p("PER-ACCOUNT PERFORMANCE vs ALPHABETICAL RANK (since epoch reset)")
    print(f"{'rank':<5}{'account':<18}{'ledger_net':<12}{'cur_equity':<12}{'trades':<8}{'open':<6}")
    rows=[]
    for i,a in enumerate(accts):
        aid=a['id']
        led=run(prod_query("""
            select round(sum(coalesce(net_pnl,0))::numeric,2) net, count(*) n,
                   sum(case when status!='closed' then 1 else 0 end) open_n
            from trades where account_id=$1 and opened_at>$2::timestamptz
        """, aid, EPOCH))[0]
        eq=run(prod_query("""
            select round(equity::numeric,2) eq from high_freq_snapshots
            where account_id=$1 order by ts desc limit 1
        """, aid))
        cur_eq = eq[0]['eq'] if eq else None
        rows.append((i+1, a['label'], led['net'], cur_eq, led['n'], led['open_n']))
        print(f"{i+1:<5}{a['label']:<18}{str(led['net']):<12}{str(cur_eq):<12}{str(led['n']):<8}{str(led['open_n']):<6}")

    p("CORRELATION: alphabetical rank vs current equity")
    valid=[(r[0], float(r[3])) for r in rows if r[3] is not None]
    n=len(valid)
    if n>2:
        xs=[v[0] for v in valid]; ys=[v[1] for v in valid]
        mx=sum(xs)/n; my=sum(ys)/n
        cov=sum((x-mx)*(y-my) for x,y in valid)
        vx=sum((x-mx)**2 for x in xs); vy=sum((y-my)**2 for y in ys)
        r=cov/((vx*vy)**0.5) if vx and vy else 0
        print(f"Pearson r(rank, equity) = {r:.3f}  (n={n})")
        print("interpretation: r near 0 => alphabetical rank does NOT predict equity")
        print(f"  best equity: {max(valid,key=lambda v:v[1])}  worst: {min(valid,key=lambda v:v[1])}")
        # where does Unni rank in equity?
        eq_sorted=sorted(valid,key=lambda v:-v[1])
        unni_rank=next((i+1 for i,(rk,_) in enumerate(eq_sorted) if rk==20),None)
        print(f"  Unni (alpha rank 20) equity rank among {n}: {unni_rank}")

if __name__=="__main__":
    main()
