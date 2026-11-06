"""Data access layer for the web dashboard.

Reads result JSON files from the results directory and provides them to the
web server in a structured form. Read-only: the dashboard never writes to the
results directory.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Results files are named results_<timestamp>_<slug>.json
_RESULTS_RE = re.compile(r"^results_(\d{8}_\d{6})_(.+)\.json$")


@dataclass
class DealSummary:
    """Simplified view of one deal for the dashboard."""

    rank: int
    title: str
    site_name: str
    price_eur: float
    effective_price_eur: float
    condition: str
    score: float
    verdict: str
    url: str
    domain: str


@dataclass
class SearchRun:
    """One completed search run (one results JSON file)."""

    timestamp: str      # e.g. "20261105_143022"
    slug: str           # e.g. "18650-battery-capacity-price"
    prompt: str
    generated_at: str   # full ISO timestamp
    deal_count: int
    filtered_out_count: int
    site_count: int
    path: Path          # path to the results JSON file
    deals: list[DealSummary] = field(default_factory=list)
    price_alerts: list[dict] = field(default_factory=list)


class ResultsStore:
    """Reads and caches results JSON files from a results directory."""

    def __init__(self, results_dir: str | Path = "results"):
        self.results_dir = Path(results_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_runs(self, sort_by: str = "timestamp", reverse: bool = True) -> list[SearchRun]:
        """Return all search runs found in the results directory.

        *sort_by* can be "timestamp" or "deal_count".
        """
        runs: list[SearchRun] = []
        if not self.results_dir.exists():
            return runs

        for path in sorted(self.results_dir.glob("results_*.json")):
            run = self._load_run(path)
            if run is not None:
                runs.append(run)

        if sort_by == "deal_count":
            runs.sort(key=lambda r: r.deal_count, reverse=reverse)
        else:
            runs.sort(key=lambda r: r.timestamp, reverse=reverse)
        return runs

    def get_run(self, timestamp: str, slug: str) -> SearchRun | None:
        """Return one search run by timestamp + slug, or None."""
        path = self.results_dir / f"results_{timestamp}_{slug}.json"
        if not path.exists():
            return None
        return self._load_run(path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_run(self, path: Path) -> SearchRun | None:
        match = _RESULTS_RE.match(path.name)
        if match is None:
            return None
        timestamp, slug = match.group(1), match.group(2)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable results file %s: %s", path, exc)
            return None

        deals = []
        for item in data.get("deals", []) or []:
            try:
                deals.append(
                    DealSummary(
                        rank=item.get("rank", 0),
                        title=item.get("title", ""),
                        site_name=item.get("site_name", ""),
                        price_eur=float(item.get("price_eur") or 0.0),
                        effective_price_eur=float(item.get("effective_price_eur") or 0.0),
                        condition=item.get("condition", "unknown"),
                        score=float(item.get("score") or 0.0),
                        verdict=item.get("verdict", "watch"),
                        url=item.get("url", ""),
                        domain=item.get("domain", "generic"),
                    )
                )
            except (TypeError, ValueError):
                logger.warning("Skipping malformed deal in %s", path)
                continue

        return SearchRun(
            timestamp=timestamp,
            slug=slug,
            prompt=data.get("prompt", ""),
            generated_at=data.get("generated_at", ""),
            deal_count=len(deals),
            filtered_out_count=data.get("filtered_out_count", 0),
            site_count=len({d.site_name for d in deals}),
            path=path,
            deals=deals,
            price_alerts=data.get("price_alerts", []) or [],
        )
