"""Filters component."""

import logging

from src.browser.pom.base import BasePage

logger = logging.getLogger(__name__)


class Filters(BasePage):
    """Reusable filter panel."""

    async def apply(self, filters: dict) -> bool:
        applied = False
        for key, _value in (filters or {}).items():
            sel = f'[data-filter="{key}"]'
            try:
                if await self.safe_click(sel):
                    applied = True
            except Exception as exc:  # noqa: BLE001 - filter apply is best-effort
                logger.debug("Filter apply failed for %s: %s", key, exc)
                continue
        return applied
