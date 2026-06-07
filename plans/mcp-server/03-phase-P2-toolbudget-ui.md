# Phase P2 — Tool Budget + Operator UI

**Goal:** The user's tool-budget control surface — enable/disable groups + individual tools with presets and a context-cost meter — plus the `/mcp` operator page (Overview/Tools/Connection/Status/Activity) and the System nav entry. Backend registry/presets already exist (P0); this phase wires the control-plane + frontend.

**Entry:** P1 exit met.
**Exit:** tool toggle property-test green (most-restrictive, never a disabled tool, persistence round-trip); budget ±10% test; `/mcp` page renders all sections + states; axe a11y green; OFF-path nav zero-overhead.

**Requirements:** FR-007/008/009/010, NFR-004/013, AC-003/004; UI §L; R-45..57/143..179.

---

## J. Frontend Implementation Plan

### Files (new `frontend/src/components/mcp/`)
- `McpPage.tsx` — shell (PageHeader + `ui/tabs`/accordion); sections Overview/Tools/Connection/Status/Activity in P2, **Optimizer + Proposals tabs added in P4** (frontend-R1-F2 — the shell must host them, not just deep-link).
- `sections/OverviewSection.tsx` (master toggle + status + disable/kill), `ToolsSection.tsx` (group cards + budget meter), `ConnectionSection.tsx` (endpoint/token/snippet), `StatusSection.tsx`, `ActivitySection.tsx` (audit feed). 503/"MCP unavailable" panel state in `McpPage.tsx` (module absent → `GET /status` 503, mirror the debug 503 gate — frontend-R1-F4).
- `McpProposalReview.tsx` — stub here (filled P4), reached via the flat route `/mcp/proposals/$proposalId`.
- **API client (frontend-R1-F1):** add an `mcpApi` namespace object INSIDE `frontend/src/api/client.ts` (the established pattern — `request`/`mutate` are module-private and NOT exported; do NOT create a separate file importing them). zod v4 schemas mirroring control-plane responses live in `frontend/src/api/mcpSchemas.ts`.
- `ui/` new primitives: `Switch.tsx` (`@base-ui/react` switch/), `Accordion.tsx` (`@base-ui/react` accordion/), `SegmentedControl.tsx` (composes `@base-ui/react` toggle-group/ — NOT a direct primitive, frontend-R1-F7).

### Tasks
- TASK-P2-01: Master ON/OFF switch (default OFF) + security-warning confirm dialog (lists capabilities + data-egress consent) → `POST /enable`; OFF-state hero (explainer + single Enable CTA); ON reveals sections; disable/kill confirm (warns of dropped sessions).
- TASK-P2-02: Tools section — group cards (tri-state master toggle + "X of Y enabled"), per-tool `Switch`+safety badge+tooltip, preset selector (Minimal/Standard/Full/Read-only/Backtest-only), select-all/none, search/filter, explicit **Save** (unsaved-changes guard) → `PATCH /config`.
- TASK-P2-03: Context-budget meter — sticky "N enabled" + token meter (green/amber/red, warning at 16k = 80% of Full ceiling); computed client-side from `GET /tools` `est_tokens` (no per-checkbox round-trip), within ±10% (BPE-referenced, biased up).
- TASK-P2-04: Connection section — endpoint URL+copy; masked token (reveal only in the one-time post-generation window) + copy + Regenerate(confirm→`POST /token/regenerate`); client-config snippet (`ui/tabs` per client: Claude Desktop mcp-remote / Claude Code --header / generic) + "Test connection" → `POST /test-connection`.
- TASK-P2-05: Status + Activity — `GET /status` (running/leader/sessions/last-error/pending_proposals) polled while enabled; activity feed `GET /audit` (keyset, filter by tool/group/outcome, expand to redacted args).
- TASK-P2-06: Route + nav — `route-tree.tsx`: TWO FLAT routes (the codebase has no nested routing — frontend-R1-F5) `mcpRoute` at `/mcp` + `mcpProposalRoute` at `/mcp/proposals/$proposalId` via `createRoute`→`addChildren` (mirror the `/backtest/$runId` precedent; `useParams({from:"/mcp/proposals/$proposalId"})`). `navigation.ts`: System-section "AI Agent (MCP)" entry with an icon (e.g. `Bot`/`PlugZap`/`Network` from lucide-react — icon is REQUIRED — frontend-R1-F6), `matches:(p)=>p.startsWith("/mcp")`; extend `NavItem` with `status?`/`badgeCount?`. Extend `HealthResponse` with `mcp?: {enabled:boolean; state:string; pending_proposals:number}` (frontend-R1-F8); the nav status SHARES the existing `getHealth` query (same queryKey as AppMarketBar — no double-fetch) for the one-shot seed, then polls `GET /status` only when enabled, backs off on 503 (zero-overhead OFF). Status dot in mobile System header (not the dock).

## K. Backend Implementation Plan (P2)
- TASK-P2-07: `GET /api/v1/mcp/tools` returns the FULL registry (`name/group/description/safety_class/mutating/annotations/input_schema/est_tokens`) + preset definitions. `est_tokens` precomputed at registration via a BPE reference (biased up).
- TASK-P2-08: `PATCH /config` applies group/tool/preset/tier changes (optimistic-concurrency `row_version`); on change emit `notifications/tools/list_changed` to connected sessions (registry-filter, no rebuild — ADR-7); env-managed fields write-blocked (403).
- TASK-P2-09: `tools/list_changed` wiring + the registry-filter dispatch path (disabled tool → `-32601`).

## L. Security (P2)
- Reveal-token only in the post-generation window; env-managed fields read-only/write-blocked; data-egress consent recorded on first enable (AC-022); activity-feed XSS hardening (render agent/market strings inert, strict CSP on `/mcp`).

## M. Testing Plan (P2)
- TASK-P2-10 (a11y tooling, frontend-R1-F3): install `vitest-axe` + `axe-core`, extend `src/test/setup.ts` with the `toHaveNoViolations` matcher; the a11y spec pins jsdom via `// @vitest-environment jsdom` (axe is unreliable under the global happy-dom env).
- Property (Hypothesis): toggle/registry state machine (advertised set == most-restrictive, never a disabled tool, persistence round-trip) — AC-003.
- Budget test: each READ-TOOL preset's summed est_tokens ≤ ceiling and within ±10% of actual `tools/list` payload (AC-004); the FULL-registry budget ceiling (2k/8k/20k) is re-asserted at P4 exit when all tools exist (arch-R1-F10).
- Frontend (vitest): McpPage renders OFF hero / ON sections / **503 panel**; tool toggles + Save; budget meter; connection snippet copy; nav OFF-path asserts NO MCP control calls when disabled (NFR-011, shares the health query).
- zod drift test: `/mcp` zod schemas validate against MSW fixtures **sourced from recorded real control-plane responses** (not hand-authored — frontend-R1-F9).
- a11y: axe test of `/mcp` panels in both themes (NFR-013); keyboard nav of the tool matrix.

## N. Manual Verification (P2)
1. `/mcp` OFF → explainer + Enable. Enable → confirm → sections appear.
2. Tools → toggle a group/tool, watch the meter, Save → reconnect a client → `tools/list` reflects the change.
3. Apply "Backtest-only" preset → only backtest+read tools enabled.
4. Connection → reveal token once, copy snippet, Test connection → OK.

## O. Completion Criteria (P2)
All P2 tests green; `npx tsc --noEmit` clean; axe green. Commit `feat(mcp): P2 tool-budget control + /mcp operator UI`.
