# Trading Accounts Dashboard — Specification

## 1. Overview

### 1.1 Purpose
Provide a unified dashboard for users to view all their Bybit crypto trading accounts (demo and live), showing balances, equity, open positions, running trades, PnL analysis (today, 7d, 30d, custom range), and account health metrics.

### 1.2 Scope
- **Exchange**: Bybit only (V5 API)
- **Asset type**: Crypto (linear USDT-settled perpetual contracts)
- **Account types**: Demo, Live, Sub-accounts
- **Access pattern**: Read-only portfolio monitoring (no trade execution from dashboard)
- **User model**: Single-user application (no multi-tenant auth). The app has no user authentication — all accounts belong to the single operator. This is consistent with the existing architecture (no user_id on analysis_runs or scans tables).

### 1.3 Key User Stories
1. As a trader, I want to see all my Bybit accounts in one place so I can monitor my total exposure.
2. As a trader, I want to add accounts with API keys so the system can fetch my data.
3. As a trader, I want to see my PnL across different time periods to evaluate performance.
4. As a trader, I want to see all open positions with liquidation warnings to manage risk.

---

## 2. Functional Requirements

### 2.1 Account Management (CRUD)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-001 | Users can add a Bybit account by providing: label, account_type (demo/live), api_key, api_secret | Must |
| FR-002 | System validates API credentials against Bybit before saving (calls /v5/account/wallet-balance) | Must |
| FR-003 | Users can update account label without re-entering credentials | Must |
| FR-004 | Users can rotate (update) API key/secret with re-validation | Must |
| FR-005 | Users can soft-delete an account (sets deleted_at, excluded from dashboard) | Must |
| FR-006 | API secret is encrypted at rest using Fernet (symmetric encryption) with a server-side key | Must |
| FR-007 | API responses never expose the full api_secret; api_key shown masked (first 4 + last 4 chars) | Must |
| FR-008 | Multiple accounts per user supported (no hard limit) | Must |
| FR-009 | Sub-accounts displayed nested under parent with "Sub" badge | Should |

### 2.2 Wallet & Balance Display

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-010 | Display per-account: totalEquity (USD), totalWalletBalance, totalAvailableBalance, totalPerpUPL | Must |
| FR-011 | Show per-coin breakdown: coin, walletBalance, equity, unrealisedPnl, usdValue | Must |
| FR-012 | Color-code available balance: green (>50%), amber (20-50%), red (<20% of equity) | Should |
| FR-013 | Show margin usage: initial margin rate, maintenance margin rate | Should |
| FR-014 | Display account-level aggregate across all active accounts (total equity, total PnL) | Must |
| FR-015 | Show last-fetched timestamp per account with staleness indicator | Must |

### 2.3 Open Positions

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-016 | List all open positions with: symbol, side, size, avgPrice, markPrice, unrealisedPnl, leverage, liqPrice, TP/SL | Must |
| FR-017 | Sortable columns in positions table | Should |
| FR-018 | Liquidation warning: amber when mark price within 15% of liq price, red within 5% | Must |
| FR-019 | Show distance-to-liquidation as absolute $ and % move required | Should |
| FR-020 | Display effective leverage (notional / equity) alongside set leverage | Should |

### 2.4 PnL Tracking

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-021 | Show realized PnL for: today (UTC), 7d rolling, 30d rolling | Must |
| FR-022 | Custom date-range PnL picker (calendar UI) | Must |
| FR-023 | Per-symbol PnL breakdown for selected period | Should |
| FR-024 | Win rate calculation: profitable trades / total trades for period | Should |
| FR-025 | Backend paginates Bybit closed-pnl API (7-day max) transparently for longer ranges | Must |
| FR-026 | Cache closed-pnl records in PostgreSQL to avoid re-fetching historical data | Must |
| FR-027 | PnL summary endpoint: total_pnl, win_count, loss_count, win_rate, avg_win, avg_loss | Should |

### 2.5 Open Orders

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-028 | List all open orders: orderId, symbol, side, orderType, qty, price, status, createdTime | Must |
| FR-029 | Show conditional orders (TP/SL/trailing) separately from limit orders | Should |
| FR-030 | Display total notional of pending orders per account | Should |

### 2.6 Dashboard UX

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-031 | Account cards on main dashboard showing: label, type badge, equity, 24h PnL, positions count, status | Must |
| FR-032 | Demo/Live filter toggle in toolbar | Must |
| FR-033 | Manual refresh button per account (throttled to 1 per 10 seconds) | Must |
| FR-034 | Auto-refresh configurable: 30s, 60s (default), 5min, manual-only | Should |
| FR-035 | Skeleton loaders during data fetch (no layout shift) | Should |
| FR-036 | Error state per account card (inline error + last successful timestamp + retry) | Must |
| FR-037 | Empty state when no accounts with "Connect your first account" CTA | Must |
| FR-038 | Account drill-down view showing full wallet, positions, orders, PnL details | Must |

---

## 3. Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-001 | API secrets encrypted with Fernet using env-sourced ACCOUNTS_ENCRYPTION_KEY | Must |
| NFR-002 | All Bybit calls use HMAC-SHA256 signed requests per V5 spec | Must |
| NFR-003 | Wallet data cached in-process with 30s TTL | Must |
| NFR-004 | Position data cached with 15s TTL | Must |
| NFR-005 | Bybit rate limit: max 10 req/s per account, 120 req/min global | Must |
| NFR-006 | Single-flight coalescing: concurrent requests for same account+endpoint share one Bybit call | Should |
| NFR-007 | Wallet endpoint responds <500ms (cache hit), <3s (cache miss) at p95 | Should |
| NFR-008 | Closed-pnl max query range: 90 days per request | Must |
| NFR-009 | All exceptions return structured JSON error (never stack traces to client) | Must |
| NFR-010 | Frontend dashboard interactive within 2s on initial load | Should |
| NFR-011 | Responsive layout: 375px mobile to 2560px desktop | Should |

---

## 4. API Design

### 4.1 Account Management

```
POST   /api/v1/accounts                 — Create account
GET    /api/v1/accounts                 — List all accounts (masked secrets)
GET    /api/v1/accounts/{id}            — Get single account
PATCH  /api/v1/accounts/{id}            — Update label/active status
PATCH  /api/v1/accounts/{id}/credentials — Rotate API key/secret
DELETE /api/v1/accounts/{id}            — Soft-delete
POST   /api/v1/accounts/{id}/test       — Test connection
```

### 4.2 Portfolio Data

```
GET /api/v1/accounts/{id}/wallet        — Wallet balance
GET /api/v1/accounts/{id}/positions     — Open positions
GET /api/v1/accounts/{id}/orders        — Open orders
GET /api/v1/accounts/{id}/closed-pnl?start_date=&end_date= — Closed PnL
GET /api/v1/accounts/{id}/closed-pnl/summary?start_date=&end_date= — PnL aggregates
```

### 4.3 Aggregation

```
GET /api/v1/accounts/dashboard          — All accounts summary (cards data)
GET /api/v1/accounts/aggregate/wallet   — Cross-account totals
```

---

## 5. Data Model

### 5.1 Database Tables

#### `trading_accounts`
```sql
CREATE TABLE trading_accounts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('demo', 'live')),
    api_key_masked TEXT NOT NULL,
    api_key_encrypted BYTEA NOT NULL,
    api_secret_encrypted BYTEA NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMPTZ,
    bybit_uid TEXT,
    last_connected_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### `closed_pnl_records`
```sql
CREATE TABLE closed_pnl_records (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    avg_entry_price NUMERIC NOT NULL,
    avg_exit_price NUMERIC NOT NULL,
    closed_pnl NUMERIC NOT NULL,
    leverage INTEGER NOT NULL DEFAULT 1,
    created_time BIGINT NOT NULL,
    bybit_order_id TEXT NOT NULL,
    UNIQUE(account_id, bybit_order_id)
);
CREATE INDEX idx_closed_pnl_account_time ON closed_pnl_records(account_id, created_time DESC);
```

---

## 6. Bybit API Integration

### 6.1 Endpoints Used

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| GET /v5/account/wallet-balance?accountType=UNIFIED | Wallet balances | 120/min |
| GET /v5/position/list?category=linear&settleCoin=USDT | Open positions | 120/min |
| GET /v5/order/realtime?category=linear | Open orders | 120/min |
| GET /v5/position/closed-pnl?category=linear | Historical PnL | 120/min |

### 6.2 Authentication
- HMAC-SHA256 signature: `sign = HMAC(secret, timestamp + api_key + recv_window + params_string)`
- Headers: X-BAPI-API-KEY, X-BAPI-TIMESTAMP, X-BAPI-SIGN, X-BAPI-RECV-WINDOW

### 6.3 Demo vs Live Routing
- Live: `https://api.bybit.com`
- Demo: `https://api-demo.bybit.com`
- Testnet: `https://api-testnet.bybit.com`

---

## 7. Frontend Design

### 7.1 New Route
- `/accounts` — Trading Accounts Dashboard (main page)
- `/accounts/{id}` — Account Detail/Drill-down view

### 7.2 Components
- `AccountsDashboard` — Main page with aggregate summary + account cards grid
- `AccountCard` — Summary card per account
- `AddAccountDialog` — Multi-step wizard for adding accounts
- `AccountDetailView` — Full detail with tabs (Wallet, Positions, Orders, PnL)
- `PnLPanel` — Period selector + PnL breakdown + chart
- `PositionsTable` — Sortable table with liquidation warnings

### 7.3 State Management
- New Redux slice: `accounts-slice.ts` for account list, selected account, polling state

---

## 8. Acceptance Criteria

1. User can add a demo and live Bybit account with API keys
2. Dashboard shows all accounts with real-time equity and PnL
3. Open positions visible with liquidation distance warnings
4. PnL queryable for today, 7d, 30d, and custom date range
5. API secrets never exposed in any response or log
6. Invalid API keys show clear error message
7. Dashboard loads within 2 seconds with cached data

---

## 9. Design Decisions (Review Findings Addressed)

### 9.1 Single-User Model (Security F3/F4)
This app is single-user (no multi-tenant auth exists). No user_id column needed. All accounts are owned by the single operator. IDOR is N/A.

### 9.2 Route Collision Fix (Backend F1)
Use prefix `/api/v1/accounts` for CRUD. Move aggregate endpoints to separate paths:
- `GET /api/v1/portfolio/dashboard` — aggregate cards
- `GET /api/v1/portfolio/summary` — cross-account totals
This eliminates `{id}` collision with `dashboard`/`aggregate`.

### 9.3 CSRF Header (Backend F2)
All mutating requests require `X-Requested-With: XMLHttpRequest` header (enforced by existing CSRFMiddleware). Frontend API client already sets this by default.

### 9.4 Encryption Strategy (Security F1/F5/F10)
- Use Fernet with a single server key (`ACCOUNTS_ENCRYPTION_KEY` env var)
- Store `key_version INTEGER DEFAULT 1` column for future rotation
- Decrypt at request time, use for signing, do not cache plaintext
- Validate key at startup in lifespan()

### 9.5 Log Sanitization (Security F2/F8)
- Never log api_key or api_secret values
- `last_error` column: max 512 chars, sanitized (strip anything matching key patterns)
- Bybit error messages scrubbed before storage

### 9.6 Rate Limiting (Security F7)
- Account creation/credential rotation: max 5 per minute (enforced in-process)

### 9.7 Timestamp Convention (Backend F5)
Use TEXT with ISO8601 format (matching existing pattern in persistence.py). No TIMESTAMPTZ.

### 9.8 Leverage Column (Backend F4)
Use `NUMERIC(10,2)` not INTEGER for leverage (Bybit returns decimal values).

### 9.9 Caching Strategy (Backend F7)
Single-worker deployment (documented constraint). In-process dict with TTL. Cache invalidation on soft-delete.

### 9.10 Closed-PnL Pagination (Backend F8)
Add `page` and `limit` query params (default limit=100, max=1000). Return `{items, total, page, limit}` envelope.

### 9.11 Frontend Routes (Frontend F1)
Add `/accounts` and `/accounts/$accountId` to route-tree.tsx. Add nav link.

### 9.12 Redux State Shape (Frontend F2)
```ts
interface AccountsState {
  accounts: TradingAccount[];
  status: 'idle' | 'loading' | 'success' | 'error';
  walletData: Record<accountId, { status, data, error, lastFetchedAt }>;
  positionsData: Record<accountId, { status, data, error, lastFetchedAt }>;
  ordersData: Record<accountId, { status, data, error, lastFetchedAt }>;
  pnlData: Record<accountId, { status, data, error, lastFetchedAt }>;
  pollingIntervalMs: number;
  filterType: 'all' | 'demo' | 'live';
  selectedAccountId: string | null;
}
```

### 9.13 Secret Input UX (Frontend F3)
- `api_key`: text input with reveal toggle
- `api_secret`: `type="password"` with show/hide toggle
- Test connection step before save (shows success/fail/retry)
- On edit: masked display, "Leave empty to keep current" placeholder

### 9.14 Tab State in URL (Frontend F4)
Account detail route uses search param `?tab=wallet|positions|orders|pnl` via TanStack Router `validateSearch`.

### 9.15 Polling Lifecycle (Frontend F7)
- `useAccountPolling` hook manages setInterval + AbortController cleanup
- Pause on `document.visibilityState === "hidden"`
- Per-account in-flight abort on unmount or new fetch

### 9.16 PnL Date Validation (Frontend F8)
- Disable future dates in calendar
- Clamp end_date to start_date + 90 days
- Show "No closed trades" empty state for zero results

### 9.17 Accessibility (Frontend F6)
- Liquidation warnings: icon + color + aria-label (not color alone)
- Balance tiers: text label "Healthy"/"Low"/"Critical" alongside color

### 9.18 updated_at Column (Backend F9)
Explicitly set `updated_at` in every UPDATE SQL statement (no trigger — matches existing pattern).
