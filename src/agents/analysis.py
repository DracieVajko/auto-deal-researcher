"""Legacy shim - imports from new package locations."""

from src.agents.base import AgentRole
from src.agents.expertise.domain_expert import DomainExpertAgent
from src.agents.expertise.latest_tech_tracker import LatestTechTrackerAgent
from src.agents.price.price_hunter import PriceHunterAgent

__all__ = ["DomainExpertAgent", "LatestTechTrackerAgent", "PriceHunterAgent"]
