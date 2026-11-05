"""Anti-bot handling for Playwright scraping.

Provides stealth browser context configuration, Cloudflare/anti-bot challenge
detection, and retry-with-backoff logic. Blocked sites are skipped gracefully
rather than failing the entire search.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

# User agents rotated per site to avoid fingerprinting.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Markers that indicate an interstitial rather than real search results.
BLOCK_MARKERS = [
    ("just a moment", "cloudflare challenge"),
    ("checking your browser", "cloudflare challenge"),
    ("enable javascript and cookies", "cloudflare challenge"),
    ("are you a robot", "captcha"),
    ("unusual traffic", "rate limited"),
    ("attention required", "bot block"),
    ("pardon our interruption", "bot block"),
    ("something went wrong on our end", "ebay bot block"),
    ("_____tmd_____", "aliexpress anti-bot challenge"),
    ("x5secdata", "aliexpress anti-bot challenge"),
    ("verify you are human", "human verification"),
    ("access denied", "access denied"),
]


async def stealth_context(browser) -> BrowserContext:
    """Create a Playwright browser context with anti-detection settings.

    - Random user-agent
    - Realistic viewport
    - No webdriver flag
    - Extra HTTP headers
    """
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="sk-SK",
        timezone_id="Europe/Bratislava",
    )
    # Remove webdriver fingerprint
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['sk-SK', 'sk', 'en']});
        Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
    """)
    return context


async def detect_block(page: Page) -> str | None:
    """Detect if the current page shows an anti-bot/challenge page.

    Returns the block reason string, or None if the page looks normal.
    """
    try:
        content = (await page.content()).lower()
        title = (await page.title()).lower()
        combined = f"{title} {content}"
        for marker, reason in BLOCK_MARKERS:
            if marker in combined:
                return reason
    except Exception:
        # If we can't read the page, assume it's blocked
        return "unreadable page"
    return None


async def retry_with_backoff(
    page: Page,
    action: Callable,
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> bool:
    """Retry an action with exponential backoff when anti-bot is detected.

    Returns True if the action succeeded (no block detected), False if
    blocked after all attempts.
    """
    import asyncio

    for attempt in range(max_attempts):
        block_reason = detect_block(page)
        if not block_reason:
            return True
        logger.warning(
            "Anti-bot detected (%s), attempt %d/%d, retrying in %.fs",
            block_reason, attempt + 1, max_attempts, base_delay * (2 ** attempt),
        )
        await asyncio.sleep(base_delay * (2 ** attempt))
        try:
            await page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
    return False
