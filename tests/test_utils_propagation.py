"""Tests for tradingagents.dataflows.utils and tradingagents.graph.propagation — Phase 1 unit tests."""

import pytest
from datetime import datetime


class TestSafeTickerComponent:
    def _call(self, *args, **kwargs):
        from tradingagents.dataflows.utils import safe_ticker_component
        return safe_ticker_component(*args, **kwargs)

    def test_valid_ticker(self):
        assert self._call("AAPL") == "AAPL"

    def test_valid_with_dots(self):
        assert self._call("CNC.TO") == "CNC.TO"

    def test_valid_index(self):
        assert self._call("^GSPC") == "^GSPC"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            self._call("")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            self._call(None)

    def test_too_long_raises(self):
        with pytest.raises(ValueError):
            self._call("A" * 33)

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError):
            self._call("../../../etc")

    def test_dots_only_raises(self):
        with pytest.raises(ValueError):
            self._call("..")

    def test_single_dot_raises(self):
        with pytest.raises(ValueError):
            self._call(".")

    def test_special_chars_raises(self):
        with pytest.raises(ValueError):
            self._call("AAPL;DROP")


class TestGetNextWeekday:
    def test_weekday_returns_same(self):
        from tradingagents.dataflows.utils import get_next_weekday
        wed = datetime(2025, 1, 8)  # Wednesday
        assert get_next_weekday(wed) == wed

    def test_saturday_returns_monday(self):
        from tradingagents.dataflows.utils import get_next_weekday
        sat = datetime(2025, 1, 11)  # Saturday
        result = get_next_weekday(sat)
        assert result.weekday() == 0  # Monday

    def test_sunday_returns_monday(self):
        from tradingagents.dataflows.utils import get_next_weekday
        sun = datetime(2025, 1, 12)  # Sunday
        result = get_next_weekday(sun)
        assert result.weekday() == 0

    def test_string_date(self):
        from tradingagents.dataflows.utils import get_next_weekday
        result = get_next_weekday("2025-01-11")  # Saturday
        assert result.weekday() == 0


class TestSaveOutput:
    def test_no_path_does_nothing(self):
        import pandas as pd
        from tradingagents.dataflows.utils import save_output
        save_output(pd.DataFrame(), "tag", None)

    def test_with_path_saves(self, tmp_path):
        import pandas as pd
        from tradingagents.dataflows.utils import save_output
        p = str(tmp_path / "out.csv")
        df = pd.DataFrame({"a": [1, 2]})
        save_output(df, "tag", p)
        assert (tmp_path / "out.csv").exists()


class TestGetCurrentDate:
    def test_format(self):
        from tradingagents.dataflows.utils import get_current_date
        import re
        result = get_current_date()
        assert re.match(r"\d{4}-\d{2}-\d{2}", result)


class TestDecorateAllMethods:
    def test_decorates(self):
        from tradingagents.dataflows.utils import decorate_all_methods

        calls = []

        def my_decorator(fn):
            def wrapper(*a, **kw):
                calls.append(fn.__name__)
                return fn(*a, **kw)
            return wrapper

        @decorate_all_methods(my_decorator)
        class Foo:
            def bar(self):
                return 1

        f = Foo()
        assert f.bar() == 1
        assert "bar" in calls


class TestPropagator:
    def test_create_initial_state(self):
        from tradingagents.graph.propagation import Propagator
        p = Propagator()
        state = p.create_initial_state("AAPL", "2025-01-10")
        assert state["company_of_interest"] == "AAPL"
        assert state["trade_date"] == "2025-01-10"
        assert state["asset_type"] == "stock"
        assert state["error"] is None

    def test_create_initial_state_crypto(self):
        from tradingagents.graph.propagation import Propagator
        p = Propagator()
        state = p.create_initial_state("BTCUSDT", "2025-01-10", asset_type="crypto")
        assert state["asset_type"] == "crypto"
        assert state["crypto_interval"] is None

    def test_create_initial_state_crypto_interval(self):
        from tradingagents.graph.propagation import Propagator
        p = Propagator()
        state = p.create_initial_state("BTCUSDT", "2025-01-10", asset_type="crypto", crypto_interval="15")
        assert state["crypto_interval"] == "15"

    def test_create_initial_state_stock_no_interval(self):
        from tradingagents.graph.propagation import Propagator
        p = Propagator()
        state = p.create_initial_state("AAPL", "2025-01-10")
        assert state["crypto_interval"] is None

    def test_get_graph_args_no_callbacks(self):
        from tradingagents.graph.propagation import Propagator
        p = Propagator(max_recur_limit=50)
        args = p.get_graph_args()
        assert args["config"]["recursion_limit"] == 50
        assert "callbacks" not in args["config"]

    def test_get_graph_args_with_callbacks(self):
        from tradingagents.graph.propagation import Propagator
        p = Propagator()
        cb = [lambda: None]
        args = p.get_graph_args(callbacks=cb)
        assert args["config"]["callbacks"] is cb
