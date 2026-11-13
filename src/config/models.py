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
    # Maximum number of models that may be loaded simultaneously (including
    # ours). Default 1: if another model is already resident we wait.
    max_concurrent_models: int = 1
    # How long (seconds) to wait for a slot before falling back to cloud.
    # Default 3600 (1 hour).
    wait_timeout_seconds: int = 3600
    # Poll interval (seconds) while waiting for a slot.
    wait_poll_seconds: int = 120
    # Preload the model at startup so the first request is fast.
    preload: bool = False
    # Unload the model after the job finishes to free resources.
    unload_after_job: bool = True


class LLMConfig(BaseModel):
    local: list["LLMLocalConfig"] = []
    api_fallback: list["LLMAPIConfig"] = []
    # LLM optimization settings
    reasoning_enabled: bool = True
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    reasoning_token_budget: int = 4096  # Max tokens for reasoning
    context_window: int = 32768  # Max context window (model dependent)
    auto_context_sizing: bool = True
    total_token_budget: int = 128000
    local_coordination: "LocalCoordinationConfig | None" = None


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
    # Reports are written under reports/<slug>/ so each search type has its
    # own folder. Change to "./results" to keep the legacy flat layout.
    directory: str = "./reports"
    # How many historical runs to keep per search type. Older run files are
    # pruned automatically; the deals themselves live in data/deals.db.
    keep_runs: int = 5
    # Force a product domain (bike, computer, phone, car, furniture, generic).
    # Empty means auto-detect from the listing text.
    domain: str = ""


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
    # Disable the Chrome sandbox. Required in many container/CI environments;
    # opt-in only because it weakens process isolation.
    no_sandbox: bool = True
    # Reuse cookies/credentials between runs instead of a fresh profile.
    storage_state: str | None = None
    # Accept self-signed certificates. Off by default; a MITM proxy that
    # re-signs TLS needs this opt-in.
    ignore_https_errors: bool = False
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


class SpecsResearchConfig(BaseModel):
    """Configuration for item specs research (replacement finder foundation)."""
    enabled: bool = True
    default_category: str = "auto"
    max_sources: int = 5
    max_review_snippets: int = 8


class SearchConfig(BaseModel):
    websites: list[WebsiteConfig] = []
    default_filters: dict[str, str | float] = Field(default_factory=dict)
    winners_count: int = 3
    max_rounds: int = 3
    retry_on_empty: bool = True
    prune_after_days: int = 30
    user_country: str = "SK"
    user_city: str = ""
    max_sites: int = 0
    concurrency: int = 3
    sources: bool = True
    source_count: int = 5
    default_currency: str = ""
    currency_rates: dict[str, float] = Field(default_factory=dict)
    enrich_limit: int = 20
    diamond_search: DiamondSearchConfig = DiamondSearchConfig()
    specs_research: SpecsResearchConfig = SpecsResearchConfig()
    pages_per_site: int = 3
    cache_ttl_seconds: int = 3600


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