"""Stage 1: Unni - Demo loss overview.

Pulls: account meta, every trade, close-reason breakdown, daily/hf snapshots,
close_rules fired, AI manager decision count. Read-only against prod.
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from _prod import prod_query, prod_one, prod_val, run, p, ACCT

def main():
    # --- Account meta ---
    p("ACCOUNT META")
    acct = run(prod_one("""
        select id,label,is_active,created_at,
               (select count(*) from trades where account_id=$1) as all_trades
        from trading_accounts where id=$1
    """, ACCT))
    print(json.dumps(acct, default=str, indent=2))

    # --- Wallet / latest daily snapshot ---
    p("LATEST DAILY SNAPSHOTS")
    ds = run(prod_query("""
        select snapshot_date, equity, wallet_balance, available_balance,
               unrealised_pnl, realised_pnl, positions_count, cumulative_pnl,
               daily_return_pct, peak_equity, drawdown_pct
        from daily_snapshots where account_id=$1
        order by snapshot_date desc limit 5
    """, ACCT))
    for r in ds:
        print(r)

    # --- All trades chronological ---
    p("ALL TRADES (chronological)")
    trades = run(prod_query("""
        select symbol, side, signal_direction, trade_direction, status,
               leverage, capital_pct, base_capital, entry_price, avg_fill_price,
               exit_price, take_profit_pct, stop_loss_pct,
               round(net_pnl::numeric,4) as net_pnl,
               round(realized_pnl::numeric,4) as realized_pnl,
               round(fees::numeric,4) as fees,
               close_reason, ai_closed, source, scan_result_id, close_rule_id,
               opened_at, closed_at,
               round(extract(epoch from (closed_at-opened_at))/60.0,1) as hold_min
        from trades where account_id=$1
        order by opened_at asc nulls last, created_at asc
    """, ACCT))
    print(f"total trade rows: {len(trades)}")
    for i, t in enumerate(trades):
        print(f"\n--- trade #{i+1}: {t['symbol']} {t['side']} dir={t['signal_direction']}/{t['trade_direction']} status={t['status']}")
        print(f"    lev={t['leverage']} cap%={t['capital_pct']} base={t['base_capital']} entry={t['entry_price']} avg_fill={t['avg_fill_price']} exit={t['exit_price']}")
        print(f"    TP%={t['take_profit_pct']} SL%={t['stop_loss_pct']} net_pnl={t['net_pnl']} realized={t['realized_pnl']} fees={t['fees']} hold_min={t['hold_min']}")
        print(f"    close_reason={t['close_reason']} ai_closed={t['ai_closed']} source={t['source']}")
        print(f"    scan_result_id={t['scan_result_id']} close_rule_id={t['close_rule_id']}")
        print(f"    opened={t['opened_at']} closed={t['closed_at']}")

    # --- Close reason breakdown ---
    p("CLOSE REASON BREAKDOWN")
    cr = run(prod_query("""
        select close_reason, count(*) cnt,
               round(sum(net_pnl)::numeric,4) total_pnl,
               round(avg(net_pnl)::numeric,4) avg_pnl,
               sum(case when net_pnl>0 then 1 else 0 end) wins
        from trades where account_id=$1 and status='closed'
        group by close_reason order by total_pnl asc
    """, ACCT))
    for r in cr:
        print(r)

    # --- PnL totals ---
    p("PNL TOTALS")
    tot = run(prod_one("""
        select count(*) closed, round(sum(net_pnl)::numeric,4) net,
               round(sum(realized_pnl)::numeric,4) realized,
               round(sum(fees)::numeric,4) fees,
               sum(case when net_pnl>0 then 1 else 0 end) wins,
               sum(case when net_pnl<0 then 1 else 0 end) losses
        from trades where account_id=$1 and status='closed'
    """, ACCT))
    print(tot)
    open_t = run(prod_one("select count(*) c, round(sum(net_pnl)::numeric,4) pnl from trades where account_id=$1 and status!='closed'", ACCT))
    print("non-closed:", open_t)

    # --- Close rules fired ---
    p("CLOSE RULES (account-level)")
    rules = run(prod_query("""
        select trigger_type, threshold_value, reference_value, status,
               created_at, triggered_at, expires_at, cycle_id
        from close_rules where account_id=$1
        order by created_at asc
    """, ACCT))
    for r in rules:
        print(r)

    # --- AI manager decisions count ---
    p("AI MANAGER DECISION SUMMARY")
    ai = run(prod_query("""
        select evaluation_type, urgency, count(*) cnt,
               min(timestamp) first, max(timestamp) last
        from ai_manager_decisions where account_id=$1
        group by evaluation_type, urgency order by cnt desc
    """, ACCT))
    for r in ai:
        print(r)
    ai_tot = run(prod_val("select count(*) from ai_manager_decisions where account_id=$1", ACCT))
    print("total AI decisions:", ai_tot)

    # --- High-freq equity span ---
    p("HIGH-FREQ EQUITY SNAPSHOTS (span + extremes)")
    hf = run(prod_one("""
        select count(*) n, min(ts) first, max(ts) last,
               min(equity) min_eq, max(equity) max_eq
        from high_freq_snapshots where account_id=$1
    """, ACCT))
    print(hf)

if __name__ == "__main__":
    main()
