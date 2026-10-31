"""Browser manager with CDP and persistent context support."""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Error as PlaywrightError

from src.browser.fingerprint import FingerprintRotator, apply_fingerprint

logger = logging.getLogger(__name__)


def _port_from(endpoint: str | None) -> int | None:
    """Extract the debugging port from a CDP endpoint URL."""
    if not endpoint:
        return None
    tail = endpoint.rsplit(":", 1)[-1]
    tail = tail.split("/")[0]
    return int(tail) if tail.isdigit() else None


class BrowserManager:
    def __init__(self, config):
        self.config = config
        self._playwright = None
        self._browser: Browser | BrowserContext | None = None
        self._context = None
        self._cdp_connected = False
        self._fingerprint_rotator = FingerprintRotator()

    def _resolve_browser(self, browser_config) -> tuple[str | None, str | None, str]:
        """Pick the browser to launch.

        Returns (browser_id, executable_path, label). Falls back to Playwright's
        bundled Chromium when nothing is detected.
        """
        from src.browser.browsers import by_id, resolve

        self._extra_args = []
        try:
            exe, label = resolve(browser_config.browser_id, browser_config.browser_executable)
        except ValueError as e:
            logger.warning("%s", e)
            return None, None, "Playwright bundled Chromium (requested browser not found)"

        profile = by_id(browser_config.browser_id) if browser_config.browser_id else None
        if profile:
            self._extra_args = list(profile.extra_args)
        return (profile.id if profile else None), exe, label

    async def get_browser(self) -> Browser | BrowserContext:
        """Get or create browser instance (for async context manager)."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._create_browser()
        return self._browser

    async def _create_browser(self) -> Browser | BrowserContext:
        browser_config = self.config.browser
        
        # Try CDP connection first (attach to an already-running browser so the
        # user's real profile, cookies and logins are reused).
        # connect_over_cdp() is the API for a raw DevTools endpoint;
        # connect() speaks Playwright's own protocol and fails against it.
        try:
            logger.info(f"Connecting to browser via CDP: {browser_config.cdp_endpoint}")
            browser = await self._playwright.chromium.connect_over_cdp(
                browser_config.cdp_endpoint
            )
            logger.info("CDP connection successful - using existing browser")
            self._context = browser.contexts[0] if browser.contexts else await browser.new_context()
            self._cdp_connected = True
            await self._setup_context(self._context)
        except PlaywrightError as e:
            logger.info(f"CDP connection failed: {e}")
        else:
            return self._context
        
        # Fallback to persistent context (headless by default)
        if browser_config.use_persistent_context:
            browser_id, exe_path, label = self._resolve_browser(browser_config)
            suffix = f"/{browser_id}" if (browser_id and browser_config.separate_profiles) else ""
            user_data_dir = Path(browser_config.user_data_dir) / suffix if suffix \
                else Path(browser_config.user_data_dir)
            await asyncio.to_thread(user_data_dir.mkdir, parents=True, exist_ok=True)
            logger.info(f"Launching {label} persistent context (headless={browser_config.headless}): {user_data_dir}")
            launch: dict = {
                "user_data_dir": str(user_data_dir),
                "headless": browser_config.headless,
                "slow_mo": browser_config.slow_mo,
                "viewport": {'width': 1920, 'height': 1080},
                "user_agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                "ignore_https_errors": True,
                "args": [
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ],
            }
            # Point at the chosen real browser instead of bundled Chromium.
            if exe_path:
                launch["executable_path"] = exe_path
                port = _port_from(browser_config.cdp_endpoint)
                if port:
                    launch["args"] = launch["args"] + [f"--remote-debugging-port={port}"]
                if self._extra_args:
                    launch["args"] = launch["args"] + self._extra_args
            context = await self._playwright.chromium.launch_persistent_context(**launch)
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

    async def get_page(self, session_id: str | None = None, browser_type: str = "chromium") -> Page:
        """Get a new page with fingerprint rotation and cookie consent handling."""
        browser = await self.get_browser()
        page = await browser.new_page()
        await self._setup_page(page)
        
        # Apply fingerprint if not using CDP (CDP browser already has its own fingerprint)
        if not self._is_cdp_connected():
            fingerprint = self._fingerprint_rotator.get_fingerprint(browser_type, session_id)
            await apply_fingerprint(page, fingerprint)
        
        return page
    
    def _is_cdp_connected(self) -> bool:
        """Check if we're connected via CDP to an existing browser."""
        # If we have a context from CDP connection, we can't easily apply fingerprints
        return self._context is not None and hasattr(self._context, 'browser') and self._context.browser.is_connected()

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
                    except PlaywrightError as e:
                        logger.debug(f"Cookie selector {selector} not matched: {e}")
                        continue
            except PlaywrightError as e:
                logger.debug(f"Cookie handling error: {e}")
            return False

        # Attach handler for navigation
        page.on("framenavigated", lambda frame: asyncio.create_task(handle_cookies()))

    async def close(self):
        """Close the browser and Playwright, without killing a CDP-attached browser."""
        if self._cdp_connected:
            # Only disconnect. Closing the context would close the user's own
            # browser window and every tab in it.
            if self._browser and hasattr(self._browser, "close"):
                await self._browser.close()
        else:
            if self._context and hasattr(self._context, "close"):
                await self._context.close()
            if self._browser and hasattr(self._browser, "close"):
                await self._browser.close()
        self._browser = None
        self._context = None
        self._cdp_connected = False
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

