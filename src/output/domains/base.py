"""Domain profiles: one product type's keywords, extractors and constraints."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from src.text.normalize import fold

logger = logging.getLogger(__name__)

Constraint = Callable[[dict[str, str], str | None], tuple[list[str], bool]]
Extractor = Callable[[str], "str | None"]


def _keyword_hits(folded: str, keywords: tuple[str, ...]) -> list[str]:
    """Return the keywords present in folded text, using word boundaries."""
    hits = []
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", folded):
            hits.append(keyword)
    return hits


@dataclass(frozen=True)
class DomainProfile:
    """Everything the pipeline needs to know about one product type.

    Keywords and aliases are stored folded, so a profile never asks which
    language a listing is in: it matches every language at once.
    """

    name: str
    strong_keywords: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    key_specs: tuple[str, ...] = ()
    aliases: Mapping[str, str] = field(default_factory=dict)
    extractors: Mapping[str, Extractor] = field(default_factory=dict)
    constraints: tuple[Constraint, ...] = ()
    optional_rows: tuple[str, ...] = ()
    weights: Mapping[str, float] | None = None
    source: str = "builtin"

    def matches(self, folded: str) -> int:
        """Score how specifically this profile matches folded text; 0 means no match."""
        strong = _keyword_hits(folded, self.strong_keywords)
        if strong:
            return 1000 + max(len(keyword) for keyword in strong)

        regular = _keyword_hits(folded, self.keywords)
        if len(regular) < 2:
            return 0
        return 100 * len(regular) + max(len(keyword) for keyword in regular)

    def extract(self, text: str) -> dict[str, str]:
        """Run this profile's extractors on raw text and keep only stated values."""
        folded = fold(text)
        specs: dict[str, str] = {}
        for key in self.key_specs or tuple(self.extractors):
            extractor = self.extractors.get(key)
            if extractor is None:
                continue
            try:
                value = extractor(folded)
            except Exception as exc:  # noqa: BLE001 - a broken pattern means "not stated"
                logger.warning("extractor %s/%s failed: %s", self.name, key, exc)
                continue
            if value is None:
                continue
            cleaned = value.strip()
            if cleaned:
                specs[key] = cleaned
        return specs

    def normalise_specs(self, specs: Mapping[str, str]) -> dict[str, str]:
        """Apply aliases and drop keys this profile does not define."""
        normalised: dict[str, str] = {}
        for key, value in specs.items():
            mapped = self.aliases.get(key, key)
            if mapped == "price_eur":
                continue
            if self.key_specs and mapped not in self.key_specs:
                continue
            normalised[mapped] = value
        return normalised

    def check(
        self, specs: dict[str, str], prompt: str | None
    ) -> tuple[list[str], bool]:
        """Run this profile's constraints and combine their verdicts."""
        messages: list[str] = []
        disqualify = False
        for constraint in self.constraints:
            try:
                found, veto = constraint(specs, prompt)
            except Exception as exc:  # noqa: BLE001 - a broken check must not kill the run
                logger.warning("constraint %s failed: %s", self.name, exc)
                continue
            messages.extend(found)
            disqualify = disqualify or veto
        return messages, disqualify
