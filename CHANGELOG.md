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
- Prompt-only search: `run --prompt "..."` without `--condition`/`--category`
  reads condition, category, price, brand, shipping, location and sort from the
  prompt itself (condition through the multilingual parser and the LLM, category
  via the same LLM call that already extracts filters); the explicit flags
  remain as overrides and `--category any` forces the old broad shop list.
- `ask` command: an interactive wizard that needs only a prompt, prints what it
  understood and the selected shops before searching, then the report paths.
- `scripts/search.bat` (Windows) and `scripts/search.sh` (Linux/macOS)
  launchers; `run_once.ps1`/`run_once.sh` now forward `-Condition`/`-Category`
  only when you supply them.
- Bazos detail pages are fetched after the result list, so the description and
  the seller's town (`Deal.metadata["description"]` / `["location"]`) reach the
  report. Frame size, fork, brakes and drivetrain now come from the seller's own
  text instead of the title. `ADS_BAZOS_DETAILS=0` disables the extra requests
  and `ADS_BAZOS_DETAIL_LIMIT` caps them (default 10).
- Offline bike spec extraction (`wheel_size`, `frame_size`, `suspension`,
  `brakes`, `drivetrain`) works without an LLM; car ads that only mention
  "kolesá" are not treated as bikes.
- A stated frame size is compared with the rider height in the request, so an
  XXS frame is skipped for a 180 cm rider instead of scoring well.
- Product domains (`src/output/domains/`): every listing is matched to a
  domain from its own text — `bike`, `computer`, `phone`, `car`, `furniture`,
  or `generic` when nothing matches. Each domain owns its keywords, spec
  extractors, constraints and scoring rows. Detection order: `--domain` first,
  then built-in keywords, then a cached AI draft, then one live AI proposal,
  then `generic`.
- AI domain proposals: when an LLM is configured and a listing matches no
  built-in domain, the model may propose a new one; the proposal is validated,
  cached under `data/domains/ai/*.yaml` (git-ignored) and applied only to
  listings that match its own keywords. Drafts never write into `src/`.
- One canonical text folding (`src/text/normalize.py`): keywords, aliases and
  patterns are stored folded, so a listing matches regardless of case or
  diacritics (`gauč` = `gauc`, `Straße` = `strasse`) in sk, cs, de, en and pl
  without a single language branch.
- CLI flag `--domain` and config key `output.domain` (empty means
  auto-detect); the report JSON now carries `domain` and `spec_coverage`
  (`stated`/`missing` per domain key specs), and the Markdown card shows
  "Domain: <name> — n/m specs stated".

### Changed
- Scores change on purpose: `Spec match` is now the share of a domain's
  `key_specs` the listing states (a bike with 3 of 5 stated specs scores 60,
  not the old fixed 95), and the final score normalises over only the rows the
  domain enables, so a sofa is no longer capped by a Connectivity row it
  cannot have.
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
- The deal-analysis prompt now includes the seller's description (up to 600
  characters), so frame size, defects and included parts are judged from the
  listing text instead of the title alone.

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
- Non-PC listings were scored with the PC spec formula: 45/100 spec match and
  20/100 connectivity regardless of the item, so a complete bicycle could
  never score well. Bike specs now feed the spec score and the port row is
  neutral for bikes.

### Verification
- Test suite: 538 passed, 11 skipped (live tests skipped by default).
- Live wizard run (`ask`): `Understood: condition=used, category=hobby, max_price=200.0`,
  `Shops: bazos`, 0 deals found (no matching listings in the search window).
- Live bare run (`run --prompt "iPhone 13 použitý 128 GB"`): 8 deals, all
  `"domain": "phone"`, `sites: ["bazos"]`, no `--condition`/`--category` flags used.
- Final whole-branch review fixes (each with a test that failed first): battery
  capacity in mAh is never health and values above 100% are dropped; a failed
  detail fetch no longer produces "does not state the CPU/memory" cons; unit-less
  furniture dimensions default to cm; requirement-guard patterns are scoped to
  their attribute; `bicycle` detects the bike domain; `meilen` converts to km per
  spec 13.3; corrupt AI drafts log a warning (spec section 10); `ram 8 gb` is
  never recorded as storage.
- Live search SK (bazos, bike): 14 deals, all `"domain": "bike"`, `spec_coverage`
  present, no `Connectivity` row, 14/14 descriptions fetched, bike vocabulary only.
- Live search CZ (bazos_cz, phone): 6 deals, all `"domain": "phone"`, `storage` and
  `battery_health` extracted, no bike keys, `price_eur` never in `specs`.
- German search not verified: no runtime-ready German adapter (mobile.de profile
  is still incomplete). German *understanding* is covered by the fixture tests.
- Defects from the 2026-10-26 cloud test are gone: no "storage not stated" con for
  a listing whose title states the storage, no two deals with the same folded
  title, `duplicates_collapsed` is in every report, and no con claims a price is
  above or below market.

## [1.0.0] - 2026-10-20

### Added
- Open-source community files and MIT license
