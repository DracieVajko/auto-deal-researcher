"""LLM Client with multi-provider fallback chain."""

import asyncio
import concurrent.futures
import logging
import os
import re
import time

import requests

from src.searcher.adapters.base import Deal

logger = logging.getLogger(__name__)

# Adaptive HTTP timeouts (seconds) per provider class.
#
# Local models (LM Studio / Ollama / llama.cpp) need a long budget: the model
# may not be loaded yet and a 30B load alone can take minutes on RAM-only
# hardware, and slow models generate at ~1-2 tok/s. Cloud APIs answer quickly,
# so they get a shorter budget to fail over fast.
LOCAL_TIMEOUT = float(os.environ.get("ADS_LOCAL_LLM_TIMEOUT", "900"))
CLOUD_TIMEOUT = float(os.environ.get("ADS_CLOUD_LLM_TIMEOUT", "120"))


def _timeout_from_env(name: str = "ADS_LOCAL_LLM_TIMEOUT", default: float = LOCAL_TIMEOUT) -> float:
    """Read a timeout override from the environment, ignoring invalid values."""
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


class LocalCircuitBreaker:
    """Skip a local endpoint for a while after it fails.

    Without this, an unreachable or hung LM Studio is retried on *every*
    LLM call and each one burns the full local timeout, so a run that should
    take seconds stalls for many minutes.
    """

    def __init__(self, cooldown: float = 300.0, threshold: int = 2):
        self.cooldown = cooldown
        self.threshold = threshold
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        until = self._open_until.get(key, 0.0)
        if until and time.time() < until:
            return True
        if until:
            # cooldown elapsed: half-open, allow a probe
            self._open_until.pop(key, None)
            self._failures.pop(key, None)
        return False

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._open_until.pop(key, None)

    def record_failure(self, key: str) -> None:
        n = self._failures.get(key, 0) + 1
        self._failures[key] = n
        if n >= self.threshold:
            self._open_until[key] = time.time() + self.cooldown

    def reset(self) -> None:
        self._failures.clear()
        self._open_until.clear()


def _post_with_retry(url: str, *, headers: dict, json_body: dict, timeout: float,
                     attempts: int = 3) -> requests.Response:
    """POST, retrying transient 5xx / 429 responses with a short backoff.

    Cloud providers intermittently answer 503 (model overloaded) or 429
    (rate limited). Both clear on their own, so retrying avoids needlessly
    failing over to another provider. Client errors (4xx) are not retried.
    """
    last: requests.Response | None = None
    for attempt in range(attempts):
        last = requests.post(url, headers=headers, json=json_body, timeout=timeout)
        if last.status_code < 500 and last.status_code != 429:
            return last
        if attempt < attempts - 1:
            logger.info(f"Transient {last.status_code} from {url}; retrying")
            time.sleep(2 * (attempt + 1))
    return last


def _content_from(payload: dict) -> str:
    """Extract assistant text from an OpenAI-shaped response.

    Reasoning models may return content=None, or place the answer under
    'reasoning' / 'reasoning_content'. The previous inline
    ``...["content"].strip()`` raised AttributeError in those cases, and
    AttributeError was not caught by the fallback chain, so one such response
    aborted the entire provider loop.
    """
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    for key in ("content", "reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


class LLMClient:
    def __init__(self, config):
        self.config = config
        self.llm_config = config.llm
        self._breaker = LocalCircuitBreaker(
            cooldown=float(os.environ.get("ADS_LOCAL_BREAKER_COOLDOWN", "300")),
            threshold=int(os.environ.get("ADS_LOCAL_BREAKER_THRESHOLD", "2")),
        )

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

    # === Public API used by agents ===
    async def chat(self, system: str, user: str, max_tokens: int = 400) -> str:
        """Public single-turn chat across the whole fallback chain.

        Returns the raw user text as the last resort so callers always get a
        usable string instead of an exception.
        """
        return await self._chat(system, user, max_tokens)

    async def chat_json(self, system: str, user: str, max_tokens: int = 400):
        """Chat and parse a JSON object/list from the reply."""
        raw = await self._chat(system, user, max_tokens)
        from src.agents.llm_support import extract_json

        return extract_json(raw)

    # === New async methods ===
    async def _chat(self, system: str, user: str, max_tokens: int = 100) -> str:
        """Unified chat method with fallback chain."""
        # Try local LLMs first
        for local in self.llm_config.local:
            key = f"{local.type}:{local.endpoint}"
            if self._breaker.is_open(key):
                logger.info(f"Skipping local LLM {local.type} (circuit open)")
                continue
            try:
                logger.info(f"Trying local LLM: {local.type} at {local.endpoint}")
                reply = await self._call_local_llm_async(local, system, user, max_tokens)
                if reply.strip():
                    self._breaker.record_success(key)
                    return reply
                logger.warning(f"Local LLM ({local.type}) returned an empty response")
                self._breaker.record_failure(key)
            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                logger.warning(f"Local LLM ({local.type}) failed: {e}")
                self._breaker.record_failure(key)

        # Try cloud APIs from new config
        for api in self.llm_config.api_fallback:
            api_key = self._get_api_key(api.api_key_env)
            if api_key:
                try:
                    logger.info(f"Trying cloud API: {api.provider} with model {api.model}")
                    reply = await self._call_cloud_llm_async(
                        api.provider, api_key, api.model, system, user, max_tokens
                    )
                    if reply.strip():
                        return reply
                    # An empty body is a failure; fall through to the next provider.
                    logger.warning(f"Cloud API ({api.provider}) returned an empty response")
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
                    reply = await self._call_cloud_llm_async(
                        provider, api_key, model, system, user, max_tokens
                    )
                    if reply.strip():
                        return reply
                    logger.warning(f"Legacy {provider} returned an empty response")
                except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                    logger.warning(f"Legacy {provider} failed: {e}")

        logger.error("All LLM providers failed, falling back to prompt as search query")
        # Fallback: return the user prompt as search query
        return user

    @staticmethod
    def _clean_query(raw: str, fallback: str = "", max_words: int = 12) -> str:
        """Turn an LLM reply into a single usable marketplace search query.

        Small instruct models often answer with prose ("Here's a refined
        search query: ... *\\"a\\" OR \\"b\\" OR \\"c\\"") or a chain of
        alternatives. Fed to a site search that becomes a 300+ character URL
        that matches nothing, which is why runs intermittently returned zero
        deals. The first quoted phrase wins; otherwise strip the preamble,
        take the first sentence and cap the length.
        """
        if not raw:
            return fallback
        text = raw.strip()

        quoted = re.findall(r'"([^"\n]{2,60})"', text)
        if quoted:
            return quoted[0].strip()

        text = re.sub(r"\*{1,3}|`", "", text)
        text = re.sub(
            r"(?is)^(here(?: is|'s| is)?[^:\n]*|sure[^:\n]*|certainly[^:\n]*):\s*",
            "",
            text,
        ).strip()
        line = next((ln for ln in text.splitlines() if ln.strip()), "")
        line = line.strip(" -*:.\t")
        line = re.split(r"(?<=[.!?])\s", line)[0].strip(" -*:.")
        words = line.split()[:max_words]
        cleaned = " ".join(words).strip(" -*:.")
        return cleaned or fallback

    async def _generate_search_query_async(self, prompt: str, broader: bool = False) -> str:
        system = "You are a search query optimizer for e-commerce sites. Output ONLY the search query string."
        user = f"User wants: {prompt}\nGenerate a concise search query for marketplace sites."
        if broader:
            user += " Make it broader to find more results."
        raw = await self._chat(system, user, max_tokens=100)
        return self._clean_query(raw, fallback=prompt)

    async def refine_query(self, prompt: str, current_deals: list[Deal], round_num: int) -> str:
        """Generate query to find DIFFERENT items than already found."""
        titles = [d.title for d in current_deals[:10]]
        system = "Generate a search query to find DIFFERENT items than these already found."
        user = f"Original request: {prompt}\nAlready found: {titles}\nRound: {round_num}\nNew query:"
        raw = await self._chat(system, user, max_tokens=100)
        return self._clean_query(raw, fallback=prompt)

    async def judge_results(self, prompt: str, deals: list[Deal]) -> dict:
        """Classify each deal as keep/discard. Return {'keep': [urls]}.

        Small models often answer with prose or fewer lines than the batch,
        so zero KEEP verdicts usually means the reply was unreadable rather
        than that every item was bad. In that case the original deals are
        kept instead of returning nothing, which is what made whole runs
        come back empty.
        """
        if not deals:
            return {"keep": []}

        keep_urls: list[str] = []
        parsed_lines = 0

        for i in range(0, len(deals), 10):
            batch = deals[i : i + 10]
            items = "\n".join(
                [f"- {d.title} | {d.price_eur} EUR | {d.condition} | {d.site_name}" for d in batch]
            )
            system = (
                "You are a deal judge. For each item reply with exactly one line "
                "containing KEEP or DISCARD and nothing else. No commentary."
            )
            user = f"User wants: {prompt}\nItems:\n{items}\nReply with KEEP/DISCARD per line:"
            response = await self._chat(system, user, max_tokens=200)

            verdicts = re.findall(r"\b(KEEP|DISCARD)\b", response or "", re.IGNORECASE)
            if verdicts:
                parsed_lines += len(verdicts)
                for verdict, deal in zip(verdicts, batch, strict=False):
                    if verdict.upper() == "KEEP":
                        keep_urls.append(deal.url)

        if not keep_urls and parsed_lines == 0:
            logger.warning(
                "Deal judge returned no parseable verdicts; keeping all %d deals", len(deals)
            )
            return {"keep": [d.url for d in deals]}

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
        # Local inference may need a long prefill/load window (see LOCAL_TIMEOUT).
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=LOCAL_TIMEOUT))
        response.raise_for_status()
        return _content_from(response.json())

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
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=CLOUD_TIMEOUT))
        response.raise_for_status()
        return _content_from(response.json())

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
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=CLOUD_TIMEOUT))
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
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=CLOUD_TIMEOUT))
        response.raise_for_status()
        return _content_from(response.json())

    def _get_api_key(self, env_var: str) -> str | None:
        """Get API key from environment variable."""
        return os.environ.get(env_var)