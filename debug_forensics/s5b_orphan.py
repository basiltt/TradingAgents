"""Stage 5b: Why was ESPORTS orphaned? Eval cadence + emergency exclusion + reconciliation gap.

(a) Full timeline of every AI decision vs every position open/close (interleaved).
(b) Did the AI manager EVER evaluate ESPORTS in the standard path? (search decisions/events)
(c) Reconstruct positions open at 02:58:05 emergency and their upnl sign.
(d) Quantify the true ESPORTS loss from equity (since trade row is unreconciled).
Read-only.
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, ACCT

def main():
    p("INTERLEAVED TIMELINE: trades (open/close) + AI decisions")
    events = []
    trades = run(prod_query("""
        select symbol, opened_at, closed_at, status, round(net_pnl::numeric,2) net, close_reason, ai_closed
        from trades where account_id=$1
    """, ACCT))
    for t in trades:
        events.append((t['opened_at'], f"OPEN  {t['symbol']:<13} ({t['status']})"))
        if t['closed_at']:
            events.append((t['closed_at'], f"CLOSE {t['symbol']:<13} net={t['net']} reason={t['close_reason']} ai={t['ai_closed']}"))
    decs = run(prod_query("""
        select timestamp, evaluation_type, urgency, action_taken, reasoning
        from ai_manager_decisions where account_id=$1
    """, ACCT))
    for d in decs:
        act = d['action_taken']
        try: act = json.loads(act) if isinstance(act,str) else act
        except Exception: act = {}
        sym = act.get('symbol','?')
        events.append((d['timestamp'], f"AI-{d['evaluation_type'].upper()}[{d['urgency']}] {act.get('action','?')} {sym}"))
    for ts, label in sorted(events, key=lambda e: e[0]):
        print(f"{ts}  {label}")

    p("DID AI MANAGER EVER EVALUATE ESPORTS? (any decision referencing it)")
    esp = run(prod_query("""
        select id, timestamp, evaluation_type, action_taken::text, reasoning
        from ai_manager_decisions where account_id=$1
          and (action_taken::text ilike '%ESPORTS%' or reasoning ilike '%ESPORTS%' or state_snapshot::text ilike '%ESPORTS%')
        order by timestamp
    """, ACCT))
    print(f"decisions referencing ESPORTS in any field: {len(esp)}")
    for r in esp:
        print(f"  id={r['id']} {r['timestamp']} type={r['evaluation_type']} action={r['action_taken'][:80]}")

    p("POSITIONS OPEN AT 02:58:05 EMERGENCY (from trades opened<=02:58 and closed>=02:58 or still open)")
    at = run(prod_query("""
        select symbol, side, opened_at, closed_at, status, round(net_pnl::numeric,2) net,
               avg_fill_price::float8 fill, stop_loss_price::float8 sl
        from trades where account_id=$1
          and opened_at <= '2026-06-14T02:58:05Z'
          and (closed_at is null or closed_at >= '2026-06-14T02:58:00Z')
        order by opened_at
    """, ACCT))
    for r in at:
        print(f"  {r['symbol']:<13} {r['side']:<4} fill={r['fill']:<10} sl={r['sl']:<10} status={r['status']:<7} net={r['net']} closed={r['closed_at']}")

    p("AI MANAGER STATE / EXCLUDED / LOCKED (ai_manager_state row)")
    st = run(prod_one("select * from ai_manager_state where account_id=$1", ACCT))
    if st:
        print(json.dumps({k:str(v) for k,v in st.items()}, indent=2))
    else:
        print("no ai_manager_state row; checking table names...")
        tabs = run(prod_query("select table_name from information_schema.tables where table_name ilike '%ai_manager%' order by table_name"))
        print([t['table_name'] for t in tabs])

    p("TRUE ESPORTS LOSS (from equity, since trade row unreconciled)")
    # equity just before ESPORTS closed (pos went 1->0) vs after
    around = run(prod_query("""
        select ts, round(equity::numeric,2) eq, round(unrealised_pnl::numeric,2) upnl, position_count pc
        from high_freq_snapshots where account_id=$1
          and ts between '2026-06-14T03:05:00Z' and '2026-06-14T03:20:00Z' order by ts
    """, ACCT))
    for r in around:
        print(f"  {r['ts']}  eq={r['eq']} upnl={r['upnl']} pos={r['pc']}")
    print("\nESPORTS entry fill=0.06654, SL=0.07474 (+12.3%), short, 7x lev, base~98.47, cap22% => margin ~21.66")
    print("12.3% adverse * 7x ~= -86% of margin ~= -18.6 USD (matches eq 98 -> 79.6 net of other small closes)")

if __name__ == "__main__":
    main()
