"""Configuration loader."""

import os

import yaml

from .models import (
    AppConfig,
    BrowserConfig,
    LLMConfig,
    OutputConfig,
    ScheduleConfig,
    SearchConfig,
    StorageConfig,
)

__all__ = [
    "AppConfig",
    "BrowserConfig",
    "LLMConfig",
    "OutputConfig",
    "ScheduleConfig",
    "SearchConfig",
    "StorageConfig",
    "load_config",
]


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file."""
    # Check if config file exists
    if not os.path.exists(config_path):
        # Return default configuration
        return AppConfig()

    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    return AppConfig(**config_data)