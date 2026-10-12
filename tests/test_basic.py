import pytest

from src.config import load_config
from src.config.models import AppConfig


def test_config_loading():
    """Test that configuration loads correctly"""
    config = load_config()
    assert isinstance(config, AppConfig)

def test_config_has_search():
    """Test that config has search section"""
    config = load_config()
    assert hasattr(config.search, 'websites')
    assert hasattr(config.search, 'winners_count')

def test_config_has_llm():
    """Test that config has LLM section at top level"""
    config = load_config()
    assert hasattr(config, 'llm')
    assert hasattr(config.llm, 'local')
    assert hasattr(config.llm, 'api_fallback')

def test_config_has_output():
    """Test that config has output section"""
    config = load_config()
    assert hasattr(config, 'output')
    assert hasattr(config.output, 'format')
    assert hasattr(config.output, 'directory')

def test_config_has_storage():
    """Test that config has storage section"""
    config = load_config()
    assert hasattr(config, 'storage')
    assert hasattr(config.storage, 'db_path')

def test_config_has_schedule():
    """Test that config has schedule section"""
    config = load_config()
    assert hasattr(config, 'schedule')
    assert hasattr(config.schedule, 'tasks')

def test_config_has_browser():
    """Test that config has browser section"""
    config = load_config()
    assert hasattr(config, 'browser')
    assert hasattr(config.browser, 'cdp_endpoint')

if __name__ == "__main__":
    pytest.main([__file__])