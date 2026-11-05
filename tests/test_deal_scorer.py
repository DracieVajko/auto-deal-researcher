"""Tests for deal_scorer.py (spec-based deal scoring)."""

from src.intelligence.deal_scorer import DealScorer, DealScore, ScoringCriteria


class FakeQuote:
    def __init__(self, trust=1.0, effective=None):
        self.trust = trust
        self.effective_price_eur = effective


class FakeDeal:
    def __init__(self, url="https://example.com/1", title="Test", price_eur=18000.0,
                 condition="used", site_name="bazos", trust=1.0,
                 effective=None, warranty=None, seller_type="classifieds",
                 metadata=None):
        self.url = url
        self.title = title
        self.price_eur = price_eur
        self.condition = condition
        self.site_name = site_name
        self.price_quote = FakeQuote(trust=trust, effective=effective) if effective else None
        self.warranty = warranty
        self.seller_type = seller_type
        self.metadata = metadata or {}


def test_score_perfect_match():
    scorer = DealScorer()
    ref = {
        "item_name": "Citroen eC3",
        "category": "auto",
        "price_eur": 18000.0,
        "power_kw": 83.0,
        "weight_kg": 1420.0,
    }
    deal = FakeDeal(price_eur=18000.0, condition="new", warranty="2 years")
    deal.metadata = {"power_kw": 83.0, "weight_kg": 1420.0}
    result = scorer.score(deal, ref)
    assert result.score >= 90.0
    assert result.matches_requirements


def test_score_price_mismatch():
    scorer = DealScorer()
    ref = {
        "item_name": "Citroen eC3",
        "category": "auto",
        "price_eur": 18000.0,
        "power_kw": 83.0,
    }
    deal = FakeDeal(price_eur=50000.0, condition="used")
    deal.metadata = {"power_kw": 83.0}
    result = scorer.score(deal, ref)
    # Price is way off, should lower the score
    assert result.score < 80.0


def test_score_condition_new():
    scorer = DealScorer()
    ref = {"item_name": "Test", "category": "auto"}
    deal = FakeDeal(condition="new")
    result = scorer.score(deal, ref)
    assert result.breakdown.get("condition", 0) == 100.0


def test_score_condition_used():
    scorer = DealScorer()
    ref = {"item_name": "Test", "category": "auto"}
    deal = FakeDeal(condition="used")
    result = scorer.score(deal, ref)
    assert result.breakdown.get("condition", 0) == 40.0


def test_score_condition_unknown():
    scorer = DealScorer()
    ref = {"item_name": "Test", "category": "auto"}
    deal = FakeDeal(condition="unknown")
    result = scorer.score(deal, ref)
    assert result.breakdown.get("condition", 0) == 50.0


def test_score_trust():
    scorer = DealScorer()
    ref = {"item_name": "Test", "category": "auto"}
    deal = FakeDeal(trust=0.65, effective=100.0)
    result = scorer.score(deal, ref)
    assert result.breakdown.get("trust", 0) == 65.0


def test_score_no_applicable_criteria():
    scorer = DealScorer()
    ref = {}
    deal = FakeDeal(condition="unknown", warranty=None, seller_type=None)
    result = scorer.score(deal, ref)
    # Only condition applies (no price, power, etc.)
    assert result.score == 50.0  # condition unknown = 50


def test_scoring_criteria_sum():
    criteria = ScoringCriteria()
    total = (criteria.price + criteria.power + criteria.weight +
             criteria.battery + criteria.condition + criteria.warranty + criteria.trust)
    assert total == 100.0
