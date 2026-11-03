# Site Catalog and Unlimited Site Selection — Design

Date: 2026-11-03
Status: approved in session
Scope: site catalogue, site selection, cookie sessions and the first new
adapters/profiles. Report restructuring and Google/Bing discovery are separate
sub-projects.

## 1. Problem

The searcher is capped at eight shops per round and the `ask` wizard asks the
user how many shops to open. The user does not want a count question: either
they name the shops, or the LLM decides which shops are genuinely suitable,
with no upper bound.

The catalogue also misses shops the user actually buys from:

* Amazon.de and eBay.de (browser scraping with the user's cookies);
* nkon.nl (new and used batteries, chargers);
* ecoprodukt.sk (photovoltaics, batteries, used/open-box);
* Solaro.sk (photovoltaics, batteries; currently behind Cloudflare);
* Nay.sk (electronics).

The LLM currently sees only id/name/country/categories. It does not know that
nkon sells batteries or that ecoprodukt sells solar components, so it cannot
classify specialty shops correctly.

## 2. Verified facts (2026-11-03, Playwright headless)

| Site | Result | Evidence |
|---|---|---|
| Amazon.de | 200 | Search page loads; cookie consent banner; result grid present |
| eBay.de | 403 | Direct `/sch/i.html` returns "Error Page"; homepage also 403 headless |
| nkon.nl | 200 | Magento; search form posts to `/en/catalogsearch/result/?q=` |
| ecoprodukt.sk | 200 | Search and product cards render |
| Nay.sk | 200 | Search form posts to `/vyhladavanie?q=`; profile `nay.yaml` is validated |
| Solaro.sk | 403 | Cloudflare "Len chvíľu..." challenge |
| Planeo.sk | 403 | Geo-block "Blocked - Access Restricted" |
| CZC.cz | 403 | Redirects to Allegro |
| Datart.sk / Hej.sk | 200 | Both redirect to Nay.sk |
| TS Bohemia | 403 | Bot wall |

Current code facts:

* `SearchConfig.max_sites` defaults to `8`
  (`src/config/models.py`), and `_select_sites` slices the LLM result
  (`src/searcher/playwright_searcher.py:220-222`).
* `SiteSelector._llm_pick` hardcodes "Pick at most 6"
  (`src/searcher/site_selection.py`).
* `SiteCandidate` carries id, name, country, currency, categories, conditions,
  status and adapter class; it has no notes or specialty keywords.
* The selection cache key is `(condition, category)` and ignores the prompt, so
  a battery search and a laptop search in the same category share a selection.
* `ask` asks "Max shops" when `--max-sites` is omitted
  (`src/cli/app.py:149-150`).
* `scripts/login.py` writes `data/sessions/<site>.json`, but the search flow
  never loads those cookies into the browser context.
* `amazon_de` is in the registry as `planned`; `ebay` is `blocked`; both are
  disabled in `config.yaml`. `nay` is `planned` and disabled, although
  `nay.yaml` is validated. nkon, ecoprodukt and solaro are absent.
* `amazon_de.yaml` is `draft` with generic selectors and no working result
  cards. An Amazon adapter is the reliable route, not that profile.

## 3. Goals

* G1 — No site-count question. `max_sites = 0` means unlimited; the `ask`
  wizard no longer asks.
* G2 — The user can name shops explicitly with `--sites`; that list is
  authoritative and bypasses the LLM.
* G3 — Otherwise the LLM classifies every runnable candidate using the product
  prompt, shop notes and specialty keywords, and may select all of them.
* G4 — The LLM can only return candidate ids; it can never invent or widen the
  runnable set.
* G5 — Add Amazon.de, eBay.de, nkon.nl, ecoprodukt.sk, Solaro.sk and Nay.sk to
  the catalogue with honest statuses.
* G6 — Load saved cookie sessions per site before searching, so eBay/Amazon and
  Cloudflare-protected shops can work with a real login.
* G7 — The report lists which shops were searched and which were skipped, with
  a reason.
* G8 — Blocked or unvalidated shops never produce a silent empty result.

## 4. Non-goals

* Google/Bing web discovery and profile proposals (sub-project 3).
* Moving the winner and full detail to the top of the report (sub-project 4).
* AliExpress, or any marketplace whose supported route is an official API.
* Solving Cloudflare or geo-blocks in code. A blocked site stays catalogue-only
  until a real session or a different route works.
* LLM spec extraction (GPU, CPU, camera, battery) beyond price quotes.
* Replacing the existing adapters for Alza, Bazos or Facebook.

## 5. Catalogue changes

### 5.1 Model

`SiteSpec` and `SiteCandidate` gain:

```python
notes: str = ""
specialties: tuple[str, ...] = ()
```

`SiteSpec.status` keeps `working | blocked | needs_login | planned`.
`specialties` are lowercase keywords used by the selector and the report, e.g.
`("battery", "18650", "charger", "used")`.

### 5.2 New entries

| id | name | base_url | status | categories | specialties |
|---|---|---|---|---|---|
| `amazon_de` | Amazon.de | `https://www.amazon.de` | `working` after adapter verification | electronics, appliances, auto, general, home, hobby | marketplace, broad |
| `ebay` | eBay.de | `https://www.ebay.de` | `needs_login` | electronics, appliances, auto, general, home, hobby | marketplace, used, refurbished |
| `nkon_nl` | NKON.nl | `https://www.nkon.nl` | `working` after profile validation | electronics, hobby | battery, 18650, lifepo4, charger, used |
| `ecoprodukt_sk` | Ecoprodukt.sk | `https://ecoprodukt.sk` | `working` after profile validation | electronics, home, hobby | solar, photovoltaic, battery, inverter, used, open_box |
| `solaro_sk` | Solaro.sk | `https://solaro.sk` | `blocked` | electronics, home, hobby | solar, photovoltaic, battery, inverter |
| `nay` | Nay.sk | `https://www.nay.sk` | `working` (profile validated) | electronics, appliances | electronics, retailer |

Rejected after live checks, with the reason recorded in the design and commit
message: Planeo.sk (geo-block), CZC.cz (redirects to Allegro), TS Bohemia
(403), Datart.sk and Hej.sk (redirect to Nay).

`nay` already exists as `SiteSpec("nay", ...)`. Keep the existing id to preserve
`nay.yaml` and config compatibility; rename the display name to "Nay.sk" only.

### 5.3 Config

Add/enable entries in both `config.yaml` and `config.example.yaml`:

* `amazon_de`: enabled, `adapter_class: amazon`, `requires_login: false`.
* `ebay`: enabled, `adapter_class: ebay`, `requires_login: true`.
* `nkon_nl`, `ecoprodukt_sk`: enabled, `adapter_class` equal to the site id
  (profile-backed; `_filter_sites` falls back to the profile when no adapter
  exists).
* `nay`: enabled, `adapter_class: nay`, profile-backed.
* `solaro_sk`: disabled, `adapter_class: solaro_sk`; registry status `blocked`.

`config.example.yaml` must remain loadable by `tests/test_config_example.py`.

## 6. Selection

### 6.1 Candidate construction

`PlaywrightSearcher._select_sites` passes every runnable site with `notes` and
`specialties` from the registry. A site is runnable only when:

1. it is enabled in config;
2. its adapter matches the requested condition and category, or its profile is
   runtime-ready;
3. its registry status is `working` or `needs_login`; and
4. a `needs_login` site has a saved session
   (`src/searcher/sessions.has_session(site.name)`).

`blocked` and `planned` sites are never runnable. `needs_login` without a
session is runnable only when the user explicitly lists it in `--sites`; in
that case the adapter still tries, and a block is reported. `_filter_sites`
therefore accepts the requested set and enforces the session gate only for
non-requested sites. Skipped sites are recorded with a reason, never silently
dropped.

### 6.2 LLM prompt

The selector prompt becomes:

```
You choose which online shops are worth searching for one product request.
The user shops in {country}. Prefer local shops, then neighbouring markets.
Use the specialties and notes: a battery request belongs on nkon/ecoprodukt,
a solar request on solaro/ecoprodukt, a general electronics request on
amazon/nay/alza. Select EVERY shop that is genuinely useful. There is no
count limit; do not stop at 6.
Return ONLY JSON:
{"selected": ["site_id", ...], "reasoning": "one short sentence"}.
Use only ids from the list. An empty list is valid when no shop fits.
```

* The LLM may return all candidates.
* Unknown ids are ignored.
* A valid empty list means "no suitable shop"; the search returns no deals
  instead of opening unrelated shops.
* Malformed JSON, a timeout or a missing LLM falls back to **all runnable
  candidates**, with reasoning "Ranked by market distance (no usable LLM
  selection)."
* `max_sites > 0` is an optional hard cap (backward compatibility). `0` or
  `None` is unlimited.

### 6.3 User-selected shops

`--sites amazon_de,ebay,nkon_nl` (CLI on `run`, `ask` and `search`) or
`sites=[...]` (API):

* matches case-insensitively against `SiteSpec.id`, `SiteSpec.name` and
  `WebsiteConfig.name`;
* is applied to the runnable candidates before the LLM;
* bypasses the LLM entirely;
* an unknown name raises `ValueError` listing the known ids;
* a known but blocked/disabled name is recorded as skipped with the registry
  status as the reason.

### 6.4 Cache and prompt

Selection is computed once per run from the original user prompt, not from each
round's rewritten query. The cache key is
`(condition, category, original_prompt, frozenset(requested_sites))`.
`on_sites` is called once with the final selected list.

## 7. Sessions and scraping

### 7.1 Cookie sessions

New module `src/searcher/sessions.py`:

```python
SESSION_DIR = Path("data/sessions")

def session_path(site_id: str) -> Path: ...
def has_session(site_id: str) -> bool: ...
def load_cookies(site_id: str) -> list[dict]: ...
async def apply_session(context, site_id: str) -> bool: ...
```

`apply_session` reads `data/sessions/<site>.json` and calls
`context.add_cookies(cookies)`. A missing or malformed file is not an error:
it returns `False` and the normal browser profile is used. `data/` is already
git-ignored.

`PlaywrightSearcher._execute_round` calls `apply_session` for every site before
the adapter/profile search.

### 7.2 Login script

`scripts/login.py`:

* add login URLs for `amazon_de`, `ebay`, `nkon_nl`, `ecoprodukt_sk`,
  `nay`, `solaro_sk`;
* resolve a profile-only site through `src.searcher.site_registry.by_id` when
  `get_adapter` raises `ValueError`;
* `--list` includes sites from `browser.login_sites` plus adapters with
  `requires_login = True`;
* `--check` uses the registry base URL when no adapter exists.

No credentials are stored in the repository; only cookies under `data/`.

### 7.3 Amazon adapter

New `src/searcher/adapters/amazon.py`, registered as `amazon`:

* search URL: `https://www.amazon.de/s?k={query}`;
* result cards: `div[data-component-type="s-search-result"]`;
* title: `h2 a span` or `h2 span`;
* price: `.a-price .a-offscreen`, with `.a-price-whole` +
  `.a-price-fraction` as fallback;
* link: `h2 a` or `a.a-link-normal`;
* condition: title/subtitle text (`Used`, `Renewed`, `Neu`);
* full card text goes to `metadata["card_text"]`; the existing
  `extract_price_signals`/`build_price_quote` attaches the quote;
* block detection: `/errors/validateCaptcha`, title `Robot Check`, body
  `Enter the characters you see below`;
* `seller_type = "marketplace"`, `has_warranty = False`.

### 7.4 eBay

Keep the existing adapter but:

* attach `price_quote` and `metadata["card_text"]` like Alza/Bazos;
* detect `Pardon Our Interruption`, `Error Page`, and 403 as a block;
* rely on the saved cookie session and the existing search-box fallback.

### 7.5 Profiles

`nkon_nl.yaml` (Magento):

* `url_template: https://www.nkon.nl/en/catalogsearch/result/?q={query}`;
* item selector `li.product-item`;
* title `.product-item-link`; price `.price`; link `.product-item-link`;
* condition from card text (`Used`, `New`, `Refurbished`).

`ecoprodukt_sk.yaml` (WooCommerce):

* `url_template: https://ecoprodukt.sk/?s={query}&post_type=product`;
* item `ul.products li.product`;
* title `.woocommerce-loop-product__title`; price `.price`;
* link `a.woocommerce-LoopProduct-link`.

`nay.yaml` is already validated; enable it and keep its selectors.

`solaro_sk.yaml` can be added as `blocked` with the same WooCommerce shape, but
must not be selected while its status is blocked.

Profiles are committed only after `scripts/discover_sites.py validate --site
<id>` (or an equivalent replay) passes; until then the registry status stays
`planned` and `_filter_sites` skips them. The status is changed to `working` in
the same commit only when the replay passes.

## 8. Report

`PlaywrightSearcher` exposes a `SitePlan`:

```python
@dataclass
class SitePlan:
    selected: list[str]
    reasoning: str
    skipped: list[dict]  # {"name": ..., "reason": ...}
```

`run_search` passes it to `ResultProcessor.save_results(..., site_plan=...)`.
The JSON payload gains `site_plan`, and Markdown gains a `## Shops searched`
section before the summary:

```markdown
## Shops searched

Selected automatically: alza, nkon_nl, ecoprodukt_sk, amazon_de.
Reason: battery request; local retailers and battery specialists.

Skipped: solaro_sk (Cloudflare block), ebay (no saved session).
```

If the user passed `--sites`, the section says "Requested by the user" and
lists the resolved shops.

## 9. Backward compatibility

* `max_sites` remains in `SearchConfig`; `0` is the new default, but an explicit
  positive value keeps the old cap behaviour.
* `--max-sites` remains an optional flag; omitting it no longer asks a question.
* `SiteSpec`/`SiteCandidate` fields are optional with defaults.
* `save_results` accepts `site_plan=None`; old callers and tests keep working.
* Existing profiles and adapters are unchanged except eBay quote attachment.
* No new third-party dependency.

## 10. Testing

Unit tests:

* `tests/test_site_selection.py`: no cap; LLM may select all; empty list means
  no shops; malformed response falls back to all; unknown ids ignored.
* `tests/test_site_registry.py`: every new id is unique; blocked sites are not
  runnable; specialties are lowercase.
* `tests/test_playwright_site_selection.py`: `--sites` bypasses the LLM;
  unknown name raises; blocked requested site is skipped with a reason; cache
  key includes the prompt.
* `tests/test_sessions.py`: missing file returns `False`; valid cookies are
  added to a fake context; malformed JSON is ignored.
* `tests/test_amazon_adapter.py`: fake cards produce a Deal with a quote;
  captcha page is detected as blocked.
* `tests/test_adapters.py`: eBay quote and block markers.
* `tests/test_profile_adapter.py`: nkon/ecoprodukt fake cards extract title,
  price, URL and quote.
* `tests/test_ask.py` / `tests/test_cli.py`: `ask` does not prompt for a shop
  count; `--sites` is parsed and forwarded.
* `tests/test_processor_details.py`: `## Shops searched` appears with selected
  and skipped entries; JSON contains `site_plan`.

Integration tests:

* `ProfileAdapter` over a saved nkon/ecoprodukt fixture;
* `PlaywrightSearcher._select_sites` with a fake LLM returning all candidates;
* report rendering with a skipped blocked site.

Live verification (manual, after implementation):

1. `python scripts/login.py --site ebay` and `--check`.
2. `python -m src.cli run --prompt "18650 battery" --sites nkon_nl,ecoprodukt_sk --debug`
3. `python -m src.cli run --prompt "solar inverter" --debug` (LLM should pick
   ecoprodukt/solaro only if runnable).
4. Confirm the report lists the selected and skipped shops.

## 11. Risks

* Amazon/eBay DOM changes often; the adapters are intentionally small and the
  block detector fails fast.
* eBay headless is 403 without cookies. A missing session means a skipped site
  with a clear reason, not a silent empty result.
* Solaro's Cloudflare challenge may still block even with cookies. It remains
  `blocked` until a real session passes.
* More sites means longer runs. The user explicitly accepted an unbounded
  count; `--max-sites` remains as an emergency cap.
* An LLM selection can be wrong. It is constrained to runnable candidate ids;
  the user's `--sites` bypasses it; the report explains the choice.
* New profiles can rot. The profile status and `last_verified` date are the
  guard; a failed replay keeps the site out of the runnable set.

## 12. Rollout

1. Extend `SiteSpec`/`SiteCandidate` with notes and specialties; add registry
   entries and config entries.
2. Remove the count question and the hard cap; add `--sites`; update selection
   prompt, cache and fallback.
3. Add `sessions.py`, extend `login.py`, and apply sessions in the search loop.
4. Add the Amazon adapter; attach eBay quotes and block detection.
5. Add/validate nkon, ecoprodukt and Solaro profiles; enable Nay.
6. Add `SitePlan` to the search/report flow.
7. Update README/CHANGELOG; run the full suite and the live smoke tests.
