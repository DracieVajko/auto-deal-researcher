"""Item specs research for the replacement finder.

Researches an arbitrary item's specs from the web (EV range, battery kWh,
weight, dimensions, price, etc.), reads and summarizes reviews, and caches
the result in SQLite so subsequent runs don't re-research the same item.

This is the foundation of the replacement/alternative finder: before you can
search for similar items, you need to know what the reference item actually
is.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

from src.config import load_config
from src.llm.client import LLMClient
from src.research.web_search import WebSource, search_web
from src.storage.manager import StorageManager

logger = logging.getLogger(__name__)


@dataclass
class ReviewSummary:
    """Summarised reviews for an item."""

    summary: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    source_count: int = 0


@dataclass
class ItemSpecs:
    """Structured specs for one researched item.

    ``extras`` holds anything that doesn't fit a named field (voltage_volt,
    wheel_size_inch, storage_gb, etc.) — consistent with the pricing model.
    """

    item_name: str
    category: str = "general"
    condition: str = "any"
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    price_eur: float | None = None
    power_kw: float | None = None
    power_hp: float | None = None
    weight_kg: float | None = None
    length_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    battery_kwh: float | None = None
    range_km: float | None = None
    extras: dict[str, str] = field(default_factory=dict)
    review: ReviewSummary = field(default_factory=ReviewSummary)
    source_urls: list[str] = field(default_factory=list)
    researched_at: str = ""

    def to_dict(self) -> dict:
        return {
            "item_name": self.item_name,
            "category": self.category,
            "condition": self.condition,
            "brand": self.brand,
            "model": self.model,
            "year": self.year,
            "price_eur": self.price_eur,
            "power_kw": self.power_kw,
            "power_hp": self.power_hp,
            "weight_kg": self.weight_kg,
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "battery_kwh": self.battery_kwh,
            "range_km": self.range_km,
            "extras": self.extras,
            "review": {
                "summary": self.review.summary,
                "pros": self.review.pros,
                "cons": self.review.cons,
                "source_count": self.review.source_count,
            },
            "source_urls": self.source_urls,
            "researched_at": self.researched_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ItemSpecs:
        # Specs may be nested under "specs" key (as returned by get_item_specs)
        # or flat (as returned by to_dict).
        specs_data = data.get("specs") or data
        review = ReviewSummary(
            summary=data.get("review", {}).get("summary", ""),
            pros=data.get("review", {}).get("pros", []),
            cons=data.get("review", {}).get("cons", []),
            source_count=data.get("review", {}).get("source_count", 0),
        )
        return cls(
            item_name=data["item_name"],
            category=specs_data.get("category", "general"),
            condition=specs_data.get("condition", "any"),
            brand=specs_data.get("brand"),
            model=specs_data.get("model"),
            year=specs_data.get("year"),
            price_eur=specs_data.get("price_eur"),
            power_kw=specs_data.get("power_kw"),
            power_hp=specs_data.get("power_hp"),
            weight_kg=specs_data.get("weight_kg"),
            length_mm=specs_data.get("length_mm"),
            width_mm=specs_data.get("width_mm"),
            height_mm=specs_data.get("height_mm"),
            battery_kwh=specs_data.get("battery_kwh"),
            range_km=specs_data.get("range_km"),
            extras=specs_data.get("extras", {}),
            review=review,
            source_urls=data.get("source_urls", []),
            researched_at=data.get("researched_at", ""),
        )


class ItemSpecsResearcher:
    """Researches an item's specs and reviews from the web.

    Uses the existing LLMClient for structured JSON extraction and the
    existing DuckDuckGo/Bing web search for source pages. Results are cached
    in SQLite via StorageManager.
    """

    def __init__(
        self,
        storage: StorageManager | None = None,
        llm: LLMClient | None = None,
        config=None,
    ):
        self.config = config or load_config()
        self.storage = storage or StorageManager(self.config.storage.db_path)
        self.llm = llm or LLMClient(self.config)
        self.enabled = getattr(
            self.config.search, "specs_research", None
        ) and self.config.search.specs_research.enabled
        self.default_category = (
            self.config.search.specs_research.default_category
            if self.enabled
            else "general"
        )
        self.max_sources = (
            self.config.search.specs_research.max_sources if self.enabled else 5
        )
        self.max_review_snippets = (
            self.config.search.specs_research.max_review_snippets
            if self.enabled
            else 8
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def research(self, item_name: str, category: str | None = None) -> ItemSpecs:
        """Research specs and reviews for *item_name*.

        Returns cached specs if already researched, otherwise fetches from the
        web, extracts via LLM, and stores in SQLite.
        """
        category = category or self.default_category

        cached = self.storage.get_item_specs(item_name)
        if cached is not None:
            logger.info("Specs cache hit for %s", item_name)
            return ItemSpecs.from_dict(cached)

        if not self.enabled:
            logger.info("Specs research disabled; returning empty specs")
            return ItemSpecs(item_name=item_name, category=category)

        logger.info("Researching specs for %s (category=%s)", item_name, category)

        # Search for spec pages and review pages
        spec_query = f"{item_name} specifications technical data"
        review_query = f"{item_name} review pros cons"

        spec_sources = self._search(spec_query, self.max_sources)
        review_sources = self._search(review_query, self.max_review_snippets)

        all_snippets = " ".join(s.snippet for s in spec_sources + review_sources)

        # Extract specs via LLM with deterministic fallback
        specs = self._extract_specs(item_name, category, all_snippets, spec_sources)

        # Extract reviews via LLM with deterministic fallback
        review = self._extract_reviews(item_name, all_snippets, review_sources)
        specs.review = review

        specs.source_urls = [s.url for s in spec_sources + review_sources]
        specs.researched_at = datetime.now(UTC).isoformat()

        # Persist
        self.storage.save_item_specs(
            item_name=item_name,
            category=category,
            specs=specs.to_dict(),
            review={
                "summary": review.summary,
                "pros": review.pros,
                "cons": review.cons,
                "source_count": review.source_count,
            },
            source_urls=specs.source_urls,
        )

        logger.info(
            "Specs research complete for %s: %d spec fields, %d review sources",
            item_name,
            len(specs.to_dict()),
            review.source_count,
        )
        return specs

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _search(self, query: str, limit: int) -> list[WebSource]:
        """Run a web search and return sources."""
        try:
            return search_web(query, max_results=limit)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Web search failed for %r: %s", query, exc)
            return []

    def _extract_specs(
        self,
        item_name: str,
        category: str,
        snippets: str,
        sources: list[WebSource],
    ) -> ItemSpecs:
        """Extract structured specs from web snippets via LLM, with fallback."""
        # Deterministic fallback: brand/model/year from item name
        fallback = self._fallback_specs(item_name, category)

        if not self.llm or not snippets.strip():
            logger.info("LLM unavailable or no snippets; using fallback specs")
            return fallback

        system = (
            "You extract structured product specifications from web search "
            "snippets. Return ONLY a JSON object with keys: "
            "category, condition, brand, model, year, price_eur, power_kw, "
            "power_hp, weight_kg, length_mm, width_mm, height_mm, battery_kwh, "
            "range_km, extras. Use null for unknown values. Prices are EUR. "
            "Power in kW (convert hp if needed). Weight in kg. Dimensions in mm. "
            "Battery in kWh (EVs only). Range in km. ``extras`` is an object of "
            "string key/value pairs for anything else (voltage_volt, "
            "wheel_size_inch, storage_gb, etc.). Do not invent values."
        )
        user = (
            f"Item: {item_name}\nCategory: {category}\n"
            f"Search snippets: {snippets[:4000]}\n"
            "Extract the specs."
        )
        try:
            data = self.llm.chat_json(system, user, max_tokens=600)
            if isinstance(data, dict):
                specs = ItemSpecs(
                    item_name=item_name,
                    category=data.get("category") or category,
                    condition=data.get("condition") or "any",
                    brand=data.get("brand") or fallback.brand,
                    model=data.get("model") or fallback.model,
                    year=data.get("year") or fallback.year,
                    price_eur=data.get("price_eur") or fallback.price_eur,
                    power_kw=data.get("power_kw") or fallback.power_kw,
                    power_hp=data.get("power_hp") or fallback.power_hp,
                    weight_kg=data.get("weight_kg") or fallback.weight_kg,
                    length_mm=data.get("length_mm") or fallback.length_mm,
                    width_mm=data.get("width_mm") or fallback.width_mm,
                    height_mm=data.get("height_mm") or fallback.height_mm,
                    battery_kwh=data.get("battery_kwh") or fallback.battery_kwh,
                    range_km=data.get("range_km") or fallback.range_km,
                    extras=data.get("extras") or fallback.extras,
                )
                return specs
        except Exception as exc:
            logger.warning("LLM spec extraction failed: %s", exc)
        return fallback

    def _extract_reviews(
        self,
        item_name: str,
        snippets: str,
        sources: list[WebSource],
    ) -> ReviewSummary:
        """Extract review summary and pros/cons via LLM, with fallback."""
        if not self.llm or not snippets.strip():
            logger.info("LLM unavailable or no snippets; using empty review")
            return ReviewSummary(source_count=len(sources))

        system = (
            "You summarise product reviews from web snippets. Return ONLY a "
            "JSON object with keys: summary (1-2 sentences), pros (list of "
            "strings), cons (list of strings). Keep each pro/con short. "
            "Use empty lists if none found. Do not invent claims."
        )
        user = (
            f"Item: {item_name}\nSearch snippets: {snippets[:3000]}\n"
            "Summarise the reviews."
        )
        try:
            data = self.llm.chat_json(system, user, max_tokens=400)
            if isinstance(data, dict):
                return ReviewSummary(
                    summary=data.get("summary", ""),
                    pros=data.get("pros", []) or [],
                    cons=data.get("cons", []) or [],
                    source_count=len(sources),
                )
        except Exception as exc:
            logger.warning("LLM review extraction failed: %s", exc)
        return ReviewSummary(source_count=len(sources))

    @staticmethod
    def _fallback_specs(item_name: str, category: str) -> ItemSpecs:
        """Deterministic brand/model/year extraction from item name."""
        brand = None
        model = None
        year = None

        # Year: 4-digit number starting with 19 or 20
        year_match = re.search(r"\b(19|20)\d{2}\b", item_name)
        if year_match:
            year = int(year_match.group(0))

        # Brand: first capitalised word before the model
        words = item_name.split()
        if words:
            brand = words[0].strip(".,-")
            model = " ".join(words[1:]) or None

        return ItemSpecs(
            item_name=item_name,
            category=category,
            brand=brand,
            model=model,
            year=year,
        )
