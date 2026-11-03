import pytest

from src.searcher.filters import parse_filters_from_text


@pytest.mark.parametrize(
    ("prompt", "max_price"),
    [
        ("iPhone unter 300 Euro", 300),
        ("iPhone bis 300 €", 300),
        ("iPhone maximal 300 Euro", 300),
        ("iPhone do 300 eur", 300),
        ("iPhone pod 300", 300),
        ("iPhone under 300 EUR", 300),
        ("iPhone max 300", 300),
    ],
)
def test_max_price_in_four_languages(prompt, max_price):
    assert parse_filters_from_text(prompt).max_price == max_price


@pytest.mark.parametrize(
    ("prompt", "condition"),
    [
        ("gebrauchtes iPhone 13", "used"),
        ("použité iPhone 13", "used"),
        ("použité pouzdro", "used"),
        ("used iPhone 13", "used"),
        ("neues iPhone 13", "new"),
        ("nové iPhone 13", "new"),
        ("generalüberholtes iPhone", "refurbished"),
        ("repasované iPhone", "refurbished"),
    ],
)
def test_condition_in_four_languages(prompt, condition):
    assert parse_filters_from_text(prompt).condition == condition


def test_german_shipping_and_sort():
    filters = parse_filters_from_text(
        "iPhone mit kostenlosem Versand, günstigste zuerst"
    )
    assert filters.shipping == "free"
    assert filters.sort == "price_asc"


def test_price_regex_accepts_czech_and_polish_currency():
    assert parse_filters_from_text("kolo do 5000 Kč").max_price == 5000
    assert parse_filters_from_text("kolo do 2000 zł").max_price == 2000

def test_filters_from_mapping_drops_inverted_prices_but_keeps_brand():
    from src.searcher.filters import filters_from_mapping

    filters = filters_from_mapping(
        {"min_price": 500, "max_price": 100, "brand": "AMD"}
    )

    assert filters.min_price is None
    assert filters.max_price is None
    assert filters.brand == "AMD"


def test_filters_from_mapping_drops_negative_prices():
    from src.searcher.filters import filters_from_mapping

    filters = filters_from_mapping({"min_price": -1, "max_price": 100})

    assert filters.min_price is None
    assert filters.max_price == 100
