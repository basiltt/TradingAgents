"""Information barrier enforcement via state read/write filtering."""

from __future__ import annotations

import copy
import logging

from tradingagents.agents.constants import READABLE_KEYS, WRITABLE_KEYS
from tradingagents.config.feature_flags import is_enabled

logger = logging.getLogger(__name__)


def filter_state_for_read(state: dict, role: str) -> dict:
    if not is_enabled("use_information_barriers"):
        return state
    if role not in READABLE_KEYS:
        logger.error("Unknown role '%s' — returning empty state (fail-closed)", role)
        return {}
    allowed = READABLE_KEYS[role]
    return {
        k: copy.deepcopy(v) if isinstance(v, (dict, list)) else v
        for k, v in state.items()
        if k in allowed
    }


def validate_state_write(updates: dict, role: str) -> dict:
    if not is_enabled("use_information_barriers"):
        return updates
    if role not in WRITABLE_KEYS:
        logger.error("Unknown role '%s' — dropping all writes (fail-closed)", role)
        return {}
    allowed = WRITABLE_KEYS[role]
    violations = set(updates.keys()) - set(allowed)
    if violations:
        sanitized = {repr(k)[:64] for k in list(violations)[:10]}
        logger.error("Role %s attempted to write disallowed keys: %s", role, sanitized)
    return {k: v for k, v in updates.items() if k in allowed}
