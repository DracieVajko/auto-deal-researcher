"""Console notification channel."""

import logging

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class ConsoleChannel(NotificationChannel):
    """Console output channel - always available for debugging."""

    async def send(self, alert: Alert) -> bool:
        prefix = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
        }.get(alert.severity, "📢")
        logger.info(f"{prefix} [{alert.severity.upper()}] {alert.title}: {alert.message}")
        return True
