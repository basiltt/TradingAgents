"""SweepRepository — TASK-P4-12b (G1).

All SQL for mcp_sweep_jobs + mcp_sweep_results. A sweep job tracks an async
parameter sweep (queued→running→completed/cancelled/failed/interrupted) and its
per-combo results; the agent fire-and-polls by sweep_id, and a finished sweep can
be re-ranked by an alternate stored objective WITHOUT re-running (FR-040).

All asyncpg lives here (no SQL in tools/orchestrator — §F). Each result is
written in its own committed txn so a crash leaves a resumable partial sweep.
"""
from __future__ import annotations

import json
import math
from typing import Any, Optional

import asyncpg

# Re-rankable objective metrics → "min" means lower is better.
_MINIMIZE = {"max_drawdown"}


def _nan_to_null(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so the persisted JSON is
    strictly valid (NFR-012: NaN/Inf → NULL at the persist boundary). Postgres
    jsonb rejects the bare `NaN`/`Infinity` tokens json.dumps would otherwise
    emit, and a downstream strict parser would choke on them."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _nan_to_null(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_to_null(v) for v in obj]
    return obj


def _safe_objective(v: Optional[float]) -> Optional[float]:
    """NaN/Inf objective → NULL (NUMERIC column rejects non-finite)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _loads(v: Any) -> Any:
    if v is None or isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return v


def _job_row(r: asyncpg.Record) -> dict[str, Any]:
    d = dict(r)
    for k in ("param_space",):
        if k in d:
            d[k] = _loads(d[k])
    for k in ("id", "best_result_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("created_at", "started_at", "completed_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


def _result_row(r: asyncpg.Record) -> dict[str, Any]:
    d = dict(r)
    for k in ("config", "metrics"):
        if k in d:
            d[k] = _loads(d[k])
    for k in ("id", "sweep_id", "backtest_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if d.get("objective_value") is not None:
        d["objective_value"] = float(d["objective_value"])
    if d.get("created_at") is not None and hasattr(d["created_at"], "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d


class SweepRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_job(
        self,
        *,
        strategy: str,
        param_space: dict[str, Any],
        objective_metric: str,
        total_combos: int,
        principal_token_id: Optional[str] = None,
        session_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        async with self._pool.acquire() as conn:
            sid = await conn.fetchval(
                """
                INSERT INTO mcp_sweep_jobs
                  (status, strategy, param_space, objective_metric, total_combos,
                   principal_token_id, session_id, idempotency_key, started_at)
                VALUES ('running',$1,$2::jsonb,$3,$4,$5,$6,$7, now())
                RETURNING id
                """,
                strategy, json.dumps(param_space), objective_metric, total_combos,
                principal_token_id, session_id, idempotency_key,
            )
        return str(sid)

    async def write_result(
        self,
        *,
        sweep_id: str,
        config: dict[str, Any],
        config_hash: str,
        metrics: dict[str, Any],
        objective_value: Optional[float],
        result_rank: Optional[int] = None,
    ) -> None:
        """Persist one combo result in its OWN txn + bump completed_combos.
        Idempotent on (sweep_id, config_hash)."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                    INSERT INTO mcp_sweep_results
                      (sweep_id, config, config_hash, metrics, objective_value, result_rank)
                    VALUES ($1,$2::jsonb,$3,$4::jsonb,$5,$6)
                    ON CONFLICT (sweep_id, config_hash) DO UPDATE
                      SET metrics = EXCLUDED.metrics,
                          objective_value = EXCLUDED.objective_value,
                          result_rank = EXCLUDED.result_rank
                    """,
                sweep_id, json.dumps(config), config_hash,
                json.dumps(_nan_to_null(metrics)), _safe_objective(objective_value),
                result_rank,
            )
            await conn.execute(
                "UPDATE mcp_sweep_jobs SET completed_combos = "
                "LEAST(completed_combos + 1, total_combos) WHERE id = $1",
                sweep_id,
            )

    async def finish_job(
        self, sweep_id: str, *, status: str, best_result_id: Optional[str] = None
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE mcp_sweep_jobs SET status=$1, best_result_id=$2, "
                "completed_at=now() WHERE id=$3",
                status, best_result_id, sweep_id,
            )

    async def cancel_job(self, sweep_id: str) -> bool:
        """Mark a running/queued sweep cancelled (partial results kept)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE mcp_sweep_jobs SET status='cancelled', completed_at=now() "
                "WHERE id=$1 AND status IN ('queued','running') RETURNING id",
                sweep_id,
            )
        return row is not None

    async def get_job(self, sweep_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM mcp_sweep_jobs WHERE id=$1", sweep_id)
        return _job_row(row) if row else None

    async def list_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mcp_sweep_jobs ORDER BY created_at DESC LIMIT $1", limit
            )
        return [_job_row(r) for r in rows]

    async def completed_config_hashes(self, sweep_id: str) -> set[str]:
        """For crash-recovery: the config hashes already persisted for a sweep."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT config_hash FROM mcp_sweep_results WHERE sweep_id=$1", sweep_id
            )
        return {r["config_hash"] for r in rows}

    async def results(
        self, sweep_id: str, *, objective: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return stored results, optionally RE-RANKED by an alternate objective
        server-side (FR-040) — no sweep re-run. Default order is stored rank."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mcp_sweep_results WHERE sweep_id=$1 LIMIT $2",
                sweep_id, max(limit, 1),
            )
        out = [_result_row(r) for r in rows]
        if objective:
            minimize = objective in _MINIMIZE
            from backend.mcp.tools.optimizer.ranker import _resolve_metric

            def _key(row: dict[str, Any]):
                v = _resolve_metric(row.get("metrics", {}), objective)
                # missing/NaN sort last regardless of direction
                if v is None:
                    return (1, 0.0, row.get("config_hash", ""))
                fv = float(v)
                return (0, fv if minimize else -fv, row.get("config_hash", ""))

            out.sort(key=_key)
        else:
            out.sort(key=lambda r: (r.get("result_rank") is None, r.get("result_rank") or 0))
        return out

    async def recover_interrupted(self) -> int:
        """Boot recovery (AC-023): mark sweeps left 'running' by a dead process as
        'interrupted' so they are never perpetually running. Returns the count."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "UPDATE mcp_sweep_jobs SET status='interrupted' "
                "WHERE status='running' RETURNING id"
            )
        return len(rows)
