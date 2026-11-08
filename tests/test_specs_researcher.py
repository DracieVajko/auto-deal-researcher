"""Tests for ItemSpecsResearcher (sub-project 1: specs research & review reading)."""

import json
from unittest.mock import patch

from src.intelligence.specs_researcher import ItemSpecs, ItemSpecsResearcher


class FakeLLM:
    """Deterministic fake LLM for testing spec extraction."""

    def __init__(self, specs_json: str, review_json: str):
        self._specs = specs_json
        self._review = review_json

    def chat_json(self, system: str, user: str, max_tokens: int = 400):
        if "review" in system.lower() or "review" in user.lower():
            return json.loads(self._review)
        return json.loads(self._specs)


class FakeStorage:
    """Minimal fake storage for testing."""

    def __init__(self):
        self.saved = None
        self.cached = None

    def get_item_specs(self, item_name: str):
        return self.cached

    def save_item_specs(self, item_name, category, specs, review, source_urls):
        self.saved = {
            "item_name": item_name,
            "category": category,
            "specs": specs,
            "review": review,
            "source_urls": source_urls,
        }


def test_item_specs_to_dict_and_from_dict():
    specs = ItemSpecs(
        item_name="Citroen eC3",
        category="auto",
        brand="Citroen",
        model="eC3",
        year=2024,
        price_eur=18990.0,
        power_kw=83.0,
        battery_kwh=44.0,
        range_km=350.0,
        weight_kg=1420.0,
    )
    specs.review.summary = "Good small EV"
    specs.review.pros = ["Cheap", "Compact"]
    specs.review.cons = ["Slow charging"]
    d = specs.to_dict()
    assert d["item_name"] == "Citroen eC3"
    assert d["power_kw"] == 83.0
    assert d["review"]["summary"] == "Good small EV"

    restored = ItemSpecs.from_dict(d)
    assert restored.item_name == "Citroen eC3"
    assert restored.power_kw == 83.0
    assert restored.review.summary == "Good small EV"
    assert restored.review.pros == ["Cheap", "Compact"]


def test_fallback_specs_extracts_year():
    specs = ItemSpecsResearcher._fallback_specs("Citroen eC3 2024", "auto")
    assert specs.year == 2024
    assert specs.brand == "Citroen"
    assert specs.model == "eC3 2024"


def test_research_returns_cached_specs():
    storage = FakeStorage()
    storage.cached = {
        "item_name": "Citroen eC3",
        "category": "auto",
        "specs": {"power_kw": 83.0},
        "review": {"summary": "cached", "pros": [], "cons": [], "source_count": 0},
        "source_urls": [],
        "researched_at": "2026-11-05",
    }
    researcher = ItemSpecsResearcher(storage=storage, llm=None, config=None)
    specs = researcher.research("Citroen eC3")
    assert specs.power_kw == 83.0
    assert specs.review.summary == "cached"
    assert storage.saved is None  # no re-save


def test_research_calls_llm_and_saves(monkeypatch):
    storage = FakeStorage()
    llm = FakeLLM(
        specs_json=json.dumps({
            "category": "auto",
            "brand": "Citroen",
            "model": "eC3",
            "power_kw": 83.0,
            "battery_kwh": 44.0,
        }),
        review_json=json.dumps({
            "summary": "Good small city EV",
            "pros": ["Affordable", "Compact"],
            "cons": ["Limited range"],
        }),
    )
    researcher = ItemSpecsResearcher(storage=storage, llm=llm, config=None)
    researcher.enabled = True

    from src.research.web_search import WebSource

    fake_sources = [
        WebSource(
            title="Citroen eC3 specs",
            url="https://example.com/specs",
            snippet="Citroen eC3 electric car 83 kW 44 kWh battery 350 km range",
        )
    ]
    with patch.object(researcher, "_search", return_value=fake_sources):
        specs = researcher.research("Citroen eC3")

    assert specs.brand == "Citroen"
    assert specs.model == "eC3"
    assert specs.power_kw == 83.0
    assert specs.battery_kwh == 44.0
    assert specs.review.summary == "Good small city EV"
    assert specs.review.pros == ["Affordable", "Compact"]
    assert storage.saved is not None
    assert storage.saved["item_name"] == "Citroen eC3"


def test_research_without_llm_uses_fallback():
    storage = FakeStorage()
    researcher = ItemSpecsResearcher(storage=storage, llm=None, config=None)
    researcher.enabled = True

    with patch.object(researcher, "_search", return_value=[]):
        specs = researcher.research("Tesla Model 3 2023", category="auto")

    assert specs.brand == "Tesla"
    assert specs.model == "Model 3 2023"
    assert specs.year == 2023
    assert specs.power_kw is None
    assert storage.saved is not None


def test_research_disabled_returns_empty():
    storage = FakeStorage()
    researcher = ItemSpecsResearcher(storage=storage, llm=None, config=None)
    researcher.enabled = False

    specs = researcher.research("Citroen eC3")
    assert specs.item_name == "Citroen eC3"
    assert specs.category == "auto"  # real config default
    assert storage.saved is None
