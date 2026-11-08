# App Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the Auto Deal Searcher app's correctness, layering, dependency hygiene, and search throughput, based on the verified open review issues and the remaining deep-research roadmap items.

**Architecture:** Six independent tasks, each carrying its own test cycle. Tasks 1-4 are correctness/layering fixes (no new features); Task 5 makes site concurrency adaptive to recorded health; Task 6 makes adapter registration genuinely plugin-style (entry-point based) so new marketplaces can be added without editing core. All changes are stdlib-only where new code is added; no new runtime dependencies.

**Tech Stack:** Python 3.11+, mypy (strict on `src/`), pytest, ruff, SQLite (stdlib `sqlite3` target), Playwright, sqlite-utils (to be removed from direct deps), pydantic, yaml.

**Spec:** `docs/specs/2026-11-06-deep-research-analysis.md` (roadmap) + verified desloppify review issues (open, T1).

**Global Constraints:**
- Python 3.11+; `python -m mypy src --no-incremental` must stay clean (130 source files).
- Full suite `python -m pytest` must stay green (baseline 757 passed / 11 skipped); no test weakening.
- Ruff clean on every changed file (pre-existing errors in untouched files are out of scope).
- No new runtime dependencies; stdlib-only for new features where a dependency already exists.
- Backward compatible: keep public signatures unless a task explicitly changes them (and updates all callers + tests).
- No broad `except Exception` swallowing without a debug log; no unjustified `type: ignore` / `Any`.
- Commit after each task; user has authorized push to `origin/master` on completion.

## Review Focus

The five input classes / failure modes most likely to bite a person using this software, most likely first:

1. **A site with no recorded health yet** — adaptive concurrency must fall back to the configured base (3) instead of 0 or a crash; otherwise the very first run after install searches nothing.
2. **`condition`/`category` arriving as `"any"` from JSON/CLI vs. `Condition.ANY`/`Category.ANY` from the enum layer** — both must agree; a filter built from a JSON deal and one built from a scraped deal must produce the same match decision.
3. **A per-site search that raises** — must be recorded in `site_plan.skipped` with the exception type/message; the report must never claim a crashed site was "searched with 0 deals".
4. **A failed watchlist write** — must surface to the CLI user (non-zero exit, printed error); no silent success.
5. **Removing `sqlite-utils`** — must not destroy data in existing v6 databases; the stdlib `sqlite3` migration path must read/write the same schema and preserve all rows.

---

## File Structure

Files created or modified by this plan:

- `src/searcher/adapters/base.py` — `Deal.matches_condition`/`matches_category` signatures and comparison (Task 1).
- `src/searcher/filter_engine.py` — filter comparison (Task 1).
- `src/intelligence/price_tracker.py` — filter comparison (Task 1).
- `src/cli/app.py` — filter comparison + config coupling site (Task 1, 3).
- `src/notifications/channels/system.py` — `send()` return contract (Task 2).
- `src/history/watchlist.py` — `_save()` return contract (Task 2).
- `src/cli/commands/history.py` — propagate save failure (Task 2).
- `src/agents/coordinator.py` — `_extract_result` failure shape (Task 2).
- `src/searcher/playwright_searcher.py` — crash → skipped (Task 2); adaptive concurrency (Task 5).
- `src/config/__init__.py` — remove currency import (Task 3).
- `src/searcher/currency.py` — expose `set_rates` via a shared hook (Task 3).
- `src/llm/client.py` — remove `Deal` import, use a protocol (Task 3).
- `src/llm/protocols.py` (new) — `DealLike` protocol (Task 3).
- `config.example.yaml` — drop legacy keys or add validator (Task 4).
- `pyproject.toml`, `requirements.txt` — drop `greenlet`, `pydantic-core`, move `sqlite-utils` (Task 4).
- `src/storage/schema.py` — migrate to stdlib `sqlite3` (Task 4).
- `src/diagnostics/selector_health.py` — expose `concurrency_for(site)` helper (Task 5).
- `src/searcher/adapters/__init__.py` — entry-point based registration (Task 6).
- `tests/` — one new/updated test per task (see each task).

---

### Task 1: Type condition/category comparisons against enum members

**Files:**
- Modify: `src/searcher/adapters/base.py` (lines ~150-158)
- Modify: `src/searcher/filter_engine.py` (lines ~100, 110)
- Modify: `src/intelligence/price_tracker.py` (line ~111)
- Modify: `src/cli/app.py` (line ~173)
- Test: `tests/test_enum_comparisons.py` (new)

**Interfaces:**
- Consumes: `src.config.models.Condition`, `src.config.models.Category` (existing enums).
- Produces: `matches_condition(condition: Condition | str) -> bool` and `matches_category(category: Category | str) -> bool` on `Deal`; filter helpers accept the same union and normalize internally.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enum_comparisons.py
from src.config.models import Category, Condition
from src.searcher.adapters.base import Deal

def test_condition_any_matches_regardless_of_input_form():
    deal = Deal(url="https://x/1", title="X", condition="new")
    assert deal.matches_condition(Condition.ANY) is True
    assert deal.matches_condition("any") is True

def test_condition_specific_does_not_match_other():
    deal = Deal(url="https://x/1", title="X", condition="used")
    assert deal.matches_condition(Condition.NEW) is False
    assert deal.matches_condition("new") is False

def test_category_any_matches_regardless_of_input_form():
    deal = Deal(url="https://x/1", title="X", category="electronics")
    assert deal.matches_category(Category.ANY) is True
    assert deal.matches_category("any") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enum_comparisons.py -v`
Expected: FAIL (current code compares `condition == "any"` only, so `Condition.ANY` (an enum) never equals the string `"any"`).

- [ ] **Step 3: Implement**

In `base.py`, change the two methods to normalize the incoming value before comparison:

```python
def matches_condition(self, condition: "Condition | str") -> bool:
    incoming = condition.value if hasattr(condition, "value") else str(condition)
    if incoming == "any" or self.condition == incoming:
        return True
    return False

def matches_category(self, category: "Category | str") -> bool:
    incoming = category.value if hasattr(category, "value") else str(category)
    if incoming == "any" or self.category == incoming:
        return True
    return False
```

Apply the same normalization in `filter_engine.py`, `price_tracker.py` (`condition == "any" or deal.condition == condition`) and `cli/app.py` (`b.category == "any"`), converting the left operand the same way. Prefer comparing `.value`/`str()` on both sides rather than changing call sites.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_enum_comparisons.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite + mypy**

Run: `python -m mypy src --no-incremental && python -m pytest -q`
Expected: no mypy errors; 760+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/searcher/adapters/base.py src/searcher/filter_engine.py src/intelligence/price_tracker.py src/cli/app.py tests/test_enum_comparisons.py
git commit -m "fix(types): compare condition/category via enum value, not raw 'any' string"
```

---

### Task 2: Fix error-contract violations (false success + swallowed failures)

**Files:**
- Modify: `src/notifications/channels/system.py` (`send`)
- Modify: `src/history/watchlist.py` (`_save`, `add_item`, `remove_item`)
- Modify: `src/cli/commands/history.py` (watchlist command)
- Modify: `src/agents/coordinator.py` (`_extract_result`, `_run_*` budget branches)
- Modify: `src/searcher/playwright_searcher.py` (generic `except` in `_search_one_site`)
- Test: `tests/test_error_contracts.py` (new)

**Interfaces:**
- Consumes: existing `Watchlist`, `NotificationChannel.send` contract (returns `bool`).
- Produces: `Watchlist._save() -> bool`; `add_item/remove_item` raise `WatchlistStorageError` on failure; coordinator returns `{}` (not `str`) for failed/budget-skipped agents plus a parallel `errors: dict[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_error_contracts.py
import pytest
from src.notifications.channels.system import SystemChannel
from src.history.watchlist import Watchlist, WatchlistStorageError

@pytest.mark.asyncio
async def test_system_channel_returns_false_on_subprocess_failure(monkeypatch):
    ch = SystemChannel()
    def boom(*a, **k):
        raise RuntimeError("no notify-send")
    monkeypatch.setattr("subprocess.run", boom)
    alert = type("A", (), {"title": "t", "message": "m", "severity": "info"})()
    assert await ch.send(alert) is False

def test_watchlist_save_failure_propagates(tmp_path, monkeypatch):
    w = Watchlist(path=tmp_path / "wl.json")
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(WatchlistStorageError):
        w.add_item("https://x/1", "X")

def test_coordinator_failure_returns_dict_not_str():
    from src.agents.coordinator import _extract_result
    r = _extract_result(RuntimeError("boom"))
    assert isinstance(r, dict)
    assert r.get("error") == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_error_contracts.py -v`
Expected: FAIL (SystemChannel returns True; Watchlist has no exception; `_extract_result` returns str).

- [ ] **Step 3: Implement**

`system.py`: in the `except` block, after the console fallback print, `return False`. For the success path, only return `True` when `subprocess.run(...).returncode == 0`; otherwise log and return `False`.

`watchlist.py`: define `class WatchlistStorageError(Exception)`. Make `_save()` return `bool` (True on success) and raise `WatchlistStorageError` on failure (or return False and have callers check). Simplest: `_save()` raises on failure; `add_item`/`remove_item` already call it, so they propagate. Update `history.py` CLI to catch and print `Error: could not save watchlist` + `raise SystemExit(1)`.

`coordinator.py`: change `_extract_result` so that on failure it returns `{"error": str(...)}` instead of a bare string; update `_run_expertise_layer` / `_run_price_layer` budget-skip branches to return `{"error": "Budget exceeded, ... skipped"}`. Downstream `.get("evaluated_deals")` already uses `.get()`, so this is safe.

`playwright_searcher.py`: in the generic `except` branch of `_search_one_site`, before `return []`, append `{"name": site.name, "reason": f"search failed: {type(exc).__name__}: {exc}"}` to `self._skipped_sites`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_error_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite + mypy**

Run: `python -m mypy src --no-incremental && python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add src/notifications/channels/system.py src/history/watchlist.py src/cli/commands/history.py src/agents/coordinator.py src/searcher/playwright_searcher.py tests/test_error_contracts.py
git commit -m "fix(contracts): SystemChannel/watchlist/coordinator/playwright report failures honestly"
```

---

### Task 3: Break cross-module coupling (config↔currency, llm↔Deal)

**Files:**
- Modify: `src/config/__init__.py` (remove `from src.searcher.currency import set_rates`)
- Modify: `src/searcher/currency.py` (add a module-level `_rates` default + `set_rates` stays; add `get_rates()`)
- Modify: `src/cli/app.py` (call `set_rates(config.search.currency_rates)` at the point where config is consumed, instead of at load time)
- Create: `src/llm/protocols.py` (`DealLike` Protocol)
- Modify: `src/llm/client.py` (replace `list[Deal]` with `Sequence[DealLike]`)
- Test: `tests/test_layering.py` (new)

**Interfaces:**
- Consumes: `src.searcher.currency.set_rates`, `get_rates`.
- Produces: `src.llm.protocols.DealLike` (Protocol with `url`, `title`, `price_eur`, `condition`, `category`, `site_name`, `metadata`); `LLMClient.refine_query/judge_results/rank_results` accept `Sequence[DealLike]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layering.py
import ast, pathlib

def test_config_does_not_import_searcher():
    src = pathlib.Path("src/config/__init__.py").read_text(encoding="utf-8")
    assert "src.searcher" not in src and "searcher.currency" not in src

def test_llm_client_does_not_import_deal():
    src = pathlib.Path("src/llm/client.py").read_text(encoding="utf-8")
    assert "from src.searcher.adapters.base import Deal" not in src
    assert "import Deal" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layering.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`config/__init__.py`: delete the `from src.searcher.currency import set_rates` + `set_rates(...)` block at the end of `load_config`. Keep `load_config` returning `AppConfig`.

`currency.py`: keep `set_rates` (and add `get_rates() -> dict[str, float]` returning the current table, defaulting to the built-in rates). Default rates are applied lazily on first `parse_number`/`to_eur` call if `set_rates` was never called.

`cli/app.py`: at the start of each command that uses search, call `from src.searcher.currency import set_rates; set_rates(config.search.currency_rates)` once. (Grep for where `load_config` results are used in `app.py` to find the right hook points.)

`llm/protocols.py`: define `DealLike` as a `typing.Protocol` with the read-only attributes `url`, `title`, `price_eur`, `condition`, `category`, `site_name`, `metadata`.

`llm/client.py`: replace `from src.searcher.adapters.base import Deal` with `from src.llm.protocols import DealLike`; change `list[Deal]` → `Sequence[DealLike]`. `Deal` already satisfies the protocol structurally, so no adapter changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_layering.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite + mypy**

Run: `python -m mypy src --no-incremental && python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add src/config/__init__.py src/searcher/currency.py src/cli/app.py src/llm/protocols.py src/llm/client.py tests/test_layering.py
git commit -m "refactor(layering): decouple config from searcher.currency and llm from Deal"
```

---

### Task 4: Dependency hygiene (legacy config keys + transitive deps + sqlite-utils)

**Files:**
- Modify: `config.example.yaml` (drop or validate `local_endpoint`/`model_name` legacy block)
- Modify: `pyproject.toml`, `requirements.txt` (remove `greenlet`, `pydantic-core`; move `sqlite-utils` to optional `[storage]` extra)
- Modify: `src/storage/schema.py` (use stdlib `sqlite3` instead of `sqlite_utils.Database`)
- Test: `tests/test_storage_schema.py` (new, or extend `tests/test_storage_persistence.py`)

**Interfaces:**
- Consumes: existing schema (SCHEMA_VERSION 6, migrations 001-006).
- Produces: identical `StorageManager` public API; `schema.py` internally uses `sqlite3.Connection`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage_schema.py
import sqlite3, tempfile, os
from src.storage.manager import StorageManager

def test_schema_creates_all_tables_with_stdlib(tmp_path):
    db_path = tmp_path / "t.db"
    sm = StorageManager(db_path=str(db_path))
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "deals" in tables and "price_history" in tables
    assert "item_specs" in tables and "alert_rules" in tables

def test_existing_v6_db_still_readable(tmp_path):
    # build a db with the old (sqlite-utils) layout is not possible here;
    # instead assert StorageManager opens a pre-created v6 fixture without error
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage_schema.py -v`
Expected: FAIL (current schema imports `sqlite_utils`).

- [ ] **Step 3: Implement**

`schema.py`: replace `from sqlite_utils import Database` with `import sqlite3`; wrap connection creation in a small helper that sets `row_factory = sqlite3.Row` and enables `PRAGMA foreign_keys = ON`. Keep every `CREATE TABLE IF NOT EXISTS` statement and migration verbatim. Keep `Database`-shaped access behind a thin adapter class so `manager.py` (`db.table(...)`) keeps working, OR refactor `manager.py` to use the connection directly. Prefer the adapter to minimize churn: a `Database` shim exposing `.table(name)` returning a `Table`-like object with `.insert/.update/.delete/.rows_where`.

`config.example.yaml`: remove the `local_endpoint`/`model_name` legacy block (or add a pydantic `model_validator` in `LLMConfig` that maps them into `local[0]` with a `DeprecationWarning`). Choose removal for simplicity; document in CHANGELOG.

`pyproject.toml`/`requirements.txt`: remove `greenlet`, `pydantic-core` from direct deps; move `sqlite-utils` to `[project.optional-dependencies] storage = ["sqlite-utils>=3.35"]` (kept as fallback for users who want it, but not required).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage_schema.py tests/test_storage_persistence.py -v`

- [ ] **Step 5: Run full suite + mypy**

Run: `python -m mypy src --no-incremental && python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add src/storage/schema.py config.example.yaml pyproject.toml requirements.txt tests/test_storage_schema.py
git commit -m "refactor(storage): stdlib sqlite3; drop transitive deps; remove legacy llm config keys"
```

---

### Task 5: Adaptive per-site concurrency based on recorded health

**Files:**
- Modify: `src/diagnostics/selector_health.py` (add `concurrency_for(site_name, base) -> int`)
- Modify: `src/searcher/playwright_searcher.py` (`execute_search` concurrency computation)
- Test: `tests/test_adaptive_concurrency.py` (new)

**Interfaces:**
- Consumes: `SelectorHealthTracker.get_site_health`, `SiteHealth.is_healthy`, `consecutive_failures`.
- Produces: `SelectorHealthTracker.concurrency_for(site_name: str, base: int = 3) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adaptive_concurrency.py
from src.diagnostics.selector_health import SelectorHealthTracker, SiteHealth

def test_unknown_site_gets_base_concurrency():
    t = SelectorHealthTracker.__new__(SelectorHealthTracker)
    t.sites = {}
    assert t.concurrency_for("never-seen", base=3) == 3

def test_unhealthy_site_gets_one():
    t = SelectorHealthTracker.__new__(SelectorHealthTracker)
    site = SiteHealth(site_name="x", adapter_class="A")
    site.consecutive_failures = 6  # unhealthy
    t.sites = {"x": site}
    assert t.concurrency_for("x", base=3) == 1

def test_healthy_site_keeps_base():
    t = SelectorHealthTracker.__new__(SelectorHealthTracker)
    site = SiteHealth(site_name="x", adapter_class="A")
    site.successful_searches = 9
    site.total_searches = 10
    t.sites = {"x": site}
    assert t.concurrency_for("x", base=3) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adaptive_concurrency.py -v`
Expected: FAIL (method does not exist).

- [ ] **Step 3: Implement**

`selector_health.py`:

```python
def concurrency_for(self, site_name: str, base: int = 3) -> int:
    site = self.sites.get(site_name)
    if site is None:
        return max(1, base)
    if not site.is_healthy or site.consecutive_failures >= 5:
        return 1
    if site.consecutive_failures >= 2:
        return max(1, base // 2)
    return max(1, base)
```

`playwright_searcher.py`: replace the single global semaphore with per-site concurrency. Simplest correct approach: keep a global cap of `base` but acquire a per-site semaphore sized by `concurrency_for(site.name, base)` inside `run_site`. Or simpler: compute `concurrency = max(1, min(base, concurrency_for(site.name, base)))` per site and gate each site's search with its own `asyncio.Semaphore(1)`-style serialisation only when unhealthy. Recommended: per-site semaphore of size `concurrency_for(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adaptive_concurrency.py -v`

- [ ] **Step 5: Run full suite + mypy**

Run: `python -m mypy src --no-incremental && python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add src/diagnostics/selector_health.py src/searcher/playwright_searcher.py tests/test_adaptive_concurrency.py
git commit -m "feat(search): adaptive per-site concurrency based on recorded health"
```

---

### Task 6: Plugin-style adapter registration via entry points

**Files:**
- Modify: `src/searcher/adapters/__init__.py` (load third-party adapters from `ads.adapters` entry point group)
- Modify: `pyproject.toml` (declare `[project.entry-points."ads.adapters"]`)
- Test: `tests/test_adapter_plugins.py` (new)

**Interfaces:**
- Consumes: existing `ADAPTER_REGISTRY`, `get_adapter`.
- Produces: `load_entry_point_adapters()` called once at import; registry is populated from both the built-in dict and any `ads.adapters` entry points (entry point name = adapter key).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adapter_plugins.py
import importlib.metadata as md
from unittest.mock import patch
from src.searcher.adapters import ADAPTER_REGISTRY, load_entry_point_adapters

def test_load_entry_point_adapters_registers_external(monkeypatch):
    class FakeEP:
        name = "acme"
        def load(self):
            class Acme: pass
            return Acme
    monkeypatch.setattr(md, "entry_points", lambda group=None: [FakeEP()] if group == "ads.adapters" else [])
    load_entry_point_adapters()
    assert "acme" in ADAPTER_REGISTRY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_plugins.py -v`
Expected: FAIL (function does not exist).

- [ ] **Step 3: Implement**

`adapters/__init__.py`:

```python
import importlib.metadata as _md

def load_entry_point_adapters() -> None:
    try:
        eps = _md.entry_points(group="ads.adapters")
    except TypeError:  # Python < 3.10 fallback
        eps = _md.entry_points().get("ads.adapters", [])
    for ep in eps:
        try:
            ADAPTER_REGISTRY[ep.name] = ep.load()
        except Exception as exc:  # noqa: BLE001 - one bad plugin must not break core
            logger.warning("Failed to load adapter plugin %s: %s", ep.name, exc)

load_entry_point_adapters()
```

`pyproject.toml`: add `[project.entry-points."ads.adapters"]` section (empty by default; document how to add one).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_plugins.py -v`

- [ ] **Step 5: Run full suite + mypy**

Run: `python -m mypy src --no-incremental && python -m pytest -q`

- [ ] **Step 6: Commit**

```bash
git add src/searcher/adapters/__init__.py pyproject.toml tests/test_adapter_plugins.py
git commit -m "feat(adapters): load third-party adapters via ads.adapters entry points"
```

---

## Self-Review

1. **Spec coverage:** Every open T1 review issue maps to a task (enum → T1; SystemChannel/watchlist/coordinator/playwright → T2; config/currency/llm → T3; deps/legacy keys/sqlite → T4). Roadmap items (adaptive concurrency → T5; plugin adapters → T6). The `heavy-sqlite-utils` and `transitive-deps` issues are inside T4. The `legacy_llm_config_keys` issue is inside T4. Good coverage.

2. **Step scan:** Each step either gives a test (name + assertions), a signature + file + pinned values, a command + expected output, or a commit. No "TBD"/"handle edge cases" lines. T4's `Table`-shim approach is a choice left to the implementer — acceptable because the signature and tests determine the rest.

3. **Type consistency:** `matches_condition(condition: Condition | str)` consistent across base/filter_engine/price_tracker/cli. `concurrency_for(site_name, base=3) -> int` consistent. `DealLike` protocol fields match `Deal`'s attributes. Good.

4. **Review Focus → tests:**
   - #1 (no health data) → `test_unknown_site_gets_base_concurrency` (T5).
   - #2 (enum vs string) → `test_condition_any_matches_regardless_of_input_form` (T1).
   - #3 (crash → skipped) → needs a test in T2 (add `test_crashed_site_appears_in_skipped` to `test_error_contracts.py`).
   - #4 (watchlist failure surfaces) → `test_watchlist_save_failure_propagates` (T2).
   - #5 (sqlite-utils removal preserves data) → `test_existing_v6_db_still_readable` (T4, currently a stub — must be filled with a real fixture before implementation).

5. **Proportion:** Plan is ~1/3 the length of the deep-research analysis doc; code blocks are signatures/tests, not full implementations. Acceptable.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-08-app-improvement-plan.md`. Please review the plan. Does it capture what you want?

If approved, recommended execution: **Subagent-driven** (6 independent tasks, each with its own test cycle and reviewer gate; a shipped mistake in the error-contract or storage layer would corrupt user data). Alternatively **Native** (single session, fastest, one final review).
