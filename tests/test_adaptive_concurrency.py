from src.diagnostics.selector_health import SelectorHealthTracker, SiteHealth


def test_unknown_site_gets_base_concurrency():
    t = SelectorHealthTracker.__new__(SelectorHealthTracker)
    t.sites = {}
    assert t.concurrency_for("never-seen", base=3) == 3


def test_unhealthy_site_gets_one():
    t = SelectorHealthTracker.__new__(SelectorHealthTracker)
    site = SiteHealth(site_name="x", adapter_class="A")
    site.consecutive_failures = 6  # unhealthy
    t.sites = {"x": site}
    assert t.concurrency_for("x", base=3) == 1


def test_healthy_site_keeps_base():
    t = SelectorHealthTracker.__new__(SelectorHealthTracker)
    site = SiteHealth(site_name="x", adapter_class="A")
    site.successful_searches = 9
    site.total_searches = 10
    t.sites = {"x": site}
    assert t.concurrency_for("x", base=3) == 3