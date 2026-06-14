# FIX-005 — Structured signal shorts oversold/bounce-prone coins

**Status:** identified
**Severity:** High (signal quality)
**First seen:** Unni investigation (2026-06-14)
**Accounts affected:** system-wide (signal generation — all accounts that trade these signals)

## Symptom
6 of Unni's 7 trades were shorts, several into coins that had already crashed and were bouncing.
The worst — ESPORTS — was shorted at 0.06654 after a −72%/24h crash, sitting on the 0.060
support with RSI ~33, and it immediately ripped +15.7% into the stop. The signal shorted a
falling knife at the moment it reversed.

## Evidence — production-parity LLM replay
We re-ran each signal through the **exact production model** (MiniMax-M2.7-highspeed) on
point-in-time, no-look-ahead indicators. It **disagreed with 5 of 7** recorded signals, and in
every disagreement flagged **reversal/bounce risk**:

| Symbol | Prod | MiniMax replay | Rev-risk | Actual move after entry |
|--------|------|----------------|----------|-------------------------|
| ESPORTS | Short | **No Trade** | **HIGH** | +15.7% adverse |
| NOKIA | Short | No Trade | high | +0.7% |
| TSTBSC | Short | No Trade | high | +2.5% |
| B3 | Short | **Long** | low | (fell later — lucky) |
| FOLKS | Long | No Trade | medium | −4.5% |
| GWEI | Short | Short ✓ | medium | +3.0% |
| HMSTR | Short | Short ✓ | medium | −6.8% (favorable) |

ESPORTS verdict: *"Price near 0.060 support, no breakdown confirmed; RSI near 33 and bounce
possible; risk of reversal high."* The production model itself would not have opened the trade
that caused 88% of the loss.

## Root cause
The structured signal path (`tradingagents/agents/crypto_analysts.py` and the scanner's
structured-signal route) shorts on short-term EMA alignment without sufficiently weighting
mean-reversion/bounce risk on already-stretched, oversold, beaten-down coins. Counter-trend
shorts (B3 had EMA9>EMA21, RSI 60.8, +4.3%/24h) also slipped through.

## Fix approach (proposed)
1. Add a **bounce/mean-reversion guard** to short signals: penalize or veto shorts on coins
   already down more than X% in 24h, sitting on/near support, with RSI < ~35.
2. Require a **confirmed breakdown** (close below a defined support level) rather than mere
   EMA alignment before a high-conviction short on a crashed coin.
3. Consider surfacing a `reversal_risk` field in the structured signal so downstream gates can
   filter — the production model already reasons about it when asked.

> Caveat: this is a signal-*quality* contributor, not the proximate cause of Unni's $19 loss
> (that was the exit machinery — FIX-002/003/004). But it set up the bad trade, and it recurs
> across accounts (Jerin lost on the same MEGA/ARIA/FOLKS counter-trend shorts). LLMs are
> non-deterministic and the replay used a distilled single-prompt rubric, so treat the
> *direction* of the finding as robust, not exact scores.

## Verification plan
- Re-run the replay harness (skill Stage 4) on a future scan; measure short-signal agreement and
  the rate of HIGH-reversal-risk shorts before/after the guard.
- Backtest the guard over historical scans: does vetoing high-reversal shorts improve net PnL?

## Cross-references
- Account findings: `../accounts/unni/FINDINGS.md`
- Evidence: `../accounts/unni/REPORT.md` §4 (LLM signal replay)
- Tooling: `investigate-account` skill Stage 4 (`s4_llm_replay.py`)
