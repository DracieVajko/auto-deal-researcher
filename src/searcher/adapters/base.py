from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from playwright.async_api import Page


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


class BaseAdapter(ABC):
    """Abstract adapter for a single marketplace/site."""

    name: str = ""           # e.g., "alza"
    base_url: str = ""       # e.g., "https://www.alza.sk"
    requires_login: bool = False
    supported_conditions: ClassVar[list[str]] = ["new", "used", "refurbished", "open_box"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]
    
    # Selectors for doctor diagnostics
    results_selector: str = ""      # Main results container selector
    item_selector: str = ""         # Individual item selector

    @abstractmethod
    async def search(self, page: Page, query: str, max_results: int = 20) -> list[Deal]:
        """Execute search on the site, return list of Deal objects."""
        ...

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