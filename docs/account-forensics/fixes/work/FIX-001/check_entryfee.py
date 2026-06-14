import sys; sys.path.insert(0, ".")
from _prod import prod_query, run, p, ACCT
# Is the original entry fee recoverable? check trade metadata, order tables, anything
p("Unni ESPORTS — any fee history / order rows?")
r = run(prod_query("""
    select t.fees, t.metadata, t.order_id, t.created_at, t.updated_at
    from trades t where t.account_id=$1 and t.symbol='ESPORTSUSDT'
""", ACCT))
for x in r: print(" ", dict(x))
# Compute exact entry fee from known entry notional (taker 0.055%)
entry_px=0.06654; qty=2280
print(f"\n  entry_notional = {entry_px*qty:.4f}; taker entry_fee = {entry_px*qty*0.00055:.6f}")
print("  (original row showed fees=0.16688232 in Stage 1 = entry fee at open)")
