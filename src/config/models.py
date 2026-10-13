"""Configuration models for Auto Deal Searcher."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class Condition(StrEnum):
    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"
    OPEN_BOX = "open_box"
    MARKETPLACE = "marketplace"
    ANY = "any"


class Category(StrEnum):
    ELECTRONICS = "electronics"
    APPLIANCES = "appliances"
    AUTO = "auto"
    GENERAL = "general"
    ANY = "any"


class WebsiteConfig(BaseModel):
    name: str
    base_url: str
    enabled: bool = True
    adapter_class: str  # matches ADAPTER_REGISTRY key
    categories: list[Category] = [Category.ANY]
    conditions: list[Condition] = [Condition.ANY]
    requires_login: bool = False
    extra_params: dict = {}


class LLMLocalConfig(BaseModel):
    type: Literal["lmstudio", "ollama", "llamacpp"]
    endpoint: str
    model: str = "auto"


class LLMAPIConfig(BaseModel):
    provider: Literal["openrouter", "gemini", "mistral"]
    api_key_env: str
    model: str


class LLMConfig(BaseModel):
    local: list[LLMLocalConfig] = []
    api_fallback: list[LLMAPIConfig] = []
    # Legacy fields for backward compatibility
    local_endpoint: str = "http://localhost:11434"
    openrouter: str | None = None
    gemini: str | None = None
    mistral: str | None = None
    api_key: str | None = None
    model_name: str = "llama3"


class NotificationChannelConfig(BaseModel):
    name: str = "console"
    type: Literal["console", "webhook", "discord", "email"] = "console"
    cooldown_seconds: int = 3600
    rate_limit: int = 10
    settings: dict = {}


class NotificationConfig(BaseModel):
    channels: list[NotificationChannelConfig] = []
    default_cooldown_seconds: int = 3600


class OutputConfig(BaseModel):
    format: Literal["json", "markdown", "both"] = "both"
    directory: str = "./results"


class ScheduleTaskConfig(BaseModel):
    name: str
    prompt_file: str
    times: list[str]  # ["08:00", "20:00"]
    enabled: bool = True


class ScheduleConfig(BaseModel):
    tasks: list[ScheduleTaskConfig] = []


class BrowserConfig(BaseModel):
    cdp_endpoint: str = "http://localhost:9222"
    use_persistent_context: bool = True
    user_data_dir: str = "./browser_profile"
    headless: bool = True  # Run headless by default (no admin prompts)
    slow_mo: int = 0  # Slow down operations by N ms (useful for debugging)


class StorageConfig(BaseModel):
    db_path: str = "./data/deals.db"


class DiamondSearchConfig(BaseModel):
    """Configuration for Diamond Search 7-agent pipeline."""
    enabled: bool = True
    max_rounds: int = 3
    research_parallel: bool = True
    expertise_parallel: bool = True
    price_sequential: bool = True
    llm_model_override: str | None = None
    confidence_threshold: float = 0.7
    llm_call_budget: int = 50
    llm_token_budget: int = 100000


class SearchConfig(BaseModel):
    websites: list[WebsiteConfig] = []
    winners_count: int = 3
    max_rounds: int = 3
    retry_on_empty: bool = True
    prune_after_days: int = 30
    diamond_search: DiamondSearchConfig = DiamondSearchConfig()


class AppConfig(BaseModel):
    search: SearchConfig = SearchConfig()
    llm: LLMConfig = LLMConfig()
    output: OutputConfig = OutputConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    browser: BrowserConfig = BrowserConfig()
    storage: StorageConfig = StorageConfig()
    notifications: NotificationConfig = NotificationConfig()