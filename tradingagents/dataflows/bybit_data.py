"""Bybit perpetual futures data layer — rate limiter, circuit breaker, HTTP client.

Public API functions: get_bybit_klines, get_bybit_funding_rates,
get_bybit_open_interest, get_bybit_ticker, get_bybit_indicators.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import io
import logging
import threading
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from stockstats import wrap

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level HTTP session (singleton, thread-safe via urllib3)
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(pool_connections=1, pool_maxsize=5, max_retries=0),
)

BYBIT_BASE_URL = "https://api.bybit.com"


# ---------------------------------------------------------------------------
# BybitRateLimiter — token bucket with threading.Condition
# ---------------------------------------------------------------------------

class BybitRateLimiter:
    """Token bucket rate limiter safe for multi-threaded use.

    Uses threading.Condition so waiting threads release the lock and can be
    woken when tokens become available.
    """

    def __init__(self, capacity: float = 80, refill_rate: float = 16.0):
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._cond = threading.Condition(threading.Lock())

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            self._last_refill = now

    def acquire(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        warned = False
        wait_start = time.monotonic()

        with self._cond:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Rate limiter: could not acquire token within {timeout}s"
                    )

                if not warned and (time.monotonic() - wait_start) > 1.0:
                    logger.warning(
                        "Rate limiter: blocked >1s waiting for token "
                        "(%.1fs so far)", time.monotonic() - wait_start,
                    )
                    warned = True

                self._cond.wait(timeout=min(remaining, 0.1))


# ---------------------------------------------------------------------------
# BybitCircuitBreaker — per-run instance, trips after N consecutive failures
# ---------------------------------------------------------------------------

class BybitUnavailableError(Exception):
    """Raised when the circuit breaker is open (Bybit API unreachable)."""


class BybitCircuitBreaker:
    """Simple consecutive-failure circuit breaker. Thread-safe."""

    def __init__(self, failure_threshold: int = 3):
        self._threshold = failure_threshold
        self._consecutive_failures = 0
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self._consecutive_failures >= self._threshold:
                raise BybitUnavailableError(
                    f"Circuit breaker open: {self._consecutive_failures} "
                    f"consecutive failures"
                )

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0


# ---------------------------------------------------------------------------
# HMAC signing + log scrubbing
# ---------------------------------------------------------------------------

_SENSITIVE_PARAM_KEYS = {"api_key", "sign", "timestamp", "api_secret"}


def _sign_request(params: dict, api_key: str, api_secret: str) -> dict:
    """Add HMAC-SHA256 signature to request params (Bybit V5 auth)."""
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    signed = dict(params)
    signed["api_key"] = api_key
    signed["timestamp"] = timestamp
    signed["recv_window"] = recv_window

    param_str = "&".join(f"{k}={v}" for k, v in sorted(signed.items()))
    secret = api_secret
    if hasattr(api_secret, "get_secret_value"):
        secret = api_secret.get_secret_value()
    signature = hmac_mod.new(
        secret.encode("utf-8"), param_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    signed["sign"] = signature
    return signed


def _scrub_params_for_logging(params: dict) -> dict:
    """Remove sensitive keys from params before logging."""
    return {k: ("***" if k in _SENSITIVE_PARAM_KEYS else v) for k, v in params.items()}


# ---------------------------------------------------------------------------
# _bybit_request — DRY helper: cache, rate limiter, HTTP, retry, deadline
# ---------------------------------------------------------------------------

_DEFAULT_TOOL_DEADLINE = 45.0
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _bybit_request(
    endpoint: str,
    params: dict,
    cache_key: tuple,
    *,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    deadline: float | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict:
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    if circuit_breaker:
        circuit_breaker.check()

    if deadline is None:
        deadline = time.monotonic() + _DEFAULT_TOOL_DEADLINE

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Bybit request deadline exceeded")

        if limiter:
            limiter.acquire(timeout=min(remaining, 10.0))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Bybit request deadline exceeded after rate limiter wait")

        try:
            resp = _session.get(
                f"{BYBIT_BASE_URL}{endpoint}",
                params=params,
                timeout=(5, min(30, remaining)),
            )
            resp.raise_for_status()
        except Exception as exc:
            if circuit_breaker:
                circuit_breaker.record_failure()
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES - 1:
                backoff = _RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Bybit %s retry %d/%d (status=%s, backoff=%.1fs)",
                    endpoint, attempt + 1, _MAX_RETRIES, status, backoff,
                )
                time.sleep(min(backoff, max(0, deadline - time.monotonic())))
                continue
            raise

        if circuit_breaker:
            circuit_breaker.record_success()

        try:
            data = resp.json()
        except Exception:
            raise ValueError(f"Malformed JSON response from {endpoint}")

        ret_code = data.get("retCode")
        if ret_code is None:
            raise ValueError(f"Malformed response from {endpoint}: missing retCode")
        if ret_code != 0:
            raise ValueError(
                f"Bybit API error on {endpoint}: "
                f"retCode={ret_code}, retMsg={data.get('retMsg', 'unknown')}"
            )

        result = data.get("result", data)
        if cache is not None:
            cache[cache_key] = result
        return result

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_bybit_klines — paginated OHLCV data
# ---------------------------------------------------------------------------

_MAX_KLINE_PAGES = 5
_KLINE_PAGE_SIZE = 200


def get_bybit_klines(
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    cache_key = ("klines", symbol, interval, start_time, end_time)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    deadline = time.monotonic() + _DEFAULT_TOOL_DEADLINE
    all_rows: list[list] = []
    current_end = end_time
    prev_min_ts: int | None = None

    for page in range(_MAX_KLINE_PAGES):
        if deadline - time.monotonic() <= 0:
            break

        result = _bybit_request(
            "/v5/market/kline",
            {
                "category": "linear",
                "symbol": symbol,
                "interval": interval,
                "start": start_time,
                "end": current_end,
                "limit": _KLINE_PAGE_SIZE,
            },
            cache_key=("_kline_page", symbol, interval, start_time, current_end),
            cache=None,  # don't cache individual pages
            limiter=limiter,
            circuit_breaker=circuit_breaker,
            deadline=deadline,
            api_key=api_key,
            api_secret=api_secret,
        )

        rows = result.get("list", [])
        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < _KLINE_PAGE_SIZE:
            break

        timestamps = [int(r[0]) for r in rows]
        min_ts = min(timestamps)

        if prev_min_ts is not None and min_ts == prev_min_ts:
            break

        prev_min_ts = min_ts
        current_end = min_ts - 1

    csv_lines = [
        ",".join(str(v) for v in row)
        for row in all_rows
    ]
    csv_result = "timestamp,open,high,low,close,volume\n" + "\n".join(csv_lines)

    if cache is not None:
        cache[cache_key] = csv_result
    return csv_result


# ---------------------------------------------------------------------------
# get_bybit_funding_rates
# ---------------------------------------------------------------------------

def get_bybit_funding_rates(
    symbol: str,
    start_time: int,
    end_time: int,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    cache_key = ("funding", symbol, start_time, end_time)

    result = _bybit_request(
        "/v5/market/funding/history",
        {"category": "linear", "symbol": symbol, "startTime": start_time, "endTime": end_time, "limit": 200},
        cache_key,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    items = result.get("list", [])
    if not items:
        return f"No funding rate data available for {symbol}."

    lines = [f"Funding Rate History for {symbol}:"]
    for item in items:
        ts = item.get("fundingRateTimestamp", "?")
        rate = item.get("fundingRate", "?")
        lines.append(f"  Timestamp: {ts}, Rate: {rate}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_bybit_open_interest
# ---------------------------------------------------------------------------

def get_bybit_open_interest(
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    cache_key = ("oi", symbol, interval, start_time, end_time)

    result = _bybit_request(
        "/v5/market/open-interest",
        {"category": "linear", "symbol": symbol, "intervalTime": interval, "startTime": start_time, "endTime": end_time, "limit": 200},
        cache_key,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    items = result.get("list", [])
    if not items:
        return f"No open interest data available for {symbol}."

    lines = [f"Open Interest History for {symbol}:"]
    for item in items:
        ts = item.get("timestamp", "?")
        oi = item.get("openInterest", "?")
        lines.append(f"  Timestamp: {ts}, OI: {oi}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_bybit_ticker
# ---------------------------------------------------------------------------

def get_bybit_ticker(
    symbol: str,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    cache_key = ("ticker", symbol)

    result = _bybit_request(
        "/v5/market/tickers",
        {"category": "linear", "symbol": symbol},
        cache_key,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    items = result.get("list", [])
    if not items:
        return f"No ticker data available for {symbol}."

    t = items[0]
    return (
        f"Ticker: {t.get('symbol', symbol)}\n"
        f"Last Price: {t.get('lastPrice', '?')}\n"
        f"24h High: {t.get('highPrice24h', '?')}\n"
        f"24h Low: {t.get('lowPrice24h', '?')}\n"
        f"24h Volume: {t.get('volume24h', '?')}\n"
        f"Funding Rate: {t.get('fundingRate', '?')}\n"
        f"Open Interest: {t.get('openInterest', '?')}"
    )


# ---------------------------------------------------------------------------
# get_bybit_indicators — RSI, MACD, Bollinger, EMA via stockstats
# ---------------------------------------------------------------------------

def get_bybit_indicators(
    symbol: str,
    interval: str,
    start_time: int,
    end_time: int,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    cache_key = ("indicators", symbol, interval, start_time, end_time)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    kline_csv = get_bybit_klines(
        symbol, interval, start_time, end_time,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    df = pd.read_csv(io.StringIO(kline_csv))
    df.columns = [c.lower() for c in df.columns]

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])

    if len(df) < 14:
        result = f"Insufficient data for indicators ({len(df)} rows)."
        if cache is not None:
            cache[cache_key] = result
        return result

    ss = wrap(df)
    rsi = ss["rsi_14"]
    macd = ss["macd"]
    macds = ss["macds"]
    macdh = ss["macdh"]
    boll_ub = ss["boll_ub"]
    boll_lb = ss["boll_lb"]
    ema_20 = ss["close_20_ema"]

    last = len(df) - 1
    lines = [
        f"Technical Indicators for {symbol} ({interval} interval):",
        f"  RSI(14): {rsi.iloc[last]:.2f}",
        f"  MACD: {macd.iloc[last]:.4f}",
        f"  MACD Signal: {macds.iloc[last]:.4f}",
        f"  MACD Histogram: {macdh.iloc[last]:.4f}",
        f"  Bollinger Upper: {boll_ub.iloc[last]:.2f}",
        f"  Bollinger Lower: {boll_lb.iloc[last]:.2f}",
        f"  EMA(20): {ema_20.iloc[last]:.2f}",
        f"  Close: {df['close'].iloc[last]:.2f}",
    ]
    result = "\n".join(lines)

    if cache is not None:
        cache[cache_key] = result
    return result
