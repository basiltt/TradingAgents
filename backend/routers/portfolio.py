"""Portfolio aggregation router — cross-account views."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio/dashboard")
async def get_dashboard(request: Request):
    svc = request.app.state.accounts_service
    return await svc.get_dashboard()


@router.get("/portfolio/summary")
async def get_portfolio_summary(request: Request):
    svc = request.app.state.accounts_service
    return await svc.get_portfolio_summary()
