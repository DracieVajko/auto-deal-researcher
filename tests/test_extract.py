"""Tests for extract.py (generic product card extraction)."""

from unittest.mock import AsyncMock

import pytest

from src.searcher.extract import _detect_condition, _parse_price, extract_product_card


def test_parse_price_eur():
    assert _parse_price("18.990 €") == 18990.0
    assert _parse_price("350 EUR") == 350.0
    assert _parse_price("1,234.56") == 1234.56
    assert _parse_price("no price") is None
    assert _parse_price("") is None


def test_detect_condition():
    assert _detect_condition("nové auto") == "new"
    assert _detect_condition("gebraucht") == "used"
    assert _detect_condition("repasované") == "refurbished"
    assert _detect_condition("open box") == "open_box"
    assert _detect_condition("unknown item") == "unknown"


def _make_card_el(resolver):
    card_el = AsyncMock()
    card_el.query_selector = AsyncMock(side_effect=resolver)
    return card_el


@pytest.mark.asyncio
async def test_extract_product_card_success():
    title_el = AsyncMock()
    title_el.inner_text = AsyncMock(return_value="Citroen eC3")
    price_el = AsyncMock()
    price_el.inner_text = AsyncMock(return_value="18 990 €")
    link_el = AsyncMock()
    link_el.get_attribute = AsyncMock(return_value="/item/123")
    condition_el = AsyncMock()
    condition_el.inner_text = AsyncMock(return_value="used")

    def resolver(selector):
        if "product-title" in selector:
            return title_el
        if "price" in selector:
            return price_el
        if selector == "a[href]":
            return link_el
        if "availability" in selector:
            return condition_el
        return None

    card = await extract_product_card(_make_card_el(resolver), "bazos", base_url="https://example.com")
    assert card is not None
    assert card.title == "Citroen eC3"
    assert card.price_eur == 18990.0
    assert card.url == "https://example.com/item/123"
    assert card.site_name == "bazos"
    assert card.condition == "used"


@pytest.mark.asyncio
async def test_extract_product_card_missing_title_returns_none():
    card_el = AsyncMock()
    card_el.query_selector = AsyncMock(return_value=None)
    card = await extract_product_card(card_el, "bazos")
    assert card is None


@pytest.mark.asyncio
async def test_extract_product_card_missing_price_returns_none():
    title_el = AsyncMock()
    title_el.inner_text = AsyncMock(return_value="Citroen eC3")

    def resolver(selector):
        if "product-title" in selector:
            return title_el
        return None

    card = await extract_product_card(_make_card_el(resolver), "bazos")
    assert card is None


@pytest.mark.asyncio
async def test_extract_product_card_missing_url_uses_empty_string():
    title_el = AsyncMock()
    title_el.inner_text = AsyncMock(return_value="Citroen eC3")
    price_el = AsyncMock()
    price_el.inner_text = AsyncMock(return_value="100 €")
    link_el = AsyncMock()
    link_el.get_attribute = AsyncMock(return_value=None)

    def resolver(selector):
        if "product-title" in selector:
            return title_el
        if "price" in selector:
            return price_el
        if selector == "a[href]":
            return link_el
        return None

    card = await extract_product_card(_make_card_el(resolver), "bazos")
    assert card is not None
    assert card.url == ""
    assert card.price_eur == 100.0


def test_detect_condition_all_values():
    assert _detect_condition("nové auto") == "new"
    assert _detect_condition("gebraucht") == "used"
    assert _detect_condition("repasované") == "refurbished"
    assert _detect_condition("open box") == "open_box"
    assert _detect_condition("unknown item") == "unknown"
