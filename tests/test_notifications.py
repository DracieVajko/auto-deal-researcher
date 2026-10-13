import pytest

from src.notifications.manager import NotificationManager


@pytest.mark.asyncio
async def test_cooldown_dedups():
    mgr = NotificationManager(cooldown_seconds=3600)
    assert await mgr.notify("hi") is True
    assert await mgr.notify("hi") is False
