"""Canonical search filters and prompt/CLI parsing."""

import pytest

from src.config.models import SearchConfig
from src.searcher.filters import (
    SearchFilters,
    filters_from_mapping,
    from_cli,
    merge_filters,
    parse_filters_from_text,
    resolve_filters,
)


def test_rejects_inverted_price_range():
    with pytest.raises(ValueError):
        SearchFilters(min_price=500, max_price=100).validate()


def test_rejects_negative_price():
    with pytest.raises(ValueError):
        SearchFilters(min_price=-1).validate()


def test_rejects_unknown_condition():
    with pytest.raises(ValueError):
        SearchFilters(condition="broken").validate()


def test_merge_cli_overrides_prompt_and_keeps_extras():
    base = SearchFilters(max_price=500, extras={"socket": "AM5"})
    override = SearchFilters(max_price=300, brand="amd")
    merged = merge_filters(base, override)
    assert merged.max_price == 300
    assert merged.brand == "amd"
    assert merged.extras == {"socket": "AM5"}


def test_merge_extras_override_same_key():
    base = SearchFilters(extras={"socket": "AM5", "ram": "32"})
    override = SearchFilters(extras={"ram": "64"})
    assert merge_filters(base, override).extras == {"socket": "AM5", "ram": "64"}


def test_parse_price_from_slovak_prompt():
    f = parse_filters_from_text("mini PC do 400 EUR, AMD")
    assert f.max_price == 400


def test_parse_price_with_space_and_currency_symbol():
    f = parse_filters_from_text("notebook od 1 200 € do 1 500 €")
    assert f.min_price == 1200
    assert f.max_price == 1500


def test_parse_price_range_with_dash():
    f = parse_filters_from_text("grafika 300-500 EUR")
    assert f.min_price == 300
    assert f.max_price == 500


def test_parse_condition_and_shipping():
    f = parse_filters_from_text("použitý notebook, doprava zdarma")
    assert f.condition == "used"
    assert f.shipping == "free"


def test_parse_sort():
    assert parse_filters_from_text("najlacnejšie SSD").sort == "price_asc"
    assert parse_filters_from_text("najdrahšie SSD").sort == "price_desc"


def test_parse_empty_text_is_empty():
    assert parse_filters_from_text("").is_empty()
    assert parse_filters_from_text("bez filtra").is_empty()


def test_from_cli_parses_price_and_extras():
    f = from_cli(
        min_price="100",
        max_price="1 299,50 EUR",
        condition="any",
        brand=" AMD ",
        extra_filters=["socket=AM5", "ram=32GB"],
    )
    assert f.min_price == 100
    assert f.max_price == 1299.50
    assert f.condition is None
    assert f.brand == "AMD"
    assert f.extras == {"socket": "AM5", "ram": "32GB"}


def test_from_cli_rejects_bad_extra():
    with pytest.raises(ValueError):
        from_cli(extra_filters=["socket"])


def test_filters_from_mapping_accepts_aliases():
    f = filters_from_mapping(
        {
            "price_min": 100,
            "price_max": "500",
            "condition": "used",
            "extras": {"socket": "AM5"},
            "socket": "AM5",
        }
    )
    assert f.min_price == 100
    assert f.max_price == 500
    assert f.condition == "used"
    assert f.extras["socket"] == "AM5"


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def extract_search_filters(self, prompt):
        return self.payload


@pytest.mark.asyncio
async def test_resolve_filters_cli_wins_over_llm():
    llm = FakeLLM({"max_price": 500, "condition": "used"})
    result = await resolve_filters("pc", SearchFilters(max_price=300), llm)
    assert result.max_price == 300
    assert result.condition == "used"


@pytest.mark.asyncio
async def test_resolve_filters_survives_llm_error():
    class BrokenLLM:
        async def extract_search_filters(self, prompt):
            raise RuntimeError("offline")

    result = await resolve_filters("pc do 300 eur", SearchFilters(), BrokenLLM())
    assert result.max_price == 300


def test_search_config_has_default_filters():
    config = SearchConfig(default_filters={"max_price": 500})
    assert config.default_filters == {"max_price": 500}
