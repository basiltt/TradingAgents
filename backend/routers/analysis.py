"""Analysis router — CRUD + report download — TASK-013."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response

from backend.schemas import AnalysisRequest, AnalysisCreateResponse, ErrorResponse
from backend.services.analysis_service import ConcurrencyLimitError

router = APIRouter(tags=["analysis"])


def _validate_run_id(run_id: str) -> None:
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

_PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
}


@router.post("/analysis", response_model=AnalysisCreateResponse, status_code=201)
async def start_analysis(request: Request, body: AnalysisRequest):
    provider = body.provider or request.app.state.config_service.get_config()["resolved"].get("llm_provider", "openai")
    backend_url = body.backend_url or request.app.state.config_service.get_config()["resolved"].get("backend_url")
    env_key = _PROVIDER_KEY_MAP.get(provider)
    if env_key and not backend_url and not os.getenv(env_key):
        raise HTTPException(
            status_code=422,
            detail=f"API key not set: {env_key} environment variable required for provider '{provider}'",
        )

    try:
        run_id = await request.app.state.analysis_service.start_analysis(body.model_dump())
    except ConcurrencyLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return AnalysisCreateResponse(run_id=run_id, status="running")


@router.get("/analysis")
async def list_analyses(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    ticker: str = Query(None),
    status: str = Query(None),
    from_date: str = Query(None),
    to_date: str = Query(None),
):
    return await request.app.state.analysis_service.list_runs(
        page=page, limit=limit, ticker=ticker, status=status,
        from_date=from_date, to_date=to_date,
    )


@router.get("/analysis/{run_id}")
async def get_analysis(request: Request, run_id: str):
    _validate_run_id(run_id)
    run = await request.app.state.analysis_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/analysis/{run_id}/report")
async def get_report(request: Request, run_id: str):
    _validate_run_id(run_id)
    run = await request.app.state.analysis_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    report = await request.app.state.analysis_service.get_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not available")

    filename = f"report-{run_id}.md"
    return Response(
        content=report,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/analysis/{run_id}/snapshot")
async def get_snapshot(request: Request, run_id: str):
    _validate_run_id(run_id)
    snapshot = await request.app.state.analysis_service.get_snapshot(run_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not available")
    return snapshot


@router.post("/analysis/{run_id}/cancel")
async def cancel_analysis(request: Request, run_id: str):
    _validate_run_id(run_id)
    result = await request.app.state.analysis_service.cancel_analysis(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "cancelled"}


@router.delete("/analysis/{run_id}", status_code=204)
async def delete_analysis(request: Request, run_id: str):
    _validate_run_id(run_id)
    deleted = await request.app.state.analysis_service.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    return Response(status_code=204)
