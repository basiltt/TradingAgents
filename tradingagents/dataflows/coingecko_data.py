"""CoinGecko data access for crypto fundamentals and community metrics.

Supports Demo and Basic (Pro) API plans via COINGECKO_PLAN env var.
Lazy-configured on first API call via _ensure_configured().

ALL outbound HTTP requests to CoinGecko go through the central semaphore
and rate limiter — no direct _SESSION.get() calls are allowed outside
the gated helpers.
"""

from __future__ import annotations

import copy
import json as _json
import logging
import os
import threading
import time
import requests

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json"})

# ---------------------------------------------------------------------------
# Tier configuration — lazy-initialized by _ensure_configured()
# ---------------------------------------------------------------------------

_TIER_DEFAULTS = {
    "demo":  {"base": "https://api.coingecko.com/api/v3",     "auth": "header", "rpm": 30,  "concurrency": 2},
    "basic": {"base": "https://pro-api.coingecko.com/api/v3", "auth": "param",  "rpm": 300, "concurrency": 5},
}

_configured = False
_configure_lock = threading.Lock()
_plan: str = "demo"
_BASE: str = "https://api.coingecko.com/api/v3"
_API_KEY: str = ""
_AUTH_MODE: str | None = None


# ---------------------------------------------------------------------------
# Central rate limiter & concurrency gate
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Token-bucket rate limiter that enforces max requests per sliding 60s window."""

    def __init__(self, max_per_min: int = 10):
        self._lock = threading.Lock()
        self._timestamps: list[float] = []
        self._max = max_per_min

    @property
    def rpm(self) -> int:
        return self._max

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                self._timestamps = [t for t in self._timestamps if now - t < 60]
                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return
                sleep_for = 60 - (now - self._timestamps[0]) + 0.1
            logger.warning("CoinGecko rate limit: sleeping %.1fs", sleep_for)
            time.sleep(sleep_for)


_limiter = _RateLimiter(max_per_min=30)
_coingecko_semaphore = threading.Semaphore(2)


def _configure() -> None:
    global _plan, _BASE, _API_KEY, _AUTH_MODE, _limiter, _coingecko_semaphore

    _API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
    explicit_plan = os.environ.get("COINGECKO_PLAN", "")

    if explicit_plan:
        _plan = explicit_plan.lower()
    else:
        _plan = "demo"

    if _plan not in _TIER_DEFAULTS:
        raise ValueError(f"Invalid COINGECKO_PLAN: {_plan!r}. Must be one of: demo, basic")

    if _plan == "basic" and not _API_KEY:
        logger.warning("COINGECKO_PLAN=basic but no COINGECKO_API_KEY set — falling back to demo plan (30 RPM)")
        _plan = "demo"

    tier = _TIER_DEFAULTS[_plan]
    _BASE = str(tier["base"])
    _AUTH_MODE = str(tier["auth"]) if _API_KEY else None

    rpm = int(os.environ.get("COINGECKO_RATE_LIMIT_RPM",
              os.environ.get("COINGECKO_MAX_PER_MIN", str(tier["rpm"]))))
    concurrency = int(os.environ.get("COINGECKO_MAX_CONCURRENT", str(tier["concurrency"])))

    _limiter = _RateLimiter(max_per_min=rpm)
    _coingecko_semaphore = threading.Semaphore(concurrency)

    if _AUTH_MODE == "header":
        _SESSION.headers.update({"x-cg-demo-api-key": _API_KEY})

    logger.info("CoinGecko: plan=%s base=%s rpm=%d concurrency=%d key=%s",
                _plan, _BASE, rpm, concurrency, "****" + _API_KEY[-4:] if _API_KEY else "none")


def _ensure_configured() -> None:
    global _configured
    if _configured:
        return
    with _configure_lock:
        if _configured:
            return
        _configure()
        _configured = True


def _gated_get(path: str, params: dict | None = None, timeout: int = 20) -> requests.Response:
    """Single choke-point for ALL CoinGecko HTTP requests."""
    _ensure_configured()
    url = f"{_BASE}{path}"
    if _AUTH_MODE == "param" and _API_KEY:
        params = dict(params or {})
        params["x_cg_pro_api_key"] = _API_KEY
    sem = _coingecko_semaphore
    sem.acquire()
    try:
        _limiter.wait()
        return _SESSION.get(url, params=params, timeout=timeout)
    finally:
        sem.release()


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict | list]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 600  # 10 min
_CACHE_MAX = 1000
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _cached_get(path: str, params: dict | None = None) -> dict | list:
    key = path + (_json.dumps(params, sort_keys=True) if params else "")
    with _cache_lock:
        if key in _cache and (time.time() - _cache[key][0]) < _CACHE_TTL:
            return copy.deepcopy(_cache[key][1])

    max_retries = 3
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = _gated_get(path, params=params)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            wait_time = 10 + (attempt * 15)
            logger.warning(
                "CoinGecko connection error on %s, waiting %ds (attempt %d/%d): %s",
                path, wait_time, attempt + 1, max_retries, exc,
            )
            time.sleep(wait_time)
            continue

        if resp.status_code in _RETRYABLE_STATUS:
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                wait_time = max(retry_after, 60) + (attempt * 30)
            else:
                wait_time = 10 + (attempt * 15)
            logger.warning(
                "CoinGecko %d on %s, waiting %ds (attempt %d/%d)",
                resp.status_code, path, wait_time, attempt + 1, max_retries,
            )
            time.sleep(wait_time)
            continue

        resp.raise_for_status()
        data = resp.json()
        with _cache_lock:
            _cache[key] = (time.time(), copy.deepcopy(data))
            _evict_oldest(_cache, _CACHE_MAX)
        return data

    if last_exc:
        raise last_exc
    resp.raise_for_status()
    return {}


# ---------------------------------------------------------------------------
# Symbol mapping  BTCUSDT -> bitcoin (CoinGecko slug)
# ---------------------------------------------------------------------------

_coin_list_cache: dict[str, str] = {}
_coin_list_lock = threading.Lock()
_coin_list_ts: float = 0.0
_COIN_LIST_TTL = 3600 * 6  # refresh every 6 hours


def _fetch_coin_list() -> dict[str, str]:
    """Return {SYMBOL_UPPER: coingecko_id} mapping."""
    resp = _gated_get("/coins/list", timeout=15)
    resp.raise_for_status()
    mapping: dict[str, str] = {}
    for coin in resp.json():
        sym = coin.get("symbol", "").upper()
        cid = coin.get("id", "")
        if sym and cid:
            if sym not in mapping:
                mapping[sym] = cid
    return mapping


def _get_coin_id(symbol: str) -> str | None:
    """Convert a trading symbol like BTCUSDT to a CoinGecko id like 'bitcoin'."""
    global _coin_list_ts
    needs_refresh = False
    with _coin_list_lock:
        needs_refresh = not _coin_list_cache or (time.time() - _coin_list_ts > _COIN_LIST_TTL)

    if needs_refresh:
        try:
            new_map = _fetch_coin_list()
            with _coin_list_lock:
                _coin_list_cache.clear()
                _coin_list_cache.update(new_map)
                _coin_list_ts = time.time()
            logger.info("CoinGecko coin list refreshed: %d entries", len(new_map))
        except Exception:
            logger.warning("Failed to refresh CoinGecko coin list")
            with _coin_list_lock:
                if not _coin_list_cache:
                    return None

    sym = symbol.upper()
    for suffix in ("PERP", "USDT", "USD"):
        if sym.endswith(suffix):
            sym = sym[:-len(suffix)]
            break
    if not sym:
        sym = symbol.upper()

    with _coin_list_lock:
        return _coin_list_cache.get(sym)


# ---------------------------------------------------------------------------
# Bulk market data & description caches
# ---------------------------------------------------------------------------

_bulk_cache: dict[str, tuple[float, dict]] = {}
_bulk_cache_lock = threading.Lock()
_BULK_CACHE_TTL = 7200  # 2 hours — must outlast a full scan round
_BULK_CACHE_MAX = 1000

_desc_cache: dict[str, tuple[float, str, list[str]]] = {}
_desc_cache_lock = threading.Lock()
_DESC_CACHE_TTL = 86400  # 24 hours
_DESC_CACHE_MAX = 1000


def _evict_oldest(cache: dict, max_size: int) -> None:
    """Evict oldest entries to bring cache under max_size (batch for O(n) amortized)."""
    if len(cache) <= max_size:
        return
    evict_count = max(len(cache) - max_size, max_size // 10)
    by_ts = sorted(cache, key=lambda k: cache[k][0])
    for key in by_ts[:evict_count]:
        del cache[key]


def _normalize_bulk_to_coin_format(bulk_item: dict) -> dict:
    """Map flat /coins/markets response to nested /coins/{id} format."""
    def _num(val):
        return val if val is not None else 0

    def _pct(period: str):
        """Extract price change % from bulk response — flat for 24h, nested for others."""
        if period == "24h":
            return bulk_item.get("price_change_percentage_24h")
        nested = bulk_item.get(f"price_change_percentage_{period}_in_currency")
        if isinstance(nested, dict):
            return nested.get("usd")
        return bulk_item.get(f"price_change_percentage_{period}")

    return {
        "name": bulk_item.get("name", ""),
        "symbol": bulk_item.get("symbol", ""),
        "market_cap_rank": bulk_item.get("market_cap_rank"),
        "market_data": {
            "market_cap": {"usd": _num(bulk_item.get("market_cap"))},
            "total_volume": {"usd": _num(bulk_item.get("total_volume"))},
            "current_price": {"usd": bulk_item.get("current_price")},
            "circulating_supply": _num(bulk_item.get("circulating_supply")),
            "total_supply": _num(bulk_item.get("total_supply")),
            "max_supply": bulk_item.get("max_supply"),
            "ath": {"usd": bulk_item.get("ath")},
            "ath_change_percentage": {"usd": bulk_item.get("ath_change_percentage")},
            "atl": {"usd": bulk_item.get("atl")},
            "atl_change_percentage": {"usd": bulk_item.get("atl_change_percentage")},
            "fully_diluted_valuation": {"usd": bulk_item.get("fully_diluted_valuation")},
            "price_change_percentage_1h": _pct("1h"),
            "price_change_percentage_24h": _pct("24h"),
            "price_change_percentage_7d": _pct("7d"),
            "price_change_percentage_14d": _pct("14d"),
            "price_change_percentage_30d": _pct("30d"),
            "price_change_percentage_200d": _pct("200d"),
            "price_change_percentage_1y": _pct("1y"),
            "high_24h": {"usd": bulk_item.get("high_24h")},
            "low_24h": {"usd": bulk_item.get("low_24h")},
            "price_change_24h": bulk_item.get("price_change_24h"),
            "market_cap_change_24h": bulk_item.get("market_cap_change_24h"),
            "market_cap_change_percentage_24h": bulk_item.get("market_cap_change_percentage_24h"),
        },
    }


def get_bulk_market_data(coin_ids: list[str]) -> dict[str, dict]:
    """Fetch market data for up to 250 coins per API call via /coins/markets."""
    _ensure_configured()
    result: dict[str, dict] = {}
    for i in range(0, len(coin_ids), 250):
        chunk = coin_ids[i:i + 250]
        items = _cached_get(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": ",".join(chunk),
                "per_page": "250",
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d,14d,30d,200d,1y",
            },
        )
        for item in items:
            cid = item.get("id")
            if cid:
                normalized = _normalize_bulk_to_coin_format(item)
                result[cid] = normalized
                with _bulk_cache_lock:
                    _bulk_cache[cid] = (time.time(), copy.deepcopy(normalized))
                    _evict_oldest(_bulk_cache, _BULK_CACHE_MAX)
    return result


def _get_description_and_categories(coin_id: str) -> tuple[str, list[str]]:
    """Fetch and cache description/categories for a coin (24h TTL)."""
    with _desc_cache_lock:
        entry = _desc_cache.get(coin_id)
        if entry and (time.time() - entry[0]) < _DESC_CACHE_TTL:
            return entry[1], entry[2]

    data = _cached_get(
        f"/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "false",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        },
    )
    assert isinstance(data, dict)
    desc = data.get("description", {}).get("en", "")
    categories = data.get("categories", []) or []

    with _desc_cache_lock:
        _desc_cache[coin_id] = (time.time(), desc, categories)
        _evict_oldest(_desc_cache, _DESC_CACHE_MAX)

    return desc, categories


def prefetch_fundamentals(symbols: list[str]) -> None:
    """Bulk-fetch market data + descriptions for a list of symbols before analysis."""
    valid_ids = _resolve_coin_ids(symbols)
    if not valid_ids:
        return

    get_bulk_market_data(valid_ids)

    desc_misses = 0
    for cid in valid_ids:
        with _desc_cache_lock:
            entry = _desc_cache.get(cid)
        if not entry or (time.time() - entry[0]) >= _DESC_CACHE_TTL:
            _get_description_and_categories(cid)
            desc_misses += 1

    logger.info("Prefetched %d/%d coins (bulk), %d desc cache misses",
                len(valid_ids), len(symbols), desc_misses)


def _resolve_coin_ids(symbols: list[str]) -> list[str]:
    """Deduplicate and resolve symbol list to CoinGecko IDs."""
    _ensure_configured()
    seen: set[str] = set()
    valid_ids: list[str] = []
    for sym in symbols:
        cid = _get_coin_id(sym)
        if cid and cid not in seen:
            valid_ids.append(cid)
            seen.add(cid)
    return valid_ids


def prefetch_bulk_market_only(symbols: list[str]) -> None:
    """Fetch only bulk market data (fast: ~3 API calls for 558 coins)."""
    valid_ids = _resolve_coin_ids(symbols)
    if valid_ids:
        get_bulk_market_data(valid_ids)
        logger.info("Bulk market prefetch done for %d/%d coins", len(valid_ids), len(symbols))


def prefetch_descriptions_background(symbols: list[str]) -> None:
    """Fetch per-coin descriptions (slow). Safe to run in background thread."""
    try:
        valid_ids = _resolve_coin_ids(symbols)
    except Exception:
        logger.warning("Background desc prefetch: failed to resolve coin IDs")
        return
    desc_misses = 0
    for cid in valid_ids:
        with _desc_cache_lock:
            entry = _desc_cache.get(cid)
        if not entry or (time.time() - entry[0]) >= _DESC_CACHE_TTL:
            try:
                _get_description_and_categories(cid)
                desc_misses += 1
            except Exception:
                logger.debug("Background desc fetch failed for %s", cid)
    logger.info("Background desc prefetch done: %d cache misses filled", desc_misses)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def _usd(nested: dict, fallback: str = "N/A"):
    """Extract USD value from nested CoinGecko dict, returning fallback for None."""
    val = nested.get("usd")
    return val if val is not None else fallback


def _val(v, fallback: str = "N/A"):
    """Return v unless it is None, in which case return fallback."""
    return v if v is not None else fallback

def get_coingecko_market_data(symbol: str) -> str:
    """Fetch market data: market cap, volume, supply, ATH/ATL, price changes.

    NOTE: Not used in the crypto graph — the crypto_fundamentals analyst calls
    get_coingecko_fundamentals_only (CoinGecko) + get_bybit_price_changes (Bybit)
    instead.  Kept for standalone/API usage and potential stock-crypto convergence.
    """
    coin_id = _get_coin_id(symbol)
    if not coin_id:
        return f"Could not resolve CoinGecko ID for symbol '{symbol}'"

    data = _cached_get(
        f"/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        },
    )
    assert isinstance(data, dict)

    md = data.get("market_data", {})
    lines = [
        f"# {data.get('name', symbol)} ({data.get('symbol', '').upper()}) — Market Fundamentals",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Market Cap Rank | #{data.get('market_cap_rank', 'N/A')} |",
        f"| Market Cap (USD) | ${_usd(md.get('market_cap', {})):,} |" if isinstance(_usd(md.get('market_cap', {})), (int, float)) else "| Market Cap (USD) | N/A |",
        f"| 24h Volume (USD) | ${_usd(md.get('total_volume', {})):,} |" if isinstance(_usd(md.get('total_volume', {})), (int, float)) else "| 24h Volume (USD) | N/A |",
        f"| Current Price (USD) | ${_usd(md.get('current_price', {}))} |",
        f"| Circulating Supply | {md.get('circulating_supply', 'N/A'):,} |" if isinstance(md.get('circulating_supply'), (int, float)) else "| Circulating Supply | N/A |",
        f"| Total Supply | {md.get('total_supply', 'N/A'):,} |" if isinstance(md.get('total_supply'), (int, float)) else "| Total Supply | N/A |",
        f"| Max Supply | {md.get('max_supply', 'N/A'):,} |" if isinstance(md.get('max_supply'), (int, float)) else "| Max Supply | N/A |",
        f"| ATH (USD) | ${_usd(md.get('ath', {}))} |",
        f"| ATH Change % | {_usd(md.get('ath_change_percentage', {}))}% |",
        f"| ATL (USD) | ${_usd(md.get('atl', {}))} |",
        "",
        "## Price Changes",
        "| Period | Change % |",
        "|--------|----------|",
        f"| 1h | {_val(md.get('price_change_percentage_1h'))}% |",
        f"| 24h | {_val(md.get('price_change_percentage_24h'))}% |",
        f"| 7d | {_val(md.get('price_change_percentage_7d'))}% |",
        f"| 14d | {_val(md.get('price_change_percentage_14d'))}% |",
        f"| 30d | {_val(md.get('price_change_percentage_30d'))}% |",
        f"| 200d | {_val(md.get('price_change_percentage_200d'))}% |",
        f"| 1y | {_val(md.get('price_change_percentage_1y'))}% |",
        "",
        "## Fully Diluted Valuation",
        f"FDV (USD): ${_usd(md.get('fully_diluted_valuation', {})):,}" if isinstance(_usd(md.get('fully_diluted_valuation', {})), (int, float)) else "FDV (USD): N/A",
    ]

    desc = data.get("description", {}).get("en", "")
    if desc:
        short = desc[:500] + ("..." if len(desc) > 500 else "")
        lines += ["", "## Project Description", short]

    categories = data.get("categories", [])
    if categories:
        lines += ["", f"**Categories:** {', '.join(c for c in categories if c)}"]

    return "\n".join(lines)


def get_coingecko_community_data(symbol: str) -> str:
    """Fetch community and developer metrics."""
    coin_id = _get_coin_id(symbol)
    if not coin_id:
        return f"Could not resolve CoinGecko ID for symbol '{symbol}'"

    data = _cached_get(
        f"/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "false",
            "community_data": "true",
            "developer_data": "true",
            "sparkline": "false",
        },
    )
    assert isinstance(data, dict)

    cd = data.get("community_data", {})
    dd = data.get("developer_data", {})
    sent = _val(data.get("sentiment_votes_up_percentage"))
    sent_down = _val(data.get("sentiment_votes_down_percentage"))

    lines = [
        f"# {data.get('name', symbol)} ({data.get('symbol', '').upper()}) — Community & Social Metrics",
        "",
        "## Community",
        "| Platform | Metric | Value |",
        "|----------|--------|-------|",
        f"| Twitter/X | Followers | {cd.get('twitter_followers', 'N/A'):,} |" if isinstance(cd.get('twitter_followers'), (int, float)) else "| Twitter/X | Followers | N/A |",
        f"| Reddit | Subscribers | {cd.get('reddit_subscribers', 'N/A'):,} |" if isinstance(cd.get('reddit_subscribers'), (int, float)) else "| Reddit | Subscribers | N/A |",
        f"| Reddit | Active Users (48h) | {cd.get('reddit_accounts_active_48h', 'N/A'):,} |" if isinstance(cd.get('reddit_accounts_active_48h'), (int, float)) else "| Reddit | Active Users (48h) | N/A |",
        f"| Reddit | Avg Posts (48h) | {_val(cd.get('reddit_average_posts_48h'))} |",
        f"| Reddit | Avg Comments (48h) | {_val(cd.get('reddit_average_comments_48h'))} |",
        f"| Telegram | Members | {cd.get('telegram_channel_user_count', 'N/A'):,} |" if isinstance(cd.get('telegram_channel_user_count'), (int, float)) else "| Telegram | Members | N/A |",
        f"| Facebook | Likes | {cd.get('facebook_likes', 'N/A'):,} |" if isinstance(cd.get('facebook_likes'), (int, float)) else "| Facebook | Likes | N/A |",
        "",
        "## Sentiment",
        f"- Bullish: {sent}%",
        f"- Bearish: {sent_down}%",
        "",
        "## Developer Activity",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Forks | {_val(dd.get('forks'))} |",
        f"| Stars | {_val(dd.get('stars'))} |",
        f"| Subscribers | {_val(dd.get('subscribers'))} |",
        f"| Total Issues | {_val(dd.get('total_issues'))} |",
        f"| Closed Issues | {_val(dd.get('closed_issues'))} |",
        f"| PR Merged (4w) | {_val(dd.get('pull_requests_merged'))} |",
        f"| PR Contributors (4w) | {_val(dd.get('pull_request_contributors'))} |",
        f"| Commit Count (4w) | {_val(dd.get('commit_count_4_weeks'))} |",
    ]

    code_changes = dd.get("code_additions_deletions_4_weeks") or {}
    if code_changes:
        lines += [
            f"| Code Additions (4w) | {_val(code_changes.get('additions'))} |",
            f"| Code Deletions (4w) | {_val(code_changes.get('deletions'))} |",
        ]

    links = data.get("links", {})
    homepage = links.get("homepage", [])
    repos = links.get("repos_url", {}).get("github", [])
    if homepage and homepage[0]:
        lines += ["", f"**Website:** {homepage[0]}"]
    if repos and repos[0]:
        lines += [f"**GitHub:** {repos[0]}"]

    return "\n".join(lines)


def get_coingecko_fundamentals_only(symbol: str) -> str:
    """Fetch ONLY data that Bybit cannot provide: market cap, supply, ATH/ATL, FDV, description.

    Uses bulk cache if available (populated by prefetch_fundamentals), otherwise
    falls back to individual /coins/{id} call.
    """
    coin_id = _get_coin_id(symbol)
    if not coin_id:
        return f"Could not resolve CoinGecko ID for symbol '{symbol}'"

    with _bulk_cache_lock:
        entry = _bulk_cache.get(coin_id)
    data: dict | list
    if entry and (time.time() - entry[0]) < _BULK_CACHE_TTL:
        data = copy.deepcopy(entry[1])
    else:
        data = _cached_get(
            f"/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )
    assert isinstance(data, dict)

    try:
        desc, categories = _get_description_and_categories(coin_id)
    except Exception as exc:
        logger.warning("Failed to fetch description for %s: %s", coin_id, exc)
        desc, categories = "", []
    data.setdefault("description", {})["en"] = desc
    data["categories"] = categories

    md = data.get("market_data", {})
    lines = [
        f"# {data.get('name', symbol)} ({data.get('symbol', '').upper()}) — Fundamentals (CoinGecko)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Market Cap Rank | #{data.get('market_cap_rank', 'N/A')} |",
        f"| Market Cap (USD) | ${_usd(md.get('market_cap', {})):,} |" if isinstance(_usd(md.get('market_cap', {})), (int, float)) else "| Market Cap (USD) | N/A |",
        f"| Circulating Supply | {md.get('circulating_supply', 'N/A'):,} |" if isinstance(md.get('circulating_supply'), (int, float)) else "| Circulating Supply | N/A |",
        f"| Total Supply | {md.get('total_supply', 'N/A'):,} |" if isinstance(md.get('total_supply'), (int, float)) else "| Total Supply | N/A |",
        f"| Max Supply | {md.get('max_supply', 'N/A'):,} |" if isinstance(md.get('max_supply'), (int, float)) else "| Max Supply | N/A |",
        f"| ATH (USD) | ${_usd(md.get('ath', {}))} |",
        f"| ATH Change % | {_usd(md.get('ath_change_percentage', {}))}% |",
        f"| ATL (USD) | ${_usd(md.get('atl', {}))} |",
        f"| ATL Change % | {_usd(md.get('atl_change_percentage', {}))}% |",
        f"| FDV (USD) | ${_usd(md.get('fully_diluted_valuation', {})):,} |" if isinstance(_usd(md.get('fully_diluted_valuation', {})), (int, float)) else "| FDV (USD) | N/A |",
        f"| 24h Volume (USD) | ${_usd(md.get('total_volume', {})):,} |" if isinstance(_usd(md.get('total_volume', {})), (int, float)) else "| 24h Volume (USD) | N/A |",
        f"| High 24h (USD) | ${_usd(md.get('high_24h', {}))} |",
        f"| Low 24h (USD) | ${_usd(md.get('low_24h', {}))} |",
        f"| Price Change 24h (USD) | {_val(md.get('price_change_24h'))} |",
        f"| Market Cap Change 24h | {_val(md.get('market_cap_change_24h'))} |",
        f"| Market Cap Change % 24h | {_val(md.get('market_cap_change_percentage_24h'))}% |" if md.get('market_cap_change_percentage_24h') is not None else "| Market Cap Change % 24h | N/A |",
    ]

    price_changes = {
        "1h": md.get("price_change_percentage_1h"),
        "24h": md.get("price_change_percentage_24h"),
        "7d": md.get("price_change_percentage_7d"),
        "14d": md.get("price_change_percentage_14d"),
        "30d": md.get("price_change_percentage_30d"),
        "200d": md.get("price_change_percentage_200d"),
        "1y": md.get("price_change_percentage_1y"),
    }
    if any(v is not None for v in price_changes.values()):
        lines += [
            "",
            "## Price Changes (CoinGecko)",
            "| Period | Change % |",
            "|--------|----------|",
        ]
        for period, pct in price_changes.items():
            lines.append(f"| {period} | {pct:.2f}% |" if isinstance(pct, (int, float)) else f"| {period} | N/A |")

    desc_text = data.get("description", {}).get("en", "")
    if desc_text:
        short = desc_text[:500] + ("..." if len(desc_text) > 500 else "")
        lines += ["", "## Project Description", short]

    cats = data.get("categories", [])
    if cats:
        lines += ["", f"**Categories:** {', '.join(c for c in cats if c)}"]

    return "\n".join(lines)


def get_coingecko_status() -> dict:
    """Return CoinGecko configuration status for health checks."""
    _ensure_configured()
    return {
        "plan": _plan,
        "key_configured": bool(_API_KEY),
        "rate_limit_rpm": _limiter.rpm,
    }
