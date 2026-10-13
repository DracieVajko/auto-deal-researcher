"""Webhook notification channel."""

import logging

import aiohttp

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class WebhookChannel(NotificationChannel):
    """HTTP webhook channel for custom integrations."""

    def __init__(self, name: str, url: str, cooldown_minutes: int = 60, headers: dict = None):
        super().__init__(name, cooldown_minutes)
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}

    async def send(self, alert: Alert) -> bool:
        payload = {
            "title": alert.title,
            "message": alert.message,
            "severity": alert.severity,
            "source": alert.source,
            "timestamp": alert.timestamp,
            "metadata": alert.metadata,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status < 300:
                        logger.info(f"Webhook {self.name} sent successfully")
                        return True
                    logger.warning(f"Webhook {self.name} failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Webhook {self.name} failed: {e}")
            return False
