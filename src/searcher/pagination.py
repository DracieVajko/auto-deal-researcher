"""Multi-page scraping for marketplace search results.

Detects "next page" links and scrapes multiple pages of results up to a
configurable limit. Stops early when no next page is found or when a block
is detected.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Common "next page" link selectors across marketplaces.
NEXT_PAGE_SELECTORS = [
    'a[rel="next"]',
    '.pagination__next, .pagination-next, .next-page, .next',
    'a:has-text("Ďalšia"), a:has-text("Další"), a:has-text("Nächste"), a:has-text("Dalej"), a:has-text("Next")',
    'a:has-text("»"), a:has-text("›")',
    '.pager-next a, .page-next a',
]


async def find_next_page_link(page: Page) -> str | None:
    """Find the URL of the next page of results, if any.

    Returns the href of the next page link, or None if there is no next page.
    """
    for selector in NEXT_PAGE_SELECTORS:
        try:
            element = await page.query_selector(selector)
            if element:
                href = await element.get_attribute("href")
                if href:
                    return href
                # Check if it's a button that triggers navigation
                disabled = await element.get_attribute("disabled")
                aria_disabled = await element.get_attribute("aria-disabled")
                if not disabled and aria_disabled != "true":
                    # Element exists and isn't disabled - try clicking
                    return "click"
        except Exception:
            continue
    return None


async def scrape_pages(
    page: Page,
    search_action: Callable,
    max_pages: int = 3,
) -> list:
    """Scrape multiple pages of results.

    ``search_action`` is an async callable that takes a Page and returns a
    list of deals for the current page. It is called once per page.

    Returns the combined list of deals from all pages.
    """
    all_deals: list = []

    for page_num in range(1, max_pages + 1):
        logger.info("Scraping page %d/%d", page_num, max_pages)

        # Scrape current page
        try:
            deals = await search_action(page)
            all_deals.extend(deals)
        except Exception as exc:
            logger.warning("Failed to scrape page %d: %s", page_num, exc)
            break

        # Don't look for next page on the last page
        if page_num >= max_pages:
            break

        # Find next page link
        next_link = await find_next_page_link(page)
        if not next_link:
            logger.info("No next page found after page %d", page_num)
            break

        if next_link == "click":
            try:
                # Click the next button
                for selector in ["a:has-text('Ďalšia')", "a:has-text('Další')",
                                 "a:has-text('Nächste')", "a:has-text('Dalej')",
                                 "a:has-text('Next')", 'a[rel="next"]']:
                    element = await page.query_selector(selector)
                    if element:
                        await element.click()
                        break
            except Exception as exc:
                logger.warning("Failed to click next page: %s", exc)
                break
        else:
            # Navigate to the next page URL
            from urllib.parse import urljoin
            current_url = page.url
            next_url = urljoin(current_url, next_link)
            try:
                await page.goto(next_url, wait_until="domcontentloaded")
            except Exception as exc:
                logger.warning("Failed to navigate to next page %s: %s", next_url, exc)
                break

    logger.info("Scraped %d deals from %d page(s)", len(all_deals), page_num)
    return all_deals
