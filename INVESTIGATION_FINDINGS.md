# TradingAgents Frontend Investigation Report

## EXECUTIVE SUMMARY

### Auto-Scroll: FOUND
Location: frontend/src/components/analysis/MessagesPanel.tsx, lines 108-110
Status: Working correctly using scrollIntoView()

### Configuration Display: NOT IMPLEMENTED
Data Available: YES - Full config in API response
Location: Data fetched at AnalysisDashboard.tsx lines 67-72
Status: Config fetched but never displayed

---

## PART 1: AUTO-SCROLL BEHAVIOR

### Location: MessagesPanel.tsx

Line 104: Create ref for scroll target
```
const bottomRef = useRef<HTMLDivElement>(null);
```

Lines 108-110: Auto-scroll effect
```
useEffect(() => {
  bottomRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages.length]);
```

Line 159: ScrollArea container
```
<ScrollArea className="h-[28rem]" role="log">
```

Line 177: Scroll target element
```
<div ref={bottomRef} />
```

### How it Works
1. Empty div at bottom of messages with ref
2. useEffect watches messages.length
3. When new message arrives, calls scrollIntoView()
4. Smooth behavior animates the scroll
5. Shows newest messages at bottom

### Performance
- Component wrapped in memo() (line 103)
- Only scrolls on length change, not content change
- Efficient dependency tracking

---

## PART 2: CONFIGURATION DATA

### Data Fetched But Never Used

AnalysisDashboard.tsx lines 67-72:
```
const { data: runDetails } = useQuery({
  queryKey: ["analysis", runId, "details"],
  queryFn: ({ signal }) => apiClient.getAnalysis(runId, signal),
  staleTime: 10_000,
  refetchInterval: status === "connected" ? 15_000 : false,
});
```

What gets used:
- Line 132: runDetails?.ticker
- Lines 140-141: runDetails?.started_at, runDetails?.completed_at
- NEVER: runDetails?.config

### API Response Type

api/client.ts lines 91-101:
```
export interface AnalysisRun {
  run_id: string;
  ticker: string;
  analysis_date: string;
  status: string;
  config: Record<string, unknown>;  // FULL CONFIG HERE
  started_at: string;
  completed_at?: string;
  error?: string;
  asset_type?: AssetType;
}
```

### Configuration Contents

From backend analysis_service.py _build_config() method:

- llm_provider: openai|anthropic|google|xai|deepseek|qwen|glm|openrouter|azure|ollama
- deep_think_llm: model ID string
- quick_think_llm: model ID string
- research_depth: 1-5
- max_debate_rounds: 1-10
- max_risk_discuss_rounds: 1-10
- max_recur_limit: 1-500
- checkpoint_enabled: boolean
- asset_type: stock|crypto
- crypto_interval: 15|60|240|D
- output_language: English|Chinese|Japanese|etc
- data_vendors: mapping of categories to vendors
- backend_url: custom URL if provided

### Backend Configuration Building

File: backend/services/analysis_service.py

Lines 160-214: _build_config() method
- Deep copies app defaults
- Overrides with request parameters
- Returns complete config object

Line 63: Secrets masked before storage
Line 70: Config stored in database as JSON

Backend Router (routers/analysis.py):
- Lines 75-81: get_analysis() returns run with config

### What Dashboard Displays

Currently shows:
- Ticker symbol (from runDetails.ticker)
- Status badge (from runDetails.status)
- Duration (from runDetails.started_at/completed_at)
- Agent status table (from WebSocket)
- Messages panel (from WebSocket)
- Reports panel (from snapshot)
- Stats bar (from WebSocket)

Does NOT show:
- LLM provider
- Model IDs
- Research parameters
- Data vendors
- Checkpoint status
- Crypto settings
- Language setting

---

## CODE LOCATIONS SUMMARY

### Auto-Scroll References
File: MessagesPanel.tsx
- Line 104: bottomRef creation
- Lines 108-110: useEffect with scrollIntoView
- Line 110: [messages.length] dependency
- Line 159: ScrollArea container
- Line 177: ref target div

### Configuration References
File: AnalysisDashboard.tsx
- Lines 67-72: useQuery fetch

File: api/client.ts
- Lines 91-101: AnalysisRun interface with config
- Lines 239-244: getAnalysis() method

File: backend/schemas.py
- Lines 188-198: AnalysisResponse schema

File: backend/services/analysis_service.py
- Lines 160-214: _build_config() method
- Line 63: mask_secrets()
- Line 70: config storage

File: backend/routers/analysis.py
- Lines 75-81: get_analysis endpoint

---

## FINDINGS

1. Auto-scroll works correctly at MessagesPanel.tsx:108-110
   - Uses scrollIntoView({ behavior: "smooth" })
   - Triggers on message count change
   - Well-implemented with refs

2. Configuration is available but not displayed
   - Fetched from API in AnalysisDashboard.tsx:67-72
   - Data is clean and masked
   - Rich information available (models, parameters, settings)
   - No UI to display it

3. Configuration data flow
   - Built by backend _build_config() method
   - Stored in database with secrets masked
   - Returned by API endpoint
   - Received by frontend but unused
