"""Bicycle specs and the rider-height constraint, over folded listing text."""

import re

from src.output.domains.base import DomainProfile
from src.text.normalize import fold

_WHEEL_SIZE = re.compile(
    r"\b(2[46]|27[.,]5|28|29)\s*"
    r'(?:palcov\w*|zoll|inch|cala|cali|[x\u00d7]\s*\d|\\?"|\\?\u2033)'
)
_WHEEL_FROM_KOLESA = re.compile(r"kolesa\s*(?:su\s*)?(2[46]|27[.,]5|28|29)")

_FRAME_WORD = r"(?:ram|rahmen|frame|velkost\s+ramu|velikost\s+ramu)"
_FRAME_LETTER = re.compile(
    rf"\b{_FRAME_WORD}\s*(?:je\s*)?(?:velkosti\s*)?(xxs|xs|s|m|l|xl|xxl)\b"
)
_FRAME_NUMBER = re.compile(
    rf'\b{_FRAME_WORD}\s*(?:je\s*)?(?:velkosti\s*)?(\d{{2}})\s*'
    r'(?:palc|zoll|inch|cala|cali|\\?"|\\?\u2033)'
)
_FRAME_NUMBER_BARE = re.compile(rf"\b{_FRAME_WORD}\s*(\d{{2}})\b")
_FRAME_IN_PARENS = re.compile(r"velkosti\s*(?:xxs|xs|s|m|l|xl|xxl)\s*\((\d{2})")

# Approximate rider height ranges in cm. They only reject a frame that is
# clearly wrong; borderline sizes stay the buyer's call.
_LETTER_RANGES = {
    "XXS": (145, 155),
    "XS": (155, 165),
    "S": (160, 170),
    "M": (168, 178),
    "L": (175, 185),
    "XL": (182, 192),
    "XXL": (188, 198),
}
_NUMBER_RANGES = {
    14: (145, 155),
    15: (150, 160),
    16: (160, 170),
    17: (165, 175),
    18: (170, 180),
    19: (175, 185),
    20: (180, 190),
    21: (185, 195),
    22: (188, 198),
}


def extract_wheel_size(text: str) -> str | None:
    match = _WHEEL_SIZE.search(text) or _WHEEL_FROM_KOLESA.search(text)
    if not match:
        return None
    return f'{match.group(1).replace(",", ".")}"'


def extract_frame_size(text: str) -> str | None:
    letter = _FRAME_LETTER.search(text)
    number = _FRAME_NUMBER.search(text) or _FRAME_NUMBER_BARE.search(text)
    if not number:
        number = _FRAME_IN_PARENS.search(text)

    parts = []
    if letter:
        parts.append(letter.group(1).upper())
    if number:
        parts.append(f'{number.group(1)}"')
    return " ".join(parts) or None


def extract_suspension(text: str) -> str | None:
    if (
        "celoodpru" in text
        or re.search(r"odpruzen\w*\s*ram", text)
        or re.search(r"zadn\w*\s*odpruzen", text)
        or "vollfederung" in text
        or re.search(r"full\s+suspension", text)
    ):
        return "Full suspension"
    if (
        re.search(r"odpruzen\w*\s*vidlic", text)
        or "federgabel" in text
        or re.search(r"front\s+suspension", text)
    ):
        return "Front suspension"
    if (
        re.search(r"pevn\w*\s*vidlic", text)
        or re.search(r"bez\s*odpruzen", text)
        or "starrgabel" in text
    ):
        return "Rigid fork"
    return None


def extract_brakes(text: str) -> str | None:
    if re.search(r"kotucov|kotoucov|scheibenbremsen|disc\s*brakes?", text):
        return "Disc brakes"
    # Felgenbremse and rim brake are both rim brakes; the report keeps the
    # existing "V-brakes" value so old reports stay comparable.
    if re.search(r"felgenbremsen|rim\s*brakes?|\bv[- ]?brzd|v[- ]?brake", text):
        return "V-brakes"
    return None


def extract_drivetrain(text: str) -> str | None:
    if "shimano" in text:
        return "Shimano"
    if "sram" in text:
        return "SRAM"
    if "campagnolo" in text:
        return "Campagnolo"
    return None


def bike_size_check(
    specs: dict[str, str], prompt: str | None
) -> tuple[list[str], bool]:
    """Compare a stated frame size with the rider height in the request."""
    height_match = re.search(r"\b(1[5-9]\d)\s*cm\b", fold(prompt or ""))
    frame = (specs.get("frame_size") or "").upper()
    if not height_match or not frame:
        return [], False
    height = int(height_match.group(1))

    letter = re.match(r"(XXS|XS|S|M|L|XL|XXL)\b", frame)
    number = re.search(r"(\d{2})", frame)
    if letter:
        low, high = _LETTER_RANGES[letter.group(1)]
    elif number:
        low, high = _NUMBER_RANGES.get(int(number.group(1)), (0, 250))
    else:
        return [], False

    if height > high + 2:
        return [f"Frame size {frame} is too small for a {height} cm rider"], True
    if height < low - 5:
        return [f"Frame size {frame} is likely too large for a {height} cm rider"], False
    return [], False


BIKE = DomainProfile(
    name="bike",
    strong_keywords=(
        "bicykel",
        "bicykl",
        "bike",
        "mtb",
        "fahrrad",
        "mountainbike",
        "mountain bike",
        "ebike",
        "rower",
    ),
    key_specs=("wheel_size", "frame_size", "suspension", "brakes", "drivetrain"),
    extractors={
        "wheel_size": extract_wheel_size,
        "frame_size": extract_frame_size,
        "suspension": extract_suspension,
        "brakes": extract_brakes,
        "drivetrain": extract_drivetrain,
    },
    constraints=(bike_size_check,),
)
