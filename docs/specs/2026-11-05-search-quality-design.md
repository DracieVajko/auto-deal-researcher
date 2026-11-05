# Design: Search Quality & Relevance (Sub-project 2)

**Date:** 2026-11-05  
**Deep research goal:** Search quality & relevance (multi-language NLP, anti-bot, pagination, structured extraction)  
**Status:** Draft  

## Problem

The replacement finder needs to search for similar items across marketplaces using specs extracted in Sub-project 1. Current limitations:

1. **Filter extraction** (`extract_search_filters`) is basic — only handles EUR prices, a fixed category list, and simple condition keywords. Doesn't handle multi-language queries (SK, CZ, DE, PL) or spec-based filters (power, battery, weight, dimensions).
2. **Anti-bot protection** — sites like mobile.de, idealo.de, alza.sk use Cloudflare/anti-bot that blocks automated Playwright sessions. No strategy beyond "fails fast".
3. **Pagination** — no handling of multi-page results or infinite scroll; only the first page is scraped.
4. **Structured extraction** — no library for extracting price/title/availability from arbitrary e-commerce pages; each adapter is hand-written.

Without these, the replacement finder can't reliably find similar items across multiple marketplaces.

## Scope

**In scope:**

1. **Multi-language NLP filter extraction** — extend `extract_search_filters` to handle SK/CZ/DE/PL language keywords for condition, price, brand, category, and spec-based filters (power_kw, battery_kwh, weight_kg, etc.) from specs research output.
2. **Anti-bot handling** — add stealth Playwright configuration (user-agent rotation, viewport, headers), Cloudflare challenge detection with retry, and graceful degradation (skip blocked sites, log reason).
3. **Pagination handling** — add "next page" link detection and multi-page scraping up to a configurable page limit (default 3 pages per site).
4. **Structured product data extraction** — add a generic `extract_product_card` helper using CSS selectors + regex fallback for price, title, availability from arbitrary listing cards.

**Out of scope (later sub-projects):**
- CLI wizard for replacement search (Sub-project 3)
- Parallel search architecture (Sub-project 4)
- Web dashboard (Sub-project 3)

## Architecture

```
src/searcher/filter_extractor.py      (new) — Multi-language filter extraction
  ├── extract_filters_from_specs(specs: ItemSpecs) -> SearchFilters
  ├── extract_filters_from_prompt(prompt: str) -> dict   (existing, enhanced)
  └── LANGUAGE_KEYWORDS — SK/CZ/DE/PL term mappings

src/searcher/anti_bot.py              (new) — Anti-bot Playwright helpers
  ├── stealth_context(browser) -> BrowserContext
  ├── detect_block(page) -> str | None
  └── retry_with_backoff(page, max_attempts=3)

src/searcher/pagination.py            (new) — Multi-page scraping
  ├── find_next_page_link(page) -> str | None
  └── scrape_pages(search_fn, max_pages=3) -> list[Deal]

src/searcher/extract.py               (new) — Generic product card extraction
  └── extract_product_card(element, selectors) -> dict
```

## Changes to existing files

- `src/searcher/playwright_searcher.py` — integrate anti-bot stealth context + pagination in `_search_site`
- `src/searcher/adapters/base.py` — add `extract_product_card` static method
- `src/cli/app.py` — add `--pages` flag to `diamond_search` and `run` commands
- `config.yaml` — add `search.pages_per_site` (default 3)

## Data flow (replacement finder)

1. `ItemSpecsResearcher.research("Citroen eC3")` → `ItemSpecs` (Sub-project 1, done)
2. `extract_filters_from_specs(specs)` → `SearchFilters` with spec-based filters (power_kw, battery_kwh, etc.)
3. `PlaywrightSearcher.search()` with anti-bot + pagination → `list[Deal]`
4. `ResultProcessor.save_results()` → report with comparison

## Error handling

- Anti-bot detected: skip site, log reason, continue with next site
- Pagination: stop at max_pages or when no "next page" link found
- Filter extraction: return partial filters, never fail the whole search
- LLM unavailable: deterministic keyword fallback

## Testing

- Unit tests for `filter_extractor.py` with SK/CZ/DE/PL keyword mappings
- Unit tests for `anti_bot.py` block detection
- Unit tests for `pagination.py` next-page detection
- Unit tests for `extract.py` product card extraction
- Integration test: specs → filters → search → deals
- Full suite must remain green (677 passed, 11 skipped baseline)

## Design decisions

- **Specs as filters**: power_kw, battery_kwh, weight_kg, dimensions become `extras` filters in SearchFilters
- **Page limit default 3**: balances coverage vs. anti-bot risk
- **Stealth context**: random user-agent, realistic viewport, no webdriver flag
- **Graceful degradation**: blocked sites are skipped, not fatal

## Files to create/modify

**Create:**
- `src/searcher/filter_extractor.py` — multi-language filter extraction
- `src/searcher/anti_bot.py` — anti-bot Playwright helpers
- `src/searcher/pagination.py` — multi-page scraping
- `src/searcher/extract.py` — generic product card extraction
- `tests/test_filter_extractor.py`
- `tests/test_anti_bot.py`
- `tests/test_pagination.py`
- `tests/test_extract.py`

**Modify:**
- `src/searcher/playwright_searcher.py` — integrate anti-bot + pagination
- `src/searcher/adapters/base.py` — add extract_product_card
- `src/cli/app.py` — add --pages flag
- `config.yaml` — add pages_per_site
- `docs/specs/2026-11-05-search-quality-design.md` — this file
