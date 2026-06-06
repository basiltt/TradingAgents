"""Models and providers router — TASK-007."""

import ipaddress
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.schemas import PROVIDER_API_KEY_MAP, VALID_PROVIDERS
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

# Env var holding each provider's key, for native fetches when the UI sends none.
# Extends the shared PROVIDER_API_KEY_MAP with providers it omits.
_PROVIDER_ENV_KEYS: dict[str, str] = {**PROVIDER_API_KEY_MAP, "nvidia": "NVIDIA_API_KEY"}

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

    # Provider-specific URL and auth patterns
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    if req.custom_url:
        url = f"{base}/v1/models"
        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"
    elif req.provider == "anthropic":
        url = f"{base}/v1/models"
        if req.api_key:
            headers["x-api-key"] = req.api_key
            headers["anthropic-version"] = "2023-06-01"
    elif req.provider == "google":
        url = f"{base}/v1beta/models"
        if req.api_key:
            params["key"] = req.api_key
    else:
        url = f"{base}/v1/models"
        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
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
    url: str | None = None
    api_key: str | None = None
    provider: str | None = None


def _parse_openai_models(data: dict) -> list[dict]:
    """Parse the OpenAI-compatible {"data": [{"id", "name"?}]} shape."""
    return [
        {"id": m.get("id", ""), "name": m.get("name")}
        for m in (data.get("data") or [])
        if isinstance(m, dict) and m.get("id")
    ]


def _parse_anthropic_models(data: dict) -> list[dict]:
    """Parse the Anthropic {"data": [{"id", "display_name"}]} shape."""
    return [
        {"id": m.get("id", ""), "name": m.get("display_name") or m.get("name")}
        for m in (data.get("data") or [])
        if isinstance(m, dict) and m.get("id")
    ]


def _parse_google_models(data: dict) -> list[dict]:
    """Parse the Google {"models": [{"name": "models/x", "displayName"}]} shape."""
    out: list[dict] = []
    for m in data.get("models") or []:
        if not isinstance(m, dict):
            continue
        raw = m.get("name") or ""
        model_id = raw.split("/", 1)[1] if raw.startswith("models/") else raw
        if model_id:
            out.append({"id": model_id, "name": m.get("displayName") or model_id})
    return out


@router.post("/fetch-models")
async def fetch_models(req: FetchModelsRequest):
    """List models from a custom proxy endpoint OR a native provider.

    Two modes (custom URL wins when both are present):
      * Custom proxy: GET {url}/v1/models with Bearer auth (OpenAI shape).
      * Native provider: resolve the official base URL, use the provider's auth
        convention (anthropic x-api-key, google ?key=, others Bearer), and parse
        that provider's response shape. Falls back to the provider's env API key
        when the request supplies none — mirroring /connectivity-check so the
        native option lists real models instead of the hardcoded catalog.
    """
    custom_url = (req.url or "").strip().rstrip("/")
    provider = (req.provider or "").strip().lower()

    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    parser = _parse_openai_models

    if custom_url:
        # Existing proxy behaviour — unchanged.
        _validate_url_ssrf(custom_url)
        endpoint = custom_url if custom_url.endswith("/v1/models") else f"{custom_url}/v1/models"
        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"
    elif provider:
        if provider not in VALID_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
        base = PROVIDER_BASE_URLS.get(provider, "")
        if not base:
            raise HTTPException(status_code=400, detail=f"No base URL for provider: {provider}")
        # Use the supplied key, else the provider's configured env key.
        api_key = (req.api_key or "").strip() or os.environ.get(
            _PROVIDER_ENV_KEYS.get(provider, ""), ""
        )
        if provider == "anthropic":
            endpoint = f"{base}/v1/models"
            parser = _parse_anthropic_models
            if api_key:
                headers["x-api-key"] = api_key
                headers["anthropic-version"] = "2023-06-01"
        elif provider == "google":
            endpoint = f"{base}/v1beta/models"
            parser = _parse_google_models
            if api_key:
                params["key"] = api_key
        else:
            endpoint = f"{base}/v1/models"
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
    else:
        raise HTTPException(status_code=400, detail="A url or provider is required")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(endpoint, headers=headers, params=params)
        if resp.status_code not in (200, 201):
            return {"models": [], "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        if not isinstance(data, dict):
            return {"models": [], "error": "Unexpected response format"}
        return {"models": parser(data)}
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
