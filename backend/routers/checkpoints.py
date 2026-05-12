"""Checkpoints router — TASK-007."""

from fastapi import APIRouter, HTTPException, Query, Request, Response

from backend.schemas import TICKER_RE

router = APIRouter(tags=["checkpoints"])


def _validate_ticker(ticker: str) -> None:
    if not TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker format")


@router.get("/checkpoints")
async def get_checkpoint(
    request: Request,
    ticker: str = Query(...),
    date: str = Query(...),
):
    _validate_ticker(ticker)
    exists = await request.app.state.db.get_checkpoint_exists(ticker, date)
    return {"exists": exists, "ticker": ticker, "date": date}


@router.delete("/checkpoints", status_code=204)
async def delete_all_checkpoints(
    request: Request,
    confirm: bool = Query(False),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    await request.app.state.db.delete_all_checkpoints()
    return Response(status_code=204)


@router.delete("/checkpoints/{ticker}", status_code=204)
async def delete_ticker_checkpoints(
    request: Request,
    ticker: str,
    confirm: bool = Query(False),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")
    _validate_ticker(ticker)
    await request.app.state.db.delete_ticker_checkpoints(ticker)
    return Response(status_code=204)
