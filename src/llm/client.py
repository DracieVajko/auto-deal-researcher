"""LLM Client with multi-provider fallback chain."""

import asyncio
import concurrent.futures
import logging
import os
import re
import time

import requests

from src.llm.local_coordinator import LocalModelCoordinator
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
        self._apply_env_overrides()
        self._breaker = LocalCircuitBreaker(
            cooldown=float(os.environ.get("ADS_LOCAL_BREAKER_COOLDOWN", "300")),
            threshold=int(os.environ.get("ADS_LOCAL_BREAKER_THRESHOLD", "2")),
        )
        self._coordinator = self._build_coordinator()

    def _apply_env_overrides(self) -> None:
        """Environment wins over config.yaml.

        LMSTUDIO_ENDPOINT / ADS_OLLAMA_ENDPOINT let a deployment move the
        local endpoint without editing config.yaml. Only the type is matched,
        so adding a provider needs no new flag.
        """
        mapping = {
            "lmstudio": "LMSTUDIO_ENDPOINT",
            "ollama": "ADS_OLLAMA_ENDPOINT",
            "llamacpp": "ADS_LLAMACPP_ENDPOINT",
        }
        for local in self.llm_config.local:
            var = mapping.get(local.type)
            if not var:
                continue
            override = (os.environ.get(var) or "").strip()
            if override:
                logger.info("Local LLM endpoint overridden from %s: %s", var, override)
                local.endpoint = override

    def _build_coordinator(self):
        """Create the local-backend coordinator from config (or env overrides)."""
        policy = os.environ.get("ADS_LOCAL_POLICY")
        coord = getattr(self.llm_config, "local_coordination", None)
        if policy:
            policy = policy.strip().lower()
        elif coord is None:
            # No config, but env var is set - use env policy
            if not policy:
                return None
            policy = policy.strip().lower()
        elif not coord.enabled:
            policy = "never"
        else:
            policy = coord.policy
        try:
            return LocalModelCoordinator(
                policy=policy,
                quiet_seconds=int(os.environ.get("ADS_LOCAL_QUIET_SECONDS", coord.quiet_seconds if coord else 300)),
                poll_seconds=int(os.environ.get("ADS_LOCAL_POLL_SECONDS", coord.poll_seconds if coord else 15)),
                max_wait_seconds=int(os.environ.get("ADS_LOCAL_MAX_WAIT", coord.max_wait_seconds if coord else 0)),
                probe_busy=coord.probe_busy if coord else False,
            )
        except ValueError as e:
            logger.error("Invalid local coordination policy %r: %s; defaulting to 'never'", policy, e)
            return LocalModelCoordinator(policy="never")

    def describe_local_state(self) -> str:
        """Human-readable state of both local backends (read-only)."""
        return self._coordinator.describe() if self._coordinator else "not configured"

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
    async def _chat(self, system: str, user: str, max_tokens: int = 100,
                    temperature: float = 0.3) -> str:
        """Unified chat method with fallback chain."""
        # Try local LLMs first
        # Try local LLMs first, but only when the backend is free.
        our_models = {getattr(l, "model", "") for l in self.llm_config.local}
        if self._coordinator is not None:
            safe, reason = self._coordinator.acquire(our_models)
            if not safe:
                logger.info("Skipping local LLMs: %s", reason)
                self.llm_config.local = []

        for local in self.llm_config.local:
            key = f"{local.type}:{local.endpoint}"
            if self._breaker.is_open(key):
                logger.info(f"Skipping local LLM {local.type} (circuit open)")
                continue
            try:
                logger.info(f"Trying local LLM: {local.type} at {local.endpoint}")
                reply = await self._call_local_llm_async(
                        local, system, user, max_tokens, temperature
                    )
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
                        api.provider, api_key, api.model, system, user,
                        max_tokens, temperature
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
                        provider, api_key, model, system, user, max_tokens, temperature
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
    def _clean_query(raw: str, fallback: str = "", max_words: int = 6) -> str:
        """Turn an LLM reply into a single usable marketplace search query.

        Small instruct models answer with prose, an OR-chain of alternatives,
        or one long descriptive sentence. Fed to a site search that becomes a
        URL nobody's catalogue matches, which is why runs returned zero deals.
        The first quoted phrase wins; if it is longer than ``max_words`` the
        filler words are dropped so "mini PC or barebone new/used with
        Thunderbolt/OCuLink, DDR5 RAM 32GB/64GB, AMD Ryzen" becomes
        "mini PC barebone Thunderbolt OCuLink DDR5".
        """
        if not raw:
            return fallback
        text = raw.strip()

        quoted = re.findall(r'"([^"\n]{2,160})"', text)
        if quoted:
            candidate = quoted[0].strip()
        else:
            text = re.sub(r"\*{1,3}|`", "", text)
            text = re.sub(
                r"(?is)^(here(?: is|'s| is)?[^:\n]*|sure[^:\n]*|certainly[^:\n]*):\s*",
                "",
                text,
            ).strip()
            line = next((ln for ln in text.splitlines() if ln.strip()), "")
            line = line.strip(" -*:.\t")
            line = re.split(r"(?<=[.!?])\s", line)[0].strip(" -*:.")
            candidate = line

        words = candidate.split()
        if len(words) <= max_words:
            return candidate.strip(" -*:.,") or fallback

        trimmed = LLMClient._trim_terms(candidate, max_words)
        return trimmed or " ".join(words[:max_words]).strip(" -*:.,") or fallback

    # Filler words that add no value to a marketplace search.
    _QUERY_STOPWORDS = frozenset({
        "a", "an", "and", "or", "the", "with", "without", "for", "of", "to",
        "in", "on", "by", "at", "from", "as", "is", "are", "be", "been",
        "new", "used", "refurbished", "open", "box", "any", "all", "either",
        "preferably", "prefer", "preferred", "good", "better", "best", "great",
        "least", "less", "than", "more", "most", "about", "around",
        "must", "should", "would", "could", "can", "have", "has", "need",
        "needs", "want", "wants", "looking", "search", "find", "product",
        "products", "item", "items", "something", "like", "such", "including",
        "include", "also", "both", "plus", "very", "really", "please", "that",
        "this", "these", "those", "it", "its", "their", "your", "my",
    })

    @staticmethod
    def _trim_terms(text: str, max_words: int) -> str:
        """Keep the most searchable tokens, dropping filler words.

        Splits on slashes too, so "new/used" and "Thunderbolt/OCuLink"
        become separate tokens instead of one unusable compound.
        """
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+._-]*", text)
        kept = [
            t.strip("+._-")
            for t in tokens
            if t.lower() not in LLMClient._QUERY_STOPWORDS and len(t) > 1
        ]
        kept = [t for t in kept if len(t) > 1]
        return " ".join(kept[:max_words])

    @staticmethod
    def keyword_query(prompt: str, max_words: int = 5) -> str:
        """Deterministic short query derived from the prompt.

        Used when the LLM's query returns nothing, so a run does not depend
        on one model's phrasing.
        """
        return LLMClient._trim_terms(prompt, max_words)

    @staticmethod
    def _clean_slug(raw: str) -> str:
        """Reduce an LLM reply to a safe kebab-case file-name slug."""
        text = (raw or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-")
        words = [w for w in text.split("-") if w][:4]
        return "-".join(words)[:48].strip("-")

    async def _filename_slug_async(self, prompt: str) -> str:
        system = (
            "Name this deal search in 2-4 kebab-case words. Output only the "
            "slug: lowercase letters, digits and hyphens. Examples: "
            "mini-pc-ddr5, dji-drone-350, used-laptop-16gb."
        )
        user = f"Search request: {prompt}\nSlug:"
        raw = await self._chat(system, user, max_tokens=20, temperature=0.0)
        return self._clean_slug(raw)

    def _generate_filename_slug_sync(self, prompt: str) -> str:
        """Synchronous wrapper used by ResultProcessor (naming must not block)."""

        def _run() -> str:
            return asyncio.run(self._filename_slug_async(prompt))

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(_run).result()
        return _run()

    async def _generate_search_query_async(self, prompt: str, broader: bool = False) -> str:
        system = (
            "You convert a product request into a SHORT marketplace search query. "
            "Reply with 2-5 plain words only, for example 'mini pc ryzen' or "
            "'dji drone 350'. No quotes, no punctuation, no lists, no explanation."
        )
        user = f"Request: {prompt}\nShort search query:"
        if broader:
            user += " Use only 1-3 generic words."
        raw = await self._chat(system, user, max_tokens=40)
        return self._clean_query(raw, fallback=self.keyword_query(prompt))

    async def refine_query(self, prompt: str, current_deals: list[Deal], round_num: int) -> str:
        """Generate query to find DIFFERENT items than already found."""
        titles = [d.title for d in current_deals[:10]]
        system = (
            "Write a SHORT marketplace search query (2-5 plain words) for items "
            "different from those already found. No quotes, no punctuation."
        )
        user = f"Original request: {prompt}\nAlready found: {titles}\nNew query:"
        raw = await self._chat(system, user, max_tokens=40)
        return self._clean_query(raw, fallback=self.keyword_query(prompt))

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
                "You are a strict product-matching judge. Check requirements in this order:\n"
                "1. PRODUCT TYPE first. If the listing is not the product the user asked "
                "for (a full-size desktop, a laptop, a part, an accessory or a different "
                "kind of item), reply DISCARD even when its specs look impressive.\n"
                "2. Then price, condition and the requested specs.\n"
                "3. If the price is implausibly low for that product, DISCARD it as a "
                "likely accessory, part or pricing error.\n"
                "For each item reply with exactly one line containing KEEP or DISCARD "
                "and nothing else. No commentary."
            )
            user = (
                f"User wants: {prompt}\n\n"
                f"Items (title | price | condition | site):\n{items}\n\n"
                "One KEEP/DISCARD line per item, in the same order:"
            )
            response = await self._chat(system, user, max_tokens=200, temperature=0.0)

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
    async def _call_local_llm_async(self, local_cfg, system: str, user: str,
                                    max_tokens: int, temperature: float = 0.3) -> str:
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
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        # Local inference may need a long prefill/load window (see LOCAL_TIMEOUT).
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=LOCAL_TIMEOUT))
        response.raise_for_status()
        return _content_from(response.json())

    # === Cloud API calls ===
    async def _call_cloud_llm_async(self, provider: str, api_key: str, model: str,
                                    system: str, user: str, max_tokens: int,
                                    temperature: float = 0.3) -> str:
        if provider == "openrouter":
            return await self._call_openrouter_async(
            api_key, model, system, user, max_tokens, temperature
        )
        elif provider == "gemini":
            return await self._call_gemini_async(
            api_key, model, system, user, max_tokens, temperature
        )
        elif provider == "mistral":
            return await self._call_mistral_async(
            api_key, model, system, user, max_tokens, temperature
        )
        else:
            msg = f"Unknown provider: {provider}"
            raise ValueError(msg)

    async def _call_openrouter_async(self, api_key: str, model: str, system: str,
                                     user: str, max_tokens: int,
                                     temperature: float = 0.3) -> str:
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
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=CLOUD_TIMEOUT))
        response.raise_for_status()
        return _content_from(response.json())

    async def _call_gemini_async(self, api_key: str, model: str, system: str,
                                 user: str, max_tokens: int,
                                 temperature: float = 0.3) -> str:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        # Gemini doesn't support system prompt separately, combine them
        payload = {
            "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=CLOUD_TIMEOUT))
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    async def _call_mistral_async(self, api_key: str, model: str, system: str,
                                  user: str, max_tokens: int,
                                  temperature: float = 0.3) -> str:
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
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=CLOUD_TIMEOUT))
        response.raise_for_status()
        return _content_from(response.json())

    def _get_api_key(self, env_var: str) -> str | None:
        """Get API key from environment variable."""
        return os.environ.get(env_var)