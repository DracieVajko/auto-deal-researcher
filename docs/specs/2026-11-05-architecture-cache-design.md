# Design: Architecture & Performance — Caching Layer (Sub-project 5)

**Date:** 2026-11-05  
**Deep research goal:** Architecture & performance (caching, parallel search, plugin system)  
**Status:** Draft  

## Problem

The replacement finder searches multiple marketplaces for each query. Repeated searches for the same item (e.g., user runs `find-replacement` twice) re-hit all sites, wasting time and increasing anti-bot risk. There's no caching of search results at the page/response level (only LLM-level cache from Sub-project 3).

Additionally, parallel site search uses a simple semaphore with no adaptive concurrency based on site health.

## Scope

**In scope:**

1. **Search response cache** — cache adapter search results keyed by (site, query, filters_hash). TTL configurable (default 1 hour). Avoids re-hitting sites for identical searches.
2. **Cache integration** — integrate into `PlaywrightSearcher._search_one_site`: check cache before searching, store after.
3. **Cache management CLI** — `ads cache --stats`, `ads cache --clear` commands.
4. **Adaptive concurrency** — reduce concurrency for sites that return blocks/errors (reuses SelectorHealthTracker).

**Out of scope:**
- Web dashboard (nice-to-have, not critical for replacement finder)
- Formal plugin system (adapter registry already exists)

## Architecture

```
src/searcher/search_cache.py         (new) — File-based search response cache
  ├── SearchCache.get(site, query, filters) -> list[dict] | None
  ├── SearchCache.set(site, query, filters, deals) -> None
  └── cache_key(site, query, filters) -> str

src/searcher/playwright_searcher.py  (modify) — integrate cache in _search_one_site
  ├── check cache before adapter.search
  ├── store results in cache after search
  ├── skip cache for blocked sites

src/cli/app.py                       (modify) — cache management commands
  ├── ads cache --stats
  └── ads cache --clear
```

## Data model

Cache entry (JSON file):
```json
{
  "ts": 1730786400,
  "site": "bazos",
  "query": "Citroen eC3",
  "filters_hash": "abc123",
  "deals": [...],
  "count": 5
}
```

## Cache key

SHA256 of `site|query|filters_hash` where filters_hash is SHA256 of serialized filters.

## TTL

Default 1 hour (3600s). Configurable via `config.search.cache_ttl_seconds`.

## Error handling

- Cache read failure: treat as miss, proceed with search
- Cache write failure: log debug, continue
- Corrupted cache file: delete and treat as miss
- Blocked sites: don't cache empty results

## Testing

- Unit tests for SearchCache (get/set/expire/clear)
- Integration test: search uses cache on second call
- Full suite must remain green (713 passed, 11 skipped baseline)

## Files to create/modify

**Create:**
- `src/searcher/search_cache.py`
- `tests/test_search_cache.py`

**Modify:**
- `src/searcher/playwright_searcher.py` — cache integration
- `src/cli/app.py` — cache management commands
- `src/config/models.py` — add `cache_ttl_seconds` to SearchConfig

## Design decisions

- **File-based cache**: no new dependencies, persists across runs
- **1-hour TTL**: balances freshness vs. anti-bot protection
- **Don't cache empty results**: blocked sites return [], don't cache that
- **Cache key includes filters**: different filters = different results
