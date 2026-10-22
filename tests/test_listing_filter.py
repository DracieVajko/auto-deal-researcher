"""Deterministic form-factor filtering shared by search and output."""

from src.searcher.listing_filter import (
    excluded_by_form_factor,
    is_laptop_title,
    wants_mini_pc_form_factor,
)

MINI_PC_PROMPT = (
    "mini pc barebone with Thunderbolt/OCuLink, DDR5, 32-64GB, "
    "AMD Ryzen 5+/i5+, AMD Radeon iGPU"
)


def test_zenbook_is_detected_as_laptop():
    assert is_laptop_title("ASUS Zenbook S 14 OLED (UX5406S) - NOVY, ZARUKA 2 ROKY")


def test_generic_notebook_words_are_detected():
    assert is_laptop_title("HP EliteBook 840 G9 notebook")
    assert is_laptop_title("Dell Latitude 5440 Laptop")


def test_mini_pc_is_not_a_laptop():
    assert not is_laptop_title("ASUS NUC 14 Pro+ NUC14RVSU9000R2")
    assert not is_laptop_title("Mini PC Ryzen 7 5800H 32GB DDR5")


def test_laptop_is_excluded_only_for_mini_pc_requests():
    title = "ASUS Zenbook S 14 OLED"
    assert excluded_by_form_factor(MINI_PC_PROMPT, title)
    assert not excluded_by_form_factor("gaming laptop under 1000 EUR", title)


def test_mini_pc_hint_detection():
    assert wants_mini_pc_form_factor(MINI_PC_PROMPT)
    assert wants_mini_pc_form_factor("barebone with OCuLink")
    assert not wants_mini_pc_form_factor("dji drone under 350")
