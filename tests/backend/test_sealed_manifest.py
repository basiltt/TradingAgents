"""Tests for the sealed-day manifest + completion frontier (Phase P1).

Pure-logic tests (no DB, no network) — run fully headless (N3). They pin the
immutability contract that kills RC-3 (re-download every rerun): a closed day is
fetched once, then sealed forever, regardless of how few candles it has.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.services.sealed_manifest import (
    DayClass,
    classify_days,
    completion_frontier,
    contiguous_runs,
    day_is_closed,
    days_needing_fetch,
    days_to_seal,
    interval_seconds,
    ratchet_frontier,
)

UTC = timezone.utc


class TestCompletionFrontier:
    def test_floors_to_bar_boundary_5m(self):
        now = datetime(2026, 6, 10, 12, 7, 30, tzinfo=UTC)  # 12:07:30
        f = completion_frontier(now, "5m")
        assert f == datetime(2026, 6, 10, 12, 5, 0, tzinfo=UTC)  # floored to 12:05

    def test_floors_to_bar_boundary_1h(self):
        now = datetime(2026, 6, 10, 12, 59, tzinfo=UTC)
        f = completion_frontier(now, "1h")
        assert f == datetime(2026, 6, 10, 12, 0, tzinfo=UTC)

    def test_naive_now_treated_as_utc(self):
        f = completion_frontier(datetime(2026, 6, 10, 0, 3), "5m")
        assert f == datetime(2026, 6, 10, 0, 0, tzinfo=UTC)

    def test_interval_seconds_defaults_to_5m(self):
        assert interval_seconds("nonsense") == 300
        assert interval_seconds("1h") == 3600


class TestDayClosed:
    def test_yesterday_is_closed(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        frontier = completion_frontier(now, "5m")
        assert day_is_closed(date(2026, 6, 9), frontier) is True

    def test_today_is_not_closed(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        frontier = completion_frontier(now, "5m")
        assert day_is_closed(date(2026, 6, 10), frontier) is False

    def test_day_closes_exactly_at_midnight_frontier(self):
        # frontier exactly at 2026-06-10 00:00 → 06-09 is closed, 06-10 is not.
        frontier = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
        assert day_is_closed(date(2026, 6, 9), frontier) is True
        assert day_is_closed(date(2026, 6, 10), frontier) is False


class TestRefetchDecision:
    """The core contract: a SEALED day never refetches — the RC-3 fix."""

    def test_sealed_day_never_fetches_even_if_short(self):
        # A sealed day with only 1 cached candle (vs 288 expected) must NOT refetch.
        c = DayClass(date=date(2026, 6, 1), sealed=True, closed=True, cached_count=1)
        assert c.needs_fetch is False

    def test_closed_unsealed_never_cached_fetches_once(self):
        c = DayClass(date=date(2026, 6, 1), sealed=False, closed=True, cached_count=0)
        assert c.needs_fetch is True

    def test_closed_unsealed_already_cached_fetches_to_lazy_seal(self):
        # Pre-manifest rows: closed, has candles, but not yet sealed → fetch once to seal.
        c = DayClass(date=date(2026, 6, 1), sealed=False, closed=True, cached_count=288)
        assert c.needs_fetch is True

    def test_forming_day_always_eligible(self):
        c = DayClass(date=date(2026, 6, 10), sealed=False, closed=False, cached_count=100)
        assert c.needs_fetch is True


class TestClassifyAndSeal:
    def test_sealed_short_day_not_in_fetch_list(self):
        """The exact RC-3 scenario: a closed day with 144/288 candles, already
        sealed, must NOT appear in days_needing_fetch on a rerun."""
        now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        frontier = completion_frontier(now, "5m")
        expected = [date(2026, 6, 1)]
        classes = classify_days(
            expected_dates=expected,
            sealed_dates={date(2026, 6, 1)},      # already sealed
            cached_counts={date(2026, 6, 1): 144},  # legitimately short
            frontier=frontier,
        )
        assert days_needing_fetch(classes) == []  # the fix: zero refetch

    def test_unsealed_short_day_fetches_then_becomes_sealable(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        frontier = completion_frontier(now, "5m")
        expected = [date(2026, 6, 1)]
        classes = classify_days(
            expected_dates=expected,
            sealed_dates=set(),                    # NOT sealed yet
            cached_counts={date(2026, 6, 1): 144},
            frontier=frontier,
        )
        assert days_needing_fetch(classes) == [date(2026, 6, 1)]
        # after fetch+store, this closed day is sealable (so next run won't refetch)
        assert days_to_seal(classes) == [date(2026, 6, 1)]

    def test_forming_day_not_sealed(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        frontier = completion_frontier(now, "5m")
        classes = classify_days(
            expected_dates=[date(2026, 6, 10)],    # today (forming)
            sealed_dates=set(),
            cached_counts={date(2026, 6, 10): 144},
            frontier=frontier,
        )
        assert days_to_seal(classes) == []  # forming day must never seal


class TestContiguousRuns:
    def test_single_run(self):
        days = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]
        assert contiguous_runs(days) == [(date(2026, 6, 1), date(2026, 6, 3))]

    def test_split_runs_skip_cached_interior(self):
        # Gap at 06-02 (cached) → two runs, NOT one min→max bracket that refetches 06-02.
        days = [date(2026, 6, 1), date(2026, 6, 3), date(2026, 6, 4)]
        assert contiguous_runs(days) == [
            (date(2026, 6, 1), date(2026, 6, 1)),
            (date(2026, 6, 3), date(2026, 6, 4)),
        ]

    def test_empty(self):
        assert contiguous_runs([]) == []


class TestRatchet:
    def test_frontier_never_regresses_on_backward_clock(self):
        prev = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        computed = datetime(2026, 6, 10, 11, 0, tzinfo=UTC)  # clock stepped back 1h
        assert ratchet_frontier(prev, computed) == prev  # held — sealed days stay sealed

    def test_frontier_advances_normally(self):
        prev = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        computed = datetime(2026, 6, 10, 13, 0, tzinfo=UTC)
        assert ratchet_frontier(prev, computed) == computed

    def test_first_frontier_no_prev(self):
        computed = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        assert ratchet_frontier(None, computed) == computed
