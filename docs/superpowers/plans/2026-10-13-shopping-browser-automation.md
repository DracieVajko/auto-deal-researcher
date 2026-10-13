# Shopping Browser Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure existing Etapa-2 codebase into target modular layout (agents split, notifications split, POM, CLI split) plus test coverage and verification.

**Architecture:** Keep current behavior; move code into spec paths with thin re-export shims for backward compat. Diamond Search coordinator orchestrates research → expertise → price → synthesis with run_id and LLM/call budgets.

**Tech Stack:** Python 3.11+, Playwright chromium, Pydantic v2, Typer, sqlite-utils, pytest + pytest-asyncio

**Spec:** User OpenCode Execution Prompt 2026-10-13 (Shopping Browser Automation) + existing repo at `C:\Users\DracieVajko\Downloads\PC_Commands\AI\PersonalAIDealSearcher`

## Global Constraints
- Python >=3.11 (pyproject requires-python >=3.11).
- Headless by default: `BrowserConfig.headless=True, slow_mo=0`.
- Local-first LLM chain: LM Studio → Ollama → llamacpp → OpenRouter → Gemini → Mistral with 5s fast-failover per provider.
- State stays local: SQLite + JSON watchlist; no external cloud required for core.
- `config.yaml` in .gitignore; ship `config.example.yaml` template only.
- Graceful degradation: selector fail → log and continue; LLM unavailable → rule-based scoring fallback.

## Review Focus
- Adapter selector drift on Alza/eBay/BackMarket returning 0 deals while Bazos works — expect empty-result path to still produce valid JSON+MD.
- Concurrent Diamond Search agents sharing one Playwright context causing state leakage — expect per-page fingerprint isolation.
- LLM budget overrun on 7-agent fan-out — expect early abort when `llm_call_budget` exceeded.
- SQLite `deals.url` PK vs `price_history.deal_id` join mismatch — expect joins on `url`, not integer id.
- Windows Task Scheduler quoting of `--prompt-file` paths with spaces — expect quoted args in install script.

---

### Task 1: Config models + NotificationConfig

**Files:**
- Modify: `src/config/models.py`
- Test: `tests/test_config_models.py`

**Interfaces:**
- Consumes: existing `AppConfig, SearchConfig, DiamondSearchConfig`
- Produces: `NotificationChannelConfig(name, type, cooldown_seconds, rate_limit, settings: dict)`, `NotificationConfig(channels: list, default_cooldown_seconds=3600)`, `AppConfig.notifications: NotificationConfig`; `DiamondSearchConfig.llm_call_budget: int=50, llm_token_budget: int=100000`

- [ ] **Step 1: Write failing test for NotificationConfig defaults**
```python
def test_notification_config_defaults():
    cfg = AppConfig()
    assert cfg.notifications.default_cooldown_seconds == 3600
    assert cfg.search.diamond_search.llm_call_budget == 50
```
- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_config_models.py::test_notification_config_defaults -v`
Expected: FAIL with missing attribute
- [ ] **Step 3: Implement `NotificationChannelConfig, NotificationConfig` in `src/config/models.py`**
Add classes with exact field names above; wire into `AppConfig`.
- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_config_models.py -v`
Expected: PASS
- [ ] **Step 5: Commit**
```bash
git add src/config/models.py tests/test_config_models.py
git commit -m "feat: add NotificationConfig and LLM budget fields"
```

### Task 2: Agents restructure to target layout

**Files:**
- Create: `src/agents/base.py`, `src/agents/research/query_expansion.py`, `src/agents/research/site_selection.py`, `src/agents/research/market_intel.py`, `src/agents/expertise/domain_expert.py`, `src/agents/expertise/latest_tech_tracker.py`, `src/agents/price/price_hunter.py`, `src/agents/synthesis/recommendation.py`, `src/agents/coordinator.py`
- Modify: `src/agents/__init__.py`, `src/agents/research.py`, `src/agents/analysis.py`, `src/agents/synthesis.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `AgentMessage(sender, recipient, payload, run_id)`, `AgentResult`
- Produces: `CoordinatorAgent.run(input: dict with run_id) -> AgentResult`, `QueryExpansionAgent.run`, `SiteSelectionAgent.run`, `MarketIntelAgent.run`, `DomainExpertAgent.run`, `LatestTechTrackerAgent.run`, `PriceHunterAgent.run`, `RecommendationAgent.run`

- [ ] **Step 1: Write failing import test**
```python
def test_agent_imports():
    from src.agents.base import AgentBase, MessageBus
    from src.agents.coordinator import CoordinatorAgent
    assert CoordinatorAgent is not None
```
- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_agents.py::test_agent_imports -v`
Expected: FAIL module not found
- [ ] **Step 3: Implement `src/agents/base.py` by moving AgentBase, MessageBus, AgentMessage, AgentResult from `src/agents/__init__.py`**
Keep `__init__.py` as re-export shim.
- [ ] **Step 4: Split research/ expertise/ price/ synthesis files, implement `coordinator.py` with run_id propagation + `_check_budget/_record_llm_usage`**
Move existing logic verbatim; fix coordinator to reference new paths.
- [ ] **Step 5: Run tests**
Run: `python -m pytest tests/test_agents.py tests/test_basic.py -v`
Expected: PASS
- [ ] **Step 6: Commit**
```bash
git add src/agents tests/test_agents.py
git commit -m "refactor: split agents into research/expertise/price/synthesis layout"
```

### Task 3: Notifications split

**Files:**
- Create: `src/notifications/base.py`, `src/notifications/channels/console.py`, `src/notifications/channels/webhook.py`, `src/notifications/channels/discord.py`, `src/notifications/channels/email.py`, `src/notifications/manager.py`, `src/notifications/rules.py`
- Modify: `src/notifications/__init__.py`
- Test: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `Alert(title, message, severity)`
- Produces: `NotificationChannel.send(message: str) -> None`, `NotificationManager.notify(msg, cooldown_seconds)`, `AlertRule.matches(deal: dict) -> bool`

- [ ] **Step 1: Write failing cooldown test**
```python
async def test_cooldown_dedups():
    mgr = NotificationManager(cooldown_seconds=3600)
    assert await mgr.notify("hi") is True
    assert await mgr.notify("hi") is False
```
- [ ] **Step 2: Run to verify FAIL**
Run: `python -m pytest tests/test_notifications.py -v`
Expected: FAIL import error
- [ ] **Step 3: Move ABC to `base.py`, each channel to `channels/`, manager + rules to own files, keep `__init__.py` re-exports**
- [ ] **Step 4: Run tests**
Run: `python -m pytest tests/test_notifications.py -v`
Expected: PASS
- [ ] **Step 5: Commit**
```bash
git add src/notifications tests/test_notifications.py
git commit -m "refactor: split notifications into channels/manager/rules"
```

### Task 4: Browser POM base + components

**Files:**
- Create: `src/browser/pom/base.py`, `src/browser/pom/components/search_bar.py`, `src/browser/pom/components/product_card.py`, `src/browser/pom/components/filters.py`, `src/browser/pom/components/pagination.py`, `src/browser/pom/components/sort.py`, `src/browser/pom/registry.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: Playwright `Page`
- Produces: `BasePage.goto(), safe_click(), safe_fill(), handle_cookie_consent()`, `SearchBar.search(q)`, `ProductCard.parse() -> Deal`, `Filters.apply()`, `Pagination.next()`, `Sort.apply()`

- [ ] **Step 1: Write failing POM parse test with fixture HTML**
```python
def test_product_card_parse():
    from src.browser.pom.components.product_card import ProductCard
    assert ProductCard.extract_from_html("<div></div>") is not None
```
- [ ] **Step 2: Run to verify FAIL**
Run: `python -m pytest tests/test_browser.py::test_product_card_parse -v`
Expected: FAIL
- [ ] **Step 3: Implement base + 5 components + registry mapping `website.name -> page classes`**
- [ ] **Step 4: Run tests**
Run: `python -m pytest tests/test_browser.py -v`
Expected: PASS
- [ ] **Step 5: Commit**
```bash
git add src/browser/pom tests/test_browser.py
git commit -m "feat: add POM base and e-commerce components"
```

### Task 5: Site-specific POMs

**Files:**
- Create: `src/browser/pom/pages/alza/{home,search_results,product_detail}.py`, `bazos/{home,search_results,listing_detail}.py`, `backmarket/{home,search_results,product_detail}.py`, `ebay/{home,search_results,item_detail}.py`, `facebook/{marketplace_home,search_results,listing_detail}.py`
- Test: extend `tests/test_browser.py`

**Interfaces:**
- Consumes: components from Task 4
- Produces: per-site `Home.goto(), SearchResults.extract_cards() -> list[Deal], ProductDetail.parse()`

- [ ] **Step 1: Write failing registry test**
```python
def test_registry_has_all_sites():
    from src.browser.pom.registry import POM_REGISTRY
    assert set(POM_REGISTRY) >= {"alza","bazos","backmarket","ebay","facebook"}
```
- [ ] **Step 2: Run to verify FAIL**
- [ ] **Step 3: Implement 14 page classes reusing existing adapter selectors**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

### Task 6: Storage models alignment

**Files:**
- Create: `src/storage/models.py`
- Modify: `src/storage/manager.py`, `src/storage/schema.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `Deal`
- Produces: `Deal, PriceHistory, WatchlistItem` dataclasses; `save_deal(), get_deal(), prune_older_than(), record_price_sighting(), get_price_history()`

- [ ] **Step 1: Write failing join test (url-based join)**
- [ ] **Step 2: Run to verify FAIL**
- [ ] **Step 3: Implement models + fix joins to `ph.url=d.url`**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

### Task 7: CLI split

**Files:**
- Create: `src/cli/main.py`, `src/cli/commands/run.py`, `src/cli/commands/monitor.py`, `src/cli/commands/doctor.py`, `src/cli/commands/config_check.py`
- Modify: `src/cli.py`, `src/cli/app.py`, `src/cli/commands/history.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `AppConfig`
- Produces: `python -m src.cli config-check`, `doctor --site`, `run --prompt`, `monitor --max-runs`

- [ ] **Step 1: Write failing CLI invoke test**
- [ ] **Step 2: Run to verify FAIL**
- [ ] **Step 3: Split commands, keep `src/cli.py` as shim**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

### Task 8: Integration + verification

**Files:**
- Create: `tests/test_integration.py`, `OVERNIGHT_EXECUTION_REPORT.md`
- Modify: `requirements.txt`, `README.md`, `config.example.yaml`

**Interfaces:**
- Produces: `pytest -q` green, `config-check` pass, `doctor --site bazos` ≥1 selector, single run creates JSON+MD, monitor 1 iteration

- [ ] **Step 1: Write failing integration test (mock LLM + fixture HTML)**
- [ ] **Step 2: Run full suite**
Run: `python -m pytest -q`
Expected: PASS ≥80% on new modules
- [ ] **Step 3: Run verification commands**
Run: `python -m src.cli config-check`, `python -m src.cli doctor --site bazos`, `python -m src.cli run --prompt "DJI drone under 350 euros" --condition refurbished --category electronics`
Expected: JSON+MD in results/
- [ ] **Step 4: Commit docs**
