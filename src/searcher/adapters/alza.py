import logging
from typing import ClassVar
from urllib.parse import quote_plus

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import SiteProfile

from .base import BaseAdapter, Deal, SiteBlockedError

logger = logging.getLogger(__name__)


class AlzaAdapter(BaseAdapter):
    name = "alza"
    base_url = "https://www.alza.sk"
    # Verified against the live DOM: alza.sk/search.htm?exps=... returns
    # div.browsingitem containers; the old .browsinglink selector matched 0.
    results_selector = ".browsingitemcontainer"
    item_selector = ".browsingitem"
    supported_conditions: ClassVar[list[str]] = ["new", "open_box"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances"]
    seller_type = "retailer"
    has_warranty = True
    warranty_note = "New items carry the manufacturer warranty; open-box carries Alza's warranty."

    async def search(
        self,
        page: Page,
        query: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
        category: str = "any",
        profile: SiteProfile | None = None,
    ) -> list[Deal]:
        # /search is a 404 on alza.sk; the real endpoint is /search.htm?exps=
        try:
            await self._goto_search(page, query, filters, category, profile)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] Navigation error: {e}")
            return []

        blocked = await self.detect_block(page)
        if blocked:
            raise SiteBlockedError(f"{self.name}: {blocked}")  # noqa: TRY003

        try:
            await page.wait_for_selector(self.item_selector, timeout=20000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] results not found: {e}")
            return []

        applied = await self._apply_filters(page, filters, profile)
        if applied:
            try:
                await page.wait_for_selector(self.item_selector, timeout=10000)
            except PlaywrightError as e:
                logger.debug(f"[{self.name}] filtered results not found: {e}")
                return []

        deals = []
        for el in (await page.query_selector_all(self.item_selector))[:max_results]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
        return deals

    def default_search_url(self, query: str) -> str:
        return f"{self.base_url}/search.htm?exps={quote_plus(query)}"

    async def extract_deal(self, page: Page, element) -> Deal | None:
        try:
            name_el = await element.query_selector(".name")
            price_el = await element.query_selector(".price")
            link_el = await element.query_selector(".browsinglink") or await element.query_selector("a")

            if not name_el or not price_el or not link_el:
                return None

            title = " ".join((await name_el.inner_text()).split())
            parsed = self.parse_price_with_currency(await price_el.inner_text())
            if not title or parsed is None:
                return None
            price_eur, original_price, original_currency = parsed

            url = await link_el.get_attribute("href")
            if not url:
                return None
            if not url.startswith("http"):
                url = f"{self.base_url}{url}"

            # Alza flags open-box with an "almost new" data attribute.
            almost_new = (await element.get_attribute("data-almostnew") or "").lower()
            text = (await element.inner_text()).lower()
            condition = "open_box" if almost_new == "true" or "rozbalen" in text else "new"

            description_el = await element.query_selector(".Description")
            description = (
                " ".join((await description_el.inner_text()).split())
                if description_el
                else ""
            )
            rating_el = await element.query_selector(".star-rating-block__value")
            rating = (await rating_el.inner_text()).strip() if rating_el else ""
            reviews_el = await element.query_selector(".star-rating-block__count")
            reviews = (
                (await reviews_el.inner_text()).strip().rstrip("\u00d7x")
                if reviews_el
                else ""
            )

            return Deal(
                url=url.split("?")[0],
                title=title,
                price_eur=price_eur,
                condition=condition,
                category="electronics",
                site_name=self.name,
                metadata={
                    "source": "alza",
                    "code": await element.get_attribute("data-code") or "",
                    "description": description,
                    "rating": rating,
                    "reviews": reviews,
                    "original_price": original_price,
                    "original_currency": original_currency,
                },
                original_price=original_price,
                original_currency=original_currency,
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as e:
            logger.debug(f"[{self.name}] Extract error: {e}")
            return None