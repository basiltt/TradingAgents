"""Auto-trade debug forensics API (/api/v1/debug)."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas.debug import DebugConfigUpdate

router = APIRouter(tags=["debug"])


def _repo(request: Request):
    recorder = getattr(request.app.state, "debug_trace_recorder", None)
    if recorder is None or getattr(recorder, "repo", None) is None:
        raise HTTPException(503, detail="Debug tracing not available")
    return recorder, recorder.repo


@router.get("/debug/scan/{scan_id}")
async def get_scan_tree(request: Request, scan_id: str, run_id: Optional[int] = Query(None)):
    _, repo = _repo(request)
    rid = run_id or await repo.get_latest_run_id_for_scan(scan_id)
    if rid is None:
        raise HTTPException(404, detail="No debug run found for this scan")
    tree = await repo.get_run_tree(rid)
    if not tree:
        raise HTTPException(404, detail="Debug run not found")
    return tree


@router.get("/debug/scan/{scan_id}/account/{account_id}")
async def get_scan_account(request: Request, scan_id: str, account_id: str, run_id: Optional[int] = Query(None)):
    _, repo = _repo(request)
    rid = run_id or await repo.get_latest_run_id_for_scan(scan_id)
    if rid is None:
        raise HTTPException(404, detail="No debug run found for this scan")
    tree = await repo.get_run_tree(rid)
    for acct in tree.get("accounts", []):
        if acct["account_id"] == account_id:
            return {"run": tree["run"], "account": acct}
    raise HTTPException(404, detail="Account not found in this run")


@router.get("/debug/runs")
async def list_runs(request: Request, limit: int = Query(20, ge=1, le=100),
                    offset: int = Query(0, ge=0), trigger_source: Optional[str] = None,
                    account_id: Optional[str] = None,
                    from_ts: Optional[str] = Query(None, alias="from"),
                    to_ts: Optional[str] = Query(None, alias="to")):
    _, repo = _repo(request)
    return await repo.list_runs(limit=limit, offset=offset,
                                trigger_source=trigger_source, account_id=account_id,
                                from_ts=from_ts, to_ts=to_ts)


@router.get("/debug/account/{account_id}/timeline")
async def account_timeline(request: Request, account_id: str, limit: int = Query(50, ge=1, le=200),
                           from_ts: Optional[str] = Query(None, alias="from"),
                           to_ts: Optional[str] = Query(None, alias="to")):
    _, repo = _repo(request)
    return {"items": await repo.get_account_timeline(account_id, limit=limit,
                                                     from_ts=from_ts, to_ts=to_ts)}


@router.get("/debug/symbol/{symbol}")
async def symbol_decisions(request: Request, symbol: str, scan_id: Optional[str] = None,
                           limit: int = Query(200, ge=1, le=1000)):
    _, repo = _repo(request)
    return {"items": await repo.get_symbol_decisions(symbol, scan_id=scan_id, limit=limit)}


@router.get("/debug/config")
async def get_config(request: Request):
    _, repo = _repo(request)
    return await repo.get_config()


@router.put("/debug/config")
async def update_config(request: Request, body: DebugConfigUpdate):
    recorder, repo = _repo(request)
    cfg = await repo.update_config(
        tracing_enabled=body.tracing_enabled,
        retention_days=body.retention_days,
        symbol_decision_cap=body.symbol_decision_cap,
    )
    await recorder.refresh_config()
    return cfg
