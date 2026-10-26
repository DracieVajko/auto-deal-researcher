import asyncio
import logging
import os
import re
from typing import ClassVar
from urllib.parse import quote_plus

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import SiteProfile

from .base import BaseAdapter, Deal

logger = logging.getLogger(__name__)


class BazosAdapter(BaseAdapter):
    name = "bazos"
    base_url = "https://www.bazos.sk"
    supported_conditions: ClassVar[list[str]] = ["used"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general", "home", "hobby"]
    seller_type = "classifieds"
    has_warranty = False
    warranty_note = "Private sellers; warranty only if they hand over the receipt."
    results_selector = ".inzeraty"
    item_selector = ".inzeraty > div"

    # Detail pages carry the description, location and the specs that the
    # result cards omit (frame size, fork, brakes). Fetching them costs one
    # request per listing, so it can be disabled with ADS_BAZOS_DETAILS=0.
    detail_description_selector = ".popisdetail"
    detail_main_selector = ".maincontent"
    detail_timeout_ms = 10000
    detail_delay_seconds = 0.5

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
            # Wait a bit for cookie consent to appear
            await asyncio.sleep(2)
            # Handle cookie consent (TermsFeed used by Bazos)
            await self._handle_cookie_consent(page)
            await page.wait_for_selector(self.results_selector, timeout=15000)
            await page.wait_for_selector(self.item_selector, timeout=10000)
        except PlaywrightError as e:
            logger.debug(f"[{self.name}] Navigation error: {e}")
            return []

        applied = await self._apply_filters(page, filters, profile)
        if applied:
            try:
                await page.wait_for_selector(self.item_selector, timeout=10000)
            except PlaywrightError as e:
                logger.debug(f"[{self.name}] filtered results not found: {e}")
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

        if deals and os.environ.get("ADS_BAZOS_DETAILS", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        ):
            try:
                limit = int(os.environ.get("ADS_BAZOS_DETAIL_LIMIT", "10"))
            except ValueError:
                logger.warning(
                    "[%s] Invalid ADS_BAZOS_DETAIL_LIMIT; using 10", self.name
                )
                limit = 10
            selected = deals[: max(0, limit)]
            failed = await self._enrich_details(page, selected)
            if failed:
                logger.warning(
                    "[%s] %d/%d detail pages returned no description; "
                    "those listings keep their card data only",
                    self.name,
                    failed,
                    len(selected),
                )

        return deals

    def default_search_url(self, query: str) -> str:
        return f"{self.base_url}/search.php?hledat={quote_plus(query)}"

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

    async def _enrich_details(self, page: Page, deals: list[Deal]) -> int:
        """Load each listing page for its description and location.

        The result cards only carry title and price. Frame size, fork type and
        the seller's town are written in the description, so without this step
        the report can only guess from the title. A failed page leaves the card
        data untouched and does not abort the run.

        Returns the number of pages that produced no description, so the caller
        can report the gap instead of silently shipping a thinner report.
        """
        failed = 0
        for deal in deals:
            try:
                await page.goto(
                    deal.url,
                    wait_until="domcontentloaded",
                    timeout=self.detail_timeout_ms,
                )
                description = await self._inner_text(
                    page, self.detail_description_selector
                )
                main = await self._inner_text(page, self.detail_main_selector)
                if not description:
                    # Bazos occasionally serves an empty shell when requests
                    # come too fast. One reload is cheaper than a report with
                    # no specs.
                    await asyncio.sleep(1.0)
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=self.detail_timeout_ms,
                    )
                    description = await self._inner_text(
                        page, self.detail_description_selector
                    )
                    main = await self._inner_text(page, self.detail_main_selector)
                if not description:
                    failed += 1
                    logger.debug(
                        "[%s] No description on detail page %s (title=%r, url=%s)",
                        self.name,
                        deal.url,
                        await page.title(),
                        page.url,
                    )
            except PlaywrightError as e:
                logger.debug(f"[{self.name}] Detail fetch failed for {deal.url}: {e}")
                failed += 1
                continue

            if description:
                deal.metadata["description"] = description
            location = self._parse_location(main)
            if location:
                deal.metadata["location"] = location
            await asyncio.sleep(self.detail_delay_seconds)

        return failed

    @staticmethod
    async def _inner_text(page: Page, selector: str) -> str:
        element = await page.query_selector(selector)
        if not element:
            return ""
        return " ".join((await element.inner_text()).split())

    @staticmethod
    def _parse_location(main_text: str) -> str:
        """Pull "841 04 Bratislava" out of the detail page's metadata block."""
        match = re.search(
            r"Lokalita:\s*(\d{3}\s?\d{2})\s+(.+?)\s+(?:Videlo|Zobrazené):",
            main_text,
        )
        if match:
            return f"{match.group(1)} {match.group(2)}".strip()
        match = re.search(
            r"Lokalita:\s*(.+?)\s*(?:Videlo|Zobrazené):", main_text
        )
        return match.group(1).strip() if match else ""

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

            # "26 €" on bazos.sk, "8 900 Kč" on bazos.cz.
            parsed = self.parse_price_with_currency(price_text)
            if parsed is None:
                return None
            price_eur, original_price, original_currency = parsed

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
                    "source": "bazos",
                    "original_price": original_price,
                    "original_currency": original_currency,
                },
                original_price=original_price,
                original_currency=original_currency,
            )
        except (PlaywrightError, ValueError, AttributeError, TypeError) as e:
            logger.debug(f"[{self.name}] Extract error: {e}")
            return None