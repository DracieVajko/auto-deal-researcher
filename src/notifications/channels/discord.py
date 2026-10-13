"""Discord notification channel."""

import logging

import aiohttp

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class DiscordChannel(NotificationChannel):
    """Discord webhook channel with rich embeds."""

    def __init__(self, name: str, webhook_url: str, cooldown_minutes: int = 60):
        super().__init__(name, cooldown_minutes)
        self.webhook_url = webhook_url

    async def send(self, alert: Alert) -> bool:
        color_map = {"info": 0x3498DB, "warning": 0xF39C12, "critical": 0xE74C3C}
        embed = {
            "title": alert.title,
            "description": alert.message,
            "color": color_map.get(alert.severity, 0x3498DB),
            "fields": [
                {"name": "Severity", "value": alert.severity.capitalize(), "inline": True},
                {"name": "Source", "value": alert.source, "inline": True},
                {"name": "Time", "value": alert.timestamp, "inline": True},
            ],
            "footer": {"text": f"Auto Deal Searcher • {alert.source}"},
            "timestamp": alert.timestamp,
        }
        if alert.metadata:
            for key, value in alert.metadata.items():
                embed["fields"].append({"name": key, "value": str(value), "inline": True})
        payload = {"embeds": [embed]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status < 300:
                        return True
                    logger.warning(f"Discord webhook failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Discord webhook failed: {e}")
            return False
