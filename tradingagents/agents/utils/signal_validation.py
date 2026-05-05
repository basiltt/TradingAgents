"""Signal validation for crypto trader output (TASK-010)."""

from __future__ import annotations

import json
import math
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


def validate_signal(
    signal: dict,
    max_leverage: int = 20,
    current_price: float | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    trade_type = signal.get("trade_type")
    if trade_type not in ("Long", "Short", "No Trade"):
        errors.append(f"Invalid trade_type: {trade_type}")
        return False, errors

    confidence = signal.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or math.isnan(confidence) or confidence < 1 or confidence > 10:
        errors.append(f"Confidence must be in [1, 10], got {confidence}")

    leverage = signal.get("leverage")
    if not isinstance(leverage, (int, float)) or isinstance(leverage, bool) or math.isnan(leverage) or leverage < 1 or leverage > max_leverage:
        errors.append(f"Leverage must be in [1, {max_leverage}], got {leverage}")
    elif isinstance(leverage, float) and leverage != int(leverage):
        errors.append(f"Leverage must be a whole number, got {leverage}")

    if trade_type == "No Trade":
        return len(errors) == 0, errors

    entry = signal.get("entry_price")
    sls = signal.get("stop_losses") or []
    tps = signal.get("take_profits") or []

    if entry is None:
        errors.append("entry_price required for Long/Short")
        return False, errors

    if not isinstance(entry, (int, float)) or isinstance(entry, bool) or math.isnan(entry) or entry <= 0:
        errors.append(f"entry_price must be a positive number, got {entry}")
        return False, errors

    def _is_valid_num(v: object) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(v)

    if not sls:
        errors.append("At least one stop_loss required for Long/Short")
    elif not all(_is_valid_num(s) for s in sls):
        errors.append("All stop_loss values must be numbers")
        sls = [s for s in sls if _is_valid_num(s)]

    if not tps:
        errors.append("At least one take_profit required for Long/Short")
    elif not all(_is_valid_num(t) for t in tps):
        errors.append("All take_profit values must be numbers")
        tps = [t for t in tps if _is_valid_num(t)]

    if current_price is not None and current_price > 0:
        deviation = abs(entry - current_price) / current_price
        if deviation > 0.02:
            errors.append(
                f"entry_price {entry} deviates {deviation:.1%} from current price {current_price}; "
                f"must be within 2%"
            )

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

    # Catch objectively bad setups without biasing toward no-trade
    if sls and tps:
        closest_sl = min(abs(sl - entry) for sl in sls)
        closest_tp = min(abs(tp - entry) for tp in tps)
        # R:R below 0.5 is a genuinely bad setup regardless of strategy
        if closest_sl > 0 and closest_tp / closest_sl < 0.5:
            errors.append(
                f"Risk:reward ratio {closest_tp / closest_sl:.2f} is below 0.5; "
                f"TP distance must be at least half of SL distance"
            )
        # SL more than 10% from entry is dangerously wide for leveraged futures
        if entry > 0 and closest_sl / entry > 0.10:
            errors.append(
                f"Stop-loss distance {closest_sl / entry:.1%} exceeds 10% of entry — "
                f"too wide for leveraged futures"
            )

    # High leverage with low confidence is reckless
    if (
        isinstance(leverage, (int, float))
        and isinstance(confidence, (int, float))
        and not isinstance(leverage, bool)
        and not isinstance(confidence, bool)
        and leverage > 10
        and confidence < 5
    ):
        errors.append(
            f"Leverage {leverage}x with confidence {confidence}/10 is excessive; "
            f"leverage above 10x requires confidence >= 5"
        )

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
    signal_keys = {"trade_type", "entry_price", "stop_losses", "take_profits", "confidence", "leverage"}
    scored = [(len(signal_keys & c.keys()), len(c), c) for c in candidates]
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]


def extract_current_price(price_context: str) -> float | None:
    """Extract last-traded price from the price context string."""
    for pattern in (
        r"Last\s*(?:Traded)?\s*Price[:\s]*\$?([\d,]+\.?\d*)",
        r"lastPrice[\"']?\s*[:=]\s*[\"']?([\d,]+\.?\d*)",
        r"Last\s*Price[:\s]*([\d,]+\.?\d*)",
    ):
        m = re.search(pattern, price_context, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None
