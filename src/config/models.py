"""Configuration models for Auto Deal Searcher."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


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
    HOME = "home"          # furniture, interior, DIY, garden
    HOBBY = "hobby"        # sport, outdoor, tools, models
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
    # Market the site belongs to (SK, CZ, DE, EU) and the currency it lists
    # prices in. Used to rank sites by the user's location and to convert
    # prices to EUR. Empty means "take it from the site registry".
    country: str = ""
    currency: str = ""


class LLMLocalConfig(BaseModel):
    type: Literal["lmstudio", "ollama", "llamacpp"]
    endpoint: str
    model: str = "auto"


class LLMAPIConfig(BaseModel):
    provider: Literal["openrouter", "gemini", "mistral"]
    api_key_env: str
    model: str


class LocalCoordinationConfig(BaseModel):
    enabled: bool = True
    policy: Literal["wait", "cloud", "never", "force"] = "wait"
    quiet_seconds: int = 300
    poll_seconds: int = 15
    max_wait_seconds: int = 0
    probe_busy: bool = False


class LLMConfig(BaseModel):
    local: list["LLMLocalConfig"] = []
    api_fallback: list["LLMAPIConfig"] = []
    # LLM optimization settings
    reasoning_enabled: bool = True
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    reasoning_token_budget: int = 4096  # Max tokens for reasoning
    context_window: int = 32768  # Max context window (model dependent)
    # Dynamic context sizing based on available RAM
    auto_context_sizing: bool = True
    # Token budget for the entire pipeline
    total_token_budget: int = 128000
    # Reasoning token budget within total budget
    reasoning_token_budget: int = 8192
    # LLM optimization settings
    llm_optimization: dict = {
        "reasoning_enabled": True,
        "reasoning_effort": "medium",
        "reasoning_token_budget": 4096,
        "context_window": 32768,
        "total_token_budget": 128000,
        "auto_context_sizing": True,
    }
    # Legacy fields
    local: list["LLMLocalConfig"] = []
    api_fallback: list["LLMAPIConfig"] = []
    local_coordination: "LocalCoordinationConfig" = None
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
    cdp_endpoint: str = "http://127.0.0.1:9222"
    browser_id: str | None = None
    browser_executable: str | None = None
    use_persistent_context: bool = True
    user_data_dir: str = "./browser_profile"
    separate_profiles: bool = True
    headless: bool = True  # Run headless by default (no admin prompts)
    slow_mo: int = 0  # Slow down operations by N ms (useful for debugging)
    # Reuse cookies/credentials between runs instead of a fresh profile.
    storage_state: str | None = None
    # Sites that need a manual login on first run (adapter id list).
    login_sites: list[str] = ["facebook"]


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
    default_filters: dict[str, str | float] = Field(default_factory=dict)
    winners_count: int = 3
    max_rounds: int = 3
    retry_on_empty: bool = True
    prune_after_days: int = 30
    # Where the user shops. Sites in this market rank first, neighbouring
    # markets second, the rest last.
    user_country: str = "SK"
    user_city: str = ""
    # Upper bound on how many shops are opened per search round.
    max_sites: int = 8
    # Static EUR rates for the currencies the sites list prices in.
    currency_rates: dict[str, float] = Field(default_factory=dict)
    diamond_search: DiamondSearchConfig = DiamondSearchConfig()


class AppConfig(BaseModel):
    search: SearchConfig = SearchConfig()
    llm: LLMConfig = LLMConfig()
    output: OutputConfig = OutputConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    browser: BrowserConfig = BrowserConfig()
    storage: StorageConfig = StorageConfig()
    notifications: NotificationConfig = NotificationConfig()


# Forward references resolution
LLMConfig.model_rebuild()
LLMLocalConfig.model_rebuild()
LLMAPIConfig.model_rebuild()
LocalCoordinationConfig.model_rebuild()
WebsiteConfig.model_rebuild()
DiamondSearchConfig.model_rebuild()
SearchConfig.model_rebuild()
AppConfig.model_rebuild()