# TradingAgents — Project Context

## Current Work

### Active Feature: Backtesting System
**Skill:** `/new-feature`
**Status:** Starting — CLAUDE.md created, ready to invoke skill
**Started:** 2026-06-05

**Summary:** Building a comprehensive backtesting system that simulates the full auto-trade cycle (scan results → signal filtering → trade placement → close rule evaluation → position closure) using historical scheduled market scan data. Must produce TradingView-level metrics and visualizations.

**Key Requirements:**
- Uses real scan results from DB as signal source (not re-analyzing)
- Same parameters as Scheduled Market Scanner (all config fields from AutoTradeConfig)
- No account configs used — user provides fresh capital, TP/SL, leverage, etc.
- Must enforce auto-trade cycle rules (no new trades while previous cycle running)
- All close rules: EQUITY_RISE_PCT, EQUITY_DROP_PCT, BREAKEVEN_TIMEOUT, MAX_DURATION, TRAILING_PROFIT
- Super fast execution (seconds, not minutes) — uses cached kline data
- TradingView-quality results: equity curve, drawdown chart, all standard backtest metrics
- NO AI Manager feature (deferred)
- <1% deviation from real trading results

**Architecture Decisions (pending skill workflow):**
- Backend: Python simulation engine (no real API calls)
- Kline cache: Local DB table or file cache
- Frontend: Full results dashboard with charts

## Codebase Overview

- **Backend:** FastAPI (Python) at `backend/`
- **Frontend:** React + TypeScript + Vite at `frontend/`
- **Trading Engine:** LangGraph multi-agent at `tradingagents/`
- **Database:** PostgreSQL (asyncpg)
- **Key Services:**
  - `scanner_service.py` — orchestrates market scans
  - `auto_trade_service.py` — AutoTradeExecutor (signal filtering + trade placement)
  - `close_rule_evaluator.py` — evaluates close conditions (TP/SL/drawdown/trailing)
  - `position_reconciler.py` — syncs positions with exchange
  - `accounts_service.py` — Bybit API interaction
  - `sector_service.py` — dynamic sector classification
  - `ai_manager_task.py` — AI-powered position management (excluded from backtest)

## Recent Changes (2026-06-04/05)

- Fixed 93% sell signal bias (crypto PM prompt)
- Added price drift validation, adaptive blacklist, sector concentration limit
- Dynamic sector classification (CoinGecko + LLM + DB cache)
- Fixed AI Manager execution pipeline (dry_run gate, outcome tracking)
- DB constraint fix for EQUITY_DROP_PCT_SMART, TRAILING_PROFIT, PAUSE_TRADING
- Added POST /scanner/{scan_id}/auto-trade endpoint

---

## Commands

```bash
# Backend
python -m pytest tests/ -x -q                    # Run all tests
python -m pytest tests/backend/ -x -q            # Backend tests only
python -m uvicorn backend.main:app --reload      # Dev server

# Frontend
cd frontend && npm run dev                       # Dev server
cd frontend && npx tsc --noEmit                  # Type check
cd frontend && npm run build                     # Production build

# Database
# Migrations auto-apply on app startup (persistence.py / async_persistence.py)
```

## Code Rules

### Backend
- Python 3.12+, asyncio throughout
- All DB operations use `asyncpg` (async) via `AsyncAnalysisDB`
- Tests in `tests/`, use `pytest` + `pytest-asyncio`
- Services at `backend/services/`, routers at `backend/routers/`
- Schemas at `backend/schemas/__init__.py` (Pydantic v2)

### Frontend
- TypeScript strict, React 18+ with TanStack Query + Router
- API calls through `frontend/src/api/client.ts`
- Components at `frontend/src/components/`

### Environment
- `DATABASE_URL` — PostgreSQL connection
- `ACCOUNTS_ENCRYPTION_KEY` — required for trading
- `TRADINGAGENTS_LLM_PROVIDER` + API keys — for AI features
- `COINGECKO_API_KEY` — for sector classification

---

## Agent Behaviour

### Skill Execution — STRICT ENFORCEMENT

When a skill is loaded (via `/skill-name` or auto-trigger), its instructions are **mandatory procedures, not suggestions**. Every step and review loop is a hard requirement. Reviews are governed by **convergence**, not a round quota.

**1. Never skip mandated reviews.**
- There is NO minimum round count. Each review runs until **2 consecutive rounds produce no new findings** (convergence), then stops. A review that converges on round 3 is complete and valid; do NOT pad rounds to hit a number.
- Always 5 agents per round, all in one message. 1 agent for 1 round is a critical violation — convergence needs at least 2 rounds of evidence.
- Fix every valid Critical/High/Medium finding the moment it appears. Convergence means findings have run dry, not that review was cut short.
- Every ⛔ STOP gate means you cannot proceed until the gate condition is satisfied.

**2. Never collapse multi-step workflows.**
- If the skill prescribes Steps 2→3→4→5→6→7, execute ALL in order. Never jump from partial spec to implementation.

**3. Never implement without passing all review gates.**
- No code until spec review AND plan review have converged (2 consecutive rounds with no new findings).
- No phase advances until per-phase reviews ALL converge.
- No final commit until final review steps converge.

**4. TDD is non-negotiable.**
- Every phase must include tests. Zero-test implementations are invalid.

**5. Progress tracker must be updated in real-time.**
- Every activity gets a row immediately. Next session resumes from tracker state.

**6. Context compaction does not excuse violations.**
- After compaction: (1) read the progress tracker, (2) re-read the skill's SKILL.md, (3) resume from tracker state. Do not default to "just implement it."
- The `.claude/rules/skill-recovery.md` rule file reinforces this — it is always loaded.

**7. Auto-progression — NEVER stop, pause, or ask permission between steps.**
- Proceed through ALL steps continuously without pausing. Do not say "this is a good stopping point", "ready for next session", "shall I continue?", or present the work as complete mid-workflow.
- A skill workflow is ONE continuous execution from start to finish. If context runs out, the progress tracker ensures the next session resumes — but YOU never voluntarily stop.
- The ONLY reasons to stop mid-workflow: (a) a genuine external blocker you cannot resolve, (b) the skill's final step explicitly presents completion options (e.g., merge/PR/discard).
- "Planning is done, implementation is next" is NOT a stopping point. Keep going.

**8. Reviews converge — they are not round quotas.**
- There is no "minimum rounds" and no "AT LEAST N." A review is done when 2 consecutive rounds surface no new findings.
- The numbers some docs still mention (15, 25) are infinite-loop safety caps only — a backstop, never a target. Never keep reviewing just to reach a cap.

**If you're about to skip a step because "it seems unnecessary" — STOP. That instinct is exactly what these rules prevent. Follow the procedure.**

### Output & Editing
- All large edits: smaller chunks (~150 lines max per tool call), never reduce content
- Plan files must be comprehensive — do not compromise length/size; write in multiple sequential edits

### Validation Before Claiming Completion

Before saying any task is done:
1. Run the relevant validation command (test, lint, typecheck, build)
2. Read the full output — do not assume it passes
3. Only claim success after verifying actual output

### Commit Discipline

- Run tests before every commit
- Never commit without tests for new functionality
- Use conventional commits: `feat(scope):`, `fix(scope):`, `refactor(scope):`
- Keep commits atomic — one logical change per commit

---

## Context Compaction Recovery — CRITICAL (Survives Compaction)

**After EVERY context compaction, BEFORE doing anything else:**

1. **Find the active tracker:** `Glob: plans/*/progress-tracker.md` and `plans/*/TRACKER.md` and `plans/*/implementation-progress.md`
2. **Read the tracker.** It tells you: which skill is active, what step you're on, what's done, what's next.
3. **Re-read the active skill's SKILL.md** (path will be in the tracker or use `~/.claude/skills/<skill-name>/SKILL.md`).
4. **Resume from the tracker's last IN_PROGRESS or next PENDING step.** Do not restart, skip, or freelance.

**Rules that NEVER expire, even after compaction:**

- If a tracker exists, the workflow is IN PROGRESS — follow it.
- Never implement without a reviewed spec and plan.
- Never reduce review rounds below convergence (2 consecutive rounds with no new findings).
- Never ask "shall I continue?" — auto-progress is mandatory.
- The skill workflow order is: discovery → requirements → spec → spec review → plan → plan review → implement (per phase with TDD) → final review → commit. Never jump phases.
- **If you feel lost — READ THE TRACKER.** Do not guess, do not start over.

---

## Compact Instructions

When compacting this conversation, ALWAYS preserve these in the summary:

1. Which skill workflow is active (e.g., `/new-feature`, `/develop-plan`, `/implement-plan`)
2. The exact step number currently in progress
3. The path to the progress tracker file
4. How many review rounds have run for the active review and whether it has converged (2 consecutive rounds with no new findings)
5. Any blockers or decisions made during the session
6. The instruction: "After compaction, read the progress tracker and skill SKILL.md before doing anything else"
