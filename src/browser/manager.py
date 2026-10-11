import asyncio
from playwright.async_api import async_playwright
import logging

logger = logging.getLogger(__name__)

class BrowserManager:
    def __init__(self, config):
        self.config = config
        
    async def connect(self):
        """Connect to browser using CDP or persistent context"""
        try:
            # Try connecting via CDP first
            async with async_playwright() as p:
                browser = await p.chromium.connect("http://localhost:9222")
                return browser
        except Exception as e:
            logger.info(f"CDP connection failed, falling back to persistent context: {e}")
            # Fallback to persistent context
            async with async_playwright() as p:
                browser = await p.chromium.launch_persistent_context(
                    user_data_dir="/tmp/browser-profile",
                    headless=False,
                    slow_mo=500
                )
                return browser

    async def close(self, browser):
        """Close the browser connection"""
        await browser.close()