"""Price trust: shipping, bundles, ranges and gated promotions.

The rest of the searcher compares ``Deal.price_eur``. That is only the listed
price, so a cheap item with expensive shipping, a newcomer-only price and a
three-piece bundle all look better than they are. This module keeps the full
price story in :class:`PriceQuote` and exposes one comparable number.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from src.searcher.currency import parse_number, parse_price_detail


class PriceKind(StrEnum):
    """Why the listed price is what it is."""

    REGULAR = "regular"
    PROMO = "promo"
    COUPON = "coupon"
    ACCOUNT_GATED = "account_gated"
    BUNDLE = "bundle"
    RANGE = "range"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ShippingQuote:
    """Shipping cost. ``cost_eur=None`` means unknown, never free."""

    cost_eur: float | None = None
    min_eur: float | None = None
    max_eur: float | None = None
    is_free: bool | None = None
    note: str = ""


@dataclass(frozen=True)
class BundleTerms:
    """A listing that only makes sense when several pieces are bought."""

    min_quantity: int = 1
    total_price_eur: float | None = None
    note: str = ""


@dataclass(frozen=True)
class PriceQuote:
    """The full, comparable price story for one listing."""

    listed_price_eur: float
    effective_price_eur: float
    kind: PriceKind = PriceKind.UNKNOWN
    shipping: ShippingQuote = field(default_factory=ShippingQuote)
    bundle: BundleTerms = field(default_factory=BundleTerms)
    price_from: bool = False
    price_max_eur: float | None = None
    regular_price_eur: float | None = None
    trust: float = 1.0
    confidence: float = 1.0
    evidence: tuple[str, ...] = ()
    source: str = "regex"
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Serialise the quote for storage and JSON reports."""
        return {
            "listed_price_eur": self.listed_price_eur,
            "effective_price_eur": self.effective_price_eur,
            "kind": self.kind.value,
            "shipping": asdict(self.shipping),
            "bundle": asdict(self.bundle),
            "price_from": self.price_from,
            "price_max_eur": self.price_max_eur,
            "regular_price_eur": self.regular_price_eur,
            "trust": self.trust,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "source": self.source,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PriceSignals:
    """What the deterministic scanner found in one card's text."""

    kind: PriceKind = PriceKind.REGULAR
    shipping: ShippingQuote = field(default_factory=ShippingQuote)
    bundle: BundleTerms = field(default_factory=BundleTerms)
    price_from: bool = False
    price_max_eur: float | None = None
    regular_price_eur: float | None = None
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


_TRUST_FLOOR = 0.4


def _trust_for(
    kind: PriceKind,
    shipping: ShippingQuote,
    bundle: BundleTerms,
    price_from: bool,
) -> tuple[float, list[str]]:
    """Return the trust multiplier and the human-readable reasons."""
    trust = 1.0
    warnings: list[str] = []

    if shipping.is_free is not True and shipping.cost_eur is None:
        trust *= 0.90
        warnings.append("shipping unknown")

    if kind == PriceKind.PROMO:
        trust *= 0.90
        warnings.append("public promo price")
    if price_from or kind == PriceKind.RANGE:
        trust *= 0.85
        warnings.append("price from/range")
    if bundle.min_quantity > 1 or kind == PriceKind.BUNDLE:
        trust *= 0.85
        warnings.append(f"bundle min. {max(1, bundle.min_quantity)} pcs")
    if kind == PriceKind.COUPON:
        trust *= 0.80
        warnings.append("coupon-gated price")
    if kind == PriceKind.ACCOUNT_GATED:
        trust *= 0.65
        warnings.append("new user / account-gated price")

    return max(_TRUST_FLOOR, round(trust, 2)), warnings


def build_price_quote(
    listed_price_eur: float,
    *,
    kind: PriceKind = PriceKind.REGULAR,
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
    """Build a quote and compute the comparable per-unit effective price."""
    shipping = shipping or ShippingQuote()
    bundle = bundle or BundleTerms()
    quantity = max(1, int(bundle.min_quantity or 1))
    listed = max(0.0, float(listed_price_eur or 0.0))

    unit_price = listed / quantity
    if shipping.is_free is True:
        shipping_unit = 0.0
    elif shipping.cost_eur is not None:
        shipping_unit = max(0.0, float(shipping.cost_eur)) / quantity
    else:
        shipping_unit = 0.0

    trust, computed_warnings = _trust_for(kind, shipping, bundle, price_from)
    all_warnings = tuple(dict.fromkeys([*warnings, *computed_warnings]))

    return PriceQuote(
        listed_price_eur=listed,
        effective_price_eur=round(unit_price + shipping_unit, 2),
        kind=kind,
        shipping=shipping,
        bundle=BundleTerms(
            min_quantity=quantity,
            total_price_eur=bundle.total_price_eur or listed,
            note=bundle.note,
        ),
        price_from=price_from,
        price_max_eur=price_max_eur,
        regular_price_eur=regular_price_eur,
        trust=trust,
        confidence=max(0.0, min(1.0, float(confidence))),
        evidence=tuple(evidence),
        source=source,
        warnings=all_warnings,
    )


def comparable_price(deal: Any) -> float:
    """Return the price used for ranking, filters and reports.

    Deals without a quote keep the historical behaviour: their listed price is
    the comparable price.
    """
    quote = getattr(deal, "price_quote", None)
    if quote is not None:
        effective = getattr(quote, "effective_price_eur", None)
        if effective is not None and effective > 0:
            return float(effective)
    try:
        return float(getattr(deal, "price_eur", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Deterministic signal extraction
# ---------------------------------------------------------------------------

_ACCOUNT_PATTERNS = (
    r"\bnew\s+user\b",
    r"\bnew\s+customer\b",
    r"\bnewcomer\b",
    r"\bwelcome\s+deal\b",
    r"\bfirst\s+(?:order|purchase)\b",
    r"\bmember\s+price\b",
    r"\bapp[-\s]?only\b",
    r"\bnov\w*\s+z[áa]kazn\w*\b",
    r"\bprv[ýy]\s+n[áa]kup\b",
    r"\bprv[áa]\s+objedn[áa]vka\b",
    r"\buv[íi]tacia\b",
    r"\bneukunde\b",
    r"\bneuer\s+kunde\b",
    r"\berste\s+bestellung\b",
    r"\berstbestellung\b",
    r"\bwillkommensangebot\b",
    r"\bmitgliederpreis\b",
)

_COUPON_PATTERNS = (
    r"\bcoupon\b",
    r"\bkup[óo]n\b",
    r"\bwith\s+code\b",
    r"\bcode\s*[:=]",
    r"\bauto[-\s]?applied\b",
    r"\bgutschein\b",
    r"\bs\s+k[óo]dom\b",
)

_BUNDLE_PATTERNS = (
    r"\b(?:min(?:imum)?\.?\s*(?:order|qty|quantity|mno[žz]stvo)?\s*[:=]?\s*)(\d{1,3})\s*(?:ks|pcs|pieces|stk|items?)\b",
    r"\b(?:buy|k[úu]p|kup|objednaj)\s*(\d{1,3})\b",
    r"\b(\d{1,3})\s*(?:ks|pcs|pieces|stk)\s*(?:za|for|/|:)\b",
    r"\b(\d{1,3})\s*(?:for|za)\s*\d",
    r"\b(?:balenie|set\s+of|pack\s+of)\D{0,12}(\d{1,3})\b",
    r"\b(\d{1,3})er[-\s]?(?:pack|set)\b",
    r"\b(\d{1,3})[-\s]?pack\b",
    r"\bpack\s+of\s+(\d{1,3})\b",
    r"\bset\s+of\s+(\d{1,3})\b",
)

_FREE_SHIPPING_PATTERNS = (
    r"\bfree\s+shipping\b",
    r"\bshipping\s+free\b",
    r"\bdoprava\s+zdarma\b",
    r"\bpo[šs]tovn[ée]\s+zdarma\b",
    r"\bversandkostenfrei\b",
    r"\bkostenlos(?:er|e|en)?\s+(?:versand|lieferung)\b",
)

_SHIPPING_PATTERNS = (
    r"(?:shipping|doprava|po[šs]tovn[ée]|versand|lieferung)\s*(?:od|from|ab)?\s*[:=]?\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)?",
    # Postfix form used by many cards: "+ 9,90 € doprava".
    r"\+\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)\s*(?:shipping|doprava|po[šs]tovn[ée]|versand|lieferung)\b",
)

_SHIPPING_RANGE_PATTERNS = (
    r"(?:shipping|doprava|po[šs]tovn[ée]|versand|lieferung)\s*(?:od|from|ab)\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)?",
)

_PRICE_FROM_PATTERNS = (
    r"\b(?:from|od|ab)\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)",
)

_PRICE_RANGE_PATTERNS = (
    r"\b(?:od|from|ab)\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)\s*(?:do|to|bis|a[žz])\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)",
    r"\b(\d[\d\s.,]*)\s*[-\u2013\u2014]\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)",
)

_ORIGINAL_PRICE_PATTERNS = (
    r"\b(?:was|statt|p[ůu]vodn[ée]|p[ôo]vodn[áa])\s*(\d[\d\s.,]*)\s*(?:€|eur|k[čc]|czk)",
)


def _match_any(text: str, patterns: tuple[str, ...]) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for pattern in patterns:
        matches.extend(re.finditer(pattern, text, re.IGNORECASE))
    return matches


def _amount(text: str, default_currency: str) -> float | None:
    detail = parse_price_detail(text, default_currency)
    if detail is None:
        return None
    return detail[1]


def _mask(text: str, matches: list[re.Match[str]]) -> str:
    """Blank out matched spans so a shipping amount is not read as a price."""
    chars = list(text)
    for match in matches:
        for index in range(match.start(), match.end()):
            chars[index] = " "
    return "".join(chars)


def extract_price_signals(
    text: str,
    listed_price_eur: float,
    currency: str = "EUR",
) -> PriceSignals:
    """Scan a listing card for shipping, bundle, range and gated-price labels."""
    text = text or ""
    evidence: list[str] = []
    warnings: list[str] = []
    confidence = 0.0

    account = _match_any(text, _ACCOUNT_PATTERNS)
    coupon = _match_any(text, _COUPON_PATTERNS)
    bundle = _match_any(text, _BUNDLE_PATTERNS)
    free_shipping = _match_any(text, _FREE_SHIPPING_PATTERNS)
    shipping_range = _match_any(text, _SHIPPING_RANGE_PATTERNS)
    shipping = _match_any(text, _SHIPPING_PATTERNS)
    original = _match_any(text, _ORIGINAL_PRICE_PATTERNS)

    for match in account + coupon + bundle + free_shipping + shipping_range + shipping + original:
        snippet = " ".join(match.group(0).split())
        if snippet and snippet not in evidence:
            evidence.append(snippet)

    shipping_quote = ShippingQuote()
    if free_shipping:
        shipping_quote = ShippingQuote(cost_eur=0.0, is_free=True)
        confidence = 1.0
    elif shipping_range:
        amount = _amount(shipping_range[0].group(0), currency)
        if amount is not None:
            shipping_quote = ShippingQuote(
                cost_eur=amount, min_eur=amount, is_free=False
            )
            confidence = 1.0
    elif shipping:
        amount = _amount(shipping[0].group(0), currency)
        if amount is not None:
            shipping_quote = ShippingQuote(cost_eur=amount, is_free=False)
            confidence = 1.0

    min_quantity = 1
    if bundle:
        for match in bundle:
            for group in match.groups():
                if group and group.isdigit():
                    min_quantity = max(1, int(group))
                    break
            if min_quantity > 1:
                break
        if min_quantity > 1:
            confidence = 1.0
            warnings.append(f"bundle min. {min_quantity} pcs")

    # Shipping text is masked so "Doprava od 2 €" is not read as "price from".
    masked = _mask(text, shipping_range + shipping + free_shipping)
    price_from = False
    price_max = None
    range_match = _match_any(masked, _PRICE_RANGE_PATTERNS)
    if range_match:
        first, second = range_match[0].group(1), range_match[0].group(2)
        low = parse_number(first)
        high = parse_number(second)
        if low is not None:
            price_from = True
            price_max = high
            confidence = 1.0
            warnings.append("price from/range")
    else:
        from_match = _match_any(masked, _PRICE_FROM_PATTERNS)
        if from_match:
            low = parse_number(from_match[0].group(1))
            if low is not None:
                price_from = True
                confidence = 1.0
                warnings.append("price from/range")

    regular_price = None
    if original:
        regular_price = _amount(original[0].group(0), currency)
        if regular_price is not None:
            confidence = 1.0

    if account:
        kind = PriceKind.ACCOUNT_GATED
        confidence = 1.0
        warnings.append("new user / account-gated price")
    elif coupon:
        kind = PriceKind.COUPON
        confidence = 1.0
        warnings.append("coupon-gated price")
    elif min_quantity > 1:
        kind = PriceKind.BUNDLE
    elif price_from:
        kind = PriceKind.RANGE
    elif regular_price is not None:
        kind = PriceKind.PROMO
        confidence = 1.0
    else:
        kind = PriceKind.REGULAR

    return PriceSignals(
        kind=kind,
        shipping=shipping_quote,
        bundle=BundleTerms(
            min_quantity=min_quantity,
            total_price_eur=listed_price_eur if min_quantity > 1 else None,
        ),
        price_from=price_from,
        price_max_eur=price_max,
        regular_price_eur=regular_price,
        confidence=confidence,
        evidence=tuple(evidence),
        warnings=tuple(dict.fromkeys(warnings)),
    )


# ---------------------------------------------------------------------------
# LLM response validation
# ---------------------------------------------------------------------------

_ALLOWED_KINDS = {kind.value for kind in PriceKind}
_PRICE_NUMBER_FIELDS = (
    "shipping_cost_eur",
    "shipping_min_eur",
    "shipping_max_eur",
    "price_max_eur",
    "regular_price_eur",
)
_MAX_AMOUNT = 1_000_000.0
_INVALID = object()


def _valid_amount(value: Any) -> float | object | None:
    """Return a finite non-negative amount, ``None``, or ``_INVALID``."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _INVALID
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return _INVALID
    if number < 0 or number > _MAX_AMOUNT:
        return _INVALID
    return number


def validate_price_classification(
    payload: Any, card_text: str
) -> dict[str, Any] | None:
    """Validate one LLM price classification against the card text.

    The model may only report what is visible on the card. Every evidence
    snippet must be a literal substring, and every number must be finite and
    sane. A response that breaks a rule is rejected as a whole, so a
    hallucinated shipping cost cannot leak into the ranking.
    """
    if not isinstance(payload, dict):
        return None

    kind = payload.get("kind", PriceKind.UNKNOWN.value)
    if kind not in _ALLOWED_KINDS:
        kind = PriceKind.UNKNOWN.value

    evidence = payload.get("evidence") or []
    if not isinstance(evidence, list):
        return None
    cleaned_evidence: list[str] = []
    for item in evidence:
        if not isinstance(item, str):
            return None
        if item and item not in card_text:
            return None
        if item:
            cleaned_evidence.append(item)

    numbers = {name: _valid_amount(payload.get(name)) for name in _PRICE_NUMBER_FIELDS}
    if any(value is _INVALID for value in numbers.values()):
        return None

    quantity = payload.get("bundle_min_quantity", 1)
    if quantity is None:
        quantity = 1
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return None
    if quantity < 1 or quantity > 1000:
        return None

    warnings = payload.get("warnings") or []
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
        return None

    confidence = payload.get("confidence", 0.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    confidence = max(0.0, min(1.0, float(confidence)))

    def _flag(name: str) -> bool:
        return payload.get(name) is True

    return {
        "kind": kind,
        "shipping_cost_eur": numbers["shipping_cost_eur"],
        "shipping_is_free": (
            payload.get("shipping_is_free")
            if isinstance(payload.get("shipping_is_free"), bool)
            else None
        ),
        "shipping_min_eur": numbers["shipping_min_eur"],
        "shipping_max_eur": numbers["shipping_max_eur"],
        "bundle_min_quantity": quantity,
        "price_from": _flag("price_from"),
        "price_max_eur": numbers["price_max_eur"],
        "regular_price_eur": numbers["regular_price_eur"],
        "warnings": warnings,
        "confidence": confidence,
        "evidence": cleaned_evidence,
    }


__all__ = [
    "BundleTerms",
    "PriceKind",
    "PriceQuote",
    "PriceSignals",
    "ShippingQuote",
    "build_price_quote",
    "comparable_price",
    "extract_price_signals",
    "validate_price_classification",
]
