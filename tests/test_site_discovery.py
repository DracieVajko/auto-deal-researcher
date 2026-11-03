"""Web discovery marks known shops and new domains without opening them."""

import json
from pathlib import Path

from src.research.site_discovery import discover_domains, save_discovery_report
from src.research.web_search import WebSource


def _search(sources):
    return lambda query, max_results=10: sources


def test_discover_marks_known_and_new_domains():
    domains = discover_domains(
        "18650 battery",
        search=_search(
            [
                WebSource("Alza batteries", "https://www.alza.sk/18650"),
                WebSource("Review", "https://example.com/review"),
                WebSource("Alza duplicate", "https://alza.sk/other"),
            ]
        ),
    )

    by_domain = {item.domain: item for item in domains}
    assert by_domain["alza.sk"].known_id == "alza"
    assert by_domain["alza.sk"].status == "working"
    assert by_domain["example.com"].known_id == ""
    assert by_domain["example.com"].status == "new"
    assert len(domains) == 2


def test_discovery_report_is_json(tmp_path):
    domains = discover_domains(
        "x", search=_search([WebSource("Example", "https://example.com/x")])
    )
    path = save_discovery_report("x", domains, tmp_path)

    assert path == tmp_path / "discovered_sites.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["query"] == "x"
    assert payload["domains"][0]["domain"] == "example.com"


def test_discovery_report_is_reviewable_not_a_profile(tmp_path):
    domains = discover_domains(
        "x", search=_search([WebSource("Example", "https://example.com/x")])
    )
    save_discovery_report("x", domains, tmp_path)

    assert not list(Path(tmp_path).glob("*.yaml"))
