"""Apply profitability config changes to the scheduled scan after code deployment.

Run this after deploying the code changes that add the new AutoTradeConfig fields.
Usage: python scripts/apply_profitability_config.py
"""
import json
import sys
import urllib.request

BASE_URL = "https://157-173-124-192.sslip.io/api/v1"
SCAN_ID = "d9c5f14f-a71f-4907-9449-dab3b75a52cb"
PREETHY_ACCOUNT = "a59250e3-9696-4399-9fe2-aeab8a0a8db6"

# New fields to add to ALL auto_trade_configs
NEW_FIELDS = {
    "min_score": 7,
    "max_trades": 3,
    "capital_pct": 18,
    "smart_drawdown_close": True,
    "trailing_profit_pct": 2.0,
    "max_signal_age_minutes": 90,
    "max_same_direction": 3,
    "symbol_blacklist": ["BIGTIMEUSDT", "PLAYSOUTUSDT", "SOXLUSDT", "SPXUSDT", "POWERUSDT"],
    "target_goal_value": 8,
    # New fields from 2026-06-04 implementation session
    "max_price_drift_pct": 3.0,
    "max_same_sector": 2,
    "adaptive_blacklist_enabled": True,
    "adaptive_blacklist_min_trades": 5,
    "adaptive_blacklist_max_win_rate": 30.0,
    "adaptive_blacklist_lookback_hours": 48,
}


def main():
    # Fetch current config
    req = urllib.request.Request(f"{BASE_URL}/scheduled-scans/{SCAN_ID}")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    configs = data["scan_config"]["auto_trade_configs"]
    print(f"Found {len(configs)} auto_trade_configs")

    for cfg in configs:
        cfg.update(NEW_FIELDS)

    data["scan_config"]["auto_trade_configs"] = configs

    # Apply via PATCH
    payload = json.dumps({"scan_config": data["scan_config"]}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/scheduled-scans/{SCAN_ID}",
        data=payload,
        method="PATCH",
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    if "id" in result:
        sample = result["scan_config"]["auto_trade_configs"][0]
        print(f"SUCCESS! Updated {len(result['scan_config']['auto_trade_configs'])} configs.")
        print(f"  min_score={sample.get('min_score')}")
        print(f"  smart_drawdown_close={sample.get('smart_drawdown_close')}")
        print(f"  trailing_profit_pct={sample.get('trailing_profit_pct')}")
        print(f"  max_signal_age_minutes={sample.get('max_signal_age_minutes')}")
        print(f"  max_price_drift_pct={sample.get('max_price_drift_pct')}")
        print(f"  max_same_sector={sample.get('max_same_sector')}")
        print(f"  adaptive_blacklist_enabled={sample.get('adaptive_blacklist_enabled')}")
    else:
        print(f"FAILED: {json.dumps(result)[:500]}")
        sys.exit(1)

    # Update Preethy AI Manager config
    print(f"\nUpdating Preethy AI Manager config (min_profit_to_close_ratio=0.3)...")
    payload = json.dumps({"min_profit_to_close_ratio": 0.3}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/ai-manager/{PREETHY_ACCOUNT}/config",
        data=payload,
        method="PATCH",
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        print(f"  AI Manager config updated: min_profit_to_close_ratio={result.get('min_profit_to_close_ratio')}")
    except Exception as e:
        print(f"  AI Manager config update failed: {e}")


if __name__ == "__main__":
    main()
