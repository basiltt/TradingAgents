"""AI Manager Prompt Assembly — Phase 3 Task 3.2.

Builds system and context prompts for the LLM decision call.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

_INJECTION_PATTERNS = re.compile(
    r"("
    r"system\s*:"
    r"|<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>"
    r"|<\|assistant\|>|<\|user\|>|<\|system\|>"
    r"|\n\nHuman:|\n\nAssistant:"
    r"|\[INST\]|\[/INST\]"
    r"|<s>|</s>|<<SYS>>|<</SYS>>"
    r"|###\s*Instruction:|###\s*Response:"
    r"|<tool_call>|<function_call>"
    r")",
    re.IGNORECASE,
)

_HTML_TAGS = re.compile(r"<[^>]+>")

_VALID_REGIMES = frozenset(["trending_up", "trending_down", "ranging", "volatile"])
_VALID_SESSIONS = frozenset(["asia", "europe", "us", "overlap"])

_MAX_FIELD_LEN = 200

_RISK_TOLERANCE_MAP = {
    "conservative": {"confidence_boost": 0.1, "loss_sensitivity": 1.5},
    "moderate": {"confidence_boost": 0.0, "loss_sensitivity": 1.0},
    "aggressive": {"confidence_boost": -0.05, "loss_sensitivity": 0.7},
}


def sanitize_for_injection(text: str, max_len: int = 0) -> str:
    """NFC-normalize, strip injection patterns, remove non-printable chars."""
    if not text:
        return ""
    if max_len > 0:
        text = text[:max_len]
    text = unicodedata.normalize("NFC", text)
    text = _INJECTION_PATTERNS.sub("", text)
    text = "".join(c for c in text if c.isprintable() or c in ("\n", "\t"))
    return text.strip()


def sanitize_llm_output(text: str) -> str:
    """Strip HTML/script tags from LLM reasoning before persistence."""
    if not text:
        return ""
    return _HTML_TAGS.sub("", text).strip()


def validate_regime(regime: str) -> str:
    """Validate market regime, default to 'ranging' on invalid."""
    if regime and regime.lower() in _VALID_REGIMES:
        return regime.lower()
    return "ranging"


def validate_market_session(session: str) -> str:
    """Validate market session, default to 'unknown' on invalid."""
    if session and session.lower() in _VALID_SESSIONS:
        return session.lower()
    return "unknown"


def truncate_to_token_budget(prompt: str, max_tokens: int = 4000) -> str:
    """Approximate token truncation (4 chars per token estimate)."""
    max_chars = max_tokens * 4
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars]


def build_system_prompt(
    risk_tolerance: str = "moderate",
    cold_start: bool = False,
    daily_profit_target_pct: Optional[float] = None,
) -> str:
    """Build immutable system prompt for AI Manager LLM call."""
    risk_params = _RISK_TOLERANCE_MAP.get(risk_tolerance, _RISK_TOLERANCE_MAP["moderate"])

    prompt = (
        "You are an AI trading position manager. Your primary goal is to MAXIMIZE daily profit "
        "while protecting capital from excessive drawdowns.\n\n"
        "## Decision Framework\n"
        "Evaluate each open position and decide: HOLD, FULL_CLOSE, or PARTIAL_CLOSE.\n\n"
        "## When to CLOSE (high confidence required):\n"
        "1. **Trend Reversal**: Price action, moving averages, or momentum indicators confirm "
        "the trend has reversed against the position direction.\n"
        "2. **Profit Preservation**: Position reached a significant profit peak but is now "
        "declining. If drawdown-from-peak exceeds 30-50% of peak profit, consider closing "
        "to preserve gains rather than risk giving them back.\n"
        "3. **Abnormal Market Conditions**: Sudden volatility spikes, funding rate flips, "
        "or volume anomalies that signal unpredictable price movement.\n"
        "4. **Adverse Momentum**: PnL velocity is strongly negative and accelerating.\n"
        "5. **Risk-Reward Deterioration**: The remaining upside potential is poor relative "
        "to the downside risk given current market structure.\n\n"
        "## When to HOLD:\n"
        "- Trend is intact and aligned with position direction\n"
        "- Normal market fluctuations within expected range\n"
        "- Position is young and hasn't had time to develop\n"
        "- No clear reversal signals present\n\n"
        "## Key Principles:\n"
        "- You can only act on ONE position per evaluation. Choose the most urgent one.\n"
        "- Never recommend actions on symbols not in the position list.\n"
        "- Consider the account's recent decision history and learned patterns.\n"
        "- A position with high unrealized profit that starts declining is URGENT — "
        "preserving realized profit is better than hoping for more.\n"
        "- Use multi-indicator confluence: one signal alone is not enough.\n"
        f"- Risk sensitivity: {risk_params['loss_sensitivity']:.1f}x (higher = more cautious).\n"
        f"- Confidence adjustment: {risk_params['confidence_boost']:+.2f}.\n"
    )

    if daily_profit_target_pct:
        prompt += (
            f"\n## Daily Target: {daily_profit_target_pct:.1f}% of equity\n"
            "If cumulative realized profit is approaching or has reached the daily target, "
            "be more aggressive about closing remaining positions to lock in the target.\n"
        )

    if cold_start:
        prompt += (
            "\nIMPORTANT: This is a new account with limited history. "
            "Be very conservative — only act on extremely clear signals with high confluence.\n"
        )

    prompt += (
        "\nRespond ONLY with valid JSON:\n"
        '{"action": "HOLD"|"FULL_CLOSE"|"PARTIAL_CLOSE", '
        '"symbol": "<symbol or empty for HOLD>", '
        '"confidence": <0.0-1.0>, '
        '"reason": "<brief explanation>"}\n'
    )

    return prompt


def build_context_prompt(
    positions: List[Dict[str, Any]],
    wallet: Dict[str, Any],
    indicators: Optional[Dict[str, Any]] = None,
    episodic_memory: Optional[List[Dict[str, Any]]] = None,
    patterns: Optional[List[Dict[str, Any]]] = None,
    regime: str = "ranging",
    session: str = "unknown",
    peak_pnl: Optional[Dict[str, float]] = None,
    daily_realized_pnl: float = 0.0,
    daily_profit_target: Optional[float] = None,
) -> str:
    """Build user context prompt with all available data."""
    regime = validate_regime(regime)
    session = validate_market_session(session)

    parts = []

    # Market context
    parts.append(f"Market regime: {regime}")
    parts.append(f"Session: {session}")

    # Wallet
    if wallet:
        equity = wallet.get("equity", "N/A")
        available = wallet.get("available_balance", "N/A")
        parts.append(f"Equity: {equity}, Available: {available}")

    # Daily P&L progress
    if daily_profit_target and daily_profit_target > 0:
        progress_pct = (daily_realized_pnl / daily_profit_target) * 100 if daily_profit_target else 0
        parts.append(
            f"Daily realized PnL: ${daily_realized_pnl:.2f} "
            f"(target: ${daily_profit_target:.2f}, progress: {progress_pct:.0f}%)"
        )
    elif daily_realized_pnl != 0:
        parts.append(f"Daily realized PnL: ${daily_realized_pnl:.2f}")

    # Positions with drawdown-from-peak
    parts.append("\nOpen positions:")
    peak_pnl = peak_pnl or {}
    for pos in (positions or []):
        symbol = sanitize_for_injection(str(pos.get("symbol", "")), max_len=50)
        side = pos.get("side", "")
        size = pos.get("size", 0)
        avg_price = pos.get("avgPrice", pos.get("entryPrice", 0))
        unrealized_pnl = pos.get("unrealisedPnl", pos.get("unrealized_pnl", "N/A"))
        mark_price = pos.get("markPrice", "N/A")
        leverage = pos.get("leverage", "N/A")
        liq_price = pos.get("liqPrice", "")
        position_value = pos.get("positionValue", "")

        line = f"  {symbol} {side} size={size} entry={avg_price} mark={mark_price} uPnL={unrealized_pnl}"
        if leverage and leverage != "N/A" and leverage != "0":
            line += f" lev={leverage}x"
        if liq_price and liq_price != "" and liq_price != "0":
            line += f" liq={liq_price}"
        if position_value and position_value != "0":
            line += f" value=${position_value}"

        # Drawdown from peak
        peak = peak_pnl.get(symbol, 0.0)
        try:
            current_pnl = float(unrealized_pnl) if unrealized_pnl != "N/A" else 0.0
            if peak > 0 and current_pnl < peak:
                drawdown_pct = ((peak - current_pnl) / peak) * 100
                line += f" peakPnL={peak:.2f} drawdown={drawdown_pct:.0f}%"
            elif peak > 0:
                line += f" peakPnL={peak:.2f} (at/near peak)"
        except (ValueError, TypeError):
            pass

        parts.append(line)

    # Indicators (enriched)
    if indicators:
        parts.append("\nMarket indicators:")
        for sym, data in indicators.items():
            sym_clean = sanitize_for_injection(str(sym), max_len=50)
            lines = [f"  {sym_clean}:"]
            if data.get("mark_price") is not None:
                lines.append(f"    price={data['mark_price']:.4f}")
            if data.get("ema_9") is not None and data.get("ema_21") is not None:
                trend = "bullish" if data["ema_9"] > data["ema_21"] else "bearish"
                lines.append(f"    EMA9={data['ema_9']:.4f} EMA21={data['ema_21']:.4f} ({trend})")
            if data.get("rsi_14") is not None:
                lines.append(f"    RSI14={data['rsi_14']:.1f}")
            if data.get("atr_14") is not None:
                lines.append(f"    ATR14={data['atr_14']:.4f}")
            if data.get("price_24h_pct") is not None:
                lines.append(f"    24h_change={data['price_24h_pct']*100:.2f}%")
            if data.get("funding_rate") is not None:
                lines.append(f"    funding={data['funding_rate']:.6f}")
            if data.get("pnl_velocity_30s") is not None:
                lines.append(f"    pnl_velocity_30s={data['pnl_velocity_30s']:.4f}")
            if data.get("volume_24h") is not None:
                lines.append(f"    volume_24h=${data['volume_24h']:,.0f}")
            if data.get("open_interest") is not None:
                lines.append(f"    open_interest=${data['open_interest']:,.0f}")
            if data.get("ema_trend_strength") is not None:
                lines.append(f"    trend_strength={data['ema_trend_strength']:.4f}")
            parts.append("\n".join(lines))

    # Episodic memory
    if episodic_memory:
        parts.append("\nRecent decisions:")
        for mem in episodic_memory[:10]:
            action = sanitize_for_injection(str(mem.get("action", "")), max_len=20)
            symbol = sanitize_for_injection(str(mem.get("symbol", "")), max_len=50)
            outcome = mem.get("outcome_label", "unknown")
            parts.append(f"  {action} {symbol} → {outcome}")

    # Patterns
    if patterns:
        parts.append("\nLearned patterns:")
        for pat in patterns[:5]:
            desc = sanitize_for_injection(str(pat.get("description", "")), max_len=_MAX_FIELD_LEN)
            parts.append(f"  [{pat.get('type', '')}] {desc}")

    full_prompt = "\n".join(parts)
    full_prompt = _INJECTION_PATTERNS.sub("", full_prompt)

    return truncate_to_token_budget(full_prompt)
