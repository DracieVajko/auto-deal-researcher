import re
from typing import Optional
from playwright.async_api import Page
from .base import BaseAdapter, Deal


class BazosAdapter(BaseAdapter):
    name = "bazos"
    base_url = "https://www.bazos.sk"
    supported_conditions = ["used"]
    supported_categories = ["electronics", "appliances", "auto", "general"]

    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        search_url = f"{self.base_url}/search.php?hledat={query.replace(' ', '+')}"
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_selector(".inzerat", timeout=15000)
        except Exception:
            return []

        deals = []
        elements = await page.query_selector_all(".inzerat")
        for el in elements[:max_results]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
        return deals

    async def extract_deal(self, page: Page, element) -> Optional[Deal]:
        try:
            title_el = await element.query_selector(".nadpis")
            price_el = await element.query_selector(".cena")
            link_el = await element.query_selector("a")

            if not all([title_el, price_el, link_el]):
                return None

            title = await title_el.inner_text()
            price_text = await price_el.inner_text()
            url = await link_el.get_attribute("href")

            # Parse price: "1 299 €" → 1299.0
            price_clean = price_text.replace(" ", "").replace(",", ".")
            price_match = re.search(r"([\d.]+)\s*€", price_clean)
            if not price_match:
                return None
            price_eur = float(price_match.group(1))

            # Bazos is primarily used items
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
                metadata={"source": "bazos"}
            )
        except Exception:
            return None