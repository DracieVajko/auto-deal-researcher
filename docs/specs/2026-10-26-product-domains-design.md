# Product Domains — Generic Spec Extraction and Scoring Design

- **Date:** 2026-10-26
- **Status:** Approved for implementation
- **Scope:** replace the bicycle-only spec branch with a domain registry; deterministic profiles for common product types; AI fallback that proposes domains and expected specs; domain-neutral scoring; multilingual text handling (sk, cs, de, en); canonical spec keys; enrichment, duplicate and price-baseline fixes found by the cloud test
- **Related code:** `src/output/processor.py`, `src/output/domains/` (new), `src/text/normalize.py` (new), `src/searcher/adapters/bazos.py`, `src/searcher/filters.py`, `src/cli/app.py`, `config.example.yaml`, `README.md`

## 1. Problem

Spec extraction and scoring were built for mini PCs and then extended for bicycles.
Both are hardcoded branches inside `ResultProcessor`:

- `_looks_like_bike(text)` gates `_extract_bike_specs`, `_bike_size_note` and a bike
  branch in `_score_breakdown`.
- `_wants_pc_details(specs, prompt)` gates the PC rules in the heuristic analysis,
  the LLM prompt and `_matches_prompt`.

Anything that is neither a PC nor a bicycle falls through to the PC formula. Measured
on the production path (`_add_cross_alternatives`) with three listings:

| Listing | specs | Requirement fit | Spec match | Connectivity | Score |
|---|---|---|---|---|---|
| iPhone 13 128GB | `{}` | 100 | 45 | 20 | 66.2 |
| Sedacia súprava (sofa) | `{}` | 100 | 45 | 20 | 66.2 |
| Horský bicykel 26" | `{wheel_size, frame_size, brakes, drivetrain}` | 100 | 85 | 50 | 77.8 |

The phone and the sofa receive `Connectivity: 20/100`, a row that only makes sense for
a computer, and `Spec match: 45` for stating nothing. A sofa can never score well, and
a phone's own specs (storage, battery health) are never extracted.

Adding a third product type the same way would mean a third branch. The bicycle was a
test case; the requirement is a system that covers any product type on any site.

## 2. Goals

- Detect the product domain from the listing text, not from the shop.
- Extract domain-specific specs deterministically for common domains.
- Score every domain with the same formula; no domain gets another domain's rows.
- Let the LLM propose a domain and the specs worth tracking when no built-in profile
  matches, and remember that proposal between runs.
- Keep bicycle and PC output byte-compatible with the current reports.
- Work on every registered site without per-site code.
- Work in every language the registered markets use. Today that is Slovak, Czech,
  German and English on both sides of the pipeline: the user's request and the
  seller's listing. No language is privileged, and a mixed listing (Slovak title,
  English description) must work.
- Report each real listing once, and enrich the listings that are actually reported
  rather than an arbitrary prefix of the search page.
- Keep the LLM's output inside the domain's vocabulary: a spec key the profile does
  not define is not a spec.

## 3. Non-goals

- Per-site spec extractors. The domain is derived from text, so the same profile runs
  on Bazos, Alza, eBay and the other 27 sites.
- AI-generated regex extractors. An AI draft stores which specs matter, not how to
  find them (see 7.4 for the consequence).
- Replacing the LLM deal analysis. The LLM keeps its role; domains decide which specs
  are expected and how the score is composed.
- Automatic promotion of AI drafts into tracked profiles.
- Changing `Deal.category`. It is a shop-level field (`alza` → `electronics`,
  `bazos` → `general`) and stays as it is.
- Translating the report itself. JSON keys, labels and logs stay English; the values are
  language-neutral (section 13.3).
- Fuzzy duplicate matching. v1 treats identical folded titles as duplicates and nothing
  else, so it cannot merge two genuinely different listings.
- Claiming a language as supported without a fixture. Folding and keyword tables are
  extensible, but "supported" means a test exists in that language.

## 4. Verified facts

- `Deal.category` is set by the adapter, per site: `alza.py:119` and `ebay.py:183` use
  `electronics`, `bazos.py:271` and `profile_adapter.py:176` use `general`. It cannot
  identify the product type of an individual listing.
- `_looks_like_bike` requires `bicykel|bike|mtb`, or `koles` plus `rám|ram`. A phone
  listing that mentions "rám telefónu" does not match it (verified).
- Bike specs currently reach the report only through `Deal.metadata["description"]`,
  which the Bazos adapter fills; other adapters supply title and attributes only.
- The scoring weights are `Requirement fit 0.30, Spec match 0.25, Price 0.20,
  Condition & warranty 0.10, Seller trust 0.10, Connectivity 0.05`.

## 5. Domain profiles

### 5.1 `DomainProfile`

`src/output/domains/base.py`:

```python
@dataclass(frozen=True)
class DomainProfile:
    name: str
    strong_keywords: tuple[str, ...] = ()   # one match is enough
    keywords: tuple[str, ...] = ()          # two matches required
    key_specs: tuple[str, ...] = ()         # specs worth tracking
    aliases: Mapping[str, str] = field(default_factory=dict)  # LLM key -> key_specs entry
    extractors: Mapping[str, Callable[[str], str | None]] = field(default_factory=dict)
    constraints: tuple[Callable[[dict[str, str], str | None], tuple[list[str], bool]], ...] = ()
    optional_rows: tuple[str, ...] = ()     # scoring rows this domain enables
    weights: Mapping[str, float] | None = None
    source: str = "builtin"                 # builtin | ai
```

`extractors` maps a `key_specs` entry to a function over the **folded** listing text
(section 13.1): title plus metadata, including `description` when the adapter provides
it. `extract()` folds its input, so a caller may pass the raw title and metadata. Every
keyword, alias and pattern in a profile is stored already folded, so a profile never needs
to know which language or case the seller used.

`aliases` translates the keys an LLM invents into the profile's vocabulary, for example
`storage_gb → storage` and `battery_percentage → battery_health` (section 16.1).

### 5.2 Built-in profiles for v1

Keywords are stored folded (section 13.1) and cover the four languages the registered
markets use. A listing may mix languages; the lists are flat and unordered, so a Slovak
title with a German description still matches.

| Domain | Strong keywords (folded, any language) | Key specs | Optional rows |
|---|---|---|---|
| `computer` | `mini pc`, `barebone`, `nuc`, `laptop`, `notebook`, `computer`, `rechner`, `komputer` | cpu, ram, storage, connectivity | Connectivity |
| `bike` | `bicykel`, `bicykl`, `bike`, `mtb`, `fahrrad`, `mountainbike`, `ebike`, `rower` | wheel_size, frame_size, suspension, brakes, drivetrain | — |
| `phone` | `iphone`, `smartfon`, `smartphone`, `mobil`, `handy`, `samsung galaxy`, `xiaomi`, `pixel`, `huawei`, `oneplus` | storage, ram, battery_health, screen_size | — |
| `car` | `automobil`, `vozidlo`, `fahrzeug`, `pkw`, `samochod`, `skoda`, `vw`, `audi`, `bmw`, `mercedes`, `opel`, `ford`, `renault`, `peugeot`, `citroen`, `toyota`, `hyundai`, `kia`, `seat`, `fiat`, `volvo`, `mazda`, `nissan`, `honda`, `suzuki`, `dacia` | year, mileage, fuel, engine, transmission | — |
| `furniture` | `sedacia`, `sedaci`, `gauc`, `sofa`, `couch`, `sessel`, `stuhl`, `tisch`, `schrank`, `bett`, `regal`, `nabytek`, `meble`, `kanapa`, `fotel`, `stol`, `skrina`, `postel`, `komoda`, `polica` | dimensions, material, color, condition_notes | — |
| `generic` | — (fallback) | — | — |

`auto` is deliberately **not** a strong keyword: it is a substring of `automaticka`
(automatic) and appears in `autoskola`. The same reasoning excludes `rad` (Slovak
"row" and German "wheel") and `kolo` (Slovak "wheel", Czech "bike").

`car` also lists `km`, `rok`, `najeto`, `najazdene`, `baujahr`, `kilometer`, `mileage`,
`przebieg`, `year` as regular `keywords`: two of them are enough to match a listing that
does not name a brand, while a single one is not.

Keyword matching uses `\b` word boundaries on folded text, so `bike` does not match
`motorbike` and `bett` does not match `bettwasche`. Every keyword added to a profile
needs a positive test in each language and a negative test for the ambiguous word it
was chosen over (section 11).

`constraints` are per-domain checks that can veto a listing regardless of specs. The
`bike` profile keeps the existing rider-height check: a stated frame size is compared
with a height in the request (for example `180 cm`), and an XXS frame for a 180 cm
rider marks the listing as not matching and adds a con. The height and frame words are
read from folded text, so `veľkosť rámu: XXS`, `velikost ramu XXS`, `Rahmen XXS` and
`frame size XXS` all reach the same check.

`generic` has no `key_specs`. Its `Spec match` is a neutral 50, so an unknown product
is not punished for specs nobody defined.

The existing bicycle and computer keys are unchanged (`wheel_size`, `frame_size`,
`suspension`, `brakes`, `drivetrain`; `cpu`, `ram`, `storage`, `connectivity`), so
current reports and tests stay valid.

Adding a domain is one new module plus one test file; it is not a change to
`ResultProcessor`. Adding a language is data only: keywords and patterns go into the
existing tuples, never into a new `if`.

### 5.3 Detection precedence

`src/output/domains/registry.py`:

1. `--domain <name>` on the CLI — explicit override, no detection.
2. Built-in profile whose keywords match the listing text.
3. A cached AI draft in `data/domains/ai/<slug>.yaml` whose `keywords` match the
   listing text.
4. A live AI proposal, only when an LLM is available and the run allows LLM calls.
5. `generic`.

Matching rule: a profile matches when one `strong_keywords` entry is present, or at
least two `keywords` entries are present. This stops a car listing that says "kolesá"
from being classified as a bicycle. Matching runs on folded text with word boundaries
(section 13.1), so case, diacritics and the seller's language do not change the result.

When several profiles match, the one with more matched keywords wins; a tie goes to
the profile with the longer matched keyword, then to the earlier entry in the registry.

The resolved `DomainProfile` is carried on the analysis, not looked up again by name.
That is what lets an AI draft — which is not in `DOMAIN_REGISTRY` — keep its vocabulary
for scoring and spec normalisation after detection.

## 6. Scoring

Rows for a listing are the base rows plus the rows its domain enables:

| Row | Weight | Condition |
|---|---|---|
| Requirement fit | 0.30 | always |
| Spec match | 0.25 | always |
| Price | 0.20 | always |
| Condition & warranty | 0.10 | always |
| Seller trust | 0.10 | always |
| Connectivity | 0.05 | only when the domain lists it in `optional_rows` |

```
score = Σ(row_score × weight) / Σ(weight of applicable rows)
```

Normalising over applicable rows is what fixes the sofa: the five base rows sum to 0.95,
and dividing by that 0.95 rescales them to 1.00, so the missing `Connectivity` row no
longer costs four points. `Connectivity` is the only optional row in v1; a domain that
enables it uses the full 1.00 scale.

`Spec match` for a domain with `key_specs`:

```
spec_match = 100 × stated / len(key_specs)
```

`stated` counts key specs whose extractor returned a non-empty value. A domain with no
`key_specs` (`generic`) scores 50 — neutral, not zero.

`Requirement fit`, `Price`, `Condition & warranty` and `Seller trust` keep their
current formulas. The `weights` field on `DomainProfile` is reserved for a future
override; v1 scores every domain with `BASE_WEIGHTS` plus the optional `Connectivity`
row, and no built-in profile sets `weights`.

## 7. AI fallback

### 7.1 When it runs

Only when steps 1–3 of the detection order produced no domain and `llm` is available.
V1 makes at most one live proposal per run: the first unknown listing triggers the call,
the result is memoised for the rest of the run, and it is applied only to listings whose
text matches its keywords. A second, different unknown product stays `generic` rather
than borrowing the first product's vocabulary. Cached drafts are checked for every
unknown listing, so a repeated product type does not need a new call.

### 7.2 Contract

The model returns exactly:

```json
{
  "domain": "camera",
  "keywords": ["camera", "fotoaparat", "canon", "nikon"],
  "key_specs": ["megapixels", "shutter_count", "lens_mount"],
  "specs": {"megapixels": "24", "shutter_count": "12000", "lens_mount": "EF"}
}
```

`specs` are the values found in the listing being analysed. `key_specs` is the set
worth tracking for this product type. `keywords` are the words that identify this
product type in a listing; without them a cached draft could never be matched to a
later listing, which would make the cache write-only.

### 7.3 Validation

A proposal is accepted only when all of these hold:

- `domain` matches `^[a-z0-9_]{2,32}$` and is not a built-in name.
- `keywords` has 1–6 unique entries of 2–32 characters after folding; they are stored
  folded so a draft matches any case or diacritics.
- `key_specs` has 2–12 unique snake_case entries, none empty.
- every `specs` value is a non-empty string of at most 60 characters without newlines.
- `key_specs` contains at least one key present in `specs`.

A rejected proposal logs a warning with the reason and falls back to `generic`. It never
aborts the run. A proposal that does not match the very listing that produced it is also
rejected: a draft whose keywords cannot name its own example is write-only, so it is
discarded instead of cached.

### 7.4 Cache

Accepted drafts are written to `data/domains/ai/<slug>.yaml` (git-ignored):

```yaml
name: camera
source: ai
created_at: "2026-10-26T12:00:00Z"
keywords: [camera, fotoaparat, canon, nikon]
key_specs: [megapixels, shutter_count, lens_mount]
examples:
  - "Canon EOS 5D Mark II"
```

`examples` holds at most three listing titles, for human review. `keywords` is what makes
the draft usable on the next run: detection matches it exactly like a built-in profile.
The draft's `keywords` become `strong_keywords`, so one hit is enough; validation keeps
the list short and specific to stop a broad word from claiming unrelated listings.

**Known limitation, stated explicitly:** a cached draft records *which* specs matter,
not how to extract them. On a later run without an LLM, the domain is still detected
and coverage is still reported, but values come from the LLM only. Deterministic
extraction for an AI domain requires a human to add a profile module with extractors.

## 8. Report

JSON per deal gains:

```json
"domain": "bike",
"spec_coverage": {
  "stated": ["wheel_size", "frame_size"],
  "missing": ["suspension", "brakes", "drivetrain"]
}
```

Markdown gains one line under the score breakdown:

```
Domain: bike — 2/5 specs stated
```

Specs in the report keep their current label and are described as stated by the seller,
because the pipeline never verifies a claim.

## 9. Compatibility and migration

- `_looks_like_bike`, `_extract_bike_specs`, `_bike_size_note` and the bike branch of
  `_score_breakdown` move into `bike.py`. The bicycle keys, extractors and the
  rider-height check are unchanged.
- **Scores change for bicycles and computers.** `Spec match` used to be
  `45 + 20 + 20 + 10` for wheel/frame/suspension; it becomes coverage of `key_specs`
  (section 6). A bicycle stating 3 of 5 expected specs scores 60 instead of 95. This is
  a deliberate correction — the old formula rewarded a fixed set of keys and ignored
  everything else — but it is a visible change in reports, so it is stated here rather
  than hidden behind a "no behaviour change" claim.
- `_wants_pc_details` becomes `domain == "computer"`; the hardware-token gate in
  `_matches_prompt` applies only to that domain.
- The PC prompt rules (`barebone`, `cpu/ram/storage`, form factor) are injected only
  when the domain is `computer`, exactly as they are today.
- `Deal.category`, the search filters and the adapters are untouched.
- `config.example.yaml` gains an optional `output.domain: ""` (empty = auto-detect).

## 10. Error handling

| Failure | Behaviour |
|---|---|
| Unknown domain, no LLM | `generic`, `Spec match` 50, report says `domain: generic` |
| AI returns invalid JSON | warning, `generic`, run continues |
| Cached draft is corrupt | warning, draft ignored, live AI or `generic` |
| `--domain` names a missing profile | startup error listing the known names |
| Extractor raises | that spec counts as missing, warning logged |

## 11. Testing

- Detection: `--domain` wins; strong keyword beats two weak ones; "kolesá" alone in a
  car ad does not select `bike`.
- Isolation: a phone listing gets no bike or computer keys; a sofa has no
  `Connectivity` row and its applicable weights are rescaled to 1.0.
- Scoring: bicycle and computer listings keep their spec keys, row names and optional
  `Connectivity` row; `Spec match` now follows coverage, and fixtures pin the new
  numbers so an accidental change is caught.
- Generic: `Spec match` is 50, score is not dragged down by a missing port row.
- Constraints: the bike rider-height check still skips an XXS frame for a 180 cm
  request, and a `generic` or `phone` domain never runs it.
- AI validation: one key spec rejected, empty value rejected, built-in name rejected,
  valid proposal accepted.
- Cache: round-trip write/read; corrupt file ignored.
- Report: `domain` and `spec_coverage` present in JSON; Markdown line rendered.
- Multilingual (section 13): every built-in domain has one listing per language
  (sk, cs, de, en) that produces the same canonical specs; folding is tested on
  `GAUČ`, `gauč`, `Straße`, `Łódź`; every ambiguous keyword has a negative test;
  a German prompt yields the same filters as its Slovak equivalent; a translated query
  that loses a brand token is rejected.
- Enrichment (section 14): a reported listing carries `description` when the adapter can
  fetch it; a failed fetch sets `detail_failed` and the report does not say "not stated".
- Duplicates (section 15): identical titles collapse to the cheapest offer and the
  others stay visible under `duplicates`.
- Canonical keys (section 16.1): `storage_gb` maps to `storage`, `price_eur` is dropped,
  a deterministic value is not overwritten.
- Requirement guard (section 16.2): `128 GB` in the title rescues an LLM "storage not
  stated" verdict; a rejection for a different reason is not rescued.
- Price baseline (section 17): fewer than four distinct prices yields a neutral 50;
  duplicates do not move the median.

## 12. Risks

| Risk | Mitigation |
|---|---|
| AI invents a spec that is not in the listing | prompt forbids invention; report labels specs as seller-stated; validation rejects structurally empty values |
| False detection from a shared word | two weak keywords required, or one strong keyword |
| Extra LLM call per unknown domain | one call per domain per run, only when no built-in and no cache hit |
| AI drafts accumulate | git-ignored directory, human review via `examples`, drafts never override a built-in |
| Scores shift for existing reports | documented in section 9 and pinned by fixtures; the shift is a correction, not an accident |
| A folded keyword collides with an unrelated word in another language | ambiguous words are excluded by name (`auto`, `rad`, `kolo`) and every keyword needs a negative test |
| Translation changes the product or drops a model number | brand/model tokens must survive translation, otherwise the original query is used |
| Dedup hides a better seller | the cheapest offer is kept and the rest stay visible under `duplicates` |
| Enrichment cost grows with the shortlist | cap after filtering, not before; default 20 |
| The requirement guard rescues a genuinely bad listing | it only rescues when the model's own con says the attribute is "not stated"; any other rejection stands |

## 13. Multilingual support

The registered markets are SK, CZ, DE and EU, so the pipeline must understand Slovak,
Czech, German and English. It must do so on both sides: the request the user types and
the listing the seller wrote. Nothing in this section is a per-language branch; a new
language is added by appending data.

### 13.1 Canonical folding

`src/text/normalize.py` (new) exports one function used by filters, domain detection,
extractors and duplicate detection:

```python
def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # Lower first: _EXTRA_FOLDS is keyed by lowercase letters, and NFKD leaves
    # uppercase forms such as Ł, Æ and Ø untouched.
    lowered = stripped.lower()
    for src, dst in _EXTRA_FOLDS.items():      # letters NFKD cannot decompose
        lowered = lowered.replace(src, dst)
    return lowered
```

`_EXTRA_FOLDS` covers `ß → ss`, `æ → ae`, `œ → oe`, `ø → o`, `đ → d`, `ð → d`,
`þ → th`, `ł → l`, `ı → i`, `ħ → h`, `ŋ → n`, `ĸ → k`. NFKD handles the rest of the
Latin diacritics, including `á ä č ć é ě í ĺ ľ ń ň ó ô ő ö ŕ ř ś š ť ú ů ü ű ý ź ż ž`.

Folding must not touch characters that carry meaning in a value: `×` (U+00D7) stays,
so `250×180` survives, and `%` stays. Folding also normalises punctuation: typographic
quotes become `"`, dashes become `-`, non-breaking spaces become a regular space.

Why this exists: `str.lower()` maps `GAUČ` to `gauč` but leaves `gauc` different, so a
listing that writes without diacritics would never match a keyword written with them.
Folding makes both `gauc`.

Two copies of this logic already exist (`filters.py:120`, `profile_adapter.py:21`) and a
third variant is inlined in `processor.py:1121`. They move to the shared module.

### 13.2 Keywords and patterns

Every keyword, alias and regex in a profile is written in folded form. Detection matches
with `\b` boundaries on folded text. This means:

- `Bicykel`, `bicykel` and `bicykl` are the same keyword.
- `Fahrrad`, `fahrrad` and `FAHRRAD` are the same keyword.
- A profile never asks "which language is this?" before matching; it matches all
  languages at once, because listings mix them.

### 13.3 Units and canonical values

Extractors accept the unit spellings of all four languages and store one canonical value,
so a report reads the same regardless of the seller's language:

| Spec | Accepted spellings (folded) | Stored as |
|---|---|---|
| `storage` | `128 gb`, `128gb`, `1 tb`, `128 go` | `128 GB` |
| `battery_health` | `bateria 89%`, `baterie 89 %`, `akku 89%`, `battery 89%`, `stav baterie 89`, `zdravie baterie 89`, `batterie 89` | `89%` |
| `screen_size` | `6.1"`, `6,1"`, `6.1 palca`, `6.1 zoll`, `6.1 inch`, `6.1 cala` | `6.1"` |
| `wheel_size` | `26"`, `26 palcov`, `26 zoll`, `26 cali`, `26 inch` | `26"` |
| `frame_size` | `ram 18`, `rahmen 18`, `frame 18`, a letter after a frame word | `18"` or `M` |
| `mileage` | `180000 km`, `180 000 km`, `180.000 km`, `180 tkm`, `112000 meilen` | `180000 km` |
| `dimensions` | `250x180 cm`, `250 x 180 cm`, `250×180`, `2,5 x 1,8 m` | `250x180 cm` |

Decimal comma and dot are both accepted and normalised to a dot in the stored value.
A unit written in a language the profile does not list counts as "not stated", never as a
wrong value.

### 13.4 The user's request

`parse_filters_from_text` already folds the prompt before matching. It gains the missing
German, Czech, English and Polish words:

| Filter | Added words |
|---|---|
| maximum price | `bis`, `unter`, `maximal`, `höchstens`, `do`, `pod`, `max`, `under`, `up to` |
| minimum price | `ab`, `mindestens`, `od`, `from`, `over` |
| condition | `gebraucht`, `neu`, `generalüberholt`, `aufbereitet`, `wie neu`, `použité`, `nové`, `repasované`, `used`, `new`, `refurbished` |
| shipping | `versandkostenfrei`, `kostenloser versand`, `doprava zdarma`, `free shipping` |
| sort | `günstigste`, `billigste`, `nejlevnější`, `najlacnejšie`, `cheapest`, `teuerste`, `nejdražší`, `neueste`, `nejnovější` |

Currency suffixes in the price patterns gain `kč`, `czk`, `zł`, `pln`, `ft`, `huf`
alongside `eur`, `euro`, `€`.

### 13.5 The search query

A query written in Slovak sent to a German shop returns nothing useful. The query sent to
a site is therefore produced in that site's language:

1. Map the site country to a language: `SK → sk`, `CZ → cs`, `DE/AT → de`, `PL → pl`,
   `HU → hu`, anything else `en`.
2. Detect the request language with a cheap marker-word/diacritic heuristic. Marker
   words are weighted above diacritics, and only language-exclusive diacritics are
   counted: `á é ý` occur in both Czech and Slovak, so a Czech sentence such as
   `Prodám horské kolo` is decided by its marker words. If the detected language equals
   the site language, send the request unchanged.
3. Otherwise ask the LLM for the same query in the site language, preserving brand and
   model strings verbatim. Validate that every token that looks like a model (contains a
   digit or an uppercase letter in the original, which covers `iPhone`, `128GB` and
   `Kellys`) survives; if one is missing, discard the translation and send the original.
4. Cache the result per (request, language) for the run. No LLM means the original query
   is sent — never worse than today.

`QueryExpansionAgent._fallback` currently appends English suffixes (`used`, `new`,
`refurbished`, `open box`, `under 350`, `bargain`) to any prompt. It must use the
request's language, falling back to English when detection is unsure.

### 13.6 What stays English

JSON keys, report labels and log messages stay English. They are machine-readable or
operator-facing, and localising them is a separate change. The values they carry are
already language-neutral because of 13.3.

## 14. Enrichment coverage

`bazos.py:99` enriches `deals[:10]` in page order. Bazos sorts newest first, while the
report rewards the cheapest listings, which are the oldest. The result is that the
listings actually reported are exactly the ones without a description.

Measured on the 2026-10-26 run: all six reported deals had no `description` and no
`location`, while the same three URLs enriched successfully when fetched directly
(0/3 failures). The fetch is fine; the coverage is wrong.

The search already caps each adapter at `max_results=20`, so the fix is to cover the
whole returned page instead of half of it:

- `search.enrich_limit` defaults to 20, matching `max_results`. Every listing the adapter
  returns is enriched in the normal case.
- When a site returns more than the limit, the adapter sorts by `price_eur` ascending
  before applying it, because the report rewards cheap listings. Listings left out get
  `metadata["detail_skipped"] = True`.
- A listing whose detail fetch fails keeps its card data and gets
  `metadata["detail_failed"] = True`.
- The report distinguishes three states: a value is shown, the seller did not state it,
  or **we did not fetch it**. The last one says "description unavailable" and never
  "not stated", because "not stated" is a claim about the seller that we would not have
  earned.

Enrichment stays inside the adapter, because the adapter owns the detail selectors and
the open page. Moving it into the pipeline would mean reopening pages per site and would
still make the judge decide before the description is known.

## 15. Duplicate listings

Deduplication exists only for `alternatives` (`processor.py:861-885`). The main list keeps
duplicates: in the 2026-10-26 report four of six deals were two products, and the model
itself wrote "duplicate of L2/L3" in the notes.

Rule:

- Same site plus identical folded title, with whitespace collapsed, is a duplicate. No
  fuzzy matching in v1.
- Keep the cheapest offer, because for any request the cheaper of two identical listings
  is the better offer. Attach the others under `metadata["duplicates"]` with `url` and
  `price_eur`, so nothing is hidden.
- Deduplication runs **before** scoring, so the price median is not built from copies of
  the same listing.
- `count` reflects deduplicated deals; `duplicates_collapsed` reports how many were
  merged.

## 16. Canonical spec keys and the requirement guard

### 16.1 Keys the profile defines

The analysis prompt says only "use short snake_case keys in specs" outside `pc_mode`
(`processor.py:307`). That is an instruction to invent a vocabulary: the phone run
produced `storage_gb`, `battery_percentage`, `color` and `price_eur`.

- The prompt lists the profile's `key_specs` and says: use only these keys, omit a key
  the listing does not state. When the profile has no `key_specs` (`generic`), the old
  rule stands: use short snake_case keys for facts stated in the listing.
- After parsing, keys are mapped through `profile.aliases` and anything still outside
  `key_specs` is dropped. `generic` has no vocabulary, so it keeps every key except
  `price_eur`; otherwise an unknown product would lose the only structured specs the
  model found.
- `price_eur` is never a spec. It is a deal field and already appears on the listing line.
- Deterministic values keep winning (`setdefault` in `_merge_llm_analysis`, already
  correct); the model only fills gaps.

Dropping is deliberate. A report that says "3/4 specs stated" must count tracked specs,
not whatever vocabulary the model chose that day.

### 16.2 Hard requirements from the request

`matches_requirements` is currently set only by the model (`processor.py:388`). In the
2026-10-26 run the cheapest phone was marked as not matching because the model wrote
"storage not stated", although the title said `128GB`.

- `extract_requirements(prompt)` returns the hard numeric requirements the request states:
  `storage_gb`, `min_battery_percent`, `max_price_eur`.
- For each requirement the deterministic extractor found **and satisfied**, any con
  matching `<attribute>.*not stated`, `no mention of <attribute>` or
  `<attribute>.*not mentioned` is removed.
- `matches_requirements` is restored to True only when such a con existed **and** no
  remaining con names an independent hard defect (`cracked`, `broken`, `water damage`,
  `wrong model`, `locked`). A cracked screen or a wrong model is a rejection for another
  reason, and it stands even if the requirement claim was false.
- The guard can rescue a listing, never condemn one. It only ever removes a con; it never
  adds one and never turns a True into False.
- A request with no hard requirement runs no guard, so behaviour is unchanged.

## 17. Price baseline

`median` is `statistics.median` over the analysed sample (`processor.py:789`). In the
2026-10-26 run prices were `[159, 219, 320, 320, 320, 340]`, so the median was 320 and the
320 € listings scored `Price 75` while their cons said "price far exceeds reasonable used
market value". The sample's own duplicates defined the market, and the row contradicted
the text.

- Deduplicate before computing the median (section 15).
- Require at least four distinct prices. Below that, `Price` is a neutral 50, because a
  median of two or three listings is not a market.
- The model may not make market-value claims. The prompt gains: "do not say a price is
  above or below market; you do not know the market." The `Price` row is the only place a
  price is judged, and it is computed from data the report shows. A con that still makes
  such a claim is dropped deterministically before the report is written, because a
  prompt rule alone is not enforcement.

After deduplication the example has three distinct prices, so all three get `Price 50` and
the ranking is decided by requirement fit and specs. That is the honest outcome: three
listings are not a market.
