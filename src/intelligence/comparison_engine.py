"""Multi-candidate comparison for the replacement finder.

Takes a reference ItemSpecs and a list of candidate deals, scores each
against the reference, ranks them, and produces a comparison result with
winner, runner-ups, and a comparison table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.intelligence.deal_scorer import DealScorer

logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    """Result of comparing candidate deals against a reference item."""

    reference_item: str
    reference_category: str
    candidates: list[dict] = field(default_factory=list)
    winner: dict | None = None
    runner_ups: list[dict] = field(default_factory=list)
    comparison_table: list[dict] = field(default_factory=list)
    total_candidates: int = 0


class ComparisonEngine:
    """Compares candidate deals against reference specs and ranks them."""

    def __init__(self, scorer: DealScorer | None = None):
        self.scorer = scorer or DealScorer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(self, reference_specs: dict, deals: list) -> ComparisonResult:
        """Score and rank *deals* against *reference_specs*.

        Returns a ComparisonResult with winner, runner-ups, and table.
        """
        reference_specs = reference_specs or {}
        reference_item = reference_specs.get("item_name", "unknown item")
        reference_category = reference_specs.get("category", "general")

        scored: list[tuple] = []
        for deal in deals:
            deal_score = self.scorer.score(deal, reference_specs)
            scored.append((deal, deal_score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1].score, reverse=True)

        # Build result
        result = ComparisonResult(
            reference_item=reference_item,
            reference_category=reference_category,
            total_candidates=len(deals),
        )

        for rank, (deal, deal_score) in enumerate(scored, 1):
            candidate = {
                "rank": rank,
                "url": getattr(deal, "url", ""),
                "title": getattr(deal, "title", ""),
                "site_name": getattr(deal, "site_name", ""),
                "price_eur": getattr(deal, "price_eur", 0.0),
                "effective_price_eur": self._effective_price(deal),
                "condition": getattr(deal, "condition", "unknown"),
                "score": deal_score.score,
                "breakdown": deal_score.breakdown,
                "reasons": deal_score.reasons,
                "matches_requirements": deal_score.matches_requirements,
            }
            result.candidates.append(candidate)

            if rank == 1:
                result.winner = candidate
            elif rank <= 3:
                result.runner_ups.append(candidate)

        # Build comparison table (simplified for display)
        for candidate in result.candidates[:10]:
            result.comparison_table.append({
                "rank": candidate["rank"],
                "title": candidate["title"],
                "site": candidate["site_name"],
                "price": candidate["effective_price_eur"],
                "score": candidate["score"],
                "match": "yes" if candidate["matches_requirements"] else "no",
            })

        logger.info(
            "Comparison complete: %d candidates, winner=%s (score %.1f)",
            len(deals),
            result.winner["title"] if result.winner else "none",
            result.winner["score"] if result.winner else 0.0,
        )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _effective_price(deal) -> float:
        quote = getattr(deal, "price_quote", None)
        if quote is not None and hasattr(quote, "effective_price_eur") and quote.effective_price_eur > 0:
            return float(quote.effective_price_eur)
        return float(getattr(deal, "price_eur", 0.0) or 0.0)
