"""Base page object."""

import logging

logger = logging.getLogger(__name__)


class BasePage:
    """Common methods for all page objects."""

    def __init__(self, page):
        self.page = page

    async def goto(self, url: str):
        await self.page.goto(url)
        await self.wait_for_load()

    async def wait_for_load(self):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception as exc:
            logger.debug("wait_for_load failed: %s", exc)

    async def handle_cookie_consent(self) -> bool:
        selectors = [
            'button:has-text("Accept")',
            '#onetrust-accept-btn-handler',
            '.cookie-accept',
        ]
        for sel in selectors:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=1000)
                if btn and await btn.is_visible():
                    await btn.click()
                    return True
            except Exception as exc:
                logger.debug("cookie selector %s failed: %s", sel, exc)
                continue
        return False

    async def safe_click(self, selector: str) -> bool:
        try:
            await self.page.click(selector, timeout=5000)
            return True
        except Exception as exc:
            logger.debug("safe_click %s failed: %s", selector, exc)
            return False

    async def safe_fill(self, selector: str, value: str) -> bool:
        try:
            await self.page.fill(selector, value, timeout=5000)
            return True
        except Exception as exc:
            logger.debug("safe_fill %s failed: %s", selector, exc)
            return False
