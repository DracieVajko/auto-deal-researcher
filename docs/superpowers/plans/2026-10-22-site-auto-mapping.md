# Site Auto-Mapping and Runtime Filters Implementation Plan

**Goal:** Make all 21 registered sites discoverable through profile-driven mapping and apply category/filter choices at runtime.

**Spec:** `docs/specs/2026-10-22-site-auto-mapping-design.md`

**Architecture:** `SiteProfile` YAML stores search URL templates, category URLs, filter descriptors, and extraction selectors. Discovery records sites and writes sanitized profiles. Runtime loads validated profiles, builds filtered URLs, applies UI filters when needed, and post-filters extracted deals.

**Constraints:** All 21 sites in scope. Raw flows stay in git-ignored `flows/`; committed profiles contain no cookies, HTML, tokens, e-mails, or phone numbers. Filter order: URL, UI, Python. CLI overrides prompt. Keep the suite green and ruff clean. `alza_cz` and `bazos_cz` must use their own base URLs.

## Task 1: SearchFilters and config defaults

**Files:** create `src/searcher/filters.py`; modify `src/config/models.py`; test `tests/test_search_filters.py`.

**Interfaces:** `SearchFilters` dataclass (`min_price`, `max_price`, `condition`, `brand`, `location`, `shipping`, `seller_type`, `sort`, `extras`), `validate()`, `merge_filters()`, `from_cli()`, `parse_filters_from_text()`, `resolve_filters()`. Add `SearchConfig.default_filters`.

**TDD:**
1. Write failing tests for inverted price ranges, CLI-over-prompt merge, Slovak price parsing, extras parsing, and unknown prompt fields.
2. Implement validation, merge, deterministic prompt parsing, and CLI `KEY=VALUE` extras.
3. Add `default_filters` and verify config loading.
4. Run `pytest tests/test_search_filters.py tests/test_basic.py -v`.
5. Commit `feat(filters): add search filter model and prompt parsing`.

## Task 2: SiteProfile schema, loader, sanitizer

**Files:** create `src/searcher/site_profiles.py`, `src/searcher/site_profiles/.gitkeep`; test `tests/test_site_profiles.py`.

**Interfaces:** `UrlFilterSpec`, `UiFilterSpec`, `FilterSpec`, `ProfileFilters`, `SearchSpec`, `ExtractionSpec`, `SiteProfile`; `PROFILE_DIR`, `load_profile()`, `load_profiles()`, `save_profile()`, `sanitize_profile_data()`.

**TDD:**
1. Write failing tests for YAML round-trip, invalid filter without URL/UI, invalid status, secret-key stripping, URL token stripping, and missing profile returning `None`.
2. Implement Pydantic v2 models with `extra="forbid"` and validators.
3. Implement recursive sanitizer: drop `cookie`, `cookies`, `headers`, `storage_state`, `html`, `screenshot`, `authorization`, `token`, `password`, `email`, `phone`; sanitize URLs.
4. Run `pytest tests/test_site_profiles.py -v`.
5. Commit `feat(profiles): add site profile schema and sanitizer`.

## Task 3: FilterEngine URL, UI, post-filter

**Files:** create `src/searcher/filter_engine.py`; test `tests/test_filter_engine.py`.

**Interfaces:** `FilterEngine.build_search_url(profile, query, category, filters) -> str | None`, `apply_ui(page, profile, filters) -> list[str]`, `post_filter(deals, filters) -> list[Deal]`.

**TDD:**
1. Write failing tests for category URL + query parameter, `url_template`, mapped condition values, encoding spaces/diacritics, missing UI selector continuing, input/select/checkbox dispatch, price post-filter, unknown price kept, brand metadata filter, and sort.
2. Implement URL building with `urllib.parse`.
3. Implement per-filter UI dispatch with exception isolation.
4. Implement post-filter with known/unknown semantics.
5. Run `pytest tests/test_filter_engine.py -v`.
6. Commit `feat(filters): add URL, UI and post-filter engine`.

## Task 4: BaseAdapter and existing adapters

**Files:** modify `src/searcher/adapters/base.py`, `alza.py`, `bazos.py`, `backmarket.py`, `ebay.py`, `facebook.py`; test `tests/test_adapter_filters.py`.

**Interfaces:** `BaseAdapter(base_url=None)`, `search(page, query, max_results=20, filters=None, category="any", profile=None)`, `_goto_search()`, `_apply_filters()`, `default_search_url(query)`.

**TDD:**
1. Write failing tests that Alza/Bazos use configured base URLs and that `search()` calls goto then filters before extraction.
2. Add constructor and helpers; keep `extract_deal` abstract.
3. Move each adapter's hardcoded URL into `default_search_url`; replace `page.goto` with `_goto_search`; apply filters before waiting for results.
4. Run `pytest tests/test_adapter_filters.py tests/test_adapters.py -v`.
5. Commit `feat(adapters): add base-url and filter hooks`.

## Task 5: Runtime integration and CLI

**Files:** modify `src/searcher/playwright_searcher.py`, `src/cli/app.py`, `src/llm/client.py`; tests `tests/test_search_filters.py`, `tests/test_playwright_searcher_filters.py`.

**Interfaces:** `LLMClient.extract_search_filters(prompt) -> dict`; `resolve_filters(prompt, cli_filters, llm) -> SearchFilters`; `PlaywrightSearcher.search(prompt, condition="any", category="any", filters=None)`.

**TDD:**
1. Write failing tests for LLM extraction fallback and CLI precedence; fake adapter records filters; profile-only site is included; unknown profile does not crash.
2. Add LLM JSON extraction with safe fallback.
3. Add CLI flags `--min-price`, `--max-price`, `--brand`, `--location`, `--shipping`, `--seller-type`, `--sort`, `--filter`.
4. Load profiles in searcher, include validated profile sites, instantiate with `base_url`, pass filters/category/profile, and post-filter before judging.
5. Run `pytest tests/test_search_filters.py tests/test_playwright_searcher_filters.py -v`.
6. Commit `feat(search): apply CLI and prompt filters at runtime`.

## Task 6: ProfileAdapter and discovery

**Files:** create `src/searcher/adapters/profile_adapter.py`, `scripts/discover_sites.py`; modify `src/searcher/adapters/__init__.py`, `src/searcher/site_registry.py`; tests `tests/test_profile_adapter.py`, `tests/test_discover_helpers.py`.

**Interfaces:** `ProfileAdapter(BaseAdapter)`; discovery CLI `discover` and `validate` with `--all`, `--site`, `--category`, `--resume`, `--force`, `--headed`, `--no-llm`; `SiteSpec.discovery_queries`.

**TDD:**
1. Write failing tests for generic card extraction, discovery seed overrides, and sanitized profile output.
2. Implement `ProfileAdapter` using `profile.extraction`; parse prices; skip incomplete cards.
3. Implement discovery: open base URL, find search box, submit seed, capture final URL and controls, classify filter labels, build extraction selectors, replay validation, save raw flow and sanitized profile.
4. Add seed queries and profile-only adapter selection.
5. Run `pytest tests/test_profile_adapter.py tests/test_discover_helpers.py -v`.
6. Commit `feat(discovery): add profile adapter and site discovery`.

## Task 7: Config, docs, full validation

**Files:** modify `config.example.yaml`, `README.md`, `CHANGELOG.md`.

1. Add all 21 site entries from `SITES`; enable only validated sites.
2. Document discovery, validation, filter flags, and the `flows/` vs `site_profiles/` split.
3. Run `pytest -q` and `ruff check src tests scripts`.
4. Commit `docs: document site discovery and runtime filters`.
