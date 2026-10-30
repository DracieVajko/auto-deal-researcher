"""System (OS) notification channel.

Uses Windows toast via PowerShell on Windows, osascript on macOS,
notify-send on Linux. Falls back to console print when unavailable.
"""

import logging
import platform
import subprocess

from src.notifications.base import Alert, NotificationChannel

logger = logging.getLogger(__name__)


class SystemChannel(NotificationChannel):
    """Desktop notification channel."""

    def __init__(self, name: str = "system", cooldown_minutes: int = 60):
        super().__init__(name, cooldown_minutes)

    async def send(self, alert: Alert) -> bool:
        title = alert.title
        message = alert.message
        system = platform.system()
        def _ps_escape(value: str) -> str:
            return str(value).replace("'", "''")

        def _sh_escape(value: str) -> str:
            return str(value).replace("\\", "\\\\").replace('"', '\\"')

        try:
            if system == "Windows":
                # PowerShell toast (BurntToast not required; use basic balloon)
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$n = New-Object System.Windows.Forms.NotifyIcon; "
                    "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                    "$n.Visible = $true; "
                    f"$n.ShowBalloonTip(5000, '{_ps_escape(title)}', '{_ps_escape(message)}', "
                    "[System.Windows.Forms.ToolTipIcon]::Info); "
                    "Start-Sleep -Seconds 6"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, timeout=15,
                )
                return True
            elif system == "Darwin":
                subprocess.run(
                    ["osascript", "-e", f'display notification "{_sh_escape(message)}" with title "{_sh_escape(title)}"'],
                    capture_output=True, timeout=10,
                )
                return True
            else:
                subprocess.run(
                    ["notify-send", title, message],
                    capture_output=True, timeout=10,
                )
                return True
        except Exception as exc:
            logger.debug("System notification failed: %s", exc)
            print(f"[{alert.severity.upper()}] {title}: {message}")
            return True