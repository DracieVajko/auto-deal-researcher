"""Sort component."""

from src.browser.pom.base import BasePage


class Sort(BasePage):
    """Reusable sort control."""

    async def apply(self, sort_key: str) -> bool:
        sels = [f'[data-sort="{sort_key}"]', f'select[name="sort"]']
        for sel in sels:
            if await self.safe_click(sel):
                return True
        return False
