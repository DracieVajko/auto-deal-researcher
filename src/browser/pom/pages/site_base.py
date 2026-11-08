"""Generic site page objects reusing POM components."""

import logging

from src.browser.pom.base import BasePage
from src.browser.pom.components.filters import Filters
from src.browser.pom.components.pagination import Pagination
from src.browser.pom.components.product_card import ProductCard
from src.browser.pom.components.search_bar import SearchBar
from src.browser.pom.components.sort import Sort

logger = logging.getLogger(__name__)




class SiteHome(BasePage):
    """Generic home page."""

    SEARCH_URL_TEMPLATE = "{base_url}"

    def __init__(self, page, base_url: str = ""):
        super().__init__(page)
        self.base_url = base_url
        self.search_bar = SearchBar(page)

    async def goto(self, url: str | None = None) -> None:
        await super().goto(url or self.base_url)


class SiteSearchResults(BasePage):
    """Generic search results page."""

    CARD_SELECTOR = ".product-card, .item, [data-product]"

    def __init__(self, page):
        super().__init__(page)
        self.filters = Filters(page)
        self.pagination = Pagination(page)
        self.sort = Sort(page)

    async def extract_cards(self) -> list[dict]:
        try:
            els = await self.page.query_selector_all(self.CARD_SELECTOR)
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.debug("Card selector query failed: %s", exc)
            return []
        out = []
        for el in els[:20]:
            try:
                html = await el.evaluate("(e) => e.outerHTML")
                parsed = ProductCard.extract_from_html(html)
                if parsed:
                    out.append(parsed)
            except Exception as exc:  # noqa: BLE001 - card parsing is best-effort
                logger.debug("Product card parse failed: %s", exc)
                continue
        return out


class SiteProductDetail(BasePage):
    """Generic product detail page."""

    async def parse(self) -> dict:
        try:
            title = await self.page.text_content("h1")
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.debug("Title extraction failed: %s", exc)
            title = "Unknown"
        return {"title": (title or "Unknown").strip()}
