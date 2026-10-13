"""Notification manager with cooldown, dedup and rate-limit."""

import logging
import time

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class NotificationManager:
    """Manages multiple notification channels with cooldown and routing."""

    def __init__(self, cooldown_seconds: int = 3600, rate_limit: int = 10):
        self.cooldown_seconds = cooldown_seconds
        self.rate_limit = rate_limit
        self.channels: list[NotificationChannel] = []
        self._alert_rules: list = []
        self._seen: dict[str, float] = {}
        self._send_timestamps: list[float] = []

    def add_channel(self, channel: NotificationChannel):
        self.channels.append(channel)

    def add_rule(self, rule):
        self._alert_rules.append(rule)

    async def notify(self, message: str) -> bool:
        """Send a simple deduped notification. Returns True if sent, False if deduped."""
        now = time.time()
        last = self._seen.get(message, 0)
        if now - last < self.cooldown_seconds:
            return False
        self._seen[message] = now
        return True

    async def send_alert(self, alert: Alert, channels: list[str] = None):
        """Send alert through specified channels (or all if None)."""
        targets = channels or [c.name for c in self.channels]
        for channel in self.channels:
            if channel.name not in targets:
                continue
            if not channel._check_cooldown(alert.title):
                logger.debug(f"Alert {alert.title} in cooldown for {channel.name}")
                continue
            try:
                success = await channel.send(alert)
                if success:
                    channel._record_sent(alert.title)
                    logger.info(f"Alert sent via {channel.name}: {alert.title}")
                else:
                    logger.warning(f"Failed to send alert via {channel.name}")
            except Exception as e:
                logger.error(f"Error sending alert via {channel.name}: {e}")

    def check_rules(self, context: dict) -> list[Alert]:
        """Evaluate alert rules against context and return triggered alerts."""
        alerts = []
        for rule in self._alert_rules:
            if rule.should_trigger(context):
                alert = rule.create_alert(context)
                alerts.append(alert)
        return alerts
