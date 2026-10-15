"""Configuration loader."""

import os
import re
from pathlib import Path

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
    "resolve_env_placeholders",
]

# Matches ${VAR} and ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _load_dotenv() -> None:
    """Load .env into os.environ without overwriting already-set variables."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv stays optional
        return

    for candidate in (Path(".env"), Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


def resolve_env_placeholders(text: str, strict: bool = True) -> str:
    """Substitute ${VAR} / ${VAR:-default} placeholders from the environment.

    In strict mode a placeholder with no value and no default raises, so a
    missing secret fails loudly instead of silently resolving to "".
    """

    def _replace(match: re.Match) -> str:
        name = match.group("name")
        default = match.group(2)
        value = os.environ.get(name)
        if value is not None:
            return value
        if default is not None:
            return default
        if strict:
            msg = f"Missing environment variable '{name}' required by config"
            raise ValueError(msg)
        return ""

    return _ENV_PATTERN.sub(_replace, text)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file, resolving ${VAR} env placeholders."""
    _load_dotenv()

    # Check if config file exists
    if not os.path.exists(config_path):
        # Return default configuration
        return AppConfig()

    with open(config_path, encoding="utf-8") as f:
        raw = f.read()

    config_data = yaml.safe_load(resolve_env_placeholders(raw)) or {}

    return AppConfig(**config_data)