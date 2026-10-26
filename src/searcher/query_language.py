"""Send each site a search query written in that site's own language.

A Slovak query on a German shop returns nothing useful. The searcher asks
this module to translate (once per query and target), and the translation is
only accepted when every brand/model token survived it. Without an LLM the
original query is used — the pipeline must work offline.
"""

from __future__ import annotations

import logging
import re

from src.text.normalize import fold

logger = logging.getLogger(__name__)

_COUNTRY_LANGUAGE = {
    "SK": "sk",
    "CZ": "cs",
    "DE": "de",
    "AT": "de",
    "PL": "pl",
    "HU": "hu",
}

# Function words plus frequent listing words that actually distinguish these
# languages. A plain stopword table is not enough: "Prodám horské kolo" has no
# function word and shares its vowels with Slovak.
_MARKERS = {
    "sk": ("predam", "horsky", "bicykel", "pouzity"),
    "cs": ("prodam", "horske", "bicykl", "pouzite"),
    "de": ("verkaufe", "fahrrad", "gebraucht", "zustand"),
    "en": ("selling", "bike", "used", "condition"),
}

# Diacritics exclusive to one language. Letters shared by Slovak and Czech
# (á é í ý č š ž ť ď ň) are deliberately absent: counting them would bias
# the result toward whichever language owns the bigger set.
_EXCLUSIVE_DIACRITICS = {
    "sk": set("ľĺŕô"),
    "cs": set("ěřů"),
    "de": set("äöüß"),
}


def language_for_country(country: str) -> str:
    """The market's written language; unknown markets search in English."""
    return _COUNTRY_LANGUAGE.get((country or "").upper(), "en")


def detect_language(text: str) -> str:
    """Marker words decide; exclusive diacritics only break ties; unsure -> en."""
    if not text:
        return "en"
    lowered = text.lower()  # diacritics must be read from the raw text
    folded = fold(text)     # marker words from the folded text
    scores: dict[str, int] = {}
    for language, markers in _MARKERS.items():
        hits = sum(1 for marker in markers if re.search(rf"\b{marker}\b", folded))
        diacritics = sum(
            1 for ch in lowered if ch in _EXCLUSIVE_DIACRITICS.get(language, set())
        )
        scores[language] = hits * 3 + diacritics

    best = max(scores.values())
    if best == 0:
        return "en"
    winners = [language for language, score in scores.items() if score == best]
    if len(winners) != 1:
        return "en"
    return winners[0]


def protected_tokens(query: str) -> list[str]:
    """Tokens a translation must keep: anything with a digit or an uppercase letter.

    `iPhone` counts even though the capital is mid-word, so model names never
    disappear into a generic translation.
    """
    tokens: list[str] = []
    for raw in (query or "").split():
        core = raw.strip(",.;:!?()[]{}\"'")
        if core and any(ch.isdigit() or ch.isupper() for ch in core):
            tokens.append(core)
    return tokens


_SYSTEM = (
    "You translate marketplace search queries. Reply with the translated "
    "query only - no quotes, no explanations."
)


async def localise_query(
    llm, query: str, target: str, cache: dict[tuple[str, str], str]
) -> str:
    """Translate a query into the site's language, keeping brand/model tokens."""
    if llm is None or not query or not target:
        return query
    if detect_language(query) == target:
        return query
    key = (query, target)
    if key in cache:
        return cache[key]

    user = (
        f"Translate this marketplace search query to {target}. "
        "Keep brand and model strings exactly as they are.\n\n"
        f"Query: {query}"
    )
    try:
        response = await llm._chat(_SYSTEM, user, max_tokens=80, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 - the original query is a fine fallback
        logger.debug("Query translation to %s failed: %s", target, exc)
        return query

    translated = (response or "").strip().strip("\"'")
    if not translated:
        return query
    for token in protected_tokens(query):
        if token not in translated:
            logger.debug(
                "Translation %r lost the token %r; keeping the original query",
                translated,
                token,
            )
            return query
    cache[key] = translated
    return translated
