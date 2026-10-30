"""Canonical search filters shared by the CLI, prompt parsing and adapters.

The user-facing filter vocabulary is deliberately small and site-agnostic.
Site profiles map these canonical keys onto each marketplace's own parameter
names and values.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.config.models import Category, Condition

from src.text.normalize import fold

logger = logging.getLogger(__name__)

CONDITION_VALUES = ("new", "used", "refurbished", "open_box", "marketplace")
SHIPPING_VALUES = ("free", "paid")
SELLER_TYPE_VALUES = ("retailer", "marketplace", "classifieds", "auction", "private")
SORT_VALUES = ("relevance", "price_asc", "price_desc", "newest")

_CONDITION_ALIASES = {
    "new": "new",
    "brand new": "new",
    "novy": "new",
    "nove": "new",
    "nové": "new",
    "neu": "new",
    "neue": "new",
    "neues": "new",
    "neuer": "new",
    "used": "used",
    "pouzity": "used",
    "pouzite": "used",
    "použitý": "used",
    "použité": "used",
    "gebraucht": "used",
    "gebrauchte": "used",
    "gebrauchter": "used",
    "gebrauchtes": "used",
    "wie neu": "used",
    "bazar": "used",
    "bazarovy": "used",
    "second hand": "used",
    "refurbished": "refurbished",
    "rekonstruovany": "refurbished",
    "repasovany": "refurbished",
    "generaluberholt": "refurbished",
    "generaluberholte": "refurbished",
    "generaluberholter": "refurbished",
    "generaluberholtes": "refurbished",
    "aufbereitet": "refurbished",
    "aufbereitete": "refurbished",
    "aufbereiteter": "refurbished",
    "aufbereitetes": "refurbished",
    "open box": "open_box",
    "openbox": "open_box",
    "open_box": "open_box",
    "rozbaleny": "open_box",
    "rozbalene": "open_box",
    "marketplace": "marketplace",
}

_SHIPPING_ALIASES = {
    "free": "free",
    "zdarma": "free",
    "free shipping": "free",
    "doprava zdarma": "free",
    "postovne zdarma": "free",
    "versandkostenfrei": "free",
    "kostenloser versand": "free",
    "kostenloses versand": "free",
    "kostenlosem versand": "free",
    "kostenlosen versand": "free",
    "paid": "paid",
    "platena": "paid",
    "platena doprava": "paid",
}

_SORT_ALIASES = {
    "relevance": "relevance",
    "relevant": "relevance",
    "najrelevantnejsie": "relevance",
    "price_asc": "price_asc",
    "price ascending": "price_asc",
    "najlacnejsie": "price_asc",
    "od najlacnejsieho": "price_asc",
    "cheapest": "price_asc",
    "gunstigste zuerst": "price_asc",
    "gunstigsten zuerst": "price_asc",
    "billigste": "price_asc",
    "billigsten": "price_asc",
    "nejlevnejsi": "price_asc",
    "price_desc": "price_desc",
    "price descending": "price_desc",
    "najdrahsie": "price_desc",
    "od najdrahsieho": "price_desc",
    "most expensive": "price_desc",
    "teuerste": "price_desc",
    "teuersten": "price_desc",
    "nejdrazsi": "price_desc",
    "newest": "newest",
    "najnovsie": "newest",
    "latest": "newest",
    "neueste": "newest",
    "neuesten": "newest",
    "nejnovejsi": "newest",
}

_SELLER_ALIASES = {
    "retailer": "retailer",
    "obchod": "retailer",
    "shop": "retailer",
    "marketplace": "marketplace",
    "classifieds": "classifieds",
    "bazar": "classifieds",
    "private": "private",
    "sukromny": "private",
    "auction": "auction",
    "aukcia": "auction",
}

_NUMBER_RE = re.compile(r"\d[\d\s\u00a0\u202f.,]*")
_MIN_RE = re.compile(
    r"\b(?:od|min(?:imum)?|nad|above|over|viac\s+ako|from|ab|mindestens)\s*"
    r"(\d[\d\s\u00a0\u202f.,]*)\s*(?:eur|euro|€|kč|kc|czk|zł|zl|pln|ft|huf)?",
    re.IGNORECASE,
)
_MAX_RE = re.compile(
    r"\b(?:do|maximal|max(?:imum)?|pod|unter|bis|under|najviac|menej\s+ako|"
    r"up\s+to|h[oö]chstens)\s*"
    r"(\d[\d\s\u00a0\u202f.,]*)\s*(?:eur|euro|€|kč|kc|czk|zł|zl|pln|ft|huf)?",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"(\d[\d\s\u00a0\u202f.,]*)\s*(?:-|\u2013|\u2014|až|az|to)\s*"
    r"(\d[\d\s\u00a0\u202f.,]*)\s*(?:eur|euro|€|kč|kc|czk|zł|zl|pln|ft|huf)?",
    re.IGNORECASE,
)
_BETWEEN_RE = re.compile(
    r"(?:medzi|between)\s*(\d[\d\s\u00a0\u202f.,]*)\s*(?:a|and|až|az|-)\s*"
    r"(\d[\d\s\u00a0\u202f.,]*)\s*(?:eur|euro|€|kč|kc|czk|zł|zl|pln|ft|huf)?",
    re.IGNORECASE,
)
_BRAND_RE = re.compile(r"\b(?:brand|znacka|značka)\s*[:=]\s*([^,;]+)", re.IGNORECASE)
_LOCATION_RE = re.compile(r"\b(?:location|lokalita|mesto)\s*[:=]\s*([^,;]+)", re.IGNORECASE)
_SELLER_RE = re.compile(r"\b(?:seller|predajca)\s*[:=]\s*([^,;]+)", re.IGNORECASE)
_SORT_RE = re.compile(r"\b(?:sort|zoradenie|triedenie)\s*[:=]\s*([^,;]+)", re.IGNORECASE)
_EXTRA_RE = re.compile(r"\b([a-z][a-z0-9_]{1,24})\s*=\s*([\w./+-]{1,40})", re.IGNORECASE)


def _clean(text: Any) -> str | None:
    if text is None:
        return None
    if isinstance(text, list):
        parts = [" ".join(str(t).split()).strip() for t in text if t is not None]
        value = ", ".join(p for p in parts if p)
    else:
        value = " ".join(str(text).split()).strip()
    return value or None


def _parse_number(text: str) -> float | None:
    """Parse a European or US formatted price from a short string."""
    raw = _NUMBER_RE.search(text or "")
    if not raw:
        return None
    num = raw.group(0).replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    num = num.rstrip(".,")
    if not num:
        return None

    last_dot = num.rfind(".")
    last_comma = num.rfind(",")
    last_sep = max(last_dot, last_comma)
    if last_sep == -1:
        try:
            return float(num)
        except ValueError:
            return None

    tail = num[last_sep + 1 :]
    if len(tail) in (1, 2):
        head = num[:last_sep].replace(".", "").replace(",", "")
        frac = tail
        try:
            return float(f"{head}.{frac}")
        except ValueError:
            return None

    try:
        return float(num.replace(".", "").replace(",", ""))
    except ValueError:
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return _parse_number(str(value))


def _normalise_choice(value: Any, aliases: Mapping[str, str], allowed: tuple[str, ...], *, strict: bool) -> str | None:
    if value is None or value == "":
        return None
    text = fold(_clean(value) or "").lower()
    if text in (Condition.ANY, "all", "alles", "vsetko", "všetko"):
        return None
    normalised = aliases.get(text, text)
    if normalised in allowed:
        return normalised
    if strict:
        msg = f"Unsupported filter value {value!r}; expected one of {', '.join(allowed)}"
        raise ValueError(msg)
    return None


def _normalise_condition(value: Any, *, strict: bool) -> str | None:
    return _normalise_choice(value, _CONDITION_ALIASES, CONDITION_VALUES, strict=strict)


def _normalise_shipping(value: Any, *, strict: bool) -> str | None:
    return _normalise_choice(value, _SHIPPING_ALIASES, SHIPPING_VALUES, strict=strict)


def _normalise_sort(value: Any, *, strict: bool) -> str | None:
    return _normalise_choice(value, _SORT_ALIASES, SORT_VALUES, strict=strict)


def _normalise_seller(value: Any, *, strict: bool) -> str | None:
    return _normalise_choice(value, _SELLER_ALIASES, SELLER_TYPE_VALUES, strict=strict)


@dataclass(frozen=True)
class SearchFilters:
    """Canonical, site-agnostic filters for one search."""

    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    brand: str | None = None
    location: str | None = None
    shipping: str | None = None
    seller_type: str | None = None
    sort: str | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def validate(self) -> SearchFilters:
        for name in ("min_price", "max_price"):
            value = getattr(self, name)
            if value is not None and value < 0:
                msg = f"{name} must not be negative"
                raise ValueError(msg)
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            msg = "min_price must not be greater than max_price"
            raise ValueError(msg)
        for name, _aliases, allowed in (
            ("condition", _CONDITION_ALIASES, CONDITION_VALUES),
            ("shipping", _SHIPPING_ALIASES, SHIPPING_VALUES),
            ("seller_type", _SELLER_ALIASES, SELLER_TYPE_VALUES),
            ("sort", _SORT_ALIASES, SORT_VALUES),
        ):
            value = getattr(self, name)
            if value is not None and value not in allowed:
                msg = f"Unsupported {name} {value!r}; expected one of {', '.join(allowed)}"
                raise ValueError(msg)
        return self

    def is_empty(self) -> bool:
        return not any(
            (
                self.min_price is not None,
                self.max_price is not None,
                self.condition,
                self.brand,
                self.location,
                self.shipping,
                self.seller_type,
                self.sort,
                self.extras,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "min_price": self.min_price,
            "max_price": self.max_price,
            "condition": self.condition,
            "brand": self.brand,
            "location": self.location,
            "shipping": self.shipping,
            "seller_type": self.seller_type,
            "sort": self.sort,
            "extras": dict(self.extras),
        }
        return {key: value for key, value in data.items() if value not in (None, {}, "")}


def merge_filters(base: SearchFilters | None, override: SearchFilters | None) -> SearchFilters:
    """Merge two filter sets; scalar values from *override* win, extras combine."""
    base = base or SearchFilters()
    override = override or SearchFilters()
    extras = dict(base.extras)
    extras.update(override.extras)
    # Guard against LLM hallucinating a min_price equal to max_price (e.g.
    # interpreting "up to 300" as "exactly 300"). Only trust an override
    # min_price when it differs from the override max_price or base already had one.
    override_min = override.min_price
    if (
        override_min is not None
        and base.min_price is None
        and override.max_price is not None
        and override_min == override.max_price
    ):
        override_min = None
    return SearchFilters(
        min_price=override_min if override_min is not None else base.min_price,
        max_price=override.max_price if override.max_price is not None else base.max_price,
        condition=override.condition or base.condition,
        brand=override.brand or base.brand,
        location=override.location or base.location,
        shipping=override.shipping or base.shipping,
        seller_type=override.seller_type or base.seller_type,
        sort=override.sort or base.sort,
        extras=extras,
    )


def from_cli(
    min_price: Any = None,
    max_price: Any = None,
    condition: Any = None,
    brand: Any = None,
    location: Any = None,
    shipping: Any = None,
    seller_type: Any = None,
    sort: Any = None,
    extra_filters: Iterable[str] | None = None,
) -> SearchFilters:
    """Build filters from CLI values. Raises ValueError for malformed input."""
    extras: dict[str, str] = {}
    for raw in extra_filters or ():
        key, sep, value = str(raw).partition("=")
        key = key.strip().lower()
        value = value.strip()
        if not sep or not key or not value:
            msg = f"Invalid filter {raw!r}; use KEY=VALUE"
            raise ValueError(msg)
        extras[key] = value

    return SearchFilters(
        min_price=_optional_float(min_price),
        max_price=_optional_float(max_price),
        condition=_normalise_condition(condition, strict=True),
        brand=_clean(brand),
        location=_clean(location),
        shipping=_normalise_shipping(shipping, strict=True),
        seller_type=_normalise_seller(seller_type, strict=True),
        sort=_normalise_sort(sort, strict=True),
        extras=extras,
    ).validate()


def filters_from_mapping(data: Mapping[str, Any] | None) -> SearchFilters:
    """Build filters from LLM/config data, ignoring unknown or malformed values."""
    if not isinstance(data, Mapping):
        return SearchFilters()

    raw_extras = data.get("extras") or {}
    extras: dict[str, str] = {}
    if isinstance(raw_extras, Mapping):
        extras.update({str(k).strip().lower(): str(v).strip() for k, v in raw_extras.items() if v is not None})
    elif isinstance(raw_extras, Iterable) and not isinstance(raw_extras, (str, bytes)):
        for raw in raw_extras:
            key, sep, value = str(raw).partition("=")
            if sep and key.strip() and value.strip():
                extras[key.strip().lower()] = value.strip()

    known = {
        "min_price",
        "max_price",
        "price_min",
        "price_max",
        "condition",
        "brand",
        "location",
        "shipping",
        "seller_type",
        "sort",
        "extras",
    }
    for key, value in data.items():
        normalised_key = str(key).strip().lower()
        if normalised_key in known or value is None or value == "":
            continue
        if isinstance(value, (str, int, float, bool)):
            extras[normalised_key] = str(value).lower() if isinstance(value, bool) else str(value)

    result = SearchFilters(
        min_price=_optional_float(data.get("min_price", data.get("price_min"))),
        max_price=_optional_float(data.get("max_price", data.get("price_max"))),
        condition=_normalise_condition(data.get("condition"), strict=False),
        brand=_clean(data.get("brand")),
        location=_clean(data.get("location")),
        shipping=_normalise_shipping(data.get("shipping"), strict=False),
        seller_type=_normalise_seller(data.get("seller_type"), strict=False),
        sort=_normalise_sort(data.get("sort"), strict=False),
        extras=extras,
    )
    return result.validate()


def parse_filters_from_text(prompt: str) -> SearchFilters:
    """Extract obvious filters from natural language without an LLM.

    This is intentionally conservative: the LLM extraction step handles
    ambiguous wording. Here we only catch explicit prices, condition words,
    shipping wording and sort wording.
    """
    text = prompt or ""
    normalised = fold(text).lower()

    min_price = None
    max_price = None
    between = _BETWEEN_RE.search(text)
    if between:
        min_price = _parse_number(between.group(1))
        max_price = _parse_number(between.group(2))
    else:
        price_range = _RANGE_RE.search(text)
        if price_range:
            min_price = _parse_number(price_range.group(1))
            max_price = _parse_number(price_range.group(2))

    if min_price is None:
        match = _MIN_RE.search(text)
        if match:
            min_price = _parse_number(match.group(1))
    if max_price is None:
        match = _MAX_RE.search(text)
        if match:
            max_price = _parse_number(match.group(1))

    condition = None
    for patterned, value in (
        (r"\bopen[\s_-]?box\b|\brozbalen(?:y|e)\b", "open_box"),
        (
            r"\brefurbished\b|\brepasovan(?:y|e)\b|\brekonstruovan(?:y|e)\b"
            r"|generaluberholt(?:e|es|er)?|aufbereitet(?:e|es|er)?",
            "refurbished",
        ),
        (
            r"\bused\b|\bpouzit(?:y|e)\b|\bbazar(?:ovy|ove)?\b|\bsecond[\s-]?hand\b"
            r"|gebraucht(?:e|es|er)?|wie neu",
            "used",
        ),
        (r"\bbrand[\s-]?new\b|\bnew\b|\bnov(?:y|e)\b|\bneu(?:e|es|er)?\b", "new"),
        (r"\bmarketplace\b", "marketplace"),
    ):
        if re.search(patterned, normalised):
            condition = value
            break

    shipping = None
    if re.search(
        r"\b(?:free[\s-]?shipping|doprava\s+zdarma|postovne\s+zdarma"
        r"|versandkostenfrei|kostenlos(?:er|em|en|e)?\s+versand)\b",
        normalised,
    ):
        shipping = "free"
    elif re.search(r"\b(?:paid[\s-]?shipping|platena\s+doprava)\b", normalised):
        shipping = "paid"

    sort = None
    for patterned, value in (
        (
            r"\bnajlacnejsie\b|\bcheapest\b|\bprice[\s_-]?asc\b"
            r"|gunstigste(?:n)?\s+zuerst|billigste(?:n)?|nejlevnejsi",
            "price_asc",
        ),
        (
            r"\bnajdrahsie\b|\bmost[\s-]?expensive\b|\bprice[\s_-]?desc\b"
            r"|teuerste(?:n)?|nejdrazsi",
            "price_desc",
        ),
        (
            r"\bnajnovsie\b|\bnewest\b|\blatest\b|neueste(?:n)?|nejnovejsi",
            "newest",
        ),
        (r"\bnajrelevantnejsie\b|\brelevance\b", "relevance"),
    ):
        if re.search(patterned, normalised):
            sort = value
            break

    brand_match = _BRAND_RE.search(text)
    location_match = _LOCATION_RE.search(text)
    seller_match = _SELLER_RE.search(text)
    sort_match = _SORT_RE.search(text)
    if sort_match:
        sort = _normalise_sort(sort_match.group(1), strict=False) or sort

    extras: dict[str, str] = {}
    for raw_key, value in _EXTRA_RE.findall(text):
        key = raw_key.lower()
        if key not in {"brand", "location", "seller", "sort"}:
            extras[key] = value

    return SearchFilters(
        min_price=min_price,
        max_price=max_price,
        condition=condition,
        brand=_clean(brand_match.group(1)) if brand_match else None,
        location=_clean(location_match.group(1)) if location_match else None,
        shipping=shipping,
        seller_type=_normalise_seller(seller_match.group(1), strict=False) if seller_match else None,
        sort=sort,
        extras=extras,
    ).validate()


CATEGORIES: tuple[Category, ...] = (
    Category.ELECTRONICS,
    Category.APPLIANCES,
    Category.AUTO,
    Category.HOME,
    Category.HOBBY,
    Category.GENERAL,
)


@dataclass
class SearchRequest:
    """Grouped filter inputs flowing from CLI through run_search."""

    prompt: str = ""
    prompt_file: str | None = None
    condition: str = Condition.ANY
    category: str | None = None
    winners: int | None = None
    output_format: str | None = None
    min_price: str | None = None
    max_price: str | None = None
    brand: str | None = None
    location: str | None = None
    shipping: str | None = None
    seller_type: str | None = None
    sort: str | None = None
    extra_filters: list[str] | None = None
    country: str | None = None
    max_sites: int | None = None
    llm_mode: str | None = None
    debug: bool = False
    domain: str | None = None


@dataclass(frozen=True)
class ResolvedRequest:
    """Prompt-derived filters plus the product category the model proposed."""

    filters: SearchFilters
    category: str | None


def _normalise_category(raw: Any) -> str | None:
    """Fold the model's category word; anything outside CATEGORIES is no answer."""
    if not isinstance(raw, str):
        return None
    value = fold(raw).strip()
    if value in CATEGORIES:
        return value
    logger.debug("LLM proposed unusable category %r; ignoring it", raw)
    return None


async def resolve_request(
    prompt: str, cli_filters: SearchFilters | None, llm: Any = None
) -> ResolvedRequest:
    """Resolve prompt filters through deterministic parsing, LLM, then CLI.

    CLI values always win. An unavailable or broken LLM must never prevent a
    search from running. The category arrives on the same LLM call that
    extracts filters — it is popped before mapping so it can never leak into
    ``extras``, and an unusable value degrades to ``None`` (= search anything).
    """
    parsed = parse_filters_from_text(prompt)
    llm_filters = SearchFilters()
    category: str | None = None
    if llm is not None and hasattr(llm, "extract_search_filters"):
        try:
            payload = await llm.extract_search_filters(prompt)
            if isinstance(payload, dict):
                category = _normalise_category(payload.get("category"))
                payload = {k: v for k, v in payload.items() if k != "category"}
            llm_filters = filters_from_mapping(payload)
        except Exception as exc:  # noqa: BLE001 - optional enrichment must not break the run
            logger.warning("Filter extraction failed: %s", exc)
            category = None
    merged = merge_filters(parsed, llm_filters)
    merged = merge_filters(merged, cli_filters)
    return ResolvedRequest(filters=merged.validate(), category=category)


async def resolve_filters(
    prompt: str, cli_filters: SearchFilters | None, llm: Any = None
) -> SearchFilters:
    """Filters only, for callers that have no use for the inferred category."""
    resolved = await resolve_request(prompt, cli_filters, llm)
    return resolved.filters
