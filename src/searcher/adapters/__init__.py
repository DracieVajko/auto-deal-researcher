"""Site adapters registry."""

from .alza import AlzaAdapter
from .backmarket import BackMarketAdapter
from .base import BaseAdapter, Deal, SiteBlockedError
from .bazos import BazosAdapter
from .ebay import EbayAdapter
from .facebook import FacebookAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "alza": AlzaAdapter,
    "bazos": BazosAdapter,
    "backmarket": BackMarketAdapter,
    "facebook": FacebookAdapter,
    "ebay": EbayAdapter,
}


def get_adapter(name: str) -> type[BaseAdapter]:
    """Get adapter class by name."""
    if name not in ADAPTER_REGISTRY:
        msg = f"No adapter for site: {name}. Available: {list(ADAPTER_REGISTRY.keys())}"
        raise ValueError(msg)
    return ADAPTER_REGISTRY[name]


__all__ = [
    "ADAPTER_REGISTRY",
    "AlzaAdapter",
    "BackMarketAdapter",
    "BaseAdapter",
    "BazosAdapter",
    "Deal",
    "EbayAdapter",
    "FacebookAdapter",
    "SiteBlockedError",
    "get_adapter",
]