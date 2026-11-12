"""Shared search pipeline for all CLI search commands.

Encapsulates the logic previously duplicated across ``run_search``,
``_diamond_search_async``, and ``_search_async`` so a single change covers
all entry points.

Class dependencies (LLMClient, StorageManager, BrowserManager,
ResultProcessor, PlaywrightSearcher) are accepted as parameters so tests can
monkeypatch them in the caller's module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from src.browser.manager import BrowserManager
from src.config.models import AppConfig
from src.llm.client import LLMClient
from src.notifications.manager import NotificationManager
from src.output.processor import ResultProcessor
from src.searcher.adapters.base import Deal
from src.searcher.filters import SearchFilters
from src.searcher.site_selection import SitePlan
from src.storage.manager import StorageManager

logger = logging.getLogger(__name__)


@dataclass
class SearchContext:
    """Shared resources for one search cycle."""

    config: AppConfig
    llm: LLMClient
    storage: StorageManager
    browser_mgr: BrowserManager
    processor: ResultProcessor


@dataclass
class SearchResult:
    """Outcome of one search cycle."""

    deals: list[Deal]
    sites: list[str]
    json_path: str | None
    md_path: str | None
    results_dir: str
    site_plan: SitePlan | None = None


def build_notification_manager(config: AppConfig) -> NotificationManager:
    """Build a NotificationManager with console channel plus any configured channels."""
    import os

    from src.notifications.channels.console import ConsoleChannel
    from src.notifications.channels.discord import DiscordChannel
    from src.notifications.channels.email import EmailChannel
    from src.notifications.channels.system import SystemChannel
    from src.notifications.channels.webhook import WebhookChannel
    from src.notifications.manager import NotificationManager

    nm = NotificationManager()
    nm.add_channel(ConsoleChannel())
    for ch in getattr(config.notifications, "channels", []) or []:
        ctype = (ch.type or "console").lower()
        try:
            if ctype == "console":
                nm.add_channel(ConsoleChannel(name=ch.name or "console"))
            elif ctype == "system":
                nm.add_channel(SystemChannel(name=ch.name or "system"))
            elif ctype == "webhook":
                url = (
                    ch.settings.get("url")
                    or ch.settings.get("webhook_url")
                    or os.environ.get("ADS_WEBHOOK_URL", "")
                )
                if url:
                    nm.add_channel(WebhookChannel(name=ch.name or "webhook", url=url))
            elif ctype == "email":
                nm.add_channel(EmailChannel(name=ch.name or "email"))
            elif ctype == "discord":
                url = (
                    ch.settings.get("webhook_url")
                    or os.environ.get("ADS_DISCORD_WEBHOOK_URL", "")
                )
                if url:
                    nm.add_channel(DiscordChannel(name=ch.name or "discord", webhook_url=url))
        except Exception:  # noqa: BLE001 - a misconfigured channel must not break the run
            logger.debug("Failed to add notification channel %s", ctype)
    return nm


async def build_context(
    config,
    brand_filter: str | None = None,
    llm_class=None,
    storage_class=None,
    browser_manager_class=None,
    processor_class=None,
) -> SearchContext:
    """Build shared resources from config, injecting injectable classes."""
    if llm_class is None:
        from src.llm.client import LLMClient as llm_class
    if storage_class is None:
        from src.storage.manager import StorageManager as storage_class
    if browser_manager_class is None:
        from src.browser.manager import BrowserManager as browser_manager_class
    if processor_class is None:
        from src.output.processor import ResultProcessor as processor_class

    llm = llm_class(config)
    storage = storage_class(config.storage.db_path)
    browser_mgr = browser_manager_class(config)
    processor = processor_class(config, llm, brand_filter=brand_filter)
    return SearchContext(config, llm, storage, browser_mgr, processor)


async def _price_alerts(storage: StorageManager) -> list[dict]:
    """Run price-drop, new-low, and fake-promo checks."""
    alerts: list[dict] = []
    try:
        from src.intelligence.price_tracker import PriceTracker

        tracker = PriceTracker(storage)
        objects: list = []
        objects.extend(tracker.check_price_drops(threshold_pct=5.0, days=7))
        objects.extend(tracker.check_new_lows(days=30))
        objects.extend(tracker.check_fake_promos(threshold_pct=30.0, days=30))
        alerts = [
            {
                "title": a.title,
                "message": a.message,
                "severity": a.severity,
                "metadata": a.metadata,
            }
            for a in objects
        ]
    except (AttributeError, ImportError) as exc:
        logger.warning("Price tracking unavailable: %s", exc)
    return alerts


async def _evaluate_alert_rules(config: AppConfig, storage: StorageManager) -> None:
    """Evaluate user-configurable alert rules."""
    try:
        from src.intelligence.price_tracker import AlertRuleEngine

        engine = AlertRuleEngine(storage, build_notification_manager(config))
        engine.evaluate_rules()
    except (AttributeError, ImportError) as exc:
        logger.warning("Alert rules unavailable: %s", exc)


async def run_pipeline(
    prompt: str,
    condition: str,
    category: str,
    filters: SearchFilters,
    sites: list[str] | None,
    ctx: SearchContext,
    *,
    diamond: bool = False,
    output_dir: str | None = None,
    on_sites: Callable[[list[str]], None] | None = None,
    searcher_class=None,
) -> SearchResult:
    """Single shared search pipeline.

    All CLI search commands route through here. Steps:
    1. Open browser and search sites
    2. Prune missing deals, save new ones
    3. Run price-tracking and alert-rule checks
    4. Save JSON/Markdown results
    """
    if searcher_class is None:
        from src.searcher.playwright_searcher import PlaywrightSearcher as searcher_class

    async with searcher_class(
        ctx.config,
        ctx.llm,
        ctx.storage,
        ctx.browser_mgr,
    ) as searcher:
        try:
            if diamond:
                if not searcher.diamond_search_enabled:
                    raise RuntimeError("Diamond Search agents unavailable")
                deals = await searcher.search_with_diamond(
                    prompt, condition, category, filters
                )
                site_plan = searcher.site_plan
            else:
                captured: list[str] = []

                def _capture(names: list[str]) -> None:
                    for name in names:
                        if name not in captured:
                            captured.append(name)
                    if on_sites:
                        on_sites(list(names))

                deals = await searcher.search(
                    prompt,
                    condition,
                    category,
                    filters,
                    on_sites=_capture,
                    sites=sites,
                )
                site_plan = searcher.site_plan
                sites = captured
        finally:
            await ctx.browser_mgr.close()

    # Prune missing (deals not found this run)
    ctx.storage.prune_missing(
        max_age_days=ctx.config.search.prune_after_days or 30
    )

    # Save new deals
    for deal in deals:
        ctx.storage.save_deal(deal)

    # Price tracking alerts
    alerts = await _price_alerts(ctx.storage)

    # Alert rules
    await _evaluate_alert_rules(ctx.config, ctx.storage)

    # Save results
    target_dir = output_dir or ctx.config.output.directory
    if alerts:
        json_path, md_path = await ctx.processor.save_results(
            deals,
            target_dir,
            prompt=prompt,
            site_plan=site_plan,
            price_alerts=alerts,
        )
    else:
        json_path, md_path = await ctx.processor.save_results(
            deals,
            target_dir,
            prompt=prompt,
            site_plan=site_plan,
        )

    return SearchResult(
        deals=deals,
        sites=list(sites) if sites else [],
        json_path=json_path,
        md_path=md_path,
        results_dir=target_dir,
        site_plan=site_plan,
    )
