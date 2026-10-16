"""Shared fixtures for the live Playwright/site tests.

These tests hit real websites. They are skipped unless explicitly enabled:

    pytest -m live                 # run the live suite
    pytest -m live --site bazos    # one site

The `live` marker is already registered in pyproject.toml.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.browser.manager import BrowserManager  # noqa: E402
from src.config import load_config  # noqa: E402
from src.searcher.adapters import get_adapter  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--site",
        action="store",
        default=None,
        help="Only run the live test for this site (e.g. alza, bazos, ebay)",
    )
    parser.addoption(
        "--headed",
        action="store_true",
        default=False,
        help="Run the browser headed so you can watch it in VSCode",
    )


def pytest_collection_modifyitems(config, items):
    """Deselect live tests unless -m live was passed."""
    run_live = "live" in (config.getoption("-m") or "")
    skip_live = pytest.mark.skip(reason="live site test; enable with: pytest -m live")
    for item in items:
        if "live" in item.keywords and not run_live:
            item.add_marker(skip_live)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits real websites")


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture
def site_filter(request):
    return request.config.getoption("--site")


@pytest_asyncio.fixture
async def browser_manager(config):
    """A BrowserManager shared by the live tests; torn down automatically."""
    bm = BrowserManager(config)
    yield bm
    await bm.close()


@pytest.fixture
def make_page(browser_manager):
    """Factory: create a page with standard timeouts."""

    async def _make(session_id: str):
        page = await browser_manager.get_page(session_id=session_id)
        page.set_default_timeout(45000)
        page.set_default_navigation_timeout(45000)
        return page

    return _make


@pytest.fixture
def adapter_factory():
    """Factory: build an adapter instance by registry id."""

    def _make(site_id: str):
        return get_adapter(site_id)()

    return _make


def require_site(request, site_id: str) -> bool:
    """True when the current run is scoped to this site."""
    selected = request.config.getoption("--site")
    return selected in (None, site_id)


@pytest.fixture
def env_flag(name: str) -> bool:
    """Read a boolean env flag (used to skip optional live checks)."""
    return os.environ.get(name, "").lower() in {"1", "true", "yes"}