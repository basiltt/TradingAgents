"""AI Manager Multi-Position Correlation.

Detects when multiple positions are effectively the same bet.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List


class CorrelationAnalyzer:
    """Computes pairwise correlation between position symbols."""

    def __init__(self, correlation_threshold: float = 0.7):
        self._threshold = correlation_threshold

    def compute(self, positions: List[Dict[str, Any]], klines: Dict[str, Dict[str, List]]) -> Dict[str, Any]:
        if len(positions) < 2:
            return {"matrix": {}, "portfolio_heat": 0.0, "clusters": [], "max_correlated_exposure_pct": 0.0}

        symbols = [p["symbol"] for p in positions if p.get("symbol")]
        symbols = list(dict.fromkeys(symbols))

        if len(symbols) < 2:
            return {"matrix": {}, "portfolio_heat": 0.0, "clusters": [], "max_correlated_exposure_pct": 0.0}

        returns = {}
        for sym in symbols:
            sym_klines = klines.get(sym, {}).get("1h", [])
            if len(sym_klines) >= 10:
                closes = [float(k[4]) for k in sym_klines]
                returns[sym] = [
                    (closes[i] - closes[i-1]) / closes[i-1]
                    for i in range(1, len(closes))
                    if closes[i-1] != 0
                ]

        matrix = {}
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i+1:]:
                if s1 in returns and s2 in returns:
                    corr = self._pearson(returns[s1], returns[s2])
                    matrix[f"{s1}:{s2}"] = round(corr, 4)

        heat = self._compute_heat(positions, matrix)
        clusters = self._detect_clusters(positions, matrix)

        max_exposure = 0.0
        total_notional = sum(abs(float(p.get("positionValue", 0))) for p in positions)
        for c in clusters:
            if total_notional > 0:
                pct = c["combined_notional_usd"] / total_notional * 100
                max_exposure = max(max_exposure, pct)

        return {
            "matrix": matrix,
            "portfolio_heat": round(heat, 4),
            "clusters": clusters,
            "max_correlated_exposure_pct": round(max_exposure, 2),
        }

    def _pearson(self, x: List[float], y: List[float]) -> float:
        n = min(len(x), len(y))
        if n < 5:
            return 0.0
        x, y = x[:n], y[:n]
        mx, my = sum(x) / n, sum(y) / n
        sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
        sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)
        if sx == 0 or sy == 0:
            return 0.0
        cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n
        return max(-1.0, min(1.0, cov / (sx * sy)))

    def _compute_heat(self, positions: List[Dict], matrix: Dict[str, float]) -> float:
        if not matrix:
            return 0.0
        total = sum(abs(float(p.get("positionValue", 0))) for p in positions)
        if total == 0:
            return 0.0

        heat_sum = 0.0
        pair_count = 0
        pos_map = {p["symbol"]: p for p in positions}

        for pair, corr in matrix.items():
            s1, s2 = pair.split(":")
            p1, p2 = pos_map.get(s1), pos_map.get(s2)
            if not p1 or not p2:
                continue
            same_dir = 1.0 if p1.get("side") == p2.get("side") else -1.0
            # Risk (heat) is high when: same direction + positive correlation (same-way bet)
            # Risk is low when: opposite directions OR negative correlation (hedging effect)
            risk_weight = 1.0 if same_dir > 0 and corr > 0 else 0.1
            heat_sum += abs(corr) * risk_weight
            pair_count += 1

        return min(1.0, heat_sum / max(1, pair_count)) if pair_count else 0.0

    def _detect_clusters(self, positions: List[Dict], matrix: Dict[str, float]) -> List[Dict[str, Any]]:
        pos_map = {p["symbol"]: p for p in positions}
        symbols = list(pos_map.keys())
        visited = set()
        clusters = []

        for sym in symbols:
            if sym in visited:
                continue
            cluster_syms = [sym]
            visited.add(sym)
            for other in symbols:
                if other in visited:
                    continue
                key = f"{sym}:{other}" if f"{sym}:{other}" in matrix else f"{other}:{sym}"
                corr = matrix.get(key, 0.0)
                if abs(corr) >= self._threshold:
                    cluster_syms.append(other)
                    visited.add(other)

            if len(cluster_syms) >= 2:
                notional = sum(abs(float(pos_map[s].get("positionValue", 0))) for s in cluster_syms)
                corrs = []
                for i, s1 in enumerate(cluster_syms):
                    for s2 in cluster_syms[i+1:]:
                        key = f"{s1}:{s2}" if f"{s1}:{s2}" in matrix else f"{s2}:{s1}"
                        corrs.append(abs(matrix.get(key, 0.0)))
                avg_corr = sum(corrs) / len(corrs) if corrs else 0.0
                sides = [pos_map[s].get("side", "Buy") for s in cluster_syms]
                net_dir = "long" if sides.count("Buy") > sides.count("Sell") else "short"

                clusters.append({
                    "symbols": cluster_syms,
                    "avg_correlation": round(avg_corr, 4),
                    "net_direction": net_dir,
                    "combined_notional_usd": notional,
                    "combined_pnl_pct": 0.0,
                })

        return clusters
