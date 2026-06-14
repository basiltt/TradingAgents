"""Stage 4c: clean MiniMax verdict for ESPORTS + FOLKS (the two that need it),
with a big token budget so the text block survives the thinking block.
Production parity model: MiniMax-M2.7-highspeed.
"""
from __future__ import annotations
import sys, json, urllib.request, datetime as dt
sys.path.insert(0, "."); sys.path.insert(0, "..")
from _prod import prod_query, run, p, ACCT
from anthropic import Anthropic
KEY='sk-cp-4oYrqXDm58WJYXZt41owvsdfbAapOEQW_KyNDOJ1R0j-eNK7qp54mLNwEdW0nBkoMuFA4Boe-2eQSmPT95PltboPlvri1u9WvQexAq3EHi37qMAFBtSZAvY'
CLIENT=Anthropic(api_key=KEY,base_url='https://api.minimax.io/anthropic',timeout=120.0,max_retries=2)
MODEL='MiniMax-M2.7-highspeed'
def flush(*a): print(*a); sys.stdout.flush()
def llm_text(r): return "\n".join(b.text for b in (r.content or []) if getattr(b,'type',None)=='text' and getattr(b,'text',None)).strip()
RUBRIC=("You are a crypto perp futures Research Manager opening NEW positions. Rate Short/Long/No Trade. "
        "Short needs confirmed bearish evidence (breakdown below support, bearish alignment, momentum DOWN); "
        "shorting has unlimited upside risk so require strong evidence and FLAG bounce/reversal setups. "
        'Reply STRICT JSON only: {"call":"Short|Long|No Trade","confidence":1-10,"reason":"<=35 words","reversal_risk":"low|medium|high"}')
def bk(sym,iv,s,e):
    u=f'https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval={iv}&start={s}&end={e}&limit=400'
    d=json.load(urllib.request.urlopen(u,timeout=20))
    return sorted(([int(k[0])]+[float(x) for x in k[1:6]] for k in d.get('result',{}).get('list',[])),key=lambda x:x[0])
def ema(v,n):
    if len(v)<n: return None
    k=2/(n+1); e=sum(v[:n])/n
    for x in v[n:]: e=x*k+e*(1-k)
    return e
def rsi(c,n=14):
    if len(c)<n+1: return None
    g=l=0.0
    for i in range(-n,0):
        ch=c[i]-c[i-1]; g+=max(ch,0); l+=max(-ch,0)
    return 100.0 if l==0 else 100-100/(1+(g/n)/(l/n))
def ms(t): return int(t.timestamp()*1000)

def main():
    targets = run(prod_query("""
        select sr.ticker, sr.score, sr.direction, ar.completed_at ac, round(t.net_pnl::numeric,2) net, t.status
        from scan_results sr join analysis_runs ar on ar.run_id=sr.run_id
        join trades t on t.scan_result_id=sr.id and t.account_id=$1
        where sr.id in (1242,1652) order by t.opened_at
    """, ACCT))
    out=[]
    for s in targets:
        sym=s['ticker']; ac=s['ac']
        if isinstance(ac,str): ac=dt.datetime.fromisoformat(ac.replace('Z','+00:00'))
        a=ms(ac)
        kl=[k for k in bk(sym,'15',ms(ac-dt.timedelta(hours=20)),a) if k[0]<=a]
        c=[k[4] for k in kl]; last=c[-1]; e9,e21,e50=ema(c,9),ema(c,21),ema(c,50); r=rsi(c)
        chg=((last-c[-96])/c[-96]*100) if len(c)>=96 else (last-c[0])/c[0]*100
        rec="\n".join(f"  {dt.datetime.fromtimestamp(k[0]/1000,dt.timezone.utc).strftime('%H:%M')} O={k[1]:.6g} H={k[2]:.6g} L={k[3]:.6g} C={k[4]:.6g}" for k in kl[-10:])
        snap=(f"Symbol {sym} perp @ {ac.strftime('%Y-%m-%d %H:%M')}Z (no future data).\n"
              f"last_close={last:.6g} EMA9={e9:.6g} EMA21={e21:.6g} EMA50={e50 and f'{e50:.6g}'} RSI14={round(r,1)}\n"
              f"approx_24h_change={chg:.1f}%  EMA9 {'ABOVE' if e9>e21 else 'BELOW'} EMA21\nRecent 15m:\n{rec}")
        flush(f"\n=== {sym} (prod={s['direction']}, score {s['score']}, net {s['net']}) ===")
        j=None
        for att in range(4):
            try:
                m=CLIENT.messages.create(model=MODEL,max_tokens=3000,
                    messages=[{'role':'user','content':RUBRIC+"\n\n---DATA---\n"+snap+"\n\nOutput ONLY the JSON."}])
                txt=llm_text(m)
                flush(f"  [attempt {att+1}] raw_text_len={len(txt)} stop={m.stop_reason}")
                if '{' in txt and '}' in txt:
                    j=json.loads(txt[txt.find('{'):txt.rfind('}')+1]); break
            except Exception as e:
                flush(f"  [attempt {att+1}] ERR {str(e)[:100]}")
        prod_call={'sell':'Short','buy':'Long'}.get(s['direction'])
        flush(f"  RESULT: PROD={prod_call} | MiniMax={j.get('call') if j else 'ERR'} conf={j.get('confidence') if j else '-'} reversal={j.get('reversal_risk') if j else '-'}")
        flush(f"  reason: {j.get('reason') if j else 'n/a'}")
        out.append({"symbol":sym,"prod":prod_call,"score":s['score'],"net":str(s['net']),
                    "minimax":(j or {}).get('call'),"conf":(j or {}).get('confidence'),
                    "reversal":(j or {}).get('reversal_risk'),"reason":(j or {}).get('reason')})
    json.dump(out, open("s4c_esports_folks.json","w"), indent=2)
    flush("\nwrote s4c_esports_folks.json")

if __name__=="__main__": main()
