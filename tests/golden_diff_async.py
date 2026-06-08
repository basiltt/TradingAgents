"""Phase 6 — Golden-diff equivalence harness for the sync vs async graph path.

Runs the SAME ticker(s) through BOTH execution paths and diffs the resulting
final_trade_decision + structured signal data + persisted report sections. The async
conversion is transport-only, so for a deterministic provider (temperature 0 / seed) the
decision and structured fields must be IDENTICAL; only free-text prose may vary.

This is the GATE: do NOT default TRADINGAGENTS_ASYNC_GRAPH=1 until this is clean for the
provider in use across >=20 symbols.

Usage (needs real LLM keys in the environment, same as a live scan):
    python -m tests.golden_diff_async --tickers BTCUSDT ETHUSDT SOLUSDT ...
    python -m tests.golden_diff_async --tickers BTCUSDT --interval 15 --asset crypto

What it does, per ticker:
  1. Build a TradingAgentsGraph (quick_trade crypto by default — the scan hot path).
  2. Drive it via graph.stream(...)  → capture final state  (SYNC)
  3. Drive it via graph.astream(...) → capture final state  (ASYNC)
  4. Diff the decision-relevant fields and report PASS/FAIL.

It compares the decision + structured signal (BUY/SELL/HOLD + levels), NOT raw prose
wording, because LLM prose is nondeterministic even on the sync path across two calls.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict, List, Tuple


# Fields whose EQUALITY is the real quality gate (decision + structured execution plan).
# Prose reports (market_report, news_report, ...) are excluded — they vary run-to-run even
# sync-vs-sync because the LLM is nondeterministic; the structured signal is what trades.
_DECISION_KEYS = [
    "final_trade_decision",
    "trader_investment_plan",
    "_trader_signal_data",
    "investment_plan",
]


def _build_graph(asset: str, interval: str):
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    if asset == "crypto":
        analysts = ["crypto_technical", "crypto_derivatives", "crypto_news"]
    else:
        analysts = ["market", "news"]
    # TradingAgentsGraph does NOT merge a partial config with defaults — it uses the dict
    # as-is. So start from DEFAULT_CONFIG (which already reads TRADINGAGENTS_* / provider
    # env vars) and override only the run-shape keys. This matches how a live scan builds it.
    config = dict(DEFAULT_CONFIG)
    config.update({
        "workflow_mode": "quick_trade",
        "asset_type": asset,
        "crypto_interval": interval if asset == "crypto" else config.get("crypto_interval"),
        "max_debate_rounds": 1,
    })
    graph = TradingAgentsGraph(config=config, selected_analysts=analysts)
    return graph, config


def _initial_state(graph, ticker: str, asset: str, interval: str) -> Dict[str, Any]:
    return graph.propagator.create_initial_state(
        ticker, "2026-01-01",
        past_context="",
        asset_type=asset,
        crypto_interval=interval if asset == "crypto" else None,
    )


def _final_from_chunks(chunks: List[dict]) -> Dict[str, Any]:
    """Merge stream chunks into the last-known value per node-key (the final state)."""
    final: Dict[str, Any] = {}
    for chunk in chunks:
        for _node, payload in chunk.items():
            if isinstance(payload, dict):
                final.update(payload)
    return final


def _signal_repr(v: Any) -> Any:
    """Normalise a structured signal (pydantic / dict) to a comparable JSON-ish form."""
    if v is None:
        return None
    if hasattr(v, "model_dump"):
        return v.model_dump()
    return v


def _decision_view(state: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k in _DECISION_KEYS:
        out[k] = _signal_repr(state.get(k))
    return out


def _run_sync(graph, ticker, asset, interval, args) -> Dict[str, Any]:
    chunks = list(graph.graph.stream(_initial_state(graph, ticker, asset, interval), **args))
    return _decision_view(_final_from_chunks(chunks))


def _run_async(graph, ticker, asset, interval, args) -> Dict[str, Any]:
    async def _arun():
        return [c async for c in graph.graph.astream(_initial_state(graph, ticker, asset, interval), **args)]
    chunks = asyncio.run(_arun())
    return _decision_view(_final_from_chunks(chunks))


def _diff(a: Dict[str, Any], b: Dict[str, Any], a_label: str, b_label: str) -> Tuple[bool, str]:
    if a == b:
        return True, "identical decision + structured signal"
    diffs = []
    for k in _DECISION_KEYS:
        if a.get(k) != b.get(k):
            diffs.append(
                f"  {k}:\n    {a_label}={json.dumps(a.get(k), default=str)[:300]}"
                f"\n    {b_label}={json.dumps(b.get(k), default=str)[:300]}"
            )
    return False, "DIVERGENCE:\n" + "\n".join(diffs)


def run_ticker(ticker: str, asset: str, interval: str, baseline: bool = False) -> Tuple[bool, str]:
    """Compare two runs of the SAME ticker.

    baseline=False (default): sync path vs async path — the real equivalence gate.
    baseline=True: sync path vs sync path — measures the MODEL's own run-to-run variance,
      so a non-deterministic provider can be told apart from an actual async bug.
    """
    graph, _ = _build_graph(asset, interval)
    args = graph.propagator.get_graph_args(callbacks=[])

    first = _run_sync(graph, ticker, asset, interval, args)
    if baseline:
        second = _run_sync(graph, ticker, asset, interval, args)
        return _diff(first, second, "sync#1", "sync#2")
    second = _run_async(graph, ticker, asset, interval, args)
    return _diff(first, second, "sync", "async")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", required=True)
    ap.add_argument("--asset", default="crypto", choices=["crypto", "stock"])
    ap.add_argument("--interval", default="15")
    ap.add_argument("--baseline", action="store_true",
                    help="Run sync-vs-sync to measure the model's own nondeterminism first.")
    args = ap.parse_args()

    mode = "sync-vs-sync BASELINE (model variance)" if args.baseline else "sync-vs-ASYNC (equivalence gate)"
    print(f"=== {mode} ===")
    passed = 0
    for t in args.tickers:
        try:
            ok, detail = run_ticker(t, args.asset, args.interval, baseline=args.baseline)
        except Exception as exc:  # noqa: BLE001 — a crash on one ticker shouldn't hide the rest
            ok, detail = False, f"EXCEPTION: {type(exc).__name__}: {exc}"
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {t}: {detail}")
        passed += int(ok)

    total = len(args.tickers)
    print(f"\n=== {passed}/{total} tickers identical (sync==async) ===")
    print("GATE: only set TRADINGAGENTS_ASYNC_GRAPH=1 if this is 100% across >=20 symbols.")
    raise SystemExit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
