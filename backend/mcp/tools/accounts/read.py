"""Accounts read tools — TASK-P1-02 (redacted, demo-aware)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.mcp.core.errors import MCPServiceUnavailableError
from backend.mcp.core.redact import redact_record, redact_records
from backend.mcp.core.registry import SafetyClass, ToolGroup, tool


class AccountsListIn(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)
    financial_detail: bool = False


class AccountsListOut(BaseModel):
    accounts: list[dict[str, Any]]
    count: int


@tool(
    name="accounts_list",
    group=ToolGroup.ACCOUNTS,
    input_schema=AccountsListIn,
    output_schema=AccountsListOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def accounts_list(args: AccountsListIn, ctx: Any) -> AccountsListOut:
    """List trading accounts (id, label, type, status) with balances redacted by default."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("account storage unavailable")
    rows = await db.list_accounts()
    redacted = redact_records(rows[: args.limit], allow_financial_detail=args.financial_detail)
    return AccountsListOut(accounts=redacted, count=len(redacted))


class AccountGetIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    financial_detail: bool = False


class AccountGetOut(BaseModel):
    account: Optional[dict[str, Any]]


@tool(
    name="accounts_get",
    group=ToolGroup.ACCOUNTS,
    input_schema=AccountGetIn,
    output_schema=AccountGetOut,
    safety_class=SafetyClass.READ_ONLY,
)
async def accounts_get(args: AccountGetIn, ctx: Any) -> AccountGetOut:
    """Get one trading account's metadata (secrets stripped, balances redacted by default)."""
    db = ctx.services.db
    if db is None:
        raise MCPServiceUnavailableError("account storage unavailable")
    row = await db.get_account(args.account_id)
    account = redact_record(row, allow_financial_detail=args.financial_detail) if row else None
    return AccountGetOut(account=account)
