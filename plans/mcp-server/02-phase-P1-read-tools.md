# Phase P1 — Read Tools + Resources + Prompts

**Goal:** Build the full read-tool suite (the agent's "basic features" surface), MCP resources, and static prompts — all READ_ONLY, redacted-by-default, shaped/paginated. Each tool follows the P0 `@tool` + dispatch pipeline (no new plumbing).

**Entry:** P0 exit met (registry/dispatch/auth/audit + `scans_list` green).
**Exit:** every read tool contract-tested (advertised schema == Pydantic); redaction leak-test green; resources/prompts e2e green; per-tool registry-completeness passes.

**Requirements:** FR-011/012/013/031, AC-003/017; resources/prompts (R-14/15); shape/pagination (R-129/461/500); redaction (R-296).

---

## K. Backend Implementation Plan

### Read tools — one module per tool under `backend/mcp/tools/<group>/`
Each: `@tool(... safety_class=READ_ONLY, mutating=False)`, thin handler calling an EXISTING side-effect-free service/repo method (or a NEW thin read-only repo method where none exists — never a method that triggers a scan/trade). Compact `summary` projection by default, `detail` opt-in, keyset pagination (≤500 rows), top-N (≤20) + drill-down handle.

| TASK | Tool | Group | Backing read | Redaction |
|------|------|-------|--------------|-----------|
| P1-01 | `scans_get` | SCANS | stored scan + ranked signals (no re-run) | — |
| P1-02 | `accounts_list` / `accounts_get` | ACCOUNTS | accounts_service read | balances→ratios by default (FR-031); demo-only unless live tier |
| P1-03 | `positions_list` / `positions_get` | POSITIONS | positions read | opaque ids |
| P1-04 | `trades_list` / `trades_get` | TRADES | trades read (filters) | absolute P&L→ratios by default |
| P1-05 | `portfolio_overview` | PORTFOLIO | portfolio read | aggregated |
| P1-06 | `analytics_summary` / `signal_analytics` | ANALYTICS | analytics + signal_analytics read | — |
| P1-07 | `scheduled_list` / `scheduled_get` | SCHEDULED | scheduled_scans read (incl. auto_trade_configs, redacted) | — |
| P1-08 | `strategies_list` / `config_current` | STRATEGIES | strategy_service + current AutoTradeConfig | — |
| P1-09 | `symbols_search` / `symbols_get` | SYMBOLS | symbols + sector read | — |

- **Shape utility (`core/shape.py`, built P0-light, finalized here):** `summary` vs `detail` projection, truncation markers, keyset cursor `(sort_key, last_id)` opaque+validated, equity downsample ≤1000 pts (LTTB). Reused by every tool (no per-tool re-impl).
- **Redaction (`core/redact.py`):** `redact_financial(obj, *, allow_raw: bool)` — balances/abs-P&L → ratios unless the financial-detail opt-in flag is set; runs in the dispatch `shape/redact` stage over ALL outputs.

### Resources (`backend/mcp/resources/`)
- TASK-P1-10: `resources/list` + `resources/read` for `tradingagents://scan/latest`, `tradingagents://config/current`, `tradingagents://portfolio/snapshot`, `tradingagents://server/info` (version/contract). `resources/templates/list` for `tradingagents://scan/{id}` with strict UUID param validation (reject `../`, cross-scope). `resources.subscribe=false` (P5 deferral).

### Prompts (`backend/mcp/prompts/`)
- TASK-P1-11: `prompts/list` + `prompts/get` for static templates: `optimize_my_config`, `audit_last_scan`, `explain_trade_close`. Server-owned, read-only, integrity-checked; `prompts/get` args validated+escaped before interpolation.

## L. Security Implementation Plan (P1)
- Redaction-by-default leak test (balances/P&L never raw without opt-in); resource-URI param validation parity (UUID, no traversal); prompt-arg escaping; secret leak test extended to resource/prompt outputs.

## M. Testing Plan (P1)
- Contract test (parametrized over all P1 tools): advertised input schema == `Pydantic.model_json_schema()`; registry-completeness now asserts each tool has an error-map entry + emits one audit row.
- Per-tool unit: correct shape, redaction default, no side-effect (spy asserts no scan/trade triggered), pagination cursor stability.
- Integration (in-memory ASGI): resources/list+read+templates; prompts/list+get; the MVP resource/prompt e2e (AC — R-562).
- Redaction leak test (AC-017): account/trade tools return ratios by default; raw only with the financial-detail opt-in.

## N. Manual Verification (P1)
1. Enable MCP, Standard preset → `tools/list` shows the read suite.
2. Call `accounts_list` → balances are ratios; set financial-detail opt-in → raw appears.
3. `resources/read tradingagents://scan/latest` → latest scan summary.
4. `prompts/get optimize_my_config` → a guided prompt.

## O. Completion Criteria (P1)
All P1 tests green; contract + redaction + resource/prompt e2e green. Commit `feat(mcp): P1 read tools, resources, prompts (redacted, shaped)`.
