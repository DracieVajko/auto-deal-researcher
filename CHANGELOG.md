# Changelog

## [Unreleased]

### Added
- Profile-driven site auto-mapping: `scripts/discover_sites.py` records search
  pages and filter controls, writes sanitized `src/searcher/site_profiles/*.yaml`
  maps, and validates them by replay.
- Generic `ProfileAdapter` plus profile-aware `BaseAdapter` hooks
  (`base_url`, `_goto_search`, `_apply_filters`).
- Canonical runtime filters (`min_price`, `max_price`, `condition`, `brand`,
  `location`, `shipping`, `seller_type`, `sort`, extras) with CLI flags,
  prompt/LLM extraction, and URL → UI → Python post-filter application.
- Location-aware shop selection: candidates are ranked by the user's market
  (`search.user_country`) and the LLM narrows the list. It can only narrow,
  never widen, and falls back to the deterministic ranking.
- Currency normalisation (`src/searcher/currency.py`): CZK, USD and GBP
  prices are converted to EUR, with the original amount kept on the deal.
- New `home` and `hobby` categories for furniture, DIY, garden and sport.
- 10 new registered sites: Autobazar.sk/.EU/.cz, mobile.de, OBI, Merkury
  Market, BAUHAUS, Hornbach, JYSK, FAVI.sk, IKEA, Decathlon.
- CLI flags `--country` and `--max-sites` for `run`, `diamond-search` and
  `search`.
- `search.default_currency` (with `search.currency_rates`) lets reports show
  prices in the user's currency; the JSON keeps the internal `price_eur` and
  the original amount.
- `python -m src.cli llm-check` probes every configured LLM provider on its own
  and reports status, latency, provider error text and a fix hint (exit code 1
  when nothing is healthy).

### Changed
- Site profiles are loaded at runtime; unknown adapters participate only when
  a validated profile exists.
- `search.default_filters` provides optional baseline filters below prompt and
  CLI precedence.
- `SiteSelectionAgent` reads the site registry instead of a hardcoded
  capability table.
- The Bazos adapter no longer requires a literal `€`, so it also works on
  bazos.cz.
- Discovery submits the search form's action instead of pressing Enter in an
  autocomplete widget, and keeps the requested URL when the site redirects a
  search to a category page. Nay.sk is mapped and validated this way.
- The deal-analysis prompt is now a generic "product buyer" prompt. PC rules
  (CPU/RAM/SSD keys, barebone cost, wrong form factor) are injected only when
  the request or the listing is about computing hardware, so bicycle, furniture
  and other reports no longer get CPU/RAM advice or a memory-screenshot
  checklist item.
- `ADS_LOCAL_LLM_TIMEOUT` default lowered from 900 s to 180 s: a warm local
  model answers well inside that, and an unloaded or dead backend now fails
  over instead of stalling the whole run. Start the model with `llm-check` or
  LM Studio first, or raise the variable for slow hardware.
- Cloud fallback order is Mistral → Gemini → OpenRouter. The free OpenRouter
  model is code-oriented and is kept only as a last resort.

### Removed
- `src/searcher/judge.py`: an unreferenced stub that could not even be
  imported (duplicate argument, wrong import, undefined names).
- The `datart` site: datart.sk redirects to nay.sk, so it duplicated Nay.

### Fixed
- `discover_sites.py` honoured `--headless` and `--headed` backwards, so the
  browser never opened in headed mode.
- The selector table had duplicate keys (`mall` three times, `heureka`,
  `ebay` and `backmarket` twice), so the richer selector lists were silently
  dropped. Every site now appears once.
- A failed discovery printed `failed:` without the reason.
- A cloud provider was retried on every LLM call even after the provider
  rejected the credential. HTTP 401/403 now disables that provider for the rest
  of the run; other failures open the circuit breaker after two attempts.
- Gemini thinking models answered `200 OK` with no text when the output budget
  was small, which looked like a dead provider. Thinking parts are skipped when
  parsing and the output budget has a floor (`ADS_GEMINI_MIN_OUTPUT_TOKENS`).
- The legacy fallback used retired model IDs (`mistralai/mistral-7b-instruct`),
  so that branch could only answer 404.
- The local circuit breaker was keyed by endpoint only. One model that timed
  out or failed to load therefore disabled every other model on the same
  endpoint for the rest of the run. The key now includes the model id.

### Verification
- Test suite: 358 passed, 11 skipped (live tests skipped by default).

## [1.0.0] - 2026-10-20

### Added
- Open-source community files and MIT license
