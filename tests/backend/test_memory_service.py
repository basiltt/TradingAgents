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
[2025-06-01 | SPY | BUY | pending]

DECISION:
Strong momentum signals. Recommend buying.

<!-- ENTRY_END -->

[2025-05-15 | AAPL | SELL | +2.5% | +1.2% | 10d]

DECISION:
Overvalued based on fundamentals.

REFLECTION:
Trade went well, alpha was positive.

<!-- ENTRY_END -->

[2025-05-10 | TSLA | HOLD | -1.0% | -0.5% | 5d]

DECISION:
Mixed signals from analysts.

REFLECTION:
Should have been more cautious.

<!-- ENTRY_END -->

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
    assert result["items"][0]["status"] == "pending"
    assert result["items"][1]["ticker"] == "AAPL"
    assert result["items"][1]["status"] == "resolved"


def test_pagination(memory_service, memory_file):
    memory_file.write_text(SAMPLE_MEMORY)
    result = memory_service.get_entries(page=1, limit=2)
    assert len(result["items"]) == 2
    assert result["total"] == 3

    result2 = memory_service.get_entries(page=2, limit=2)
    assert len(result2["items"]) == 1


def test_malformed_entries_skipped(memory_service, memory_file):
    content = """\
[2025-06-01 | SPY | BUY | pending]

DECISION:
Good.

<!-- ENTRY_END -->

This is malformed no brackets

<!-- ENTRY_END -->

[2025-05-15 | AAPL | SELL | +1.0% | +0.5% | 7d]

DECISION:
Bad.

<!-- ENTRY_END -->

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
[2025-06-01 | GOOG | BUY | pending]

DECISION:
Cloud growth.

<!-- ENTRY_END -->

""")
    result2 = memory_service.get_entries(page=1, limit=10)
    assert result2["total"] == 1
