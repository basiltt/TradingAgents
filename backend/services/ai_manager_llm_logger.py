"""Async batch buffer for LLM call logging."""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_FINANCIAL_PATTERN = re.compile(
    r'\$[\d,]+\.?\d*'
    r'|\d+\.\d+%'
    r'|\b\d{5,}\b'
)


def sanitize_reasoning(text: str | None, max_len: int = 200) -> str | None:
    """Strip financial figures from reasoning text and truncate."""
    if text is None:
        return None
    sanitized = _FINANCIAL_PATTERN.sub('[—]', text)
    return sanitized[:max_len]


class LLMCallBatchLogger:
    """Async batch buffer for LLM call log entries.

    Flushes to DB when buffer reaches flush_count entries or flush_interval_s
    seconds elapse. On flush failure: retry once, then drop.
    """

    def __init__(
        self,
        repo: Any,
        flush_interval_s: float = 5.0,
        flush_count: int = 10,
        max_buffer: int = 100,
    ):
        self._repo = repo
        self._flush_interval_s = flush_interval_s
        self._flush_count = flush_count
        self._max_buffer = max_buffer
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info("LLMCallBatchLogger started")

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()
        logger.info("LLMCallBatchLogger stopped")

    async def log_call(
        self,
        account_id: str,
        call_id: UUID,
        evaluation_cycle_id: UUID,
        node_name: str,
        timestamp: datetime,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        success: bool,
        urgency_tier: str,
        action_returned: str | None = None,
        confidence: float | None = None,
        reasoning: str | None = None,
        attempt_number: int = 1,
    ) -> None:
        if not self._running:
            return
        entry = {
            'account_id': account_id,
            'call_id': call_id,
            'evaluation_cycle_id': evaluation_cycle_id,
            'node_name': node_name,
            'timestamp': timestamp,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'latency_ms': latency_ms,
            'success': success,
            'urgency_tier': urgency_tier,
            'action_returned': action_returned,
            'confidence': confidence,
            'reasoning_preview': sanitize_reasoning(reasoning),
            'attempt_number': attempt_number,
        }
        async with self._lock:
            if len(self._buffer) >= self._max_buffer:
                logger.warning("LLM log buffer full (%d), dropping oldest", self._max_buffer)
                self._buffer.pop(0)
            self._buffer.append(entry)
            should_flush = len(self._buffer) >= self._flush_count

        if should_flush:
            await self._flush()

    async def _periodic_flush(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval_s)
            await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            to_flush = self._buffer.copy()
            self._buffer.clear()

        try:
            await self._repo.insert_llm_calls_batch(to_flush)
        except Exception as e:
            logger.warning("LLM log flush failed (attempt 1): %s", e)
            try:
                await self._repo.insert_llm_calls_batch(to_flush)
            except Exception as e2:
                logger.error("LLM log flush failed (attempt 2), dropping %d entries: %s", len(to_flush), e2)
