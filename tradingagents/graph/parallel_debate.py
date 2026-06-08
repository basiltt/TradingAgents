"""Parallel debate wrappers — run round-1 debaters concurrently.

These wrapper nodes call multiple debater functions with the SAME input state
(so they produce independent arguments, as in a real first round) and merge
the results into a single state update.  The graph then continues with
normal sequential edges for subsequent rounds.

Quality guarantee: identical prompts, identical number of debate turns.
The only difference is wall-clock time — round 1 finishes in ~1 LLM call
instead of 2-3.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from typing import Any, Callable, Dict, List

from tradingagents.agents.utils.dual_node import dual_node

logger = logging.getLogger(__name__)


def _invoke_node(fn: Callable, state: Dict[str, Any]) -> Any:
    """Invoke a debater node SYNCHRONOUSLY, whether it's a plain callable or a
    LangChain Runnable (dual_node nodes are RunnableLambda — NOT directly callable)."""
    if hasattr(fn, "invoke"):
        return fn.invoke(state)
    return fn(state)


async def _ainvoke_node(fn: Callable, state: Dict[str, Any]) -> Any:
    """Invoke a debater node ASYNCHRONOUSLY. Uses the Runnable's native ainvoke when
    available (the non-blocking path); falls back to a thread for a plain sync callable."""
    if hasattr(fn, "ainvoke"):
        return await fn.ainvoke(state)
    return await asyncio.to_thread(fn, state)

_MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_ANALYSES", "6"))
_WORKERS_PER_ANALYSIS = int(os.environ.get("DEBATE_WORKERS_PER_ANALYSIS", "3"))
# Pool must accommodate retries: an orphaned timed-out thread still holds its
# slot while the retry runs in a new slot.  Factor of 2 covers worst case.
_DEBATE_EXECUTOR_WORKERS = int(os.environ.get(
    "DEBATE_EXECUTOR_WORKERS",
    str(_MAX_CONCURRENT * _WORKERS_PER_ANALYSIS * 2),
))
_DEBATE_TIMEOUT = int(os.environ.get("DEBATE_TIMEOUT_SECONDS", "420"))
_debate_executor: ThreadPoolExecutor | None = None
_debate_lock = threading.Lock()
_debate_shutting_down = False


def _get_debate_executor() -> ThreadPoolExecutor:
    global _debate_executor
    with _debate_lock:
        if _debate_shutting_down:
            raise RuntimeError("Debate executor is shutting down")
        if _debate_executor is None or _debate_executor._shutdown:
            _debate_executor = ThreadPoolExecutor(
                max_workers=_DEBATE_EXECUTOR_WORKERS,
                thread_name_prefix="debate",
            )
    return _debate_executor


def shutdown_debate_executor():
    global _debate_executor, _debate_shutting_down
    with _debate_lock:
        _debate_shutting_down = True
        if _debate_executor is not None:
            _debate_executor.shutdown(wait=False, cancel_futures=True)
            _debate_executor = None


def reset_debate_executor():
    global _debate_executor, _debate_shutting_down
    with _debate_lock:
        _debate_shutting_down = False
        if _debate_executor is not None:
            _debate_executor.shutdown(wait=False, cancel_futures=True)
            _debate_executor = None


def _merge_risk_debate_states(
    base_state: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge multiple debater outputs into a single risk_debate_state."""
    risk = dict(base_state["risk_debate_state"])
    base_history = risk.get("history", "")

    combined_history = base_history
    count = risk.get("count", 0)

    for result in results:
        r = result["risk_debate_state"]
        # Each debater appended to base_history; extract only the new part
        new_piece = r.get("history", "")[len(base_history):]
        if new_piece.strip():
            combined_history += new_piece
        count += 1

        for key in ("aggressive_history", "conservative_history", "neutral_history"):
            new_val = r.get(key, "")
            old_val = risk.get(key, "")
            if new_val and len(new_val) > len(old_val):
                risk[key] = new_val

        for key in ("current_aggressive_response", "current_conservative_response", "current_neutral_response"):
            if r.get(key) and r[key] != risk.get(key, ""):
                risk[key] = r[key]

    risk["history"] = combined_history
    risk["count"] = count
    risk["latest_speaker"] = results[-1]["risk_debate_state"].get("latest_speaker", "")

    return risk


def _merge_invest_debate_states(
    base_state: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge multiple researcher outputs into a single investment_debate_state."""
    debate = dict(base_state["investment_debate_state"])
    base_history = debate.get("history", "")

    combined_history = base_history
    count = debate.get("count", 0)

    for result in results:
        r = result["investment_debate_state"]
        # Each researcher appended to base_history; extract only the new part
        new_piece = r.get("history", "")[len(base_history):]
        if new_piece.strip():
            combined_history += new_piece
        count += 1

        for key in ("bull_history", "bear_history"):
            new_val = r.get(key, "")
            old_val = debate.get(key, "")
            if new_val and len(new_val) > len(old_val):
                debate[key] = new_val

        if r.get("current_response") and r["current_response"] != debate.get("current_response", ""):
            debate["current_response"] = r["current_response"]

    debate["history"] = combined_history
    debate["count"] = count

    return debate


def _run_with_retry(
    callables: List[Callable],
    state: Dict[str, Any],
    label: str,
) -> List[Any]:
    """Run callables in parallel with a single retry for timed-out futures.

    Returns ordered results matching the input callables list.
    Cancellation is handled at the graph-stream level (analysis_service checks
    cancel_event between stream chunks), not inside individual nodes.
    """
    executor = _get_debate_executor()
    futures = [executor.submit(_invoke_node, fn, copy.deepcopy(state)) for fn in callables]
    done, not_done = futures_wait(futures, timeout=_DEBATE_TIMEOUT)

    if not_done:
        # cancel() only prevents queued futures from starting; already-running
        # threads finish on their own but results are discarded.
        for f in not_done:
            f.cancel()

        timed_out_indices = [i for i, f in enumerate(futures) if f in not_done]
        logger.warning(
            "%s: %d/%d futures timed out after %ds, retrying once",
            label, len(not_done), len(callables), _DEBATE_TIMEOUT,
        )
        for i in timed_out_indices:
            futures[i] = executor.submit(_invoke_node, callables[i], copy.deepcopy(state))
        retry_futures = [futures[i] for i in timed_out_indices]
        _, retry_not_done = futures_wait(retry_futures, timeout=_DEBATE_TIMEOUT)
        if retry_not_done:
            for f in retry_not_done:
                f.cancel()
            raise RuntimeError(
                f"{label}: {len(retry_not_done)}/{len(callables)} futures timed out after retry"
            )

    results = []
    for i, future in enumerate(futures):
        try:
            results.append(future.result())
        except Exception:
            logger.exception("%s: future %d failed", label, i)
            raise

    return results


async def _arun_with_retry(
    callables: List[Callable],
    state: Dict[str, Any],
    label: str,
) -> List[Any]:
    """Async mirror of _run_with_retry. Runs the debaters CONCURRENTLY via asyncio tasks
    and assembles results in ARGUMENT ORDER (so the downstream merge sees the same ordering
    as the sync path). Mirrors the sync retry EXACTLY: on timeout, only the TIMED-OUT
    positions are retried (successful results are kept), and the orphaned timed-out tasks
    are cancelled before the retry so they neither make wasted paid LLM calls nor hold
    concurrency slots. Same per-call deepcopy. Quality is identical; only wall-clock improves."""

    async def _one(fn):
        return await _ainvoke_node(fn, copy.deepcopy(state))

    # Round 1: launch all, wait up to the timeout, keep what finished.
    tasks = [asyncio.ensure_future(_one(fn)) for fn in callables]
    done, pending = await asyncio.wait(tasks, timeout=_DEBATE_TIMEOUT)

    if pending:
        # Cancel the orphans (mirrors the sync path discarding timed-out futures) so they
        # stop mid-call instead of finishing in the background and wasting an LLM call.
        timed_out_indices = [i for i, t in enumerate(tasks) if t in pending]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)  # let cancellation settle

        logger.warning(
            "%s: %d/%d debaters timed out after %ds, retrying once",
            label, len(pending), len(callables), _DEBATE_TIMEOUT,
        )
        # Retry ONLY the timed-out positions, in place.
        retry_tasks = {i: asyncio.ensure_future(_one(callables[i])) for i in timed_out_indices}
        r_done, r_pending = await asyncio.wait(list(retry_tasks.values()), timeout=_DEBATE_TIMEOUT)
        if r_pending:
            for t in r_pending:
                t.cancel()
            await asyncio.gather(*r_pending, return_exceptions=True)
            raise RuntimeError(
                f"{label}: {len(r_pending)}/{len(callables)} debaters timed out after retry"
            )
        for i, t in retry_tasks.items():
            tasks[i] = t

    # Assemble in argument order; surface any task exception like the sync path.
    results = []
    for i, t in enumerate(tasks):
        try:
            results.append(t.result())
        except Exception:
            logger.exception("%s: debater %d failed", label, i)
            raise
    return results


def create_parallel_risk_round1(
    debater_nodes: List[Callable],
) -> Callable:
    """Return a node that runs all debaters in parallel for round 1.

    Works for both 2-party (crypto: bull/bear) and 3-party (stock:
    aggressive/conservative/neutral) debates.
    """
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        results = _run_with_retry(debater_nodes, state, "Risk debate R1")
        merged = _merge_risk_debate_states(state, results)
        return {"risk_debate_state": merged}

    async def anode(state: Dict[str, Any]) -> Dict[str, Any]:
        results = await _arun_with_retry(debater_nodes, state, "Risk debate R1")
        merged = _merge_risk_debate_states(state, results)
        return {"risk_debate_state": merged}

    return dual_node(node, anode)


def create_parallel_researcher_round1(
    bull_researcher: Callable,
    bear_researcher: Callable,
) -> Callable:
    """Return a node that runs bull and bear researchers in parallel for round 1."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        results = _run_with_retry(
            [bull_researcher, bear_researcher], state, "Researcher debate R1"
        )
        merged = _merge_invest_debate_states(state, results)
        return {"investment_debate_state": merged}

    async def anode(state: Dict[str, Any]) -> Dict[str, Any]:
        results = await _arun_with_retry(
            [bull_researcher, bear_researcher], state, "Researcher debate R1"
        )
        merged = _merge_invest_debate_states(state, results)
        return {"investment_debate_state": merged}

    return dual_node(node, anode)
