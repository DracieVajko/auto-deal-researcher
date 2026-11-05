"""Tests for search_cache.py (search response caching)."""

import json
import time
from src.searcher.search_cache import SearchCache


def test_cache_set_and_get(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    deals = [{"url": "https://a/1", "title": "Item 1", "price_eur": 100.0}]
    cache.set("bazos", "Citroen eC3", deals, {"max_price": 20000})
    result = cache.get("bazos", "Citroen eC3", {"max_price": 20000})
    assert result == deals


def test_cache_miss_different_query(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("bazos", "Citroen eC3", [{"url": "https://a/1"}], {})
    assert cache.get("bazos", "Tesla Model 3", {}) is None


def test_cache_miss_different_site(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("bazos", "Citroen eC3", [{"url": "https://a/1"}], {})
    assert cache.get("alza", "Citroen eC3", {}) is None


def test_cache_miss_different_filters(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("bazos", "Citroen eC3", [{"url": "https://a/1"}], {"max_price": 20000})
    assert cache.get("bazos", "Citroen eC3", {"max_price": 10000}) is None


def test_cache_expiry(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=1)
    cache.set("bazos", "Citroen eC3", [{"url": "https://a/1"}], {})
    assert cache.get("bazos", "Citroen eC3", {}) is not None
    time.sleep(1.1)
    assert cache.get("bazos", "Citroen eC3", {}) is None


def test_cache_empty_not_stored(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("bazos", "Citroen eC3", [], {})
    assert cache.get("bazos", "Citroen eC3", {}) is None


def test_cache_clear(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("bazos", "Citroen eC3", [{"url": "https://a/1"}], {})
    cache.set("alza", "Tesla", [{"url": "https://b/1"}], {})
    assert cache.clear() == 2
    assert cache.get("bazos", "Citroen eC3", {}) is None
    assert cache.get("alza", "Tesla", {}) is None


def test_cache_stats(tmp_path):
    cache = SearchCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("bazos", "Citroen eC3", [{"url": "https://a/1"}, {"url": "https://a/2"}], {})
    stats = cache.stats()
    assert stats["entries"] == 1
    assert stats["total_deals"] == 2
