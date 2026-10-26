# Product Domains — Generic Spec Extraction and Scoring Design

- **Date:** 2026-10-26
- **Status:** Approved for implementation
- **Scope:** replace the bicycle-only spec branch with a domain registry; deterministic profiles for common product types; AI fallback that proposes domains and expected specs; domain-neutral scoring
- **Related code:** `src/output/processor.py`, `src/output/domains/` (new), `src/cli/app.py`, `config.example.yaml`, `README.md`

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
    extractors: Mapping[str, Callable[[str], str | None]] = field(default_factory=dict)
    constraints: tuple[Callable[[dict[str, str], str | None], tuple[str, bool]], ...] = ()
    optional_rows: tuple[str, ...] = ()     # scoring rows this domain enables
    weights: Mapping[str, float] | None = None
    source: str = "builtin"                 # builtin | ai
```

`extractors` maps a `key_specs` entry to a function over the lowercased listing text
(title + metadata, including `description` when the adapter provides it).

### 5.2 Built-in profiles for v1

| Domain | Strong keywords | Key specs | Optional rows |
|---|---|---|---|
| `computer` | `mini pc`, `barebone`, `nuc`, `laptop`, `notebook` | cpu, ram, storage, connectivity | Connectivity |
| `bike` | `bicykel`, `bike`, `mtb` | wheel_size, frame_size, suspension, brakes, drivetrain | — |
| `phone` | `iphone`, `smartfon`, `mobil`, `samsung galaxy`, `xiaomi`, `pixel` | storage, ram, battery_health, screen_size | — |
| `car` | `automobil`, `vozidlo`, `skoda`, `vw`, `audi`, `bmw` | year, mileage, fuel, engine, transmission | — |
| `furniture` | `sedacia`, `gauč`, `stol`, `skrina`, `postel`, `nabytok` | dimensions, material, color, condition_notes | — |
| `generic` | — (fallback) | — | — |

`car` also lists `km`, `rok`, `najazdene` as regular `keywords`, so a listing needs the
brand plus one of them; none of those three is strong enough on its own.

`constraints` are per-domain checks that can veto a listing regardless of specs. The
`bike` profile keeps the existing rider-height check: a stated frame size is compared
with a height in the request (for example `180 cm`), and an XXS frame for a 180 cm
rider marks the listing as not matching and adds a con. This is the only constraint in
v1; it moves out of `_bike_size_note` unchanged.

`generic` has no `key_specs`. Its `Spec match` is a neutral 50, so an unknown product
is not punished for specs nobody defined.

The existing bicycle and computer keys are unchanged (`wheel_size`, `frame_size`,
`suspension`, `brakes`, `drivetrain`; `cpu`, `ram`, `storage`, `connectivity`), so
current reports and tests stay valid.

Adding a domain is one new module plus one test file; it is not a change to
`ResultProcessor`.

### 5.3 Detection precedence

`src/output/domains/registry.py`:

1. `--domain <name>` on the CLI — explicit override, no detection.
2. Built-in profile whose keywords match the listing text.
3. A cached AI draft in `data/domains/ai/<slug>.yaml`.
4. A live AI proposal, only when an LLM is available and the run allows LLM calls.
5. `generic`.

Matching rule: a profile matches when one `strong_keywords` entry is present, or at
least two `keywords` entries are present. This stops a car listing that says "kolesá"
from being classified as a bicycle.

When several profiles match, the one with more matched keywords wins; a tie goes to
the profile with the longer matched keyword, then to the earlier entry in the registry.

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

Normalising over applicable rows is what fixes the sofa: five rows sum to 1.00, so the
missing `Connectivity` row no longer costs four points.

`Spec match` for a domain with `key_specs`:

```
spec_match = 100 × stated / len(key_specs)
```

`stated` counts key specs whose extractor returned a non-empty value. A domain with no
`key_specs` (`generic`) scores 50 — neutral, not zero.

`Requirement fit`, `Price`, `Condition & warranty` and `Seller trust` keep their
current formulas. A domain may override `weights`; no built-in profile does in v1.

## 7. AI fallback

### 7.1 When it runs

Only when steps 1–3 of the detection order produced no domain and `llm` is available.
One call per run per unknown domain: the first unknown listing triggers the call, the
result is memoised for the rest of the run.

### 7.2 Contract

The model returns exactly:

```json
{
  "domain": "camera",
  "key_specs": ["megapixels", "shutter_count", "lens_mount"],
  "specs": {"megapixels": "24", "shutter_count": "12000", "lens_mount": "EF"}
}
```

`specs` are the values found in the listing being analysed. `key_specs` is the set
worth tracking for this product type.

### 7.3 Validation

A proposal is accepted only when all of these hold:

- `domain` matches `^[a-z0-9_]{2,32}$` and is not a built-in name.
- `key_specs` has 2–12 unique snake_case entries, none empty.
- every `specs` value is a non-empty string of at most 60 characters without newlines.
- `key_specs` contains at least one key present in `specs`.

A rejected proposal logs a warning with the reason and falls back to `generic`. It never
aborts the run.

### 7.4 Cache

Accepted drafts are written to `data/domains/ai/<slug>.yaml` (git-ignored):

```yaml
name: camera
source: ai
created_at: "2026-10-26T12:00:00Z"
key_specs: [megapixels, shutter_count, lens_mount]
examples:
  - "Canon EOS 5D Mark II"
```

`examples` holds at most three listing titles, for human review.

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
  `_score_breakdown` move into `bike.py`. Behaviour for bicycle listings is unchanged.
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
  `Connectivity` row and its weights sum to 1.0.
- Scoring: bike and computer listings produce the same breakdown and score as before
  (regression fixtures taken from `results/results_20261026_111427_*.json`).
- Generic: `Spec match` is 50, score is not dragged down by a missing port row.
- Constraints: the bike rider-height check still skips an XXS frame for a 180 cm
  request, and a `generic` or `phone` domain never runs it.
- AI validation: one key spec rejected, empty value rejected, built-in name rejected,
  valid proposal accepted.
- Cache: round-trip write/read; corrupt file ignored.
- Report: `domain` and `spec_coverage` present in JSON; Markdown line rendered.

## 12. Risks

| Risk | Mitigation |
|---|---|
| AI invents a spec that is not in the listing | prompt forbids invention; report labels specs as seller-stated; validation rejects structurally empty values |
| False detection from a shared word | two weak keywords required, or one strong keyword |
| Extra LLM call per unknown domain | one call per domain per run, only when no built-in and no cache hit |
| AI drafts accumulate | git-ignored directory, human review via `examples`, drafts never override a built-in |
| Scores shift for existing reports | bike/computer profiles keep the original keys and weights; regression fixtures pin the numbers |
