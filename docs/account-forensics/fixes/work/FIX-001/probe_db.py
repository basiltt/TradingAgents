import sys; sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, ACCT

p("CURRENT ESPORTS ROW (did the 24h backfill heal it?)")
r = run(prod_one("""
    select symbol,status,close_reason,exit_price,realized_pnl,net_pnl,fees,
           filled_qty,qty,side,entry_price,avg_fill_price,opened_at,closed_at,updated_at
    from trades where account_id=$1 and symbol='ESPORTSUSDT'
""", ACCT))
for k, v in (r or {}).items():
    print(f"  {k}: {v}")

p("ALL net_pnl=0 external closed trades across ALL accounts (blast radius)")
rows = run(prod_query("""
    select a.label, t.symbol, t.side, t.close_reason, t.exit_price, t.net_pnl, t.closed_at
    from trades t join trading_accounts a on a.id=t.account_id
    where t.status='closed' and (t.net_pnl=0 or t.net_pnl is null) and t.close_reason='external'
    order by t.closed_at desc limit 40
"""))
print(f"  count (external + net_pnl 0/null): {len(rows)}")
for r in rows:
    print(f"  {str(r['label'])[:16]:<16} {r['symbol']:<13} {r['side']:<4} exit={r['exit_price']} net={r['net_pnl']} closed={r['closed_at']}")

p("ZERO-exit_price closed trades (what the 24h backfill query targets)")
z = run(prod_query("""
    select a.label, t.symbol, t.close_reason, t.net_pnl, t.closed_at,
           (now() - t.closed_at) > interval '24 hours' as past_24h
    from trades t join trading_accounts a on a.id=t.account_id
    where t.status='closed' and t.exit_price=0
    order by t.closed_at desc limit 40
"""))
print(f"  count (exit_price=0 closed): {len(z)}")
for r in z:
    flag = "  <<< PAST 24h — backfill gave up" if r['past_24h'] else ""
    print(f"  {str(r['label'])[:16]:<16} {r['symbol']:<13} close={r['close_reason']} net={r['net_pnl']} closed={r['closed_at']}{flag}")
