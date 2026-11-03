"""Notification channel construction and agent lifecycle regressions."""

import asyncio

import pytest

from src.agents.base import AgentBase, AgentResult, AgentRole
from src.notifications.base import Alert, NotificationChannel
from src.notifications.channels.console import ConsoleChannel
from src.notifications.channels.webhook import WebhookChannel
from src.notifications.rules import AlertRule


def test_console_channel_has_a_default_name():
    channel = ConsoleChannel()
    assert isinstance(channel, NotificationChannel)
    assert channel.name == "console"


def test_webhook_channel_requires_a_url_but_accepts_optional_headers():
    channel = WebhookChannel("hooks", "https://example.com/hook")
    assert channel.url == "https://example.com/hook"
    assert channel.headers["Content-Type"] == "application/json"


def test_alert_and_rule_defaults_are_real_containers():
    alert = Alert("title", "message")
    rule = AlertRule(name="rule", condition=lambda context: True, alert_template={})
    assert alert.metadata == {}
    assert rule.channels == []


class SlowAgent(AgentBase):
    def __init__(self):
        super().__init__("slow", AgentRole.QUERY_EXPANSION)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, input_data):
        self.started.set()
        await self.release.wait()
        return AgentResult(agent_name=self.name, success=True)


@pytest.mark.asyncio
async def test_agent_is_running_during_execute():
    agent = SlowAgent()
    task = asyncio.create_task(agent.run({}))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)

    assert agent.is_running is True
    agent.release.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert agent.is_running is False
