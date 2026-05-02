"""Checkpoints router — TASK-007."""

from fastapi import APIRouter, HTTPException, Query, Request, Response

router = APIRouter(tags=["checkpoints"])


@router.get("/checkpoints")
async def get_checkpoint(
    request: Request,
    ticker: str = Query(...),
    date: str = Query(...),
):
    exists = request.app.state.db.get_checkpoint_exists(ticker, date)
    return {"exists": exists, "ticker": ticker, "date": date}


@router.delete("/checkpoints", status_code=204)
async def delete_all_checkpoints(
    request: Request,
    confirm: bool = Query(False),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    return Response(status_code=204)


@router.delete("/checkpoints/{ticker}", status_code=204)
async def delete_ticker_checkpoints(
    request: Request,
    ticker: str,
    confirm: bool = Query(False),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    return Response(status_code=204)
