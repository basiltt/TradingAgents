"""Dual-mode graph node helper — lets one LangGraph node run sync OR async.

LangGraph's sync ``.stream()`` cannot execute an ``async def`` node ("No synchronous
function provided"), and the async ``.astream()`` path is exactly what makes the
multi-agent scan fast (non-blocking LLM calls instead of one-thread-per-graph).

``dual_node(sync_fn, async_fn)`` returns a ``RunnableLambda`` carrying BOTH bodies.
LangGraph then picks automatically:

- ``graph.stream(...)``  → runs ``sync_fn``   (the existing, proven path — flag OFF)
- ``graph.astream(...)`` → runs ``async_fn``  (the new non-blocking path — flag ON)

So a converted node is byte-identical to today on the sync path and concurrent on the
async path. ``async_fn`` must be the exact async mirror of ``sync_fn`` (same prompt,
same state writes) — only the LLM call is awaited.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from langchain_core.runnables import RunnableLambda


def dual_node(sync_fn: Callable[[dict], dict], async_fn: Callable[[dict], Awaitable[dict]]):
    """Wrap a (sync, async) node pair into a single dual-mode graph node.

    The returned RunnableLambda runs sync_fn under .stream() and async_fn under
    .astream(); a node name is preserved for LangGraph's stream-chunk keys.
    """
    runnable = RunnableLambda(sync_fn, afunc=async_fn)
    # Preserve a stable name so stream-chunk keys / tracing match the sync closure.
    name = getattr(sync_fn, "__name__", None)
    if name:
        try:
            runnable.name = name
        except Exception:  # RunnableLambda.name is settable, but never let this break wiring
            pass
    return runnable
