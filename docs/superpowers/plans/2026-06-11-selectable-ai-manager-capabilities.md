# Selectable AI Manager Capabilities (Per-Scan) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each market/scheduled scan independently choose which of the 8 AI Manager capabilities run when the AI Position Manager auto-enables, defaulting to all-on, without rewriting the account's saved AI Manager config.

**Architecture:** A new optional nested `AIManagerCapabilityToggles` object on `AutoTradeConfig` (per-scan) carries the choice (`null` = legacy behavior). When a scan auto-enables the AI Manager, a pure helper maps the 8 toggles onto a copy of the account's `AIManagerConfig`, and the manager is enabled via a new non-persisting path (`persist=False` + `config_override` on `_spawn_task`) so the account's stored config row is never overwritten. The frontend adds a nested capability panel under the existing AI Manager switch in the shared `AutoTradeSection`, covering both scan forms automatically.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest + pytest-asyncio (backend); React 18 + TypeScript + Vitest + Testing Library (frontend).

**Spec:** `docs/superpowers/specs/2026-06-11-selectable-ai-manager-capabilities-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/schemas/__init__.py` | Per-scan config schema | Add `AIManagerCapabilityToggles` model; add `ai_manager_capabilities` field on `AutoTradeConfig`. |
| `backend/services/ai_manager_capability_map.py` | Pure toggle→flag mapping | **Create.** `apply_capability_overrides(config, toggles)` returns an overridden copy of `AIManagerConfig`. |
| `backend/services/ai_account_manager_service.py` | AI Manager lifecycle | Add `persist: bool = True` to `enable()`; add `config_override` to `_spawn_task()`; thread override through both branches. |
| `backend/services/auto_trade_service.py` | Auto-trade enable branch | In the AI-Manager enable block, apply per-scan override and call `enable(..., persist=False)` when override present; legacy path otherwise. |
| `frontend/src/api/client.ts` | TS types | Add `AIManagerCapabilities` interface + `ai_manager_capabilities` field on `AutoTradeConfig`. |
| `frontend/src/components/scanner/aiManagerCapabilities.ts` | Capability metadata + helpers | **Create.** Capability list (key/title/description) + `allCapabilitiesOn()` factory. |
| `frontend/src/components/scanner/AutoTradeSection.tsx` | Scan form UI | Nested capability panel under AI Manager switch; default-seeding on enable; reset affordance; `DEFAULT_CONFIG` entry. |
| `tests/backend/test_ai_manager_capability_toggles.py` | Schema + mapping tests | **Create.** |
| `tests/backend/test_ai_manager_capability_enable.py` | Service enable/persist tests | **Create.** |
| `tests/backend/test_auto_trade_ai_capability_override.py` | Auto-trade integration tests | **Create.** |
| `frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx` | UI + helper tests | **Create.** |

---

## Task 1: Backend schema — `AIManagerCapabilityToggles` + field

**Files:**
- Modify: `backend/schemas/__init__.py` (add model just above `class AutoTradeConfig` at line 444; add field near line 468)
- Test: `tests/backend/test_ai_manager_capability_toggles.py` (create)

Context: `backend/schemas/__init__.py` already imports `BaseModel, ConfigDict, Field` from pydantic (line 15) and `Optional` is in use throughout. `AutoTradeConfig` already sets `model_config = ConfigDict(extra="forbid")`.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_ai_manager_capability_toggles.py`:

```python
"""Schema tests for per-scan AI Manager capability toggles."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas import AIManagerCapabilityToggles, AutoTradeConfig

ALL_KEYS = {
    "mtf", "orderbook", "sweep_defense", "correlation",
    "regime_enhanced", "event_driven", "trailing", "emergency_close",
}


def test_toggles_default_all_true():
    t = AIManagerCapabilityToggles()
    for key in ALL_KEYS:
        assert getattr(t, key) is True


def test_toggles_partial_object_fills_defaults_true():
    t = AIManagerCapabilityToggles(mtf=False)
    assert t.mtf is False
    assert t.orderbook is True  # omitted key defaults True


def test_toggles_rejects_unknown_key():
    with pytest.raises(ValidationError):
        AIManagerCapabilityToggles(bogus=True)


def test_autotrade_config_capabilities_defaults_none():
    cfg = AutoTradeConfig(account_id="acc_1")
    assert cfg.ai_manager_capabilities is None


def test_autotrade_config_accepts_capabilities_object():
    cfg = AutoTradeConfig(
        account_id="acc_1",
        ai_manager_enabled=True,
        ai_manager_capabilities={"trailing": False},
    )
    assert cfg.ai_manager_capabilities is not None
    assert cfg.ai_manager_capabilities.trailing is False
    assert cfg.ai_manager_capabilities.mtf is True


def test_autotrade_config_capabilities_roundtrip():
    cfg = AutoTradeConfig(
        account_id="acc_1",
        ai_manager_enabled=True,
        ai_manager_capabilities=AIManagerCapabilityToggles(orderbook=False),
    )
    dumped = cfg.model_dump()
    restored = AutoTradeConfig(**dumped)
    assert restored.ai_manager_capabilities.orderbook is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/test_ai_manager_capability_toggles.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'AIManagerCapabilityToggles'`.

- [ ] **Step 3: Add the model and field**

In `backend/schemas/__init__.py`, insert this class immediately **above** `class AutoTradeConfig(BaseModel):` (currently line 444):

```python
class AIManagerCapabilityToggles(BaseModel):
    """Per-scan selection of which AI Manager capabilities run.

    Presence on AutoTradeConfig (non-null) means the user made an explicit
    per-scan choice; absence (null) means "didn't choose" and the account's
    saved AIManagerConfig is used unchanged (legacy behavior). Every flag
    defaults True so the literal "enable all" model holds.
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

Then add this field inside `AutoTradeConfig`, immediately **after** the
`ai_manager_enabled: bool = False` line (line 468):

```python
    # Per-scan AI Manager capability selection. None = "didn't choose" → the
    # account's saved AIManagerConfig is used unchanged (legacy behavior).
    # Non-null = explicit override applied (without persisting) when the AI
    # Manager auto-enables for this scan. Only consulted when ai_manager_enabled.
    ai_manager_capabilities: Optional[AIManagerCapabilityToggles] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/test_ai_manager_capability_toggles.py -x -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/__init__.py tests/backend/test_ai_manager_capability_toggles.py
git commit -m "feat(schema): add per-scan AIManagerCapabilityToggles to AutoTradeConfig"
```

---

## Task 2: Pure capability-mapping helper

**Files:**
- Create: `backend/services/ai_manager_capability_map.py`
- Test: `tests/backend/test_ai_manager_capability_toggles.py` (append to the file from Task 1)

Context: maps the 8 toggle keys to the real `AIManagerConfig` flag names. Pure (no I/O), returns a copy so the input is never mutated. `AIManagerConfig` lives in `backend/ai_manager_schemas.py`. Account default for `trailing_enabled` is `False`, so a `trailing=True` toggle must flip it on.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/test_ai_manager_capability_toggles.py`:

```python
from backend.ai_manager_schemas import AIManagerConfig
from backend.services.ai_manager_capability_map import (
    CAPABILITY_FLAG_MAP,
    apply_capability_overrides,
)


def test_flag_map_covers_all_eight_keys():
    assert set(CAPABILITY_FLAG_MAP.keys()) == ALL_KEYS


def test_apply_none_returns_unchanged_copy():
    base = AIManagerConfig()
    out = apply_capability_overrides(base, None)
    assert out.model_dump() == base.model_dump()


def test_apply_overrides_all_flags_off():
    base = AIManagerConfig()
    toggles = AIManagerCapabilityToggles(
        mtf=False, orderbook=False, sweep_defense=False, correlation=False,
        regime_enhanced=False, event_driven=False, trailing=False,
        emergency_close=False,
    )
    out = apply_capability_overrides(base, toggles)
    assert out.mtf_enabled is False
    assert out.orderbook_enabled is False
    assert out.sweep_defense_enabled is False
    assert out.correlation_enabled is False
    assert out.regime_enhanced is False
    assert out.event_driven_enabled is False
    assert out.trailing_enabled is False
    assert out.emergency_close_enabled is False


def test_apply_trailing_true_flips_account_default():
    base = AIManagerConfig()
    assert base.trailing_enabled is False  # account default
    out = apply_capability_overrides(base, AIManagerCapabilityToggles())
    assert out.trailing_enabled is True  # toggle default True wins


def test_apply_does_not_mutate_input():
    base = AIManagerConfig()
    apply_capability_overrides(base, AIManagerCapabilityToggles(mtf=False))
    assert base.mtf_enabled is True  # original untouched


def test_apply_accepts_dict_toggles():
    base = AIManagerConfig()
    out = apply_capability_overrides(base, {"orderbook": False})
    assert out.orderbook_enabled is False
    assert out.mtf_enabled is True  # omitted dict key → default True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/test_ai_manager_capability_toggles.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.ai_manager_capability_map'`.

- [ ] **Step 3: Create the helper**

Create `backend/services/ai_manager_capability_map.py`:

```python
"""Pure mapping from per-scan capability toggles to AIManagerConfig flags.

No I/O — unit-testable in isolation. Used by auto_trade_service to layer a
per-scan capability override onto the account's AIManagerConfig without
persisting it.
"""
from __future__ import annotations

from typing import Any

from backend.ai_manager_schemas import AIManagerConfig
from backend.schemas import AIManagerCapabilityToggles

# toggle key -> AIManagerConfig flag name
CAPABILITY_FLAG_MAP: dict[str, str] = {
    "mtf": "mtf_enabled",
    "orderbook": "orderbook_enabled",
    "sweep_defense": "sweep_defense_enabled",
    "correlation": "correlation_enabled",
    "regime_enhanced": "regime_enhanced",
    "event_driven": "event_driven_enabled",
    "trailing": "trailing_enabled",
    "emergency_close": "emergency_close_enabled",
}


def apply_capability_overrides(
    config: AIManagerConfig,
    toggles: "AIManagerCapabilityToggles | dict[str, Any] | None",
) -> AIManagerConfig:
    """Return a copy of `config` with the 8 capability flags overridden by `toggles`.

    No-op (returns an equivalent copy) when `toggles` is None. A dict is read by
    key, falling back to True for any omitted capability (matching the toggle
    model's all-True defaults). The input `config` is never mutated.
    """
    if toggles is None:
        return config.model_copy()

    if isinstance(toggles, AIManagerCapabilityToggles):
        toggle_values = toggles.model_dump()
    else:
        toggle_values = {
            key: bool(toggles.get(key, True)) for key in CAPABILITY_FLAG_MAP
        }

    updates = {
        CAPABILITY_FLAG_MAP[key]: toggle_values[key]
        for key in CAPABILITY_FLAG_MAP
    }
    return config.model_copy(update=updates)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/test_ai_manager_capability_toggles.py -x -q`
Expected: PASS (12 passed total).

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_manager_capability_map.py tests/backend/test_ai_manager_capability_toggles.py
git commit -m "feat(ai-manager): add pure capability toggle->flag mapping helper"
```

---

## Task 3: Non-persisting enable path on `AIAccountManagerService`

**Files:**
- Modify: `backend/services/ai_account_manager_service.py` — `enable()` (lines 237-257) and `_spawn_task()` (lines 877-890)
- Test: `tests/backend/test_ai_manager_capability_enable.py` (create)

Context — **why `_spawn_task` must also change:** `_spawn_task()` (line 880-887)
**re-reads config from the DB** via `get_state()`. So in the respawn branch, skipping
`sync_config_columns` is not enough — the freshly spawned task would load the *stale
persisted* config and lose the override. The fix: `_spawn_task` accepts an optional
`config_override`; when provided it uses that instead of the DB config. `enable()`
passes the override through on the `persist=False` respawn path. All 7 existing
`_spawn_task(...)` callers pass nothing → unchanged (override defaults None).
The alive-task branch already calls `reload_config(config)` in-memory, so it only
needs to skip the DB write when `persist=False`.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_ai_manager_capability_enable.py`:

```python
"""enable(persist=False) must spawn/reload with the given config but NOT write it to DB."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai_manager_schemas import AIManagerConfig


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.upsert_state = AsyncMock(return_value={})
    repo.sync_config_columns = AsyncMock()
    repo.insert_log = AsyncMock()
    repo.get_state = AsyncMock(return_value={
        "enabled": True, "fsm_state": "sleeping", "config": "{}",
        "circuit_breaker_count": 0, "circuit_breaker_active": False,
    })
    return repo


@pytest.fixture
def service(mock_repo):
    from backend.services.ai_account_manager_service import AIAccountManagerService
    from backend.services.ai_manager_llm_scheduler import PriorityLLMScheduler
    from backend.services.position_lock_registry import PositionLockRegistry

    return AIAccountManagerService(
        accounts_service=MagicMock(),
        close_positions_service=MagicMock(),
        ws_manager=None,
        ai_manager_repo=mock_repo,
        market_data_cache=MagicMock(),
        position_lock_registry=PositionLockRegistry(),
        llm_scheduler=PriorityLLMScheduler(),
        hmac_key="test-key",
    )


@pytest.mark.asyncio
async def test_enable_persist_false_skips_config_write_on_spawn(service, mock_repo):
    """Fresh spawn with persist=False must NOT call sync_config_columns."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        inst = MagicMock()
        inst.start = MagicMock()
        MockTask.return_value = inst
        cfg = AIManagerConfig(auto_enabled=True, trailing_enabled=True)

        await service.enable("acc-1", cfg, persist=False)

        mock_repo.sync_config_columns.assert_not_called()
        # Task spawned with the override config (not the empty DB config)
        assert MockTask.call_args.kwargs["config"].trailing_enabled is True


@pytest.mark.asyncio
async def test_enable_persist_true_writes_config_on_spawn(service, mock_repo):
    """Default persist=True preserves existing behavior (writes config)."""
    with patch("backend.services.ai_manager_task.AIManagerTask") as MockTask:
        inst = MagicMock()
        inst.start = MagicMock()
        MockTask.return_value = inst

        await service.enable("acc-1", AIManagerConfig(auto_enabled=True))

        mock_repo.sync_config_columns.assert_called_once()


@pytest.mark.asyncio
async def test_enable_persist_false_alive_task_reloads_without_write(service, mock_repo):
    """Alive task: reload_config in-memory, no DB write when persist=False."""
    alive = MagicMock()
    alive.is_dead = MagicMock(return_value=False)
    alive._config = AIManagerConfig(auto_enabled=False)
    alive.reload_config = MagicMock()
    service._tasks["acc-1"] = alive

    cfg = AIManagerConfig(auto_enabled=True, mtf_enabled=False)
    await service.enable("acc-1", cfg, persist=False)

    alive.reload_config.assert_called_once()
    assert alive.reload_config.call_args.args[0].mtf_enabled is False
    mock_repo.sync_config_columns.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/test_ai_manager_capability_enable.py -x -q`
Expected: FAIL — `enable()` got an unexpected keyword argument `persist` (and/or spawn uses DB config).

- [ ] **Step 3: Modify `enable()` and `_spawn_task()`**

Replace `enable()` (lines 237-257) with:

```python
    async def enable(
        self,
        account_id: str,
        config: AIManagerConfig,
        *,
        persist: bool = True,
    ) -> None:
        """Enable AI Manager for an account — spawns the decision loop task.

        persist=True (default) writes `config` to the DB (unchanged legacy
        behavior). persist=False spawns/reloads the task with `config` in-memory
        only — used for per-scan capability overrides that must not overwrite the
        account's stored config.
        """
        lock = self._get_account_lock(account_id)
        async with lock:
            existing_task = self._tasks.get(account_id)
            if existing_task and not existing_task.is_dead():
                # Task is alive — sync config if auto_enabled changed OR an
                # explicit non-persisting override was supplied.
                changed = getattr(existing_task._config, "auto_enabled", False) != config.auto_enabled
                if changed or not persist:
                    if persist:
                        await self._repo.sync_config_columns(account_id, config.model_dump())
                    existing_task.reload_config(config)
                return
            # No task or dead task — (re)spawn
            if existing_task and existing_task.is_dead():
                logger.info("AI Manager: respawning dead task for account %s on enable()", account_id)
                existing_task.cancel()
                self._tasks.pop(account_id, None)
            await self._repo.upsert_state(account_id, enabled=True, fsm_state="sleeping")
            if persist:
                await self._repo.sync_config_columns(account_id, config.model_dump())
            await self._spawn_task(account_id, config_override=None if persist else config)
            source = "auto" if config.auto_enabled else "manual"
            await self._repo.insert_log(account_id, "info", "lifecycle", f"AI Manager enabled ({source})")
```

Then change the `_spawn_task` signature (line 877) and its config-loading block
(lines 883-890):

```python
    async def _spawn_task(
        self,
        account_id: str,
        *,
        config_override: "AIManagerConfig | None" = None,
    ) -> None:
        from backend.services.ai_manager_task import AIManagerTask

        state = await self._repo.get_state(account_id)
        if not state or not state.get("enabled", False):
            return
        if config_override is not None:
            config = config_override
        else:
            try:
                raw_config = state.get("config") or {}
                if isinstance(raw_config, str):
                    raw_config = _json.loads(raw_config)
                config = AIManagerConfig(**raw_config)
            except Exception:
                logger.warning("Invalid config for %s, using defaults", account_id)
                config = AIManagerConfig()
```

(The remainder of `_spawn_task` is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/test_ai_manager_capability_enable.py -x -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing service tests to confirm no regression**

Run: `python -m pytest tests/backend/test_ai_account_manager_service.py -x -q`
Expected: PASS (all existing tests still green — `persist` defaults True).

- [ ] **Step 6: Commit**

```bash
git add backend/services/ai_account_manager_service.py tests/backend/test_ai_manager_capability_enable.py
git commit -m "feat(ai-manager): add non-persisting enable path with config_override"
```

---

## Task 4: Wire the per-scan override into `auto_trade_service`

**Files:**
- Modify: `backend/services/auto_trade_service.py` — the AI-Manager enable block (lines 1747-1767)
- Test: `tests/backend/test_auto_trade_ai_capability_override.py` (create)

Context: the enable block currently loads the account config, sets `auto_enabled=True`,
and calls `enable(account_id, config_to_use)`. We add: read `cfg.get("ai_manager_capabilities")`;
if present, map it onto the config via `apply_capability_overrides` and call
`enable(..., persist=False)`. If absent (None), keep the **exact** current path
(`enable(...)` with default `persist=True`). `cfg` here is a plain dict (the config
is stored/looked-up as a dict in executor state), so `ai_manager_capabilities` is a
nested dict when present.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_auto_trade_ai_capability_override.py`:

```python
"""The auto-trade enable branch applies per-scan capability overrides w/o persisting."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.auto_trade_service import AutoTradeExecutor


def _make_executor_with_ai():
    ai_svc = AsyncMock()
    # No stored config → get_config raises, so defaults are used.
    ai_svc.get_config = AsyncMock(side_effect=ValueError("not configured"))
    ai_svc.enable = AsyncMock()
    ex = AutoTradeExecutor(MagicMock(), MagicMock(), ai_manager_service=ai_svc)
    return ex, ai_svc


@pytest.mark.asyncio
async def test_override_present_calls_enable_persist_false():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {
        "ai_manager_enabled": True,
        "ai_manager_capabilities": {"trailing": False, "mtf": False},
    }
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")

    ai_svc.enable.assert_awaited_once()
    _args, kwargs = ai_svc.enable.await_args
    assert kwargs.get("persist") is False
    sent_config = _args[1]
    assert sent_config.auto_enabled is True
    assert sent_config.trailing_enabled is False
    assert sent_config.mtf_enabled is False
    assert sent_config.orderbook_enabled is True  # untouched key stays on


@pytest.mark.asyncio
async def test_no_override_uses_legacy_persist_true():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {"ai_manager_enabled": True}  # no capabilities key
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")

    ai_svc.enable.assert_awaited_once()
    _args, kwargs = ai_svc.enable.await_args
    # legacy path: persist not forced False (default True)
    assert kwargs.get("persist", True) is True


@pytest.mark.asyncio
async def test_mean_reversion_skips_enable():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {"ai_manager_enabled": True, "ai_manager_capabilities": {"mtf": False}}
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="mean_reversion")
    ai_svc.enable.assert_not_called()


@pytest.mark.asyncio
async def test_enable_only_once_per_account():
    ex, ai_svc = _make_executor_with_ai()
    cfg = {"ai_manager_enabled": True}
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    await ex._maybe_enable_ai_manager("acc-1", cfg, strategy_kind="trend")
    ai_svc.enable.assert_awaited_once()  # second call is a no-op
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/test_auto_trade_ai_capability_override.py -x -q`
Expected: FAIL — `AttributeError: 'AutoTradeExecutor' object has no attribute '_maybe_enable_ai_manager'`.

> The current logic is inline in the placement method. We extract it into a small
> named method `_maybe_enable_ai_manager` so it is unit-testable in isolation, then
> call that method from the original site. This is a behavior-preserving refactor of
> the extracted block plus the new override branch.

- [ ] **Step 3: Extract + extend the enable logic**

In `backend/services/auto_trade_service.py`, **replace** the inline block at lines
1747-1767 with a call to a new method:

```python
            # Enable AI Manager for this account if configured (FR-052: MR excluded).
            await self._maybe_enable_ai_manager(account_id, cfg, strategy_kind=strategy_kind)
```

Then add this method to the `AutoTradeExecutor` class (place it near the other
private helpers in the class):

```python
    async def _maybe_enable_ai_manager(
        self, account_id: str, cfg: Dict[str, Any], *, strategy_kind: str
    ) -> None:
        """Auto-enable the AI Manager for an account on first placement of this scan.

        Applies a per-scan capability override (without persisting) when
        cfg['ai_manager_capabilities'] is present; otherwise preserves the legacy
        path (load account config, enable with persist=True). No-op for
        mean-reversion placements (their positions are excluded from AI management).
        """
        if strategy_kind == "mean_reversion":
            return
        if not cfg.get("ai_manager_enabled"):
            return
        if account_id in self._ai_manager_enabled_accounts:
            return
        self._ai_manager_enabled_accounts.add(account_id)
        if not self._ai_manager_service:
            return
        try:
            # Preserve any existing config — only use defaults if none exists yet.
            existing_config = None
            try:
                existing_dict = await self._ai_manager_service.get_config(account_id)
                existing_config = _AIMConfig(**existing_dict)
            except Exception:
                pass
            config_to_use = existing_config or _AIMConfig()
            config_to_use.auto_enabled = True

            capabilities = cfg.get("ai_manager_capabilities")
            if capabilities is not None:
                from backend.services.ai_manager_capability_map import (
                    apply_capability_overrides,
                )
                config_to_use = apply_capability_overrides(config_to_use, capabilities)
                config_to_use.auto_enabled = True
                await self._ai_manager_service.enable(
                    account_id, config_to_use, persist=False
                )
                logger.info(
                    "ai_manager_auto_enabled",
                    extra={"account_id": account_id, "capability_override": True},
                )
            else:
                await self._ai_manager_service.enable(account_id, config_to_use)
                logger.info(
                    "ai_manager_auto_enabled",
                    extra={"account_id": account_id, "capability_override": False},
                )
        except Exception as e:
            # Match legacy behavior: a failed enable must not abort the placement.
            self._ai_manager_enabled_accounts.discard(account_id)
            logger.warning(
                "ai_manager_auto_enable_failed",
                extra={"account_id": account_id, "error": str(e)[:200]},
            )
```

> Note: `apply_capability_overrides` returns a copy, so we re-assert
> `auto_enabled = True` on the returned config before enabling (the account-default
> `auto_enabled` is False and the toggle map does not touch it). Also note the
> `discard` on failure — the legacy inline code added to the set *before* the try and
> never rolled back; rolling back on failure is a small correctness improvement so a
> transient enable error can be retried on the next placement.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/test_auto_trade_ai_capability_override.py -x -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the existing auto-trade tests to confirm no regression**

Run: `python -m pytest tests/backend/test_auto_trade_service_unit.py -x -q`
Expected: PASS (all existing tests still green).

- [ ] **Step 6: Commit**

```bash
git add backend/services/auto_trade_service.py tests/backend/test_auto_trade_ai_capability_override.py
git commit -m "feat(auto-trade): apply per-scan AI Manager capability override on enable"
```

---

## Task 5: Frontend types + capability metadata module

**Files:**
- Modify: `frontend/src/api/client.ts` — add `AIManagerCapabilities` interface (after `AutoTradeConfig`, ~line 380+) and field on `AutoTradeConfig` (after `ai_manager_enabled?` at line 346)
- Create: `frontend/src/components/scanner/aiManagerCapabilities.ts`
- Test: `frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import {
  AI_MANAGER_CAPABILITIES,
  allCapabilitiesOn,
  type AICapabilityKey,
} from "../aiManagerCapabilities";

const EXPECTED_KEYS: AICapabilityKey[] = [
  "mtf", "orderbook", "sweep_defense", "correlation",
  "regime_enhanced", "event_driven", "trailing", "emergency_close",
];

describe("AI_MANAGER_CAPABILITIES metadata", () => {
  it("lists all 8 capabilities with title + description", () => {
    expect(AI_MANAGER_CAPABILITIES.map((c) => c.key)).toEqual(EXPECTED_KEYS);
    for (const cap of AI_MANAGER_CAPABILITIES) {
      expect(cap.title.length).toBeGreaterThan(0);
      expect(cap.description.length).toBeGreaterThan(0);
    }
  });
});

describe("allCapabilitiesOn", () => {
  it("returns every capability set to true", () => {
    const all = allCapabilitiesOn();
    for (const key of EXPECTED_KEYS) {
      expect(all[key]).toBe(true);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/scanner/__tests__/aiManagerCapabilities.test.tsx`
Expected: FAIL — cannot resolve module `../aiManagerCapabilities`.

- [ ] **Step 3: Add the TS type to `client.ts`**

In `frontend/src/api/client.ts`, add this field to the `AutoTradeConfig` interface,
immediately after `ai_manager_enabled?: boolean;` (line 346):

```typescript
  ai_manager_capabilities?: AIManagerCapabilities | null;
```

And add this interface immediately **after** the `AutoTradeConfig` interface closes
(after line ~408, wherever the interface's closing `}` is):

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
```

- [ ] **Step 4: Create the metadata module**

Create `frontend/src/components/scanner/aiManagerCapabilities.ts`:

```typescript
import type { AIManagerCapabilities } from "@/api/client";

export type AICapabilityKey = keyof AIManagerCapabilities;

export interface AICapabilityMeta {
  key: AICapabilityKey;
  title: string;
  description: string;
}

/** Display order + copy for the per-scan AI Manager capability toggles. */
export const AI_MANAGER_CAPABILITIES: AICapabilityMeta[] = [
  { key: "mtf", title: "Multi-Timeframe Analysis", description: "Aligns trend across 5m/15m/1h/4h before acting on a position." },
  { key: "orderbook", title: "Order Book Monitoring", description: "Reads live bid/ask imbalance and depth around the position." },
  { key: "sweep_defense", title: "Sweep / Stop-Hunt Defense", description: "Avoids closing into liquidity sweeps and stop-hunts." },
  { key: "correlation", title: "Correlation & Clustering", description: "Tracks portfolio heat and correlated-position clusters." },
  { key: "regime_enhanced", title: "Regime Enhancement", description: "Adapts decisions to the detected market regime." },
  { key: "event_driven", title: "Event-Driven Evaluation", description: "Reacts to live triggers (price moves, drawdown) plus a safety-net timer." },
  { key: "trailing", title: "Trailing TP/SL", description: "Dynamically trails take-profit / stop-loss on profitable positions." },
  { key: "emergency_close", title: "Emergency Close", description: "Deterministic fast-path crash protection on sharp adverse moves." },
];

/** All 8 capabilities enabled — the default when the AI Manager is switched on. */
export function allCapabilitiesOn(): AIManagerCapabilities {
  return {
    mtf: true,
    orderbook: true,
    sweep_defense: true,
    correlation: true,
    regime_enhanced: true,
    event_driven: true,
    trailing: true,
    emergency_close: true,
  };
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/scanner/__tests__/aiManagerCapabilities.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/scanner/aiManagerCapabilities.ts frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx
git commit -m "feat(frontend): add AIManagerCapabilities type + capability metadata"
```

---

## Task 6: Capability panel UI + default-seeding in `AutoTradeSection`

**Files:**
- Create: `frontend/src/components/scanner/AICapabilityPanel.tsx`
- Modify: `frontend/src/components/scanner/AutoTradeSection.tsx` — `DEFAULT_CONFIG` (line 18-55), AI Manager `ToggleRow` (lines 741-751)
- Test: `frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx` (append)

Context: `AICapabilityPanel` is a small self-contained component (mountable in tests
without scan-page providers). `ToggleRow` is exported-in-file only, so the panel
defines its own minimal row markup (reusing the same Tailwind tokens) to stay
decoupled. The AI Manager `ToggleRow`'s `onChange` is updated to seed/clear
`ai_manager_capabilities`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { AICapabilityPanel } from "../AICapabilityPanel";
import { allCapabilitiesOn } from "../aiManagerCapabilities";

describe("AICapabilityPanel", () => {
  it("renders a toggle for each of the 8 capabilities", () => {
    render(<AICapabilityPanel value={allCapabilitiesOn()} onChange={vi.fn()} />);
    // NeuSwitch renders role="switch" (not checkbox).
    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(8);
  });

  it("flips a single capability without touching the others", () => {
    const onChange = vi.fn();
    render(<AICapabilityPanel value={allCapabilitiesOn()} onChange={onChange} />);
    // Each row wraps its switch in a data-testid container (NeuSwitch does not
    // forward arbitrary props). Click the switch inside the mtf row.
    const mtfRow = screen.getByTestId("ai-cap-row-mtf");
    fireEvent.click(mtfRow.querySelector('[role="switch"]')!);
    expect(onChange).toHaveBeenCalledTimes(1);
    const payload = onChange.mock.calls[0][0];
    expect(payload.mtf).toBe(false);
    expect(payload.orderbook).toBe(true);
  });

  it("reset button restores all-on", () => {
    const onChange = vi.fn();
    const partial = { ...allCapabilitiesOn(), mtf: false, trailing: false };
    render(<AICapabilityPanel value={partial} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("ai-cap-reset"));
    expect(onChange).toHaveBeenCalledWith(allCapabilitiesOn());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/scanner/__tests__/aiManagerCapabilities.test.tsx`
Expected: FAIL — cannot resolve module `../AICapabilityPanel`.

- [ ] **Step 3: Create the panel component**

Create `frontend/src/components/scanner/AICapabilityPanel.tsx`:

```tsx
import type { AIManagerCapabilities } from "@/api/client";
import { NeuSwitch } from "@/design-system/neumorphism";
import {
  AI_MANAGER_CAPABILITIES,
  allCapabilitiesOn,
  type AICapabilityKey,
} from "./aiManagerCapabilities";

interface AICapabilityPanelProps {
  value: AIManagerCapabilities;
  onChange: (next: AIManagerCapabilities) => void;
}

/**
 * Nested panel of per-scan AI Manager capability toggles. Rendered only when the
 * AI Position Manager switch is on. Each toggle flips one capability; "Reset to
 * all on" restores every capability to true.
 *
 * NeuSwitch does not forward arbitrary DOM props, so each row is wrapped in a
 * div carrying the data-testid; NeuSwitch's own `label`/`description` render the
 * copy. NeuSwitch renders role="switch".
 */
export function AICapabilityPanel({ value, onChange }: AICapabilityPanelProps) {
  const setKey = (key: AICapabilityKey, checked: boolean) =>
    onChange({ ...value, [key]: checked });

  return (
    <div className="mt-3 ml-3 rounded-[var(--neu-radius-md)] neu-surface-base bg-[var(--neu-surface-muted)] p-3 shadow-[var(--neu-shadow-inset)] space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
          AI Manager capabilities
        </p>
        <button
          type="button"
          data-testid="ai-cap-reset"
          className="text-[10px] font-semibold uppercase tracking-wider text-[var(--neu-accent)] hover:underline"
          onClick={() => onChange(allCapabilitiesOn())}
        >
          Reset to all on
        </button>
      </div>
      {AI_MANAGER_CAPABILITIES.map((cap) => (
        <div
          key={cap.key}
          data-testid={`ai-cap-row-${cap.key}`}
          className="rounded-[var(--neu-radius-sm)] neu-surface-base p-3 border-none shadow-[var(--shadow-card)]"
        >
          <NeuSwitch
            checked={value[cap.key]}
            onChange={(checked: boolean) => setKey(cap.key, checked)}
            label={cap.title}
            description={cap.description}
          />
        </div>
      ))}
    </div>
  );
}
```

> **`NeuSwitch` API confirmed** (`frontend/src/design-system/neumorphism/inputs.tsx`
> line 1009): props are `{ checked, onChange, label, description, disabled, accent,
> className }` — it does **not** spread extra DOM props, and the toggle element is a
> `<button role="switch" aria-checked>`. The component above and the Step 1 test
> queries (`getAllByRole("switch")`, `getByTestId("ai-cap-row-<key>")`) match this.
> If a future NeuSwitch refactor changes the role, update both together.

- [ ] **Step 4: Wire the panel + default-seeding into `AutoTradeSection.tsx`**

(a) Add the import near the other scanner imports (top of file, after the
`RegimeStrategyFields` import on line 14):

```tsx
import { AICapabilityPanel } from "./AICapabilityPanel";
import { allCapabilitiesOn } from "./aiManagerCapabilities";
```

(b) In `DEFAULT_CONFIG` (lines 18-55), add after `ai_manager_enabled: false,`
(line 37):

```tsx
  ai_manager_capabilities: null,
```

(c) Replace the AI Manager `ToggleRow` (lines 741-751) with the toggle plus the
nested panel:

```tsx
            <ToggleRow
              checked={config.ai_manager_enabled ?? false}
              onChange={(checked) =>
                onChange({
                  ai_manager_enabled: checked,
                  // Seed all-on when turning on (if not already chosen); clear when off.
                  ai_manager_capabilities: checked
                    ? (config.ai_manager_capabilities ?? allCapabilitiesOn())
                    : null,
                })
              }
              title="AI Position Manager"
              description="Automatically monitor and close positions using AI-driven analysis (trend reversals, profit preservation, abnormal conditions)."
              trailing={
                config.ai_manager_enabled ? (
                  <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider bg-[color-mix(in_oklch,var(--neu-accent)_12%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_30%,var(--neu-stroke-soft))]">AI</Badge>
                ) : null
              }
            />
            {config.ai_manager_enabled ? (
              <AICapabilityPanel
                value={config.ai_manager_capabilities ?? allCapabilitiesOn()}
                onChange={(next) => onChange({ ai_manager_capabilities: next })}
              />
            ) : null}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/scanner/__tests__/aiManagerCapabilities.test.tsx`
Expected: PASS (5 passed total).

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/scanner/AICapabilityPanel.tsx frontend/src/components/scanner/AutoTradeSection.tsx frontend/src/components/scanner/__tests__/aiManagerCapabilities.test.tsx
git commit -m "feat(frontend): nested AI Manager capability panel in auto-trade form"
```

---

## Task 7: Full-suite verification

**Files:** none (validation only)

- [ ] **Step 1: Backend — run the new + adjacent suites**

Run:
```bash
python -m pytest tests/backend/test_ai_manager_capability_toggles.py \
  tests/backend/test_ai_manager_capability_enable.py \
  tests/backend/test_auto_trade_ai_capability_override.py \
  tests/backend/test_ai_account_manager_service.py \
  tests/backend/test_auto_trade_service_unit.py -q
```
Expected: all PASS.

- [ ] **Step 2: Backend — sanity-check no schema importers broke**

Run: `python -m pytest tests/backend/ -q -k "auto_trade or ai_manager"`
Expected: all PASS (no collection/import errors from the new schema field).

- [ ] **Step 3: Frontend — full unit run + type-check + build**

Run:
```bash
cd frontend && npx vitest run src/components/scanner && npx tsc --noEmit && npm run build
```
Expected: tests PASS, no type errors, build succeeds.

- [ ] **Step 4: Manual round-trip smoke (documented, not automated)**

Confirm by inspection / dev server:
1. Market Scan form → enable "AI Position Manager" → 8 capability toggles appear, all on.
2. Turn one off, reload (localStorage persistence) → choice survives.
3. Disable AI Manager → panel hides and `ai_manager_capabilities` clears to null.
4. Scheduled Scan form shows the same panel (shared `AutoTradeSection`).

- [ ] **Step 5: Commit (if any lint/format fixups were needed)**

```bash
git add -A
git commit -m "test: verify selectable AI Manager capabilities end-to-end"
```

(Skip if nothing changed.)

---

## Self-Review

**Spec coverage** — every spec section maps to a task:

| Spec item | Task |
|-----------|------|
| §5.1 `AIManagerCapabilityToggles` + field (D5) | Task 1 |
| §5.2 capability mapping helper | Task 2 |
| §5.3 non-persisting enable path (D4) | Task 3 |
| §5.3 caller wiring + once-per-scan guard | Task 4 |
| §5.4 frontend type | Task 5 |
| §5.5 UI panel, default-seeding (D3), reset, DEFAULT_CONFIG | Tasks 5 + 6 |
| §6 edge cases E1–E8 | E1/E7 Task 1; E3/E6 Task 1; E2 Task 6; E4/E8 Task 3; E5 Task 4 |
| §7 testing strategy | Tasks 1-7 (TDD throughout) |
| D1 (scan-form, both forms) | Task 6 (shared `AutoTradeSection`) |
| D2 (all 8 flags) | Tasks 1, 5 |

**Type/name consistency check:**
- Toggle keys identical across backend (`AIManagerCapabilityToggles`), helper
  (`CAPABILITY_FLAG_MAP`), TS (`AIManagerCapabilities`), metadata
  (`AI_MANAGER_CAPABILITIES`): `mtf, orderbook, sweep_defense, correlation,
  regime_enhanced, event_driven, trailing, emergency_close`. ✓
- `AIManagerConfig` flag names verified against `backend/ai_manager_schemas.py`:
  `mtf_enabled, orderbook_enabled, sweep_defense_enabled, correlation_enabled,
  regime_enhanced, event_driven_enabled, trailing_enabled, emergency_close_enabled`. ✓
- `apply_capability_overrides(config, toggles)` signature identical in Task 2
  (definition), Task 3 (not used), Task 4 (call site). ✓
- `enable(account_id, config, *, persist=True)` — Task 3 definition matches Task 4
  call (`persist=False`) and Task 3 tests. ✓
- `_spawn_task(account_id, *, config_override=None)` — Task 3 definition matches the
  internal call from `enable()`. The 7 pre-existing callers pass no override. ✓
- `allCapabilitiesOn()` returns `AIManagerCapabilities` — used in Tasks 5 & 6. ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code; every test step
shows full test code and exact run command + expected result. ✓

**Known risk flagged inline:** Task 6 Step 3 includes a `NeuSwitch` prop-forwarding
verification note — the only assumption that must be confirmed against real component
behavior before the UI test will pass.

---

## Execution Order & Dependencies

```
Task 1 (schema) ──► Task 2 (helper, imports schema)
                     │
Task 3 (enable path, independent of 1/2) 
                     │
Task 1+2+3 ─────────► Task 4 (auto-trade wiring, imports helper + uses persist)
Task 5 (FE types/meta, independent) ──► Task 6 (FE panel, imports meta)
All ────────────────► Task 7 (verification)
```

Backend Tasks 1→2→4 are strictly ordered; Task 3 can be done any time before Task 4.
Frontend Tasks 5→6 are ordered. Backend and frontend tracks are independent until
Task 7.