"""Configuration loader."""

from .models import AppConfig, SearchConfig, LLMConfig, OutputConfig, ScheduleConfig, BrowserConfig, StorageConfig
import yaml
import os


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file."""
    # Check if config file exists
    if not os.path.exists(config_path):
        # Return default configuration
        return AppConfig()

    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)

    return AppConfig(**config_data)