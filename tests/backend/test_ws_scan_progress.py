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
    assert ws.closed_code == 4404


def test_wire_projection_strips_account_id_and_label():
    """The wire allow-list must drop the raw internal account_id (the UI uses the
    opaque acct_ordinal) and any free-text label, regardless of what the emitter set."""
    from backend.services.scan_progress_manager import ScanProgressManager
    mgr = ScanProgressManager()
    ev = mgr.emit("s", "execute_batch", "secret label", account_id="acct-raw", acct_ordinal=3, symbol="BTCUSDT")
    wire = wsp._project_for_wire(ev)
    assert "account_id" not in wire
    assert "label" not in wire
    assert wire["acct_ordinal"] == 3
    assert wire["symbol"] == "BTCUSDT"
    assert wire["scan_id"] == "s"


@pytest.mark.asyncio
async def test_missing_manager_closes_1011():
    app = _make_app(manager=None, scan_ids=set())
    valid_uuid = "11111111-1111-1111-1111-111111111111"
    ws = _FakeWS(origin="http://localhost:5173", host_app=app)
    await wsp.scan_auto_trade_progress_ws(ws, valid_uuid)
    assert ws.closed_code == 1011


@pytest.mark.asyncio
async def test_db_error_fails_closed_clean_close():
    """A DB error during the existence check must fail closed (clean close, no crash)."""
    from backend.services.scan_progress_manager import ScanProgressManager
    app = _make_app(manager=ScanProgressManager(), scan_ids=set())
    app.state.db.get_scan.side_effect = RuntimeError("db down")
    valid_uuid = "11111111-1111-1111-1111-111111111111"
    ws = _FakeWS(origin="http://localhost:5173", host_app=app)
    await wsp.scan_auto_trade_progress_ws(ws, valid_uuid)
    assert ws.accepted is True
    assert not any(s.get("type") == "error" for s in ws.sent)


def test_wire_fields_cover_event_schema_except_account_id():
    """Every event field must be a CONSCIOUS wire/no-wire decision: the only field
    intentionally withheld is account_id. A new event field added without deciding
    fails this so the omission can't be silent."""
    from backend.services.scan_progress_manager import ScanProgressManager
    mgr = ScanProgressManager()
    ev = mgr.emit(
        "s", "execute_batch", "lbl", status="active", pct=10,
        account_id="a", acct_ordinal=1, symbol="BTCUSDT", side="buy", phase="batch",
        reason_code="max_trades", trades_executed=1, trades_failed=0, trades_skipped=0,
        dry_run=False, cooloff_until=None, substatus=None,
    )
    omitted = set(ev) - wsp._WIRE_FIELDS
    assert omitted == {"account_id"}, f"unexpected wire omissions: {omitted}"


def test_terminal_stages_single_source():
    """The WS router imports the manager's terminal-stage tuple (no drift)."""
    from backend.services import scan_progress_manager as m
    assert wsp._TERMINAL_STAGES == m.TERMINAL_STAGES
