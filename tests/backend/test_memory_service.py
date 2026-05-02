"""Tests for memory service — TASK-006."""

import pytest


@pytest.fixture
def memory_file(tmp_path):
    return tmp_path / "trading_memory.md"


@pytest.fixture
def memory_service(memory_file):
    from backend.services.memory_service import MemoryService

    return MemoryService(memory_path=str(memory_file))


SAMPLE_MEMORY = """\
## SPY | 2025-06-01 | BUY | High | resolved
Reasoning: Strong momentum signals.

## AAPL | 2025-05-15 | SELL | Medium | pending
Reasoning: Overvalued based on fundamentals.

## TSLA | 2025-05-10 | HOLD | Low | resolved
Reasoning: Mixed signals from analysts.
"""


def test_empty_file(memory_service, memory_file):
    memory_file.write_text("")
    result = memory_service.get_entries(page=1, limit=10)
    assert result["total"] == 0
    assert result["items"] == []


def test_missing_file(memory_service):
    result = memory_service.get_entries(page=1, limit=10)
    assert result["total"] == 0
    assert result["items"] == []


def test_parse_entries(memory_service, memory_file):
    memory_file.write_text(SAMPLE_MEMORY)
    result = memory_service.get_entries(page=1, limit=10)
    assert result["total"] == 3
    assert result["items"][0]["ticker"] == "SPY"
    assert result["items"][0]["decision"] == "BUY"


def test_pagination(memory_service, memory_file):
    memory_file.write_text(SAMPLE_MEMORY)
    result = memory_service.get_entries(page=1, limit=2)
    assert len(result["items"]) == 2
    assert result["total"] == 3

    result2 = memory_service.get_entries(page=2, limit=2)
    assert len(result2["items"]) == 1


def test_malformed_entries_skipped(memory_service, memory_file):
    content = """\
## SPY | 2025-06-01 | BUY | High | resolved
Reasoning: Good.

## This is malformed no pipes

## AAPL | 2025-05-15 | SELL | Medium | pending
Reasoning: Bad.
"""
    memory_file.write_text(content)
    result = memory_service.get_entries(page=1, limit=10)
    assert result["total"] == 2


def test_cache_invalidation(memory_service, memory_file):
    memory_file.write_text(SAMPLE_MEMORY)
    result1 = memory_service.get_entries(page=1, limit=10)
    assert result1["total"] == 3

    import time
    time.sleep(0.1)

    memory_file.write_text("""\
## GOOG | 2025-06-01 | BUY | High | resolved
Reasoning: Cloud growth.
""")
    result2 = memory_service.get_entries(page=1, limit=10)
    assert result2["total"] == 1
