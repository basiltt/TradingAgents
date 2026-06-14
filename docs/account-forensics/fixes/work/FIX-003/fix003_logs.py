import sys; sys.path.insert(0, "fix001")
from _prod import prod_query, prod_one, run, p, ACCT

p("ai_manager_logs for Unni mentioning ESPORTS (ground truth)")
rows = run(prod_query("""
    select timestamp, level, category, message, details::text
    from ai_manager_logs where account_id=$1
      and (message ilike '%ESPORTS%' or details::text ilike '%ESPORTS%')
    order by timestamp
""", ACCT))
print(f"  {len(rows)} ESPORTS log rows")
for r in rows:
    print(f"  {r['timestamp']} [{r['level']}/{r['category']}] {r['message'][:120]}")

p("ALL Unni ai_manager_logs around 02:25-03:16 (what the AI was doing while ESPORTS bled)")
rows = run(prod_query("""
    select timestamp, level, category, message
    from ai_manager_logs where account_id=$1
      and timestamp between '2026-06-14T02:20:00Z' and '2026-06-14T03:16:00Z'
    order by timestamp
""", ACCT))
print(f"  {len(rows)} log rows in window")
for r in rows:
    print(f"  {r['timestamp']} [{r['level']}/{r['category']}] {r['message'][:130]}")

p("loss-cap / skip / urgency messages for Unni (any time)")
rows = run(prod_query("""
    select timestamp, message from ai_manager_logs where account_id=$1
      and (message ilike '%decision loss%' or message ilike '%exceeds cap%'
           or message ilike '%too young%' or message ilike '%skip%' or message ilike '%urgenc%')
    order by timestamp
""", ACCT))
print(f"  {len(rows)} skip/cap/urgency rows")
for r in rows:
    print(f"  {r['timestamp']} {r['message'][:130]}")
