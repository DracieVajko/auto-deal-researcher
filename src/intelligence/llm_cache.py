"""File-based LLM response cache.

Caches LLM responses keyed by (provider, model, prompt_hash) to avoid
re-paying for identical extractions across runs. Cache entries expire after
a configurable TTL (default 24 hours).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class LLMCache:
    """File-based JSON cache for LLM responses."""

    def __init__(self, cache_dir: str | Path | None = None, ttl_seconds: int = 86400):
        self.cache_dir = Path(cache_dir or Path.home() / ".cache" / "autodeal" / "llm")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, provider: str, model: str, prompt: str) -> str | None:
        """Return cached response for (provider, model, prompt), or None."""
        key = self._cache_key(provider, model, prompt)
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        # Check expiry
        if time.time() - data.get("ts", 0) > self.ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return data.get("response")

    def set(self, provider: str, model: str, prompt: str, response: str) -> None:
        """Store response for (provider, model, prompt)."""
        key = self._cache_key(provider, model, prompt)
        path = self.cache_dir / f"{key}.json"
        data = {"ts": time.time(), "provider": provider, "model": model, "response": response}
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.debug("Failed to write cache entry %s: %s", key, exc)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cache_key(self, provider: str, model: str, prompt: str) -> str:
        raw = f"{provider}|{model}|{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

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
