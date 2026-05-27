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
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from stockstats import wrap

from backend.services.bybit_rate_gate import get_rate_gate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level HTTP session (singleton, thread-safe via urllib3)
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(pool_connections=10, pool_maxsize=50, max_retries=0),
)


_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    ConnectionResetError,
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

    def __init__(self, capacity: float = 18, refill_rate: float = 18.0):
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
    """Simple consecutive-failure circuit breaker with auto-reset. Thread-safe."""

    def __init__(self, failure_threshold: int = 5, reset_after: float = 30.0):
        self._threshold = failure_threshold
        self._reset_after = reset_after
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self._consecutive_failures >= self._threshold:
                if time.monotonic() - self._last_failure_time > self._reset_after:
                    self._consecutive_failures = 0
                    return
                raise BybitUnavailableError(
                    f"Circuit breaker open: {self._consecutive_failures} "
                    f"consecutive failures"
                )

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_time = time.monotonic()

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0


# ---------------------------------------------------------------------------
# Module-level singletons — shared across all graph instances so aggregate
# request rate stays within Bybit's API limits during parallel scanner runs.
# ---------------------------------------------------------------------------

_shared_limiter: BybitRateLimiter | None = None
_shared_cb: BybitCircuitBreaker | None = None
_shared_infra_lock = threading.Lock()


def get_shared_limiter() -> BybitRateLimiter:
    """Return process-wide rate limiter (lazy init, thread-safe)."""
    global _shared_limiter
    with _shared_infra_lock:
        if _shared_limiter is None:
            _shared_limiter = BybitRateLimiter()
        return _shared_limiter


def get_shared_circuit_breaker() -> BybitCircuitBreaker:
    """Return process-wide circuit breaker (lazy init, thread-safe)."""
    global _shared_cb
    with _shared_infra_lock:
        if _shared_cb is None:
            _shared_cb = BybitCircuitBreaker()
        return _shared_cb


class TTLCache:
    """Thread-safe cache with per-entry TTL expiry.

    Uses composition (not dict inheritance) so only the explicitly
    implemented methods are exposed — no inherited dict methods can
    bypass TTL checks.  Periodic sweeps on write keep memory bounded.
    """

    _SWEEP_INTERVAL = 64  # purge expired entries every N writes

    def __init__(self, ttl_seconds: float = 300.0):
        self._ttl = ttl_seconds
        self._data: dict = {}
        self._timestamps: dict = {}
        self._lock = threading.Lock()
        self._write_count = 0

    def __contains__(self, key) -> bool:
        with self._lock:
            return self._is_alive(key)

    def __getitem__(self, key):
        with self._lock:
            if self._is_alive(key):
                return self._data[key]
            raise KeyError(key)

    def __setitem__(self, key, value):
        with self._lock:
            self._data[key] = value
            self._timestamps[key] = time.monotonic()
            self._write_count += 1
            if self._write_count >= self._SWEEP_INTERVAL:
                self._sweep()
                self._write_count = 0

    def get(self, key, default=None):
        with self._lock:
            if self._is_alive(key):
                return self._data[key]
            return default

    def _is_alive(self, key) -> bool:
        """Check if key exists and is not expired. Evicts if expired. Caller must hold _lock."""
        ts = self._timestamps.get(key)
        if ts is None:
            return False
        if time.monotonic() - ts <= self._ttl:
            return True
        del self._data[key]
        del self._timestamps[key]
        return False

    def _sweep(self) -> None:
        """Remove all expired entries. Caller must hold _lock."""
        now = time.monotonic()
        expired = [k for k, ts in self._timestamps.items() if now - ts > self._ttl]
        for k in expired:
            self._data.pop(k, None)
            self._timestamps.pop(k, None)


_CACHE_MISS = object()


# ---------------------------------------------------------------------------
# HMAC signing + log scrubbing
# ---------------------------------------------------------------------------

_SENSITIVE_PARAM_KEYS = {"api_key", "sign", "timestamp", "api_secret"}

# ---------------------------------------------------------------------------
# Symbol validation — fetch available linear perpetual symbols from Bybit
# ---------------------------------------------------------------------------

_valid_symbols_cache: set[str] | None = None
_valid_symbols_lock = threading.Lock()
_valid_symbols_ts: float = 0.0
_SYMBOLS_TTL = 3600  # refresh every hour


def _fetch_valid_symbols() -> set[str]:
    """Fetch all valid linear perpetual symbols from Bybit."""
    symbols: set[str] = set()
    cursor = ""
    for _ in range(20):  # safety limit
        params: dict = {"category": "linear", "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = _session.get(
                "https://api.bybit.com/v5/market/instruments-info",
                params=params,
                timeout=10,
            )
            data = resp.json()
            if data.get("retCode") != 0:
                logger.warning("Failed to fetch Bybit instruments: %s", data.get("retMsg"))
                break
            for item in data.get("result", {}).get("list", []):
                sym = item.get("symbol", "")
                if not sym:
                    continue
                if item.get("status") != "Trading":
                    continue
                if item.get("contractType") != "LinearPerpetual":
                    continue
                if not sym.endswith("USDT"):
                    continue
                symbols.add(sym)
            cursor = data.get("result", {}).get("nextPageCursor", "")
            if not cursor:
                break
        except Exception:
            logger.warning("Error fetching Bybit instruments", exc_info=True)
            break
    logger.info("Loaded %d valid Bybit linear symbols", len(symbols))
    return symbols


def get_valid_symbols() -> set[str]:
    """Return cached set of valid Bybit linear perpetual symbols."""
    global _valid_symbols_cache, _valid_symbols_ts
    now = time.monotonic()
    if _valid_symbols_cache is not None and (now - _valid_symbols_ts) < _SYMBOLS_TTL:
        return _valid_symbols_cache
    with _valid_symbols_lock:
        # double-check after acquiring lock
        if _valid_symbols_cache is not None and (time.monotonic() - _valid_symbols_ts) < _SYMBOLS_TTL:
            return _valid_symbols_cache
        _valid_symbols_cache = _fetch_valid_symbols()
        _valid_symbols_ts = time.monotonic()
        return _valid_symbols_cache


class InvalidSymbolError(ValueError):
    """Raised when a symbol is not listed on Bybit linear perpetuals."""
    pass


def normalize_bybit_symbol(symbol: str) -> str:
    """Normalize a symbol to Bybit's listed format, raising if not found."""
    upper = symbol.upper().strip()
    valid = get_valid_symbols()
    if not valid:
        logger.warning(
            "Bybit symbol catalog unavailable; skipping strict validation for %s",
            upper,
        )
        return upper
    if upper in valid:
        return upper
    # Try 1000x prefix for low-priced tokens
    prefixed = f"1000{upper}"
    if prefixed in valid:
        logger.info("Symbol %s normalized to %s", upper, prefixed)
        return prefixed
    raise InvalidSymbolError(
        f"Symbol '{upper}' is not available on Bybit linear perpetuals. "
        f"Check https://www.bybit.com/derivatives/en/usdt-perpetual for valid symbols."
    )


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
    if cache is not None:
        _cached = cache.get(cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

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
            if not get_rate_gate().acquire_sync(timeout=min(remaining, 10.0)):
                raise TimeoutError("Bybit rate gate timeout")
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
        except _RETRYABLE_EXCEPTIONS as exc:
            if circuit_breaker:
                circuit_breaker.record_failure()
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                backoff = _RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Bybit %s connection error retry %d/%d (backoff=%.1fs): %s",
                    endpoint, attempt + 1, _MAX_RETRIES, backoff, exc,
                )
                time.sleep(min(backoff, max(0, deadline - time.monotonic())))
                continue
            raise
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

        try:
            data = resp.json()
        except Exception:
            raise ValueError(f"Malformed JSON response from {endpoint}")

        ret_code = data.get("retCode")
        if ret_code is None:
            raise ValueError(f"Malformed response from {endpoint}: missing retCode")

        if ret_code in (10006, 10018):
            if attempt < _MAX_RETRIES - 1:
                last_exc = ValueError(
                    f"Bybit rate limited on {endpoint}: retCode={ret_code}"
                )
                reset_ts = resp.headers.get("X-Bapi-Limit-Reset-Timestamp")
                if reset_ts:
                    try:
                        delay = max((int(reset_ts) - int(time.time() * 1000)) / 1000.0, 0.5)
                        delay = min(delay, 10.0)
                    except (ValueError, TypeError):
                        delay = _RETRY_BACKOFF_BASE * (2 ** attempt)
                else:
                    delay = _RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Bybit rate limited on %s (retCode=%d), retrying in %.1fs (attempt %d/%d)",
                    endpoint, ret_code, delay, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(min(delay, max(0, deadline - time.monotonic())))
                continue
            raise ValueError(
                f"Bybit API error on {endpoint}: "
                f"retCode={ret_code}, retMsg={data.get('retMsg', 'unknown')}"
            )

        if circuit_breaker:
            circuit_breaker.record_success()

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
    symbol = normalize_bybit_symbol(symbol)
    cache_key = ("klines", symbol, interval, start_time, end_time)
    if cache is not None:
        _cached = cache.get(cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

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

    truncated = len(all_rows) >= _MAX_KLINE_PAGES * _KLINE_PAGE_SIZE

    csv_lines = [
        ",".join(str(v) for v in row[:6])
        for row in all_rows
    ]
    csv_result = "timestamp,open,high,low,close,volume\n" + "\n".join(csv_lines)

    if truncated:
        csv_result = (
            f"[WARNING: Data truncated to {len(all_rows)} candles due to API pagination limit. "
            f"The requested date range requires more data than was fetched. "
            f"Analysis based on this data may not reflect the full historical period.]\n"
            + csv_result
        )

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
    symbol = normalize_bybit_symbol(symbol)
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
    for item in items[:21]:  # Last 21 entries (~7 days at 8h intervals)
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
    symbol = normalize_bybit_symbol(symbol)
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
    for item in items[:42]:  # Cap at 42 entries (7 days at 4h intervals)
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
    symbol = normalize_bybit_symbol(symbol)
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
    symbol = normalize_bybit_symbol(symbol)
    cache_key = ("indicators", symbol, interval, start_time, end_time)
    if cache is not None:
        _cached = cache.get(cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

    kline_csv = get_bybit_klines(
        symbol, interval, start_time, end_time,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    # Strip any warning prefix lines (e.g., from truncated data) before CSV parsing
    csv_lines = kline_csv.split("\n")
    csv_clean = "\n".join(line for line in csv_lines if not line.startswith("["))
    df = pd.read_csv(io.StringIO(csv_clean))
    df.columns = [c.lower() for c in df.columns]

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing or len(df) == 0:
        result = f"No kline data available for {symbol} (missing columns: {missing}, rows: {len(df)})."
        if cache is not None:
            cache[cache_key] = result
        return result

    for col in required:
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


# ---------------------------------------------------------------------------
# build_current_price_context — live ticker + recent 5-min candles
# ---------------------------------------------------------------------------

def build_current_price_context(
    symbol: str,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    as_of_ms: int | None = None,
    primary_interval: str | None = None,
) -> str:
    """Fetch live ticker + multi-timeframe candles for immediate price context.

    This gives all agents awareness of the CURRENT price and recent
    price action across multiple timeframes (5m, 15m, 1h, 4h, daily).

    All 6 API calls (ticker + 5 kline intervals) run concurrently for
    ~3x speedup vs sequential fetching.

    Pass ``as_of_ms`` to pin the time window so parallel analyses that
    start seconds apart use the same candle boundaries.

    Pass ``primary_interval`` to tag the section matching the user's
    selected kline interval with ``(PRIMARY TIMEFRAME)``.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time

    symbol = normalize_bybit_symbol(symbol)
    now_ms = as_of_ms if as_of_ms is not None else int(_time.time() * 1000)

    shared = dict(cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
                  api_key=api_key, api_secret=api_secret)

    def _ptag(interval: str) -> str:
        return " (PRIMARY TIMEFRAME)" if primary_interval == interval else ""

    def _fetch_ticker():
        return get_bybit_ticker(symbol, **shared)

    def _fetch_kline(interval, start):
        return get_bybit_klines(symbol, interval, start, now_ms, **shared)

    # (heading, callable) — heading is the single source of truth for both
    # success output and error fallback.
    tasks = [
        ("## LIVE PRICE SNAPSHOT (real-time)",
         _fetch_ticker),
        (f"\n## RECENT 5-MIN CANDLES (last ~2 hours){_ptag('5')}",
         lambda: _fetch_kline("5", now_ms - 2 * 3600_000)),
        (f"\n## RECENT 15-MIN CANDLES (last ~6 hours){_ptag('15')}",
         lambda: _fetch_kline("15", now_ms - 6 * 3600_000)),
        (f"\n## 1-HOUR CANDLES (last ~24 hours){_ptag('60')}",
         lambda: _fetch_kline("60", now_ms - 24 * 3600_000)),
        (f"\n## 4-HOUR CANDLES (last ~48 hours){_ptag('240')}",
         lambda: _fetch_kline("240", now_ms - 48 * 3600_000)),
        (f"\n## DAILY CANDLES (last ~30 days){_ptag('D')}",
         lambda: _fetch_kline("D", now_ms - 30 * 24 * 3600_000)),
    ]

    results: list[tuple[str, str]] = [("", "")] * len(tasks)

    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="price_ctx") as pool:
        future_to_idx = {pool.submit(fn): i for i, (_heading, fn) in enumerate(tasks)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            heading = tasks[idx][0]
            try:
                data = future.result()
                results[idx] = (heading, data)
            except Exception as exc:
                results[idx] = (heading, f"Unavailable: {exc}")

    parts: list[str] = []
    for heading, data in results:
        parts.append(heading)
        parts.append(data)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# get_bybit_price_changes — compute multi-timeframe % changes from klines
# ---------------------------------------------------------------------------

def get_bybit_price_changes(
    symbol: str,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict[str, float | None]:
    """Compute price change percentages for 24h, 7d, 14d, 30d, 60d, 200d, 1y.

    Returns dict like {"24h": 2.5, "7d": -1.3, ...}. Uses daily klines.
    Fetches in two pages (200 each) to cover ~400 days for 1y calculation.
    """
    import time as _time

    symbol = normalize_bybit_symbol(symbol)
    now_ms = int(_time.time() * 1000)
    cache_hour = now_ms // (3600_000)

    # Check combined cache first
    combined_cache_key = ("price_changes_combined", symbol, cache_hour)
    if cache is not None:
        _cached = cache.get(combined_cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

    all_rows: list[list] = []

    # Page 1: most recent 200 days
    result1 = _bybit_request(
        "/v5/market/kline",
        {"category": "linear", "symbol": symbol, "interval": "D",
         "start": now_ms - (200 * 24 * 60 * 60 * 1000), "end": now_ms, "limit": 200},
        cache_key=("price_changes_p1", symbol, cache_hour),
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )
    all_rows.extend(result1.get("list", []))

    # Page 2: 200-400 days ago (needed for 200d and 1y calculations)
    # Non-critical: if this fails, we still have short-term changes from page 1
    page2_end = now_ms - (200 * 24 * 60 * 60 * 1000)
    page2_start = now_ms - (400 * 24 * 60 * 60 * 1000)
    try:
        result2 = _bybit_request(
            "/v5/market/kline",
            {"category": "linear", "symbol": symbol, "interval": "D",
             "start": page2_start, "end": page2_end, "limit": 200},
            cache_key=("price_changes_p2", symbol, cache_hour),
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        all_rows.extend(result2.get("list", []))
    except Exception:
        pass  # 200d and 1y will show N/A, short-term changes still available

    if not all_rows:
        return {}

    # Bybit klines: [timestamp, open, high, low, close, volume, turnover] desc order
    # Deduplicate by timestamp and sort ascending
    seen: set[str] = set()
    unique_rows: list[list] = []
    for row in all_rows:
        ts = row[0]
        if ts not in seen:
            seen.add(ts)
            unique_rows.append(row)
    unique_rows.sort(key=lambda r: int(r[0]))

    current_close = float(unique_rows[-1][4])

    periods = {"7d": 7, "14d": 14, "30d": 30, "60d": 60, "200d": 200, "1y": 365}
    changes: dict[str, float | None] = {}

    # 24h change: use ticker's rolling 24h percentage (more accurate than daily candle close-to-close)
    try:
        ticker_result = _bybit_request(
            "/v5/market/tickers",
            {"category": "linear", "symbol": symbol},
            cache_key=("ticker", symbol),
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        ticker_items = ticker_result.get("list", [])
        if ticker_items:
            pct_str = ticker_items[0].get("price24hPcnt", "")
            if pct_str:
                changes["24h"] = round(float(pct_str) * 100, 2)
            else:
                changes["24h"] = None
        else:
            changes["24h"] = None
    except Exception:
        changes["24h"] = None

    for label, days in periods.items():
        idx = len(unique_rows) - 1 - days
        if idx >= 0:
            past_close = float(unique_rows[idx][4])
            if past_close > 0:
                changes[label] = round((current_close - past_close) / past_close * 100, 2)
            else:
                changes[label] = None
        else:
            changes[label] = None

    if cache is not None:
        cache[combined_cache_key] = changes
    return changes


# ---------------------------------------------------------------------------
# get_bybit_long_short_ratio — trader sentiment from actual positions
# ---------------------------------------------------------------------------

def get_bybit_long_short_ratio(
    symbol: str,
    period: str = "1d",
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    """Fetch long/short ratio (account-based) for a symbol.

    period: 5min, 15min, 30min, 1h, 4h, 1d
    """
    symbol = normalize_bybit_symbol(symbol)
    cache_key = ("ls_ratio", symbol, period)

    result = _bybit_request(
        "/v5/market/account-ratio",
        {"category": "linear", "symbol": symbol, "period": period, "limit": 50},
        cache_key,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    items = result.get("list", [])
    if not items:
        return f"No long/short ratio data available for {symbol}."

    lines = [f"Long/Short Ratio for {symbol} ({period} period):"]
    for item in items[:20]:
        ts = item.get("timestamp", "?")
        buy = item.get("buyRatio", "?")
        sell = item.get("sellRatio", "?")
        lines.append(f"  Timestamp: {ts}, Long: {buy}, Short: {sell}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_bybit_derivatives_summary — combined OI + funding + long/short snapshot
# ---------------------------------------------------------------------------

def get_bybit_derivatives_summary(
    symbol: str,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> str:
    """Comprehensive derivatives snapshot: ticker, OI history, funding history, L/S ratio."""
    import time as _time

    symbol = normalize_bybit_symbol(symbol)
    now_ms = int(_time.time() * 1000)
    parts: list[str] = []

    # 1) Ticker (price, volume, current funding, current OI)
    try:
        ticker = get_bybit_ticker(symbol, cache=cache, limiter=limiter,
                                   circuit_breaker=circuit_breaker,
                                   api_key=api_key, api_secret=api_secret)
        parts.append("## Live Ticker")
        parts.append(ticker)
    except Exception as exc:
        parts.append(f"## Live Ticker\nUnavailable: {exc}")

    # 2) Open Interest history (last 7 days, 4h intervals)
    try:
        seven_days_ago = now_ms - (7 * 24 * 60 * 60 * 1000)
        oi = get_bybit_open_interest(symbol, "4h", seven_days_ago, now_ms,
                                      cache=cache, limiter=limiter,
                                      circuit_breaker=circuit_breaker,
                                      api_key=api_key, api_secret=api_secret)
        parts.append("\n## Open Interest (7d, 4h intervals)")
        parts.append(oi)
    except Exception as exc:
        parts.append(f"\n## Open Interest\nUnavailable: {exc}")

    # 3) Funding rate history (last 7 days)
    try:
        funding = get_bybit_funding_rates(symbol, now_ms - (7 * 24 * 60 * 60 * 1000), now_ms,
                                           cache=cache, limiter=limiter,
                                           circuit_breaker=circuit_breaker,
                                           api_key=api_key, api_secret=api_secret)
        parts.append("\n## Funding Rates (7d)")
        parts.append(funding)
    except Exception as exc:
        parts.append(f"\n## Funding Rates\nUnavailable: {exc}")

    # 4) Long/Short ratio
    try:
        ls = get_bybit_long_short_ratio(symbol, "1d", cache=cache, limiter=limiter,
                                         circuit_breaker=circuit_breaker,
                                         api_key=api_key, api_secret=api_secret)
        parts.append("\n## Long/Short Ratio (daily)")
        parts.append(ls)
    except Exception as exc:
        parts.append(f"\n## Long/Short Ratio\nUnavailable: {exc}")

    # 5) Price changes computed from klines
    try:
        changes = get_bybit_price_changes(symbol, cache=cache, limiter=limiter,
                                           circuit_breaker=circuit_breaker,
                                           api_key=api_key, api_secret=api_secret)
        if changes:
            parts.append("\n## Price Changes (from Bybit klines)")
            parts.append("| Period | Change % |")
            parts.append("|--------|----------|")
            for period, pct in changes.items():
                parts.append(f"| {period} | {pct}% |" if pct is not None else f"| {period} | N/A |")
    except Exception as exc:
        parts.append(f"\n## Price Changes\nUnavailable: {exc}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Multi-Timeframe Analysis (F4)
# ---------------------------------------------------------------------------

_HIGHER_TF_MAP: dict[str, str | None] = {
    "1": "60",
    "3": "60",
    "5": "60",
    "15": "240",
    "30": "240",
    "60": "240",
    "240": "D",
    "D": "W",
    "W": None,
}


def get_higher_timeframe(interval: str) -> str | None:
    return _HIGHER_TF_MAP.get(str(interval))


def _parse_kline_csv(csv_text: str) -> pd.DataFrame:
    lines = csv_text.strip().split("\n")
    data_lines = [line for line in lines if not line.startswith("[")]
    csv_str = "\n".join(data_lines)
    df = pd.read_csv(io.StringIO(csv_str))
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Order Book Depth (F7)
# ---------------------------------------------------------------------------

def get_bybit_orderbook(
    symbol: str,
    depth: int = 25,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict:
    symbol = normalize_bybit_symbol(symbol)
    cache_key = ("orderbook", symbol, depth)
    if cache is not None:
        _cached = cache.get(cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

    result = _bybit_request(
        "/v5/market/orderbook",
        {"category": "linear", "symbol": symbol, "limit": min(depth, 200)},
        cache_key=cache_key,
        cache=None,
        limiter=limiter,
        circuit_breaker=circuit_breaker,
        deadline=time.monotonic() + 10,
        api_key=api_key,
        api_secret=api_secret,
    )

    bids = [(float(p), float(q)) for p, q in result.get("b", [])]
    asks = [(float(p), float(q)) for p, q in result.get("a", [])]

    best_bid = bids[0][0] if bids else 0
    best_ask = asks[0][0] if asks else 0
    mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
    spread_bps = ((best_ask - best_bid) / mid * 10000) if mid else 0

    bid_vol = sum(q for _, q in bids)
    ask_vol = sum(q for _, q in asks)
    total_vol = bid_vol + ask_vol
    imbalance_ratio = (bid_vol - ask_vol) / total_vol if total_vol else 0

    wall_levels = []
    if bids:
        avg_bid_size = bid_vol / len(bids)
        wall_levels += [{"side": "bid", "price": p, "size": q}
                        for p, q in bids if q > avg_bid_size * 3]
    if asks:
        avg_ask_size = ask_vol / len(asks)
        wall_levels += [{"side": "ask", "price": p, "size": q}
                        for p, q in asks if q > avg_ask_size * 3]

    out = {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": round(spread_bps, 2),
        "imbalance_ratio": round(imbalance_ratio, 4),
        "bid_depth": round(bid_vol, 4),
        "ask_depth": round(ask_vol, 4),
        "wall_levels": wall_levels[:5],
    }
    if cache is not None:
        cache[cache_key] = out
    return out


# ---------------------------------------------------------------------------
# Volatility Metrics (F7)
# ---------------------------------------------------------------------------



def get_volatility_metrics(kline_csv: str, lookback: int = 90, intervals_per_year: int | None = None) -> dict:
    df = _parse_kline_csv(kline_csv)
    if len(df) < 14:
        return {"atr_14": None, "rv_24h": None, "rv_7d": None,
                "bb_width": None, "volatility_regime": "Normal"}

    # Infer annualization factor from candle timestamps if not provided
    if intervals_per_year is None and len(df) >= 2 and "timestamp" in df.columns:
        try:
            gap_ms = int(float(df["timestamp"].iloc[-1])) - int(float(df["timestamp"].iloc[-2]))
        except (ValueError, TypeError):
            gap_ms = 0
        if gap_ms > 0:
            intervals_per_year = int(365 * 24 * 3600 * 1000 / gap_ms)
        else:
            intervals_per_year = 365 * 24  # fallback: assume hourly
    elif intervals_per_year is None:
        intervals_per_year = 365 * 24  # fallback: assume hourly

    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_14 = tr.rolling(14).mean().iloc[-1]

    log_ret = np.log(close / close.shift(1)).dropna()
    ann_factor = np.sqrt(intervals_per_year)
    _rv24 = float(log_ret.tail(24).std() * ann_factor) if len(log_ret) >= 24 else None
    rv_24h = _rv24 if _rv24 is not None and pd.notna(_rv24) else None
    _rv7 = float(log_ret.tail(168).std() * ann_factor) if len(log_ret) >= 168 else None
    rv_7d = _rv7 if _rv7 is not None and pd.notna(_rv7) else None

    sma_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std()
    bb_upper = sma_20 + 2 * std_20
    bb_lower = sma_20 - 2 * std_20
    if pd.notna(sma_20.iloc[-1]) and sma_20.iloc[-1] != 0:
        _bw = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / sma_20.iloc[-1]
        bb_width = float(_bw) if pd.notna(_bw) else None
    else:
        bb_width = None

    lb = min(lookback, len(tr) - 14)
    if lb >= 14:
        atr_history = tr.rolling(14).mean().dropna().tail(lb)
        pctl = atr_history.rank(pct=True).iloc[-1] if len(atr_history) > 0 else 0.5
    else:
        pctl = 0.5

    if pctl < 0.25:
        regime = "Low"
    elif pctl > 0.75:
        regime = "High"
    else:
        regime = "Normal"

    return {
        "atr_14": round(float(atr_14), 4) if pd.notna(atr_14) else None,
        "rv_24h": round(rv_24h, 4) if rv_24h else None,
        "rv_7d": round(rv_7d, 4) if rv_7d else None,
        "bb_width": round(bb_width, 4) if bb_width else None,
        "volatility_regime": regime,
    }


# ---------------------------------------------------------------------------
# Market Regime (F7)
# ---------------------------------------------------------------------------

def get_market_regime(kline_csv: str) -> dict:
    df = _parse_kline_csv(kline_csv)
    if len(df) < 200:
        return {"regime": "Unknown", "trend_direction": "Unknown",
                "trend_strength": 0, "adx": None,
                "ema_20": None, "ema_50": None, "ema_200": None}

    close = df["close"]
    ema_20 = close.ewm(span=20).mean().iloc[-1]
    ema_50 = close.ewm(span=50).mean().iloc[-1]
    ema_200 = close.ewm(span=200).mean().iloc[-1]

    high, low = df["high"], df["low"]
    plus_dm = (high - high.shift(1)).clip(lower=0)
    minus_dm = (low.shift(1) - low).clip(lower=0)
    mask = plus_dm > minus_dm
    plus_dm = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_14 = tr.ewm(span=14).mean()
    plus_di = 100 * (plus_dm.ewm(span=14).mean() / atr_14.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(span=14).mean() / atr_14.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1))
    adx = dx.ewm(span=14).mean().iloc[-1]

    if not pd.notna(adx):
        regime = "Unknown"
    elif adx > 25:
        regime = "Trending"
    elif adx < 20:
        regime = "Ranging"
    else:
        regime = "Transitional"

    if ema_20 > ema_50 > ema_200:
        direction = "Bullish"
        strength = min(10, int((ema_20 / ema_200 - 1) * 500))
    elif ema_20 < ema_50 < ema_200:
        direction = "Bearish"
        strength = min(10, int((1 - ema_20 / ema_200) * 500))
    else:
        direction = "Mixed"
        strength = 3

    return {
        "regime": regime,
        "trend_direction": direction,
        "trend_strength": max(1, strength),
        "adx": round(float(adx), 2) if pd.notna(adx) else None,
        "ema_20": round(float(ema_20), 2),
        "ema_50": round(float(ema_50), 2),
        "ema_200": round(float(ema_200), 2),
    }


# ---------------------------------------------------------------------------
# Liquidation Price Estimation (F7)
# ---------------------------------------------------------------------------

def estimate_liquidation_price(
    entry: float, leverage: int, side: str,
    maint_margin_rate: float = 0.005,
) -> dict:
    if leverage <= 0 or entry <= 0:
        return {"liq_price": None, "distance_pct": None}

    if side.lower() in ("long", "buy"):
        liq = entry * (1 - 1 / leverage + maint_margin_rate)
        distance_pct = (entry - liq) / entry * 100
    else:
        liq = entry * (1 + 1 / leverage - maint_margin_rate)
        distance_pct = (liq - entry) / entry * 100

    return {
        "liq_price": round(liq, 4),
        "distance_pct": round(distance_pct, 2),
    }


# ---------------------------------------------------------------------------
# Funding Rate Cost Projection (F7)
# ---------------------------------------------------------------------------

def project_funding_cost(
    funding_csv: str,
    hold_intervals: int = 21,
) -> dict:
    lines = funding_csv.strip().split("\n")
    rates: list[float] = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                rates.append(float(parts[1]))
            except (ValueError, IndexError):
                continue

    if not rates:
        return {"total_rate": None, "annualized_pct": None,
                "break_even_move_pct": None, "severity": "unknown"}

    recent_24h = rates[-3:] if len(rates) >= 3 else rates
    older = rates[:-3] if len(rates) > 3 else []
    if older:
        weighted_avg = (sum(recent_24h) * 2 + sum(older)) / (len(recent_24h) * 2 + len(older))
    else:
        weighted_avg = sum(recent_24h) / len(recent_24h)

    total_rate = weighted_avg * hold_intervals
    annualized_pct = weighted_avg * 3 * 365 * 100

    if abs(weighted_avg * 100) > 0.1:
        severity = "extreme"
    elif abs(weighted_avg * 100) > 0.03:
        severity = "elevated"
    else:
        severity = "normal"

    return {
        "total_rate": round(total_rate, 6),
        "annualized_pct": round(annualized_pct, 2),
        "break_even_move_pct": round(abs(total_rate) * 100, 4),
        "severity": severity,
    }


# ---------------------------------------------------------------------------
# Market Microstructure Aggregation (F7)
# ---------------------------------------------------------------------------

def get_market_microstructure(
    symbol: str,
    kline_csv: str | None = None,
    funding_csv: str | None = None,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict:
    micro: dict = {}

    try:
        ob = get_bybit_orderbook(
            symbol, cache=cache, limiter=limiter,
            circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        micro["orderbook"] = ob
    except Exception as exc:
        logger.warning("Microstructure: orderbook fetch failed: %s", exc)
        micro["orderbook"] = None

    if kline_csv:
        try:
            micro["volatility"] = get_volatility_metrics(kline_csv)
        except Exception as exc:
            logger.warning("Microstructure: volatility calc failed: %s", exc)
            micro["volatility"] = None

        try:
            micro["regime"] = get_market_regime(kline_csv)
        except Exception as exc:
            logger.warning("Microstructure: regime calc failed: %s", exc)
            micro["regime"] = None
    else:
        micro["volatility"] = None
        micro["regime"] = None

    if funding_csv:
        try:
            micro["funding_projection"] = project_funding_cost(funding_csv)
        except Exception as exc:
            logger.warning("Microstructure: funding projection failed: %s", exc)
            micro["funding_projection"] = None
    else:
        micro["funding_projection"] = None

    return micro


# ---------------------------------------------------------------------------
# Recent Trades & CVD (Cumulative Volume Delta)
# ---------------------------------------------------------------------------

def get_bybit_recent_trades(
    symbol: str,
    limit: int = 500,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict:
    """Fetch recent trades and compute CVD + whale detection.

    Returns dict with: trades summary, CVD, buy/sell volume breakdown,
    whale trades (>95th percentile size).
    """
    symbol = normalize_bybit_symbol(symbol)
    cache_key = ("recent_trades", symbol, limit)
    if cache is not None:
        _cached = cache.get(cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

    result = _bybit_request(
        "/v5/market/recent-trade",
        {"category": "linear", "symbol": symbol, "limit": min(limit, 1000)},
        cache_key=cache_key,
        cache=None,
        limiter=limiter,
        circuit_breaker=circuit_breaker,
        api_key=api_key,
        api_secret=api_secret,
    )

    trades = result.get("list", [])
    if not trades:
        return {"cvd": 0, "buy_volume": 0, "sell_volume": 0,
                "trade_count": 0, "whale_trades": [], "net_whale_flow": 0}

    buy_vol = 0.0
    sell_vol = 0.0
    sizes = []
    for t in trades:
        qty = float(t.get("size", 0))
        side = t.get("side", "")
        sizes.append(qty)
        if side == "Buy":
            buy_vol += qty
        else:
            sell_vol += qty

    cvd = buy_vol - sell_vol

    # Whale detection: trades > 95th percentile
    whale_trades = []
    threshold = 0.0
    if sizes:
        threshold = float(np.percentile(sizes, 95))
        whale_buy = 0.0
        whale_sell = 0.0
        for t in trades:
            qty = float(t.get("size", 0))
            if qty >= threshold:
                side = t.get("side", "")
                price = float(t.get("price", 0))
                whale_trades.append({"side": side, "price": price, "size": qty})
                if side == "Buy":
                    whale_buy += qty
                else:
                    whale_sell += qty
        net_whale_flow = whale_buy - whale_sell
    else:
        net_whale_flow = 0.0

    out = {
        "cvd": round(cvd, 4),
        "buy_volume": round(buy_vol, 4),
        "sell_volume": round(sell_vol, 4),
        "trade_count": len(trades),
        "whale_trades": whale_trades[:10],
        "net_whale_flow": round(net_whale_flow, 4),
        "whale_threshold_size": round(threshold, 4) if sizes else 0,
    }
    if cache is not None:
        cache[cache_key] = out
    return out


# ---------------------------------------------------------------------------
# Cross-Asset Correlation (BTC/ETH)
# ---------------------------------------------------------------------------

def compute_correlation(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    cache: dict | None = None,
    limiter: BybitRateLimiter | None = None,
    circuit_breaker: BybitCircuitBreaker | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict:
    """Compute rolling correlation of symbol returns vs BTC and ETH.

    Returns correlation coefficients and beta values.
    Uses only the most recent 100 candles to minimize API calls.
    """
    symbol = normalize_bybit_symbol(symbol)
    cache_key = ("correlation", symbol, interval, start_ms, end_ms)
    if cache is not None:
        _cached = cache.get(cache_key, _CACHE_MISS)
        if _cached is not _CACHE_MISS:
            return _cached

    # Limit to 100 candles from end_ms to reduce API calls (1 page per symbol)
    _CORR_CANDLES = 100
    _interval_ms_map = {"1": 60_000, "5": 300_000, "15": 900_000, "30": 1_800_000,
                        "60": 3_600_000, "120": 7_200_000, "240": 14_400_000,
                        "D": 86_400_000, "W": 604_800_000}
    interval_ms = _interval_ms_map.get(str(interval), 3_600_000)
    corr_start_ms = max(start_ms, end_ms - _CORR_CANDLES * interval_ms)

    def _fetch_closes(sym: str) -> pd.Series:
        raw = get_bybit_klines(
            sym, interval, corr_start_ms, end_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        df = _parse_kline_csv(raw)
        return df["close"]

    try:
        target_closes = _fetch_closes(symbol)
    except Exception as exc:
        logger.warning("Correlation: failed to fetch klines for %s: %s", symbol, exc)
        return {"btc_corr": None, "eth_corr": None, "btc_beta": None, "eth_beta": None}

    result = {}
    for ref_symbol, key in [("BTCUSDT", "btc"), ("ETHUSDT", "eth")]:
        if symbol == ref_symbol:
            result[f"{key}_corr"] = 1.0
            result[f"{key}_beta"] = 1.0
            continue
        try:
            ref_closes = _fetch_closes(ref_symbol)
            # Align lengths
            min_len = min(len(target_closes), len(ref_closes))
            if min_len < 5:
                result[f"{key}_corr"] = None
                result[f"{key}_beta"] = None
                continue
            t_ret = target_closes.tail(min_len).pct_change().dropna()
            r_ret = ref_closes.tail(min_len).pct_change().dropna()
            min_len2 = min(len(t_ret), len(r_ret))
            if min_len2 < 2:
                result[f"{key}_corr"] = None
                result[f"{key}_beta"] = None
                continue
            t_ret = t_ret.tail(min_len2).reset_index(drop=True)
            r_ret = r_ret.tail(min_len2).reset_index(drop=True)

            corr = float(t_ret.corr(r_ret))
            # Beta = cov(target, ref) / var(ref)
            cov = float(t_ret.cov(r_ret))
            var_ref = float(r_ret.var())
            beta = cov / var_ref if var_ref > 0 else None

            result[f"{key}_corr"] = round(corr, 4) if pd.notna(corr) else None
            result[f"{key}_beta"] = round(beta, 4) if beta is not None and pd.notna(beta) else None
        except Exception as exc:
            logger.warning("Correlation: failed for %s vs %s: %s", symbol, ref_symbol, exc)
            result[f"{key}_corr"] = None
            result[f"{key}_beta"] = None

    if cache is not None:
        cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Market Session Detection
# ---------------------------------------------------------------------------

def get_market_session() -> dict:
    """Determine current trading session and overlap status.

    Sessions (UTC):
      Asia: 00:00 - 08:00
      London: 07:00 - 16:00
      New York: 13:00 - 22:00
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour = now.hour

    sessions = []
    if 0 <= hour < 8:
        sessions.append("Asia")
    if 7 <= hour < 16:
        sessions.append("London")
    if 13 <= hour < 22:
        sessions.append("New York")
    if not sessions:
        sessions.append("Off-hours")

    overlap = None
    if "Asia" in sessions and "London" in sessions:
        overlap = "Asia-London"
    elif "London" in sessions and "New York" in sessions:
        overlap = "London-New York"

    volatility_profile = "normal"
    if overlap == "London-New York":
        volatility_profile = "high"
    elif overlap == "Asia-London":
        volatility_profile = "elevated"
    elif "Off-hours" in sessions:
        volatility_profile = "low"
    elif "Asia" in sessions and len(sessions) == 1:
        volatility_profile = "low-moderate"

    return {
        "active_sessions": sessions,
        "overlap": overlap,
        "volatility_profile": volatility_profile,
        "utc_hour": hour,
    }
