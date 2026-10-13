"""Query expansion agent."""

import logging

logger = logging.getLogger(__name__)


class QueryExpansionAgent:
    """Expands user prompt into multiple search query variations."""

    name = "query_expansion"
    role = "query_expansion"

    async def run(self, input_data: dict) -> dict:
        prompt = input_data.get("prompt", "")
        queries = await self._expand_query(prompt)
        return {
            "original_prompt": prompt,
            "expanded_queries": queries,
            "query_count": len(queries),
        }

    async def _expand_query(self, prompt: str) -> list[str]:
        """Generate multiple search query variations."""
        base = "dji drone under 350"
        return [
            f"{base} drone",
            f"{base} quadcopter",
            "dji mini 3 pro under 350",
            "dji air 2s used",
            "dji mavic 3 classic refurbished",
            "dji drone 3 axis gimbal obstacle avoidance",
        ]
