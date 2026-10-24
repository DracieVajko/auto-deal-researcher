"""Generic adapter driven entirely by a validated SiteProfile."""

from __future__ import annotations

import logging
import unicodedata
from typing import ClassVar
from urllib.parse import quote_plus, urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import SiteProfile

from .base import BaseAdapter, Deal, SiteBlockedError

logger = logging.getLogger(__name__)


def _strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


class ProfileAdapter(BaseAdapter):
    """Extract listings using selectors recorded in a site profile."""

    name = "profile"
    supported_conditions: ClassVar[list[str]] = ["new", "used", "refurbished", "open_box", "marketplace"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]

    def __init__(
        self,
        base_url: str | None = None,
        profile: SiteProfile | None = None,
        currency: str | None = None,
    ):
        super().__init__(base_url, currency)
        self.profile = profile
        if profile is not None:
            self.name = profile.site_id
            if profile.extraction.item_selector:
                self.item_selector = profile.extraction.item_selector
            if profile.base_url:
                self.base_url = profile.base_url.rstrip("/")
            # An explicitly passed currency (the registry) wins over the one
            # stored in the profile, which may predate the currency layer.
            if profile.currency and not currency:
                self.currency = profile.currency.upper()

    def default_search_url(self, query: str) -> str:
        if self.profile and self.profile.search.url_template:
            return self.profile.search.url_template.replace("{query}", quote_plus(query))
        if self.profile and self.profile.search.query_param:
            return f"{self.base_url}/?{self.profile.search.query_param}={quote_plus(query)}"
        return f"{self.base_url}/"

    async def search(
        self,
        page: Page,
        query: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
        category: str = "any",
        profile: SiteProfile | None = None,
    ) -> list[Deal]:
        profile = profile or self.profile
        if profile is None or not profile.is_runtime_ready:
            return []
        self.profile = profile

        try:
            await self._goto_search(page, query, filters, category, profile)
        except PlaywrightError as exc:
            logger.debug("[%s] navigation failed: %s", profile.site_id, exc)
            return []

        blocked = await self.detect_block(page)
        if blocked:
            raise SiteBlockedError(f"{profile.site_id}: {blocked}")  # noqa: TRY003

        if self.item_selector:
            try:
                await page.wait_for_selector(self.item_selector, timeout=20000)
            except PlaywrightError as exc:
                logger.debug("[%s] results not found: %s", profile.site_id, exc)
                return []

        applied = await self._apply_filters(page, filters, profile)
        if applied and self.item_selector:
            try:
                await page.wait_for_selector(self.item_selector, timeout=10000)
            except PlaywrightError as exc:
                logger.debug("[%s] filtered results not found: %s", profile.site_id, exc)
                return []

        elements = await page.query_selector_all(self.item_selector) if self.item_selector else []
        deals: list[Deal] = []
        for element in elements[:max_results]:
            deal = await self.extract_deal(page, element)
            if deal is not None:
                deals.append(deal)
        return deals

    async def _text(self, element, selector: str | None) -> str:
        if not selector:
            return ""
        try:
            child = await element.query_selector(selector)
            if child is None:
                return ""
            return " ".join((await child.inner_text()).split())
        except (PlaywrightError, AttributeError, TypeError):
            return ""

    async def extract_deal(self, page: Page, element) -> Deal | None:
        if self.profile is None:
            return None
        extraction = self.profile.extraction
        try:
            title = await self._text(element, extraction.title_selector)
            if not title:
                text = " ".join((await element.inner_text()).split())
                title = text[:200]

            price_text = await self._text(element, extraction.price_selector)
            if not price_text:
                price_text = " ".join((await element.inner_text()).split())
            parsed = self.parse_price_with_currency(price_text)
            if not title or parsed is None:
                return None
            price_eur, original_price, original_currency = parsed

            link_el = None
            if extraction.link_selector:
                link_el = await element.query_selector(extraction.link_selector)
            if link_el is None:
                link_el = await element.query_selector("a[href]")
            url = await link_el.get_attribute("href") if link_el else None
            if not url:
                url = await element.get_attribute("href")
            if not url:
                return None
            url = urljoin(f"{self.base_url}/", url)

            condition_text = await self._text(element, extraction.condition_selector)
            condition = self._detect_condition(condition_text or title)

            metadata: dict[str, str] = {
                "source": "profile",
                "original_price": original_price,
                "original_currency": original_currency,
            }
            for key, selector in (
                ("brand", extraction.brand_selector),
                ("seller", extraction.seller_selector),
                ("seller_type", extraction.seller_type_selector),
                ("location", extraction.location_selector),
                ("shipping", extraction.shipping_selector),
            ):
                value = await self._text(element, selector)
                if value:
                    metadata[key] = value
            image = await self._text(element, extraction.image_selector)
            if image:
                metadata["image"] = image

            return Deal(
                url=url.split("?")[0],
                title=title,
                price_eur=price_eur,
                condition=condition,
                category="general",
                site_name=self.profile.site_id,
                metadata=metadata,
                original_price=original_price,
                original_currency=original_currency,
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as exc:
            logger.debug("[%s] extract error: %s", self.profile.site_id, exc)
            return None

    @staticmethod
    def _detect_condition(text: str) -> str:
        normalised = _strip_diacritics(text).lower()
        if "open box" in normalised or "openbox" in normalised or "rozbalen" in normalised:
            return "open_box"
        if "refurbished" in normalised or "repasovan" in normalised or "rekonstruovan" in normalised:
            return "refurbished"
        if "new" in normalised or "novy" in normalised or "nove" in normalised:
            return "new"
        if "used" in normalised or "pouzit" in normalised or "bazar" in normalised:
            return "used"
        return "unknown"
