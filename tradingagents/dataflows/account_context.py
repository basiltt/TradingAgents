"""Account context data: positions, wallet balance, and trade history summary.

Provides portfolio-level awareness for the Trader agent so it can factor in
existing exposure, margin utilization, and historical performance.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import logging
import time
from typing import Any

import requests

from tradingagents.dataflows.bybit_data import BYBIT_BASE_URL

logger = logging.getLogger(__name__)

_session = requests.Session()


def _signed_request(endpoint: str, params: dict, api_key: str, api_secret: str) -> dict:
    """Make authenticated GET request to Bybit V5 private API."""
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"

    sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sign_payload = f"{timestamp}{api_key}{recv_window}{sorted_params}"
    signature = hmac_mod.new(
        api_secret.encode("utf-8"),
        sign_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": signature,
        "X-BAPI-SIGN-TYPE": "2",
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
    }

    resp = _session.get(
        f"{BYBIT_BASE_URL}{endpoint}",
        params=params,
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit API error: {data.get('retMsg', 'unknown')}")
    return data.get("result", {})


def get_account_positions(api_key: str, api_secret: str) -> str:
    """Fetch all open perpetual positions formatted for LLM consumption."""
    try:
        result = _signed_request(
            "/v5/position/list",
            {"category": "linear", "settleCoin": "USDT"},
            api_key, api_secret,
        )
    except Exception as exc:
        logger.warning("Failed to fetch positions: %s", exc)
        return "Account positions unavailable."

    positions = result.get("list", [])
    active = []
    for p in positions:
        try:
            if float(p.get("size", 0)) > 0:
                active.append(p)
        except (ValueError, TypeError):
            continue
    if not active:
        return "No open positions."

    lines = ["## Current Open Positions"]
    total_unrealised = 0.0
    total_notional = 0.0
    for pos in active:
        symbol = pos.get("symbol", "?")
        side = pos.get("side", "?")
        size = pos.get("size", "0")
        entry = pos.get("avgPrice", "0")
        mark = pos.get("markPrice", "0")
        try:
            unrealised = float(pos.get("unrealisedPnl", 0))
        except (ValueError, TypeError):
            unrealised = 0.0
        leverage = pos.get("leverage", "?")
        liq_price = pos.get("liqPrice", "N/A")
        try:
            notional = float(size) * float(mark) if mark else 0
        except (ValueError, TypeError):
            notional = 0.0

        total_unrealised += unrealised
        total_notional += notional

        lines.append(
            f"- **{symbol}** {side} | Size: {size} | Entry: {entry} | "
            f"Mark: {mark} | uPnL: {unrealised:+.2f} USDT | "
            f"Leverage: {leverage}x | Liq: {liq_price}"
        )

    lines.append(f"\n**Total Unrealised PnL:** {total_unrealised:+.2f} USDT")
    lines.append(f"**Total Notional Exposure:** {total_notional:.2f} USDT")
    return "\n".join(lines)


def get_account_wallet(api_key: str, api_secret: str) -> str:
    """Fetch wallet balance summary formatted for LLM consumption."""
    try:
        result = _signed_request(
            "/v5/account/wallet-balance",
            {"accountType": "UNIFIED"},
            api_key, api_secret,
        )
    except Exception as exc:
        logger.warning("Failed to fetch wallet: %s", exc)
        return "Wallet data unavailable."

    accounts = result.get("list", [])
    if not accounts:
        return "Wallet data unavailable."

    acct = accounts[0]
    equity = acct.get("totalEquity", "0")
    wallet_bal = acct.get("totalWalletBalance", "0")
    available = acct.get("totalAvailableBalance", "0")
    margin_used = acct.get("totalInitialMargin", "0")
    unrealised = acct.get("totalPerpUPL", "0")

    margin_ratio = ""
    try:
        if float(equity) > 0 and float(margin_used) > 0:
            ratio = float(margin_used) / float(equity) * 100
            margin_ratio = f" ({ratio:.1f}% utilised)"
    except (ValueError, TypeError):
        pass

    return (
        f"## Account Wallet\n"
        f"- **Equity:** {equity} USDT\n"
        f"- **Wallet Balance:** {wallet_bal} USDT\n"
        f"- **Available Balance:** {available} USDT\n"
        f"- **Margin Used:** {margin_used} USDT{margin_ratio}\n"
        f"- **Unrealised PnL:** {unrealised} USDT"
    )


def get_account_state(api_key: str, api_secret: str) -> str:
    """Combined account state: wallet + positions."""
    wallet = get_account_wallet(api_key, api_secret)
    positions = get_account_positions(api_key, api_secret)
    return f"{wallet}\n\n{positions}"


def get_trade_history_summary(
    trades: list[dict[str, Any]],
    symbol: str | None = None,
    lookback_days: int = 30,
) -> str:
    """Summarise recent trade performance for LLM context.

    Args:
        trades: List of executed trade dicts with keys: symbol, side, pnl,
                closed_at (or timestamp), entry_price, exit_price
        symbol: If provided, filter to this symbol only
        lookback_days: How far back to look
    """
    if not trades:
        return "No trade history available for performance analysis."

    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    filtered = []
    for t in trades:
        ts = t.get("closed_at") or t.get("timestamp", "")
        if isinstance(ts, str) and ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
        if symbol and t.get("symbol", "").upper() != symbol.upper():
            continue
        filtered.append(t)

    if not filtered:
        period_label = f"last {lookback_days} days"
        sym_label = f" for {symbol}" if symbol else ""
        return f"No completed trades{sym_label} in the {period_label}."

    def _pnl(t: dict) -> float:
        try:
            return float(t.get("pnl", 0))
        except (ValueError, TypeError):
            return 0.0

    wins = [t for t in filtered if _pnl(t) > 0]
    losses = [t for t in filtered if _pnl(t) < 0]
    breakeven = [t for t in filtered if _pnl(t) == 0]

    total = len(filtered)
    win_rate = len(wins) / total * 100

    avg_win = sum(_pnl(t) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(_pnl(t) for t in losses) / len(losses) if losses else 0
    total_pnl = sum(_pnl(t) for t in filtered)

    # Current streak
    streak = 0
    streak_type = "none"
    for t in reversed(filtered):
        pnl = _pnl(t)
        if streak == 0:
            streak_type = "win" if pnl > 0 else "loss"
            streak = 1
        elif (pnl > 0 and streak_type == "win") or (pnl < 0 and streak_type == "loss"):
            streak += 1
        else:
            break

    # Profit factor
    gross_profit = sum(_pnl(t) for t in wins)
    gross_loss = abs(sum(_pnl(t) for t in losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float('inf')
    else:
        profit_factor = 1.0

    sym_label = f" ({symbol})" if symbol else ""
    lines = [
        f"## Trade History{sym_label} — Last {lookback_days} Days",
        f"- **Total Trades:** {total} (Wins: {len(wins)}, Losses: {len(losses)}, BE: {len(breakeven)})",
        f"- **Win Rate:** {win_rate:.1f}%",
        f"- **Avg Win:** +{avg_win:.2f} USDT | **Avg Loss:** {avg_loss:.2f} USDT",
        f"- **Profit Factor:** {profit_factor:.2f}",
        f"- **Total PnL:** {total_pnl:+.2f} USDT",
        f"- **Current Streak:** {streak} {streak_type}{'s' if streak > 1 else ''}",
    ]

    if avg_loss != 0:
        rr_ratio = abs(avg_win / avg_loss)
        lines.append(f"- **Avg Risk/Reward:** {rr_ratio:.2f}")

    return "\n".join(lines)
