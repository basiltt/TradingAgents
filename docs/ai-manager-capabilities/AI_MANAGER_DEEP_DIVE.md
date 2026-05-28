# TradingAgents AI Manager — Complete Deep Dive

## Executive Summary

The AI Manager is a **production-grade autonomous position management system** that runs one finite state machine (FSM) instance per trading account. It continuously monitors open crypto futures positions on Bybit, evaluates market conditions in real-time using Claude AI, and executes position management decisions with multi-layered safety controls.

**It is NOT an entry-signal generator.** It manages existing positions — deciding when to hold, partially close, or fully close — with crash protection, profit preservation, and risk management as primary objectives.

---

## Architecture Overview

### Per-Account Finite State Machine

```
WebSocket Events → FSM (SLEEPING → MONITORING → ANALYZING → EXECUTING → loop)
                          ↓
                   8-Node LangGraph Decision Graph
                          ↓
                   Claude AI (structured JSON output)
                          ↓
                   Risk Gates → Execute or Reject
```

**FSM States:**

| State | Description | Transition |
|-------|-------------|------------|
| SLEEPING | Idle, no open positions (60s heartbeat) | → MONITORING (WebSocket position detected) |
| MONITORING | Evaluating every N seconds | → ANALYZING (timer expired) |
| ANALYZING | Running decision graph | → EXECUTING (action determined) |
| EXECUTING | Placing order on exchange | → MONITORING (loop) |
| PAUSED | Manual user pause | → MONITORING (resume) |
| ERROR | Crash or kill switch | → Requires manual reset |

**FSM Task Specifics:**
- SLEEPING heartbeat interval: **60 seconds**
- Per-symbol cooldown after action: **15.0 seconds** (prevents rapid re-evaluation of same symbol)
- Max reasoning characters stored: **2000** (truncated if longer)
- Token budget per account per day: **100,000 tokens**
- Min position age before closing (default): **300 seconds**

### Key Source Files

| File | Purpose | Size |
|------|---------|------|
| `backend/services/ai_manager_task.py` | Per-account FSM engine | 2100+ lines |
| `backend/services/ai_manager_graph.py` | LangGraph decision graph (8 nodes) | 600+ lines |
| `backend/ai_manager_schemas.py` | Configuration and type definitions | — |
| `backend/services/ai_manager_market_data.py` | Real-time Bybit ticker/kline feeds | — |
| `backend/services/ai_manager_mtf.py` | Multi-timeframe analysis | — |
| `backend/services/ai_manager_correlation.py` | Correlation analysis and clustering | — |
| `backend/services/ai_manager_orderbook.py` | Order book monitoring and sweep detection | — |
| `backend/services/ai_manager_regime.py` | Market regime classification | — |
| `backend/services/ai_manager_prompts.py` | System and context prompts | 400+ lines |
| `backend/services/ai_manager_llm_provider.py` | Claude API integration | — |
| `backend/services/ai_manager_llm_scheduler.py` | LLM call rate limiting | — |
| `backend/services/ai_manager_evaluator.py` | Urgency classification | — |
| `backend/services/ai_manager_circuit_breaker.py` | Fault tolerance pattern | — |
| `backend/services/ai_manager_degradation.py` | Graceful degradation tiers | — |
| `backend/services/ai_manager_memory.py` | Episodic memory and pattern learning | — |
| `backend/services/ai_manager_repository.py` | PostgreSQL persistence + decision chain | 1000+ lines |
| `backend/routers/ai_manager.py` | REST API endpoints | — |

---

## Decision Graph (8 Nodes)

The core intelligence runs as a LangGraph with 8 sequential nodes:

| # | Node | Purpose | Timeout |
|---|------|---------|---------|
| 1 | **preflight** | Validate positions exist, detect cold-start | — |
| 2 | **data_aggregation** | Extract positions, wallet, indicators | — |
| 3 | **signal_detection** | Classify urgency (EMERGENCY/FAST/STANDARD/DEEP) | — |
| 4 | **context_enrichment** | Compute regime, session, memory, patterns | 20s |
| 5 | **action_generation** | Claude API call → structured decision | 30s (2 retries) |
| 6 | **risk_validation** | Gate checks (locked, sweep, cold-start) | — |
| 7 | **output** | Finalize action | — |
| 8 | **error_fallback** | Safe default HOLD on any failure | — |

### Node Details

#### 1. Preflight Node
- Checks that the account has at least one open position
- Determines if account is in cold-start phase (< 10 total decisions)
- If no positions → immediate HOLD, skip remaining nodes

#### 2. Data Aggregation Node
- Extracts all open positions with: symbol, side, size, entry price, mark price, unrealized PnL, leverage, liquidation price, position value
- Computes **peak PnL** per symbol (highest unrealized profit seen) and **drawdown from peak** as percentage
- Retrieves wallet data: equity, available balance
- Collects latest indicators per symbol from market data service

#### 3. Signal Detection Node
- Runs the AIManagerEvaluator (detailed in Urgency Classification section)
- Classifies current state into EMERGENCY/FAST/STANDARD/DEEP
- Per-symbol cooldown tracking (15s after last urgent evaluation)

#### 4. Context Enrichment Node (20s timeout)
- **Regime**: Classify market as trending_up/down, ranging, volatile, compression
- **Session**: Identify trading session (Asia, London, New York)
- **Memory**: Retrieve last 15 episodic decisions + top 5 active patterns
- **MTF**: Multi-timeframe trend alignment (if enabled)
- **Correlation**: Portfolio heat and clusters (if enabled)
- **Orderbook**: Imbalance, depth, sweep alerts (if enabled)
- On timeout: proceeds with partial enrichment (graceful degradation)

#### 5. Action Generation Node (30s timeout, 2 retries)
- Constructs full prompt from system prompt + context prompt
- Calls Claude API with structured JSON output schema
- Parses response into action/symbol/confidence/reason
- On failure after retries: falls through to error_fallback

#### 6. Risk Validation Node
- Applies all risk gates sequentially (see Risk Gates section)
- Can REJECT action (converts to HOLD) or WARN (annotate but allow)
- Validates symbol exists in open positions
- Checks locked positions, sweep blocks, cold-start gates

#### 7. Output Node
- Finalizes the action
- Records decision to repository (with hash chain)
- Increments daily/hourly action counters atomically
- Returns action for execution by FSM

#### 8. Error Fallback Node
- Catches any unhandled exception from any prior node
- Returns safe default: `{"action": "HOLD", "confidence": 0.0, "reason": "error_fallback"}`
- Logs error for debugging
- Increments circuit breaker failure count

### Decision Output Format

```json
{
  "action": "HOLD | FULL_CLOSE | PARTIAL_CLOSE",
  "symbol": "<symbol or empty for HOLD>",
  "confidence": 0.0-1.0,
  "reason": "<explanation, max 2000 chars>"
}
```

---

## Market Analysis Capabilities

### Real-Time Data Pipeline

| Source | Frequency | Data |
|--------|-----------|------|
| Bybit Tickers | 15s | mark_price, funding_rate, price_24h_pct, high/low_24h, volume_24h, open_interest |
| Bybit Klines | 60s | 1m, 5m, 15m, 1h, 4h candles (50 per symbol) |
| Bybit Trade Tape | <1s | For sweep/stop-hunt detection |

### Computed Indicators

- **EMA-9 / EMA-21** — Trend direction and strength
- **RSI-14** — Momentum and overbought/oversold
- **ATR-14** — Volatility measurement
- **PnL Velocity (30s)** — Rate of price change for emergency detection
- **Conflicting Signals Flag** — Divergence between indicators

### Enhanced Analysis Modules

#### Multi-Timeframe Analysis (MTF)

Analyzes trend alignment across 4 timeframes with weighted scoring:

| Timeframe | Weight |
|-----------|--------|
| 5m | 10% |
| 15m | 20% |
| 1h | 35% |
| 4h | 35% |

Outputs: dominant trend, trend strength, confidence, key support/resistance levels.

#### Correlation Analysis

**Computation Method:**
- Pairwise Pearson correlation from **1h klines** (close prices)
- Only computed between symbols that have open positions
- Updated every evaluation cycle

**Portfolio Heat Calculation:**
```
For each pair of positions:
  if same_direction AND correlation > 0:
    heat_contribution = correlation × 1.0   (full risk weight)
  elif opposite_direction AND correlation < 0:
    heat_contribution = |correlation| × 0.1  (hedged — low weight)
  else:
    heat_contribution = 0

portfolio_heat = sum(heat_contributions) / max_possible_pairs
```

Range: 0.0 (fully diversified) to 1.0 (all positions maximally correlated).

**Position Clustering:**
- Group positions where `|correlation| ≥ correlation_threshold` (default 0.7)
- Each cluster reports: symbols, directions, combined PnL %
- Cluster-level urgency: if `combined_pnl_pct < -2.0%` → escalate to FAST

**Risk Classification per Pair:**

| Position Directions | Correlation | Risk Level |
|--------------------|-------------|------------|
| Same direction | Positive (> 0.7) | **HIGH** — amplified exposure |
| Same direction | Negative (< -0.7) | LOW — natural diversification |
| Opposite direction | Positive (> 0.7) | LOW — effective hedge |
| Opposite direction | Negative (< -0.7) | **HIGH** — both can lose simultaneously |

#### OrderBook Monitoring

**WebSocket Connection:**
- Public endpoint: `wss://stream.bybit.com/v5/public/linear`
- Subscriptions: `orderbook.50.{SYMBOL}`, `publicTrade.{SYMBOL}`
- Reconnect: Exponential backoff 2s → 30s max
- REST fallback on disconnect (via rate gate)

**Metrics Computed:**

| Metric | Calculation |
|--------|-------------|
| Imbalance ratio | `sum(bid_sizes[0:N]) / sum(ask_sizes[0:N])` — >1.0 = bullish pressure |
| Spread (bps) | `(best_ask - best_bid) / mid_price * 10000` |
| Depth ratio | `bid_volume_top_25 / ask_volume_top_25` |
| Bid/Ask clusters | Sizes > `baseline × 3.0` (max 5 per side) |

**Cluster Detection Algorithm:**
1. For each side (bid/ask), collect all order sizes
2. Calculate baseline: average of the lower half of sizes
3. Threshold: `baseline × 3.0`
4. Any order size > threshold = cluster (max 5 reported per side)
5. Each cluster annotated with `near_my_sl: bool` (within 0.3% of stop loss)

**Sweep/Stop-Hunt Detection Algorithm:**

```
Parameters:
  TAPE_SIZE = 1000 trades (rolling buffer)
  VOLUME_WINDOW = 30 seconds
  SL_PROXIMITY = 0.5% (0.005)
  CONFIDENCE_THRESHOLD = 0.5

Algorithm:
1. Maintain rolling tape of last 1000 trades (only recent 30s considered)
2. Calculate 30-second average volume per trade
3. Check if price approaching stop loss:
   - LONG: current_price < stop_loss × 1.005
   - SHORT: current_price > stop_loss × 0.995
4. If approaching, analyze last 10 seconds of trades:
   - burst_volume = sum of trade sizes in last 10s
   - recent_count = number of trades in last 10s
   - volume_ratio = burst_volume / (avg_volume_30s × recent_count)
5. Confidence = min(1.0, (volume_ratio - 1.0) / 2.0)
6. If confidence ≥ 0.5: SWEEP DETECTED
   - Returns: confidence, direction (buy/sell), targets_my_position flag
   - Symbol added to sweep_blocked list for N candles (default 3)
```

**Sweep Defense Response:**
- Symbol added to `sweep_blocked_symbols` set
- All non-EMERGENCY actions for that symbol are REJECTED by risk gate
- Block expires after `sweep_recovery_timeout_candles` (default 3) complete candles
- Rationale: sweeps often cause false breakdowns followed by rapid recovery

#### Market Regime Classification

Classifies current conditions using multiple indicators:

| Regime | Conditions |
|--------|-----------|
| `trending_up` | ADX > 25 AND price above EMA-21 AND EMA-9 > EMA-21 |
| `trending_down` | ADX > 25 AND price below EMA-21 AND EMA-9 < EMA-21 |
| `ranging` | ADX ≤ 25 AND not volatile AND not compression |
| `volatile` | ATR ratio ≥ 2.0 (current ATR vs 20-period average ATR) |
| `compression` | Bollinger Band Width < 0.1 AND ATR ratio < 0.7 |

Each classification includes confidence score, ADX value, and ATR ratio.

---

## LLM Decision Framework (Prompting System)

### Risk Tolerance Mapping

The system adjusts Claude's behavior based on the configured risk tolerance:

```python
_RISK_TOLERANCE_MAP = {
    "conservative": {"confidence_boost": +0.1, "loss_sensitivity": 1.5},
    "moderate":     {"confidence_boost":  0.0, "loss_sensitivity": 1.0},
    "aggressive":   {"confidence_boost": -0.05, "loss_sensitivity": 0.7},
}
```

- **confidence_boost**: Added to the effective confidence threshold (conservative = harder to act)
- **loss_sensitivity**: Multiplier on loss-related signals (conservative = more loss-averse)

### Decision Rules Given to Claude

**When to CLOSE (high confidence required):**

1. **Trend Reversal** — Price action, moving averages, or momentum indicators confirm the trend has reversed against the position direction
2. **Profit Preservation** — Position reached significant profit peak but is declining. If drawdown-from-peak **exceeds 30–50%** of peak profit, consider closing
3. **Abnormal Market Conditions** — Sudden volatility spikes, funding rate flips, volume anomalies suggesting regime change
4. **Adverse Momentum** — PnL velocity strongly negative and accelerating
5. **Risk-Reward Deterioration** — Remaining upside potential is poor relative to downside risk

**When to HOLD:**

- Trend intact and aligned with position direction
- Normal market fluctuations within expected range
- Position is young and hasn't had time to develop
- No clear reversal signals present
- Single-indicator signals without confluence

**Key Principles Enforced:**

- Only ONE position per evaluation (choose the most urgent)
- Multi-indicator confluence required — one signal alone is never sufficient
- Must consider account's recent decision history (avoid flip-flopping)
- Preserving realized profit is prioritized over hoping for more
- Position age matters — don't close positions that are too young (< min_position_age_s)

### Cold-Start Override

When `decision_count < 10`:
```
"IMPORTANT: This is a new account with limited history.
Be very conservative — only act on extremely clear signals with high confluence."
```

### Daily Profit Target Override

When `daily_profit_target_pct` is configured:
```
"If cumulative realized profit is approaching or has reached the daily target,
be more aggressive about closing remaining positions to lock in the target."
```

### Context Prompt Structure (Exact Order)

The full context fed to Claude for each decision, in this exact order:

1. **Market Context** — Regime classification, trading session (Asia/London/New York)
2. **Wallet** — Equity, available balance
3. **Daily P&L Progress** — Realized PnL vs target with percentage progress
4. **Open Positions** (per position):
   - Symbol, side, size, entry price, mark price
   - Unrealized PnL, leverage, liquidation price, position value
   - `peakPnL={peak:.2f} drawdown={drawdown_pct:.0f}%`
5. **Market Indicators** (per symbol):
   - Price, EMA-9, EMA-21 (with trend label)
   - RSI-14, ATR-14
   - 24h change %, funding rate, PnL velocity (30s)
   - Volume 24h, open interest, EMA trend strength
6. **Episodic Memory** — Last 10 recent decisions (action, symbol, outcome)
7. **Learned Patterns** — Top 5 active patterns with type and description
8. **Regime Detail** — Confidence, ADX, ATR ratio
9. **Multi-Timeframe** — Alignment, dominant trend, trend strength, key levels
10. **OrderBook** — Imbalance ratio, spread (bps), depth ratio
11. **Correlation** — Portfolio heat, max correlated exposure %
12. **Sweep Alert** (if active) — Confidence, direction, targets_my_position flag

### Prompt Security (Injection Sanitization)

All user-derived data is sanitized before injection into prompts. Stripped patterns:
- `system:`, `<|im_start|>`, `<|im_end|>`, `<|endoftext|>`
- `[INST]`, `[/INST]`, `<<SYS>>`, `<</SYS>>`
- `Human:`, `Assistant:`, Anthropic control tokens

Max field length: **200 characters** per individual field.
Token budget truncation: `max_chars = max_tokens * 4` (conservative 4-chars-per-token estimate).

---

## Urgency Classification System

The evaluator classifies every evaluation cycle into one of four urgency levels:

### EMERGENCY (Immediate, No LLM, <50ms)

**Triggers (deterministic, not AI-driven):**
- `unrealisedPnl < 0` AND `|pnl_velocity_30s| >= emergency_pnl_velocity_pct` (default 5.0%)
- Side-aware: LONG loses on negative velocity, SHORT loses on positive velocity
- OR: Portfolio equity drop ≥ `emergency_equity_drop_pct` (default 10%)

**Response:**
- FULL_CLOSE immediately — no LLM call, no cooldown check, bypasses daily limits
- 30-second cooldown after execution before next emergency can fire
- **Never skipped** — evaluated on every single WebSocket event

### FAST (Escalated, 15s Per-Symbol Cooldown)

**Triggers (any one is sufficient):**
1. **PnL Velocity**: `|pnl_velocity_30s| >= 2.0%` in 30 seconds
2. **RSI Crosses**: Previous RSI < 70 → current RSI ≥ 70, OR previous RSI > 30 → current RSI ≤ 30
3. **Funding Rate Flip**: Sign of funding rate changed since last check
4. **Volatility Spike**: 1-minute candle body > `2.0 × ATR-14`
5. **Drawdown-from-Peak**: `(peak_pnl - current_pnl) / peak_pnl > 0.40` (40%)
6. **Correlation Escalation**: Any position cluster's `combined_pnl_pct < -2.0%`

**Per-symbol cooldown**: 15.0 seconds after last urgent evaluation for that symbol.

### DEEP (Conflicting Signals — Full Analysis)

**Triggers:**
- Conflicting technical signals detected simultaneously
- Example: Bullish EMA crossover + overbought RSI (> 70) + negative PnL velocity
- Triggers full context enrichment (regime, MTF, correlation, orderbook) before decision
- Ensures the LLM gets maximum context for ambiguous situations

### STANDARD (Default — Balanced)

**Triggers:**
- No urgent signals detected
- Standard evaluation cycle (every `evaluation_interval_s` seconds, default 60)
- Fast enrichment (subset of context) before decision

### Peak PnL Tracking

- Maintained per symbol in a `peak_pnl` dictionary
- Updated whenever new position data arrives with higher unrealized profit
- Reset when position is closed
- Used for drawdown-from-peak urgency calculation and profit preservation signals

---

## Safety Mechanisms

### 1. Circuit Breaker

```
CLOSED (normal) → 3 consecutive failures → HALF_OPEN (probe with one decision)
                                               ↓ probe succeeds → CLOSED
                                               ↓ probe fails → OPEN (suspend for 3600s)
                                                                  ↓ cooldown expires → HALF_OPEN
```

**Exact Parameters:**
- Failure threshold to trip: **3 consecutive failures**
- Cooldown duration (OPEN state): **3600 seconds (1 hour)**
- Probe: Single decision allowed in HALF_OPEN — success resets, failure re-opens

Prevents cascading failures from repeated LLM errors, API timeouts, or exchange connectivity issues.

### 2. Kill Switch

- Activated via `POST /ai-manager/kill`
- Effect: FSM transitions to ERROR state immediately
- All pending evaluations cancelled
- Recovery: Manual `POST /ai-manager/kill/reset` required
- No automatic recovery — requires human confirmation
- Global kill available: `POST /ai-manager/global-kill` (all accounts)

### 3. Emergency Fast-Path

- **No LLM involvement** — purely deterministic logic
- Total latency: **<50ms** from detection to order submission
- Evaluates on **every WebSocket event** (not just evaluation intervals)
- **Bypasses** daily action limits, hourly limits, and token budget
- Triggers on:
  1. PnL velocity ≥ `emergency_pnl_velocity_pct` (5%) AND position is losing
  2. Portfolio equity drop ≥ `emergency_equity_drop_pct` (10%)
- Post-execution cooldown: **30 seconds**

### 4. Graceful Degradation Tiers

| Tier | Behavior | Trigger |
|------|----------|---------|
| 0 | Normal operation — all features active | Default state |
| 1 | Reduce confidence threshold, increase evaluation interval | Elevated error rate |
| 2 | Only FAST/EMERGENCY urgency processed, skip enrichment | Sustained errors |
| 3 | Only emergency close — no LLM decisions at all | Critical failures |
| 4 | Full shutdown — no actions taken | Unrecoverable state |

**Hysteresis for recovery**: **300 seconds (5 minutes)** of stable operation required before downgrading a tier.

### 5. Cold-Start Protection

- First **10 decisions** operate in conservative mode
- Requires confidence ≥ **0.85** (vs normal 0.7 threshold)
- Prevents early aggressive behavior before system learns account patterns
- Cold-start flag passed to Claude in system prompt for extra conservatism
- Automatically disengages after 10 successful decisions

### 6. Decision Chain Hashing (Immutable Audit)

Every decision is cryptographically chained to the previous:

```python
GENESIS_PREV_HASH = "0" * 64  # First decision in chain

decision_hash = hmac.new(
    hmac_key.encode(),
    "|".join([
        prev_hash,                    # Previous decision's hash
        account_id,
        timestamp.isoformat(),
        action_type,                  # HOLD, FULL_CLOSE, PARTIAL_CLOSE
        symbol,
        f"{confidence:.4f}",
    ]).encode(),
    hashlib.sha256,
).hexdigest()
```

**Per-decision storage (PostgreSQL):**
```sql
INSERT INTO ai_manager_decisions (
    account_id, timestamp, evaluation_type, urgency,
    state_snapshot, action_taken, reasoning, confidence,
    graph_path, strategy_version, prev_decision_hash,
    decision_hash, chain_key_version
)
```

**Outcome tracking:**
- `pnl > 0.5` → `"profitable"`
- `pnl < -0.5` → `"loss"`
- else → `"neutral"`

**Atomic operations:**
- `increment_actions_atomic()` — Only increments if under daily/hourly limits
- `increment_token_budget_atomic()` — Reserves tokens, rejects if over 100K daily cap
- Advisory locks for pattern generation (prevents duplicate patterns)

### 7. Rate Limiting

- **Daily actions**: Default 30 (range 5–100)
- **Hourly actions**: Default 10 (range 2–30)
- **Token budget**: 100K tokens/day per account
- Emergency actions **bypass all limits**
- Atomic increment ensures no race conditions under concurrent evaluations

---

## Risk Gates (Pre-Execution Validation)

Before any action is executed, it passes through these gates:

| # | Gate | Condition | Result |
|---|------|-----------|--------|
| 1 | Locked Positions | Symbol in `locked_positions` | **REJECT** |
| 2 | Symbol Existence | Symbol not in open positions | **REJECT** |
| 3 | Cold-Start | decision_count < 10 AND confidence < 0.85 | **REJECT** |
| 4 | Sweep Block | Symbol in sweep_blocked AND urgency ≠ EMERGENCY | **REJECT** |
| 5 | Correlation Heat | portfolio_heat > threshold | **WARN** (annotate, don't reject) |

---

## Memory & Learning Systems

### Episodic Memory

Stores the last **15 decisions** with full context and outcomes:

```python
{
    "action": "HOLD|FULL_CLOSE|PARTIAL_CLOSE",
    "symbol": "BTCUSDT",
    "confidence": 0.75,
    "entry_price": 98500.0,
    "close_price": 99200.0,       # if closed
    "realized_pnl": 142.50,       # if closed
    "outcome_label": "profitable|loss|neutral|unknown",
    "reasoning": "RSI overbought + EMA divergence...",
    "timestamp": "2026-05-28T14:30:00Z"
}
```

- Fed directly into Claude's context prompt (last 10 shown to LLM)
- Enables Claude to recognize repetitive patterns and avoid flip-flopping
- Outcome labels: profitable (> $0.50), loss (< -$0.50), neutral (in between)

### Pattern Learning

Up to **5 active patterns** maintained per account:

**Pattern structure:**
- Pattern type (e.g., "false_breakout", "funding_reversal", "sweep_recovery")
- Symbol (specific or "ALL")
- Confidence score (0.0–1.0)
- Evidence count (incremented on each match)
- Description text

**Lifecycle:**
1. **Creation**: After 3+ similar outcomes, system generates a pattern via advisory-locked DB operation
2. **Reinforcement**: Evidence count incremented when pattern matches new decision context
3. **Deactivation**: When confidence drops below threshold due to counter-evidence
4. **Pruning**: Only top 5 by confidence kept active; older patterns archived

**In context**: Patterns are injected into Claude's prompt so it can reference learned behavior:
```
Learned Patterns:
- [funding_reversal] ETHUSDT: When funding flips negative after extended positive, 
  short positions tend to recover within 2-4 candles (confidence: 0.82, evidence: 7)
```

### Decision Audit Trail

- Immutable HMAC-SHA256 chain (see Safety Mechanisms §6)
- Full state snapshot stored per decision (positions, indicators, wallet)
- Outcome tracked post-execution (PnL, label)
- Enables retrospective analysis: "what did the system see when it made decision X?"
- Chain integrity verifiable: recompute hashes from genesis to detect tampering

---

## LLM Scheduler (Rate Limiting & Concurrency)

The LLM scheduler manages concurrent Claude API calls across all accounts:

### Slot Architecture

```
┌─────────────────────────────────────────────┐
│  FAST Queue: 3 reserved semaphores          │
│  - High priority (equity crash, vol spike)  │
│  - Timeout: 10ms (non-blocking)             │
│  - If no slot available → REJECT (not queue)│
├─────────────────────────────────────────────┤
│  GENERAL Queue: 7 shared semaphores         │
│  - STANDARD + DEEP evaluations              │
│  - Timeout: 5 seconds (burst allowance)     │
│  - DEEP sub-limit: max 2 concurrent         │
├─────────────────────────────────────────────┤
│  Total concurrent LLM calls: 10 max         │
└─────────────────────────────────────────────┘
```

### Acquire Logic

```python
# Per-account saturation: max 2 (inflight + queued) per account
if inflight + queued >= 2:
    return False  # Reject — account already has enough pending

if urgency == "FAST":
    # Non-blocking instant acquire (10ms timeout)
    if await fast_sem.acquire(timeout=0.01):
        return True
    else:
        return False  # Drop — FAST must be instant or not at all

else:  # STANDARD or DEEP
    # DEEP sub-limit: max 2 concurrent DEEP jobs
    if urgency == "DEEP" and _deep_active >= 2:
        urgency = "STANDARD"  # Downgrade to STANDARD

    # Burst-allow acquire (5s timeout)
    if await general_sem.acquire(timeout=5.0):
        return True
    else:
        return False  # Reject — system overloaded
```

### Token Tracking

- Per-account: tracks inflight count and queued count
- Token key format: `{account_id}:{monotonic_counter}`
- Maps token key → urgency level for priority management
- Daily token budget: **100,000 tokens** per account (enforced atomically in DB)

---

## Configuration Reference

All parameters are hot-reloadable via `PATCH /ai-manager/config` — no restart required.

### Full AIManagerConfig Schema

```python
class AIManagerConfig(BaseModel):
    # ── Core Operation ──
    enabled: bool = False
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = "moderate"
    evaluation_interval_s: int = Field(default=60, ge=30, le=300)

    # ── Budget & Rate Limits ──
    max_daily_actions: int = Field(default=30, ge=5, le=100)
    max_hourly_actions: int = Field(default=10, ge=2, le=30)
    max_daily_loss_pct: float = Field(default=5.0, ge=1.0, le=25.0)
    daily_profit_target_pct: Optional[float] = Field(default=None, gt=0.0, le=100.0)

    # ── Position Rules ──
    min_position_age_s: int = Field(default=300, ge=60, le=3600)
    confidence_threshold: float = Field(default=0.7, ge=0.3, le=0.95)
    max_single_decision_loss_pct: float = Field(default=3.0, ge=0.5, le=10.0)

    # ── Safety Valves ──
    dry_run: bool = False
    grace_period_s: int = Field(default=0, ge=0, le=30)
    excluded_symbols: List[str] = Field(default_factory=list, max_length=50)
    locked_positions: List[str] = Field(default_factory=list, max_length=50)

    # ── Emergency Close (Deterministic) ──
    emergency_close_enabled: bool = True
    emergency_equity_drop_pct: float = Field(default=10.0, ge=3.0, le=50.0)
    emergency_pnl_velocity_pct: float = Field(default=5.0, ge=2.0, le=20.0)

    # ── Auto Mode ──
    auto_enabled: bool = False

    # ── Enhanced Capabilities ──
    regime_enhanced: bool = False
    mtf_enabled: bool = False
    mtf_timeframes: str = "5m,15m,1h,4h"
    orderbook_enabled: bool = False
    sweep_defense_enabled: bool = False
    sweep_recovery_timeout_candles: int = Field(default=3, ge=1, le=10)
    correlation_enabled: bool = False
    correlation_threshold: float = Field(default=0.7, ge=0.3, le=0.95)
    portfolio_heat_warning: float = Field(default=0.8, ge=0.3, le=1.0)

    # ── Strategy ──
    strategy_version: Optional[str] = None  # For A/B testing
```

**Symbol validation pattern**: `^[A-Z0-9]{1,20}$` (uppercase alphanumeric, 1–20 characters)

---

## REST API Reference

### Enable / Disable

```
POST /accounts/{account_id}/ai-manager/enable
POST /accounts/{account_id}/ai-manager/disable
```

### Configuration

```
GET  /accounts/{account_id}/ai-manager/config
PATCH /accounts/{account_id}/ai-manager/config   (hot-reload any field)
```

### Control

```
POST /accounts/{account_id}/ai-manager/pause
POST /accounts/{account_id}/ai-manager/resume
POST /accounts/{account_id}/ai-manager/kill
POST /accounts/{account_id}/ai-manager/kill/reset
```

### Position Locking

```
POST   /accounts/{account_id}/ai-manager/positions/{symbol}/lock
DELETE /accounts/{account_id}/ai-manager/positions/{symbol}/lock
```

### Status & History

```
GET /accounts/{account_id}/ai-manager/status
GET /accounts/{account_id}/ai-manager/decisions?limit=50
GET /accounts/{account_id}/ai-manager/logs?level=warning&category=lifecycle
GET /accounts/{account_id}/ai-manager/performance?period=7d
```

### Global Operations

```
POST /ai-manager/global-kill    (kill switch across ALL accounts)
```

---

## Recommended Configurations

### Conservative (New Accounts / Learning Phase)

```json
{
  "risk_tolerance": "conservative",
  "evaluation_interval_s": 120,
  "max_daily_actions": 10,
  "confidence_threshold": 0.85,
  "emergency_equity_drop_pct": 5.0,
  "dry_run": true
}
```

### Balanced (Production)

```json
{
  "risk_tolerance": "moderate",
  "evaluation_interval_s": 60,
  "max_daily_actions": 25,
  "confidence_threshold": 0.7,
  "emergency_equity_drop_pct": 10.0,
  "daily_profit_target_pct": 3.0
}
```

### Aggressive (Experienced Traders)

```json
{
  "risk_tolerance": "aggressive",
  "evaluation_interval_s": 30,
  "max_daily_actions": 50,
  "confidence_threshold": 0.6,
  "emergency_equity_drop_pct": 15.0,
  "daily_profit_target_pct": 5.0
}
```

---

## Performance Characteristics

### Latency

| Operation | Time |
|-----------|------|
| WebSocket event → state update | <10ms |
| Emergency signal detection | <50ms |
| Standard evaluation cycle | 60–90s (includes LLM call) |
| Claude LLM call | 1–5s with retries |
| Full decision → execution | 30–90s |

### Resource Usage

| Resource | Budget |
|----------|--------|
| Token budget | 100K/day per account |
| Daily decisions | 30 max (configurable) |
| Memory per account | ~1MB |
| Market data | ~50 candles × tracked symbols |

---

## Expected Outcomes

| Market Condition | Performance |
|-----------------|-------------|
| Well-trending (clear profit peaks) | Preserves 60–80% of peak profits |
| Mixed conditions | Preserves 40–50% of peak profits |
| Choppy/ranging | Frequent whipsaws, may underperform buy-and-hold |
| Flash crash | Emergency close fires, but slippage is unavoidable |

---

## Complementary Systems

The AI Manager works alongside higher-level agents in the TradingAgents ecosystem:

| Agent | Role | Frequency |
|-------|------|-----------|
| **Research Manager** | Bull/bear debate synthesis → investment recommendation | Lower frequency |
| **Portfolio Manager** | Final decision judge integrating research + risk | Lower frequency |
| **Risk Manager** | Independent veto gate with quantitative checks | Per-trade |
| **AI Manager** | Real-time position monitoring and exit management | Continuous (sub-second) |

The higher-level agents handle **entry decisions**. The AI Manager handles **real-time position management and exit**.

---

## Capabilities Summary

### What It Can Do

- Real-time position monitoring (sub-second latency)
- Multi-signal intelligent decision-making (8-node graph + Claude AI)
- Rapid profit preservation (drawdown-from-peak detection)
- Emergency crash protection (non-LLM fast-path, <50ms)
- Sweep/stop-hunt detection via orderbook analysis
- Multi-position correlated risk management
- Context-aware evaluation (regime, session, daily progress)
- Pattern learning from past decision outcomes
- Hot-reload configuration without restart
- Immutable audit trail (decision chain hashing)
- 24/7 autonomous operation with no human fatigue

### What It Cannot Do

- Generate entry signals (exit/risk management only)
- Predictive modeling or ML forecasting
- Cross-exchange arbitrage (Bybit only)
- Options or complex derivatives (linear futures only)
- Guarantee protection against liquidity gaps or flash crashes
- Portfolio optimization or hedging algorithms
- Live model training (batch pattern updates only)

---

## Known Limitations

### Liquidity Gaps & Flash Crashes

The emergency close submits a market order to Bybit. During a liquidity gap:

1. **Order book is thin** — market orders fill at progressively worse prices (slippage)
2. **Price gaps faster than WebSocket** — even <50ms reaction can't exit at intermediate prices that don't exist
3. **Exchange overload** — during extreme volatility, API can lag or reject orders
4. **No intermediate price** — a "gap" means price jumped A→C with no B to exit at

The system controls *when* it sends the order. It cannot control *what price the exchange fills at*.

### Other Limitations

- Pattern learning is incremental, not backtested against historical data
- Correlation analysis uses 1h klines only (may miss intraday divergences)
- Single exchange (Bybit) — no cross-venue liquidity access
- LLM hallucination risk mitigated by structured output + risk gates, but not eliminated

---

## All Exact Threshold Values (Quick Reference)

| Component | Parameter | Value |
|-----------|-----------|-------|
| **Evaluator** | Emergency PnL velocity | 5.0% in 30s |
| **Evaluator** | Urgent PnL velocity (FAST) | 2.0% in 30s |
| **Evaluator** | RSI upper threshold | 70 |
| **Evaluator** | RSI lower threshold | 30 |
| **Evaluator** | ATR volatility multiplier | 2.0× |
| **Evaluator** | Per-symbol cooldown | 15.0 seconds |
| **Evaluator** | Drawdown-from-peak threshold | 40% |
| **Evaluator** | Cluster PnL escalation | -2.0% combined |
| **Circuit Breaker** | Failure threshold to trip | 3 consecutive |
| **Circuit Breaker** | Cooldown duration (OPEN) | 3600s (1 hour) |
| **Degradation** | Hysteresis for tier recovery | 300s (5 min) |
| **Regime** | ADX trend threshold | > 25 |
| **Regime** | ATR ratio for volatile | ≥ 2.0 |
| **Regime** | Compression BBW threshold | < 0.1 |
| **Regime** | Compression ATR threshold | < 0.7 |
| **MTF** | 5m weight | 0.10 (10%) |
| **MTF** | 15m weight | 0.20 (20%) |
| **MTF** | 1h weight | 0.35 (35%) |
| **MTF** | 4h weight | 0.35 (35%) |
| **Correlation** | Default cluster threshold | 0.7 |
| **Correlation** | Same-dir risk weight | 1.0 |
| **Correlation** | Hedged risk weight | 0.1 |
| **OrderBook** | Cluster detection multiplier | 3.0× baseline |
| **OrderBook** | Max clusters per side | 5 |
| **OrderBook** | SL proximity for sweep | 0.5% (0.005) |
| **OrderBook** | Near-SL annotation | 0.3% |
| **Sweep** | Trade tape buffer size | 1000 trades |
| **Sweep** | Volume analysis window | 30 seconds |
| **Sweep** | Confidence threshold | 0.5 |
| **Sweep** | Recovery timeout | 3 candles (default) |
| **Graph** | Cold-start decision count | 10 |
| **Graph** | Cold-start confidence | 0.85 |
| **Graph** | Context enrichment timeout | 20 seconds |
| **Graph** | LLM call timeout | 30 seconds |
| **Graph** | LLM retry attempts | 2 |
| **Task** | SLEEPING heartbeat | 60 seconds |
| **Task** | Max reasoning stored | 2000 characters |
| **Task** | Per-symbol cooldown | 15.0 seconds |
| **Task** | Token budget (daily) | 100,000 |
| **Task** | Min position age (default) | 300 seconds |
| **Scheduler** | FAST semaphore slots | 3 |
| **Scheduler** | GENERAL semaphore slots | 7 |
| **Scheduler** | DEEP concurrent sub-limit | 2 |
| **Scheduler** | FAST acquire timeout | 10ms |
| **Scheduler** | GENERAL burst timeout | 5 seconds |
| **Scheduler** | Per-account max inflight+queued | 2 |
| **Prompts** | Max field length (sanitized) | 200 characters |
| **Prompts** | Token estimate ratio | 4 chars per token |
| **Prompts** | Episodic memory shown to LLM | 10 decisions |
| **Prompts** | Patterns shown to LLM | 5 max |
| **Risk Tolerance** | Conservative confidence boost | +0.10 |
| **Risk Tolerance** | Conservative loss sensitivity | 1.5× |
| **Risk Tolerance** | Moderate confidence boost | 0.00 |
| **Risk Tolerance** | Moderate loss sensitivity | 1.0× |
| **Risk Tolerance** | Aggressive confidence boost | -0.05 |
| **Risk Tolerance** | Aggressive loss sensitivity | 0.7× |
| **Decision Chain** | Genesis hash | "0" × 64 |
| **Decision Chain** | Hash algorithm | HMAC-SHA256 |
| **Outcome Labels** | Profitable threshold | > $0.50 |
| **Outcome Labels** | Loss threshold | < -$0.50 |
| **Emergency** | Post-execution cooldown | 30 seconds |

---

## Getting Started

1. Enable with `dry_run: true` and conservative settings
2. Monitor decision logs for 1–2 weeks
3. Verify decisions align with your trading style
4. Gradually lower `confidence_threshold` and enable `auto_enabled`
5. Scale `max_daily_actions` as confidence grows
6. Enable enhanced features (MTF, correlation, orderbook) one at a time
