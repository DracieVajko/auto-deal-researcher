"""Per-provider LLM health checks.

`python -m src.cli llm-check` probes every configured provider on its own so a
broken credential or an empty model reply is reported directly, instead of
being buried in the fallback chain where the only visible symptom is a slow
run and a generic "all providers failed" warning.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

from src.llm.client import PERMANENT_AUTH_ERRORS, LLMClient

# Actionable hints per provider, shown when the probe fails.
_HINTS = {
    "openrouter": (
        "Create or rotate the key at https://openrouter.ai/keys. "
        "HTTP 401 'User not found' means the account or the key no longer exists."
    ),
    "gemini": (
        "Key: https://aistudio.google.com/apikey. Prefer a fast model such as "
        "gemini-2.5-flash; 3.x thinking models can take a minute per reply."
    ),
    "mistral": "Key: https://console.mistral.ai/api-keys/.",
    "lmstudio": "Start LM Studio, load a model and enable the local server (port 1234).",
    "ollama": "Start it with `ollama serve` and pull the model named in config.yaml.",
    "llamacpp": "Start llama.cpp's server on the configured port.",
}

_EMPTY_HINTS = {
    "gemini": (
        "The model answered 200 OK with no text. Thinking models spend the "
        "output budget on reasoning first; raise ADS_GEMINI_MIN_OUTPUT_TOKENS "
        "or switch to gemini-2.5-flash."
    ),
}

_RATE_LIMIT_HINTS = {
    "gemini": (
        "Free-tier quota is per minute and per day. Wait for the window to "
        "reset, or enable billing: https://ai.google.dev/gemini-api/docs/rate-limits"
    ),
    "openrouter": "Free models are rate-limited per minute; wait or add credits.",
    "mistral": "Check your plan's rate limits: https://console.mistral.ai/",
}


@dataclass
class ProviderStatus:
    """Result of probing one provider."""

    provider: str
    model: str
    kind: str  # "local" | "cloud"
    status: str  # ok | auth | empty | timeout | http | error | no-key
    latency: float = 0.0
    detail: str = ""
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _http_detail(response) -> str:
    """Pull the provider's own error message out of an HTTP response."""
    if response is None:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()[:200]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:200]
        if isinstance(error, str) and error:
            return error[:200]
    return str(payload)[:200]


def _preview(text: str, limit: int = 60) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


async def check_cloud(
    client: LLMClient, config, prompt: str, request_timeout: float
) -> list[ProviderStatus]:
    """Probe each configured cloud API and report what actually happened."""
    results: list[ProviderStatus] = []
    for api in config.llm.api_fallback:
        api_key = (os.environ.get(api.api_key_env) or "").strip()
        hint = _HINTS.get(api.provider, "")
        if not api_key:
            results.append(
                ProviderStatus(
                    provider=api.provider,
                    model=api.model,
                    kind="cloud",
                    status="no-key",
                    detail=f"{api.api_key_env} is not set",
                    hint=hint,
                )
            )
            continue

        started = time.perf_counter()
        try:
            reply = await client._call_cloud_llm_async(
                api.provider,
                api_key,
                api.model,
                "You are terse.",
                prompt,
                64,
                0.0,
                request_timeout,
            )
        except requests.Timeout:
            results.append(
                ProviderStatus(
                    provider=api.provider,
                    model=api.model,
                    kind="cloud",
                    status="timeout",
                    latency=time.perf_counter() - started,
                    detail=f"no reply within {request_timeout:.0f}s",
                    hint=hint,
                )
            )
            continue
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", 0)
            results.append(
                ProviderStatus(
                    provider=api.provider,
                    model=api.model,
                    kind="cloud",
                    status="auth" if status_code in PERMANENT_AUTH_ERRORS else "http",
                    latency=time.perf_counter() - started,
                    detail=f"HTTP {status_code}: {_http_detail(exc.response)}",
                    hint=(
                        _RATE_LIMIT_HINTS.get(api.provider, "")
                        if status_code == 429
                        else hint
                    ),
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - report any provider failure verbatim
            results.append(
                ProviderStatus(
                    provider=api.provider,
                    model=api.model,
                    kind="cloud",
                    status="error",
                    latency=time.perf_counter() - started,
                    detail=f"{type(exc).__name__}: {exc}",
                    hint=hint,
                )
            )
            continue

        latency = time.perf_counter() - started
        if reply.strip():
            results.append(
                ProviderStatus(
                    provider=api.provider,
                    model=api.model,
                    kind="cloud",
                    status="ok",
                    latency=latency,
                    detail=_preview(reply),
                )
            )
        else:
            results.append(
                ProviderStatus(
                    provider=api.provider,
                    model=api.model,
                    kind="cloud",
                    status="empty",
                    latency=latency,
                    detail="provider answered but returned no text",
                    hint=_EMPTY_HINTS.get(api.provider, ""),
                )
            )
    return results


async def check_local(
    client: LLMClient, config, prompt: str, request_timeout: float
) -> list[ProviderStatus]:
    """Probe each configured local endpoint (connection refused is instant)."""
    results: list[ProviderStatus] = []
    for local in config.llm.local:
        hint = _HINTS.get(local.type, "")
        started = time.perf_counter()
        try:
            reply = await client._call_local_llm_async(
                local, "You are terse.", prompt, 32, 0.0, request_timeout
            )
        except requests.Timeout:
            results.append(
                ProviderStatus(
                    provider=local.type,
                    model=local.model,
                    kind="local",
                    status="timeout",
                    latency=time.perf_counter() - started,
                    detail=(
                        f"{local.endpoint} did not answer within {request_timeout:.0f}s "
                        "(the model may still be loading)"
                    ),
                    hint=hint,
                )
            )
            continue
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", 0)
            results.append(
                ProviderStatus(
                    provider=local.type,
                    model=local.model,
                    kind="local",
                    status="http",
                    latency=time.perf_counter() - started,
                    detail=f"HTTP {status_code}: {_http_detail(exc.response)}",
                    hint=hint,
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - report any provider failure verbatim
            results.append(
                ProviderStatus(
                    provider=local.type,
                    model=local.model,
                    kind="local",
                    status="error",
                    latency=time.perf_counter() - started,
                    detail=f"{type(exc).__name__}: {exc}",
                    hint=hint,
                )
            )
            continue

        latency = time.perf_counter() - started
        if reply.strip():
            results.append(
                ProviderStatus(
                    provider=local.type,
                    model=local.model,
                    kind="local",
                    status="ok",
                    latency=latency,
                    detail=_preview(reply),
                )
            )
        else:
            results.append(
                ProviderStatus(
                    provider=local.type,
                    model=local.model,
                    kind="local",
                    status="empty",
                    latency=latency,
                    detail="endpoint answered but returned no text",
                    hint=hint,
                )
            )
    return results


async def run_checks(
    config,
    *,
    local: bool = True,
    cloud: bool = True,
    request_timeout: float = 20.0,
    local_timeout: float = 10.0,
    prompt: str = "Reply with OK.",
) -> list[ProviderStatus]:
    """Probe providers in the same order the runtime chain uses them."""
    client = LLMClient(config)
    results: list[ProviderStatus] = []
    if local:
        results.extend(await check_local(client, config, prompt, local_timeout))
    if cloud:
        results.extend(await check_cloud(client, config, prompt, request_timeout))
    return results
