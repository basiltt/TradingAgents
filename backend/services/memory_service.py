"""Memory service — parses trading_memory.md with cache — TASK-006."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from tradingagents.agents.utils.memory import TradingMemoryLog

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, memory_path: str = "~/.tradingagents/memory/trading_memory.md"):
        self._path = os.path.expanduser(memory_path)
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._cache_mtime: float = 0.0

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.isfile(self._path):
            return []

        mtime = os.path.getmtime(self._path)
        if self._cache is not None and mtime == self._cache_mtime:
            return self._cache

        log = TradingMemoryLog({"memory_log_path": self._path})
        raw_entries = log.load_entries()

        entries: List[Dict[str, Any]] = []
        for e in raw_entries:
            entries.append({
                "ticker": e.get("ticker", ""),
                "date": e.get("date", ""),
                "decision": e.get("rating", ""),
                "confidence": "pending" if e.get("pending") else (e.get("raw") or "resolved"),
                "status": "pending" if e.get("pending") else "resolved",
                "reasoning": e.get("decision", "") or None,
            })

        self._cache = entries
        self._cache_mtime = mtime
        return entries

    def get_entries(
        self, page: int = 1, limit: int = 50
    ) -> Dict[str, Any]:
        entries = self._load()
        total = len(entries)
        start = (page - 1) * limit
        end = start + limit
        return {
            "items": entries[start:end],
            "total": total,
            "page": page,
            "limit": limit,
        }
