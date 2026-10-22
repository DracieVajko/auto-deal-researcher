"""Result processor for JSON and Markdown output."""

import json
import logging
import re
from pathlib import Path

from src.config.models import OutputConfig
from src.searcher.adapters.base import Deal
from src.utils.time import utcnow_stamp

logger = logging.getLogger(__name__)


class ResultProcessor:
    def __init__(self, config, llm=None):
        self.config: OutputConfig = config.output
        self.llm = llm

    def save_results(
        self,
        deals: list[Deal],
        output_dir: str | None = None,
        prompt: str | None = None,
    ):
        """Save results in both JSON and Markdown formats.

        The file name is ``results_<timestamp>_<slug>`` where the slug is a
        short AI-generated description of what was searched, so runs are
        identifiable at a glance instead of being a bare timestamp.
        """
        if output_dir is None:
            output_dir = self.config.directory

        timestamp = utcnow_stamp()
        slug = self._describe_search(prompt)
        stem = f"results_{timestamp}_{slug}" if slug else f"results_{timestamp}"

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        json_path = Path(output_dir) / f"{stem}.json"
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
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        title = slug.replace("-", " ") if slug else "Deal Search Results"
        md_content = self._convert_to_markdown(deals, timestamp, title=title)
        md_path = Path(output_dir) / f"{stem}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return str(json_path), str(md_path)

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------
    def _describe_search(self, prompt: str | None) -> str:
        """Short kebab-case slug describing the search, from the LLM if possible."""
        if not prompt:
            return ""

        raw = None
        if self.llm is not None:
            try:
                raw = self.llm._generate_filename_slug_sync(prompt)
            except Exception as e:  # noqa: BLE001 - naming must never break a run
                logger.debug("Slug generation failed: %s", e)
                raw = None

        if not raw:
            # Deterministic fallback: keyword terms from the prompt.
            try:
                from src.llm.client import LLMClient

                raw = LLMClient.keyword_query(prompt, max_words=4)
            except Exception:
                raw = prompt

        return self._slugify(raw)

    @staticmethod
    def _slugify(text: str, max_words: int = 5, max_len: int = 48) -> str:
        """Reduce arbitrary text to a safe file-name slug."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-")
        words = [w for w in text.split("-") if w][:max_words]
        slug = "-".join(words)
        if len(slug) > max_len:
            slug = slug[:max_len].rstrip("-")
        return slug

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------
    def _convert_to_markdown(self, deals: list[Deal], timestamp: str, title: str = "") -> str:
        """Convert search results to Markdown format."""
        heading = title.strip() or "Deal Search Results"
        if not deals:
            return f"# {heading} - {timestamp}\n\nNo deals found.\n"

        md = f"# {heading} - {timestamp}\n\n"
        md += f"Found **{len(deals)}** deals:\n\n"
        md += "| # | Site | Product | Price | Condition | Category | Link |\n"
        md += "|---|------|---------|-------|-----------|----------|------|\n"

        for i, deal in enumerate(deals, 1):
            md += (
                f"| {i} | {deal.site_name} | {deal.title} | "
                f"{deal.price_eur:.2f} {deal.currency} | {deal.condition} | "
                f"{deal.category} | [Link]({deal.url}) |\n"
            )

        return md