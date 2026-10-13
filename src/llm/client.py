"""LLM Client with multi-provider fallback chain."""

import asyncio
import concurrent.futures
import logging

import requests

from src.searcher.adapters.base import Deal

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, config):
        self.config = config
        self.llm_config = config.llm

    # === Sync methods (backward compatibility) ===
    def generate_search_query(self, product_description):
        """Generate search queries using LLM (sync version)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        if loop and loop.is_running():
            # We're in an async context, run in thread pool
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self._generate_search_query_async(product_description))
                return future.result()
        else:
            return asyncio.run(self._generate_search_query_async(product_description))

    # === New async methods ===
    async def _chat(self, system: str, user: str, max_tokens: int = 100) -> str:
        """Unified chat method with fallback chain."""
        # Try local LLMs first
        for local in self.llm_config.local:
            try:
                logger.info(f"Trying local LLM: {local.type} at {local.endpoint}")
                return await self._call_local_llm_async(local, system, user, max_tokens)
            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                logger.warning(f"Local LLM ({local.type}) failed: {e}")

        # Try cloud APIs from new config
        for api in self.llm_config.api_fallback:
            api_key = self._get_api_key(api.api_key_env)
            if api_key:
                try:
                    logger.info(f"Trying cloud API: {api.provider} with model {api.model}")
                    return await self._call_cloud_llm_async(api.provider, api_key, api.model, system, user, max_tokens)
                except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                    logger.warning(f"Cloud API ({api.provider}) failed: {e}")
            else:
                logger.warning(f"Cloud API ({api.provider}) skipped: no API key in env {api.api_key_env}")

        # Legacy fallback with correct models per provider
        legacy_models = {
            "openrouter": "mistralai/mistral-7b-instruct",
            "gemini": "gemini-1.5-flash",
            "mistral": "mistral-small-latest",
        }
        for provider in ["openrouter", "gemini", "mistral"]:
            api_key = getattr(self.llm_config, provider, None)
            if api_key:
                model = legacy_models.get(provider, "mistralai/mistral-7b-instruct")
                try:
                    logger.info(f"Trying legacy {provider} with model {model}")
                    return await self._call_cloud_llm_async(provider, api_key, model, system, user, max_tokens)
                except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                    logger.warning(f"Legacy {provider} failed: {e}")

        logger.error("All LLM providers failed, falling back to prompt as search query")
        # Fallback: return the user prompt as search query
        return user

    async def _generate_search_query_async(self, prompt: str, broader: bool = False) -> str:
        system = "You are a search query optimizer for e-commerce sites. Output ONLY the search query string."
        user = f"User wants: {prompt}\nGenerate a concise search query for marketplace sites."
        if broader:
            user += " Make it broader to find more results."
        return await self._chat(system, user, max_tokens=100)

    async def refine_query(self, prompt: str, current_deals: list[Deal], round_num: int) -> str:
        """Generate query to find DIFFERENT items than already found."""
        titles = [d.title for d in current_deals[:10]]
        system = "Generate a search query to find DIFFERENT items than these already found."
        user = f"Original request: {prompt}\nAlready found: {titles}\nRound: {round_num}\nNew query:"
        return await self._chat(system, user, max_tokens=100)

    async def judge_results(self, prompt: str, deals: list[Deal]) -> dict:
        """Classify each deal as keep/discard. Return {'keep': [urls]}."""
        if not deals:
            return {"keep": []}
        
        keep_urls = []
        for i in range(0, len(deals), 10):
            batch = deals[i:i+10]
            items = "\n".join([f"- {d.title} | {d.price_eur}€ | {d.condition} | {d.site_name}" for d in batch])
            system = "You are a deal judge. For each item, reply KEEP or DISCARD only."
            user = f"User wants: {prompt}\nItems:\n{items}\nReply with KEEP/DISCARD per line:"
            response = await self._chat(system, user, max_tokens=200)
            for line, deal in zip(response.strip().splitlines(), batch, strict=False):
                if "KEEP" in line.upper():
                    keep_urls.append(deal.url)
        return {"keep": keep_urls}

    async def rank_results(self, prompt: str, deals: list[Deal], top_n: int) -> list[Deal]:
        """Rank deals by relevance to prompt, return top N."""
        if len(deals) <= top_n:
            return deals
        
        items = "\n".join([f"{i}. {d.title} | {d.price_eur}€ | {d.condition} | {d.site_name}" for i, d in enumerate(deals)])
        system = f"Rank these deals 1-{len(deals)} by relevance to user request. Output ONLY the ranked indices (e.g., '3,1,5,2,4')."
        user = f"User wants: {prompt}\nDeals:\n{items}"
        response = await self._chat(system, user, max_tokens=200)
        try:
            indices = [int(x.strip()) - 1 for x in response.split(",")]
            return [deals[i] for i in indices[:top_n] if 0 <= i < len(deals)]
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse LLM ranking, using input order: {e}")
            return deals[:top_n]

    # === Local LLM calls ===
    async def _call_local_llm_async(self, local_cfg, system: str, user: str, max_tokens: int) -> str:
        """Call local LLM (LM Studio / Ollama / llama.cpp) via OpenAI-compatible API."""
        endpoint = local_cfg.endpoint.rstrip("/")
        api_url = f"{endpoint}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": local_cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens
        }
        # Run sync request in thread pool with reduced timeout
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(api_url, headers=headers, json=payload, timeout=5))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    # === Cloud API calls ===
    async def _call_cloud_llm_async(self, provider: str, api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
        if provider == "openrouter":
            return await self._call_openrouter_async(api_key, model, system, user, max_tokens)
        elif provider == "gemini":
            return await self._call_gemini_async(api_key, model, system, user, max_tokens)
        elif provider == "mistral":
            return await self._call_mistral_async(api_key, model, system, user, max_tokens)
        else:
            msg = f"Unknown provider: {provider}"
            raise ValueError(msg)

    async def _call_openrouter_async(self, api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/DracieVajko/auto-deal-researcher",
            "X-Title": "Auto Deal Searcher"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(api_url, headers=headers, json=payload, timeout=5))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    async def _call_gemini_async(self, api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        # Gemini doesn't support system prompt separately, combine them
        payload = {
            "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": max_tokens
            }
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(api_url, headers=headers, json=payload, timeout=5))
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    async def _call_mistral_async(self, api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
        api_url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(api_url, headers=headers, json=payload, timeout=5))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def _get_api_key(self, env_var: str) -> str | None:
        """Get API key from environment variable."""
        import os
        return os.environ.get(env_var)