# Prompt-Only Search and Launcher Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user search with one natural-language prompt — the model infers condition (already works) and category (new) — and start everything through `ask` / `search.bat` / `search.sh` interactive launchers.

**Architecture:** The existing single LLM filter-extraction call gains a `category` key; `resolve_request` in `filters.py` validates it and everything else keeps the current merge chain (`config < prompt < CLI`). The body of `_run_async` is extracted into a shared `run_search` coroutine with two display hooks (`brief`, `plan`) so the new `ask` wizard and the untouched `run` command call the same code. `.bat`/`.sh` launchers are thin Python-discovery wrappers around `ask`.

**Tech Stack:** Python 3.11+, Typer, pytest, ruff; batch (cmd) and POSIX shell scripts.

**Spec:** `docs/specs/2026-10-26-prompt-only-search-design.md`

## Global Constraints

- Baseline before this work: `509 passed, 11 skipped`; the suite must stay green.
- No new third-party dependency.
- Category inference rides on the LLM call that already extracts filters — never a second request per run.
- Offline is sacred: without an LLM every command behaves exactly as today (category `any`).
- `run` keeps its observable output string `Found {N} deals. Results in {dir}/` and all flags; only `--category`'s default changes from `"any"` to auto-inference. `--category any` remains an explicit "search everything".
- Canonical categories, verbatim: `electronics`, `appliances`, `auto`, `home`, `hobby`, `general` (spec 5.1). Validation rejects anything else silently → `None` → `any`.
- `.bat` files: ASCII-only messages, CRLF; `.sh` files: one script usable on Linux and macOS.
- Report labels and CLI copy stay English.
- Scoped `ruff check` must pass on every touched file (repo has ~215 pre-existing findings elsewhere; check only changed paths).
- `tests/test_search_filters.py` calls `resolve_filters` directly — it must keep working unchanged.

## Review Focus

- **The LLM returns `category` in the wrong shape** — `" Electronics "`, `"Electronics"`, `["electronics"]`, `12` — must normalise or drop to `None`; it must never reach `SearchFilters.extras` and never crash the run.
- **No LLM at all / extraction raises** — the run behaves exactly as today: category `any`, and the wizard's summary states that no inference happened.
- **`ask` on piped stdin / EOF** (launcher closed, double-click quirks) — clean `Aborted.`, exit 1, the browser never launches.
- **Explicit `--category any` must suppress inference** even when the model confidently says `electronics`.
- **Old wrapper calls keep working**: `run_once.ps1 -Prompt x -Condition used` behaves as before; `-Prompt x` (new style) gains inference instead of forced `any`.
- **A mis-guessed category is visible before the search**: the wizard prints `Understood: ... category=...` and the chosen shops *before* the first page loads, so the user can abort and re-run with `--category any`.

---

### Task 1: ResolvedRequest — infer the category from the filter-extraction call

**Files:**
- Modify: `src/searcher/filters.py` (the `resolve_filters` block at the end of the file)
- Modify: `src/llm/client.py` — `extract_search_filters` system prompt
- Test: `tests/test_resolve_request.py`

**Interfaces:**
- Consumes: `parse_filters_from_text`, `filters_from_mapping`, `merge_filters`, `SearchFilters` (all already in `filters.py`); `LLMClient.extract_search_filters(prompt) -> dict`.
- Produces:
  - `CATEGORIES: tuple[str, ...] = ("electronics", "appliances", "auto", "home", "hobby", "general")` in `src/searcher/filters.py`.
  - `ResolvedRequest` frozen dataclass: `filters: SearchFilters`, `category: str | None`.
  - `async resolve_request(prompt: str, cli_filters: SearchFilters | None, llm: Any = None) -> ResolvedRequest`.
  - `resolve_filters(prompt, cli_filters, llm=None) -> SearchFilters` — kept as a thin wrapper returning `resolve_request(...).filters`.
  - The extraction system prompt now also lists `category (electronics|appliances|auto|home|hobby|general)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolve_request.py
import pytest

from src.searcher.filters import CATEGORIES, SearchFilters, resolve_filters, resolve_request


class StubLLM:
    def __init__(self, payload):
        self.payload = payload

    async def extract_search_filters(self, prompt):
        return self.payload


class BrokenLLM:
    async def extract_search_filters(self, prompt):
        raise RuntimeError("429")


@pytest.mark.asyncio
async def test_valid_category_is_returned_folded():
    req = await resolve_request(
        "notebook", SearchFilters(), StubLLM({"category": " Electronics "})
    )
    assert req.category == "electronics"


@pytest.mark.asyncio
async def test_uppercase_and_accented_spellings_normalise():
    req = await resolve_request("notebook", SearchFilters(), StubLLM({"category": "Hobby"}))
    assert req.category == "hobby"


@pytest.mark.asyncio
async def test_category_outside_the_enum_is_dropped():
    for bad in ("drone", "", None, 12):
        req = await resolve_request("notebook", SearchFilters(), StubLLM({"category": bad}))
        assert req.category is None, bad


@pytest.mark.asyncio
async def test_category_list_is_dropped():
    req = await resolve_request("notebook", SearchFilters(), StubLLM({"category": ["electronics"]}))
    assert req.category is None


@pytest.mark.asyncio
async def test_category_never_reaches_extras():
    req = await resolve_request(
        "notebook", SearchFilters(), StubLLM({"category": "electronics", "max_price": 300})
    )
    assert req.filters.max_price == 300.0
    assert req.category == "electronics"
    assert "category" not in req.filters.extras


@pytest.mark.asyncio
async def test_broken_or_missing_llm_yields_no_category():
    assert (await resolve_request("pc", SearchFilters(), BrokenLLM())).category is None
    assert (await resolve_request("pc", SearchFilters(), None)).category is None


@pytest.mark.asyncio
async def test_cli_filters_still_win_over_prompt():
    req = await resolve_request("pc do 300 eur", SearchFilters(max_price=100), None)
    assert req.filters.max_price == 100.0


def test_categories_constant_matches_spec():
    assert CATEGORIES == ("electronics", "appliances", "auto", "home", "hobby", "general")


def test_resolve_filters_wrapper_is_unchanged():
    import asyncio

    result = asyncio.run(
        resolve_filters("pc", SearchFilters(max_price=300), StubLLM({"category": "electronics"}))
    )
    assert isinstance(result, SearchFilters)
    assert result.max_price == 300.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_resolve_request.py -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_request'` (collection error)

- [ ] **Step 3: Implement in `filters.py`**

Move the body of the current `resolve_filters` into `resolve_request`: keep `parsed = parse_filters_from_text(prompt)`, keep the `hasattr(llm, "extract_search_filters")` guard and the `except Exception` catch, but read `raw_category = payload.pop("category", None)` **before** `filters_from_mapping(payload)` (an un-popped key would leak into `extras` — see the unknown-key tail of `filters_from_mapping`). Validate with `fold(str(raw))` after an `isinstance(raw, str)` check; a value not in `CATEGORIES` becomes `None` with a `logger.debug`. On the exception path category is `None`. Return `ResolvedRequest(filters=merged.validate(), category=category)`. `resolve_filters` becomes `(await resolve_request(...)).filters`. Module-top constant `CATEGORIES`.

- [ ] **Step 4: Add `category` to the extraction prompt**

In `src/llm/client.py`, extend the `extract_search_filters` system string after `condition (...)` with `category (electronics|appliances|auto|home|hobby|general), ` — one string edit, no logic change. Append to `tests/test_resolve_request.py`:

```python
@pytest.mark.asyncio
async def test_extraction_prompt_asks_for_category(monkeypatch):
    from src.config.models import AppConfig
    from src.llm.client import LLMClient

    captured = {}

    async def fake_chat_json(self, system, user, **kwargs):
        captured["system"] = system
        return {}

    monkeypatch.setattr(LLMClient, "chat_json", fake_chat_json)
    await LLMClient(AppConfig()).extract_search_filters("notebook")
    assert "category (electronics|appliances|auto|home|hobby|general)" in captured["system"]
```

This mirrors how `tests/test_llm_*.py` already builds clients; `AppConfig()` has defaults so no config file is read by the constructor (and `chat_json` never runs, so no network).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_resolve_request.py tests/test_search_filters.py -q`
Expected: PASS — new tests green, old `resolve_filters` tests untouched and green

- [ ] **Step 6: Full suite and commit**

Run: `python -m pytest -q` → expected: all pass (0 failures).
Run: `python -m ruff check src/searcher/filters.py src/llm/client.py tests/test_resolve_request.py` → expected: All checks passed!

```bash
git add src/searcher/filters.py src/llm/client.py tests/test_resolve_request.py
git commit -m "feat(filters): let the LLM propose the search category"
```

---

### Task 2: Wire inference into `run` — default auto, explicit wins, invalid fails

**Files:**
- Modify: `src/cli/app.py` — `run` signature, `_resolve_runtime_filters`, `_run_async` (its filter/category section), `diamond_search_async` and `_search_async` (unpacking only)
- Test: `tests/test_run_category.py`

**Interfaces:**
- Consumes: `resolve_request`, `ResolvedRequest`, `CATEGORIES` from Task 1.
- Produces:
  - `_resolve_runtime_filters(...) -> ResolvedRequest` (was `SearchFilters`): merges config/prompt/CLI filters exactly as before and carries the inferred category.
  - `run --category` default is now `None` (= auto); allowed explicit values are `CATEGORIES + ("any",)`.
  - Effective category inside `_run_async`: `category if category else (resolved.category or "any")` — explicit `"any"` therefore suppresses inference.

- [ ] **Step 1: Write the failing test**

`tests/test_run_category.py` drives the real `run` command through Typer with the whole search pipeline stubbed. The pattern mirrors `tests/test_cli_flags.py` (CliRunner + monkeypatch) but stubs deeper, so filters and category really flow:

```python
import importlib

from typer.testing import CliRunner

from src.config.models import AppConfig

app_module = importlib.import_module("src.cli.app")
runner = CliRunner()


class StubLLMClient:
    def __init__(self, config, payload=None):
        self.payload = payload if payload is not None else {}

    async def extract_search_filters(self, prompt):
        return self.payload


class FakeSearcher:
    calls = []

    def __init__(self, config, llm, storage, browser_mgr):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def search(self, prompt, condition, category, filters, on_sites=None):
        FakeSearcher.calls.append({"condition": condition, "category": category})
        return []


class FakeStorage:
    def __init__(self, path):
        pass

    def prune_missing(self, **kwargs):
        pass

    def save_deal(self, deal):
        pass


class FakeBrowser:
    def __init__(self, config):
        pass

    async def close(self):
        pass


def _setup(monkeypatch, tmp_path, payload):
    config = AppConfig()
    config.output.directory = str(tmp_path)
    monkeypatch.setattr(app_module, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(
        app_module, "LLMClient", lambda cfg: StubLLMClient(cfg, payload)
    )
    monkeypatch.setattr(app_module, "PlaywrightSearcher", FakeSearcher)
    monkeypatch.setattr(app_module, "StorageManager", FakeStorage)
    monkeypatch.setattr(app_module, "BrowserManager", FakeBrowser)
    FakeSearcher.calls = []
    return config


def test_inferred_category_reaches_the_searcher(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"category": "hobby"})
    result = runner.invoke(app_module.app, ["run", "--prompt", "horsky bicykel"])
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "hobby"


def test_explicit_category_beats_inference(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"category": "hobby"})
    result = runner.invoke(
        app_module.app, ["run", "--prompt", "x", "--category", "electronics"]
    )
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "electronics"


def test_any_suppresses_inference(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"category": "hobby"})
    result = runner.invoke(
        app_module.app, ["run", "--prompt", "x", "--category", "any"]
    )
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "any"


def test_unknown_explicit_category_fails_before_searching(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {})
    result = runner.invoke(app_module.app, ["run", "--prompt", "x", "--category", "bicycle"])
    assert result.exit_code == 1
    assert "electronics" in result.output
    assert FakeSearcher.calls == []


def test_no_llm_category_stays_any(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {})
    result = runner.invoke(app_module.app, ["run", "--prompt", "x"])
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "any"
```

`run` constructs `LLMClient(config)` — the stub's `__init__` signature must match that call. `ResultProcessor` stays real (writes an empty report into `tmp_path`; its slug step swallows the missing `_filename_slug_async` by design).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run_category.py -q`
Expected: FAIL — `inferred_category_reaches_the_searcher` gets `"any"` (no wiring yet); `unknown_explicit_category_fails_before_searching` exits 0 (no validation yet). `test_any_suppresses_inference` and `test_explicit_category_beats_inference` may pass accidentally today — they pin the contract, not the bug.

- [ ] **Step 3: Implement in `app.py`**

- `run`: `category: str | None = typer.Option(None, "--category", "-cat", help="Pin the category (electronics, appliances, auto, home, hobby, general). 'any' searches everything; omit it to let the model infer.")`.
- `_resolve_runtime_filters`: call `resolve_request(prompt, SearchFilters(), llm)` instead of `resolve_filters`; build the merged filters as before; return `ResolvedRequest(filters=merged, category=resolved.category)`. Update its three call sites (`run`, `diamond_search_async`, `_search_async`) to unpack `resolved.filters` — diamond and `search` keep passing their own `--category` flag through untouched (no inference there yet).
- In `_run_async`, right where the effective condition is chosen (the `if condition == "any" and filters.condition:` line): compute `effective_category = category if category else (resolved.category or "any")` after validation, and pass it to `searcher.search`.
- Validation: call `_validate_category_arg(category)` as the first statement inside the `try:` block that already resolves filters and ends with `except ValueError as exc: typer.echo(f"Error: {exc}", err=True); raise typer.Exit(1)`. So `_validate_category_arg` raises `ValueError(f"unknown category '{category}'. Allowed: any, {', '.join(CATEGORIES)}")` and reuses that existing error path — no new echo/exit code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_category.py tests/test_cli_flags.py -q`
Expected: PASS — new tests green; the `_run_async`-monkeypatching CLI wiring tests unchanged.

- [ ] **Step 5: Full suite, ruff, commit**

Run: `python -m pytest -q` → all pass. Run scoped ruff on `src/cli/app.py tests/test_run_category.py` → clean.

```bash
git add src/cli/app.py tests/test_run_category.py
git commit -m "feat(cli): infer the search category from the prompt"
```

---

### Task 3: Shared `run_search` runner with `brief` and `plan` hooks

**Files:**
- Modify: `src/cli/app.py` — extract `_run_async`'s body into `run_search`; `_run_async` becomes a thin wrapper
- Modify: `src/searcher/playwright_searcher.py` — `search()` and `_execute_round()` gain `on_sites`
- Test: `tests/test_run_category.py` (extend), `tests/test_playwright_searcher_filters.py` (extend one test)

**Interfaces:**
- Consumes: `ResolvedRequest` (Task 1), effective-category logic (Task 2), the FakeSearcher harness (Task 2's `_setup`).
- Produces:
  - `@dataclass class SearchBrief: filters: SearchFilters; condition: str; category: str` and `@dataclass class SearchOutcome: deal_count: int; sites: list[str]; json_path: str; md_path: str; results_dir: str` in `src/cli/app.py`.
  - `async def run_search(prompt: str, *, condition: str = "any", category: str | None = None, winners: int | None = None, output_format: str | None = None, min_price: str | None = None, max_price: str | None = None, brand: str | None = None, location: str | None = None, shipping: str | None = None, seller_type: str | None = None, sort: str | None = None, extra_filters: list[str] | None = None, country: str | None = None, max_sites: int | None = None, domain: str | None = None, brief: Callable[[SearchBrief], None] | None = None, plan: Callable[[list[str]], None] | None = None) -> SearchOutcome`.
  - `_run_async` keeps its exact current signature (positional order unchanged — `tests/test_cli_flags.py` asserts positional args).
  - `PlaywrightSearcher.search(self, prompt, condition="any", category="any", filters=None, on_sites: Callable[[list[str]], None] | None = None)`; `_execute_round(self, query, condition, category, seen_urls, filters, on_sites=None)` calls `on_sites([site.name for site in sites])` immediately after `_select_sites` returns; `search` forwards `on_sites` **only to its first round**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_category.py` (reuse `_setup`; extend `FakeSearcher.search` to call `on_sites(["alza"])` when given — add that to the existing stub now, guarded by the parameter so old tests stay green):

```python
def test_run_command_output_is_unchanged(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {})
    result = runner.invoke(app_module.app, ["run", "--prompt", "x"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Found 0 deals. Results in")


def test_run_search_returns_outcome_and_fires_brief(monkeypatch, tmp_path):
    import asyncio

    config = _setup(monkeypatch, tmp_path, {"category": "hobby", "max_price": 300})
    seen_briefs = []
    seen_sites = []
    outcome = asyncio.run(
        app_module.run_search(
            "notebook do 300",
            brief=lambda b: seen_briefs.append(b),
            plan=lambda names: seen_sites.extend(names),
        )
    )
    assert outcome.deal_count == 0
    assert seen_briefs[0].category == "hobby"
    assert seen_briefs[0].filters.max_price == 300.0
    assert seen_sites == ["alza"]
```

Append to `tests/test_playwright_searcher_filters.py`: inside the existing `_execute_round` test module, a small unit test for the new parameter — build a searcher the same way that file's current `_execute_round` test does, call `searcher._execute_round("q", "any", "any", set(), None, on_sites=names.append)` and assert `names == ["<the site name the test fixture registers>"]`. Read the existing test's fixture (it already patches browser/page and `get_adapter`) and copy its construction verbatim; the only new argument is `on_sites`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_category.py tests/test_playwright_searcher_filters.py -q`
Expected: FAIL — `AttributeError: module 'src.cli.app' has no attribute 'run_search'`; the `_execute_round` test fails with `TypeError: unexpected keyword 'on_sites'`.

- [ ] **Step 3: Implement the extraction**

Move the whole `_run_async` body from `config = load_config()` down to the `save_results` call into `async def run_search(prompt, *, ...)` with the signature above; `_run_async(prompt, prompt_file, condition, category, ...)` keeps its signature, resolves `prompt_file` (that part stays), calls `outcome = await run_search(prompt, condition=condition, category=category, ...)`, and keeps the observable echo there: `typer.echo(f"Found {outcome.deal_count} deals. Results in {outcome.results_dir}/")` — `run`'s output is unchanged because the echo simply moved to the wrapper. `run_search` computes the effective condition/category exactly as `_run_async` does now, builds `SearchBrief(filters=..., condition=..., category=...)`, calls `brief(brief_)` if given, and passes `on_sites` through to `searcher.search(..., on_sites=_capture_plan)` where `_capture_plan` appends names into the local `sites` list (deduplicated) returned in `SearchOutcome` and forwards to `plan`. `run_search` itself prints nothing, so `ask` owns its own summary/result lines. `config` handling: `run_search` calls `load_config()` itself; the country/max-sites overrides move in unchanged; `results_dir` in the outcome is `config.output.directory`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_category.py tests/test_playwright_searcher_filters.py tests/test_cli_flags.py -q`
Expected: PASS — Task 2's five tests still green (they drive `run`), `_run_async` monkeypatch tests green, `FakeSearcher.calls[0]` shape unchanged.

- [ ] **Step 5: Full suite, ruff, commit**

```bash
git add src/cli/app.py src/searcher/playwright_searcher.py tests/test_run_category.py tests/test_playwright_searcher_filters.py
git commit -m "refactor(cli): share one run_search between run and the wizard"
```

---

### Task 4: The `ask` wizard

**Files:**
- Create: `src/cli/app.py` — new `ask` command + `_ask_async`
- Test: `tests/test_ask.py`

**Interfaces:**
- Consumes: `run_search`, `SearchBrief`, `SearchOutcome` (Task 3), `load_config`, `typer.prompt` (click semantics: a prompt without default re-prompts on empty and raises `Abort` at EOF; `type=int` re-prompts on garbage).
- Produces: `python -m src.cli ask` interactive wizard; `_ask_async(country: str | None, max_sites: int | None) -> None`. Optional seeds `--country`, `--max-sites` skip their question when given.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ask.py
import importlib

from typer.testing import CliRunner

from src.config.models import AppConfig

app_module = importlib.import_module("src.cli.app")
runner = CliRunner()


def _stub(monkeypatch, tmp_path):
    calls = {}
    config = AppConfig()
    config.output.directory = str(tmp_path)
    monkeypatch.setattr(app_module, "load_config", lambda *a, **k: config)

    async def fake_run_search(prompt, *, condition="any", category=None,
                              country=None, max_sites=None, brief=None, plan=None,
                              **kwargs):
        calls["prompt"] = prompt
        calls["country"] = country
        calls["max_sites"] = max_sites
        from src.cli.app import SearchBrief

        brief(SearchBrief(filters=__import__("src.searcher.filters", fromlist=["SearchFilters"]).SearchFilters(max_price=200.0, condition="used"),
                          condition="used", category="hobby"))
        plan(["bazos"])
        from src.cli.app import SearchOutcome

        return SearchOutcome(deal_count=3, sites=["bazos"], json_path="j",
                             md_path="m", results_dir="d")

    monkeypatch.setattr(app_module, "run_search", fake_run_search)
    return calls


def test_ask_prompts_once_and_prints_the_summary(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(
        app_module.app, ["ask"], input="horské kolo used do 200\n\n\n"
    )
    assert result.exit_code == 0, result.output
    assert calls["prompt"] == "horské kolo used do 200"
    out = result.output
    assert "Understood:" in out and "condition=used" in out and "category=hobby" in out
    assert "Shops: bazos" in out
    assert "Found 3 deals" in out


def test_ask_empty_prompt_reprompts(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="\n  \nnotebook\n\n\n")
    assert result.exit_code == 0, result.output
    assert calls["prompt"] == "notebook"


def test_ask_seeds_skip_questions(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(
        app_module.app, ["ask", "--country", "CZ", "--max-sites", "4"], input="kolo\n"
    )
    assert result.exit_code == 0, result.output
    assert calls["country"] == "CZ"
    assert calls["max_sites"] == 4


def test_ask_non_numeric_max_sites_reprompts(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="kolo\nSK\nabc\n7\n")
    assert result.exit_code == 0, result.output
    assert calls["max_sites"] == 7


def test_ask_aborts_cleanly_at_eof(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="")
    assert result.exit_code != 0
    assert "prompt" not in calls
```

If `runner`'s CliRunner needs `mix_stderr`, mirror whatever `tests/test_run_category.py` already uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ask.py -q`
Expected: FAIL — Typer reports `No such command 'ask'` (exit code 2).

- [ ] **Step 3: Implement**

In `src/cli/app.py`:

```python
@app.command()
def ask(
    country: str | None = typer.Option(None, "--country", help="Skip the country question"),
    max_sites: int | None = typer.Option(None, "--max-sites", help="Skip the max-shops question"),
):
    """Prompt-only search: describe what you want, the app infers the rest."""
    asyncio.run(_ask_async(country, max_sites))


async def _ask_async(country, max_sites):
    config = load_config()
    prompt = typer.prompt("What are you looking for?").strip()
    while not prompt:
        prompt = typer.prompt("Please type a description of what you want.").strip()
    if not country:
        country = typer.prompt("Country", default=config.search.user_country)
    if max_sites is None:
        max_sites = typer.prompt(
            "Max shops", default=config.search.max_sites, type=int
        )
    ...
```

The loop re-prompts empty answers itself (so whitespace counts as empty); EOF inside `typer.prompt` raises click's `Abort` — Typer prints `Aborted.` and exits 1, matching the Review Focus without extra code. Then the body:

- define `_brief(b): print("Understood: " + ", ".join(parts))` where `parts` are `condition=<x>` / `category=<x>` plus every non-None of `min_price, max_price, brand, location, shipping, seller_type, sort` on `b.filters` formatted `key=value`; when `b.category == "any"` append `" (no category inferred — searching every shop that fits)"`;
- define `_plan(names): typer.echo("Shops: " + ", ".join(names))`;
- `outcome = await run_search(prompt, country=country.upper(), max_sites=max_sites, brief=_brief, plan=_plan)` (condition/category stay default here — inference);
- after it: `typer.echo(f"Found {outcome.deal_count} deals. Results in {outcome.results_dir}/")` and then the two report paths, one per line (`outcome.json_path`, `outcome.md_path`). `run_search` prints nothing itself (Task 3), so the wizard owns these lines.

Click prints the default in the question (`show_default`) — keep Typer's default behaviour, no custom hints.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ask.py -q`
Expected: PASS

- [ ] **Step 5: Full suite, ruff, commit**

```bash
git add src/cli/app.py tests/test_ask.py
git commit -m "feat(cli): add the prompt-only ask wizard"
```

---

### Task 5: Launcher scripts

**Files:**
- Create: `scripts/search.bat`
- Create: `scripts/search.sh`
- Modify: `scripts/run_once.ps1` — default `""` for `$Condition`/`$Category`, forward only when set
- Test: `tests/test_launchers.py`

**Interfaces:**
- Consumes: `python -m src.cli ask` (Task 4).
- Produces: double-clickable / `./scripts/search.sh` entry points; `run_once.ps1` without `-Condition`/`-Category` no longer forces `any`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_launchers.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(name: str) -> bytes:
    return (ROOT / "scripts" / name).read_bytes()


def test_search_bat_is_ascii_and_launches_ask():
    raw = read("search.bat")
    raw.decode("ascii")  # no codepage traps
    assert b"\r\n" in raw
    text = raw.decode()
    assert "src.cli ask" in text
    assert "py -3" in text  # the setup.bat discovery fallback


def test_search_sh_launches_ask_on_linux_and_macos():
    text = read("search.sh").decode("utf-8")
    assert "#!/usr/bin/env bash" in text
    assert "src.cli ask" in text
    assert "python3" in text


def test_run_once_forwards_filters_only_when_given():
    text = read("run_once.ps1").decode("utf-8")
    assert '[string]$Condition = ""' in text
    assert '[string]$Category = ""' in text
    assert 'if ($Condition)' in text
    assert 'if ($Category)' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_launchers.py -q`
Expected: FAIL — `FileNotFoundError: ...scripts\search.bat`

- [ ] **Step 3: Write the scripts**

`scripts/search.bat` (save with CRLF; ASCII only):

```bat
@echo off
REM Prompt-only deal search - Windows launcher.
cd /d "%~dp0.."

set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Install Python 3.11+ or run scripts\setup.bat first.
    exit /b 1
  )
  set "PY=py -3"
)

%PY% -m src.cli ask
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
```

`scripts/search.sh`:

```bash
#!/usr/bin/env bash
# Prompt-only deal search - Linux/macOS launcher.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "python3 not found. Install Python 3.11+ or run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$PY" -m src.cli ask
```

`run_once.ps1`: change `[string]$Condition = "any"` and `[string]$Category = "any"` to `""` and replace the always-appended `$args += @("--condition", $Condition, "--category", $Category)` with two guarded appends (`if ($Condition) { $args += @("--condition", $Condition) }`, same for `$Category`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_launchers.py -q` → PASS
Syntax-check the shell script: `bash -n scripts/search.sh` → expected: exit 0, no output. (On this Windows box bash may be absent — run it under Git Bash if available; otherwise record the skip honestly in the commit notes.) `search.bat` cannot be executed in the dev environment — the user double-clicks it once during Task 6 verification; say so plainly rather than claiming it tested.

- [ ] **Step 5: Commit**

```bash
git add scripts/search.bat scripts/search.sh scripts/run_once.ps1 tests/test_launchers.py
git commit -m "feat(scripts): add search.bat and search.sh launcher scripts"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` — "Single Run (Manual)" examples, new "Prompt-only search" and "Launcher scripts" subsections
- Modify: `CHANGELOG.md` — Added entries

**Interfaces:**
- Consumes: the final behaviour from Tasks 1-5.
- Produces: user-facing copy only.

- [ ] **Step 1: README**

Under `## Usage`:
- in "Single Run (Manual)", add the new first example:
  `python -m src.cli run --prompt "DJI drone refurbished under 350 euros"` with a line saying condition, category, price and the rest are read from the prompt; the explicit flags remain as overrides (`--category any` forces all shops).
- new `### Prompt-only search` subsection: describe `ask` and its three questions (prompt required; country and max-shops press-Enter defaults; the `Understood:` line shows what the model read, the shop list prints before anything opens).
- new `### Launcher scripts` subsection: `scripts\search.bat` (Windows, double-click), `./scripts/search.sh` (Linux/macOS, first run `chmod +x`), what they run (`src.cli ask`), and the note that no LLM is still a full search with `category=any`.

- [ ] **Step 2: CHANGELOG**

Under `### Added`:
- Category inference: `run --prompt "..."` without `--category` lets the model pick the shop category on the same LLM call that already extracts filters; `--category any` keeps the old broad behaviour; invalid values list the allowed ones.
- `ask` command: prompt-only wizard that echoes what it understood and the selected shops before searching.
- `scripts/search.bat` / `scripts/search.sh` launchers; `run_once.ps1` stops forcing `--condition/--category any`.

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: describe prompt-only search and the launcher scripts"
```

---

### Task 7: Final verification

**Files:**
- Modify: `CHANGELOG.md` — verification line only

- [ ] **Step 1: Full suite**

Run: `python -m pytest -q`
Expected: all pass, 0 failures. Record the exact counts for the CHANGELOG line.

- [ ] **Step 2: Scoped ruff**

Run: `python -m ruff check src/searcher/filters.py src/llm/client.py src/cli/app.py src/searcher/playwright_searcher.py tests/test_resolve_request.py tests/test_run_category.py tests/test_ask.py tests/test_launchers.py`
Expected: `All checks passed!`

- [ ] **Step 3: Live wizard run (no LLM required for the plumbing)**

```powershell
"použité horské kolo 26 palcové do 200 eur`n`n1`n" | python -m src.cli ask --country SK
```

Expected: an `Understood:` line (condition at minimum `used` from the deterministic parser; category may be `any` when no LLM answered), a `Shops:` line, a `Found N deals.` line and a report in `results/`. If LM Studio answers, `category=hobby` should appear — either outcome is recorded, not judged.

- [ ] **Step 4: Live `run` without category (old command, new default)**

```powershell
$env:ADS_LOCAL_POLICY = "never"
python -m src.cli run --prompt "horsky bicykel 26 palcovy repasovany"
```

Expected: exit 0, report written, and the report's `sites` list sane (this is the no-LLM path: category fell back to `any`, exactly today's behaviour — spec G3).

- [ ] **Step 5: Update CHANGELOG, commit**

Set the verification line to Step 1's counts and note the two live runs.

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record prompt-only search verification"
```
