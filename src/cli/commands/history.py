"""CLI commands for history, trends, watchlist, and monitoring."""

import asyncio
from typing import Optional

import typer

from src.config import load_config
from src.diagnostics.selector_health import SelectorHealthTracker, run_health_check
from src.history.trends import TrendsAnalyzer
from src.history.watchlist import WatchlistManager
from src.intelligence.price_tracker import PriceTracker
from src.notifications import NotificationManager
from src.storage.manager import StorageManager

history_app = typer.Typer(help="History, trends, watchlist, and monitoring commands")


@history_app.command()
def history(
    url: str = typer.Argument(..., help="Product URL to show history for"),
    days: int = typer.Option(30, "--days", "-d", help="Number of days of history to show"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, csv"),
):
    """Show price history for a specific product URL."""
    config = load_config()
    storage = StorageManager(config.storage.db_path)
    tracker = PriceTracker(storage)
    
    history = tracker.get_price_history(url, days)
    
    if not history:
        typer.echo("No history found for this URL")
        return
    
    if format == "json":
        import json
        typer.echo(json.dumps(history, indent=2))
    elif format == "csv":
        import csv
        import sys
        writer = csv.writer(sys.stdout)
        writer.writerow(["timestamp", "price_eur", "condition", "link"])
        for h in history:
            writer.writerow([h["timestamp"], h["price_eur"], h.get("condition", ""), h.get("link", "")])
    else:
        typer.echo(f"Price History for {url} (last {days} days)")
        typer.echo("-" * 80)
        typer.echo(f"{'Date':<20} {'Price (€)':>10} {'Condition':<15} {'Link':<40}")
        typer.echo("-" * 90)
        for h in history:
            typer.echo(f"{h['timestamp']:<20} {h['price_eur']:>10.2f} {h.get('condition', 'unknown'):<15} {h.get('link', ''):<40}")


@history_app.command()
def trends(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category to analyze (electronics, appliances, auto, etc.)"),
    days: int = typer.Option(30, "--days", "-d", help="Number of days to analyze"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table, json"),
):
    """Show price trends for a category or all categories."""
    config = load_config()
    storage = StorageManager(config.storage.db_path)
    analyzer = TrendsAnalyzer(storage)
    
    if category:
        result = analyzer.analyze_category(category, days)
        if "error" in result:
            typer.echo(f"Error: {result['error']}")
            return
        
        if result.get("trend") == "insufficient_data":
            typer.echo(f"Insufficient data for {category} (need more price history)")
            return
        
        trend_emoji = {"dropping": "📉", "rising": "📈", "stable": "➡️", "volatile": "📊", "insufficient_data": "❓"}
        
        if result.get("details"):
            typer.echo(f"\nTop movers in {category}:")
            for item in result["details"][:10]:
                emoji = "📉" if item["change_pct"] < 0 else "📈"
                typer.echo(f"  {emoji} {item['change_pct']:+.1f}% - {item['url'][:60]}")
    else:
        result = analyzer.get_all_category_trends(days)
        
        typer.echo(f"\n📊 Market Trends (last {days} days)")
        typer.echo("=" * 60)
        
        for cat, data in sorted(result.items()):
            if data.get("trend") == "insufficient_data":
                continue
            trend_emoji = {"dropping": "📉", "rising": "📈", "stable": "➡️", "volatile": "📊"}.get(data["trend"], "❓")
            typer.echo(f"\n{data['trend'].upper()} {data['trend']} {trend_emoji} — {cat.title()}")
            typer.echo(f"  Avg change: {data['avg_change_pct']:+.1f}% | Volatility: {data['avg_volatility']:.1%} | Products: {data['products_tracked']}")
            typer.echo(f"  📉 Dropping: {data['dropping_count']} | 📈 Rising: {data['rising_count']} | ➡️ Stable: {data['stable_count']}")


# Watchlist commands
watchlist_app = typer.Typer(help="Manage watchlist and price alerts")


@watchlist_app.command()
def watchlist_cmd(
    action: str = typer.Argument(..., help="Action: add, remove, list, check, trends"),
    url: str = typer.Option(None, "--url", "-u", help="Product URL"),
    title: str = typer.Option(None, "--title", "-t", help="Product title (for add)"),
    target_price: float = typer.Option(None, "--target-price", "-p", help="Target price in EUR"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Category filter"),
    threshold: float = typer.Option(5.0, "--threshold", help="Alert threshold % for price drops"),
    days: int = typer.Option(30, "--days", "-d", help="Days for trend analysis"),
):
    """Manage watchlist and check prices."""
    from src.storage.manager import StorageManager as SM
    config = load_config()
    db_storage = SM(config.storage.db_path)
    notifications = NotificationManager()
    wl_manager = WatchlistManager(db_storage, notifications)
    
    if action == "add":
        if not url or not title or target_price is None:
            typer.echo("Error: --url, --title, and --target-price required for add", err=True)
            raise typer.Exit(1)
        
        item = wl_manager.add_item(url, title, target_price, condition, category, threshold)
        typer.echo(f"✅ Added to watchlist: {title}")
        typer.echo(f"  Target: {target_price}€ | Threshold: {threshold}% | Condition: {condition}")
    
    elif action == "remove":
        if not url:
            typer.echo("Error: --url required for remove", err=True)
            raise typer.Exit(1)
        
        if wl_manager.remove_item(url):
            typer.echo("✅ Removed from watchlist")
        else:
            typer.echo("Not found in watchlist")
    
    elif action == "list":
        items = wl_manager.get_all()
        if not items:
            typer.echo("Watchlist is empty")
            return
        
        typer.echo(f"\n📋 Watchlist ({len(items)} items)")
        typer.echo("-" * 80)
        for item in items:
            status = "🎯" if item.target_price_reached else ("🔔" if item.alert_enabled else "🔕")
            typer.echo(f"{status} {item.title[:50]}")
            typer.echo(f"  Target: {item.target_price_eur}€ | Current: {item.current_price_eur or 'N/A'}€ | Threshold: {item.alert_threshold_pct}%")
            typer.echo(f"  URL: {item.url}")
            typer.echo()
    
    elif action == "check":
        typer.echo("🔍 Checking watchlist prices...")
        typer.echo("Run with: python -m src.cli watchlist check-async")
    
    elif action == "check-async":
        async def run_check():
            config = load_config()
            db_path = config.storage.db_path
            from src.storage.manager import StorageManager as SM
            from src.browser.manager import BrowserManager
            from src.llm.mock_client import MockLLMClient
            
            db_storage = SM(db_path)
            notifications = NotificationManager()
            wl_manager_async = WatchlistManager(db_storage, notifications)
            
            browser = BrowserManager(load_config())
            llm = MockLLMClient(load_config())
            
            async def run():
                from src.searcher.playwright_searcher import PlaywrightSearcher
                browser2 = BrowserManager(load_config())
                async with PlaywrightSearcher(load_config(), MockLLMClient(load_config()), None, browser2) as searcher:
                    await wl_manager_async.check_prices(searcher, None)
            
            asyncio.run(run())
            typer.echo("✅ Price check completed")
        
        asyncio.run(run_check())
    
    elif action == "trends":
        from src.history.trends import TrendsAnalyzer
        from src.storage.manager import StorageManager
        
        storage = StorageManager(load_config().storage.db_path)
        analyzer = TrendsAnalyzer(storage)
        result = analyzer.analyze_category(category, days)
        
        if result.get("trend") == "insufficient_data":
            typer.echo(f"Insufficient data for {category}")
            return
        
        typer.echo(f"\n📈 Trends for {category} (last {days} days)")
        typer.echo(f"  Trend: {result['trend'].upper()} {result['avg_change_pct']:+.1f}%")
        typer.echo(f"  Volatility: {result['avg_volatility']:.1%}")
        typer.echo(f"  Products tracked: {result['products_tracked']}")
        
        if result.get("details"):
            typer.echo("\nTop movers:")
            for item in result["details"][:10]:
                emoji = "📉" if item["change_pct"] < 0 else "📈"
                typer.echo(f"  {item['change_pct']:+.1f}% - {item['url'][:60]}")
    
    else:
        typer.echo(f"Unknown action: {action}")
        typer.echo("Available: add, remove, list, check, check-async, trends")


# Selector health commands
selector_app = typer.Typer(help="Selector health monitoring and diagnostics")


@selector_app.command()
def health(
    site: str = typer.Option(None, "--site", "-s", help="Check specific site only"),
    live: bool = typer.Option(False, "--live", "-l", help="Run live health check (requires browser)"),
):
    """Show selector health report."""
    config = load_config()
    
    if live:
        async def run_live():
            from src.browser.manager import BrowserManager
            browser = BrowserManager(config)
            try:
                results = await run_health_check(config, browser)
                typer.echo("\n🔍 Live Health Check Results:")
                for site_name, result in results.items():
                    status_emoji = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "❌"}.get(result.get("status", ""), "❓")
                    typer.echo(f"  {status_emoji} {site_name}: {result.get('status', 'unknown')} - {result.get('deals_found', 0)} deals, {result.get('latency_ms', 0)}ms")
            finally:
                await browser.close()
        
        asyncio.run(run_live())
        return
    
    # Static report from stored data
    tracker = SelectorHealthTracker()
    
    if site:
        report = tracker.get_selector_report(site)
        if not report:
            typer.echo(f"No data for site: {site}")
            return
        
        typer.echo(f"\n📊 Selector Health Report: {site}")
        typer.echo(f"  Overall Health: {report['overall_health']:.1%} {'✅' if report['is_healthy'] else '❌'}")
        typer.echo(f"  Total Searches: {report['total_searches']}")
        typer.echo(f"  Avg Deals/Search: {report['avg_deals_per_search']:.2f}")
        typer.echo(f"  Avg Latency: {report['avg_latency_ms']:.1f}ms")
        typer.echo("\n  Selectors:")
        for selector, data in report["selectors"].items():
            health_emoji = "✅" if data["health_score"] >= 0.7 else "⚠️" if data["health_score"] >= 0.4 else "❌"
            typer.echo(f"    {health_emoji} {selector}")
            typer.echo(f"       Success: {data['success_rate']:.1%} ({data['success_count']}/{data['success_count']+data['failure_count']})")
            typer.echo(f"       Avg Latency: {data['avg_latency_ms']:.1f}ms")
        return
    
    # Summary for all sites
    summary = tracker.get_summary()
    typer.echo(f"\n📊 Selector Health Summary")
    typer.echo(f"  Total Sites: {summary['total_sites']}")
    typer.echo(f"  Healthy: {summary['healthy_sites']} | Unhealthy: {summary['unhealthy_sites']}")
    typer.echo()
    
    for site_name, data in summary["sites"].items():
        health_emoji = "✅" if data["is_healthy"] else "❌"
        typer.echo(f"  {health_emoji} {site_name}: {data['success_rate']:.1%} success, {data['consecutive_failures']} consecutive failures, {data['avg_deals']:.1f} avg deals")


@selector_app.command()
def unhealthy():
    """List unhealthy sites that need attention."""
    tracker = SelectorHealthTracker()
    unhealthy = tracker.get_unhealthy_sites()
    
    if not unhealthy:
        typer.echo("✅ All sites healthy!")
        return
    
    typer.echo("❌ Unhealthy sites:")
    for site in unhealthy:
        report = tracker.get_selector_report(site)
        typer.echo(f"  {site}: {report['overall_health']:.1%} health, {report['consecutive_failures']} consecutive failures")


@selector_app.command()
def clear(
    site: str = typer.Option(None, "--site", "-s", help="Clear health data for specific site"),
    all: bool = typer.Option(False, "--all", help="Clear all health data"),
):
    """Clear selector health data (use with caution)."""
    if not all and not site:
        typer.echo("Error: specify --site or --all", err=True)
        raise typer.Exit(1)
    
    import os
    path = "data/selector_health.json"
    
    if all:
        if os.path.exists(path):
            os.remove(path)
            typer.echo("✅ Cleared all selector health data")
        else:
            typer.echo("No health data file found")
    elif site:
        tracker = SelectorHealthTracker()
        if site in tracker.sites:
            del tracker.sites[site]
            tracker._save()
            typer.echo(f"✅ Cleared health data for {site}")
        else:
            typer.echo(f"No data for site: {site}")


history_app.add_typer(selector_app, name="selector")
history_app.add_typer(watchlist_app, name="watchlist")
