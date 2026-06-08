"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI/Anthropic, function-calling as fallback, tool-use for others)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _schema_instruction(schema: type[T]) -> str:
    """Build a short JSON-schema reminder for the free-text fallback path.

    Only used when structured output has already failed and we're falling
    back to plain LLM invocation — gives the model a hint of the expected
    output shape so the free-text response is at least semi-structured.
    Not used on the structured path (the provider already handles schema
    enforcement there).
    """
    try:
        s = schema.model_json_schema()
        fields = {}
        for name, prop in s.get("properties", {}).items():
            t = prop.get("type", prop.get("anyOf", "unknown"))
            fields[name] = t
        return (
            "\n\nRespond with a structured analysis covering these fields:\n"
            f"{json.dumps(fields, indent=2)}\n"
        )
    except Exception:
        return ""


def _augment_prompt(prompt: Any, hint: str) -> Any:
    """Append a schema hint to the prompt, handling both str and message-list formats."""
    if not hint:
        return prompt
    if isinstance(prompt, str):
        return prompt + hint
    if isinstance(prompt, list) and prompt:
        last = prompt[-1]
        if isinstance(last, dict) and "content" in last:
            patched = list(prompt)
            patched[-1] = {**last, "content": last["content"] + hint}
            return patched
    return prompt


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Tries ``method="json_schema"`` first (prevents tool-call hallucination by
    forcing direct JSON output), then falls back to the provider default.
    Both bindings are returned so invoke can fall back at runtime.
    """
    methods = ("json_schema", None)
    bindings: list[Any] = []

    for method in methods:
        try:
            kwargs: dict[str, Any] = {}
            if method:
                kwargs["method"] = method
            bound = llm.with_structured_output(schema, **kwargs)
            bindings.append((method, bound))
        except (NotImplementedError, AttributeError, TypeError, ValueError) as exc:
            if method:
                logger.debug(
                    "%s: method=%s not supported at bind time (%s), trying default",
                    agent_name, method, exc,
                )
                continue
            logger.warning(
                "%s: provider does not support with_structured_output (%s); "
                "falling back to free-text generation",
                agent_name, exc,
            )

    if not bindings:
        return None
    if len(bindings) == 1:
        return bindings[0][1]
    return _FallbackStructured(bindings, agent_name)


class _FallbackStructured:
    """Wraps multiple structured bindings; tries each at invoke time.

    After the first successful invoke, remembers which method worked and
    skips failing methods on subsequent calls to avoid repeated 400 errors.
    """

    def __init__(self, bindings: list[tuple], agent_name: str):
        self._bindings = bindings
        self._agent_name = agent_name
        self._skip_methods: set[str | None] = set()

    def invoke(self, prompt: Any) -> Any:
        last_exc = None
        for method, bound in self._bindings:
            if method in self._skip_methods:
                continue
            try:
                result = bound.invoke(prompt)
                if result is None:
                    logger.debug(
                        "%s: method=%s returned None, trying next",
                        self._agent_name, method,
                    )
                    last_exc = ValueError("structured call returned None")
                    continue
                return result
            except Exception as exc:
                exc_str = str(exc)
                if "400" in exc_str or "invalid_request" in exc_str.lower():
                    logger.debug(
                        "%s: method=%s rejected at invoke time (%s), trying next",
                        self._agent_name, method, exc,
                    )
                    self._skip_methods.add(method)
                    last_exc = ValueError(str(exc))
                    continue
                raise
        raise last_exc or RuntimeError("All structured methods failed")

    async def ainvoke(self, prompt: Any) -> Any:
        """Async mirror of invoke(). IDENTICAL fallthrough + skip-method semantics — only
        awaits bound.ainvoke instead of calling bound.invoke. _skip_methods is shared with
        the sync path (a method that 400s is skipped on either)."""
        last_exc = None
        for method, bound in self._bindings:
            if method in self._skip_methods:
                continue
            try:
                result = await bound.ainvoke(prompt)
                if result is None:
                    logger.debug(
                        "%s: method=%s returned None, trying next",
                        self._agent_name, method,
                    )
                    last_exc = ValueError("structured call returned None")
                    continue
                return result
            except Exception as exc:
                exc_str = str(exc)
                if "400" in exc_str or "invalid_request" in exc_str.lower():
                    logger.debug(
                        "%s: method=%s rejected at invoke time (%s), trying next",
                        self._agent_name, method, exc,
                    )
                    self._skip_methods.add(method)
                    last_exc = ValueError(str(exc))
                    continue
                raise
        raise last_exc or RuntimeError("All structured methods failed")


def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    schema: Optional[type[T]] = None,
) -> tuple[str, Optional[BaseModel]]:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    Returns (rendered_text, typed_object_or_none).
    The typed object is None on the free-text fallback path.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            if result is None:
                raise ValueError("structured call returned None")
            return render(result), result
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    schema_hint = _schema_instruction(schema) if schema else ""
    response = plain_llm.invoke(_augment_prompt(prompt, schema_hint))
    return response.content or "", None


async def ainvoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
    schema: Optional[type[T]] = None,
) -> tuple[str, Optional[BaseModel]]:
    """Async mirror of invoke_structured_or_freetext. IDENTICAL behavior — structured
    call first, render on success, free-text fallback on any failure — only awaited. Output
    matches the sync function for the same input."""
    if structured_llm is not None:
        try:
            result = await structured_llm.ainvoke(prompt)
            if result is None:
                raise ValueError("structured call returned None")
            return render(result), result
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    schema_hint = _schema_instruction(schema) if schema else ""
    response = await plain_llm.ainvoke(_augment_prompt(prompt, schema_hint))
    return response.content or "", None
