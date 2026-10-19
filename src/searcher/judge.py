"""LLM Judge - evaluates deals against user criteria."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from src.llm.client import LLMClient
from src.config.models import SearchCriteria

logger = logging.getLogger(__name__)


class LLMJudge:
    """Evaluates deals against user criteria using LLM."""

    def __init__(self, config, llm: Optional["LLMClient"] = None):
        self.config = config
        self.llm = llm or LLMClient(config)

    async def judge(
        self,
        item_title: str,
        item_price: float,
        item_condition: str,
        item_url: str,
        item_condition: str,
        prompt: str,
        criteria,
        detail_html: str = "",
    ) -> dict:
        """Judge a single deal against user criteria."""
        prompt_text = f"""
You are an expert deal evaluator. Judge if this item matches the user's criteria.

User criteria:
- Query: {prompt}
- Max price: {self.max_price or 'unlimited'} EUR
- Condition: {self.condition}
- Category: {self.category}
- Keywords: {', '.join(keywords) if keywords else 'any'}
- Exclusions: {', '.join(exclusions) if exclusions else 'none'}

Item:
- Title: {title}
- Price: {price} EUR
- Condition: {condition}
- URL: {url}
- Seller: {seller_name} ({seller_type})

Full page HTML (truncated):
{detail_html[:8000]}

Respond with ONLY valid JSON:
{{
  "decision": "ACCEPT|REJECT|NEED_DETAIL",
  "confidence": 0.0-1.0,
  "reasoning": "detailed reasoning",
  "match_score": 0-100,
  "deal_quality": "excellent|good|fair|poor",
  "match_reasons": ["reason1", "reason2"],
  "concerns": ["concern1", "concern2"]
}}
"""

        try:
            # This would need an actual LLM call
            # For now return mock
            return {
                "decision": "ACCEPT",
                "confidence": 0.8,
                "reasoning": "Matches criteria",
                "match_score": 85,
                "deal_quality": "good"
            }
        except Exception as e:
            return {"decision": "UNCERTAIN", "confidence": 0.0, "reasoning": str(e)}