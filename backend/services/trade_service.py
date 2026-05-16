"""TradeService — orchestration layer for trade lifecycle operations."""

from __future__ import annotations

import json
import logging
import time
import uuid as _uuid
from decimal import Decimal
from typing import Any

from backend.async_persistence import AsyncAnalysisDB
from backend.utils import serialize_trade as _serialize_trade_shared
from backend.services.trade_repository import (
    ConcurrentModification,
    InvalidStatusTransition,
    TradeNotFound,
    TradeRepository,
)

logger = logging.getLogger(__name__)

VALID_SOURCES = {"manual", "cycle"}


class TradeService:
    """Orchestrates trade lifecycle: open, close (full/partial), cancel.

    Coordinates between TradeRepository (DB), AccountsService (exchange clients),
    and WebSocket manager (real-time broadcast). Maintains a per-account stats
    cache with bounded size and TTL eviction.
    """

    def __init__(
        self,
        db: AsyncAnalysisDB,
        trade_repo: TradeRepository,
        accounts_service: Any,
        ws_manager: Any = None,
    ) -> None:
        """Initialize with database, repository, accounts service, and optional WS manager."""
        self._db = db
        self._repo = trade_repo
        self._accounts = accounts_service
        self._ws = ws_manager
        self._stats_cache: dict[str, tuple[float, dict]] = {}

    _STATS_CACHE_TTL = 10.0
    _STATS_CACHE_MAX = 1000

    async def get_cached_stats(self, account_id: str) -> dict:
        """Return trade statistics for an account, using a TTL cache."""
        now = time.monotonic()
        cached = self._stats_cache.get(account_id)
        if cached and (now - cached[0]) < self._STATS_CACHE_TTL:
            return cached[1]
        async with self._db.pool.acquire() as conn:
            stats = await self._repo.get_trade_stats(conn, account_id=account_id)
        if len(self._stats_cache) >= self._STATS_CACHE_MAX and account_id not in self._stats_cache:
            oldest_key = min(self._stats_cache, key=lambda k: self._stats_cache[k][0])
            del self._stats_cache[oldest_key]
        self._stats_cache[account_id] = (now, stats)
        return stats

    def _invalidate_stats_cache(self, account_id: str) -> None:
        """Remove cached stats for an account, forcing re-fetch on next access."""
        self._stats_cache.pop(account_id, None)

    async def get_open_trades(self, account_id: str, limit: int = 500) -> list[dict]:
        """Fetch open trades for an account from the database."""
        async with self._db.pool.acquire() as conn:
            return await self._repo.get_open_trades(conn, account_id=account_id, limit=limit)

    async def close_single_trade(
        self,
        account_id: str,
        trade_id: str,
        qty: float | None = None,
        close_reason: str = "manual_single",
        close_rule_id: str | None = None,
    ) -> dict:
        """Close a trade (full or partial) via the exchange.

        Args:
            account_id: Account owning the trade.
            trade_id: UUID of the trade to close.
            qty: Quantity to close; None means close entire position.
            close_reason: Reason code for audit trail.
            close_rule_id: Optional rule ID that triggered the close.

        Returns:
            Closed (or child) trade record dict.

        Raises:
            ValueError: If qty is non-positive or exceeds remaining size.
            TradeNotFound: If trade doesn't exist.
            InvalidStatusTransition: If trade is already closed/failed/cancelled.
        """
        if qty is not None and qty <= 0:
            raise ValueError("qty must be positive")

        async with self._db.pool.acquire() as conn:
            trade = await self._repo.get_trade(conn, account_id=account_id, trade_id=trade_id)
        if not trade:
            raise TradeNotFound(f"Trade {trade_id} not found")

        if trade["status"] in ("closed", "failed", "cancelled"):
            raise InvalidStatusTransition(f"Trade is already {trade['status']}")

        client = await self._accounts.get_client(account_id)
        remaining = float(trade["qty"]) - float(trade.get("filled_qty") or 0)

        if qty is not None and qty > remaining:
            raise ValueError(f"qty ({qty}) exceeds remaining position size ({remaining})")

        is_partial = qty is not None and qty < remaining

        if is_partial:
            return await self._close_partial(client, trade, qty, close_reason, close_rule_id)
        return await self._close_full(client, trade, close_reason, close_rule_id)

    async def close_trade_record_only(
        self,
        account_id: str,
        trade_id: str,
        close_reason: str = "manual_single",
        close_rule_id: str | None = None,
    ) -> dict:
        """Close a trade record in the DB without placing an exchange order.

        Used when the position has already been closed on the exchange
        (e.g., by a stop-loss) and only the DB record needs updating.
        """
        async with self._db.pool.acquire() as conn:
            trade = await self._repo.get_trade(conn, account_id=account_id, trade_id=trade_id)
        if not trade:
            raise TradeNotFound(f"Trade {trade_id} not found")
        if trade["status"] in ("closed", "failed", "cancelled"):
            raise InvalidStatusTransition(f"Trade is already {trade['status']}")

        version = trade["version"]
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                await self._repo.update_trade_status(
                    conn, trade_id=str(trade["id"]), account_id=account_id,
                    expected_version=version, new_status="closing",
                    event_type="close_requested", actor="system",
                )
                closed = await self._repo.close_trade(
                    conn, trade_id=str(trade["id"]), account_id=account_id,
                    expected_version=version + 1, close_reason=close_reason,
                    close_rule_id=close_rule_id,
                    exit_price=0.0, realized_pnl=0.0, realized_pnl_pct=0.0,
                    fees=0.0, net_pnl=0.0,
                )

        self._invalidate_stats_cache(account_id)
        await self._broadcast_trade_event("trade.closed", closed)
        return closed

    async def _close_full(
        self, client: Any, trade: dict, close_reason: str, close_rule_id: str | None,
    ) -> dict:
        """Execute a full close: transition to 'closing', place exchange order, finalize."""
        account_id = trade["account_id"]
        trade_id = str(trade["id"])
        version = trade["version"]

        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                await self._repo.update_trade_status(
                    conn, trade_id=trade_id, account_id=account_id,
                    expected_version=version, new_status="closing",
                    event_type="close_requested", actor="system",
                )
        version += 1

        try:
            result = await client.place_market_close_order(
                symbol=trade["symbol"],
                side=trade["side"],
                qty=str(trade["qty"]),
                position_idx=trade.get("position_idx", 0),
            )
        except Exception as e:
            logger.warning("bybit_close_failed", extra={"trade_id": trade_id, "error": str(e)})
            await self._handle_close_failure(client, trade, version)
            raise

        pnl_data = self._extract_pnl(result, trade, float(trade["qty"]))
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                closed = await self._repo.close_trade(
                    conn, trade_id=trade_id, account_id=account_id,
                    expected_version=version, close_reason=close_reason,
                    close_rule_id=close_rule_id, **pnl_data,
                )

        self._invalidate_stats_cache(account_id)
        await self._broadcast_trade_event("trade.closed", closed)
        return closed

    async def _close_partial(
        self, client: Any, trade: dict, qty: float, close_reason: str, close_rule_id: str | None,
    ) -> dict:
        """Execute a partial close: close a child portion, keep parent open with reduced qty."""
        account_id = trade["account_id"]
        trade_id = str(trade["id"])
        version = trade["version"]

        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                await self._repo.update_trade_status(
                    conn, trade_id=trade_id, account_id=account_id,
                    expected_version=version, new_status="closing",
                    event_type="close_requested", actor="system",
                )
        version += 1

        try:
            result = await client.place_market_close_order(
                symbol=trade["symbol"],
                side=trade["side"],
                qty=str(qty),
                position_idx=trade.get("position_idx", 0),
            )
        except Exception as e:
            logger.warning("bybit_partial_close_failed", extra={"trade_id": trade_id, "error": str(e)})
            await self._handle_close_failure(client, trade, version)
            raise

        pnl_data = self._extract_pnl(result, trade, qty)
        previously_filled = float(trade.get("filled_qty") or 0)
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                child = await self._repo.create_child_trade(
                    conn, parent_trade=trade, closed_qty=qty,
                    exit_price=pnl_data["exit_price"],
                    realized_pnl=pnl_data["realized_pnl"],
                    realized_pnl_pct=pnl_data["realized_pnl_pct"],
                    fees=pnl_data["fees"],
                    net_pnl=pnl_data["net_pnl"],
                    close_reason=close_reason,
                    close_rule_id=close_rule_id,
                )
                updated_trade = await self._repo.update_trade_status(
                    conn, trade_id=trade_id, account_id=account_id,
                    expected_version=version, new_status="partially_closed",
                    event_type="closed", actor="system",
                    updates={"filled_qty": previously_filled + qty},
                )

        self._invalidate_stats_cache(account_id)
        await self._broadcast_trade_event("trade.closed", child)

        new_filled = previously_filled + qty
        remaining = float(trade["qty"]) - new_filled
        if self._ws:
            try:
                pc_payload = {
                    "trade_id": trade_id,
                    "account_id": account_id,
                    "version": updated_trade["version"] if updated_trade else trade["version"],
                    "filled_qty": new_filled,
                    "remaining_qty": remaining,
                    "realized_pnl": float(child.get("net_pnl") or 0) if child else None,
                }
                await self._ws.broadcast_to_account(account_id, "trade.partially_closed", pc_payload)
            except Exception:
                logger.warning("ws_partially_closed_broadcast_failed", extra={"trade_id": trade_id})

        return child

    async def _handle_close_failure(self, client: Any, trade: dict, version: int) -> None:
        """Revert trade status from 'closing' back to 'open' after exchange failure."""
        account_id = trade["account_id"]
        trade_id = str(trade["id"])
        previous_status = trade.get("status")
        try:
            positions = await client.get_positions()
            position_gone = not any(
                p["symbol"] == trade["symbol"] and p["side"] == trade["side"]
                for p in positions
            )
        except Exception:
            position_gone = False

        if position_gone:
            try:
                async with self._db.pool.acquire() as conn:
                    async with conn.transaction():
                        await self._repo.reconcile_close(
                            conn, trade_id=trade_id, account_id=account_id,
                            exit_price=0.0, realized_pnl=0.0, realized_pnl_pct=0.0,
                            fees=0.0, net_pnl=0.0, close_reason="external",
                        )
                self._invalidate_stats_cache(account_id)
                return
            except Exception:
                logger.exception("reconcile_after_failure_failed", extra={"trade_id": trade_id})

        reverted_version = None
        try:
            async with self._db.pool.acquire() as conn:
                async with conn.transaction():
                    updated = await self._repo.update_trade_status(
                        conn, trade_id=trade_id, account_id=account_id,
                        expected_version=version, new_status="open",
                        event_type="failed", actor="system",
                    )
                    reverted_version = updated.get("version") if updated else version + 1
        except ConcurrentModification:
            logger.warning("revert_concurrent_modification", extra={"trade_id": trade_id})
            return
        except Exception:
            logger.exception("revert_to_open_failed", extra={"trade_id": trade_id})

        trade["_previous_status"] = previous_status
        await self._broadcast_trade_event(
            "trade.close_failed", trade, version_override=reverted_version,
        )

    async def cancel_trade(self, account_id: str, trade_id: str) -> dict:
        """Cancel a pending/open trade without placing an exchange order."""
        async with self._db.pool.acquire() as conn:
            trade = await self._repo.get_trade(conn, account_id=account_id, trade_id=trade_id)
        if not trade:
            raise TradeNotFound(f"Trade {trade_id} not found")

        status = trade["status"]
        if status not in ("pending", "partially_filled"):
            raise InvalidStatusTransition(f"Cannot cancel trade in {status} state")

        client = await self._accounts.get_client(account_id)
        version = trade["version"]

        if status == "pending":
            if trade.get("order_id"):
                try:
                    await client.cancel_order(symbol=trade["symbol"], order_id=trade["order_id"])
                except Exception:
                    logger.warning("bybit_cancel_failed", extra={"trade_id": trade_id})
            async with self._db.pool.acquire() as conn:
                async with conn.transaction():
                    updated = await self._repo.update_trade_status(
                        conn, trade_id=trade_id, account_id=account_id,
                        expected_version=version, new_status="cancelled",
                        event_type="cancelled", actor="user",
                    )
        else:
            if trade.get("order_id"):
                try:
                    await client.cancel_order(symbol=trade["symbol"], order_id=trade["order_id"])
                except Exception:
                    logger.warning("bybit_cancel_partial_failed", extra={"trade_id": trade_id})
            async with self._db.pool.acquire() as conn:
                async with conn.transaction():
                    updated = await self._repo.update_trade_status(
                        conn, trade_id=trade_id, account_id=account_id,
                        expected_version=version, new_status="open",
                        event_type="filled", actor="system",
                        updates={"filled_qty": trade.get("filled_qty")},
                    )

        self._invalidate_stats_cache(account_id)
        return updated

    def _extract_pnl(self, bybit_result: dict, trade: dict, close_qty: float | None = None) -> dict:
        """Calculate realized PnL from exchange close result and trade entry data."""
        exit_price = Decimal(str(bybit_result.get("avgPrice") or bybit_result.get("price") or 0))
        entry = Decimal(str(trade.get("entry_price") or trade.get("avg_fill_price") or 0))
        qty = Decimal(str(close_qty)) if close_qty is not None else Decimal(str(trade["qty"]))
        side_mult = Decimal(1) if trade["side"] == "Buy" else Decimal(-1)
        realized_pnl = (exit_price - entry) * qty * side_mult if entry else Decimal(0)
        realized_pnl_pct = (realized_pnl / abs(entry * qty) * 100) if entry and qty else Decimal(0)
        fees = Decimal(str(bybit_result.get("cumExecFee") or 0))
        net_pnl = realized_pnl - fees
        return {
            "exit_price": float(exit_price),
            "realized_pnl": float(round(realized_pnl, 8)),
            "realized_pnl_pct": float(round(realized_pnl_pct, 4)),
            "fees": float(round(fees, 8)),
            "net_pnl": float(round(net_pnl, 8)),
        }

    @staticmethod
    def _serialize_trade_for_ws(trade: dict) -> dict:
        """Serialize a trade dict for WebSocket broadcast using shared serializer."""
        return _serialize_trade_shared(trade)

    async def _broadcast_trade_event(
        self, event_type: str, trade: dict, *, version_override: int | None = None,
    ) -> None:
        """Broadcast a trade lifecycle event to account subscribers via WebSocket."""
        if not self._ws:
            return
        try:
            if event_type == "trade.closed":
                payload = {
                    "trade_id": str(trade["id"]),
                    "account_id": trade["account_id"],
                    "symbol": trade["symbol"],
                    "close_reason": trade.get("close_reason"),
                    "realized_pnl": float(trade["realized_pnl"]) if trade.get("realized_pnl") else None,
                    "net_pnl": float(trade["net_pnl"]) if trade.get("net_pnl") else None,
                }
            elif event_type == "trade.opened":
                payload = {
                    "trade_id": str(trade["id"]),
                    "account_id": trade["account_id"],
                    "data": self._serialize_trade_for_ws(trade),
                }
            elif event_type == "trade.close_failed":
                meta = trade.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                payload = {
                    "trade_id": str(trade["id"]),
                    "account_id": trade["account_id"],
                    "symbol": trade["symbol"],
                    "error_code": meta.get("error_code", "UNKNOWN"),
                    "error_message": meta.get("error_message", meta.get("error_code", "UNKNOWN")),
                    "previous_status": trade.get("_previous_status"),
                }
            else:
                return
            payload["version"] = version_override if version_override is not None else trade.get("version")
            await self._ws.broadcast_to_account(trade["account_id"], event_type, payload)
        except Exception:
            logger.warning("ws_broadcast_failed", extra={"event_type": event_type, "trade_id": str(trade["id"])})
