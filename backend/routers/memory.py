"""Memory router — TASK-007."""

import asyncio

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["memory"])


@router.get("/memory")
async def get_memory(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    return await asyncio.to_thread(request.app.state.memory_service.get_entries, page=page, limit=limit)
