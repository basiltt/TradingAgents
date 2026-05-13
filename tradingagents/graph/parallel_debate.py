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

import concurrent.futures
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_ANALYSES", "6"))
_WORKERS_PER_ANALYSIS = int(os.environ.get("DEBATE_WORKERS_PER_ANALYSIS", "5"))
_DEBATE_EXECUTOR_WORKERS = int(os.environ.get(
    "DEBATE_EXECUTOR_WORKERS",
    str(_MAX_CONCURRENT * _WORKERS_PER_ANALYSIS),
))
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


def create_parallel_risk_round1(
    debater_nodes: List[Callable],
) -> Callable:
    """Return a node that runs all debaters in parallel for round 1.

    Works for both 2-party (crypto: bull/bear) and 3-party (stock:
    aggressive/conservative/neutral) debates.
    """
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        ordered_futures = [_get_debate_executor().submit(fn, state) for fn in debater_nodes]
        done, not_done = futures_wait(ordered_futures, timeout=300)
        for f in not_done:
            f.cancel()
        if not_done:
            raise RuntimeError(f"{len(not_done)}/{len(ordered_futures)} risk debate futures timed out")

        results = []
        for future in ordered_futures:
            if future in done:
                try:
                    results.append(future.result())
                except Exception:
                    logger.exception("Parallel risk debater failed")
                    raise

        merged = _merge_risk_debate_states(state, results)
        return {"risk_debate_state": merged}

    return node


def create_parallel_researcher_round1(
    bull_researcher: Callable,
    bear_researcher: Callable,
) -> Callable:
    """Return a node that runs bull and bear researchers in parallel for round 1."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        bull_future = _get_debate_executor().submit(bull_researcher, state)
        bear_future = _get_debate_executor().submit(bear_researcher, state)
        done, not_done = futures_wait([bull_future, bear_future], timeout=300)
        for f in not_done:
            f.cancel()
        if not_done:
            raise RuntimeError(f"{len(not_done)}/2 researcher futures timed out")

        bull_result = bull_future.result()
        bear_result = bear_future.result()

        merged = _merge_invest_debate_states(state, [bull_result, bear_result])
        return {"investment_debate_state": merged}

    return node
