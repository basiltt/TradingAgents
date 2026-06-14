"""Run ON PROD via ssh_run.py. Fetches the RAW Bybit closed-PnL record for Unni
ESPORTS exactly as the reconciler does, and replays the reconciler's match filter
to see which condition rejects it. Read-only (no DB writes)."""
import asyncio, sys, time
sys.path.insert(0, "/root/projects/TradingAgents")

ACCT = "3aca7442-2bd0-44c6-b4ef-bc46a9593f35"  # Unni
SYMBOL = "ESPORTSUSDT"
SIDE = "Sell"            # the trade side stored in trades
CLOSE_SIDE = "Buy" if SIDE == "Sell" else "Sell"

async def main():
    from backend.main import create_app
    app = create_app()
    # grab the wired services off app state
    accounts = app.state.accounts_service
    client = await accounts.get_client(ACCT)

    # window = trade opened_at .. now (same as reconciler)
    opened_ms = 1781400699596  # 2026-06-14 01:31:39 (opened_at)
    end_ms = int(time.time() * 1000)
    print(f"window {opened_ms} .. {end_ms}  close_side={CLOSE_SIDE}")

    cursor = ""
    page = 0
    found = None
    all_esports = []
    while page < 50:
        page += 1
        result = await client.get_closed_pnl(opened_ms, end_ms, limit=100, cursor=cursor) if not cursor \
            else await client.get_closed_pnl(opened_ms, end_ms, limit=100, cursor=cursor)
        lst = result.get("list", [])
        for r in lst:
            if r.get("symbol") == SYMBOL:
                all_esports.append(r)
        # replay the exact reconciler filter
        matches = [r for r in lst if r.get("symbol") == SYMBOL and r.get("side") == CLOSE_SIDE]
        if matches:
            found = matches[0]
            break
        cursor = result.get("nextPageCursor", "")
        if not cursor:
            break

    print(f"pages scanned: {page}")
    print(f"ESPORTS records seen (any side): {len(all_esports)}")
    for r in all_esports:
        print("  RAW:", {k: r.get(k) for k in ("symbol","side","closedPnl","avgExitPrice","orderType","execType","updatedTime","qty")})
    print(f"\nMATCH on side=={CLOSE_SIDE}: {'FOUND' if found else 'NONE'}")
    if found:
        print("  matched:", {k: found.get(k) for k in ("symbol","side","closedPnl","avgExitPrice")})

asyncio.run(main())
