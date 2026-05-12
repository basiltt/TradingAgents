"""Strategy management service — CRUD for trading strategies."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.async_persistence import AsyncAnalysisDB

logger = logging.getLogger(__name__)


class StrategyService:
    def __init__(self, db: AsyncAnalysisDB):
        self._db = db

    def _serialize_datetimes(self, strategy: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("created_at", "updated_at"):
            val = strategy.get(key)
            if val and not isinstance(val, str):
                strategy[key] = val.isoformat()
        return strategy

    async def create_strategy(self, data: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        strategy = {
            "id": str(uuid.uuid4()),
            "name": data["name"],
            "description": data["description"],
            "category": data["category"],
            "status": data["status"],
            "config": data["config"],
            "created_at": now,
            "updated_at": now,
        }
        await self._db.insert_strategy(strategy)
        logger.info("Strategy created: %s (%s)", strategy["id"], strategy["name"])
        return strategy

    async def list_strategies(
        self, status: Optional[str] = None, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        rows = await self._db.list_strategies(status=status, category=category)
        return [self._serialize_datetimes(r) for r in rows]

    async def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        row = await self._db.get_strategy(strategy_id)
        return self._serialize_datetimes(row) if row else None

    async def update_strategy(self, strategy_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not data:
            return await self.get_strategy(strategy_id)
        ok = await self._db.update_strategy(strategy_id, **data)
        if not ok:
            return None
        return await self.get_strategy(strategy_id)

    async def delete_strategy(self, strategy_id: str) -> bool:
        ok = await self._db.delete_strategy(strategy_id)
        if ok:
            logger.info("Strategy deleted: %s", strategy_id)
        return ok

    async def import_strategies(self, strategies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        imported = []
        for s in strategies:
            s.pop("id", None)
            s.pop("created_at", None)
            s.pop("updated_at", None)
            imported.append(await self.create_strategy(s))
        return imported
