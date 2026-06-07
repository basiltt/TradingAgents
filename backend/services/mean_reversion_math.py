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


def check_geometry(entry: float, mean: float, side: Side, tight_sl_pct: float,
                   leverage: float, *, min_edge_pct: float, capture_pct: float = 100.0,
                   round_trip_fee_frac: float = DEFAULT_ROUND_TRIP_FEE_FRAC
                   ) -> Optional[ReasonCode]:
    """Return a skip ReasonCode if the MR trade geometry is invalid, else None.

    Guards (each fires even under relaxed mode), all measured against the ACTUAL
    placed TP (capture-scaled, IR3) — not the full-capture distance:
      - degenerate target: TP on the wrong side of entry for the side
      - no edge: |entry-mean|/entry*100 < min_edge_pct
      - fee floor: placed margin TP% <= round-trip fee (as margin %)
      - inverted geometry: tight-SL distance (margin %) >= placed TP distance
      - SL beyond liquidation: tight-SL price-move >= the leverage-implied
        liquidation distance (~1/leverage) (IR7 / FR-025)
    """
    if entry <= 0 or mean <= 0:
        return ReasonCode.MR_DEGENERATE_TARGET

    distance_pct = abs(entry - mean) / entry * 100.0
    if distance_pct < min_edge_pct:
        return ReasonCode.MR_NO_EDGE

    tp_price = mr_target_price(entry, mean, capture_pct)
    # A long fades a dip (entry below mean) => TP above entry; a short fades a pop
    # (entry above mean) => TP below entry. Wrong side => degenerate.
    if side == "long" and tp_price <= entry:
        return ReasonCode.MR_DEGENERATE_TARGET
    if side == "short" and tp_price >= entry:
        return ReasonCode.MR_DEGENERATE_TARGET

    # actual placed margin TP (capture-scaled)
    tp_margin = margin_tp_pct(entry, mean, capture_pct, leverage)
    fee_margin = round_trip_fee_frac * leverage * 100.0
    if tp_margin <= fee_margin:
        return ReasonCode.MR_FEE_FLOOR

    # tight_sl_pct is a margin %; if the stop risks more than the target,
    # reward < risk => skip (inverted geometry).
    if tight_sl_pct >= tp_margin:
        return ReasonCode.MR_INVERTED_GEOMETRY

    # SL must sit inside the leverage-implied liquidation boundary (FR-025). The
    # SL price-move fraction = tight_sl_pct / leverage / 100; liquidation is at
    # ~1/leverage. Require the SL to trigger before liquidation, with margin.
    sl_price_move_frac = (tight_sl_pct / 100.0) / leverage if leverage else 1.0
    liquidation_frac = 1.0 / leverage if leverage else 1.0
    if sl_price_move_frac >= 0.9 * liquidation_frac:
        return ReasonCode.MR_SL_LIQUIDATION

    return None


def mr_target_price(entry: float, mean: float, capture_pct: float, side: Side = "short") -> float:
    """Absolute TP price: capture `capture_pct`% of the distance from entry toward
    mean. Direction is implicit in sign(mean-entry); `side` is accepted for call-site
    clarity but not required."""
    frac = capture_pct / 100.0
    return entry + (mean - entry) * frac
