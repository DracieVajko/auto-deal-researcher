from src.config.models import AppConfig


def test_notification_config_defaults():
    cfg = AppConfig()
    assert cfg.notifications.default_cooldown_seconds == 3600
    assert cfg.search.diamond_search.llm_call_budget == 50
