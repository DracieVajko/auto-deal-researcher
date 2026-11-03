"""Phone specs: storage, memory, battery health and screen size."""

import re

from src.output.domains.base import DomainProfile

_STORAGE = re.compile(r"\b(\d{1,4})\s*(gb|go|tb)\b")
_RAM = re.compile(
    r"\b(\d{1,3})\s*(gb|go)\s*ram\b|\bram\s*(\d{1,3})\s*(gb|go)\b"
)
_BATTERY = re.compile(
    r"(?:bateria|baterie|akku|battery|batterie|stav\s+baterie|zdravie\s+baterie)"
    r"\s*(\d{1,3})(?!\d)\s*%?"
)
_SCREEN = re.compile(r"\b(\d[.,]\d)\s*(?:palca|palce|palcov|zoll|inch|cala|cali|\")")
_CAMERA = re.compile(r"\b(\d{1,3})\s*(?:mp|mpx)\b")
_BATTERY_CAPACITY = re.compile(r"\b(\d{3,5})\s*mah\b")
_CHARGING = re.compile(
    r"\b(\d{1,3})\s*w\b[^.]{0,30}(?:nabij|charg|charge|watt)"
    r"|(?:nabij|charg|charge)[^.]{0,30}\b(\d{1,3})\s*w\b"
)
_BATTERY_LIFE = re.compile(
    r"\b(?:vydrz|battery life|akkulaufzeit|autonomie)"
    r"[^.]{0,30}?\b(\d{1,3}(?:[.,]\d)?)\s*(?:h|hod|hours?|std)\b"
)


def extract_storage(text: str) -> str | None:
    for match in _STORAGE.finditer(text):
        # "8gb ram" or "ram 8 gb" is memory, not storage.
        if re.match(r"\s*ram\b", text[match.end():]):
            continue
        if re.search(r"\bram\s+$", text[: match.start()]):
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
    value = int(match.group(1))
    if value > 100:
        # "bateria 300" is a capacity, never a health percentage.
        return None
    return f"{value}%"


def extract_screen_size(text: str) -> str | None:
    match = _SCREEN.search(text)
    if not match:
        return None
    return f'{match.group(1).replace(",", ".")}"'


def extract_camera(text: str) -> str | None:
    match = _CAMERA.search(text)
    return f"{match.group(1)} MP" if match else None


def extract_battery_capacity(text: str) -> str | None:
    match = _BATTERY_CAPACITY.search(text)
    return f"{match.group(1)} mAh" if match else None


def extract_charging(text: str) -> str | None:
    match = _CHARGING.search(text)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return f"{value} W" if value else None


def extract_battery_life(text: str) -> str | None:
    match = _BATTERY_LIFE.search(text)
    if not match:
        return None
    return f"{match.group(1).replace(',', '.')} h"


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
    key_specs=(
        "storage",
        "ram",
        "camera",
        "battery_capacity",
        "battery_life",
        "charging",
        "battery_health",
        "screen_size",
    ),
    aliases={
        "storage_gb": "storage",
        "battery_percentage": "battery_health",
        "battery": "battery_health",
        "ram_gb": "ram",
        "screen": "screen_size",
        "camera_mp": "camera",
        "battery_capacity_mah": "battery_capacity",
        "battery_life_h": "battery_life",
        "charging_w": "charging",
    },
    extractors={
        "storage": extract_storage,
        "ram": extract_ram,
        "camera": extract_camera,
        "battery_capacity": extract_battery_capacity,
        "battery_life": extract_battery_life,
        "charging": extract_charging,
        "battery_health": extract_battery_health,
        "screen_size": extract_screen_size,
    },
)
