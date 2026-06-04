"""Scanner router — batch analysis of all available symbols."""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas import ScanRequest, ScanResultItem, FilterPreviewResponse, PROVIDER_API_KEY_MAP
from backend.services.scanner_service import ScannerBusyError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanner"])

_background_tasks: set = set()
_in_flight_auto_trades: set = set()


def _validate_scan_id(scan_id: str) -> None:
    try:
        uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scan_id format")


def _validate_scan_response(raw: dict) -> dict:
    """Run scan results through Pydantic to coerce/reject invalid signal values."""
    validated_results = []
    for r in raw.get("results", []):
        try:
            validated_results.append(ScanResultItem.model_validate(r).model_dump())
        except Exception:
            logger.exception("Scan result item validation failed — skipping item: %r", r)
    raw["results"] = validated_results
    return raw


@router.post("/scanner", status_code=201)
async def start_scan(request: Request, body: ScanRequest):
    resolved = request.app.state.config_service.get_config()["resolved"]
    provider = body.provider or resolved.get("llm_provider", "openai")
    backend_url = body.backend_url or resolved.get("backend_url")
    env_key = PROVIDER_API_KEY_MAP.get(provider)
    if env_key and not backend_url and not body.llm_api_key and not os.getenv(env_key):
        raise HTTPException(
            status_code=422,
            detail=f"API key not set for provider '{provider}'. "
                   f"Either enter a Provider API Key in the UI or set the {env_key} environment variable.",
        )

    scan_config = body.model_dump()
    from backend.utils import mask_secrets
    logger.debug("New scan request config: %s", mask_secrets(scan_config))
    try:
        scan_id = await request.app.state.scanner_service.start_scan(scan_config)
    except ScannerBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"scan_id": scan_id, "status": "running"}


@router.get("/scanner")
async def list_scans(request: Request):
    scans = await request.app.state.scanner_service.list_scans()
    return {"scans": scans}


@router.get("/scanner/{scan_id}")
async def get_scan(request: Request, scan_id: str):
    _validate_scan_id(scan_id)
    scan = await request.app.state.scanner_service.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _validate_scan_response(scan)


@router.post("/scanner/{scan_id}/cancel")
async def cancel_scan(request: Request, scan_id: str):
    _validate_scan_id(scan_id)
    result = await request.app.state.scanner_service.cancel_scan(scan_id)
    if not result:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"status": "cancelled"}


@router.get("/scanner/{scan_id}/delete-preview")
async def delete_scan_preview(request: Request, scan_id: str):
    """Return the count of associated analysis runs that would be deleted."""
    _validate_scan_id(scan_id)
    count = await request.app.state.scanner_service.get_scan_analysis_count(scan_id)
    return {"scan_id": scan_id, "analysis_count": count}


@router.delete("/scanner/{scan_id}", status_code=200)
async def delete_scan(request: Request, scan_id: str):
    _validate_scan_id(scan_id)
    from backend.services.scanner_service import ScannerBusyError
    try:
        result = await request.app.state.scanner_service.delete_scan(scan_id)
    except ScannerBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return result


@router.get("/scans/{scan_id}/filter-preview", response_model=FilterPreviewResponse)
async def filter_preview(
    request: Request,
    scan_id: str,
    min_score: float = Query(default=3.0, ge=-10, le=10),
    min_confidence: str = Query(default="moderate"),
    signal_filter: str = Query(default="both"),
):
    from backend.services.trading_cycle_engine import TradingCycleEngine
    _validate_scan_id(scan_id)
    db = request.app.state.db
    scan = await db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    config = {
        "min_score": min_score, "min_confidence": min_confidence,
        "signal_filter": signal_filter, "max_trades": 999,
    }
    filtered = TradingCycleEngine.filter_scan_results(scan.get("results", []), config)
    direction_breakdown: dict[str, int] = {}
    for r in filtered:
        d = r["direction"]
        direction_breakdown[d] = direction_breakdown.get(d, 0) + 1
    return FilterPreviewResponse(
        qualifying_count=len(filtered),
        symbols=[r["ticker"] for r in filtered],
        direction_breakdown=direction_breakdown,
    )


@router.post("/scanner/{scan_id}/auto-trade")
async def trigger_auto_trade(request: Request, scan_id: str):
    """Trigger auto-trade execution on a completed scan using its stored auto_trade_configs."""
    _validate_scan_id(scan_id)

    if scan_id in _in_flight_auto_trades:
        raise HTTPException(status_code=409, detail="Auto trade already in progress for this scan")

    db = request.app.state.db
    accounts_service = getattr(request.app.state, "accounts_service", None)
    if not accounts_service:
        raise HTTPException(status_code=503, detail="Accounts service not available")

    close_svc = getattr(request.app.state, "close_positions_service", None)
    ai_manager_service = getattr(request.app.state, "ai_manager_service", None)
    sector_service = getattr(request.app.state, "sector_service", None)
    scanner_service = request.app.state.scanner_service

    # Load raw scan from DB (includes config with auto_trade_configs)
    scan = await db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Scan is not completed")

    # Check existing auto_trade_results (prevent double-execution)
    existing_results = scan.get("auto_trade_results")
    if isinstance(existing_results, str):
        try:
            existing_results = _json.loads(existing_results)
        except (ValueError, TypeError):
            existing_results = []
    if existing_results:
        raise HTTPException(status_code=409, detail="Auto trade already executed for this scan")

    # Extract auto_trade_configs from stored config
    config = scan.get("config", {})
    if isinstance(config, str):
        config = _json.loads(config)
    auto_configs = config.get("auto_trade_configs")
    if not auto_configs:
        raise HTTPException(status_code=422, detail="No auto_trade_configs found in scan config")

    results = scan.get("results", [])
    if not results:
        raise HTTPException(status_code=400, detail="Scan has no results")

    _in_flight_auto_trades.add(scan_id)

    async def _run_auto_trade():
        from backend.services.auto_trade_service import AutoTradeExecutor
        try:
            # Compute adaptive blacklist
            adaptive_bl = await scanner_service._compute_adaptive_blacklist(auto_configs)
            if adaptive_bl:
                for cfg in auto_configs:
                    if cfg.get("adaptive_blacklist_enabled"):
                        existing = set(cfg.get("_computed_adaptive_blacklist") or [])
                        cfg["_computed_adaptive_blacklist"] = list(existing | adaptive_bl)

            # Pre-classify symbols for sector service
            if sector_service:
                tickers = [r.get("ticker", "") for r in results if r.get("ticker")]
                try:
                    await sector_service.ensure_classified(tickers)
                except Exception:
                    pass

            # Create executor and initialize
            executor = AutoTradeExecutor(accounts_service, close_svc, ai_manager_service, sector_service=sector_service)
            executor.init_configs(auto_configs)
            await executor.init_balances()

            all_executions = []

            # Batch execution
            try:
                batch_execs = await executor.execute_batch(results)
                if batch_execs:
                    all_executions.extend(batch_execs)
            except Exception as e:
                logger.warning("auto_trade_manual_batch_error", extra={"scan_id": scan_id, "error": str(e)[:200]})

            # Fill remaining
            try:
                fill_execs = await executor.fill_immediate_remaining(results)
                if fill_execs:
                    all_executions.extend(fill_execs)
            except Exception as e:
                logger.warning("auto_trade_manual_fill_error", extra={"scan_id": scan_id, "error": str(e)[:200]})

            # Post-scan recheck
            try:
                recheck_execs = await executor.post_scan_recheck(results)
                if recheck_execs:
                    all_executions.extend(recheck_execs)
            except Exception as e:
                logger.warning("auto_trade_manual_recheck_error", extra={"scan_id": scan_id, "error": str(e)[:200]})

            # Cleanup unused rules
            try:
                await executor.cleanup_unused_rules()
            except Exception:
                pass

            # Persist results to DB
            trade_results = [
                {"symbol": e.symbol, "side": e.side, "status": e.status,
                 "order_id": e.order_id, "error": e.error, "account_id": e.account_id}
                for e in all_executions
            ]
            summaries = executor.get_summaries()

            await db.update_scan(
                scan_id,
                auto_trade_results=_json.dumps(trade_results),
                auto_trade_summaries=_json.dumps(summaries),
            )

            logger.info("auto_trade_manual_completed", extra={
                "scan_id": scan_id,
                "total_executions": len(all_executions),
                "successful": sum(1 for e in all_executions if e.status == "success"),
            })

        except Exception:
            logger.exception("auto_trade_manual_failed", extra={"scan_id": scan_id})
        finally:
            _in_flight_auto_trades.discard(scan_id)

    task = asyncio.create_task(_run_auto_trade())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "started", "scan_id": scan_id}
