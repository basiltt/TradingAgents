"""Pluggable LLM strategies for the signal-replay engine.

Each strategy(ticker, features) -> prompt string. The LLM must reply STRICT JSON:
{"call": "Long|Short|No Trade", "confidence": 1-10, ...optional fields...}

Research-grounded ladder (see signal_research notes):
- S0 baseline_prompt: minimal, mimics a naive single-shot call (control).
- S1 rich_features: same ask + the full point-in-time feature snapshot.
- S2 reversal_guard: rich + explicit falling-knife / fade-trap rules.
- S3 regime_gated: reversal_guard + regime classification gate (ADX/trend votes).
- S4 bull_bear_debate: structured symmetric bull/bear scoring (no open CoT) + regime.
"""
from __future__ import annotations
from _features import render

_JSON = ('Reply with STRICT JSON only, no prose:\n'
         '{"call":"Long|Short|No Trade","confidence":<1-10>,"reason":"<=30 words"}')

def baseline_prompt(ticker, f):
    """Control: minimal info, single-shot (approximates a naive signal call)."""
    return (f"You are a crypto futures analyst. Decide a directional trade for {ticker}.\n"
            f"price={f['price']:.6g}, EMA9{'>' if f['ema9_gt_21'] else '<'}EMA21, "
            f"RSI14={f['rsi14']:.0f}, 24h_change={f.get('ret_24h')}%.\n"
            f"Open a Long, Short, or No Trade.\n{_JSON}")

def rich_features(ticker, f):
    """Same decision, but with the full point-in-time technical snapshot."""
    return (f"You are a disciplined crypto perpetual-futures analyst opening a NEW position "
            f"for a 2-8 hour horizon. Decide Long, Short, or No Trade.\n\n"
            f"{render(f, ticker)}\n\n"
            f"Weigh trend, momentum, and levels. {_JSON}")

def reversal_guard(ticker, f):
    """rich + explicit anti-falling-knife / anti-fade rules (research §2)."""
    return (f"You are a disciplined crypto perp analyst opening a NEW position (2-8h horizon).\n\n"
            f"{render(f, ticker)}\n\n"
            f"CRITICAL ANTI-TRAP RULES (shorting crashed coins is the #1 loss source):\n"
            f"- Do NOT Short if the coin already crashed (24h<-15%) AND is oversold (RSI<32) OR "
            f"sitting on support — that is a falling-knife / dead-cat-bounce trap. Prefer No Trade.\n"
            f"- Do NOT Long a coin that already pumped (24h>+15%) and is overbought near resistance.\n"
            f"- A SHORT needs a confirmed breakdown (price closing below support with lower-highs), "
            f"NOT just a low RSI. A LONG needs a confirmed breakout / higher-lows.\n"
            f"- When momentum and the move are exhausted (big move already happened), prefer No Trade.\n"
            f"Only take a trade with a clear, confirmed directional edge. {_JSON}")

def regime_gated(ticker, f):
    """reversal_guard + regime gate: mean-revert only in RANGING; trend-follow in TRENDING."""
    # crude regime hint from available features
    trend_align = (f.get("trend_15m"), f.get("trend_1h"), f.get("trend_4h"))
    return (f"You are a disciplined crypto perp analyst opening a NEW position (2-8h horizon).\n\n"
            f"{render(f, ticker)}\n\n"
            f"STEP 1 — REGIME: classify the market as TRENDING (5m/15m/1h/4h EMAs aligned, strong "
            f"directional returns) or RANGING (mixed TF trends, small returns, price oscillating).\n"
            f"STEP 2 — DIRECTION RULES:\n"
            f"- TRENDING DOWN: only Short WITH the trend on pullbacks; never Long a falling knife; "
            f"an oversold RSI in a downtrend keeps dropping — it is NOT a long signal.\n"
            f"- TRENDING UP: only Long with the trend; never Short strength.\n"
            f"- RANGING: fade extremes — Short near resistance/overbought, Long near support/oversold.\n"
            f"- If timeframes conflict (e.g. 4h up but 5m down) or edge is unclear: No Trade.\n"
            f"ANTI-TRAP: a coin that crashed 24h<-15% and is oversold/on-support is a bounce trap — "
            f"do NOT short it; No Trade unless a fresh breakdown confirms.\n"
            f'Reply STRICT JSON: {{"regime":"trending_up|trending_down|ranging","call":"Long|Short|No Trade",'
            f'"confidence":<1-10>,"reason":"<=30 words"}}')

def bull_bear_debate(ticker, f):
    """Structured symmetric bull/bear scoring (research §4: no open CoT, score both sides)."""
    return (f"You are adjudicating a crypto perp trade for {ticker} (2-8h horizon).\n\n"
            f"{render(f, ticker)}\n\n"
            f"Do NOT free-associate. Fill these fields objectively:\n"
            f"1. bull_case: the single strongest evidence-based reason price goes UP (cite the data).\n"
            f"2. bear_case: the single strongest evidence-based reason price goes DOWN (cite the data).\n"
            f"3. bull_score: 0-100 strength of the bull case.\n"
            f"4. bear_score: 0-100 strength of the bear case.\n"
            f"5. regime: trending_up | trending_down | ranging.\n"
            f"Base rate is ~50/50; most setups have NO edge. Decide:\n"
            f"- call = Long if bull_score - bear_score >= 25; Short if bear_score - bull_score >= 25; "
            f"else No Trade.\n"
            f"- NEVER short a coin that crashed 24h<-15% and is oversold/on-support (bounce trap).\n"
            f"- In a confirmed downtrend an oversold RSI is continuation, not a long.\n"
            f'Reply STRICT JSON: {{"bull_case":"...","bear_case":"...","bull_score":<0-100>,'
            f'"bear_score":<0-100>,"regime":"...","call":"Long|Short|No Trade","confidence":<1-10>}}')

def mtf_confirm(ticker, f):
    """Trade only WITH multi-timeframe trend alignment (research §3). Strong abstention."""
    return (f"You are a crypto perp trend-trader for {ticker} (2-8h horizon). You ONLY trade WITH "
            f"the higher-timeframe trend — never counter-trend.\n\n"
            f"{render(f, ticker)}\n\n"
            f"RULES:\n"
            f"- Long ONLY if 1h AND 4h trend are both 'up' and price shows a higher-low/pullback entry.\n"
            f"- Short ONLY if 1h AND 4h trend are both 'down' and price shows a lower-high/pullback entry.\n"
            f"- If 1h and 4h disagree, or either is missing, or the move looks exhausted: No Trade.\n"
            f"- NEVER short a coin that already crashed 24h<-15% and is oversold/on-support.\n"
            f"Most setups should be No Trade — only act on clean trend alignment.\n{_JSON}")

def confluence_filter(ticker, f):
    """High-bar quality filter (research: fewer, higher-quality trades). Requires confluence."""
    return (f"You are a selective crypto perp analyst for {ticker} (2-8h horizon). You take a trade "
            f"ONLY when MULTIPLE independent signals agree — otherwise No Trade.\n\n"
            f"{render(f, ticker)}\n\n"
            f"A valid LONG needs >=3 of: 1h+4h trend up; RSI rising from <50 (not overbought); "
            f"price reclaiming a level / higher-low; volume expansion; NOT pumped+overbought.\n"
            f"A valid SHORT needs >=3 of: 1h+4h trend down; confirmed breakdown below support (close, "
            f"not wick); lower-high structure; volume on the drop; NOT crashed+oversold+on-support.\n"
            f"Count the confluences honestly. If <3 agree, or it's a falling-knife/exhausted move: No Trade.\n"
            f'Reply STRICT JSON: {{"long_confluences":<int>,"short_confluences":<int>,'
            f'"call":"Long|Short|No Trade","confidence":<1-10>,"reason":"<=25 words"}}')

# ─── Round 2: round-1 showed rule-heavy prompts cause 79-100% abstention. Force a
# directional call on a LEAN prompt; rely on ENSEMBLE voting for quality, not rules. ───

def forced_lean(ticker, f):
    """Force Long or Short (no easy No-Trade). Lean prompt. Measures raw directional skill —
    the substrate the ensemble will vote over. Trend-following bias baked in lightly."""
    return (f"Crypto perp {ticker}, 2-8h horizon. You MUST pick a direction (Long or Short) — "
            f"choose the more likely one, do not say No Trade.\n\n"
            f"{render(f, ticker)}\n\n"
            f"Decide with the dominant trend unless a clear reversal is confirmed. "
            f'Reply STRICT JSON: {{"call":"Long|Short","confidence":<1-10>}}')

def trend_follow_lean(ticker, f):
    """Lean trend-follower: go WITH the higher-TF trend; only No-Trade if TFs truly conflict.
    Directly targets the short-bias by making direction follow the actual trend, not a hunch."""
    return (f"Crypto perp {ticker}, 2-8h horizon. Trade WITH the prevailing trend.\n\n"
            f"{render(f, ticker)}\n\n"
            f"Rule: if 1h and 4h trend agree, go that direction (up->Long, down->Short). "
            f"Only if 1h and 4h clearly conflict, say No Trade. Do not counter-trade an aligned trend.\n"
            f'Reply STRICT JSON: {{"call":"Long|Short|No Trade","confidence":<1-10>}}')

def reversal_aware_lean(ticker, f):
    """Lean prompt with ONE targeted guard (the falling-knife trap) instead of many rules."""
    return (f"Crypto perp {ticker}, 2-8h horizon. Pick the more likely direction (Long or Short); "
            f"only abstain if genuinely 50/50.\n\n"
            f"{render(f, ticker)}\n\n"
            f"Default: trade with the 1h/4h trend. ONE exception — if SHORT_bounce_risk is True "
            f"(coin already crashed and is oversold on support), do NOT short; either Long the bounce "
            f"or No Trade.\n"
            f'Reply STRICT JSON: {{"call":"Long|Short|No Trade","confidence":<1-10>}}')

def final_v1(ticker, f):
    """Winning design: lean + trend-following + symmetric framing (correct the short bias) +
    ONE falling-knife guard. Deployed via 5-vote ensemble. Grounded in the data:
    - lean prompts beat rule-heavy (avoid over-abstention),
    - longs are the profitable trades (don't default to short),
    - trade WITH the higher-TF trend (the directional edge)."""
    return (f"You are a crypto perp analyst for {ticker} (2-8 hour horizon). Pick the direction more "
            f"likely to be PROFITABLE over the next several hours. Long and Short are equally valid — "
            f"do NOT default to Short.\n\n"
            f"{render(f, ticker)}\n\n"
            f"How to decide:\n"
            f"1. Trade WITH the dominant higher-timeframe trend (1h + 4h): up -> prefer Long, "
            f"down -> prefer Short, on a pullback entry.\n"
            f"2. If 1h and 4h trend agree, follow them. If they conflict, go with 4h (the stronger TF).\n"
            f"3. DO NOT short a coin that already crashed (24h < -15%) and is oversold/on support — "
            f"that is a bounce trap; prefer Long or No Trade.\n"
            f"4. Only answer No Trade when the timeframes genuinely conflict AND there is no clear edge.\n"
            f'Reply STRICT JSON: {{"call":"Long|Short|No Trade","confidence":<1-10>}}')

def final_symmetric(ticker, f):
    """Variant: explicit symmetric scoring of up vs down likelihood, then threshold — tests
    whether forcing a both-sides estimate further reduces the short bias."""
    return (f"Crypto perp {ticker}, 2-8 hour horizon.\n\n{render(f, ticker)}\n\n"
            f"Estimate independently (each 0-100):\n"
            f"- up_prob: probability price is higher in 2-8h (weigh: 1h/4h uptrend, higher-lows, "
            f"reclaim of levels, oversold bounce off support after a crash).\n"
            f"- down_prob: probability price is lower (weigh: 1h/4h downtrend, lower-highs, "
            f"confirmed breakdown, overbought fade — but NOT just 'already fell a lot').\n"
            f"Then: Long if up_prob - down_prob >= 15; Short if down_prob - up_prob >= 15; else No Trade.\n"
            f'Reply STRICT JSON: {{"up_prob":<0-100>,"down_prob":<0-100>,'
            f'"call":"Long|Short|No Trade","confidence":<1-10>}}')
