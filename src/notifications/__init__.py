"""Notifications package - re-exports for backward compatibility."""

from src.notifications.base import Alert, NotificationChannel
from src.notifications.channels.console import ConsoleChannel
from src.notifications.channels.discord import DiscordChannel
from src.notifications.channels.email import EmailChannel
from src.notifications.channels.system import SystemChannel
from src.notifications.channels.webhook import WebhookChannel
from src.notifications.manager import NotificationManager
from src.notifications.rules import AlertRule

__all__ = [
    "Alert",
    "NotificationChannel",
    "ConsoleChannel",
    "WebhookChannel",
    "DiscordChannel",
    "EmailChannel",
    "SystemChannel",
    "NotificationManager",
    "AlertRule",
]
