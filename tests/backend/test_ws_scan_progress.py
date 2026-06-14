"""Tests for the scan auto-trade progress WS endpoint (TASK-1.3)."""
from unittest.mock import MagicMock, AsyncMock

import pytest

from backend.routers import ws_scan_progress as wsp


class _FakeWS:
    def __init__(self, origin=None, host_app=None):
        self.headers = {"origin": origin} if origin is not None else {}
        self.app = host_app
        self.accepted = False
        self.closed_code = None
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        self.closed_code = code

    async def send_json(self, obj):
        self.sent.append(obj)


def _make_app(cors_origins=None, manager=None, scan_ids=None):
    app = MagicMock()
    app.state.cors_origins = cors_origins if cors_origins is not None else ["http://localhost:5173"]
    app.state.scan_progress_manager = manager
    db = MagicMock()
    existing = set(scan_ids or [])

    async def _get_scan(sid):
        return {"scan_id": sid} if sid in existing else None
    db.get_scan = AsyncMock(side_effect=_get_scan)
    app.state.db = db
    return app


def test_exact_origin_required():
    """Strict origin: reject a missing Origin (mirror ws.py, not ws_backtest)."""
    app = _make_app()
    ws = _FakeWS(origin=None, host_app=app)
    assert wsp._check_origin(ws) is False


def test_exact_origin_match_only():
    """Port-only fallback must NOT pass — exact origin match for the money feed."""
    app = _make_app(cors_origins=["http://localhost:5173"])
    ok = _FakeWS(origin="http://localhost:5173", host_app=app)
    bad = _FakeWS(origin="http://evil.example:5173", host_app=app)
    assert wsp._check_origin(ok) is True
    assert wsp._check_origin(bad) is False


@pytest.mark.asyncio
async def test_unknown_scan_and_missing_scan_close_identically():
    """An unknown scan_id and a known scan with no events must take the SAME close
    path (no enumeration/timing oracle): accept then close cleanly, no error frame."""
    from backend.services.scan_progress_manager import ScanProgressManager
    mgr = ScanProgressManager()
    app = _make_app(manager=mgr, scan_ids=set())  # no scans exist
    valid_uuid = "11111111-1111-1111-1111-111111111111"
    ws = _FakeWS(origin="http://localhost:5173", host_app=app)
    await wsp.scan_auto_trade_progress_ws(ws, valid_uuid)
    # Accepted then closed with no error payload leaked.
    assert ws.accepted is True
    assert not any(s.get("type") == "error" for s in ws.sent)


@pytest.mark.asyncio
async def test_invalid_uuid_rejected():
    app = _make_app()
    ws = _FakeWS(origin="http://localhost:5173", host_app=app)
    await wsp.scan_auto_trade_progress_ws(ws, "not-a-uuid")
    assert ws.closed_code is not None
