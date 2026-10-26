"""Detection order for product domains: override, built-ins, cached drafts, generic."""

from __future__ import annotations

from collections.abc import Iterable

from src.output.domains.base import DomainProfile
from src.output.domains.bike import BIKE
from src.output.domains.car import CAR
from src.output.domains.computer import COMPUTER
from src.output.domains.furniture import FURNITURE
from src.output.domains.generic import GENERIC
from src.output.domains.phone import PHONE
from src.text.normalize import fold

# Insertion order breaks ties: built-ins are checked before caller-supplied drafts.
DOMAIN_REGISTRY: dict[str, DomainProfile] = {
    GENERIC.name: GENERIC,
    COMPUTER.name: COMPUTER,
    BIKE.name: BIKE,
    PHONE.name: PHONE,
    CAR.name: CAR,
    FURNITURE.name: FURNITURE,
}


def get(name: str) -> DomainProfile:
    """Return the profile registered under name, or raise KeyError."""
    return DOMAIN_REGISTRY[name]


def detect(
    text: str,
    override: str | None = None,
    extra: Iterable[DomainProfile] = (),
) -> DomainProfile:
    """Pick the profile that matches a listing's text most specifically."""
    if override:
        return get(override)

    folded = fold(text)
    best: DomainProfile | None = None
    best_score = 0
    for profile in list(DOMAIN_REGISTRY.values()) + list(extra):
        score = profile.matches(folded)
        if score > best_score:
            best = profile
            best_score = score
    return best or GENERIC
