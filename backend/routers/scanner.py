"""Scanner router — batch analysis of all available symbols."""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import ScanRequest, ScanResultItem, PROVIDER_API_KEY_MAP
from backend.services.scanner_service import ScannerBusyError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanner"])


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
