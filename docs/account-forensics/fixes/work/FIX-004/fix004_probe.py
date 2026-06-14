import sys, json; sys.path.insert(0, "fix001")
from _prod import prod_query, prod_one, run, p, ACCT

p("ai_manager_state disarm fields for Unni (the FIX-004 evidence)")
st = run(prod_one("select * from ai_manager_state where account_id=$1", ACCT))
for k in ["circuit_breaker_count","circuit_breaker_active","circuit_breaker_half_open_used",
          "emergency_ref_equity","emergency_cooldown_until","emergency_closed_symbols",
          "actions_today","actions_this_hour","max_hourly_actions"]:
    if k in st: print(f"  {k} = {st[k]}")

p("Circuit breaker config (what trips it, how it recovers)")
cfg = json.loads(st["config"]) if isinstance(st.get("config"), str) else (st.get("config") or {})
for k in ["max_daily_actions","max_hourly_actions","emergency_equity_drop_pct","max_position_loss_pct",
          "evaluation_interval_s","safety_net_interval_s"]:
    print(f"  config.{k} = {cfg.get(k)}")

p("KEY QUESTION: was ESPORTS ever in emergency_closed_symbols? (would block FIX-003 hard-loss for 30s)")
ecs = st.get("emergency_closed_symbols")
print(f"  emergency_closed_symbols = {ecs}")
print("  => if ESPORTS NOT listed, FIX-003 hard-loss would fire on it on the next tick (not cooldown-blocked)")

p("circuit breaker source: how does it trip + recover? (grep)")
