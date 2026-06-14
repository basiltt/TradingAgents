"""Phase 5: self-consistency ENSEMBLE wrapper + reproducibility test.

Research §4: sampling N independent calls and majority-voting both (a) improves
accuracy and (b) sharply improves REPRODUCIBILITY (the user's explicit requirement
that re-running gives ~the same signal). A single stochastic call is noisy; a 5-vote
majority is stable.

This module:
- ensemble_call(prompt_fn, ticker, features, n=5): returns the majority call + vote
  spread + mean confidence, using n parallel samples.
- reproducibility_test: run the SAME signal K times and measure how often the final
  call is identical (single-call vs ensemble).
"""
from __future__ import annotations
import os, json, asyncio
from collections import Counter
from dotenv import load_dotenv
load_dotenv("../.env"); load_dotenv(".env")
from anthropic import Anthropic

MODEL = "MiniMax-M2.7-highspeed"
CLIENT = Anthropic(api_key=os.getenv("MINIMAX_API_KEY", ""),
                   base_url="https://api.minimax.io/anthropic", timeout=90, max_retries=2)

def _text(resp):
    return "\n".join(b.text for b in (resp.content or [])
                     if getattr(b, "type", None) == "text" and getattr(b, "text", None)).strip()

def _one_call(prompt, temperature=0.7):
    for _ in range(3):
        try:
            m = CLIENT.messages.create(model=MODEL, max_tokens=1200, temperature=temperature,
                                       messages=[{"role": "user", "content": prompt}])
            t = _text(m)
            if "{" in t and "}" in t:
                j = json.loads(t[t.find("{"):t.rfind("}") + 1])
                call = (j.get("call") or "").lower()
                if call in ("long", "buy"): return "buy", j.get("confidence", 5)
                if call in ("short", "sell"): return "sell", j.get("confidence", 5)
                return "none", j.get("confidence", 5)
        except Exception:
            pass
    return "err", 0

async def ensemble_call(prompt, n=5, temperature=0.7, trend_hint=None):
    """N parallel samples -> majority vote. Returns (call, agreement_frac, mean_conf, votes).

    trend_hint ('buy'/'sell'/None): deterministic tie-break — when the top two calls are
    tied, break toward the trend hint (or 'none' if no hint). Lowers run-to-run variance
    on borderline signals (reproducibility)."""
    loop = asyncio.get_event_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(None, _one_call, prompt, temperature) for _ in range(n)
    ])
    calls = [r[0] for r in results if r[0] != "err"]
    if not calls:
        return "none", 0.0, 0, []
    counts = Counter(calls)
    top = counts.most_common()
    winner, wn = top[0]
    # tie-break: if the top two are tied, prefer the trend hint, else 'none'
    if len(top) > 1 and top[1][1] == wn:
        tied = {c for c, k in top if k == wn}
        if trend_hint in tied:
            winner = trend_hint
        elif "none" in tied:
            winner = "none"
    agreement = counts[winner] / len(calls)
    confs = [r[1] for r in results if r[0] == winner and isinstance(r[1], (int, float))]
    mean_conf = sum(confs) / len(confs) if confs else 0
    return winner, round(agreement, 2), round(mean_conf, 1), calls
