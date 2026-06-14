# Drawdown Root-Cause & Prevention — Proof Pack

Backtest under study: run `5460914a` — Every-2-Hour schedule, 2026-06-04 → 06-11,
$234 start, lev 8, capital 22%, max_trades 3. Result: **+$999.92 (+427%), max DD 17.91%.**

All experiments below were run on the **REAL BacktestEngine**. The offline harness
(`scripts/squeeze_research/harness.py`) reproduces the baseline **bit-exact**
(net 999.9207011072158, dd 17.910244812110403 — identical to 13 decimals), so every
delta here is trustworthy. No production code was modified.

---

## 1. What the drawdown actually is

The −17.91% max DD is a **short-squeeze tail**. 47 of 48 trades are SHORTS (the
strategy fades pumped alts expecting reversion; its edge depends on surviving adverse
wicks). Two squeeze events caused the whole drawdown:

| When | Trade(s) | Loss | Close reason |
|---|---|---|---|
| 6/7 01:00 | TSTBSCUSDT −47.2%, POLYXUSDT −20.0% (same scan) | −$95 | equity_drop_smart |
| **6/8 01:25** | **SAHARAUSDT −87.5%** (peak $696→$571) | **−$125** | stop_loss |

SAHARA (verified vs Bybit): a short that **ground +11% UP over 11h** at 8× = −87% of
margin. BTC was flat/up during both events (+1.15%, +1.75%) → **not** a market-wide move.

---

## 2. Every "obvious" fix BACKFIRES (proof it's not a stop/filter problem)

| Approach | Max DD | Net P&L | Verdict |
|---|---|---|---|
| **Baseline** | **17.9%** | **+$999** | — |
| Stop loss 100→50 | 30.8% | +$340 | ❌ worse |
| Stop loss 100→60 + max_same_dir 2 | 64.8% | −$31 | ❌ catastrophic |
| Portfolio DD stop 12→8 | 35.8% | +$289 | ❌ worse |
| Portfolio DD stop 12→6 | 36.1% | +$269 | ❌ worse |
| **Blacklist the 3 losers (perfect hindsight!)** | **51.5%** | +$457 | ❌ WORSE |
| Vol-veto shorts ATR%≥0.80 (selection filter) | 53.4% | −$1 | ❌ catastrophic |
| max_trades 3→2 + lev 7 | 28.1% | +$117 | ❌ worse |

**Why they all fail — proven by trade-diff** (`diff_trades.py`): removing ANY entry
(even the 3 known losers) reshuffles `fill_to_max_trades` backfill into different
symbols, shifts every later scan's selection + drawdown-stop timing, and changes when
`cooloff_on_double_failure` fires. Concretely, the vol-veto:
- **Avoided** the 3 squeezes — but in doing so dropped the slate that netted **+$802**
  of winners (B3 +101, BABA +90, AIO +83, HEMI +76, MRVL +68…).
- **Backfilled** 28 NEW trades netting **−$103**, including a *brand-new* HOMEUSDT
  −87.6% squeeze and a cascade of equity_drop_smart losses.

The trade path is **chaotically coupled**. You can't surgically delete 3 trades.

---

## 3. The squeezes are nearly unfilterable at entry

Tested against Bybit + the engine's loaded klines:
- **Momentum / run-up / extension**: do NOT separate squeezes from winners (winner
  AIO entered +24.7% pumped and won +34%; winners routinely go deep underwater first).
- **Liquidity / 24h turnover**: a floor catching all 3 losers (<$5M) also kills **27
  of 40 winners** (BABA won +42% on $62K turnover).
- **Pre-entry ATR%** DID separate them (squeezes 0.84–0.95 vs winner median 0.51) —
  but vetoing on it still backfired (§2) because of path-coupling. A good feature is
  not enough when removing the trade poisons the path.

---

## 4. The ONLY robust lever: position sizing (leverage)

Leverage scales every trade proportionally without changing *which* symbols rank/fill
the same way an entry filter does, so it tames the tail far more reliably:

| Config | Max DD | Net P&L | Net % | Win% | Sharpe | PF | Largest loss |
|---|---|---|---|---|---|---|---|
| **Baseline (lev 8)** | 17.9% | +$999 | +427% | 83.3% | 18.2 | 4.99 | −$125 |
| **lev 7** ⭐ | **11.2%** | **+$321** | **+137%** | 71.9% | 11.0 | 3.32 | **−$38** |
| lev 6 | 12.9% | +$228 | +97% | 72.7% | 9.8 | 2.61 | −$37 |
| lev 5 | 12.4% | +$219 | +94% | 80.6% | 13.6 | 2.57 | −$35 |
| lev 6 + capital 15% | 5.6% | +$159 | +68% | 69% | 10.4 | 4.65 | −$16 |

**Leverage 7** is the recommended single change: max DD **11.2%** (under your 12%
target), still **+137%** profit, and the worst single trade shrinks from −$125 to −$38.

Logical-capital check: deployed margin = capital_pct 22% × max_trades 3 = **66%** of
equity per cycle (≤ 97% bound, leaves fee/funding headroom). Leverage does not change
this; it only reduces amplification. ✓

---

## 5. Volatility-targeted SIZING (keep every trade, shrink the volatile ones)

The one idea that doesn't *remove* trades: scale each short's `capital_pct` down by
its pre-entry ATR% (squeeze-prone names bet smaller, calm names full size; never
ABOVE base, so deployed margin only falls — ≤97% bound respected trivially).

Trade-diff proof it does the right thing on the squeezes (pivot 0.75 / min 0.70):
- SAHARA −$125 → −$73 (qty 32.9k → 19.1k), TSTBSC −$67 → −$45, POLYX −$28 → −$20.

But it is path-LIGHT, not path-free: smaller positions grow equity slower, so the
`target_goal_value=15` EQUITY_RISE flush + `fill_to_max` fire on different bars and
the path forks (48 → 44 trades; drops +$464 of baseline winners, adds +$84 of new).

### Out-of-sample robustness (the decisive test)

| Window | Baseline DD / Net | VolSize DD / Net |
|---|---|---|
| orig 6/04-11 | 17.9% / +$999 | 14.1% / +$683 |
| full 6/04-13 | 17.9% / +$1089 | 14.1% / +$622 |
| oos 6/08-13  | 17.5% / +$317 | 10.8% / +$136 |
| oos 6/09-13  | 15.3% / +$179 | 13.0% / +$61  |

**Vol-sizing robustly lowers drawdown on EVERY window (not curve-fit) — but it also
lowers profit on every window (−35% to −66%).** Worst-trade sometimes grows on OOS
windows due to path forks. It is a real de-risking lever, but mathematically it is
"bet less" — the same axis as lowering leverage.

---

## CONCLUSION

Across entry filters, stop tightening, portfolio stops, selection re-ranking, AND
volatility-targeted sizing — **no intervention cuts this drawdown without
proportionally cutting profit.** On this config the two are ONE axis, because:

1. The squeeze risk is intrinsic to a 47/48-short, fade-the-pump strategy.
2. `EQUITY_RISE flush (target_goal 15) + fill_to_max_trades + double_failure cooloff`
   make the trade path hypersensitive — any per-trade change forks the whole history,
   so you cannot surgically excise the 3 bad trades; you can only scale total risk.

The decision is therefore a **risk-appetite** choice, not a filter to add:

| Setting | Max DD | Net (orig week) | Notes |
|---|---|---|---|
| Baseline lev8 | 17.9% | +$999 (+427%) | max profit, deepest DD |
| Vol-size .75/.70 (lev8) | 14.1% | +$683 (+292%) | best DD-for-profit among interventions |
| **Leverage 7** | **11.2%** | +$321 (+137%) | simplest; DD under your 12% target |
| Leverage 6 + cap 15 | 5.6% | +$159 (+68%) | most conservative |

Recommendation: **leverage 7** (one number, robust, DD < your 12% target) — OR
vol-sizing .75/.70 if you want to keep more upside and accept ~14% DD. Both are
config/sizing changes; neither requires a new engine filter.

---

## 6. Adaptive profit target — "let winners run, cut losers early" (user idea)

Tested whether replacing the fixed +15% equity-rise flush with a dynamic target
(extend when book momentum favorable, close early when it turns) captures more
profit at the same ~18% DD.

### Does holding past +15% even have edge? (forward measurement)

At each of the 26 cycle +15% crossings, measured the MAX cycle rise reachable over
the next 24 candles (2h) if the book were held frozen:
- avg forward max rise **+22.5%** vs +15-17% at the cross → **avg hold benefit +6%**,
  positive in **25 / 26** cases.

So there IS a forward edge on paper. But it is an UPPER BOUND (the peak), not a
realizable exit.

### Can it be captured? (realized backtests — NO)

Raising the static target, in the REAL engine:

| target | Max DD | Net P&L | Net% |
|---|---|---|---|
| **15 (baseline)** | **17.9%** | **+$999** | **+427%** |
| 18 | 12.2% | +$398 | +170% |
| 20 | 22.3% | +$198 | +85% |
| 22 | 23.3% | +$307 | +131% |
| 25 | 32.8% | +$155 | +66% |
| 30 | 32.8% | +$203 | +87% |
| no flush (1000) | 32.8% | +$164 | +70% |

Momentum-gated adaptive versions (extend on favorable book, give-back early close):
best was +$574 — still well below the +$999 baseline, and some blew DD to 36%.

### Why "let it run" fails despite the forward edge

1. The +6% forward benefit is the cycle PEAK; to realize it you must exit at the
   perfect bar. Holding to a higher fixed/dynamic target rides PAST the peak and the
   volatile shorts reverse (squeeze risk is live the whole hold) — giving it back.
2. The +15% flush's hidden value is FAST CAPITAL RECYCLING: bank 15%, free the book,
   redeploy into the next scan's fresh winners. Compounding 15%-quick beats 22%-slow.
   At "no flush" profit collapses to +$164 — capital sits in aging positions.
3. Path-fork tax on top (holding changes every later cycle's entries).

**Conclusion: the fixed +15% flush is already near-optimal — it is load-bearing,
not a limitation. "Let winners run" is intuitive but the data shows this strategy's
edge is fast capital recycling at a modest target; extending it destroys that.**

---

## 7. Squeeze hedge / flip (user idea) — NO EDGE at the trigger

Idea: when a short is squeezing hard against us, OPEN a hedge / FLIP to long instead
of just bleeding to the stop. Tested the prerequisite FIRST (does the squeeze persist
past an adverse trigger?) before building any rule.

Measured every short that hit −X% adverse margin, then what price did over the next 2h:

| Adverse trigger | Continued UP (flip wins) | Reverted (flip loses) | Flat |
|---|---|---|---|
| −30% | 2 | **6** | 2 |
| −40% | 2 | **5** | 0 |
| −50% | 3 | **4** | 0 |
| −60% | 1 | **3** | 2 |
| −70% | 2 | **4** | 0 |

**At EVERY trigger, reversion dominates continuation.** A short that's deep underwater
is more likely to revert than keep climbing — which is precisely WHY the fade-the-pump
edge exists. Trades that hit −40% adverse and still WON: TRUTH (→+15%), BSB (→+16%),
BLESS (→+32%). A flip/hedge at the trigger would have:
  1. Bought the local top and lost 4–6 times out of 7, and
  2. Destroyed the winners that recover (most of them).

SAHARA (the one that kept going) is indistinguishable from TRUTH/BSB/BLESS at the
trigger instant — same unfilterable-at-the-moment problem, now proven on the
exit/reaction side too.

**Conclusion: flip/hedge has negative expectancy here. Reacting to the squeeze loses
more than absorbing it, because deep-adverse shorts usually revert (that's the edge).**
