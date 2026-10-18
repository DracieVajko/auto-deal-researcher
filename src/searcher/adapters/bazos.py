import asyncio
import logging
import re
from typing import ClassVar

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .base import BaseAdapter, Deal

logger = logging.getLogger(__name__)


class BazosAdapter(BaseAdapter):
    name = "bazos"
    base_url = "https://www.bazos.sk"
    supported_conditions: ClassVar[list[str]] = ["used"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]
    seller_type = "classifieds"
    has_warranty = False
    warranty_note = "Private sellers; warranty only if they hand over the receipt."
    results_selector = ".inzeraty"
    item_selector = ".inzeraty > div"

    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        search_url = f"{self.base_url}/search.php?hledat={query.replace(' ', '+')}"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            # Wait a bit for cookie consent to appear
            await asyncio.sleep(2)
            # Handle cookie consent (TermsFeed used by Bazos)
            await self._handle_cookie_consent(page)
            await page.wait_for_selector(self.results_selector, timeout=15000)
            await page.wait_for_selector(self.item_selector, timeout=10000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] Navigation error: {e}")
            return []

        deals = []
        # Items are split across 5 divs per listing in .inzeraty > div
        # Group them: [title/link, price, location, views, actions]
        elements = await page.query_selector_all(self.item_selector)

        # Process in groups of 5
        for i in range(0, len(elements), 5):
            if len(deals) >= max_results:
                break

            if i + 4 >= len(elements):
                break

            title_el = elements[i]
            price_el = elements[i + 1]
                                    
            deal = await self._extract_from_group(page, title_el, price_el)
            if deal:
                deals.append(deal)

        return deals

    async def _handle_cookie_consent(self, page: Page):
        """Handle cookie consent dialogs explicitly."""
        cookie_selectors = [
            # TermsFeed specific (used by Bazos, etc.)
            'button.cc-nb-okagree',
            'button.cc-nb-reject',
            'button.cc-nb-changep',
            # Generic
            'button:has-text("Accept")',
            'button:has-text("Accept all")',
            'button:has-text("Prijať")',
            'button:has-text("Prijať všetko")',
            'button:has-text("Súhlasím")',
            'button:has-text("Suhlasim")',
            'button:has-text("Souhlasím")',
            'button:has-text("Souhlasím se vším")',
            # Common patterns
            'button[id*="accept"]',
            'button[class*="accept"]',
            'button[data-testid*="accept"]',
            '#onetrust-accept-btn-handler',
            '.cookie-accept',
            '[aria-label*="accept" i]',
        ]
        for selector in cookie_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    return True
            except PlaywrightError as e:
                logger.debug(f"Cookie selector {selector} not matched: {e}")
                continue
        return False

    async def extract_deal(self, page: Page, element) -> Deal | None:
        """Abstract method required by BaseAdapter - not used in this adapter."""
        return None

    async def _extract_from_group(self, page: Page, title_container, price_container) -> Deal | None:
        """Extract deal from title container (has link) and price container."""
        try:
            # Get title and link from title container
            title_link = await title_container.query_selector(".nadpis a")
            if not title_link:
                title_link = await title_container.query_selector("a[href*='inzerat']")
            if not title_link:
                return None

            title = await title_link.inner_text()
            url = await title_link.get_attribute("href")

            # Get price from price container
            price_el = await price_container.query_selector("span, b, strong")
            if not price_el:
                price_el = price_container
            price_text = await price_el.inner_text()

            # Parse price: "26 €" → 26.0
            price_clean = price_text.replace(" ", "").replace(",", ".")
            price_match = re.search(r"([\d.]+)\s*€", price_clean)
            if not price_match:
                return None
            price_eur = float(price_match.group(1))

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
        except (PlaywrightError, ValueError, AttributeError, TypeError) as e:
            logger.debug(f"[{self.name}] Extract error: {e}")
            return None