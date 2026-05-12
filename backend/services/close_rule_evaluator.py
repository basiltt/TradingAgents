"""Background service that evaluates conditional close rules every 30 seconds."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

EVALUATION_INTERVAL = 30  # seconds
PER_ACCOUNT_TIMEOUT = 10  # seconds
MAX_CONCURRENT_ACCOUNTS = 5


class CloseRuleEvaluator:
    def __init__(self, close_service: Any, accounts_service: Any, db: Any):
        self._close_service = close_service
        self._accounts_service = accounts_service
        self._db = db
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())
        logger.info("CloseRuleEvaluator started (interval=%ds)", EVALUATION_INTERVAL)

    async def shutdown(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CloseRuleEvaluator stopped")

    async def _evaluation_loop(self) -> None:
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            return

        while self._running:
            try:
                await self._evaluate_all_rules()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Rule evaluation cycle failed")
            try:
                await asyncio.sleep(EVALUATION_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _evaluate_all_rules(self) -> None:
        rules = await asyncio.to_thread(self._db.list_active_rules)
        if not rules:
            return

        accounts: dict[str, list[dict]] = {}
        for rule in rules:
            aid = rule["account_id"]
            accounts.setdefault(aid, []).append(rule)

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNTS)

        async def evaluate_account(account_id: str, account_rules: list[dict]) -> None:
            async with semaphore:
                try:
                    await asyncio.wait_for(
                        self._evaluate_account_rules(account_id, account_rules),
                        timeout=PER_ACCOUNT_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Rule evaluation timed out for account %s", account_id)
                except Exception:
                    logger.exception("Rule evaluation failed for account %s", account_id)

        await asyncio.gather(*[
            evaluate_account(aid, arules) for aid, arules in accounts.items()
        ])

    async def _evaluate_account_rules(self, account_id: str, rules: list[dict]) -> None:
        try:
            wallet = await self._accounts_service.get_wallet(account_id)
        except Exception:
            logger.warning("Cannot fetch wallet for account %s, skipping rules", account_id)
            return

        equity = Decimal(wallet.get("totalEquity", "0"))
        pnl = Decimal(wallet.get("totalPerpUPL", "0"))
        balance = Decimal(wallet.get("totalWalletBalance", "0"))

        for rule in rules:
            try:
                triggered = self._check_condition(rule, equity=equity, pnl=pnl, balance=balance)
                if triggered:
                    logger.info(
                        "Rule %s triggered for account %s (type=%s, threshold=%s)",
                        rule["id"], account_id, rule["trigger_type"], rule["threshold_value"],
                    )
                    did_transition = await asyncio.to_thread(self._db.atomic_trigger_rule, rule["id"])
                    if not did_transition:
                        continue
                    try:
                        await self._close_service.close_all_for_rule(account_id, rule["id"])
                    except Exception:
                        logger.exception("Failed to close positions for rule %s", rule["id"])
            except Exception:
                logger.exception("Error evaluating rule %s", rule["id"])

    def _check_condition(
        self,
        rule: dict,
        equity: Decimal,
        pnl: Decimal,
        balance: Decimal,
    ) -> bool:
        trigger_type = rule["trigger_type"]
        threshold = Decimal(rule["threshold_value"])
        reference = Decimal(rule["reference_value"]) if rule.get("reference_value") else None

        if trigger_type == "BALANCE_BELOW":
            return balance <= threshold
        elif trigger_type == "BALANCE_ABOVE":
            return balance >= threshold
        elif trigger_type == "PNL_BELOW":
            return pnl <= -threshold
        elif trigger_type == "PNL_ABOVE":
            return pnl >= threshold
        elif trigger_type == "EQUITY_DROP_PCT":
            if not reference or reference == 0:
                return False
            drop_pct = ((reference - equity) / reference) * Decimal("100")
            return drop_pct >= threshold
        elif trigger_type == "EQUITY_RISE_PCT":
            if not reference or reference == 0:
                return False
            rise_pct = ((equity - reference) / reference) * Decimal("100")
            return rise_pct >= threshold

        return False
