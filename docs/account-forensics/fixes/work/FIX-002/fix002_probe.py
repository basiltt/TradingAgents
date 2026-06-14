import sys, json; sys.path.insert(0, "fix001")
from _prod import prod_query, prod_one, run, p, ACCT

p("The 02:58:05 EMERGENCY decision — full state_snapshot + action")
d = run(prod_one("""
    select timestamp, evaluation_type, urgency, state_snapshot::text ss, action_taken::text at, execution_result::text er
    from ai_manager_decisions where account_id=$1 and evaluation_type='emergency'
    order by timestamp desc limit 1
""", ACCT))
if d:
    print(f"  ts={d['timestamp']} urgency={d['urgency']}")
    ss = json.loads(d['ss']) if d['ss'] else {}
    print(f"  state_snapshot.symbols = {ss.get('symbols')}")
    print(f"  state_snapshot.reason  = {ss.get('reason')}")
    print(f"  action_taken = {d['at']}")
    print(f"  execution_result = {d['er']}")

p("What was ACTUALLY open at 02:58:05? (trades opened<=02:58:05 and closed>=02:58:05 or still open)")
rows = run(prod_query("""
    select symbol, side, status, round(net_pnl::numeric,2) net, opened_at, closed_at,
           round(extract(epoch from (closed_at - '2026-06-14T02:58:05.864109Z'::timestamptz)),3) close_delta_s
    from trades where account_id=$1
      and opened_at <= '2026-06-14T02:58:05.864109Z'
      and (closed_at is null or closed_at >= '2026-06-14T02:58:00Z')
    order by opened_at
""", ACCT))
for r in rows:
    print(f"  {r['symbol']:<13} {r['side']:<4} status={r['status']:<7} net={r['net']} "
          f"closed={r['closed_at']} (Δ vs emergency: {r['close_delta_s']}s)")

p("Timeline of the 3 closes around 02:58 (TSTBSC, FOLKS, + the emergency decision)")
rows = run(prod_query("""
    select symbol, closed_at, close_reason from trades where account_id=$1
      and closed_at between '2026-06-14T02:57:00Z' and '2026-06-14T02:59:00Z'
    order by closed_at
""", ACCT))
for r in rows:
    print(f"  {r['closed_at']}  CLOSE {r['symbol']:<13} reason={r['close_reason']}")
print("  emergency decision recorded at 2026-06-14 02:58:05.864109")
