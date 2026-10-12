import re
from typing import ClassVar

from playwright.async_api import Page

from .base import BaseAdapter, Deal


class FacebookAdapter(BaseAdapter):
    name = "facebook"
    base_url = "https://www.facebook.com"
    requires_login = True
    supported_conditions: ClassVar[list[str]] = ["used", "marketplace"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]
    results_selector = '[role="feed"]'
    item_selector = '[role="feed"] > div > div > div > div > a'

    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        search_url = f"{self.base_url}/marketplace/search/?query={query.replace(' ', '%20')}"
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=45000)
            await page.wait_for_selector(self.results_selector, timeout=20000)
        except Exception:
            return []

        deals = []
        elements = await page.query_selector_all(self.item_selector)
        for el in elements[:max_results]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
        return deals

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

            # Parse price
            price_clean = price_text.replace(" ", "").replace(",", ".")
            price_match = re.search(r"([\d.]+)\s*€", price_clean)
            price_eur = float(price_match.group(1)) if price_match else 0.0

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
                metadata={"source": "facebook"}
            )
        except Exception:
            return None