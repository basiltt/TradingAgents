"""Market-scoped regime classification + per-symbol EMA mean (Phase 1, market_data.py).

Pure indicator math over kline dicts (shape from KlineCacheService.get_klines:
{"open","high","low","close","volume", "open_time"}). Market-scoped (BTC) and
deliberately simpler than the per-symbol ai_manager_regime classifier (ADR-2).

Classifier (SD1): from BTC klines compute
  atr_ratio       = ATR(n) / SMA(ATR(n) over n)          # needs >= 2n+1 candles
  ema_distance_pct = (close - EMA(n)) / EMA(n) * 100
and first-match:
  unknown   if candles < required depth (2n+1)
  volatile  if atr_ratio >= regime_volatile_atr (default 2.0)
  trending  if abs(ema_distance_pct) >= regime_trend_ema_dist_pct (default 1.0)
  ranging   otherwise
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from backend.services.scan_context import BtcRegime, ScanContext

logger = logging.getLogger(__name__)

Kline = dict[str, Any]
# fetcher(symbol, interval, depth) -> list[Kline]
Fetcher = Callable[[str, str, int], Awaitable[list[Kline]]]


def _closes(klines: list[Kline]) -> list[float]:
    return [float(k["close"]) for k in klines]


def _true_ranges(klines: list[Kline]) -> list[float]:
    """Wilder's true range series (length len(klines)-1)."""
    trs: list[float] = []
    for i in range(1, len(klines)):
        high = float(klines[i]["high"])
        low = float(klines[i]["low"])
        prev_close = float(klines[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return trs


def _wilder_atr(trs: list[float], n: int) -> list[float]:
    """Wilder-smoothed ATR series from a true-range series. Returns one ATR value
    per position from index n-1 onward (length len(trs)-n+1)."""
    if len(trs) < n:
        return []
    atrs: list[float] = []
    atr = sum(trs[:n]) / n  # initial ATR = simple average of first n TRs
    atrs.append(atr)
    for i in range(n, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        atrs.append(atr)
    return atrs


def ema(values: list[float], period: int) -> Optional[float]:
    """Final EMA value over `values` with the given period, or None if too short."""
    if len(values) < period or period < 1:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period  # seed with SMA of first `period`
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def compute_ema_mean(klines: list[Kline], period: int) -> Optional[float]:
    """EMA of closes over `period`. None if fewer than `period` candles (F2 mean)."""
    closes = _closes(klines)
    return ema(closes, period)


def compute_ema_distance_pct(klines: list[Kline], period: int) -> Optional[float]:
    """(last_close - EMA(period)) / EMA(period) * 100. None if too short."""
    closes = _closes(klines)
    e = ema(closes, period)
    if e is None or e == 0:
        return None
    return (closes[-1] - e) / e * 100.0


def required_depth(lookback: int) -> int:
    """Minimum candles for a non-degenerate atr_ratio: an n-wide SMA over the ATR
    series needs ~2n TR values (+1 for the first TR's prev-close). (SD1a)"""
    return 2 * lookback + 1


def compute_atr_ratio(klines: list[Kline], n: int) -> Optional[float]:
    """ATR(n) / SMA(ATR(n) over n). None if fewer than required_depth(n) candles
    (prevents the degenerate atr_ratio == 1.0 from a single ATR value).

    A genuinely flat/calm market (every ATR == 0) is NOT "unavailable" — it has a
    well-defined neutral ratio of 1.0 (current volatility == its own average). We
    only return None when there is insufficient *history*, never for low volatility.
    """
    if len(klines) < required_depth(n):
        return None
    trs = _true_ranges(klines)
    atrs = _wilder_atr(trs, n)
    if len(atrs) < n:
        return None
    sma_atr = sum(atrs[-n:]) / n
    if sma_atr == 0:
        # Flat market: latest ATR is also 0 => ratio is 1.0 (neutral), not undefined.
        return 1.0
    return atrs[-1] / sma_atr


def classify_regime(
    klines: list[Kline],
    *,
    lookback: int,
    volatile_atr: float = 2.0,
    trend_ema_dist_pct: float = 1.0,
) -> BtcRegime:
    """Classify the market (BTC) regime. First-match rules (SD1)."""
    if len(klines) < required_depth(lookback):
        return {"regime": "unknown", "vol_value": None, "unavailable": True}

    atr_ratio = compute_atr_ratio(klines, lookback)
    ema_dist = compute_ema_distance_pct(klines, lookback)
    if atr_ratio is None or ema_dist is None:
        return {"regime": "unknown", "vol_value": atr_ratio, "unavailable": True}

    if atr_ratio >= volatile_atr:
        regime = "volatile"
    elif abs(ema_dist) >= trend_ema_dist_pct:
        regime = "trending"
    else:
        regime = "ranging"
    return {"regime": regime, "vol_value": atr_ratio, "unavailable": False}


def _precompute_enabled(auto_configs: list[dict[str, Any]]) -> bool:
    """True if any config needs scan-time regime/mean precompute (FR-003 predicate).

    Note: session-only F1 needs NO BTC precompute (it gates on placement-time UTC),
    so the BTC-vol sub-mode or MR (enabled or cohort) is what triggers precompute.
    """
    for cfg in auto_configs:
        if cfg.get("regime_filter_enabled") and cfg.get("btc_vol_filter_enabled"):
            return True
        if cfg.get("mean_reversion_enabled"):
            return True
        if cfg.get("strategy_cohort") == "mean_reversion":
            return True
    return False


def _btc_tuples(auto_configs: list[dict[str, Any]]) -> set[tuple[str, int]]:
    """Distinct (interval, lookback) BTC tuples needed for regime classification.

    PR1-6: MR-enabled / MR-cohort configs contribute their tuple even when the vol
    filter is OFF (else routing_regime -> unknown -> route 'none' -> MR never fires).
    """
    tuples: set[tuple[str, int]] = set()
    for cfg in auto_configs:
        needs = (
            (cfg.get("regime_filter_enabled") and cfg.get("btc_vol_filter_enabled"))
            or cfg.get("mean_reversion_enabled")
            or cfg.get("strategy_cohort") == "mean_reversion"
        )
        if needs:
            tuples.add((cfg.get("btc_vol_interval", "1h"), int(cfg.get("btc_vol_lookback_candles", 14))))
    return tuples


def _mr_symbol_params(auto_configs: list[dict[str, Any]], scan_results: list[dict[str, Any]]
                      ) -> tuple[set[str], set[tuple[int, str]]]:
    """Qualifying MR symbols (extreme score, per the loosest MR threshold) and the
    distinct (period, interval) mean params across MR-enabled configs."""
    mr_cfgs = [c for c in auto_configs if c.get("mean_reversion_enabled")]
    if not mr_cfgs:
        return set(), set()
    min_score = min(float(c.get("mr_extreme_min_abs_score", 5.0)) for c in mr_cfgs)
    symbols = {
        (r.get("ticker", "") if str(r.get("ticker", "")).endswith("USDT") else f"{r.get('ticker','')}USDT")
        for r in scan_results
        if r.get("status") == "completed" and abs(float(r.get("score", 0))) >= min_score and r.get("ticker")
    }
    params = {(int(c.get("mr_mean_period", 20)), c.get("mr_mean_interval", "1h")) for c in mr_cfgs}
    return symbols, params


async def build_scan_context(
    auto_configs: list[dict[str, Any]],
    scan_results: list[dict[str, Any]],
    *,
    now: datetime,
    kill: dict[str, bool],
    fetcher: Fetcher,
    concurrency: int = 8,
    budget_seconds: float = 60.0,
) -> ScanContext:
    """Precompute scan-global BTC regime/vol + per-symbol MR means once per scan.

    kill is read UNCONDITIONALLY in start_scan and passed in (R3-F1) so it is carried
    even on the no-precompute path. On any failure/timeout the context degrades
    (empty + degraded=True) so F1 fails-open and F2 fails-closed while trend proceeds.
    """
    if not _precompute_enabled(auto_configs):
        return ScanContext.empty(degraded=False, kill=kill)

    try:
        return await asyncio.wait_for(
            _build(auto_configs, scan_results, now, kill, fetcher, concurrency),
            timeout=budget_seconds,
        )
    except Exception:
        logger.warning("scan_context_precompute_failed_degrading", exc_info=True)
        return ScanContext.empty(degraded=True, kill=kill)


async def _build(auto_configs, scan_results, now, kill, fetcher, concurrency):
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(coro):
        async with sem:
            return await coro

    # BTC regimes (per distinct interval/lookback tuple)
    btc: dict[tuple[str, int], BtcRegime] = {}
    btc_tuples = _btc_tuples(auto_configs)

    async def _btc_one(interval, lookback):
        klines = await fetcher("BTCUSDT", interval, required_depth(lookback))
        return (interval, lookback), classify_regime(
            klines, lookback=lookback,
            volatile_atr=float(_first(auto_configs, "regime_volatile_atr", 2.0)),
            trend_ema_dist_pct=float(_first(auto_configs, "regime_trend_ema_dist_pct", 1.0)),
        )

    btc_pairs = await asyncio.gather(*[_guarded(_btc_one(i, lb)) for (i, lb) in btc_tuples])
    for key, regime in btc_pairs:
        btc[key] = regime

    # MR means + per-symbol mark prices (qualifying symbols only)
    means: dict[tuple[str, int, str], float] = {}
    prices: dict[str, float] = {}
    symbols, params = _mr_symbol_params(auto_configs, scan_results)

    async def _mean_one(symbol, period, interval):
        klines = await fetcher(symbol, interval, period + 1)
        m = compute_ema_mean(klines, period)
        return symbol, period, interval, m, (klines[-1]["close"] if klines else None)

    jobs = [_guarded(_mean_one(s, p, i)) for s in symbols for (p, i) in params]
    for symbol, period, interval, m, last_close in await asyncio.gather(*jobs):
        if m is not None:
            means[(symbol, period, interval)] = m
        if last_close is not None:
            prices.setdefault(symbol, float(last_close))

    return ScanContext(btc=btc, means=means, prices=prices, computed_at=now,
                       degraded=False, kill=dict(kill))


def _first(auto_configs: list[dict[str, Any]], key: str, default):
    for cfg in auto_configs:
        if key in cfg and cfg[key] is not None:
            return cfg[key]
    return default
