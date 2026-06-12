"""CooloffClassifier — deferred, fail-open classification of scanner cycles.

This is the LIVE half of the Cool Off Time engine. It runs in its OWN transaction,
NEVER inside a trade-close transaction (D16): a cool-off bug can therefore only ever
delay or skip a PAUSE — it can never roll back or delay a position close.

Driven three ways (all idempotent via the monotonic (closed_at, id) high-water mark):
  (a) a post-commit fire-and-forget trigger from trade_service (latency),
  (b) a 60s per-account sweep (authoritative safety net),
  (c) a gate-time synchronous call from the executor before reading cool-off status.

For an account it: takes a non-blocking per-account advisory lock; if the account is
flat (zero open scanner positions); walks the closed scanner trades since the high-water
mark, splitting at flat boundaries; for the earliest complete + fully-settled episode it
sums net_pnl, classifies via cooloff_core, updates the streak, and arms a cool-off
(anchored at the episode's max(closed_at)). A permanently-unsettled episode older than
STALE_MIN is advanced as neutral with an ERROR alert so it can't starve later episodes.

Spec: FR-008/009, arch §3/§4/§10. Decisions D16/D17/D22/D31/D32/D38/D43/D51, CR-4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from backend.services import cooloff_core
from backend.services.cooloff_core import (
    STALE_MIN_MINUTES,
    CooloffSettings,
    StreakState,
    classify_outcome,
)

logger = logging.getLogger(__name__)

_SETTING_KEYS = (
    "success_enabled", "success_minutes",
    "failure_enabled", "failure_minutes",
    "double_success_enabled", "double_success_minutes",
    "double_failure_enabled", "double_failure_minutes",
)


def _settings_from_row(row: dict) -> CooloffSettings:
    return CooloffSettings(
        success_enabled=bool(row.get("success_enabled")),
        success_minutes=row.get("success_minutes"),
        failure_enabled=bool(row.get("failure_enabled")),
        failure_minutes=row.get("failure_minutes"),
        double_success_enabled=bool(row.get("double_success_enabled")),
        double_success_minutes=row.get("double_success_minutes"),
        double_failure_enabled=bool(row.get("double_failure_enabled")),
        double_failure_minutes=row.get("double_failure_minutes"),
    )


@dataclass
class _Episode:
    trades: list[dict]
    max_closed_at: datetime
    max_id: str
    net_pnl: float
    all_settled: bool


def _is_settled(trade: dict) -> bool:
    """A closed trade is settled once its realized P&L is final.

    The failure-close placeholder path writes exit_price=0 AND net_pnl=0.0; the
    reconciler later backfills the real net_pnl (and a real exit_price) via a direct
    UPDATE that does not touch closed_at. So 'settled' = exit_price<>0 OR net_pnl<>0
    (D31/D43): either a real exit price or a real non-zero P&L means the values landed.
    A genuine breakeven (net_pnl exactly 0) has a real exit_price>0, so it is caught by
    the exit_price<>0 arm.
    """
    exit_price = trade.get("exit_price")
    net_pnl = trade.get("net_pnl")
    ep = float(exit_price) if exit_price is not None else 0.0
    np_ = float(net_pnl) if net_pnl is not None else 0.0
    return ep != 0.0 or np_ != 0.0


def split_earliest_episode(rows: list[dict]) -> Optional[_Episode]:
    """Reconstruct the EARLIEST flat-bounded episode from closed scanner trades.

    `rows` are closed scanner trades after the high-water mark, ordered by (closed_at, id).
    The classifier only calls this when the account is currently flat (zero open scanner
    positions), so every row belongs to an already-closed episode. An episode boundary is
    where, replaying opened_at(+1)/closed_at(-1) in time order, the running open count
    returns to 0. On equal timestamps a close (-1) is applied before an open (+1) so a
    close@T and a new open@T split into two episodes (D45 parity with the backtest).

    Invariant (P3B-F1): episodes are contiguous in (closed_at, id) order because any
    episode opening after a flat point at instant M opens at >= M, so a later episode can
    only tie M via a zero-duration trade (opened_at == closed_at == M) — unreachable at
    real microsecond fill timestamps. The high-water (closed_at, id) advance is therefore
    skip-free in practice.

    Returns the earliest episode (the rows up to and including the first flat point), or
    None if `rows` is empty.
    """
    if not rows:
        return None

    # Build a time-ordered event stream: each trade contributes an OPEN at opened_at and
    # a CLOSE at closed_at. Sort by (timestamp, kind) with CLOSE(0) before OPEN(1) on ties.
    events: list[tuple[datetime, int, int]] = []  # (ts, kind 0=close/1=open, row_index)
    for idx, r in enumerate(rows):
        opened = r.get("opened_at")
        closed = r.get("closed_at")
        if opened is not None:
            events.append((_aware(opened), 1, idx))
        if closed is not None:
            events.append((_aware(closed), 0, idx))

    events.sort(key=lambda e: (e[0], e[1]))

    open_count = 0
    seen_open = False
    cohort_idx: set[int] = set()
    boundary_pos: Optional[int] = None
    for pos, (_ts, kind, idx) in enumerate(events):
        cohort_idx.add(idx)
        if kind == 1:  # open
            open_count += 1
            seen_open = True
        else:  # close
            open_count = max(0, open_count - 1)
        if seen_open and open_count == 0:
            boundary_pos = pos
            break

    if boundary_pos is None:
        # No complete flat boundary within these rows (shouldn't happen when the account
        # is confirmed flat, but be defensive): treat ALL rows as one episode.
        cohort_rows = rows
    else:
        cohort_rows = [rows[i] for i in sorted(cohort_idx)]

    max_closed_at = max(_aware(r["closed_at"]) for r in cohort_rows)
    # max_id among the trades sharing max_closed_at (the (closed_at,id) high-water tuple)
    tied = [r for r in cohort_rows if _aware(r["closed_at"]) == max_closed_at]
    max_id = max(str(r["id"]) for r in tied)
    net = sum(float(r.get("net_pnl") or 0.0) for r in cohort_rows)
    all_settled = all(_is_settled(r) for r in cohort_rows)
    return _Episode(cohort_rows, max_closed_at, max_id, net, all_settled)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class CooloffClassifier:
    def __init__(self, db: Any, repo: Any, *, now_fn: Callable[[], datetime] = None):
        self._db = db
        self._repo = repo
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    async def maybe_classify(self, account_id: str) -> None:
        """Classify any newly-completed scanner episodes for the account and arm cool-offs.

        Fully fail-open: the entire body is wrapped so a cool-off failure never raises into
        the caller (a post-commit trigger, the sweep, or the gate). Runs in its own txn.
        """
        try:
            await self._classify(account_id)
        except Exception:  # noqa: BLE001 — cool-off must never break the caller
            logger.warning("cooloff_classify_failed", extra={"account_id": account_id}, exc_info=True)

    async def _classify(self, account_id: str) -> None:
        # Skip immediately if the account has no settings row with any tier enabled.
        state = await self._repo.get_state(account_id)
        if not state or not cooloff_core.any_tier_enabled(_settings_from_row(state)):
            return
        settings = _settings_from_row(state)

        async with self._db.pool.acquire() as conn, conn.transaction():
            if not await self._repo.try_lock(conn, account_id):
                return  # another trigger/sweep owns this account right now

            # Loop: process complete episodes one at a time until caught up.
            while True:
                open_count = await self._repo.count_open_scanner(conn, account_id)
                if open_count > 0:
                    return  # not flat — episode still in progress (CO-DET-5)

                # re-read state inside the loop so streak/high-water reflect prior iterations
                cur = await self._repo.get_state_conn(conn, account_id)
                mark_at = cur.get("last_processed_close_at") if cur else None
                mark_id = str(cur["last_processed_close_id"]) if cur and cur.get("last_processed_close_id") else None
                wins = int(cur.get("consecutive_wins") or 0) if cur else 0
                losses = int(cur.get("consecutive_losses") or 0) if cur else 0

                rows = await self._repo.fetch_unprocessed_closed(conn, account_id, mark_at, mark_id)
                episode = split_earliest_episode(rows)
                if episode is None:
                    return  # nothing new

                now = self._now_fn()
                if not episode.all_settled:
                    # Wait for settlement, unless the episode is so old the reconciler has
                    # given up — then advance past it as neutral so it can't starve later ones.
                    if episode.max_closed_at < now - timedelta(minutes=STALE_MIN_MINUTES):
                        logger.error(
                            "cooloff_staleness_escape",
                            extra={"account_id": account_id,
                                   "episode_max_closed_at": episode.max_closed_at.isoformat(),
                                   "trades": len(episode.trades)},
                        )
                        await self._repo.apply_classification(
                            conn, account_id, new_wins=wins, new_losses=losses,
                            mark_at=episode.max_closed_at, mark_id=episode.max_id,
                            cooloff_until=None, cooloff_reason=None, now=now,
                        )
                        continue  # move past it; try the next episode
                    return  # not yet settled, not yet stale — retry next sweep

                outcome = classify_outcome(episode.net_pnl)
                decision = cooloff_core.decide(StreakState(wins, losses), outcome, settings)
                cooloff_until = None
                if decision.arm and decision.duration_minutes is not None:
                    cooloff_until = episode.max_closed_at + timedelta(minutes=decision.duration_minutes)
                await self._repo.apply_classification(
                    conn, account_id,
                    new_wins=decision.streaks.consecutive_wins,
                    new_losses=decision.streaks.consecutive_losses,
                    mark_at=episode.max_closed_at, mark_id=episode.max_id,
                    cooloff_until=cooloff_until, cooloff_reason=decision.reason, now=now,
                )
                if decision.arm:
                    logger.info(
                        "cooloff_armed",
                        extra={"account_id": account_id, "reason": decision.reason,
                               "duration_minutes": decision.duration_minutes,
                               "net_pnl": episode.net_pnl, "trades": len(episode.trades)},
                    )
                else:
                    logger.info(
                        "cooloff_outcome",
                        extra={"account_id": account_id, "outcome": outcome,
                               "net_pnl": episode.net_pnl},
                    )
                # loop to the next episode (high-water strictly advanced -> terminates)
