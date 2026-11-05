"""Tests for anti_bot.py (anti-bot handling)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.searcher.anti_bot import BLOCK_MARKERS, detect_block


@pytest.mark.asyncio
async def test_detect_block_cloudflare():
    page = MagicMock()
    page.content = AsyncMock(return_value="<html>Just a moment</html>")
    page.title = AsyncMock(return_value="Cloudflare")
    result = await detect_block(page)
    assert result == "cloudflare challenge"


@pytest.mark.asyncio
async def test_detect_block_captcha():
    page = MagicMock()
    page.content = AsyncMock(return_value="<html>Are you a robot?</html>")
    page.title = AsyncMock(return_value="Verification")
    result = await detect_block(page)
    assert result == "captcha"


@pytest.mark.asyncio
async def test_detect_block_none():
    page = MagicMock()
    page.content = AsyncMock(return_value="<html>Search results for cars</html>")
    page.title = AsyncMock(return_value="Search Results")
    result = await detect_block(page)
    assert result is None


def test_block_markers_not_empty():
    assert len(BLOCK_MARKERS) > 0
