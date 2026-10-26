"""Phone specs: storage, memory, battery health and screen size."""

import re

from src.output.domains.base import DomainProfile

_STORAGE = re.compile(r"\b(\d{1,4})\s*(gb|go|tb)\b")
_RAM = re.compile(
    r"\b(\d{1,3})\s*(gb|go)\s*ram\b|\bram\s*(\d{1,3})\s*(gb|go)\b"
)
_BATTERY = re.compile(
    r"(?:bateria|baterie|akku|battery|batterie|stav\s+baterie|zdravie\s+baterie)"
    r"\s*(\d{1,3})\s*%?"
)
_SCREEN = re.compile(r"\b(\d[.,]\d)\s*(?:palca|palce|palcov|zoll|inch|cala|cali|\")")


def extract_storage(text: str) -> str | None:
    for match in _STORAGE.finditer(text):
        # "8gb ram" is memory, not storage.
        if re.match(r"\s*ram\b", text[match.end():]):
            continue
        size, unit = match.group(1), match.group(2)
        return f"{size} {'GB' if unit == 'go' else unit.upper()}"
    return None


def extract_ram(text: str) -> str | None:
    match = _RAM.search(text)
    if not match:
        return None
    size = match.group(1) or match.group(3)
    return f"{size} GB"


def extract_battery_health(text: str) -> str | None:
    match = _BATTERY.search(text)
    if not match:
        return None
    return f"{match.group(1)}%"


def extract_screen_size(text: str) -> str | None:
    match = _SCREEN.search(text)
    if not match:
        return None
    return f'{match.group(1).replace(",", ".")}"'


PHONE = DomainProfile(
    name="phone",
    strong_keywords=(
        "iphone",
        "smartfon",
        "smartphone",
        "mobil",
        "handy",
        "samsung galaxy",
        "xiaomi",
        "pixel",
        "huawei",
        "oneplus",
    ),
    key_specs=("storage", "ram", "battery_health", "screen_size"),
    aliases={
        "storage_gb": "storage",
        "battery_percentage": "battery_health",
        "battery": "battery_health",
        "ram_gb": "ram",
        "screen": "screen_size",
    },
    extractors={
        "storage": extract_storage,
        "ram": extract_ram,
        "battery_health": extract_battery_health,
        "screen_size": extract_screen_size,
    },
)
