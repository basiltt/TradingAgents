"""Service for closing positions and managing conditional close rules."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.services.bybit_client import BybitAPIError

logger = logging.getLogger(__name__)

MAX_RULES_PER_ACCOUNT = 10
CLOSE_RATE_LIMIT = 10  # max concurrent close orders


class ClosePositionsService:
    def __init__(self, db: Any, accounts_service: Any, ws_manager: Any = None):
        self._db = db
        self._accounts_service = accounts_service
        self._ws_manager = ws_manager
        self._closing_accounts: set[str] = set()

    async def close_all_positions(self, account_id: str) -> dict[str, Any]:
        if account_id in self._closing_accounts:
            raise ValueError("Close already in progress for this account")
        self._closing_accounts.add(account_id)

        try:
            positions = await self._accounts_service.get_positions(account_id)
            if not positions:
                execution = await asyncio.to_thread(
                    self._db.insert_close_execution,
                    {
                        "account_id": account_id,
                        "trigger_source": "manual",
                        "total_positions": 0,
                        "closed_count": 0,
                        "failed_count": 0,
                        "results": [],
                    },
                )
                return {"total": 0, "closed": 0, "failed": 0, "results": [], "execution_id": execution["id"]}

            client = await self._accounts_service._build_client(account_id)
            semaphore = asyncio.Semaphore(CLOSE_RATE_LIMIT)

            async def close_one(pos: dict) -> dict:
                async with semaphore:
                    try:
                        result = await client.place_market_close_order(
                            symbol=pos["symbol"],
                            side=pos["side"],
                            qty=pos["size"],
                        )
                        return {
                            "symbol": pos["symbol"],
                            "status": "closed",
                            "orderId": result.get("orderId", ""),
                        }
                    except BybitAPIError as e:
                        logger.warning("Failed to close %s: %s", pos["symbol"], e.ret_msg)
                        return {
                            "symbol": pos["symbol"],
                            "status": "failed",
                            "error": f"Order rejected (code {e.ret_code})",
                        }
                    except Exception as e:
                        logger.warning("Failed to close %s: %s", pos["symbol"], e)
                        return {
                            "symbol": pos["symbol"],
                            "status": "failed",
                            "error": "Connection error",
                        }

            results = await asyncio.gather(*[close_one(p) for p in positions])

            closed = sum(1 for r in results if r["status"] == "closed")
            failed = sum(1 for r in results if r["status"] == "failed")

            execution = await asyncio.to_thread(
                self._db.insert_close_execution,
                {
                    "account_id": account_id,
                    "trigger_source": "manual",
                    "total_positions": len(positions),
                    "closed_count": closed,
                    "failed_count": failed,
                    "results": results,
                },
            )

            self._accounts_service._invalidate_cache(account_id)

            await self._broadcast_close_event(account_id, "manual", closed, failed, len(positions))

            return {
                "total": len(positions),
                "closed": closed,
                "failed": failed,
                "results": results,
                "execution_id": execution["id"],
            }
        finally:
            self._closing_accounts.discard(account_id)

    async def close_all_for_rule(self, account_id: str, rule_id: str) -> dict[str, Any]:
        """Close all positions triggered by a rule. Uses same guard as manual close."""
        if account_id in self._closing_accounts:
            logger.info("Skipping rule close for %s — close already in progress", account_id)
            return {"total": 0, "closed": 0, "failed": 0, "results": [], "skipped": True}
        self._closing_accounts.add(account_id)

        try:
            positions = await self._accounts_service.get_positions(account_id)

            if not positions:
                await asyncio.to_thread(
                    self._db.insert_close_execution,
                    {
                        "account_id": account_id,
                        "rule_id": rule_id,
                        "trigger_source": "rule",
                        "total_positions": 0,
                        "closed_count": 0,
                        "failed_count": 0,
                        "results": [],
                    },
                )
                return {"total": 0, "closed": 0, "failed": 0, "results": []}

            client = await self._accounts_service._build_client(account_id)
            semaphore = asyncio.Semaphore(CLOSE_RATE_LIMIT)

            async def close_one(pos: dict) -> dict:
                async with semaphore:
                    try:
                        result = await client.place_market_close_order(
                            symbol=pos["symbol"],
                            side=pos["side"],
                            qty=pos["size"],
                        )
                        return {"symbol": pos["symbol"], "status": "closed", "orderId": result.get("orderId", "")}
                    except BybitAPIError as e:
                        return {"symbol": pos["symbol"], "status": "failed", "error": f"Order rejected (code {e.ret_code})"}
                    except Exception:
                        return {"symbol": pos["symbol"], "status": "failed", "error": "Connection error"}

            results = await asyncio.gather(*[close_one(p) for p in positions])
            closed = sum(1 for r in results if r["status"] == "closed")
            failed = sum(1 for r in results if r["status"] == "failed")

            await asyncio.to_thread(
                self._db.insert_close_execution,
                {
                    "account_id": account_id,
                    "rule_id": rule_id,
                    "trigger_source": "rule",
                    "total_positions": len(positions),
                    "closed_count": closed,
                    "failed_count": failed,
                    "results": results,
                },
            )

            self._accounts_service._invalidate_cache(account_id)

            await self._broadcast_close_event(account_id, "rule", closed, failed, len(positions))

            return {"total": len(positions), "closed": closed, "failed": failed, "results": results}
        finally:
            self._closing_accounts.discard(account_id)

    # ── WebSocket broadcast ────────────────────────────────────

    async def _broadcast_close_event(self, account_id: str, source: str, closed: int, failed: int, total: int) -> None:
        if not self._ws_manager:
            return
        await self._ws_manager.broadcast_event({
            "type": "close_execution",
            "account_id": account_id,
            "data": {"trigger_source": source, "closed": closed, "failed": failed, "total": total},
        })

    # ── Rule CRUD ────────────────────────────────────────────────

    async def create_rule(self, account_id: str, rule_data: dict) -> dict:
        account = await asyncio.to_thread(self._db.get_account, account_id)
        if not account:
            raise ValueError("Account not found")

        count = await asyncio.to_thread(self._db.count_rules_for_account, account_id)
        if count >= MAX_RULES_PER_ACCOUNT:
            raise ValueError(f"Maximum {MAX_RULES_PER_ACCOUNT} rules per account")

        trigger_type = rule_data["trigger_type"]
        threshold = rule_data["threshold_value"]
        reference = rule_data.get("reference_value")

        if trigger_type in ("EQUITY_DROP_PCT", "EQUITY_RISE_PCT") and not reference:
            wallet = await self._accounts_service.get_wallet(account_id)
            reference = wallet.get("totalEquity", "0")

        row = await asyncio.to_thread(
            self._db.insert_close_rule,
            {
                "account_id": account_id,
                "trigger_type": trigger_type,
                "threshold_value": threshold,
                "reference_value": reference,
                "status": "active",
            },
        )
        return row

    async def list_rules(self, account_id: str) -> list:
        return await asyncio.to_thread(self._db.list_close_rules, account_id)

    async def update_rule(self, account_id: str, rule_id: str, data: dict) -> dict | None:
        rule = await asyncio.to_thread(self._db.get_close_rule, rule_id)
        if not rule or rule["account_id"] != account_id:
            return None
        fields = {}
        if data.get("trigger_type") is not None:
            fields["trigger_type"] = data["trigger_type"]
        if data.get("threshold_value") is not None:
            fields["threshold_value"] = data["threshold_value"]
        if data.get("reference_value") is not None:
            fields["reference_value"] = data["reference_value"]
        if data.get("status") is not None:
            fields["status"] = data["status"]
        if not fields:
            return rule
        return await asyncio.to_thread(self._db.update_close_rule, rule_id, **fields)

    async def delete_rule(self, account_id: str, rule_id: str) -> bool:
        rule = await asyncio.to_thread(self._db.get_close_rule, rule_id)
        if not rule or rule["account_id"] != account_id:
            return False
        return await asyncio.to_thread(self._db.delete_close_rule, rule_id)

    async def list_executions(self, account_id: str, page: int = 1, limit: int = 20) -> dict:
        return await asyncio.to_thread(self._db.list_close_executions, account_id, page, limit)
