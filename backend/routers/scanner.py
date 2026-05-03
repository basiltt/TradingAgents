"""Scanner router — batch analysis of all available symbols."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import ScanRequest
from backend.services.scanner_service import ScannerBusyError

router = APIRouter(tags=["scanner"])


def _validate_scan_id(scan_id: str) -> None:
    try:
        uuid.UUID(scan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scan_id format")


@router.post("/scanner", status_code=201)
async def start_scan(request: Request, body: ScanRequest):
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
