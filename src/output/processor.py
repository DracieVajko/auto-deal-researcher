"""Result processor for JSON and Markdown output."""

import json
import os
from datetime import datetime
from pathlib import Path
from src.searcher.adapters.base import Deal
from src.config.models import OutputConfig


class ResultProcessor:
    def __init__(self, config):
        self.config: OutputConfig = config.output

    def save_results(self, deals: list[Deal], output_dir: str = None):
        """Save results in both JSON and Markdown formats."""
        if output_dir is None:
            output_dir = self.config.directory
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Save as JSON
        json_path = Path(output_dir) / f"results_{timestamp}.json"
        json_data = [
            {
                "url": d.url,
                "title": d.title,
                "price_eur": d.price_eur,
                "currency": d.currency,
                "condition": d.condition,
                "category": d.category,
                "site_name": d.site_name,
                "metadata": d.metadata,
            }
            for d in deals
        ]
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        # Convert to Markdown
        md_content = self._convert_to_markdown(deals, timestamp)
        md_path = Path(output_dir) / f"results_{timestamp}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        return str(json_path), str(md_path)

    def _convert_to_markdown(self, deals: list[Deal], timestamp: str) -> str:
        """Convert search results to Markdown format."""
        if not deals:
            return f"# Deal Search Results - {timestamp}\n\nNo deals found.\n"

        md = f"# Deal Search Results - {timestamp}\n\n"
        md += f"Found **{len(deals)}** deals:\n\n"
        md += "| # | Site | Product | Price | Condition | Category | Link |\n"
        md += "|---|------|---------|-------|-----------|----------|------|\n"

        for i, deal in enumerate(deals, 1):
            md += f"| {i} | {deal.site_name} | {deal.title} | {deal.price_eur:.2f} {deal.currency} | {deal.condition} | {deal.category} | [Link]({deal.url}) |\n"

        return md