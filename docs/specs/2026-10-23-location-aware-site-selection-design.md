# Location-Aware Site Selection, Currency Normalisation and New Sites — Design

- **Date:** 2026-10-23
- **Status:** Approved for implementation
- **Scope:** 19 new sites on top of the existing 21; new `home`/`hobby` categories; currency normalisation; AI-driven site selection based on the user's country
- **Related code:** `src/searcher/site_registry.py`, `src/searcher/site_selection.py` (new), `src/searcher/currency.py` (new), `src/searcher/playwright_searcher.py`, `src/agents/research/site_selection.py`, `src/config/models.py`, `config.example.yaml`

## 1. Problem

Three separate gaps block the project from being useful for the actual user need (auto markets, electronics, hobby/home goods, and deciding which shops to look at based on where the user lives).

**Gap 1 — the category taxonomy cannot express the new domains.** `Category` has exactly four values: `electronics`, `appliances`, `auto`, `general`. Furniture, DIY, garden, tools and sport have no home. Mapping OBI or JYSK into `general` would make the searcher visit them for a drone query.

**Gap 2 — the AI does not choose the sites.** `SiteSelectionAgent` exists but carries a hardcoded five-entry `SITE_CAPABILITIES` dict, and its result is not used by the normal search path: `PlaywrightSearcher._filter_sites` filters deterministically on `enabled` + adapter capabilities + profile readiness, and `search_with_diamond` calls `self.search()` which re-filters the same way. The agent's `selected_sites` never reaches the browser.

**Gap 3 — prices outside EUR are wrong.** `parse_price_eur` returns the first number it finds and treats it as EUR. Czech portals (bazos.cz, garaz.cz, tipcars.com, auto.cz, hobbyshop.cz, mironet.cz) and Czech Alza quote in Kč. A 242 000 Kč car would be recorded as €242 000 — roughly 25× too high. The Bazos adapter is worse: its regex requires a literal `€`, so on bazos.cz it extracts nothing at all.

**Gap 4 — there is no notion of the user's location.** Neither the registry nor the config knows where the user is, so nothing can prefer domestic shops over cross-border ones.

## 2. Goals

- Add `home` and `hobby` categories so furniture/DIY/sport sites can be targeted precisely.
- Register 19 verified, reachable sites across auto markets, electronics, home/DIY, furniture and hobby.
- Normalise every price to EUR, keeping the original amount and currency.
- Let the LLM choose which candidate shops to visit, informed by the user's country and the site's market, with a deterministic fallback.
- Keep the existing 21 sites, adapters, filters and profiles working unchanged.

## 3. Non-goals

- Live FX fetching. Rates are static and user-overridable.
- Cross-border shipping cost modelling beyond the currency conversion.
- Bypassing bot walls on Decathlon, Sportisimo or Hornbach — they are registered as `blocked`.
- Replacing `PlaywrightSearcher._filter_sites` with an LLM-only decision. The deterministic filter stays as the hard gate.

## 4. Verified new sites

All URLs were checked with HTTP HEAD/GET plus `<title>` parsing. Only reachable domains are registered.

| id | URL | Country | Currency | Categories |
|---|---|---|---|---|
| `autobazar_sk` | https://www.autobazar.sk | SK | EUR | auto |
| `autobazar_eu` | https://www.autobazar.eu | EU | EUR | auto |
| `autobazar_cz` | https://www.autobazar.cz | CZ | CZK | auto |
| `garaz_cz` | https://www.garaz.cz | CZ | CZK | auto |
| `tipcars_cz` | https://www.tipcars.com | CZ | CZK | auto |
| `auto_cz` | https://www.auto.cz | CZ | CZK | auto |
| `mobile_de` | https://www.mobile.de | DE | EUR | auto |
| `obi_sk` | https://www.obi.sk | SK | EUR | home, hobby |
| `merkurymarket_sk` | https://www.merkurymarket.sk | SK | EUR | home, hobby |
| `dek_sk` | https://dek.sk | SK | EUR | home, hobby |
| `bauhaus_sk` | https://www.bauhaus.sk | SK | EUR | home, hobby |
| `hornbach_sk` | https://www.hornbach.sk | SK | EUR | home, hobby (bot wall) |
| `jysk_sk` | https://jysk.sk | SK | EUR | home |
| `favi_sk` | https://favi.sk | SK | EUR | home (comparator) |
| `ikea_sk` | https://www.ikea.com/sk/sk/ | SK | EUR | home |
| `herman_sk` | https://www.herman.sk | SK | EUR | hobby |
| `hobbyshop_cz` | https://www.hobbyshop.cz | CZ | CZK | hobby |
| `decathlon_sk` | https://www.decathlon.sk | SK | EUR | hobby (bot wall) |
| `mironet_cz` | https://www.mironet.cz | CZ | CZK | electronics |

Rejected after verification: `fovi.sk` (does not resolve), `kika.sk` (connection timeout), `mall.cz` (redirects to allegro.cz), `electroworld.cz` (redirects to datart.cz), `auto.cz` without `www` (404), `autovitry.cz` (DNS failure), `gastroart.sk` / `vavc.sk` / `konzoleshop.sk` / `digitalstore.sk` / `gigafabrik.sk` / `nabytokonline.sk` / `skladme.sk` / `interio.sk` / `betreten.sk` (DNS failure), `sportisimo.sk` and `tsbohemia.cz` (Cloudflare wall → not registered).

## 5. Design

### 5.1 Categories

`Category` gains `HOME = "home"` and `HOBBY = "hobby"`. `SiteSpec.categories` for the new sites uses these. The CLI help strings and `market_intel`'s price-benchmark table are extended to match.

### 5.2 Currency normalisation

New module `src/searcher/currency.py`:

```text
DEFAULT_RATES = {"EUR": 1.0, "CZK": 0.0265, "USD": 0.92, "GBP": 1.16}
detect_currency(text) -> str | None      # €, Kč, CZK, $, USD
to_eur(amount, currency, rates) -> float
parse_price(text, default_currency, rates) -> (eur_amount, original_currency) | None
```

`Deal` gains `original_price: float | None` and `original_currency: str`. `price_eur` always holds the EUR value; the raw amount and currency are kept on the deal and mirrored into `metadata` so the storage layer keeps both. `storage/manager.py` already persists `original_currency`, so no schema change is needed.

`SiteProfile` gains `currency: str = "EUR"`, filled by the discovery script from the registry. `ProfileAdapter` uses the profile currency as the default when the price text carries no symbol. The Bazos adapter stops requiring a literal `€` and parses Kč as well.

Rates live in `search.currency_rates` in the config so they can be corrected without a code change.

### 5.3 Location-aware site selection

New module `src/searcher/site_selection.py`:

```text
SiteCandidate(id, name, country, currency, categories, conditions, status, priority)
rank_by_location(candidates, user_country) -> list[SiteCandidate]
    # domestic market first, EU/EEA neighbours second, rest last
class SiteSelector:
    async select(candidates, prompt, user_country, max_sites, llm) -> SelectionResult
        # LLM picks a subset; ids outside the candidate set are dropped;
        # empty/invalid answer falls back to the deterministic ranking
```

`SiteSelectionAgent` is rewritten to derive its capabilities from the registry instead of a hardcoded dict, and gains an LLM-backed `select()` that returns `{selected_sites, reasoning}`.

`PlaywrightSearcher` gets an async `_select_sites(condition, category, prompt)` layered on top of the existing deterministic `_filter_sites`:

1. `_filter_sites` produces the runnable candidates (enabled + category/condition + adapter or validated profile).
2. `rank_by_location` orders them by the user's country.
3. The LLM picks the final subset, capped by `search.max_sites`.
4. The result is cached per `(condition, category)` for the lifetime of the searcher, so it is computed once per run, not once per round.

The deterministic filter is never bypassed. The LLM can only narrow the candidate set, never widen it.

### 5.4 Configuration

```yaml
search:
  user_country: "SK"
  user_city: ""
  max_sites: 8
  currency_rates:
    EUR: 1.0
    CZK: 0.0265
```

`max_sites` caps how many shops are opened per run. With 40 registered sites, opening all of them per round is not viable.

## 6. Testing

- `tests/test_currency.py` — symbol detection, CZK→EUR conversion, decimal separators, unknown symbol fallback.
- `tests/test_site_selection.py` — ranking by country, LLM selection restricted to candidates, fallback on garbage/empty LLM answer, cap enforcement.
- `tests/test_site_registry.py` — updated status counts, new categories in the known set, new sites present with country/currency.
- `tests/test_config_example.py` — the site ids in `config.example.yaml` match the registry exactly, in both directions.
- `tests/test_playwright_searcher_filters.py` — selection caching and the cap.

## 7. Rollout

All 19 new sites are registered as `planned` and disabled in `config.example.yaml`. They become usable exactly like the existing planned sites: run `scripts/discover_sites.py discover --site <id> --headed`, validate the profile, then set `enabled: true`.
