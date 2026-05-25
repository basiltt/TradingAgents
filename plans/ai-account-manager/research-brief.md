# AI Account Manager — Research Brief

## 1. AI Trading Architecture

- **Multi-agent debate pattern** (Bull/Bear advocates) improves decision quality by forcing opposing arguments before synthesis
- **FSM + event-driven hybrid** is industry standard for trading bots (sleep/monitor/analyze/execute states)
- **Structured output via Pydantic** with `.with_structured_output()` ensures deterministic action schemas
- **Per-account task isolation** prevents cross-contamination; single asyncio.Task per account is correct pattern
- **Priority hierarchy**: Safety rules > Execution engine > AI intelligence (confirmed by Knight Capital post-mortem)

## 2. Trend Reversal Detection (Specific Thresholds)

- **RSI divergence**: Price makes new high but RSI doesn't → reversal signal. Threshold: RSI crosses 70 (overbought) or 30 (oversold)
- **MACD histogram**: Sign flip (positive→negative) with declining momentum = early reversal. Use 12/26/9 standard params
- **Volume-price divergence**: Price up + volume down = weakening trend. Confirm with 3+ candles
- **Funding rate flip**: Sign change in perpetual funding = sentiment shift. Check every 8h cycle
- **ATR-based trailing**: Trail at 2-3x ATR for crypto volatility. Tighten to 1.5x ATR in high-urgency
- **Order flow imbalance**: Bid/ask ratio < 0.3 or > 3.0 signals directional pressure
- **PnL velocity**: >2% unrealized PnL change in 30s = urgent signal (confirmed threshold)

## 3. LangGraph Patterns

- **StateGraph** with TypedDict state — nodes are pure functions, edges are conditional
- **Conditional routing**: `add_conditional_edges(node, router_fn, {value: next_node})` for urgency-based path selection
- **Error handling**: Wrap nodes in try/except → route to fallback node that emits safe HOLD action
- **Retry policy**: Single retry on malformed LLM output, then fallback (not infinite retry)
- **Checkpointing**: Use MemorySaver for working memory within session; PostgreSQL for persistence across restarts
- **Structured output**: `model.with_structured_output(PydanticSchema)` — no manual JSON parsing needed
- **Token management**: Keep prompts under 4K tokens total; truncate oldest episodic memories first

## 4. Financial AI Safety Systems

- **Circuit breaker**: 3 consecutive losses → OPEN (no actions) → cooldown 1h → HALF_OPEN (1 test action) → reset on profit
- **Write-ahead logging (WAL)**: Record decision BEFORE execution; fill outcome AFTER. Enables crash recovery
- **Position reconciliation**: Exchange state is source of truth. Poll every 60s to detect phantom positions
- **Graceful degradation**: 4 tiers (Nominal → Degraded → Conservative → Safe). Each tier reduces AI autonomy
- **Kill switch**: Checked at EVERY execution boundary. Fail-closed (if check fails, assume killed)
- **Max single-decision loss**: Cap at 3% of account equity per action (configurable by risk tolerance)
- **Daily loss limit**: 5% cumulative AI-initiated losses → auto-pause until next day
- **Knight Capital lesson**: Always have automated kill switches; never rely solely on manual intervention
- **Defense-in-depth**: 10 layers from LLM output validation through to human escalation

## 5. Memory Architecture

- **FinMem K=5 retrieval**: 2 shallow (recent) + 2 mid-depth + 1 deep (oldest relevant) — optimal for trading context
- **Three-tier memory**:
  - Episodic: Raw decision records with outcomes (90-day retention, last 15 in prompt)
  - Semantic: Distilled patterns/rules ("avoid closing ETH positions during US market open" type insights)
  - Working: Current session state (positions, recent signals, in-memory only)
- **Outcome labeling**: profitable (>0.5% net), loss (<-0.5% net), neutral (in between). Include fees+slippage
- **Pattern invalidation**: If pattern confidence drops below 0.4 after 10+ episodes → mark inactive
- **Token budget**: ~3,400 tokens for full context injection fits 4K window comfortably
- **Confidence calibration**: Track Brier score; if consistently overconfident, apply dampening factor
- **Pattern generation**: Run every 24h as background job; analyze clusters of similar decisions

## Key Implementation Decisions (From Research)

1. Use `asyncio.Semaphore(5)` for LLM concurrency (not 10 — research shows 5 is safer for rate limits)
2. Temperature 0.0 for deterministic decisions (confirmed best practice for financial AI)
3. 30s hard timeout on LLM calls (industry standard for trading latency requirements)
4. Debounce WS events at 1.5s (matches existing close-rule pattern)
5. JSONB columns for flexible schema evolution without migrations
6. Append-only decision table (no UPDATEs except outcome backfill)
7. Brier score tracking for confidence calibration (add to semantic patterns)
