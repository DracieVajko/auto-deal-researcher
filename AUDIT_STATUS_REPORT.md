# Auto Deal Searcher — Audit & Status Report

**Date:** 2026-10-14
**Repository:** `C:\Users\DracieVajko\Downloads\PC_Commands\AI\PersonalAIDealSearcher`
**GitHub:** https://github.com/DracieVajko/auto-deal-researcher
**Branch:** `chore/overnight-full-stabilization-20261013` (HEAD `9a559ed`)
**Python:** 3.14.7 (system) — requirements target 3.11/3.12
**Local LLM endpoint:** `http://localhost:1234` (LM Studio; original config pointed at `100.88.219.120`)

<!-- SECTION:EXEC -->
## 1. Executive Summary

The project is a substantial, well-structured Python codebase: 14 `src/` subpackages, 5 site adapters, a 7-agent "Diamond Search" pipeline, SQLite storage with migrations, notifications, history/trends/watchlist, selector-health diagnostics, and a Typer CLI. All 20 unit tests pass and the Bazos adapter works end-to-end.

**However, it is not production-reliable yet.** Key findings from evidence gathered:

- **Bazos is the only adapter that works.** Doctor: 1/4 sites healthy; Alza, BackMarket, eBay return 0 items (selectors/navigation do not match current site DOM).
- **LLM path is effectively broken against local models.** `LLMClient` hardcodes a **5-second** HTTP timeout (`timeout=5`) for every provider. This kills any slow local model (the stated 1–2 t/s case). One request path also hardcodes an OpenRouter/Gemini/Mistral **404/429** legacy fallback that never succeeds.
- **Secrets were NOT committed.** Verified by scanning every blob in `--all`: `config.yaml` is git-ignored and was never tracked with real keys (history holds `api_key: null`); `config.example.yaml` only ever had `YOUR_KEY_HERE` placeholders. Real keys existed only in the local, untracked working-tree `config.yaml` — still a plaintext-secret risk, now remediated (§7.5).
- **Config drift:** `config.yaml` was pointing at an unreachable host; the `model: "auto"` value is not a valid LM Studio model id (LM Studio returns HTTP 400). Both were fixed during this audit.
- **Diamond Search** orchestration and budget tracking exist, but the 7 agents are **mostly hardcoded/stub logic** (fixed DJI/drone data), not real LLM-driven reasoning.
- **POM framework exists structurally but is empty in practice:** site page classes are just aliases to a generic `SiteHome`/`SiteSearchResults`/`SiteProductDetail`.
- Several integration/reliability items from the spec are **absent**: structured JSON logging, graceful shutdown handlers, health endpoint, circuit breaker, session warmup method, integration tests with Testcontainers, fingerprint rotation actually wired to CDP sessions.

**Bottom line:** the scaffolding is comprehensive and tests pass, but the *functional* core (non-Bazos adapters + local LLM client) is the critical path. Fix secrets, the LLM timeout, and the adapters before relying on it.

### 1.1 Addendum (post-audit remediation round)

A second round of empirical probing found a **P0 that blocked all persistence**, which the first-round static review had missed. Reproduced, then fixed:

| # | Defect | Evidence | Status |
|---|---|---|---|
| P0-1 | `deals` table PK is `id`, but code treated `url` as PK → `get_deal()`/`save_deal()` raised `sqlite_utils.NotFoundError` **on every call**. No deal could ever be persisted. | `db["deals"].pks == ['id']`; repro raised `NotFoundError` | ✅ fixed |
| P0-2 | `StoredDeal(**row)` could never bind — rows carry extra `id`/`currency` columns. | `TypeError` path | ✅ fixed (`_row_to_stored_deal`) |
| P0-3 | `sqlite_utils.Database.execute()` returns **plain tuples**, so every `row["col"]` in trends/change-detector failed. | `type(row).__name__ == 'tuple'` | ✅ fixed (`row_factory = sqlite3.Row`) |
| P0-4 | `ChangeDetector._get_deals_for_run()` selected non-existent `ph.site_name` / `ph.title`. | `OperationalError: no such column: ph.site_name` | ✅ fixed (aliased `LEFT JOIN`) |
| P1-5 | `PriceTracker.get_price_trend_for_deal()` called non-existent `storage.get_deal_by_id`. | `AttributeError` | ✅ fixed (method added) |
| P1-6 | `trends.py`: `url_prices` NameError, `last` NameError, wrong positional indices for `title`/`site_name`. | NameError / wrong data | ✅ fixed |
| P1-7 | `db.executemany` does not exist on `Database`. | `AttributeError` | ✅ fixed (`db.conn.executemany`) |
| P0-8 | `LLMClient` hardcoded `timeout=5` on all four HTTP calls. | source + 5s read timeouts in logs | ✅ fixed (`LOCAL_TIMEOUT=900`, `CLOUD_TIMEOUT=60`, env-overridable) |

P0-1/2/3 explain why `history trends` reported *"insufficient data"* despite runs completing: **nothing was ever written**. Root-cause chain, not three unrelated bugs.

**Verification:** `pytest` 20 → **38 passed** (18 new regression tests). End-to-end search → save → trends now persists 3/3 deals and writes 3 price-history rows.

### 1.2 Addendum: adapter remediation (live DOM probing)

Every selector was re-derived from the **live** site, not guessed. Findings:

| Site | Root cause of 0 results | Action | Verified |
|---|---|---|---|
| **Alza** | Two bugs: search URL was `/?q=` (Alza ignores it and serves the homepage) and `/search` is a **404**. Real endpoint is `/search.htm?exps=`. Item class is `.browsingitem`, not `.browsinglink`. | Adapter rewritten | ✅ **10 deals**, correct prices (339/249/422 €), conditions, URLs |
| **eBay** | Class renamed `.s-item` → **`.s-card`** (title `.s-card__title`, price `.s-card__price`). Direct `/sch/i.html` is rate-limited/intermittent. | Selectors updated, search-box warmup + 3 attempts, sponsored/decoy filter | ⚠️ **unreliable** — see below |
| **BackMarket** | Not a selector bug: Cloudflare interstitial (403 → `/testchallengepage`) that never clears (verified 60 s). Locale path is `/sk-sk/search`, not `/search`. | Correct URL, fails fast with reason (**43 s → 0.8 s**) | ❌ not scrapable |
| **Bazos** | Working | unchanged | ✅ 3 deals |

**eBay serves decoy results to scrapers.** Offline verification against a saved "successful" page found 93 `.s-card` nodes that were all placeholders (`ebay.com/itm/123456`, "Shop on eBay", `$20.00`). The adapter now rejects them, but reliable access requires the official Browse API or an affiliate feed. **No anti-bot evasion was implemented** — that is deliberate, both on correctness and on the site's terms.

**Also in this round:**
- `BaseAdapter.parse_price_eur()` — shared parser replacing three divergent inline regexes. Handles NBSP/thin spaces, `1.299,50` vs `1,299.50`, and `EUR 249,00`. (First implementation wrongly returned `1.2995` for `1,299.50`; caught by tests and corrected to "rightmost separator is decimal only when followed by 1–2 digits".)
- `BaseAdapter.detect_block()` + `SiteBlockedError` — adapters now raise a typed error on an interstitial instead of waiting out selector timeouts.
- `PlaywrightSearcher` now feeds `SelectorHealthTracker`, so `history selector` reports real per-site data instead of zeros. `[DEBUG] print(...)` statements removed from `doctor.py`.

**Configuration:** `backmarket` and `ebay` are now `enabled: false` in `config.yaml` with the reason inline. `doctor` reports **2/2 enabled sites healthy**.

<!-- SECTION:STRUCT -->
## 2. Repository Structure

### 2.1 Top-level

```
PersonalAIDealSearcher/
├── .git/  .gitignore  .mypy_cache/  .pytest_cache/  .ruff_cache/  .superpowers/
├── auto_deal_searcher.egg-info/
├── browser_profile/            # Playwright persistent context
├── data/                       # SQLite DB + json state
├── docs/
├── prompts/                    # auto.yaml, example_prompts.md
├── results/                    # JSON/Markdown output
├── scripts/
├── src/                        # 14 subpackages (below)
├── tests/                      # 10 test files
├── config.yaml                 # EXISTS (committed, contains secrets)
├── config.example.yaml         # EXISTS
├── requirements.txt            # EXISTS
├── pyproject.toml              # EXISTS
├── setup.py                    # EXISTS (stale)
├── deals.db                    # stray DB at repo root
├── install_requirements.bat
├── OVERNIGHT_EXECUTION_REPORT.md
└── README.md
```

### 2.2 `src/` package structure (14 subpackages)

| Package | Purpose | Key files |
|---|---|---|
| `src/config/` | Config loading + Pydantic models | `__init__.py`, `models.py` |
| `src/llm/` | LLM client + mock | `client.py`, `mock_client.py` |
| `src/browser/` | Browser mgmt, fingerprint, POM | `manager.py`, `fingerprint.py`, `pom/` |
| `src/searcher/` | Search orchestration + adapters | `playwright_searcher.py`, `adapters/` |
| `src/storage/` | SQLite persistence | `manager.py`, `models.py`, `schema.py` |
| `src/agents/` | 7-agent Diamond Search | `base.py`, `coordinator.py`, `research/`, `expertise/`, `price/`, `synthesis/` |
| `src/notifications/` | Alert channels | `manager.py`, `base.py`, `rules.py`, `channels/` |
| `src/history/` | Watchlist + trends | `watchlist.py`, `trends.py` |
| `src/diagnostics/` | Doctor + selector health | `doctor.py`, `selector_health.py` |
| `src/cli/` | Typer CLI | `app.py`, `main.py`, `commands/` |
| `src/scheduler/` | Cross-platform tasks | `tasks.py` |
| `src/intelligence/` | Change detection, price tracking | `change_detector.py`, `price_tracker.py` |
| `src/output/` | Result processing | `processor.py` |
| `src/utils/` | Time helpers, `__main__.py` | `time.py` |

### 2.3 Existence check

| File | Status |
|---|---|
| `config.yaml` | ✅ EXISTS (contains live secrets — see §6) |
| `config.example.yaml` | ✅ EXISTS |
| `requirements.txt` | ✅ EXISTS |
| `pyproject.toml` | ✅ EXISTS |
| `setup.py` | ✅ EXISTS (stale, see §6) |

All five present. No expected file is missing.

<!-- SECTION:DEPS -->
### 2.4 Dependency audit

`requirements.txt` (25 lines) declares:

```
playwright>=1.44.0   pydantic>=2.9.0     pydantic-core>=2.23.0  greenlet>=3.1.0
typer>=0.12.0        requests>=2.32.0    markdown>=3.6.0        pyyaml
sqlite-utils         aiohttp
pytest>=8.0.0        pytest-cov>=5.0.0   pytest-asyncio
black>=24.0.0        flake8>=7.0.0       ruff                   mypy
```

Verified installed environment (pytest run succeeded): Python 3.14.7, pytest 9.1.1, pytest-asyncio 1.4.0 (STRICT), pytest-cov 7.1.0, anyio 4.15.1.

- ⚠️ **`aiohttp` is imported** (`notifications/channels/discord.py`, `webhook.py`) and listed in `requirements.txt`, but **missing from `pyproject.toml [project].dependencies`** — dependency drift.
- ⚠️ **`setup.py` is stale**: `typer>=0.9.0`, `playwright>=1.30.0`, `pydantic>=2.0.0`, `python>=3.9` vs `pyproject.toml` requires-python `>=3.11`.
- ⚠️ Running on **Python 3.14** while requirements say "3.11/3.12 compatible". Tests pass, but third-party compatibility (Playwright, pydantic-core wheels) is not guaranteed on 3.14.
- Playwright browsers: **work** (BrowserManager launched Chromium successfully, Bazos returned deals), so `playwright install` has been done at least for chromium.

<!-- SECTION:GIT -->
### 2.5 Git state

```
On branch chore/overnight-full-stabilization-20261013
nothing to commit, working tree clean
```

Recent commits (newest first):

```
9a559ed feat: Etapa-2 CLI package split, monitor restore, fingerprint rotation, history/watchlist/selector-health
6e1b1a0 fix: url joins, layer budgets, scheduler quoting, cli entry, per-site fingerprint sessions
6ba87d2 feat: add storage models, CLI split, integration smoke and verification docs
08469d7 refactor: split CLI into main plus run/monitor/doctor/config_check commands
7e2c615 feat: add canonical storage models with url-based joins
cf14eeb feat: add site POMs and registry
12da7e3 feat: add POM base and e-commerce components
4693dda refactor: split notifications into channels/manager/rules
7860976 refactor: split agents into research/expertise/price/synthesis layout
22f4aeb feat: add NotificationConfig and LLM budget fields
```

Branches:

```
* chore/overnight-full-stabilization-20261013   9a559ed  (origin/… same)
  master                                        8b58acd  [origin/master]
```

Working tree clean; work is on a stabilization branch, `master` lags behind. Changes made during this audit (config endpoint/model fix) are **not yet committed** against clean state.

<!-- SECTION:COMPONENTS -->
## 3. Component Analysis (per module)

### 3.1 Configuration (`src/config/`)

Files: `__init__.py`, `models.py`.

- `load_config(config_path="config.yaml")` **exists and works** — returns `AppConfig()` default if file missing, otherwise `AppConfig(**yaml.safe_load(f))`.
- **Enums:** yes — `Condition` (`new, used, refurbished, open_box, marketplace, any`) and `Category` (`electronics, appliances, auto, general, any`), both `StrEnum`.
- **Pydantic classes & key fields:**
  - `WebsiteConfig`: `name, base_url, enabled, adapter_class, categories, conditions, requires_login, extra_params`
  - `LLMLocalConfig`: `type (lmstudio|ollama|llamacpp), endpoint, model="auto"`
  - `LLMAPIConfig`: `provider (openrouter|gemini|mistral), api_key_env, model`
  - `LLMConfig`: `local[], api_fallback[]` + **legacy fields** `local_endpoint, openrouter, gemini, mistral, api_key, model_name`
  - `NotificationChannelConfig` / `NotificationConfig`: `channels[], default_cooldown_seconds` ✅ present
  - `OutputConfig`, `ScheduleTaskConfig`, `ScheduleConfig`, `BrowserConfig` (`cdp_endpoint, use_persistent_context, user_data_dir, headless=True, slow_mo`), `StorageConfig`
  - `DiamondSearchConfig` ✅ present: `enabled, max_rounds=3, research_parallel, expertise_parallel, price_sequential, llm_model_override, confidence_threshold=0.7, llm_call_budget=50, llm_token_budget=100000`
  - `SearchConfig`: `websites[], winners_count=3, max_rounds=3, retry_on_empty, prune_after_days=30, diamond_search`
  - `AppConfig`: `search, llm, output, schedule, browser, storage, notifications`
- **Validation:** Pydantic types catch wrong shapes, but `load_config()` has **no try/except** — a malformed YAML raises raw. No explicit "missing required field" messaging beyond Pydantic.
- **Environment variables:** supported only via the `{env:...}` / `{file:...}` substitution mechanism *if used in the YAML*; the loader itself does not resolve env vars. API keys are read from env in `LLMClient._get_api_key`.

### 3.2 LLM Client (`src/llm/`)

Files: `client.py`, `mock_client.py`.

- **Local-first:** ✅ `_chat()` iterates `config.llm.local` first (LM Studio/Ollama/llama.cpp via OpenAI-compatible `/v1/chat/completions`), then `api_fallback`, then legacy provider fields, then falls back to returning the raw user prompt as the search query.
- **Failover timeout:** ❌ **hardcoded `timeout=5` seconds on every `requests.post`** (`_call_local_llm_async`, `_call_openrouter_async`, `_call_gemini_async`, `_call_mistral_async`). This is the primary breakage for slow local models.
- **`MockLLMClient`:** ✅ exists — deterministic: expands queries based on keywords, keeps deals where title matches DJI/mini/air/mavic and `price_eur <= 350`, ranks by a fixed heuristic score. `call_count` tracked.
- **Methods:** `generate_search_query` is **sync** (wraps async via `asyncio.run` in a thread pool); `_generate_search_query_async`, `refine_query`, `judge_results`, `rank_results` are **async**.
- **Token counting / budget:** ❌ none in the client. Budget tracking exists only in `CoordinatorAgent` (see §3.8), and it uses **estimated** fixed token counts, not measured usage.

### 3.3 Browser Manager (`src/browser/`)

Files: `manager.py`, `fingerprint.py`.

- **CDP connection:** ✅ tries `chromium.connect(cdp_endpoint)` first and uses an existing browser context.
- **Fallback:** ✅ Playwright `launch_persistent_context` (headless), then plain `launch`.
- **Headless default:** `True` (`BrowserConfig.headless = True`).
- **`fingerprint.py`:** ✅ exists. `FingerprintGenerator.generate()` produces UA, platform, screen, timezone, language, CPU cores, device memory, color depth, WebGL vendor/renderer, canvas/audio noise, fonts, plugins. `FingerprintRotator` (with a module-level `fingerprint_rotator` singleton) returns per-`session_id` stable fingerprints + `rotate()`.
- **Integration into `get_page()`:** ⚠️ partial — `get_page()` calls `apply_fingerprint` **only when not CDP-connected**; `apply_fingerprint` wraps its whole body in `except Exception: pass`, so failures are silent.
- **Cookie consent:** ✅ attached to `framenavigated` (async task) with a large selector list (EN/SK/CZ).
- **`_warmup_browser_sessions()`:** ❌ **does not exist** anywhere.

### 3.4 Page Object Models (`src/browser/pom/`)

- `pom/` **exists**: `base.py`, `registry.py`, `components/`, `pages/`.
- **Components:** `SearchBar`, `ProductCard` (regex HTML parser + price normalizer), `Filters`, `Pagination`, `Sort` — all present but generic.
- **Pages:** identical problem to adapters — `pages/__init__.py` **aliases every site to the same generic classes** (`SiteHome`, `SiteSearchResults`, `SiteProductDetail`). The per-site directories (`alza/`, `bazos/`, `backmarket/`, `ebay/`, `facebook/`) **exist but are empty**.
- **`registry.py`:** ✅ maps `alza / bazos / backmarket / ebay / facebook` → the aliased generic page classes.
- **Verdict:** POM is a **structural shell** — present in tree and registry, but no site-specific selector/locator logic.

### 3.5 Searcher (`src/searcher/`)

- `PlaywrightSearcher` ✅ exists with both `search()` and `search_with_diamond()`.
- **Multi-round + LLM refinement:** ✅ `search()` generates an initial query, retries once broader if empty, judges results with `judge_results()`, calls `refine_query()` for subsequent rounds, then `rank_results()` → top `winners_count`.
- **Condition/category filtering:** ✅ `_filter_sites()` calls `adapter.matches_condition/matches_category`.
- **Fresh page per site:** ✅ `get_page(session_id=f"search-{site.name}")` then `page.close()` in `finally`; 1s rate-limit between sites.
- **`_warmup_browser_sessions()` before diamond search:** ❌ not present.
- **Adapters count:** 5 (`alza, bazos, backmarket, ebay, facebook`).
- **Diamond:** `search_with_diamond()` runs the coordinator, then **falls back to a normal `search()`** and merges expert scores; if diamond import fails it degrades to `search()`.

### 3.6 Adapters (`src/searcher/adapters/`)

`base.py` defines `Deal` dataclass (`url, title, price_eur, currency, condition, category, site_name, metadata`) and `BaseAdapter` (abstract `search`, `extract_deal`, `matches_condition/category`, plus `results_selector`, `item_selector`).

| Adapter | Site | results/item selector | Extraction | Live status |
|---|---|---|---|---|
| `bazos` | bazos.sk | `.inzeraty` / `.inzeraty > div` | Groups items in 5s; title from `.nadpis a`/`a[href*='inzerat']`; price regex `([\d.]+)\s*€`; condition forced `used` | ✅ **10 deals for "dji drone"** |
| `alza` | alza.sk | `.browsinglink` | `.name`, `.price-box__price`, `a`; open-box badge detection | ❌ 0 items (doctor) |
| `backmarket` | backmarket.sk | `[data-testid="product-card"]` | `product-title`, `product-price`, `a` | ❌ 0 items |
| `ebay` | ebay.de | `.s-item` | `.s-item__title`, `.s-item__price`, `.s-item__link`, `.SECONDARY_INFO` | ❌ 0 items |
| `facebook` | facebook.com | `[role="feed"]` | `span[dir="auto"]`, `span:has-text("€")` | disabled (`requires_login=True`) |

- All adapters implement `search(page, query, max_results)` and inherit `extract_deal` (bazos returns `None` there and uses a group extractor instead).
- **Known flakiness:** Bazos `search()` sleeps 2s for the consent dialog, then waits for selectors — this is the "first attempt times out, retry succeeds" behavior noted in the brief; in the direct searcher test round 1 returned 18 deals, round 2 returned 0 (fresh page likely hit consent/anti-bot or a slow navigation).
- **URL join bug risk:** `backmarket.base_url` is `.sk` but its `search` builds `/search?q=`; adapters concatenate `base_url + href` which is fragile for absolute vs relative hrefs.

### 3.7 Storage (`src/storage/`)

Files: `manager.py`, `models.py`, `schema.py`.

- **DB path:** from config `storage.db_path` default `./data/deals.db` (a stray `deals.db` also sits at repo root).
- **Tables:** `deals` (PK url, `id` autoincrement), `runs`, `alerts`, `price_history`, `migrations`.
- **Methods:** ✅ `save_deal`, `get_deal`, `get_all_deals`, `is_known`, `record_price_sighting`, `get_price_history`, `get_price_history_for_deal`, `detect_price_drops`, `detect_new_lows`, `get_price_trend`, `mark_seen_today`, `prune_missing`, `create_run/complete_run/get_run/get_last_completed_run/get_all_runs`, `add_alert/get_unsent_alerts/mark_alert_sent`, `get_deal_by_id` (referenced in price_tracker).
- **Migrations:** ✅ `schema.py` with `SCHEMA_VERSION=2`, `migrations` table, `_migration_001_initial`, `_migration_002_price_history` (adds columns idempotently via PRAGMA check).
- **`prune_missing`:** ✅ `prune_missing(max_age_days=30, grace_period_days=7)` — deletes deals older than `max_age_days` (price history preserved) and marks `availability='missing'` within the grace window.

### 3.8 Diamond Search Agents (`src/agents/`)

- **Present:** `base.py`, `coordinator.py`, plus all 7 agents under `research/` (QueryExpansion, SiteSelection, MarketIntel), `expertise/` (DomainExpert, LatestTechTracker), `price/` (PriceHunter), `synthesis/` (Recommendation).
- **`AgentBase`:** `run()` (timing + error capture → `AgentResult`), abstract `execute()`, `register_handler`, `send_message`, `status`/`is_running`. `MessageBus` = in-memory pub/sub with history. `AgentMessage` carries `correlation_id`.
- **`CoordinatorAgent`:** ✅ generates/accepts `run_id` (uuid4), tracks `llm_call_budget`/`llm_token_budget` with `_check_budget()` and `_record_llm_usage()`, and orchestrates **Research (parallel) → Expertise (parallel) → Price (sequential) → Synthesis**.
- ⚠️ **Budget uses fixed estimates** (3/3k, 2/4k, 2/5k, 1/3k tokens) — not real usage.
- ⚠️ **Agents are stubs.** `QueryExpansionAgent` returns a hardcoded DJI drone list; `MarketIntel` and `LatestTechTracker` return hardcoded dicts; `DomainExpert` scoring has `price_score = 0` always and DJI-specific text; `PriceHunter`/`Recommendation` do heuristic math, no LLM calls. None call `LLMClient` — the "7-agent LLM pipeline" is currently a deterministic demo.
- `run_id` propagation is present in signatures/logging.

### 3.9 Notifications (`src/notifications/`)

- **Channels:** ✅ `ConsoleChannel`, `WebhookChannel`, `DiscordChannel` (rich embeds via aiohttp), `EmailChannel` (SMTP/TLS).
- **`NotificationManager`:** ✅ cooldown (`_seen` map), dedup, `add_channel/add_rule`, `notify`, `send_alert` (per-channel `_check_cooldown`), `check_rules(context)`.
- **`AlertRule`:** ✅ `should_trigger` (with per-rule cooldown), `create_alert`, `matches`; `Alert` dataclass in `base.py`.
- ⚠️ **Rule evaluation after diamond search: not wired.** `check_rules()` is defined but the search/monitor paths do not invoke it; the CLI creates a bare `NotificationManager()` with no channels/rules.

### 3.10 History & Watchlist (`src/history/`)

- **`WatchlistManager`:** ✅ JSON persistence at `data/watchlist.json`; `add_item/remove_item/get_item/get_all`, `check_prices`, `get_items_below_price`, `get_price_trend`. Target-price + `alert_threshold_pct` supported.
- ⚠️ `check_prices` → `_search_item()` **returns `[]`** (not implemented), so price checking does nothing; alerts only logged, not dispatched.
- **`trends.py` (`TrendsAnalyzer`):** ✅ `analyze_category`, `get_all_category_trends`, `get_price_drops`, `get_new_lows`. **⚠️ Multiple bugs:** `analyze_category` references undefined `url_prices` (NameError), and `get_new_lows` uses `row["url"]` on a raw tuple (`row[2]` used elsewhere) and joins on `ph.deal_id = d.id` inconsistently.
- **CLI commands:** ✅ `history`, `trends`, `watchlist`, `selector` exist (see §3.12) — but `watchlist` exposes a single `watchlist-cmd` with an `action` argument, not separate subcommands.

### 3.11 Diagnostics (`src/diagnostics/`)

- **`doctor.py`:** ✅ `Doctor.check_site/check_all`, `DoctorResult`, `print_doctor_results`. Checks config membership, enabled flag, then live-runs the adapter's `search("test")`. Leaves `[DEBUG] print(...)` statements in production code.
- **`selector_health.py`:** ✅ `SelectorMetric` (success_rate, `health_score` with decay), `SiteHealth` (`is_healthy`), `SelectorHealthTracker` (JSON at `data/selector_health.json`, record start/result/latency, `get_selector_report`, `get_summary`), `run_health_check(config, browser_manager)`.
- ⚠️ `health_score` decay has unreachable branches (`hours>24` then `hours>72`; the 72 branch can never run after 24).
- ⚠️ `run_health_check` iterates the async loop incorrectly (records start/result inside try without awaiting-free structure) — works but fragile.

### 3.12 CLI (`src/cli/`)

`app.py` (Typer) + `commands/` (`run.py`, `monitor.py`, `doctor.py`, `config_check.py`, `history.py`).

- **Commands:** `run`, `schedule-install`, `schedule-uninstall`, `config-check`, `doctor`, `monitor`, and the `history` sub-app.
- `run`: ✅ `--prompt/-p`, `--prompt-file/-f`, `--condition/-c`, `--category/-cat`, `--winners/-w`, `--format`.
- `monitor`: ✅ `--prompt-file`, `--interval`, `--max-runs`, `--output-dir`, `--price-drop-threshold`.
- `history`: ✅ `history <url>`, `trends`, `selector {health,unhealthy,clear}`, `watchlist` (single `watchlist-cmd` with `action`: add/remove/list/check/check-async/trends).
- **`schedule-install` / `schedule-uninstall`:** ✅ exist (Windows Task Scheduler / cron).

### 3.13 Scheduler (`src/scheduler/`)

- Only `tasks.py`. `install_schedule`/`uninstall_schedule` dispatch by `sys.platform`.
- Windows: builds `New-ScheduledTaskAction/Trigger/Settings` PowerShell strings and `Register-ScheduledTask`. Unix: appends lines to `crontab`.
- There is **no "intelligent scheduler"** — just OS cron/Task Scheduler wrappers. (Note `_install_windows_tasks` computes `run_once.ps1` path but never uses it.)

### 3.14 Tests (`tests/`)

Files: `test_agents.py`, `test_basic.py`, `test_browser.py`, `test_cli.py`, `test_config_models.py`, `test_fixpass.py`, `test_integration.py`, `test_notifications.py`, `test_storage.py` + `fixtures/`.

**Result:** `python -m pytest tests/ -v` → **20 passed in 2.50s** (0 failed, 0 skipped). Coverage plugin present but not invoked; no coverage % measured. Tests are mostly import/smoke and assertion-light (e.g. `test_agents.py` only checks imports); `test_integration.py::test_integration_pipeline_smoke` passes. **No Testcontainers / browser-based integration tests.**

<!-- SECTION:VERIFY -->
## 4. Functional Verification Results

### 4.1 `config-check`

```
$ python -m src.cli config-check
✅ Config valid
  Sites enabled: ['alza', 'bazos', 'backmarket', 'ebay']
  LLM local: lmstudio
  Winners: 3
```
✅ Passes. Loads config, reports 4 enabled sites.

### 4.2 `doctor --site bazos`

```
$ python -m src.cli doctor --site bazos
🔍 bazos (bazos)
   HTTP Status: 200
   Selector Found: ✅
   Items Found: 3
   Duration: 9041ms
   [1] Ford Mustang Mach-E ... | 27450.0€ | used
   [2] Tesla Model 3 Performance ... | 22900.0€ | used
   [3] ✔️OBHLIADKA ÁUT PRED KÚPOU ... | 199.0€ | used
SUMMARY: 1/1 sites healthy
```
✅ Works — Bazos healthy, 3 deals, selectors OK.

**Full `doctor` (all sites):**
```
SUMMARY: 1/4 sites healthy
✅ bazos     3 items   3347ms
❌ alza      0 items  22636ms
❌ backmarket 0 items 43530ms
❌ ebay      0 items  20173ms
```
Confirms only Bazos is functional.

### 4.3 Single search (`run`)

```
$ python -m src.cli run --prompt "test" --condition used --category electronics --winners 1
Local LLM (lmstudio) failed: ... Read timed out. (read timeout=5)   ← before config fix: '100.88.219.120'
All LLM providers failed, falling back to prompt as search query
[bazos] Got 0 deals
[ebay] Got 0 deals
Found 0 deals. Results in ./results/
```

- ❌ **Did not find deals.** Query `"test"` returns nothing on Bazos; eBay returns nothing.
- The LLM chain failed at the **5-second timeout**; cloud fallbacks 404/429.
- Verified independently: `BazosAdapter.search(page, "dji drone")` → **10 deals**; full `PlaywrightSearcher.search("dji drone", ...)` with `MockLLMClient` → **18 deals round 1, 3 ranked final**.
- **Conclusion:** the pipeline works when (a) the query is a real search term and (b) a functioning LLM generates/refines queries. With "test" + no LLM, output is 0.

### 4.4 Monitor (1 iteration)

```
$ python -m src.cli monitor --prompt-file prompts/auto.yaml --max-runs 1
Monitor Run #1 — monitor_20261014_094132
Local LLM (lmstudio) failed: ... read timeout=5
[alza] 0  [bazos] 0  [backmarket] 0  [ebay] 0
```
- ❌ **0 deals, no report content.** `prompts/auto.yaml` is a *prose paragraph*, not a search query; with the LLM unavailable it passed the whole paragraph as the query and every adapter returned 0.
- **No alerts fired** (rules are not wired into the monitor path).
- Confirms the reported "Bazos flaky in monitor" symptom is actually a *query-quality + LLM* problem, not just Bazos.

### 4.5 History commands

```
$ python -m src.cli history trends --category electronics
Insufficient data for electronics (need more price history)

$ python -m src.cli history watchlist watchlist-cmd list
Watchlist is empty

$ python -m src.cli history selector health
📊 Selector Health Summary
  Total Sites: 4
  Healthy: 0 | Unhealthy: 4
  ❌ alza: 0.0% success, 2 consecutive failures
  ❌ bazos: 0.0% success, 2 consecutive failures
  ❌ backmarket: 0.0% success, 2 consecutive failures
  ❌ ebay: 0.0% success, 1 consecutive failures
```

- `history watchlist list` **fails** as a literal command — the CLI is `history watchlist watchlist-cmd <action>`, so the documented `list` form is a UX mismatch.
- `selector health` reports all sites unhealthy — consistent with the 0-deal runs, though Bazos works in isolation (health file was written by failing full runs).
- `trends` returns "insufficient data" because no successful run has populated `price_history` yet.

<!-- SECTION:GAPS -->
## 5. Gap Analysis

| Area | Expected | Actual | Gap |
|---|---|---|---|
| Site Adapters | 14+ sites | **5** (alza, bazos, backmarket, ebay, facebook) | ❌ 9+ missing |
| Working adapters | all selectors valid | **1/4 enabled work** (bazos only) | ❌ critical |
| Page Object Models | full site-specific POM | registry + components exist; **all pages alias generic classes**; per-site dirs empty | ❌ shell only |
| Diamond Search Agents | 7 agents, 3 layers | 7 agents + coordinator present, **logic is hardcoded stubs** | ⚠️ scaffold only |
| Smart Alerting | 4 channels, cooldowns, post-search eval | 4 channels + cooldowns exist; **rules not invoked** | ⚠️ partial |
| History/Trends CLI | 4 subcommands | `history`, `trends`, `selector`, `watchlist` exist; **`trends.py` has NameError bugs; watchlist check is a no-op** | ⚠️ partial |
| Selector Health | per-site/per-selector metrics | ✅ implemented, but decay bug & written from failed runs | ⚠️ partial |
| Fingerprint Rotation | CDP integration | ✅ generator+rotator; applied only when not CDP; silent failures | ⚠️ partial |
| Session Warmup | `_warmup_browser_sessions()` | **absent** | ❌ missing |
| Budget Tracker | real `llm_call_budget`/`llm_token_budget` | fields exist; **fixed estimates, no real token counting** | ⚠️ partial |
| run_id Propagation | UUID through all agents | ✅ in coordinator/logs | ✅ ok |
| Graceful Shutdown | SIGTERM handler | **absent** (only `KeyboardInterrupt` in monitor) | ❌ missing |
| Structured Logging | JSON logs | **absent** — stdlib `logging`, plus stray `print("[DEBUG]…")` | ❌ missing |
| Health Endpoint | HTTP readiness probe | **absent** | ❌ missing |
| Circuit Breaker | LLM failover | **absent** — simple sequential try (with 5s timeout) | ❌ missing |
| Integration Tests | Testcontainers | **absent** — only smoke/import tests | ❌ missing |

<!-- SECTION:RECS -->
## 6. Recommendations

### 6.1 What's working well

- Clean, modular package layout (14 subpackages) with a coherent domain model.
- `config` Pydantic models are comprehensive (incl. `DiamondSearchConfig`, `NotificationConfig`, budget fields).
- SQLite layer with real migrations (`schema.py`), url-keyed joins, price-history + run tracking, `prune_missing` with grace period.
- `PlaywrightSearcher` multi-round search + LLM refinement/ranking **works** (verified 18→3 deals with mock LLM).
- **Bazos adapter works end-to-end** (10–18 deals).
- Notifications framework (4 channels, cooldown/dedup) and `SelectorHealthTracker` are solid designs.
- **All 20 unit tests pass.**

### 6.2 What's broken or missing

1. **Secrets committed** in `config.yaml` (OpenRouter/Gemini/Mistral keys).
2. **`LLMClient` 5s hardcoded timeout** breaks all slow local models.
3. **Alza, BackMarket, eBay adapters return 0 items** (selectors/navigation stale).
4. **`config.yaml` default `model: "auto"`** invalid → LM Studio HTTP 400.
5. Diamond agents are **hardcoded stubs**, not LLM-driven.
6. Alert rules **never evaluated**; watchlist `check_prices`/`_search_item` **no-op**.
7. `history/trends.py` **NameError / tuple-indexing bugs**.
8. POM site classes are **empty aliases**.
9. Missing: `_warmup_browser_sessions`, graceful shutdown, structured logging, health endpoint, circuit breaker, real token counting, integration tests.
10. **Dependency drift** (`aiohttp` missing from pyproject; stale `setup.py`); running on **Python 3.14** vs declared 3.11/3.12.

### 6.3 Critical path items (must-fix before reliable use)

1. ~~**Purge secrets**~~ — done: keys moved to git-ignored `.env`, `${VAR}` substitution added to `load_config()`, `python-dotenv` wired in. No git history rewrite was needed (keys were never committed). **Rotate the keys anyway** — they sat in plaintext on disk and in shell history.
2. **Fix `LLMClient` timeouts** — make them configurable (e.g. 300–1800s for local) instead of `timeout=5`; add a proper failover/circuit-breaker.
3. **Repair adapters** (Alza, BackMarket, eBay): re-derive selectors from live DOM; add per-adapter tests; make URL joins robust.
4. **Validate `load_config()`** with friendly errors; fix `model: "auto"` handling (auto-select a loaded model from `/api/v1/models`).
5. **Wire alert rules** into the search/monitor flow and implement `WatchlistManager._search_item`.
6. **Fix `trends.py` bugs** and align the `watchlist` CLI with documented `list`/`add` subcommands.

### 6.4 Nice-to-have enhancements

- Replace stub agents with real LLM-backed reasoning + measured token budget.
- Implement site-specific POMs and use them in adapters.
- `_warmup_browser_sessions()` + anti-bot retry/backoff.
- Structured JSON logging, SIGTERM handling, `/health` endpoint.
- Expand tests: adapter fixtures, integration (Playwright), coverage gates in CI.
- Reconcile `requirements.txt` / `pyproject.toml` / `setup.py`; pin a supported Python.
- Add `requests`→`httpx`/`aiohttp` consistency; remove `[DEBUG] print`s.

### 6.5 Prioritized implementation roadmap (4 weeks)

**Week 1 — Security & core reliability**
- Remove/rotate secrets; externalize config (env/`{env:}`); add `config.local.yaml` to `.gitignore`.
- Make LLM timeouts configurable; add retry + basic circuit breaker.
- Fix `load_config()` validation and `model` resolution (auto-detect loaded LM Studio model).
- Verify `run`/`monitor` end-to-end with a real query + local model.

**Week 2 — Adapters**
- Rewrite Alza, BackMarket, eBay adapters against live DOM; add fixture/HTML tests.
- Stabilize Bazos (consent/retry), add warmup + per-site retry/backoff.
- Implement site-specific POM classes; wire them into adapters.

**Week 3 — Intelligence & alerts**
- Implement `WatchlistManager._search_item`; wire `AlertRule`s + `NotificationManager` into search/monitor.
- Fix `history/trends.py`; reconcile watchlist CLI subcommands.
- Real token accounting for `CoordinatorAgent` budgets.

**Week 4 — Hardening & observability**
- Structured JSON logging, SIGTERM graceful shutdown, `/health` endpoint.
- Replace stub agents with LLM-backed versions (behind a flag).
- Integration test suite (Playwright + fixture DB); CI with coverage; dependency/Python cleanup; commit the stabilized branch.

<!-- SECTION:APPENDIX -->
## 7. Appendix: Raw Command Outputs

### 7.1 `git status` / `log` / `branch`
```
On branch chore/overnight-full-stabilization-20261013
nothing to commit, working tree clean

9a559ed (HEAD) feat: Etapa-2 CLI package split, monitor restore, fingerprint rotation, history/watchlist/selector-health
6e1b1a0 fix: url joins, layer budgets, scheduler quoting, cli entry, per-site fingerprint sessions
6ba87d2 feat: add storage models, CLI split, integration smoke and verification docs
08469d7 refactor: split CLI into main plus run/monitor/doctor/config_check commands
7e2c615 feat: add canonical storage models with url-based joins

* chore/overnight-full-stabilization-20261013   9a559ed
  master                                        8b58acd [origin/master]
```

### 7.2 LM Studio inventory (`GET http://localhost:1234/api/v1/models`)

| key | max_context | vision | tools |
|---|---|---|---|
| google/gemma-4-26b-a4b-qat | 262144 | ✓ | ✓ |
| dolphin-2.5-mixtral-8x7b | 32768 | ✗ | ✗ |
| mirothinker-v1.5-30b-q2ks-mixed-autoround | 262144 | ✗ | ✓ |
| prism-ml/bonsai-27b | 262144 | ✓ | ✓ |
| qwen/qwen3-coder-30b | 262144 | ✗ | ✓ |
| allenai/olmocr-2-7b | 128000 | ✓ | ✗ |
| qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp | 262144 | ✓ | ✓ |
| qwen3.8-9b-distill | 262144 | ✗ | ✓ |
| openai/gpt-oss-20b | 131072 | ✗ | ✓ |
| mistralai/ministral-3-3b | 262144 | ✓ | ✓ |
| text-embedding-nomic-embed-text-v1.5 | 2048 | — | — |

All models showed `state: "not-loaded"` at audit time (LM Studio loads on demand).

### 7.3 Pytest
```
python -m pytest tests/ -v
...
============================= 20 passed in 2.50s ==============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
```

### 7.4 Direct Bazos adapter smoke test
```
BazosAdapter.search(page, "dji drone", max_results=10)
Deals found: 10
  DJI Avata 360 - nový, nelietaný, záruka do 04/2028 | 389.0€
  DJI mavic 4 pro drone s rc2 | 2000.0€
  Variabilní ND filtr pro DJI Phantom 4 Pro/Pro+/Advance | 26.0€
```

### 7.5 Changes applied during this audit
- `config.yaml`: LM Studio endpoint `http://100.88.219.120:1234` → `http://localhost:1234` (local + legacy `local_endpoint`).
- `config.yaml`: LM Studio `model: "auto"` → `model: "qwen/qwen3-coder-30b"` (auto caused HTTP 400).
- **Secrets externalised:** real OpenRouter/Gemini/Mistral keys removed from `config.yaml` → replaced with `${OPENROUTER_API_KEY:-}` / `${GEMINI_API_KEY:-}` / `${MISTRAL_API_KEY:-}`; values now live in git-ignored `.env`.
- `src/config/__init__.py`: added `_load_dotenv()` + `resolve_env_placeholders()` supporting `${VAR}` and `${VAR:-default}`, applied inside `load_config()`; strict mode raises on a missing var instead of silently yielding `""`.
- `.env.example` added (committed, empty placeholders); `.gitignore` extended with `.env.*` + `!.env.example`.
- `config.example.yaml`: stale remote IP → `localhost`, real model id, env-based secret guidance.
- `pyproject.toml` + `requirements.txt`: added `aiohttp` (was missing from pyproject) and `python-dotenv>=1.0.0`.

**Verification after change:** `config-check` OK · secrets resolve from `.env` (3 of 3 providers) · no key material in any tracked file · `.env` confirmed ignored · `pytest` 20 passed at that point.
