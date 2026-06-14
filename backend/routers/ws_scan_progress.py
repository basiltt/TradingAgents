"""WebSocket endpoint for real-time post-scan auto-trade progress.

Streams the per-stage / per-account / per-order events the post-scan auto-trade
tail emits (init_balances → execute_batch → fill → recheck → cleanup → summaries
→ complete) for ONE scan_id, so the Scanner UI shows live status instead of the
old "results appear only at the end" 3s poll.

Mirrors the STRUCTURE of ws_backtest.py (subscribe → history replay → live →
ping/pong keepalive → close on terminal) but adopts STRICTER security for a
real-money feed:
- exact-origin match, rejecting a MISSING Origin (mirrors ws.py, NOT
  ws_backtest's permissive no-Origin bypass);
- validates scan_id as a UUID;
- verifies the scan EXISTS before streaming, and uses an IDENTICAL accept-then-
  close path for an unknown/foreign scan and a known-but-empty one (no error
  frame), so the post-accept event stream is not itself an existence/timing
  oracle.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.scan_progress_manager import TERMINAL_STAGES as _TERMINAL_STAGES

logger = logging.getLogger(__name__)

router = APIRouter()

# Explicit allow-list of fields that may cross the wire. The raw internal
# `account_id` is DELIBERATELY excluded — the UI uses the opaque per-scan
# `acct_ordinal` instead — so a real trading-account id can never be disclosed
# to a subscriber regardless of what any emitter passes. Free-text label/detail
# are likewise never forwarded (the manager already keeps `label` server-side).
_WIRE_FIELDS = frozenset({
    "type", "schema_version", "scan_id", "stage", "status", "pct", "seq", "ts",
    "acct_ordinal", "symbol", "side", "phase", "reason_code",
    "trades_executed", "trades_failed", "trades_skipped",
    "dry_run", "cooloff_until", "substatus",
})


def _project_for_wire(event: dict) -> dict:
    """Strip an event down to the allow-listed wire fields (drops account_id etc.)."""
    return {k: v for k, v in event.items() if k in _WIRE_FIELDS}


def _check_origin(websocket: WebSocket) -> bool:
    """Exact-origin allow-list. Rejects a missing Origin (a real-money feed must
    not accept non-browser clients that can forge/omit the header). NO port-only
    fallback — the host must match exactly."""
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    allowed = getattr(websocket.app.state, "cors_origins", None) or []
    return origin in set(allowed)


async def scan_auto_trade_progress_ws(websocket: WebSocket, scan_id: str) -> None:
    app = websocket.app

    if not _check_origin(websocket):
        await websocket.accept()
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    # Validate the scan_id shape before any lookup.
    try:
        uuid.UUID(scan_id)
    except (ValueError, AttributeError, TypeError):
        await websocket.accept()
        await websocket.close(code=4404, reason="Invalid scan_id")
        return

    manager = getattr(app.state, "scan_progress_manager", None)
    if manager is None:
        await websocket.accept()
        await websocket.close(code=1011, reason="Scan progress not available")
        return

    # Existence check BEFORE streaming. An unknown/foreign scan and a known-but-
    # empty scan both take this same accept-then-clean-close path (no error frame,
    # no distinct code) so the stream can't be used to enumerate scans.
    db = getattr(app.state, "db", None)
    scan_exists = False
    if db is not None:
        try:
            scan = await db.get_scan(scan_id)
            scan_exists = scan is not None
        except Exception:
            scan_exists = False
    await websocket.accept()
    if not scan_exists:
        await websocket.close(code=1000, reason="")
        return

    queue = manager.subscribe(scan_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(_project_for_wire(event))
                # Terminal stage — flush then close cleanly so the client's
                # reconnect logic doesn't keep re-opening a finished scan.
                if event.get("stage") in _TERMINAL_STAGES and event.get("status") in ("done", "failed", "cancelled"):
                    break
            except asyncio.TimeoutError:
                # Keepalive ping; if the client is gone the receive times out -> break.
                await websocket.send_json({"type": "ping"})
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                except asyncio.TimeoutError:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.debug("Scan progress WS closed: %s", e)
    finally:
        manager.unsubscribe(scan_id, queue)


# Register the route on the module router (kept as a thin wrapper so the handler
# is unit-testable without a full ASGI client).
@router.websocket("/ws/v1/scanner/{scan_id}/auto-trade")
async def _scan_auto_trade_progress_ws_route(websocket: WebSocket, scan_id: str) -> None:
    await scan_auto_trade_progress_ws(websocket, scan_id)
