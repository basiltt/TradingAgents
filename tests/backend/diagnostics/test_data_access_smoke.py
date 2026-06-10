import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PARITY_DB_SMOKE"), reason="set PARITY_DB_SMOKE=1 to run against local DB")


@pytest.mark.asyncio
async def test_fetch_live_trades_returns_51_closed():
    from backend.async_persistence import AsyncAnalysisDB
    from backend.diagnostics.parity.data_access import ParityDataAccess
    from datetime import datetime, timezone
    db = AsyncAnalysisDB(os.environ["DATABASE_URL"])
    await db.connect()
    try:
        da = ParityDataAccess(db)
        rows = await da.fetch_live_trades(
            "75aecaa7-0f10-400b-a562-1ddd7ae6cf94",
            datetime(2026, 6, 4, 22, tzinfo=timezone.utc),
            datetime(2026, 6, 10, 6, tzinfo=timezone.utc))
        closed = [r for r in rows if r["status"] == "closed"]
        assert len(closed) == 51
    finally:
        await db.close()
