"""Configuration models for Auto Deal Searcher."""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum


class Condition(str, Enum):
    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"
    OPEN_BOX = "open_box"
    MARKETPLACE = "marketplace"
    ANY = "any"


class Category(str, Enum):
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
    categories: List[Category] = [Category.ANY]
    conditions: List[Condition] = [Condition.ANY]
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
    local: List[LLMLocalConfig] = []
    api_fallback: List[LLMAPIConfig] = []
    # Legacy fields for backward compatibility
    local_endpoint: str = "http://localhost:11434"
    openrouter: Optional[str] = None
    gemini: Optional[str] = None
    mistral: Optional[str] = None
    api_key: Optional[str] = None
    model_name: str = "llama3"


class OutputConfig(BaseModel):
    format: Literal["json", "markdown", "both"] = "both"
    directory: str = "./results"


class ScheduleTaskConfig(BaseModel):
    name: str
    prompt_file: str
    times: List[str]  # ["08:00", "20:00"]
    enabled: bool = True


class ScheduleConfig(BaseModel):
    tasks: List[ScheduleTaskConfig] = []


class BrowserConfig(BaseModel):
    cdp_endpoint: str = "http://localhost:9222"
    use_persistent_context: bool = True
    user_data_dir: str = "./browser_profile"


class StorageConfig(BaseModel):
    db_path: str = "./data/deals.db"


class SearchConfig(BaseModel):
    websites: List[WebsiteConfig] = []
    winners_count: int = 3
    max_rounds: int = 3
    retry_on_empty: bool = True
    prune_after_days: int = 30


class AppConfig(BaseModel):
    search: SearchConfig = SearchConfig()
    llm: LLMConfig = LLMConfig()
    output: OutputConfig = OutputConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    browser: BrowserConfig = BrowserConfig()
    storage: StorageConfig = StorageConfig()