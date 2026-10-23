from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from playwright.async_api import Page

from src.searcher.currency import parse_price_detail
from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import SiteProfile


class SiteBlockedError(RuntimeError):
    """Raised when a site serves an anti-bot / challenge page instead of results."""


# Markers that indicate an interstitial rather than real search results.
BLOCK_MARKERS = (
    ("just a moment", "cloudflare challenge"),
    ("testchallengepage", "cloudflare challenge"),
    ("attention required", "cloudflare challenge"),
    ("enable javascript and cookies to continue", "cloudflare challenge"),
    ("checking your browser", "bot challenge"),
    ("are you a robot", "captcha"),
    ("something went wrong on our end", "ebay bot block"),
    ("pardon our interruption", "bot block"),
    ("unusual traffic", "rate limited"),
    ("_____tmd_____", "aliExpress anti-bot challenge"),
    ("x5secdata", "aliExpress anti-bot challenge"),
)


@dataclass
class Deal:
    """Represents a deal found on a marketplace."""
    url: str
    title: str
    price_eur: float
    currency: str = "EUR"
    condition: str = "unknown"          # new | used | refurbished | open_box
    category: str = "general"           # electronics | appliances | auto | etc.
    site_name: str = ""
    metadata: dict = field(default_factory=dict)  # extra: shipping, seller, location, etc.
    original_price: float | None = None  # amount as listed, in original_currency
    original_currency: str = "EUR"


class BaseAdapter(ABC):
    """Abstract adapter for a single marketplace/site."""

    name: str = ""           # e.g., "alza"
    base_url: str = ""       # e.g., "https://www.alza.sk"
    requires_login: bool = False
    # Currency the shop lists prices in. Overridden per site when the same
    # adapter serves several markets (Alza SK vs. Alza CZ).
    currency: str = "EUR"
    supported_conditions: ClassVar[list[str]] = ["new", "used", "refurbished", "open_box"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]

    # Warranty / seller trust metadata. These are the deciding factors when
    # choosing between a cheap classifieds listing and a slightly dearer
    # retailer open-box item with a real warranty.
    seller_type: str = "retailer"  # retailer | marketplace | classifieds | auction
    has_warranty: bool = False     # true when the seller is a retailer/official
    warranty_note: str = ""        # human-readable caveat for the user

    # Selectors for doctor diagnostics
    results_selector: str = ""      # Main results container selector
    item_selector: str = ""         # Individual item selector

    def __init__(self, base_url: str | None = None, currency: str | None = None):
        """Allow a site entry to override the adapter's default country domain.

        The currency can be overridden too, because one adapter can serve
        several markets (Alza SK quotes in EUR, Alza CZ in CZK).
        """
        self.base_url = (base_url or type(self).base_url).rstrip("/")
        self.currency = (currency or type(self).currency or "EUR").upper()

    @abstractmethod
    async def search(
        self,
        page: Page,
        query: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
        category: str = "any",
        profile: SiteProfile | None = None,
    ) -> list[Deal]:
        """Execute search on the site, return list of Deal objects."""
        ...

    def default_search_url(self, query: str) -> str:
        """Adapter-specific URL used when no profile supplies one."""
        return ""

    async def _goto_search(
        self,
        page: Page,
        query: str,
        filters: SearchFilters | None = None,
        category: str = "any",
        profile: SiteProfile | None = None,
        *,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,  # noqa: ASYNC109 - Playwright wants milliseconds
    ) -> str | None:
        """Navigate to a profile URL when available, otherwise the adapter URL."""
        url: str | None = None
        if profile is not None:
            from src.searcher.filter_engine import FilterEngine

            url = FilterEngine.build_search_url(profile, query, category, filters)
        if not url:
            url = self.default_search_url(query)
        if not url:
            return None
        await page.goto(url, wait_until=wait_until, timeout=timeout)
        return url

    async def _apply_filters(
        self,
        page: Page,
        filters: SearchFilters | None = None,
        profile: SiteProfile | None = None,
    ) -> list[str]:
        """Apply profile UI filters; no profile means no-op."""
        if profile is None or filters is None:
            return []
        from src.searcher.filter_engine import FilterEngine

        return await FilterEngine.apply_ui(page, profile, filters)

    @abstractmethod
    async def extract_deal(self, page: Page, element) -> Deal | None:
        """Extract Deal from a single result element on search results page."""
        ...

    def matches_condition(self, condition: str) -> bool:
        if condition == "any":
            return True
        return condition in self.supported_conditions

    def matches_category(self, category: str) -> bool:
        if category == "any":
            return True
        return category in self.supported_categories

    async def detect_block(self, page: Page) -> str | None:
        """Return a human-readable reason if the page is an anti-bot interstitial.

        Adapters call this right after navigation so a hard block fails fast
        instead of waiting out the full selector timeout.
        """
        try:
            url = (page.url or "").lower()
            title = ((await page.title()) or "").lower()
        except Exception:  # noqa: BLE001 - page may already be closed
            return None

        for marker, reason in BLOCK_MARKERS:
            if marker in title or marker in url:
                return reason
        return None

    def parse_price_with_currency(self, text: str) -> tuple[float, float, str] | None:
        """Parse *text* into ``(price_eur, original_amount, currency)``.

        The adapter's own currency is used when the price text carries no
        symbol, which is the normal case on Czech portals.
        """
        detail = parse_price_detail(text, self.currency)
        if detail is None:
            return None
        original, eur, currency = detail
        return eur, original, currency

    @staticmethod
    def parse_price_eur(text: str) -> float | None:
        """Parse the first euro price out of adapter text.

        Handles NBSP/thin spaces (SK/CZ/German listings) and both European
        ("1.299,50") and US ("1,299.50") thousand separators. The rightmost
        separator is treated as decimal only when followed by 1-2 digits.
        """
        import re

        if not text:
            return None
        cleaned = text.replace("\u00a0", " ").replace("\u202f", " ")
        match = re.search(r"\d[\d\s.,]*", cleaned)
        if not match:
            return None

        num = match.group(0).replace(" ", "").rstrip(".,")
        if not num:
            return None

        dec_pos = max(num.rfind("."), num.rfind(","))
        if dec_pos == -1:
            try:
                return float(num)
            except ValueError:
                return None

        tail = num[dec_pos + 1 :]
        if len(tail) in (1, 2):
            head = num[:dec_pos].replace(".", "").replace(",", "")
            frac = tail.replace(".", "").replace(",", "")
            try:
                return float(f"{head}.{frac}")
            except ValueError:
                return None

        # No decimal digits after the separator -> it was a thousands group.
        try:
            return float(num.replace(".", "").replace(",", ""))
        except ValueError:
            return None