"""Tests for backend Pydantic schemas — TASK-002."""

import pytest
from datetime import date, timedelta


def test_valid_ticker():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01")
    assert req.ticker == "SPY"


def test_ticker_with_exchange_suffix():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="CNC.TO", analysis_date="2025-06-01")
    assert req.ticker == "CNC.TO"


def test_ticker_with_number():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="7203.T", analysis_date="2025-06-01")
    assert req.ticker == "7203.T"


def test_invalid_ticker_special_chars():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="SP Y!", analysis_date="2025-06-01")


def test_ticker_too_long():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="A" * 21, analysis_date="2025-06-01")


def test_empty_ticker():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="", analysis_date="2025-06-01")


def test_valid_date():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01")
    assert req.analysis_date == "2025-06-01"


def test_future_date_rejected():
    from backend.schemas import AnalysisRequest

    future = (date.today() + timedelta(days=30)).isoformat()
    with pytest.raises(Exception):
        AnalysisRequest(ticker="SPY", analysis_date=future)


def test_invalid_date_format():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="SPY", analysis_date="06-01-2025")


def test_valid_provider():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", provider="anthropic")
    assert req.provider == "anthropic"


def test_invalid_provider():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", provider="invalid_provider")


def test_valid_model_id():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(
        ticker="SPY", analysis_date="2025-06-01", deep_think_llm="claude-opus-4.6"
    )
    assert req.deep_think_llm == "claude-opus-4.6"


def test_model_id_with_slash():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(
        ticker="SPY", analysis_date="2025-06-01", deep_think_llm="google/gemma-4-26b"
    )
    assert req.deep_think_llm == "google/gemma-4-26b"


def test_invalid_model_id():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="SPY", analysis_date="2025-06-01", deep_think_llm="model with spaces!"
        )


def test_model_id_too_long():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="SPY", analysis_date="2025-06-01", deep_think_llm="a" * 101
        )


def test_valid_output_language_preset():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", output_language="Japanese")
    assert req.output_language == "Japanese"


def test_valid_output_language_custom():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", output_language="Turkish")
    assert req.output_language == "Turkish"


def test_invalid_output_language():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", output_language="123bad")


def test_output_language_too_long():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", output_language="A" * 31)


def test_valid_data_vendors():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(
        ticker="SPY",
        analysis_date="2025-06-01",
        data_vendors={"core_stock_apis": "alpha_vantage"},
    )
    assert req.data_vendors["core_stock_apis"] == "alpha_vantage"


def test_invalid_data_vendor_category():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="SPY",
            analysis_date="2025-06-01",
            data_vendors={"bad_category": "yfinance"},
        )


def test_invalid_data_vendor_value():
    from backend.schemas import AnalysisRequest

    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="SPY",
            analysis_date="2025-06-01",
            data_vendors={"core_stock_apis": "bad_vendor"},
        )


def test_analysis_request_defaults():
    from backend.schemas import AnalysisRequest

    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01")
    assert req.provider is None
    assert req.deep_think_llm is None
    assert req.quick_think_llm is None
    assert req.analysts is None
    assert req.output_language is None
    assert req.data_vendors is None


def test_error_response_schema():
    from backend.schemas import ErrorResponse

    err = ErrorResponse(detail="Not found", code="NOT_FOUND")
    assert err.detail == "Not found"
    assert err.code == "NOT_FOUND"


def test_error_response_no_code():
    from backend.schemas import ErrorResponse

    err = ErrorResponse(detail="Something went wrong")
    assert err.code is None


def test_config_response_structure():
    from backend.schemas import ConfigResponse

    resp = ConfigResponse(
        defaults={"llm_provider": "openai"},
        overrides={},
        resolved={"llm_provider": "openai"},
    )
    assert resp.resolved["llm_provider"] == "openai"


def test_memory_entry():
    from backend.schemas import MemoryEntry

    entry = MemoryEntry(
        ticker="SPY",
        date="2025-06-01",
        decision="BUY",
        confidence="High",
        status="resolved",
    )
    assert entry.ticker == "SPY"


# ---------------------------------------------------------------------------
# Crypto schema tests (TASK-014)
# ---------------------------------------------------------------------------

def test_valid_crypto_request():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(
        ticker="BTCUSDT", analysis_date="2025-01-15",
        asset_type="crypto", interval="60",
    )
    assert req.asset_type == "crypto"
    assert req.interval == "60"


def test_crypto_invalid_symbol():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="btc usdt!", analysis_date="2025-01-15",
            asset_type="crypto", interval="60",
        )


def test_crypto_stock_analysts_rejected():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="BTCUSDT", analysis_date="2025-01-15",
            asset_type="crypto", interval="60",
            analysts=["market"],
        )


def test_crypto_valid_analysts():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(
        ticker="BTCUSDT", analysis_date="2025-01-15",
        asset_type="crypto", interval="60",
        analysts=["crypto_technical", "crypto_derivatives"],
    )
    assert len(req.analysts) == 2


def test_crypto_invalid_interval():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="BTCUSDT", analysis_date="2025-01-15",
            asset_type="crypto", interval="999",
        )


def test_crypto_requires_interval():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="BTCUSDT", analysis_date="2025-01-15",
            asset_type="crypto",
        )


def test_stock_request_unchanged():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01")
    assert req.asset_type == "stock"


def test_stock_analysts_valid():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(
        ticker="SPY", analysis_date="2025-06-01",
        analysts=["market", "news"],
    )
    assert len(req.analysts) == 2


def test_output_language_none():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", output_language=None)
    assert req.output_language is None


def test_data_vendors_none():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", data_vendors=None)
    assert req.data_vendors is None


def test_crypto_ticker_invalid_format():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception, match="Crypto ticker"):
        AnalysisRequest(ticker="CNC.TO", analysis_date="2025-06-01", asset_type="crypto", interval="D")


def test_invalid_stock_analyst():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception, match="Invalid stock analyst"):
        AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", analysts=["crypto_technical"])


def test_invalid_asset_type():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception, match="Invalid asset_type"):
        AnalysisRequest(ticker="SPY", analysis_date="2025-06-01", asset_type="forex")


def test_scan_request_invalid_date():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid date"):
        ScanRequest(analysis_date="not-a-date")


def test_scan_request_future_date():
    from backend.schemas import ScanRequest
    future = (date.today() + timedelta(days=30)).isoformat()
    with pytest.raises(Exception, match="future"):
        ScanRequest(analysis_date=future)
