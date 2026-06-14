"""Stage 5: AI manager decisions (full) + ESPORTS exit divergence.

(a) Dump all 5 Unni AI manager decisions in full (state_snapshot, action_taken,
    reasoning, execution_result, outcome).
(b) Compare ESPORTS exits across the 7 accounts that shorted it — when/why each
    closed, and which cohort/config each had (drawdown, smart_close, ai_manager).
(c) Show the per-trade stop_loss_price vs the exit to confirm Unni rode to full SL.
Read-only.
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, ACCT

ESPORTS_ACCTS_QUERY = """
    select t.account_id, t.avg_fill_price::float8 fill, t.stop_loss_price::float8 sl,
           t.exit_price::float8 exit, t.status, round(t.net_pnl::numeric,3) net,
           t.close_reason, t.ai_closed, t.opened_at, t.closed_at,
           round(extract(epoch from (t.closed_at-t.opened_at))/60,1) hold_min
    from trades t where t.symbol='ESPORTSUSDT' and t.opened_at>'2026-06-13T17:00:00Z'
    order by t.opened_at asc
"""

def main():
    labels = {r['id']: r['label'] for r in run(prod_query("select id,label from trading_accounts"))}

    p("ALL 5 UNNI AI-MANAGER DECISIONS (full)")
    decs = run(prod_query("""
        select id, timestamp, evaluation_type, urgency, confidence,
               state_snapshot, action_taken, reasoning, execution_result,
               outcome, outcome_label, created_at
        from ai_manager_decisions where account_id=$1
        order by timestamp asc
    """, ACCT))
    for i, d in enumerate(decs):
        print(f"\n################ DECISION #{i+1}  id={d['id']} ################")
        print(f"timestamp={d['timestamp']}  type={d['evaluation_type']} urgency={d['urgency']} conf={d['confidence']}")
        print(f"outcome={d['outcome']} outcome_label={d['outcome_label']}")
        for fld in ("state_snapshot","action_taken","execution_result"):
            v = d[fld]
            try:
                v = json.dumps(json.loads(v), indent=2) if isinstance(v,str) else json.dumps(v, default=str, indent=2)
            except Exception:
                pass
            print(f"\n--- {fld} ---\n{str(v)[:2500]}")
        print(f"\n--- reasoning ---\n{str(d['reasoning'])[:1500]}")

    p("ESPORTS EXIT DIVERGENCE (7 accounts) + cohort knobs")
    rows = run(prod_query(ESPORTS_ACCTS_QUERY))
    for r in rows:
        lbl = labels.get(r['account_id'],'?')
        mark = "  <<<UNNI" if r['account_id']==ACCT else ""
        sl = r['sl']; fill = r['fill']
        sl_move = ((sl-fill)/fill*100) if fill else 0
        print(f"{lbl:<16} fill={fill:<10} sl_price={sl:<10} (+{sl_move:.1f}% = SL trigger) status={r['status']:<7} "
              f"net={str(r['net']):>8} close={str(r['close_reason']):<14} ai={r['ai_closed']} hold={r['hold_min']}min closed={r['closed_at']}{mark}")

    p("PER-ACCOUNT CONFIG for ESPORTS traders (cohort knobs from scan a9907)")
    SCAN = "a9907e9a-f55c-4acc-802c-d44a05e1a188"
    for r in rows:
        aid = r['account_id']
        cfg = run(prod_one("""
            select c->>'max_drawdown_pct' dd, c->>'smart_drawdown_close' smart,
                   c->>'ai_manager_enabled' ai, c->>'leverage' lev,
                   c->>'max_trades' mt, c->>'target_goal_value' goal,
                   c->'ai_manager_capabilities'->>'emergency_close' emerg
            from scans s, jsonb_array_elements(s.config::jsonb->'auto_trade_configs') c
            where s.scan_id=$1 and c->>'account_id'=$2 limit 1
        """, SCAN, aid))
        lbl = labels.get(aid,'?')
        mark = "  <<<UNNI" if aid==ACCT else ""
        print(f"{lbl:<16} drawdown%={cfg['dd']:<6} smart_close={cfg['smart']:<6} ai_mgr={cfg['ai']:<5} emerg_close={cfg['emerg']:<5} lev={cfg['lev']} max_trades={cfg['mt']} goal={cfg['goal']}{mark}")

    p("UNNI CLOSE_RULES full (account-level safety net)")
    rules = run(prod_query("""
        select trigger_type, threshold_value, reference_value, status, created_at, triggered_at, cycle_id
        from close_rules where account_id=$1 order by created_at asc
    """, ACCT))
    for r in rules:
        print(r)

if __name__ == "__main__":
    main()
