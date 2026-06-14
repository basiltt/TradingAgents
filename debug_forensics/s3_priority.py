"""Stage 3: 'name starts with U' priority hypothesis — EMPIRICAL cross-account test.

For each symbol Unni traded, compare Unni's entry timestamp + fill price against
EVERY other account that traded the same symbol from the same scan_result lineage.
If alphabetical position-20 materially harms Unni, its opened_at should be latest
and its fill price systematically worse than position-1..19 accounts.
Read-only.
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
from _prod import prod_query, run, p, ACCT

SYMBOLS = ["GWEIUSDT","NOKIAUSDT","HMSTRUSDT","ESPORTSUSDT","B3USDT","TSTBSCUSDT","FOLKSUSDT"]

def main():
    labels = {r['id']: r['label'] for r in run(prod_query("select id,label from trading_accounts"))}

    p("CROSS-ACCOUNT ENTRY COMPARISON (same symbol, by opened_at)")
    for sym in SYMBOLS:
        rows = run(prod_query("""
            select account_id, side, signal_direction,
                   avg_fill_price::float8 fill, entry_price::float8 entry,
                   opened_at, scan_result_id, status,
                   round(net_pnl::numeric,3) net, close_reason
            from trades
            where symbol=$1 and opened_at > '2026-06-13T17:00:00Z'
            order by opened_at asc
        """, sym))
        if not rows:
            continue
        print(f"\n=== {sym} === ({len(rows)} accounts traded it)")
        first_open = rows[0]['opened_at']
        first_fill = rows[0]['fill']
        for i, r in enumerate(rows):
            lbl = labels.get(r['account_id'], '?')[:16]
            dt_ms = (r['opened_at'] - first_open).total_seconds()
            fill_bps = ((r['fill'] - first_fill)/first_fill*1e4) if first_fill else 0
            mark = "  <<<UNNI" if r['account_id']==ACCT else ""
            print(f"  {i+1:>2}. {lbl:<16} open=+{dt_ms:>6.1f}s fill={r['fill']:<12} fillΔ={fill_bps:+6.1f}bps {r['side']:<4} net={str(r['net']):>8} {str(r['close_reason'])[:14]}{mark}")

    p("UNNI ENTRY RANK SUMMARY (position among same-symbol traders)")
    for sym in SYMBOLS:
        rows = run(prod_query("""
            select account_id, opened_at, avg_fill_price::float8 fill, side
            from trades where symbol=$1 and opened_at > '2026-06-13T17:00:00Z'
            order by opened_at asc
        """, sym))
        if not rows: continue
        n = len(rows)
        uni_idx = next((i for i,r in enumerate(rows) if r['account_id']==ACCT), None)
        if uni_idx is None: continue
        first_fill = rows[0]['fill']
        uni = rows[uni_idx]
        # for a SHORT, higher fill = better entry; for LONG, lower fill = better
        side = uni['side']
        best_fill = max(r['fill'] for r in rows) if side=='Sell' else min(r['fill'] for r in rows)
        worst_fill = min(r['fill'] for r in rows) if side=='Sell' else max(r['fill'] for r in rows)
        gap_vs_first = (uni['fill']-first_fill)/first_fill*1e4 if first_fill else 0
        dt = (uni['opened_at']-rows[0]['opened_at']).total_seconds()
        print(f"{sym:<13} side={side:<4} Unni rank {uni_idx+1}/{n}  +{dt:5.1f}s after first  fill={uni['fill']:<12} (Δfirst={gap_vs_first:+.1f}bps)  best_possible={best_fill} worst={worst_fill}")

if __name__ == "__main__":
    main()
