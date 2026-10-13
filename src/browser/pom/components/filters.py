"""Filters component."""

from src.browser.pom.base import BasePage


class Filters(BasePage):
    """Reusable filter panel."""

    async def apply(self, filters: dict) -> bool:
        applied = False
        for key, value in (filters or {}).items():
            sel = f'[data-filter="{key}"]'
            try:
                if await self.safe_click(sel):
                    applied = True
            except Exception:
                continue
        return applied
