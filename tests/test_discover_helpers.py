"""Pure discovery helper tests (no browser)."""

from datetime import datetime
from pathlib import Path

from scripts.discover_sites import (
    build_profile,
    classify_control,
    control_to_filter_spec,
    derive_extraction,
    derive_search_spec,
    option_value_map,
    registry_currency,
)
from src.searcher.site_profiles import save_profile
from src.searcher.site_registry import seed_query


def test_seed_query_uses_site_override():
    assert seed_query("sreality", "general") == "byt"
    assert seed_query("autobazar_sk", "auto") == "skoda fabia"
    assert seed_query("mimibazar", "electronics") == "notebook"


def test_seed_query_uses_category_default():
    assert seed_query("alza", "electronics") == "notebook"
    assert seed_query("bazos", "appliances") == "washing machine"
    assert seed_query("bazos", "general") == "deal"


def test_derive_search_spec_replaces_query_param():
    spec = derive_search_spec("https://x.test/search?q=notebook&page=1", "notebook")
    assert spec.query_param == "q"
    assert spec.url_template == "https://x.test/search?q={query}&page=1"


def test_derive_search_spec_handles_encoded_space():
    spec = derive_search_spec("https://x.test/search?q=washing+machine&page=1", "washing machine")
    assert spec.query_param == "q"
    assert spec.url_template == "https://x.test/search?q={query}&page=1"


def test_derive_search_spec_keeps_fixed_url_when_query_not_found():
    spec = derive_search_spec("https://x.test/deals", "notebook")
    assert spec.query_param is None
    assert spec.url_template == "https://x.test/deals"


def test_classify_control_price_max():
    control = {"tag": "input", "type": "text", "name": "max", "label": "Cena do"}
    assert classify_control(control) == "price_max"


def test_classify_control_condition_select():
    control = {"tag": "select", "name": "stav", "label": "Stav tovaru"}
    assert classify_control(control) == "condition"


def test_classify_control_ignores_search_box():
    control = {"tag": "input", "type": "search", "name": "q", "label": "Hľadať"}
    assert classify_control(control) is None


def test_classify_control_shipping_and_sort():
    assert classify_control({"tag": "select", "label": "Doprava"}) == "shipping"
    assert classify_control({"tag": "select", "label": "Zoradiť podľa"}) == "sort"


def test_option_value_map_condition():
    control = {
        "options": [
            {"value": "1", "text": "Nové"},
            {"value": "2", "text": "Použité"},
            {"value": "3", "text": "Refurbished"},
            {"value": "4", "text": "Rozbalené"},
        ]
    }
    assert option_value_map(control, "condition") == {
        "new": "1",
        "used": "2",
        "refurbished": "3",
        "open_box": "4",
    }


def test_option_value_map_sort():
    control = {
        "options": [
            {"value": "price", "text": "Najlacnejšie"},
            {"value": "-price", "text": "Najdrahšie"},
        ]
    }
    assert option_value_map(control, "sort") == {
        "price_asc": "price",
        "price_desc": "-price",
    }


def test_control_to_filter_spec_builds_url_and_ui():
    control = {
        "tag": "input",
        "type": "text",
        "name": "max",
        "selector": "input[name='max']",
        "label": "Cena do",
    }
    spec = control_to_filter_spec(control, "price_max")
    assert spec is not None
    assert spec.url is not None
    assert spec.url.param == "max"
    assert spec.ui is not None
    assert spec.ui.kind == "input"
    assert spec.ui.selector == "input[name='max']"


def test_control_to_filter_spec_rejects_missing_selector():
    assert control_to_filter_spec({"tag": "input", "name": "max"}, "price_max") is None


def test_derive_extraction_uses_existing_selectors():
    extraction = derive_extraction("alza")
    assert extraction.item_selector == ".browsingitem"
    assert extraction.title_selector == ".name"
    assert extraction.link_selector is not None


def test_build_profile_sets_category_and_filters():
    controls = [
        {
            "tag": "input",
            "type": "text",
            "name": "max",
            "selector": "input[name='max']",
            "label": "Cena do",
        },
        {
            "tag": "select",
            "name": "stav",
            "selector": "select[name='stav']",
            "label": "Stav",
            "options": [
                {"value": "1", "text": "Nové"},
                {"value": "2", "text": "Použité"},
            ],
        },
    ]
    profile = build_profile(
        "alza_cz",
        "https://www.alza.cz",
        "https://www.alza.cz/search.htm?exps=notebook",
        "notebook",
        "electronics",
        controls,
        derive_extraction("alza"),
        "validated",
        input_selector="input[name='q']",
        notes="test",
    )
    assert profile.site_id == "alza_cz"
    assert profile.status == "validated"
    assert profile.last_verified == datetime.now().astimezone().date()
    assert profile.search.category_urls["electronics"] == (
        "https://www.alza.cz/search.htm?exps={query}"
    )
    assert profile.search.input_selector == "input[name='q']"
    assert profile.filters.price_max is not None
    assert profile.filters.price_max.url is not None
    assert profile.filters.price_max.url.param == "max"
    assert profile.filters.condition is not None
    assert profile.filters.condition.ui is not None
    assert profile.filters.condition.ui.value_map == {"new": "1", "used": "2"}


def test_registry_currency_follows_the_site_registry():
    assert registry_currency("bazos_cz") == "CZK"
    assert registry_currency("bazos") == "EUR"
    assert registry_currency("does-not-exist") == "EUR"


def test_build_profile_saved_yaml_has_no_secret_query_params(tmp_path: Path):
    profile = build_profile(
        "alza_cz",
        "https://www.alza.cz",
        "https://www.alza.cz/search.htm?exps=notebook&token=secret",
        "notebook",
        "electronics",
        [],
        derive_extraction("alza"),
        "draft",
    )
    path = save_profile(profile, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "token=" not in text
    assert "exps={query}" in text
