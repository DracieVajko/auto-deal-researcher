"""Storage models - canonical dataclasses."""

from dataclasses import dataclass, field


@dataclass
class Deal:
    """Canonical deal record (url is PK)."""
    url: str
    title: str
    price_eur: float
    currency: str = "EUR"
    condition: str = "unknown"
    category: str = "general"
    site_name: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class PriceHistory:
    """Price sighting joined on url (not integer id)."""
    url: str
    price_eur: float
    timestamp: str
    run_id: str = ""
    condition: str = "unknown"


@dataclass
class WatchlistItem:
    """Watchlist entry with target price."""
    url: str
    target_price: float
    alert_on_drop: bool = True
    last_notified: str = ""
