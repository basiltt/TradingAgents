"""Stage 2: Scan cycle correctness + cross-account 'U-priority' test.

For each scan_result_id Unni traded, pull the parent scan, the result row
(score/confidence/direction/completed_at), scan completeness & staleness, and the
schedule's auto_trade config for Unni. Then test the 'name starts with U => low
priority' hypothesis by comparing Unni's entry time/price vs other accounts that
traded the SAME symbol in the SAME scan.
Read-only.
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from _prod import prod_query, prod_one, run, p, ACCT

CYCLE1 = [262, 218, 175]
CYCLE2 = [1242, 1247, 1435, 1652]
ALL_SR = CYCLE1 + CYCLE2

def main():
    p("SCAN RESULTS Unni traded (join scans)")
    rows = run(prod_query("""
        select sr.id sr_id, sr.scan_id, sr.ticker, sr.status, sr.direction,
               sr.confidence, sr.score, sr.run_id, sr.completed_at sr_completed,
               sr.analysis_price, sr.decision_summary, sr.signal_source,
               ar.completed_at as ar_completed, ar.started_at as ar_started,
               s.status scan_status, s.total, s.completed, s.failed,
               s.started_at, s.completed_at, s.schedule_id, s.triggered_by
        from scan_results sr
        left join scans s on s.scan_id = sr.scan_id
        left join analysis_runs ar on ar.run_id = sr.run_id
        where sr.id = any($1::int[])
        order by sr.id
    """, ALL_SR))
    for r in rows:
        print(f"\nsr_id={r['sr_id']} scan={r['scan_id']} {r['ticker']:<13} dir={r['direction']} conf={r['confidence']} score={r['score']} run_id={r['run_id']}")
        print(f"   scan_status={r['scan_status']} total={r['total']} completed={r['completed']} failed={r['failed']} trig={r['triggered_by']} sched={r['schedule_id']}")
        print(f"   scan.started_at={r['started_at']}  scan.completed_at={r['completed_at']}")
        print(f"   sr.completed_at={r['sr_completed']} analysis_price={r['analysis_price']} signal_source={r['signal_source']}")
        print(f"   analysis_run.started_at={r['ar_started']} completed_at={r['ar_completed']}")
        print(f"   decision_summary={str(r['decision_summary'])[:200]}")

    # distinct scans
    scan_ids = sorted({r['scan_id'] for r in rows})
    p(f"DISTINCT SCANS INVOLVED: {scan_ids}")
    for sid in scan_ids:
        s = run(prod_one("""
            select scan_id, status, total, completed, failed, started_at, completed_at,
                   schedule_id, triggered_by,
                   (config::jsonb) ? 'auto_trade_configs' as has_atc
            from scans where scan_id=$1
        """, sid))
        print(f"\nscan {sid}: status={s['status']} total={s['total']} completed={s['completed']} failed={s['failed']}")
        print(f"   started_at={s['started_at']} completed_at={s['completed_at']} trig={s['triggered_by']} has_atc={s['has_atc']}")
        # signal distribution
        dist = run(prod_one("""
            select count(*) n,
              sum(case when score=0 then 1 else 0 end) neutral,
              sum(case when abs(score)>=6 then 1 else 0 end) actionable,
              sum(case when abs(score)>=7 then 1 else 0 end) high_conf,
              sum(case when status='completed' then 1 else 0 end) completed_rows
            from scan_results where scan_id=$1
        """, sid))
        print(f"   signal dist: {dist}")

    # Unni's auto_trade config from the most recent involved scan
    p("UNNI AUTO_TRADE CONFIG (from scan config json)")
    for sid in scan_ids:
        cfg = run(prod_one("""
            select c->>'account_id' aid, c
            from scans s,
                 jsonb_array_elements(s.config::jsonb->'auto_trade_configs') c
            where s.scan_id=$1 and c->>'account_id'=$2
            limit 1
        """, sid, ACCT))
        if cfg:
            print(f"\n--- scan {sid} Unni config ---")
            print(json.dumps(cfg['c'], indent=2)[:2500])
            break

    p("HYPOTHESIS TEST: config ORDER in auto_trade_configs (is Unni last? alphabetical?)")
    order = run(prod_query("""
        select ord, c->>'account_id' aid
        from scans s,
             jsonb_array_elements(s.config::jsonb->'auto_trade_configs') with ordinality as t(c, ord)
        where s.scan_id=$1
        order by ord
    """, scan_ids[-1]))
    # map account ids to labels
    labels = {r['id']: r['label'] for r in run(prod_query("select id,label from trading_accounts"))}
    print(f"auto_trade_configs order in scan {scan_ids[-1]} ({len(order)} configs):")
    for r in order:
        lbl = labels.get(r['aid'], '?')
        mark = "  <<< UNNI" if r['aid']==ACCT else ""
        print(f"   pos {r['ord']:>2}: {lbl}{mark}")

if __name__ == "__main__":
    main()
