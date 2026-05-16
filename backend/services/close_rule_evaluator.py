"""Background service that evaluates conditional close rules every 30 seconds."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

EVALUATION_INTERVAL = 30  # seconds
PER_ACCOUNT_TIMEOUT = 30  # seconds — must accommodate closing multiple positions
MAX_CONCURRENT_ACCOUNTS = 5
MAX_RULE_FAILURES = 3


class CloseRuleEvaluator:
    def __init__(self, close_service: Any, accounts_service: Any, db: Any):
        self._close_service = close_service
        self._cycle_callback: Optional[Any] = None
        self._cycle_repo: Optional[Any] = None
        self._accounts_service = accounts_service
        self._db = db
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._rule_failures: dict[str, int] = {}

    def set_cycle_callback(self, callback: Any) -> None:
        self._cycle_callback = callback

    def set_cycle_repo(self, repo: Any) -> None:
        self._cycle_repo = repo

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
        try:
            recovered = await self._db.recover_stuck_triggered_rules(90)
            if recovered:
                logger.warning("Recovered %d stuck triggered rules", recovered)
        except Exception:
            logger.exception("Failed to recover stuck triggered rules")

        rules = await self._db.list_active_rules()
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

        active_ids = {r["id"] for r in rules}
        self._rule_failures = {k: v for k, v in self._rule_failures.items() if k in active_ids}

    async def _evaluate_account_rules(self, account_id: str, rules: list[dict]) -> None:
        try:
            wallet = await self._accounts_service.get_wallet(account_id)
        except Exception:
            logger.warning("Cannot fetch wallet for account %s, skipping rules", account_id)
            return

        try:
            equity = Decimal(wallet.get("totalEquity") or "0")
            pnl = Decimal(wallet.get("totalPerpUPL") or "0")
            balance = Decimal(wallet.get("totalWalletBalance") or "0")
        except Exception:
            logger.warning("Invalid wallet data for account %s, skipping rules", account_id)
            return

        logger.debug(
            "Account %s wallet: equity=%s, balance=%s, pnl=%s, rules=%d",
            account_id, equity, balance, pnl, len(rules),
        )

        for rule in rules:
            try:
                triggered = self._check_condition(rule, equity=equity, pnl=pnl, balance=balance)
                if triggered:
                    logger.info(
                        "Rule %s triggered for account %s (type=%s, threshold=%s)",
                        rule["id"], account_id, rule["trigger_type"], rule["threshold_value"],
                    )
                    did_transition = await self._db.atomic_trigger_rule(rule["id"])
                    if not did_transition:
                        continue
                    try:
                        close_kwargs: dict[str, Any] = {}
                        if rule.get("cycle_id") and self._cycle_repo:
                            try:
                                close_kwargs["symbols"] = await self._cycle_repo.get_cycle_trade_symbols(rule["cycle_id"])
                            except Exception:
                                logger.warning("Failed to get cycle trade symbols for rule %s, closing all", rule["id"])
                        result = await self._close_service.close_all_for_rule(account_id, rule["id"], **close_kwargs)
                        if result.get("skipped"):
                            logger.info("Close skipped for rule %s (concurrent close), reverting to active", rule["id"])
                            await self._db.update_close_rule(rule["id"], status="active")
                        else:
                            logger.info("Rule %s executed successfully, transitioning to 'executed'", rule["id"])
                            await self._db.update_close_rule(rule["id"], status="executed")
                            self._rule_failures.pop(rule["id"], None)
                            cleared = await self._db.deactivate_rules_for_account(account_id, exclude_rule_id=rule["id"])
                            if cleared:
                                logger.info("Deactivated %d remaining rules for account %s after rule %s executed", cleared, account_id, rule["id"])
                            if self._cycle_callback and rule.get("cycle_id"):
                                try:
                                    await self._cycle_callback(rule)
                                except Exception:
                                    logger.exception("Cycle callback failed for rule %s", rule["id"])
                            break  # all other rules deactivated, stop evaluating this account
                    except asyncio.CancelledError:
                        logger.warning("Close cancelled (timeout) for rule %s, reverting to active", rule["id"])
                        await self._db.update_close_rule(rule["id"], status="active")
                        raise
                    except Exception:
                        rule_id = rule["id"]
                        self._rule_failures[rule_id] = self._rule_failures.get(rule_id, 0) + 1
                        if self._rule_failures[rule_id] >= MAX_RULE_FAILURES:
                            logger.error("Rule %s failed %d times, pausing", rule_id, self._rule_failures[rule_id])
                            await self._db.update_close_rule(rule_id, status="paused")
                            self._rule_failures.pop(rule_id, None)
                        else:
                            logger.exception("Failed to close positions for rule %s (attempt %d), reverting to active", rule_id, self._rule_failures[rule_id])
                            await self._db.update_close_rule(rule_id, status="active")
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
            return equity <= threshold
        elif trigger_type == "BALANCE_ABOVE":
            return equity >= threshold
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

        logger.warning("unknown_trigger_type", extra={"trigger_type": trigger_type, "rule_id": rule.get("id")})
        return False
