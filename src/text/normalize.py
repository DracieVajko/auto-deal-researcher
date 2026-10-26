"""One folding rule for every text comparison in the pipeline."""

import unicodedata

_EXTRA_FOLDS = {
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ð": "d",
    "þ": "th", "ł": "l", "ı": "i", "ħ": "h", "ŋ": "n", "ĸ": "k",  # noqa: RUF001 - literal table
}
_PUNCTUATION = str.maketrans(
    {
        "’": "'", "‘": "'", "´": "'",  # noqa: RUF001 - literal table
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "-",  # noqa: RUF001 - literal table
        "\u00a0": " ", "\u202f": " ",
    }
)


def fold(text: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # Lower first: _EXTRA_FOLDS is keyed by lowercase letters, and NFKD leaves
    # uppercase forms such as Ł, Æ and Ø untouched.
    lowered = stripped.translate(_PUNCTUATION).lower()
    for src, dst in _EXTRA_FOLDS.items():
        lowered = lowered.replace(src, dst)
    return lowered


def collapse_ws(text: str) -> str:
    return " ".join((text or "").split())
