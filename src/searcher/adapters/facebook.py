import logging
from typing import ClassVar
from urllib.parse import quote_plus

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import SiteProfile

from .base import BaseAdapter, Deal

logger = logging.getLogger(__name__)


class FacebookAdapter(BaseAdapter):
    name = "facebook"
    base_url = "https://www.facebook.com"
    requires_login = True
    supported_conditions: ClassVar[list[str]] = ["used", "marketplace"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general", "home", "hobby"]
    seller_type = "classifieds"
    has_warranty = False
    warranty_note = "Private sellers; warranty depends on the seller."
    results_selector = '[role="feed"]'
    item_selector = '[role="feed"] > div > div > div > div > a'

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
            await self._goto_search(
                page, query, filters, category, profile,
                wait_until="networkidle", timeout=45000,
            )
            await page.wait_for_selector(self.results_selector, timeout=20000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] Navigation error: {e}")
            return []

        applied = await self._apply_filters(page, filters, profile)
        if applied:
            try:
                await page.wait_for_selector(self.results_selector, timeout=10000)
            except PlaywrightError as e:
                logger.debug(f"[{self.name}] filtered results not found: {e}")
                return []

        deals = []
        elements = await page.query_selector_all(self.item_selector)
        for el in elements[:max_results]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
        return deals

    def default_search_url(self, query: str) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/marketplace"):
            return f"{base}/search/?query={quote_plus(query)}"
        return f"{base}/marketplace/search/?query={quote_plus(query)}"

    async def extract_deal(self, page: Page, element) -> Deal | None:
        try:
            # Facebook Marketplace structure is complex and changes frequently
            # This is a best-effort extraction
            title_el = await element.query_selector('span[dir="auto"]')
            price_el = await element.query_selector('span:has-text("€")')
            url = await element.get_attribute("href")

            if not title_el or not url:
                return None

            title = await title_el.inner_text()
            price_text = await price_el.inner_text() if price_el else "0 €"

            parsed = self.parse_price_with_currency(price_text)
            price_eur, original_price, original_currency = parsed or (0.0, 0.0, "EUR")

            condition = "used"

            # Ensure full URL
            if url and not url.startswith("http"):
                url = f"{self.base_url}{url}"

            return Deal(
                url=url,
                title=title.strip(),
                price_eur=price_eur,
                condition=condition,
                category="general",
                site_name=self.name,
                metadata={
                    "source": "facebook",
                    "original_price": original_price,
                    "original_currency": original_currency,
                },
                original_price=original_price,
                original_currency=original_currency,
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as e:
            logger.debug(f"[{self.name}] Extract error: {e}")
            return None