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

from backend.services.analysis_service import ConcurrencyLimitError, DEFAULT_MAX_CONCURRENT
from backend.services.auto_trade_service import AutoTradeExecutor

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10  # default; overridden by config max_parallel (1–15)
_MAX_PARALLEL_CAP = 15
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

_VALID_DIRECTIONS = frozenset({"buy", "sell", "hold"})
_VALID_CONFIDENCES = frozenset({"high", "moderate", "low", "none"})

# ─────────────────────────────────────────────────────────────────────────────
# Signal extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_signal(direction: str, conf_score: Optional[int]) -> Dict[str, Any]:
    """Build a normalized signal dict from direction + raw confidence score."""
    if direction == "hold":
        return {"direction": "hold", "confidence": "none", "score": 0}
    if conf_score is None:
        conf_score = 5
    try:
        conf_score = max(1, min(10, int(conf_score)))
    except (TypeError, ValueError):
        conf_score = 5
    if conf_score >= 7:
        confidence = "high"
    elif conf_score >= 4:
        confidence = "moderate"
    else:
        confidence = "low"
    sign = 1 if direction == "buy" else (-1 if direction == "sell" else 0)
    return {"direction": direction, "confidence": confidence, "score": sign * conf_score}


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

    return _build_signal(direction, conf_score)


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

    signal = _build_signal(direction, conf_score)

    # Final safety validation — reject any value not in the allowed sets
    if signal["direction"] not in _VALID_DIRECTIONS:
        logger.error("Invalid direction value %r — forcing hold", signal["direction"])
        return {"direction": "hold", "confidence": "none", "score": 0}
    if signal["confidence"] not in _VALID_CONFIDENCES:
        logger.error("Invalid confidence value %r — forcing none", signal["confidence"])
        signal["confidence"] = "none"

    return signal



class ScannerBusyError(Exception):
    """Raised when a scan is already in progress for the target account."""
    pass


class ScannerService:
    """Orchestrates multi-symbol analysis scans using the analysis service.

    Manages scan lifecycle (start → progress → complete/cancel), persists results
    to DB, and broadcasts progress via WebSocket. Supports concurrent scans across
    different accounts with per-account locking.
    """

    SCAN_LIST_TOPIC = "__scan_list__"

    def __init__(self, analysis_service: Any, db: Any = None, ws_manager: Any = None, accounts_service: Any = None, close_positions_service: Any = None, ai_manager_service: Any = None, sector_service: Any = None, debug_recorder: Any = None, kline_cache: Any = None):
        self._analysis = analysis_service
        self._db = db
        self._ws = ws_manager
        self._accounts = accounts_service
        self._close_svc = close_positions_service
        self._ai_manager_service = ai_manager_service
        self._sector_service = sector_service
        self._debug_recorder = debug_recorder
        self._kline_cache = kline_cache  # for Regime Multi-Strategy BTC/MR-mean fetches
        self._scans: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def _notify_scan_list_changed(self) -> None:
        if self._ws:
            try:
                await self._ws.broadcast(self.SCAN_LIST_TOPIC, {"type": "scan_list_changed"})
            except Exception:
                pass

    async def _resolve_account_cohorts(self, auto_configs: List[Dict[str, Any]]) -> None:
        """Resolve each per-scan config's effective strategy_cohort (F3/FR-040).

        Tri-state: a None cfg cohort inherits the account's STORED
        trading_accounts.strategy_cohort (so the fleet-roster bulk-assign actually
        drives routing); an explicit per-scan value (incl "trend") overrides. Writes a
        CONCRETE value back so the executor never sees None. One batched list_accounts()
        lookup (not per-account get_account) so a default-off / trend-only fleet pays a
        single query, not N. Fail-soft: on a lookup error each cfg keeps its own value
        coerced to a concrete default. Mutates cfg in place, once per scan.
        """
        if not self._db:
            # No DB to read stored cohorts — still coerce None -> default so the
            # executor sees a concrete value.
            from backend.services.features import DEFAULT_COHORT as _default_cohort
            for cfg in auto_configs:
                if isinstance(cfg, dict):
                    cfg["strategy_cohort"] = cfg.get("strategy_cohort") or _default_cohort
            return
        from backend.services import features as _feat
        try:
            accounts = {a["id"]: a for a in await self._db.list_accounts()}
        except Exception:
            accounts = {}
        for cfg in auto_configs:
            if not isinstance(cfg, dict):
                continue
            stored = (accounts.get(cfg.get("account_id")) or {}).get("strategy_cohort")
            cfg["strategy_cohort"] = _feat.resolve_cohort(cfg.get("strategy_cohort"), stored)

    async def _set_executor_scan_context(self, executor, auto_configs: List[Dict[str, Any]]) -> None:
        """Read the kill-switch unconditionally + build the scan-time ScanContext and
        attach it to the executor. Safe no-op for the default (all-off) fleet."""
        from datetime import datetime, timezone
        from backend.services.kill_switch import read_kill_switches
        from backend.services import market_data as _md

        kill = await read_kill_switches(self._db) if self._db else {"__all__": True}

        # FR-065: evaluate the F2-long rolling-drawdown breaker BEFORE placement so a
        # trip disables live longs within this same scan (not just the next one). Only
        # runs for accounts that actually enable MR-long; fail-open per account.
        if self._db and not kill.get("__all__") and not kill.get("f2_long"):
            from backend.services import safety_monitors as _sm
            checked: set[str] = set()
            for cfg in auto_configs:
                acct = cfg.get("account_id")
                if (acct and acct not in checked
                        and cfg.get("mean_reversion_enabled") and cfg.get("mr_long_enabled")):
                    checked.add(acct)
                    try:
                        if await _sm.check_f2_long_breaker(self._db, acct):
                            kill["f2_long"] = True  # reflect the trip in this scan's view
                            break
                    except Exception:
                        logger.warning("f2_long_breaker_check_failed", exc_info=True)

        async def _fetch(symbol: str, interval: str, depth: int):
            # Adapt the kline cache to (symbol, interval, depth) -> list[kline].
            kc = getattr(self, "_kline_cache", None)
            if kc is None:
                return []
            try:
                from datetime import timedelta
                # Size the window from interval*depth (IR10) so non-default intervals
                # (4h/1d) still fetch enough candles, with generous margin.
                _mins = {"15m": 15, "1h": 60, "4h": 240}.get(interval, 60)
                span_min = max(_mins * (depth + 5), _mins * 35)
                end = datetime.now(timezone.utc)
                start = end - timedelta(minutes=span_min)
                klines = await kc.get_klines(symbol, interval, start, end)
                return klines[-depth:] if depth and len(klines) > depth else klines
            except Exception:
                return []

        ctx = await _md.build_scan_context(
            auto_configs, [], now=datetime.now(timezone.utc), kill=kill, fetcher=_fetch,
        )
        executor.set_scan_context(ctx)
        executor.set_mean_fetcher(_fetch)   # IR1: lazy MR mean source

    async def _compute_adaptive_blacklist(
        self,
        auto_configs: List[Dict[str, Any]],
        strategy_kind: str = "trend",
        *,
        require_mr: bool = False,
    ) -> set:
        """Query signal_performance for symbols with consistently poor win rates.

        FR-030: scoped per strategy by joining ``trades.strategy_kind`` so a
        mean-reversion losing streak feeds ONLY the MR blacklist and never the
        trend blacklist (and vice-versa). For all-trend historical data the
        ``strategy_kind='trend'`` join is identical to the legacy unscoped query
        (migration 44 backfilled every existing row to 'trend'), so default-off /
        trend-only behaviour is byte-identical. ``require_mr`` makes the MR scope
        opt in only when some config has ``mean_reversion_enabled``.
        """
        min_trades = 5
        max_win_rate = 30.0
        lookback_hours = 48
        for cfg in auto_configs:
            if cfg.get("adaptive_blacklist_enabled") and (not require_mr or cfg.get("mean_reversion_enabled")):
                min_trades = cfg.get("adaptive_blacklist_min_trades", 5)
                max_win_rate = cfg.get("adaptive_blacklist_max_win_rate", 30.0)
                lookback_hours = cfg.get("adaptive_blacklist_lookback_hours", 48)
                break
        else:
            return set()
        try:
            rows = await self._db.pool.fetch(
                "SELECT sp.symbol AS symbol, COUNT(*) AS total, "
                "SUM(CASE WHEN sp.is_win THEN 1 ELSE 0 END) AS wins "
                "FROM signal_performance sp "
                "JOIN trades t ON t.id = sp.trade_id "
                "WHERE sp.closed_at > NOW() - make_interval(hours => $1) "
                "AND t.strategy_kind = $3 "
                "GROUP BY sp.symbol HAVING COUNT(*) >= $2",
                lookback_hours, min_trades, strategy_kind,
            )
            blacklisted = set()
            for row in rows:
                win_rate = (row["wins"] / row["total"]) * 100 if row["total"] > 0 else 0
                if win_rate < max_win_rate:
                    blacklisted.add(row["symbol"])
            if blacklisted:
                logger.info("adaptive_blacklist_computed", extra={"strategy_kind": strategy_kind, "count": len(blacklisted), "symbols": sorted(blacklisted)[:10]})
            return blacklisted
        except Exception:
            logger.warning("adaptive_blacklist_query_failed", exc_info=True)
            return set()

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
            "auto_trade_executor": None,
            "auto_trade_results": [],
        }

        # Initialize auto-trade executor if configs provided
        auto_configs = config.get("auto_trade_configs")
        if auto_configs and self._accounts:
            # F3/FR-040: settle each account's effective cohort (stored field merged
            # under the per-scan override) BEFORE anything cohort-dependent runs.
            await self._resolve_account_cohorts(auto_configs)
            # Compute adaptive blacklist from signal_performance (pre-inject into configs)
            if self._db:
                adaptive_bl = await self._compute_adaptive_blacklist(auto_configs, "trend")
                if adaptive_bl:
                    for cfg in auto_configs:
                        if cfg.get("adaptive_blacklist_enabled"):
                            existing = set(cfg.get("_computed_adaptive_blacklist") or [])
                            cfg["_computed_adaptive_blacklist"] = list(existing | adaptive_bl)
                # FR-030: a separate MR-scoped blacklist so mean-reversion losses
                # never poison the trend blacklist (and vice-versa). Only computed
                # when some config runs MR; injected under a distinct key the
                # _try_trade gate reads on the fade path.
                mr_bl = await self._compute_adaptive_blacklist(auto_configs, "mean_reversion", require_mr=True)
                if mr_bl:
                    for cfg in auto_configs:
                        if cfg.get("adaptive_blacklist_enabled") and cfg.get("mean_reversion_enabled"):
                            existing = set(cfg.get("_computed_mr_adaptive_blacklist") or [])
                            cfg["_computed_mr_adaptive_blacklist"] = list(existing | mr_bl)
            # trigger_source: scan_scheduler calls start_scan(triggered_by="scheduled");
            # the API run-now path uses triggered_by="run_now"; manual default is "manual".
            _trigger = triggered_by if triggered_by in ("scheduled", "manual", "run_now") else "manual"
            # FR-066: a one-time "ignore session filter this scan" escape hatch. ONLY
            # honoured on a manual/run-now scan (never "scheduled", so a saved schedule
            # cannot smuggle a persistent bypass). It is stamped onto the per-scan config
            # copies, so it auto-reverts next scan (non-persistent). Overridden entries
            # record f1_active=False (truthful: F1 did not act) — SD20 keeps them OUT of
            # f1 before/after efficacy stats. Audit-logged for the operator trail.
            if config.get("session_filter_override") and _trigger in ("manual", "run_now"):
                try:
                    from backend.services import features as _feat
                    _n = _feat.apply_session_override(config, auto_configs, _trigger)
                    if _n:
                        logger.warning(
                            "f1_session_filter_override_engaged",
                            extra={"scan_id": scan_id, "trigger": _trigger, "accounts": _n},
                        )
                except Exception:
                    # An override-stamping fault must NEVER abort the scan / regress
                    # trend trading. Degrade to "no override" and proceed.
                    logger.warning("f1_session_filter_override_stamp_failed", exc_info=True)
            if self._debug_recorder is not None:
                debug_ctx = self._debug_recorder.new_run_context(
                    scan_id=scan_id,
                    trigger_source=_trigger,
                    schedule_id=schedule_id,
                )
            executor = AutoTradeExecutor(
                self._accounts, self._close_svc, self._ai_manager_service,
                sector_service=self._sector_service,
                recorder=self._debug_recorder, debug_ctx=debug_ctx,
                position_lock_registry=getattr(self, "_position_lock_registry", None),
            )
            # ── Regime Multi-Strategy: build the scan-time ScanContext ──
            # Kill-switch is read UNCONDITIONALLY (R3-F1) so master/per-feature kills
            # work even for fleets that never trigger precompute. build_scan_context
            # returns an empty (non-degraded) context when no regime feature is on,
            # so executor behavior is unchanged in the default case.
            try:
                await self._set_executor_scan_context(executor, auto_configs)
            except Exception:
                logger.warning("scan_context_setup_failed", exc_info=True)
                # C2: if context setup itself throws (before set_scan_context ran),
                # install a fail-CLOSED context so the master kill is honored and MR
                # stays disabled, rather than running on the permissive default.
                from backend.services.scan_context import ScanContext as _SC
                executor.set_scan_context(_SC.empty(degraded=True, kill={"__all__": True}))
            if self._debug_recorder is not None and debug_ctx is not None:
                await self._debug_recorder.open_run(
                    debug_ctx,
                    config_snapshot={"num_configs": len(auto_configs)},
                )
            executor.init_configs(auto_configs)
            await executor.init_balances()
            scan["auto_trade_executor"] = executor
            scan["debug_ctx"] = debug_ctx
        elif auto_configs and not self._accounts:
            logger.warning("auto_trade_configs provided but accounts service unavailable — ignoring")

        async with self._lock:
            self._scans[scan_id] = scan

        if self._db:
            await self._db.insert_scan(
                {"scan_id": scan_id, "status": "running", "config": _json.dumps(config), "started_at": now,
                 "schedule_id": schedule_id, "triggered_by": triggered_by},
            )

        task = asyncio.create_task(self._run_scan(scan_id))
        async with self._lock:
            if scan_id in self._scans:
                self._scans[scan_id]["task"] = task

        await self._notify_scan_list_changed()

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
            scan["status"] = "cancelled"
            scan["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            task = scan.get("task")
            if task and not task.done():
                task.cancel()
        if self._db:
            await self._db.update_scan(scan_id, status="cancelled", completed_at=scan["completed_at"])
        await self._notify_scan_list_changed()
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
            valid_tasks = [t for t in tasks if t is not None]
            if valid_tasks:
                await asyncio.gather(*valid_tasks, return_exceptions=True)

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
        await self._notify_scan_list_changed()
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
        result.sort(key=lambda s: s.get("started_at") or "", reverse=True)
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
                "auto_trade_executor": None,
                "auto_trade_results": [],
            }

            # Restore auto-trade executor on resume — use prior results to restore trade counters
            auto_configs = config.get("auto_trade_configs")
            if auto_configs and self._accounts:
                # F3/FR-040: settle stored cohort on resume too (parity with start path).
                await self._resolve_account_cohorts(auto_configs)
                # Pre-classify remaining symbols for sector service
                if self._sector_service:
                    try:
                        await self._sector_service.ensure_classified(remaining)
                    except Exception:
                        pass
                debug_ctx = None
                if self._debug_recorder is not None:
                    debug_ctx = self._debug_recorder.new_run_context(
                        scan_id=scan_id, trigger_source="scheduled", schedule_id=None,
                    )
                executor = AutoTradeExecutor(
                    self._accounts, self._close_svc, self._ai_manager_service,
                    sector_service=self._sector_service,
                    recorder=self._debug_recorder, debug_ctx=debug_ctx,
                    position_lock_registry=getattr(self, "_position_lock_registry", None),
                )
                # Regime Multi-Strategy: rebuild the ScanContext on resume too, else
                # MR would be silently inert (and the kill-switch unread) for resumed
                # scans. Fail-safe: a degraded context just keeps MR fail-closed.
                try:
                    await self._set_executor_scan_context(executor, auto_configs)
                except Exception:
                    logger.warning("scan_context_setup_failed_on_resume", exc_info=True)
                    from backend.services.scan_context import ScanContext as _SC
                    executor.set_scan_context(_SC.empty(degraded=True, kill={"__all__": True}))
                executor.init_configs(auto_configs)
                # Restore counters from already-executed trades stored in DB
                prior_auto_results = (db_results or {}).get("auto_trade_results", [])
                if prior_auto_results:
                    executor.restore_state(prior_auto_results)
                if self._debug_recorder is not None and debug_ctx is not None:
                    await self._debug_recorder.open_run(debug_ctx, config_snapshot={"num_configs": len(auto_configs), "resumed": True})
                await executor.init_balances()
                scan["auto_trade_executor"] = executor
                scan["debug_ctx"] = debug_ctx
                scan["auto_trade_results"] = list(prior_auto_results)
                logger.info("auto_trade_restored_on_resume", extra={
                    "scan_id": scan_id, "prior_trades": len(prior_auto_results),
                })
            elif auto_configs:
                logger.warning("auto_trade_configs_on_resume_but_no_accounts_service", extra={"scan_id": scan_id})

            async with self._lock:
                self._scans[scan_id] = scan

            task = asyncio.create_task(self._run_scan(scan_id, symbols_override=remaining))
            async with self._lock:
                if scan_id in self._scans:
                    self._scans[scan_id]["task"] = task

            resumed += 1
            logger.info("Resumed scan %s with %d/%d remaining symbols", scan_id, len(remaining), len(all_symbols))

        if resumed:
            await self._notify_scan_list_changed()
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
            "auto_trade_results": scan.get("auto_trade_results", []),
            "auto_trade_summaries": scan.get("auto_trade_summaries", []),
        }

    def _serialize_db(self, scan: Dict[str, Any]) -> Dict[str, Any]:
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
            "auto_trade_results": scan.get("auto_trade_results") or [],
            "auto_trade_summaries": scan.get("auto_trade_summaries") or [],
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
            fail_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["status"] = "failed"
                    scan["completed_at"] = fail_time
            if self._db:
                await self._db.update_scan(scan_id, status="failed", completed_at=fail_time)
            await self._notify_scan_list_changed()
            return

        async with self._lock:
            scan = self._scans.get(scan_id)
            if not scan:
                return
            batch_size = min(int(scan["config"].get("max_parallel", _BATCH_SIZE) or _BATCH_SIZE), _MAX_PARALLEL_CAP)
            logger.debug("Resolved batch_size=%d (config max_parallel=%s, cap=%d)", batch_size, scan["config"].get("max_parallel"), _MAX_PARALLEL_CAP)
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
                from tradingagents.dataflows.coingecko_data import prefetch_bulk_market_only
                await asyncio.to_thread(prefetch_bulk_market_only, symbols)
            except Exception:
                logger.warning("CoinGecko bulk prefetch failed", exc_info=True)
            # Descriptions are fetched lazily on cache miss — warm up in background
            try:
                from tradingagents.dataflows.coingecko_data import prefetch_descriptions_background
                loop = asyncio.get_running_loop()
                fut = loop.run_in_executor(None, prefetch_descriptions_background, symbols)
                fut.add_done_callback(lambda f: None if f.cancelled() else (logger.warning("Background desc prefetch error: %s", f.exception()) if f.exception() else None))
            except Exception:
                pass
        else:
            logger.debug("Skipping CoinGecko prefetch — no fundamentals/social analysts selected")

        # Pre-classify symbols for sector concentration limit (only if auto-trade is active)
        if self._sector_service and scan.get("auto_trade_executor"):
            try:
                await self._sector_service.ensure_classified(symbols)
            except Exception:
                logger.debug("sector_ensure_classified_failed", exc_info=True)

        # Raise the analysis service concurrency limit to match user's max_parallel
        self._analysis.set_max_concurrent(batch_size)
        sem = asyncio.Semaphore(batch_size)
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
        finally:
            self._analysis.set_max_concurrent(DEFAULT_MAX_CONCURRENT)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        final_status = "failed" if scan_error else "completed"
        final_completed = 0
        final_failed = 0
        final_completed_at = now

        # Auto-trade batch execution (after scan completes, not on cancel/error)
        if not scan_error:
            async with self._lock:
                scan = self._scans.get(scan_id)
                executor = scan.get("auto_trade_executor") if scan else None
                all_results = list(scan["results"]) if scan else []
                cancelled = scan.get("cancel", False) if scan else True
                total = scan["total"] if scan else 0
                failed_count = scan["failed"] if scan else 0
            # Skip batch if >50% of symbols failed (unreliable data)
            too_many_failures = total > 0 and failed_count > total * 0.5
            if executor and all_results and not cancelled and not too_many_failures:
                try:
                    batch_executions = await executor.execute_batch(all_results)
                    if batch_executions:
                        async with self._lock:
                            scan = self._scans.get(scan_id)
                            if scan:
                                scan["auto_trade_results"].extend(
                                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                                     "order_id": e.order_id, "error": e.error, "account_id": e.account_id}
                                    for e in batch_executions
                                )
                except Exception as e:
                    logger.warning("auto_trade_batch_error", extra={"scan_id": scan_id, "error": str(e)[:200]})
                # Fill remaining slots for immediate-mode configs with fill_to_max_trades
                try:
                    fill_executions = await executor.fill_immediate_remaining(all_results)
                    if fill_executions:
                        async with self._lock:
                            scan = self._scans.get(scan_id)
                            if scan:
                                scan["auto_trade_results"].extend(
                                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                                     "order_id": e.order_id, "error": e.error, "account_id": e.account_id}
                                    for e in fill_executions
                                )
                except Exception as e:
                    logger.warning("auto_trade_fill_error", extra={"scan_id": scan_id, "error": str(e)[:200]})
                # Post-scan re-check: handle accounts where conditions changed during the scan
                # (positions closed by TP/SL/drawdown, or close_on_profit_pct threshold now met)
                try:
                    recheck_executions = await executor.post_scan_recheck(all_results)
                    if recheck_executions:
                        async with self._lock:
                            scan = self._scans.get(scan_id)
                            if scan:
                                scan["auto_trade_results"].extend(
                                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                                     "order_id": e.order_id, "error": e.error, "account_id": e.account_id}
                                    for e in recheck_executions
                                )
                except Exception as e:
                    logger.warning("auto_trade_post_scan_recheck_error", extra={"scan_id": scan_id, "error": str(e)[:200]})

        async with self._lock:
            scan = self._scans.get(scan_id)
            executor = scan.get("auto_trade_executor") if scan else None
            if scan:
                if scan["cancel"]:
                    scan["status"] = "cancelled"
                elif scan_error:
                    scan["status"] = "failed"
                else:
                    scan["status"] = "completed"
                if not scan.get("completed_at"):
                    scan["completed_at"] = now
                scan["current_tickers"] = []
                scan["task"] = None
                scan["auto_trade_executor"] = None
                final_status = scan["status"]
                final_completed = scan["completed"]
                final_failed = scan["failed"]
                final_completed_at = scan["completed_at"]

        # Clean up close rules for accounts that had zero successful trades
        if executor:
            try:
                await executor.cleanup_unused_rules()
            except Exception:
                pass
            # Fix #4: Surface per-account summaries (including stopped_reason) to UI
            async with self._lock:
                scan = self._scans.get(scan_id)
                if scan:
                    scan["auto_trade_summaries"] = executor.get_summaries()

            # Debug: emit account summaries and close the debug run.
            # NOTE: OUTSIDE the `async with self._lock` above — emit_account_summaries
            # does account-label DB lookups; must not run inside the scanner lock.
            debug_ctx = scan.get("debug_ctx") if scan else None
            if self._debug_recorder is not None and debug_ctx is not None:
                num_accounts = 0
                try:
                    num_accounts = await executor.emit_account_summaries()
                except Exception:
                    pass
                async with self._lock:
                    _scan = self._scans.get(scan_id)
                    _total = (_scan.get("total", 0) if _scan else 0)
                # phase_reached mirrors the real scan outcome so a cancelled/failed
                # scan is not mislabeled "finalized" in the forensic record.
                _phase = {"cancelled": "cancelled", "failed": "failed"}.get(final_status, "finalized")
                await self._debug_recorder.close_run(
                    debug_ctx, phase_reached=_phase,
                    total_symbols=_total, completed_symbols=final_completed,
                    failed_symbols=final_failed, num_accounts=num_accounts,
                )

        if self._db:
            async with self._lock:
                scan_data = self._scans.get(scan_id, {})
                auto_results = list(scan_data.get("auto_trade_results", []))
                auto_summaries = list(scan_data.get("auto_trade_summaries", []))
            await self._db.update_scan(
                scan_id,
                status=final_status, completed_at=final_completed_at,
                completed=final_completed, failed=final_failed,
                auto_trade_results=_json.dumps(auto_results) if auto_results else "[]",
                auto_trade_summaries=_json.dumps(auto_summaries) if auto_summaries else "[]",
            )

        await self._notify_scan_list_changed()

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
            "prompt_cache_enabled": config.get("prompt_cache_enabled"),
            "data_vendors": config.get("data_vendors"),
            "workflow_mode": config.get("workflow_mode"),
            "agent_model_overrides": config.get("agent_model_overrides"),
            "ta_prefilter_enabled": config.get("ta_prefilter_enabled", True),
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
            assert run_id is not None
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
            elif (trader_json := reports.get("_trader_signal")):
                # quick_trade mode: no PM, use trader's structured JSON directly
                try:
                    trader_parsed = _extract_trader_signal(trader_json)
                    if trader_parsed is None:
                        signal = _parse_signal_from_reports(reports)
                        signal_source = "regex_fallback"
                    elif not trader_parsed.get("no_trade"):
                        signal = _build_signal(trader_parsed["direction"], trader_parsed.get("confidence_score"))
                        signal_source = "structured"
                    else:
                        signal = {"direction": "hold", "confidence": "none", "score": 0}
                        signal_source = "structured"
                except Exception:
                    logger.exception(
                        "Failed to parse _trader_signal for %s/%s — falling back",
                        scan_id, run_id,
                    )
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

        # Extract analysis_price from trader's entry_price for drift validation
        analysis_price = None
        if status == "completed" and reports:
            try:
                t_json = reports.get("_trader_signal")
                if t_json:
                    t_data = _json.loads(t_json) if isinstance(t_json, str) else t_json
                    ep = t_data.get("entry_price")
                    if ep and float(ep) > 0:
                        analysis_price = float(ep)
            except (TypeError, ValueError, _json.JSONDecodeError):
                pass

        result = {
            "ticker": ticker,
            "run_id": run_id,
            "status": status,
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "decision_summary": decision_text[:500] if decision_text else "",
            "signal_source": signal_source,
            "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        if analysis_price:
            result["analysis_price"] = analysis_price

        async with self._lock:
            scan = self._scans.get(scan_id)
            if scan:
                if status == "completed":
                    scan["completed"] += 1
                else:
                    scan["failed"] += 1
                scan["results"].append(result)

        # Persist scan result first so we have the row ID for auto-trade linking
        if self._db:
            scan_result_id = await self._db.insert_scan_result(scan_id, result)
            if scan_result_id:
                result["id"] = scan_result_id
            count_field = "completed" if status == "completed" else "failed"
            await self._db.increment_scan_counter(scan_id, count_field)

        # Auto-trade immediate execution
        if status == "completed":
            async with self._lock:
                scan = self._scans.get(scan_id)
                executor = scan.get("auto_trade_executor") if scan else None
                cancelled = scan.get("cancel", False) if scan else True
            if executor and not cancelled:
                try:
                    executions = await executor.evaluate_result(result)
                    if executions:
                        async with self._lock:
                            scan = self._scans.get(scan_id)
                            if scan:
                                scan["auto_trade_results"].extend(
                                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                                     "order_id": e.order_id, "error": e.error, "account_id": e.account_id}
                                    for e in executions
                                )
                except Exception as e:
                    logger.warning("auto_trade_immediate_error", extra={"scan_id": scan_id, "error": str(e)[:200]})
