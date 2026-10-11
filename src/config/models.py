from pydantic import BaseModel
from typing import List, Optional

class WebsiteConfig(BaseModel):
    name: str
    url_pattern: str
    allowlisted: bool = True
    blocklisted: bool = False

class LLMConfig(BaseModel):
    local_endpoint: str = "http://localhost:11434"
    api_key: Optional[str] = None
    model_name: str = "llama3"

class SearchConfig(BaseModel):
    websites: List[WebsiteConfig]
    llm: LLMConfig
    output_format: str = "both"
    winners_count: int = 3

class AppConfig(BaseModel):
    search: SearchConfig