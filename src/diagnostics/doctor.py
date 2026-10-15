"""Doctor - Site health diagnostics."""

import time
from dataclasses import dataclass

from src.browser.manager import BrowserManager
from src.config import load_config
from src.searcher.adapters import get_adapter
from src.utils.time import utcnow, utcnow_iso


@dataclass
class DoctorResult:
    site_name: str
    adapter_class: str
    http_status: int | None
    selector_found: bool
    items_found: int
    first_items: list[dict]
    duration_ms: int
    error: str | None
    timestamp: str


class Doctor:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.browser_manager = BrowserManager(self.config)

    async def check_site(self, site_name: str, live: bool = True) -> DoctorResult:
        """Check a single site's health."""
        start = time.perf_counter()
        
        # Find site config
        site_config = None
        for site in self.config.search.websites:
            if site.name == site_name:
                site_config = site
                break
        
        if not site_config:
            return DoctorResult(
                site_name=site_name,
                adapter_class="",
                http_status=None,
                selector_found=False,
                items_found=0,
                first_items=[],
                duration_ms=0,
                error=f"Site '{site_name}' not found in config",
                timestamp=utcnow_iso()
            )
        
        if not site_config.enabled:
            return DoctorResult(
                site_name=site_name,
                adapter_class=site_config.adapter_class,
                http_status=None,
                selector_found=False,
                items_found=0,
                first_items=[],
                duration_ms=0,
                error="Site disabled in config",
                timestamp=utcnow_iso()
            )
        
        if not live:
            return DoctorResult(
                site_name=site_name,
                adapter_class=site_config.adapter_class,
                http_status=None,
                selector_found=False,
                items_found=0,
                first_items=[],
                duration_ms=0,
                error="Offline mode - no network check",
                timestamp=utcnow_iso()
            )
        
        # Use browser manager's get_page() which has cookie handling
        page = await self.browser_manager.get_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(30000)

        try:
            adapter_cls = get_adapter(site_config.adapter_class)
            adapter = adapter_cls()

            # Use adapter's search method which handles navigation and extraction
            deals = await adapter.search(page, "test", max_results=3)
            items_found = len(deals)
            selector_found = items_found > 0
            http_status = 200  # adapter.search navigates internally
            
            # Extract first 3 items from search results
            first_items = []
            for deal in deals[:3]:
                first_items.append({
                    "title": deal.title,
                    "price": deal.price_eur,
                    "condition": deal.condition,
                    "url": deal.url
                })
            
            duration_ms = int((time.perf_counter() - start) * 1000)
            
            return DoctorResult(
                site_name=site_name,
                adapter_class=site_config.adapter_class,
                http_status=http_status,
                selector_found=selector_found,
                items_found=items_found,
                first_items=first_items,
                duration_ms=duration_ms,
                error=None,
                timestamp=utcnow_iso()
            )
            
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return DoctorResult(
                site_name=site_name,
                adapter_class=site_config.adapter_class,
                http_status=None,
                selector_found=False,
                items_found=0,
                first_items=[],
                duration_ms=duration_ms,
                error=str(e),
                timestamp=utcnow_iso()
            )
        finally:
            await page.close()

    async def check_all(self, live: bool = True) -> list[DoctorResult]:
        """Check all enabled sites."""
        results = []
        for site in self.config.search.websites:
            if site.enabled:
                result = await self.check_site(site.name, live=live)
                results.append(result)
        return results


def print_doctor_results(results: list[DoctorResult]) -> None:
    """Print doctor results in a nice table."""
    print("\n" + "=" * 80)
    print(f"DOCTOR REPORT - {utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 80)
    
    for r in results:
        print(f"\n🔍 {r.site_name} ({r.adapter_class})")
        print(f"   HTTP Status: {r.http_status if r.http_status else 'N/A'}")
        print(f"   Selector Found: {'✅' if r.selector_found else '❌'}")
        print(f"   Items Found: {r.items_found}")
        print(f"   Duration: {r.duration_ms}ms")
        if r.error:
            print(f"   Error: {r.error}")
        if r.first_items:
            for i, item in enumerate(r.first_items):
                print(f"   [{i+1}] {item['title'][:60]} | {item['price']}€ | {item['condition']}")
    
    # Summary
    total = len(results)
    healthy = sum(1 for r in results if r.selector_found and r.items_found > 0)
    print(f"\n{'='*80}")
    print(f"SUMMARY: {healthy}/{total} sites healthy")
    print(f"{'='*80}\n")