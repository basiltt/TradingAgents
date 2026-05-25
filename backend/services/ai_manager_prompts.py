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
) -> str:
    """Build immutable system prompt for AI Manager LLM call."""
    risk_params = _RISK_TOLERANCE_MAP.get(risk_tolerance, _RISK_TOLERANCE_MAP["moderate"])

    prompt = (
        "You are a trading position manager. Your role is to evaluate open positions "
        "and decide whether to HOLD, FULL_CLOSE, or PARTIAL_CLOSE each position.\n\n"
        "Rules:\n"
        "- Only recommend closing if you have high confidence in a trend reversal or abnormality.\n"
        "- Consider the account's recent history, patterns, and current market regime.\n"
        "- Never recommend actions on symbols not currently in the position list.\n"
        "- Provide a clear, concise reason for your decision.\n"
        f"- Risk sensitivity: {risk_params['loss_sensitivity']:.1f}x (higher = more cautious).\n"
        f"- Confidence adjustment: {risk_params['confidence_boost']:+.2f}.\n"
    )

    if cold_start:
        prompt += (
            "\nIMPORTANT: This is a new account with limited history. "
            "Be conservative — only act on very clear signals.\n"
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

    # Positions
    parts.append("\nOpen positions:")
    for pos in (positions or []):
        symbol = sanitize_for_injection(str(pos.get("symbol", "")), max_len=50)
        side = pos.get("side", "")
        size = pos.get("size", 0)
        avg_price = pos.get("avgPrice", 0)
        unrealized_pnl = pos.get("unrealisedPnl", pos.get("unrealized_pnl", "N/A"))
        parts.append(f"  {symbol} {side} size={size} entry={avg_price} uPnL={unrealized_pnl}")

    # Indicators
    if indicators:
        parts.append("\nIndicators:")
        for sym, data in indicators.items():
            sym_clean = sanitize_for_injection(str(sym), max_len=50)
            rsi = data.get("rsi_14", "N/A")
            atr = data.get("atr_14", "N/A")
            parts.append(f"  {sym_clean}: RSI={rsi}, ATR={atr}")

    # Episodic memory
    if episodic_memory:
        parts.append("\nRecent decisions:")
        for mem in episodic_memory[:10]:
            action = sanitize_for_injection(str(mem.get("action", "")), max_len=20)
            symbol = sanitize_for_injection(str(mem.get("symbol", "")), max_len=50)
            outcome = mem.get("outcome", "unknown")
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
