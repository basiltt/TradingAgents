"""CoinGecko data access for crypto fundamentals and community metrics.

Supports optional Demo API key via COINGECKO_API_KEY env var.
Rate-limited to 30 req/min by default (free tier allows 30 req/min).

ALL outbound HTTP requests to CoinGecko go through the central semaphore
and rate limiter — no direct _SESSION.get() calls are allowed outside
the gated helpers.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json"})

# Support CoinGecko Demo API key for a dedicated rate-limit bucket
_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
if _API_KEY:
    _SESSION.headers.update({"x-cg-demo-api-key": _API_KEY})
    _BASE = "https://api.coingecko.com/api/v3"
    logger.info("CoinGecko: using Demo API key")
else:
    _BASE = "https://api.coingecko.com/api/v3"
    logger.info("CoinGecko: no API key, using public rate limits")


# ---------------------------------------------------------------------------
# Central rate limiter & concurrency gate — ALL CoinGecko HTTP requests
# (including coin list refresh) MUST go through these.
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Token-bucket rate limiter that enforces max requests per sliding 60s window."""

    def __init__(self, max_per_min: int = 10):
        self._lock = threading.Lock()
        self._timestamps: list[float] = []
        self._max = max_per_min

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                self._timestamps = [t for t in self._timestamps if now - t < 60]
                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return
                sleep_for = 60 - (now - self._timestamps[0]) + 0.1
            time.sleep(sleep_for)


_limiter = _RateLimiter(max_per_min=30)

_coingecko_semaphore = threading.Semaphore(2)
_coingecko_sem_lock = threading.Lock()


def configure_coingecko_concurrency(max_concurrent: int) -> None:
    global _coingecko_semaphore
    with _coingecko_sem_lock:
        _coingecko_semaphore = threading.Semaphore(max_concurrent)
    logger.info("CoinGecko concurrency limit set to %d", max_concurrent)


def configure_coingecko_rate_limit(max_per_min: int) -> None:
    global _limiter
    _limiter = _RateLimiter(max_per_min=max_per_min)
    logger.info("CoinGecko rate limit set to %d req/min", max_per_min)


def _gated_get(url: str, params: dict | None = None, timeout: int = 20) -> requests.Response:
    """Single choke-point for ALL CoinGecko HTTP requests.

    Acquires the concurrency semaphore and waits on the rate limiter
    before issuing the request. Every caller MUST use this instead of
    _SESSION.get() directly.
    """
    _coingecko_semaphore.acquire()
    try:
        _limiter.wait()
        return _SESSION.get(url, params=params, timeout=timeout)
    except Exception:
        raise
    finally:
        _coingecko_semaphore.release()


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 600  # 10 min


def _cached_get(url: str, params: dict | None = None) -> dict:
    import json as _json

    key = url + (_json.dumps(params, sort_keys=True) if params else "")
    with _cache_lock:
        if key in _cache and (time.time() - _cache[key][0]) < _CACHE_TTL:
            return _json.loads(_cache[key][1])

    max_retries = 3
    for attempt in range(max_retries):
        resp = _gated_get(url, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            wait_time = max(retry_after, 60) + (attempt * 30)
            logger.warning(
                "CoinGecko 429 rate limited, waiting %ds (attempt %d/%d)",
                wait_time, attempt + 1, max_retries,
            )
            time.sleep(wait_time)
            continue
        resp.raise_for_status()
        data = resp.json()
        with _cache_lock:
            _cache[key] = (time.time(), _json.dumps(data))
        return data

    resp.raise_for_status()
    return {}  # unreachable but satisfies type checker


# ---------------------------------------------------------------------------
# Symbol mapping  BTCUSDT -> bitcoin (CoinGecko slug)
# ---------------------------------------------------------------------------

_coin_list_cache: dict[str, str] = {}
_coin_list_lock = threading.Lock()
_coin_list_ts: float = 0.0
_COIN_LIST_TTL = 3600 * 6  # refresh every 6 hours


def _fetch_coin_list() -> dict[str, str]:
    """Return {SYMBOL_UPPER: coingecko_id} mapping."""
    resp = _gated_get(f"{_BASE}/coins/list", timeout=15)
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
    with _coin_list_lock:
        if not _coin_list_cache or (time.time() - _coin_list_ts > _COIN_LIST_TTL):
            try:
                new_map = _fetch_coin_list()
                _coin_list_cache.clear()
                _coin_list_cache.update(new_map)
                _coin_list_ts = time.time()
                logger.info("CoinGecko coin list refreshed: %d entries", len(_coin_list_cache))
            except Exception:
                logger.warning("Failed to refresh CoinGecko coin list")
                if not _coin_list_cache:
                    return None

    sym = symbol.upper()
    for suffix in ("PERP", "USDT", "USD"):
        if sym.endswith(suffix):
            sym = sym[:-len(suffix)]
            break
    if not sym:
        sym = symbol.upper()

    return _coin_list_cache.get(sym)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_coingecko_market_data(symbol: str) -> str:
    """Fetch market data: market cap, volume, supply, ATH/ATL, price changes."""
    coin_id = _get_coin_id(symbol)
    if not coin_id:
        return f"Could not resolve CoinGecko ID for symbol '{symbol}'"

    data = _cached_get(
        f"{_BASE}/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        },
    )

    md = data.get("market_data", {})
    lines = [
        f"# {data.get('name', symbol)} ({data.get('symbol', '').upper()}) — Market Fundamentals",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Market Cap Rank | #{data.get('market_cap_rank', 'N/A')} |",
        f"| Market Cap (USD) | ${md.get('market_cap', {}).get('usd', 'N/A'):,} |" if isinstance(md.get('market_cap', {}).get('usd'), (int, float)) else "| Market Cap (USD) | N/A |",
        f"| 24h Volume (USD) | ${md.get('total_volume', {}).get('usd', 'N/A'):,} |" if isinstance(md.get('total_volume', {}).get('usd'), (int, float)) else "| 24h Volume (USD) | N/A |",
        f"| Current Price (USD) | ${md.get('current_price', {}).get('usd', 'N/A')} |",
        f"| Circulating Supply | {md.get('circulating_supply', 'N/A'):,} |" if isinstance(md.get('circulating_supply'), (int, float)) else "| Circulating Supply | N/A |",
        f"| Total Supply | {md.get('total_supply', 'N/A'):,} |" if isinstance(md.get('total_supply'), (int, float)) else "| Total Supply | N/A |",
        f"| Max Supply | {md.get('max_supply', 'N/A'):,} |" if isinstance(md.get('max_supply'), (int, float)) else "| Max Supply | N/A |",
        f"| ATH (USD) | ${md.get('ath', {}).get('usd', 'N/A')} |",
        f"| ATH Change % | {md.get('ath_change_percentage', {}).get('usd', 'N/A')}% |",
        f"| ATL (USD) | ${md.get('atl', {}).get('usd', 'N/A')} |",
        "",
        "## Price Changes",
        "| Period | Change % |",
        "|--------|----------|",
        f"| 24h | {md.get('price_change_percentage_24h', 'N/A')}% |",
        f"| 7d | {md.get('price_change_percentage_7d', 'N/A')}% |",
        f"| 14d | {md.get('price_change_percentage_14d', 'N/A')}% |",
        f"| 30d | {md.get('price_change_percentage_30d', 'N/A')}% |",
        f"| 60d | {md.get('price_change_percentage_60d', 'N/A')}% |",
        f"| 200d | {md.get('price_change_percentage_200d', 'N/A')}% |",
        f"| 1y | {md.get('price_change_percentage_1y', 'N/A')}% |",
        "",
        "## Fully Diluted Valuation",
        f"FDV (USD): ${md.get('fully_diluted_valuation', {}).get('usd', 'N/A'):,}" if isinstance(md.get('fully_diluted_valuation', {}).get('usd'), (int, float)) else "FDV (USD): N/A",
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
        f"{_BASE}/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "false",
            "community_data": "true",
            "developer_data": "true",
            "sparkline": "false",
        },
    )

    cd = data.get("community_data", {})
    dd = data.get("developer_data", {})
    sent = data.get("sentiment_votes_up_percentage", "N/A")
    sent_down = data.get("sentiment_votes_down_percentage", "N/A")

    lines = [
        f"# {data.get('name', symbol)} ({data.get('symbol', '').upper()}) — Community & Social Metrics",
        "",
        "## Community",
        "| Platform | Metric | Value |",
        "|----------|--------|-------|",
        f"| Twitter/X | Followers | {cd.get('twitter_followers', 'N/A'):,} |" if isinstance(cd.get('twitter_followers'), (int, float)) else "| Twitter/X | Followers | N/A |",
        f"| Reddit | Subscribers | {cd.get('reddit_subscribers', 'N/A'):,} |" if isinstance(cd.get('reddit_subscribers'), (int, float)) else "| Reddit | Subscribers | N/A |",
        f"| Reddit | Active Users (48h) | {cd.get('reddit_accounts_active_48h', 'N/A'):,} |" if isinstance(cd.get('reddit_accounts_active_48h'), (int, float)) else "| Reddit | Active Users (48h) | N/A |",
        f"| Reddit | Avg Posts (48h) | {cd.get('reddit_average_posts_48h', 'N/A')} |",
        f"| Reddit | Avg Comments (48h) | {cd.get('reddit_average_comments_48h', 'N/A')} |",
        f"| Telegram | Members | {cd.get('telegram_channel_user_count', 'N/A'):,} |" if isinstance(cd.get('telegram_channel_user_count'), (int, float)) else "| Telegram | Members | N/A |",
        "",
        "## Sentiment",
        f"- Bullish: {sent}%",
        f"- Bearish: {sent_down}%",
        "",
        "## Developer Activity",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Forks | {dd.get('forks', 'N/A')} |",
        f"| Stars | {dd.get('stars', 'N/A')} |",
        f"| Subscribers | {dd.get('subscribers', 'N/A')} |",
        f"| Total Issues | {dd.get('total_issues', 'N/A')} |",
        f"| Closed Issues | {dd.get('closed_issues', 'N/A')} |",
        f"| PR Merged (4w) | {dd.get('pull_requests_merged', 'N/A')} |",
        f"| PR Contributors (4w) | {dd.get('pull_request_contributors', 'N/A')} |",
        f"| Commit Count (4w) | {dd.get('commit_count_4_weeks', 'N/A')} |",
    ]

    code_changes = dd.get("code_additions_deletions_4_weeks", {})
    if code_changes:
        lines += [
            f"| Code Additions (4w) | {code_changes.get('additions', 'N/A')} |",
            f"| Code Deletions (4w) | {code_changes.get('deletions', 'N/A')} |",
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

    This is a lighter version that skips price changes (computed from Bybit klines)
    and current price/volume (from Bybit ticker). Saves CoinGecko rate limit budget.
    """
    coin_id = _get_coin_id(symbol)
    if not coin_id:
        return f"Could not resolve CoinGecko ID for symbol '{symbol}'"

    data = _cached_get(
        f"{_BASE}/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        },
    )

    md = data.get("market_data", {})
    lines = [
        f"# {data.get('name', symbol)} ({data.get('symbol', '').upper()}) — Fundamentals (CoinGecko)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Market Cap Rank | #{data.get('market_cap_rank', 'N/A')} |",
        f"| Market Cap (USD) | ${md.get('market_cap', {}).get('usd', 'N/A'):,} |" if isinstance(md.get('market_cap', {}).get('usd'), (int, float)) else "| Market Cap (USD) | N/A |",
        f"| Circulating Supply | {md.get('circulating_supply', 'N/A'):,} |" if isinstance(md.get('circulating_supply'), (int, float)) else "| Circulating Supply | N/A |",
        f"| Total Supply | {md.get('total_supply', 'N/A'):,} |" if isinstance(md.get('total_supply'), (int, float)) else "| Total Supply | N/A |",
        f"| Max Supply | {md.get('max_supply', 'N/A'):,} |" if isinstance(md.get('max_supply'), (int, float)) else "| Max Supply | N/A |",
        f"| ATH (USD) | ${md.get('ath', {}).get('usd', 'N/A')} |",
        f"| ATH Change % | {md.get('ath_change_percentage', {}).get('usd', 'N/A')}% |",
        f"| ATL (USD) | ${md.get('atl', {}).get('usd', 'N/A')} |",
        f"| ATL Change % | {md.get('atl_change_percentage', {}).get('usd', 'N/A')}% |",
        f"| FDV (USD) | ${md.get('fully_diluted_valuation', {}).get('usd', 'N/A'):,} |" if isinstance(md.get('fully_diluted_valuation', {}).get('usd'), (int, float)) else "| FDV (USD) | N/A |",
    ]

    desc = data.get("description", {}).get("en", "")
    if desc:
        short = desc[:500] + ("..." if len(desc) > 500 else "")
        lines += ["", "## Project Description", short]

    categories = data.get("categories", [])
    if categories:
        lines += ["", f"**Categories:** {', '.join(c for c in categories if c)}"]

    return "\n".join(lines)
