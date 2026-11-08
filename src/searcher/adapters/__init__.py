"""Site adapters registry."""

import importlib.metadata as _md
import logging

from .alza import AlzaAdapter
from .amazon import AmazonAdapter
from .backmarket import BackMarketAdapter
from .base import BaseAdapter, Deal, SiteBlockedError
from .bazos import BazosAdapter
from .ebay import EbayAdapter
from .facebook import FacebookAdapter
from .profile_adapter import ProfileAdapter

logger = logging.getLogger(__name__)

class _AdapterRegistry(dict[str, type]):
    """Dict whose iteration exposes only BaseAdapter subclasses.

    Third-party plugins may register arbitrary objects; iteration (used by
    diagnostics/tests that assume scraper adapters) skips anything that is not
    a ``BaseAdapter`` subclass, while membership checks (``in``) and ``[]``
    still report all registered entries.
    """

    def _is_adapter(self, value: object) -> bool:
        return isinstance(value, type) and issubclass(value, BaseAdapter)

    def __iter__(self):
        for key, value in super().items():
            if self._is_adapter(value):
                yield key

    def keys(self):
        return (k for k, v in super().items() if self._is_adapter(v))

    def values(self):
        for value in super().values():
            if self._is_adapter(value):
                yield value

    def items(self):
        for key, value in super().items():
            if self._is_adapter(value):
                yield key, value

    def __len__(self) -> int:
        return sum(1 for v in super().values() if self._is_adapter(v))


ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = _AdapterRegistry(
    {
        "alza": AlzaAdapter,
        "amazon": AmazonAdapter,
        "bazos": BazosAdapter,
        "backmarket": BackMarketAdapter,
        "facebook": FacebookAdapter,
        "ebay": EbayAdapter,
    }
)


def get_adapter(name: str) -> type[BaseAdapter]:
    """Get adapter class by name."""
    if name not in ADAPTER_REGISTRY:
        msg = f"No adapter for site: {name}. Available: {list(ADAPTER_REGISTRY.keys())}"
        raise ValueError(msg)
    return ADAPTER_REGISTRY[name]


def load_entry_point_adapters() -> None:
    """Load third-party adapters registered under the ``ads.adapters`` entry point group.

    Entry point name becomes the adapter key. A single bad plugin is logged and
    skipped so it cannot break the built-in registry.
    """
    eps = _md.entry_points(group="ads.adapters")
    for ep in eps:
        try:
            ADAPTER_REGISTRY[ep.name] = ep.load()
        except Exception as exc:  # noqa: BLE001 - one bad plugin must not break core
            logger.warning("Failed to load adapter plugin %s: %s", ep.name, exc)


load_entry_point_adapters()


__all__ = [
    "ADAPTER_REGISTRY",
    "AlzaAdapter",
    "AmazonAdapter",
    "BackMarketAdapter",
    "BaseAdapter",
    "BazosAdapter",
    "Deal",
    "EbayAdapter",
    "FacebookAdapter",
    "ProfileAdapter",
    "SiteBlockedError",
    "get_adapter",
    "load_entry_point_adapters",
]
