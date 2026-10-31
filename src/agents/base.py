"""Agent base classes and message passing infrastructure."""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class AgentRole(str, Enum):
    """Agent roles in the Diamond Search methodology."""
    QUERY_EXPANSION = "query_expansion"
    SITE_SELECTION = "site_selection"
    MARKET_INTEL = "market_intel"
    DOMAIN_EXPERT = "domain_expert"
    LATEST_TECH = "latest_tech"
    PRICE_HUNTER = "price_hunter"
    RECOMMENDATION = "recommendation"
    COORDINATOR = "coordinator"


class AgentStatus(str, Enum):
    """Agent lifecycle status."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentMessage(Generic[T]):
    """Message passed between agents."""
    sender: str
    recipient: str
    payload: T
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = ""


@dataclass
class AgentResult(Generic[R]):
    """Result from agent execution."""
    agent_name: str
    success: bool
    payload: Optional[R] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


class AgentBase(ABC, Generic[T, R]):
    """Base class for all agents in the Diamond Search pipeline."""

    def __init__(self, name: str, role: AgentRole, config: dict | None = None):
        self.name = name
        self.role = role
        self.config = config or {}
        self.status = AgentStatus.IDLE
        self._message_handlers: dict[str, Callable] = {}
        self._message_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def register_handler(self, message_type: str, handler: Callable[[AgentMessage], Any]):
        """Register a message handler for a specific message type."""
        self._message_handlers[message_type] = handler

    async def send_message(self, recipient: str, message_type: str, payload: Any, correlation_id: str = ""):
        """Send a message to another agent (via message bus)."""
        pass

    @abstractmethod
    async def execute(self, input_data: T) -> AgentResult[R]:
        """Execute the agent's main logic."""
        pass

    async def run(self, input_data: T) -> AgentResult[R]:
        """Execute the agent with error handling and timing."""
        self.status = AgentStatus.RUNNING
        try:
            result = await self.execute(input_data)
            result.completed_at = datetime.now(timezone.utc)
            self.status = AgentStatus.COMPLETED if result.success else AgentStatus.FAILED
            return result
        except Exception as e:
            logger.exception(f"Agent {self.name} failed")
            self.status = AgentStatus.FAILED
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
                completed_at=datetime.now(timezone.utc),
            )
        finally:
            self._running = False


class MessageBus:
    """Simple in-memory message bus for agent communication."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._message_history: list[AgentMessage] = []

    def subscribe(self, message_type: str, handler: Callable[[AgentMessage], Any]):
        self._subscribers[message_type].append(handler)

    async def publish(self, message: AgentMessage):
        self._message_history.append(message)
        for handler in self._subscribers.get(message.payload.__class__.__name__, []):
            await handler(message)

    def get_history(self, message_type: type | None = None) -> list[AgentMessage]:
        if message_type is not None:
            return [m for m in self._message_history if isinstance(m.payload, message_type)]
        return self._message_history.copy()
