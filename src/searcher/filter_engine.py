"""Apply canonical filters to a site profile.

Order is deliberate: URL parameters first, UI controls second, and a final
Python-side pass for whatever the site ignored or did not expose.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import FilterSpec, SiteProfile

if TYPE_CHECKING:
    from src.searcher.adapters.base import Deal

logger = logging.getLogger(__name__)

FILTER_KEYS = (
    "price_min",
    "price_max",
    "condition",
    "brand",
    "location",
    "shipping",
    "seller_type",
    "sort",
)

# SearchFilters uses the public CLI names; profiles use the URL-oriented names.
_FILTER_FIELD = {
    "price_min": "min_price",
    "price_max": "max_price",
    "condition": "condition",
    "brand": "brand",
    "location": "location",
    "shipping": "shipping",
    "seller_type": "seller_type",
    "sort": "sort",
}


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"
    return str(value)


def _mapped(value_map: dict[str, str], value: str) -> str:
    if value in value_map:
        return value_map[value]
    return value_map.get(value.lower(), value)


class FilterEngine:
    """Build filtered URLs, drive UI controls and enforce residual filters."""

    @staticmethod
    def _filter_values(filters: SearchFilters) -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        for key in FILTER_KEYS:
            value = getattr(filters, _FILTER_FIELD[key], None)
            if value is not None and value != "":
                values.append((key, _format_value(value)))
        values.extend((str(key), _format_value(value)) for key, value in filters.extras.items())
        return values

    @staticmethod
    def _set_query(url: str, param: str, value: str) -> str:
        parsed = urlparse(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        replaced = False
        updated: list[tuple[str, str]] = []
        for key, old_value in pairs:
            if key == param:
                if not replaced:
                    updated.append((key, value))
                    replaced = True
                continue
            updated.append((key, old_value))
        if not replaced:
            updated.append((param, value))
        query = urlencode(updated)
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
        )

    @classmethod
    def build_search_url(
        cls,
        profile: SiteProfile,
        query: str,
        category: str = "any",
        filters: SearchFilters | None = None,
    ) -> str | None:
        """Build the best URL the profile exposes for this query/category.

        Returns ``None`` when the profile has no search URL at all, so the
        adapter's own default URL remains the fallback.
        """
        filters = filters or SearchFilters()
        base: str | None = None
        if category and category != "any":
            base = profile.search.category_urls.get(category)
        if not base:
            base = profile.search.url_template
        if not base:
            return None

        url = base
        if "{query}" in url:
            url = url.replace("{query}", quote_plus(query or ""))
        elif query and profile.search.query_param:
            url = cls._set_query(url, profile.search.query_param, query)

        for key, value in cls._filter_values(filters):
            spec: FilterSpec | None = getattr(profile.filters, key, None)
            if spec is None:
                spec = profile.filters.extras.get(key)
            if spec is None or spec.url is None:
                continue
            url = cls._set_query(url, spec.url.param, _mapped(spec.url.value_map, value))
        return url

    @classmethod
    async def apply_ui(
        cls,
        page: Any,
        profile: SiteProfile,
        filters: SearchFilters | None = None,
    ) -> list[str]:
        """Apply supported filters through page controls.

        One broken selector must not stop the remaining filters. Returns the
        canonical keys that were successfully applied.
        """
        filters = filters or SearchFilters()
        applied: list[str] = []
        for key, value in cls._filter_values(filters):
            spec: FilterSpec | None = getattr(profile.filters, key, None)
            if spec is None:
                spec = profile.filters.extras.get(key)
            ui = spec.ui if spec else None
            if ui is None:
                continue
            mapped = _mapped(ui.value_map, value)
            try:
                if ui.kind == "input":
                    await page.fill(ui.selector, mapped)
                elif ui.kind == "select":
                    try:
                        await page.select_option(ui.selector, value=mapped)
                    except Exception:  # noqa: BLE001 - sites differ between value/label
                        await page.select_option(ui.selector, label=mapped)
                elif ui.kind in ("checkbox", "radio"):
                    selector = (
                        ui.selector.replace("{value}", mapped)
                        if "{value}" in ui.selector
                        else ui.selector
                    )
                    try:
                        await page.check(selector)
                    except Exception:  # noqa: BLE001 - custom controls are often not real inputs
                        await page.click(selector)
                elif ui.kind == "button":
                    selector = (
                        ui.selector.replace("{value}", mapped)
                        if "{value}" in ui.selector
                        else ui.selector
                    )
                    await page.click(selector)
                if ui.wait_selector:
                    await page.wait_for_selector(ui.wait_selector, timeout=5000)
                applied.append(key)
            except Exception as exc:  # noqa: BLE001 - optional UI filters must not abort search
                logger.debug(
                    "[%s] UI filter %s failed for %r: %s",
                    profile.site_id,
                    key,
                    mapped,
                    exc,
                )
        return applied

    @staticmethod
    def _price(deal: Any) -> float:
        try:
            return float(deal.price_eur or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _matches(cls, deal: Any, filters: SearchFilters) -> bool:
        price = cls._price(deal)
        if price > 0:
            if filters.min_price is not None and price < filters.min_price:
                return False
            if filters.max_price is not None and price > filters.max_price:
                return False

        if filters.condition:
            condition = (getattr(deal, "condition", "") or "").lower()
            if condition and condition != "unknown" and condition != filters.condition:
                return False

        metadata = getattr(deal, "metadata", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}

        if filters.brand:
            brand = metadata.get("brand")
            if brand is not None and filters.brand.lower() not in str(brand).lower():
                return False

        if filters.location:
            location = metadata.get("location")
            if location is not None and filters.location.lower() not in str(location).lower():
                return False

        if filters.seller_type:
            seller = metadata.get("seller_type") or metadata.get("seller")
            if seller is not None and filters.seller_type.lower() not in str(seller).lower():
                return False

        if filters.shipping:
            shipping = metadata.get("shipping")
            if shipping is not None:
                text = str(shipping).lower()
                free = any(token in text for token in ("free", "zdarma", "0", "true"))
                if filters.shipping == "free" and not free:
                    return False
                if filters.shipping == "paid" and free:
                    return False

        for key, expected in filters.extras.items():
            if key in metadata:
                if str(metadata[key]).lower() != expected.lower():
                    return False
        return True

    @classmethod
    def post_filter(cls, deals: list[Deal], filters: SearchFilters | None = None) -> list[Deal]:
        """Enforce filters that the site did not apply itself."""
        filters = filters or SearchFilters()
        if filters.is_empty():
            return list(deals)

        result = [deal for deal in deals if cls._matches(deal, filters)]
        if filters.sort in ("price_asc", "price_desc"):
            known = [deal for deal in result if cls._price(deal) > 0]
            unknown = [deal for deal in result if cls._price(deal) <= 0]
            known.sort(key=cls._price, reverse=filters.sort == "price_desc")
            result = known + unknown
        return result
