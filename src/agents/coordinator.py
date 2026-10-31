"""Coordinator agent - orchestrates Diamond Search layers with budgets."""

from __future__ import annotations

import asyncio
import logging
import uuid

from src.agents.base import AgentBase, AgentResult, AgentRole, MessageBus

logger = logging.getLogger(__name__)


def __extract_result(result):
    """Hoisted helper: unwrap an AgentResult/Exception/dict into a payload."""
    if isinstance(result, AgentResult):
        return result.payload if result.success else str(result.error)
    if isinstance(result, Exception):
        return str(result)
    if isinstance(result, dict):
        return result
    return result


class CoordinatorAgent(AgentBase[dict, dict]):
    """Meta-agent that orchestrates the Diamond Search pipeline."""

    def __init__(self, agents: list[AgentBase], config: dict = None):
        super().__init__("coordinator", AgentRole.COORDINATOR, config)
        self.agents = {agent.name: agent for agent in agents}
        self.agent_order = [a.name for a in agents]
        self.message_bus = MessageBus()

        # Budget tracker for LLM calls
        self.llm_call_budget = config.get("llm_call_budget", 50) if config else 50
        self.llm_token_budget = config.get("llm_token_budget", 100000) if config else 100000
        self.llm_calls_made = 0
        self.llm_tokens_used = 0

    def _check_budget(self, estimated_calls: int = 1, estimated_tokens: int = 1000) -> bool:
        """Check if we have budget for the operation."""
        if self.llm_calls_made + estimated_calls > self.llm_call_budget:
            logger.warning(f"LLM call budget exceeded: {self.llm_calls_made}/{self.llm_call_budget}")
            return False
        if self.llm_tokens_used + estimated_tokens > self.llm_token_budget:
            logger.warning(f"LLM token budget exceeded: {self.llm_tokens_used}/{self.llm_token_budget}")
            return False
        return True

    def _record_llm_usage(self, calls: int = 1, tokens: int = 1000):
        """Record LLM usage against budget."""
        self.llm_calls_made += calls
        self.llm_tokens_used += tokens

    async def execute(self, input_data: dict) -> AgentResult[dict]:
        """Execute the full Diamond Search pipeline.

        input_data may carry ``deals`` (already-scraped Deal dicts). When
        present they are forwarded to the expertise, price and synthesis
        layers; otherwise those layers run in intelligence-only mode.
        """
        prompt = input_data.get("prompt", "")
        max_rounds = self.config.get("max_rounds", 3)
        deals = input_data.get("deals") or []

        # Generate or use existing run_id for traceability
        run_id = input_data.get("run_id", str(uuid.uuid4()))
        logger.info(f"Starting Diamond Search pipeline [run_id={run_id}]")

        results = {}

        # Phase 1: Research Layer (parallel)
        logger.info(f"[run_id={run_id}] Starting Research Layer (parallel)")
        research_results = await self._run_research_layer(prompt, run_id)
        results["research"] = research_results

        # Phase 2: Expertise Layer (parallel)
        logger.info(f"[run_id={run_id}] Starting Expertise Layer (parallel)")
        expertise_results = await self._run_expertise_layer(
            prompt, research_results, run_id, deals
        )
        results["expertise"] = expertise_results

        # Phase 3: Price Layer (sequential)
        logger.info(f"[run_id={run_id}] Starting Price Layer (sequential)")
        scored = expertise_results.get("domain_expert", {}).get("evaluated_deals") or deals
        price_results = await self._run_price_layer(
            prompt, research_results, expertise_results, run_id, scored
        )
        results["price"] = price_results

        # Final synthesis
        final_result = await self._synthesize_results(prompt, results, run_id)

        return AgentResult(
            agent_name=self.name,
            success=True,
            payload=final_result,
            metadata={
                "run_id": run_id,
                "rounds": len(results),
                "agents_used": list(self.agents.keys()),
                "llm_calls": self.llm_calls_made,
                "llm_tokens": self.llm_tokens_used,
            }
        )

    async def _run_research_layer(self, prompt: str, run_id: str) -> dict:
        """Run research agents in parallel."""
        if not self._check_budget(estimated_calls=3, estimated_tokens=3000):
            logger.warning(f"[run_id={run_id}] Budget exceeded, skipping research layer")
            return {"error": "Budget exceeded, research skipped"}

        agents = [
            self.agents["query_expansion"],
            self.agents["site_selection"],
            self.agents["market_intel"],
        ]

        tasks = [agent.run({"prompt": prompt, "run_id": run_id}) for agent in agents if agent]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._record_llm_usage(calls=3, tokens=3000)

        def _extract_result(result):
            if isinstance(result, AgentResult):
                return result.payload if result.success else str(result.error)
            elif isinstance(result, Exception):
                return str(result)
            elif isinstance(result, dict):
                return result
            else:
                return str(result)

        return {
            agent.name: _extract_result(result)
            for agent, result in zip([self.agents["query_expansion"], self.agents["site_selection"], self.agents["market_intel"]], results)
            if agent
        }

    async def _run_expertise_layer(self, prompt: str, research_results: dict, run_id: str,
                                   deals: list | None = None) -> dict:
        """Run domain expert and latest tech agents."""
        if not self._check_budget(estimated_calls=2, estimated_tokens=4000):
            logger.warning(f"[run_id={run_id}] Budget exceeded, skipping expertise layer")
            return {"domain_expert": "Budget exceeded, skipped", "latest_tech": "Budget exceeded, skipped"}

        deals = deals or []
        tasks = [
            self.agents["domain_expert"].run({
                "prompt": prompt, "research": research_results,
                "run_id": run_id, "deals": deals,
            }),
            self.agents["latest_tech"].run({"prompt": prompt, "research": research_results, "run_id": run_id}),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._record_llm_usage(calls=2, tokens=4000)

        def _extract_result(result):
            if isinstance(result, AgentResult):
                return result.payload if result.success else str(result.error)
            elif isinstance(result, Exception):
                return str(result)
            elif isinstance(result, dict):
                return result
            else:
                return str(result)

        return {
            "domain_expert": _extract_result(results[0]),
            "latest_tech": _extract_result(results[1]),
        }

    async def _run_price_layer(self, prompt: str, research_results: dict, expertise_results: dict,
                                run_id: str, deals: list | None = None) -> dict:
        """Run price hunter agent."""
        if not self._check_budget(estimated_calls=2, estimated_tokens=5000):
            logger.warning(f"[run_id={run_id}] Budget exceeded, skipping price layer")
            return {"price_hunter": "Budget exceeded, skipped"}

        result = await self.agents["price_hunter"].run({
            "prompt": prompt,
            "research": research_results,
            "expertise": expertise_results,
            "run_id": run_id,
            "deals": deals or [],
        })
        self._record_llm_usage(calls=2, tokens=5000)

        def _extract_result(result):
            if isinstance(result, AgentResult):
                return result.payload if result.success else str(result.error)
            elif isinstance(result, Exception):
                return str(result)
            elif isinstance(result, dict):
                return result
            else:
                return str(result)

        return {"price_hunter": _extract_result(result)}

    async def _synthesize_results(self, prompt: str, all_results: dict, run_id: str) -> dict:
        """Synthesize final recommendation."""
        if not self._check_budget(estimated_calls=1, estimated_tokens=3000):
            logger.warning(f"[run_id={run_id}] Budget exceeded, skipping synthesis")
            return {"error": "Budget exceeded, synthesis skipped"}

        result = await self.agents["recommendation"].run({
            "prompt": prompt,
            "all_results": all_results,
            "run_id": run_id,
        })
        self._record_llm_usage(calls=1, tokens=3000)

        def _extract_result(result):
            if isinstance(result, AgentResult):
                return result.payload if result.success else str(result.error)
            elif isinstance(result, Exception):
                return str(result)
            elif isinstance(result, dict):
                return result
            else:
                return str(result)

        return _extract_result(result)
