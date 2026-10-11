import pytest
from src.config.models import AppConfig
from src.config import load_config

def test_config_loading():
    """Test that configuration loads correctly"""
    config = load_config()
    assert isinstance(config, AppConfig)
    
def test_config_has_search():
    """Test that config has search section"""
    config = load_config()
    assert hasattr(config.search, 'websites')
    assert hasattr(config.search, 'llm')

if __name__ == "__main__":
    pytest.main([__file__])