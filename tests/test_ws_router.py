"""Tests for backend.routers.ws — Phase 1 unit tests."""

from unittest.mock import MagicMock, AsyncMock
import pytest


class TestCheckOrigin:
    def test_no_origin_header(self):
        from backend.routers.ws import _check_origin
        ws = MagicMock()
        ws.headers = {}
        assert _check_origin(ws) is False

    def test_allowed_origin(self):
        from backend.routers.ws import _check_origin
        ws = MagicMock()
        ws.headers = {"origin": "http://localhost:3000"}
        ws.app.state.cors_origins = ["http://localhost:3000", "http://localhost:5173"]
        assert _check_origin(ws) is True

    def test_disallowed_origin(self):
        from backend.routers.ws import _check_origin
        ws = MagicMock()
        ws.headers = {"origin": "http://evil.com"}
        ws.app.state.cors_origins = ["http://localhost:3000"]
        assert _check_origin(ws) is False
