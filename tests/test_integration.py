"""Real storage + notification seam, not an import-only smoke test."""

import pytest

from src.notifications.base import Alert, NotificationChannel
from src.notifications.manager import NotificationManager
from src.searcher.adapters.base import Deal
from src.storage.manager import StorageManager


class FakeChannel(NotificationChannel):
    def __init__(self):
        super().__init__("fake", cooldown_minutes=0)
        self.alerts: list[Alert] = []

    async def send(self, alert: Alert) -> bool:
        self.alerts.append(alert)
        return True


@pytest.mark.asyncio
async def test_storage_and_notification_seam(tmp_path):
    storage = StorageManager(str(tmp_path / "deals.db"))
    storage.save_deal(
        Deal(
            url="https://example.test/1",
            title="Test deal",
            price_eur=10.0,
            site_name="example",
        )
    )
    assert storage.get_deal("https://example.test/1") is not None

    channel = FakeChannel()
    manager = NotificationManager(cooldown_seconds=0)
    manager.add_channel(channel)
    await manager.send_alert(Alert("Deal found", "10 EUR"))

    assert [alert.title for alert in channel.alerts] == ["Deal found"]
