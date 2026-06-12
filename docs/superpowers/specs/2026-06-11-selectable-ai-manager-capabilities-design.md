# Selectable AI Manager Capabilities (Per-Scan) — Design Spec

**Date:** 2026-06-11
**Status:** Approved — ready for implementation plan
**Author:** Brainstorming session (TradingAgents)

---

## 1. Problem Statement

The auto-trader feature (present in both the **Market Scan** form and the
**Scheduled Market Scan** form) exposes an account-specific **"AI Position Manager"**
toggle. This toggle is **binary**: enabling it turns on the *entire* AI Manager
capability suite at once. There is no way for a user to choose which individual
capabilities run and which stay off.

The AI Manager is a rich subsystem with many independently-useful capabilities
(multi-timeframe analysis, order-book monitoring, sweep/stop-hunt defense,
correlation/clustering, regime enhancement, event-driven evaluation, trailing
TP/SL, emergency close). Users want **granular selection**: when the AI Manager is
enabled, they should be able to pick exactly which capabilities are active.

**Default behavior:** when the AI Manager is enabled and the user has not
customized the capabilities, **all capabilities are enabled** (the literal
"enable everything" model).

---

## 2. Goals & Non-Goals

### Goals
- Let each scan independently choose which of the 8 AI Manager capabilities are on.
- Preserve the current one-switch UX as the entry point; capabilities appear only
  when the AI Manager switch is on.
- Default to **all 8 capabilities ON** when the AI Manager is enabled and the user
  has not touched the capability toggles.
- Apply per-scan choices as a **one-time override** layered onto the account's
  AI Manager config — **without** rewriting the account's saved configuration.
- Full backward-compatibility: existing saved scans and scheduled jobs (which have
  no capability field) behave exactly as they do today.

### Non-Goals
- **Backtesting** integration (AI Manager is explicitly deferred in backtests per
  project context).
- **Account-level** capability-selection UI (decided: scan-form only).
- **Persisting** per-scan choices back into the account's `AIManagerConfig`.
- Changing the AI Manager's internal decision logic or adding new capabilities.

---

## 3. Locked Decisions

These were resolved during brainstorming and are fixed for this design:

| # | Decision | Choice |
|---|----------|--------|
| D1 | **Where** the selection lives | **Scan form, per-scan** — stored in `AutoTradeConfig`, the single source of truth the scan already uses. Each scan can choose a different set. |
| D2 | **Which** capabilities are exposed | **All 8 toggleable flags**: Multi-Timeframe, Order Book, Sweep Defense, Correlation, Regime Enhancement, Event-Driven Evaluation, Trailing TP/SL, Emergency Close. |
| D3 | **Default** state when AI Manager on & untouched | **All 8 ON literally** — including Trailing TP/SL (which normally defaults off at the account level). Clean "enable everything" mental model. |
| D4 | **Precedence** vs account config | **Override, do NOT persist.** Per-scan choices win for that scan's enablement, layered on top of the account config, but never rewrite the account's saved config. A scan with no explicit choices keeps today's behavior. |
| D5 | **Data model** shape | **Nested object** (`AIManagerCapabilityToggles`) — one optional field on `AutoTradeConfig`. `null` = "didn't choose"; non-null = explicit override. Mirrors the existing `strategy_cohort` tri-state convention. |

### The 8 capabilities & their AIManagerConfig flag mapping

| Toggle key | `AIManagerConfig` flag | Account default | Per-scan default (D3) |
|------------|------------------------|-----------------|------------------------|
| `mtf`             | `mtf_enabled`            | `True`  | `True` |
| `orderbook`       | `orderbook_enabled`      | `True`  | `True` |
| `sweep_defense`   | `sweep_defense_enabled`  | `True`  | `True` |
| `correlation`     | `correlation_enabled`    | `True`  | `True` |
| `regime_enhanced` | `regime_enhanced`        | `True`  | `True` |
| `event_driven`    | `event_driven_enabled`   | `True`  | `True` |
| `trailing`        | `trailing_enabled`       | `False` | **`True`** |
| `emergency_close` | `emergency_close_enabled`| `True`  | `True` |

---

## 4. Architecture & Data Flow

```
Scan form (ScannerPage / ScheduledScansPage)
   └─ AutoTradeSection  ──►  AutoTradeConfig.ai_manager_capabilities  (8 bools | null)
                                       │
                          (saved in scan request / scheduled job)
                                       ▼
   scan runs ──► AutoTradeExecutor (auto_trade_service.py, ~L1745)
                   │  ai_manager_enabled == true?  AND strategy_kind != mean_reversion
                   │  load account AIManagerConfig (existing or AIManagerConfig() default)
                   │  IF ai_manager_capabilities is not null:
                   │       apply_capability_overrides(config, toggles)  # maps 8 flags
                   │  config.auto_enabled = True
                   ▼
            ai_manager_service.enable(account_id, config, persist=<bool>)
                   │  spawn/refresh FSM task with (possibly overridden) config
                   └─ IF persist=False: account's stored config row is NOT rewritten
```

**Key principle — two layers stay separate:**
- `AutoTradeConfig` (per-scan) carries the *choice*.
- `AIManagerConfig` (account) remains the long-term default.
- The override lives only in the running FSM task for that scan's lifetime; the
  persisted account config row is left intact when `persist=False`.

---

## 5. Component Design

### 5.1 Backend schema — `backend/schemas/__init__.py`

New sub-model, declared just above `AutoTradeConfig`:

```python
class AIManagerCapabilityToggles(BaseModel):
    """Per-scan selection of which AI Manager capabilities run.

    Presence of this object (non-null on AutoTradeConfig) means the user made an
    explicit choice for this scan; absence (null) means "didn't choose" and the
    account's saved AIManagerConfig is used unchanged (legacy behavior).
    Every flag defaults True so the literal "enable all" model holds (D3).
    """
    model_config = ConfigDict(extra="forbid")

    mtf: bool = True
    orderbook: bool = True
    sweep_defense: bool = True
    correlation: bool = True
    regime_enhanced: bool = True
    event_driven: bool = True
    trailing: bool = True
    emergency_close: bool = True
```

New field on `AutoTradeConfig` (placed near `ai_manager_enabled` / `ai_pause_cycles`):

```python
    ai_manager_capabilities: Optional[AIManagerCapabilityToggles] = None
```

- `None` → "didn't choose" → today's behavior preserved (backward-compat with all
  saved scans and scheduled jobs).
- non-null → explicit per-scan override.
- `extra="forbid"` rejects unknown capability keys (matches the codebase's strict
  validation norm; `AutoTradeConfig` itself already uses `extra="forbid"`).

**Validator (tolerant, non-rejecting):** capabilities set while
`ai_manager_enabled=False` are *ignored*, not rejected — a stale capability object
must never block an otherwise-valid scan. (No `model_validator` that raises; the
override is simply not consulted unless `ai_manager_enabled` is true. A code comment
documents this so a future reader doesn't add a spurious cross-field check.)

### 5.2 Capability mapping helper

A pure function maps the 8 toggle keys onto the real `AIManagerConfig` flag names
(table in §3). Location: alongside the auto-trade enablement code (e.g. a module-level
helper in `auto_trade_service.py`, or a small `ai_manager_capability_map` helper module
if the plan prefers isolation).

```python
def apply_capability_overrides(
    config: AIManagerConfig,
    toggles: "AIManagerCapabilityToggles | dict | None",
) -> AIManagerConfig:
    """Return a copy of `config` with the 8 capability flags overridden by `toggles`.

    No-op when toggles is None. Pure (no I/O) so it is unit-testable in isolation.
    """
```

- Returns a **copy** (`config.model_copy(update=...)`) — does not mutate the input.
- `None` toggles → returns config unchanged (defensive; callers already gate on null).
- Maps exactly the 8 known keys; any flag not in the map is untouched.

### 5.3 Non-persisting enablement path — `ai_account_manager_service.py`

`enable()` currently **always** writes the passed config to the DB via
`sync_config_columns(...)` (both in the alive-task branch and the respawn branch).
To honor D4 ("override, don't persist"), add a parameter:

```python
async def enable(self, account_id: str, config: AIManagerConfig, *, persist: bool = True) -> None:
```

- `persist=True` (default) → **unchanged** behavior for every existing caller
  (manual enable, account config panel, etc.).
- `persist=False` → spawn/reload the FSM task with `config`, but **skip**
  `sync_config_columns(...)` so the account's stored config row is untouched.
  - Alive-task branch: still call `existing_task.reload_config(config)` (in-memory),
    just skip the DB write.
  - Respawn branch: still `upsert_state(enabled=True, ...)` and `_spawn_task(...)`,
    skip the config-column write.

**Caller (`auto_trade_service.py`, ~L1745–1767):** when a per-scan override is
present, build the overridden config and call `enable(..., persist=False)`. When no
override is present (`ai_manager_capabilities is None`), preserve the **exact**
current code path (load existing config, `persist` defaults True) for zero behavior
change.

> **Note on the once-per-scan guard.** `auto_trade_service` only enables the AI
> Manager the first time it sees the account in a scan (`account_id not in
> self._ai_manager_enabled_accounts`). The override is applied at that first
> enablement. This is unchanged structurally — the override slots into the existing
> branch; the guard still prevents repeated enable calls within one scan.

### 5.4 Frontend type — `frontend/src/api/client.ts`

Add a matching interface and field on the `AutoTradeConfig` TS interface:

```typescript
export interface AIManagerCapabilities {
  mtf: boolean;
  orderbook: boolean;
  sweep_defense: boolean;
  correlation: boolean;
  regime_enhanced: boolean;
  event_driven: boolean;
  trailing: boolean;
  emergency_close: boolean;
}

// on AutoTradeConfig:
  ai_manager_capabilities?: AIManagerCapabilities | null;
```

### 5.5 Frontend UI — `frontend/src/components/scanner/AutoTradeSection.tsx`

- Keep the existing **"AI Position Manager"** `ToggleRow` (unchanged copy/badge).
- When `config.ai_manager_enabled` is true, render a **nested capability panel**
  below it: 8 `ToggleRow`s (reusing the existing component), each with a title and a
  one-line description. Grouped in a visually-nested container (indented / inset
  surface) to signal they belong to the AI Manager.
- **Capability metadata** (title + description) defined as a local constant array of
  `{ key, title, description }` so the 8 rows render from a single map — easy to
  maintain and keeps ordering stable.
- **Default seeding (D3):** when the user flips AI Manager **on** and
  `ai_manager_capabilities` is currently `null`, set it to all-8-`true` in the same
  `onChange`. When AI Manager is flipped **off**, **clear to `null`** so the saved
  scan stays clean and legacy-equivalent (the backend ignores it when disabled
  regardless).
- A small **"Reset to all on"** affordance (text button) restores all-8-`true`.
- `DEFAULT_CONFIG` (top of file) adds `ai_manager_capabilities: null`.
- **Both forms covered automatically:** `ScannerPage` and `ScheduledScansPage` both
  render the shared `AutoTradeSection`, so no per-page edits are required.

#### Proposed capability copy

| key | Title | Description |
|-----|-------|-------------|
| `mtf` | Multi-Timeframe Analysis | Aligns trend across 5m/15m/1h/4h before acting on a position. |
| `orderbook` | Order Book Monitoring | Reads live bid/ask imbalance and depth around the position. |
| `sweep_defense` | Sweep / Stop-Hunt Defense | Avoids closing into liquidity sweeps and stop-hunts. |
| `correlation` | Correlation & Clustering | Tracks portfolio heat and correlated-position clusters. |
| `regime_enhanced` | Regime Enhancement | Adapts decisions to the detected market regime. |
| `event_driven` | Event-Driven Evaluation | Reacts to live triggers (price moves, drawdown) plus a safety-net timer. |
| `trailing` | Trailing TP/SL | Dynamically trails take-profit / stop-loss on profitable positions. |
| `emergency_close` | Emergency Close | Deterministic fast-path crash protection on sharp adverse moves. |

---

## 6. Edge Cases

| # | Case | Handling |
|---|------|----------|
| E1 | **Legacy saved scan / scheduled job** with no `ai_manager_capabilities` field | Deserializes to `None` → override not consulted → today's exact behavior (load account config untouched). |
| E2 | **AI Manager OFF** but capabilities object populated | Override ignored — capabilities are only consulted inside the `ai_manager_enabled` enable branch. UI clears to `null` on toggle-off as a belt-and-suspenders cleanup. |
| E3 | **All 8 toggled OFF** while AI Manager ON | Valid intentional state. AI Manager still runs its core HOLD/close decisioning; every *optional* capability is disabled. `emergency_close=False` is allowed (user's explicit choice) — documented as a deliberate risk in the UI copy. |
| E4 | **Account already has a live AI Manager task** from a prior scan | `enable()`'s alive-task branch reloads the overridden config in-memory (`reload_config`) without the DB write when `persist=False`. |
| E5 | **Mean-reversion positions/accounts** | Already excluded from AI management by the existing `strategy_kind != "mean_reversion"` guard — unaffected by this change. |
| E6 | **Unknown capability key** sent by a malformed client | `extra="forbid"` on `AIManagerCapabilityToggles` → 422 validation error, consistent with the rest of `AutoTradeConfig`. |
| E7 | **Partial object** (some keys omitted) | Omitted keys fall back to their `True` defaults — equivalent to "on". This is intended; the UI always sends the full object, but the API tolerates partials. |
| E8 | **`persist=False` regression risk** for existing callers | Default is `persist=True`; every current call site is unchanged. Only the new auto-trade override path passes `persist=False`. |

---

## 7. Testing Strategy (TDD)

Tests are written **before** implementation for each unit.

### Backend — unit
- `AIManagerCapabilityToggles`: accepts empty (`{}` → all True), full, and partial
  objects; rejects unknown keys (`extra="forbid"`).
- `AutoTradeConfig.ai_manager_capabilities`: accepts `None`, accepts a full object;
  round-trips through `model_dump()`/re-parse.
- `apply_capability_overrides`: maps all 8 toggle keys to the correct
  `AIManagerConfig` flags; returns a copy (input unmutated); `None` → unchanged;
  verifies `trailing=True` override flips the account default (`trailing_enabled`
  False → True).

### Backend — integration (`auto_trade_service`)
- Override present → `enable()` called with `persist=False` and a config whose 8
  flags match the toggles.
- Override present → account's stored config row is **not** rewritten (assert
  `sync_config_columns` not called / DB row unchanged).
- Override `None` → legacy path: existing account config loaded, `enable()` called
  with `persist=True` (default), behavior identical to pre-change.
- `enable(persist=False)` on an **alive** task reloads config in-memory without DB
  write; on a **dead/absent** task respawns without the config-column write.
- MR strategy_kind → AI Manager enable path still skipped (existing guard intact).

### Frontend
- Flipping AI Manager **on** seeds `ai_manager_capabilities` to all-8-`true`.
- Flipping AI Manager **off** clears it to `null`.
- Toggling an individual capability updates only that key.
- "Reset to all on" restores all-8-`true`.
- Round-trips through save/load: localStorage (market scan) and scheduled-job
  persistence keep the object intact.
- `npx tsc --noEmit` passes (type parity with backend).

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Disabling `emergency_close` removes crash protection | UI description states this explicitly; it is an opt-in user choice, default ON. |
| Behavior drift for existing scans | `None` sentinel + `persist=True` default guarantee byte-for-byte legacy behavior; covered by integration tests E1/E8. |
| Two configs diverging confusingly (scan vs account) | Override is non-persisting and scan-scoped by design (D4); account panel remains the durable default. |
| Large `AutoTradeConfig` model growth | Single nested field (D5) instead of 8 flat fields keeps the model readable. |

---

## 9. Files Touched (summary)

| File | Change |
|------|--------|
| `backend/schemas/__init__.py` | Add `AIManagerCapabilityToggles` model + `ai_manager_capabilities` field on `AutoTradeConfig`. |
| `backend/services/auto_trade_service.py` | Apply override + call `enable(persist=False)` in the AI-Manager enable branch; add `apply_capability_overrides` helper (or import it). |
| `backend/services/ai_account_manager_service.py` | Add `persist: bool = True` param to `enable()`; skip `sync_config_columns` when False. |
| `frontend/src/api/client.ts` | Add `AIManagerCapabilities` interface + field on `AutoTradeConfig`. |
| `frontend/src/components/scanner/AutoTradeSection.tsx` | Nested capability panel, default-seeding, reset affordance, `DEFAULT_CONFIG` entry. |
| Tests (backend + frontend) | New unit/integration tests per §7. |

---

## 10. Out of Scope (restated)

- Backtesting integration (AI Manager deferred there).
- Account-level capability-selection UI.
- Persisting per-scan choices into the account `AIManagerConfig`.
- New AI Manager capabilities or decision-logic changes.

---

## 11. Post-Review Addendum (2026-06-12)

A multi-lens code review surfaced findings that refined the implementation beyond
the original §5 design. Recorded here so the spec stays truthful.

### 11.1 Respawn must re-apply the override (the missed Critical)

§5.3 assumed `enable(persist=False)` + `_spawn_task(config_override=...)` was
sufficient. It is not on its own: `_spawn_task` is **also** called with no override
by the health-sweep loop, the kill-switch-reset path, and app-restart bootstrap —
each re-reads config from the DB. Because `persist=False` deliberately leaves the DB
config untouched (often empty/default for an auto-enabled account), an in-process
respawn would **silently revert** the per-scan capability choice to defaults — flipping
safety capabilities back on/off against operator intent, and persisting that drift
across crashes.

**Resolution:** an in-memory `_ephemeral_capability_overrides` registry on the
service, keyed by account, storing **only the 8 capability toggles** (not the whole
config). Written by `enable(persist=False)` via `_set_ephemeral_capabilities`, read by
`_spawn_task` when no explicit override arg is passed, cleared by
`_clear_ephemeral_capabilities` on `disable()`, on any persisting `enable()`, and when
`patch_config` edits a capability flag. On a no-arg respawn `_spawn_task` loads the
**current** DB config and re-applies just those toggles via `apply_capability_overrides`
— so `locked_positions`, patched limits, and every non-capability field reflect current
state (no stale snapshot), while the per-scan capability selection is preserved. This
keeps D4 intact (the account's **saved DB config is never rewritten**).

> **Why toggles-only, not the whole config (round-2 fix):** an earlier iteration stored
> the entire `AIManagerConfig` snapshot and re-used it wholesale on respawn. That
> resurrected stale fields — e.g. a position the user `locked` *after* the override was
> set would be un-locked on respawn, letting the AI close it. Storing only the 8 bools
> and re-applying onto fresh DB config eliminates that class of bug.

On a full process restart the registry is empty by design — the driving scan/executor
is gone too, so the account falls back to its saved DB config. This is safe for the
seven capabilities that default ON (disabled ones revert to protective/neutral); the
lone asymmetry is `trailing` (config default OFF, per-scan default ON), so a restart
drops trailing — a profit-preservation feature, not a crash-safety one — which is an
accepted, non-dangerous direction.

### 11.2 Override validation fails loud, caller fails safe

`apply_capability_overrides` now validates a dict override through
`AIManagerCapabilityToggles` (Pydantic, `extra="forbid"`, real boolean coercion)
instead of a hand-rolled `bool(...)` read. This (a) correctly coerces JSON-y
`"false"` → `False` (the prior `bool("false")==True` footgun is gone), and (b) raises
on unknown keys / non-coercible values. The caller (`_maybe_enable_ai_manager`)
**falls back to a managed enable with the account's own config** (`persist=True`) when
the override is malformed — a bad override never leaves open positions unmanaged.

### 11.3 Crash-protection warning (UI)

Disabling `emergency_close` or `sweep_defense` per-scan is allowed (D2: all 8 are
selectable), but the panel now renders a danger Notice when either is off, so reducing
crash protection is a deliberate, visible choice rather than a silent footgun.

### 11.4 Drift guards

Key-set drift is now caught by tests rather than convention: backend asserts
`CAPABILITY_FLAG_MAP` keys == `AIManagerCapabilityToggles` fields and that every mapped
flag is a real `AIManagerConfig` field; frontend derives `allCapabilitiesOn()` from the
metadata array and asserts its key set. The dashboard's separate `CAPABILITY_REGISTRY`
(`ai_manager_capabilities_status.py`) uses a different display vocabulary and is
cross-referenced with an explanatory comment — intentionally not unified.

### 11.5 Accepted risks (pre-existing, not introduced here)

- **Cross-scan last-writer-wins:** the AI Manager is a per-account singleton, so two
  concurrent scans targeting one account share one task; the later enable's capability
  set wins. This is inherent to the existing single-task-per-account design, not new to
  this feature.
- **`extra="forbid"` on persisted configs:** a stale/unknown key in a saved scheduled
  job can fail that job's re-validation. This is the pre-existing `AutoTradeConfig`
  philosophy applied to every field, not specific to capability toggles.
- **Dashboard reflects in-memory task config:** the dashboard reads the running task's
  config (which *does* include an active per-scan override), so it is accurate while a
  task is live; it does not show overrides for accounts whose task isn't running.
