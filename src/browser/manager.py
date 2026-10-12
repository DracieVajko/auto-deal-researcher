"""Browser manager with CDP and persistent context support."""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, async_playwright

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self, config):
        self.config = config
        self._playwright = None
        self._browser: Browser | BrowserContext | None = None
        self._context = None

    async def get_browser(self) -> Browser | BrowserContext:
        """Get or create browser instance (for async context manager)."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._create_browser()
        return self._browser

    async def _create_browser(self) -> Browser | BrowserContext:
        browser_config = self.config.browser
        
        # Try CDP connection first (connect to existing browser)
        try:
            logger.info(f"Connecting to browser via CDP: {browser_config.cdp_endpoint}")
            browser = await self._playwright.chromium.connect(browser_config.cdp_endpoint)
            logger.info("CDP connection successful - using existing browser")
            # Create a new context in the existing browser
            self._context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                ignore_https_errors=True,
            )
            await self._setup_context(self._context)
            return self._context
        except Exception as e:
            logger.info(f"CDP connection failed: {e}")
        
        # Fallback to persistent context (headless by default)
        if browser_config.use_persistent_context:
            user_data_dir = Path(browser_config.user_data_dir)
            user_data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Launching persistent context (headless={browser_config.headless}): {user_data_dir}")
            context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=browser_config.headless,
                slow_mo=browser_config.slow_mo,
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                ignore_https_errors=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            await self._setup_context(context)
            return context
        
        # Last resort: regular launch (headless)
        logger.info("Launching regular browser (headless)")
        browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
            ]
        )
        self._context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            ignore_https_errors=True,
        )
        await self._setup_context(self._context)
        return self._context

    async def _setup_context(self, context: BrowserContext):
        """Setup context with cookie handling and anti-detection."""
        # Add init script to hide automation
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'sk', 'cs']
            });
        """)
        
        # Set default timeout
        context.set_default_timeout(30000)
        context.set_default_navigation_timeout(30000)

    async def get_page(self):
        """Get a new page with cookie consent handling."""
        browser = await self.get_browser()
        page = await browser.new_page()
        await self._setup_page(page)
        return page

    async def _setup_page(self, page):
        """Setup page with cookie consent handling."""
        # Handle common cookie consent patterns
        async def handle_cookies():
            try:
                # Common cookie consent selectors
                cookie_selectors = [
                    'button:has-text("Accept")',
                    'button:has-text("Accept all")',
                    'button:has-text("Prijať")',
                    'button:has-text("Prijať všetko")',
                    'button:has-text("Souhlasím")',
                    'button:has-text("Souhlasím se vším")',
                    'button[id*="accept"]',
                    'button[class*="accept"]',
                    'button[data-testid*="accept"]',
                    '#onetrust-accept-btn-handler',
                    '.cookie-accept',
                    '[aria-label*="accept" i]',
                ]
                for selector in cookie_selectors:
                    try:
                        btn = await page.wait_for_selector(selector, timeout=2000)
                        if btn and await btn.is_visible():
                            await btn.click()
                            logger.info(f"Clicked cookie consent: {selector}")
                            await asyncio.sleep(0.5)
                            return True
                    except Exception as e:
                        logger.debug(f"Cookie selector {selector} not matched: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Cookie handling error: {e}")
            return False

        # Attach handler for navigation
        page.on("framenavigated", lambda frame: asyncio.create_task(handle_cookies()))

    async def close(self):
        """Close the browser and playwright."""
        if self._context and hasattr(self._context, 'close'):
            await self._context.close()
        if self._browser and hasattr(self._browser, 'close'):
            await self._browser.close()
        self._browser = None
        self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # Backward compatibility
    async def connect(self):
        return await self.get_browser()