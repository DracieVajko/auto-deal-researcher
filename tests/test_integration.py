def test_integration_pipeline_smoke():
    from src.agents.coordinator import CoordinatorAgent
    from src.notifications.manager import NotificationManager
    from src.searcher.adapters.base import Deal
    assert CoordinatorAgent is not None
    assert NotificationManager is not None
    assert Deal is not None
