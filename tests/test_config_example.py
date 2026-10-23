"""config.example.yaml must stay in sync with the site registry."""

from pathlib import Path

import yaml

from src.searcher.site_registry import SITES

ROOT = Path(__file__).resolve().parents[1]


def _example_sites() -> dict:
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    return {site["name"]: site for site in data["search"]["websites"]}


def test_example_config_has_every_registered_site():
    assert set(_example_sites()) == {s.id for s in SITES}


def test_example_config_has_no_unknown_sites():
    assert set(_example_sites()) <= {s.id for s in SITES}


def test_example_config_currencies_match_the_registry():
    example = _example_sites()
    for spec in SITES:
        assert example[spec.id].get("currency", "EUR") == spec.currency, spec.id
        assert example[spec.id].get("country", "SK") == spec.country, spec.id


def test_example_config_only_enables_verified_sites():
    enabled = [name for name, site in _example_sites().items() if site.get("enabled")]
    assert enabled == ["alza", "bazos"]


def test_example_config_declares_user_location_and_rates():
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    search = data["search"]
    assert search["user_country"] == "SK"
    assert search["max_sites"] >= 1
    assert search["currency_rates"]["EUR"] == 1.0
    assert search["currency_rates"]["CZK"] > 0
