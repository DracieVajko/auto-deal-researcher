"""Site adapters registry."""

from .base import BaseAdapter, Deal
from .alza import AlzaAdapter
from .bazos import BazosAdapter
from .backmarket import BackMarketAdapter
from .facebook import FacebookAdapter
from .ebay import EbayAdapter


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
        raise ValueError(f"No adapter for site: {name}. Available: {list(ADAPTER_REGISTRY.keys())}")
    return ADAPTER_REGISTRY[name]


__all__ = [
    "BaseAdapter",
    "Deal",
    "ADAPTER_REGISTRY",
    "get_adapter",
    "AlzaAdapter",
    "BazosAdapter",
    "BackMarketAdapter",
    "FacebookAdapter",
    "EbayAdapter",
]