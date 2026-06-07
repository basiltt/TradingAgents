# Profitability Research Report — 2026-06-07 01:26 UTC

**Focus question (from operator):** *"Profitability is reducing when the market is choppy. I'm thinking of running multiple strategies on multiple markets. How can we earn money in a choppy market?"*

This report is regime-focused: it answers that question with data rather than running the full standard sweep.

---

## 1. Executive Summary

**The headline is counterintuitive: aggregate profitability is at an all-time high, not falling.** Total system PnL grew **$1,370.92 → $2,065.28** (+$694) since the 2026-06-04 baseline, and the **last 48h is the best window in the entire dataset** ($989.70 PnL, **$1.80/trade**, 59.5% win rate). The prior round of fixes (min_score 7, max_trades 3, drift filter, blacklist, trailing profit) clearly worked.

**But the operator's instinct is correct — there is a real, large, recurring choppy-market leak, and it is precisely localizable.** The losses are not diffuse "bad luck." They are concentrated in **a specific market session** and **a specific trade-shape**:

1. **The system is a directional SHORT engine, not an all-weather system.** Shorts: 5,251 trades, **+$2,149**. Longs: 364 trades, **−$106** (−$0.29/trade, unprofitable in every regime). The edge is "sell into weakness," which works in trending/volatile tape and **fails in ranging tape**.

2. **The choppy leak = the Asian session.** Trades opened roughly **23:00–09:00 UTC bleed massively** (last 5 days: −$474, −$291, −$285, −$199, −$86 across those hours = **~−$1,335 lost in 5 hours-of-day over 5 days**, win rates 0–31%). The US/EU session (13:00–20:00 UTC) is where nearly all profit is made (win rates 57–86%). Asian-session crypto is the textbook low-volatility, mean-reverting, choppy regime — and the trend-following short engine gets chopped to pieces in it.

3. **"Multiple strategies on multiple markets" is the right architecture — but today you have the OPPOSITE: one strategy on 21 accounts (false diversification).** All 21 accounts trade the **same signals at the same time**, so a bad scan is a **21× correlated loss**, not a hedge. On 2026-06-06 13:00, 12–13 accounts all opened TAUSDT / ARMUSDT / POPCATUSDT in the same hour and all lost together (−$268 batch). There is currently **zero strategy diversification** — only capital replication.

4. **Trade-shape confirms the chop mechanism.** Trades held **1–3h win big** (+$1,532, 54.9%); trades held **3–6h lose** (−$97, 42%). In chop, a position that doesn't hit TP quickly gets ground down before the 24h timeout. The current TP (150% of margin) is a *trend* target applied indiscriminately to *ranging* tape.

**The single most actionable lever:** a **regime/session filter** that detects chop (by time-of-day session and/or realized volatility) and either suppresses the trend-short strategy or swaps in a chop-appropriate mean-reversion strategy. This is higher-impact and far cheaper than literally adding new markets.

---

## 2. Changes Since Last Report (what shipped and how it's doing)

| Recommendation (2026-06-04) | Status | Early result |
|---|---|---|
| Raise min_score 6 → 7 | ✅ SHIPPED | Validated. Score 7 = +$1,268 (53.2% WR), score 8 = +$477 (54.9%). Score 6 = +$134 (45.3%) — far weaker, confirms the cutoff. |
| Reduce max_trades 5 → 3 | ✅ SHIPPED | Config confirms `max_trades: 3`. |
| Post-scan price-drift filter | ✅ SHIPPED | `max_price_drift_pct: 3`, `max_signal_age: 120min` live. |
| Symbol blacklist | ⚠️ SHIPPED BUT LEAKY | Blacklist is configured, but see §8 — toxic symbols still being traded under *new* tickers, and the old blacklist entries only stopped ~06-03/04. |
| Trailing stop after +2% | ✅ SHIPPED | `trailing_profit_pct: 2` live. |
| Lower profit goal 14% → 8% | ✅ SHIPPED | Most accounts now `target_goal: 8`. |
| 93% sell-bias root-cause fix | ✅ SHIPPED | Longs went from ~7% to ~10% of volume — but **longs are still unprofitable** (see §4). The fix removed the *bug*; it did not create a *long edge*. |
| Fix AI Manager execution pipeline | 🔶 PARTIAL | `external` closes (AI/manual) = 1,118 trades at **+$0.03 avg** — essentially break-even noise. AI manager is not yet a profit contributor. |

**Net:** PnL +$694 since baseline. The fixes converted a marginal system into a solidly profitable one **in its favored regime**. They did not address the regime problem itself — which is now the dominant remaining leak.

---

## 3. The Choppy-Market Leak, Quantified

### 3a. By session (hour-of-day, UTC) — the clearest signal in the entire dataset

| Session | Hours (UTC) | Character | Result |
|---|---|---|---|
| **US/EU active** | 13:00–22:00 | Trending, volatile | **Strongly profitable** — hrs 15,16,18,19 all +$280–$614, win rates 57–68% |
| **Early US / late EU** | 02:00–05:00 | Volatile | Profitable — hr 4 +$523, hr 5 +$350 (85.8% WR!) |
| **Asian / low-vol** | **01:00, 06:00–12:00** | **Choppy, mean-reverting** | **Bleeding** — hr 11 −$533 (21% WR), hr 1 −$468 (38%), hr 7 −$298 (24%), hr 9 −$262 (17%), hr 8 −$185 (41%) |

**Last-5-day persistence check (this is not historical noise):** hours 1, 7, 8, 9, 11 lost **−$474, −$199, −$291, −$86, −$285** respectively in just the last 5 days, win rates **25%, 22%, 18%, 0%, 31%**. This is a live, repeating leak.

**Interpretation:** crypto's Asian session is the canonical choppy regime — tight ranges, low volume, frequent fakeouts. A momentum-short strategy enters on a down-tick, price mean-reverts, and the trade either stops out or gets ground to a scratch-loss. The US session brings real directional volume, and the same strategy prints money.

### 3b. By trade-shape (hold time) — the chop mechanism

| Hold time | Trades | Total PnL | Win rate | Reading |
|---|---|---|---|---|
| 0–1h | 1,967 | +$338 | 44.1% | Fast TP hits + fast stop-outs mixed |
| **1–3h** | 1,953 | **+$1,532** | **54.9%** | **The money zone** — trend follows through to TP |
| 3–6h | 919 | **−$97** | 42.0% | **Chop zone** — didn't hit TP fast, now grinding down |
| 6–12h | 621 | +$233 | 46.1% | Survivors that eventually trend |
| 12h+ | 155 | +$38 | 35.5% | Timeout-bound stragglers |

A trade that hasn't resolved in ~3h is in chop and statistically should be cut, not held to the 24h `max_trade_duration`.

---

## 4. Direction: You Have ONE Edge, Not Two

| Direction | Trades | Total PnL | Avg | Win rate |
|---|---|---|---|---|
| **Short (Sell)** | 5,251 | **+$2,149** | +$0.41 | 47.8% |
| **Long (Buy)** | 364 | **−$106** | −$0.29 | 43.4% |
| Long, last 7d | 125 | **−$71** | −$0.57 | 55.2% ⚠️ |

The last-7-day long row is the most instructive in the report: **55.2% win rate but −$0.57/trade**. The longs win slightly more than half the time and **still lose money** — meaning long losers are much bigger than long winners. The system has no long edge; it has a long *liability*. Daily breakdown confirms longs are random: +$32 one day, −$107 the next (2026-06-06, 7 trades, 14% WR).

**Strategic consequence:** when people say "trade both directions to survive choppy markets," that only works if you have a *validated* long strategy. You do not. Bolting more long trades onto this engine would *increase* the chop leak, not hedge it. A genuine second strategy must be **designed and validated as a mean-reversion system**, not "the same model allowed to go long."

---

## 5. The "21 Accounts" Illusion — Correlation, Not Diversification

All 21 accounts consume the **same scan signals in the same scan cycle**. They differ only in capital %, leverage, and AI-manager on/off — **not in strategy, market, or timing**. Consequences from the data:

- **Account PnL rank-orders almost perfectly by leverage/capital, not by skill.** Every account is 20× now; spread (−$18 to +$387) is mostly capital-% and variance, not strategy edge.
- **Correlated drawdowns.** 2026-06-06 13:00 batch: TAUSDT opened by **12 accounts**, ARMUSDT by **13**, POPCATUSDT by **11** — all in one hour, all losing (−$268 combined). When the strategy is wrong, it's wrong 21 times simultaneously.
- **38 "big loss batches" (<−$20/hr) vs 51 "big win batches"** — the loss batches are deep because every account piles into the same losers.

**This is the strongest argument for the operator's own proposal.** "Multiple strategies on multiple markets" is correct — but the first step isn't *more* accounts, it's making the *existing* accounts strategically distinct so they stop losing in lockstep.

---

## 6. Symbol & Blacklist Findings

### Blacklist IS enforced — the leak is NEW tickers, not the listed ones
**CORRECTION (post-audit):** An earlier draft of this report flagged BIGTIME/SOXL/PLAYSOUT as "reappearing despite being blacklisted." A direct enforcement audit **disproves that** — all three last traded **2026-06-03** and have had **zero trades since** the blacklist deployed (~06-04). The static blacklist works for *listed* tickers. The misleading signal was a **7-day-window artifact**: the lookback reached back past the blacklist date and swept up the pre-blacklist 06-03 blowup. (`pnl_7d` for these even exceeds their all-time loss, because they *made* ~$86 early in trending tape — e.g. PLAYSOUT +$80 on 05-27 — then gave it back in 06-03 chop.)

**The 06-03 blowup itself is the lesson:** ~−$344 lost across the three in a single choppy day, each hitting **16–23 accounts simultaneously** (BIGTIME 21, PLAYSOUT 23, SOXL 16). The blacklist is **reactive** — it bans a coin *after* a correlated 16–23× loss, never before.

**The real exposure is the *next* toxic coin, not the named ones.** Same pattern reappeared this week under tickers not yet on any list:

| New toxic (7d) | Trades | PnL | Win rate |
|---|---|---|---|
| BABYUSDT | 19 | −$208 | 15.8% |
| PARTIUSDT | 17 | −$197 | 0.0% |
| TAUSDT | 12 | −$196 | 0.0% |
| HOMEUSDT | 17 | −$114 | 0.0% |
| HMSTRUSDT | 7 | −$107 | 14.3% |
| ARKMUSDT, MUBARAKUSDT, PENDLEUSDT, MIRAUSDT | — | −$64 to −$96 each | <16% |

A static blacklist is a treadmill — low-float meme/new-listing coins rotate faster than you can ban them, and each is only banned *after* it has already cost a correlated 16–23× loss. **The durable fix is a structural filter** (min 24h volume, min listing age, max spread, exclude coins whose price action is pure noise) that rejects them *pre*-blowup — which a name list can never do.

### Golden symbols (7d) — these are trending, liquid names
BARDUSDT (+$211, 100% WR), NOKIAUSDT (+$203, 100%), COINUSDT (+$190, 66%), BILLUSDT (+$183, 79%), GIGAUSDT (+$176, 100%), DEEPUSDT, B3USDT (93%). The winners are **higher-liquidity, trending tickers** — exactly the inverse of the toxic set. This validates a liquidity/quality structural filter.

---

## 7. Close-Mechanism Health

| Close reason | Count | Avg PnL | Total | Reading |
|---|---|---|---|---|
| rule_triggered (TP/SL/timeout) | 4,078 | +$0.42 | **+$1,725** | The core engine — healthy |
| manual_close_all (equity rise/drop) | 401 | +$1.12 | +$447 | Profit-lock is working well |
| external (AI mgr/manual) | 1,118 | +$0.03 | +$36 | **Break-even noise — AI mgr adds ~nothing** |
| liquidation | 13 | −$12.85 | **−$167** | Should be zero — SL not always protecting |
| stop_loss / take_profit (explicit) | 5 | — | +$1.5 | Negligible |

**Win-day vs lose-day split is the cleanest regime tell:** on **win days** `rule_triggered` = +$1.09 avg (+$2,578 total); on **lose days** the *same mechanism* = −$0.50 avg (−$853). Same rules, opposite outcome — because the **input regime** flipped. This proves the leak is upstream (signal/regime selection), not in the close logic.

**Liquidations (−$167, avg −$12.85, 2.4h hold):** 13 trades blew through SL to liquidation. At 20× a fast adverse move skips the stop. These cluster in volatile hours and are a leverage-risk issue (see §11).

---

## 8. How to Actually Earn in a Choppy Market (the direct answer)

Your hypothesis — *"multiple strategies on multiple markets"* — is directionally right but needs to be re-sequenced. You do not earn in chop by adding markets; you earn by (a) **not bleeding** in chop with the trend strategy, and (b) deploying a strategy whose edge *is* mean-reversion. Three concrete ways, in priority order:

### Way 1 — Regime detection + suppression (biggest, cheapest win)
**Don't trade the trend-short strategy during detected chop.** Detection signals available today:
- **Session filter (zero new infra):** down-weight or skip trades opened in UTC hours **01, 06–12** (the proven bleed window). Even a blunt "no new entries 06:00–12:00 UTC" would have avoided ~−$1,300 over the last 5 days alone.
- **Volatility filter (light infra):** compute realized volatility / ATR% on BTC (regime proxy) at scan time. If BTC 1h realized-vol is below a threshold → market is ranging → suppress trend entries or require score 8+.
- **Breadth filter:** the scan already produces signal counts. A scan that yields **few high-conviction signals** is itself a chop tell — when actionable signals dry up, the regime has turned. Gate entries on minimum breadth.

**Expected impact:** removing/halving the Asian-session leak is worth **~$200–$300/day** based on current bleed rates — larger than any single golden-symbol gain.

### Way 2 — A genuine mean-reversion strategy for chop (the real "second strategy")
This is where "multiple strategies" pays off. In a *range*, the money is made by **fading extremes, not chasing breaks**:
- Entry: price at upper/lower band of an established range (Bollinger/Keltner, RSI overbought/oversold) **with no trend confirmation**.
- Target: the *mid-band* (mean), **not** 150%-of-margin. Chop TPs must be **small and fast** (recall: 1–3h holds win; 3–6h holds lose).
- Tight invalidation: if price breaks the range, exit immediately — a failed mean-reversion is a trend starting.
- **Only active when the regime detector says "chop."** Trend-short runs in trending regime; mean-reversion runs in ranging regime. They are **mutually exclusive by regime**, which is exactly what makes them a hedge rather than 2× correlated risk.

### Way 3 — Strategy-segment the 21 accounts (turn replication into a portfolio)
Instead of 21 clones, partition accounts into **strategy cohorts**:
- Cohort A (trend-short, current engine) — runs US/EU session.
- Cohort B (mean-reversion) — runs Asian/low-vol session.
- Cohort C (long-only, *if/when* a long edge is validated) — currently **none qualify**; do not fund this until backtested.

Now a bad trend-scan hurts Cohort A but Cohort B is flat or hedged — **real diversification**, and your equity curve smooths through regime changes instead of lurching.

> **Build-it note:** the **Backtesting System** currently in flight (per CLAUDE.md) is the correct vehicle to validate Ways 2 & 3 *before* risking capital. Do not deploy a mean-reversion strategy live until the backtester shows positive expectancy in the 06:00–12:00 UTC chop window on historical scan data. The backtester should be **regime-segmented** (report metrics per session/volatility bucket), or it will average the chop leak into the trend profit and hide the very effect this report isolates.

---

## 9. Recommendations (prioritized)

| # | Recommendation | Impact | Effort | Why |
|---|---|---|---|---|
| 1 | **Session/regime entry filter** — suppress or score-gate entries in UTC 01,06–12 | 🔴 Very High (~$200–300/day) | Low | Proven, persistent, localized leak. Fastest ROI in the system. |
| 2 | **Structural symbol filter** (min 24h vol, listing age, max spread) replacing/augmenting static blacklist | 🔴 High (−$1,000+ of recent toxic losses) | Low-Med | Ticker churn defeats name lists; toxic coins share liquidity traits. |
| 3 | **Cut the long side to zero** until a long strategy is backtested | 🟠 Med (+$106 stop-bleed, removes tail risk) | Trivial | Longs lose in every regime; 55% WR but negative expectancy. |
| 4 | **Tighten chop exit**: if a trade hasn't hit TP in ~3h during detected chop, cut to breakeven/scratch | 🟠 Med (3–6h bucket is −$97 and growing) | Med | 3–6h holds are the chop death-zone. |
| 5 | **Backtest a mean-reversion strategy** for the chop window (regime-segmented metrics) | 🟢 High (long-term) | High | The actual "earn in chop" engine. Validate before funding. |
| 6 | **~~Audit blacklist enforcement~~ — RESOLVED** (audited: blacklist holds, BIGTIME/SOXL/PLAYSOUT zero trades since 06-03) | — | Done | No gap; earlier flag was a 7-day-window artifact. |
| 7 | **Strategy-cohort the accounts** (A=trend US session, B=mean-rev Asian session) | 🟢 High (smooths equity curve) | High | Converts false diversification into a real portfolio. |
| 8 | **Reduce leverage on chop-session cohort** 20× → 10× | 🟠 Med (−$167 liq + variance) | Low | 10× had best risk-adjusted returns historically; chop + 20× = liquidation risk. |

---

## 10. New Discoveries (not in prior research)

1. **Session-of-day is the dominant profit factor** — stronger and more persistent than score, symbol, or account. The Asian session is a structural −EV window for this strategy. *(Prior research never bucketed by hour-of-day.)*
2. **"55% win rate, negative expectancy" on longs** — proves win-rate is a vanity metric here; the long book has a fat-left-tail. Direction edge must be measured in expectancy, not hit-rate.
3. **The 1–3h vs 3–6h cliff** — there is a sharp profitability cliff at ~3h hold time. Trades are either fast trend-followers (win) or slow chop-grinders (lose). This is a clean, actionable exit signal.
4. **Toxic symbols rotate by ticker** — the blacklist is a treadmill; the underlying trait is low liquidity / new listing, which is filterable structurally. **A toxic coin hits 16–23 accounts simultaneously before it gets blacklisted** (BIGTIME/SOXL/PLAYSOUT each blew up on 06-03 across 16–23 accounts, ~−$344 in one day, *then* were banned) — the name-list is purely reactive.
5. **AI manager is break-even noise** (+$0.03/trade over 1,118 closes) — not yet earning its complexity. Either fix its edge or simplify.

---

## 11. Equity / Risk Patterns

- **Daily PnL swings are widening** as volume grows: 2026-06-05 +$827, 2026-06-06 +$233, partial 2026-06-07 **−$207** (14% WR, 21 trades). The −$207 partial-day is an Asian-session chop print, consistent with §3a.
- **Hourly PnL std is rising** (06-06 std $157 vs 05-30 std $14) — bigger position counts mean bigger correlated swings (§5). Without strategy diversification, equity volatility scales with capital.
- **13 liquidations (−$167)** at 20× — the tail risk of running max leverage into volatile/illiquid names.

---

## 12. Appendix — Key Raw Data

- **System:** 4,924 trades, 28 open, 51.0% WR, **+$2,065.28** total, +$0.42/trade.
- **Direction:** Short +$2,149 (5,251 tr) / Long −$106 (364 tr).
- **Score:** 7→+$1,268 (53.2%), 8→+$477 (54.9%), 6→+$134 (45.3%), 5→−$16, 9→−$29 (n=3).
- **Hold:** 1–3h +$1,532 / 3–6h −$97.
- **Worst hours (UTC):** 11 (−$533, 21%), 1 (−$468, 38%), 7 (−$298, 24%), 9 (−$262, 17%).
- **Best hours (UTC):** 22 (+$619), 19 (+$614), 4 (+$523), 10 (+$446), 5 (+$350, 86%).
- **Close:** rule_triggered +$1,725 / manual_close_all +$447 / external +$36 / liquidation −$167.
- **Momentum:** last 48h +$990 (59.5% WR, $1.80/tr) vs prior 3–7d +$876 (52%).
- **Top accounts:** Dad +$387, Appu +$210 (67% WR), Autotrader +$197. **Bottom:** Jerin −$18, Brother −$14.
- **Config:** min_score 7, max_trades 3, TP 150%, SL 100%, drift 3%, signal_age 120m, trailing 2%, 20× most accounts.

---

*Generated by the profitability-research skill. Regime-focused run prompted by operator's choppy-market question. No code changed — research only.*


