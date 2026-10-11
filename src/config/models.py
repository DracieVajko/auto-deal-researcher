from pydantic import BaseModel
from typing import List, Optional

class WebsiteConfig(BaseModel):
    name: str
    url_pattern: str
    allowlisted: bool = True
    blocklisted: bool = False

class LLMConfig(BaseModel):
    # Local LLM endpoint (Ollama or LM Studio)
    local_endpoint: str = "http://localhost:11434"
    # Cloud API keys (optional)
    openrouter: Optional[str] = None
    gemini: Optional[str] = None
    mistral: Optional[str] = None
    # Legacy single api_key field for backward compatibility
    api_key: Optional[str] = None
    model_name: str = "llama3"

class SearchConfig(BaseModel):
    websites: List[WebsiteConfig]
    llm: LLMConfig
    output_format: str = "both"
    winners_count: int = 3

class AppConfig(BaseModel):
    search: SearchConfig