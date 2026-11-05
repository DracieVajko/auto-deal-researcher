"""Tests for pagination.py (multi-page scraping)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.searcher.pagination import find_next_page_link, scrape_pages


@pytest.mark.asyncio
async def test_find_next_page_link_none():
    """No next page link found."""
    page = MagicMock()
    page.query_selector = AsyncMock(return_value=None)
    result = await find_next_page_link(page)
    assert result is None


@pytest.mark.asyncio
async def test_scrape_pages_single():
    """Only one page when no next link."""
    page = MagicMock()
    page.query_selector = AsyncMock(return_value=None)
    page.url = "https://example.com/search?q=test"

    async def search_action(p):
        return [{"title": "Item 1", "price_eur": 100.0}]

    deals = await scrape_pages(page, search_action, max_pages=3)
    assert len(deals) == 1
    assert deals[0]["title"] == "Item 1"
