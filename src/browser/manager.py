"""Browser manager with CDP and persistent context support."""

import asyncio
from playwright.async_api import async_playwright, Browser
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self, config):
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None

    async def get_browser(self) -> Browser:
        """Get or create browser instance (for async context manager)."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._create_browser()
        return self._browser

    async def _create_browser(self) -> Browser:
        browser_config = self.config.browser
        
        # Try CDP connection first
        try:
            logger.info(f"Connecting to browser via CDP: {browser_config.cdp_endpoint}")
            browser = await self._playwright.chromium.connect(browser_config.cdp_endpoint)
            logger.info("CDP connection successful")
            return browser
        except Exception as e:
            logger.info(f"CDP connection failed: {e}")
        
        # Fallback to persistent context
        if browser_config.use_persistent_context:
            user_data_dir = Path(browser_config.user_data_dir)
            user_data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Launching persistent context: {user_data_dir}")
            browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False,
                slow_mo=500
            )
            return browser
        
        # Last resort: regular launch
        logger.info("Launching regular browser")
        return await self._playwright.chromium.launch(headless=False)

    async def close(self):
        """Close the browser and playwright."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # Backward compatibility
    async def connect(self):
        return await self.get_browser()