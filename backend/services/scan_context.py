"""Frozen scan-time context shared from scanner_service.start_scan to the executor.

Produced once per scan (Phase 1 build_scan_context); consumed read-only by the
gate chain / strategy router (Phases 2-4). Keeping it frozen + dict-keyed means
the trade hot path does O(1) lookups with zero network I/O (FR-003, NFR-001).

Contract notes (from plan review):
- btc keyed by (interval, lookback) — metric was cut (atr_ratio is constant, PD8).
- means keyed by (symbol, period, interval).
- prices: per-symbol mark price, precomputed (account-independent, PR1-9) so the
  MR branch does a dict lookup instead of a per-account get_mark_price call.
- kill: feature_name -> killed; value is the feature_kill_switches.killed column
  verbatim (R2-F2). Read UNCONDITIONALLY in start_scan and carried even by empty()
  (R3-F1) so the master/f1 kill works for fleets that never trigger precompute.
- is_stale short-circuits True when degraded; empty() stamps computed_at=epoch so a
  degraded context is always stale => F2 fail-closed cleanly (R2-F5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TypedDict

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class BtcRegime(TypedDict):
    regime: str           # "ranging" | "trending" | "volatile" | "unknown"
    vol_value: Optional[float]
    unavailable: bool


@dataclass(frozen=True)
class ScanContext:
    btc: dict[tuple[str, int], BtcRegime] = field(default_factory=dict)        # (interval, lookback) -> BtcRegime
    means: dict[tuple[str, int, str], float] = field(default_factory=dict)     # (symbol, period, interval) -> EMA
    prices: dict[str, float] = field(default_factory=dict)                     # symbol -> mark price
    computed_at: datetime = _EPOCH
    degraded: bool = False
    kill: dict[str, bool] = field(default_factory=dict)                        # feature_name -> killed

    # ── factories ──
    @classmethod
    def empty(cls, *, degraded: bool = True, kill: Optional[dict[str, bool]] = None) -> "ScanContext":
        """Empty context for the no-precompute / degrade path.

        computed_at is epoch so is_stale() is always True (F2 fail-closed). The
        kill dict is still carried so master/per-feature kills are enforced even
        when no account triggered precompute (R3-F1).
        """
        return cls(btc={}, means={}, prices={}, computed_at=_EPOCH,
                   degraded=degraded, kill=dict(kill or {}))

    # ── accessors ──
    def get_btc(self, interval: str, lookback: int) -> Optional[BtcRegime]:
        return self.btc.get((interval, lookback))

    def routing_regime(self, interval: str, lookback: int) -> str:
        """Regime label used by route_strategy. 'unknown' if absent/degraded."""
        if self.degraded:
            return "unknown"
        br = self.btc.get((interval, lookback))
        return br["regime"] if br else "unknown"

    def get_mean(self, symbol: str, period: int, interval: str) -> Optional[float]:
        return self.means.get((symbol, period, interval))

    def get_price(self, symbol: str) -> Optional[float]:
        return self.prices.get(symbol)

    def is_killed(self, feature: str) -> bool:
        return bool(self.kill.get("__all__") or self.kill.get(feature, False))

    def is_stale(self, now: datetime, ttl_minutes: float) -> bool:
        if self.degraded:
            return True
        return (now - self.computed_at).total_seconds() / 60.0 > ttl_minutes
