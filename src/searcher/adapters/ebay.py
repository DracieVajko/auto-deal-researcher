import re
from typing import Optional
from playwright.async_api import Page
from .base import BaseAdapter, Deal


class EbayAdapter(BaseAdapter):
    name = "ebay"
    base_url = "https://www.ebay.de"
    supported_conditions = ["used", "refurbished", "new", "open_box"]
    supported_categories = ["electronics", "appliances", "auto", "general"]
    results_selector = ".s-item"
    item_selector = ".s-item"

    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        search_url = f"{self.base_url}/sch/i.html?_nkw={query.replace(' ', '+')}&_dcat=0"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_selector(self.results_selector, timeout=10000)
        except Exception:
            return []

        deals = []
        elements = await page.query_selector_all(self.item_selector)
        for el in elements[:max_results]:
            deal = await self.extract_deal(page, el)
            if deal:
                deals.append(deal)
        return deals

    async def extract_deal(self, page: Page, element) -> Optional[Deal]:
        try:
            title_el = await element.query_selector(".s-item__title")
            price_el = await element.query_selector(".s-item__price")
            link_el = await element.query_selector(".s-item__link")
            condition_el = await element.query_selector(".SECONDARY_INFO")

            if not all([title_el, price_el, link_el]):
                return None

            title = await title_el.inner_text()
            price_text = await price_el.inner_text()
            url = await link_el.get_attribute("href")
            condition_text = await condition_el.inner_text() if condition_el else ""

            # Parse price: "EUR 1.299,00" or "1 299,00 €" → 1299.0
            price_clean = price_text.replace(" ", "").replace("EUR", "").replace("€", "").replace(",", ".")
            price_match = re.search(r"([\d.]+)", price_clean)
            if not price_match:
                return None
            price_eur = float(price_match.group(1))

            # Determine condition from text
            condition_text_lower = condition_text.lower()
            if "refurbished" in condition_text_lower or "generalüberholt" in condition_text_lower:
                condition = "refurbished"
            elif "new" in condition_text_lower or "neu" in condition_text_lower:
                condition = "new"
            elif "open box" in condition_text_lower or "opened" in condition_text_lower:
                condition = "open_box"
            else:
                condition = "used"

            return Deal(
                url=url,
                title=title.strip(),
                price_eur=price_eur,
                condition=condition,
                category="electronics",
                site_name=self.name,
                metadata={"source": "ebay"}
            )
        except Exception:
            return None