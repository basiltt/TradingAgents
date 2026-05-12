"""Custom callback handler for LangGraph — emits domain events to event bus — TASK-010."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from backend.stream_parser import MessageEvent, StatsEvent, ToolCallEvent


class WebCallbackHandler(BaseCallbackHandler):
    def __init__(self, run_id: str, event_bus: Any):
        super().__init__()
        self._run_id = run_id
        self._bus = event_bus
        self._tokens_in = 0
        self._tokens_out = 0
        self._llm_calls = 0
        self._tool_calls = 0

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._llm_calls += 1
        model_name = (kwargs.get("invocation_params") or {}).get("model", "")
        if not model_name:
            model_name = (kwargs.get("metadata") or {}).get("ls_model_name", "")
        class_name = serialized.get("name", serialized.get("id", ["unknown"])[-1] if isinstance(serialized.get("id"), list) else "unknown")
        display = f"{class_name} ({model_name})" if model_name else class_name
        self._bus.emit_threadsafe(
            self._run_id,
            MessageEvent(sender="System", content=f"LLM call started: {display}"),
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        # Try OpenAI-style llm_output.token_usage first
        usage = getattr(response, "llm_output", {}) or {}
        token_usage = usage.get("token_usage", {}) or {}
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)

        # Fall back to generation-level usage_metadata (Anthropic, newer LangChain)
        # generations is a list-of-lists: [[ChatGeneration, ...], ...]
        if not prompt_tokens and not completion_tokens:
            for gen_list in getattr(response, "generations", []):
                for gen in (gen_list if isinstance(gen_list, list) else [gen_list]):
                    msg = getattr(gen, "message", None)
                    if msg:
                        um = getattr(msg, "usage_metadata", None) or {}
                        prompt_tokens += um.get("input_tokens", 0)
                        completion_tokens += um.get("output_tokens", 0)

        self._tokens_in += prompt_tokens
        self._tokens_out += completion_tokens
        self._bus.emit_threadsafe(
            self._run_id,
            StatsEvent(
                tokens_in=self._tokens_in,
                tokens_out=self._tokens_out,
                llm_calls=self._llm_calls,
                tool_calls=self._tool_calls,
            ),
        )

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._tool_calls += 1
        tool_name = serialized.get("name", "unknown")
        self._bus.emit_threadsafe(
            self._run_id,
            ToolCallEvent(tool_name=tool_name, args={"input": input_str[:200]}),
        )

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        truncated = output[:200] if isinstance(output, str) else str(output)[:200]
        self._bus.emit_threadsafe(
            self._run_id,
            MessageEvent(sender="Tool", content=truncated),
        )
