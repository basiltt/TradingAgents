"""Tick-level data for parity exits — Bybit public trade archive + a slim local cache.

Live close rules fire ~continuously (60s poll, sub-second execution); the 5m/1m
candle engine can only act at bar closes, leaving a small bar-vs-tick exit error.
This module resolves exits at TRUE tick resolution: it downloads Bybit's public
daily trade archive (https://public.bybit.com/trading/<SYM>/<SYM><DATE>.csv.gz),
caches a slim (timestamp, price) view on disk, and walks the merged tick stream of a
cycle's positions to find the exact instant a portfolio threshold (target-goal /
drawdown) crosses — closing all positions at their tick prices there.

Performance: each symbol-day is fetched ONCE and cached as a compact .npz-like pair
of arrays; re-runs read the cache (instant). Only the symbol-days a cycle touches
are fetched.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import io
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

_ARCHIVE_URL = "https://public.bybit.com/trading/{sym}/{sym}{day}.csv.gz"
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "_tick_cache")


@dataclass
class TickSeries:
    """Ascending (timestamp_seconds, price) arrays for one symbol-day (or window)."""
    timestamps: list[float]
    prices: list[float]

    def __post_init__(self) -> None:
        # Ensure ascending by timestamp (Bybit archives are sometimes reverse-chron).
        if self.timestamps and self.timestamps[0] > self.timestamps[-1]:
            self.timestamps = self.timestamps[::-1]
            self.prices = self.prices[::-1]


def price_at(series: TickSeries, t: float) -> Optional[float]:
    """Last trade price at-or-before epoch-seconds `t`; None if before the first tick."""
    ts = series.timestamps
    if not ts:
        return None
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return series.prices[i]


def _upnl(side: str, entry: float, mark: float, qty: float) -> float:
    return (entry - mark) * qty if side == "Sell" else (mark - entry) * qty


def merged_upnl_crossing(
    positions: list[dict[str, Any]],
    threshold: float,
    direction: str,
) -> Optional[dict[str, Any]]:
    """Walk the merged tick stream of all positions; return the first instant the
    book-wide unrealised PnL crosses `threshold`.

    positions: each {symbol, side, entry_price, qty, ticks: TickSeries}.
    direction: "rise" → fire when total uPnL >= threshold (target-goal);
               "drop" → fire when total uPnL <= threshold (drawdown, threshold < 0).

    Returns {time, total_upnl, exit_prices:{symbol: price}} or None if never crosses.
    Each position's mark at a given instant is its last tick at-or-before that instant;
    a position with no tick yet (before its first trade) contributes 0 uPnL (held at
    entry), matching "not yet marked".
    """
    # Collect every distinct tick timestamp across all positions, ascending.
    all_t: set[float] = set()
    for p in positions:
        all_t.update(p["ticks"].timestamps)
    if not all_t:
        return None
    timeline = sorted(all_t)

    for t in timeline:
        total = 0.0
        marks: dict[str, float] = {}
        for p in positions:
            mark = price_at(p["ticks"], t)
            if mark is None:
                mark = p["entry_price"]  # not yet traded at t → held at entry (0 uPnL)
            marks[p["symbol"]] = mark
            total += _upnl(p["side"], p["entry_price"], mark, p["qty"])
        crossed = total >= threshold if direction == "rise" else total <= threshold
        if crossed:
            return {"time": t, "total_upnl": total, "exit_prices": marks}
    return None


# --------------------------------------------------------------------------- #
# Archive fetch + slim disk cache
# --------------------------------------------------------------------------- #

def _cache_path(symbol: str, day: str) -> str:
    return os.path.join(_CACHE_DIR, f"{symbol}{day}.csv")


def load_symbol_day(symbol: str, day: str, *, timeout: float = 90.0) -> TickSeries:
    """Return a TickSeries for one symbol-day, fetching+caching the Bybit archive.

    `day` is "YYYY-MM-DD". A slim two-column (timestamp,price) CSV is cached on disk
    so subsequent calls (and re-runs) skip the network. A missing/failed archive
    yields an empty series (caller falls back to candle price).
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = _cache_path(symbol, day)
    if os.path.exists(path):
        ts: list[float] = []
        px: list[float] = []
        with open(path, newline="") as f:
            for row in csv.reader(f):
                ts.append(float(row[0]))
                px.append(float(row[1]))
        return TickSeries(ts, px)

    url = _ARCHIVE_URL.format(sym=symbol, day=day)
    try:
        r = httpx.get(url, timeout=timeout)
        if r.status_code != 200:
            return TickSeries([], [])
        rows = csv.DictReader(io.StringIO(gzip.decompress(r.content).decode()))
        ts2: list[float] = []
        px2: list[float] = []
        for row in rows:
            ts2.append(float(row["timestamp"]))
            px2.append(float(row["price"]))
    except Exception:
        return TickSeries([], [])

    series = TickSeries(ts2, px2)  # __post_init__ sorts ascending
    # Cache the slim ascending view.
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        for a, b in zip(series.timestamps, series.prices):
            w.writerow((a, b))
    os.replace(tmp, path)
    return series


def load_window(
    symbol: str, start: datetime, end: datetime, *, timeout: float = 90.0
) -> TickSeries:
    """TickSeries for [start, end] across the spanned day(s), concatenated ascending."""
    days: list[str] = []
    d = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_day = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    while d <= end_day:
        days.append(d.strftime("%Y-%m-%d"))
        d = datetime.fromtimestamp(d.timestamp() + 86400, tz=timezone.utc)

    lo, hi = start.timestamp(), end.timestamp()
    ts: list[float] = []
    px: list[float] = []
    for day in days:
        s = load_symbol_day(symbol, day, timeout=timeout)
        for a, b in zip(s.timestamps, s.prices):
            if lo <= a <= hi:
                ts.append(a)
                px.append(b)
    return TickSeries(ts, px)
