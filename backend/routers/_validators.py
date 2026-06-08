"""Shared input validators for router endpoints."""

from __future__ import annotations

import uuid as _uuid

from fastapi import HTTPException


def validate_account_id(account_id: str) -> str:
    """Validate UUID format and return the ID, or raise HTTPException(400)."""
    try:
        _uuid.UUID(account_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail="Invalid account ID format") from None
    return account_id


def clamp_limit(value: int, lo: int, hi: int) -> int:
    """Clamp a pagination ``limit`` into ``[lo, hi]`` (equivalent to ``min(max(value, lo), hi)``)."""
    return min(max(value, lo), hi)
