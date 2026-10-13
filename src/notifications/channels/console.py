"""Console notification channel."""

from src.notifications.base import Alert, NotificationChannel


class ConsoleChannel(NotificationChannel):
    """Console output channel - always available for debugging."""

    async def send(self, alert: Alert) -> bool:
        prefix = {
            "info": "ℹ️",
            "warning": "⚠️",
            "critical": "🚨",
        }.get(alert.severity, "📢")
        print(f"{prefix} [{alert.severity.upper()}] {alert.title}: {alert.message}")
        return True
