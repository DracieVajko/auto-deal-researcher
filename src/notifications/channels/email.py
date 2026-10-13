"""Email notification channel."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    """Email notification channel via SMTP."""

    def __init__(
        self,
        name: str,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        to_emails: list[str],
        cooldown_minutes: int = 60,
        use_tls: bool = True,
    ):
        super().__init__(name, cooldown_minutes)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_emails = to_emails
        self.use_tls = use_tls

    async def send(self, alert: Alert) -> bool:
        try:
            msg = MIMEMultipart()
            msg["From"] = self.from_email
            msg["To"] = ", ".join(self.to_emails)
            msg["Subject"] = f"[{alert.severity.upper()}] {alert.title}"
            body = f"{alert.message}\n\n---\nSeverity: {alert.severity.upper()}\nSource: {alert.source}\nTime: {alert.timestamp}\n\nDetails:\n{alert.metadata}\n"
            msg.attach(MIMEText(body, "plain"))
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            logger.error(f"Email channel {self.name} failed: {e}")
            return False
