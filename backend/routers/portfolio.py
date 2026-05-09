"""Portfolio aggregation router — cross-account views."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["portfolio"])


def _get_service(request: Request):
    svc = request.app.state.accounts_service
    if svc is None:
        raise HTTPException(503, detail="Accounts feature disabled — set ACCOUNTS_ENCRYPTION_KEY")
    return svc


@router.get("/portfolio/dashboard")
async def get_dashboard(
    request: Request,
    account_type: str = Query(None, description="Filter by account type: demo or live"),
):
    svc = _get_service(request)
    cards = await svc.get_dashboard()
    if account_type:
        cards = [c for c in cards if c.get("account_type") == account_type]
    return cards


@router.get("/portfolio/summary")
async def get_portfolio_summary(request: Request):
    svc = _get_service(request)
    return await svc.get_portfolio_summary()
