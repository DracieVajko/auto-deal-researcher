"""Product card component."""

import re


class ProductCard:
    """Reusable product card parser.

    Intentionally a stateless parser (not a BasePage subclass) because it
    operates on already-fetched HTML strings rather than a live page, so it
    needs no browser context or selectors registry.
    """

    @staticmethod
    def extract_from_html(html: str) -> dict | None:
        if not html:
            return None
        title_m = re.search(r"<(?:h[1-3]|a|span)[^>]*>([^<]{3,200})<", html)
        price_m = re.search(r"(\d[\d\s.,]*)\s*(€|EUR|CZK|Kč)", html, re.IGNORECASE)
        return {
            "title": title_m.group(1).strip() if title_m else "Unknown",
            "price_raw": price_m.group(0) if price_m else "",
            "html_len": len(html),
        }

    @staticmethod
    def normalize_price(price_raw: str) -> float:
        m = re.search(r"(\d[\d\s.,]*)", price_raw or "")
        if not m:
            return 0.0
        num = m.group(1).replace(" ", "").replace(",", ".")
        try:
            return float(num)
        except ValueError:
            return 0.0
