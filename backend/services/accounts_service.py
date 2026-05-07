"""Service layer for trading account management and portfolio data."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.crypto import decrypt_value, encrypt_value, mask_api_key
from backend.persistence import AnalysisDB
from backend.services.bybit_client import BybitAPIError, BybitClient

logger = logging.getLogger(__name__)

_SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
_MAX_RANGE_DAYS = 90


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _sanitize_error(msg: str) -> str:
    if len(msg) > 512:
        msg = msg[:512]
    return msg


class AccountsService:
    def __init__(self, db: AnalysisDB):
        self._db = db
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._refresh_locks: Dict[str, float] = {}
        self._clients: Dict[str, BybitClient] = {}

    async def shutdown(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
        self._cache.clear()

    def _get_cached(self, key: str, ttl: float) -> Any | None:
        entry = self._cache.get(key)
        if entry and time.time() < entry[0]:
            return entry[1]
        return None

    def _set_cached(self, key: str, data: Any, ttl: float) -> None:
        self._cache[key] = (time.time() + ttl, data)

    def _invalidate_cache(self, account_id: str) -> None:
        keys_to_remove = [k for k in self._cache if k.startswith(f"{account_id}:")]
        for k in keys_to_remove:
            del self._cache[k]
        self._clients.pop(account_id, None)

    def _can_refresh(self, account_id: str, cooldown: float = 10.0) -> bool:
        last = self._refresh_locks.get(account_id, 0)
        return time.time() - last >= cooldown

    def _mark_refreshed(self, account_id: str) -> None:
        self._refresh_locks[account_id] = time.time()

    def _build_client(self, account_id: str) -> BybitClient:
        if account_id in self._clients:
            return self._clients[account_id]
        creds = self._db.get_account_credentials(account_id)
        if not creds:
            raise ValueError(f"Account {account_id} not found")
        api_key = decrypt_value(creds["api_key_encrypted"])
        api_secret = decrypt_value(creds["api_secret_encrypted"])
        client = BybitClient(api_key, api_secret, creds["account_type"])
        self._clients[account_id] = client
        return client

    # ── CRUD ────────────────────────────────────────────────────────────

    async def create_account(
        self, label: str, account_type: str, api_key: str, api_secret: str
    ) -> Dict[str, Any]:
        client = BybitClient(api_key, api_secret, account_type)
        try:
            test_result = await client.test_connection()
        finally:
            await client.close()
        if not test_result["success"]:
            raise ValueError(f"Connection test failed: {test_result['error']}")

        account_id = str(uuid.uuid4())
        now = _now_iso()
        self._db.insert_account({
            "id": account_id,
            "label": label,
            "account_type": account_type,
            "api_key_masked": mask_api_key(api_key),
            "api_key_encrypted": encrypt_value(api_key),
            "api_secret_encrypted": encrypt_value(api_secret),
            "bybit_uid": test_result.get("uid"),
            "last_connected_at": now,
            "created_at": now,
            "updated_at": now,
        })

        return self._db.get_account(account_id)  # type: ignore

    def list_accounts(self) -> List[Dict[str, Any]]:
        return self._db.list_accounts()

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        return self._db.get_account(account_id)

    def update_account(self, account_id: str, label: str | None = None, is_active: bool | None = None) -> Optional[Dict[str, Any]]:
        fields: Dict[str, Any] = {"updated_at": _now_iso()}
        if label is not None:
            fields["label"] = label
        if is_active is not None:
            fields["is_active"] = 1 if is_active else 0
        self._db.update_account(account_id, **fields)
        if is_active is False:
            self._invalidate_cache(account_id)
        return self._db.get_account(account_id)

    async def rotate_credentials(
        self, account_id: str, api_key: str, api_secret: str
    ) -> Optional[Dict[str, Any]]:
        account = self._db.get_account(account_id)
        if not account:
            return None

        client = BybitClient(api_key, api_secret, account["account_type"])
        try:
            test_result = await client.test_connection()
        finally:
            await client.close()
        if not test_result["success"]:
            raise ValueError(f"Connection test failed: {test_result['error']}")

        self._db.rotate_account_credentials(
            account_id,
            mask_api_key(api_key),
            encrypt_value(api_key),
            encrypt_value(api_secret),
            _now_iso(),
        )
        self._invalidate_cache(account_id)
        return self._db.get_account(account_id)

    def delete_account(self, account_id: str) -> bool:
        result = self._db.soft_delete_account(account_id, _now_iso())
        if result:
            self._invalidate_cache(account_id)
        return result

    async def test_connection(self, account_id: str) -> Dict[str, Any]:
        client = self._build_client(account_id)
        result = await client.test_connection()
        now = _now_iso()
        if result["success"]:
            self._db.update_account(account_id, last_connected_at=now, last_error=None, updated_at=now)
        else:
            self._db.update_account(account_id, last_error=_sanitize_error(result["error"] or ""), updated_at=now)
        return result

    # ── Portfolio Data ──────────────────────────────────────────────────

    async def get_wallet(self, account_id: str) -> Dict[str, Any]:
        cache_key = f"{account_id}:wallet"
        cached = self._get_cached(cache_key, 30)
        if cached is not None:
            return cached

        client = self._build_client(account_id)
        try:
            data = await client.get_wallet_balance()
            data["fetched_at"] = _now_iso()
            self._set_cached(cache_key, data, 30)
            self._db.update_account(account_id, last_connected_at=_now_iso(), last_error=None, updated_at=_now_iso())
            return data
        except BybitAPIError as e:
            self._db.update_account(account_id, last_error=_sanitize_error(e.ret_msg), updated_at=_now_iso())
            raise

    async def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        cache_key = f"{account_id}:positions"
        cached = self._get_cached(cache_key, 15)
        if cached is not None:
            return cached

        client = self._build_client(account_id)
        data = await client.get_positions()
        self._set_cached(cache_key, data, 15)
        return data

    async def get_orders(self, account_id: str) -> List[Dict[str, Any]]:
        cache_key = f"{account_id}:orders"
        cached = self._get_cached(cache_key, 10)
        if cached is not None:
            return cached

        client = self._build_client(account_id)
        data = await client.get_open_orders()
        self._set_cached(cache_key, data, 10)
        return data

    async def get_closed_pnl(
        self, account_id: str, start_date: str, end_date: str,
        page: int = 1, limit: int = 100,
    ) -> Dict[str, Any]:
        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (24 * 60 * 60 * 1000 - 1)

        days_diff = (end_ms - start_ms) / (24 * 60 * 60 * 1000)
        if days_diff > _MAX_RANGE_DAYS:
            raise ValueError(f"Date range exceeds maximum of {_MAX_RANGE_DAYS} days")

        await self._fetch_and_store_closed_pnl(account_id, start_ms, end_ms)
        return self._db.get_closed_pnl(account_id, start_ms, end_ms, page, limit)

    async def get_pnl_summary(
        self, account_id: str, start_date: str, end_date: str,
    ) -> Dict[str, Any]:
        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (24 * 60 * 60 * 1000 - 1)

        days_diff = (end_ms - start_ms) / (24 * 60 * 60 * 1000)
        if days_diff > _MAX_RANGE_DAYS:
            raise ValueError(f"Date range exceeds maximum of {_MAX_RANGE_DAYS} days")

        await self._fetch_and_store_closed_pnl(account_id, start_ms, end_ms)
        return self._db.get_closed_pnl_summary(account_id, start_ms, end_ms)

    async def _fetch_and_store_closed_pnl(self, account_id: str, start_ms: int, end_ms: int) -> None:
        client = self._build_client(account_id)
        current_start = start_ms
        max_pages = 50

        while current_start < end_ms:
            window_end = min(current_start + _SEVEN_DAYS_MS, end_ms)
            cursor = ""
            for _ in range(max_pages):
                result = await client.get_closed_pnl(current_start, window_end, limit=100, cursor=cursor)
                records = result.get("list", [])
                if records:
                    self._db.insert_closed_pnl_records(account_id, records)
                next_cursor = result.get("nextPageCursor", "")
                if not next_cursor or not records:
                    break
                cursor = next_cursor
            current_start = window_end

    # ── Aggregation ─────────────────────────────────────────────────────

    async def _fetch_card(self, acc: Dict[str, Any], today_start_ms: int, today_end_ms: int) -> Dict[str, Any]:
        if not acc["is_active"]:
            return {**acc, "total_equity": None, "total_perp_upl": None, "positions_count": 0, "today_pnl": None, "status": "disabled"}

        try:
            wallet, positions, _ = await asyncio.gather(
                self.get_wallet(acc["id"]),
                self.get_positions(acc["id"]),
                self._fetch_and_store_closed_pnl(acc["id"], today_start_ms, today_end_ms),
            )
            today_summary = self._db.get_closed_pnl_summary(acc["id"], today_start_ms, today_end_ms)
            return {
                **acc,
                "total_equity": wallet.get("totalEquity", "0"),
                "total_perp_upl": wallet.get("totalPerpUPL", "0"),
                "positions_count": len(positions),
                "today_pnl": today_summary.get("total_pnl", "0"),
                "status": "active",
            }
        except Exception as e:
            return {
                **acc,
                "total_equity": None,
                "total_perp_upl": None,
                "positions_count": 0,
                "today_pnl": None,
                "status": "error",
                "last_error": _sanitize_error(str(e)),
            }

    async def get_dashboard(self) -> List[Dict[str, Any]]:
        accounts = self._db.list_accounts()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_start_ms = _date_to_ms(today_str)
        today_end_ms = today_start_ms + (24 * 60 * 60 * 1000 - 1)

        cards = await asyncio.gather(
            *[self._fetch_card(acc, today_start_ms, today_end_ms) for acc in accounts]
        )
        return list(cards)

    async def get_portfolio_summary(self) -> Dict[str, Any]:
        accounts = self._db.list_accounts()
        total_equity = 0.0
        total_pnl = 0.0
        active_count = 0
        failed_count = 0

        for acc in accounts:
            if not acc["is_active"]:
                continue
            try:
                wallet = await self.get_wallet(acc["id"])
                total_equity += float(wallet.get("totalEquity", 0))
                total_pnl += float(wallet.get("totalPerpUPL", 0))
                active_count += 1
            except Exception:
                failed_count += 1

        return {
            "total_equity": str(total_equity),
            "total_unrealised_pnl": str(total_pnl),
            "active_accounts": active_count,
            "total_accounts": len(accounts),
            "failed_accounts": failed_count,
        }
