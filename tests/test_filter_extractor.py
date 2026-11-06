"""Tests for filter_extractor (multi-language filter extraction)."""

from src.searcher.filter_extractor import (
    Condition,
    ExtractedFilters,
    detect_language,
    extract_category,
    extract_condition,
    extract_filters_from_prompt,
    extract_filters_from_specs,
    extract_price,
    extract_specs_from_text,
    to_search_filters,
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


def test_detect_language_pl():
    assert detect_language("używane auto do 15000") == "pl"
    assert detect_language("samochód używany max 20000") == "pl"


def test_detect_language_unknown_returns_en():
    assert detect_language("xyzqw random words nothing") == "en"
    assert detect_language("12345 symbols only") == "en"


def test_detect_language_ambiguous_prefers_sk():
    # "do" and "od" score in SK, CS and PL; SK wins the deterministic tie-break
    assert detect_language("do 20000 od 10000") == "sk"


def test_extract_condition_all_locales():
    assert extract_condition("nové", "sk") == "new"
    assert extract_condition("použité", "sk") == "used"
    assert extract_condition("repasované", "sk") == "refurbished"
    assert extract_condition("gebraucht", "de") == "used"
    assert extract_condition("neu", "de") == "new"
    assert extract_condition("używane", "pl") == "used"
    assert extract_condition("nowe", "pl") == "new"
    assert extract_condition("new", "en") == "new"
    assert extract_condition("used", "en") == "used"
    assert extract_condition("refurbished", "en") == "refurbished"
    assert extract_condition("open box", "en") == "open_box"
    assert extract_condition("unknown thing", "en") is None


def test_extract_category_all_locales():
    assert extract_category("automobil", "sk") == "auto"
    assert extract_category("elektronika", "cs") == "electronics"
    assert extract_category("domáca spotrebiča", "sk") == "appliances"
    assert extract_category("haushaltsgerät", "de") == "appliances"
    assert extract_category("möbel", "de") == "home"
    assert extract_category("samochód", "pl") == "auto"
    assert extract_category("furniture", "en") == "home"
    assert extract_category("sport", "en") == "hobby"
    assert extract_category("nothing here", "en") is None


def test_to_search_filters_conversion():
    from src.searcher.filters import SearchFilters

    ef = ExtractedFilters(
        min_price=100.0,
        max_price=20000.0,
        condition="used",
        brand="Citroen",
        location="Bratislava",
        shipping="free",
        seller_type="retailer",
        sort="price_asc",
        extras={"power_kw": "83"},
        language="sk",
        confidence=0.8,
    )
    sf = to_search_filters(ef)
    assert isinstance(sf, SearchFilters)
    assert sf.min_price == 100.0
    assert sf.max_price == 20000.0
    assert sf.condition == Condition.USED
    assert sf.brand == "Citroen"
    assert sf.location == "Bratislava"
    assert sf.shipping == "free"
    assert sf.seller_type == "retailer"
    assert sf.sort == "price_asc"
    assert sf.extras == {"power_kw": "83"}


def test_to_search_filters_preserves_extras():
    ef = ExtractedFilters(
        category="auto",
        brand="Tesla",
        condition="new",
        extras={"battery_kwh": "44.0", "range_km": "350"},
    )
    sf = to_search_filters(ef)
    assert sf.extras == {"battery_kwh": "44.0", "range_km": "350"}


def test_to_search_filters_none_condition_is_any():
    ef = ExtractedFilters(condition=None)
    sf = to_search_filters(ef)
    assert sf.condition == Condition.ANY
