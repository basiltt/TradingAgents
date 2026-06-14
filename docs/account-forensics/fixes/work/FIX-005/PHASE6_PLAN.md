DIRECTIONAL DISCIPLINE — Phase-6 RM prompt addition (draft)
=========================================================
Source: signal_research Phase 4-5. WINNER final_v1 beat production baseline:
  dir_pnl +1.195% vs +0.436% (2.7x), dir_acc 60.6% vs 56.6%, short/long 48/27 vs 134/16.

Rules proven to drive the lift (to encode into the crypto Research Manager prompt,
which is the directional decision point, crypto_analysts.py:632):

1. TRADE WITH THE DOMINANT HIGHER-TIMEFRAME TREND.
   - If the 1h and 4h trend agree, follow them (up -> Buy/Overweight, down -> Sell).
   - If 1h and 4h conflict, defer to the 4h (stronger TF) or Hold.
   - Do NOT counter-trade an aligned multi-timeframe trend.

2. LONG AND SHORT ARE EQUALLY VALID — REMOVE THE SHORT BIAS.
   - The current "require stronger evidence for Sell than Buy" guidance has produced a
     ~8:1 short skew that LOSES money; longs were the more profitable trades in
     backtest. Weigh the bull and bear cases SYMMETRICALLY.
   - An uptrend with higher-lows is just as tradeable (Buy) as a downtrend breakdown.

3. ANTI-FALLING-KNIFE GUARD (the single biggest loss source).
   - Do NOT issue Sell on a coin that has already crashed (24h < -15%) AND is oversold
     (RSI < 32) / sitting on support. That is a dead-cat-bounce trap; prefer Hold or,
     if a reversal is confirmed, Buy the bounce.
   - A low RSI in a confirmed downtrend is continuation (Sell-with-trend is fine); a low
     RSI after a capitulation crash on support is a bounce risk (do NOT short).

4. CONFIDENCE CALIBRATION.
   - The model is overconfident: in backtest, conf 5-6 calls were MORE accurate (71%)
     than conf 7-10 (57%). Do not inflate confidence; a moderate, well-reasoned lean
     outperforms a loud one.

5. KEEP IT LEAN — DO NOT OVER-ABSTAIN.
   - Rule-stuffing made the model answer "No Trade" 80-100% of the time in tests.
     Reserve Hold for genuine TF conflict / no edge; otherwise commit to the
     trend-aligned direction.

Deployment mechanism (separate from prompt): self-consistency ENSEMBLE — run the RM
decision N=5 times and majority-vote, for both accuracy and reproducibility (stable
signal across re-runs). See _ensemble.py.

MTF feature note: the RM currently works "solely on debate history" with no explicit
multi-timeframe trend. The market analyst already computes EMAs/RSI; ensure the 1h/4h
trend alignment is surfaced into the debate/confluence summary the RM reads.
