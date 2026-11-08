"""Structural protocols shared by the LLM layer.

Keeping these here lets ``src.llm`` depend on a shape rather than on the
concrete ``Deal`` dataclass in ``src.searcher.adapters.base``, breaking the
llm -> searcher coupling.
"""

from __future__ import annotations

from typing import Protocol


class DealLike(Protocol):
    """The subset of a deal the LLM client actually reads."""

    url: str
    title: str
    price_eur: float
    condition: str
    category: str
    site_name: str
    metadata: dict
