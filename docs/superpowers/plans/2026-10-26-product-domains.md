# Product Domains Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bicycle-only spec branch with a domain registry so every product type gets its own specs, scoring rows and constraints, with an AI fallback for unknown types. The same work makes the pipeline language-neutral (sk, cs, de, en) and fixes the enrichment, duplicate, spec-key and price-baseline defects found by the 2026-10-26 cloud test.

**Architecture:** A `DomainProfile` value object plus a `DOMAIN_REGISTRY` of small modules. All text comparison goes through one `fold()` function, so keywords and patterns are written once in folded form and match any case, diacritics or language. Detection runs on listing text (title + metadata, including the adapter-provided description), never on the shop. `ResultProcessor` asks the registry for a profile, extracts specs with that profile's extractors, and scores with only the rows the profile enables, normalised to sum 1.0. Unknown types fall back to `generic`, or to an AI-proposed draft cached under `data/domains/ai/`. Enrichment moves out of the adapter and runs on the filtered shortlist, duplicates collapse before scoring, and the LLM is restricted to the profile's spec keys.

**Tech Stack:** Python 3.12, pytest, ruff, pydantic config, Typer CLI, PyYAML (already a dependency).

**Spec:** `docs/specs/2026-10-26-product-domains-design.md`

## Global Constraints

- Baseline before this work: `376 passed, 11 skipped`; the suite must stay green.
- Existing bicycle keys (`wheel_size`, `frame_size`, `suspension`, `brakes`, `drivetrain`) and computer keys (`cpu`, `ram`, `storage`, `connectivity`) keep their names and values.
- No per-site code. Domains are derived from listing text only.
- No per-language code. Keywords, aliases and patterns are data in folded form; a new language is a new tuple entry, never a new `if`.
- Every text comparison uses `src.text.normalize.fold`. A `lower()` or inline `unicodedata` call in new code is a review failure.
- Every keyword added to a profile needs a positive test in each of sk, cs, de, en and a negative test for the ambiguous word it was chosen over.
- Report JSON keys, labels and log messages stay English; values are canonical (`128 GB`, `89%`, `6.1"`).
- `data/domains/ai/` is git-ignored; AI drafts never write into `src/`.
- No new third-party dependency.
- Scoped `ruff check` must pass on every file touched; the repo has ~215 pre-existing ruff findings elsewhere, so run it on the changed paths only.
- `Deal.category` is untouched — it is a shop-level field, not a product type.

## Review Focus

- **A listing that matches two domains** (a bundle: "bicykel + iPhone") — detection must pick one deterministically and never raise.
- **The same product written four ways** — `Horský bicykel 26"`, `horský bicykl 26"`, `Mountainbike 26 Zoll`, `mountain bike 26 inch` must all reach `bike` and the same canonical specs.
- **A listing without diacritics** — `gauč` and `gauc`, `Škoda` and `Skoda`, `Dvořák` and `Dvorak` must be the same string after `fold`.
- **A word that exists in two languages** — `auto`, `rad`, `kolo` must not be keywords; the tests must prove the exclusion.
- **An extractor returning only whitespace** — must count as "not stated", not as a stated spec.
- **An AI proposal with more than 12 key specs** — must be rejected, not truncated silently.
- **An empty prompt** — detection must still work from the listing text alone, because `--prompt` is optional for some flows.
- **A reported listing with no description** — must say "description unavailable" when the fetch failed, and only say "not stated" when the fetch succeeded.
- **Two identical titles at different prices** — must collapse to the cheaper one and keep the other under `duplicates`.
- **Three listings only** — must not produce a confident `Price` score from a median of three.

---

### Task 1: Canonical folding, DomainProfile registry and the generic fallback

**Files:**
- Create: `src/text/__init__.py`
- Create: `src/text/normalize.py`
- Create: `src/output/domains/__init__.py`
- Create: `src/output/domains/base.py`
- Create: `src/output/domains/registry.py`
- Create: `src/output/domains/generic.py`
- Test: `tests/test_normalize.py`
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `src.text.normalize.fold(text: str) -> str` — lowercase, strip diacritics, map the
    letters NFKD cannot decompose, preserve `×` and `%`.
  - `src.text.normalize.collapse_ws(text: str) -> str` — collapse runs of whitespace.
  - `DomainProfile` dataclass (frozen) with fields `name: str`, `strong_keywords: tuple[str, ...]`, `keywords: tuple[str, ...]`, `key_specs: tuple[str, ...]`, `aliases: Mapping[str, str]`, `extractors: Mapping[str, Callable[[str], str | None]]`, `constraints: tuple[Callable[[dict[str, str], str | None], tuple[list[str], bool]], ...]`, `optional_rows: tuple[str, ...]`, `weights: Mapping[str, float] | None`, `source: str`.
  - `DomainProfile.matches(folded: str) -> int` — 0 means no match, higher means more specific. Expects folded text.
  - `DomainProfile.extract(text: str) -> dict[str, str]` — folds `text` itself, so callers may pass raw listing text; returns only non-empty values, whitespace-only results dropped.
  - `DomainProfile.normalise_specs(specs: Mapping[str, str]) -> dict[str, str]` — apply `aliases`, drop keys outside `key_specs` and drop `price_eur`. When `key_specs` is empty (`generic`), keep every key except `price_eur`: there is no vocabulary to enforce.
  - `DomainProfile.check(specs: dict[str, str], prompt: str | None) -> tuple[list[str], bool]` — (messages, disqualify).
  - `DOMAIN_REGISTRY: dict[str, DomainProfile]`, `get(name: str) -> DomainProfile` (raises `KeyError`), `detect(text: str, override: str | None = None, extra: Iterable[DomainProfile] = ()) -> DomainProfile`.
  - `GENERIC` — profile named `generic` with no `key_specs`.

- [ ] **Step 1: Write the failing folding test**

```python
# tests/test_normalize.py
import pytest

from src.text.normalize import collapse_ws, fold


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GAUČ", "gauc"),
        ("gauč", "gauc"),
        ("Bicykel", "bicykel"),
        ("Fahrrad", "fahrrad"),
        ("Straße", "strasse"),
        ("Łódź", "lodz"),
        ("İstanbul", "istanbul"),
        ("Dvořák", "dvorak"),
        ("kręgle", "kregle"),
        ("", ""),
        (None, ""),
    ],
)
def test_fold_is_case_and_diacritic_insensitive(raw, expected):
    assert fold(raw) == expected


def test_fold_preserves_meaningful_symbols():
    assert fold("250×180 cm") == "250×180 cm"
    assert fold("89 %") == "89 %"


def test_collapse_ws_normalises_spaces():
    assert collapse_ws("  iPhone   13 \n 128GB ") == "iPhone 13 128GB"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.text'`

- [ ] **Step 3: Implement `src/text/normalize.py`**

```python
"""One folding rule for every text comparison in the pipeline."""

import unicodedata

_EXTRA_FOLDS = {
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ð": "d",
    "þ": "th", "ł": "l", "ı": "i", "ħ": "h", "ŋ": "n", "ĸ": "k",
}
_PUNCTUATION = str.maketrans(
    {
        "’": "'", "‘": "'", "´": "'",
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "-",
        "\u00a0": " ", "\u202f": " ",
    }
)


def fold(text: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # Lower first: _EXTRA_FOLDS is keyed by lowercase letters, and NFKD leaves
    # uppercase forms such as Ł, Æ and Ø untouched.
    lowered = stripped.translate(_PUNCTUATION).lower()
    for src, dst in _EXTRA_FOLDS.items():
        lowered = lowered.replace(src, dst)
    return lowered


def collapse_ws(text: str) -> str:
    return " ".join((text or "").split())
```

`src/text/__init__.py` re-exports `fold` and `collapse_ws`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Write the failing domain test**

```python
# tests/test_domains.py
import pytest

from src.output.domains import DOMAIN_REGISTRY, detect, get


def test_unknown_text_falls_back_to_generic():
    assert detect("Predám kávovar, 2 roky starý").name == "generic"


def test_generic_has_no_key_specs():
    assert get("generic").key_specs == ()


def test_override_wins_over_detection():
    assert detect("Predám bicykel", override="generic").name == "generic"


def test_unknown_override_raises():
    with pytest.raises(KeyError):
        get("nope")


def test_detect_accepts_none_prompt():
    assert detect("Predám kávovar", override=None).name == "generic"


def test_extractor_returning_whitespace_counts_as_missing():
    from src.output.domains import DomainProfile

    profile = DomainProfile(
        name="probe", key_specs=("thing",), extractors={"thing": lambda text: "   "}
    )
    assert profile.extract("anything") == {}


def test_extractor_that_raises_counts_as_missing():
    from src.output.domains import DomainProfile

    def boom(text: str) -> str:
        raise RuntimeError("bad pattern")

    profile = DomainProfile(name="probe", key_specs=("thing",), extractors={"thing": boom})
    assert profile.extract("anything") == {}


def test_listing_matching_two_domains_picks_one_deterministically():
    from src.output.domains import DomainProfile

    coffee = DomainProfile(name="coffee_probe", strong_keywords=("kavovar",))
    mixer = DomainProfile(name="mixer_probe", strong_keywords=("mixer",))
    text = "Predám kávovar a mixer"
    first = detect(text, extra=[coffee, mixer])
    second = detect(text, extra=[coffee, mixer])
    assert first.name == second.name
    assert first.name in {"coffee_probe", "mixer_probe"}


def test_detect_folds_case_and_diacritics():
    from src.output.domains import DomainProfile

    probe = DomainProfile(name="probe", strong_keywords=("kavovar",))
    assert detect("KÁVOVAR", extra=[probe]).name == "probe"
    assert detect("kávovar", extra=[probe]).name == "probe"


def test_normalise_specs_maps_aliases_and_drops_unknown():
    from src.output.domains import DomainProfile

    profile = DomainProfile(
        name="probe", key_specs=("storage",), aliases={"storage_gb": "storage"}
    )
    assert profile.normalise_specs(
        {"storage_gb": "128", "price_eur": "300", "color": "pink"}
    ) == {"storage": "128"}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.output.domains'`

- [ ] **Step 7: Implement the package**

`base.py` holds the dataclass and its four methods. Every collection field defaults to an
empty tuple or dict, so a profile can be built with only the fields it uses. `matches`
runs on **folded** text and matches `strong_keywords` with `\b` boundaries. It returns 0
for no match; one strong hit returns `1000 + len(keyword)`; regular keywords return
`100 * hits + max(len(keyword))` when at least two hit, else 0. This makes a strong hit
beat weak hits, more weak hits beat fewer, and a longer matched keyword break a tie
before registry order does (spec section 5.3). `extract` calls `fold(text)` first, then
each extractor inside `try/except Exception`, strips the result, and keeps it only when
non-empty — a failing extractor logs a warning and counts as "not stated" (spec section
10). `normalise_specs` maps keys through `aliases`, keeps only `key_specs`, and always
drops `price_eur` (spec section 16.1). A profile with an empty `key_specs` (`generic`) has
no vocabulary to enforce, so it keeps every key except `price_eur`; otherwise an unknown
product would lose the only structured specs the model found. `check` runs each constraint
and concatenates messages, OR-ing the disqualify flag.

`registry.py` exposes `DOMAIN_REGISTRY` (insertion order matters for ties),
`get(name)`, and `detect(text, override=None, extra=())`: `detect` first calls
`fold(text)` once, so every caller may pass raw listing text; `override` resolves through
`get`; otherwise every profile from `DOMAIN_REGISTRY` plus every profile in `extra` is
scored with `matches()`, the highest score wins, ties go to the earlier entry (built-ins
before extras); no match returns `GENERIC`. `detect` performs no file I/O — callers pass
cached drafts through `extra`.

`generic.py` defines `GENERIC = DomainProfile(name="generic")`.

`__init__.py` re-exports `DomainProfile`, `DOMAIN_REGISTRY`, `detect`, `get`, `GENERIC`.

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 9: Commit**

```bash
git add src/text src/output/domains tests/test_normalize.py tests/test_domains.py
git commit -m "feat(domains): add folded text matching and DomainProfile registry"
```

---

### Task 2: Move computer and bicycle specs into profiles

**Files:**
- Create: `src/output/domains/computer.py`
- Create: `src/output/domains/bike.py`
- Modify: `src/output/domains/registry.py`
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: `DomainProfile`, `DOMAIN_REGISTRY` from Task 1.
- Produces: `COMPUTER` and `BIKE` profiles registered as `computer` and `bike`.
  `COMPUTER.optional_rows == ("Connectivity",)`. `BIKE.constraints` holds the
  rider-height check `(specs, prompt) -> tuple[list[str], bool]`.

- [ ] **Step 1: Write the failing test**

```python
def test_computer_extracts_cpu_ram_storage():
    specs = get("computer").extract(
        "mini pc ryzen 7 5800h 32gb ddr5 512gb ssd thunderbolt"
    )
    assert specs["cpu"] == "RYZEN 7 5800H"
    assert specs["ram"] == "32 GB DDR5"
    assert specs["storage"] == "512 GB SSD"


def test_bike_extracts_specs_from_description():
    specs = get("bike").extract(
        'horský bicykel 26" kolesá, rám 18", kotúčové brzdy, sram'
    )
    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == '18"'
    assert specs["brakes"] == "Disc brakes"
    assert specs["drivetrain"] == "SRAM"


def test_bike_detected_from_keyword():
    assert detect("Predám horský bicykel Author").name == "bike"


def test_computer_detected_from_keyword():
    assert detect("Mini PC barebone NUC").name == "computer"


def test_bike_rejects_xxs_frame_for_tall_rider():
    messages, disqualify = get("bike").check(
        {"frame_size": "XXS"}, "horsky bicykel pre muza 180 cm"
    )
    assert disqualify is True
    assert any("too small" in message for message in messages)


def test_bike_accepts_large_frame_for_tall_rider():
    messages, disqualify = get("bike").check(
        {"frame_size": 'L 19"'}, "horsky bicykel pre muza 180 cm"
    )
    assert disqualify is False
    assert messages == []


def test_bike_keywords_match_uppercase():
    assert detect("Predám Horský Bicykel Author").name == "bike"


def test_bike_detected_in_german_czech_english():
    assert detect("Verkaufe Mountainbike, 26 Zoll").name == "bike"
    assert detect("Prodám horský bicykl, rám 18").name == "bike"
    assert detect("Selling a mountain bike, 26 inch").name == "bike"


def test_bike_keyword_does_not_match_motorbike():
    assert detect("Predám motorbike helmet, nový").name == "generic"


def test_bike_extracts_german_specs():
    specs = get("bike").extract(
        "fahrrad 26 zoll, rahmen 18 zoll, scheibenbremsen, sram"
    )
    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == '18"'
    assert specs["brakes"] == "Disc brakes"


def test_computer_detected_in_german():
    assert detect("Verkaufe Laptop, 32 GB RAM").name == "computer"
    assert detect("Gebrauchter Rechner, i5").name == "computer"


def test_bike_check_without_prompt_does_not_disqualify():
    messages, disqualify = get("bike").check({"frame_size": "XXS"}, None)
    assert disqualify is False
    assert messages == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -v`
Expected: FAIL — `get("computer")` raises `KeyError`

- [ ] **Step 3: Move the existing logic**

Copy the CPU/RAM/storage/connectivity patterns from `ResultProcessor._extract_specs`
(`src/output/processor.py:977-1060`) into `computer.py` extractors. Copy the wheel,
frame, suspension, brakes and drivetrain patterns from `_extract_bike_specs`
(`src/output/processor.py:1074-1090`) into `bike.py`. Copy `_bike_size_note`
(`src/output/processor.py:546-600`) into `bike.py` as a constraint that returns
`([message], True)` when the frame is clearly too small, `([message], False)` when it is
clearly too large, and `([], False)` otherwise. The message text and the approximate
ranges stay unchanged, so the existing warning still reaches the report.

**Multilingual is part of the move, not a later pass.** The inline
`unicodedata.normalize("NFKD", ...)` block at `processor.py:1121-1125` is deleted and
replaced by `fold()` from Task 1. Every pattern is rewritten in folded form and gains the
German, Czech and English spellings it was missing:

| Spec | Add to the existing patterns |
|---|---|
| `wheel_size` | `zoll`, `inch`, `cala`, `cali` alongside `palcov`, `"`; keep the existing `26x2.10` tyre notation |
| `frame_size` | `rahmen`, `frame`, `velikost ramu` alongside `rám`, `ram`; accept `zoll`, `inch`, `cala`, `cali` and the inch symbols as the numeric suffix |
| `suspension` | `vollfederung`, `federgabel`, `starrgabel`, `full suspension`, `front suspension` |
| `brakes` | `scheibenbremsen`, `felgenbremsen`, `disc brake`, `rim brake` |
| `drivetrain` | brand names only (`sram`, `shimano`, `campagnolo`), no language words |

Keywords, stored folded:

- `COMPUTER` strong: `mini pc`, `barebone`, `nuc`, `laptop`, `notebook`, `computer`,
  `rechner`, `komputer`.
- `BIKE` strong: `bicykel`, `bicykl`, `bike`, `mtb`, `fahrrad`, `mountainbike`,
  `mountain bike`, `ebike`, `rower`.

`auto`, `rad` and `kolo` are deliberately absent (spec section 5.2).

Register both in `DOMAIN_REGISTRY` after `generic`.

Do not delete the processor functions yet — Task 5 does that after the profiles are proven.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/domains tests/test_domains.py
git commit -m "feat(domains): add computer and bicycle profiles"
```

---

### Task 3: Add phone, car and furniture profiles

**Files:**
- Create: `src/output/domains/phone.py`
- Create: `src/output/domains/car.py`
- Create: `src/output/domains/furniture.py`
- Modify: `src/output/domains/registry.py`
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: `DomainProfile` from Task 1.
- Produces: `PHONE`, `CAR`, `FURNITURE` registered as `phone`, `car`, `furniture`.

- [ ] **Step 1: Write the failing test**

```python
def test_phone_extracts_specs_in_four_languages():
    cases = [
        "iphone 13 128gb, bateria 89%, 6.1 palca",        # sk
        "iphone 13 128 gb, baterie 89 %, 6,1 palce",       # cs
        "iphone 13 128 gb, akku 89 %, 6,1 zoll",           # de
        "iphone 13 128gb, battery 89%, 6.1 inch",          # en
    ]
    for text in cases:
        specs = get("phone").extract(text)
        assert specs["storage"] == "128 GB", text
        assert specs["battery_health"] == "89%", text
        assert specs["screen_size"] == '6.1"', text


def test_phone_does_not_match_on_the_word_telefon_alone():
    assert detect("Kontakt: telefón 0900 000 000").name == "generic"
    assert detect("Kontakt: Telefon 0900 000 000").name == "generic"


def test_phone_aliases_map_llm_keys():
    specs = get("phone").normalise_specs(
        {"storage_gb": "128", "battery_percentage": "89", "price_eur": "219"}
    )
    assert specs == {"storage": "128", "battery_health": "89"}


def test_car_needs_a_brand_or_two_regular_keywords():
    assert detect("Predám kolesá, 18 palcov").name == "generic"
    assert detect("Predám auto, 180 000 km").name == "generic"
    assert detect("Predám auto, rok 2015, 180 000 km").name == "car"
    assert detect("Škoda Octavia 2015, 180 000 km").name == "car"


def test_car_detected_in_german_and_czech():
    assert detect("Verkaufe VW Golf, Baujahr 2015, 180000 km").name == "car"
    assert detect("Prodám Škoda Octavia, rok 2015, najeto 180 000 km").name == "car"


def test_car_extracts_specs_in_german():
    specs = get("car").extract(
        "vw golf baujahr 2015, 180000 km, diesel, automatik"
    )
    assert specs["year"] == "2015"
    assert specs["mileage"] == "180000 km"
    assert specs["fuel"] == "Diesel"
    assert specs["transmission"] == "Automatic"


def test_furniture_extracts_specs_in_four_languages():
    cases = [
        "sedacia súprava, rozmery 250x180 cm, koža",
        "sedací souprava, rozměry 250 x 180 cm, kůže",
        "sofa, masse 250 x 180 cm, leder",
        "couch, dimensions 250×180 cm, leather",
    ]
    for text in cases:
        specs = get("furniture").extract(text)
        assert specs["dimensions"] == "250x180 cm", text
        assert specs["material"] == "Leather", text


def test_generic_is_not_selected_for_a_known_domain():
    assert detect("Gauč, koža, 200x90 cm").name == "furniture"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -v`
Expected: FAIL — `get("phone")` raises `KeyError`

- [ ] **Step 3: Implement the three profiles**

All patterns run on `fold(text)` from Task 1 and return one canonical value, so a report
reads the same whichever language the seller used (spec section 13.3).

`PHONE`: strong `iphone`, `smartfon`, `smartphone`, `mobil`, `handy`, `samsung galaxy`,
`xiaomi`, `pixel`, `huawei`, `oneplus`; key specs `storage`, `ram`, `battery_health`,
`screen_size`; aliases `storage_gb → storage`, `battery_percentage → battery_health`,
`battery → battery_health`, `ram_gb → ram`, `screen → screen_size`.
Storage accepts `128gb`, `128 gb`, `128 go`, `1 tb` and stores `128 GB`. `ram` accepts
`8 GB RAM`, `8gb ram` and `12 GB` only when the word `ram` is present; a bare `128 GB` is
storage, not memory. Battery health accepts `bateria 89%`, `baterie 89 %`, `akku 89%`,
`battery 89%`, `stav baterie 89`, `zdravie baterie 89`, `batterie 89` and stores `89%`.
`screen_size` accepts `6.1 palca`, `6,1 palce`, `6,1 zoll`, `6.1 inch`, `6.1 cala`, `6,1"`
and stores `6.1"`.
`telefon` is deliberately not a keyword: it appears in contact lines.

`CAR`: strong `automobil`, `vozidlo`, `fahrzeug`, `pkw`, `samochod`, plus the brands in
spec section 5.2; keywords `km`, `rok`, `najeto`, `najazdene`, `baujahr`, `kilometer`,
`mileage`, `przebieg`, `year`; key specs `year`, `mileage`, `fuel`, `engine`,
`transmission`. `mileage` accepts `180000 km`, `180 000 km`, `180.000 km`, `180 tkm`,
`112000 meilen` and stores `180000 km`. `fuel` maps `benzin`/`benzín`/`petrol` →
`Petrol`, `nafta`/`diesel`/`dizel` → `Diesel`, `elektro`/`electric` → `Electric`,
`hybrid` → `Hybrid`. `transmission` maps `automat`/`automatik`/`automatic`/`dsg` →
`Automatic`, `manual`/`manuál`/`manuell`/`schaltgetriebe` → `Manual`. The regexes run on
folded text, so the accented spellings are source words, not separate patterns.

`FURNITURE`: strong `sedacia`, `sedaci`, `gauc`, `sofa`, `couch`, `sessel`, `stuhl`,
`tisch`, `schrank`, `bett`, `regal`, `nabytek`, `meble`, `kanapa`, `fotel`, `stol`,
`skrina`, `postel`, `komoda`, `polica`; key specs `dimensions`, `material`, `color`,
`condition_notes`. Dimensions accepts `250x180 cm`, `250 x 180 cm`, `250×180`,
`2,5 x 1,8 m` and stores `250x180 cm`. `material` maps `koza|kuze|leder|leather` →
`Leather`, `sklo|glass|glas` → `Glass`, `drevo|holz|wood` → `Wood`, `textil|stoff` →
`Fabric`, `kov|metal|metall` → `Metal`.

`color`, `condition_notes` and the car's `engine` have no deterministic extractor: they
stay empty offline and the LLM fills them when it is available. `spec_coverage` therefore
counts them as missing in an offline run, which is accurate — the listing did not state
them in a form the deterministic layer can read.

Register in `DOMAIN_REGISTRY` after `bike`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/domains tests/test_domains.py
git commit -m "feat(domains): add phone, car and furniture profiles"
```

---

### Task 4: Domain-neutral scoring

**Files:**
- Modify: `src/output/processor.py` — `DealAnalysis`, `_score_breakdown` (lines 887-974),
  `_add_cross_alternatives` (lines 782-814)
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: `get()` and `DOMAIN_REGISTRY` from Task 1.
- Produces: `DealAnalysis.domain: str = "generic"` and
  `DealAnalysis.profile: DomainProfile | None = None`; `ResultProcessor.BASE_WEIGHTS`,
  `ResultProcessor.CONNECTIVITY_WEIGHT` and `ResultProcessor._weighted_score`;
  `_score_breakdown` returns only applicable rows, and `_weighted_score` normalises the
  final score by the weight sum of those rows.

- [ ] **Step 1: Write the failing test**

Add `from src.output.processor import DealAnalysis, ResultProcessor` and
`from src.searcher.adapters.base import Deal` to the imports at the top of
`tests/test_domains.py`, then append:

```python
def _analysis_for(title: str, domain: str, specs: dict[str, str]):
    deal = Deal(url="u", title=title, price_eur=200.0, condition="used", site_name="bazos")
    return DealAnalysis(deal=deal, domain=domain, specs=specs, seller_type="classifieds")


def test_furniture_has_no_connectivity_row():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for("Sedačka", "furniture", {"dimensions": "200x90 cm"})
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert "Connectivity" not in breakdown


def test_computer_keeps_connectivity_row():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for("Mini PC", "computer", {"cpu": "RYZEN 7"})
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert "Connectivity" in breakdown


def test_base_weights_are_0_95_and_connectivity_completes_the_scale():
    assert sum(ResultProcessor.BASE_WEIGHTS.values()) == pytest.approx(0.95)
    assert (
        sum(ResultProcessor.BASE_WEIGHTS.values())
        + ResultProcessor.CONNECTIVITY_WEIGHT
    ) == pytest.approx(1.0)


def test_weights_normalise_when_a_row_is_missing():
    processor = ResultProcessor.__new__(ResultProcessor)
    breakdown = {label: 100.0 for label in ResultProcessor.BASE_WEIGHTS}
    # No Connectivity row: the five base rows are rescaled from 0.95 to 1.00.
    assert processor._weighted_score(breakdown, get("furniture")) == 100.0
    # A computer does have the row; a breakdown without it loses its 0.05.
    assert processor._weighted_score(
        breakdown, get("computer")
    ) == pytest.approx(95.0)


def test_phone_spec_match_is_coverage():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for(
        "iPhone", "phone", {"storage": "128 GB", "battery_health": "89%"}
    )
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert breakdown["Spec match"] == 50  # 2 of 4 key specs


def test_generic_spec_match_is_neutral():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for("Kávovar", "generic", {})
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert breakdown["Spec match"] == 50
    assert "Connectivity" not in breakdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -k "connectivity or coverage or neutral or weights" -v`
Expected: FAIL — `DealAnalysis` has no `domain`, `ResultProcessor` has no `BASE_WEIGHTS`,
and `Connectivity` is always present

- [ ] **Step 3: Rewrite the scoring**

Add `domain: str = "generic"` and `profile: DomainProfile | None = None` to
`DealAnalysis`. The `profile` field keeps the exact object that detected the domain,
including an AI draft that is not in `DOMAIN_REGISTRY`; every consumer resolves
`profile = analysis.profile or get(analysis.domain)`. Without it, scoring an AI domain
would raise `KeyError`. Define the weights as class attributes on `ResultProcessor`,
next to the existing class-level constants:

```python
BASE_WEIGHTS = {
    "Requirement fit": 0.30,
    "Spec match": 0.25,
    "Price": 0.20,
    "Condition & warranty": 0.10,
    "Seller trust": 0.10,
}
CONNECTIVITY_WEIGHT = 0.05
```

In `_score_breakdown`, resolve `profile = analysis.profile or get(analysis.domain)`. Build
rows from `BASE_WEIGHTS` plus `Connectivity` only when
`"Connectivity" in profile.optional_rows`.
Compute `spec_match` as `round(100 * stated / len(profile.key_specs))` when
`profile.key_specs` is non-empty, else `50`. `stated` counts keys present in
`analysis.specs` with a non-empty stripped value. Delete the bike and computer
`spec_match` branches, the `_looks_like_bike` call and the `if bike: connectivity = 50`
special case: a domain without the `Connectivity` row never computes it, and only
`computer` enables the row. Keep the existing price, condition and seller formulas and
the `wrong_form_factor` overrides. Return only the rows that were built.

Add a helper that turns a breakdown into the final score, so the normalisation has one
home and one test:

```python
def _weighted_score(
    self, breakdown: dict[str, float], profile: DomainProfile
) -> float:
    weights = dict(self.BASE_WEIGHTS)
    if "Connectivity" in profile.optional_rows:
        weights["Connectivity"] = self.CONNECTIVITY_WEIGHT
    total = sum(weights.values())
    return round(
        sum(breakdown.get(label, 0.0) * weight for label, weight in weights.items())
        / total,
        1,
    )
```

In `_add_cross_alternatives`, replace the inline `weights` dict and the raw weighted sum
with
`analysis.score = self._weighted_score(analysis.score_breakdown, analysis.profile or get(analysis.domain))`.
`BASE_WEIGHTS` sums to 0.95; `CONNECTIVITY_WEIGHT` brings a computer to 1.00, while a
domain without the row is rescaled by 0.95 so its maximum stays 100.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/processor.py tests/test_domains.py
git commit -m "feat(scoring): score only the rows a domain enables"
```

---

### Task 5: Wire domains into analysis and the report

**Files:**
- Modify: `src/output/processor.py` — `_heuristic_analysis` (602-660), `_llm_analyze_batch` (260-345), `_matches_prompt` (664-698), `_deal_to_dict` (1177+), Markdown renderer (~1149)
- Modify: `src/output/domains/__init__.py` if exports are missing
- Test: `tests/test_domains.py`, `tests/test_processor_details.py`

**Interfaces:**
- Consumes: `detect()`, `get()`, `DomainProfile.extract/check` from Tasks 1-3.
- Produces: `DealAnalysis.spec_coverage: dict[str, list[str]]` with keys `stated` and
  `missing`; JSON deal gains `"domain"` and `"spec_coverage"`.

- [ ] **Step 1: Write the failing test**

Append these to `tests/test_processor_details.py`, which already imports `asyncio`,
`json`, `Path`, `load_config`, `Deal` and `ResultProcessor`.

```python
def test_report_markdown_shows_domain_and_coverage(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/iphone",
        title="iPhone 13 128GB",
        price_eur=350.0,
        condition="used",
        site_name="bazos",
        metadata={"description": "Batéria 89%, 128 GB."},
    )
    _, md_path = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="iphone 13 pouzity")
    )
    markdown = Path(md_path).read_text(encoding="utf-8")
    assert "Domain: phone" in markdown
    assert "2/4 specs stated" in markdown


def test_phone_report_has_no_bike_keys(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/iphone",
        title="iPhone 13 128GB",
        price_eur=350.0,
        condition="used",
        site_name="bazos",
        metadata={"description": "Batéria 89%, 128 GB, bez škrabancov."},
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="iphone 13 pouzity")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "phone"
    assert "wheel_size" not in result["specs"]
    assert "frame_size" not in result["specs"]
    assert result["spec_coverage"]["stated"]
    # A phone has storage and ram keys, but it is not a computer: no CPU advice.
    assert not any("CPU" in con for con in result["cons"])
    assert not any("memory size" in con for con in result["cons"])


def test_sofa_report_has_no_connectivity_row(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/sedacka",
        title="Sedacia súprava",
        price_eur=200.0,
        condition="used",
        site_name="bazos",
        metadata={"description": "Kožená, rozmery 250x180 cm."},
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="sedacia supravy")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "furniture"
    assert "Connectivity" not in result["score_breakdown"]


def test_bike_report_still_skips_xxs_for_tall_rider(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/kellys",
        title="Kellys Madman 10 bicykel",
        price_eur=280.0,
        condition="used",
        site_name="bazos",
        metadata={"description": 'veľkosť rámu: XXS, 26" kolesá'},
    )
    json_path, _ = asyncio.run(
        processor.save_results(
            [deal], str(tmp_path), prompt="horsky bicykel pre muza 180 cm"
        )
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["verdict"] == "skip"
    assert any("too small" in con for con in result["cons"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_processor_details.py -k "domain or bike_keys or connectivity_row or xxs" -v`
Expected: FAIL — `TypeError: DealAnalysis.__init__() got an unexpected keyword argument
'domain'`

- [ ] **Step 3: Replace the hardcoded branches**

In `_heuristic_analysis`: build the folded text once with
`fold(f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}")`, call
`profile = detect(folded, override=self.domain_override)`, set
`analysis.domain = profile.name` and `analysis.profile = profile`, set
`analysis.specs = profile.extract(folded)`, and run
`messages, disqualify = profile.check(specs, prompt)`. Extend the cons with `messages`
and set `matches = False` when `disqualify` is true, exactly as `_bike_size_note` did.
Gate the mini-PC form-factor check on `profile.name == "computer"`, so a furniture or
phone listing is never judged by a PC rule. Pass `profile.name` to
`_heuristic_pros_cons`. Add
`spec_coverage: dict[str, list[str]] = field(default_factory=dict)` to `DealAnalysis`.
Delete `_extract_specs`, `_looks_like_bike`, `_extract_bike_specs` and
`_bike_size_note` from the processor.

In `_heuristic_pros_cons`, `_matches_prompt`, `_checklist` and `_wants_pc_details`:
replace the spec-key guess with the domain. Change the signature to
`_wants_pc_details(domain: str, prompt: str | None = None)`; it returns True only when
`domain == "computer"` or the prompt itself names PC hardware. A phone has `storage` and
`ram` keys, so the old key check would add "Listing does not state the CPU" to every
phone report. Every caller must pass a domain, not `analysis.specs`:
`_heuristic_pros_cons` gets the domain as a new parameter, `_matches_prompt` passes the
domain it already receives, and `_checklist` uses `analysis.domain`.

In `_llm_analyze_batch`: replace `pc_mode` with
`any(analysis.domain == "computer" for analysis in analyses)`.

In `_matches_prompt`: the hardware-token gate applies only when the domain is
`"computer"`; take the domain as a parameter rather than recomputing it. The method is a
`@staticmethod` over `(prompt, deal, specs, wrong_form)`, so it never sees `analysis`.

In `_add_cross_alternatives`: after scoring, set
`analysis.spec_coverage = {"stated": [...], "missing": [...]}` from
`(analysis.profile or get(analysis.domain)).key_specs` and `analysis.specs` (non-empty
stripped values count as stated).

In `_deal_to_dict`: add `"domain": analysis.domain` and
`"spec_coverage": analysis.spec_coverage`.

In the Markdown renderer: add `Domain: <name> — <n>/<total> specs stated`, or
`Domain: <name>` when the profile has no key specs.

Add `self.domain_override: str | None = None` to `ResultProcessor.__init__` (Task 7
sets it from the CLI).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py tests/test_processor_details.py -v`
Expected: PASS. `tests/test_processor_details.py` calls `ResultProcessor._extract_specs`,
`_bike_size_note` and `_wants_pc_details` directly, so it needs a real migration, not just
new numbers:
- `_extract_specs(deal)` is domain-specific now. Replace each call with the profile the
  fixture is about: `get("computer").extract(...)` in
  `test_alza_description_is_parsed_into_specs` and `test_pc_specs_do_not_get_bike_keys`,
  `get("car").extract(...)` in `test_car_wheels_are_not_bike_specs`, and
  `get("bike").extract(...)` in the bike tests. Keep the escaped-quote, PC-without-bike-keys
  and car-wheels assertions; they now prove profile isolation rather than one shared
  extractor.
- `_bike_size_note(specs, prompt)` → `get("bike").check(specs, prompt)`. The new return
  is `(messages, disqualify)`: `message is None` becomes `messages == []`, and
  `message` becomes `messages[0]`.
- `_wants_pc_details({}, prompt)` → `_wants_pc_details("generic", prompt)`.
- `_matches_prompt(prompt, deal, specs, wrong_form)` gains the domain argument; the bike
  case passes `"bike"` and the PC case passes `"computer"`.
Update expected `Spec match` values to the coverage values and note the behaviour change
in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/output/processor.py src/output/domains tests
git commit -m "feat(processor): detect product domains and report spec coverage"
```

---

### Task 6: AI fallback with validation and cache

**Files:**
- Create: `src/output/domains/ai.py`
- Create: `src/output/domains/cache.py`
- Modify: `src/output/processor.py` — `_analyze_deals` (214-258)
- Modify: `.gitignore`
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: `DomainProfile`, `DOMAIN_REGISTRY`, `detect(text, override, extra)`.
- Produces:
  - `DomainProposal(domain: str, keywords: list[str], key_specs: list[str], specs: dict[str, str])`.
  - `validate_proposal(payload: dict) -> DomainProposal | None`.
  - `async propose_domain(llm, text: str, prompt: str | None) -> DomainProposal | None`.
  - `proposal_to_profile(proposal: DomainProposal) -> DomainProfile` — sets
    `strong_keywords` from `keywords` and `source="ai"`.
  - `load_drafts(directory: Path) -> dict[str, DomainProfile]`.
  - `save_draft(proposal: DomainProposal, example_title: str, directory: Path) -> Path`.

- [ ] **Step 1: Write the failing test**

Add `import asyncio`, `import json`, `from pathlib import Path`,
`from src.config import load_config`,
`from src.output.domains.ai import DomainProposal, propose_domain, validate_proposal` and
`from src.output.domains.cache import load_drafts, save_draft` to the imports at the top
of `tests/test_domains.py`, then append:

```python
def test_validate_rejects_a_builtin_name():
    assert validate_proposal(
        {
            "domain": "bike",
            "keywords": ["bicykel"],
            "key_specs": ["a", "b"],
            "specs": {"a": "1"},
        }
    ) is None


def test_validate_rejects_too_many_key_specs():
    payload = {
        "domain": "camera",
        "keywords": ["camera"],
        "key_specs": [f"k{i}" for i in range(13)],
        "specs": {"k0": "1"},
    }
    assert validate_proposal(payload) is None


def test_validate_rejects_a_proposal_without_keywords():
    assert validate_proposal(
        {"domain": "camera", "key_specs": ["a", "b"], "specs": {"a": "1"}}
    ) is None


def test_validate_rejects_a_single_key_spec():
    assert validate_proposal(
        {
            "domain": "camera",
            "keywords": ["camera"],
            "key_specs": ["megapixels"],
            "specs": {"megapixels": "24"},
        }
    ) is None


def test_validate_rejects_an_empty_spec_value():
    assert validate_proposal(
        {
            "domain": "camera",
            "keywords": ["camera"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": ""},
        }
    ) is None


def test_validate_accepts_a_valid_proposal():
    proposal = validate_proposal(
        {
            "domain": "camera",
            "keywords": ["camera", "fotoaparat"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": "24"},
        }
    )
    assert proposal is not None
    assert proposal.domain == "camera"
    assert proposal.keywords == ["camera", "fotoaparat"]


def test_validate_folds_keywords_before_storing_them():
    proposal = validate_proposal(
        {
            "domain": "camera",
            "keywords": ["Fotoaparát", "kamera"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": "24"},
        }
    )
    assert proposal is not None
    assert proposal.keywords == ["fotoaparat", "kamera"]


def test_validate_deduplicates_keywords_after_folding():
    proposal = validate_proposal(
        {
            "domain": "camera",
            "keywords": ["fotoaparát", "fotoaparat"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": "24"},
        }
    )
    assert proposal is not None
    assert proposal.keywords == ["fotoaparat"]


@pytest.mark.asyncio
async def test_propose_domain_parses_a_model_reply():
    class FakeLLM:
        async def _chat(self, system, user, **kwargs):
            return json.dumps(
                {
                    "domain": "camera",
                    "keywords": ["camera", "fotoaparat"],
                    "key_specs": ["megapixels", "shutter_count"],
                    "specs": {"megapixels": "24"},
                }
            )

    proposal = await propose_domain(FakeLLM(), "Canon EOS 5D, 24 MP", None)
    assert proposal is not None
    assert proposal.domain == "camera"
    assert proposal.specs == {"megapixels": "24"}


def test_draft_round_trip(tmp_path):
    proposal = DomainProposal(
        domain="camera",
        keywords=["camera", "fotoaparat"],
        key_specs=["megapixels", "shutter_count"],
        specs={},
    )
    save_draft(proposal, "Canon EOS 5D", tmp_path)
    drafts = load_drafts(tmp_path)
    assert drafts["camera"].key_specs == ("megapixels", "shutter_count")
    assert drafts["camera"].strong_keywords == ("camera", "fotoaparat")


def test_cached_draft_is_used_for_detection(tmp_path):
    proposal = DomainProposal(
        domain="camera",
        keywords=["camera", "fotoaparat"],
        key_specs=["megapixels", "shutter_count"],
        specs={},
    )
    save_draft(proposal, "Canon EOS 5D", tmp_path)
    drafts = load_drafts(tmp_path)
    profile = detect("Predám fotoaparát Canon EOS", extra=drafts.values())
    assert profile.name == "camera"


def test_cached_draft_reaches_the_report(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    processor.draft_dir = tmp_path
    save_draft(
        DomainProposal(
            domain="camera",
            keywords=["camera", "fotoaparat"],
            key_specs=["megapixels", "shutter_count"],
            specs={"megapixels": "24"},
        ),
        "Canon EOS 5D",
        tmp_path,
    )
    deal = Deal(
        url="https://bazos.sk/canon",
        title="Predám fotoaparát Canon EOS 5D",
        price_eur=400.0,
        condition="used",
        site_name="bazos",
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="fotoaparat")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "camera"
    assert result["spec_coverage"]["missing"] == ["megapixels", "shutter_count"]


def test_corrupt_draft_is_ignored(tmp_path):
    (tmp_path / "camera.yaml").write_text(":::not yaml", encoding="utf-8")
    assert load_drafts(tmp_path) == {}


def test_draft_with_an_invalid_shape_is_ignored(tmp_path):
    (tmp_path / "camera.yaml").write_text(
        "name: camera\nsource: ai\nkeywords: []\nkey_specs: [a, b]\n",
        encoding="utf-8",
    )
    assert load_drafts(tmp_path) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -k "validate or draft or corrupt or propose" -v`
Expected: FAIL — `ImportError: cannot import name 'validate_proposal'`

- [ ] **Step 3: Implement the fallback**

`ai.py`: `validate_proposal` enforces the rules in spec section 7.3 (including the
`keywords` rule) and returns `None` on any violation, logging the reason at debug level.
Before validating, map every keyword through `fold()` and drop duplicates, so
`fotoaparát` becomes `fotoaparat` and matches folded listing text; the uniqueness and
length checks run on the folded values. `propose_domain` sends one JSON-only prompt, asks
for `domain`, `keywords`, `key_specs` and `specs`, and returns `validate_proposal` of the
parsed reply; any exception returns `None`. `proposal_to_profile` builds a `DomainProfile`
with `strong_keywords=tuple(proposal.keywords)`, `key_specs=tuple(proposal.key_specs)`, no
extractors and `source="ai"`.

`cache.py`: `AI_DRAFT_DIR = Path("data/domains/ai")`. `save_draft` writes YAML with
`name`, `source`, `created_at`, `keywords`, `key_specs`, `examples` (one title). When the
file already exists, keep its `created_at` and merge examples up to three. `load_drafts`
reads every `*.yaml` and validates the **stored shape** directly: `name` matches
`^[a-z0-9_]{2,32}$` and is not built-in, `keywords` has 1–6 unique entries, `key_specs`
has 2–12 unique entries. Fold each keyword and drop duplicates before validating, so a
hand-edited draft with diacritics still loads. It must not call `validate_proposal`,
because the cache has no `specs` field; that function validates a live model reply, not a
file. Files that fail to parse or validate are skipped.

`_analyze_deals`: add `self.draft_dir = AI_DRAFT_DIR` to `ResultProcessor.__init__` and
call `drafts = load_drafts(self.draft_dir)` once. The attribute keeps the real cache
path in production and lets a test point it at `tmp_path`, so tests never read a
developer's `data/domains/ai/`. For every analysis whose `domain == "generic"`, rebuild
`folded = fold(f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}")` and
re-run `detect(folded, extra=drafts.values())`. If a draft matches, set
`analysis.domain = profile.name`, `analysis.profile = profile`, and
`analysis.specs = profile.extract(folded)`; the extractors are empty for an AI draft, but
the call is uniform and keeps the contract.

If an analysis is still `generic` and `self.llm` is set, call `propose_domain` once with
the first such listing's folded text, remembering which analysis it came from. If the
proposal does not match its own listing (`proposal_to_profile(proposal).matches(source)
== 0`), discard it: do not save the draft and leave the listing `generic` — a draft that
cannot name the listing that produced it is write-only and would only pollute the cache.
On success: `save_draft`, build `profile = proposal_to_profile(proposal)`, and apply it
**only to analyses whose folded text matches `profile.matches(folded) > 0`**, setting
`analysis.domain = profile.name` and `analysis.profile = profile` on each. Merge
`profile.normalise_specs(proposal.specs)` into the analysis whose text was sent, and only
if it matched: the proposal's `specs` describe that one listing, not the others. A
different unknown product that does not match the proposal's keywords stays `generic`:
forcing one camera proposal onto a sofa listing would mislabel it. This is spec section
5.3 order: cache before live AI. V1 makes at most one live proposal per run; a second,
different unknown product stays `generic` rather than borrowing the first product's
vocabulary.

Add `data/domains/` to `.gitignore`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/domains src/output/processor.py tests/test_domains.py .gitignore
git commit -m "feat(domains): let the LLM propose unknown domains with a validated cache"
```

---

### Task 7: CLI override, config and docs

**Files:**
- Modify: `src/cli/app.py` — `run` command (~62-100), processor construction (~167)
- Modify: `src/config/models.py` — `OutputConfig`
- Modify: `config.example.yaml`
- Modify: `README.md`, `CHANGELOG.md`
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: `ResultProcessor.domain_override` from Task 5.
- Produces: `--domain` Typer option; `OutputConfig.domain: str = ""`.

- [ ] **Step 1: Write the failing test**

```python
def test_domain_override_reaches_the_report(tmp_path):
    config = load_config()
    config.output.domain = "computer"
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/x",
        title="Predám bicykel",
        price_eur=90.0,
        condition="used",
        site_name="bazos",
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="nieco")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "computer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -k override_reaches -v`
Expected: FAIL — `OutputConfig` has no field `domain`

- [ ] **Step 3: Wire the option**

Add to the `run` command:
`domain: str | None = typer.Option(None, "--domain", help="Force a product domain (bike, computer, phone, car, furniture, generic)")`.
Validate it through `get()` and exit with code 1 listing `sorted(DOMAIN_REGISTRY)` when
the name is unknown. Set
`processor.domain_override = domain or processor.domain_override`, so the CLI wins over
the config value.

Add `domain: str = ""` to `OutputConfig` and document it in `config.example.yaml` as
`output.domain: ""` (empty means auto-detect). In `ResultProcessor.__init__`, replace
`self.domain_override: str | None = None` from Task 5 with
`self.domain_override = getattr(self.config, "domain", "") or None`, so the config value
is honoured even when the CLI passes nothing.

README: add `--domain` to the command reference and a short "Product domains" section
listing the built-in names and the AI fallback. CHANGELOG: describe the domain registry,
the scoring change from section 9 of the spec, and the new env-free config key.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/cli/app.py src/config/models.py config.example.yaml README.md CHANGELOG.md tests/test_domains.py
git commit -m "feat(cli): add --domain override and document product domains"
```

---

### Task 8: Interim verification

This is a checkpoint after the domain work, not the end of the plan. Task 16 repeats it
with the multilingual and defect-fix work included.

**Files:**
- Modify: `CHANGELOG.md` — verification line only
- Test: whole suite

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass, 0 failures. Record the exact counts.

- [ ] **Step 2: Run scoped ruff**

Run: `python -m ruff check src/output/processor.py src/output/domains tests/test_domains.py src/cli/app.py src/config/models.py`
Expected: `All checks passed!`

- [ ] **Step 3: Live smoke test (bike and phone)**

Temporarily disable every site except `bazos` in `config.yaml` (the file is git-ignored;
restore it afterwards), then run:

```powershell
$env:ADS_LOCAL_POLICY = "never"
python -m src.cli run --prompt "horský bicykel pre muža 180 cm" --condition used --category hobby --country SK --max-sites 1
python -m src.cli run --prompt "iPhone 13 128 GB" --condition used --category electronics --country SK --max-sites 1
```

Confirm each report's `sites` field is `["bazos"]`, the JSON contains `"domain": "bike"`
and `"domain": "phone"` respectively, and no cross-domain keys appear.

- [ ] **Step 4: Update CHANGELOG verification line**

Set it to the counts from Step 1.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record verification for product domains"
```

---

### Task 9: Enrichment covers the whole page and reports its own gaps

**Files:**
- Modify: `src/searcher/adapters/base.py` — `enrich_limit` on `__init__`
- Modify: `src/searcher/adapters/bazos.py` — limit, price sort, `detail_failed`, `detail_skipped`
- Modify: `src/searcher/adapters/profile_adapter.py` — accept and forward `enrich_limit`
- Modify: `src/searcher/playwright_searcher.py` — pass `config.search.enrich_limit`
- Modify: `src/config/models.py` — `SearchConfig.enrich_limit`
- Modify: `src/output/processor.py` — `_heuristic_pros_cons`, `_llm_analyze_batch`
- Test: `tests/test_bazos_details.py`, `tests/test_processor_details.py`

**Interfaces:**
- Consumes: `Deal.metadata`.
- Produces: `BaseAdapter.enrich_limit: int` (default 20); `metadata["detail_failed"]`,
  `metadata["detail_skipped"]`; one con when either is set; a prompt rule that forbids
  "not stated" for a description we never fetched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bazos_details.py`:

```python
@pytest.mark.asyncio
async def test_enrichment_covers_the_whole_page_by_default(monkeypatch):
    import src.searcher.adapters.bazos as bazos_mod

    adapter = BazosAdapter()
    calls = []

    async def fake_enrich(page, selected):
        calls.append(list(selected))
        return 0

    async def noop(*args, **kwargs):
        return None

    async def elements(*args, **kwargs):
        return [object()] * 75

    created = []

    async def fake_extract(page, title_el, price_el):
        deal = _deal(url=f"https://sport.bazos.sk/inzerat/{len(created)}/item.php")
        created.append(deal)
        return deal

    monkeypatch.delenv("ADS_BAZOS_DETAIL_LIMIT", raising=False)
    monkeypatch.setattr(adapter, "_enrich_details", fake_enrich)
    monkeypatch.setattr(adapter, "_goto_search", noop)
    monkeypatch.setattr(adapter, "_handle_cookie_consent", noop)
    monkeypatch.setattr(adapter, "_apply_filters", noop)
    monkeypatch.setattr(adapter, "_extract_from_group", fake_extract)
    monkeypatch.setattr(bazos_mod.asyncio, "sleep", noop)

    page = FakePage()
    page.wait_for_selector = noop
    page.query_selector_all = elements

    assert len(await adapter.search(page, "iphone")) == 15
    assert len(calls[0]) == 15


@pytest.mark.asyncio
async def test_enrichment_prefers_the_cheapest_when_capped(monkeypatch):
    import src.searcher.adapters.bazos as bazos_mod

    adapter = BazosAdapter()
    prices = [300.0, 100.0, 200.0, 400.0]
    calls = []

    async def fake_enrich(page, selected):
        calls.append(list(selected))
        return 0

    async def noop(*args, **kwargs):
        return None

    async def elements(*args, **kwargs):
        return [object()] * 20

    created = []

    async def fake_extract(page, title_el, price_el):
        deal = _deal(url=f"https://sport.bazos.sk/inzerat/{len(created)}/item.php")
        deal.price_eur = prices[len(created)]
        created.append(deal)
        return deal

    monkeypatch.setenv("ADS_BAZOS_DETAIL_LIMIT", "2")
    monkeypatch.setattr(adapter, "_enrich_details", fake_enrich)
    monkeypatch.setattr(adapter, "_goto_search", noop)
    monkeypatch.setattr(adapter, "_handle_cookie_consent", noop)
    monkeypatch.setattr(adapter, "_apply_filters", noop)
    monkeypatch.setattr(adapter, "_extract_from_group", fake_extract)
    monkeypatch.setattr(bazos_mod.asyncio, "sleep", noop)

    page = FakePage()
    page.wait_for_selector = noop
    page.query_selector_all = elements

    await adapter.search(page, "iphone")
    assert [d.price_eur for d in calls[0]] == [100.0, 200.0]


@pytest.mark.asyncio
async def test_failed_detail_is_marked_not_guessed():
    adapter = BazosAdapter()
    adapter.detail_delay_seconds = 0
    deal = _deal()

    failed = await adapter._enrich_details(FakePage(fail=True), [deal])

    assert failed == 1
    assert deal.metadata["detail_failed"] is True
```

Update the existing `test_enrich_details_keeps_card_data_when_page_fails` to expect
`deal.metadata == {"detail_failed": True}`.

Append to `tests/test_processor_details.py`:

```python
def test_report_says_description_unavailable_when_fetch_failed(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/x",
        title="iPhone 13 128GB",
        price_eur=300.0,
        condition="used",
        site_name="bazos",
        metadata={"detail_failed": True},
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="iphone 13")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert any("could not be fetched" in con for con in result["cons"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bazos_details.py tests/test_processor_details.py -k "whole_page or cheapest or marked or unavailable" -v`
Expected: FAIL — default limit is still 10, no marker, no con

- [ ] **Step 3: Implement**

`base.py`: add `enrich_limit: int | None = None` to `__init__`, store
`self.enrich_limit = enrich_limit or 20`.

`bazos.py`: replace `limit = int(os.environ.get("ADS_BAZOS_DETAIL_LIMIT", "10"))` with
`limit = int(os.environ.get("ADS_BAZOS_DETAIL_LIMIT", str(self.enrich_limit)))` and make
the `ValueError` fallback use `self.enrich_limit` too (the warning text must not say
"using 10"). Before slicing, sort by price with unknown prices last:

```python
ordered = sorted(deals, key=lambda deal: (deal.price_eur <= 0, deal.price_eur))
selected = ordered[: max(0, limit)]
for deal in ordered[max(0, limit):]:
    deal.metadata["detail_skipped"] = True
```

In `_enrich_details`, set `deal.metadata["detail_failed"] = True` where it currently
counts a failure, and do not clear it on success.

`playwright_searcher.py:348` and `:354`: pass
`enrich_limit=getattr(self.config.search, "enrich_limit", 20)` to both adapter
constructors. `ProfileAdapter.__init__` does not accept it today, so add
`enrich_limit: int | None = None` there and forward it to
`super().__init__(base_url, currency, enrich_limit)`; otherwise the profile path raises
`TypeError` before it can search.

`config/models.py`: add `enrich_limit: int = 20` to `SearchConfig` and document it in
`config.example.yaml`.

`processor.py`: in `_heuristic_pros_cons`, append
`"listing description could not be fetched — specs may be missing"` when
`deal.metadata.get("detail_failed")` or `deal.metadata.get("detail_skipped")`. In
`_llm_analyze_batch`, write `description: not fetched` for those deals instead of
omitting the field, and add the rule: "When a listing says its description was not
fetched, do not claim a specification is not stated; say it could not be checked."

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bazos_details.py tests/test_processor_details.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/searcher/adapters/base.py src/searcher/adapters/bazos.py src/searcher/adapters/profile_adapter.py src/searcher/playwright_searcher.py src/config/models.py config.example.yaml src/output/processor.py tests/test_bazos_details.py tests/test_processor_details.py
git commit -m "fix(enrichment): cover the whole page and mark unfetched details"
```

---

### Task 10: Collapse duplicate listings before scoring

**Files:**
- Create: `src/output/dedup.py`
- Modify: `src/output/processor.py` — `save_results` before `_analyze_deals`
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: `fold`, `collapse_ws` from Task 1.
- Produces: `collapse_duplicates(deals: list[Deal]) -> tuple[list[Deal], int]` — keeps the
  cheapest of each identical-title group, records the rest under
  `metadata["duplicates"]`, returns the collapsed count.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedup.py
from src.output.dedup import collapse_duplicates
from src.searcher.adapters.base import Deal


def _deal(url: str, title: str, price: float, site: str = "bazos") -> Deal:
    return Deal(url=url, title=title, price_eur=price, site_name=site)


def test_identical_titles_collapse_to_the_cheapest():
    deals = [
        _deal("a", "iPhone 13 Pink BATERIE 100% TOP", 320),
        _deal("b", "iPhone 13  Pink  BATERIE 100% TOP", 300),
        _deal("c", "iPhone 13 Blue BATERIE 100% TOP", 340),
    ]
    kept, collapsed = collapse_duplicates(deals)
    assert collapsed == 1
    assert [d.url for d in kept] == ["b", "c"]
    assert kept[0].metadata["duplicates"] == [
        {"url": "a", "price_eur": 320.0}
    ]


def test_same_title_on_different_sites_is_not_a_duplicate():
    deals = [
        _deal("a", "iPhone 13", 300, "bazos"),
        _deal("b", "iPhone 13", 280, "alza"),
    ]
    kept, collapsed = collapse_duplicates(deals)
    assert collapsed == 0
    assert len(kept) == 2


def test_diacritics_do_not_prevent_a_duplicate():
    deals = [_deal("a", "Kožená sedačka", 200), _deal("b", "Kozena sedacka", 180)]
    kept, collapsed = collapse_duplicates(deals)
    assert collapsed == 1
    assert kept[0].url == "b"


def test_unknown_price_never_beats_a_known_one():
    deals = [_deal("a", "iPhone 13", 0.0), _deal("b", "iPhone 13", 250.0)]
    kept, _ = collapse_duplicates(deals)
    assert kept[0].url == "b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.output.dedup'`

- [ ] **Step 3: Implement**

`src/output/dedup.py` groups deals by
`(deal.site_name, fold(collapse_ws(deal.title)))`, preserving first-seen order. Within a
group, sort by `(price_eur <= 0, price_eur)` so a known cheap price wins and an unknown
price loses. Keep the first, and if the group had more than one member set
`metadata["duplicates"]` to a list of `{"url", "price_eur"}` for the rest.
Return `(kept, collapsed)`.

In `save_results`, before `analyses = await self._analyze_deals(deals, prompt)`:

```python
deals, duplicates_collapsed = collapse_duplicates(deals)
```

Add `"duplicates_collapsed": duplicates_collapsed` to the JSON payload.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/dedup.py src/output/processor.py tests/test_dedup.py
git commit -m "fix(report): collapse duplicate listings before scoring"
```

---

### Task 11: Restrict LLM spec keys to the profile vocabulary

**Files:**
- Modify: `src/output/processor.py` — `_llm_analyze_batch` (listing line + rules), `_merge_llm_analysis`
- Test: `tests/test_processor_details.py`

**Interfaces:**
- Consumes: `analysis.profile or get(analysis.domain)` and `.normalise_specs()` from
  Tasks 1–3, so an AI draft keeps its vocabulary.
- Produces: LLM specs mapped through aliases, restricted to `key_specs`, `price_eur`
  always dropped; the prompt names the allowed keys per listing.

- [ ] **Step 1: Write the failing test**

```python
def test_llm_specs_are_restricted_to_the_profile_keys():
    processor = ResultProcessor(load_config())
    analysis = DealAnalysis(
        deal=Deal(
            url="u",
            title="iPhone 13",
            price_eur=300.0,
            condition="used",
            site_name="bazos",
        ),
        domain="phone",
    )
    processor._merge_llm_analysis(
        analysis,
        {
            "id": "L0",
            "specs": {
                "storage_gb": "128",
                "battery_percentage": "89",
                "color": "pink",
                "price_eur": "300",
            },
        },
        "iphone 13",
    )
    assert analysis.specs == {"storage": "128", "battery_health": "89"}


def test_generic_keeps_model_specs_but_never_price_eur():
    processor = ResultProcessor(load_config())
    analysis = DealAnalysis(
        deal=Deal(
            url="u",
            title="Kávovar Delonghi",
            price_eur=120.0,
            condition="used",
            site_name="bazos",
        ),
        domain="generic",
    )
    processor._merge_llm_analysis(
        analysis,
        {
            "id": "L0",
            "specs": {"pressure_bar": "15", "color": "silver", "price_eur": "120"},
        },
        "kavovar",
    )
    assert analysis.specs == {"pressure_bar": "15", "color": "silver"}


def test_llm_prompt_names_the_profile_keys():
    captured = {}

    class CaptureLLM:
        async def _chat(self, system, user, **kwargs):
            captured["user"] = user
            return "[]"

    processor = ResultProcessor(load_config(), llm=CaptureLLM())
    analysis = DealAnalysis(
        deal=Deal(
            url="u",
            title="iPhone 13",
            price_eur=300.0,
            condition="used",
            site_name="bazos",
        ),
        domain="phone",
    )
    asyncio.run(processor._llm_analyze_batch([analysis], "iphone 13"))
    assert "storage, ram, battery_health, screen_size" in captured["user"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_processor_details.py -k "restricted or names_the_profile" -v`
Expected: FAIL — `storage_gb`, `color` and `price_eur` survive

- [ ] **Step 3: Implement**

In `_llm_analyze_batch`, append the allowed keys to each listing line:

```python
profile = analysis.profile or get(analysis.domain)
if profile.key_specs:
    line += " | track these specs: " + ", ".join(profile.key_specs)
```

Change the rule at `processor.py:307` from "Use short snake_case keys in specs for facts
stated in the listing" to "Use only the spec keys listed for that listing and omit a key
the listing does not state; when no keys are listed, use short snake_case keys for facts
stated in the listing." The second clause keeps `generic` useful, because it has no
`key_specs` to list. Delete the `pc_mode` key-list rule, because the profile now supplies
it for every domain that has a vocabulary.

In `_merge_llm_analysis`, keep the existing `unknown` value filter, but build a filtered
dict first and normalise that:

```python
filtered = {}
for key, value in specs.items():
    if value is None:
        continue
    text = self._tidy_text(str(value).strip())
    if text.casefold() in unknown:
        continue
    filtered[str(key)] = text

for key, value in (
    analysis.profile or get(analysis.domain)
).normalise_specs(filtered).items():
    ...
    analysis.specs.setdefault(key, value)
```

This keeps `"not stated"` out of the values and prevents `price_eur` or an invented key
from reaching the report.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_processor_details.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/processor.py tests/test_processor_details.py
git commit -m "fix(llm): keep spec keys inside the domain vocabulary"
```

---

### Task 12: Deterministic guard for "not stated" claims

**Files:**
- Create: `src/output/requirements.py`
- Modify: `src/output/processor.py` — `_merge_llm_analysis`
- Test: `tests/test_requirements.py`

**Interfaces:**
- Consumes: `fold` from Task 1, `analysis.specs` from Task 11.
- Produces: `extract_requirements(prompt) -> dict[str, float | int | None]` with keys
  `storage_gb`, `min_battery_percent`, `max_price_eur`;
  `apply_requirement_guard(cons, specs, requirements) -> tuple[list[str], bool]`;
  `has_hard_defect(cons) -> bool` — True when a remaining con names an independent
  defect (cracked, broken, water damage, wrong model, locked) that the guard must not
  override.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_requirements.py
import pytest

from src.output.requirements import apply_requirement_guard, extract_requirements


@pytest.mark.parametrize(
    ("prompt", "key", "value"),
    [
        ("iPhone 13 128 GB, batéria aspoň 85%", "storage_gb", 128),
        ("iPhone 13 128GB, battery at least 85%", "min_battery_percent", 85),
        ("iPhone 13, Akku mindestens 85 %", "min_battery_percent", 85),
        ("iPhone 13, baterie alespoň 85 %", "min_battery_percent", 85),
        ("iPhone 13 do 300 eur", "max_price_eur", 300),
        ("iPhone 13 unter 300 Euro", "max_price_eur", 300),
    ],
)
def test_extract_requirements_in_four_languages(prompt, key, value):
    assert extract_requirements(prompt)[key] == value


def test_guard_drops_a_false_not_stated_con():
    kept, rescued = apply_requirement_guard(
        ["storage not stated", "no mention of physical condition"],
        {"storage": "128 GB"},
        {"storage_gb": 128},
    )
    assert kept == ["no mention of physical condition"]
    assert rescued is True


def test_guard_does_not_rescue_a_different_rejection():
    kept, rescued = apply_requirement_guard(
        ["cracked screen"], {"storage": "128 GB"}, {"storage_gb": 128}
    )
    assert kept == ["cracked screen"]
    assert rescued is False


def test_guard_matches_the_no_mention_wording():
    kept, rescued = apply_requirement_guard(
        ["no mention of storage capacity"], {"storage": "128 GB"}, {"storage_gb": 128}
    )
    assert kept == []
    assert rescued is True


def test_hard_defect_remains_after_the_false_con_is_dropped():
    from src.output.requirements import has_hard_defect

    kept, rescued = apply_requirement_guard(
        ["storage not stated", "cracked screen"],
        {"storage": "128 GB"},
        {"storage_gb": 128},
    )
    assert kept == ["cracked screen"]
    # The false "not stated" con is gone, but the caller must not flip the
    # requirement flag while an independent defect remains.
    assert rescued is True
    assert has_hard_defect(kept) is True


def test_guard_respects_a_battery_below_the_minimum():
    kept, rescued = apply_requirement_guard(
        ["battery not stated"], {"battery_health": "79%"}, {"min_battery_percent": 85}
    )
    assert kept == ["battery not stated"]
    assert rescued is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_requirements.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.output.requirements'`

- [ ] **Step 3: Implement**

`extract_requirements` folds the prompt and reads three optional numbers. Every pattern
is written in folded form, because the prompt it receives has already lost its
diacritics:

- storage: `\b(\d{2,4})\s*(?:gb|go)\b` — store `storage_gb`.
- battery: `\b(?:aspon|min|minimalne|alespon|mindestens|at least|least)\s*(\d{2,3})\s*%`
  or `\b(\d{2,3})\s*%\s*(?:bater|batter|akku)` — store `min_battery_percent`. Note
  `alespon`, not `alespoň`: the folded prompt contains the ASCII form.
- price: a local regex with the full vocabulary
  `\b(?:do|max(?:imum)?|maximal|pod|unter|bis|under|up\s+to|najviac|menej\s+ako)\s*(\d[\d\s.,]*)`
  — store `max_price_eur`. Do not import `_MAX_RE` here: Task 14 adds `unter` and `bis`
  to the shared filter regex, and Task 12 must pass before that change exists.

`apply_requirement_guard` maps requirement keys to spec keys and con patterns:

| Requirement | Spec | Con pattern |
|---|---|---|
| `storage_gb` | `storage` | `storage.*not stated`, `not stated.*storage`, `no mention of storage`, `storage.*not mentioned`, `storage.*missing`, `neuveden`, `nicht angegeben` |
| `min_battery_percent` | `battery_health` | `batter.*not stated`, `not stated.*batter`, `no mention of batter`, `battery.*not mentioned`, `batter.*missing`, `akku.*nicht`, `bater.*neuveden` |

`max_price_eur` is extracted for completeness but not used by the guard: price is a deal
field, and "above your maximum" is a real reason, not a false "not stated" claim.

A con is dropped only when the spec is present, its numeric value satisfies the
requirement, and the con matches the pattern. Match against `fold(con)` and write the
patterns in folded form, so `Storage not stated` and `storage not stated` behave the
same. Return `(kept_cons, rescued)` where `rescued` is True when at least one con was
dropped.

`has_hard_defect` folds each remaining con and returns True for an independent defect:
`cracked`, `broken`, `water damage`, `does not work`, `not working`, `faulty`,
`missing part`, `wrong model`, `icloud locked`, `blacklisted`. The list is data, so a new
language is a new entry.

In `_merge_llm_analysis`, after cons are merged and before the wrong-form-factor block:

```python
requirements = extract_requirements(prompt or "")
kept, rescued = apply_requirement_guard(analysis.cons, analysis.specs, requirements)
if rescued:
    analysis.cons = kept
    if not has_hard_defect(kept):
        analysis.matches_requirements = True
```

The false con is removed even when a hard defect remains, but the flag stays False: a
cracked screen or a wrong model is a rejection for another reason, and the guard must not
override it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_requirements.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/requirements.py src/output/processor.py tests/test_requirements.py
git commit -m "fix(requirements): verify not-stated claims against the listing text"
```

---

### Task 13: Stop inventing a market from three listings

**Files:**
- Modify: `src/output/processor.py` — `_add_cross_alternatives`, `_llm_analyze_batch` rules
- Test: `tests/test_domains.py`

**Interfaces:**
- Consumes: deduplicated `analyses` from Task 10.
- Produces: `MIN_PRICE_SAMPLE = 4`; `Price` is 50 when fewer than four distinct prices
  exist; the LLM prompt forbids market-value claims and `_merge_llm_analysis` drops any
  con that still makes one.

- [ ] **Step 1: Write the failing test**

```python
def test_price_is_neutral_with_fewer_than_four_distinct_prices():
    processor = ResultProcessor.__new__(ResultProcessor)
    analyses = [_analysis_for(f"Deal {i}", "generic", {}) for i in range(3)]
    for analysis, price in zip(analyses, (100.0, 200.0, 300.0), strict=True):
        analysis.deal.price_eur = price

    processor._add_cross_alternatives(analyses)

    assert all(a.score_breakdown["Price"] == 50 for a in analyses)


def test_price_uses_the_median_with_four_distinct_prices():
    processor = ResultProcessor.__new__(ResultProcessor)
    analyses = [_analysis_for(f"Deal {i}", "generic", {}) for i in range(4)]
    for analysis, price in zip(analyses, (100.0, 200.0, 300.0, 400.0), strict=True):
        analysis.deal.price_eur = price

    processor._add_cross_alternatives(analyses)

    assert analyses[0].score_breakdown["Price"] == 95
    assert analyses[3].score_breakdown["Price"] == 25


def test_price_claim_cons_are_dropped():
    processor = ResultProcessor(load_config())
    analysis = _analysis_for("iPhone 13", "phone", {})
    processor._merge_llm_analysis(
        analysis,
        {
            "id": "L0",
            "cons": [
                "price far exceeds reasonable used market value",
                "storage not stated",
            ],
        },
        "iphone 13",
    )
    assert not any("market" in con for con in analysis.cons)
    assert any("storage" in con for con in analysis.cons)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domains.py -k "price_is_neutral or median_with_four or price_claim" -v`
Expected: FAIL — the three-listing case still scores from a median, and the market-value
con survives

- [ ] **Step 3: Implement**

In `_add_cross_alternatives`:

```python
MIN_PRICE_SAMPLE = 4
...
distinct = {round(analysis.deal.price_eur, 2) for analysis in relevant}
median = statistics.median(prices) if len(distinct) >= MIN_PRICE_SAMPLE else 0.0
```

`median == 0.0` already means "neutral 50" in `_score_breakdown`, so no other change is
needed there. Declare `MIN_PRICE_SAMPLE` as a class attribute on `ResultProcessor`.

In `_llm_analyze_batch`, add the rule: "Do not say a price is above or below market; you
do not know the market. The report computes the price score itself."

A prompt rule is not enforcement. Add a class-level `_PRICE_CLAIM_RE` next to
`MIN_PRICE_SAMPLE`:

```python
_PRICE_CLAIM_RE = re.compile(
    r"\b(?:above|below|over|under)\s+(?:the\s+)?(?:market|reasonable)\b"
    r"|\bmarket\s+value\b|\boverpriced\b|\bprice\s+far\s+exceeds\b",
    re.IGNORECASE,
)
```

In `_merge_llm_analysis`, inside the cons loop, skip a con whose folded text matches it:

```python
if key == "cons" and self._PRICE_CLAIM_RE.search(low):
    continue
```

The `Price` row is then the only place a price is judged, and it is computed from the
sample the report shows.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domains.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/output/processor.py tests/test_domains.py
git commit -m "fix(scoring): require four distinct prices before judging price"
```

---

### Task 14: Multilingual prompt filters

**Files:**
- Modify: `src/searcher/filters.py` — `_CONDITION_ALIASES`, `_SHIPPING_ALIASES`,
  `_SORT_ALIASES`, `_MIN_RE`, `_MAX_RE`, condition patterns, currency suffixes
- Modify: `src/searcher/adapters/profile_adapter.py` — replace its local
  `_strip_diacritics` with `fold`
- Test: `tests/test_filters_multilingual.py`

**Interfaces:**
- Consumes: `fold` from Task 1.
- Produces: `parse_filters_from_text` recognises German, Czech, Slovak, English and Polish
  price, condition, shipping and sort wording.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filters_multilingual.py
import pytest

from src.searcher.filters import parse_filters_from_text


@pytest.mark.parametrize(
    ("prompt", "max_price"),
    [
        ("iPhone unter 300 Euro", 300),
        ("iPhone bis 300 €", 300),
        ("iPhone maximal 300 Euro", 300),
        ("iPhone do 300 eur", 300),
        ("iPhone pod 300", 300),
        ("iPhone under 300 EUR", 300),
        ("iPhone max 300", 300),
    ],
)
def test_max_price_in_four_languages(prompt, max_price):
    assert parse_filters_from_text(prompt).max_price == max_price


@pytest.mark.parametrize(
    ("prompt", "condition"),
    [
        ("gebrauchtes iPhone 13", "used"),
        ("použité iPhone 13", "used"),
        ("použité pouzdro", "used"),
        ("used iPhone 13", "used"),
        ("neues iPhone 13", "new"),
        ("nové iPhone 13", "new"),
        ("generalüberholtes iPhone", "refurbished"),
        ("repasované iPhone", "refurbished"),
    ],
)
def test_condition_in_four_languages(prompt, condition):
    assert parse_filters_from_text(prompt).condition == condition


def test_german_shipping_and_sort():
    filters = parse_filters_from_text("iPhone mit kostenlosem Versand, günstigste zuerst")
    assert filters.shipping == "free"
    assert filters.sort == "price_asc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_filters_multilingual.py -v`
Expected: FAIL — German and Polish words are not recognised

- [ ] **Step 3: Implement**

Replace the local `_strip_diacritics` in `filters.py` and in
`src/searcher/adapters/profile_adapter.py` with `fold` from Task 1 (keep a thin alias in
each module so the rest of the module does not change). The condition, shipping and sort
checks run on `fold(text)`, so the patterns below are folded and must accept the
inflected German forms the tests use:

- Condition, in the existing priority order:
  - refurbished: add `generaluberholt(?:e|es|er)?`, `aufbereitet(?:e|es|er)?`.
  - used: add `gebraucht(?:e|es|er)?`, `wie neu`.
  - new: add `neu(?:e|es|er)?` (the `\b` keeps `neuwertig` out).
- Shipping: add `versandkostenfrei`, `kostenlos(?:er|em|en)?\s+versand`.
- Sort: add `gunstigste(?:n)?\s+zuerst`, `billigste(?:n)?` to `price_asc`;
  `teuerste(?:n)?` to `price_desc`; `neueste(?:n)?` to `newest`. Add the folded Czech
  forms `nejlevnejsi`, `nejdrazsi`, `nejnovejsi`; the Slovak forms `najlacnejsie` and
  `najnovsie` are already present.
- Price regexes: add `unter`, `bis`, `maximal`, `h[oö]chstens` to `_MAX_RE`; `ab`,
  `mindestens`, `over` to `_MIN_RE`; and extend the currency suffix in `_MIN_RE`,
  `_MAX_RE`, `_RANGE_RE` and `_BETWEEN_RE` from `(?:eur|euro|€)?` to
  `(?:eur|euro|€|kč|kc|czk|zł|zl|pln|ft|huf)?`.

The price regexes search the raw prompt, not the folded one, so the currency suffix
needs the literal `kč` and `zł` spellings as well as their ASCII forms.

Mirror the same words in `_CONDITION_ALIASES`, `_SHIPPING_ALIASES` and `_SORT_ALIASES`,
so a `config.yaml` filter can use them too; those tables are looked up with folded
values, so store them folded.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_filters_multilingual.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/searcher/filters.py src/searcher/adapters/profile_adapter.py tests/test_filters_multilingual.py
git commit -m "feat(filters): understand German, Czech and Polish requests"
```

---

### Task 15: Search in the site's language

**Files:**
- Create: `src/searcher/query_language.py`
- Modify: `src/searcher/playwright_searcher.py` — `_execute_round`
- Modify: `src/agents/research/query_expansion.py` — `_fallback`
- Test: `tests/test_query_language.py`

**Interfaces:**
- Consumes: `fold` from Task 1, `self.llm._chat`.
- Produces:
  - `language_for_country(country: str) -> str` — `SK→sk`, `CZ→cs`, `DE/AT→de`,
    `PL→pl`, `HU→hu`, everything else `en`.
  - `detect_language(text: str) -> str` — marker-word/diacritic heuristic, `en` when unsure.
  - `protected_tokens(query: str) -> list[str]` — tokens containing a digit or an
    uppercase letter, so `iPhone`, `128GB` and `Kellys` survive translation.
  - `async localise_query(llm, query, target, cache) -> str` — translated query when every
    protected token survives, otherwise the original.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_language.py
import pytest

from src.searcher.query_language import (
    detect_language,
    language_for_country,
    localise_query,
    protected_tokens,
)


def test_country_to_language():
    assert language_for_country("SK") == "sk"
    assert language_for_country("CZ") == "cs"
    assert language_for_country("DE") == "de"
    assert language_for_country("AT") == "de"
    assert language_for_country("EU") == "en"
    assert language_for_country("") == "en"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Predám horský bicykel, dobrý stav", "sk"),
        ("Prodám horské kolo, dobrý stav", "cs"),
        ("Verkaufe Fahrrad, guter Zustand", "de"),
        ("Selling a mountain bike, good condition", "en"),
        ("horský bicykel fahrrad", "sk"),
    ],
)
def test_detect_language(text, language):
    assert detect_language(text) == language


def test_protected_tokens_keep_models():
    assert protected_tokens("iPhone 13 128GB unter 300") == ["iPhone", "13", "128GB", "300"]


@pytest.mark.asyncio
async def test_translation_is_rejected_when_a_model_disappears():
    class BadLLM:
        async def _chat(self, system, user, **kwargs):
            return "Fahrrad"

    result = await localise_query(BadLLM(), "Kellys Madman 10", "de", {})
    assert result == "Kellys Madman 10"


@pytest.mark.asyncio
async def test_translation_is_used_when_models_survive():
    class GoodLLM:
        async def _chat(self, system, user, **kwargs):
            return "Kellys Madman 10 Mountainbike"

    result = await localise_query(GoodLLM(), "Kellys Madman 10 bicykel", "de", {})
    assert result == "Kellys Madman 10 Mountainbike"


@pytest.mark.asyncio
async def test_no_llm_keeps_the_original_query():
    result = await localise_query(None, "horský bicykel", "de", {})
    assert result == "horský bicykel"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_language.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.searcher.query_language'`

- [ ] **Step 3: Implement**

`query_language.py` holds the country map, a small **marker-word** table per language
(sk, cs, de, en) and the **exclusive** diacritic sets (`ľ ĺ ŕ ô` for sk; `ě ř ů` for cs;
`ä ö ü ß` for de). Shared letters (`á é í ý č š ž ť ď ň`) are deliberately in no set:
they occur in both Slovak and Czech, so counting them for one language would bias the
result. Marker words are the function words plus a few frequent listing words that
actually distinguish the languages: `predam`, `horsky`, `bicykel`, `pouzity` for sk;
`prodam`, `horske`, `bicykl`, `pouzite` for cs; `verkaufe`, `fahrrad`, `gebraucht`,
`zustand` for de; `selling`, `bike`, `used`, `condition` for en. A plain stopword table is
not enough: `Prodám horské kolo, dobrý stav` contains no function word, and its `á é ý`
are shared with Slovak, so diacritics alone would pick `sk`.

`detect_language` reads **diacritics from the raw text** and **marker words from
`fold(text)`**, because folding removes the diacritics it needs to count. A marker hit is
worth 3 points and a unique diacritic 1 point, so words decide and diacritics only break
ties. Return the winner or `en` on a tie.

`localise_query` returns the original when `llm` is None or when the detected language
already equals `target`. Otherwise it calls `llm._chat` with a JSON-free prompt: "Translate
this marketplace search query to <target>. Keep brand and model strings exactly as they
are. Reply with the query only." Strip whitespace and wrapping quotes from the reply. The
result is accepted only when every protected token appears in it and the reply is
non-empty. Cache by `(query, target)`.

`playwright_searcher._execute_round`: inside the per-site loop, resolve the market first,
then localise:

```python
country, currency = self._site_market(site)
site_query = await localise_query(
    self.llm, query, language_for_country(country), self._query_language_cache
)
deals = await adapter.search(page, site_query, ...)
```

Use the resolved country, not `site.country`: a config entry may leave `country` empty
and rely on the registry, and `language_for_country("")` would wrongly return `en`.

Initialise `self._query_language_cache: dict[tuple[str, str], str] = {}` in `__init__`.

`query_expansion._fallback`: replace the hardcoded English suffix tuple with
`SUFFIXES = {"en": (...), "sk": (...), "cs": (...), "de": (...)}` selected by
`detect_language(prompt)`. These are search terms, not matching keys, so keep their real
spelling: `used/new/refurbished/under 350/bargain`,
`použité/nové/repasované/do 350/výhodná kúpa`,
`použité/nové/repasované/do 350/výhodná koupě`,
`gebraucht/neu/generalüberholt/unter 350/Schnäppchen`. `detect_language` returns `en`
when unsure, so the English tuple is the fallback; there is no separate "unknown"
branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_query_language.py -v`
Expected: PASS — no failures

- [ ] **Step 5: Commit**

```bash
git add src/searcher/query_language.py src/searcher/playwright_searcher.py src/agents/research/query_expansion.py tests/test_query_language.py
git commit -m "feat(search): send each site a query in its own language"
```

---

### Task 16: Final verification

**Files:**
- Modify: `CHANGELOG.md` — verification line only
- Test: whole suite, then live searches

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass, 0 failures. Record the exact counts.

- [ ] **Step 2: Run scoped ruff**

Run: `python -m ruff check src/text src/output src/searcher/filters.py src/searcher/query_language.py src/searcher/adapters src/searcher/playwright_searcher.py src/cli/app.py src/config/models.py tests`
Expected: `All checks passed!`

- [ ] **Step 3: Live search in Slovak (bike)**

Temporarily disable every site except `bazos` in `config.yaml` (git-ignored), then run:

```powershell
$env:ADS_LOCAL_POLICY = "never"
python -m src.cli run --prompt "horský bicykel pre muža 180 cm" --condition used --category hobby --country SK --max-sites 1
```

Confirm in the JSON: `"sites": ["bazos"]`, `"domain": "bike"`, `spec_coverage` present,
no `Connectivity` row, and at least one deal with a non-empty `description`.

- [ ] **Step 4: Live search in Czech (phone)**

In `config.yaml`, disable `bazos` and enable `bazos_cz` (it already points at
`https://www.bazos.cz` and reuses the `bazos` adapter), then run:

```powershell
python -m src.cli run --prompt "použitý iPhone 13 128 GB" --condition used --category electronics --country CZ --max-sites 1
```

Confirm `"sites": ["bazos_cz"]`, `"domain": "phone"`, `storage` and `battery_health`
keys, no bike keys, and that `price_eur` is not in `specs`.

- [ ] **Step 5: Live search in German (phone)**

Enable `mobile_de` in `config.yaml` and run a German phone prompt. Use the profile only
if it is runtime-ready: `_filter_sites` skips a site whose adapter class is unknown and
whose profile is not `is_runtime_ready`. Confirm the same phone assertions as Step 4.
**If the profile is not runtime-ready, stop and record the limitation** in
`CHANGELOG.md` ("German search not verified: no runtime-ready German adapter"); do not
claim German search works. German *understanding* is covered by the Task 3 fixtures.

- [ ] **Step 6: Confirm the four defects are gone**

In the Czech phone report from Step 4:
- no `"storage not stated"` con for a listing whose title states the required storage;
- no two deals with the same folded title;
- `duplicates_collapsed` is present in the JSON;
- no con claims a price is above or below market.

Check the same four points in the Slovak bike report where they apply (dedup, the
`duplicates_collapsed` field, and the price-claim rule).

- [ ] **Step 7: Update CHANGELOG**

Record the suite counts, the three search results (SK, CZ, and DE or the stated
limitation), and the four confirmations from Step 6.

- [ ] **Step 8: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record multilingual verification"
```
