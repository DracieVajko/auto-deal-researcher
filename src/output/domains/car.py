"""Car specs: year, mileage, fuel and transmission."""

import re

from src.output.domains.base import DomainProfile

_YEAR = re.compile(r"\b(?:rok(?:\s+vyroby)?|baujahr|year|rocznik)\s*:?\s*(\d{4})\b")
_MILEAGE = re.compile(r"\b(\d{1,3}(?:[ .]\d{3})+|\d{4,7})\s*(km|tkm|meilen)\b")
_FUEL = (
    ("Petrol", re.compile(r"\b(?:benzin|petrol)\b")),
    ("Diesel", re.compile(r"\b(?:nafta|diesel|dizel)\b")),
    ("Electric", re.compile(r"\b(?:elektro|electric)\b")),
    ("Hybrid", re.compile(r"\bhybrid\b")),
)
_TRANSMISSION = (
    ("Automatic", re.compile(r"\b(?:automat|automatik|automatic|dsg)\b")),
    ("Manual", re.compile(r"\b(?:manual|manuell|schaltgetriebe)\b")),
)


def _first_label(text: str, table: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    for label, pattern in table:
        if pattern.search(text):
            return label
    return None


def extract_year(text: str) -> str | None:
    match = _YEAR.search(text)
    return match.group(1) if match else None


def extract_mileage(text: str) -> str | None:
    match = _MILEAGE.search(text)
    if not match:
        return None
    digits = re.sub(r"[ .]", "", match.group(1))
    if match.group(2) == "tkm":
        digits = str(int(digits) * 1000)
    return f"{digits} km"


def extract_fuel(text: str) -> str | None:
    return _first_label(text, _FUEL)


def extract_transmission(text: str) -> str | None:
    return _first_label(text, _TRANSMISSION)


CAR = DomainProfile(
    name="car",
    strong_keywords=(
        "automobil",
        "vozidlo",
        "fahrzeug",
        "pkw",
        "samochod",
        "skoda",
        "vw",
        "audi",
        "bmw",
        "mercedes",
        "opel",
        "ford",
        "renault",
        "peugeot",
        "citroen",
        "toyota",
        "hyundai",
        "kia",
        "seat",
        "fiat",
        "volvo",
        "mazda",
        "nissan",
        "honda",
        "suzuki",
        "dacia",
    ),
    keywords=(
        "km",
        "rok",
        "najeto",
        "najazdene",
        "baujahr",
        "kilometer",
        "mileage",
        "przebieg",
        "year",
    ),
    key_specs=("year", "mileage", "fuel", "engine", "transmission"),
    extractors={
        "year": extract_year,
        "mileage": extract_mileage,
        "fuel": extract_fuel,
        "transmission": extract_transmission,
    },
)
