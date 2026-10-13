"""Search bar component."""

from src.browser.pom.base import BasePage


class SearchBar(BasePage):
    """Reusable search bar."""

    INPUT_SELECTORS = ['input[type="search"]', 'input[name="q"]', 'input[name="search"]', '#search']

    async def search(self, query: str) -> bool:
        for sel in self.INPUT_SELECTORS:
            if await self.safe_fill(sel, query):
                await self.page.keyboard.press("Enter")
                await self.wait_for_load()
                return True
        return False
