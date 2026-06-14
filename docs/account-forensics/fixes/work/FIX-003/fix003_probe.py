import sys; sys.path.insert(0, "fix001")
sys.path.insert(0, "../fix001")
from _prod import prod_query, prod_one, run, p, ACCT

p("AI events/decisions mentioning ESPORTS for Unni (DB-persisted, survives log rotation)")
rows = run(prod_query("""
    select timestamp, evaluation_type, urgency, action_taken::text at, reasoning
    from ai_manager_decisions where account_id=$1
      and (action_taken::text ilike '%ESPORTS%' or reasoning ilike '%ESPORTS%' or state_snapshot::text ilike '%ESPORTS%')
    order by timestamp
""", ACCT))
print(f"  decisions referencing ESPORTS: {len(rows)}")
for r in rows:
    print(f"  {r['timestamp']} type={r['evaluation_type']} urgency={r['urgency']} action={r['at'][:70]}")

p("Is there an ai_manager_events / log table in prod?")
t = run(prod_query("select table_name from information_schema.tables where table_name ilike '%ai_manager%' order by table_name"))
print("  tables:", [x['table_name'] for x in t])

# Check if there's an events/log table with per-symbol skip reasons
for tbl in ['ai_manager_events','ai_manager_logs','ai_manager_activity']:
    try:
        n = run(prod_one(f"select count(*) c from {tbl} where account_id=$1", ACCT))
        cols = run(prod_query("select column_name from information_schema.columns where table_name=$1", tbl))
        print(f"  {tbl}: {n['c']} rows, cols={[c['column_name'] for c in cols]}")
    except Exception as e:
        pass

p("Reconstruct: ESPORTS unrealized loss vs 3% equity cap over its life (from hf snapshots)")
# ESPORTS was the lone position 03:00-03:15; before that it was 1 of 3-4. We know peak upnl.
rows = run(prod_query("""
    select ts, round(equity::numeric,2) eq, round(unrealised_pnl::numeric,2) upnl, position_count pc
    from high_freq_snapshots where account_id=$1
      and ts between '2026-06-14T01:31:00Z' and '2026-06-14T03:16:00Z' order by ts
""", ACCT))
print("  (3% of ~$95 equity = ~$2.85 cap; ESPORTS alone would exceed it once losing >$2.85)")
for r in rows[::3]:
    cap = float(r['eq'])*0.03
    print(f"  {r['ts']} eq={r['eq']} total_upnl={r['upnl']} pos={r['pc']} (3% cap=${cap:.2f})")
