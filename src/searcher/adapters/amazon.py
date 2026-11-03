"""Amazon.de search adapter (browser scraping with the user's cookies)."""

import logging
from typing import ClassVar
from urllib.parse import quote_plus

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from src.searcher.filters import SearchFilters
from src.searcher.pricing import build_price_quote, extract_price_signals
from src.searcher.site_profiles import SiteProfile

from .base import BaseAdapter, Deal, SiteBlockedError

logger = logging.getLogger(__name__)


class AmazonAdapter(BaseAdapter):
    name = "amazon"
    base_url = "https://www.amazon.de"
    results_selector = 'div[data-component-type="s-search-result"]'
    item_selector = 'div[data-component-type="s-search-result"]'
    supported_conditions: ClassVar[list[str]] = [
        "new",
        "used",
        "refurbished",
        "open_box",
    ]
    supported_categories: ClassVar[list[str]] = [
        "electronics",
        "appliances",
        "auto",
        "general",
        "home",
        "hobby",
    ]
    seller_type = "marketplace"
    has_warranty = False
    warranty_note = "Amazon returns; third-party warranty varies."

    async def search(
        self,
        page: Page,
        query: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
        category: str = "any",
        profile: SiteProfile | None = None,
    ) -> list[Deal]:
        try:
            await self._goto_search(page, query, filters, category, profile)
        except PlaywrightError as exc:
            logger.debug("[%s] navigation failed: %s", self.name, exc)
            return []

        blocked = await self.detect_block(page)
        if blocked:
            raise SiteBlockedError(f"{self.name}: {blocked}")  # noqa: TRY003

        try:
            await page.wait_for_selector(self.item_selector, timeout=20000)
        except PlaywrightError as exc:
            logger.debug("[%s] results not found: %s", self.name, exc)
            return []

        applied = await self._apply_filters(page, filters, profile)
        if applied:
            try:
                await page.wait_for_selector(self.item_selector, timeout=10000)
            except PlaywrightError as exc:
                logger.debug("[%s] filtered results not found: %s", self.name, exc)
                return []

        deals: list[Deal] = []
        for element in (await page.query_selector_all(self.item_selector))[:max_results]:
            deal = await self.extract_deal(page, element)
            if deal is not None:
                deals.append(deal)
        return deals

    def default_search_url(self, query: str) -> str:
        return f"{self.base_url}/s?k={quote_plus(query)}"

    async def detect_block(self, page: Page) -> str | None:
        base = await super().detect_block(page)
        if base:
            return base
        try:
            url = (page.url or "").lower()
            title = ((await page.title()) or "").lower()
        except Exception:  # noqa: BLE001 - page may already be closed
            return None
        if "validatecaptcha" in url or "robot check" in title:
            return "amazon captcha"
        if "enter the characters you see below" in title:
            return "amazon captcha"
        return None

    async def extract_deal(self, page: Page, element) -> Deal | None:
        try:
            title_el = (
                await element.query_selector("h2 a span")
                or await element.query_selector("h2 span")
            )
            price_el = await element.query_selector(".a-price .a-offscreen")
            link_el = (
                await element.query_selector("h2 a")
                or await element.query_selector("a.a-link-normal")
            )
            if not title_el or not price_el or not link_el:
                return None

            title = " ".join((await title_el.inner_text()).split())
            price_text = await price_el.inner_text()
            url = await link_el.get_attribute("href")
            if not title or not url:
                return None
            if url.startswith("/"):
                url = f"{self.base_url}{url}"
            if not url.startswith("http"):
                return None

            parsed = self.parse_price_with_currency(price_text)
            if parsed is None:
                return None
            price_eur, original_price, original_currency = parsed

            full_text = " ".join((await element.inner_text()).split())
            condition = self._detect_condition(f"{title} {full_text}")
            signals = extract_price_signals(full_text, price_eur, original_currency)

            return Deal(
                url=url.split("?")[0],
                title=title,
                price_eur=price_eur,
                condition=condition,
                category="general",
                site_name=self.name,
                metadata={
                    "source": "amazon",
                    "original_price": original_price,
                    "original_currency": original_currency,
                    "card_text": full_text[:2000],
                },
                original_price=original_price,
                original_currency=original_currency,
                price_quote=build_price_quote(
                    price_eur,
                    kind=signals.kind,
                    shipping=signals.shipping,
                    bundle=signals.bundle,
                    price_from=signals.price_from,
                    price_max_eur=signals.price_max_eur,
                    regular_price_eur=signals.regular_price_eur,
                    evidence=signals.evidence,
                    source="regex",
                    confidence=signals.confidence,
                    warnings=signals.warnings,
                ),
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as exc:
            logger.debug("[%s] extract error: %s", self.name, exc)
            return None

    @staticmethod
    def _detect_condition(text: str) -> str:
        lowered = text.lower()
        if "refurbished" in lowered or "renewed" in lowered:
            return "refurbished"
        if "open box" in lowered or "opened" in lowered:
            return "open_box"
        if "used" in lowered or "gebraucht" in lowered:
            return "used"
        return "new"
