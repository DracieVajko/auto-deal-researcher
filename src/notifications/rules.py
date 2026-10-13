"""Alert rule definition."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.notifications.base import Alert


@dataclass
class AlertRule:
    """Rule for automatically generating alerts."""
    name: str
    condition: callable
    alert_template: dict
    cooldown_minutes: int = 60
    channels: list[str] = None
    _last_triggered: dict = field(default_factory=dict)

    def should_trigger(self, context: dict) -> bool:
        if not self.condition(context):
            return False
        key = self.name
        if key in self._last_triggered:
            elapsed = datetime.now() - self._last_triggered[key]
            if elapsed < timedelta(minutes=self.cooldown_minutes):
                return False
        return True

    def create_alert(self, context: dict) -> Alert:
        """Create alert from template with context."""
        alert = Alert(
            title=self.alert_template.get("title", "Alert"),
            message=self.alert_template.get("message", "Alert triggered"),
            severity=self.alert_template.get("severity", "info"),
            metadata={**self.alert_template.get("metadata", {}), **context},
        )
        self._last_triggered[self.name] = datetime.now()
        return alert

    def matches(self, deal: dict) -> bool:
        """Check if a deal matches this rule."""
        try:
            return bool(self.condition(deal))
        except Exception:
            return False
