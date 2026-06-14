# TradingAgents — Environment & Skills Briefing

> Paste-ready context for any session. Point Claude at this file to load full
> environment understanding in one shot.

## Two environments
- **LOCAL DEV** = the Windows dev machine. Safe to mutate/experiment freely.
- **PROD** = remote server `157.173.124.192` (hostname `vmi3290883`). Treat as
  read-only / production-careful unless explicitly told "write to prod".

## Rule of thumb
- MCP tools + `localhost` → **DEV** (mutate freely)
- `ssh_run.py` / `157.173.124.192` / sslip.io → **PROD** (careful)

## 1. Production server access (SSH)
- Script: `c:\Users\ttbasil\Desktop\Projects\PublicProjects\copilot-api\ssh_run.py`
  - SSHes to `root@157.173.124.192`, runs one command, exits with its code.
  - Usage: `python "<path>/ssh_run.py" "<cmd>" [timeout_secs]` (default 120s).
  - GOTCHA: call the script path with **FORWARD SLASHES**
    (`c:/Users/.../ssh_run.py`). Backslashes get stripped and mangle the path.
- Prod runs as **systemd services (NOT Docker)**:
  - `tradingagents-backend.service` → uvicorn `backend.main:create_app`, `127.0.0.1:8877` (factory)
  - `tradingagents-frontend.service` → vite `0.0.0.0:5177`
  - `nginx` (`:80`/`:443` reverse proxy), `postgresql@16-main` (`:5432`)
  - Code at `/root/projects/TradingAgents/`

## 2. Databases (same URL shape, host swaps the target)
`postgresql://postgres:Mywings123@<host>:5432/tradingagents`
- `localhost` → **LOCAL DEV** DB (Postgres 18.3, ~72 public tables)
- `157.173.124.192` → **PROD** DB (Postgres 16). Reachable **directly over TCP**
  AND via SSH+psql. (Note: profitability-research doc says "SSH only / 5432 not
  exposed" — that's stale; direct 5432 works.)
- Prod psql via SSH:
  `python copilot-api/ssh_run.py 'psql "postgresql://postgres:Mywings123@localhost:5432/tradingagents" -t -A -F"|" -c "<SQL>"'`
- Prod API (WebFetch-able): `https://157-173-124-192.sslip.io/api/v1/`

## 3. MCP server — LOCAL/DEV ONLY
- `.mcp.json` defines `tradingagents` (HTTP) → `http://127.0.0.1:8877/mcp/rpc/mcp`
  with a bearer token. Tools-only (no MCP resources).
- Because it's `127.0.0.1:8877`, **`mcp__tradingagents__*` = local dev backend only.
  It CANNOT reach prod.** For prod use ssh_run.py / direct DB / prod API.

## 4. Skill: copy-prod-scans  (sync prod scan data → LOCAL for backtesting)
- Run the bundled script, don't hand-write SQL:
  `python .claude/skills/copy-prod-scans/scripts/sync_scans.py`
  - `--dry-run` (reads prod, stages local, prints counts, ROLLS BACK)
  - `--since YYYY-MM-DD` (faster incremental)
- Default flow: read `sync-log.md` → pick `--since` ~1 day before newest local
  scan → dry-run → show counts/continuity → real sync.
- Prod = read-only (SELECT only); local writes in one verified transaction.
  Hard guards: LOCAL must be localhost/tradingagents, PROD must be non-localhost.
- Copies (FK order): scheduled_scans → scans → scan_results → analysis_runs →
  schedule_executions → symbol_sectors → backtest_adaptive_blacklist_history.
  NOT copied: klines, accounts, API keys, trades.
- LOCAL from `DATABASE_URL`; PROD from `PROD_DATABASE_URL` in repo-root `.env`
  (gitignored; confirmed set). Logs each committed run to `sync-log.md`.

## 5. Command: /profitability-research  (analyze LIVE/PROD performance)
- Reads PRODUCTION (via SSH+psql and prod API). 7 steps: read
  `docs/research/research-history.md` baseline → live API state → DB deep-dive
  (account rankings, signal-score perf, close reasons, leverage/direction, scan
  staleness, batch wipeouts, toxic/golden symbols, AI-manager effectiveness,
  equity curves) → new patterns → write `docs/research/reports/YYYY-MM-DD_HH-MM-…md`
  → update history log → concise summary.
- Schema quirks: `scans.started_at`/`completed_at` are TEXT and appear SWAPPED;
  scores signed (use ABS() for magnitude); `high_freq_snapshots` ts col = `ts`;
  AI `execution_result` may be all-NULL; close_reason: `rule_triggered`=per-trade
  TP/SL, `manual_close_all`=equity rule, `external`=AI/manual.
- Context: Epoch 2 reset on 2026-06-14 — all 21 demo accounts → $100 on new
  "Every 3 Hour Scan"; cohorts A (8×, drawdown 12%, smart-close ON) and
  B (7×, drawdown off); AI-manager on/off split. Account IDs in the command doc.

## 6. Codebase (from CLAUDE.md)
- Backend FastAPI `backend/`; Frontend React+TS+Vite `frontend/`; engine
  LangGraph `tradingagents/`; Postgres via asyncpg.
- Active feature in progress: **Backtesting System** (`/new-feature`),
  tracker at `plans/backtesting-system/progress-tracker.md`.
