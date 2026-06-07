"""Pure mean-reversion math: TP conversion, fade side, and geometry guards (Phase 4).

Kept as pure functions (no I/O) so the money-critical TP conversion has an oracle
test (T-06) and the guards (FR-025) are unit-testable in isolation.
"""

from __future__ import annotations

from typing import Literal, Optional

from backend.services.strategy_reason_codes import ReasonCode

Side = Literal["long", "short"]

# round-trip taker fee + slippage estimate (fraction of notional). Bybit taker ~0.055%
# each side; add slippage headroom. Conservative default used by the fee-floor guard.
DEFAULT_ROUND_TRIP_FEE_FRAC = 0.0015  # 0.15% of notional round-trip


def margin_tp_pct(entry: float, mean: float, capture_pct: float, leverage: float) -> float:
    """Convert a price-distance-to-mean target into percent-of-margin TP (FR-022/SD9).

    margin_tp% = (capture/100) * (|entry-mean|/entry) * leverage * 100
    Clamped to the distance-implied max (capture=100%).
    """
    if entry <= 0:
        return 0.0
    distance_frac = abs(entry - mean) / entry
    raw = (capture_pct / 100.0) * distance_frac * leverage * 100.0
    distance_implied_max = distance_frac * leverage * 100.0
    return min(raw, distance_implied_max)


def mr_target_price(entry: float, mean: float, capture_pct: float, side: Side) -> float:
    """Absolute TP price: capture `capture_pct`% of the distance from entry toward mean."""
    frac = capture_pct / 100.0
    return entry + (mean - entry) * frac  # moves entry toward mean by `frac`


def check_geometry(entry: float, mean: float, side: Side, tight_sl_pct: float,
                   leverage: float, *, min_edge_pct: float,
                   round_trip_fee_frac: float = DEFAULT_ROUND_TRIP_FEE_FRAC
                   ) -> Optional[ReasonCode]:
    """Return a skip ReasonCode if the MR trade geometry is invalid, else None.

    Guards (each fires even under relaxed mode):
      - degenerate target: TP on the wrong side of entry for the side
      - no edge: |entry-mean|/entry*100 < min_edge_pct
      - fee floor: margin TP% <= round-trip fee (as margin %) => net-negative win
      - inverted geometry: tight-SL distance (margin %) >= TP distance (margin %)
    """
    if entry <= 0 or mean <= 0:
        return ReasonCode.MR_DEGENERATE_TARGET

    distance_pct = abs(entry - mean) / entry * 100.0
    if distance_pct < min_edge_pct:
        return ReasonCode.MR_NO_EDGE

    tp_price = mr_target_price(entry, mean, 100.0, side)  # full-capture target = the mean
    # A long fades a dip (entry below mean) => TP above entry; a short fades a pop
    # (entry above mean) => TP below entry. Wrong side => degenerate.
    if side == "long" and tp_price <= entry:
        return ReasonCode.MR_DEGENERATE_TARGET
    if side == "short" and tp_price >= entry:
        return ReasonCode.MR_DEGENERATE_TARGET

    tp_margin = margin_tp_pct(entry, mean, 100.0, leverage)
    fee_margin = round_trip_fee_frac * leverage * 100.0
    if tp_margin <= fee_margin:
        return ReasonCode.MR_FEE_FLOOR

    # tight_sl_pct is already a margin %; if the stop risks more than the target,
    # reward < risk => skip (inverted geometry).
    if tight_sl_pct >= tp_margin:
        return ReasonCode.MR_INVERTED_GEOMETRY

    return None
