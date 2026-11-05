# Design: Item Specs Research & Review Reading (Sub-project 1)

**Date:** 2026-11-05  
**Deep research goal:** LLM integration (structured extraction, review reading) + search quality (web research for specs)  
**Status:** Draft — awaiting implementation  

## Problem

The replacement finder ("find me a replacement for Citroen eC3") needs to first research the specs of the reference item before it can search for alternatives. Currently the codebase can extract filters from a user prompt (`extract_search_filters`) and classify price quotes, but it cannot:

1. Research an arbitrary item's specs from the web (EV range, battery kW, weight, dimensions, price)
2. Read and summarize reviews for that item
3. Normalize specs into a structured, comparable format across categories (cars, electronics, appliances)

Without step 1, the system cannot generate the spec-based filters needed to find similar replacements.

## Scope

**In scope:**
- `ItemSpecsResearcher` class: takes an item name + optional category, queries the web, extracts structured specs via LLM
- Spec schema: category, condition, power (kW/hp), weight (kg), dimensions (L×W×H mm), battery (kWh for EVs), range_km, price_eur, brand, model, year, plus free-form `extras` dict
- Review reading: search for "[item] review", fetch snippets, summarize pros/cons via LLM
- `ItemSpecs` dataclass stored in SQLite `item_specs` table (new table) for reuse across runs
- Config option `specs_research.enabled` (default true) and `specs_research.default_category` (default "auto")
- CLI: `ads research-specs --item "Citroen eC3"` command that prints specs + review summary

**Out of scope (later sub-projects):**
- Searching for similar items based on specs (Sub-project 2)
- Replacement report format (Sub-project 3)
- Parallel/caching architecture (Sub-project 4)

## Architecture

```
ItemSpecsResearcher
├── web_search(query) -> list[WebSource]      (reuse src/research/web_search.py)
├── extract_specs(snippets, item_name) -> ItemSpecs   (LLM via chat_json)
├── extract_reviews(snippets) -> ReviewSummary         (LLM via chat_json)
└── save(item_specs) -> None                        (SQLite item_specs table)
```

- Reuses `LLMClient.chat_json` for structured JSON extraction
- Reuses `WebSource`/DuckDuckGo search from `src/research/web_search.py`
- New table `item_specs` in SQLite: id, item_name, category, specs_json, review_json, researched_at, source_urls
- New module: `src/intelligence/specs_researcher.py`
- New CLI command: `src/cli/commands/research_specs.py` (or inline in app.py)

## Data model

```python
@dataclass
class ItemSpecs:
    item_name: str
    category: str          # auto, electronics, appliances, home, hobby, general
    condition: str         # new | used | refurbished | any
    brand: str | None
    model: str | None
    year: int | None
    price_eur: float | None
    power_kw: float | None
    power_hp: float | None
    weight_kg: float | None
    length_mm: float | None
    width_mm: float | None
    height_mm: float | None
    battery_kwh: float | None   # EVs only
    range_km: float | None      # EVs only
    extras: dict[str, str]      # anything else (voltage, wheel_size, storage_gb, etc.)
    review_summary: str | None
    review_pros: list[str]
    review_cons: list[str]
    source_urls: list[str]
    researched_at: str          # ISO timestamp
```

## Error handling

- Web search failure: return empty specs with `category` from config default; log warning
- LLM failure: return partial specs from deterministic parsing of snippets (brand/model/year regex)
- Missing specs fields: leave as `None`; never invent values
- Duplicate item research: update existing row (upsert by item_name)

## Testing

- Unit tests for `ItemSpecsResearcher` with mocked web search and LLM
- Test that specs extraction returns correct types for known items (e.g., Citroen eC3 -> EV, battery_kwh ~44)
- Test that missing/invalid LLM JSON degrades gracefully
- Test SQLite upsert behavior
- Full suite must remain green (671 passed, 11 skipped baseline)

## Files to create/modify

**Create:**
- `src/intelligence/specs_researcher.py` — ItemSpecsResearcher + ItemSpecs + ReviewSummary
- `src/storage/schema.py` — add `ITEM_SPECS_COLUMNS` + migration to version 5
- `src/storage/manager.py` — `save_item_specs`, `get_item_specs` methods
- `tests/test_specs_researcher.py` — unit tests
- `docs/specs/2026-11-05-item-specs-research-design.md` — this file

**Modify:**
- `src/cli/app.py` — add `research-specs` command
- `src/config/models.py` — add `specs_research` config section (enabled, default_category)

## Design decisions

- **Specs stored in SQLite** so subsequent runs don't re-research the same item
- **Reuse existing web search** (DuckDuckGo HTML) — no new dependencies
- **LLM extraction with deterministic fallback** — regex for brand/model/year when LLM unavailable
- **Reviews stored as JSON** (pros/cons list + summary string) — flexible for any category
- **`extras` dict** for non-standard specs (voltage_volt, wheel_size_inch, storage_gb) — consistent with existing pricing model
