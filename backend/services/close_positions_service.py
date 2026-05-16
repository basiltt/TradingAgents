"""Service for closing positions and managing conditional close rules."""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

from backend.services.bybit_client import BybitAPIError

logger = logging.getLogger(__name__)

MAX_RULES_PER_ACCOUNT = 10
CLOSE_RATE_LIMIT = 10  # max concurrent close orders


class ClosePositionsService:
    def __init__(self, db: Any, accounts_service: Any, ws_manager: Any = None, trade_service: Any = None):
        self._db = db
        self._accounts_service = accounts_service
        self._ws_manager = ws_manager
        self._trade_service = trade_service
        self._closing_accounts: set[str] = set()

    def set_trade_service(self, trade_service: Any) -> None:
        self._trade_service = trade_service

    async def close_all_positions(self, account_id: str) -> dict[str, Any]:
        if account_id in self._closing_accounts:
            raise ValueError("Close already in progress for this account")
        self._closing_accounts.add(account_id)
        t0 = time.monotonic()
        logger.info("close_all_positions_start", extra={"account_id": account_id})

        try:
            client = await self._accounts_service.get_client(account_id)
            positions = await client.get_positions()
            if not positions:
                execution = await self._db.insert_close_execution(
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

            semaphore = asyncio.Semaphore(CLOSE_RATE_LIMIT)

            async def close_one(pos: dict) -> dict:
                async with semaphore:
                    try:
                        result = await client.place_market_close_order(
                            symbol=pos["symbol"],
                            side=pos["side"],
                            qty=pos["size"],
                            position_idx=pos.get("positionIdx", 0),
                        )
                        return {
                            "symbol": pos["symbol"],
                            "side": pos["side"],
                            "status": "closed",
                            "orderId": result.get("orderId", ""),
                            "avgPrice": result.get("avgPrice"),
                            "cumExecFee": result.get("cumExecFee"),
                            "cumExecQty": result.get("cumExecQty"),
                        }
                    except BybitAPIError as e:
                        logger.warning("Failed to close %s: %s", pos["symbol"], e.ret_msg)
                        return {
                            "symbol": pos["symbol"],
                            "side": pos["side"],
                            "status": "failed",
                            "error": f"Order rejected (code {e.ret_code})",
                        }
                    except Exception as e:
                        logger.warning("Failed to close %s: %s", pos["symbol"], e)
                        return {
                            "symbol": pos["symbol"],
                            "side": pos["side"],
                            "status": "failed",
                            "error": "Connection error",
                        }

            results = await asyncio.gather(*[close_one(p) for p in positions])

            closed = sum(1 for r in results if r["status"] == "closed")
            failed = sum(1 for r in results if r["status"] == "failed")

            await self._close_matching_trades(account_id, positions, results, "manual_close_all")

            execution = await self._db.insert_close_execution(
                {
                    "account_id": account_id,
                    "trigger_source": "manual",
                    "total_positions": len(positions),
                    "closed_count": closed,
                    "failed_count": failed,
                    "results": results,
                },
            )

            self._accounts_service.invalidate_cache(account_id)
            if self._trade_service:
                self._trade_service._invalidate_stats_cache(account_id)

            await self._broadcast_close_event(account_id, "manual", closed, failed, len(positions))
            logger.info("close_all_positions_done", extra={"account_id": account_id, "total": len(positions), "closed": closed, "failed": failed, "elapsed_ms": int((time.monotonic() - t0) * 1000)})

            return {
                "total": len(positions),
                "closed": closed,
                "failed": failed,
                "results": results,
                "execution_id": execution["id"],
            }
        finally:
            self._closing_accounts.discard(account_id)

    async def close_all_for_rule(self, account_id: str, rule_id: str | None, *, symbols: list[str] | None = None) -> dict[str, Any]:
        """Close positions triggered by a rule or cycle stop. If symbols is provided, only close those symbols."""
        if account_id in self._closing_accounts:
            logger.info("Skipping rule close for %s — close already in progress", account_id)
            return {"total": 0, "closed": 0, "failed": 0, "results": [], "skipped": True}
        self._closing_accounts.add(account_id)
        t0 = time.monotonic()

        try:
            client = await self._accounts_service.get_client(account_id)
            positions = await client.get_positions()

            if symbols:
                symbol_set = set(symbols)
                positions = [p for p in positions if p["symbol"] in symbol_set]

            if not positions:
                await self._db.insert_close_execution(
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

            semaphore = asyncio.Semaphore(CLOSE_RATE_LIMIT)

            async def close_one(pos: dict) -> dict:
                async with semaphore:
                    try:
                        result = await client.place_market_close_order(
                            symbol=pos["symbol"],
                            side=pos["side"],
                            qty=pos["size"],
                            position_idx=pos.get("positionIdx", 0),
                        )
                        return {
                            "symbol": pos["symbol"], "side": pos["side"], "status": "closed",
                            "orderId": result.get("orderId", ""),
                            "avgPrice": result.get("avgPrice"),
                            "cumExecFee": result.get("cumExecFee"),
                            "cumExecQty": result.get("cumExecQty"),
                        }
                    except BybitAPIError as e:
                        logger.warning("rule_close_bybit_error", extra={"symbol": pos["symbol"], "ret_code": e.ret_code})
                        return {"symbol": pos["symbol"], "side": pos["side"], "status": "failed", "error": f"Order rejected (code {e.ret_code})"}
                    except Exception as e:
                        logger.warning("rule_close_position_failed", extra={"symbol": pos["symbol"], "error": str(e)[:200]})
                        return {"symbol": pos["symbol"], "side": pos["side"], "status": "failed", "error": "Connection error"}

            results = await asyncio.gather(*[close_one(p) for p in positions])
            closed = sum(1 for r in results if r["status"] == "closed")
            failed = sum(1 for r in results if r["status"] == "failed")

            await self._close_matching_trades(account_id, positions, results, "rule_triggered", rule_id=rule_id)

            await self._db.insert_close_execution(
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

            self._accounts_service.invalidate_cache(account_id)

            await self._broadcast_close_event(account_id, "rule", closed, failed, len(positions))
            logger.info("close_all_for_rule_done", extra={"account_id": account_id, "rule_id": rule_id, "total": len(positions), "closed": closed, "failed": failed, "elapsed_ms": int((time.monotonic() - t0) * 1000)})

            return {"total": len(positions), "closed": closed, "failed": failed, "results": results}
        finally:
            self._closing_accounts.discard(account_id)

    # ── Trade record integration ────────────────────────────────

    async def _close_matching_trades(
        self, account_id: str, positions: list[dict], results: list[dict],
        close_reason: str, rule_id: str | None = None,
    ) -> None:
        if not self._trade_service:
            return
        closed_pairs = {
            (r["symbol"], r["side"]): r for r in results if r["status"] == "closed"
        }
        if not closed_pairs:
            return
        try:
            open_trades = await self._trade_service.get_open_trades(account_id, limit=500)
            for trade in open_trades:
                key = (trade["symbol"], trade["side"])
                if key in closed_pairs:
                    exchange_result = closed_pairs[key]
                    try:
                        await self._trade_service.close_trade_record_only(
                            account_id=account_id,
                            trade_id=str(trade["id"]),
                            close_reason=close_reason,
                            close_rule_id=rule_id,
                            exchange_result=exchange_result,
                        )
                    except Exception:
                        logger.warning("failed_to_close_trade_record", extra={
                            "trade_id": str(trade["id"]), "symbol": trade["symbol"],
                        })
        except Exception:
            logger.exception("close_matching_trades_failed", extra={"account_id": account_id})

    # ── WebSocket broadcast ────────────────────────────────────

    async def _broadcast_close_event(self, account_id: str, source: str, closed: int, failed: int, total: int) -> None:
        if not self._ws_manager:
            return
        await self._ws_manager.broadcast_to_account(account_id, "close_execution", {
            "trigger_source": source, "closed": closed, "failed": failed, "total": total,
        })

    # ── Rule CRUD ────────────────────────────────────────────────

    async def create_rule(self, account_id: str, rule_data: dict) -> dict:
        account = await self._db.get_account(account_id)
        if not account:
            raise ValueError("Account not found")

        count = await self._db.count_rules_for_account(account_id)
        if count >= MAX_RULES_PER_ACCOUNT:
            raise ValueError(f"Maximum {MAX_RULES_PER_ACCOUNT} rules per account")

        trigger_type = rule_data["trigger_type"]
        threshold = rule_data["threshold_value"]
        reference = rule_data.get("reference_value")

        if trigger_type in ("EQUITY_DROP_PCT", "EQUITY_RISE_PCT") and not reference:
            wallet = await self._accounts_service.get_wallet(account_id)
            reference = wallet.get("totalEquity", "0")
            if not reference or Decimal(reference) <= 0:
                raise ValueError("Cannot create percentage rule: current equity is zero or unavailable")

        if Decimal(threshold) <= 0:
            raise ValueError("threshold_value must be positive")

        row = await self._db.insert_close_rule(
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
        return await self._db.list_close_rules(account_id)

    async def update_rule(self, account_id: str, rule_id: str, data: dict) -> dict | None:
        rule = await self._db.get_close_rule(rule_id)
        if not rule or rule["account_id"] != account_id:
            return None

        if rule["status"] in ("triggered", "executed", "expired"):
            raise ValueError(f"Cannot update rule in '{rule['status']}' state")

        fields = {}
        if data.get("trigger_type") is not None:
            fields["trigger_type"] = data["trigger_type"]
        if data.get("threshold_value") is not None:
            fields["threshold_value"] = data["threshold_value"]
        if data.get("reference_value") is not None:
            fields["reference_value"] = data["reference_value"]
        if data.get("status") is not None:
            allowed_statuses = {"active", "paused"}
            if data["status"] not in allowed_statuses:
                raise ValueError(f"Status must be one of: {', '.join(sorted(allowed_statuses))}")
            fields["status"] = data["status"]

        new_type = fields.get("trigger_type", rule["trigger_type"])
        pct_types = {"EQUITY_DROP_PCT", "EQUITY_RISE_PCT"}

        effective_threshold = fields.get("threshold_value", rule["threshold_value"])
        if new_type in pct_types and Decimal(effective_threshold) > Decimal("100"):
            raise ValueError("Percentage threshold must be between 0.01 and 100")

        if new_type in pct_types and "reference_value" not in fields:
            old_type = rule["trigger_type"]
            if old_type not in pct_types or "trigger_type" in fields:
                wallet = await self._accounts_service.get_wallet(account_id)
                fields["reference_value"] = wallet.get("totalEquity", "0")

        if not fields:
            return rule
        return await self._db.update_close_rule(rule_id, **fields)

    async def delete_rule(self, account_id: str, rule_id: str) -> bool:
        rule = await self._db.get_close_rule(rule_id)
        if not rule or rule["account_id"] != account_id:
            return False
        return await self._db.delete_close_rule(rule_id)

    async def list_executions(self, account_id: str, page: int = 1, limit: int = 20) -> dict:
        return await self._db.list_close_executions(account_id, page, limit)
