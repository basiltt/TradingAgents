"""CoinGecko free-tier data access for crypto fundamentals and community metrics.

No API key required.  Rate-limited to stay within the public tier (30 req/min, using 25 with safety margin).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json"})

_BASE = "https://api.coingecko.com/api/v3"

# ---------------------------------------------------------------------------
# Symbol mapping  BTCUSDT → bitcoin (CoinGecko slug)
# ---------------------------------------------------------------------------

_coin_list_cache: dict[str, str] = {}
_coin_list_lock = threading.Lock()
_coin_list_ts: float = 0.0
_COIN_LIST_TTL = 3600 * 6  # refresh every 6 hours


def _fetch_coin_list() -> dict[str, str]:
    """Return {SYMBOL_UPPER: coingecko_id} mapping."""
    resp = _SESSION.get(f"{_BASE}/coins/list", timeout=15)
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
                _coin_list_cache.clear()
                _coin_list_cache.update(_fetch_coin_list())
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
# Rate limiter (simple token-bucket, shared across calls)
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, max_per_min: int = 10):
        self._lock = threading.Lock()
        self._timestamps: list[float] = []
        self._max = max_per_min

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) >= self._max:
                sleep_for = 60 - (now - self._timestamps[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
            self._timestamps.append(time.time())


_limiter = _RateLimiter(max_per_min=25)

_coingecko_semaphore = threading.Semaphore(25)
_coingecko_sem_lock = threading.Lock()


def configure_coingecko_concurrency(max_concurrent: int) -> None:
    global _coingecko_semaphore
    with _coingecko_sem_lock:
        _coingecko_semaphore = threading.Semaphore(max_concurrent)
    logger.info("CoinGecko concurrency limit set to %d", max_concurrent)

# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 300  # 5 min


def _cached_get(url: str, params: dict | None = None) -> dict:
    import json as _json

    key = url + (_json.dumps(params, sort_keys=True) if params else "")
    with _cache_lock:
        if key in _cache and (time.time() - _cache[key][0]) < _CACHE_TTL:
            return _json.loads(_cache[key][1])

    _coingecko_semaphore.acquire()
    try:
        # Re-check cache after acquiring semaphore (another thread may have fetched)
        with _cache_lock:
            if key in _cache and (time.time() - _cache[key][0]) < _CACHE_TTL:
                return _json.loads(_cache[key][1])

        _limiter.wait()
        resp = _SESSION.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        with _cache_lock:
            _cache[key] = (time.time(), _json.dumps(data))
        return data
    finally:
        _coingecko_semaphore.release()


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
