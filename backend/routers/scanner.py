"""Scanner router — batch analysis of all available symbols."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import ScanRequest
from backend.services.scanner_service import ScannerBusyError

router = APIRouter(tags=["scanner"])

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


def _validate_scan_id(scan_id: str) -> None:
    try:
        uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scan_id format")


@router.post("/scanner", status_code=201)
async def start_scan(request: Request, body: ScanRequest):
    provider = body.provider or request.app.state.config_service.get_config()["resolved"].get("llm_provider", "openai")
    backend_url = body.backend_url or request.app.state.config_service.get_config()["resolved"].get("backend_url")
    env_key = _PROVIDER_KEY_MAP.get(provider)
    if env_key and not backend_url and not os.getenv(env_key):
        raise HTTPException(
            status_code=422,
            detail=f"API key not set: {env_key} environment variable required for provider '{provider}'",
        )

    try:
        scan_id = await request.app.state.scanner_service.start_scan(body.model_dump())
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
    return scan


@router.post("/scanner/{scan_id}/cancel")
async def cancel_scan(request: Request, scan_id: str):
    _validate_scan_id(scan_id)
    result = await request.app.state.scanner_service.cancel_scan(scan_id)
    if not result:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"status": "cancelled"}
