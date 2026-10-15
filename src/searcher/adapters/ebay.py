import asyncio
import logging
from typing import ClassVar
from urllib.parse import quote_plus

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .base import BaseAdapter, Deal, SiteBlockedError

logger = logging.getLogger(__name__)

# eBay serves results only intermittently from automated sessions: a direct
# /sch/i.html hit frequently returns 403 or an empty result grid. Driving the
# site through its own search box (which sets the trksid/session cookies)
# succeeds far more often, so it is used as a fallback path.
SEARCH_INPUT = 'input[name="_nkw"]'
# Verified live: result cards are .s-card (the old .s-item class is gone).
ITEM_SELECTORS = (".s-card", ".s-item")
SEARCH_ATTEMPTS = 3


class EbayAdapter(BaseAdapter):
    name = "ebay"
    base_url = "https://www.ebay.de"
    results_selector = ".srp-results"
    item_selector = ".s-card"
    supported_conditions: ClassVar[list[str]] = ["used", "refurbished", "new", "open_box"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]

    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        search_url = f"{self.base_url}/sch/i.html?_nkw={quote_plus(query)}&_sacat=0"

        cards = []
        for attempt in range(SEARCH_ATTEMPTS):
            cards = await self._collect_cards(page, search_url)
            if not cards:
                cards = await self._collect_via_search_box(page, query)
            if cards:
                break
            logger.debug(f"[{self.name}] attempt {attempt + 1} returned no cards")
            await asyncio.sleep(2)

        deals = []
        for el in cards[: max_results * 3]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
                if len(deals) >= max_results:
                    break
        return deals

    async def _collect_cards(self, page: Page, url: str) -> list:
        """Navigate directly to the search URL and wait for result cards."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] direct navigation failed: {e}")
            return []

        if await self.detect_block(page):
            return []

        return await self._wait_for_cards(page)

    async def _collect_via_search_box(self, page: Page, query: str) -> list:
        """Fallback: use the site's own search box to reach the result page."""
        try:
            await page.goto(f"{self.base_url}/", wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2500)
            box = await page.query_selector(SEARCH_INPUT)
            if not box:
                logger.debug(f"[{self.name}] search box not found")
                return []
            await box.fill(query)
            await box.press("Enter")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=25000)
            except PlaywrightError:
                pass
            if await self.detect_block(page):
                raise SiteBlockedError(f"{self.name}: blocked during search-box flow")
            return await self._wait_for_cards(page)
        except SiteBlockedError:
            raise
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] search-box flow failed: {e}")
            return []

    async def _wait_for_cards(self, page: Page) -> list:
        """Poll for result cards; eBay hydrates them asynchronously."""
        for _ in range(6):
            for sel in ITEM_SELECTORS:
                cards = await page.query_selector_all(sel)
                if cards:
                    return cards
            await asyncio.sleep(2)
        return []

    async def extract_deal(self, page: Page, element) -> Deal | None:
        try:
            title_el = (
                await element.query_selector(".s-card__title")
                or await element.query_selector(".s-item__title")
                or await element.query_selector("h3")
            )
            price_el = (
                await element.query_selector(".s-card__price")
                or await element.query_selector(".s-item__price")
            )
            link_el = await element.query_selector('a[href*="/itm/"]')
            subtitle_el = (
                await element.query_selector(".s-card__subtitle")
                or await element.query_selector(".s-item__subtitle")
            )

            if not title_el or not price_el or not link_el:
                return None

            title = " ".join((await title_el.inner_text()).split())
            url = await link_el.get_attribute("href")
            if not title or not url or "/itm/" not in url:
                return None
            # Drop "Shop on eBay" placeholder / sponsored tiles.
            if title.lower().startswith("shop on ebay"):
                return None

            price_eur = self.parse_price_eur(await price_el.inner_text())
            if price_eur is None:
                return None

            subtitle = " ".join((await subtitle_el.inner_text()).split()) if subtitle_el else ""
            condition = self._detect_condition(f"{title} {subtitle}")

            return Deal(
                url=url.split("?")[0],
                title=title,
                price_eur=price_eur,
                condition=condition,
                category="electronics",
                site_name=self.name,
                metadata={"source": "ebay", "subtitle": subtitle[:120]},
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as e:
            logger.debug(f"[{self.name}] Extract error: {e}")
            return None

    @staticmethod
    def _detect_condition(text: str) -> str:
        t = text.lower()
        if "refurbished" in t or "generalüberholt" in t or "generaluberholt" in t:
            return "refurbished"
        if "open box" in t or "opened" in t:
            return "open_box"
        if "new" in t or "neu" in t:
            return "new"
        return "used"