"""Interactive CLI wizard for the replacement finder.

Guides non-technical users through the find-replacement flow:
item → category → condition → price range → results.

Uses only built-in input() — no new dependencies.
"""

from __future__ import annotations

import sys
from typing import Optional


CATEGORIES = [
    ("auto", "Cars, motorcycles, vehicles"),
    ("electronics", "Phones, laptops, TVs, cameras"),
    ("appliances", "Home appliances, kitchen"),
    ("home", "Furniture, garden, DIY"),
    ("hobby", "Sport, outdoor, tools, models"),
    ("general", "Anything else"),
]

CONDITIONS = [
    ("new", "New"),
    ("used", "Used"),
    ("refurbished", "Refurbished"),
    ("open_box", "Open box"),
    ("any", "Any condition"),
]


def prompt(prompt_text: str, default: Optional[str] = None) -> str:
    """Prompt the user for input, with an optional default."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{prompt_text}{suffix}: ").strip()
        except EOFError:
            print()
            sys.exit(0)
        if not value and default is not None:
            return default
        if value:
            return value
        print("  Please enter a value.")


def prompt_choice(options: list[tuple[str, str]], prompt_text: str) -> str:
    """Show a numbered list and let the user pick one."""
    print(f"\n{prompt_text}")
    for i, (key, label) in enumerate(options, 1):
        print(f"  {i}. {label} ({key})")
    while True:
        try:
            choice = input(f"  Select 1-{len(options)}: ").strip()
        except EOFError:
            print()
            sys.exit(0)
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        print(f"  Please enter a number between 1 and {len(options)}.")


def prompt_optional_price(prompt_text: str) -> Optional[float]:
    """Prompt for an optional price in EUR."""
    while True:
        value = prompt(prompt_text, default="").strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            print("  Please enter a valid number (e.g. 20000).")


def confirm(prompt_text: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    suffix = "Y/n" if default else "y/N"
    while True:
        try:
            value = input(f"{prompt_text} [{suffix}] ").strip().lower()
        except EOFError:
            print()
            sys.exit(0)
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  Please answer yes or no.")


def progress(message: str) -> None:
    """Print a progress message."""
    print(f"  → {message}")


def result(message: str) -> None:
    """Print a result message."""
    print(f"  ✓ {message}")


def warn(message: str) -> None:
    """Print a warning message."""
    print(f"  ⚠ {message}")


def run_wizard() -> dict:
    """Run the interactive replacement finder wizard.

    Returns a dict with: item, category, condition, min_price, max_price.
    """
    print("\n" + "=" * 60)
    print("  Auto Deal Searcher — Replacement Finder Wizard")
    print("=" * 60)
    print()
    print("Find alternatives for any item. I'll research its specs,")
    print("search marketplaces for similar items, and rank the best matches.")
    print()

    # Step 1: Item name
    item = prompt("What item are you looking to replace?", default="")
    if not item:
        warn("No item provided. Exiting.")
        sys.exit(0)
    result(f"Item: {item}")

    # Step 2: Category
    category = prompt_choice(CATEGORIES, "What category is this item?")
    result(f"Category: {category}")

    # Step 3: Condition
    condition = prompt_choice(CONDITIONS, "What condition do you prefer?")
    result(f"Condition: {condition}")

    # Step 4: Price range
    print("\nPrice limits (optional — press Enter to skip):")
    min_price = prompt_optional_price("  Minimum price (EUR)")
    max_price = prompt_optional_price("  Maximum price (EUR)")
    if min_price is not None:
        result(f"Min price: {min_price:.2f} EUR")
    if max_price is not None:
        result(f"Max price: {max_price:.2f} EUR")

    # Step 5: Confirm
    print()
    print(f"\nSearching for replacements of: {item}")
    print(f"  Category: {category}  Condition: {condition}")
    if max_price:
        print(f"  Max price: {max_price:.2f} EUR")
    print()

    if not confirm("Start the search?", default=True):
        print("Cancelled.")
        sys.exit(0)

    return {
        "item": item,
        "category": category,
        "condition": condition,
        "min_price": min_price,
        "max_price": max_price,
    }
