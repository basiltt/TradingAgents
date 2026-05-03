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


def _parse_signal(decision: str) -> Dict[str, Any]:
    """Parse final_trade_decision text into direction, confidence, and numeric score (1-10)."""
    if not decision:
        return {"direction": "hold", "confidence": "low", "score": 0}

    text = decision.lower()

    direction = "hold"
    if re.search(r"\b(buy|long|bullish)\b", text):
        direction = "buy"
    elif re.search(r"\b(sell|short|bearish)\b", text):
        direction = "sell"

    confidence = "low"
    conf_score = 2
    if re.search(r"\b(very\s+high|extremely|exceptional|overwhelming)\b", text):
        confidence = "high"
        conf_score = 10
    elif re.search(r"\b(strong|high)\b", text):
        confidence = "high"
        conf_score = 8
    elif re.search(r"\b(moderate|medium|moderately)\b", text):
        confidence = "moderate"
        conf_score = 5

    pct_match = re.search(r"(\d{1,3})\s*%", text)
    if pct_match:
        pct = int(pct_match.group(1))
        if 0 < pct <= 100:
            conf_score = max(conf_score, round(pct / 10))

    conf_score = max(1, min(10, conf_score))

    sign = 1 if direction == "buy" else (-1 if direction == "sell" else 0)
    score = sign * conf_score

    return {"direction": direction, "confidence": confidence, "score": score}


class ScannerBusyError(Exception):
    pass
class ScannerService:
    def __init__(self, analysis_service: Any):
        self._analysis = analysis_service
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

        task = asyncio.create_task(self._run_scan(scan_id))
        async with self._lock:
            if scan_id in self._scans:
                self._scans[scan_id]["task"] = task

        return scan_id

    async def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return None
            return self._serialize(scan)

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
            return [self._serialize(s) for s in self._scans.values()]

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

    async def _run_scan(self, scan_id: str) -> None:
        try:
            from tradingagents.dataflows.bybit_data import get_valid_symbols
            symbols = sorted(await asyncio.to_thread(get_valid_symbols))
        except Exception as e:
            logger.error("Failed to fetch symbols for scan %s: %s", scan_id, e)
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["status"] = "failed"
            return

        batches = [symbols[i:i + _BATCH_SIZE] for i in range(0, len(symbols), _BATCH_SIZE)]

        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return
            scan["total"] = len(symbols)
            scan["total_batches"] = len(batches)

        scan_error = False
        try:
            for batch_idx, batch in enumerate(batches):
                async with self._lock:
                    scan = self._scans.get(scan_id)
                    if not scan or scan["cancel"]:
                        break
                    scan["current_batch"] = batch_idx + 1
                    scan["current_tickers"] = list(batch)

                run_ids = await self._launch_batch(scan_id, batch)
                await self._wait_for_batch(scan_id, run_ids, batch)

                async with self._lock:
                    scan = self._scans.get(scan_id)
                    if scan and scan["cancel"]:
                        break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Scan %s error: %s", scan_id, e, exc_info=True)
            scan_error = True

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
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

    async def _launch_batch(self, scan_id: str, tickers: List[str]) -> Dict[str, str]:
        """Launch analyses for a batch of tickers. Returns {ticker: run_id}."""
        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return {}
            config = scan["config"]

        run_ids: Dict[str, str] = {}
        for ticker in tickers:
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan and scan["cancel"]:
                    break

            request = {
                "ticker": ticker,
                "analysis_date": config.get("analysis_date"),
                "asset_type": config.get("asset_type", "crypto"),
                "interval": config.get("interval", "D"),
                "provider": config.get("provider"),
                "deep_think_llm": config.get("deep_think_llm"),
                "quick_think_llm": config.get("quick_think_llm"),
                "backend_url": config.get("backend_url"),
                "analysts": config.get("analysts"),
                "research_depth": config.get("research_depth"),
                "output_language": config.get("output_language"),
                "data_vendors": config.get("data_vendors"),
            }

            try:
                run_id = await self._analysis.start_analysis(request)
                run_ids[ticker] = run_id
            except Exception as e:
                logger.warning("Failed to start analysis for %s: %s", ticker, e)
                async with self._lock:
                    scan = self._scans.get(scan_id)
                    if scan:
                        scan["failed"] += 1
                        scan["results"].append({
                            "ticker": ticker,
                            "run_id": None,
                            "status": "failed",
                            "direction": "unknown",
                            "confidence": "none",
                            "score": 0,
                            "decision_summary": f"Failed to start: {e}",
                        })

        return run_ids

    async def _wait_for_batch(self, scan_id: str, run_ids: Dict[str, str], tickers: List[str]) -> None:
        """Poll until all runs in the batch are terminal, then collect results."""
        pending = dict(run_ids)

        while pending:
            async with self._lock:
                scan = self._scans.get(scan_id)
                if not scan or scan["cancel"]:
                    for ticker, rid in pending.items():
                        await self._analysis.cancel_analysis(rid)
                    async with self._lock:
                        scan = self._scans.get(scan_id)
                        if scan:
                            for ticker, rid in pending.items():
                                scan["failed"] += 1
                                scan["results"].append({
                                    "ticker": ticker,
                                    "run_id": rid,
                                    "status": "cancelled",
                                    "direction": "unknown",
                                    "confidence": "none",
                                    "score": 0,
                                    "decision_summary": "Cancelled",
                                })
                    return

            await asyncio.sleep(_POLL_INTERVAL)

            done_tickers = []
            for ticker, rid in list(pending.items()):
                try:
                    run = await self._analysis.get_run(rid)
                    if not run or run.get("status") in _TERMINAL_STATUSES:
                        done_tickers.append(ticker)
                        await self._collect_result(scan_id, ticker, rid, run)
                except Exception:
                    done_tickers.append(ticker)
                    async with self._lock:
                        scan = self._scans.get(scan_id)
                        if scan:
                            scan["failed"] += 1

            for t in done_tickers:
                pending.pop(t, None)

    async def _collect_result(
        self, scan_id: str, ticker: str, run_id: str, run: Optional[Dict[str, Any]]
    ) -> None:
        """Parse the completed run's decision and add to results."""
        status = (run or {}).get("status", "failed")
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

        signal = _parse_signal(decision_text)

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
