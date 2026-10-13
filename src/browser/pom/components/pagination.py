"""Pagination component."""

from src.browser.pom.base import BasePage


class Pagination(BasePage):
    """Reusable pagination."""

    NEXT_SELECTORS = ['a:has-text("Next")', 'a[rel="next"]', '.pagination-next', '[aria-label="Next"]']

    async def next(self) -> bool:
        for sel in self.NEXT_SELECTORS:
            if await self.safe_click(sel):
                await self.wait_for_load()
                return True
        return False
