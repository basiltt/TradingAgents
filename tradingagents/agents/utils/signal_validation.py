"""Signal validation for crypto trader output (TASK-010)."""

from __future__ import annotations

import json
import re

SIGNAL_SCHEMA = {
    "type": "object",
    "required": ["trade_type", "entry_price", "stop_losses", "take_profits", "confidence", "leverage"],
    "properties": {
        "trade_type": {"type": "string", "enum": ["Long", "Short", "No Trade"]},
        "entry_price": {"type": ["number", "null"]},
        "stop_losses": {"type": ["array", "null"], "items": {"type": "number"}},
        "take_profits": {"type": ["array", "null"], "items": {"type": "number"}},
        "confidence": {"type": "integer", "minimum": 1, "maximum": 10},
        "leverage": {"type": "integer", "minimum": 1},
    },
}


def validate_signal(signal: dict, max_leverage: int = 20) -> tuple[bool, list[str]]:
    errors: list[str] = []

    trade_type = signal.get("trade_type")
    if trade_type not in ("Long", "Short", "No Trade"):
        errors.append(f"Invalid trade_type: {trade_type}")
        return False, errors

    confidence = signal.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 1 or confidence > 10:
        errors.append(f"Confidence must be in [1, 10], got {confidence}")

    leverage = signal.get("leverage")
    if not isinstance(leverage, (int, float)) or leverage < 1 or leverage > max_leverage:
        errors.append(f"Leverage must be in [1, {max_leverage}], got {leverage}")

    if trade_type == "No Trade":
        return len(errors) == 0, errors

    entry = signal.get("entry_price")
    sls = signal.get("stop_losses") or []
    tps = signal.get("take_profits") or []

    if entry is None:
        errors.append("entry_price required for Long/Short")
        return False, errors

    if trade_type == "Long":
        for sl in sls:
            if sl >= entry:
                errors.append(f"Long: stop_loss {sl} must be < entry {entry}")
        for tp in tps:
            if tp <= entry:
                errors.append(f"Long: take_profit {tp} must be > entry {entry}")

    elif trade_type == "Short":
        for sl in sls:
            if sl <= entry:
                errors.append(f"Short: stop_loss {sl} must be > entry {entry}")
        for tp in tps:
            if tp >= entry:
                errors.append(f"Short: take_profit {tp} must be < entry {entry}")

    return len(errors) == 0, errors


def parse_signal_from_llm_output(text: str) -> dict:
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    candidates = []
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
        try:
            obj = json.loads(m.group())
            candidates.append(obj)
        except json.JSONDecodeError:
            continue

    if not candidates:
        return {}
    return max(candidates, key=lambda c: len(c))
