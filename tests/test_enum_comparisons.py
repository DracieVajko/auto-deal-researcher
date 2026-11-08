from src.agents.research.site_selection import SiteSelectionAgent
from src.config.models import Category, Condition
from src.searcher.adapters.base import Deal
from src.searcher.adapters.bazos import BazosAdapter
from src.searcher.filter_engine import FilterEngine
from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import SearchSpec, SiteProfile


def test_condition_any_matches_regardless_of_input_form():
    deal = Deal(url="https://x/1", title="X", condition="new")
    assert deal.matches_condition(Condition.ANY) is True
    assert deal.matches_condition("any") is True


def test_condition_specific_does_not_match_other():
    deal = Deal(url="https://x/1", title="X", condition="used")
    assert deal.matches_condition(Condition.NEW) is False
    assert deal.matches_condition("new") is False


def test_condition_enum_member_selects_specific_condition():
    deal = Deal(url="https://x/1", title="X", condition="used")
    assert deal.matches_condition(Condition.USED) is True
    assert deal.matches_condition(Condition.REFURBISHED) is False


def test_category_any_matches_regardless_of_input_form():
    deal = Deal(url="https://x/1", title="X", category="electronics")
    assert deal.matches_category(Category.ANY) is True
    assert deal.matches_category("any") is True


def test_category_enum_member_selects_specific_category():
    deal = Deal(url="https://x/1", title="X", category="electronics")
    assert deal.matches_category(Category.ELECTRONICS) is True
    assert deal.matches_category(Category.AUTO) is False


def test_adapter_supported_conditions_match_enum_member():
    adapter = BazosAdapter()
    assert adapter.matches_condition(Condition.USED) is True
    assert adapter.matches_condition(Condition.NEW) is False
    assert adapter.matches_condition(Condition.ANY) is True
    assert adapter.matches_condition("any") is True


def test_adapter_supported_categories_match_enum_member():
    adapter = BazosAdapter()
    assert adapter.matches_category(Category.ELECTRONICS) is True
    assert adapter.matches_category(Category.ANY) is True
    assert adapter.matches_category("any") is True
    assert adapter.matches_category("boats") is False


def _profile(search=None):
    data = {
        "site_id": "x",
        "base_url": "https://x.test",
        "status": "validated",
        "search": search or {},
        "filters": {},
    }
    return SiteProfile.model_validate(data)


def test_filter_engine_enum_category_any_behaves_like_string_any():
    profile = _profile(search=SearchSpec(url_template="https://x.test/s?q={query}"))
    by_enum = FilterEngine.build_search_url(profile, "pc", Category.ANY, SearchFilters())
    by_string = FilterEngine.build_search_url(profile, "pc", "any", SearchFilters())
    assert by_enum == by_string == "https://x.test/s?q=pc"


def test_site_selection_enum_any_matches_string_any():
    agent = SiteSelectionAgent()
    assert agent._select_sites(Condition.ANY, Category.ANY) == agent._select_sites("any", "any")
