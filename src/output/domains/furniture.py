"""Furniture specs: dimensions and material."""

import re

from src.output.domains.base import DomainProfile

_DIMENSIONS = re.compile(
    r"(\d{1,3}(?:[.,]\d)?)\s*[x\u00d7]\s*(\d{1,3}(?:[.,]\d)?)(?:\s*(cm|m)\b)?"
)
_MATERIAL = (
    ("Leather", re.compile(r"\b(?:koza|kuze|leder|leather)\b")),
    ("Glass", re.compile(r"\b(?:sklo|glass|glas)\b")),
    ("Wood", re.compile(r"\b(?:drevo|holz|wood)\b")),
    ("Fabric", re.compile(r"\b(?:textil|stoff)\b")),
    ("Metal", re.compile(r"\b(?:kov|metal|metall)\b")),
)


def _centimetres(value: str, unit: str) -> str:
    number = float(value.replace(",", "."))
    if unit == "m":
        number *= 100
    return str(int(number)) if number == int(number) else f"{number:g}"


def extract_dimensions(text: str) -> str | None:
    match = _DIMENSIONS.search(text)
    if not match:
        return None
    # Spec 13.3: "250x180" without a unit is a centimetre measurement.
    unit = match.group(3) or "cm"
    width = _centimetres(match.group(1), unit)
    depth = _centimetres(match.group(2), unit)
    return f"{width}x{depth} cm"


def extract_material(text: str) -> str | None:
    for label, pattern in _MATERIAL:
        if pattern.search(text):
            return label
    return None


FURNITURE = DomainProfile(
    name="furniture",
    strong_keywords=(
        "sedacia",
        "sedaci",
        "gauc",
        "sofa",
        "couch",
        "sessel",
        "stuhl",
        "tisch",
        "schrank",
        "bett",
        "regal",
        "nabytek",
        "meble",
        "kanapa",
        "fotel",
        "stol",
        "skrina",
        "postel",
        "komoda",
        "polica",
    ),
    key_specs=("dimensions", "material", "color", "condition_notes"),
    extractors={
        "dimensions": extract_dimensions,
        "material": extract_material,
    },
)
