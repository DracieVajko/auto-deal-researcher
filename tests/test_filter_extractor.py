"""Tests for filter_extractor (multi-language filter extraction)."""

from src.searcher.filter_extractor import (
    detect_language,
    extract_condition,
    extract_filters_from_prompt,
    extract_filters_from_specs,
    extract_price,
    extract_specs_from_text,
)


def test_detect_language_sk():
    assert detect_language("Citroen eC3 do 20000 eur") == "sk"
    assert detect_language("použité auto do 15000") == "sk"


def test_detect_language_de():
    assert detect_language("Citroen eC3 unter 20000 EUR") == "de"
    assert detect_language("gebrauchtes Auto maximal 15000") == "de"


def test_detect_language_en():
    assert detect_language("Citroen eC3 below 20000 EUR") == "en"
    assert detect_language("used car under 15000") == "en"


def test_detect_language_cs():
    assert detect_language("Citroen eC3 do 20000 EUR") == "sk"  # SK preferred on tie


def test_extract_filters_from_prompt_price():
    f = extract_filters_from_prompt("Citroen eC3 do 20000 eur")
    assert f.max_price == 20000.0
    assert f.language == "sk"


def test_extract_filters_from_prompt_min_max():
    f = extract_filters_from_prompt("od 10000 do 20000 eur")
    assert f.min_price == 10000.0
    assert f.max_price == 20000.0


def test_extract_filters_from_prompt_condition():
    f = extract_filters_from_prompt("použité auto")
    assert f.condition == "used"


def test_extract_filters_from_prompt_brand():
    f = extract_filters_from_prompt("Tesla Model 3")
    assert f.brand == "Tesla"


def test_extract_filters_from_specs():
    specs = {
        "category": "auto",
        "brand": "Citroen",
        "price_eur": 18990.0,
        "power_kw": 83.0,
        "battery_kwh": 44.0,
        "range_km": 350.0,
    }
    f = extract_filters_from_specs(specs)
    assert f.max_price == 18990.0
    assert f.brand == "Citroen"
    assert f.category == "auto"
    assert f.extras["power_kw"] == "83.0"
    assert f.extras["battery_kwh"] == "44.0"
    assert f.extras["range_km"] == "350.0"


def test_extract_condition_sk():
    assert extract_condition("nové auto", "sk") == "new"
    assert extract_condition("použité", "sk") == "used"
    assert extract_condition("repasované", "sk") == "refurbished"


def test_extract_condition_de():
    assert extract_condition("gebraucht", "de") == "used"
    assert extract_condition("neu", "de") == "new"


def test_extract_price_range():
    min_p, max_p = extract_price("10000-20000 eur", "en")
    assert min_p == 10000.0
    assert max_p == 20000.0


def test_extract_specs_from_text():
    extras = extract_specs_from_text("auto 83 kW 44 kWh 1420 kg")
    assert extras["power_kw"] == "83"
    assert extras["battery_kwh"] == "44"
    assert extras["weight_kg"] == "1420"
