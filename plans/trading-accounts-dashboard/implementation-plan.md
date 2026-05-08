# Trading Accounts Dashboard — Implementation Plan

## Phase 1: Backend Foundation (Database + Account CRUD)

### Task 1.1: Database Migration
**File:** `backend/persistence.py`
**Action:** Add migrations 7–8 to `_MIGRATIONS` list

Migration 7 — `trading_accounts` table:
```sql
CREATE TABLE IF NOT EXISTS trading_accounts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('demo', 'live')),
    api_key_masked TEXT NOT NULL,
    api_key_encrypted BYTEA NOT NULL,
    api_secret_encrypted BYTEA NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    deleted_at TEXT,
    bybit_uid TEXT,
    last_connected_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_active ON trading_accounts(is_active) WHERE deleted_at IS NULL;
```

Migration 8 — `closed_pnl_records` table:
```sql
CREATE TABLE IF NOT EXISTS closed_pnl_records (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES trading_accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    avg_entry_price NUMERIC NOT NULL,
    avg_exit_price NUMERIC NOT NULL,
    closed_pnl NUMERIC NOT NULL,
    leverage NUMERIC(10,2) NOT NULL DEFAULT 1,
    created_time BIGINT NOT NULL,
    bybit_order_id TEXT NOT NULL,
    UNIQUE(account_id, bybit_order_id)
);
CREATE INDEX IF NOT EXISTS idx_closed_pnl_account_time ON closed_pnl_records(account_id, created_time DESC);
```

### Task 1.2: Encryption Utility
**File:** `backend/crypto.py` (new)
**Action:** Create Fernet encryption wrapper

```python
# Functions:
def encrypt_value(plaintext: str) -> bytes  # Returns Fernet ciphertext
def decrypt_value(ciphertext: bytes) -> str  # Returns plaintext
def mask_api_key(api_key: str) -> str  # Returns "xxxx****xxxx" format
def validate_encryption_key() -> None  # Raises at startup if key missing/invalid
```

Environment variable: `ACCOUNTS_ENCRYPTION_KEY` (Fernet key)

### Task 1.3: Bybit API Client
**File:** `backend/services/bybit_client.py` (new)
**Action:** Create async Bybit V5 REST client

```python
class BybitClient:
    def __init__(self, api_key: str, api_secret: str, account_type: str):
        # Sets base_url based on account_type (demo vs live)
        
    async def get_wallet_balance(self) -> dict
    async def get_positions(self, symbol: str | None = None) -> list[dict]
    async def get_open_orders(self) -> list[dict]
    async def get_closed_pnl(self, start_time: int, end_time: int) -> list[dict]
    async def test_connection(self) -> dict  # Returns {success, uid, error}
    
    def _sign_request(self, timestamp: int, params_str: str) -> str
    async def _request(self, method: str, path: str, params: dict) -> dict
```

Key details:
- Base URLs: `https://api.bybit.com` (live), `https://api-demo.bybit.com` (demo)
- Auth headers: X-BAPI-API-KEY, X-BAPI-TIMESTAMP, X-BAPI-SIGN, X-BAPI-RECV-WINDOW=5000
- Signature: `HMAC-SHA256(secret, timestamp + api_key + recv_window + query_string_or_body)`
- HTTP client: `aiohttp.ClientSession` with 10s timeout
- Never log api_key or api_secret

### Task 1.4: Accounts Service
**File:** `backend/services/accounts_service.py` (new)
**Action:** Service layer for account CRUD + data fetching

```python
class AccountsService:
    def __init__(self, db: AnalysisDB):
        self._db = db
        self._cache: dict[str, tuple[float, Any]] = {}  # {key: (expires_at, data)}
    
    # CRUD
    def create_account(self, label, account_type, api_key, api_secret) -> dict
    def list_accounts(self) -> list[dict]
    def get_account(self, account_id: str) -> dict | None
    def update_account(self, account_id: str, label: str | None, is_active: bool | None) -> dict
    def rotate_credentials(self, account_id: str, api_key: str, api_secret: str) -> dict
    def delete_account(self, account_id: str) -> None
    
    # Data fetching (with caching)
    async def get_wallet(self, account_id: str) -> dict  # TTL 30s
    async def get_positions(self, account_id: str) -> list  # TTL 15s
    async def get_orders(self, account_id: str) -> list  # TTL 10s
    async def get_closed_pnl(self, account_id, start_date, end_date, page, limit) -> dict
    async def get_pnl_summary(self, account_id, start_date, end_date) -> dict
    async def test_connection(self, account_id: str) -> dict
    
    # Aggregation
    async def get_dashboard(self) -> list[dict]  # All accounts summary
    async def get_portfolio_summary(self) -> dict  # Cross-account totals
    
    # Cache management
    def _get_cached(self, key: str, ttl: float) -> Any | None
    def _set_cached(self, key: str, data: Any) -> None
    def _invalidate_cache(self, account_id: str) -> None
```

### Task 1.5: Accounts Router
**File:** `backend/routers/accounts.py` (new)
**Action:** FastAPI router with all account endpoints

```python
router = APIRouter(tags=["accounts"])

# CRUD
POST   /accounts                    → create_account
GET    /accounts                    → list_accounts
GET    /accounts/{account_id}       → get_account
PATCH  /accounts/{account_id}       → update_account
PATCH  /accounts/{account_id}/credentials → rotate_credentials
DELETE /accounts/{account_id}       → delete_account
POST   /accounts/{account_id}/test  → test_connection

# Portfolio data
GET /accounts/{account_id}/wallet       → get_wallet
GET /accounts/{account_id}/positions    → get_positions
GET /accounts/{account_id}/orders       → get_orders
GET /accounts/{account_id}/closed-pnl   → get_closed_pnl
GET /accounts/{account_id}/closed-pnl/summary → get_pnl_summary
```

**File:** `backend/routers/portfolio.py` (new)
```python
router = APIRouter(tags=["portfolio"])

GET /portfolio/dashboard   → get_dashboard (all accounts cards)
GET /portfolio/summary     → get_portfolio_summary (cross-account totals)
```

### Task 1.6: Register Routes + Startup Validation
**File:** `backend/main.py`
**Action:**
1. Import and include accounts_router at `/api/v1`
2. Import and include portfolio_router at `/api/v1`
3. In lifespan(), validate encryption key at startup
4. Store AccountsService on app.state

### Task 1.7: Schemas
**File:** `backend/schemas.py`
**Action:** Add Pydantic models:

```python
class AccountCreateRequest(BaseModel):
    label: str = Field(max_length=64)
    account_type: Literal['demo', 'live']
    api_key: str = Field(min_length=10, max_length=100)
    api_secret: str = Field(min_length=10, max_length=100)

class AccountUpdateRequest(BaseModel):
    label: str | None = Field(None, max_length=64)
    is_active: bool | None = None

class CredentialRotateRequest(BaseModel):
    api_key: str = Field(min_length=10, max_length=100)
    api_secret: str = Field(min_length=10, max_length=100)

class AccountResponse(BaseModel):
    id: str
    label: str
    account_type: str
    api_key_masked: str
    is_active: bool
    bybit_uid: str | None
    last_connected_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str

class WalletResponse(BaseModel):
    total_equity: str
    total_wallet_balance: str
    total_available_balance: str
    total_perp_upl: str
    coins: list[dict]
    fetched_at: str

class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: str
    avg_price: str
    mark_price: str
    unrealised_pnl: str
    leverage: str
    liq_price: str
    take_profit: str | None
    stop_loss: str | None

class ClosedPnlResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    limit: int

class PnlSummaryResponse(BaseModel):
    total_pnl: str
    win_count: int
    loss_count: int
    win_rate: float
    avg_win: str
    avg_loss: str

class DashboardAccountCard(BaseModel):
    id: str
    label: str
    account_type: str
    is_active: bool
    total_equity: str | None
    total_perp_upl: str | None
    positions_count: int
    last_connected_at: str | None
    last_error: str | None
    status: str  # 'active', 'stale', 'error', 'disabled'
```

### Task 1.8: Update .env.example
**File:** `.env.example`
**Action:** Add:
```
ACCOUNTS_ENCRYPTION_KEY=
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Phase 2: Frontend Foundation (Routes + Account Management UI)

### Task 2.1: API Client Extensions
**File:** `frontend/src/api/client.ts`
**Action:** Add account API functions:

```typescript
export const accountsApi = {
  list: () => request<AccountResponse[]>('/api/v1/accounts'),
  create: (data: AccountCreateRequest) => request<AccountResponse>('/api/v1/accounts', { method: 'POST', body: JSON.stringify(data), headers: {'Content-Type': 'application/json'} }),
  get: (id: string) => request<AccountResponse>(`/api/v1/accounts/${id}`),
  update: (id: string, data: AccountUpdateRequest) => request<AccountResponse>(`/api/v1/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(data), headers: {'Content-Type': 'application/json'} }),
  rotateCredentials: (id: string, data: CredentialRotateRequest) => request<AccountResponse>(`/api/v1/accounts/${id}/credentials`, { method: 'PATCH', body: JSON.stringify(data), headers: {'Content-Type': 'application/json'} }),
  delete: (id: string) => request<void>(`/api/v1/accounts/${id}`, { method: 'DELETE' }),
  testConnection: (id: string) => request<{success: boolean, uid?: string, error?: string}>(`/api/v1/accounts/${id}/test`, { method: 'POST' }),
  getWallet: (id: string) => request<WalletResponse>(`/api/v1/accounts/${id}/wallet`),
  getPositions: (id: string) => request<PositionResponse[]>(`/api/v1/accounts/${id}/positions`),
  getOrders: (id: string) => request<any[]>(`/api/v1/accounts/${id}/orders`),
  getClosedPnl: (id: string, params: {start_date: string, end_date: string, page?: number, limit?: number}) => request<ClosedPnlResponse>(`/api/v1/accounts/${id}/closed-pnl?${new URLSearchParams(params as any)}`),
  getPnlSummary: (id: string, params: {start_date: string, end_date: string}) => request<PnlSummaryResponse>(`/api/v1/accounts/${id}/closed-pnl/summary?${new URLSearchParams(params as any)}`),
  getDashboard: () => request<DashboardAccountCard[]>('/api/v1/portfolio/dashboard'),
  getPortfolioSummary: () => request<any>('/api/v1/portfolio/summary'),
};
```

### Task 2.2: Redux Accounts Slice
**File:** `frontend/src/store/accounts-slice.ts` (new)
**Action:** Create state management for accounts feature

### Task 2.3: Routes Registration
**File:** `frontend/src/routes/route-tree.tsx`
**Action:** Add accountsRoute and accountDetailRoute

### Task 2.4: AccountsDashboard Page
**File:** `frontend/src/components/accounts/AccountsDashboard.tsx` (new)
**Action:** Main page with:
- Aggregate summary card
- Demo/Live filter toggle
- Account cards grid
- "Add Account" button
- Empty state when no accounts

### Task 2.5: AccountCard Component
**File:** `frontend/src/components/accounts/AccountCard.tsx` (new)
**Action:** Per-account summary card showing label, type badge, equity, PnL, positions count, status, refresh button

### Task 2.6: AddAccountDialog
**File:** `frontend/src/components/accounts/AddAccountDialog.tsx` (new)
**Action:** Multi-step dialog:
1. Label + account type selection
2. API key (text with reveal) + API secret (password with toggle)
3. Test connection (shows spinner → success/fail)
4. Confirm and save

### Task 2.7: Navigation Link
**File:** `frontend/src/components/layout/RootLayout.tsx`
**Action:** Add "Accounts" nav link to sidebar

---

## Phase 3: Portfolio Data Display

### Task 3.1: AccountDetailView Page
**File:** `frontend/src/components/accounts/AccountDetailView.tsx` (new)
**Action:** Tabbed view (wallet/positions/orders/pnl) with URL search param for active tab

### Task 3.2: WalletPanel
**File:** `frontend/src/components/accounts/WalletPanel.tsx` (new)
**Action:** Display equity, balance, available, UPL, per-coin breakdown with color-coded health

### Task 3.3: PositionsTable
**File:** `frontend/src/components/accounts/PositionsTable.tsx` (new)
**Action:** Sortable table with liquidation warnings (icon + color + aria-label)

### Task 3.4: OrdersTable
**File:** `frontend/src/components/accounts/OrdersTable.tsx` (new)
**Action:** Open orders list with type badges

### Task 3.5: PnLPanel
**File:** `frontend/src/components/accounts/PnLPanel.tsx` (new)
**Action:** Period presets (today/7d/30d) + custom date picker + summary stats + breakdown

### Task 3.6: Polling Hook
**File:** `frontend/src/hooks/useAccountPolling.ts` (new)
**Action:** Manages auto-refresh with cleanup, visibility API pause, AbortController

---

## Phase 4: Testing

### Task 4.1: Backend Unit Tests
**Files:**
- `tests/backend/test_crypto.py` — encryption/decryption/masking
- `tests/backend/test_bybit_client.py` — mocked HTTP responses
- `tests/backend/test_accounts_service.py` — CRUD + caching
- `tests/backend/test_accounts_router.py` — endpoint integration tests

### Task 4.2: Frontend Tests
**Files:**
- `frontend/src/components/accounts/__tests__/AccountsDashboard.test.tsx`
- `frontend/src/components/accounts/__tests__/AddAccountDialog.test.tsx`
- `frontend/src/store/__tests__/accounts-slice.test.ts`

---

## Phase 5: Integration & Polish

### Task 5.1: End-to-end smoke test with demo account
### Task 5.2: Error state testing (invalid keys, network failures)
### Task 5.3: PnL pagination testing (>7 day ranges)
### Task 5.4: Documentation update to .env.example

---

## Errata — Review Fixes

### Fix 1: Task ordering (Critical 1)
Implementation order within Phase 1: 1.1 → 1.2 → 1.7 → 1.3 → 1.4 → 1.5 → 1.6
(Schemas before Router)

### Fix 2: Rate Limiting in BybitClient (Critical 2)
Task 1.3 BybitClient MUST include:
- `asyncio.Semaphore(10)` per-account (10 req/s)
- Global request counter with sliding window (120/min)
- On rate limit error (retCode 10006): exponential backoff retry (max 3 attempts)

### Fix 3: Global Exception Handler (High 3)
Add to Task 1.6 (main.py):
```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "code": "INTERNAL_ERROR"})
```

### Fix 4: create_account is async (High 4)
Task 1.4: `create_account` is `async def`. Flow:
1. Encrypt credentials
2. Call Bybit test_connection with plaintext creds
3. On success: save to DB, return account
4. On failure: return validation error (never save)

### Fix 5: Manual Refresh Throttle (High 5)
Task 3.6 `useAccountPolling` hook includes:
- `lastManualRefresh: Record<string, number>` in state
- `manualRefresh(accountId)` checks if 10s elapsed since last, rejects otherwise
- Button disabled with countdown when within throttle window

---

## Implementation Order

1. Phase 1 (backend): 1.1 → 1.2 → 1.7 → 1.3 → 1.4 → 1.5 → 1.6
2. Phase 2 (frontend foundation) — wires up routes and account CRUD UI
3. Phase 3 (data display) — connects portfolio data to UI
4. Phase 4 (tests) — comprehensive coverage
5. Phase 5 (integration) — end-to-end validation
