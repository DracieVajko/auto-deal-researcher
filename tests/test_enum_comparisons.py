from src.config.models import Category, Condition
from src.searcher.adapters.base import Deal


def test_condition_any_matches_regardless_of_input_form():
    deal = Deal(url="https://x/1", title="X", condition="new")
    assert deal.matches_condition(Condition.ANY) is True
    assert deal.matches_condition("any") is True

def test_condition_specific_does_not_match_other():
    deal = Deal(url="https://x/1", title="X", condition="used")
    assert deal.matches_condition(Condition.NEW) is False
    assert deal.matches_condition("new") is False

def test_category_any_matches_regardless_of_input_form():
    deal = Deal(url="https://x/1", title="X", category="electronics")
    assert deal.matches_category(Category.ANY) is True
    assert deal.matches_category("any") is True
