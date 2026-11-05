"""File-based search response cache.

Caches adapter search results keyed by (site, query, filters_hash) to avoid
re-hitting marketplaces for identical searches. TTL configurable (default 1
hour).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SearchCache:
    """File-based JSON cache for search results."""

    def __init__(self, cache_dir: str | Path | None = None, ttl_seconds: int = 3600):
        self.cache_dir = Path(cache_dir or Path.home() / ".cache" / "autodeal" / "search")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, site: str, query: str, filters: dict | None = None) -> list[dict] | None:
        """Return cached deals for (site, query, filters), or None."""
        key = self._cache_key(site, query, filters)
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            try:
                path.unlink()
            except OSError:
                pass
            return None
        # Check expiry
        if time.time() - data.get("ts", 0) > self.ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return data.get("deals")

    def set(self, site: str, query: str, deals: list[dict], filters: dict | None = None) -> None:
        """Store deals for (site, query, filters)."""
        if not deals:
            # Don't cache empty results (likely blocked sites)
            return
        key = self._cache_key(site, query, filters)
        path = self.cache_dir / f"{key}.json"
        data = {
            "ts": time.time(),
            "site": site,
            "query": query,
            "deals": deals,
            "count": len(deals),
        }
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.debug("Failed to write cache entry %s: %s", key, exc)

    def clear(self) -> int:
        """Remove all cache entries. Returns count removed."""
        count = 0
        for path in self.cache_dir.glob("*.json"):
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
        return count

    def stats(self) -> dict:
        """Return cache statistics."""
        entries = list(self.cache_dir.glob("*.json"))
        total_deals = 0
        for path in entries:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                total_deals += data.get("count", 0)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "entries": len(entries),
            "total_deals": total_deals,
            "cache_dir": str(self.cache_dir),
            "ttl_seconds": self.ttl_seconds,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cache_key(self, site: str, query: str, filters: dict | None = None) -> str:
        filters_json = json.dumps(filters or {}, sort_keys=True, ensure_ascii=False)
        filters_hash = hashlib.sha256(filters_json.encode("utf-8")).hexdigest()[:16]
        raw = f"{site}|{query}|{filters_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
