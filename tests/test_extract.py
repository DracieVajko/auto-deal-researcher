"""Tests for extract.py (generic product card extraction)."""

from src.searcher.extract import _detect_condition, _parse_price


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
