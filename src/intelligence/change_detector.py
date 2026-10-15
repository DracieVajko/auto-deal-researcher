"""Change detection between search runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.storage.manager import StorageManager
from src.utils.time import utcnow_iso


@dataclass
class DealChange:
    url: str
    title: str
    site_name: str
    old_price: float | None = None
    new_price: float | None = None
    change_pct: float | None = None
    old_condition: str | None = None
    new_condition: str | None = None
    old_availability: str | None = None
    new_availability: str | None = None
    change_type: str = ""  # new, removed, price_change, condition_change, availability_change


@dataclass
class RunChangeReport:
    current_run_id: str
    previous_run_id: str | None
    prompt: str
    generated_at: str

    new_deals: list[dict] = field(default_factory=list)
    removed_deals: list[dict] = field(default_factory=list)
    price_changes: list[dict] = field(default_factory=list)
    condition_changes: list[dict] = field(default_factory=list)
    availability_changes: list[dict] = field(default_factory=list)

    # Summary counts
    new_count: int = 0
    removed_count: int = 0
    price_drop_count: int = 0
    price_increase_count: int = 0
    condition_change_count: int = 0
    availability_change_count: int = 0

    def has_significant_changes(self, threshold_pct: float = 10.0) -> bool:
        """Check if there are significant changes worth alerting."""
        return (
            len(self.price_changes) > 0 or
            len(self.new_deals) > 0 or
            len(self.removed_deals) > 0
        )

    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            "# Monitoring Report",
            f"**Run ID:** {self.current_run_id}",
            f"**Previous Run:** {self.previous_run_id or 'N/A (first run)'}",
            f"**Prompt:** {self.prompt}",
            f"**Generated:** {self.generated_at}",
            "",
            "## Summary",
            f"- **New deals:** {self.new_count}",
            f"- **Price drops:** {self.price_drop_count}",
            f"- **Price increases:** {self.price_increase_count}",
            f"- **Removed/expired:** {self.removed_count}",
            f"- **Condition changes:** {self.condition_change_count}",
            f"- **Availability changes:** {self.availability_change_count}",
            "",
        ]

        if self.new_deals:
            lines.append("## New Deals")
            for deal in self.new_deals:
                lines.append(
                    f"- **{deal['title']}** — {deal['price_eur']}€ ({deal['condition']}) — "
                    f"[{deal['site_name']}]({deal['url']})"
                )
            lines.append("")

        if self.price_changes:
            drops = [c for c in self.price_changes if c.get("change_pct", 0) < 0]
            increases = [c for c in self.price_changes if c.get("change_pct", 0) > 0]

            if drops:
                lines.append("## Price Drops")
                for change in drops:
                    lines.append(
                        f"- **{change['title']}** — {change['old_price']}€ → {change['new_price']}€ "
                        f"(**{change['change_pct']}%** ↓) — [{change['site_name']}]({change['url']})"
                    )
                lines.append("")

            if increases:
                lines.append("## Price Increases")
                for change in increases:
                    lines.append(
                        f"- **{change['title']}** — {change['old_price']}€ → {change['new_price']}€ "
                        f"(**{change['change_pct']}%** ↑) — [{change['site_name']}]({change['url']})"
                    )
                lines.append("")

        if self.removed_deals:
            lines.append("## Removed / Expired")
            for deal in self.removed_deals:
                lines.append(
                    f"- **{deal['title']}** — was {deal['price_eur']}€ ({deal['condition']}) — "
                    f"[{deal['site_name']}]({deal['url']})"
                )
            lines.append("")

        if self.condition_changes:
            lines.append("## Condition Changes")
            for change in self.condition_changes:
                lines.append(
                    f"- **{change['title']}** — {change['old_condition']} → {change['new_condition']} — "
                    f"[{change['site_name']}]({change['url']})"
                )
            lines.append("")

        if self.availability_changes:
            lines.append("## Availability Changes")
            for change in self.availability_changes:
                lines.append(
                    f"- **{change['title']}** — {change['old_availability']} → {change['new_availability']} — "
                    f"[{change['site_name']}]({change['url']})"
                )
            lines.append("")

        lines.append("---")
        lines.append(f"*Report generated at {self.generated_at}*")
        return "\n".join(lines)


class ChangeDetector:
    """Detects changes between search runs."""

    def __init__(self, storage: StorageManager):
        self.storage = storage

    def generate_run_report(
        self,
        current_run_id: str,
        prompt: str,
        current_deals: list,
        previous_run_id: str | None = None,
    ) -> RunChangeReport:
        """Compare current run vs previous run and generate report."""
        report = RunChangeReport(
            current_run_id=current_run_id,
            previous_run_id=previous_run_id,
            prompt=prompt,
            generated_at=utcnow_iso(),
        )

        # Get current deals as dict keyed by URL
        current_by_url = {deal.url: deal for deal in current_deals}
        current_urls = set(current_by_url.keys())

        # Get previous run deals
        previous_by_url = {}
        if previous_run_id:
            prev_run = self.storage.get_run(previous_run_id)
            if prev_run:
                # Get deals from that run - we need to query price_history for that run
                prev_urls = self._get_deals_for_run(previous_run_id)
                for url, deal_data in prev_urls.items():
                    previous_by_url[url] = deal_data

        previous_urls = set(previous_by_url.keys())

        # Find new deals (in current but not in previous)
        new_urls = current_urls - previous_urls
        for url in new_urls:
            deal = current_by_url[url]
            report.new_deals.append({
                "url": deal.url,
                "title": deal.title,
                "price_eur": deal.price_eur,
                "condition": deal.condition,
                "site_name": deal.site_name,
            })

        # Find removed deals (in previous but not in current)
        removed_urls = previous_urls - current_urls
        for url in removed_urls:
            deal = previous_by_url[url]
            report.removed_deals.append({
                "url": deal["url"],
                "title": deal["title"],
                "price_eur": deal["price_eur"],
                "condition": deal["condition"],
                "site_name": deal["site_name"],
            })

        # Compare existing deals for changes
        common_urls = current_urls & previous_urls
        for url in common_urls:
            current = current_by_url[url]
            previous = previous_by_url[url]

            # Price change
            if abs(current.price_eur - previous["price_eur"]) > 0.01:
                _ = ((current.price_eur - previous["price_eur"]) / previous["price_eur"]) * 100
                price_change = {
                    "url": url,
                    "title": current.title,
                    "site_name": current.site_name,
                    "old_price": previous["price_eur"],
                    "new_price": current.price_eur,
                    "change_pct": round(((current.price_eur - previous["price_eur"]) / previous["price_eur"]) * 100, 2),
                }
                report.price_changes.append(price_change)
                if current.price_eur < previous["price_eur"]:
                    report.price_drop_count += 1
                else:
                    report.price_increase_count += 1

            # Condition change
            if current.condition != previous.get("condition", ""):
                report.condition_changes.append({
                    "url": url,
                    "title": current.title,
                    "site_name": current.site_name,
                    "old_condition": previous.get("condition", "unknown"),
                    "new_condition": current.condition,
                })

            # Availability change
            if getattr(current, "availability", "unknown") != previous.get("availability", "unknown"):
                report.availability_changes.append({
                    "url": url,
                    "title": current.title,
                    "site_name": current.site_name,
                    "old_availability": previous.get("availability", "unknown"),
                    "new_availability": getattr(current, "availability", "unknown"),
                })

        # Update summary counts
        report.new_count = len(report.new_deals)
        report.removed_count = len(report.removed_deals)
        report.price_drop_count = sum(1 for c in report.price_changes if c["change_pct"] < 0)
        report.price_increase_count = sum(1 for c in report.price_changes if c["change_pct"] > 0)
        report.condition_change_count = len(report.condition_changes)
        report.availability_change_count = len(report.availability_changes)

        return report

    def _get_deals_for_run(self, run_id: str) -> dict[str, dict]:
        """Get all deals associated with a specific run from price_history."""
        rows = self.storage.db.execute("""
            SELECT ph.url AS url, ph.price_eur AS price_eur,
                   ph.condition AS condition, ph.availability AS availability,
                   d.site_name AS site_name, d.title AS title,
                   ph.timestamp AS timestamp
            FROM price_history ph
            LEFT JOIN deals d ON ph.url = d.url
            WHERE ph.run_id = ?
        """, (run_id,)).fetchall()

        # Deduplicate by URL (keep latest)
        result = {}
        for row in rows:
            url = row["url"]
            if url not in result or row["timestamp"] > result[url]["timestamp"]:
                result[url] = dict(row)
        return result

    def generate_report_from_deals(
        self,
        current_run_id: str,
        prompt: str,
        current_deals: list,
        previous_deals: list | None = None,
    ) -> RunChangeReport:
        """Generate report from two lists of deals (for testing or manual comparison)."""
        report = RunChangeReport(
            current_run_id=current_run_id,
            previous_run_id=None,
            prompt=prompt,
            generated_at=utcnow_iso(),
        )

        current_by_url = {deal.url: deal for deal in current_deals}
        previous_by_url = {deal.url: deal for deal in (previous_deals or [])}

        current_urls = set(current_by_url.keys())
        previous_urls = set(previous_by_url.keys())

        # New deals
        for url in current_urls - previous_urls:
            deal = current_by_url[url]
            report.new_deals.append({
                "url": deal.url,
                "title": deal.title,
                "price_eur": deal.price_eur,
                "condition": deal.condition,
                "site_name": deal.site_name,
            })

        # Removed deals
        for url in previous_urls - current_urls:
            deal = previous_by_url[url]
            report.removed_deals.append({
                "url": deal.url,
                "title": deal.title,
                "price_eur": deal.price_eur,
                "condition": deal.condition,
                "site_name": deal.site_name,
            })

        # Price/condition changes
        for url in current_urls & previous_urls:
            current = current_by_url[url]
            previous = previous_by_url[url]

            if abs(current.price_eur - previous.price_eur) > 0.01:
                _ = ((current.price_eur - previous.price_eur) / previous.price_eur) * 100
                report.price_changes.append({
                    "url": url,
                    "title": current.title,
                    "site_name": current.site_name,
                    "old_price": previous.price_eur,
                    "new_price": current.price_eur,
                    "change_pct": round(((current.price_eur - previous.price_eur) / previous.price_eur) * 100, 2),
                })
                if current.price_eur < previous.price_eur:
                    report.price_drop_count += 1
                else:
                    report.price_increase_count += 1

            if current.condition != previous.condition:
                report.condition_changes.append({
                    "url": url,
                    "title": current.title,
                    "site_name": current.site_name,
                    "old_condition": previous.condition,
                    "new_condition": current.condition,
                })

            if getattr(current, "availability", "unknown") != getattr(previous, "availability", "unknown"):
                report.availability_changes.append({
                    "url": url,
                    "title": current.title,
                    "site_name": current.site_name,
                    "old_availability": getattr(previous, "availability", "unknown"),
                    "new_availability": getattr(current, "availability", "unknown"),
                })

        report.new_count = len(report.new_deals)
        report.removed_count = len(report.removed_deals)
        report.price_drop_count = sum(1 for c in report.price_changes if c["change_pct"] < 0)
        report.price_increase_count = sum(1 for c in report.price_changes if c["change_pct"] > 0)
        report.condition_change_count = len(report.condition_changes)
        report.availability_change_count = len(report.availability_changes)

        return report