"""Tests for comparison_engine.py (multi-candidate comparison)."""

from src.intelligence.comparison_engine import ComparisonEngine, ComparisonResult
from src.intelligence.deal_scorer import DealScorer


class FakeQuote:
    def __init__(self, trust=1.0, effective=None):
        self.trust = trust
        self.effective_price_eur = effective


class FakeDeal:
    def __init__(self, url="https://example.com/1", title="Test", price_eur=18000.0,
                 condition="used", site_name="bazos", trust=1.0, effective=None,
                 metadata=None):
        self.url = url
        self.title = title
        self.price_eur = price_eur
        self.condition = condition
        self.site_name = site_name
        self.price_quote = FakeQuote(trust=trust, effective=effective) if effective else None
        self.metadata = metadata or {}


def test_compare_ranks_by_score():
    engine = ComparisonEngine()
    ref = {
        "item_name": "Citroen eC3",
        "category": "auto",
        "price_eur": 18000.0,
        "power_kw": 83.0,
    }
    # Cheaper deal should score higher on price
    deal1 = FakeDeal(url="https://a/1", title="Cheap car", price_eur=17000.0, condition="new")
    deal1.metadata = {"power_kw": 83.0}
    # Expensive deal should score lower
    deal2 = FakeDeal(url="https://a/2", title="Expensive car", price_eur=40000.0, condition="used")
    deal2.metadata = {"power_kw": 83.0}

    result = engine.compare(ref, [deal2, deal1])
    assert result.total_candidates == 2
    assert result.winner is not None
    assert result.winner["title"] == "Cheap car"
    assert result.winner["rank"] == 1
    assert result.runner_ups[0]["title"] == "Expensive car"


def test_compare_empty():
    engine = ComparisonEngine()
    result = engine.compare({"item_name": "Test"}, [])
    assert result.total_candidates == 0
    assert result.winner is None
    assert result.candidates == []


def test_comparison_table():
    engine = ComparisonEngine()
    ref = {"item_name": "Test", "category": "auto"}
    deal = FakeDeal(url="https://a/1", title="Test car", price_eur=15000.0)
    result = engine.compare(ref, [deal])
    assert len(result.comparison_table) == 1
    assert result.comparison_table[0]["rank"] == 1
    assert result.comparison_table[0]["title"] == "Test car"
