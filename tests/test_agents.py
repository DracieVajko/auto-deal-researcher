def test_agent_imports():
    from src.agents.base import AgentBase, MessageBus
    from src.agents.coordinator import CoordinatorAgent
    assert CoordinatorAgent is not None
