"""Shared utilities for the web backend."""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_SECRET_SUBSTRINGS = frozenset({"api_key", "secret", "token", "password"})


def mask_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """Replace values of secret-bearing keys with '***'.

    Args:
        config: Dictionary of configuration key-value pairs.

    Returns:
        New dictionary with secret values masked.
    """
    return {
        k: "***" if any(s in k.lower() for s in _SECRET_SUBSTRINGS) and isinstance(v, str) and v else v
        for k, v in config.items()
    }


def serialize_trade(trade: dict) -> dict:
    """Serialize a trade record for JSON responses.

    Converts UUID, datetime, and Decimal fields to JSON-safe types
    and parses stringified metadata.
    """
    out = dict(trade)
    for k, v in out.items():
        if isinstance(v, _uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
    if isinstance(out.get("metadata"), str):
        try:
            out["metadata"] = json.loads(out["metadata"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("invalid_trade_metadata", extra={"trade_id": out.get("id")})
            out["metadata"] = {}
    return out


def validate_trade_id(trade_id: str) -> None:
    """Validate that trade_id is a valid UUID, raise HTTPException(400) if not."""
    try:
        _uuid.UUID(trade_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid trade ID format") from None
