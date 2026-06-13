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

# Direction thresholds (percent). EMA distance and net session move live on
# different scales, so each gets its own bar (see _direction_label). The EMA
# threshold echoes the execution-side ``regime_trend_ema_dist_pct`` default but
# is intentionally NOT coupled to it (this is account-agnostic prompt context,
# not a per-account execution gate).
REGIME_TREND_THRESH_PCT = 1.0   # EMA-distance bar
REGIME_MOVE_THRESH_PCT = 3.0    # net first→last session-move bar (~38h window)
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



def _direction_label(
    trend_pct: Optional[float],
    move_pct: Optional[float],
    trend_thresh: float,
    move_thresh: float,
) -> Optional[str]:
    """Classify BTC direction from BOTH the session move and the EMA distance.

    The two inputs live on different scales, so each has its own threshold:
      - trend_pct (EMA distance): price persistently above/below its average; a
        ~1% distance is already meaningful.
      - move_pct (net first→last over ~38h): needs a larger move (~3%) to count,
        since small net travel over many hours is noise.

    Using EMA distance ALONE misses a key case: a market that rallied and is now
    consolidating near its (now-elevated) EMA reads ~0 distance ("flat") even
    though it is clearly up on the session — exactly when blind shorts are most
    dangerous. So direction is "rising" if EITHER signal clears its UP threshold
    (and neither clears its DOWN threshold), and "falling" symmetrically. When
    neither is decisive we return None so NO line is injected (a "flat / no edge"
    line is pure noise on every prompt and is deliberately suppressed).
    """
    up = down = False
    if trend_pct is not None:
        up = up or trend_pct >= trend_thresh
        down = down or trend_pct <= -trend_thresh
    if move_pct is not None:
        up = up or move_pct >= move_thresh
        down = down or move_pct <= -move_thresh
    if up and not down:
        return "rising"
    if down and not up:
        return "falling"
    return None  # directionless or conflicting → suppress


def _clamp_move(move_pct: Optional[float]) -> Optional[float]:
    """Bound the displayed move so a garbage close can never render an absurd %."""
    if move_pct is None:
        return None
    return max(-100.0, min(100.0, move_pct))


def build_regime_context_block(
    btc_trend_pct: Optional[float],
    btc_move_pct: Optional[float],
    signal_skew: Optional[dict],
    *,
    trend_thresh: float = REGIME_TREND_THRESH_PCT,
    move_thresh: float = REGIME_MOVE_THRESH_PCT,
    min_sample: int = REGIME_SKEW_MIN_SAMPLE,
) -> str:
    """Build the account-agnostic regime-context block (FR-1).

    Returns "" when neither a BTC direction nor a sufficient skew sample is
    available, so concatenating it into a prompt is always safe. A genuinely
    directionless ("flat") market produces NO BTC line (noise suppression).
    """
    direction = _direction_label(btc_trend_pct, btc_move_pct, trend_thresh, move_thresh)

    skew_ok = bool(
        signal_skew and int(signal_skew.get("sample_n", 0) or 0) >= min_sample
    )

    if direction is None and not skew_ok:
        return ""

    lines = ["--- MARKET REGIME CONTEXT (account-agnostic) ---"]

    # BTC trend line (omitted entirely when direction is None — no "flat" noise).
    if direction is not None:
        clamped = _clamp_move(btc_move_pct)
        move_txt = f" ({clamped:+.1f}% recent session)" if clamped is not None else ""
        if direction == "rising":
            lines.append(
                f"BTC is rising{move_txt}; broad market tilts LONG. "
                f"Counter-trend shorts face elevated squeeze risk — weigh that against the setup."
            )
        else:  # falling
            lines.append(
                f"BTC is falling{move_txt}; broad market tilts SHORT. "
                f"Trend-aligned shorts are with the dominant flow; counter-trend longs face added risk."
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
                "The book is heavily one-sided toward SHORTS; judge this trade on "
                "its own merits rather than adding to an already crowded direction."
            )
        elif long_pct >= REGIME_ONE_SIDED_PCT:
            lines.append(
                "The book is heavily one-sided toward LONGS; judge this trade on "
                "its own merits rather than adding to an already crowded direction."
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
