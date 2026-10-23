"""Currency handling inside the adapters (offline, fake DOM)."""

import pytest

from src.searcher.adapters import get_adapter
from src.searcher.adapters.base import Deal
from src.searcher.currency import DEFAULT_RATES


def test_adapter_uses_its_own_currency_by_default():
    adapter = get_adapter("alza")()
    assert adapter.currency == "EUR"


def test_adapter_currency_can_be_overridden():
    adapter = get_adapter("alza")(base_url="https://www.alza.cz", currency="CZK")
    assert adapter.currency == "CZK"


def test_parse_price_with_currency_uses_adapter_currency():
    adapter = get_adapter("bazos")(base_url="https://www.bazos.cz", currency="CZK")
    parsed = adapter.parse_price_with_currency("8 900 Kč")
    assert parsed is not None
    eur, original, currency = parsed
    assert currency == "CZK"
    assert original == 8900
    assert eur == 8900 * DEFAULT_RATES["CZK"]


def test_parse_price_with_currency_uses_symbol_over_adapter_default():
    adapter = get_adapter("bazos")(base_url="https://www.bazos.cz", currency="CZK")
    parsed = adapter.parse_price_with_currency("26 €")
    assert parsed is not None
    eur, original, currency = parsed
    assert currency == "EUR"
    assert original == 26
    assert eur == 26.0


def test_parse_price_with_currency_returns_none_without_number():
    adapter = get_adapter("alza")()
    assert adapter.parse_price_with_currency("na vyžiadanie") is None


def test_deal_keeps_original_amount_and_currency():
    deal = Deal(
        url="https://x.test/p/1",
        title="Vec",
        price_eur=236.15,
        original_price=8900,
        original_currency="CZK",
    )
    assert deal.price_eur == 236.15
    assert deal.original_price == 8900
    assert deal.original_currency == "CZK"


@pytest.mark.parametrize("adapter_name", ["alza", "bazos", "ebay", "backmarket"])
def test_adapters_expose_currency_attribute(adapter_name):
    adapter = get_adapter(adapter_name)()
    assert adapter.currency == "EUR"
