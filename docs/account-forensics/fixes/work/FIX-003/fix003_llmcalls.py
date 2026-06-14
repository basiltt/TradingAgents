import sys; sys.path.insert(0, "fix001")
from _prod import prod_query, prod_one, run, p, ACCT

p("ai_manager_llm_calls schema + Unni calls 02:25-03:13 (was ESPORTS ever sent to the LLM?)")
cols = run(prod_query("select column_name from information_schema.columns where table_name='ai_manager_llm_calls' order by ordinal_position"))
print("  cols:", [c['column_name'] for c in cols])
rows = run(prod_query("""
    select * from ai_manager_llm_calls where account_id=$1
      and timestamp between '2026-06-14T02:25:00Z' and '2026-06-14T03:14:00Z'
    order by timestamp
""", ACCT))
print(f"  LLM calls in window: {len(rows)}")
for r in rows:
    d = {k: r[k] for k in r.keys() if k in ('timestamp','symbol','decision','action','urgency','prompt_summary','response_summary')}
    print("  ", d)

p("How many evals (analyzing->monitoring) vs LLM calls in window?")
ev = run(prod_one("""select count(*) c from ai_manager_logs where account_id=$1
   and message ilike '%analyzing%monitoring%'
   and timestamp between '2026-06-14T02:25:00Z' and '2026-06-14T03:13:00Z'""", ACCT))
print(f"  analyzing->monitoring transitions: {ev['c']}")
print(f"  LLM calls: {len(rows)}")
print("  => if evals >> LLM calls, ESPORTS was gated BEFORE the LLM (the cap/age/profit gates)")
