"""Tests for the auto_trade_config_count serializer field (TASK-1.4 / CR-6)."""
import json

from backend.services.scanner_service import ScannerService


def test_config_count_from_dict_config():
    assert ScannerService._auto_trade_config_count(
        {"auto_trade_configs": [{"account_id": "a"}, {"account_id": "b"}]}
    ) == 2


def test_config_count_zero_when_absent():
    assert ScannerService._auto_trade_config_count({}) == 0
    assert ScannerService._auto_trade_config_count({"auto_trade_configs": None}) == 0


def test_config_count_from_json_string_config():
    cfg = json.dumps({"auto_trade_configs": [{"account_id": "a"}]})
    assert ScannerService._auto_trade_config_count(cfg) == 1


def test_config_count_bad_json_is_zero():
    assert ScannerService._auto_trade_config_count("{not json") == 0


def test_config_count_non_dict_is_zero():
    assert ScannerService._auto_trade_config_count(None) == 0
    assert ScannerService._auto_trade_config_count(42) == 0
