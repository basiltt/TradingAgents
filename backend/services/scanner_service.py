"""Scanner service — orchestrates batch analysis of all available symbols."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10
_POLL_INTERVAL = 5  # seconds between polling for batch completion
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _parse_signal_from_reports(reports: Dict[str, str]) -> Dict[str, Any]:
    """Extract signal from structured report data instead of regex on free text.

    Priority:
    1. Portfolio manager's final decision (APPROVE/REJECT/MODIFY + direction)
    2. Trader's structured JSON (trade_type field)
    3. Fallback: regex on final_trade_decision text
    """
    direction = "hold"
    conf_score = 2
    confidence = "low"

    # --- Try trader's structured JSON first for the base signal ---
    trader_text = reports.get("trader", "")
    trader_direction = None
    trader_confidence = None
    trader_no_trade = False
    if trader_text:
        json_match = re.search(r"\{[^{}]*\"trade_type\"\s*:[^{}]*\}", trader_text, re.DOTALL)
        if json_match:
            try:
                import json
                trade_data = json.loads(json_match.group())
                tt = trade_data.get("trade_type", "").lower().strip()
                if tt in ("long", "buy"):
                    trader_direction = "buy"
                elif tt in ("short", "sell"):
                    trader_direction = "sell"
                elif tt in ("no trade", "no_trade", "hold", "neutral", "none", "pass"):
                    trader_no_trade = True
                    trader_direction = "hold"
                raw_conf = trade_data.get("confidence")
                if isinstance(raw_conf, (int, float)) and 1 <= raw_conf <= 10:
                    trader_confidence = int(raw_conf)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    # --- Check portfolio manager decision (overrides trader if it modifies) ---
    pm_text = reports.get("portfolio_manager", "") or reports.get("final_trade_decision", "")
    pm_direction = None
    if pm_text:
        pm_lower = pm_text.lower()
        decision_match = re.search(r"final\s+decision\s*:\s*(approve|reject|modify)", pm_lower)
        if decision_match:
            pm_decision = decision_match.group(1)
            if pm_decision == "reject":
                return {"direction": "hold", "confidence": "low", "score": 0}
            # For APPROVE or MODIFY, extract the direction from PM text near the decision
            dir_match = re.search(
                r"(?:final\s+decision|approved|modified).*?\b(long|short|buy|sell)\b",
                pm_lower[:2000],
            )
            if dir_match:
                d = dir_match.group(1)
                pm_direction = "buy" if d in ("long", "buy") else "sell"

    # Resolve direction: PM decision > trader structured data > fallback
    if pm_direction:
        direction = pm_direction
    elif trader_direction:
        direction = trader_direction
    elif not trader_no_trade:
        fallback_text = (pm_text or trader_text).lower()
        if re.search(r"\b(buy|long|bullish)\b", fallback_text):
            direction = "buy"
        elif re.search(r"\b(sell|short|bearish)\b", fallback_text):
            direction = "sell"

    # Resolve confidence
    if trader_confidence is not None:
        conf_score = trader_confidence
    else:
        text = (pm_text or trader_text).lower()
        pct_match = re.search(r"(\d{1,3})\s*%", text)
        if pct_match:
            pct = int(pct_match.group(1))
            if 0 < pct <= 100:
                conf_score = round(pct / 10)
        elif re.search(r"\b(very\s+high|extremely|exceptional|overwhelming)\b", text):
            conf_score = 10
        elif re.search(r"\b(strong|high)\b", text):
            conf_score = 8
        elif re.search(r"\b(moderate|medium|moderately)\b", text):
            conf_score = 5

    conf_score = max(1, min(10, conf_score))
    if conf_score >= 7:
        confidence = "high"
    elif conf_score >= 4:
        confidence = "moderate"
    else:
        confidence = "low"

    sign = 1 if direction == "buy" else (-1 if direction == "sell" else 0)
    score = sign * conf_score

    return {"direction": direction, "confidence": confidence, "score": score}


class ScannerBusyError(Exception):
    pass


class ScannerService:
    def __init__(self, analysis_service: Any, db: Any = None):
        self._analysis = analysis_service
        self._db = db
        self._scans: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def start_scan(self, config: Dict[str, Any]) -> str:
        async with self._lock:
            active = sum(1 for s in self._scans.values() if s["status"] == "running")
            if active >= 1:
                raise ScannerBusyError("A scan is already running. Cancel it first or wait for it to finish.")

            # Evict old scans (keep last 10)
            done = [sid for sid, s in self._scans.items() if s["status"] != "running"]
            for sid in done[:-10]:
                self._scans.pop(sid, None)

        scan_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        scan = {
            "scan_id": scan_id,
            "status": "running",
            "config": config,
            "total": 0,
            "completed": 0,
            "failed": 0,
            "current_batch": 0,
            "total_batches": 0,
            "current_tickers": [],
            "results": [],
            "started_at": now,
            "completed_at": None,
            "cancel": False,
            "task": None,
        }

        async with self._lock:
            self._scans[scan_id] = scan

        if self._db:
            import json as _json
            await asyncio.to_thread(
                self._db.insert_scan,
                {"scan_id": scan_id, "status": "running", "config": _json.dumps(config), "started_at": now},
            )

        task = asyncio.create_task(self._run_scan(scan_id))
        async with self._lock:
            if scan_id in self._scans:
                self._scans[scan_id]["task"] = task

        return scan_id

    async def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            scan = self._scans.get(scan_id)
            if scan:
                return self._serialize(scan)
        if self._db:
            db_scan = await asyncio.to_thread(self._db.get_scan, scan_id)
            if db_scan:
                return self._serialize_db(db_scan)
        return None

    async def cancel_scan(self, scan_id: str) -> bool:
        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return False
            scan["cancel"] = True
            task = scan.get("task")
            if task and not task.done():
                task.cancel()
            return True

    async def list_scans(self) -> List[Dict[str, Any]]:
        async with self._lock:
            in_memory_ids = set(self._scans.keys())
            result = [self._serialize(s) for s in self._scans.values()]
        if self._db:
            db_scans = await asyncio.to_thread(self._db.list_scans)
            for ds in db_scans:
                if ds["scan_id"] not in in_memory_ids:
                    result.append(self._serialize_db(ds))
        return result

    async def resume_incomplete_scans(self) -> int:
        if not self._db:
            return 0
        running = await asyncio.to_thread(self._db.get_running_scans)
        resumed = 0
        for db_scan in running:
            if resumed >= 1:
                await asyncio.to_thread(self._db.update_scan, db_scan["scan_id"], status="failed")
                logger.warning("Marking extra stale scan %s as failed (only 1 resumed at a time)", db_scan["scan_id"])
                continue
            scan_id = db_scan["scan_id"]
            try:
                import json as _json
                config = _json.loads(db_scan.get("config", "{}"))
            except Exception:
                config = {}

            done_tickers = await asyncio.to_thread(self._db.get_scan_completed_tickers, scan_id)
            db_results = await asyncio.to_thread(self._db.get_scan, scan_id)
            existing_results = (db_results or {}).get("results", [])

            try:
                from tradingagents.dataflows.bybit_data import get_valid_symbols
                all_symbols = sorted(await asyncio.to_thread(get_valid_symbols))
            except Exception as e:
                logger.error("Failed to fetch symbols for resume of %s: %s", scan_id, e)
                await asyncio.to_thread(self._db.update_scan, scan_id, status="failed")
                continue

            remaining = [s for s in all_symbols if s not in done_tickers]
            if not remaining:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                await asyncio.to_thread(
                    self._db.update_scan, scan_id, status="completed", completed_at=now,
                )
                continue

            now = db_scan.get("started_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            scan = {
                "scan_id": scan_id,
                "status": "running",
                "config": config,
                "total": len(all_symbols),
                "completed": db_scan.get("completed", 0),
                "failed": db_scan.get("failed", 0),
                "current_batch": 0,
                "total_batches": 0,
                "current_tickers": [],
                "results": list(existing_results),
                "started_at": now,
                "completed_at": None,
                "cancel": False,
                "task": None,
            }

            async with self._lock:
                self._scans[scan_id] = scan

            task = asyncio.create_task(self._run_scan(scan_id, symbols_override=remaining))
            async with self._lock:
                if scan_id in self._scans:
                    self._scans[scan_id]["task"] = task

            resumed += 1
            logger.info("Resumed scan %s with %d/%d remaining symbols", scan_id, len(remaining), len(all_symbols))

        return resumed

    def _serialize(self, scan: Dict[str, Any]) -> Dict[str, Any]:
        sorted_results = sorted(scan["results"], key=lambda r: abs(r.get("score", 0)), reverse=True)
        return {
            "scan_id": scan["scan_id"],
            "status": scan["status"],
            "total": scan["total"],
            "completed": scan["completed"],
            "failed": scan["failed"],
            "current_batch": scan["current_batch"],
            "total_batches": scan["total_batches"],
            "current_tickers": scan["current_tickers"],
            "results": sorted_results,
            "started_at": scan["started_at"],
            "completed_at": scan["completed_at"],
        }

    def _serialize_db(self, scan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "scan_id": scan["scan_id"],
            "status": scan["status"],
            "total": scan.get("total", 0),
            "completed": scan.get("completed", 0),
            "failed": scan.get("failed", 0),
            "current_batch": 0,
            "total_batches": 0,
            "current_tickers": [],
            "results": scan.get("results", []),
            "started_at": scan.get("started_at", ""),
            "completed_at": scan.get("completed_at"),
        }

    async def _run_scan(self, scan_id: str, symbols_override: Optional[List[str]] = None) -> None:
        try:
            if symbols_override is not None:
                symbols = symbols_override
            else:
                from tradingagents.dataflows.bybit_data import get_valid_symbols
                symbols = sorted(await asyncio.to_thread(get_valid_symbols))
        except Exception as e:
            logger.error("Failed to fetch symbols for scan %s: %s", scan_id, e)
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["status"] = "failed"
            if self._db:
                await asyncio.to_thread(self._db.update_scan, scan_id, status="failed")
            return

        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return
            if symbols_override is None:
                scan["total"] = len(symbols)
            scan["total_batches"] = (len(symbols) + _BATCH_SIZE - 1) // _BATCH_SIZE

        if self._db and symbols_override is None:
            await asyncio.to_thread(self._db.update_scan, scan_id, total=len(symbols))

        sem = asyncio.Semaphore(_BATCH_SIZE)
        scan_error = False

        async def _process_ticker(ticker: str) -> None:
            async with sem:
                async with self._lock:
                    s = self._scans.get(scan_id)
                    if not s or s["cancel"]:
                        return
                    s["current_tickers"] = list(set(s["current_tickers"]) | {ticker})

                try:
                    await self._run_single(scan_id, ticker)
                finally:
                    async with self._lock:
                        s = self._scans.get(scan_id)
                        if s:
                            tickers = s["current_tickers"]
                            if ticker in tickers:
                                tickers.remove(ticker)

        try:
            tasks = [asyncio.create_task(_process_ticker(t)) for t in symbols]
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Scan %s error: %s", scan_id, e, exc_info=True)
            scan_error = True

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        final_status = "failed" if scan_error else "completed"
        final_completed = 0
        final_failed = 0
        async with self._lock:
            scan = self._scans.get(scan_id)
            if scan:
                if scan_error:
                    scan["status"] = "failed"
                elif scan["cancel"]:
                    scan["status"] = "cancelled"
                else:
                    scan["status"] = "completed"
                scan["completed_at"] = now
                scan["current_tickers"] = []
                scan["task"] = None
                final_status = scan["status"]
                final_completed = scan["completed"]
                final_failed = scan["failed"]

        if self._db:
            await asyncio.to_thread(
                self._db.update_scan, scan_id,
                status=final_status, completed_at=now,
                completed=final_completed, failed=final_failed,
            )

    async def _run_single(self, scan_id: str, ticker: str) -> None:
        """Launch one analysis, poll until done, collect result."""
        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan or scan["cancel"]:
                return
            config = scan["config"]

        request = {
            "ticker": ticker,
            "analysis_date": config.get("analysis_date"),
            "asset_type": config.get("asset_type", "crypto"),
            "interval": config.get("interval", "D"),
            "provider": config.get("provider"),
            "llm_api_key": config.get("llm_api_key"),
            "deep_think_llm": config.get("deep_think_llm"),
            "quick_think_llm": config.get("quick_think_llm"),
            "backend_url": config.get("backend_url"),
            "analysts": config.get("analysts"),
            "research_depth": config.get("research_depth"),
            "output_language": config.get("output_language"),
            "max_debate_rounds": config.get("max_debate_rounds"),
            "max_risk_discuss_rounds": config.get("max_risk_discuss_rounds"),
            "max_recur_limit": config.get("max_recur_limit"),
            "checkpoint_enabled": config.get("checkpoint_enabled"),
            "data_vendors": config.get("data_vendors"),
        }

        try:
            run_id = await self._analysis.start_analysis(request)
        except Exception as e:
            logger.warning("Failed to start analysis for %s: %s", ticker, e)
            fail_result = {
                "ticker": ticker,
                "run_id": None,
                "status": "failed",
                "direction": "unknown",
                "confidence": "none",
                "score": 0,
                "decision_summary": f"Failed to start: {e}",
            }
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["failed"] += 1
                    scan["results"].append(fail_result)
            if self._db:
                await asyncio.to_thread(self._db.insert_scan_result, scan_id, fail_result)
            return

        while True:
            async with self._lock:
                scan = self._scans.get(scan_id)
                should_cancel = not scan or scan["cancel"]

            if should_cancel:
                await self._analysis.cancel_analysis(run_id)
                cancel_result = {
                    "ticker": ticker,
                    "run_id": run_id,
                    "status": "cancelled",
                    "direction": "unknown",
                    "confidence": "none",
                    "score": 0,
                    "decision_summary": "Cancelled",
                }
                async with self._lock:
                    scan = self._scans.get(scan_id)
                    if scan:
                        scan["failed"] += 1
                        scan["results"].append(cancel_result)
                if self._db:
                    await asyncio.to_thread(self._db.insert_scan_result, scan_id, cancel_result)
                return

            await asyncio.sleep(_POLL_INTERVAL)

            try:
                run = await self._analysis.get_run(run_id)
                if not run or run.get("status") in _TERMINAL_STATUSES:
                    await self._collect_result(scan_id, ticker, run_id, run)
                    return
            except Exception:
                async with self._lock:
                    scan = self._scans.get(scan_id)
                    if scan:
                        scan["failed"] += 1
                return

    async def _collect_result(
        self, scan_id: str, ticker: str, run_id: str, run: Optional[Dict[str, Any]]
    ) -> None:
        """Parse the completed run's decision and add to results."""
        status = (run or {}).get("status", "failed")
        reports: Dict[str, str] = {}
        decision_text = ""

        if status == "completed":
            try:
                snapshot = await self._analysis.get_snapshot(run_id)
                if snapshot:
                    reports = snapshot.get("reports", {})
                    decision_text = reports.get("final_trade_decision", "") or reports.get("portfolio_manager", "")
            except Exception:
                pass

            if not decision_text:
                try:
                    report = await self._analysis.get_report(run_id)
                    if report:
                        decision_text = report
                except Exception:
                    pass

        signal = _parse_signal_from_reports(reports) if reports else _parse_signal_from_reports({"final_trade_decision": decision_text})

        result = {
            "ticker": ticker,
            "run_id": run_id,
            "status": status,
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "decision_summary": decision_text[:500] if decision_text else "",
        }

        async with self._lock:
            scan = self._scans.get(scan_id)
            if scan:
                if status == "completed":
                    scan["completed"] += 1
                else:
                    scan["failed"] += 1
                scan["results"].append(result)

        if self._db:
            await asyncio.to_thread(self._db.insert_scan_result, scan_id, result)
            count_field = "completed" if status == "completed" else "failed"
            await asyncio.to_thread(self._db.increment_scan_counter, scan_id, count_field)
