"""Models and providers router — TASK-007."""

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.schemas import VALID_PROVIDERS
from tradingagents.llm_clients.model_catalog import get_model_options

router = APIRouter(tags=["models"])

PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "deepseek": "https://api.deepseek.com",
    "nvidia": "https://integrate.api.nvidia.com",
    "xai": "https://api.x.ai",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode",
    "glm": "https://api.z.ai/api/paas/v4",
    "openrouter": "https://openrouter.ai/api",
    "ollama": "http://localhost:11434",
}


class ConnectivityRequest(BaseModel):
    provider: str
    api_key: str | None = None
    custom_url: str | None = None


@router.post("/connectivity-check")
async def connectivity_check(req: ConnectivityRequest):
    base = (req.custom_url or "").strip().rstrip("/") or PROVIDER_BASE_URLS.get(req.provider, "")
    if not base:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")

    url = f"{base}/v1/models"
    headers = {}
    if req.api_key:
        headers["Authorization"] = f"Bearer {req.api_key}"

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        latency_ms = int((time.time() - start) * 1000)

        if resp.status_code in (200, 201):
            return {"status": "ok", "latency_ms": latency_ms}
        elif resp.status_code in (401, 403):
            return {"status": "error", "error": "Invalid API key", "latency_ms": latency_ms}
        else:
            return {"status": "error", "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}
    except httpx.ConnectError:
        return {"status": "error", "error": "Connection refused"}
    except httpx.TimeoutException:
        return {"status": "error", "error": "Connection timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


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
