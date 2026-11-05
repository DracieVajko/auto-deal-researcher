"""Generic product card extraction from arbitrary e-commerce pages.

Provides CSS-selector-based extraction of title, price, availability, and URL
from listing cards. Each site can override selectors, with regex fallbacks
for common patterns.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from playwright.async_api import ElementHandle

logger = logging.getLogger(__name__)


@dataclass
class ProductCard:
    """Extracted data from one listing card."""

    title: str
    price_eur: float
    url: str
    site_name: str
    condition: Literal["new", "used", "refurbished", "open_box", "unknown"] = "unknown"
    availability: str = "unknown"
    seller_name: str = ""
    image_url: str | None = None
    extras: dict = field(default_factory=dict)


# Default CSS selectors that work on many marketplace sites.
DEFAULT_SELECTORS = {
    "card": ".product, .listing, .item, .ad-item, .offer, article, [data-testid='product-card']",
    "title": "h1, h2, h3, .title, .product-title, .item-title, [data-testid='product-title']",
    "price": ".price, .product-price, .item-price, [data-testid='price'], .amount",
    "url": "a[href]",
    "availability": ".availability, .stock, .availability-status",
    "seller": ".seller, .shop-name, .vendor",
    "image": "img",
}


def _extract_text(element: ElementHandle, selector: str) -> str:
    """Extract text content from the first element matching selector."""
    try:
        sub = element.query_selector(selector)
        if sub:
            return (sub.inner_text() or "").strip()
    except Exception:
        pass
    return ""


def _extract_attr(element: ElementHandle, selector: str, attr: str) -> str | None:
    """Extract an attribute from the first element matching selector."""
    try:
        sub = element.query_selector(selector)
        if sub:
            return sub.get_attribute(attr)
    except Exception:
        pass
    return None


def _parse_price(text: str) -> float | None:
    """Parse the first EUR price from text."""
    if not text:
        return None
    # Remove currency symbols and spaces, keep digits and dot/comma
    cleaned = re.sub(r"[^\d.,]", "", text)
    if not cleaned:
        return None
    # European format: "1.234,56" -> 1234.56 (comma is decimal)
    # US format: "1,234.56" -> 1234.56 (dot is decimal)
    # "18.990" (only dot, 3 digits after) -> 18990 (European thousands)
    if "," in cleaned and "." in cleaned:
        last_comma = cleaned.rfind(",")
        last_dot = cleaned.rfind(".")
        if last_comma > last_dot:
            # European: remove dots (thousands), replace comma with dot
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: remove commas (thousands), keep dot
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Could be European decimal or thousands separator
        parts = cleaned.split(",")
        if len(parts[-1]) == 2:
            # Likely European decimal: "1234,56"
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Likely thousands: "1,234"
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        # Only dot: if 3 digits after dot -> European thousands (18.990 = 18990)
        # if 1-2 digits after dot -> US decimal (18.99 = 18.99)
        parts = cleaned.split(".")
        if len(parts[-1]) == 3 and len(parts) == 2:
            cleaned = cleaned.replace(".", "")
        # else: keep as-is (decimal)
    try:
        return float(cleaned)
    except ValueError:
        return None


async def extract_product_card(
    card_element: ElementHandle,
    site_name: str,
    selectors: dict | None = None,
    base_url: str = "",
) -> ProductCard | None:
    """Extract a ProductCard from a Playwright element handle.

    Uses configurable CSS selectors with sensible defaults. Returns None if
    the card doesn't contain a title or price (likely not a real listing).
    """
    sel = {**DEFAULT_SELECTORS, **(selectors or {})}

    title = _extract_text(card_element, sel["title"])
    if not title:
        return None  # Not a real listing card

    price_text = _extract_text(card_element, sel["price"])
    price_eur = _parse_price(price_text) if price_text else None
    if price_eur is None:
        return None  # Can't determine price

    # Extract URL - try the card's own link or the title's link
    url = _extract_attr(card_element, sel["url"], "href")
    if url and base_url and not url.startswith("http"):
        from urllib.parse import urljoin
        url = urljoin(base_url, url)

    condition_text = _extract_text(card_element, sel.get("availability", ""))
    condition = _detect_condition(condition_text + " " + title)

    availability = _extract_text(card_element, sel.get("availability", ""))
    seller = _extract_text(card_element, sel.get("seller", ""))
    image_url = _extract_attr(card_element, sel.get("image", ""), "src")

    return ProductCard(
        title=title,
        price_eur=price_eur,
        url=url or "",
        site_name=site_name,
        condition=condition,
        availability=availability,
        seller_name=seller,
        image_url=image_url,
    )


def _detect_condition(text: str) -> str:
    """Detect condition from text using keyword matching."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["nový", "nové", "novo", "neu", "new", "nowe"]):
        return "new"
    if any(k in text_lower for k in ["repasované", "refurbished", "aufgearbeitet", "generalüberholt", "odnowione"]):
        return "refurbished"
    if any(k in text_lower for k in ["open box", "otevřená", "otevrena", "offene verpackung", "otwarte opakowanie"]):
        return "open_box"
    if any(k in text_lower for k in ["použité", "pouzite", "použité", "gebraucht", "used", "używane"]):
        return "used"
    return "unknown"
