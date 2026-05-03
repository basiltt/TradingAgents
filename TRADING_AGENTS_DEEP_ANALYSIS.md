# TradingAgents: Complete Architecture Analysis

## 1. DATA TOOLS & VENDOR SYSTEM

### Overview
The TradingAgents implements a **pluggable, vendor-agnostic data fetching layer** with automatic fallback. All data tools route through a central dispatcher that can use yfinance or Alpha Vantage.

### File Structure
```
tradingagents/dataflows/
├── interface.py                    # Vendor routing dispatcher  
├── y_finance.py                    # yfinance implementations
├── alpha_vantage*.py              # Alpha Vantage (5 files)
├── config.py                       # Config getter/setter
└── stockstats_utils.py            # Technical indicators

tradingagents/agents/utils/
├── core_stock_tools.py            # get_stock_data
├── technical_indicators_tools.py  # get_indicators
├── fundamental_data_tools.py      # Finance statements
└── news_data_tools.py             # News & insider data
```

### Vendor Routing

`route_to_vendor(method, *args, **kwargs)` in `interface.py`:

**VENDOR_METHODS mapping**:
```python
{
    "get_stock_data": {"alpha_vantage": ..., "yfinance": ...},
    "get_indicators": {"alpha_vantage": ..., "yfinance": ...},
    "get_fundamentals": {...},
    "get_balance_sheet": {...},
    "get_cashflow": {...},
    "get_income_statement": {...},
    "get_news": {...},
    "get_global_news": {...},
    "get_insider_transactions": {...},
}
```

**Fallback chain**: Primary vendor → Secondary vendors → Failure
- Only `AlphaVantageRateLimitError` triggers fallback
- Other exceptions fail immediately

### Tools (LangChain @tool decorated)

**1. get_stock_data(symbol, start_date, end_date) → CSV**
- yfinance: `get_YFin_data_online()` → `yf.Ticker.history()`
- Alpha Vantage: `get_stock()` → API TIME_SERIES_DAILY_ADJUSTED

**2. get_indicators(symbol, indicator, curr_date, look_back_days=30) → text**
- Handles comma-separated indicators (splits & processes each)
- yfinance: `get_stock_stats_indicators_window()` → stockstats library
- Supported: SMA(50,200,10), MACD, RSI, Bollinger, ATR, VWMA, MFI

**3. Fundamentals (4 tools)**
- `get_fundamentals(ticker)` → Company metrics (PE, dividend, etc)
- `get_balance_sheet(ticker, freq="quarterly")`
- `get_cashflow(ticker, freq="quarterly")`
- `get_income_statement(ticker, freq="quarterly")`

**4. News (3 tools)**
- `get_news(ticker, start_date, end_date)` → Company news
- `get_global_news(curr_date, look_back_days=7, limit=5)` → Macro news
- `get_insider_transactions(ticker)` → Insider trading

