# Site Auto-Mapping and Runtime Filters — Design

- **Date:** 2026-10-22
- **Status:** Approved for implementation planning
- **Scope:** all 21 sites in `src/searcher/site_registry.py`
- **Related code:** `scripts/map_site.py`, `src/searcher/adapters/`, `src/searcher/playwright_searcher.py`, `src/browser/pom/components/filters.py`, `src/config/models.py`

## 1. Problem

The searcher can only use sites that have a hand-written adapter. Five adapters exist, two of them are blocked by anti-bot protection, and one needs a logged-in session. The remaining sites are listed in the registry but cannot be searched.

The current `scripts/map_site.py` records a manual browser walkthrough, but it does not discover filters, categories, or extraction selectors automatically. The `Filters` POM component is a generic stub (`[data-filter]`) and is not used by any adapter.

The goal is to make site mapping repeatable and mostly automatic, then use the resulting maps at runtime so category and filter choices actually reach the site.

## 2. Goals

- Discover, for every supported site and category:
  - a working search URL or category URL,
  - filter controls and their canonical meaning,
  - result-card extraction selectors,
  - a validation status.
- Store sanitized, reviewable site profiles in the repository.
- Apply filters at runtime in this order: URL parameters, UI controls, Python post-filter.
- Support these canonical filters:
  - `price_min`, `price_max`, `condition`, `brand`, `location`,
  - `shipping`, `seller_type`, `sort`, plus arbitrary `extras`.
- Let the user provide filter values through CLI flags or natural-language prompts.
- Keep existing search behaviour when no profile or no filters are available.
- Cover all 21 registered sites; sites that cannot be automated are reported explicitly instead of being silently skipped.

## 3. Non-goals

- Bypassing Cloudflare, captchas, or login walls automatically.
- Generating complete bespoke adapter code from a recording.
- Running a VLM/LLM at runtime to find and click filters.
- Guaranteeing every filter on every site. Unsupported filters are logged and, where safe, applied as post-filters.
- Committing cookies, session state, raw HTML, screenshots, or personal data.
- Replacing existing bespoke adapters for Alza, Bazos, BackMarket, eBay, or Facebook.

## 4. Decisions

| Decision | Choice |
|---|---|
| Discovery/runtime model | Hybrid: URL parameters first, UI selectors as fallback |
| Deliverable | Discovery plus runtime integration |
| Filter scope | Core (price, condition, brand, location) plus arbitrary extras |
| Site coverage | All 21 registered sites |
| Blocked/login handling | Pause and let the user intervene; skip on request |
| Map storage | Raw recordings local; sanitized profiles committed |
| Filter values | CLI flags first, then LLM prompt extraction |
| Implementation style | Profile-driven adapter hooks, no runtime VLM |

## 5. Architecture

```text
                    discovery time                         runtime
┌──────────────────────────────┐          ┌──────────────────────────────┐
│ scripts/map_site.py discover │          │ CLI flags + prompt extraction│
│  - browser walkthrough       │          │  -> SearchFilters            │
│  - heuristic + LLM labelling │          └──────────────┬───────────────┘
│  - validation replay         │                         │
└──────────────┬───────────────┘                         │
               │                                         ▼
               │                              ┌──────────────────────────┐
               │                              │ PlaywrightSearcher       │
               │                              │  loads SiteProfile       │
               │                              └────────────┬─────────────┘
               ▼                                           │
┌──────────────────────────────┐                           ▼
│ flows/<site>/<category>.json │            ┌──────────────────────────────┐
│  raw, git-ignored            │            │ BaseAdapter / ProfileAdapter │
└──────────────────────────────┘            │  _goto_search()              │
               │                            │  _apply_filters()            │
               ▼                            │  extract results             │
┌──────────────────────────────┐            └──────────────┬───────────────┘
│ src/searcher/site_profiles/  │◄──────────────────────────┘
│  <site>.yaml, committed      │
└──────────────────────────────┘
```

### Components

| Component | Responsibility |
|---|---|
| `scripts/map_site.py discover` | Opens sites, captures flows, classifies filters, validates profiles |
| `src/searcher/site_profiles.py` | Profile schema, loading, validation, sanitization |
| `src/searcher/filter_engine.py` | URL building, UI filter application, post-filtering, sorting |
| `BaseAdapter` | Accepts `filters` and `profile`; shared navigation and filter hooks |
| `ProfileAdapter` | Generic extractor for sites without a bespoke adapter |
| `PlaywrightSearcher` | Loads profiles and passes filters to adapters |
| `CLI` / `LLMClient` | Collects filter values from flags and prompts |
| `SiteSpec` | Gains optional discovery seed queries and profile metadata |

## 6. Data model

### 6.1 SearchFilters

```python
@dataclass(frozen=True)
class SearchFilters:
    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None      # new | used | refurbished | open_box
    brand: str | None = None
    location: str | None = None
    shipping: str | None = None       # free | paid | any
    seller_type: str | None = None    # retailer | marketplace | classifieds | auction
    sort: str | None = None           # price_asc | price_desc | newest | relevance
    extras: dict[str, str] = field(default_factory=dict)
```

Validation rules:

- `min_price` and `max_price` must be non-negative.
- If both are set, `min_price <= max_price`.
- Unknown enum-like values are rejected with a warning and ignored.
- `None` means "not requested"; it is distinct from `0`.

### 6.2 SiteProfile

Profiles are stored as YAML in `src/searcher/site_profiles/<site_id>.yaml`.

```yaml
version: 1
site_id: alza
base_url: https://www.alza.sk
status: validated          # draft | validated | failed | needs_login | blocked | needs_manual
last_verified: 2026-10-22

search:
  url_template: "https://www.alza.sk/search.htm?exps={query}"
  query_param: exps
  category_urls:
    electronics: "https://www.alza.sk/pocitace/"
    appliances: "https://www.alza.sk/domacnost/"

filters:
  price_min:
    url:
      param: priceFrom
    ui:
      kind: input
      selector: "input[name='priceFrom']"
    source: heuristic
    confidence: 0.95
    sample_value: "100"

  price_max:
    url:
      param: priceTo
    ui:
      kind: input
      selector: "input[name='priceTo']"
    source: heuristic
    confidence: 0.95

  condition:
    url:
      param: condition
      value_map:
        new: new
        open_box: openbox
    ui:
      kind: radio
      selector: "input[name='condition'][value='{value}']"
      value_map:
        new: new
        open_box: openbox
    source: heuristic
    confidence: 0.9

  brand:
    ui:
      kind: checkbox
      selector: "input[name='brand'][value='{value}']"
      value_map:
        amd: "AMD"
        intel: "Intel"
    source: llm
    confidence: 0.8

  location:
    ui:
      kind: select
      selector: "select[name='location']"
    source: heuristic
    confidence: 0.85

  shipping:
    ui:
      kind: checkbox
      selector: "#free-shipping"
    source: heuristic
    confidence: 0.8

  sort:
    ui:
      kind: select
      selector: "select[name='sort']"
      value_map:
        price_asc: "price_asc"
        newest: "newest"
    source: heuristic
    confidence: 0.9

extraction:
  item_selector: ".browsingitem"
  title_selector: ".name"
  price_selector: ".price"
  link_selector: ".browsinglink, a"
  condition_selector: "[data-almostnew]"
  seller_selector: null
  location_selector: null
```

### 6.3 FilterSpec

| Field | Required | Meaning |
|---|---|---|
| `url.param` | no | Query parameter name; value is URL-encoded |
| `url.value_map` | no | Canonical value to site value; identity when absent |
| `ui.kind` | no | `input`, `select`, `checkbox`, `radio`, `button` |
| `ui.selector` | no | CSS selector; `{value}` is replaced with the mapped value |
| `ui.value_map` | no | Canonical value to site label/value |
| `ui.wait_selector` | no | Selector to wait for after applying this filter |
| `source` | yes | `heuristic`, `llm`, or `manual` |
| `confidence` | yes | 0.0–1.0; used for candidate ranking |
| `sample_value` | no | Value used during validation |

A filter is valid when it has at least one of `url` or `ui`. A profile with no valid filter for a requested key reports that key as unsupported.

Arbitrary filters are stored under `filters.extras`, keyed by the extra name:

```yaml
filters:
  extras:
    socket:
      url:
        param: socket
      ui:
        kind: select
        selector: "select[name='socket']"
      source: llm
      confidence: 0.75
```

Runtime looks up `filters.extras[key]` for each `SearchFilters.extras` entry.

### 6.4 Status lifecycle

| Status | Meaning | Runtime behaviour |
|---|---|---|
| `validated` | Search/extraction replay succeeded | Use profile |
| `draft` | Map exists but validation was inconclusive | Log and fall back to adapter defaults |
| `failed` | No usable search/extraction after retries | Skip site |
| `needs_login` | Login wall detected | Skip until user logs in |
| `blocked` | Anti-bot challenge detected | Skip; selector health records the block |
| `needs_manual` | Search box or filter panel could not be identified automatically | Skip until a manual profile is provided |

`last_verified` is updated only after a successful validation replay.

## 7. Discovery

### 7.1 Entry point

```bash
python scripts/map_site.py discover --all
python scripts/map_site.py discover --site alza --category electronics
python scripts/map_site.py discover --all --resume
python scripts/map_site.py discover --all --force
python scripts/map_site.py validate --all
```

### 7.2 Pipeline

1. Load all sites from `site_registry.SITES`.
2. Expand each site into supported category combinations from `SiteSpec.categories`.
3. Skip combinations already completed in `data/discovery_state.json` unless `--force`.
4. Open a persistent headed Chromium context using the project browser profile.
5. Navigate to the site base URL.
6. Detect anti-bot or login markers:
   - print the reason and instructions,
   - wait for `Enter` to retry or `s` to skip,
   - mark `blocked` or `needs_login` when the user skips or the retry fails.
7. Find the search input with heuristics:
   - `input[type=search]`,
   - `[role=searchbox]`,
   - `input[name*=search]`, `input[id*=search]`,
   - multilingual placeholders (`hľadať`, `search`, `szukaj`, `suchen`),
   - search form containing a submit button.
   - If none match, send a compact DOM summary to the LLM; if still unresolved, mark `needs_manual` and continue.
8. Choose a seed query:
   - default: electronics → `notebook`, appliances → `washing machine`, auto → `car`, general → `deal`,
   - per-site override via `SiteSpec.discovery_queries` (e.g. `sreality` → `byt`, `sauto` → `auto`, `mimibazar` → `notebook`),
   - if the first seed returns zero results, try the next override.
9. Submit the search and wait for results or a stable network state.
10. Capture:
    - final URL, HTML snapshot, screenshot,
    - candidate result cards and field selectors,
    - all form controls and filter-like links.
11. Classify filter candidates:
    - deterministic multilingual dictionary for common labels,
    - structural rules (price inputs near “price”, checkboxes in a filter panel),
    - LLM only for ambiguous labels, using a compact candidate list rather than full HTML.
12. Rank candidates per canonical key by confidence and source; keep alternatives in the raw flow for debugging.
13. Build the sanitized profile and validate it:
    - replay the search URL,
    - apply each mapped URL filter and at least one mapped UI filter,
    - verify at least one result card is extracted,
    - if filters are unsupported, still validate search and report `filters_unavailable`.
14. Save:
    - raw flow: `flows/<site>/<category>.json` (git-ignored),
    - sanitized profile: `src/searcher/site_profiles/<site>.yaml`,
    - state: `data/discovery_state.json` (git-ignored).
15. Print a summary: `validated`, `draft`, `failed`, `blocked`, `needs_login`, `needs_manual`.

### 7.3 Seed queries

`SiteSpec` gains:

```python
discovery_queries: tuple[str, ...] = ()
```

When empty, the category defaults apply. Site-specific examples:

| Site | Category | Seed |
|---|---|---|
| sreality | general | `byt` |
| sauto | auto | `auto` |
| mimibazar | general | `notebook` |
| alza | electronics | `notebook` |
| bazos | auto | `auto` |

### 7.4 Discovery report

The report is written to `results/discovery_<timestamp>.json` and printed as a table. It contains:

| Field | Meaning |
|---|---|
| `sites` | Number of registry sites considered |
| `combinations` | Number of site × category pairs attempted |
| `validated` | Profiles that passed replay |
| `draft` | Profiles saved but not fully validated |
| `failed` | Combinations with no usable result |
| `blocked` | Anti-bot challenge |
| `needs_login` | Login wall |
| `needs_manual` | Search box or filters could not be identified |
| `filters_unavailable` | Search works but one or more requested filters are unsupported |

Counts are computed at run time from `data/discovery_state.json`.

## 8. Runtime

### 8.1 Filter value precedence

1. CLI flags.
2. LLM extraction from the prompt.
3. Config defaults.

CLI values always override prompt-derived values. If both are absent, the filter is not sent.

Global defaults live in `search.default_filters` (a new optional mapping in `SearchConfig`). Per-site overrides can use `WebsiteConfig.extra_params`; the first version uses `extra_params` only for profile selection/debugging, not for filter values.

### 8.2 CLI

```bash
python -m src.cli run \
  --prompt "mini PC do 400 EUR, AMD, bazos" \
  --category electronics \
  --condition used \
  --min-price 100 \
  --max-price 400 \
  --brand amd \
  --location bratislava \
  --shipping free \
  --seller-type classifieds \
  --sort price_asc \
  --filter socket=AM5
```

New options:

| Option | Value |
|---|---|
| `--min-price` | float |
| `--max-price` | float |
| `--brand` | string |
| `--location` | string |
| `--shipping` | `free`, `paid`, `any` |
| `--seller-type` | `retailer`, `marketplace`, `classifieds`, `auction` |
| `--sort` | `price_asc`, `price_desc`, `newest`, `relevance` |
| `--filter KEY=VALUE` | repeatable arbitrary filter |

### 8.3 Prompt extraction

`LLMClient.extract_search_filters(prompt)` returns a `SearchFilters` object plus confidence. The prompt asks for JSON only.

Deterministic fallback covers:

- price: `under 350`, `do 350 €`, `max 400 EUR`, `between 100 and 300`,
- condition: `new`, `used`, `refurbished`, `open-box`, plus Slovak/Czech/German equivalents,
- seller type: `private`, `dealer`, `marketplace`.

Brand and location are LLM-only in the fallback path; CLI values are always available.

### 8.4 Adapter integration

`BaseAdapter` changes:

```python
class BaseAdapter:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or type(self).base_url

    async def search(
        self,
        page,
        query: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
        profile: SiteProfile | None = None,
    ) -> list[Deal]:
        ...
```

Each adapter calls two shared helpers before extraction:

- `_goto_search(page, query, filters, profile)`:
  - if a profile category URL exists, use it,
  - otherwise use `search.url_template` with the query,
  - append URL filter parameters,
  - fall back to the adapter's current hardcoded URL when no profile is available.
- `_apply_filters(page, filters, profile)`:
  - apply mapped UI controls in this order: condition, price, brand, location, shipping, seller type, sort,
  - wait for `ui.wait_selector` or the adapter's `item_selector`,
  - return the list of applied filter keys; log skipped keys.

The existing extraction code stays inside each adapter. This keeps the change small and avoids a full navigation/extraction split.

`alza_cz` and `bazos_cz` are fixed by passing `site.base_url` into the adapter constructor. `PlaywrightSearcher` instantiates adapters as `adapter_cls(base_url=site.base_url)`.

### 8.5 ProfileAdapter

For sites without a bespoke adapter, `ProfileAdapter` uses the profile's `extraction` block:

- `item_selector` finds cards,
- `title_selector`, `price_selector`, `link_selector`, `condition_selector` extract fields,
- missing optional fields are stored as empty metadata,
- cards that cannot produce a title, price, or link are skipped.

`ProfileAdapter` is used only when the profile status is `validated` and `extraction.item_selector` is present. Otherwise the site is skipped with a clear log message.

Adapter selection in `PlaywrightSearcher`:

1. If `site.adapter_class` is registered, use that adapter.
2. If it is not registered and the site has a `validated` profile with extraction selectors, use `ProfileAdapter`.
3. Otherwise skip the site and report `no_adapter`.

### 8.6 Runtime order

For each site:

1. Load the profile.
2. Build the search URL from category/query/filters.
3. Navigate.
4. Apply UI filters that were not expressed in the URL.
5. Let the adapter extract deals.
6. Apply Python post-filters.
7. Sort and deduplicate as today.

### 8.7 Post-filters

Post-filters are the safety net when a site ignores a filter.

| Filter | Behaviour |
|---|---|
| `price_min` / `price_max` | Drop deals with a known price outside the range. Keep unknown prices with a warning. |
| `condition` | Drop deals with a known condition that does not match. Keep unknown conditions. |
| `brand` | Best-effort: if `metadata["brand"]` is non-empty and differs from the requested brand, drop it; otherwise keep and log. |
| `location` | Only if metadata contains a location; otherwise keep. |
| `shipping` | Only if metadata contains shipping information; otherwise keep. |
| `seller_type` | Only if metadata contains seller type; otherwise keep. |
| `sort` | Sort in Python only for `price_asc`/`price_desc`; other sort modes rely on the site. |

Post-filters never remove a deal whose relevant field is unknown.

## 9. Error handling

### Discovery

- Per-site timeout budget: 30 s navigation, 10 s search-box lookup, 15 s filter capture, 30 s validation.
- Anti-bot/login: pause, retry once after user action, then mark `blocked`/`needs_login`.
- No search box: two heuristic fallbacks, LLM fallback, then `needs_manual`.
- Zero results: try the next seed query, then `failed`.
- Invalid profile: save as `draft`; raw flow remains for debugging.
- Resumable state; `--force` re-runs completed combinations.
- Sequential execution with a 2–5 s jitter between sites.

### Runtime

- Invalid `SearchFilters`: reject the invalid field, log, continue.
- Missing/invalid profile: fall back to current adapter behaviour.
- Selector not found: log `filter_not_applied`, continue; post-filter price.
- `SiteBlockedError`: existing path; selector health records the block and the site is skipped for the rest of the run.
- LLM filter extraction failure: deterministic fallback; CLI values still work.
- One site or filter must never crash the whole search.

## 10. Security

- Raw recordings stay in `flows/`, which is git-ignored.
- Sanitization is allowlist-based: only URL templates, selectors, labels, value maps, status, and confidence are kept.
- Stripped from profiles: HTML, screenshots, cookies, headers, `storage_state`, tokens, e-mail addresses, phone numbers.
- URL query parameters matching `token`, `session`, `auth`, `sid`, `key`, `signature` are removed.
- `data/discovery_state.json` and `results/discovery_*.json` are git-ignored.
- Profiles are committed only after a secret-pattern scan.
- The sanitizer is unit-tested with a profile containing fake secrets; the test asserts they are absent.

## 11. Testing

### Unit tests

- `test_site_profiles.py`: schema validation, status gating, sanitizer strips secrets, invalid profiles rejected.
- `test_filter_engine.py`: URL building, URL encoding, value maps, category URL precedence, UI dispatch for input/select/checkbox/radio/button, unsupported filter handling.
- `test_search_filters.py`: CLI override precedence, prompt extraction with a mock LLM, deterministic price/condition fallback, invalid range rejection.
- `test_post_filters.py`: price, condition, brand, sort; unknown values are kept.
- `test_adapter_filters.py`: each existing adapter accepts `filters`/`profile` and calls the shared hooks with a fake page.
- `test_profile_adapter.py`: extraction from sanitized HTML fixtures.

### Fixture tests

- Save sanitized HTML snapshots for Alza, Bazos, Mall, and Heureka under `tests/fixtures/site_profiles/`.
- No live network in unit tests.

### Integration and live tests

- `map_site.py validate --all`: offline schema and URL-builder validation.
- `@pytest.mark.live` discovery smoke for one site, skipped by default.
- Existing live tests remain opt-in.

### Regression baseline

- Existing suite: **198 passed, 11 skipped** at design time.
- Ruff clean on touched files.
- No changes to judge/ranking output when no filters are requested.

## 12. Delivery phases

All 21 sites are in scope. Phases define implementation order, not scope reduction.

Each phase gets its own implementation plan. The first plan covers Phase 0 and Phase 1 only; later phases start after their predecessor passes its exit criteria.

### Phase 0 — Foundation

Deliverables:

- `SearchFilters` model and validation.
- `SearchConfig.default_filters` optional mapping.
- `SiteProfile` schema, loader, validator, sanitizer, including `filters.extras`.
- `BaseAdapter(base_url=...)` and shared hook signatures.
- `SiteSpec.discovery_queries`.
- Unit tests for the above.

Exit criteria: existing suite still green; no runtime behaviour change.

### Phase 1 — Runtime filters

Deliverables:

- `FilterEngine` (URL build, UI apply, post-filter, sort).
- CLI flags and prompt extraction.
- Integration into the five existing adapters.
- Tests for URL/UI/post-filter/precedence.

Exit criteria: filtering works on Alza and Bazos live; unfiltered runs behave as before.

### Phase 2 — Discovery and ProfileAdapter

Deliverables:

- `map_site.py discover` and `validate`.
- `ProfileAdapter`.
- Sanitized profiles for the seven site entries that reuse an existing adapter: Alza, Bazos, Alza.cz, Bazos.cz, BackMarket, eBay, Facebook.
- Discovery report.

Exit criteria: at least Alza, Bazos, Alza.cz, and Bazos.cz are `validated`; blocked/login sites are reported with the correct status.

### Phase 3 — Remaining sites

Deliverables:

- Discovery runs for Mall, Nay, Datart, Heureka, Idealo, Aukro, Sbazar, Amazon.de, AliExpress, Prisiel, Bazar.sk, Sauto, Sreality, Mimibazar.
- `ProfileAdapter` validation; bespoke adapters only where generic extraction fails.
- `config.example.yaml` entries for all 21 sites, with `enabled` reflecting their validated status.
- `SiteSelectionAgent` derives its capabilities from `site_registry` instead of the current five-site hardcoded dict.
- Updated profiles and report.

Exit criteria: all 21 sites are attempted; every site has a status and a reason.

### Phase 4 — Full run, docs, cleanup

Deliverables:

- Full live run and report.
- README/CHANGELOG updates.
- `.gitignore` verification for flows, state, and discovery reports.
- Final test run and ruff.

Exit criteria: acceptance criteria below are met.

## 13. Acceptance criteria

- Discovery attempts all 21 sites and writes a report.
- All seven site entries that reuse an existing adapter (five adapters plus the Alza.cz and Bazos.cz aliases) are attempted.
- At least four reachable sites have a `validated` profile; blocked/login sites have their own explicit status.
- Every non-validated site has an explicit status and reason.
- Runtime applies `price_min`/`price_max` and `condition` wherever the site supports them.
- When a site ignores a filter, the post-filter applies it when the data is known, and logs when it is not.
- CLI flags override prompt-derived values.
- No cookies, tokens, HTML, or personal data appear in committed profiles.
- Existing tests remain green; new tests cover the filter engine, profiles, sanitizer, and prompt extraction.
- `alza_cz` and `bazos_cz` search their own base URLs, not the `.sk` sites.

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Anti-bot blocks during discovery | Headed browser, pause/resume, status `blocked`, no repeated hammering |
| DOM changes break selectors | `last_verified`, validation replay, `draft` status, easy re-discovery |
| Generic extraction misreads cards | Validation requires at least one card; fall back to `draft`/bespoke adapter |
| LLM labels filters incorrectly | Heuristics first, confidence score, manual review, alternatives kept |
| Long discovery run for 21 sites | Sequential + resumable state + per-site report |
| Filter values not supported by a site | URL → UI → post-filter, with explicit `filter_not_applied` logs |
| Secrets leak into profiles | Allowlist sanitizer, secret-pattern scan, raw flows git-ignored |
| Scope grows into full adapter generation | Non-goal; `ProfileAdapter` is best-effort, bespoke adapters remain |

## Appendix A — Site matrix

| ID | Site | URL | Categories | Current state | Adapter |
|---|---|---|---|---|---|
| alza | Alza.sk | https://www.alza.sk | electronics, appliances | working | alza |
| bazos | Bazos.sk | https://www.bazos.sk | electronics, appliances, auto, general | working | bazos |
| backmarket | BackMarket.sk | https://www.backmarket.sk | electronics | blocked | backmarket |
| ebay | eBay.de | https://www.ebay.de | electronics, appliances, auto, general | blocked | ebay |
| facebook | Facebook Marketplace | https://www.facebook.com/marketplace | electronics, appliances, auto, general | needs_auth | facebook |
| alza_cz | Alza.cz | https://www.alza.cz | electronics, appliances | planned | alza (reuse) |
| bazos_cz | Bazos.cz | https://www.bazos.cz | electronics, appliances, auto, general | planned | bazos (reuse) |
| mall | Mall.sk | https://www.mall.sk | electronics, appliances, auto, general | planned | ProfileAdapter |
| nay | Nay.sk | https://www.nay.sk | electronics, appliances | planned | ProfileAdapter |
| datart | Datart.sk | https://www.datart.sk | electronics, appliances | planned | ProfileAdapter |
| heureka | Heureka.sk | https://www.heureka.sk | electronics, appliances, auto, general | planned | ProfileAdapter |
| idealo | Idealo.de | https://www.idealo.de | electronics, appliances, auto | planned | ProfileAdapter |
| aukro | Aukro.cz | https://aukro.cz | electronics, appliances, auto, general | planned | ProfileAdapter |
| sbazar | Sbazar.cz | https://www.sbazar.cz | electronics, appliances, auto, general | planned | ProfileAdapter |
| amazon_de | Amazon.de | https://www.amazon.de | electronics, appliances, auto, general | planned | ProfileAdapter |
| aliexpress | AliExpress | https://www.aliexpress.com | electronics, appliances, auto, general | planned | ProfileAdapter |
| prisiel | Prisiel.sk | https://www.prisiel.sk | electronics | planned | ProfileAdapter |
| bazar_sk | Bazar.sk | https://www.bazar.sk | electronics, appliances, auto, general | planned | ProfileAdapter |
| sauto | Sauto.cz | https://www.sauto.cz | auto | planned | ProfileAdapter |
| sreality | Sreality.cz | https://www.sreality.cz | general | planned | ProfileAdapter |
| mimibazar | Mimibazar.sk | https://www.mimibazar.sk | electronics, appliances, auto, general | planned | ProfileAdapter |

## Appendix B — CLI examples

```bash
# Discover everything, resumable
python scripts/map_site.py discover --all --resume

# Discover one site/category
python scripts/map_site.py discover --site alza --category electronics

# Offline validation of all committed profiles
python scripts/map_site.py validate --all

# Filtered search
python -m src.cli run \
  --prompt "mini PC do 400 EUR, AMD" \
  --category electronics \
  --condition used \
  --max-price 400 \
  --brand amd \
  --sort price_asc
```
