"""Computer and laptop specs, extracted from folded listing text."""

import re

from src.output.domains.base import DomainProfile

_CPU_PATTERNS = (
    r"\b(ryzen\s*[3579]\s*\d{3,4}[a-z]{0,3})\b",
    r"\b(ryzen\s*[3579])\b",
    r"\b(intel\s+core\s+ultra\s*[579]\s*\d{3}[a-z]{0,2})\b",
    r"\b(intel\s+core\s*[3579]\s*\d{3}[a-z]{0,2})\b",
    r"\b(core\s*[3579]\s*\d{3}[a-z]{0,2})\b",
    r"\b(i[3579][- ]?\d{3,5}[a-z]{0,4})\b",
    r"\b(n100|n97|n305|n95|j4125)\b",
    r"\b(celeron|pentium|athlon)\b",
    r"\b(ultra\s*[579]\s*\d{3}[a-z]{0,2})\b",
)

_PORTS = (
    ("Thunderbolt", r"thunderbolt\s*\d?"),
    ("USB4", r"usb4"),
    ("OCuLink", r"oculink"),
    ("2.5GbE", r"2\.5\s*gb?e"),
    ("HDMI", r"hdmi"),
    ("DisplayPort", r"displayport"),
)


def extract_cpu(text: str) -> str | None:
    for pattern in _CPU_PATTERNS:
        match = re.search(pattern, text)
        if match:
            cpu = match.group(1).strip().upper()
            if cpu.startswith("CORE "):
                cpu = f"INTEL {cpu}"
            elif cpu.startswith("ULTRA "):
                cpu = f"INTEL CORE {cpu}"
            return cpu
    return None


def extract_ram(text: str) -> str | None:
    match = re.search(r"(?:^|\s)(\d{1,3})\s*gb\s*(ddr[45])", text)
    if match:
        return f"{match.group(1)} GB {match.group(2).upper()}"

    match = re.search(r"(ddr[45])\s*(\d{1,3})\s*gb", text)
    if match:
        return f"{match.group(2)} GB {match.group(1).upper()}"

    size_ram = re.search(r"\b(\d{1,3})\s*gb\s*ram\b", text)
    if size_ram:
        return f"{size_ram.group(1)} GB RAM"

    bare_ram = re.search(r"\bram\s*(\d{1,3})\s*gb", text)
    if bare_ram and int(bare_ram.group(1)) == 0:
        return "No RAM included (barebone)"

    if re.search(r"bez\s+pamat[ei]\s+ram|without\s+ram", text):
        return "No RAM included (barebone)"
    return None


def extract_storage(text: str) -> str | None:
    match = re.search(r"(\d{3,4}\s*gb|\d{1,2}\s*tb)\s*(ssd|nvme|hdd)", text)
    if match:
        size = re.sub(r"(\d)\s*(GB|TB)", r"\1 \2", match.group(1).upper())
        return f"{size} {match.group(2).upper()}"

    if re.search(r"bez\s+ulozisk|bez\s+disku|without\s+storage", text):
        return "No storage included (barebone)"
    return None


def extract_connectivity(text: str) -> str | None:
    ports = [label for label, pattern in _PORTS if re.search(pattern, text)]
    return ", ".join(ports) or None


COMPUTER = DomainProfile(
    name="computer",
    strong_keywords=(
        "mini pc",
        "barebone",
        "nuc",
        "laptop",
        "notebook",
        "computer",
        "rechner",
        "komputer",
    ),
    key_specs=("cpu", "ram", "storage", "connectivity"),
    extractors={
        "cpu": extract_cpu,
        "ram": extract_ram,
        "storage": extract_storage,
        "connectivity": extract_connectivity,
    },
    optional_rows=("Connectivity",),
)
