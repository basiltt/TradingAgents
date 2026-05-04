"""Tests for tradingagents.graph.checkpointer — Phase 1 unit tests."""

import tempfile
import os
import pytest


class TestDbPath:
    def test_creates_dir_and_returns_path(self, tmp_path):
        from tradingagents.graph.checkpointer import _db_path
        p = _db_path(str(tmp_path), "AAPL")
        assert p.parent.name == "checkpoints"
        assert p.name == "AAPL.db"
        assert p.parent.exists()

    def test_rejects_traversal(self, tmp_path):
        from tradingagents.graph.checkpointer import _db_path
        with pytest.raises(ValueError):
            _db_path(str(tmp_path), "../etc/passwd")


class TestThreadId:
    def test_deterministic(self):
        from tradingagents.graph.checkpointer import thread_id
        a = thread_id("AAPL", "2025-01-10")
        b = thread_id("AAPL", "2025-01-10")
        assert a == b
        assert len(a) == 16

    def test_different_for_different_inputs(self):
        from tradingagents.graph.checkpointer import thread_id
        a = thread_id("AAPL", "2025-01-10")
        b = thread_id("GOOG", "2025-01-10")
        assert a != b


class TestClearAllCheckpoints:
    def test_no_dir(self, tmp_path):
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        assert clear_all_checkpoints(str(tmp_path)) == 0

    def test_clears_dbs(self, tmp_path):
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "AAPL.db").write_text("x")
        (cp_dir / "GOOG.db").write_text("x")
        assert clear_all_checkpoints(str(tmp_path)) == 2
        assert not list(cp_dir.glob("*.db"))


class TestCheckpointStep:
    def test_no_db_returns_none(self, tmp_path):
        from tradingagents.graph.checkpointer import checkpoint_step
        assert checkpoint_step(str(tmp_path), "AAPL", "2025-01-10") is None

    def test_has_checkpoint_false(self, tmp_path):
        from tradingagents.graph.checkpointer import has_checkpoint
        assert has_checkpoint(str(tmp_path), "AAPL", "2025-01-10") is False


class TestClearCheckpoint:
    def test_no_db_is_noop(self, tmp_path):
        from tradingagents.graph.checkpointer import clear_checkpoint
        clear_checkpoint(str(tmp_path), "AAPL", "2025-01-10")  # should not raise

    def test_clear_with_db(self, tmp_path):
        from tradingagents.graph.checkpointer import _db_path, clear_checkpoint, get_checkpointer
        # Create the DB so it exists
        with get_checkpointer(str(tmp_path), "AAPL") as saver:
            pass
        clear_checkpoint(str(tmp_path), "AAPL", "2025-01-10")  # should not raise
