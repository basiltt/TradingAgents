"""Deterministic, concurrency-safe test doubles for the post-scan tail (TASK-2.1).

Phase 2 parallelizes the per-account post-scan tail. To prove byte-identical
behavior between the sequential (width=1) and parallel (width>=2) paths, the
golden-equality test (TASK-2.10) re-runs the SAME inputs through the executor at
both widths and asserts the recorded placement stream is identical.

That requires a recording double that is:
  * deterministic — every method returns a pure function of its inputs, so two
    runs over the same inputs produce the same values (no clocks, no RNG, no real
    network). order_id = f(account_id, symbol); mark price/wallet are fixed.
  * concurrency-safe — placements may be recorded from multiple per-account tasks
    interleaved on the event loop. Recording must never lose or corrupt an entry,
    and per-account ordering must be preserved exactly as the awaits resolved.
  * configurable — per-call latency (to force interleaving), a fill model, and a
    rate-aware 10006 injector (emits BybitAPIError-like throttle when the observed
    call rate for an account/IP exceeds a threshold) so the harness can exercise
    the rate-gate and failure-isolation paths.

This module is TEST-ONLY (no production import). It models the
``accounts_service`` + ``close_positions_service`` surface the AutoTradeExecutor
actually calls (see auto_trade_service.py) — NOT the low-level BybitClient — because
that is the seam the executor places trades through.

Surface recorded / stubbed (from a grep of self._accounts.* / self._close_svc.*):
  accounts: get_wallet, get_positions, get_account, get_mark_price, place_trade
  close_svc: list_rules, create_rule, delete_rule, delete_all_rules,
             close_all_positions, update_rule
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


def deterministic_order_id(account_id: str, symbol: str, seq: int) -> str:
    """Pure, collision-free order id. Includes ``seq`` so a per-account repeat of
    the same symbol (allowed across recheck cycles) still yields distinct ids,
    while staying a pure function of its inputs (no clock/RNG)."""
    return f"ord-{account_id}-{symbol}-{seq}"


@dataclass
class Placement:
    """One recorded ``place_trade`` call — the golden-equality unit.

    Captures the full kwargs tuple the executor passes at the placement seam so
    the golden test can assert exact equality of *what* was sent, in *what order*,
    per account. Excludes nothing the executor controls; the synthesized
    ``order_id`` is deterministic so it is safe to include.
    """

    account_id: str
    symbol: str
    signal_direction: str
    trade_direction: str
    leverage: Any
    take_profit_pct: Any
    stop_loss_pct: Any
    capital_pct: Any
    base_capital: Any
    source: Optional[str]
    strategy_kind: Optional[str]
    strategy_cohort: Optional[str]
    order_id: str

    def golden_tuple(self) -> Tuple:
        """The exact, order-sensitive equality key for the golden test."""
        return (
            self.account_id, self.symbol, self.signal_direction, self.trade_direction,
            self.leverage, self.take_profit_pct, self.stop_loss_pct, self.capital_pct,
            self.base_capital, self.source, self.strategy_kind, self.strategy_cohort,
            self.order_id,
        )


class RateAwareThrottle:
    """Models Bybit's 10006 throttle in a RATE-aware, deterministic way.

    The real 10006 is IP/UID-GLOBAL — it fires when too many calls are in flight
    against the one connection, regardless of which account they belong to. So by
    default this counts GLOBAL in-flight placements and trips when the total exceeds
    ``max_in_flight``. That makes it a meaningful proof: at account-concurrency width W
    the process-wide semaphore caps global in-flight at W, so a threshold of W never
    trips while a threshold of W-1 MUST trip (the negative control).

    ``scope="account"`` keeps the legacy per-account counting (used only by the harness
    self-tests that exercise single-account concurrency). For the gate/benchmark proof,
    use the default ``scope="global"``.
    """

    def __init__(self, max_in_flight: int, *, scope: str = "global") -> None:
        self._max = max_in_flight
        self._scope = scope
        self._in_flight: Dict[str, int] = {}
        self._global_in_flight = 0
        self.tripped = 0

    def enter(self, account_id: str) -> bool:
        if self._scope == "global":
            self._global_in_flight += 1
            if self._global_in_flight > self._max:
                self.tripped += 1
                return False
            return True
        n = self._in_flight.get(account_id, 0) + 1
        self._in_flight[account_id] = n
        if n > self._max:
            self.tripped += 1
            return False
        return True

    def exit(self, account_id: str) -> None:
        if self._scope == "global":
            self._global_in_flight = max(0, self._global_in_flight - 1)
            return
        n = self._in_flight.get(account_id, 0) - 1
        self._in_flight[account_id] = max(0, n)


class FakeThrottleError(Exception):
    """Stand-in for a Bybit 10006 throttle raised by the harness."""


@dataclass
class RecordingAccountsService:
    """Deterministic recording double for ``accounts_service``.

    Concurrency-safety model: a single ``asyncio.Lock`` guards every mutation of
    the shared recording structures. Critically, the per-account placement order
    is captured by appending under the lock AFTER the (optional) latency sleep, so
    the recorded order reflects the true await-resolution order — which is exactly
    what the golden test compares.
    """

    wallet_balance: float = 1000.0
    positions_by_account: Dict[str, List[dict]] = field(default_factory=dict)
    mark_price: float = 100.0
    latency: float = 0.0
    throttle: Optional[RateAwareThrottle] = None
    # account_id -> ordered list of Placement (per-account ordering preserved)
    placements: Dict[str, List[Placement]] = field(default_factory=dict)
    # Flat, globally-ordered placement log (append order across all accounts)
    placement_log: List[Placement] = field(default_factory=list)
    _seq: Dict[str, int] = field(default_factory=dict)
    _db: Any = None  # executor reads getattr(self._accounts, "_db", None)
    # Observability: peak number of place_trade calls in flight ACROSS all accounts
    # at once. width=1 => 1; width>=2 with >=2 accounts => >=2 (proves fan-out).
    max_concurrency: int = 0
    _in_flight_global: int = 0

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def get_wallet(self, account_id: str) -> dict:
        return {
            "totalAvailableBalance": str(self.wallet_balance),
            "totalWalletBalance": str(self.wallet_balance),
            "totalEquity": str(self.wallet_balance),
        }

    async def get_positions(self, account_id: str) -> list:
        return list(self.positions_by_account.get(account_id, []))

    async def get_account(self, account_id: str) -> dict:
        return {"id": account_id, "label": f"label-{account_id}"}

    async def get_mark_price(self, account_id: str, symbol: str) -> float:
        return self.mark_price

    async def place_trade(self, **kwargs: Any) -> dict:
        account_id = kwargs["account_id"]
        symbol = kwargs["symbol"]
        # Throttle admission is checked at ENTRY (before the latency await) so the
        # in-flight window spans the await: while one placement is sleeping, a
        # concurrently-launched one for the same account sees an elevated count and
        # trips. enter() already decremented nothing on success; on rejection we
        # release immediately. With width=1 the count never exceeds 1.
        throttle = self.throttle
        if throttle is not None and not throttle.enter(account_id):
            throttle.exit(account_id)
            raise FakeThrottleError(f"10006 throttle for {account_id}")
        try:
            # Optional latency to force cross-account interleaving on the loop. Held
            # INSIDE the throttle window so concurrency is observable to the throttle.
            self._in_flight_global += 1
            self.max_concurrency = max(self.max_concurrency, self._in_flight_global)
            if self.latency:
                await asyncio.sleep(self.latency)
            async with self._lock:
                seq = self._seq.get(account_id, 0) + 1
                self._seq[account_id] = seq
                oid = deterministic_order_id(account_id, symbol, seq)
                placement = Placement(
                    account_id=account_id, symbol=symbol,
                    signal_direction=kwargs.get("signal_direction"),
                    trade_direction=kwargs.get("trade_direction"),
                    leverage=kwargs.get("leverage"),
                    take_profit_pct=kwargs.get("take_profit_pct"),
                    stop_loss_pct=kwargs.get("stop_loss_pct"),
                    capital_pct=kwargs.get("capital_pct"),
                    base_capital=kwargs.get("base_capital"),
                    source=kwargs.get("source"),
                    strategy_kind=kwargs.get("strategy_kind"),
                    strategy_cohort=kwargs.get("strategy_cohort"),
                    order_id=oid,
                )
                self.placements.setdefault(account_id, []).append(placement)
                self.placement_log.append(placement)
        finally:
            self._in_flight_global -= 1
            if throttle is not None:
                throttle.exit(account_id)
        return {"trade_id": oid, "side": kwargs.get("signal_direction"), "order_id": oid}

    # --- golden helpers -----------------------------------------------------
    def per_account_tuples(self) -> Dict[str, List[Tuple]]:
        return {aid: [p.golden_tuple() for p in plist] for aid, plist in self.placements.items()}


@dataclass
class RecordingCloseService:
    """Deterministic recording double for ``close_positions_service``.

    create_rule returns a deterministic id keyed on a per-account monotonic seq so
    rule ids are stable across runs. All mutations are guarded by a lock; the
    created/deleted rule streams are recorded per account for the golden test's
    rule-equality assertion (created AND deleted).
    """

    existing_rules_by_account: Dict[str, List[dict]] = field(default_factory=dict)
    created: Dict[str, List[dict]] = field(default_factory=dict)
    deleted: Dict[str, List[str]] = field(default_factory=dict)
    closed_accounts: List[str] = field(default_factory=list)
    _seq: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def list_rules(self, account_id: str) -> list:
        return list(self.existing_rules_by_account.get(account_id, []))

    async def create_rule(self, account_id: str, rule_data: dict) -> dict:
        async with self._lock:
            seq = self._seq.get(account_id, 0) + 1
            self._seq[account_id] = seq
            rid = f"rule-{account_id}-{seq}"
            rec = {"id": rid, **dict(rule_data)}
            self.created.setdefault(account_id, []).append(rec)
        return {"id": rid}

    async def delete_rule(self, account_id: str, rule_id: str) -> None:
        async with self._lock:
            self.deleted.setdefault(account_id, []).append(rule_id)

    async def delete_all_rules(self, account_id: str) -> int:
        async with self._lock:
            existing = self.existing_rules_by_account.get(account_id, [])
            self.deleted.setdefault(account_id, []).extend([r["id"] for r in existing])
            return len(existing)

    async def close_all_positions(self, account_id: str) -> None:
        async with self._lock:
            self.closed_accounts.append(account_id)

    async def update_rule(self, account_id: str, rule_id: str, data: dict) -> None:
        return None

    # --- golden helpers -----------------------------------------------------
    def created_rule_fingerprint(self) -> Dict[str, List[Tuple]]:
        """Per-account ordered (trigger_type, threshold_value) of created rules."""
        return {
            aid: [(r.get("trigger_type"), r.get("threshold_value")) for r in recs]
            for aid, recs in self.created.items()
        }


def build_executor(
    configs: List[dict],
    *,
    accounts: Optional[RecordingAccountsService] = None,
    close: Optional[RecordingCloseService] = None,
    base_capital: float = 1000.0,
    progress: Any = None,
    scan_id: Any = None,
):
    """Construct an AutoTradeExecutor wired to the recording doubles for a tail run.

    Bypasses ``init_balances`` (which needs more wallet/position mocking) by seeding
    each state's ``base_capital`` directly — the same shortcut the existing unit
    tests use. Returns ``(executor, accounts, close)`` so the caller can assert on
    the recorded placement/rule streams.
    """
    from backend.services.auto_trade_service import AutoTradeExecutor

    accounts = accounts or RecordingAccountsService()
    close = close if close is not None else RecordingCloseService()
    ex = AutoTradeExecutor(accounts, close, progress=progress, scan_id=scan_id)
    ex.init_configs(configs)
    for st in ex._state.values():
        st.base_capital = base_capital
    return ex, accounts, close

