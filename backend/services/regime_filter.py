"""Pure F1 (Regime/Session Entry Filter) gate predicates (Phase 3).

Pure functions over a config dict + the placement-time UTC + the ScanContext. They
return a ReasonCode to suppress, or None to allow. F1 is strictly subtractive and
applies to BOTH trend and MR entries (market-condition gating).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from backend.services.scan_context import ScanContext
from backend.services.strategy_reason_codes import ReasonCode


def gate_session(cfg: dict[str, Any], now_utc: datetime) -> Optional[ReasonCode]:
    """Suppress entries placed during a blocked UTC hour.

    F1 umbrella: requires regime_filter_enabled AND session_filter_enabled.
    Evaluated against the trade-PLACEMENT UTC hour (tz-aware), so it re-checks each
    phase. Allowlist mode (session_allowed_hours_utc) inverts to block everything
    outside the allowed set.
    """
    if not (cfg.get("regime_filter_enabled") and cfg.get("session_filter_enabled")):
        return None
    hour = now_utc.astimezone(timezone.utc).hour
    allowed = cfg.get("session_allowed_hours_utc")
    if allowed is not None:
        blocked = set(range(24)) - set(allowed)
    else:
        blocked = set(cfg.get("session_blocked_hours_utc") or [])
    return ReasonCode.SESSION_FILTER if hour in blocked else None


def gate_btc_vol(cfg: dict[str, Any], ctx: ScanContext) -> Optional[ReasonCode]:
    """Suppress entries when BTC atr_ratio is outside the configured band.

    Fail-OPEN: if the BTC regime is unavailable/degraded, return None (allow). The
    caller may emit a `vol_unavailable` trace separately. Boundary is strict
    (< lo or > hi) so a value exactly on the band edge is allowed.
    """
    if not (cfg.get("regime_filter_enabled") and cfg.get("btc_vol_filter_enabled")):
        return None
    btc = ctx.get_btc(cfg.get("btc_vol_interval", "1h"), cfg.get("btc_vol_lookback_candles", 14))
    if btc is None or btc.get("unavailable") or btc.get("vol_value") is None:
        return None  # FAIL-OPEN
    v = btc["vol_value"]
    lo = cfg.get("btc_vol_min_threshold")
    hi = cfg.get("btc_vol_max_threshold")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return ReasonCode.BTC_VOL_FILTER
    return None


def btc_vol_unavailable(cfg: dict[str, Any], ctx: ScanContext) -> bool:
    """True when the vol gate is enabled but BTC data is unavailable (for tracing)."""
    if not (cfg.get("regime_filter_enabled") and cfg.get("btc_vol_filter_enabled")):
        return False
    btc = ctx.get_btc(cfg.get("btc_vol_interval", "1h"), cfg.get("btc_vol_lookback_candles", 14))
    return btc is None or bool(btc.get("unavailable")) or btc.get("vol_value") is None
