"""AI Manager Memory System — Phase 3 Task 3.3.

Provides episodic context (recent decisions) and semantic patterns for LLM prompt assembly.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from backend.services.ai_manager_prompts import sanitize_for_injection

if TYPE_CHECKING:
    from backend.services.ai_manager_repository import AIManagerRepository

logger = logging.getLogger(__name__)


class AIManagerMemory:
    """Provides episodic and semantic memory context for AI decision prompts.

    Episodic memory: recent decisions (action, outcome) for short-term context.
    Semantic memory: extracted trading patterns (up to 50) for long-term learning.
    Pattern extraction is performed via LLM when sufficient new decisions accumulate.
    """

    def __init__(self, repo: "AIManagerRepository"):
        self._repo = repo

    async def get_episodic_context(self, account_id: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Summarized recent decisions: action, symbol, confidence, outcome_label only."""
        rows = await self._repo.get_recent_decisions(account_id, limit=limit)
        return [
            {
                "action": (row.get("action_taken") or {}).get("action", "HOLD") if isinstance(row.get("action_taken"), dict) else "HOLD",
                "symbol": (row.get("action_taken") or {}).get("symbol", "") if isinstance(row.get("action_taken"), dict) else "",
                "confidence": row.get("confidence", 0.0),
                "outcome_label": row.get("outcome_label", "unknown"),
            }
            for row in rows
        ]

    async def get_semantic_patterns(self, account_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Active patterns sorted by confidence, max 200 chars each."""
        rows = await self._repo.get_patterns(account_id, active=True, limit=limit)
        return [
            {
                "type": row.get("pattern_type", ""),
                "symbol": row.get("symbol", ""),
                "description": (row.get("description", "") or "")[:200],
                "confidence": row.get("confidence", 0.5),
            }
            for row in rows
        ]

    async def get_decision_count(self, account_id: str) -> int:
        """Count total decisions for cold-start detection."""
        return await self._repo.count_decisions(account_id)

    async def generate_patterns(
        self,
        account_id: str,
        llm_callable: Optional[Callable] = None,
    ) -> int:
        """Generate patterns from recent decisions. 50-cap, advisory lock, sanitize→truncate.

        Returns number of patterns generated.
        """
        if not llm_callable:
            return 0

        async def _do_generate(acct_id, conn):
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM ai_manager_patterns "
                "WHERE account_id = $1 AND active = TRUE", acct_id
            )
            active_count = row["cnt"]
            if active_count >= 50:
                await conn.execute(
                    "UPDATE ai_manager_patterns SET active = FALSE, updated_at = NOW() "
                    "WHERE id = (SELECT id FROM ai_manager_patterns "
                    "WHERE account_id = $1 AND active = TRUE "
                    "ORDER BY confidence ASC LIMIT 1)", acct_id
                )

            rows = await conn.fetch(
                "SELECT id, account_id, timestamp, action_taken, confidence, outcome_label "
                "FROM ai_manager_decisions "
                "WHERE account_id = $1 ORDER BY timestamp DESC LIMIT $2",
                acct_id, 50,
            )
            decisions = [dict(r) for r in rows]
            if len(decisions) < 5:
                return 0

            prompt = self._build_pattern_prompt(decisions)
            system = "You are a trading pattern analyst. Analyze decision history and extract reusable behavioral patterns. Return a JSON array of objects with: type, symbol, description, confidence."
            raw_response = await asyncio.wait_for(llm_callable(system, prompt), timeout=60.0)
            if not raw_response:
                return 0

            # Parse LLM JSON response
            try:
                text = raw_response.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                raw_patterns = _json.loads(text)
                if not isinstance(raw_patterns, list):
                    return 0
            except (_json.JSONDecodeError, ValueError):
                return 0

            generated = 0
            for pat in raw_patterns[:10]:
                description = sanitize_for_injection(str(pat.get("description", "")), max_len=200)
                if not description:
                    continue
                await conn.execute(
                    "INSERT INTO ai_manager_patterns "
                    "(account_id, pattern_type, symbol, description, confidence, active) "
                    "VALUES ($1, $2, $3, $4, $5, TRUE)",
                    acct_id,
                    str(pat.get("type", "behavioral"))[:50],
                    str(pat.get("symbol", ""))[:50],
                    description,
                    max(0.0, min(1.0, float(pat.get("confidence", 0.5)))),
                )
                generated += 1

            return generated

        return await self._repo.generate_patterns_locked(account_id, _do_generate)

    def _build_pattern_prompt(self, decisions: List[Dict[str, Any]]) -> str:
        lines = ["Analyze these trading decisions and identify behavioral patterns:"]
        for d in decisions[:30]:
            action = (d.get("action_taken") or {}).get("action", "?")
            symbol = (d.get("action_taken") or {}).get("symbol", "?")
            outcome = d.get("outcome_label", "?")
            lines.append(f"  {action} {symbol} → {outcome}")
        lines.append("\nReturn JSON array of patterns with: type, symbol, description, confidence")
        return "\n".join(lines)
