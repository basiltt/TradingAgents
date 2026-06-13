"""Account-agnostic market-regime + portfolio-skew context builder (spec FR-1).

PURE module: imports ONLY stdlib. It must NEVER import ``backend.*`` (in
particular ``backend.services.market_data`` / ``scan_context``), because that
would drag the execution-side regime subsystem into this import graph, invert
the lib→app layering, and break the isolation guarantee (spec C-3/NFR-3/AC-6).

The ~6 lines of EMA math are copied (semantically) from
``backend/services/market_data.py`` (``ema`` / ``compute_ema_distance_pct``) so
there is no cross-module import. A parity unit test pins them to the original.

The builder is a pure function of scalars + a dict — the caller
(``scanner_service``, which may legally touch ``backend``) reduces BTC klines to
the two scalars and queries the skew before calling in.
"""
from __future__ import annotations

import logging
import math
from typing import Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Direction threshold (percent EMA-distance). Matches the existing
# ``regime_trend_ema_dist_pct`` default so the two regime notions stay aligned.
REGIME_TREND_THRESH_PCT = 1.0
# Minimum recent-signal sample before a skew line is emitted (avoids noise).
REGIME_SKEW_MIN_SAMPLE = 20
# Book is considered "one-sided" toward shorts at/above this percentage.
REGIME_ONE_SIDED_PCT = 70.0


# ── EMA math — copied verbatim (semantically) from market_data.py, no import ──
def _ema(values: Sequence[float], period: int) -> Optional[float]:
    """Final EMA over ``values``; None if too short. Mirror of market_data.ema."""
    if len(values) < period or period < 1:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period  # seed with SMA of first `period`
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _ema_distance_pct(closes: Sequence[float], period: int) -> Optional[float]:
    """(last_close - EMA) / EMA * 100; None if too short or EMA==0."""
    e = _ema(closes, period)
    if e is None or e == 0:
        return None
    return (closes[-1] - e) / e * 100.0


def btc_scalars_from_closes(
    closes: Sequence[float], period: int = 14
) -> Tuple[Optional[float], Optional[float]]:
    """Reduce a BTC close series to (trend_pct, move_pct).

    trend_pct = signed EMA distance (direction); move_pct = signed first→last %
    move over the window. Either may be None when inputs are insufficient.
    Inputs MUST be ordered oldest→newest.
    """
    if not closes:
        return None, None
    trend = _ema_distance_pct(closes, period)
    first = closes[0]
    move = ((closes[-1] - first) / first * 100.0) if first else None
    return trend, move


def closes_from_kline_csv(csv_text: str) -> list:
    """Parse oldest→newest close prices from a Bybit kline CSV (FR-2.2).

    The CSV is ``timestamp,open,high,low,close,volume`` produced by
    ``get_bybit_klines``. Bybit returns rows newest-first, so rows are SORTED by
    timestamp ascending here. A leading ``[WARNING: ...]`` truncation banner and
    the header line are skipped. Returns [] on any malformed input (fail-soft).
    """
    if not csv_text:
        return []
    rows = []
    for line in csv_text.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line.lower().startswith("timestamp"):
            continue
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            ts = int(float(parts[0]))
            close = float(parts[4])
        except (ValueError, IndexError):
            continue
        if not math.isfinite(close):  # reject nan/inf defensively
            continue
        rows.append((ts, close))
    rows.sort(key=lambda r: r[0])  # oldest → newest
    return [c for _, c in rows]



def _direction_label(trend_pct: Optional[float], thresh: float) -> Optional[str]:
    """Map a signed trend percentage to a human label, or None if unknown."""
    if trend_pct is None:
        return None
    if trend_pct >= thresh:
        return "rising"
    if trend_pct <= -thresh:
        return "falling"
    return "flat"


def build_regime_context_block(
    btc_trend_pct: Optional[float],
    btc_move_pct: Optional[float],
    signal_skew: Optional[dict],
    *,
    trend_thresh: float = REGIME_TREND_THRESH_PCT,
    min_sample: int = REGIME_SKEW_MIN_SAMPLE,
) -> str:
    """Build the account-agnostic regime-context block (FR-1).

    Returns "" when neither a BTC direction nor a sufficient skew sample is
    available, so concatenating it into a prompt is always safe.
    """
    direction = _direction_label(btc_trend_pct, trend_thresh)

    skew_ok = bool(
        signal_skew and int(signal_skew.get("sample_n", 0) or 0) >= min_sample
    )

    if direction is None and not skew_ok:
        return ""

    lines = ["--- MARKET REGIME CONTEXT (account-agnostic) ---"]

    # BTC trend line
    if direction is not None:
        move_txt = (
            f" ({btc_move_pct:+.1f}% over the recent session)"
            if btc_move_pct is not None
            else ""
        )
        if direction == "rising":
            lines.append(
                f"BTC is {direction}{move_txt}; breadth favors LONGS. "
                f"Counter-trend shorts carry elevated squeeze risk."
            )
        elif direction == "falling":
            lines.append(
                f"BTC is {direction}{move_txt}; breadth favors SHORTS. "
                f"Trend-aligned shorts are with the dominant flow."
            )
        else:
            lines.append(
                f"BTC is {direction}{move_txt}; no clear directional edge. "
                f"Be selective and demand setup-specific evidence."
            )

    # Portfolio skew line
    if skew_ok:
        short_pct = float(signal_skew.get("short_pct", 0.0) or 0.0)
        long_pct = float(signal_skew.get("long_pct", 0.0) or 0.0)
        sample_n = int(signal_skew.get("sample_n", 0) or 0)
        lines.append(
            f"Recent signal book: {short_pct:.0f}% SHORT / {long_pct:.0f}% LONG "
            f"(most recent {sample_n} actionable signals)."
        )
        if short_pct >= REGIME_ONE_SIDED_PCT:
            lines.append(
                "The book is one-sided toward SHORTS - demand a higher bar "
                "for another SHORT unless this setup is exceptional."
            )
        elif long_pct >= REGIME_ONE_SIDED_PCT:
            lines.append(
                "The book is one-sided toward LONGS - demand a higher bar "
                "for another LONG unless this setup is exceptional."
            )

    # Cross-signal conflict warning: rising tape + short-heavy book
    if (
        direction == "rising"
        and skew_ok
        and float(signal_skew.get("short_pct", 0.0) or 0.0) >= REGIME_ONE_SIDED_PCT
    ):
        lines.append(
            "WARNING: counter-trend shorts into a rising tape with an already "
            "short-heavy book carry elevated squeeze risk."
        )

    return "\n".join(lines) + "\n\n"
