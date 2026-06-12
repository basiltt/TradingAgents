"""CooloffRepository — async DB access for the Cool Off Time feature.

Owns the `account_cooloff_state` table. NO business logic (that is cooloff_core); this
layer is pure persistence: read state, upsert the settings snapshot (column-scoped, never
touching live/streak/high-water columns), read derived status, clear an active cool-off,
and the classifier's flat-detection queries (open-count, unprocessed-closed window, advisory
lock, atomic classification apply).

Money-safety: all reads are plain SELECT/COUNT (never FOR UPDATE — D42); the advisory lock
is non-blocking (pg_try_advisory_xact_lock — D29/D42); writes are column-scoped so a settings
save can never clobber an active cool-off or streak (D21/D46). Holds the db object and
resolves db.pool per call (matches TradeRepository; never snapshots a raw pool — DP16).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.services.cooloff_core import CLAMP_MAX_DAYS

logger = logging.getLogger(__name__)

# Dedicated advisory-lock class id (two-arg form isolates from the migration lock — D29).
_COOLOFF_LOCK_CLASSID = 786433

_SETTING_COLS = (
    "success_enabled", "success_minutes",
    "failure_enabled", "failure_minutes",
    "double_success_enabled", "double_success_minutes",
    "double_failure_enabled", "double_failure_minutes",
)

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class CooloffRepository:
    """Async CRUD for account_cooloff_state."""

    def __init__(self, db: Any):
        # Hold the db object; resolve db.pool per call (DP16). `db` may be an
        # AsyncAnalysisDB (with a .pool property) or anything exposing `.pool`.
        self._db = db

    @property
    def _pool(self):
        return self._db.pool

    # ── state read ───────────────────────────────────────────────────────────

    async def get_state(self, account_id: str) -> Optional[dict]:
        row = await self._pool.fetchrow(
            "SELECT * FROM account_cooloff_state WHERE account_id = $1", account_id
        )
        return dict(row) if row else None

    async def get_state_conn(self, conn: Any, account_id: str) -> Optional[dict]:
        """Read state on a caller-supplied connection (sees that txn's own writes).

        Used by the classifier loop so each iteration observes the streak/high-water
        it just wrote in the prior iteration.
        """
        row = await conn.fetchrow(
            "SELECT * FROM account_cooloff_state WHERE account_id = $1", account_id
        )
        return dict(row) if row else None

    async def read_status(self, account_id: str, *, now: Optional[datetime] = None) -> dict:
        """Derived cool-off status for the API/UI/gate.

        A known account with no row returns defaults (not cooling, streak 0). The
        cooling flag is a PURE time comparison (FR-029): cooling iff cooloff_until is
        set AND now < cooloff_until. A cooloff_until further out than the corruption
        clamp (now + CLAMP_MAX_DAYS) is treated as corrupt -> not cooling + ERROR +
        best-effort reset (D7/D27/CR-4).
        """
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        row = await self.get_state(account_id)
        if not row:
            return {
                "cooloff_until": None, "cooloff_reason": None,
                "consecutive_wins": 0, "consecutive_losses": 0,
                "cooloff_remaining_seconds": 0, "cooling": False,
                "tiers_enabled": False,
            }
        until = row.get("cooloff_until")
        reason = row.get("cooloff_reason")
        cooling = False
        remaining = 0
        if until is not None:
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            clamp_ceiling = now + timedelta(days=CLAMP_MAX_DAYS)
            if until > clamp_ceiling:
                # Corrupt / impossibly-far value — never let it lock the account out.
                logger.error(
                    "cooloff_until_corrupt_reset",
                    extra={"account_id": account_id, "cooloff_until": until.isoformat()},
                )
                await self._best_effort_clear(account_id, until)
                until, reason = None, None
            elif now < until:
                cooling = True
                remaining = int((until - now).total_seconds())
        return {
            "cooloff_until": until,
            "cooloff_reason": reason,  # chk_cooloff_pair keeps this paired with until
            "consecutive_wins": int(row.get("consecutive_wins") or 0),
            "consecutive_losses": int(row.get("consecutive_losses") or 0),
            "cooloff_remaining_seconds": remaining,
            "cooling": cooling,
            # True if any tier is persisted-enabled — lets the UI offer a per-account
            # "disable cool-off" affordance even when not actively cooling (the manual-only
            # disable escape hatch, since the manual prepass never writes all-OFF).
            "tiers_enabled": bool(
                row.get("success_enabled") or row.get("failure_enabled")
                or row.get("double_success_enabled") or row.get("double_failure_enabled")
            ),
        }

    async def _best_effort_clear(self, account_id: str, expected_until: datetime) -> None:
        """Guarded clear used by the corruption path; never raises."""
        try:
            await self._pool.execute(
                "UPDATE account_cooloff_state SET cooloff_until = NULL, cooloff_reason = NULL, "
                "updated_at = NOW() WHERE account_id = $1 AND cooloff_until = $2",
                account_id, expected_until,
            )
        except Exception:
            logger.warning("cooloff_corrupt_reset_failed", extra={"account_id": account_id})

    # ── settings upsert (column-scoped — never touches state cols) ─────────────

    async def upsert_settings(self, account_id: str, settings: dict) -> None:
        """Upsert ONLY the 8 settings columns + updated_at; never the state columns.

        A settings save can therefore never clobber an active cool-off, streak, or the
        episode high-water mark (D21/D46). The caller is responsible for the clobber
        guard (only call when a tier is enabled).
        """
        # *_enabled cols are NOT NULL; default a missing key to False rather than
        # inserting NULL (defensive — the caller passes a full 8-key snapshot, P2R-F3).
        def _val(c: str):
            v = settings.get(c, False if c.endswith("_enabled") else None)
            return v if v is not None or not c.endswith("_enabled") else False
        vals = [account_id] + [_val(c) for c in _SETTING_COLS]
        placeholders = ", ".join(f"${i}" for i in range(2, len(vals) + 1))
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _SETTING_COLS)
        await self._pool.execute(
            f"""
            INSERT INTO account_cooloff_state (account_id, {", ".join(_SETTING_COLS)}, updated_at)
            VALUES ($1, {placeholders}, NOW())
            ON CONFLICT (account_id) DO UPDATE SET {set_clause}, updated_at = NOW()
            """,
            *vals,
        )

    # ── clear (guarded) ────────────────────────────────────────────────────────

    async def clear(self, account_id: str, reset_streak: bool = False,
                    disable_settings: bool = False) -> bool:
        """Clear an active cool-off (null until/reason). Optionally reset the streak
        and/or DISABLE all tier settings.

        Idempotent. Returns True if a row existed (whether or not it was active).
        Takes the per-account advisory lock inside its own transaction so a manual
        clear is ordered against a concurrent classifier arm (SR-F10/P2R-F1) — a
        clear and an in-flight arm can no longer interleave their writes.

        disable_settings=True also zeroes the 8 tier columns (all *_enabled=false,
        *_minutes=NULL) — the authoritative per-account "turn cool-off off" that works
        regardless of which surface enabled it. This is the manual-surface disable path:
        the manual scanner's settings prepass deliberately never writes all-OFF (so a
        transient manual scan can't wipe a scheduled policy), so unchecking every tier in
        the manual UI alone cannot disable; this flag gives the manual UI an explicit,
        intentional disable that the prepass guard would otherwise swallow.
        """
        set_parts = ["cooloff_until = NULL", "cooloff_reason = NULL"]
        if reset_streak:
            set_parts += ["consecutive_wins = 0", "consecutive_losses = 0"]
        if disable_settings:
            set_parts += [f"{c} = FALSE" for c in _SETTING_COLS if c.endswith("_enabled")]
            set_parts += [f"{c} = NULL" for c in _SETTING_COLS if c.endswith("_minutes")]
        set_parts.append("updated_at = NOW()")
        set_clause = ", ".join(set_parts)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.fetchval(
                "SELECT pg_advisory_xact_lock($1, hashtext($2))",
                _COOLOFF_LOCK_CLASSID, account_id,
            )
            status = await conn.execute(
                f"UPDATE account_cooloff_state SET {set_clause} WHERE account_id = $1",
                account_id,
            )
        try:
            return int(status.split()[-1]) > 0
        except (ValueError, IndexError):
            return False

    # ── classifier queries (operate on a passed-in conn inside the classifier txn) ──

    async def try_lock(self, conn: Any, account_id: str) -> bool:
        """Non-blocking per-account advisory lock (transaction-scoped)."""
        return bool(await conn.fetchval(
            "SELECT pg_try_advisory_xact_lock($1, hashtext($2))",
            _COOLOFF_LOCK_CLASSID, account_id,
        ))

    async def count_open_scanner(self, conn: Any, account_id: str) -> int:
        """Open auto-trade (scanner) positions/orders for the account.

        Includes 'pending' so an unfilled limit/MR pre-submit doesn't look flat.
        """
        return int(await conn.fetchval(
            "SELECT COUNT(*) FROM trades WHERE account_id = $1 AND source = 'scanner' "
            "AND status IN ('pending','open','partially_filled','closing','partially_closed')",
            account_id,
        ))

    async def oldest_open_scanner_opened_at(self, conn: Any, account_id: str):
        """The opened_at of the OLDEST still-open scanner trade (or None if flat).

        Used by the classifier to detect a position stuck open far longer than any real
        trade should last — a never-flat account would otherwise silently block cool-off
        arming forever. This only drives an ERROR alert (it never fabricates flatness, so
        a genuinely-open position can't be misclassified as a completed episode)."""
        return await conn.fetchval(
            "SELECT MIN(opened_at) FROM trades WHERE account_id = $1 AND source = 'scanner' "
            "AND status IN ('pending','open','partially_filled','closing','partially_closed')",
            account_id,
        )

    async def fetch_unprocessed_closed(
        self, conn: Any, account_id: str, mark_at: Optional[datetime], mark_id: Optional[str]
    ) -> list[dict]:
        """Closed scanner trades after the composite (closed_at, id) high-water mark.

        NULL-safe via COALESCE so a never-classified account reads from the beginning.
        Ordered by (closed_at, id) — the deterministic tiebreak (D45). No LIMIT: the
        open==0 flat-gate guarantees these are complete episodes (DP1).
        """
        rows = await conn.fetch(
            """
            SELECT id, opened_at, closed_at, net_pnl, exit_price, status
            FROM trades
            WHERE account_id = $1 AND source = 'scanner' AND status = 'closed'
              AND (closed_at, id) > (COALESCE($2, '-infinity'::timestamptz), COALESCE($3::uuid, $4::uuid))
            ORDER BY closed_at, id
            """,
            account_id, mark_at, mark_id, _ZERO_UUID,
        )
        return [dict(r) for r in rows]

    async def apply_classification(
        self, conn: Any, account_id: str, *,
        new_wins: int, new_losses: int,
        mark_at: datetime, mark_id: str,
        cooloff_until: Optional[datetime], cooloff_reason: Optional[str],
        now: Optional[datetime] = None,
    ) -> None:
        """Atomically write the streak + high-water mark, and (when arming) the
        cool-off using max-rearm + corruption clamp.

        When arming: cooloff_until = GREATEST(existing, LEAST(new, now + CLAMP_MAX_DAYS)),
        and cooloff_reason follows the chosen until (keeps the (until,reason) pair coherent
        under max-rearm — DP16). When not arming, the existing cool-off is left untouched.
        A row is created if absent (settings default off, which is fine — the gate reads
        cooling off the timestamp, not the flags).
        """
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if cooloff_until is not None:
            ceiling = now + timedelta(days=CLAMP_MAX_DAYS)
            capped = min(cooloff_until, ceiling)
            await conn.execute(
                """
                INSERT INTO account_cooloff_state (
                    account_id, consecutive_wins, consecutive_losses,
                    last_processed_close_at, last_processed_close_id,
                    cooloff_until, cooloff_reason, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
                ON CONFLICT (account_id) DO UPDATE SET
                    consecutive_wins = EXCLUDED.consecutive_wins,
                    consecutive_losses = EXCLUDED.consecutive_losses,
                    last_processed_close_at = EXCLUDED.last_processed_close_at,
                    last_processed_close_id = EXCLUDED.last_processed_close_id,
                    cooloff_until = GREATEST(account_cooloff_state.cooloff_until, EXCLUDED.cooloff_until),
                    cooloff_reason = CASE
                        WHEN account_cooloff_state.cooloff_until IS NULL
                             OR EXCLUDED.cooloff_until > account_cooloff_state.cooloff_until
                        THEN EXCLUDED.cooloff_reason
                        ELSE account_cooloff_state.cooloff_reason END,
                    updated_at = NOW()
                """,
                account_id, new_wins, new_losses, mark_at, mark_id, capped, cooloff_reason,
            )
        else:
            await conn.execute(
                """
                INSERT INTO account_cooloff_state (
                    account_id, consecutive_wins, consecutive_losses,
                    last_processed_close_at, last_processed_close_id, updated_at
                ) VALUES ($1,$2,$3,$4,$5,NOW())
                ON CONFLICT (account_id) DO UPDATE SET
                    consecutive_wins = EXCLUDED.consecutive_wins,
                    consecutive_losses = EXCLUDED.consecutive_losses,
                    last_processed_close_at = EXCLUDED.last_processed_close_at,
                    last_processed_close_id = EXCLUDED.last_processed_close_id,
                    updated_at = NOW()
                """,
                account_id, new_wins, new_losses, mark_at, mark_id,
            )
