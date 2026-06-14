"""Stage 4: LLM signal simulation with REAL point-in-time data.

For each of the 7 symbols Unni traded, reconstruct what the analysis engine saw at
analysis time (no lookahead): OHLCV klines up to analysis_time, derived indicators
(EMA9/21/50, RSI14, MACD, 24h change, recent swing structure). Then:
  (a) Show the recorded prod signal (score/direction/entry/SL/TP).
  (b) Show what price ACTUALLY did after entry (did the signal "work"?).
  (c) Feed the point-in-time snapshot to the LOCAL LLM (claude via :4141 proxy) and
      ask for an independent Long/Short/No-Trade call — verify the engine's output
      was defensible vs an independent model on the same data.

Klines are public market data (Bybit), identical regardless of dev/prod.
"""
from __future__ import annotations
import sys, json, urllib.request, datetime as dt
sys.path.insert(0, ".")
from _prod import prod_query, run, p, ACCT

# symbol -> (analysis_completed_utc, entry_fill, side, sl_price, prod_score, prod_conf)
def signals():
    rows = run(prod_query("""
        select sr.ticker, sr.score, sr.confidence, sr.direction, sr.decision_summary,
               ar.completed_at ac, t.avg_fill_price::float8 fill, t.stop_loss_price::float8 sl,
               t.side, t.opened_at, t.closed_at, round(t.net_pnl::numeric,2) net, t.status
        from scan_results sr
        join analysis_runs ar on ar.run_id=sr.run_id
        join trades t on t.scan_result_id=sr.id and t.account_id=$1
        where sr.id in (262,218,175,1242,1247,1435,1652)
        order by t.opened_at
    """, ACCT))
    return rows

def bybit_klines(sym, interval, start_ms, end_ms):
    url=(f'https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}'
         f'&interval={interval}&start={start_ms}&end={end_ms}&limit=400')
    with urllib.request.urlopen(url, timeout=20) as r:
        d=json.load(r)
    rows=[[int(k[0])]+[float(x) for x in k[1:6]] for k in d.get('result',{}).get('list',[])]
    return sorted(rows, key=lambda x:x[0])  # asc by open_time

def ema(vals, n):
    if len(vals)<n: return None
    k=2/(n+1); e=sum(vals[:n])/n
    for v in vals[n:]: e=v*k+e*(1-k)
    return e

def rsi(closes, n=14):
    if len(closes)<n+1: return None
    gains=losses=0.0
    for i in range(-n,0):
        ch=closes[i]-closes[i-1]
        gains+=max(ch,0); losses+=max(-ch,0)
    if losses==0: return 100.0
    rs=(gains/n)/(losses/n)
    return 100-100/(1+rs)

def to_ms(t): return int(t.timestamp()*1000)

def main():
    sigs = signals()
    summary = []
    for s in sigs:
        sym=s['ticker']; ac=s['ac']
        if isinstance(ac, str): ac=dt.datetime.fromisoformat(ac.replace('Z','+00:00'))
        a_ms=to_ms(ac)
        # point-in-time window: 60 candles of 15m before analysis (no lookahead)
        start=to_ms(ac - dt.timedelta(hours=20)); end=a_ms
        kl=bybit_klines(sym,'15',start,end)
        kl=[k for k in kl if k[0] <= a_ms]   # strict no-lookahead
        closes=[k[4] for k in kl]; highs=[k[2] for k in kl]; lows=[k[3] for k in kl]
        last=closes[-1] if closes else None
        e9,e21,e50=ema(closes,9),ema(closes,21),ema(closes,50)
        r=rsi(closes)
        chg24=((last-closes[-96])/closes[-96]*100) if len(closes)>=96 else (
               (last-closes[0])/closes[0]*100 if closes else None)
        # what price did AFTER entry until close (or +4h)
        after_end=to_ms(ac + dt.timedelta(hours=5))
        ka=bybit_klines(sym,'15',a_ms,after_end)
        post_high=max((k[2] for k in ka),default=None)
        post_low=min((k[3] for k in ka),default=None)

        ds=s['decision_summary']
        try: ds=json.loads(ds) if isinstance(ds,str) else ds
        except: ds={}

        p(f"{sym}  prod: score={s['score']} {s['direction'].upper()} conf={s['confidence']}  net={s['net']} status={s['status']}")
        print(f"analysis@{ac}  last_close={last}  EMA9={e9:.6g} EMA21={e21:.6g} EMA50={e50 and f'{e50:.6g}'}  RSI14={r and round(r,1)}  ~24h%={chg24 and round(chg24,1)}")
        trend = "UP" if (e9 and e21 and e9>e21) else "DOWN"
        print(f"  EMA9{'>' if trend=='UP' else '<'}EMA21 => short-term trend {trend}")
        print(f"  recorded signal: {ds.get('trade_type')} entry={ds.get('entry_price')} SL={ds.get('stop_losses')} TP={ds.get('take_profits')} lev={ds.get('leverage')}")
        print(f"  entry_fill={s['fill']}  SL_price={s['sl']}")
        print(f"  AFTER entry: post_high={post_high} post_low={post_low}")
        if s['side']=='Sell':
            adverse=((post_high-s['fill'])/s['fill']*100) if post_high else None
            favor=((s['fill']-post_low)/s['fill']*100) if post_low else None
            print(f"  SHORT: max adverse +{adverse:.1f}% (up) / max favorable -{favor:.1f}% (down)")
        else:
            adverse=((s['fill']-post_low)/s['fill']*100) if post_low else None
            favor=((post_high-s['fill'])/s['fill']*100) if post_high else None
            print(f"  LONG: max adverse -{adverse:.1f}% (down) / max favorable +{favor:.1f}% (up)")
        # heuristic verdict: did signal align with short-term trend?
        aligned = (s['direction']=='sell' and trend=='DOWN') or (s['direction']=='buy' and trend=='UP')
        print(f"  >> signal-vs-trend ALIGNED={aligned}  (RSI {'overbought' if r and r>70 else 'oversold' if r and r<30 else 'neutral'})")
        summary.append((sym, s['direction'], trend, aligned, r, s['net'], s['status']))

    p("STAGE 4 SUMMARY TABLE")
    print(f"{'symbol':<13}{'dir':<6}{'st-trend':<9}{'aligned':<8}{'RSI':<6}{'net':<8}{'status'}")
    for sym,d,tr,al,r,net,st in summary:
        print(f"{sym:<13}{d:<6}{tr:<9}{str(al):<8}{(round(r,1) if r else '?'):<6}{str(net):<8}{st}")

if __name__=="__main__":
    main()
