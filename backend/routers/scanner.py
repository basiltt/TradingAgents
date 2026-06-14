"""Scanner router — batch analysis of all available symbols."""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas import PROVIDER_API_KEY_MAP, FilterPreviewResponse, ScanRequest, ScanResultItem
from backend.services.bybit_rate_gate import RateGateBanAbort
from backend.services.scanner_service import ScannerBusyError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanner"])

_background_tasks: set = set()
_in_flight_auto_trades: set = set()


def _validate_scan_id(scan_id: str) -> None:
    try:
        uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scan_id format") from None


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
    """Launch a batch scan analyzing all available symbols and return its scan_id.

    Resolves the LLM provider from request/config; 422 if its API key is
    missing, 409 if a scan is already running. Returns scan_id with status
    "running".
    """
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
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"scan_id": scan_id, "status": "running"}


@router.get("/scanner")
async def list_scans(request: Request):
    """List all scans; returns {"scans": [...]}."""
    scans = await request.app.state.scanner_service.list_scans()
    return {"scans": scans}


@router.get("/scanner/{scan_id}")
async def get_scan(request: Request, scan_id: str):
    """Get one scan with its results (re-validated through Pydantic); 404 if not found."""
    _validate_scan_id(scan_id)
    scan = await request.app.state.scanner_service.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _validate_scan_response(scan)


@router.post("/scanner/{scan_id}/cancel")
async def cancel_scan(request: Request, scan_id: str):
    """Cancel a running scan; 404 if not found, else {"status": "cancelled"}."""
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
    """Delete a scan and its associated analysis runs.

    409 if a scan is currently running, 404 if not found.
    """
    _validate_scan_id(scan_id)
    from backend.services.scanner_service import ScannerBusyError
    try:
        result = await request.app.state.scanner_service.delete_scan(scan_id)
    except ScannerBusyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
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
    """Preview how many scan results qualify for trading under given filter params.

    Applies the cycle engine's filter (min_score, min_confidence, signal_filter)
    without placing trades. Returns qualifying count, symbols, and a per-direction
    breakdown. 404 if the scan is not found.
    """
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

    # Atomic claim BEFORE any await — set.add under the GIL is atomic and there is no
    # await between the membership test and the add, so two concurrent POSTs for the
    # same scan can't both pass (closes the prior check-then-later-add TOCTOU, H1). The
    # central single-flight also rejects an overlapping scheduled auto-tail.
    from backend.services import post_scan_concurrency as _psc
    if scan_id in _in_flight_auto_trades or _psc.is_tail_in_flight(scan_id):
        raise HTTPException(status_code=409, detail="Auto trade already in progress for this scan")
    _in_flight_auto_trades.add(scan_id)

    def _reject(status_code: int, detail: str) -> HTTPException:
        # Build a validation-failure exception. The claim is released by the single
        # `except BaseException` net below (which catches this HTTPException too), so
        # there is exactly ONE place that owns the release — no duplicated discard.
        return HTTPException(status_code=status_code, detail=detail)

    # Any raise between the claim above and the task spawn below (an HTTPException from
    # _reject, OR an unexpected error from db.get_scan / json.loads / a missing app.state
    # attr) must release the claim — otherwise the scan_id leaks in _in_flight_auto_trades
    # forever and the scan can never be manually re-run until a process restart (H1/R2).
    try:
        db = request.app.state.db
        accounts_service = getattr(request.app.state, "accounts_service", None)
        if not accounts_service:
            raise _reject(503, "Accounts service not available")

        close_svc = getattr(request.app.state, "close_positions_service", None)
        ai_manager_service = getattr(request.app.state, "ai_manager_service", None)
        sector_service = getattr(request.app.state, "sector_service", None)
        scanner_service = request.app.state.scanner_service

        # Load raw scan from DB (includes config with auto_trade_configs)
        scan = await db.get_scan(scan_id)
        if not scan:
            raise _reject(404, "Scan not found")
        if scan.get("status") != "completed":
            raise _reject(400, "Scan is not completed")

        # Check existing auto_trade_results (prevent double-execution)
        # Note: re-execution is allowed — the executor's built-in guards
        # (existing_symbols, skip_if_positions_open) prevent actual duplicate trades.
        # Results are overwritten with the latest execution.

        # Extract auto_trade_configs from stored config
        config = scan.get("config", {})
        if isinstance(config, str):
            config = _json.loads(config)
        auto_configs = config.get("auto_trade_configs")
        if not auto_configs:
            raise _reject(422, "No auto_trade_configs found in scan config")

        results = scan.get("results", [])
        if not results:
            raise _reject(400, "Scan has no results")
    except BaseException:
        # Fail-safe net: release the claim on ANY error in the validation region so the
        # scan stays re-runnable, then re-propagate (FastAPI maps HTTPException to its
        # status; anything else becomes a 500).
        _in_flight_auto_trades.discard(scan_id)
        raise

    debug_recorder = getattr(request.app.state, "debug_trace_recorder", None)

    async def _run_auto_trade():
        from backend.services.auto_trade_service import AutoTradeExecutor
        # Initialized before the try so they are always defined in `finally`,
        # even if an exception is raised before they are assigned inside the try.
        executor = None
        debug_ctx = None
        debug_closed = False
        try:
            # Compute adaptive blacklist
            adaptive_bl = await scanner_service._compute_adaptive_blacklist(auto_configs)
            if adaptive_bl:
                for cfg in auto_configs:
                    if cfg.get("adaptive_blacklist_enabled"):
                        existing = set(cfg.get("_computed_adaptive_blacklist") or [])
                        cfg["_computed_adaptive_blacklist"] = list(existing | adaptive_bl)
            # FR-030: MR-scoped blacklist parity on the auto-trade re-run path.
            mr_bl = await scanner_service._compute_adaptive_blacklist(auto_configs, "mean_reversion", require_mr=True)
            if mr_bl:
                for cfg in auto_configs:
                    if cfg.get("adaptive_blacklist_enabled") and cfg.get("mean_reversion_enabled"):
                        existing = set(cfg.get("_computed_mr_adaptive_blacklist") or [])
                        cfg["_computed_mr_adaptive_blacklist"] = list(existing | mr_bl)

            # Pre-classify symbols for sector service
            if sector_service:
                tickers = [r.get("ticker", "") for r in results if r.get("ticker")]
                try:
                    await sector_service.ensure_classified(tickers)
                except Exception:
                    pass

            # Create executor and initialize (with debug tracing).
            if debug_recorder is not None:
                debug_ctx = debug_recorder.new_run_context(
                    scan_id=scan_id, trigger_source="manual", schedule_id=None,
                )
            executor = AutoTradeExecutor(
                accounts_service, close_svc, ai_manager_service,
                sector_service=sector_service,
                recorder=debug_recorder, debug_ctx=debug_ctx,
                cooloff_repo=getattr(request.app.state, "cooloff_repo", None),
                cooloff_classifier=getattr(request.app.state, "cooloff_classifier", None),
                progress=getattr(request.app.state, "scan_progress_manager", None),
                scan_id=scan_id,
                # H1 fix: wire the per-(account,symbol) position lock so the manual
                # re-run's placements are serialized against the AI manager / close
                # loop acting on the same position (the scheduled path already passes
                # this; the manual path must match for defense in depth).
                position_lock_registry=getattr(request.app.state, "position_lock_registry", None),
            )
            if debug_recorder is not None and debug_ctx is not None:
                await debug_recorder.open_run(debug_ctx, config_snapshot={"num_configs": len(auto_configs), "manual": True})
            executor.init_configs(auto_configs)

            # Claim the central single-flight slot BEFORE init_balances (not just the
            # tail): init_balances force-closes positions + creates close rules, which
            # must not overlap a concurrent scheduled auto-tail for the SAME scan (R2
            # cross-path window). If an auto/scheduled tail already owns this scan, skip
            # ENTIRELY — do NOT init, touch the DB, or emit a terminal: the in-flight
            # tail owns this scan's results (update_scan is a full-column overwrite) and
            # emits the single terminal `complete`.
            from backend.services import post_scan_concurrency as _psc
            _began_central = _psc.try_begin_tail(scan_id)
            if not _began_central:
                logger.warning("auto_trade_manual_tail_skipped_single_flight", extra={"scan_id": scan_id})
                return

            tail_trade_results: list = []

            async def _persist_stage(stage: str, executions: list) -> None:
                tail_trade_results.extend(
                    {"symbol": e.symbol, "side": e.side, "status": e.status,
                     "order_id": e.order_id, "error": e.error, "account_id": e.account_id}
                    for e in executions
                )

            try:
                await executor.init_balances()
                tail_out = await executor.run_post_scan_tail(
                    results, persist_cb=_persist_stage, place_trades=True,
                    emit_complete=False,  # FR-036: terminal emitted AFTER the DB commit below
                )
                summaries = tail_out.get("summaries") or executor.get_summaries()
            except RateGateBanAbort:
                logger.warning("auto_trade_manual_tail_rate_ban", extra={"scan_id": scan_id})
                summaries = executor.get_summaries()
            except Exception as e:
                logger.warning("auto_trade_manual_tail_error", extra={"scan_id": scan_id, "error": str(e)[:200]})
                summaries = executor.get_summaries()
            finally:
                _psc.end_tail(scan_id)

            await db.update_scan(
                scan_id,
                auto_trade_results=_json.dumps(tail_trade_results),
                auto_trade_summaries=_json.dumps(summaries),
            )
            # FR-036: terminal event only after the results are persisted.
            try:
                executor.emit_tail_complete()
            except Exception:
                pass

            logger.info("auto_trade_manual_completed", extra={
                "scan_id": scan_id,
                "total_executions": len(tail_trade_results),
                "successful": sum(1 for e in tail_trade_results if e.get("status") == "success"),
            })


            # Debug: emit account summaries and close the manual debug run.
            if debug_recorder is not None and debug_ctx is not None:
                num_accounts = 0
                try:
                    num_accounts = await executor.emit_account_summaries()
                except Exception:
                    pass
                try:
                    await debug_recorder.close_run(
                        debug_ctx, phase_reached="finalized",
                        total_symbols=len(results), completed_symbols=len(results),
                        failed_symbols=0, num_accounts=num_accounts,
                    )
                    debug_closed = True
                except Exception:
                    logger.warning("debug_manual_close_run_failed", extra={"scan_id": scan_id})

        except Exception:
            logger.exception("auto_trade_manual_failed", extra={"scan_id": scan_id})
        finally:
            # Ensure the debug run is closed even if the try raised before the
            # in-try close — otherwise it leaks as in-progress until restart recovery.
            if debug_recorder is not None and debug_ctx is not None and not debug_closed:
                try:
                    num_accounts = 0
                    if executor is not None:
                        try:
                            num_accounts = await executor.emit_account_summaries()
                        except Exception:
                            pass
                    await debug_recorder.close_run(
                        debug_ctx, phase_reached="failed",
                        total_symbols=len(results), completed_symbols=0,
                        failed_symbols=0, num_accounts=num_accounts,
                    )
                except Exception:
                    logger.warning("debug_manual_close_run_failed", extra={"scan_id": scan_id})
            _in_flight_auto_trades.discard(scan_id)

    task = asyncio.create_task(_run_auto_trade())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "started", "scan_id": scan_id}
