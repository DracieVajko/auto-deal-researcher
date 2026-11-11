"""LLM Client with multi-provider fallback chain."""

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import time
from collections.abc import Sequence

import requests

from src.llm import protocols
from src.llm.local_coordinator import LocalModelCoordinator, ensure_lmstudio_model
from src.searcher.listing_filter import (
    MINI_PC_HINTS,
    excluded_by_form_factor,
    wants_mini_pc_form_factor,
)
from src.text.normalize import fold

DealLike = protocols.DealLike

logger = logging.getLogger(__name__)

# Known brands only: guessing from capitalisation picks up cities and sentence
# starts.  Product-line names such as "iPhone" count too.
_KNOWN_BRANDS = (
    "pocketbook", "dji", "iphone", "samsung", "xiaomi", "apple", "lenovo",
    "dell", "asus", "acer", "msi", "sony", "canon", "nikon", "gopro",
    "beelink", "intel", "amd", "nvidia", "google", "huawei", "oneplus",
    "realme", "oppo", "motorola", "nokia", "bosch", "makita", "dewalt",
)

# Folded superlatives that mean "cheapest first".
_CHEAPEST_WORDS = (
    "najlacne", "nejlevne", "cheapest", "gunstigst", "billigst",
    "najtaniej", "legolcso",
)

# Adaptive HTTP timeouts (seconds) per provider class.
#
# Local models (LM Studio / Ollama / llama.cpp) need a longer budget than cloud
# APIs, but an unbounded wait lets a dead backend stall a whole run. 180 s
# covers a warm model; a model that is not loaded should be started with
# `llm-check` or LM Studio first. Override with ADS_LOCAL_LLM_TIMEOUT.

# Gemini thinking models spend output tokens on reasoning before they emit any
# text. With a 16-token budget the answer was cut off entirely and the provider
# looked "empty" even though it answered 200 OK. The floor is read from the
# environment on each call; see _gemini_min_output_tokens().

# HTTP statuses that mean "this credential will never work in this run".
PERMANENT_AUTH_ERRORS = frozenset({401, 403})


def _timeout_from_env(name: str = "ADS_LOCAL_LLM_TIMEOUT", default: float = 900.0) -> float:
    """Read a timeout override from the environment, ignoring invalid values."""
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


def _gemini_min_output_tokens() -> int:
    return max(1, int(_timeout_from_env("ADS_GEMINI_MIN_OUTPUT_TOKENS", 512)))


def __getattr__(name: str):
    if name == "LOCAL_TIMEOUT":
        return _timeout_from_env("ADS_LOCAL_LLM_TIMEOUT", 900.0)
    if name == "CLOUD_TIMEOUT":
        return _timeout_from_env("ADS_CLOUD_LLM_TIMEOUT", 120.0)
    if name == "GEMINI_MIN_OUTPUT_TOKENS":
        return _gemini_min_output_tokens()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")  # noqa: TRY003



class LocalCircuitBreaker:
    """Skip a provider for a while after it fails.

    Without this, an unreachable or hung LM Studio is retried on *every*
    LLM call and each one burns the full local timeout, so a run that should
    take seconds stalls for many minutes. The same applies to a cloud key that
    the provider rejects: a 401 never heals, so retrying it on every call just
    adds noise and latency.
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

    def block(self, key: str) -> None:
        """Disable a provider for the rest of the run.

        Used for permanent failures such as a revoked API key (HTTP 401/403):
        the provider cannot start working again without a config change, so a
        timed cooldown would only waste one request per call in the meantime.
        """
        self._failures[key] = self.threshold
        self._open_until[key] = float("inf")

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
    if last is None:
        raise ValueError("attempts must be at least 1")
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


def _content_from_gemini(payload: dict) -> str:
    """Extract answer text from a Gemini ``generateContent`` response.

    Gemini thinking models stream their internal reasoning back as parts
    flagged ``thought: true`` and may omit the answer part entirely when the
    output budget runs out. The old inline indexing
    ``["candidates"][0]["content"]["parts"][0]["text"]`` raised KeyError on
    those replies, which the fallback chain logged as a provider failure with
    no explanation. Thinking parts are dropped here so the caller only ever
    sees the user-visible answer.
    """
    try:
        candidate = payload["candidates"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    parts = candidate.get("content", {}).get("parts") or []
    chunks = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("text") and not part.get("thought")
    ]
    return "".join(chunks).strip()


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
        # Model monitor: handles slot accounting, waiting, preloading, unloading.
        self._monitor = self._build_monitor()
        # Ambiguous card text -> validated price classification. Repeated
        # rounds and repeated sites often send the same card; do not pay for it
        # twice in one run.
        self._price_quote_cache: dict[tuple, dict] = {}

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

    def _build_monitor(self):
        """Create a LocalModelMonitor from config (or None if disabled)."""
        coord = getattr(self.llm_config, "local_coordination", None)
        if coord is None or not getattr(coord, "enabled", True):
            return None
        try:
            from src.llm.model_monitor import LocalModelMonitor, MonitorConfig
            config = MonitorConfig(
                enabled=True,
                policy=getattr(coord, "policy", "wait") or "wait",
                max_concurrent_models=getattr(coord, "max_concurrent_models", 1),
                wait_timeout_seconds=getattr(coord, "wait_timeout_seconds", 3600),
                poll_interval_seconds=getattr(coord, "wait_poll_seconds", 120),
                preload=getattr(coord, "preload", False),
                unload_after_job=getattr(coord, "unload_after_job", True),
                quiet_seconds=getattr(coord, "quiet_seconds", 300),
                probe_busy=getattr(coord, "probe_busy", False),
            )
            return LocalModelMonitor(config)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not build model monitor: %s", exc)
            return None

    async def release_models(self) -> None:
        """Unload all models we loaded (call after job completion)."""
        if self._monitor is None:
            return
        for model in list(self.llm_config.local):
            try:
                await self._monitor.release(model.model, model.type)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Release failed for %s: %s", model.model, exc)

    async def preload_models(self) -> None:
        """Preload all configured local models (call at startup)."""
        if self._monitor is None:
            return
        for model in self.llm_config.local:
            try:
                await self._monitor.preload(model.model, model.type)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Preload failed for %s: %s", model.model, exc)
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
            logger.warning(
                "Invalid local coordination policy %r: %s; defaulting to 'never'",
                policy,
                e,
            )
            return LocalModelCoordinator(policy="never")

    def describe_local_state(self) -> str:
        """Human-readable state of both local backends (read-only)."""
        return self._coordinator.describe() if self._coordinator else "not configured"

    async def chat(self, system: str, user: str, max_tokens: int = 400,
                   temperature: float = 0.3) -> str:
        """Public chat entry point used by agents and external callers."""
        return await self._chat(system, user, max_tokens, temperature)

    async def chat_json(self, system: str, user: str, max_tokens: int = 400):
        """Chat and parse a JSON object/list from the reply."""
        raw = await self._chat(system, user, max_tokens)
        from src.agents.llm_support import extract_json

        return extract_json(raw)

    async def extract_search_filters(self, prompt: str) -> dict:
        """Extract canonical search filters from a natural-language prompt.

        Python-first: try deterministic regex extraction for common patterns
        (prices, conditions, categories).  Only fall back to the LLM when the
        regex cannot parse the prompt, so simple queries are instant.
        """
        result = self._extract_filters_regex(prompt)
        if result is not None:
            return result

        system = (
            "Extract marketplace search filters from the user request. "
            "Return ONLY a JSON object with optional keys: "
            "min_price, max_price, condition (new|used|refurbished|open_box|marketplace), "
            "category (electronics|appliances|auto|home|hobby|general), "
            "brand, location, shipping (free|paid), "
            "seller_type (retailer|marketplace|classifieds|auction|private), "
            "sort (relevance|price_asc|price_desc|newest), and extras "
            "(an object of string key/value pairs). Use null for unknown values. "
            "min_price: only set when the user explicitly says 'from X', 'at least X' or 'over X'. "
            "max_price: set when the user says 'up to X', 'under X', 'do X', 'below X'. "
            "Give category only as one of the listed words when the request "
            "clearly implies it; omit it when unsure. "
            "ALWAYS set category to 'electronics' when the request involves phones, "
            "smartphones, laptops, tablets, TVs, cameras or any electronic device. "
            "Bikes, scooters and outdoor gear are 'hobby'. "
            "Cars, motorcycles and vehicles are 'auto'. "
            "Furniture and home appliances are 'home' or 'appliances'. "
            "Prices are EUR numbers. 'Up to X', 'under X', 'do X', 'max X' and 'su X eur' are price limits (max_price). 'Above X', 'from X', 'over X' and 'min X' are minimum price limits (min_price). Only set price limits for numbers that clearly refer to currency; voltage (V, volts), watts (W), amps (A), inches (inch, palec) and storage (GB) are NOT prices — extract them as extras (e.g. voltage_volt, wheel_size_inch, storage_gb). Do not invent values that are not in the request."
        )
        data = await self.chat_json(system, prompt, max_tokens=300)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_filters_regex(prompt: str) -> dict | None:
        """Deterministic filter extraction for common patterns."""
        import re

        text = prompt.lower()
        result: dict = {}

        max_match = re.search(
            r"\b(?:pod|do|under|below|max|bis|up to|su)\s+(\d[\d\s.,]*)\s*(?:eur|€|euro)?",
            text,
        )
        if max_match:
            raw = max_match.group(1).replace(" ", "").replace(",", ".")
            try:
                result["max_price"] = float(raw)
            except ValueError:
                pass

        # Postfix form used by Hungarian and some German/Czech requests:
        # "300 euró alatt", "500 Euro maximal".
        if "max_price" not in result:
            max_postfix = re.search(
                r"(\d[\d\s.,]*)\s*(?:eur|€|euro|euró)\s*(?:alatt|maximal|max)\b",
                text,
            )
            if max_postfix:
                raw = max_postfix.group(1).replace(" ", "").replace(",", ".")
                try:
                    result["max_price"] = float(raw)
                except ValueError:
                    pass

        min_match = re.search(
            r"\b(?:od|min|above|over|from|ab)\s+(\d[\d\s.,]*)\s*(?:eur|€|euro)?",
            text,
        )
        if min_match:
            raw = min_match.group(1).replace(" ", "").replace(",", ".")
            try:
                result["min_price"] = float(raw)
            except ValueError:
                pass

        range_match = re.search(
            r"(?:od|from)\s+(\d[\d\s.,]*)\s*(?:eur|€|euro)?\s*(?:do|to|-)\s*(\d[\d\s.,]*)\s*(?:eur|€|euro)?",
            text,
        )
        if range_match:
            try:
                result["min_price"] = float(range_match.group(1).replace(" ", "").replace(",", "."))
                result["max_price"] = float(range_match.group(2).replace(" ", "").replace(",", "."))
            except ValueError:
                pass

        if re.search(r"\b(?:nov[ýéá]|novy|new|neu\w*|nowy)\b", text):
            result["condition"] = "new"
        elif re.search(
            r"\b(?:použit\w*|pouzit\w*|used|gebraucht\w*|używan\w*|használt\w*)\b",
            text,
        ):
            result["condition"] = "used"
        elif re.search(r"\b(?:repasovan\w*|refurbished)\b", text):
            result["condition"] = "refurbished"
        elif "open box" in text:
            result["condition"] = "open_box"

        electronics_kw = ("telefón", "telefon", "phone", "smartphone", "laptop", "notebook",
                          "tablet", "tv", "kamera", "camera", "computer", "drone", "dron",
                          "pocketbook", "iphone", "samsung", "xiaomi")
        hobby_kw = ("bicykel", "bike", "kolo", "rower", "skúter", "skuter", "scooter",
                    "kolobežka", "kolobezka", "outdoor", "sport")
        auto_kw = ("auto", "car", "motor", "motocykel", "motorcycle")
        if any(w in text for w in electronics_kw):
            result["category"] = "electronics"
        elif any(w in text for w in hobby_kw):
            result["category"] = "hobby"
        elif any(w in text for w in auto_kw):
            result["category"] = "auto"

        location_kw = ("bratislava", "praha", "prague", "münchen", "munchen", "munich",
                       "kraków", "krakow", "budapest", "wien", "vienna", "berlin",
                       "brno", "košice", "kosice")
        for loc in location_kw:
            if loc in text:
                result["location"] = loc.title()
                break

        for brand in _KNOWN_BRANDS:
            if re.search(rf"\b{re.escape(brand)}\b", text):
                result["brand"] = brand
                break

        # Numeric specs are not prices; keep them as extras.
        extras: dict[str, str] = {}
        storage = re.search(r"\b(\d{1,4})\s*(?:GB|TB)\b", prompt, re.IGNORECASE)
        if storage:
            extras["storage_gb"] = storage.group(1)
        voltage = re.search(r"\b(\d{1,4})\s*V\b", prompt)
        if voltage:
            extras["voltage_volt"] = voltage.group(1)
        power = re.search(r"\b(\d{1,5})\s*W\b", prompt)
        if power:
            extras["power_w"] = power.group(1)
        wheel = re.search(
            r"\b(\d{1,2}(?:[.,]\d+)?)\s*(?:inch|palcov|palce|zoll)\b", text
        )
        if wheel:
            extras["wheel_size_inch"] = wheel.group(1).replace(",", ".")
        if extras:
            result["extras"] = extras

        # Category alone is ambiguous (a "notebook" may be paper), so let the
        # LLM confirm it.  A price, condition or location is a strong enough
        # signal to skip the round-trip.
        if not {"min_price", "max_price", "condition", "location", "brand"} & result.keys():
            return None
        for key in ("min_price", "max_price", "condition", "category", "brand",
                    "location", "shipping", "seller_type"):
            result.setdefault(key, None)
        result.setdefault("extras", {})
        return result

    async def classify_price_quotes(self, items: list[dict]) -> dict[str, dict]:
        """Classify price cards (shipping, bundles, gated promos).

        Python-first: ``extract_price_signals`` already recognises free/paid
        shipping, coupon codes, account gates, ranges and bundles.  Cards it
        reads confidently are classified without a model call; only cards it
        cannot read are sent to the LLM.  Every returned entry is validated
        against its card text, so invented evidence or impossible numbers are
        dropped rather than trusted.
        """
        if not items:
            return {}
        from src.searcher.pricing import extract_price_signals, validate_price_classification

        system = (
            "You classify marketplace listing cards by how their price works. "
            "For each card return the price kind: regular, promo (public sale), "
            "coupon (needs a code or auto-applied coupon), account_gated "
            "(new user, first order, member, app-only), bundle (minimum quantity "
            "required), range ('from X' or a variant range) or unknown. "
            "Also report shipping_cost_eur, shipping_is_free, shipping_min_eur, "
            "shipping_max_eur, bundle_min_quantity, price_from, price_max_eur, "
            "regular_price_eur, warnings, confidence (0-1) and evidence. "
            "Use null for any value the card does not show; never guess. "
            "Every evidence entry MUST be an exact substring copied from the "
            "card text. Return ONLY JSON: "
            '{"quotes": [{"id": "...", "kind": "...", "shipping_cost_eur": null, '
            '"shipping_is_free": null, "shipping_min_eur": null, '
            '"shipping_max_eur": null, "bundle_min_quantity": 1, '
            '"price_from": false, "price_max_eur": null, '
            '"regular_price_eur": null, "warnings": [], "confidence": 0.0, '
            '"evidence": []}]}'
        )
        cards = [
            {
                "id": str(item.get("id", "")),
                "text": str(item.get("text", ""))[:2000],
                "listed_price_eur": item.get("listed_price_eur"),
                "currency": item.get("currency", "EUR"),
            }
            for item in items[:10]
        ]
        result: dict[str, dict] = {}
        pending: list[tuple[dict, tuple]] = []
        for card in cards:
            key = (
                card["text"],
                card["listed_price_eur"],
                card["currency"],
            )
            cached = self._price_quote_cache.get(key)
            if cached is not None:
                result[card["id"]] = dict(cached)
                continue

            try:
                listed_price = float(card["listed_price_eur"] or 0.0)
            except (TypeError, ValueError):
                listed_price = 0.0
            signals = extract_price_signals(
                card["text"],
                listed_price,
                str(card["currency"] or "EUR"),
            )
            if signals.confidence >= 0.7:
                payload = {
                    "kind": signals.kind.value,
                    "shipping_cost_eur": signals.shipping.cost_eur,
                    "shipping_is_free": signals.shipping.is_free,
                    "shipping_min_eur": signals.shipping.min_eur,
                    "shipping_max_eur": signals.shipping.max_eur,
                    "bundle_min_quantity": signals.bundle.min_quantity,
                    "price_from": signals.price_from,
                    "price_max_eur": signals.price_max_eur,
                    "regular_price_eur": signals.regular_price_eur,
                    "warnings": list(signals.warnings),
                    "confidence": signals.confidence,
                    "evidence": list(signals.evidence),
                }
                validated = validate_price_classification(payload, card["text"])
                if validated is not None:
                    result[card["id"]] = validated
                    self._price_quote_cache[key] = validated
                    continue
            pending.append((card, key))
        if not pending:
            return result

        cards = [card for card, _key in pending]
        user = json.dumps({"cards": cards}, ensure_ascii=False)
        try:
            data = await self.chat_json(system, user, max_tokens=1200)
        except Exception as exc:  # noqa: BLE001 - optional enrichment
            logger.info("Price classification unavailable: %s", exc)
            return result

        quotes = data.get("quotes") if isinstance(data, dict) else data
        if not isinstance(quotes, list):
            return result

        by_id = {card["id"]: (card["text"], key) for card, key in pending}
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            quote_id = str(quote.get("id", ""))
            entry = by_id.get(quote_id)
            if entry is None:
                continue
            card_text, key = entry
            validated = validate_price_classification(quote, card_text)
            if validated is not None:
                result[quote_id] = validated
                self._price_quote_cache[key] = validated
        return result


    # === New async methods ===
    async def _chat(self, system: str, user: str, max_tokens: int = 100,
                    temperature: float = 0.3) -> str:
        """Unified chat method with fallback chain."""
        # Try local LLMs first, but only when the backend is free.
        our_models = {getattr(model, "model", "") for model in self.llm_config.local}
        if self._coordinator is not None:
            safe, reason = self._coordinator.acquire(our_models)
            if not safe:
                logger.info("Skipping local LLMs: %s", reason)
                self.llm_config.local = []
        # Monitor: wait for a slot if the backend is busy.
        if getattr(self, "_monitor", None) is not None and self.llm_config.local:
            for local in self.llm_config.local:
                ok, reason = await self._monitor.acquire(local.model, local.type if local.type != "lmstudio" else "lmstudio")
                if not ok:
                    logger.info("Monitor could not acquire %s: %s", local.model, reason)
                    self.llm_config.local = [
                        candidate
                        for candidate in self.llm_config.local
                        if candidate is not local
                    ]

        for local in self.llm_config.local:
            key = f"{local.type}:{local.endpoint}:{local.model}"
            if self._breaker.is_open(key):
                logger.info(f"Skipping local LLM {local.type} (circuit open)")
                continue
            if local.type == "lmstudio" and getattr(self._coordinator, "policy", "never") in ("wait", "force"):
                ensure_lmstudio_model(local.model)
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
            key = f"cloud:{api.provider}:{api.api_key_env}"
            if self._breaker.is_open(key):
                logger.info(f"Skipping cloud API {api.provider} (circuit open)")
                continue
            api_key = self._get_api_key(api.api_key_env)
            if api_key:
                try:
                    logger.info(f"Trying cloud API: {api.provider} with model {api.model}")
                    reply = await self._call_cloud_llm_async(
                        api.provider, api_key, api.model, system, user,
                        max_tokens, temperature
                    )
                    if reply.strip():
                        self._breaker.record_success(key)
                        return reply
                    # An empty body is a failure; fall through to the next provider.
                    logger.warning(f"Cloud API ({api.provider}) returned an empty response")
                    self._breaker.record_failure(key)
                except requests.HTTPError as e:
                    status = getattr(e.response, "status_code", None)
                    if status in PERMANENT_AUTH_ERRORS:
                        logger.warning(
                            "Cloud API (%s) rejected the credential (HTTP %s: %s); "
                            "disabling it for this run. Fix %s in .env or config.yaml.",
                            api.provider, status, e, api.api_key_env,
                        )
                        self._breaker.block(key)
                    else:
                        logger.warning(f"Cloud API ({api.provider}) failed: {e}")
                        self._breaker.record_failure(key)
                except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                    logger.warning(f"Cloud API ({api.provider}) failed: {e}")
                    self._breaker.record_failure(key)
            else:
                logger.warning(f"Cloud API ({api.provider}) skipped: no API key in env {api.api_key_env}")

        logger.error("All LLM providers failed, falling back to prompt as search query")
        # Return an empty string rather than the user prompt. Downstream callers
        # (chat_json, judge_results, rank_results, ...) must not mistake the
        # echoed prompt for a model reply, or they will parse garbage verdicts.
        return ""

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

    async def generate_search_query_async(self, prompt: str, broader: bool = False) -> str:
        # Query generation is the multilingual step: the model may translate
        # the request into the target site's language.  The deterministic
        # keyword query is only the fallback when the model is unavailable.
        kw = self.keyword_query(prompt)
        system = (
            "You convert a product request into a SHORT marketplace search query. "
            "Reply with 2-5 plain words only, for example 'mini pc ryzen' or "
            "'dji drone 350'. No quotes, no punctuation, no lists, no explanation."
        )
        user = f"Request: {prompt}\nShort search query:"
        if broader:
            user += " Use only 1-3 generic words."
        raw = await self._chat(system, user, max_tokens=40)
        return self._clean_query(raw, fallback=kw)

    async def refine_query(self, prompt: str, current_deals: Sequence[DealLike], round_num: int) -> str:
        """Generate query to find DIFFERENT items than already found."""
        kw = self.keyword_query(prompt)
        titles = [d.title for d in current_deals[:10]]
        system = (
            "Write a SHORT marketplace search query (2-5 plain words) for items "
            "different from those already found. No quotes, no punctuation."
        )
        user = f"Original request: {prompt}\nAlready found: {titles}\nNew query:"
        raw = await self._chat(system, user, max_tokens=40)
        return self._clean_query(raw, fallback=kw)

    async def judge_results(self, prompt: str, deals: Sequence[DealLike]) -> dict:
        """Classify each deal as keep/discard. Return {'keep': [urls]}.

        Python-first: listings that satisfy every explicit constraint are
        kept without a model call, and deterministic rejects (over budget,
        implausibly cheap, accessory or component listings) are dropped.
        Only listings with missing or unverifiable data go to the judge,
        which is where the model actually adds information.

        Small models often answer with prose or fewer lines than the batch,
        so an unreadable reply must keep its batch instead of dropping it,
        which is what made whole runs come back empty.
        """
        if not deals:
            return {"keep": []}

        confident, ambiguous = self._prefilter_deals(prompt, deals)
        if not confident and not ambiguous:
            return {"keep": []}

        # Deals that satisfy every explicit constraint are kept without a
        # model call.  Only listings with missing or unverifiable data go to
        # the judge, which is where the model actually adds information.
        keep_urls: list[str] = [d.url for d in confident]
        parsed_lines = 0

        for i in range(0, len(ambiguous), 10):
            batch = ambiguous[i : i + 10]
            items = "\n".join(
                [f"- {d.title} | {d.price_eur} EUR | {d.condition} | {d.site_name}" for d in batch]
            )
            system = (
                "You are a strict product-matching judge. Check requirements in this order:\n"
                "1. PRODUCT TYPE first. If the listing is not the product the user asked "
                "for (a full-size desktop, a laptop, a part, an accessory or a different "
                "kind of item), reply DISCARD even when its specs look impressive. "
                "A laptop/notebook is always DISCARD when the request is for a mini PC, "
                "barebone, NUC or small form factor machine.\n"
                "2. Then price and the requested specs.\n"
                "3. Condition is only a reason to DISCARD when the user explicitly asked "
                "for new/refurbished. Otherwise keep used listings: they are often the "
                "best value and the report explains the risks.\n"
                "4. If the price is implausibly low for that product, DISCARD it as a "
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
            else:
                # Unreadable batch: keep it rather than silently dropping it.
                keep_urls.extend(deal.url for deal in batch)

        if not keep_urls and parsed_lines == 0:
            candidates = confident + ambiguous
            logger.warning(
                "Deal judge returned no parseable verdicts; keeping all %d deals",
                len(candidates),
            )
            return {"keep": [d.url for d in candidates]}

        return {"keep": keep_urls}

    @staticmethod
    def _prefilter_deals(
        prompt: str, deals: Sequence[DealLike]
    ) -> tuple[list[DealLike], list[DealLike]]:
        """Split listings into provably-good and model-needed groups.

        Returns ``(confident, ambiguous)``.  A deal is confident when every
        explicit constraint in the prompt (budget, condition, RAM, model
        token, mini-PC form factor) is present in the listing and satisfied.
        Missing data makes a deal ambiguous instead of silently passing it to
        the report.  Deterministic rejects are dropped from both lists.
        """
        prompt_lower = prompt.lower()

        max_price: float | None = None
        match = re.search(
            r"\b(?:pod|do|under|below|max|bis|up to|su)\s+(\d[\d\s.,]*)",
            prompt_lower,
        )
        if match:
            raw = match.group(1).replace(" ", "").replace(",", ".")
            try:
                max_price = float(raw)
            except ValueError:
                max_price = None

        wants_new = bool(
            re.search(r"\b(?:nov[ýéá]|novy|new|neu\w*|nowy)\b", prompt_lower)
        ) and "new york" not in prompt_lower
        wants_mini_pc = wants_mini_pc_form_factor(prompt)

        accessory_pattern = re.compile(
            r"\b(?:obal|kryt|cover|cable|kabel|charger|nabíjačka|nabijacka|"
            r"stojan|stand|spare part|replacement part|náhradný diel|nahradny diel)\b",
            re.IGNORECASE,
        )
        accessory_requested = bool(accessory_pattern.search(prompt_lower))

        component_pattern = re.compile(
            r"^(?:ram|ssd|hdd|cpu|gpu|motherboard|psu|zdroj|napájanie|napajanie)\b",
            re.IGNORECASE,
        )

        required_ram: int | None = None
        ram_match = re.search(r"\b(\d{1,4})\s*gb\s*ram\b", prompt_lower)
        if ram_match:
            required_ram = int(ram_match.group(1))

        # Model tokens such as "634verse", "wh1000xm5" or "pn50".  Unit-like
        # tokens (32gb, 500w, 24v) are handled by their own rules.
        unit_suffix = re.compile(
            r"(?:gb|tb|w|v|mah|hz|mm|cm|kg|km|kw|hp|inch|eur)$", re.IGNORECASE
        )
        model_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", prompt_lower)
            if len(token) >= 4
            and any(ch.isdigit() for ch in token)
            and any(ch.isalpha() for ch in token)
            and not unit_suffix.search(token)
            and not re.fullmatch(r"(?:19|20)\d{2}", token)
        ]

        has_constraint = bool(
            max_price is not None
            or required_ram is not None
            or model_tokens
            or wants_new
            or wants_mini_pc
        )

        confident: list[DealLike] = []
        ambiguous: list[DealLike] = []
        for deal in deals:
            title = deal.title or ""
            title_lower = title.lower()
            title_norm = re.sub(r"[\s\-]+", "", title_lower)
            price = getattr(deal, "price_eur", 0) or 0
            condition = (getattr(deal, "condition", "") or "").lower()

            # --- deterministic rejects ---
            if max_price and price > 0:
                if price > max_price:
                    continue
                if price < max_price * 0.1:
                    continue
            if not accessory_requested and accessory_pattern.search(title):
                continue
            if component_pattern.search(title):
                continue
            if excluded_by_form_factor(prompt, title):
                continue
            if wants_new and condition in {"used", "refurbished", "open_box"}:
                continue
            if required_ram is not None:
                title_ram = re.search(r"\b(\d{1,4})\s*gb\s*ram\b", title_lower)
                if title_ram and int(title_ram.group(1)) < required_ram:
                    continue
            if any(token not in title_norm for token in model_tokens):
                continue

            # --- confidence ---
            verifiable = True
            if max_price is not None and price <= 0:
                verifiable = False
            if required_ram is not None:
                title_ram = re.search(r"\b(\d{1,4})\s*gb\s*ram\b", title_lower)
                if title_ram is None:
                    verifiable = False
            if wants_mini_pc and not any(
                hint in title_lower for hint in MINI_PC_HINTS
            ):
                verifiable = False
            if wants_new and condition != "new":
                verifiable = False

            if has_constraint and verifiable:
                confident.append(deal)
            else:
                ambiguous.append(deal)
        return confident, ambiguous

    @staticmethod
    def _cheapest_rank(
        prompt: str, deals: Sequence[DealLike]
    ) -> list[DealLike] | None:
        """Cheapest-first order when the request names a specific product.

        "Cheapest iPhone 15 128GB" is fully deterministic: match the brand,
        model number and storage, then sort by price.  Returns ``None`` when
        the prompt is not a cheapest request or has nothing verifiable, so the
        LLM still handles semantic relevance.
        """
        prompt_lower = prompt.lower()
        if not any(word in fold(prompt_lower) for word in _CHEAPEST_WORDS):
            return None

        brands = [
            brand for brand in _KNOWN_BRANDS
            if re.search(rf"\b{re.escape(brand)}\b", prompt_lower)
        ]

        storage: str | None = None
        storage_match = re.search(
            r"\b(\d{1,4})\s*(gb|tb)\b(?!\s*ram\b)", prompt_lower
        )
        if storage_match:
            storage = f"{storage_match.group(1)}{storage_match.group(2)}"

        model_numbers: list[str] = []
        for match in re.finditer(r"\b(\d{1,3})\b", prompt_lower):
            number = match.group(1)
            after = prompt_lower[match.end():match.end() + 5]
            before = prompt_lower[max(0, match.start() - 14):match.start()]
            if re.match(r"\s*(?:gb|tb|eur|€|w|v|mah)\b", after):
                continue
            if re.search(r"(?:do|pod|under|max|bis|od|from|above)\s*$", before):
                continue
            model_numbers.append(number)

        if not (brands or storage or model_numbers):
            return None

        def matches(deal: DealLike) -> bool:
            title_norm = re.sub(r"[\s\-]+", "", fold(deal.title or ""))
            if brands and not any(brand in title_norm for brand in brands):
                return False
            if storage and storage not in title_norm:
                return False
            if any(number not in title_norm for number in model_numbers):
                return False
            return True

        if not any(matches(deal) for deal in deals):
            return None

        # Matches first, then the rest; price ascending inside each group.
        return sorted(
            deals,
            key=lambda deal: (
                0 if matches(deal) else 1,
                getattr(deal, "price_eur", 0) or 0,
            ),
        )

    async def rank_results(self, prompt: str, deals: Sequence[DealLike], top_n: int) -> list[DealLike]:
        """Rank deals by relevance to prompt, return top N.

        When ``top_n`` covers the whole input, any deal the model forgot to
        mention is appended in its original order instead of being dropped.
        """
        if len(deals) <= 1:
            return list(deals)

        deterministic = self._cheapest_rank(prompt, deals)
        if deterministic is not None:
            return deterministic[:top_n]

        items = "\n".join([f"{i}. {d.title} | {d.price_eur}€ | {d.condition} | {d.site_name}" for i, d in enumerate(deals)])
        system = f"Rank these deals 1-{len(deals)} by relevance to user request. Output ONLY the ranked indices (e.g., '3,1,5,2,4')."
        user = f"User wants: {prompt}\nDeals:\n{items}"
        response = await self._chat(system, user, max_tokens=200)
        indices: list[int] = []
        for token in re.findall(r"\d+", response or ""):
            index = int(token) - 1
            if 0 <= index < len(deals) and index not in indices:
                indices.append(index)

        if not indices:
            logger.debug("Failed to parse LLM ranking, using input order")
            return list(deals[:top_n])

        ranked = [deals[index] for index in indices]
        if top_n >= len(deals):
            ranked.extend(
                deal for index, deal in enumerate(deals) if index not in indices
            )
        return list(ranked[:top_n])

    # === Local LLM calls ===
    async def _call_local_llm_async(self, local_cfg, system: str, user: str,
                                    max_tokens: int, temperature: float = 0.3,
                                    request_timeout: float | None = None) -> str:
        """Call local LLM (LM Studio / Ollama / llama.cpp) via OpenAI-compatible API."""
        # Thinking models (Qwen 3, Nemotron, ...) spend output tokens on
        # internal reasoning before emitting the answer. With the app's small
        # max_tokens (20-300) the answer is cut off entirely, so the reply
        # looks empty even though the model answered 200 OK. Give the model
        # room to think *and* answer by adding the configured reasoning budget.
        llm_config = getattr(self, "llm_config", None)
        reasoning_enabled = True
        reasoning_budget = 0
        if llm_config is not None:
            reasoning_enabled = getattr(llm_config, "reasoning_enabled", True)
            raw_budget = getattr(llm_config, "reasoning_token_budget", 0) or 0
            reasoning_budget = min(raw_budget, 2000)
        if reasoning_enabled and reasoning_budget > 0:
            effective_max_tokens = max(max_tokens, max_tokens + reasoning_budget)
        else:
            effective_max_tokens = max_tokens

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
            "max_tokens": effective_max_tokens
        }
        if not reasoning_enabled:
            # Best-effort: some templates honour this even though LM Studio
            # may ignore it for certain models.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        # Pass reasoning_effort when configured; ignored by backends that
        # do not support it.
        if llm_config is not None:
            effort = getattr(llm_config, "reasoning_effort", None)
            if effort:
                payload["reasoning_effort"] = effort

        # Local inference may need a long prefill/load window (see LOCAL_TIMEOUT).
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=request_timeout or _timeout_from_env()))
        response.raise_for_status()
        return _content_from(response.json())

    # === Cloud API calls ===
    async def _call_cloud_llm_async(self, provider: str, api_key: str, model: str,
                                    system: str, user: str, max_tokens: int,
                                    temperature: float = 0.3,
                                    request_timeout: float | None = None) -> str:
        if provider == "openrouter":
            return await self._call_openrouter_async(
            api_key, model, system, user, max_tokens, temperature, request_timeout
        )
        elif provider == "gemini":
            return await self._call_gemini_async(
            api_key, model, system, user, max_tokens, temperature, request_timeout
        )
        elif provider == "mistral":
            return await self._call_mistral_async(
            api_key, model, system, user, max_tokens, temperature, request_timeout
        )
        else:
            msg = f"Unknown provider: {provider}"
            raise ValueError(msg)

    async def _call_openrouter_async(self, api_key: str, model: str, system: str,
                                     user: str, max_tokens: int,
                                     temperature: float = 0.3,
                                     request_timeout: float | None = None) -> str:
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
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=request_timeout or _timeout_from_env("ADS_CLOUD_LLM_TIMEOUT", 120.0)))
        response.raise_for_status()
        return _content_from(response.json())

    async def _call_gemini_async(self, api_key: str, model: str, system: str,
                                 user: str, max_tokens: int,
                                 temperature: float = 0.3,
                                 request_timeout: float | None = None) -> str:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        # Gemini doesn't support system prompt separately, combine them.
        # Thinking models burn the output budget on internal reasoning first,
        # so a small max_tokens returns finishReason=MAX_TOKENS with no answer.
        budget = max(max_tokens, _gemini_min_output_tokens())
        payload = {
            "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": budget
            }
        }
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=request_timeout or _timeout_from_env("ADS_CLOUD_LLM_TIMEOUT", 120.0)))
        response.raise_for_status()
        return _content_from_gemini(response.json())

    async def _call_mistral_async(self, api_key: str, model: str, system: str,
                                  user: str, max_tokens: int,
                                  temperature: float = 0.3,
                                  request_timeout: float | None = None) -> str:
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
        response = await loop.run_in_executor(None, lambda: _post_with_retry(api_url, headers=headers, json_body=payload, timeout=request_timeout or _timeout_from_env("ADS_CLOUD_LLM_TIMEOUT", 120.0)))
        response.raise_for_status()
        return _content_from(response.json())

    def _get_api_key(self, env_var: str) -> str | None:
        """Get API key from environment variable."""
        return os.environ.get(env_var)