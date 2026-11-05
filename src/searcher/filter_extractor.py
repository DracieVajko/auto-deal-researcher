"""Multi-language filter extraction for search queries.

Extends the existing LLM-based ``extract_search_filters`` with deterministic
keyword mappings for Slovak, Czech, German, and Polish marketplaces, plus
spec-based filters derived from ItemSpecs research (power_kw, battery_kwh,
weight_kg, dimensions, etc.).

Used by the replacement finder to turn researched specs into marketplace
search filters, and by the standard search to handle multi-language prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from src.config.models import Category, Condition

Language = Literal["sk", "cs", "de", "pl", "en"]


# ---------------------------------------------------------------------------
# Language keyword maps
# ---------------------------------------------------------------------------

CONDITION_KEYWORDS: dict[Language, dict[str, str]] = {
    "sk": {
        "nové": "new",
        "novo": "new",
        "použité": "used",
        "pouzite": "used",
        "repasované": "refurbished",
        "repasovane": "refurbished",
        "vo fenêtre": "open_box",
        "v finestra": "open_box",
    },
    "cs": {
        "nové": "new",
        "nove": "new",
        "použité": "used",
        "pouzite": "used",
        "repasované": "refurbished",
        "repasovane": "refurbished",
        "otevřená krabice": "open_box",
        "otevrena krabice": "open_box",
    },
    "de": {
        "neu": "new",
        "gebraucht": "used",
        "aufgearbeitet": "refurbished",
        "generalüberholt": "refurbished",
        "offene verpackung": "open_box",
        "offeneverpackung": "open_box",
    },
    "pl": {
        "nowe": "new",
        "używane": "used",
        "uzywane": "used",
        "odnowione": "refurbished",
        "otwarte opakowanie": "open_box",
        "otwarteopakowanie": "open_box",
    },
    "en": {
        "new": "new",
        "used": "used",
        "refurbished": "refurbished",
        "open box": "open_box",
    },
}

CATEGORY_KEYWORDS: dict[Language, dict[str, str]] = {
    "sk": {
        "auto": "auto",
        "automobil": "auto",
        "auto-moto": "auto",
        "elektronika": "electronics",
        "mobilný telefón": "electronics",
        "mobilny telefon": "electronics",
        "notebook": "electronics",
        "domáca spotrebiča": "appliances",
        "domaca spotrebica": "appliances",
        "nábytok": "home",
        "nabytok": "home",
        "záhrada": "home",
        "zahrada": "home",
        "šport": "hobby",
        "sport": "hobby",
        "náradie": "hobby",
        "naradie": "hobby",
    },
    "cs": {
        "auto": "auto",
        "elektronika": "electronics",
        "mobilní telefon": "electronics",
        "mobilni telefon": "electronics",
        "notebook": "electronics",
        "spotřebič": "appliances",
        "spotrebic": "appliances",
        "nábytek": "home",
        "nabytek": "home",
        "zahrada": "home",
        "sport": "hobby",
        "nářadí": "hobby",
        "naradi": "hobby",
    },
    "de": {
        "auto": "auto",
        "fahrzeug": "auto",
        "elektronik": "electronics",
        "handy": "electronics",
        "laptop": "electronics",
        "haushaltsgerät": "appliances",
        "haushaltsgerat": "appliances",
        "möbel": "home",
        "moebel": "home",
        "garten": "home",
        "sport": "hobby",
        "werkzeug": "hobby",
    },
    "pl": {
        "samochód": "auto",
        "samochod": "auto",
        "elektronika": "electronics",
        "telefon": "electronics",
        "laptop": "electronics",
        "agd": "appliances",
        "meble": "home",
        "ogród": "home",
        "ogrod": "home",
        "sport": "hobby",
        "narzędzia": "hobby",
        "narzedzia": "hobby",
    },
    "en": {
        "auto": "auto",
        "car": "auto",
        "vehicle": "auto",
        "electronics": "electronics",
        "phone": "electronics",
        "laptop": "electronics",
        "appliances": "appliances",
        "home": "home",
        "furniture": "home",
        "garden": "home",
        "hobby": "hobby",
        "sport": "hobby",
        "tools": "hobby",
    },
}

PRICE_KEYWORDS: dict[Language, list[str]] = {
    "sk": ["do", "max", "najviac", "cena do", "po", "od"],
    "cs": ["do", "max", "nejvíc", "cena do", "po", "od"],
    "de": ["unter", "max", "maximal", "bis", "ab", "von"],
    "pl": ["do", "max", "maksymalnie", "cena do", "od", "powyżej"],
    "en": ["under", "max", "maximum", "below", "over", "above", "from", "to"],
}

SPEC_KEYWORDS = {
    "power_kw": ["kw", "kilowatt", "výkon", "moc", "leistung"],
    "battery_kwh": ["kwh", "kapacita baterie", "baterija", "akku"],
    "range_km": ["km", "dochod", "záves", "reichweite"],
    "weight_kg": ["kg", "hmotnosť", "hmotnost", "váha", "gewicht"],
}


@dataclass
class ExtractedFilters:
    """Result of filter extraction."""

    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    category: str | None = None
    brand: str | None = None
    location: str | None = None
    shipping: Literal["free", "paid"] | None = None
    seller_type: Literal["retailer", "marketplace", "classifieds", "auction", "private"] | None = None
    sort: Literal["relevance", "price_asc", "price_desc", "newest"] | None = None
    extras: dict[str, str] = field(default_factory=dict)
    language: Language = "en"
    confidence: float = 1.0


def _word_match(text_lower: str, kw: str) -> bool:
    """Check if keyword appears as a whole word (not substring)."""
    import re
    return bool(re.search(rf"\b{re.escape(kw)}\b", text_lower))


def detect_language(text: str) -> Language:
    """Detect the language of a text using keyword heuristics."""
    text_lower = text.lower()
    scores: dict[Language, int] = {"sk": 0, "cs": 0, "de": 0, "pl": 0, "en": 0}

    for lang, keywords in CONDITION_KEYWORDS.items():
        for kw in keywords:
            if _word_match(text_lower, kw):
                scores[lang] += 2

    for lang, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if _word_match(text_lower, kw):
                scores[lang] += 1

    # Price keywords add to language score
    for lang, keywords in PRICE_KEYWORDS.items():
        for kw in keywords:
            if _word_match(text_lower, kw):
                scores[lang] += 1

    # SK/CZ disambiguation: Slovak-specific words
    sk_words = ["čo", "kde", "ako", "prečo", "cena", "výrobca", "stav", "parametre", "do", "od"]
    cz_words = ["co", "kde", "jak", "proč", "cena", "výrobce", "stav", "parametry", "do", "od"]
    for w in sk_words:
        if _word_match(text_lower, w):
            scores["sk"] += 1
    for w in cz_words:
        if _word_match(text_lower, w):
            scores["cs"] += 1

    # DE-specific
    de_words = ["und", "oder", "der", "die", "das", "preis", "marke", "zustand", "unter", "max", "bis", "ab", "von"]
    for w in de_words:
        if _word_match(text_lower, w):
            scores["de"] += 1

    # PL-specific
    pl_words = ["i", "lub", "cena", "marka", "stan", "parametry", "do", "max", "od", "powyżej"]
    for w in pl_words:
        if _word_match(text_lower, w):
            scores["pl"] += 1

    best = "en"
    best_score = 0
    # Preference order: SK first (primary market), then CS, DE, PL, EN
    for lang in ["sk", "cs", "de", "pl", "en"]:
        if scores[lang] > best_score:
            best = lang
            best_score = scores[lang]
    return best


def extract_condition(text: str, language: Language = "en") -> str | None:
    """Extract condition from text using language keywords."""
    text_lower = text.lower()
    keywords = CONDITION_KEYWORDS.get(language, CONDITION_KEYWORDS["en"])
    # Check longer phrases first
    for kw in sorted(keywords.keys(), key=len, reverse=True):
        if kw in text_lower:
            return keywords[kw]
    return None


def extract_category(text: str, language: Language = "en") -> str | None:
    """Extract category from text using language keywords."""
    text_lower = text.lower()
    keywords = CATEGORY_KEYWORDS.get(language, CATEGORY_KEYWORDS["en"])
    for kw in sorted(keywords.keys(), key=len, reverse=True):
        if kw in text_lower:
            return keywords[kw]
    return None


def extract_price(text: str, language: Language = "en") -> tuple[float | None, float | None]:
    """Extract min/max price from text using language keywords and regex.

    Returns (min_price, max_price). Numbers are EUR.
    """
    min_price: float | None = None
    max_price: float | None = None

    # Pattern groups: (regex, is_min_context)
    patterns = [
        (r"(?:do|under|max|maximal|bis|below|nejvíc|najviac)\s*(\d+(?:\.\d+)?)\s*(?:eur|€)?", False),
        (r"(?:od|from|above|over|powyżej|ab|von)\s*(\d+(?:\.\d+)?)\s*(?:eur|€)?", True),
        (r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:eur|€)?", None),
        (r"(\d+(?:\.\d+)?)\s*(?:eur|€)", False),
    ]

    text_lower = text.lower()
    for pattern, is_min in patterns:
        matches = re.findall(pattern, text_lower)
        if matches:
            match = matches[0]
            if isinstance(match, tuple):
                if len(match) == 2:
                    try:
                        p1, p2 = float(match[0]), float(match[1])
                        min_price = min(p1, p2)
                        max_price = max(p1, p2)
                    except ValueError:
                        pass
                elif len(match) == 1:
                    try:
                        val = float(match[0])
                        if is_min is True:
                            min_price = val
                        else:
                            max_price = val
                    except ValueError:
                        pass
            else:
                # Single capture group returned as string
                try:
                    val = float(match)
                    if is_min is True:
                        min_price = val
                    else:
                        max_price = val
                except ValueError:
                    pass

    return min_price, max_price


def extract_specs_from_text(text: str) -> dict[str, str]:
    """Extract spec-based filters from text (power, battery, weight, etc.)."""
    extras: dict[str, str] = {}
    text_lower = text.lower()

    for spec_key, keywords in SPEC_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                # Try to find a number near the keyword
                pattern = rf"(\d+(?:\.\d+)?)\s*{re.escape(kw)}"
                m = re.search(pattern, text_lower)
                if m:
                    extras[spec_key] = m.group(1)
                break

    return extras


def extract_brand(text: str) -> str | None:
    """Extract brand from text - first capitalised word that looks like a brand."""
    # Common brand patterns: "Citroen eC3", "Tesla Model 3", "BMW i3"
    match = re.match(r"\b([A-Z][a-zA-Zäöüß]+)\b", text.strip())
    if match:
        return match.group(1)
    return None


def extract_filters_from_specs(specs_dict: dict) -> ExtractedFilters:
    """Convert ItemSpecs research dict into ExtractedFilters for searching.

    Maps specs fields to SearchFilters-compatible fields:
    - price_eur -> max_price
    - power_kw -> extras["power_kw"]
    - battery_kwh -> extras["battery_kwh"]
    - weight_kg -> extras["weight_kg"]
    - battery_kwh + range_km -> extras for EV filtering
    - brand -> brand
    - category -> category
    """
    filters = ExtractedFilters(
        category=specs_dict.get("category"),
        brand=specs_dict.get("brand"),
        condition=specs_dict.get("condition", "any"),
        confidence=0.8,  # specs-based, not user prompt
    )

    if specs_dict.get("price_eur") is not None:
        filters.max_price = float(specs_dict["price_eur"])

    for spec_key in ("power_kw", "power_hp", "weight_kg", "length_mm", "width_mm",
                      "height_mm", "battery_kwh", "range_km"):
        val = specs_dict.get(spec_key)
        if val is not None:
            filters.extras[spec_key] = str(val)

    return filters


def extract_filters_from_prompt(prompt: str) -> ExtractedFilters:
    """Extract filters from a natural-language prompt using keyword heuristics.

    Falls back to deterministic keyword extraction when LLM is unavailable.
    Handles SK, CS, DE, PL, EN languages.
    """
    language = detect_language(prompt)
    min_price, max_price = extract_price(prompt, language)
    condition = extract_condition(prompt, language)
    category = extract_category(prompt, language)
    brand = extract_brand(prompt)
    extras = extract_specs_from_text(prompt)

    # Shipping hints
    shipping: Literal["free", "paid"] | None = None
    text_lower = prompt.lower()
    if any(k in text_lower for k in ["zadarmo", "zdarma", "kostenlos", "free", "darmowa"]):
        shipping = "free"
    elif any(k in text_lower for k in ["doprava", "poštovné", "poštovne", "dopravné", "shipping", "dostawa"]):
        shipping = "paid"

    # Sort hints
    sort: Literal["relevance", "price_asc", "price_desc", "newest"] | None = None
    if any(k in text_lower for k in ["najlacnejší", "nejlevnější", "günstigster", "najtańszy", "cheapest", "price_asc", "lowest"]):
        sort = "price_asc"
    elif any(k in text_lower for k in ["najdrahší", "nejdražší", "teuerster", "najdroższy", "most expensive", "price_desc"]):
        sort = "price_desc"
    elif any(k in text_lower for k in ["najnovší", "nejnovější", "neueste", "najnowsze", "newest"]):
        sort = "newest"

    return ExtractedFilters(
        min_price=min_price,
        max_price=max_price,
        condition=condition,
        category=category,
        brand=brand,
        shipping=shipping,
        sort=sort,
        extras=extras,
        language=language,
        confidence=0.7,  # keyword-based, not LLM
    )


def to_search_filters(extracted: ExtractedFilters):
    """Convert ExtractedFilters to SearchFilters for the searcher."""
    from src.searcher.filters import SearchFilters

    return SearchFilters(
        min_price=extracted.min_price,
        max_price=extracted.max_price,
        condition=extracted.condition or Condition.ANY,
        category=extracted.category or Category.ANY,
        brand=extracted.brand,
        location=extracted.location,
        shipping=extracted.shipping,
        seller_type=extracted.seller_type,
        sort=extracted.sort,
        extra_filters={f"{k}={v}" for k, v in extracted.extras.items()},
    )
