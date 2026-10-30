"""Currency detection and conversion to EUR.

Prices on Czech and Slovak portals are not all in EUR. A car listed at
``242 000 Kč`` would be recorded as ``€242 000`` if the number were taken at
face value — roughly 25x too high, which silently breaks every price filter.

This module keeps the EUR value as the canonical number and remembers the
original amount and currency next to it. Rates are static on purpose: the
searcher must not depend on a network call to compare two prices. Override
them in ``config.yaml`` via ``search.currency_rates`` when they drift.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 1 unit of the currency expressed in EUR. Static defaults, overridable via
# config (search.currency_rates).
DEFAULT_RATES: dict[str, float] = {
    "EUR": 1.0,
    "CZK": 0.0265,
    "USD": 0.92,
    "GBP": 1.16,
}

# Active rate table. ``set_rates`` replaces it from the config at startup.
_RATES: dict[str, float] = dict(DEFAULT_RATES)


def set_rates(rates: dict[str, float] | None) -> None:
    """Override the active rate table (called once with the config values)."""
    global _RATES  # noqa: PLW0603 - a single process-wide rate table is intended
    if rates:
        merged = dict(DEFAULT_RATES)
        merged.update({str(k).upper(): float(v) for k, v in rates.items()})
        _RATES = merged


def get_rates() -> dict[str, float]:
    """Return the active rate table."""
    return dict(_RATES)

# Currency symbols and codes, longest first so "Kč" wins over a bare "K".
_CURRENCY_TOKENS: tuple[tuple[str, str], ...] = (
    ("Kč", "CZK"),
    ("Kc", "CZK"),
    ("CZK", "CZK"),
    ("€", "EUR"),
    ("EUR", "EUR"),
    ("$", "USD"),
    ("USD", "USD"),
    ("£", "GBP"),
    ("GBP", "GBP"),
)

# Space-like characters stripped from a captured number.
_NBSP = chr(0x00A0)
_NNBSP = chr(0x202F)
_SPACES = (" ", _NBSP, _NNBSP)

# Digits plus the whitespace variants Czech and Slovak price tags use.
# \s already matches NBSP and NNBSP for str patterns.
_NUMBER_RE = re.compile(r"\d[\d\s.,]*")


def _parse_number(text: str) -> float | None:
    """Parse the first number out of *text*, honouring EU/US separators."""
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None

    num = match.group(0)
    for space in _SPACES:
        num = num.replace(space, "")
    num = num.rstrip(".,")
    if not num:
        return None

    last_dot = num.rfind(".")
    last_comma = num.rfind(",")
    last_sep = max(last_dot, last_comma)
    if last_sep == -1:
        try:
            return float(num)
        except ValueError:
            return None

    tail = num[last_sep + 1 :]
    if len(tail) in (1, 2):
        head = num[:last_sep].replace(".", "").replace(",", "")
        frac = tail.replace(".", "").replace(",", "")
        try:
            return float(f"{head}.{frac}")
        except ValueError:
            return None

    # No decimals after the separator -> it was a thousands group.
    try:
        return float(num.replace(".", "").replace(",", ""))
    except ValueError:
        return None


def detect_currency(text: str) -> str | None:
    """Return the currency code shown in *text*, or None when unrecognised."""
    if not text:
        return None
    lowered = text.lower()
    for token, code in _CURRENCY_TOKENS:
        if token.lower() in lowered:
            return code
    return None


def to_eur(
    amount: float,
    currency: str | None = "EUR",
    rates: dict[str, float] | None = None,
) -> float:
    """Convert *amount* to EUR using *rates* (defaults to the active _RATES table).

    An unknown currency is treated as EUR: that is the historical behaviour
    of the adapters and keeps the price filters usable instead of dropping
    every listing.
    """
    if amount is None:
        return 0.0
    if not currency:
        return float(amount)
    table = rates or _RATES
    rate = table.get(currency.upper())
    if rate is None:
        logger.debug("Unknown currency %s; treating the amount as EUR", currency)
        return float(amount)
    return float(amount) * rate


def parse_price(
    text: str,
    default_currency: str = "EUR",
    rates: dict[str, float] | None = None,
) -> tuple[float, str] | None:
    """Parse *text* into ``(amount_in_eur, original_currency)``.

    The currency symbol in the text wins; *default_currency* is used when the
    text carries no symbol (many Czech cards show a bare number).
    """
    detail = parse_price_detail(text, default_currency, rates)
    if detail is None:
        return None
    _, eur, currency = detail
    return eur, currency


def parse_price_detail(
    text: str,
    default_currency: str = "EUR",
    rates: dict[str, float] | None = None,
) -> tuple[float, float, str] | None:
    """Parse *text* into ``(original_amount, amount_in_eur, currency)``.

    The original amount is what the shop showed; the EUR value is what the
    rest of the system compares and filters on.

    We look for a number associated with a currency symbol (Kč, €, etc.)
    rather than just taking the first number in the text.
    """
    # Try to find a number associated with a currency symbol
    for token, code in _CURRENCY_TOKENS:
        token_lower = token.lower()
        idx = text.lower().find(token_lower)
        if idx != -1:
            # Found a currency symbol, look for a number near it
            # Use negative lookbehind to avoid matching parts of model numbers
            import re
            token_escaped = re.escape(token)
            # Negative lookbehind: not preceded by digit or letter
            pattern = rf"(?<![0-9A-Za-z])(\d[\d\s.,]*)\s*{token_escaped}"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                num = _parse_number(match.group(1))
                if num is not None:
                    return num, to_eur(num, code), code
            # If no number before, try after the currency symbol
            after = text[idx + len(token):]
            num = _parse_number(after)
            if num is not None:
                return num, to_eur(num, code), code

    # Fallback: no currency symbol found, use first number and default currency
    amount = _parse_number(text)
    if amount is None:
        return None
    currency = (default_currency or "EUR").upper()
    return amount, to_eur(amount, currency, rates), currency


__all__ = [
    "DEFAULT_RATES",
    "detect_currency",
    "get_rates",
    "parse_price",
    "parse_price_detail",
    "set_rates",
    "to_eur",
]