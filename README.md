# TradingAgents Web App

TradingAgents is now a web-based application for running multi-agent stock and crypto analysis from a browser.

This repository still contains the reusable `tradingagents` Python package and the original CLI, but the primary product surface is the web UI:

- React + TypeScript frontend
- FastAPI backend with REST + WebSocket streaming
- TradingAgents/LangGraph orchestration layer
- SQLite persistence for runs, reports, scans, and checkpoints
- Markdown-based memory log for past decisions and reflections

## Highlights

- Launch stock or crypto analysis from a browser
- Stream agent progress, messages, stats, and report sections in real time
- Review saved run history, markdown reports, and final snapshots
- Scan crypto markets in batches from the scanner page
- Persist checkpoints and memory between runs
- Inspect resolved config and runtime overrides from the UI
- Manage browser-side watchlists for repeated analysis
- Use OpenAI, Anthropic, Google, xAI, DeepSeek, Qwen, GLM, OpenRouter, Azure OpenAI, or Ollama

## Architecture

```text
Browser (http://localhost:5177)
        |
        v
React/Vite frontend
        |
        +--> /api/*  -> FastAPI backend (http://localhost:8877)
        +--> /ws/*   -> WebSocket stream for live run updates
                         |
                         v
                TradingAgentsGraph / LangGraph
                         |
                         +--> LLM providers
                         +--> Market data providers
                         +--> SQLite + markdown memory log
```

## Repository Layout

```text
backend/         FastAPI app, routers, services, persistence, WebSocket manager
frontend/        React + Vite web app
tradingagents/   Core multi-agent trading framework
cli/             Original CLI interface
scripts/         Helper scripts, including Linux/macOS web startup
Dockerfile       Container image for the web app
docker-compose.yml
start.bat        Windows helper to launch backend + frontend
```

## Main URLs

- Frontend: `http://localhost:5177`
- Backend API: `http://localhost:8877`
- Health check: `http://localhost:8877/api/v1/health`

## Prerequisites

### Without Docker

- Git
- Python 3.10+ (`3.12` recommended)
- Node.js LTS (`20+` recommended)
- npm
- At least one supported LLM provider API key, or a custom OpenAI-compatible backend

### With Docker

- Docker Desktop on Windows, or Docker Engine + Docker Compose plugin on Linux
- At least one supported LLM provider API key, or a reachable custom backend

## Environment Setup

Copy the example environment file first:

### Windows PowerShell

```powershell
Copy-Item .env.example .env
Copy-Item .env.enterprise.example .env.enterprise
```

### Linux

```bash
cp .env.example .env
cp .env.enterprise.example .env.enterprise
```

Notes:

- `.env.enterprise` is optional. Keep it only if you use Azure OpenAI or want a separate enterprise-specific env file.
- The backend and CLI now load `.env` and `.env.enterprise` automatically on startup.
- If you change `.env`, restart the backend process or restart `docker compose`.

## Setup Without Docker

### Windows

1. Clone the repository and enter it.

```powershell
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

2. Create and activate a virtual environment.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

3. Install frontend dependencies.

```powershell
Set-Location frontend
npm install
Set-Location ..
```

4. Fill in `.env` with at least one provider key.

5. Start the web app.

```powershell
.\start.bat
```

Manual startup is also available:

```powershell
python -m uvicorn backend.main:create_app --host 0.0.0.0 --port 8877 --factory --reload --reload-dir backend --reload-dir tradingagents
```

In a second terminal:

```powershell
Set-Location frontend
npm run dev -- --host 0.0.0.0 --port 5177 --strictPort
```

If PowerShell blocks virtual environment activation, use:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### Linux

1. Clone the repository and enter it.

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

2. Create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

3. Install frontend dependencies.

```bash
cd frontend
npm install
cd ..
```

4. Fill in `.env` with at least one provider key.

5. Start the web app.

```bash
chmod +x scripts/start-web.sh
./scripts/start-web.sh
```

Manual startup is also available:

```bash
python -m uvicorn backend.main:create_app --host 0.0.0.0 --port 8877 --factory --reload --reload-dir backend --reload-dir tradingagents
```

In a second terminal:

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5177 --strictPort
```

## Setup With Docker

The checked-in Docker assets now target the web app instead of the old CLI-only container.

### Windows PowerShell

```powershell
Copy-Item .env.example .env
docker compose up --build
```

### Linux

```bash
cp .env.example .env
docker compose up --build
```

When the containers are ready:

- Frontend: `http://localhost:5177`
- Backend: `http://localhost:8877`

Useful commands:

```bash
docker compose down
docker compose down -v
docker compose logs -f
```

Notes:

- Run data is persisted in the named Docker volume `tradingagents_data`.
- The container starts both the backend and the frontend dev server.
- If you use Ollama from a Dockerized backend, point the backend to a reachable host/service URL instead of plain container `localhost`. On Docker Desktop, `http://host.docker.internal:11434/v1` is the usual host-machine target.

## Environment Variable Reference

### Provider Credentials

Set the key for the provider you actually plan to use.

| Variable | Required when | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Using OpenAI models | Auth for native OpenAI requests |
| `GOOGLE_API_KEY` | Using Gemini models | Auth for Google Generative AI |
| `ANTHROPIC_API_KEY` | Using Claude models | Auth for Anthropic |
| `XAI_API_KEY` | Using Grok/xAI models | Auth for xAI |
| `DEEPSEEK_API_KEY` | Using DeepSeek models | Auth for DeepSeek |
| `DASHSCOPE_API_KEY` | Using Qwen models | Auth for Alibaba DashScope/Qwen |
| `ZHIPU_API_KEY` | Using GLM models | Auth for Zhipu/GLM |
| `OPENROUTER_API_KEY` | Using OpenRouter | Auth for OpenRouter |
| `AZURE_OPENAI_API_KEY` | Using Azure OpenAI | Azure key |
| `AZURE_OPENAI_ENDPOINT` | Using Azure OpenAI | Azure endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Using Azure OpenAI | Azure deployment name |
| `OPENAI_API_VERSION` | Optional for Azure OpenAI | Azure/OpenAI API version override |

### Optional Data Provider Credentials

| Variable | Required when | Purpose |
| --- | --- | --- |
| `ALPHA_VANTAGE_API_KEY` | Any stock data vendor is set to `alpha_vantage` | Enables Alpha Vantage stock data |
| `BYBIT_API_KEY` | Optional only | Private Bybit endpoints, if you extend beyond public market data |
| `BYBIT_API_SECRET` | Optional only | Private Bybit endpoints, if you extend beyond public market data |

### App Defaults and Runtime Controls

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRADINGAGENTS_LLM_PROVIDER` | `openai` | Default provider shown/resolved by the backend |
| `TRADINGAGENTS_DEEP_THINK_LLM` | `gpt-5.4` | Default long-form reasoning model |
| `TRADINGAGENTS_QUICK_THINK_LLM` | `gpt-5.4-mini` | Default short/fast model |
| `TRADINGAGENTS_BACKEND_URL` | unset | Optional OpenAI-compatible backend base URL |
| `TRADINGAGENTS_RESULTS_DIR` | `~/.tradingagents/logs` | Result/log output directory |
| `TRADINGAGENTS_CACHE_DIR` | `~/.tradingagents/cache` | Cache root, including checkpoint databases |
| `TRADINGAGENTS_MEMORY_LOG_PATH` | `~/.tradingagents/memory/trading_memory.md` | Memory log path |
| `TRADINGAGENTS_WEB_DB_PATH` | `~/.tradingagents/cache/web_runs.db` | SQLite file for web runs and scans |
| `WEB_CORS_ORIGIN` | `http://localhost:5177` | Allowed browser origin(s), comma-separated |
| `WEB_CSP_CONNECT_SRC` | `'self' ws://localhost:8877 wss://localhost:8877` | CSP `connect-src` override emitted by the backend |
| `LLM_MAX_CONCURRENT` | `0` | Maximum concurrent LLM calls; `0` means unlimited |
| `COINGECKO_MAX_CONCURRENT` | `2` | Maximum concurrent CoinGecko requests from the backend |

### Frontend-Specific Environment

The frontend client also supports:

| Variable | Where to define it | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | Frontend shell env or `frontend/.env.local` | Overrides relative `/api` calls when you are not using the local Vite proxy |

Important:

- `VITE_API_BASE_URL` is not read from the repo-root `.env` when you run `npm run dev` inside `frontend/`.
- The WebSocket client uses the same host as the loaded page. If your frontend and backend live on different origins in production, put them behind a reverse proxy or same-host gateway so `/ws/...` still resolves correctly.

## Configuration Resolution Order

Runtime config is resolved in this order:

1. `tradingagents/default_config.py`
2. Environment variables from `.env` / `.env.enterprise`
3. Persisted runtime overrides stored by the web app
4. Per-request overrides from the analysis/scanner UI

This means you can keep sensible defaults in env vars and still override provider, model, language, depth, and vendor choices from the UI when launching a run.

## Persistence and Storage

By default, TradingAgents writes data under `~/.tradingagents`:

| Path | Purpose |
| --- | --- |
| `~/.tradingagents/cache/web_runs.db` | SQLite database for analyses, report sections, and scans |
| `~/.tradingagents/cache/checkpoints/` | LangGraph checkpoint databases |
| `~/.tradingagents/memory/trading_memory.md` | Markdown memory log used by the portfolio manager |
| `~/.tradingagents/logs` | General results/log output |

Additional persistence:

- Browser `localStorage` stores UI preferences and watchlists
- Docker stores the backend state in the `tradingagents_data` named volume

## Web App Pages

| Route | Purpose |
| --- | --- |
| `/` | Home dashboard |
| `/analysis/new` | Start a new stock or crypto analysis |
| `/analysis/{run_id}` | Live analysis view with agent status, messages, stats, and reports |
| `/history` | Saved run history |
| `/scanner` | Batch market scanner for crypto symbols |
| `/config` | Resolved backend config and runtime overrides |
| `/memory` | Browse memory log entries |

## API Overview

### Core REST Endpoints

- `GET /api/v1/health`
- `POST /api/v1/analysis`
- `GET /api/v1/analysis`
- `GET /api/v1/analysis/{run_id}`
- `GET /api/v1/analysis/{run_id}/report`
- `GET /api/v1/analysis/{run_id}/snapshot`
- `POST /api/v1/analysis/{run_id}/cancel`
- `DELETE /api/v1/analysis/{run_id}`
- `DELETE /api/v1/analysis`
- `GET /api/v1/config`
- `PATCH /api/v1/config`
- `GET /api/v1/models/{provider}`
- `GET /api/v1/providers`
- `GET /api/v1/memory`
- `GET /api/v1/checkpoints`
- `DELETE /api/v1/checkpoints`
- `DELETE /api/v1/checkpoints/{ticker}`
- `GET /api/v1/symbols?asset_type=crypto`
- `POST /api/v1/scanner`
- `GET /api/v1/scanner`
- `GET /api/v1/scanner/{scan_id}`
- `POST /api/v1/scanner/{scan_id}/cancel`

### WebSocket

- `WS /ws/v1/analysis/{run_id}`

The WebSocket stream carries:

- progress events
- agent status updates
- message stream entries
- token/tool statistics
- report chunks

### CSRF / Request Header Requirement

The backend rejects mutating requests that do not include:

```http
X-Requested-With: XMLHttpRequest
```

The shipped frontend client already sends this header for you. Add it yourself if you call the API from custom scripts or tools.

## Model and Provider Notes

- Native provider selection is supported for OpenAI, Anthropic, Google, xAI, DeepSeek, Qwen, GLM, OpenRouter, Azure OpenAI, and Ollama.
- `TRADINGAGENTS_BACKEND_URL` lets you route model traffic through an OpenAI-compatible gateway.
- When a custom backend URL is set, the app can use a per-request API key from the UI instead of a provider env var.
- Stock data vendors are currently `yfinance` and `alpha_vantage`.
- Crypto analysis uses public market/fundamental sources such as Bybit and CoinGecko.

## Development Commands

### Backend / Python

```bash
python -m pytest
python main.py
tradingagents
```

### Frontend

```bash
cd frontend
npm test
npm run build
npm run lint
```

### Docker

```bash
docker compose up --build
docker compose down
```

## CI/CD

GitHub Actions is configured through [`.github/workflows/ci-cd.yml`](/C:/Users/ttbasil/Desktop/Projects/PublicProjects/TradingAgents/.github/workflows/ci-cd.yml).

What it does:

- Runs backend `pytest` on Python `3.12`
- Builds the frontend with Node.js `20`
- Deploys to the Oracle VM on pushes to `main` after CI passes
- Supports manual redeploys through `workflow_dispatch`

The deploy job runs [`scripts/deploy.sh`](/C:/Users/ttbasil/Desktop/Projects/PublicProjects/TradingAgents/scripts/deploy.sh) on the server. That script:

- installs backend dependencies into `.venv`
- runs `npm ci` and `npm run build` in `frontend/`
- syncs `frontend/dist/` into nginx's web root
- restarts the `tradingagents` systemd service
- reloads nginx
- verifies the public health endpoint

Repository secrets required by the deploy job:

| Secret | Example value | Purpose |
| --- | --- | --- |
| `ORACLE_HOST` | `144.24.128.103` | Oracle VM public IP or hostname |
| `ORACLE_USER` | `ubuntu` | SSH username |
| `ORACLE_PORT` | `22` | SSH port |
| `ORACLE_APP_DIR` | `/home/ubuntu/projects/TradingAgents` | Repo path on the server |
| `ORACLE_SSH_KEY` | multiline private key | Private key used by GitHub Actions to SSH into the VM |
| `PRODUCTION_HEALTHCHECK_URL` | `https://144.24.128.103.sslip.io/api/v1/health` | Post-deploy verification URL |

Deployment notes:

- The server repository should stay on the `main` branch and remain pullable with `git pull --ff-only origin main`.
- Keep production-only files such as `.env` untracked on the VM.
- If you rotate the server SSH key, update the `ORACLE_SSH_KEY` secret in GitHub.

## Legacy Interfaces

The repository still includes:

- the `tradingagents` CLI entrypoint
- the Python package for direct library use
- `main.py` as a simple script example

Those interfaces are still usable, but this README is written around the web app because that is now the primary scope of the project.

## Troubleshooting

### `API key not set` when starting a run

The backend validates provider auth before creating a run.

Fix one of these:

- enter the Provider API Key in the Model & Engine Presets section of the UI
- set the matching provider key in `.env`
- switch to a provider whose key is already configured
- provide a custom `backend_url` and API key through the UI

### Frontend loads but runs never start

Check:

- backend health at `http://localhost:8877/api/v1/health`
- that `WEB_CORS_ORIGIN` includes your frontend origin
- that you restarted the backend after changing `.env`

### Alpha Vantage errors

If any data vendor is switched to `alpha_vantage`, you must set `ALPHA_VANTAGE_API_KEY`. Otherwise keep the vendor on `yfinance`.

### Docker is running but the page is not ready yet

The first `docker compose up --build` has to install both Python and Node dependencies. Wait for the frontend to finish startup, or inspect:

```bash
docker compose logs -f
```

### Ollama from Docker

Inside Docker, `localhost` means the container itself. If Ollama is running on the host machine, point the backend to a host-reachable URL such as `http://host.docker.internal:11434/v1` on Docker Desktop.

## Reference

- Original paper: [TradingAgents](https://arxiv.org/abs/2412.20138)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
