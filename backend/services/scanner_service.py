"""Scanner service — orchestrates batch analysis of all available symbols."""

from __future__ import annotations

import asyncio
import json as _json
import logging
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.analysis_service import ConcurrencyLimitError

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10  # default; overridden by config max_parallel (1–25)
_MAX_PARALLEL_CAP = 25
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

_VALID_DIRECTIONS = frozenset({"buy", "sell", "hold"})
_VALID_CONFIDENCES = frozenset({"high", "moderate", "low", "none"})

# ─────────────────────────────────────────────────────────────────────────────
# Signal extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_trader_signal(trader_text: str) -> Optional[Dict[str, Any]]:
    """Parse trader's structured JSON output.

    Returns dict with keys: direction, confidence_score (int 1-10), no_trade (bool).
    Returns None if no valid structured data found — never falls back to regex.
    """
    if not trader_text:
        return None

    # Try direct JSON parse first (stream_parser now emits proper JSON for dicts)
    try:
        data = _json.loads(trader_text)
        if isinstance(data, dict) and "trade_type" in data:
            return _decode_trader_dict(data)
    except (_json.JSONDecodeError, ValueError):
        pass

    # Try to extract an embedded JSON object containing trade_type
    # Use a broader pattern that allows nested objects
    for match in re.finditer(r'\{[^{}]*"trade_type"[^{}]*\}', trader_text, re.DOTALL):
        try:
            data = _json.loads(match.group())
            return _decode_trader_dict(data)
        except (_json.JSONDecodeError, ValueError):
            continue

    return None


def _decode_trader_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    tt = str(data.get("trade_type", "")).lower().strip()
    if tt in ("long", "buy"):
        direction = "buy"
        no_trade = False
    elif tt in ("short", "sell"):
        direction = "sell"
        no_trade = False
    elif tt in ("no trade", "no_trade", "hold", "neutral", "none", "pass", ""):
        direction = "hold"
        no_trade = True
    else:
        direction = "hold"
        no_trade = True

    raw_conf = data.get("confidence")
    if isinstance(raw_conf, (int, float)) and 1 <= raw_conf <= 10:
        conf_score = int(raw_conf)
    else:
        conf_score = None

    return {"direction": direction, "no_trade": no_trade, "confidence_score": conf_score}


def _extract_pm_signal(pm_text: str) -> Optional[Dict[str, Any]]:
    """Parse portfolio manager's structured decision text.

    Returns dict with: direction, confidence_score (int|None), definitive (bool).
    Returns None if no structured decision block found.
    Never runs on bulk analyst narrative text.
    """
    if not pm_text:
        return None

    # Only search within the last 3000 chars where the decision summary appears
    search_text = pm_text[-3000:].lower()

    # Use findall to collect ALL occurrences, then take the LAST one.
    # Multi-round risk discussions can produce intermediate "final decision:" lines;
    # the last one is the authoritative conclusion.
    all_matches = list(re.finditer(r"final\s+decision\s*:\s*(approve|reject|modify)", search_text))
    if not all_matches:
        return None

    decision_match = all_matches[-1]
    pm_decision = decision_match.group(1)

    if pm_decision == "reject":
        return {"direction": "hold", "no_trade": True, "confidence_score": None, "definitive": True}

    # For APPROVE or MODIFY: find direction word within 500 chars after the decision marker
    decision_pos = decision_match.start()
    window = search_text[decision_pos: decision_pos + 500]
    dir_match = re.search(
        r"\b(long|short|buy|sell|no\s+trade|no_trade)\b",
        window,
    )
    if not dir_match:
        return None

    d = dir_match.group(1).strip()
    if d in ("no trade", "no_trade"):
        return {"direction": "hold", "no_trade": True, "confidence_score": None, "definitive": True}

    direction = "buy" if d in ("long", "buy") else "sell"

    # Try to extract confidence from the decision window (e.g. "confidence: 7/10")
    conf_score = None
    conf_match = re.search(r"confidence[:\s]+(\d+)\s*(?:/\s*10)?", window)
    if conf_match:
        v = int(conf_match.group(1))
        if 0 <= v <= 10:  # 0 = explicitly zero confidence
            conf_score = v

    return {"direction": direction, "no_trade": False, "confidence_score": conf_score, "definitive": True}


def _validate_signal_consistency(
    trader: Optional[Dict[str, Any]],
    pm: Optional[Dict[str, Any]],
) -> str:
    """Cross-check trader and PM signals.

    Returns: 'consistent', 'pm_overrides', 'conflict', 'trader_only', 'pm_only', or 'no_data'.
    'conflict' means the directions differ (PM still wins, but this should be logged).
    'pm_overrides' means trader said no-trade and PM approved a direction (or vice-versa directionally).
    """
    if trader is None and pm is None:
        return "no_data"
    if trader is None:
        return "pm_only"
    if pm is None:
        return "trader_only"

    t_dir = trader["direction"]
    p_dir = pm["direction"]

    if t_dir == p_dir:
        return "consistent"

    # Directions differ — this is always worth logging
    if t_dir in ("buy", "sell") and p_dir in ("buy", "sell") and t_dir != p_dir:
        # Trader said buy, PM said sell (or vice-versa) — direct contradiction
        return "conflict"

    # One said trade (buy/sell), the other said hold — PM overrides
    return "pm_overrides"


def _rating_to_direction(rating: str) -> str:
    """Map 5-tier PortfolioRating string to 3-tier scanner direction."""
    r = rating.lower().strip()
    if r in ("buy", "overweight"):
        return "buy"
    if r in ("sell", "underweight"):
        return "sell"
    return "hold"


def _extract_signal_from_structured(
    pm_data: Dict[str, Any],
    trader_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a validated signal dict from pre-parsed structured agent output.

    pm_data: dict from PortfolioDecision.model_dump() — keys: rating, confidence, ...
    trader_data: dict from TraderProposal.model_dump() — keys: action, confidence, ...
    """
    rating = str(pm_data.get("rating") or "Hold")
    direction = _rating_to_direction(rating)

    if direction == "hold":
        return {"direction": "hold", "confidence": "none", "score": 0}

    # PM confidence is authoritative; fall back to trader's if absent
    pm_conf = pm_data.get("confidence")
    conf_score = pm_conf if pm_conf is not None else trader_data.get("confidence")
    if conf_score is None:
        conf_score = 5  # neutral default when direction is known but conviction isn't
    conf_score = max(1, min(10, int(conf_score)))

    if conf_score >= 7:
        confidence = "high"
    elif conf_score >= 4:
        confidence = "moderate"
    else:
        confidence = "low"

    sign = 1 if direction == "buy" else -1
    score = sign * conf_score

    return {"direction": direction, "confidence": confidence, "score": score}


def _parse_signal_from_reports(reports: Dict[str, str]) -> Dict[str, Any]:
    """Extract a validated trading signal from structured agent outputs.

    Design principles:
    - Structured JSON/pattern data only; no keyword regex on narrative text.
    - PM decision is authoritative and overrides trader.
    - If sources conflict, log a warning and use PM (conservative choice).
    - If no structured data exists, return hold/none/0 — never guess.
    - All outputs are validated against allowed value sets before returning.
    """
    trader_text = reports.get("trader", "")
    pm_text = reports.get("portfolio_manager", "") or reports.get("final_trade_decision", "")

    trader_signal = _extract_trader_signal(trader_text)
    pm_signal = _extract_pm_signal(pm_text)

    consistency = _validate_signal_consistency(trader_signal, pm_signal)

    if consistency == "conflict":
        logger.warning(
            "Signal CONFLICT: trader=%s pm=%s — PM wins (conservative)",
            trader_signal["direction"] if trader_signal else None,
            pm_signal["direction"] if pm_signal else None,
        )
    elif consistency == "pm_overrides":
        logger.info(
            "PM overrides trader: trader=%s → pm=%s",
            trader_signal["direction"] if trader_signal else None,
            pm_signal["direction"] if pm_signal else None,
        )

    # If PM text exists but couldn't be parsed, fall back to the trader signal rather than
    # suppressing it entirely. The PM's unparseable narrative may still agree with the trader;
    # silencing a valid structured trader signal is too aggressive. Only suppress if the PM
    # text contains explicit rejection language (conservative guard against known rejections).
    pm_text = reports.get("portfolio_manager", "") or reports.get("final_trade_decision", "")
    if pm_text and pm_signal is None:
        pm_lower = pm_text[-1500:].lower()
        if re.search(r"\b(reject|do not trade|no trade|do not proceed)\b", pm_lower):
            logger.warning(
                "PM text contains rejection language but no structured decision — returning hold/none/0"
            )
            return {"direction": "hold", "confidence": "none", "score": 0}
        logger.info(
            "PM text present but no structured decision found — falling back to trader signal"
        )
        # Fall through: pm_signal remains None, trader_signal used below

    # Resolve direction — PM is authoritative
    if pm_signal is not None:
        direction = pm_signal["direction"]
        conf_score = pm_signal.get("confidence_score")
        # If PM approved but didn't give a confidence, fall back to trader's confidence
        if conf_score is None and trader_signal is not None:
            conf_score = trader_signal.get("confidence_score")
    elif trader_signal is not None:
        direction = trader_signal["direction"]
        conf_score = trader_signal.get("confidence_score")
    else:
        # No structured data at all — return a safe hold with score 0
        logger.warning("No structured signal data found in reports — returning hold/none/0")
        return {"direction": "hold", "confidence": "none", "score": 0}

    # No-trade cases always return 0
    is_no_trade = (
        (pm_signal is not None and pm_signal.get("no_trade"))
        or (pm_signal is None and trader_signal is not None and trader_signal.get("no_trade"))
    )
    if is_no_trade:
        return {"direction": "hold", "confidence": "none", "score": 0}

    # Map confidence score to label
    if conf_score is None:
        conf_score = 5  # middle ground when direction is known but confidence isn't specified
    conf_score = max(1, min(10, int(conf_score)))

    if conf_score >= 7:
        confidence = "high"
    elif conf_score >= 4:
        confidence = "moderate"
    else:
        confidence = "low"

    sign = 1 if direction == "buy" else (-1 if direction == "sell" else 0)
    score = sign * conf_score

    # Final safety validation — reject any value not in the allowed sets
    if direction not in _VALID_DIRECTIONS:
        logger.error("Invalid direction value %r — forcing hold", direction)
        return {"direction": "hold", "confidence": "none", "score": 0}
    if confidence not in _VALID_CONFIDENCES:
        logger.error("Invalid confidence value %r — forcing none", confidence)
        confidence = "none"

    return {"direction": direction, "confidence": confidence, "score": score}



class ScannerBusyError(Exception):
    pass


class ScannerService:
    def __init__(self, analysis_service: Any, db: Any = None):
        self._analysis = analysis_service
        self._db = db
        self._scans: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def start_scan(self, config: Dict[str, Any], schedule_id: str | None = None, triggered_by: str = "manual") -> str:
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
            await self._db.insert_scan(
                {"scan_id": scan_id, "status": "running", "config": _json.dumps(config), "started_at": now,
                 "schedule_id": schedule_id, "triggered_by": triggered_by},
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
            db_scan = await self._db.get_scan(scan_id)
            if db_scan:
                return self._serialize_db(db_scan)
        return None

    async def cancel_scan(self, scan_id: str) -> bool:
        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan or scan["status"] != "running":
                return False
            scan["cancel"] = True
            task = scan.get("task")
            if task and not task.done():
                task.cancel()
        if self._db:
            await self._db.update_scan(scan_id, status="cancelled")
        return True

    async def shutdown(self) -> None:
        """Cancel all running scans and wait for tasks to finish."""
        async with self._lock:
            scan_ids = list(self._scans.keys())
        for scan_id in scan_ids:
            await self.cancel_scan(scan_id)
        # Wait for background tasks to complete
        async with self._lock:
            tasks = [s.get("task") for s in self._scans.values() if s.get("task") and not s["task"].done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def delete_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            scan = self._scans.get(scan_id)
            if scan and scan["status"] == "running":
                raise ScannerBusyError("Cannot delete a running scan — cancel it first")
            self._scans.pop(scan_id, None)
        if not self._db:
            return {"deleted_results": 0, "deleted_analyses": 0, "deleted_sections": 0}
        result = await self._db.delete_scan(scan_id)
        if not result:
            return None
        return result

    async def get_scan_analysis_count(self, scan_id: str) -> int:
        if not self._db:
            return 0
        return await self._db.get_scan_analysis_count(scan_id)

    async def list_scans(self) -> List[Dict[str, Any]]:
        async with self._lock:
            in_memory_ids = set(self._scans.keys())
            result = [self._serialize(s) for s in self._scans.values()]
        if self._db:
            db_scans = await self._db.list_scans()
            for ds in db_scans:
                if ds["scan_id"] not in in_memory_ids:
                    result.append(self._serialize_db(ds))
        return result

    async def resume_incomplete_scans(self) -> int:
        if not self._db:
            return 0
        running = await self._db.get_running_scans()
        resumed = 0
        for db_scan in running:
            if resumed >= 1:
                await self._db.update_scan(db_scan["scan_id"], status="failed")
                logger.warning("Marking extra stale scan %s as failed (only 1 resumed at a time)", db_scan["scan_id"])
                continue
            scan_id = db_scan["scan_id"]
            try:
                import json as _json
                config = _json.loads(db_scan.get("config", "{}"))
            except Exception:
                config = {}

            done_tickers = await self._db.get_scan_completed_tickers(scan_id)
            db_results = await self._db.get_scan(scan_id)
            existing_results = (db_results or {}).get("results", [])

            try:
                from tradingagents.dataflows.bybit_data import get_valid_symbols
                all_symbols = random.sample(syms := list(await asyncio.to_thread(get_valid_symbols)), len(syms))
            except Exception as e:
                logger.error("Failed to fetch symbols for resume of %s: %s", scan_id, e)
                await self._db.update_scan(scan_id, status="failed")
                continue

            remaining = [s for s in all_symbols if s not in done_tickers]
            if not remaining:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                await self._db.update_scan(scan_id, status="completed", completed_at=now)
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
        results = scan["results"]
        sorted_results = sorted(results, key=lambda r: abs(r.get("score", 0)), reverse=True)
        counts: Dict[str, int] = {}
        for r in results:
            d = r.get("direction", "unknown")
            counts[d] = counts.get(d, 0) + 1
        config = scan.get("config", {})
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
            "direction_counts": counts,
            "started_at": scan["started_at"],
            "completed_at": scan["completed_at"],
            "interval": config.get("interval"),
            "asset_type": config.get("asset_type"),
            "provider": config.get("provider"),
            "workflow_mode": config.get("workflow_mode"),
            "deep_think_llm": config.get("deep_think_llm"),
            "quick_think_llm": config.get("quick_think_llm"),
            "backend_url": config.get("backend_url"),
            "research_depth": config.get("research_depth"),
            "max_debate_rounds": config.get("max_debate_rounds"),
        }

    def _serialize_db(self, scan: Dict[str, Any]) -> Dict[str, Any]:
        import json as _json
        config = scan.get("config", {})
        if isinstance(config, str):
            try:
                config = _json.loads(config)
            except Exception:
                config = {}
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
            "direction_counts": scan.get("direction_counts", {}),
            "started_at": scan.get("started_at", ""),
            "completed_at": scan.get("completed_at"),
            "interval": config.get("interval"),
            "asset_type": config.get("asset_type"),
            "provider": config.get("provider"),
            "workflow_mode": config.get("workflow_mode"),
            "deep_think_llm": config.get("deep_think_llm"),
            "quick_think_llm": config.get("quick_think_llm"),
            "backend_url": config.get("backend_url"),
            "research_depth": config.get("research_depth"),
            "max_debate_rounds": config.get("max_debate_rounds"),
        }

    async def _run_scan(self, scan_id: str, symbols_override: Optional[List[str]] = None) -> None:
        try:
            if symbols_override is not None:
                symbols = symbols_override
            else:
                from tradingagents.dataflows.bybit_data import get_valid_symbols
                symbols = random.sample(syms := list(await asyncio.to_thread(get_valid_symbols)), len(syms))
        except Exception as e:
            logger.error("Failed to fetch symbols for scan %s: %s", scan_id, e)
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["status"] = "failed"
            if self._db:
                await self._db.update_scan(scan_id, status="failed")
            return

        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return
            batch_size = min(int(scan["config"].get("max_parallel", _BATCH_SIZE) or _BATCH_SIZE), _MAX_PARALLEL_CAP)
            if symbols_override is None:
                scan["total"] = len(symbols)
            scan["total_batches"] = (len(symbols) + batch_size - 1) // batch_size

        if self._db and symbols_override is None:
            await self._db.update_scan(scan_id, total=len(symbols))

        # Only prefetch CoinGecko data when fundamentals/social analysts are selected
        async with self._lock:
            scan = self._scans.get(scan_id)
        scan_analysts = (scan["config"].get("analysts") if scan else None) or []
        _COINGECKO_ANALYSTS = {"crypto_fundamentals", "crypto_social"}
        needs_coingecko = not scan_analysts or _COINGECKO_ANALYSTS.intersection(scan_analysts)

        if needs_coingecko:
            try:
                from tradingagents.dataflows.coingecko_data import prefetch_fundamentals
                await asyncio.to_thread(prefetch_fundamentals, symbols)
            except Exception:
                logger.warning("CoinGecko prefetch failed, analyses will use individual calls", exc_info=True)
        else:
            logger.debug("Skipping CoinGecko prefetch — no fundamentals/social analysts selected")

        sem = asyncio.Semaphore(min(batch_size, self._analysis.max_concurrent))
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
            await self._db.update_scan(
                scan_id,
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
            "workflow_mode": config.get("workflow_mode"),
            "agent_model_overrides": config.get("agent_model_overrides"),
            "ta_prefilter_enabled": config.get("ta_prefilter_enabled"),
            "ta_prefilter_threshold": config.get("ta_prefilter_threshold"),
            "llm_max_concurrent": config.get("llm_max_concurrent"),
            "llm_min_spacing_ms": config.get("llm_min_spacing_ms"),
        }

        try:
            run_id: Optional[str] = None
            for attempt in range(3):
                async with self._lock:
                    s = self._scans.get(scan_id)
                    if not s or s["cancel"]:
                        return
                try:
                    run_id = await self._analysis.start_analysis(request)
                    break
                except ConcurrencyLimitError:
                    if attempt < 2:
                        await asyncio.sleep(5 + random.uniform(0, 3))
                        continue
                    raise
        except Exception as e:
            logger.warning("Failed to start analysis for %s: %s", ticker, e)
            fail_result = {
                "ticker": ticker,
                "run_id": None,
                "status": "failed",
                "direction": "hold",
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
                await self._db.insert_scan_result(scan_id, fail_result)
            return

        # Event-based wait with cancellation awareness
        try:
            run = await self._analysis.wait_for_completion(run_id, timeout=1860)
        except asyncio.CancelledError:
            # Scan was cancelled while waiting — propagate cancellation to analysis
            await self._analysis.cancel_analysis(run_id)
            cancel_result = {
                "ticker": ticker,
                "run_id": run_id,
                "status": "cancelled",
                "direction": "hold",
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
                await self._db.insert_scan_result(scan_id, cancel_result)
                await self._db.increment_scan_counter(scan_id, "failed")
            return
        except Exception:
            run = None

        # Check if scan was cancelled while we waited — only discard if analysis didn't complete
        if run and run.get("status") in _TERMINAL_STATUSES:
            await self._collect_result(scan_id, ticker, run_id, run)
            return

        async with self._lock:
            scan = self._scans.get(scan_id)
            should_cancel = not scan or scan["cancel"]

        if should_cancel:
            await self._analysis.cancel_analysis(run_id)
            cancel_result = {
                "ticker": ticker,
                "run_id": run_id,
                "status": "cancelled",
                "direction": "hold",
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
                await self._db.insert_scan_result(scan_id, cancel_result)
                await self._db.increment_scan_counter(scan_id, "failed")
            return

        if not run:
            poll_fail_result = {
                "ticker": ticker, "run_id": run_id,
                "status": "failed", "direction": "hold",
                "confidence": "none", "score": 0,
                "decision_summary": "Timeout waiting for completion",
            }
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["failed"] += 1
                    scan["results"].append(poll_fail_result)
            if self._db:
                await self._db.insert_scan_result(scan_id, poll_fail_result)
                await self._db.increment_scan_counter(scan_id, "failed")

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
                    decision_text = (
                        reports.get("portfolio_manager", "")
                        or reports.get("trader", "")
                        or reports.get("final_trade_decision", "")
                    )
                    if not decision_text and reports.get("_ta_prefilter"):
                        try:
                            pf = _json.loads(reports["_ta_prefilter"])
                            decision_text = pf.get("reason", reports["_ta_prefilter"])
                        except (_json.JSONDecodeError, TypeError):
                            decision_text = reports["_ta_prefilter"]
            except Exception:
                logger.exception("Failed to fetch snapshot for %s/%s", scan_id, run_id)

            if not decision_text:
                try:
                    report = await self._analysis.get_report(run_id)
                    if report:
                        decision_text = report
                except Exception:
                    pass

        if status == "completed" and reports:
            # TA prefilter-skipped runs have no agent signals — short-circuit
            if reports.get("_ta_prefilter") and not reports.get("_pm_signal") and not reports.get("_trader_signal"):
                signal = {"direction": "hold", "confidence": "none", "score": 0}
                signal_source = "ta_prefilter"
            elif (pm_json := reports.get("_pm_signal")):
                trader_json = reports.get("_trader_signal")
                try:
                    pm_data = _json.loads(pm_json)
                    trader_data = _json.loads(trader_json) if trader_json else {}
                    signal = _extract_signal_from_structured(pm_data, trader_data)
                    signal_source = "structured"
                except Exception:
                    logger.exception(
                        "Failed to parse structured signal JSON for %s/%s — falling back",
                        scan_id, run_id,
                    )
                    signal = _parse_signal_from_reports(reports)
                    signal_source = "regex_fallback"
            elif reports.get("_trader_signal"):
                signal = _parse_signal_from_reports(reports)
                signal_source = "regex_fallback"
            else:
                signal = _parse_signal_from_reports(reports)
                signal_source = "regex_fallback"
        else:
            signal = {"direction": "hold", "confidence": "none", "score": 0}
            signal_source = "none"
            if not decision_text:
                decision_text = (run or {}).get("error", "") or ""

        result = {
            "ticker": ticker,
            "run_id": run_id,
            "status": status,
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "decision_summary": decision_text[:500] if decision_text else "",
            "signal_source": signal_source,
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
            await self._db.insert_scan_result(scan_id, result)
            count_field = "completed" if status == "completed" else "failed"
            await self._db.increment_scan_counter(scan_id, count_field)
