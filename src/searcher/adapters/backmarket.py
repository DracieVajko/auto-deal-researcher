import logging
from typing import ClassVar
from urllib.parse import quote_plus

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .base import BaseAdapter, Deal, SiteBlockedError

logger = logging.getLogger(__name__)


class BackMarketAdapter(BaseAdapter):
    name = "backmarket"
    base_url = "https://www.backmarket.sk"
    # The locale-aware path is /sk-sk/search (not /search).
    results_selector = '[data-testid="product-card"]'
    item_selector = '[data-testid="product-card"]'
    supported_conditions: ClassVar[list[str]] = ["refurbished"]
    supported_categories: ClassVar[list[str]] = ["electronics"]
    seller_type = "marketplace"
    has_warranty = True
    warranty_note = "BackMarket provides its own warranty on refurbished items."

    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        search_url = f"{self.base_url}/sk-sk/search?q={quote_plus(query)}"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] Navigation error: {e}")
            return []

        # BackMarket sits behind a Cloudflare interstitial that does not clear
        # for automated sessions. Fail fast with the reason instead of burning
        # the full selector timeout on every run.
        blocked = await self.detect_block(page)
        if blocked:
            raise SiteBlockedError(f"{self.name}: {blocked} (session cannot be scraped)")

        try:
            await page.wait_for_selector(self.item_selector, timeout=20000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] results not found: {e}")
            return []

        deals = []
        for el in (await page.query_selector_all(self.item_selector))[:max_results]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
        return deals

    async def extract_deal(self, page: Page, element) -> Deal | None:
        try:
            title_el = (
                await element.query_selector('[data-testid="product-title"]')
                or await element.query_selector("h2, h3")
            )
            price_el = (
                await element.query_selector('[data-testid="product-price"]')
                or await element.query_selector('[data-qa="product-price"]')
            )
            link_el = await element.query_selector('a[href*="/p/"]') or await element.query_selector("a")

            if not title_el or not price_el or not link_el:
                return None

            title = " ".join((await title_el.inner_text()).split())
            price_eur = self.parse_price_eur(await price_el.inner_text())
            if not title or price_eur is None:
                return None

            url = await link_el.get_attribute("href")
            if not url:
                return None
            if not url.startswith("http"):
                url = f"{self.base_url}{url}"

            return Deal(
                url=url.split("?")[0],
                title=title,
                price_eur=price_eur,
                condition="refurbished",
                category="electronics",
                site_name=self.name,
                metadata={"source": "backmarket"},
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as e:
            logger.debug(f"[{self.name}] Extract error: {e}")
            return None