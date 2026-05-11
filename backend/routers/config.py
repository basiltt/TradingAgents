"""Config router — GET/PATCH /api/v1/config — TASK-007."""

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import ConfigUpdateRequest
from tradingagents.llm_clients import configure_llm_concurrency, configure_llm_min_spacing

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_config(request: Request):
    return request.app.state.config_service.get_config()


@router.patch("/config")
async def update_config(request: Request, body: ConfigUpdateRequest):
    try:
        request.app.state.config_service.update_config(body.overrides)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if "llm_max_concurrent" in body.overrides:
        configure_llm_concurrency(int(body.overrides["llm_max_concurrent"]))

    if "llm_min_spacing_ms" in body.overrides:
        configure_llm_min_spacing(int(body.overrides["llm_min_spacing_ms"]))

    return request.app.state.config_service.get_config()
