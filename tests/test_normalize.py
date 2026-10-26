import pytest

from src.text.normalize import collapse_ws, fold


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GAUČ", "gauc"),
        ("gauč", "gauc"),
        ("Bicykel", "bicykel"),
        ("Fahrrad", "fahrrad"),
        ("Straße", "strasse"),
        ("Łódź", "lodz"),
        ("İstanbul", "istanbul"),
        ("Dvořák", "dvorak"),
        ("kręgle", "kregle"),
        ("", ""),
        (None, ""),
    ],
)
def test_fold_is_case_and_diacritic_insensitive(raw, expected):
    assert fold(raw) == expected


def test_fold_preserves_meaningful_symbols():
    assert fold("250×180 cm") == "250×180 cm"  # noqa: RUF001 - multiplication sign survives
    assert fold("89 %") == "89 %"


def test_collapse_ws_normalises_spaces():
    assert collapse_ws("  iPhone   13 \n 128GB ") == "iPhone 13 128GB"
