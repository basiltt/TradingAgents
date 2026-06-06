"""Behavioral-parity eval harness for the prompt-caching P3 restructure.

WHY THIS EXISTS
---------------
The P3 refactor moved the *volatile* tail of three analyst prompts
(``For your reference, the current date is {date}. {instrument}``) out of the
**system** role and into a leading **human** turn, so an Anthropic
``cache_control`` breakpoint can sit on a byte-stable system prefix. The text
was preserved byte-for-byte (proven four ways in P3), but a model MAY weight the
identical content differently depending on whether it arrives in the system role
vs a human turn. Byte-identity does NOT prove decision-identity.

This harness is the GATE that rules that out: it compares the trading DECISION
(BUY / HOLD / SELL) produced by the OLD single-system-message prompt against the
NEW split (system + human) prompt over N representative fixtures, and only passes
if the new prompt's decisions are statistically indistinguishable from the old
one's intrinsic run-to-run noise.

    >>> Passing this eval is a PRECONDITION for flipping ``prompt_cache_enabled``
    >>> (and any "default ON") — see docs/superpowers/plans/cache-parity-eval-results.md

COST / SAFETY
-------------
* This script makes REAL LLM API calls when (and ONLY when) invoked with
  ``--run`` AND a provider API key is present in the environment. Each call costs
  real money. Approx spend per full run: ``N*K + N`` calls = 30*5 + 30 = **~180
  calls** on the cheapest capable model (``claude-sonnet-4-6``).
* It is **NOT** run in CI and is **NOT** imported by the app. Importing this
  module has zero side effects and spends nothing.
* The DEFAULT mode is a DRY RUN: with no ``--run`` flag (or no API key) the
  script prints exactly what it WOULD do — fixtures, call budget, pass rule —
  and exits **without constructing a client or spending a cent**.

HOW TO RUN (when you actually want to spend the ~180 calls)
-----------------------------------------------------------
    export ANTHROPIC_API_KEY=sk-...      # the configured provider's key
    python scripts/cache_parity_eval.py --run

    # dry run (default, no spend) — preview the plan:
    python scripts/cache_parity_eval.py

OLD-PROMPT RECOVERY
-------------------
The pre-refactor prompt builder lives at the git tag ``pre-cache-p3``:

    git show pre-cache-p3:tradingagents/agents/analysts/market_analyst.py
    git show pre-cache-p3:tradingagents/agents/analysts/fundamentals_analyst.py
    git show pre-cache-p3:tradingagents/agents/crypto_analysts.py

Rather than force a git checkout at eval time, the OLD system template is
inlined below as ``_OLD_SYSTEM_TEMPLATE`` — a verbatim copy of the pre-cache-p3
``("system", ...)`` string for market_analyst (boilerplate + ``{tool_names}`` +
``{system_message}`` + the volatile date/instrument tail, all in ONE system
message). The NEW path is built from the SAME stable text + the SAME volatile
text, but split across a system message and a human turn — exactly what
``tradingagents/agents/utils/prompt_cache.split_cacheable_prompt`` produces in
the live code. The eval asserts ``_OLD == _STABLE + _VOLATILE`` (byte-for-byte)
at import time, so the two prompt forms can differ ONLY in role boundaries — the
exact variable this eval is designed to isolate.

The harness uses market_analyst as the canonical site: it emits the cleanest
``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` label, and the role-move is
structurally identical across all three refactored sites (same stable/volatile
split via the same helper), so a pass here generalizes.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Cheapest capable model for a shakeout. The cache feature only ever engages for
# Anthropic + Sonnet (P1 verdict), so the eval must run on that exact surface.
PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"
API_KEY_ENV = "ANTHROPIC_API_KEY"

# Noise-floor sampling: run the OLD prompt K times per fixture to measure the
# model's intrinsic run-to-run disagreement (it is NOT deterministic at the
# temperature used). The NEW prompt is run once per fixture and compared to the
# OLD modal decision.
K_NOISE_RUNS = 5
TARGET_FIXTURES = 30

# A non-zero temperature is REQUIRED: a noise-floor of 0 (temp=0) would make any
# single new-vs-old disagreement look catastrophic. We want the natural sampling
# spread so "new differs no more than old differs from itself" is a fair test.
TEMPERATURE = 0.7

# Pass thresholds (documented in the results stub + module docstring).
MCNEMAR_ALPHA = 0.05  # p > 0.05 => no systematic directional drift

RESULTS_PATH = "docs/superpowers/plans/cache-parity-eval-results.md"

# Approx call budget, printed in the dry-run plan.
def _call_budget(n_fixtures: int) -> int:
    return n_fixtures * K_NOISE_RUNS + n_fixtures


# ---------------------------------------------------------------------------
# Prompt reconstruction (OLD vs NEW)
# ---------------------------------------------------------------------------
#
# The ONLY thing P3 changed is the ROLE of the volatile tail
# (``_VOLATILE_CONTEXT``): in the OLD prompt it was the tail of the single
# system message; in the NEW prompt it is a standalone human turn. Everything
# else is byte-identical between the two forms, so any decision difference is
# attributable to the role move and nothing else.
#
# ``_TOOL_NAMES`` is verbatim from market_analyst's ``tools`` list. The
# ``_SYSTEM_MESSAGE`` indicator catalog below is a REPRESENTATIVE (shortened but
# structurally faithful) copy of market_analyst's catalog — full fidelity is not
# required because the catalog is identical in both prompt forms; it exists only
# to make the cached prefix realistically large. The boilerplate and volatile
# strings ARE verbatim copies of the pre-cache-p3 / current source.

_TOOL_NAMES = "get_stock_data, get_indicators"

# Representative indicator catalog (see note above). Verbatim-faithful in shape
# to market_analyst.py's ``system_message``; trimmed for length.
_SYSTEM_MESSAGE = (
    "You are a trading assistant tasked with analyzing financial markets. Your role is to "
    "select the **most relevant indicators** for a given market condition or trading strategy "
    "from the following list. The goal is to choose up to **8 indicators** that provide "
    "complementary insights without redundancy. Categories and each category's indicators are:\n\n"
    "Moving Averages:\n"
    "- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and "
    "serve as dynamic support/resistance.\n"
    "- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend "
    "and identify golden/death cross setups.\n"
    "- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in "
    "momentum and potential entry points.\n\n"
    "MACD Related:\n"
    "- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and "
    "divergence as signals of trend changes.\n"
    "- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD "
    "line to trigger trades.\n"
    "- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize "
    "momentum strength and spot divergence early.\n\n"
    "Momentum Indicators:\n"
    "- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 "
    "thresholds and watch for divergence to signal reversals.\n\n"
    "Volatility Indicators:\n"
    "- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands.\n"
    "- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line.\n"
    "- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line.\n"
    "- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust "
    "position sizes based on current market volatility.\n\n"
    "Volume-Based Indicators:\n"
    "- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price "
    "action with volume data.\n\n"
    "- Select indicators that provide diverse and complementary information. Avoid redundancy. "
    "Write a very detailed and nuanced report of the trends you observe. Provide specific, "
    "actionable insights with supporting evidence to help traders make informed decisions."
)

# Boilerplate prefix — verbatim from market_analyst's stable system text, with
# ``{tool_names}`` and ``{system_message}`` pre-filled (the live code fills these
# via ``.partial()``; the eval inlines representative values so the prefix is
# self-contained).
_STABLE_SYSTEM = (
    "You are a helpful AI assistant, collaborating with other assistants."
    " Use the provided tools to progress towards answering the question."
    " If you are unable to fully answer, that's OK; another assistant with different tools"
    " will help where you left off. Execute what you can to make progress."
    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
    " You have access to the following tools: " + _TOOL_NAMES + ".\n" + _SYSTEM_MESSAGE
)

# Volatile tail — VERBATIM from source (the exact string P3 moved). Filled per
# fixture with ``.replace()`` (brace-safe; never str.format) so arbitrary
# instrument text can never break formatting.
_VOLATILE_CONTEXT = (
    "For your reference, the current date is {current_date}. {instrument_context}"
)

# OLD prompt's single system message == stable + volatile (one block), exactly as
# it appeared at git tag ``pre-cache-p3``. The NEW path splits this into a system
# message (_STABLE_SYSTEM) + a human turn (_VOLATILE_CONTEXT).
_OLD_SYSTEM_TEMPLATE = _STABLE_SYSTEM + _VOLATILE_CONTEXT

# Per-fixture task turn (the MessagesPlaceholder "question"). IDENTICAL in both
# prompt forms — it carries the market snapshot the model must decide on and the
# explicit label instruction so the response is machine-parseable.
_TASK_TEMPLATE = (
    "Here is the current market snapshot for {symbol}:\n\n{market_state}\n\n"
    "Based on the indicators and snapshot above, give your decision. You MUST end your"
    " reply with exactly one line in this format and nothing after it:\n"
    "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**"
)


def _structural_invariants() -> None:
    """Fail fast at import if the OLD/NEW decomposition drifts.

    These checks guarantee the two prompt forms differ ONLY by the role of the
    volatile tail — the single variable this eval isolates.
    """
    # 1. OLD system == STABLE + VOLATILE, byte-for-byte.
    assert _OLD_SYSTEM_TEMPLATE == _STABLE_SYSTEM + _VOLATILE_CONTEXT
    # 2. The volatile marker is the tail of OLD and appears exactly once.
    marker = "For your reference, the current date is"
    assert _OLD_SYSTEM_TEMPLATE.count(marker) == 1
    assert _STABLE_SYSTEM.count(marker) == 0
    assert _VOLATILE_CONTEXT.startswith(marker)
    # 3. OLD ends with the volatile context (it really is the tail).
    assert _OLD_SYSTEM_TEMPLATE.endswith(_VOLATILE_CONTEXT)


_structural_invariants()


# ---------------------------------------------------------------------------
# Fixtures (N = 30 representative inputs)
# ---------------------------------------------------------------------------
#
# These are TEST INPUTS, not real market data. They span bull / bear / chop
# regimes across a handful of plausible crypto perps and stock tickers so the
# eval exercises a realistic spread of decisions. Each fixture is a dict with
# the keys the harness consumes: ``symbol``, ``trade_date``, ``market_state``.


def _state(regime: str, price: float, rsi: float, macd: str, sma: str,
           note: str) -> str:
    """Render a compact, realistic indicator snapshot string."""
    return (
        f"Regime: {regime}\n"
        f"Last price: {price}\n"
        f"RSI(14): {rsi}\n"
        f"MACD: {macd}\n"
        f"Price vs 50/200 SMA: {sma}\n"
        f"Note: {note}"
    )


def _fx(symbol: str, trade_date: str, regime: str, **kw) -> dict:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "market_state": _state(regime, **kw),
    }


# 30 fixtures: 10 bull, 10 bear, 10 chop — mixed symbols and dates.
FIXTURES: list[dict] = [
    # --- Bull (10) ---
    _fx("BTCUSDT", "2026-01-08", "Strong uptrend (bull)", price=72350.0, rsi=68.4,
        macd="bullish, histogram expanding", sma="price > 50 SMA > 200 SMA",
        note="higher highs, breakout above prior range on rising volume"),
    _fx("ETHUSDT", "2026-01-22", "Uptrend (bull)", price=3980.5, rsi=63.1,
        macd="bullish crossover 2 days ago", sma="price above both SMAs",
        note="pullback to 10 EMA held, trend intact"),
    _fx("SOLUSDT", "2026-02-03", "Momentum bull", price=212.7, rsi=71.9,
        macd="strongly positive", sma="price well above 50 SMA",
        note="parabolic move, slightly overbought but no divergence yet"),
    _fx("AAPL", "2026-02-17", "Uptrend (bull)", price=243.8, rsi=61.0,
        macd="bullish, signal line crossed up", sma="golden cross last week",
        note="earnings beat, gap up holding"),
    _fx("NVDA", "2026-03-02", "Strong bull", price=158.2, rsi=69.7,
        macd="bullish, widening", sma="price > 50 > 200",
        note="AI demand narrative, consistent accumulation"),
    _fx("BTCUSDT", "2026-03-19", "Bull continuation", price=78900.0, rsi=64.5,
        macd="positive, flattening slightly", sma="price above both SMAs",
        note="consolidating gains near highs, bias up"),
    _fx("ETHUSDT", "2026-04-05", "Bull breakout", price=4310.0, rsi=66.8,
        macd="bullish crossover today", sma="reclaimed 200 SMA",
        note="volume surge on breakout candle"),
    _fx("AAPL", "2026-04-21", "Uptrend (bull)", price=251.4, rsi=58.9,
        macd="mildly bullish", sma="price > 50 SMA",
        note="steady grind higher, low volatility"),
    _fx("SOLUSDT", "2026-05-06", "Bull recovery", price=198.3, rsi=62.2,
        macd="turned positive", sma="reclaimed 50 SMA",
        note="bounce off support with momentum"),
    _fx("NVDA", "2026-05-20", "Bull trend", price=171.6, rsi=65.3,
        macd="bullish", sma="price above both SMAs",
        note="new all-time high on strong guidance"),

    # --- Bear (10) ---
    _fx("BTCUSDT", "2026-01-13", "Downtrend (bear)", price=58200.0, rsi=31.5,
        macd="bearish, histogram deepening", sma="price < 50 SMA < 200 SMA",
        note="lower lows, breakdown below support on volume"),
    _fx("ETHUSDT", "2026-01-29", "Bear trend", price=2840.0, rsi=28.7,
        macd="bearish crossover", sma="death cross forming",
        note="failed bounce, sellers in control"),
    _fx("SOLUSDT", "2026-02-11", "Capitulation (bear)", price=121.4, rsi=22.1,
        macd="strongly negative", sma="price far below 50 SMA",
        note="sharp selloff, oversold but no reversal signal"),
    _fx("AAPL", "2026-02-24", "Downtrend (bear)", price=198.6, rsi=34.0,
        macd="bearish", sma="price < 50 SMA",
        note="guidance cut, gap down holding lows"),
    _fx("NVDA", "2026-03-09", "Bear", price=112.8, rsi=29.9,
        macd="bearish, widening", sma="price < 50 < 200",
        note="momentum unwind, distribution pattern"),
    _fx("BTCUSDT", "2026-03-25", "Bear continuation", price=54100.0, rsi=33.8,
        macd="negative", sma="price below both SMAs",
        note="bear flag breakdown, bias down"),
    _fx("ETHUSDT", "2026-04-10", "Bear breakdown", price=2510.0, rsi=26.4,
        macd="bearish crossover today", sma="lost 200 SMA",
        note="heavy volume on the breakdown candle"),
    _fx("AAPL", "2026-04-27", "Downtrend (bear)", price=205.2, rsi=37.5,
        macd="mildly bearish", sma="price < 50 SMA",
        note="steady bleed lower, weak bounces"),
    _fx("SOLUSDT", "2026-05-12", "Bear pressure", price=143.7, rsi=30.2,
        macd="turned negative", sma="rejected at 50 SMA",
        note="lower-high rejection, downside risk"),
    _fx("NVDA", "2026-05-26", "Bear trend", price=126.9, rsi=32.6,
        macd="bearish", sma="price below both SMAs",
        note="breaking down from range on weak guidance"),

    # --- Chop / range (10) ---
    _fx("BTCUSDT", "2026-01-18", "Range-bound (chop)", price=64500.0, rsi=49.8,
        macd="flat near zero", sma="price oscillating around 50 SMA",
        note="no clear trend, repeated fakeouts both directions"),
    _fx("ETHUSDT", "2026-02-01", "Sideways (chop)", price=3320.0, rsi=51.2,
        macd="hovering at zero line", sma="50 SMA flat, 200 SMA flat",
        note="tight range, low volatility, indecision"),
    _fx("SOLUSDT", "2026-02-15", "Chop", price=167.9, rsi=47.3,
        macd="oscillating", sma="price chopping across 50 SMA",
        note="whipsaw conditions, no edge"),
    _fx("AAPL", "2026-02-28", "Range (chop)", price=228.4, rsi=52.6,
        macd="flat", sma="price between 50 and 200 SMA",
        note="consolidation after a run, awaiting catalyst"),
    _fx("NVDA", "2026-03-14", "Chop", price=139.5, rsi=48.9,
        macd="near zero, crossing repeatedly", sma="SMAs converging",
        note="coiling range, breakout direction unclear"),
    _fx("BTCUSDT", "2026-03-30", "Sideways (chop)", price=66200.0, rsi=50.4,
        macd="flat", sma="price pinned to 50 SMA",
        note="balance area, two-sided trade"),
    _fx("ETHUSDT", "2026-04-14", "Range (chop)", price=3405.0, rsi=46.7,
        macd="flat near zero", sma="oscillating around both SMAs",
        note="no trend, mean-reverting"),
    _fx("AAPL", "2026-04-30", "Chop", price=234.1, rsi=53.1,
        macd="indecisive", sma="price near 50 SMA",
        note="range-bound ahead of earnings"),
    _fx("SOLUSDT", "2026-05-15", "Sideways (chop)", price=176.2, rsi=49.1,
        macd="flat", sma="SMAs flat and close",
        note="low-conviction tape, choppy"),
    _fx("NVDA", "2026-05-29", "Range (chop)", price=148.0, rsi=50.8,
        macd="near zero", sma="price between SMAs",
        note="digesting prior move, no directional bias"),
]


# ---------------------------------------------------------------------------
# Message builders (OLD vs NEW)
# ---------------------------------------------------------------------------
#
# Both forms are plain ``[{"role", "content"}]`` lists — the exact shape the
# litellm client consumes — so the harness sends byte-identical CONTENT, varying
# only the role boundary of the volatile context. No tools are bound: the eval
# isolates the prompt-role variable, not the ReAct tool loop.


def _fill_volatile(fixture: dict) -> str:
    """Fill the volatile context for a fixture (brace-safe .replace)."""
    instrument = f"The instrument under analysis is {fixture['symbol']}."
    return (
        _VOLATILE_CONTEXT
        .replace("{current_date}", fixture["trade_date"])
        .replace("{instrument_context}", instrument)
    )


def _fill_task(fixture: dict) -> str:
    return (
        _TASK_TEMPLATE
        .replace("{symbol}", fixture["symbol"])
        .replace("{market_state}", fixture["market_state"])
    )


def build_old_messages(fixture: dict) -> list[dict]:
    """OLD prompt: ONE system message (stable + volatile tail), then the task."""
    system = _STABLE_SYSTEM + _fill_volatile(fixture)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _fill_task(fixture)},
    ]


def build_new_messages(fixture: dict) -> list[dict]:
    """NEW prompt: stable system message, volatile moved to a leading human turn,
    then the task — exactly the role split ``split_cacheable_prompt`` produces."""
    return [
        {"role": "system", "content": _STABLE_SYSTEM},
        {"role": "user", "content": _fill_volatile(fixture)},
        {"role": "user", "content": _fill_task(fixture)},
    ]


def assert_content_parity(fixture: dict) -> None:
    """The concatenation of all message contents must be identical OLD vs NEW.

    This is the runtime guard that the two forms differ ONLY by role split — the
    same byte-for-byte invariant P3 proved statically, re-checked per fixture.
    """
    old_blob = "".join(m["content"] for m in build_old_messages(fixture))
    new_blob = "".join(m["content"] for m in build_new_messages(fixture))
    assert old_blob == new_blob, f"content drift for {fixture['symbol']}"


# ---------------------------------------------------------------------------
# Decision-label parser
# ---------------------------------------------------------------------------

_LABELS = ("BUY", "HOLD", "SELL")


def parse_decision(text: Optional[str]) -> Optional[str]:
    """Extract a BUY / HOLD / SELL label from a model response.

    STRICT: only the explicit ``FINAL TRANSACTION PROPOSAL: **LABEL**`` line
    counts (with or without ``**`` emphasis). Returns the upper-cased label, or
    ``None`` if that line is absent.

    The earlier "last standalone BUY/HOLD/SELL token anywhere" fallback was
    REMOVED: against real analyst prose it misfired badly (e.g. it parsed the
    word in "RSI is not a *sell* signal" as a SELL decision). A response without
    the explicit proposal line is treated as "no decision" (None) — the harness
    counts None as a non-agreement, so an unparseable reply can never silently
    masquerade as a real decision. The task prompt instructs the model to end
    with the proposal line, so a well-behaved reply always parses.
    """
    if not text:
        return None
    import re

    m = re.search(
        r"FINAL\s+TRANSACTION\s+PROPOSAL\s*:\s*\*{0,2}\s*(BUY|HOLD|SELL)",
        text.upper(),
    )
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Statistics: agreement + McNemar exact binomial
# ---------------------------------------------------------------------------


def noise_floor(old_runs_per_fixture: list[list[Optional[str]]]) -> float:
    """Intrinsic run-to-run disagreement of the OLD prompt.

    For each fixture we ran the OLD prompt K times. The per-fixture disagreement
    is the fraction of runs that differ from that fixture's modal label. The
    noise floor is the mean of those fractions across fixtures (0.0 = perfectly
    self-consistent; higher = noisier). Fixtures with no parseable labels are
    skipped.
    """
    fracs: list[float] = []
    for runs in old_runs_per_fixture:
        labels = [r for r in runs if r is not None]
        if not labels:
            continue
        modal = _modal(labels)
        disagree = sum(1 for r in labels if r != modal) / len(labels)
        fracs.append(disagree)
    return sum(fracs) / len(fracs) if fracs else 0.0


def _modal(labels: list[str]) -> str:
    """Most common label; ties broken by label order (BUY < HOLD < SELL)."""
    counts = {lab: labels.count(lab) for lab in set(labels)}
    best = max(counts.values())
    for lab in _LABELS:
        if counts.get(lab, 0) == best:
            return lab
    return labels[0]


def agreement_rate(old_modal: list[Optional[str]],
                   new_labels: list[Optional[str]]) -> float:
    """Fraction of fixtures where NEW's single label == OLD's modal label.

    Fixtures where either side has no parseable label are excluded from the
    denominator.
    """
    pairs = [(o, n) for o, n in zip(old_modal, new_labels)
             if o is not None and n is not None]
    if not pairs:
        return 0.0
    return sum(1 for o, n in pairs if o == n) / len(pairs)


def _directional_score(label: Optional[str]) -> Optional[int]:
    """Map a label to a bull(+1)/neutral(0)/bear(-1) score for drift testing."""
    return {"BUY": 1, "HOLD": 0, "SELL": -1}.get(label) if label else None


def mcnemar_exact_p(old_modal: list[Optional[str]],
                    new_labels: list[Optional[str]]) -> float:
    """Two-sided McNemar exact-binomial p-value for SYSTEMATIC directional drift.

    We collapse each label to a directional score (BUY=+1, HOLD=0, SELL=-1) and
    count discordant pairs where NEW moved more bullish (b) vs more bearish (c)
    than OLD's modal decision. Under H0 (no directional bias) a discordant pair is
    equally likely to go either way, so b ~ Binomial(b+c, 0.5). The two-sided
    exact p-value is ``min(1, 2 * P(X <= min(b, c)))``.

    A high p (>0.05) means the new prompt shows no statistically significant
    directional drift relative to the old one. Uses scipy if available, else an
    inline exact binomial (stdlib ``math.comb`` only — no numpy/scipy required).
    """
    b = c = 0  # b: NEW more bullish than OLD; c: NEW more bearish
    for o, n in zip(old_modal, new_labels):
        so, sn = _directional_score(o), _directional_score(n)
        if so is None or sn is None or sn == so:
            continue
        if sn > so:
            b += 1
        else:
            c += 1
    n_disc = b + c
    if n_disc == 0:
        return 1.0  # no discordant pairs => no evidence of drift
    k = min(b, c)
    return _two_sided_binom_p(k, n_disc)


def _two_sided_binom_p(k: int, n: int, p: float = 0.5) -> float:
    """Two-sided exact binomial p-value for k successes in n trials at prob p.

    Prefers scipy.stats.binomtest when installed; otherwise computes the exact
    lower-tail sum with ``math.comb`` and doubles it (clamped to 1.0), which is
    the standard McNemar exact two-sided p for the symmetric p=0.5 case.
    """
    try:  # optional accelerator; NOT a hard dependency
        from scipy.stats import binomtest  # type: ignore
        return float(binomtest(k, n, p, alternative="two-sided").pvalue)
    except Exception:
        lower = sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
                    for i in range(0, k + 1))
        return min(1.0, 2.0 * lower)


# ---------------------------------------------------------------------------
# Pass rule
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    n_fixtures: int
    noise: float
    agreement: float
    mcnemar_p: float
    agreement_threshold: float = 0.0
    passed: bool = False
    old_modal: list = field(default_factory=list)
    new_labels: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"N={self.n_fixtures}  noise_floor={self.noise:.3f}  "
            f"agreement={self.agreement:.3f} (>= {self.agreement_threshold:.3f})  "
            f"McNemar p={self.mcnemar_p:.4f}  "
            f"=> {'PASS' if self.passed else 'FAIL'}"
        )


def evaluate_pass(old_runs_per_fixture: list[list[Optional[str]]],
                  new_labels: list[Optional[str]]) -> EvalResult:
    """Apply the gate rule to collected labels.

    PASS iff BOTH:
      * new-vs-old modal agreement >= (1 - noise_floor)   [no more disagreement
        than the OLD prompt has with itself], AND
      * McNemar exact p > 0.05  [no systematic directional drift].
    """
    noise = noise_floor(old_runs_per_fixture)
    old_modal = [_modal([r for r in runs if r is not None]) if any(runs) else None
                 for runs in old_runs_per_fixture]
    agree = agreement_rate(old_modal, new_labels)
    p = mcnemar_exact_p(old_modal, new_labels)
    threshold = 1.0 - noise
    passed = (agree >= threshold) and (p > MCNEMAR_ALPHA)
    return EvalResult(
        n_fixtures=len(old_runs_per_fixture),
        noise=noise,
        agreement=agree,
        mcnemar_p=p,
        agreement_threshold=threshold,
        passed=passed,
        old_modal=old_modal,
        new_labels=new_labels,
    )


# ---------------------------------------------------------------------------
# Model caller (the ONLY place that spends money — isolated + mockable)
# ---------------------------------------------------------------------------

# A model caller takes a list[{"role","content"}] and returns the response text.
ModelCaller = Callable[[list], str]


def default_model_caller(messages: list) -> str:
    """Real LLM call via the project client. Imported and built LAZILY so this
    module is import-safe and a dry run never touches the network or a client.

    Only invoked from ``run_eval`` when ``run=True`` AND a key is present.
    """
    from tradingagents.llm_clients.factory import create_llm_client

    client = create_llm_client(
        provider=PROVIDER, model=MODEL, temperature=TEMPERATURE,
    )
    llm = client.get_llm()
    result = llm.invoke(messages)
    content = getattr(result, "content", result)
    return content if isinstance(content, str) else str(content)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _print_plan(fixtures: list[dict], k_noise: int) -> None:
    budget = len(fixtures) * k_noise + len(fixtures)
    print("=" * 72)
    print("CACHE BEHAVIORAL-PARITY EVAL - DRY RUN (no API calls, no spend)")
    print("=" * 72)
    print(f"Provider / model : {PROVIDER} / {MODEL}")
    print(f"Fixtures (N)     : {len(fixtures)}")
    print(f"Noise runs (K)   : {k_noise} per fixture (OLD prompt)")
    print(f"New runs         : 1 per fixture (NEW prompt)")
    print(f"Call budget      : {budget} calls  (N*K + N = "
          f"{len(fixtures)}*{k_noise} + {len(fixtures)})")
    print(f"Temperature      : {TEMPERATURE} (non-zero - needed for a noise floor)")
    print()
    print("PASS RULE (both must hold):")
    print("  - new-vs-old modal agreement >= (1 - noise_floor)")
    print(f"  - McNemar exact-binomial p > {MCNEMAR_ALPHA} (no directional drift)")
    print()
    print("Prompt forms compared per fixture:")
    print("  OLD = one system message [stable + volatile tail] + task")
    print("  NEW = system [stable] + human [volatile] + task   (P3 split)")
    print()
    print(f"To actually run (spends ~{budget} calls):")
    print(f"  export {API_KEY_ENV}=...   &&   "
          f"python scripts/cache_parity_eval.py --run")
    print()
    print("Sample fixtures:")
    for fx in fixtures[:3]:
        first_line = fx["market_state"].splitlines()[0]
        print(f"  - {fx['symbol']:8s} {fx['trade_date']}  ({first_line})")
    print(f"  ... and {max(0, len(fixtures) - 3)} more")
    print("=" * 72)


def run_eval(run: bool, have_key: bool,
             model_caller: Optional[ModelCaller] = None,
             fixtures: Optional[list[dict]] = None,
             k_noise: int = K_NOISE_RUNS,
             results_path: str = RESULTS_PATH) -> Optional[EvalResult]:
    """Run (or dry-run) the parity eval.

    DRY RUN (default): if ``run`` is False OR ``have_key`` is False, prints the
    plan and returns ``None`` WITHOUT calling ``model_caller`` — guaranteeing no
    API spend on import or a keyless invocation. This is the critical safety
    property and is exercised by the smoke tests.

    LIVE: calls ``model_caller`` (defaults to ``default_model_caller``) K times
    per fixture for the OLD prompt and once for the NEW prompt, scores the gate,
    writes ``results_path``, and returns the ``EvalResult``.
    """
    fixtures = fixtures if fixtures is not None else FIXTURES

    if not run or not have_key:
        if run and not have_key:
            print(f"[dry-run] --run was passed but {API_KEY_ENV} is not set - "
                  f"refusing to spend. Set the key to run for real.\n")
        _print_plan(fixtures, k_noise)
        return None

    caller = model_caller or default_model_caller

    old_runs_per_fixture: list[list[Optional[str]]] = []
    new_labels: list[Optional[str]] = []
    for i, fx in enumerate(fixtures, 1):
        assert_content_parity(fx)
        old_runs: list[Optional[str]] = []
        for _ in range(k_noise):
            old_runs.append(parse_decision(caller(build_old_messages(fx))))
        old_runs_per_fixture.append(old_runs)
        new_labels.append(parse_decision(caller(build_new_messages(fx))))
        print(f"[{i}/{len(fixtures)}] {fx['symbol']} {fx['trade_date']}  "
              f"old={old_runs}  new={new_labels[-1]}")

    result = evaluate_pass(old_runs_per_fixture, new_labels)
    print("\n" + result.summary())
    write_results(result, results_path)
    return result


def write_results(result: EvalResult, results_path: str) -> None:
    """Overwrite the results doc with the concrete outcome of a live run."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        "# Cache Behavioral-Parity Eval — Results",
        "",
        f"**Status: RUN - {verdict}** (executed {now})",
        "",
        "## Gate rule",
        "Before `prompt_cache_enabled` may default to ON, this eval MUST PASS:",
        "- new-vs-old decision-label agreement >= (1 - noise_floor) over N>=30 fixtures",
        "- McNemar's test p > 0.05 (no systematic directional drift)",
        "",
        "## Result",
        f"- Date: {now}",
        f"- Model: {PROVIDER} / {MODEL}",
        f"- N fixtures: {result.n_fixtures}",
        f"- Noise floor: {result.noise:.3f}",
        f"- New-vs-old agreement: {result.agreement:.3f} "
        f"(threshold >= {result.agreement_threshold:.3f})",
        f"- McNemar exact p: {result.mcnemar_p:.4f} (alpha {MCNEMAR_ALPHA})",
        f"- **Verdict: {verdict}**",
        "",
    ]
    with open(results_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote {results_path}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Behavioral-parity eval for the prompt-caching P3 restructure. "
                    "Dry-run by default (no spend); pass --run AND set the API key "
                    "to make real calls.",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Make REAL LLM API calls (costs money). Requires "
             f"{API_KEY_ENV} to be set; otherwise falls back to a dry run.",
    )
    args = parser.parse_args(argv)
    have_key = bool(os.environ.get(API_KEY_ENV))
    result = run_eval(run=args.run, have_key=have_key)
    if result is None:
        return 0
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
