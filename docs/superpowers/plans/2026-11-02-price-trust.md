# Price Trust and Effective Price Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Represent shipping, bundles, price ranges and gated promotions as a typed price quote, and rank/filter/report by a comparable effective price without breaking existing deals.

**Architecture:** A new `src/searcher/pricing.py` owns the `PriceQuote` model, deterministic signal extraction, trust calculation and effective-price math. Adapters attach quotes, an optional LLM fallback fills ambiguous cards, and the filter/processor/storage layers read `comparable_price(deal)` instead of raw `price_eur`.

**Tech Stack:** Python 3.11+, dataclasses, `StrEnum`, existing Playwright adapters, existing `LLMClient.chat_json`, sqlite-utils migrations, pytest.

**Spec:** `docs/specs/2026-11-02-price-trust-design.md`

## Global Constraints

- `Deal.price_eur` keeps its current meaning (listed unit price, or listed bundle total).
- A deal without `price_quote` must behave exactly as before: `comparable_price_eur == price_eur`.
- Unknown shipping is `None`, never `0.0`.
- LLM evidence must be a literal substring of the card text; otherwise reject that response.
- No new third-party dependency.
- Full suite must stay green; baseline is 538 passed, 11 skipped.
- Currency conversion keeps using `src.searcher.currency`.

## Review Focus

- A card says "free shipping" and the parser treats the missing amount as unknown, adding a false shipping warning.
- A card says "shipping from €2" and the code uses the maximum instead of the minimum.
- A bundle total is divided by the wrong quantity, or shipping is added once instead of per unit.
- An account-gated price wins the ranking without a visible warning.
- A legacy database row without `effective_price_eur` crashes the storage or report path.

---

### Task 1: Pricing types, trust and effective price

**Files:**
- Create: `src/searcher/pricing.py`
- Create: `tests/test_pricing.py`
- Modify: `src/searcher/adapters/base.py` (add optional `price_quote` field and property)

**Interfaces:**
- Produces: `PriceKind`, `ShippingQuote`, `BundleTerms`, `PriceQuote`, `comparable_price(deal) -> float`, `build_price_quote(...) -> PriceQuote`.
- Produces: `Deal.price_quote: PriceQuote | None = None` and `Deal.comparable_price_eur: float`.

- [ ] **Step 1: Write the failing tests**

```python
from src.searcher.adapters.base import Deal
from src.searcher.pricing import (
    BundleTerms, PriceKind, ShippingQuote, build_price_quote, comparable_price,
)


def test_regular_price_adds_known_shipping():
    quote = build_price_quote(100.0, shipping=ShippingQuote(cost_eur=5.0))
    assert quote.effective_price_eur == 105.0
    assert quote.trust == 1.0


def test_free_shipping_is_zero_not_unknown():
    quote = build_price_quote(100.0, shipping=ShippingQuote(is_free=True))
    assert quote.effective_price_eur == 100.0
    assert quote.trust == 1.0


def test_unknown_shipping_is_not_zero_and_lowers_trust():
    quote = build_price_quote(100.0, shipping=ShippingQuote())
    assert quote.effective_price_eur == 100.0
    assert quote.trust == 0.90


def test_bundle_divides_total_and_shipping_by_min_quantity():
    quote = build_price_quote(
        30.0,
        kind=PriceKind.BUNDLE,
        shipping=ShippingQuote(cost_eur=6.0),
        bundle=BundleTerms(min_quantity=3),
    )
    assert quote.effective_price_eur == 12.0
    assert quote.trust == 0.85


def test_range_uses_lowest_price_and_exposes_maximum():
    quote = build_price_quote(12.99, kind=PriceKind.RANGE, price_from=True, price_max_eur=18.99)
    assert quote.effective_price_eur == 12.99
    assert quote.price_max_eur == 18.99
    assert quote.trust == 0.85


def test_account_gated_price_lowers_trust():
    quote = build_price_quote(9.99, kind=PriceKind.ACCOUNT_GATED)
    assert quote.trust == 0.65
    assert "account-gated" in " ".join(quote.warnings).lower()


def test_flags_multiply_and_trust_has_a_floor():
    quote = build_price_quote(
        9.99,
        kind=PriceKind.ACCOUNT_GATED,
        shipping=ShippingQuote(),
        bundle=BundleTerms(min_quantity=3),
        price_from=True,
    )
    assert quote.trust == 0.4


def test_comparable_price_falls_back_to_price_eur_without_quote():
    deal = Deal(url="https://x/1", title="X", price_eur=42.0)
    assert deal.comparable_price_eur == 42.0
    assert comparable_price(deal) == 42.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pricing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.searcher.pricing'`.

- [ ] **Step 3: Implement the pricing module and the `Deal` field**

Create `src/searcher/pricing.py` with the dataclasses and enums from the spec. `build_price_quote` signature:

```python
def build_price_quote(
    listed_price_eur: float,
    *,
    kind: PriceKind = PriceKind.UNKNOWN,
    shipping: ShippingQuote | None = None,
    bundle: BundleTerms | None = None,
    price_from: bool = False,
    price_max_eur: float | None = None,
    regular_price_eur: float | None = None,
    evidence: tuple[str, ...] = (),
    source: str = "regex",
    confidence: float = 1.0,
    warnings: tuple[str, ...] = (),
) -> PriceQuote:
```

Rules:
- `quantity = max(1, bundle.min_quantity)`.
- `unit = listed_price_eur / quantity`.
- `shipping_unit = 0.0` when `shipping.is_free` is true; `shipping.cost_eur / quantity` when known; `0.0` when unknown (but trust drops).
- `effective = unit + shipping_unit`.
- Trust starts at `1.0` and multiplies: unknown shipping `0.90`, public promo `0.90`, range/price_from `0.85`, bundle `0.85`, coupon `0.80`, account-gated `0.65`; floor `0.4`.
- Add human-readable warnings for every applied penalty. The account-gated
  warning must contain the words `new user`; the range warning must contain
  `from`; the bundle warning must contain `min.` and the quantity; the unknown
  shipping warning must contain `shipping unknown`.
- `comparable_price(deal)` returns `deal.price_quote.effective_price_eur` when it is `> 0`, else `deal.price_eur`.

Add to `Deal` in `src/searcher/adapters/base.py`:

```python
price_quote: "PriceQuote | None" = None

@property
def comparable_price_eur(self) -> float:
    ...
```

Use a `TYPE_CHECKING` import to avoid a runtime cycle.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pricing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/pricing.py tests/test_pricing.py src/searcher/adapters/base.py
git commit -m "feat(pricing): add PriceQuote model and effective price math"
```

---

### Task 2: Deterministic price signals

**Files:**
- Modify: `src/searcher/pricing.py`
- Modify: `tests/test_pricing.py`

**Interfaces:**
- Produces: `PriceSignals` dataclass and `extract_price_signals(text: str, listed_price_eur: float, currency: str = "EUR") -> PriceSignals`.
- `PriceSignals` fields: `kind`, `shipping`, `bundle`, `price_from`, `price_max_eur`, `regular_price_eur`, `confidence`, `evidence`, `warnings`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from src.searcher.pricing import PriceKind, extract_price_signals


@pytest.mark.parametrize("text", [
    "New user price €9.99",
    "Welcome deal - first order",
    "Cena pre nového zákazníka 9,99 €",
    "Erste Bestellung 9,99 €",
])
def test_detects_account_gated_labels(text):
    signals = extract_price_signals(text, 9.99)
    assert signals.kind == PriceKind.ACCOUNT_GATED


def test_detects_coupon_label():
    signals = extract_price_signals("€20.00 with code SAVE10", 20.0)
    assert signals.kind == PriceKind.COUPON


def test_detects_bundle_minimum_quantity():
    signals = extract_price_signals("Balenie 3 ks za 30 €", 30.0)
    assert signals.bundle.min_quantity == 3


def test_detects_free_shipping():
    signals = extract_price_signals("Doprava zdarma", 10.0)
    assert signals.shipping.is_free is True
    assert signals.shipping.cost_eur == 0.0


def test_detects_shipping_amount_in_eur():
    signals = extract_price_signals("Doprava 4,99 €", 10.0)
    assert signals.shipping.cost_eur == 4.99


def test_detects_shipping_range_and_uses_minimum():
    signals = extract_price_signals("Doprava od 2 €", 10.0)
    assert signals.shipping.min_eur == 2.0
    assert signals.shipping.cost_eur == 2.0


def test_detects_price_from_and_range():
    signals = extract_price_signals("Od 12,99 € do 18,99 €", 12.99)
    assert signals.price_from is True
    assert signals.price_max_eur == 18.99


def test_plain_card_has_no_signals():
    signals = extract_price_signals("Notebook Lenovo 1299 €", 1299.0)
    assert signals.kind == PriceKind.REGULAR
    assert signals.confidence == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pricing.py -q`
Expected: FAIL with `ImportError: cannot import name 'extract_price_signals'`.

- [ ] **Step 3: Implement `PriceSignals` and `extract_price_signals`**

Use `src.searcher.currency.parse_price_detail` for amounts. Patterns must be case-insensitive and cover EN/SK/DE/CZ. Keep the evidence as the matched substring. Set `confidence=1.0` for an explicit label, `0.5` for a weak hint, `0.0` when nothing matched. Never infer a shipping amount from a product price.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pricing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/pricing.py tests/test_pricing.py
git commit -m "feat(pricing): extract deterministic price signals"
```

---

### Task 3: LLM fallback classifier

**Files:**
- Modify: `src/llm/client.py`
- Modify: `src/searcher/pricing.py`
- Create: `tests/test_price_llm.py`

**Interfaces:**
- Produces: `LLMClient.classify_price_quotes(items: list[dict]) -> dict[str, dict]`.
- Produces: `validate_price_classification(payload: dict, card_text: str) -> dict | None` in `pricing.py`.
- Item shape: `{"id": str, "text": str, "listed_price_eur": float, "currency": str}`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from src.llm.client import LLMClient
from src.searcher.pricing import validate_price_classification


def _client():
    cfg = type("C", (), {"llm": type("L", (), {
        "local": [], "api_fallback": [], "openrouter": None,
        "gemini": None, "mistral": None,
    })()})()
    return LLMClient(cfg)


@pytest.mark.asyncio
async def test_classify_price_quotes_parses_batch(monkeypatch):
    client = _client()

    async def fake_chat(system, user, max_tokens=100):
        return '{"quotes": [{"id": "L1", "kind": "account_gated", ' \
               '"shipping_cost_eur": 4.99, "bundle_min_quantity": 1, ' \
               '"warnings": ["new user"], "confidence": 0.9, ' \
               '"evidence": ["New user price"]}]}'

    monkeypatch.setattr(client, "_chat", fake_chat)
    result = await client.classify_price_quotes([
        {"id": "L1", "text": "New user price 9.99", "listed_price_eur": 9.99, "currency": "EUR"}
    ])
    assert result["L1"]["kind"] == "account_gated"
    assert result["L1"]["shipping_cost_eur"] == 4.99


def test_hallucinated_evidence_is_rejected():
    payload = {
        "kind": "account_gated",
        "shipping_cost_eur": 4.99,
        "evidence": ["not in the card"],
    }
    assert validate_price_classification(payload, "New user price 9.99") is None


def test_evidence_substring_is_accepted():
    payload = {
        "kind": "account_gated",
        "shipping_cost_eur": None,
        "evidence": ["New user price"],
    }
    result = validate_price_classification(payload, "New user price 9.99")
    assert result is not None
    assert result["kind"] == "account_gated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_price_llm.py -q`
Expected: FAIL with missing attribute / import error.

- [ ] **Step 3: Implement the client method and validator**

`classify_price_quotes` system prompt: classify each card, return ONLY
`{"quotes": [...]}`, use `null` for unknown numbers, never invent values, and
quote evidence from the card. Use `chat_json`; return `{}` on any failure.

`validate_price_classification`:
- require a dict;
- accept only known `kind` values;
- require every `evidence` entry to be a substring of `card_text`;
- clamp numbers to `0..1_000_000`, `bundle_min_quantity` to `1..1000`;
- return `None` if any rule fails.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_price_llm.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/client.py src/searcher/pricing.py tests/test_price_llm.py
git commit -m "feat(pricing): add validated LLM price classification"
```

---

### Task 4: Attach quotes in adapters

**Files:**
- Modify: `src/searcher/adapters/profile_adapter.py`
- Modify: `src/searcher/adapters/alza.py`
- Modify: `src/searcher/adapters/bazos.py`
- Modify: `tests/test_profile_adapter.py`
- Modify: `tests/test_adapters.py`

**Interfaces:**
- Consumes: `extract_price_signals`, `build_price_quote`.
- Produces: every adapter `Deal` may carry `price_quote`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_profile_adapter.py`:

```python
@pytest.mark.asyncio
async def test_profile_adapter_attaches_price_quote():
    element = FakeElement(
        mapping={
            ".title": FakeChild("New user deal"),
            ".price": FakeChild("9,99 €"),
            "a": FakeChild(href="/p/1"),
        },
        text="New user price 9,99 € free shipping",
    )
    adapter = ProfileAdapter(profile=_profile())
    deal = await adapter.extract_deal(None, element)
    assert deal is not None
    assert deal.price_quote is not None
    assert deal.price_quote.kind == "account_gated"
    assert deal.price_quote.shipping.is_free is True
```

In `tests/test_adapters.py`, add a Bazos shipping test using the existing fake
element pattern: card text with "Doprava 4,99 €" produces
`deal.price_quote.shipping.cost_eur == 4.99`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile_adapter.py tests/test_adapters.py -q`
Expected: FAIL because `price_quote` is `None`.

- [ ] **Step 3: Implement adapter attachment**

In `ProfileAdapter.extract_deal`:
- capture the full card text once (`full_text`);
- store `metadata["card_text"] = full_text[:2000]`;
- call `extract_price_signals(full_text, price_eur, self.currency)`;
- build a quote with `build_price_quote(..., confidence=signals.confidence,
  evidence=signals.evidence, source="regex")` and attach it.

In `AlzaAdapter` and `BazosAdapter`, build a quote from the card text they already
read. If they cannot read shipping, leave `shipping=ShippingQuote()` so trust
drops; do not invent `0.0`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_profile_adapter.py tests/test_adapters.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/adapters/profile_adapter.py src/searcher/adapters/alza.py src/searcher/adapters/bazos.py tests/test_profile_adapter.py tests/test_adapters.py
git commit -m "feat(pricing): attach price quotes in adapters"
```

---

### Task 5: LLM fallback pass in the searcher

**Files:**
- Modify: `src/searcher/playwright_searcher.py`
- Create: `tests/test_price_enrichment.py`

**Interfaces:**
- Produces: `PlaywrightSearcher._enrich_price_quotes(deals: list[Deal]) -> None` (mutates deals in place).
- Consumes: `LLMClient.classify_price_quotes`, `validate_price_classification`, `build_price_quote`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from src.searcher.adapters.base import Deal
from src.searcher.pricing import PriceKind, ShippingQuote, build_price_quote


@pytest.mark.asyncio
async def test_ambiguous_quote_is_replaced_by_validated_llm_result(monkeypatch):
    deal = Deal(
        url="https://x/1", title="New user price", price_eur=9.99,
        metadata={"card_text": "New user price 9.99"},
        price_quote=build_price_quote(
            9.99, kind=PriceKind.REGULAR,
            shipping=ShippingQuote(), source="regex",
        ),
    )

    class FakeLLM:
        async def classify_price_quotes(self, items):
            return {"L1": {"kind": "account_gated", "shipping_cost_eur": None,
                           "evidence": ["New user price"], "confidence": 0.9}}

    searcher = object.__new__(PlaywrightSearcher)
    searcher.llm = FakeLLM()
    await searcher._enrich_price_quotes([deal])
    assert deal.price_quote.kind == PriceKind.ACCOUNT_GATED
    assert deal.price_quote.source == "llm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_price_enrichment.py -q`
Expected: FAIL with `AttributeError: _enrich_price_quotes`.

- [ ] **Step 3: Implement the enrichment pass**

Only quotes with `source == "regex"` and `quote.confidence < 0.7` are batched, at
most 10 per call. Merge deterministic fields with the validated LLM result; keep
`source="regex"` when the model contributed nothing. Never let the model lower
trust directly; recompute it with `build_price_quote`.

Call `_enrich_price_quotes(deals)` in `search()` after all sites return and before
deduplication/analysis.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_price_enrichment.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/playwright_searcher.py tests/test_price_enrichment.py
git commit -m "feat(pricing): add LLM fallback for ambiguous price quotes"
```

---

### Task 6: Filter by effective price

**Files:**
- Modify: `src/searcher/filter_engine.py`
- Modify: `tests/test_filter_engine.py`

**Interfaces:**
- Consumes: `comparable_price`.
- Produces: `FilterEngine._price` returns the effective price.

- [ ] **Step 1: Write the failing test**

```python
def test_price_filter_uses_shipping_inclusive_price():
    deal = Deal(
        url="https://x/1", title="X", price_eur=95.0,
        price_quote=build_price_quote(95.0, shipping=ShippingQuote(cost_eur=10.0)),
    )
    filters = SearchFilters(max_price=100.0)
    assert FilterEngine._matches(deal, filters) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_filter_engine.py -q`
Expected: FAIL because the raw `95.0` passes.

- [ ] **Step 3: Implement the change**

Replace `float(deal.price_eur or 0)` in `FilterEngine._price` with
`comparable_price(deal)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_filter_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/filter_engine.py tests/test_filter_engine.py
git commit -m "feat(pricing): filter deals by effective price"
```

---

### Task 7: Rank by effective price

**Files:**
- Modify: `src/output/processor.py`
- Modify: `tests/test_domains.py`
- Modify: `tests/test_processor_details.py`

**Interfaces:**
- Consumes: `comparable_price`.
- Produces: median, outlier window, cheapest, best value, Price score and LLM
  winner summary use the effective price.

- [ ] **Step 1: Write the failing tests**

```python
def test_price_score_uses_effective_price():
    deal = Deal(
        url="https://x/1", title="X", price_eur=100.0,
        price_quote=build_price_quote(
            100.0, kind=PriceKind.ACCOUNT_GATED, shipping=ShippingQuote(cost_eur=20.0)
        ),
    )
    analysis = DealAnalysis(deal=deal, domain="generic", score=0)
    processor = ResultProcessor(load_config())
    breakdown = processor._score_breakdown(analysis, median=100.0, analyses=[analysis])
    assert breakdown["Price"] < 95
```

Add a test that the cheapest pick is the one with the lower effective price even
when its listed price is higher.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_domains.py tests/test_processor_details.py -q`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement the changes**

Replace `deal.price_eur` with `comparable_price(deal)` in:
- the outlier window in `save_results`;
- the median and Price score in `_score_breakdown`;
- `cheapest`, `pp` and the LLM winner summary in `_to_markdown` /
  `_llm_pick_winners`.

The Price row becomes `round(base_price_score * trust)` where `trust` comes from
`deal.price_quote.trust` (default `1.0`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_domains.py tests/test_processor_details.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/output/processor.py tests/test_domains.py tests/test_processor_details.py
git commit -m "feat(pricing): rank deals by effective price and price trust"
```

---

### Task 8: Persist effective price and kind

**Files:**
- Modify: `src/storage/schema.py`
- Modify: `src/storage/manager.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_storage_persistence.py`

**Interfaces:**
- Produces: `deals.effective_price_eur`, `deals.price_kind`,
  `price_history.effective_price_eur`, `price_history.price_kind`.
- Produces: `StoredDeal.effective_price_eur`, `StoredDeal.price_kind`.

- [ ] **Step 1: Write the failing tests**

```python
def test_schema_has_effective_price_columns(tmp_path):
    db = get_db(str(tmp_path / "x.db"))
    deal_cols = {r[1] for r in db.execute("PRAGMA table_info(deals)")}
    hist_cols = {r[1] for r in db.execute("PRAGMA table_info(price_history)")}
    assert {"effective_price_eur", "price_kind"} <= deal_cols
    assert {"effective_price_eur", "price_kind"} <= hist_cols


def test_save_deal_persists_effective_price(tmp_path):
    storage = StorageManager(str(tmp_path / "x.db"))
    deal = Deal(
        url="https://x/1", title="X", price_eur=100.0,
        price_quote=build_price_quote(100.0, shipping=ShippingQuote(cost_eur=5.0)),
    )
    storage.save_deal(deal, run_id="run1")
    saved = storage.get_deal("https://x/1")
    assert saved.effective_price_eur == 105.0
    assert saved.price_kind == "regular"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_migrations.py tests/test_storage_persistence.py -q`
Expected: FAIL with missing columns/attributes.

- [ ] **Step 3: Implement the migration and persistence**

Bump `SCHEMA_VERSION` to `4`; add a `_migration_004_price_trust` that adds the
columns to both tables. Add the columns to `DEALS_COLUMNS` and use the same
idempotent `ALTER TABLE` pattern for `price_history`.

`save_deal` writes `comparable_price(deal)` and
`deal.price_quote.kind.value` (or `"unknown"`). `record_price_sighting` writes
the same values. `_row_to_stored_deal` falls back to `price_eur` / `"unknown"`
for old rows.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_migrations.py tests/test_storage_persistence.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/storage/schema.py src/storage/manager.py tests/test_migrations.py tests/test_storage_persistence.py
git commit -m "feat(storage): persist effective price and price kind"
```

---

### Task 9: Report price breakdown and warnings

**Files:**
- Modify: `src/output/processor.py`
- Modify: `tests/test_processor_details.py`

**Interfaces:**
- Produces: JSON/CSV fields `effective_price_eur`, `price_kind`, `price_trust`,
  `price_warnings`, `price_breakdown`.
- Produces: summary markers and a deal-card price breakdown.

- [ ] **Step 1: Write the failing tests**

```python
def test_report_shows_shipping_breakdown():
    deal = Deal(
        url="https://x/1", title="X", price_eur=100.0,
        price_quote=build_price_quote(100.0, shipping=ShippingQuote(cost_eur=5.0)),
    )
    analysis = DealAnalysis(deal=deal, domain="generic", score=80)
    markdown = ResultProcessor(load_config())._to_markdown(
        "x", [analysis], [], "2026-11-02", set()
    )
    assert "Item 100.00" in markdown
    assert "shipping 5.00" in markdown
    assert "105.00" in markdown


def test_report_marks_account_gated_price():
    deal = Deal(
        url="https://x/1", title="X", price_eur=9.99,
        price_quote=build_price_quote(9.99, kind=PriceKind.ACCOUNT_GATED),
    )
    analysis = DealAnalysis(deal=deal, domain="generic", score=80)
    markdown = ResultProcessor(load_config())._to_markdown(
        "x", [analysis], [], "2026-11-02", set()
    )
    assert "new user" in markdown.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_processor_details.py -q`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement the report changes**

- Add the new keys to `_deal_to_dict`.
- Add the new columns to CSV and XLSX.
- In `_to_markdown`, use `comparable_price(deal)` for the summary price and add a
  marker; in `_deal_card`, print the breakdown from the quote.
- In `_filtered_lines`, add a `Reason` column and a link column. Use
  `analysis.filter_reason` when present, otherwise the existing form-factor text.
- Add `filter_reason: str = ""` to `DealAnalysis` and set it when the outlier
  filter drops a deal.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_processor_details.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/output/processor.py tests/test_processor_details.py
git commit -m "feat(report): show effective price breakdown and warnings"
```

---

### Task 10: Full verification

**Files:**
- Modify: `README.md` (short price-trust note)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass; the previous baseline was 538 passed, 11 skipped.

- [ ] **Step 2: Run a live search and inspect the report**

Run: `python -m src.cli run --prompt "mini pc 32gb ram" --debug`
Expected: a report where at least one deal shows either a shipping breakdown, a
bundle quantity, a range marker or an explicit "shipping unknown" warning. If no
card carries a price signal, verify the report still renders and the quote is
`regular` with trust `1.0`.

- [ ] **Step 3: Update docs**

Add one paragraph to `README.md` and an entry to `CHANGELOG.md` describing the
effective price, bundle unit price, account-gated warning and unknown shipping.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document price trust and effective price"
```
