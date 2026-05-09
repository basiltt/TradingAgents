"""Service layer for trading account management and portfolio data."""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from datetime import datetime, timezone, timedelta
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
    def __init__(self, db: AnalysisDB, ws_manager=None):
        self._db = db
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._refresh_locks: Dict[str, float] = {}
        self._clients: Dict[str, BybitClient] = {}
        self._ws_manager = ws_manager

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

        result = self._db.get_account(account_id)
        if self._ws_manager:
            asyncio.ensure_future(self._ws_manager.start_account(account_id))
        return result  # type: ignore

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
            if self._ws_manager:
                asyncio.ensure_future(self._ws_manager.stop_account(account_id))
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
        cached = self._get_cached(cache_key, 2)
        if cached is not None:
            return cached

        client = self._build_client(account_id)
        try:
            data = await client.get_wallet_balance()
            data["fetched_at"] = _now_iso()
            self._set_cached(cache_key, data, 2)
            self._db.update_account(account_id, last_connected_at=_now_iso(), last_error=None, updated_at=_now_iso())
            return data
        except BybitAPIError as e:
            self._db.update_account(account_id, last_error=_sanitize_error(e.ret_msg), updated_at=_now_iso())
            raise

    async def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        cache_key = f"{account_id}:positions"
        cached = self._get_cached(cache_key, 3)
        if cached is not None:
            return cached

        client = self._build_client(account_id)
        data = await client.get_positions()
        self._set_cached(cache_key, data, 3)
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

        if start_ms > end_ms:
            raise ValueError("start_date must be before or equal to end_date")

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

        if start_ms > end_ms:
            raise ValueError("start_date must be before or equal to end_date")

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

    # ── Daily Snapshots ────────────────────────────────────────────────

    async def take_snapshot(self, account_id: str) -> Dict[str, Any]:
        account = self._db.get_account(account_id)
        if not account:
            raise ValueError("Account not found")
        if not account["is_active"]:
            raise ValueError("Account is inactive")

        snap_key = f"snap:{account_id}"
        if not self._can_refresh(snap_key, cooldown=30.0):
            raise ValueError("Snapshot rate limited — try again in 30 seconds")
        self._mark_refreshed(snap_key)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_start_ms = _date_to_ms(today)
        today_end_ms = today_start_ms + (24 * 60 * 60 * 1000 - 1)

        wallet, positions = await asyncio.gather(
            self.get_wallet(account_id),
            self.get_positions(account_id),
        )

        equity = float(wallet.get("totalEquity", 0))
        wallet_balance = float(wallet.get("totalWalletBalance", 0))
        available_balance = float(wallet.get("totalAvailableBalance", 0))
        unrealised_pnl = float(wallet.get("totalPerpUPL", 0))
        margin_used = wallet_balance - available_balance if wallet_balance > available_balance else 0

        await self._fetch_and_store_closed_pnl(account_id, today_start_ms, today_end_ms)
        today_summary = self._db.get_closed_pnl_summary(account_id, today_start_ms, today_end_ms)
        realised_pnl = float(today_summary.get("total_pnl", 0))

        prev = self._db.get_latest_snapshot(account_id)
        is_resnapshot = prev and str(prev["snapshot_date"]) == today
        if is_resnapshot:
            yesterday = self._db.get_previous_snapshot(account_id, today)
            prev_equity = yesterday["equity"] if yesterday else equity
            prev_cumulative = prev["cumulative_pnl"] - prev["realised_pnl"]
            prev_peak = max(prev["peak_equity"], yesterday["peak_equity"]) if yesterday else prev["peak_equity"]
        elif prev:
            prev_equity = prev["equity"]
            prev_cumulative = prev["cumulative_pnl"]
            prev_peak = prev["peak_equity"]
        else:
            prev_equity = equity
            prev_cumulative = 0
            prev_peak = equity
        daily_return_pct = ((equity - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0
        cumulative_pnl = prev_cumulative + realised_pnl
        peak_equity = max(prev_peak, equity)
        drawdown_pct = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0

        snapshot = {
            "account_id": account_id,
            "snapshot_date": today,
            "equity": equity,
            "wallet_balance": wallet_balance,
            "available_balance": available_balance,
            "unrealised_pnl": unrealised_pnl,
            "realised_pnl": realised_pnl,
            "positions_count": len(positions),
            "margin_used": margin_used,
            "cumulative_pnl": cumulative_pnl,
            "daily_return_pct": round(daily_return_pct, 4),
            "peak_equity": peak_equity,
            "drawdown_pct": round(drawdown_pct, 4),
        }
        self._db.upsert_daily_snapshot(snapshot)
        return snapshot

    async def take_all_snapshots(self) -> List[Dict[str, Any]]:
        accounts = self._db.list_accounts()
        results = []
        for acc in accounts:
            if acc["is_active"] and acc.get("include_in_analytics", True):
                try:
                    snap = await self.take_snapshot(acc["id"])
                    results.append(snap)
                except Exception as e:
                    logger.warning("Snapshot failed for %s: %s", acc["id"], e)
                    results.append({"account_id": acc["id"], "error": "snapshot_failed"})
        return results

    def get_snapshots(
        self, account_id: str, start_date: str, end_date: str,
    ) -> List[Dict[str, Any]]:
        rows = self._db.get_daily_snapshots(account_id, start_date, end_date)
        for r in rows:
            if "snapshot_date" in r:
                r["snapshot_date"] = str(r["snapshot_date"])
        return rows

    def get_portfolio_snapshots(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self._db.get_all_account_snapshots(start_date, end_date, account_type=account_type)
        aggregated: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            d = str(r["snapshot_date"])
            if d not in aggregated:
                aggregated[d] = {
                    "snapshot_date": d, "equity": 0, "wallet_balance": 0,
                    "available_balance": 0, "unrealised_pnl": 0, "realised_pnl": 0,
                    "positions_count": 0, "margin_used": 0, "cumulative_pnl": 0,
                    "daily_return_pct": 0, "drawdown_pct": 0, "peak_equity": 0,
                }
            agg = aggregated[d]
            agg["equity"] += r["equity"]
            agg["wallet_balance"] += r["wallet_balance"]
            agg["available_balance"] += r.get("available_balance", 0)
            agg["unrealised_pnl"] += r["unrealised_pnl"]
            agg["realised_pnl"] += r["realised_pnl"]
            agg["positions_count"] += r["positions_count"]
            agg["margin_used"] += r.get("margin_used", 0)
            agg["cumulative_pnl"] += r["cumulative_pnl"]

        result = sorted(aggregated.values(), key=lambda x: x["snapshot_date"])
        running_peak = result[0]["equity"] if result else 0.0
        prev_equity = 0.0
        for i, r in enumerate(result):
            running_peak = max(running_peak, r["equity"])
            r["peak_equity"] = running_peak
            if running_peak > 0:
                r["drawdown_pct"] = round((running_peak - r["equity"]) / running_peak * 100, 4)
            if i > 0 and prev_equity > 0:
                r["daily_return_pct"] = round((r["equity"] - prev_equity) / prev_equity * 100, 4)
            prev_equity = r["equity"]
        return result

    # ── High-Frequency Snapshot Queries ─────────────────────────────────

    @staticmethod
    def _hf_to_snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
        ts = row["ts"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
        return {
            "snapshot_date": ts_str,
            "equity": row["equity"],
            "wallet_balance": row.get("balance", 0),
            "available_balance": 0,
            "unrealised_pnl": row.get("unrealised_pnl", 0),
            "realised_pnl": row.get("realised_pnl", 0),
            "positions_count": row.get("position_count", 0),
            "margin_used": 0,
            "cumulative_pnl": 0,
            "daily_return_pct": 0,
            "peak_equity": row["equity"],
            "drawdown_pct": 0,
        }

    def _enrich_hf_snapshots(self, snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not snapshots:
            return []
        running_peak = snapshots[0]["equity"]
        prev_equity = 0.0
        for i, s in enumerate(snapshots):
            running_peak = max(running_peak, s["equity"])
            s["peak_equity"] = running_peak
            if running_peak > 0:
                s["drawdown_pct"] = round((running_peak - s["equity"]) / running_peak * 100, 4)
            if i > 0 and prev_equity > 0:
                s["daily_return_pct"] = round((s["equity"] - prev_equity) / prev_equity * 100, 4)
            prev_equity = s["equity"]
        return snapshots

    def get_hf_snapshots(self, account_id: str, since_ts: str) -> List[Dict[str, Any]]:
        rows = self._db.get_hf_snapshots(account_id, since_ts)
        snapshots = [self._hf_to_snapshot(r) for r in rows]
        return self._enrich_hf_snapshots(snapshots)

    def get_portfolio_hf_snapshots(
        self, since_ts: str, account_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self._db.get_all_hf_snapshots(since_ts, account_type=account_type)
        by_ts: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            ts = r["ts"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
            if ts_str not in by_ts:
                by_ts[ts_str] = {
                    "snapshot_date": ts_str, "equity": 0, "wallet_balance": 0,
                    "available_balance": 0, "unrealised_pnl": 0, "realised_pnl": 0,
                    "positions_count": 0, "margin_used": 0, "cumulative_pnl": 0,
                    "daily_return_pct": 0, "peak_equity": 0, "drawdown_pct": 0,
                }
            agg = by_ts[ts_str]
            agg["equity"] += r["equity"]
            agg["wallet_balance"] += r.get("balance", 0)
            agg["unrealised_pnl"] += r.get("unrealised_pnl", 0)
            agg["realised_pnl"] += r.get("realised_pnl", 0)
            agg["positions_count"] += r.get("position_count", 0)
        result = sorted(by_ts.values(), key=lambda x: x["snapshot_date"])
        return self._enrich_hf_snapshots(result)

    def compute_hf_analytics(self, account_id: str, since_ts: str) -> Dict[str, Any]:
        snapshots = self.get_hf_snapshots(account_id, since_ts)
        return self._compute_analytics_from_snapshots(snapshots, account_id)

    def compute_portfolio_hf_analytics(
        self, since_ts: str, account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshots = self.get_portfolio_hf_snapshots(since_ts, account_type=account_type)
        return self._compute_analytics_from_snapshots(snapshots, None)

    # ── Performance Analytics ──────────────────────────────────────────

    def compute_analytics(
        self, account_id: str, start_date: str, end_date: str,
    ) -> Dict[str, Any]:
        snapshots = self._db.get_daily_snapshots(account_id, start_date, end_date)
        if not snapshots:
            return self._empty_analytics()

        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (24 * 60 * 60 * 1000 - 1)
        pnl_summary = self._db.get_closed_pnl_summary(account_id, start_ms, end_ms)

        equities = [s["equity"] for s in snapshots]
        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1] * 100)
            else:
                daily_returns.append(0)
        running_peak = equities[0] if equities else 0.0
        drawdowns = []
        for eq in equities:
            running_peak = max(running_peak, eq)
            dd = round((running_peak - eq) / running_peak * 100, 4) if running_peak > 0 else 0
            drawdowns.append(dd)

        total_return = ((equities[-1] - equities[0]) / equities[0] * 100) if equities[0] > 0 else 0
        max_drawdown = max(drawdowns) if drawdowns else 0
        avg_daily_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0

        sharpe = self._calc_sharpe(daily_returns)
        sortino = self._calc_sortino(daily_returns)
        calmar = self._calc_calmar(daily_returns, max_drawdown)

        max_consecutive_losses = self._max_consecutive(daily_returns, negative=True)
        max_consecutive_wins = self._max_consecutive(daily_returns, negative=False)

        dd_snapshots = [{"drawdown_pct": d} for d in drawdowns]
        dd_duration, recovery_time = self._calc_drawdown_duration(dd_snapshots)

        profit_factor = 0.0
        win_count = pnl_summary.get("win_count", 0)
        loss_count = pnl_summary.get("loss_count", 0)
        avg_win = float(pnl_summary.get("avg_win", 0))
        avg_loss = float(pnl_summary.get("avg_loss", 0))
        if avg_loss > 0 and loss_count > 0:
            gross_profit = avg_win * win_count
            gross_loss = avg_loss * loss_count
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        expectancy = 0.0
        total_trades = pnl_summary.get("total_count", win_count + loss_count)
        if total_trades > 0:
            expectancy = (avg_win * win_count - avg_loss * loss_count) / total_trades

        best_day = max(daily_returns) if daily_returns else 0
        worst_day = min(daily_returns) if daily_returns else 0

        best_idx = daily_returns.index(best_day) if daily_returns else 0
        worst_idx = daily_returns.index(worst_day) if daily_returns else 0
        best_date = str(snapshots[best_idx + 1]["snapshot_date"]) if daily_returns and best_idx + 1 < len(snapshots) else ""
        worst_date = str(snapshots[worst_idx + 1]["snapshot_date"]) if daily_returns and worst_idx + 1 < len(snapshots) else ""

        return {
            "total_return_pct": round(max(min(total_return, 99999.99), -99999.99), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(self._clamp(sharpe), 2),
            "sortino_ratio": round(self._clamp(sortino), 2),
            "calmar_ratio": round(self._clamp(calmar), 2),
            "profit_factor": round(self._clamp(profit_factor, 0, 999.99), 2),
            "win_rate": pnl_summary.get("win_rate", 0),
            "win_count": win_count,
            "loss_count": loss_count,
            "avg_win": pnl_summary.get("avg_win", "0"),
            "avg_loss": pnl_summary.get("avg_loss", "0"),
            "expectancy": round(expectancy, 2),
            "avg_daily_return_pct": round(avg_daily_return, 4),
            "best_day_pct": round(best_day, 2),
            "best_day_date": best_date,
            "worst_day_pct": round(worst_day, 2),
            "worst_day_date": worst_date,
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "drawdown_duration_days": dd_duration,
            "recovery_time_days": recovery_time,
            "total_trades": total_trades,
            "total_pnl": pnl_summary.get("total_pnl", "0"),
            "snapshot_count": len(snapshots),
        }

    def compute_portfolio_analytics(
        self, start_date: str, end_date: str, account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        portfolio_snaps = self.get_portfolio_snapshots(start_date, end_date, account_type=account_type)
        if not portfolio_snaps:
            return self._empty_analytics()

        equities = [s["equity"] for s in portfolio_snaps]
        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1] * 100)
            else:
                daily_returns.append(0)

        total_return = ((equities[-1] - equities[0]) / equities[0] * 100) if equities[0] > 0 else 0
        drawdowns = [s.get("drawdown_pct", 0) for s in portfolio_snaps]
        max_drawdown = max(drawdowns) if drawdowns else 0
        avg_daily_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0

        dd_duration, recovery_time = self._calc_drawdown_duration(portfolio_snaps)
        max_consecutive_losses = self._max_consecutive(daily_returns, negative=True)
        max_consecutive_wins = self._max_consecutive(daily_returns, negative=False)

        best_day = max(daily_returns) if daily_returns else 0
        worst_day = min(daily_returns) if daily_returns else 0
        best_idx = daily_returns.index(best_day) if daily_returns else 0
        worst_idx = daily_returns.index(worst_day) if daily_returns else 0
        best_date = portfolio_snaps[best_idx + 1]["snapshot_date"] if daily_returns and best_idx + 1 < len(portfolio_snaps) else ""
        worst_date = portfolio_snaps[worst_idx + 1]["snapshot_date"] if daily_returns and worst_idx + 1 < len(portfolio_snaps) else ""

        start_ms = _date_to_ms(start_date)
        end_ms = _date_to_ms(end_date) + (24 * 60 * 60 * 1000 - 1)
        pnl_summary = self._db.get_portfolio_pnl_summary(start_ms, end_ms, account_type=account_type)

        win_count = pnl_summary.get("win_count", 0)
        loss_count = pnl_summary.get("loss_count", 0)
        avg_win = float(pnl_summary.get("avg_win", 0))
        avg_loss = float(pnl_summary.get("avg_loss", 0))
        profit_factor = 0.0
        if avg_loss > 0 and loss_count > 0:
            gross_profit = avg_win * win_count
            gross_loss = avg_loss * loss_count
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        total_trades = pnl_summary.get("total_count", win_count + loss_count)
        expectancy = (avg_win * win_count - avg_loss * loss_count) / total_trades if total_trades > 0 else 0.0

        return {
            "total_return_pct": round(max(min(total_return, 99999.99), -99999.99), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(self._clamp(self._calc_sharpe(daily_returns)), 2),
            "sortino_ratio": round(self._clamp(self._calc_sortino(daily_returns)), 2),
            "calmar_ratio": round(self._clamp(self._calc_calmar(daily_returns, max_drawdown)), 2),
            "profit_factor": round(self._clamp(profit_factor, 0, 999.99), 2),
            "win_rate": pnl_summary.get("win_rate", 0),
            "win_count": win_count,
            "loss_count": loss_count,
            "avg_win": pnl_summary.get("avg_win", "0"),
            "avg_loss": pnl_summary.get("avg_loss", "0"),
            "expectancy": round(expectancy, 2),
            "avg_daily_return_pct": round(avg_daily_return, 4),
            "best_day_pct": round(best_day, 2),
            "best_day_date": str(best_date),
            "worst_day_pct": round(worst_day, 2),
            "worst_day_date": str(worst_date),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "drawdown_duration_days": dd_duration,
            "recovery_time_days": recovery_time,
            "total_trades": total_trades,
            "total_pnl": pnl_summary.get("total_pnl", "0"),
            "snapshot_count": len(portfolio_snaps),
        }

    def _compute_analytics_from_snapshots(
        self, snapshots: List[Dict[str, Any]], account_id: Optional[str],
    ) -> Dict[str, Any]:
        if not snapshots:
            return self._empty_analytics()

        equities = [s["equity"] for s in snapshots]
        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                returns.append((equities[i] - equities[i - 1]) / equities[i - 1] * 100)
            else:
                returns.append(0)

        drawdowns = [s.get("drawdown_pct", 0) for s in snapshots]
        total_return = ((equities[-1] - equities[0]) / equities[0] * 100) if equities[0] > 0 else 0
        max_drawdown = max(drawdowns) if drawdowns else 0
        avg_return = sum(returns) / len(returns) if returns else 0

        dd_duration, recovery_time = self._calc_drawdown_duration(snapshots)
        max_consecutive_losses = self._max_consecutive(returns, negative=True)
        max_consecutive_wins = self._max_consecutive(returns, negative=False)

        best = max(returns) if returns else 0
        worst = min(returns) if returns else 0
        best_idx = returns.index(best) if returns else 0
        worst_idx = returns.index(worst) if returns else 0
        best_date = snapshots[best_idx + 1]["snapshot_date"] if returns and best_idx + 1 < len(snapshots) else ""
        worst_date = snapshots[worst_idx + 1]["snapshot_date"] if returns and worst_idx + 1 < len(snapshots) else ""

        return {
            "total_return_pct": round(max(min(total_return, 99999.99), -99999.99), 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe_ratio": round(self._clamp(self._calc_sharpe(returns)), 2),
            "sortino_ratio": round(self._clamp(self._calc_sortino(returns)), 2),
            "calmar_ratio": round(self._clamp(self._calc_calmar(returns, max_drawdown)), 2),
            "profit_factor": 0,
            "win_rate": 0,
            "win_count": 0,
            "loss_count": 0,
            "avg_win": "0",
            "avg_loss": "0",
            "expectancy": 0,
            "avg_daily_return_pct": round(avg_return, 4),
            "best_day_pct": round(best, 2),
            "best_day_date": str(best_date),
            "worst_day_pct": round(worst, 2),
            "worst_day_date": str(worst_date),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "drawdown_duration_days": dd_duration,
            "recovery_time_days": recovery_time,
            "total_trades": 0,
            "total_pnl": "0",
            "snapshot_count": len(snapshots),
        }

    @staticmethod
    def _empty_analytics() -> Dict[str, Any]:
        return {
            "total_return_pct": 0, "max_drawdown_pct": 0,
            "sharpe_ratio": 0, "sortino_ratio": 0, "calmar_ratio": 0,
            "profit_factor": 0, "win_rate": 0, "win_count": 0, "loss_count": 0,
            "avg_win": "0", "avg_loss": "0", "expectancy": 0,
            "avg_daily_return_pct": 0, "best_day_pct": 0, "best_day_date": "",
            "worst_day_pct": 0, "worst_day_date": "", "max_consecutive_wins": 0,
            "max_consecutive_losses": 0, "drawdown_duration_days": 0,
            "recovery_time_days": 0, "total_trades": 0, "total_pnl": "0",
            "snapshot_count": 0,
        }

    @staticmethod
    def _clamp(value: float, lo: float = -999.99, hi: float = 999.99) -> float:
        if math.isnan(value) or math.isinf(value):
            return 0.0
        return max(lo, min(hi, value))

    @staticmethod
    def _calc_sharpe(daily_returns: List[float], risk_free_rate: float = 0.0) -> float:
        if len(daily_returns) < 2:
            return 0.0
        mean_r = sum(daily_returns) / len(daily_returns) - risk_free_rate / 365
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1))
        if std_r == 0:
            return 0.0
        return (mean_r / std_r) * math.sqrt(365)

    @staticmethod
    def _calc_sortino(daily_returns: List[float], risk_free_rate: float = 0.0) -> float:
        if len(daily_returns) < 2:
            return 0.0
        mean_r = sum(daily_returns) / len(daily_returns) - risk_free_rate / 365
        downside_sq = [min(r, 0) ** 2 for r in daily_returns]
        downside_dev = math.sqrt(sum(downside_sq) / (len(daily_returns) - 1))
        if downside_dev == 0:
            return 0.0
        return (mean_r / downside_dev) * math.sqrt(365)

    @staticmethod
    def _calc_calmar(daily_returns: List[float], max_drawdown: float) -> float:
        if not daily_returns or max_drawdown == 0:
            return 0.0
        annual_return = sum(daily_returns) / len(daily_returns) * 365
        return annual_return / max_drawdown

    @staticmethod
    def _max_consecutive(daily_returns: List[float], negative: bool) -> int:
        max_count = 0
        count = 0
        for r in daily_returns:
            if (negative and r < 0) or (not negative and r > 0):
                count += 1
                max_count = max(max_count, count)
            else:
                count = 0
        return max_count

    @staticmethod
    def _calc_drawdown_duration(snapshots: List[Dict[str, Any]]) -> tuple[int, int]:
        if not snapshots:
            return 0, 0
        max_duration = 0
        current_duration = 0
        max_recovery = 0
        recovery_start = -1
        for i, s in enumerate(snapshots):
            if s.get("drawdown_pct", 0) > 0:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
                if recovery_start < 0:
                    recovery_start = i
            else:
                if recovery_start >= 0:
                    max_recovery = max(max_recovery, i - recovery_start)
                current_duration = 0
                recovery_start = -1
        if recovery_start >= 0:
            max_recovery = max(max_recovery, len(snapshots) - recovery_start)
        return max_duration, max_recovery

    # ── High-Frequency Snapshots & Scheduler ──────────────────────────

    async def take_all_hf_snapshots(self) -> int:
        accounts = await asyncio.to_thread(self._db.list_accounts)
        eligible = [a for a in accounts if a["is_active"] and a.get("include_in_analytics", True)]
        sem = asyncio.Semaphore(5)

        async def _snap_one(acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            async with sem:
                try:
                    wallet = await self.get_wallet(acc["id"])
                    positions = await self.get_positions(acc["id"])
                    return {
                        "account_id": acc["id"],
                        "equity": float(wallet.get("totalEquity", 0)),
                        "unrealised_pnl": float(wallet.get("totalPerpUPL", 0)),
                        "realised_pnl": 0,
                        "balance": float(wallet.get("totalWalletBalance", 0)),
                        "position_count": len(positions),
                    }
                except Exception:
                    logger.debug("HF snapshot skipped for %s", acc["id"])
                    return None

        results = await asyncio.gather(*[_snap_one(a) for a in eligible])
        snapshots = [r for r in results if r is not None]
        if snapshots:
            return await asyncio.to_thread(self._db.insert_hf_snapshots, snapshots)
        if eligible:
            logger.warning("All %d eligible accounts failed HF snapshot", len(eligible))
        return 0

    async def auto_cleanup_old_snapshots(self) -> int:
        return await asyncio.to_thread(self._db.cleanup_old_hf_snapshots, max_age_days=1095)

    def set_analytics_inclusion(self, account_id: str, include: bool) -> Optional[Dict[str, Any]]:
        account = self._db.get_account(account_id)
        if not account:
            return None
        self._db.update_account(account_id, include_in_analytics=include)
        return self._db.get_account(account_id)

    @staticmethod
    def _resolve_cleanup_dates(
        preset: Optional[str],
        before_date: Optional[str],
        after_date: Optional[str],
    ) -> tuple:
        before_ts = before_date
        after_ts = after_date
        if preset:
            today = datetime.now(timezone.utc).date()
            preset_map = {
                "1w": timedelta(days=7),
                "1m": timedelta(days=30),
                "3m": timedelta(days=90),
                "6m": timedelta(days=180),
                "1y": timedelta(days=365),
            }
            if preset == "all":
                before_ts = None
                after_ts = None
            elif preset in preset_map:
                cutoff = today - preset_map[preset]
                before_ts = str(cutoff)
                after_ts = None
            else:
                raise ValueError(f"Invalid preset: {preset}")
        return before_ts, after_ts

    def cleanup_snapshot_data(
        self,
        account_id: Optional[str],
        preset: Optional[str] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        tables: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        if tables is None:
            tables = ["daily_snapshots", "high_freq_snapshots"]
        for table in tables:
            if table not in self._db._VALID_SNAPSHOT_TABLES:
                raise ValueError(f"Invalid table: {table}")
        before_ts, after_ts = self._resolve_cleanup_dates(preset, before_date, after_date)

        result: Dict[str, int] = {}
        for table in tables:
            count = self._db.cleanup_snapshots(account_id, before_ts, after_ts, table)
            result[table] = count
        return result

    def count_snapshot_data(
        self,
        account_id: Optional[str],
        preset: Optional[str] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        tables: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        if tables is None:
            tables = ["daily_snapshots", "high_freq_snapshots"]
        before_ts, after_ts = self._resolve_cleanup_dates(preset, before_date, after_date)

        result: Dict[str, int] = {}
        for table in tables:
            count = self._db.count_snapshots(account_id, before_ts, after_ts, table)
            result[table] = count
        return result
