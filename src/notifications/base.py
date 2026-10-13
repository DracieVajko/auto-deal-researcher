"""Notification base types."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """Alert to be sent through notification channels."""
    title: str
    message: str
    severity: str = "info"
    source: str = "auto-deal-searcher"
    timestamp: str = ""
    metadata: dict = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if self.metadata is None:
            self.metadata = {}


class NotificationChannel(ABC):
    """Abstract base class for notification channels."""

    def __init__(self, name: str, cooldown_minutes: int = 60):
        self.name = name
        self.cooldown_minutes = cooldown_minutes
        self._last_sent: dict[str, datetime] = {}

    @abstractmethod
    async def send(self, alert: Alert) -> bool:
        """Send alert through this channel. Returns True if sent successfully."""
        pass

    def _check_cooldown(self, alert_key: str) -> bool:
        """Check if alert is in cooldown period."""
        if alert_key not in self._last_sent:
            return True
        elapsed = datetime.now() - self._last_sent[alert_key]
        return elapsed >= timedelta(minutes=self.cooldown_minutes)

    def _record_sent(self, alert_key: str):
        self._last_sent[alert_key] = datetime.now()
