"""Query expansion agent.

Generates diverse search queries for the user's request. Uses the shared
LLMClient when one is available and falls back to a deterministic set of
template variations otherwise, so the pipeline never depends on the LLM.
"""

from __future__ import annotations

import logging

from src.agents.llm_support import LLMBackedAgent, as_list

logger = logging.getLogger(__name__)

SYSTEM = (
    "You generate e-commerce search queries. Reply with ONLY a JSON array of "
    "5-10 short product search queries, most specific first. No commentary."
)


class QueryExpansionAgent(LLMBackedAgent):
    """Expands user prompt into multiple search query variations."""

    name = "query_expansion"
    role = "query_expansion"

    def __init__(self, llm=None):
        super().__init__(llm=llm, name=self.name, role=self.role)

    async def run(self, input_data: dict) -> dict:
        prompt = input_data.get("prompt", "")
        limit = int(input_data.get("max_queries", 8))
        queries = await self._expand_query(prompt, limit)
        return {
            "original_prompt": prompt,
            "expanded_queries": queries,
            "query_count": len(queries),
            "source": "llm" if self.llm is not None else "fallback",
        }

    async def _expand_query(self, prompt: str, limit: int = 8) -> list[str]:
        user = (
            f"User wants: {prompt}\n"
            "Produce marketplace search queries covering brand/model variants, "
            "condition keywords, and accessory-free core product terms."
        )
        parsed = await self._ask_json(SYSTEM, user, max_tokens=500)
        queries = as_list(parsed, limit)
        if len(queries) >= 3:
            logger.info(f"[{self.name}] LLM produced {len(queries)} queries")
            return queries
        if queries:
            # Partial LLM output is still useful; top it up with templates.
            return queries + self._fallback(prompt)[: max(0, limit - len(queries))]
        return self._fallback(prompt)[:limit]

    @staticmethod
    def _fallback(prompt: str) -> list[str]:
        """Deterministic variations, used when the LLM is unavailable."""
        base = " ".join(prompt.split())[:60] or "dji drone"
        terms = [t for t in base.split() if len(t) > 2][:4]
        stem = " ".join(terms) if terms else base
        out = [base, stem]
        for suffix in ("used", "new", "refurbished", "open box", "under 350", "bargain"):
            candidate = f"{stem} {suffix}"
            if candidate not in out:
                out.append(candidate)
        return out