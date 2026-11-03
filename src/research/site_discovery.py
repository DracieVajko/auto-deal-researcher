"""Discover shops and product pages outside the site registry.

Discovery never runs an unknown site. It turns search results into a reviewable
list of domains, marks which ones are already in the registry, and leaves the
profile decision to the user/`discover_sites.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from src.research.web_search import WebSource, search_web
from src.searcher.site_registry import SITES
from src.utils.time import today_iso


@dataclass(frozen=True)
class DiscoveredDomain:
    domain: str
    url: str
    title: str
    known_id: str = ""
    status: str = "new"

    def as_dict(self) -> dict:
        return {
            "domain": self.domain,
            "url": self.url,
            "title": self.title,
            "known_id": self.known_id,
            "status": self.status,
        }


def _domain(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _known_domains() -> dict[str, tuple[str, str]]:
    known: dict[str, tuple[str, str]] = {}
    for spec in SITES:
        host = _domain(spec.base_url)
        if host:
            known[host] = (spec.id, spec.status)
    return known


def discover_domains(
    query: str,
    max_results: int = 10,
    search=search_web,
) -> list[DiscoveredDomain]:
    """Return one row per domain from a web search, without opening the sites."""
    sources: list[WebSource] = search(query, max_results=max_results)
    known = _known_domains()
    seen: set[str] = set()
    found: list[DiscoveredDomain] = []
    for source in sources:
        domain = _domain(source.url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        known_id, status = known.get(domain, ("", "new"))
        found.append(
            DiscoveredDomain(
                domain=domain,
                url=source.url,
                title=source.title,
                known_id=known_id,
                status=status,
            )
        )
    return found


def save_discovery_report(
    query: str,
    domains: list[DiscoveredDomain],
    output_dir: str | Path = "data",
) -> Path:
    """Write a reviewable JSON proposal; never modify config or profiles."""
    path = Path(output_dir) / "discovered_sites.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "query": query,
        "generated_at": today_iso(),
        "domains": [item.as_dict() for item in domains],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


__all__ = ["DiscoveredDomain", "discover_domains", "save_discovery_report"]
