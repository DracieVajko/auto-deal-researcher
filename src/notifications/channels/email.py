"""Email notification channel via SMTP (stdlib only)."""

import logging
import os
import smtplib
from email.message import EmailMessage

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    """Send alerts via SMTP. Configured via env vars:

    ADS_EMAIL_SMTP_HOST, ADS_EMAIL_SMTP_PORT (default 587),
    ADS_EMAIL_FROM, ADS_EMAIL_TO, ADS_EMAIL_USER, ADS_EMAIL_PASSWORD.
    """

    def __init__(self, name: str = "email", cooldown_minutes: int = 60):
        super().__init__(name, cooldown_minutes)

    async def send(self, alert: Alert) -> bool:
        host = os.environ.get("ADS_EMAIL_SMTP_HOST")
        to_addr = os.environ.get("ADS_EMAIL_TO")
        from_addr = os.environ.get("ADS_EMAIL_FROM") or os.environ.get("ADS_EMAIL_USER")
        if not host or not to_addr or not from_addr:
            logger.debug("Email channel not configured (missing env vars)")
            return False
        port = int(os.environ.get("ADS_EMAIL_SMTP_PORT", "587"))
        user = os.environ.get("ADS_EMAIL_USER")
        password = os.environ.get("ADS_EMAIL_PASSWORD")
        msg = EmailMessage()
        msg["Subject"] = f"[AutoDealSearcher] {alert.title}"
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(f"{alert.message}\n\nSeverity: {alert.severity}\nSource: {alert.source}\nTime: {alert.timestamp}")
        try:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
            return True
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)
            return False