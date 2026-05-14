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
    HTTPAdapter(pool_connections=4, pool_maxsize=10, max_retries=0),
)
_session_lock = threading.Lock()

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

    def __init__(self, capacity: float = 10, refill_rate: float = 8.0):
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
        except _RETRYABLE_EXCEPTIONS as exc:
            if circuit_breaker:
                circuit_breaker.record_failure()
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                with _session_lock:
                    _session.close()
                    _session.mount(
                        "https://",
                        HTTPAdapter(pool_connections=4, pool_maxsize=10, max_retries=0),
                    )
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
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    kline_csv = get_bybit_klines(
        symbol, interval, start_time, end_time,
        cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
        api_key=api_key, api_secret=api_secret,
    )

    df = pd.read_csv(io.StringIO(kline_csv))
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

    Pass ``as_of_ms`` to pin the time window so parallel analyses that
    start seconds apart use the same candle boundaries.

    Pass ``primary_interval`` to tag the section matching the user's
    selected kline interval with ``(PRIMARY TIMEFRAME)``.
    """
    import time as _time

    symbol = normalize_bybit_symbol(symbol)
    parts: list[str] = []
    now_ms = as_of_ms if as_of_ms is not None else int(_time.time() * 1000)

    # 1) Live ticker
    try:
        ticker_str = get_bybit_ticker(
            symbol, cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        parts.append("## LIVE PRICE SNAPSHOT (real-time)")
        parts.append(ticker_str)
    except Exception as exc:
        parts.append(f"## LIVE PRICE SNAPSHOT\nUnavailable: {exc}")

    def _ptag(interval: str) -> str:
        return " (PRIMARY TIMEFRAME)" if primary_interval == interval else ""

    # 2) Recent 5-min klines (last 2 hours = 24 candles)
    try:
        two_hours_ago = now_ms - (2 * 60 * 60 * 1000)
        recent_klines = get_bybit_klines(
            symbol, "5", two_hours_ago, now_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        parts.append(f"\n## RECENT 5-MIN CANDLES (last ~2 hours){_ptag('5')}")
        parts.append(recent_klines)
    except Exception as exc:
        parts.append(f"\n## RECENT 5-MIN CANDLES\nUnavailable: {exc}")

    # 3) Recent 15-min klines (last 6 hours = 24 candles)
    try:
        six_hours_ago = now_ms - (6 * 60 * 60 * 1000)
        recent_15m = get_bybit_klines(
            symbol, "15", six_hours_ago, now_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        parts.append(f"\n## RECENT 15-MIN CANDLES (last ~6 hours){_ptag('15')}")
        parts.append(recent_15m)
    except Exception as exc:
        parts.append(f"\n## RECENT 15-MIN CANDLES\nUnavailable: {exc}")

    # 4) 1-hour klines (last 24 hours = 24 candles)
    try:
        one_day_ago = now_ms - (24 * 60 * 60 * 1000)
        recent_1h = get_bybit_klines(
            symbol, "60", one_day_ago, now_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        parts.append(f"\n## 1-HOUR CANDLES (last ~24 hours){_ptag('60')}")
        parts.append(recent_1h)
    except Exception as exc:
        parts.append(f"\n## 1-HOUR CANDLES\nUnavailable: {exc}")

    # 5) 4-hour klines (last 48 hours = 12 candles) — medium-term trend
    try:
        two_days_ago = now_ms - (48 * 60 * 60 * 1000)
        recent_4h = get_bybit_klines(
            symbol, "240", two_days_ago, now_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        parts.append(f"\n## 4-HOUR CANDLES (last ~48 hours){_ptag('240')}")
        parts.append(recent_4h)
    except Exception as exc:
        parts.append(f"\n## 4-HOUR CANDLES\nUnavailable: {exc}")

    # 6) Daily klines (last 30 days) — higher-timeframe trend context
    try:
        thirty_days_ago = now_ms - (30 * 24 * 60 * 60 * 1000)
        recent_1d = get_bybit_klines(
            symbol, "D", thirty_days_ago, now_ms,
            cache=cache, limiter=limiter, circuit_breaker=circuit_breaker,
            api_key=api_key, api_secret=api_secret,
        )
        parts.append(f"\n## DAILY CANDLES (last ~30 days){_ptag('D')}")
        parts.append(recent_1d)
    except Exception as exc:
        parts.append(f"\n## DAILY CANDLES\nUnavailable: {exc}")

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
    if cache is not None and combined_cache_key in cache:
        return cache[combined_cache_key]

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
