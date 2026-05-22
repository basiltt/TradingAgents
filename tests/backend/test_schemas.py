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


# ---------------------------------------------------------------------------
# llm_api_key tests
# ---------------------------------------------------------------------------

def test_llm_api_key_accepted():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(
        ticker="SPY", analysis_date="2025-06-01",
        provider="anthropic", llm_api_key="sk-test-key-123",
    )
    assert req.llm_api_key == "sk-test-key-123"


def test_llm_api_key_none_by_default():
    from backend.schemas import AnalysisRequest
    req = AnalysisRequest(ticker="SPY", analysis_date="2025-06-01")
    assert req.llm_api_key is None


def test_llm_api_key_too_long():
    from backend.schemas import AnalysisRequest
    with pytest.raises(Exception):
        AnalysisRequest(
            ticker="SPY", analysis_date="2025-06-01",
            llm_api_key="k" * 201,
        )


def test_scan_request_llm_api_key():
    from backend.schemas import ScanRequest
    req = ScanRequest(
        analysis_date="2025-06-01",
        llm_api_key="sk-scan-key",
    )
    assert req.llm_api_key == "sk-scan-key"


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


# ---------------------------------------------------------------------------
# ScanRequest validator coverage (lines 281-340)
# ---------------------------------------------------------------------------

def test_scan_request_invalid_provider():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid provider"):
        ScanRequest(analysis_date="2025-01-01", provider="invalid_provider")


def test_scan_request_valid_provider():
    from backend.schemas import ScanRequest
    req = ScanRequest(analysis_date="2025-01-01", provider="openai")
    assert req.provider == "openai"


def test_scan_request_invalid_deep_think_llm():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid model ID"):
        ScanRequest(analysis_date="2025-01-01", deep_think_llm="bad model!!!")


def test_scan_request_invalid_quick_think_llm():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid model ID"):
        ScanRequest(analysis_date="2025-01-01", quick_think_llm="bad model!!!")


def test_scan_request_valid_model_ids():
    from backend.schemas import ScanRequest
    req = ScanRequest(
        analysis_date="2025-01-01",
        deep_think_llm="gpt-4o",
        quick_think_llm="claude-3-haiku",
    )
    assert req.deep_think_llm == "gpt-4o"


def test_scan_request_output_language_invalid():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception):
        ScanRequest(analysis_date="2025-01-01", output_language="123invalid")


def test_scan_request_output_language_too_long():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="30 characters"):
        ScanRequest(analysis_date="2025-01-01", output_language="A" * 31)


def test_scan_request_output_language_preset():
    from backend.schemas import ScanRequest
    req = ScanRequest(analysis_date="2025-01-01", output_language="Japanese")
    assert req.output_language == "Japanese"


def test_scan_request_invalid_data_vendor_category():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid vendor category"):
        ScanRequest(analysis_date="2025-01-01", data_vendors={"bad_category": "yfinance"})


def test_scan_request_invalid_data_vendor_value():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid vendor value"):
        ScanRequest(analysis_date="2025-01-01", data_vendors={"core_stock_apis": "bad_vendor"})


def test_scan_request_valid_data_vendors():
    from backend.schemas import ScanRequest
    req = ScanRequest(
        analysis_date="2025-01-01",
        data_vendors={"core_stock_apis": "yfinance"},
    )
    assert req.data_vendors == {"core_stock_apis": "yfinance"}


def test_scan_request_invalid_analyst_crypto():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid analyst"):
        ScanRequest(analysis_date="2025-01-01", asset_type="crypto", analysts=["market"])


def test_scan_request_invalid_analyst_stock():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid analyst"):
        ScanRequest(analysis_date="2025-01-01", asset_type="stock", analysts=["crypto_technical"])


def test_scan_request_invalid_asset_type():
    from backend.schemas import ScanRequest
    with pytest.raises(Exception, match="Invalid asset_type"):
        ScanRequest(analysis_date="2025-01-01", asset_type="forex")


def test_scan_request_output_language_none_allowed():
    from backend.schemas import ScanRequest
    req = ScanRequest(analysis_date="2025-01-01")
    assert req.output_language is None


def test_scan_request_output_language_custom_valid():
    from backend.schemas import ScanRequest
    req = ScanRequest(analysis_date="2025-01-01", output_language="Swahili")
    assert req.output_language == "Swahili"


def test_scan_request_data_vendors_none_allowed():
    from backend.schemas import ScanRequest
    req = ScanRequest(analysis_date="2025-01-01")
    assert req.data_vendors is None


def test_create_close_rule_request_valid():
    from backend.schemas import CreateCloseRuleRequest
    for trigger in ("BALANCE_BELOW", "EQUITY_DROP_PCT", "BREAKEVEN_TIMEOUT", "MAX_DURATION"):
        req = CreateCloseRuleRequest(
            trigger_type=trigger,
            threshold_value="5.5",
            reference_value="100.0" if "PCT" in trigger or "BELOW" in trigger else "2026-05-22T09:21:46Z",
        )
        assert req.trigger_type == trigger
        assert req.threshold_value == "5.5"


def test_create_close_rule_request_invalid_trigger():
    from backend.schemas import CreateCloseRuleRequest
    with pytest.raises(ValueError, match="Invalid trigger_type"):
        CreateCloseRuleRequest(
            trigger_type="INVALID_TRIGGER",
            threshold_value="5.5",
        )


def test_create_close_rule_request_invalid_threshold():
    from backend.schemas import CreateCloseRuleRequest
    with pytest.raises(ValueError, match="must be positive"):
        CreateCloseRuleRequest(
            trigger_type="BREAKEVEN_TIMEOUT",
            threshold_value="-1",
        )
    with pytest.raises(ValueError, match="valid number"):
        CreateCloseRuleRequest(
            trigger_type="BREAKEVEN_TIMEOUT",
            threshold_value="not-a-number",
        )


def test_update_close_rule_request_valid():
    from backend.schemas import UpdateCloseRuleRequest
    req = UpdateCloseRuleRequest(trigger_type="BREAKEVEN_TIMEOUT")
    assert req.trigger_type == "BREAKEVEN_TIMEOUT"


