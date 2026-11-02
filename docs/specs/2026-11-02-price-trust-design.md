# Price Trust and Effective Price — Design

Date: 2026-11-02
Status: approved in session
Scope: generic price model, independent of any single marketplace

## 1. Problem

The searcher currently treats `Deal.price_eur` as the whole truth. That number is
whatever the card parser found first, so three different real-world situations
collapse into the same value:

* a marketplace shows a **newcomer / first-order / member price** that most users
  cannot get;
* a listing shows **"from X"** or a **variant range**, not a concrete price;
* a listing is a **bundle** whose unit price is excellent only because the buyer
  must take three or more pieces;
* **shipping** is stored separately (or not at all), so a cheap item with expensive
  shipping outranks a slightly dearer item with free shipping.

The report then presents these numbers as comparable. They are not.

## 2. Verified facts (current state)

* `Deal` (`src/searcher/adapters/base.py`) has `price_eur`, `original_price`,
  `original_currency` and a free-form `metadata` dict. There is no price-kind or
  shipping field on the deal itself.
* `shipping_cost_eur` exists in `src/storage/schema.py` and `StoredDeal`, but
  adapters mostly put shipping text into `metadata["shipping"]`; the value does
  not participate in ranking.
* `FilterEngine._matches` compares `deal.price_eur` with `min_price` / `max_price`
  (`src/searcher/filter_engine.py:191-205`).
* `ResultProcessor` uses `deal.price_eur` for the median, the cheapest pick, the
  best price/performance pick, the Price score row and the report tables
  (`src/output/processor.py:1104`, `1328-1330`, `1385`).
* `ProfileAdapter.extract_deal` parses a single price from the card text and
  discards the rest of the card (`src/searcher/adapters/profile_adapter.py:113`).
* The report has a `Filtered out` table but no reason column and no link.
* AliExpress has no adapter, no registry entry in `ADAPTER_REGISTRY`, and its
  profile is `draft`. This design deliberately does not implement that adapter.

## 3. Goals

* G1 — Represent the full price story in a typed `PriceQuote`: listed price,
  shipping, bundle terms, price kind, range, trust and evidence.
* G2 — Rank and filter by a comparable **effective price** that includes known
  shipping and normalises bundles to a per-unit price.
* G3 — Never treat unknown shipping as zero. Unknown stays unknown and lowers
  trust.
* G4 — Include account-gated / coupon prices in the ranking, but mark them and
  lower their trust so they cannot win on price alone.
* G5 — Use the lowest value for "from X" and ranges, mark the quote as a range and
  lower trust.
* G6 — Keep every existing `Deal.price_eur` consumer working unchanged when no
  quote is present.
* G7 — Detect the price kind with deterministic patterns first and an LLM fallback
  only for ambiguous cards. The LLM must return evidence that is a literal
  substring of the card text.

## 4. Non-goals

* Implementing the AliExpress adapter or any new marketplace adapter.
* Changing the site-selection algorithm, the number of sites or the site catalogue.
* LLM extraction of product specs (GPU, CPU, camera, battery). That is a separate
  workstream.
* External comparison sources and the full report appendix. Only the price-related
  parts of the report change here.
* Currency conversion changes. The existing `to_eur` path stays.

## 5. Data model

New module: `src/searcher/pricing.py`.

```python
class PriceKind(StrEnum):
    REGULAR = "regular"
    PROMO = "promo"                 # public sale, no account required
    COUPON = "coupon"               # requires a code or auto-applied coupon
    ACCOUNT_GATED = "account_gated" # newcomer / first order / member / app-only
    BUNDLE = "bundle"               # requires a minimum quantity
    RANGE = "range"                 # "from X" or a variant range
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class ShippingQuote:
    cost_eur: float | None = None   # None = unknown, never silently 0
    min_eur: float | None = None
    max_eur: float | None = None
    is_free: bool | None = None
    note: str = ""

@dataclass(frozen=True)
class BundleTerms:
    min_quantity: int = 1
    total_price_eur: float | None = None
    note: str = ""

@dataclass(frozen=True)
class PriceQuote:
    listed_price_eur: float
    effective_price_eur: float
    kind: PriceKind = PriceKind.UNKNOWN
    shipping: ShippingQuote = field(default_factory=ShippingQuote)
    bundle: BundleTerms = field(default_factory=BundleTerms)
    price_from: bool = False
    price_max_eur: float | None = None
    regular_price_eur: float | None = None
    trust: float = 1.0
    confidence: float = 1.0         # how sure the classifier is about the kind
    evidence: tuple[str, ...] = ()
    source: str = "regex"           # regex | llm | default
    warnings: tuple[str, ...] = ()
```

`Deal` gains one optional field:

```python
price_quote: PriceQuote | None = None
```

and one property:

```python
@property
def comparable_price_eur(self) -> float:
    if self.price_quote is not None and self.price_quote.effective_price_eur > 0:
        return self.price_quote.effective_price_eur
    return self.price_eur
```

`price_eur` keeps its current meaning: the listed price for one unit, or the
listed total for a bundle. A module-level helper `comparable_price(deal)` exists
for callers that receive plain objects (tests, storage rows).

## 6. Detection pipeline

### 6.1 Deterministic signals

`extract_price_signals(text, listed_price_eur, currency) -> PriceSignals` scans the
whole card text for:

| signal | examples |
|---|---|
| newcomer / account | `new user`, `welcome deal`, `first order`, `first purchase`, `member price`, `app only`, `nový zákazník`, `erste Bestellung` |
| coupon | `coupon`, `with code`, `auto-applied`, `kupón`, `Gutschein` |
| bundle | `min. 3 pcs`, `minimum order 3`, `buy 3`, `3 for €X`, `balenie 3 ks` |
| shipping free | `free shipping`, `doprava zdarma`, `kostenloser Versand` |
| shipping amount | `shipping €4.99`, `doprava 4,99 €`, `Versand 4,99 €` |
| shipping range | `shipping from €2`, `doprava od 2 €` |
| price from / range | `from €12.99`, `od 12,99 €`, `12,99–18,99 €` |
| original price | crossed-out/list price when the card exposes it |

Each signal carries the literal evidence snippet. `confidence` is 1.0 when an
explicit label matched, 0.5 when only a weak hint matched, 0.0 when nothing
matched.

### 6.2 LLM fallback

Only cards with `confidence < 0.7`, or with ambiguous keywords, go to the model.
`LLMClient.classify_price_quotes(items)` accepts a batch of at most 10 cards and
returns a JSON list keyed by the caller's id.

The response schema is strict:

```json
{
  "id": "L3",
  "kind": "regular|promo|coupon|account_gated|bundle|range|unknown",
  "shipping_cost_eur": 4.99,
  "shipping_is_free": false,
  "shipping_min_eur": null,
  "shipping_max_eur": null,
  "bundle_min_quantity": 1,
  "price_from": false,
  "price_max_eur": null,
  "regular_price_eur": null,
  "warnings": ["..."],
  "confidence": 0.86,
  "evidence": ["New user price"]
}
```

Validation rules:

* every numeric field is finite and within `0..1_000_000`;
* `bundle_min_quantity` is an integer in `1..1000`;
* every `evidence` entry is a literal substring of the card text, otherwise the
  whole response for that card is rejected;
* unknown enum values fall back to `unknown`;
* malformed JSON or an unavailable model is not an error: the deterministic
  result is used with `source="regex"`.

### 6.3 Merge

Deterministic signals win for fields they matched. The LLM fills the gaps and may
add warnings. `trust` is computed from the merged flags, never taken from the
model. `source` is `llm` only when the model contributed at least one field.

### 6.4 Call sites

* `ProfileAdapter.extract_deal` stores the full card text in
  `metadata["card_text"]` (bounded, e.g. 2000 chars) and attaches the
  deterministic quote.
* `PlaywrightSearcher` runs one LLM fallback pass over the ambiguous deals after
  all sites have returned, before deduplication and analysis. One batch call per
  10 cards.
* Alza/Bazos adapters attach a quote from their existing parsed fields and
  `metadata["shipping"]`. Missing shipping stays `None`.
* Any adapter that cannot supply a quote leaves `price_quote=None`; the deal
  behaves exactly as today.

## 7. Effective price

```text
quantity       = max(1, bundle.min_quantity)
unit_price     = listed_total / quantity
shipping_unit  = shipping.cost_eur / quantity        # only when cost is known
effective      = unit_price + shipping_unit
```

* Free shipping (`is_free=True`) is a known cost of `0.0`.
* Unknown shipping: `effective = unit_price`; `trust` is reduced and a warning is
  added.
* Shipping range: use `shipping.min_eur` for `effective`, expose the range and
  reduce trust.
* Price range: use the lowest value for `effective`, set `price_from=True`,
  expose `price_max_eur` and reduce trust.
* Bundle: `effective` is per unit; the report also shows the total and the
  minimum quantity.
* Account-gated / coupon: the displayed price is used, with a warning and a
  trust penalty.
* When several flags apply, `kind` uses this precedence:
  `account_gated` > `coupon` > `bundle` > `range` > `promo` > `regular` >
  `unknown`. Every applicable warning is still kept in `warnings`, so a bundle
  that is also account-gated keeps both facts in the report.

### 7.1 Trust

Trust multiplies; the floor is `0.4`.

| situation | trust |
|---|---|
| exact price, known shipping | 1.00 |
| unknown shipping | 0.90 |
| public promo | 0.90 |
| price from / range | 0.85 |
| bundle, min quantity 2+ | 0.85 |
| coupon-gated | 0.80 |
| account-gated | 0.65 |

The Price score row becomes `base_price_score * trust`. Scoring weights are not
changed. A separate `Price certainty` row is **not** added to the weighted
breakdown; the report shows the trust and its reasons as text.

## 8. Ranking and filtering

* `FilterEngine._price` returns `comparable_price(deal)`.
* `min_price` / `max_price` therefore apply to the effective price.
* `ResultProcessor` uses the effective price for the median, the cheapest pick,
  the best price/performance pick and the Price score row.
* `Deal.price_eur` remains the listed value in JSON, CSV and storage, so existing
  consumers do not break.
* Deduplication still keys on URL. A bundle and a single unit with the same URL
  are the same listing; the quote carries the bundle terms.

## 9. Report

* Summary table: effective price, plus a short marker (`new user`, `from`,
  `bundle 3 pcs`, `shipping unknown`). The marker is explained in a footnote.
* Deal card:
  * `Item 10.00 € + shipping 4.99 € = 14.99 €`;
  * bundle: `Total 30.00 € / 3 = 10.00 € per unit`;
  * range: `From 12.99 € (variants up to 18.99 €)`;
  * account-gated: `New-user price; regular price 19.99 €` when the card shows it;
  * evidence snippets and `source` (`regex` / `llm`).
* `Filtered out`: when a deal was removed by a price filter, the reason includes
  the effective price and the limit, plus the link.
* JSON/CSV gain `effective_price_eur`, `price_kind`, `price_trust` and
  `price_warnings`. Existing columns stay.
* Price history and watch comparisons use the effective price.

## 10. Storage

* Migration adds `effective_price_eur REAL` and `price_kind TEXT` to `deals` and
  `price_history`, using the existing additive migration helper in
  `src/storage/schema.py`.
* `shipping_cost_eur` is filled from the quote when known.
* The full quote is stored as JSON in `metadata["price_quote"]`.
* Old rows are read as `effective = price_eur`, `kind = unknown`; no backfill is
  required.

## 11. Backward compatibility

* A `Deal` without `price_quote` has `comparable_price_eur == price_eur` and
  `trust == 1.0`.
* Existing constructors and tests keep working because the new field is optional.
* No new third-party dependency.

## 12. Testing

Unit tests:

* deterministic signals in EN/SK/DE/CZ: newcomer, coupon, bundle, free shipping,
  shipping amount, shipping range, price from, price range, original price;
* effective-price arithmetic: item + shipping, bundle total / min quantity,
  shipping per unit, unknown shipping not zero;
* trust table and the floor;
* range handling: lowest value, `price_from`, `price_max_eur`;
* backward compatibility: no quote means the old behaviour.

LLM tests with a fake client:

* valid batch response is applied;
* evidence that is not a substring rejects the response;
* malformed JSON, timeout and unavailable model fall back to regex;
* model cannot lower trust or invent a shipping cost.

Integration tests:

* `ProfileAdapter` card text -> `Deal.price_quote`;
* `PlaywrightSearcher` LLM fallback pass over ambiguous deals;
* `FilterEngine` uses the effective price;
* `ResultProcessor` cheapest / median / Price row use the effective price;
* report contains the breakdown and warnings;
* storage round-trip preserves the quote and the new columns.

## 13. Risks

* Card text differs per marketplace and changes often. The deterministic layer is
  intentionally conservative; the LLM fallback covers the gaps.
* An LLM can hallucinate a shipping cost. Literal-evidence validation and numeric
  bounds reduce the risk; a rejected response leaves the deterministic result.
* Bundle unit prices can make a listing look artificially cheap. The report shows
  the total and the minimum quantity, and trust is reduced.
* Adding columns touches storage. The migration is additive and old rows keep
  working.

## 14. Rollout

1. Add `pricing.py` and its unit tests.
2. Attach deterministic quotes in `ProfileAdapter`; add Alza/Bazos shipping.
3. Add the LLM fallback batch call and its validation tests.
4. Switch `FilterEngine` and `ResultProcessor` to `comparable_price`.
5. Add storage columns and report fields.
6. Run the full suite and a live search with a marketplace card that shows
   shipping and a bundle.
