"""Selector health tracking — monitors adapter reliability and selector effectiveness."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar

from src.searcher.adapters.base import BaseAdapter, Deal

logger = logging.getLogger(__name__)


@dataclass
class SelectorMetric:
    """Metric for a single selector on a specific site."""
    selector: str
    site: str
    success_count: int = 0
    failure_count: int = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    avg_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0
    
    @property
    def health_score(self) -> float:
        """Composite health score (0-1)."""
        rate = self.success_rate
        # Decay score if no recent success
        if self.last_success:
            hours_since = (datetime.now() - self.last_success).total_seconds() / 3600
            if hours_since > 24:
                rate *= 0.5
            elif hours_since > 72:
                rate *= 0.25
        return rate


@dataclass
class SiteHealth:
    """Overall health for a site/adapter."""
    site_name: str
    adapter_class: str
    metrics: dict[str, SelectorMetric] = field(default_factory=dict)
    total_searches: int = 0
    successful_searches: int = 0
    failed_searches: int = 0
    last_search: datetime | None = None
    consecutive_failures: int = 0
    avg_deals_per_search: float = 0.0
    avg_latency_ms: float = 0.0
    
    @property
    def success_rate(self) -> float:
        return self.successful_searches / self.total_searches if self.total_searches > 0 else 0.0
    
    @property
    def is_healthy(self) -> bool:
        return self.success_rate >= 0.7 and self.consecutive_failures < 5


class SelectorHealthTracker:
    """Tracks selector health across sites and adapters."""
    
    STORAGE_FILE = "data/selector_health.json"
    EVENT_LOG = ".selector_health.log"
    HEALTH_THRESHOLD = 0.5  # Below this = unhealthy
    
    def __init__(self):
        self.sites: dict[str, SiteHealth] = {}
        self._load()
    
    def _load(self):
        path = Path(self.STORAGE_FILE)
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for site_name, site_data in data.items():
                metrics = {}
                for sel_name, metric_data in site_data.get("metrics", {}).items():
                    metric_data["last_success"] = (
                        datetime.fromisoformat(metric_data["last_success"]) 
                        if metric_data.get("last_success") else None
                    )
                    metric_data["last_failure"] = (
                        datetime.fromisoformat(metric_data["last_failure"]) 
                        if metric_data.get("last_failure") else None
                    )
                    metrics[sel_name] = SelectorMetric(**metric_data)
                site_data["metrics"] = metrics
                site_data["last_search"] = (
                    datetime.fromisoformat(site_data["last_search"]) 
                    if site_data.get("last_search") else None
                )
                self.sites[site_name] = SiteHealth(**site_data)
        except Exception as e:
            logger.warning(f"Failed to load selector health: {e}")
    
    def _save(self):
        path = Path(self.STORAGE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for site_name, site in self.sites.items():
            site_dict = asdict(site)
            site_dict["last_search"] = site.last_search.isoformat() if site.last_search else None
            data[site_name] = site_dict
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save selector health: {e}")
    
    def record_search_start(self, site_name: str, adapter_class: str):
        """Record start of a search."""
        if site_name not in self.sites:
            self.sites[site_name] = SiteHealth(site_name=site_name, adapter_class=adapter_class)
        self.sites[site_name].total_searches += 1
        self.sites[site_name].last_search = datetime.now()
    
    def record_search_result(
        self, 
        site_name: str, 
        success: bool, 
        deals_found: int, 
        latency_ms: float,
        selector_results: dict[str, bool] | None = None,
        blocked: bool = False,
    ):
        """Record search result with per-selector outcomes."""
        if site_name not in self.sites:
            return
        
        site = self.sites[site_name]
        if success:
            site.successful_searches += 1
            site.consecutive_failures = 0
        else:
            site.failed_searches += 1
            site.consecutive_failures += 1
        
        # Update running average
        total = site.total_searches
        site.avg_deals_per_search = ((site.avg_deals_per_search * (total - 1)) + deals_found) / total
        site.avg_latency_ms = ((site.avg_latency_ms * (total - 1)) + latency_ms) / total
        
        # Record per-selector results
        if selector_results:
            for selector, sel_success in selector_results.items():
                if selector not in site.metrics:
                    site.metrics[selector] = SelectorMetric(selector=selector, site=site_name)
                metric = site.metrics[selector]
                if sel_success:
                    metric.success_count += 1
                    metric.last_success = datetime.now()
                else:
                    metric.failure_count += 1
                    metric.last_failure = datetime.now()

        # Append one JSON line per run so degradation can be tailed/alerted on.
        self._append_event(site_name, site, len(site.metrics), latency_ms, blocked)
        self._save()

    def _append_event(
        self,
        site_name: str,
        site: SiteHealth,
        selectors: int,
        latency_ms: float,
        blocked: bool,
    ) -> None:
        """Append a JSON line to .selector_health.log."""
        try:
            path = Path(self.EVENT_LOG)
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now().isoformat(),
                "site": site_name,
                "adapter_class": site.adapter_class,
                "success_rate": round(site.success_rate, 3),
                "total_searches": site.total_searches,
                "consecutive_failures": site.consecutive_failures,
                "selectors_tracked": selectors,
                "avg_deals_per_search": round(site.avg_deals_per_search, 2),
                "latency_ms": round(latency_ms, 1),
                "blocked": blocked,
                "is_healthy": site.is_healthy,
            }
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning(f"Failed to append selector health event: {e}")

    @staticmethod
    def read_events(limit: int = 20) -> list[dict]:
        """Read the most recent JSONL events, oldest first."""
        path = Path(SelectorHealthTracker.EVENT_LOG)
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        return out[-limit:]
    
    def record_selector_latency(self, site_name: str, selector: str, latency_ms: float):
        """Record latency for a specific selector."""
        if site_name not in self.sites:
            return
        if selector not in self.sites[site_name].metrics:
            self.sites[site_name].metrics[selector] = SelectorMetric(selector=selector, site=site_name)
        metric = self.sites[site_name].metrics[selector]
        metric.last_latency_ms = latency_ms
        metric.avg_latency_ms = (metric.avg_latency_ms + latency_ms) / 2
        self._save()
    
    def get_site_health(self, site_name: str) -> SiteHealth | None:
        """Get health for a specific site."""
        return self.sites.get(site_name)
    
    def get_all_health(self) -> dict[str, SiteHealth]:
        """Get health for all sites."""
        return self.sites.copy()
    
    def get_unhealthy_sites(self) -> list[str]:
        """Get list of unhealthy sites."""
        return [
            name for name, site in self.sites.items() 
            if not site.is_healthy
        ]
    
    def get_selector_report(self, site_name: str) -> dict:
        """Get detailed selector report for a site."""
        site = self.sites.get(site_name)
        if not site:
            return {}
        return {
            "site": site_name,
            "overall_health": site.success_rate,
            "is_healthy": site.is_healthy,
            "total_searches": site.total_searches,
            "avg_deals_per_search": round(site.avg_deals_per_search, 2),
            "avg_latency_ms": round(site.avg_latency_ms, 1),
            "selectors": {
                name: {
                    "success_rate": round(m.success_rate, 3),
                    "health_score": round(m.health_score, 3),
                    "success_count": m.success_count,
                    "failure_count": m.failure_count,
                    "avg_latency_ms": round(m.avg_latency_ms, 1),
                    "last_success": m.last_success.isoformat() if m.last_success else None,
                    "last_failure": m.last_failure.isoformat() if m.last_failure else None,
                }
                for name, m in site.metrics.items()
            }
        }
    
    def get_summary(self) -> dict:
        """Get overall health summary."""
        total_sites = len(self.sites)
        healthy = sum(1 for s in self.sites.values() if s.is_healthy)
        return {
            "total_sites": total_sites,
            "healthy_sites": healthy,
            "unhealthy_sites": total_sites - healthy,
            "sites": {
                name: {
                    "success_rate": round(site.success_rate, 3),
                    "is_healthy": site.is_healthy,
                    "consecutive_failures": site.consecutive_failures,
                    "avg_deals": round(site.avg_deals_per_search, 2),
                }
                for name, site in self.sites.items()
            }
        }


# Global instance
health_tracker = SelectorHealthTracker()


async def run_health_check(config, browser_manager) -> dict:
    """Run a quick health check on all enabled sites."""
    from src.searcher.adapters import get_adapter
    
    results = {}
    for site in config.search.websites:
        if not site.enabled:
            continue
        try:
            adapter_cls = get_adapter(site.adapter_class)
            adapter = adapter_cls()
            page = await browser_manager.get_page()
            start = time.perf_counter()
            deals = await adapter.search(page, "test query", max_results=5)
            latency = (time.perf_counter() - start) * 1000
            await page.close()
            
            health_tracker.record_search_start(site.name, site.adapter_class)
            health_tracker.record_search_result(
                site.name, 
                len(deals) > 0, 
                len(deals), 
                latency
            )
            results[site.name] = {
                "status": "healthy" if len(deals) > 0 else "degraded",
                "deals_found": len(deals),
                "latency_ms": round(latency, 1),
            }
        except Exception as e:
            logger.error(f"Health check failed for {site.name}: {e}")
            health_tracker.record_search_start(site.name, site.adapter_class)
            health_tracker.record_search_result(site.name, False, 0, 0)
            results[site.name] = {"status": "unhealthy", "error": str(e)}
    
    return results