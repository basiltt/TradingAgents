"""Models and providers router — TASK-007."""

import ipaddress
import time
from urllib.parse import urlparse

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

_ALLOWED_LOCALHOST = {"localhost", "127.0.0.1", "::1"}


def _validate_url_ssrf(url: str) -> None:
    """Reject URLs targeting private/internal networks (SSRF protection).

    Allows localhost only for ollama-like local services.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, detail="Only http/https URLs are allowed")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(400, detail="Invalid URL: missing host")
    if host in _ALLOWED_LOCALHOST:
        return
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise HTTPException(400, detail="URLs targeting private networks are not allowed")
    except ValueError:
        if host.endswith(".internal") or host.endswith(".local"):
            raise HTTPException(400, detail="URLs targeting internal domains are not allowed")


class ConnectivityRequest(BaseModel):
    provider: str
    api_key: str | None = None
    custom_url: str | None = None


@router.post("/connectivity-check")
async def connectivity_check(req: ConnectivityRequest):
    if req.provider not in VALID_PROVIDERS:
        raise HTTPException(400, detail=f"Unknown provider: {req.provider}")
    base = (req.custom_url or "").strip().rstrip("/") or PROVIDER_BASE_URLS.get(req.provider, "")
    if not base:
        raise HTTPException(status_code=400, detail=f"No base URL for provider: {req.provider}")
    if req.custom_url:
        _validate_url_ssrf(base)

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


class FetchModelsRequest(BaseModel):
    url: str
    api_key: str | None = None


@router.post("/fetch-models")
async def fetch_models(req: FetchModelsRequest):
    """Proxy model list from a custom/self-hosted endpoint (avoids browser CORS)."""
    base = req.url.strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=400, detail="URL is required")
    _validate_url_ssrf(base)
    endpoint = base if base.endswith("/v1/models") else f"{base}/v1/models"

    headers = {}
    if req.api_key:
        headers["Authorization"] = f"Bearer {req.api_key}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(endpoint, headers=headers)
        if resp.status_code not in (200, 201):
            return {"models": [], "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        if not isinstance(data, dict):
            return {"models": [], "error": "Unexpected response format"}
        models = [
            {"id": m.get("id", ""), "name": m.get("name")}
            for m in (data.get("data") or [])
            if isinstance(m, dict) and m.get("id")
        ]
        return {"models": models}
    except httpx.ConnectError:
        return {"models": [], "error": "Connection refused"}
    except httpx.TimeoutException:
        return {"models": [], "error": "Connection timeout"}
    except Exception as e:
        return {"models": [], "error": str(e)}


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
