"""Prompt-cache shaping helpers.

Two responsibilities:
  - apply_cache_control_to_messages: rewrite the first system message to block
    form with an Anthropic `cache_control` breakpoint (used by the litellm wrapper).
  - split_cacheable_prompt: build a Pattern-A prompt template whose system message
    holds only stable text and whose first human turn holds the volatile context.

Pure functions; no I/O. The cache_control block survives langchain-community's
message converter and litellm's Anthropic transform (verified against the
installed libraries).
"""
from typing import Any

from langchain_core.messages import SystemMessage

_EPHEMERAL = {"type": "ephemeral"}


def apply_cache_control_to_messages(messages: list[Any]) -> list[Any]:
    """Return messages with the FIRST system message rewritten to a single
    text block carrying cache_control. No-op if there is no string-content
    system message. Handles both BaseMessage and {"role": ...} dict shapes.
    """
    for i, m in enumerate(messages):
        if isinstance(m, SystemMessage) and isinstance(m.content, str):
            new = m.model_copy(update={"content": [
                {"type": "text", "text": m.content, "cache_control": _EPHEMERAL}]})
            return [*messages[:i], new, *messages[i + 1:]]
        if isinstance(m, dict) and m.get("role") == "system" and isinstance(m.get("content"), str):
            new = {**m, "content": [
                {"type": "text", "text": m["content"], "cache_control": _EPHEMERAL}]}
            return [*messages[:i], new, *messages[i + 1:]]
    return messages
