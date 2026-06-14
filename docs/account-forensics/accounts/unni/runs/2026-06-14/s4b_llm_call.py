"""Stage 4b: ACTUAL LLM simulation. Feed each symbol's point-in-time data snapshot
(reconstructed, no-lookahead) to the local LLM (claude-sonnet via :4141 proxy) using
the system's OWN rating rubric, and capture an independent Long/Short/No-Trade verdict.

This tests the user's question: 'simulate LLM behaviour with the data used for those
selected trades and make sure it responded with correct output.' We cannot call the
exact prod model (MiniMax, key not local), but an independent strong model on the same
point-in-time data tells us whether the recorded signals were defensible or anomalous.
"""
from __future__ import annotations
import sys, json, urllib.request, datetime as dt, os
sys.path.insert(0, ".")
from _prod import prod_query, run, p, ACCT
sys.path.insert(0, "..")
from anthropic import Anthropic

# line-buffered stdout so progress is visible when redirected to a file
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
def flush(*a, **k):
    print(*a, **k); sys.stdout.flush()

# PRODUCTION PARITY: same model prod used (analysis_runs.config.deep_think_llm=MiniMax-M2.7-highspeed)
MINIMAX_KEY='sk-cp-4oYrqXDm58WJYXZt41owvsdfbAapOEQW_KyNDOJ1R0j-eNK7qp54mLNwEdW0nBkoMuFA4Boe-2eQSmPT95PltboPlvri1u9WvQexAq3EHi37qMAFBtSZAvY'
MODEL='MiniMax-M2.7-highspeed'
CLIENT = Anthropic(api_key=MINIMAX_KEY, base_url='https://api.minimax.io/anthropic', timeout=90.0, max_retries=1)

def llm_text(resp):
    """MiniMax returns [thinking, text] blocks — pick the text block(s)."""
    out=[]
    for b in (resp.content or []):
        if getattr(b,'type',None)=='text' and getattr(b,'text',None):
            out.append(b.text)
    return "\n".join(out).strip()

# System rubric distilled from crypto_analysts.py research-manager prompt
RUBRIC = """You are a crypto perpetual-futures Research Manager. This system OPENS new
positions (Long or Short). Decide ONE rating from the technical snapshot:
- Sell  => open a SHORT (require confirmed bearish evidence: breakdown below support,
           bearish trend alignment, momentum DOWN). Shorting carries unlimited upside
           risk, so require slightly stronger evidence than a long.
- Buy   => open a LONG (breakout, bullish alignment, strong momentum up).
- Hold  => no trade (mixed/insufficient/contradictory).
Do NOT default to Hold out of caution, but DO flag if price looks like a reversal/bounce
against the proposed direction. Reply STRICT JSON:
{"call":"Short|Long|No Trade","confidence":1-10,"reason":"<=40 words","reversal_risk":"low|medium|high"}"""

def bybit_klines(sym, interval, start_ms, end_ms):
    url=(f'https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}'
         f'&interval={interval}&start={start_ms}&end={end_ms}&limit=400')
    with urllib.request.urlopen(url, timeout=20) as r:
        d=json.load(r)
    rows=[[int(k[0])]+[float(x) for x in k[1:6]] for k in d.get('result',{}).get('list',[])]
    return sorted(rows, key=lambda x:x[0])

def ema(vals,n):
    if len(vals)<n: return None
    k=2/(n+1); e=sum(vals[:n])/n
    for v in vals[n:]: e=v*k+e*(1-k)
    return e
def rsi(closes,n=14):
    if len(closes)<n+1: return None
    g=l=0.0
    for i in range(-n,0):
        ch=closes[i]-closes[i-1]; g+=max(ch,0); l+=max(-ch,0)
    if l==0: return 100.0
    return 100-100/(1+(g/n)/(l/n))
def to_ms(t): return int(t.timestamp()*1000)

def main():
    sigs = run(prod_query("""
        select sr.ticker, sr.score, sr.direction, sr.confidence, ar.completed_at ac,
               t.side, round(t.net_pnl::numeric,2) net, t.status
        from scan_results sr join analysis_runs ar on ar.run_id=sr.run_id
        join trades t on t.scan_result_id=sr.id and t.account_id=$1
        where sr.id in (262,218,175,1242,1247,1435,1652) order by t.opened_at
    """, ACCT))
    results=[]
    for s in sigs:
        sym=s['ticker']; ac=s['ac']
        if isinstance(ac,str): ac=dt.datetime.fromisoformat(ac.replace('Z','+00:00'))
        a_ms=to_ms(ac)
        kl=[k for k in bybit_klines(sym,'15',to_ms(ac-dt.timedelta(hours=20)),a_ms) if k[0]<=a_ms]
        c=[k[4] for k in kl]
        last=c[-1]; e9,e21,e50=ema(c,9),ema(c,21),ema(c,50); r=rsi(c)
        chg24=((last-c[-96])/c[-96]*100) if len(c)>=96 else (last-c[0])/c[0]*100
        recent=kl[-8:]  # last 2h of 15m candles
        candles="\n".join(f"  {dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).strftime('%H:%M')} O={k[1]:.6g} H={k[2]:.6g} L={k[3]:.6g} C={k[4]:.6g}" for k in recent)
        snap=(f"Symbol {sym} perp. Analysis time {ac.strftime('%Y-%m-%d %H:%M')}Z (no future data).\n"
              f"last_close={last:.6g}\nEMA9={e9:.6g} EMA21={e21:.6g} EMA50={e50 and f'{e50:.6g}'}\n"
              f"RSI14={r and round(r,1)}\napprox_24h_change={chg24:.1f}%\n"
              f"EMA9 {'ABOVE' if e9>e21 else 'BELOW'} EMA21 (short-term {'up' if e9>e21 else 'down'}trend)\n"
              f"Recent 15m candles:\n{candles}")
        flush(f"[{len(results)+1}/7] calling MiniMax for {sym} (analysis@{ac.strftime('%H:%M')})...")
        j=None; last_err=""
        for attempt in range(3):
            try:
                m=CLIENT.messages.create(model=MODEL,max_tokens=1500,
                    messages=[{'role':'user','content':RUBRIC+"\n\n---DATA---\n"+snap+
                        "\n\nOutput ONLY the JSON object, nothing else."}])
                txt=llm_text(m)
                if '{' in txt and '}' in txt:
                    j=json.loads(txt[txt.find('{'):txt.rfind('}')+1])
                    break
            except Exception as e:
                last_err=str(e)[:120]; flush(f"    attempt {attempt+1} err: {last_err}")
        if j is None:
            j={"call":"ERR","confidence":0,"reason":f"no_json: {last_err}","reversal_risk":"?"}
        prod_call={'sell':'Short','buy':'Long'}.get(s['direction'],s['direction'])
        agree = (j.get('call')==prod_call)
        results.append((sym,prod_call,s['score'],j.get('call'),j.get('confidence'),
                        j.get('reversal_risk'),agree,s['net'],s['status'],j.get('reason')))
        flush(f"  {sym}: PROD={prod_call}(score {s['score']}) | MiniMax={j.get('call')}(conf {j.get('confidence')}, reversal={j.get('reversal_risk')}) | AGREE={agree}")
        flush(f"    net={s['net']} status={s['status']}  reason: {str(j.get('reason'))[:160]}")
        # incremental dump
        with open("s4b_results.json","w") as f:
            json.dump([{"symbol":x[0],"prod":x[1],"score":x[2],"llm":x[3],"llm_conf":x[4],
                        "reversal":x[5],"agree":x[6],"net":str(x[7]),"status":x[8],"reason":x[9]} for x in results], f, indent=2)

    p("STAGE 4b SUMMARY: independent LLM vs prod signal (same point-in-time data)")
    print(f"{'symbol':<13}{'prod':<7}{'score':<6}{'LLM':<10}{'rev-risk':<9}{'agree':<7}{'net':<8}{'status'}")
    for sym,pc,sc,lc,lconf,rev,ag,net,st,_ in results:
        print(f"{sym:<13}{pc:<7}{sc:<6}{str(lc):<10}{str(rev):<9}{str(ag):<7}{str(net):<8}{st}")
    agree_n=sum(1 for x in results if x[6])
    print(f"\nAgreement: {agree_n}/{len(results)}.  "
          f"High reversal-risk flags: {[x[0] for x in results if x[5]=='high']}")

if __name__=="__main__":
    main()
