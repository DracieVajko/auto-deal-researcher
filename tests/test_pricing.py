"""Price quote model, effective price math and deterministic signals."""

import pytest

from src.searcher.adapters.base import Deal
from src.searcher.pricing import (
    BundleTerms,
    PriceKind,
    ShippingQuote,
    build_price_quote,
    comparable_price,
    extract_price_signals,
)


def test_regular_price_adds_known_shipping():
    quote = build_price_quote(100.0, shipping=ShippingQuote(cost_eur=5.0))
    assert quote.effective_price_eur == 105.0
    assert quote.trust == 1.0


def test_free_shipping_is_zero_not_unknown():
    quote = build_price_quote(100.0, shipping=ShippingQuote(is_free=True))
    assert quote.effective_price_eur == 100.0
    assert quote.trust == 1.0


def test_unknown_shipping_is_not_zero_and_lowers_trust():
    quote = build_price_quote(100.0, shipping=ShippingQuote())
    assert quote.effective_price_eur == 100.0
    assert quote.trust == 0.90


def test_bundle_divides_total_and_shipping_by_min_quantity():
    quote = build_price_quote(
        30.0,
        kind=PriceKind.BUNDLE,
        shipping=ShippingQuote(cost_eur=6.0),
        bundle=BundleTerms(min_quantity=3),
    )
    assert quote.effective_price_eur == 12.0
    assert quote.trust == 0.85


def test_range_uses_lowest_price_and_exposes_maximum():
    quote = build_price_quote(
        12.99,
        kind=PriceKind.RANGE,
        shipping=ShippingQuote(is_free=True),
        price_from=True,
        price_max_eur=18.99,
    )
    assert quote.effective_price_eur == 12.99
    assert quote.price_max_eur == 18.99
    assert quote.trust == 0.85


def test_account_gated_price_lowers_trust():
    quote = build_price_quote(
        9.99, kind=PriceKind.ACCOUNT_GATED, shipping=ShippingQuote(is_free=True)
    )
    assert quote.trust == 0.65
    assert "new user" in " ".join(quote.warnings).lower()


def test_flags_multiply_and_trust_stays_above_the_floor():
    quote = build_price_quote(
        9.99,
        kind=PriceKind.ACCOUNT_GATED,
        shipping=ShippingQuote(),
        bundle=BundleTerms(min_quantity=3),
        price_from=True,
    )
    assert quote.trust == 0.42
    assert quote.trust >= 0.4


def test_comparable_price_falls_back_to_price_eur_without_quote():
    deal = Deal(url="https://x/1", title="X", price_eur=42.0)
    assert deal.comparable_price_eur == 42.0
    assert comparable_price(deal) == 42.0


def test_comparable_price_uses_effective_price():
    deal = Deal(
        url="https://x/1",
        title="X",
        price_eur=100.0,
        price_quote=build_price_quote(100.0, shipping=ShippingQuote(cost_eur=5.0)),
    )
    assert deal.comparable_price_eur == 105.0


@pytest.mark.parametrize(
    "text",
    [
        "New user price €9.99",
        "Welcome deal - first order",
        "Cena pre nového zákazníka 9,99 €",
        "Erste Bestellung 9,99 €",
    ],
)
def test_detects_account_gated_labels(text):
    signals = extract_price_signals(text, 9.99)
    assert signals.kind == PriceKind.ACCOUNT_GATED


def test_detects_coupon_label():
    signals = extract_price_signals("€20.00 with code SAVE10", 20.0)
    assert signals.kind == PriceKind.COUPON


def test_detects_bundle_minimum_quantity():
    signals = extract_price_signals("Balenie 3 ks za 30 €", 30.0)
    assert signals.bundle.min_quantity == 3


def test_detects_free_shipping():
    signals = extract_price_signals("Doprava zdarma", 10.0)
    assert signals.shipping.is_free is True
    assert signals.shipping.cost_eur == 0.0


def test_detects_shipping_amount_in_eur():
    signals = extract_price_signals("Doprava 4,99 €", 10.0)
    assert signals.shipping.cost_eur == 4.99


def test_detects_shipping_range_and_uses_minimum():
    signals = extract_price_signals("Doprava od 2 €", 10.0)
    assert signals.shipping.min_eur == 2.0
    assert signals.shipping.cost_eur == 2.0


def test_detects_price_from_and_range():
    signals = extract_price_signals("Od 12,99 € do 18,99 €", 12.99)
    assert signals.price_from is True
    assert signals.price_max_eur == 18.99


def test_detects_pack_quantity_and_unit_price():
    signals = extract_price_signals("Samsung 30Q 2-pack 10 €", 10.0)
    assert signals.bundle.min_quantity == 2
    quote = build_price_quote(
        10.0, kind=signals.kind, bundle=signals.bundle
    )
    assert quote.effective_price_eur == 5.0


def test_plain_card_has_no_signals():
    signals = extract_price_signals("Notebook Lenovo 1299 €", 1299.0)
    assert signals.kind == PriceKind.REGULAR
    assert signals.confidence == 0.0
