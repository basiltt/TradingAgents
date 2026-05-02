"""Memory service — parses trading_memory.md with cache — TASK-006."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ENTRY_RE = re.compile(
    r"^##\s+(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)"
)


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

        entries: List[Dict[str, Any]] = []
        current_entry: Optional[Dict[str, Any]] = None
        reasoning_lines: List[str] = []

        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                m = _ENTRY_RE.match(line)
                if m:
                    if current_entry:
                        current_entry["reasoning"] = "\n".join(reasoning_lines).strip() or None
                        entries.append(current_entry)
                    current_entry = {
                        "ticker": m.group(1),
                        "date": m.group(2),
                        "decision": m.group(3),
                        "confidence": m.group(4),
                        "status": m.group(5),
                    }
                    reasoning_lines = []
                elif current_entry is not None:
                    if line.startswith("Reasoning:"):
                        reasoning_lines.append(line[len("Reasoning:"):].strip())
                    elif line.strip():
                        reasoning_lines.append(line)

        if current_entry:
            current_entry["reasoning"] = "\n".join(reasoning_lines).strip() or None
            entries.append(current_entry)

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
