"""Models and providers router — TASK-007."""

from fastapi import APIRouter, HTTPException

from backend.schemas import VALID_PROVIDERS
from tradingagents.llm_clients.model_catalog import get_model_options

router = APIRouter(tags=["models"])


@router.get("/models/{provider}")
async def get_models(provider: str):
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    quick = get_model_options(provider, "quick")
    deep = get_model_options(provider, "deep")
    return {"provider": provider, "quick": quick, "deep": deep}


@router.get("/providers")
async def get_providers():
    return {"providers": sorted(VALID_PROVIDERS)}
