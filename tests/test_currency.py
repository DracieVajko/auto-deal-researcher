"""Currency detection and EUR conversion."""

from src.searcher.currency import (
    DEFAULT_RATES,
    detect_currency,
    parse_price,
    to_eur,
)


def test_detect_currency_symbols():
    assert detect_currency("339 €") == "EUR"
    assert detect_currency("242 000 Kč") == "CZK"
    assert detect_currency("1 200 CZK") == "CZK"
    assert detect_currency("$49.99") == "USD"
    assert detect_currency("£10") == "GBP"


def test_detect_currency_returns_none_when_absent():
    assert detect_currency("1 299,50") is None
    assert detect_currency("") is None


def test_to_eur_converts_czk():
    assert to_eur(242000, "CZK") == 242000 * DEFAULT_RATES["CZK"]


def test_to_eur_keeps_eur_unchanged():
    assert to_eur(339, "EUR") == 339.0


def test_to_eur_unknown_currency_is_treated_as_eur():
    assert to_eur(100, "XYZ") == 100.0


def test_to_eur_uses_custom_rates():
    assert to_eur(100, "CZK", {"CZK": 0.5}) == 50.0


def test_parse_price_returns_eur_and_original_currency():
    eur, currency = parse_price("242 000 Kč")
    assert currency == "CZK"
    assert eur == 242000 * DEFAULT_RATES["CZK"]


def test_parse_price_uses_default_currency_without_symbol():
    eur, currency = parse_price("242 000", default_currency="CZK")
    assert currency == "CZK"
    assert eur == 242000 * DEFAULT_RATES["CZK"]


def test_parse_price_handles_european_separators():
    eur, currency = parse_price("1.299,50 €")
    assert currency == "EUR"
    assert eur == 1299.50


def test_parse_price_handles_us_separators():
    eur, currency = parse_price("$1,299.50")
    assert currency == "USD"
    assert eur == 1299.50 * DEFAULT_RATES["USD"]


def test_parse_price_returns_none_without_number():
    assert parse_price("na vyžiadanie") is None
