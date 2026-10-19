"""VLM Client for Vision-Language Model interactions."""

from __future__ import annotations

import base64
import json
import logging
import re
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass
class SearchCriteria:
    """Search criteria from user prompt."""
    prompt: str
    category: str = "any"
    condition: str = "any"
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    keywords: list[str] = None
    exclusions: list[str] = None
    site_preferences: list[str] = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []
        if self.exclusions is None:
            self.exclusions = []


@dataclass
class ExtractedItem:
    """Extracted product listing from a page."""
    title: str
    price_eur: Optional[float]
    currency: str = "EUR"
    condition: str = "unknown"
    url: str = ""
    title_selector: str = ""
    price_selector: str = ""
    link_selector: str = ""
    image_url: str = ""
    seller_name: str = ""
    seller_type: str = "unknown"
    raw_data: dict = None

    def __post_init__(self):
        if self.raw_data is None:
            self.raw_data = {}


class CardClassification(BaseModel):
    """Classification of a card/listing on a page."""
    type: Literal["product", "sponsored", "ad", "irrelevant", "login_wall", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class Judgment(BaseModel):
    """LLM judgment on a deal."""
    decision: Literal["ACCEPT", "REJECT", "NEED_DETAIL", "UNCERTAIN"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    match_score: int = Field(ge=0, le=100)
    deal_quality: Literal["excellent", "good", "fair", "poor"]


class SearchCriteriaModel(BaseModel):
    """Pydantic model for search criteria serialization."""
    prompt: str
    category: str = "any"
    condition: str = "any"
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    keywords: list[str] = []
    exclusions: list[str] = []
    site_preferences: list[str] = []


class VLMClient:
    """Vision-Language Model client for page analysis."""

    def __init__(
        self,
        provider: str = "lmstudio",
        model: str = "qwen2.5-vl-7b",
        endpoint: str = "http://127.0.0.1:1234/v1",
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        # Optimization params
        reasoning_enabled: bool = True,
        reasoning_effort: str = "medium",
        reasoning_token_budget: int = 4096,
        context_window: int = 32768,
        total_token_budget: int = 128000,
        reasoning_token_budget_max: int = 8192,
        auto_context_sizing: bool = True,
    ):
        self.provider = provider
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.reasoning_enabled = reasoning_enabled
        self.reasoning_effort = reasoning_effort
        self.reasoning_token_budget = reasoning_token_budget
        self.context_window = context_window
        self.total_token_budget = total_token_budget
        self.reasoning_token_budget_max = reasoning_token_budget_max
        self.auto_context_sizing = auto_context_sizing
        self._client: Optional[httpx.AsyncClient] = None
        self._token_usage = {"prompt": 0, "completion": 0, "reasoning": 0}

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.endpoint,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _encode_image(self, image_bytes: bytes) -> str:
        """Encode image to base64."""
        return base64.b64encode(image_bytes).decode("utf-8")

    async def _chat_completion(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
        response_format: Optional[dict] = None,
        reasoning_effort: Optional[str] = None,
    ) -> dict:
        """Send chat completion request with optional reasoning control."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        
        # Add reasoning parameters if enabled
        if self.reasoning_enabled:
            reasoning_config = {
                "effort": self.reasoning_effort,
                "max_tokens": min(self.reasoning_token_budget, max_tokens // 2)
            }
            # Override with provided effort if specified
            if reasoning_effort:
                reasoning_config["effort"] = reasoning_effort
            payload["reasoning"] = reasoning_config
        
        # Track token budget
        estimated_prompt_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4
        if self._token_usage["prompt"] + estimated_prompt_tokens + max_tokens > self.total_token_budget:
            logger.warning(f"Token budget exceeded: {self._token_usage['prompt'] + estimated_prompt_tokens + max_tokens} > {self.total_token_budget}")

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        result = response.json()
        
        # Track token usage if available
        if "usage" in result:
            usage = result["usage"]
            self._token_usage["prompt"] += usage.get("prompt_tokens", 0)
            self._token_usage["completion"] += usage.get("completion_tokens", 0)
            self._token_usage["reasoning"] += usage.get("reasoning_tokens", 0)
        
        return response.json()

    def _encode_image(self, image_bytes: bytes) -> str:
        """Encode image to base64."""
        return base64.b64encode(image_bytes).decode("utf-8")

    def _build_extraction_prompt(self, criteria: "SearchCriteria") -> str:
        """Build prompt for listing extraction."""
        return f"""
You are an expert e-commerce data extractor. Analyze the page screenshot and HTML to extract product listings.

User criteria:
- Search query: {criteria.prompt}
- Category: {criteria.category}
- Condition: {criteria.condition}
- Max price: {criteria.max_price or 'unlimited'} EUR
- Keywords: {', '.join(criteria.keywords) if criteria.keywords else 'any'}
- Exclusions: {', '.join(criteria.exclusions) if criteria.exclusions else 'none'}

Return ONLY valid JSON matching this schema:
{{
  "items": [
    {{
      "title": "string",
      "price_eur": number_or_null,
      "condition": "new|used|refurbished|open_box|unknown",
      "url": "string",
      "title_selector": "css_selector_for_title",
      "price_selector": "css_selector_for_price",
      "link_selector": "css_selector_for_link",
      "image_url": "string_or_null",
      "seller_name": "string_or_null",
      "seller_type": "retailer|marketplace|classifieds|auction|unknown",
      "raw_data": {{}}
    }}
  ]
}}

Rules:
1. Only extract actual product listings, NOT ads, sponsored posts, banners, or navigation
2. Price must be in EUR (convert if needed)
3. Condition must be one of: new, used, refurbished, open_box, unknown
4. Selectors must be valid CSS selectors that uniquely identify the element
5. If price not found, use null
6. Extract max 50 items per page
7. Ignore sponsored/ads/banners - only real product listings
"""

    async def extract_listings(
        self,
        page_screenshot: bytes,
        page_html: str,
        criteria: "SearchCriteria",
        max_items: int = 50,
    ) -> list[dict]:
        """Extract product listings from page screenshot and HTML."""
        img_b64 = self._encode_image(page_screenshot)

        messages = [
            {
                "role": "system",
                "content": "You are an expert e-commerce data extractor. Extract product listings from marketplace pages using both visual and HTML information."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self._build_extraction_prompt(criteria)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{self._encode_image(page_screenshot)}"}
                    }
                ]
            }
        ]

        try:
            response = await self._chat_completion(
                messages=messages,
                max_tokens=4096,
                temperature=0.1,
            )
            content = response.json()["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                items = data.get("items", [])
                return items[:50]
            return []
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return []

    async def classify_card(
        self,
        card_screenshot: bytes,
        card_html: str = "",
    ) -> dict:
        """Classify a single card: product | sponsored | ad | irrelevant | login_wall"""
        img_b64 = self._encode_image(card_screenshot)

        messages = [
            {
                "role": "system",
                "content": "Classify this e-commerce card. Return ONLY JSON: {\"type\": \"product|sponsored|ad|irrelevant|login_wall\", \"confidence\": 0.0-1.0, \"reason\": \"...\"}"
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this e-commerce card. Is it a real product listing, sponsored ad, banner ad, irrelevant content, or login wall?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{self._encode_image(card_screenshot)}"}
                    }
                ]
            }
        ]

        messages = [
            {"role": "system", "content": "Classify e-commerce card. Return JSON only."},
            {"role": "user", "content": [
                {"type": "text", "text": "Classify this e-commerce card. Is it a real product listing, sponsored ad, banner ad, irrelevant content, or login wall?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{self._encode_image(card_screenshot)}"}}
            ]},
        ]

        try:
            response = await self._chat_completion(
                messages=messages,
                max_tokens=200,
                temperature=0.0,
            )
            content = response.json()["choices"][0]["message"]["content"]
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"type": "unknown", "confidence": 0.0, "reason": "parse failed"}
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return {"type": "unknown", "confidence": 0.0, "reason": str(e)} 