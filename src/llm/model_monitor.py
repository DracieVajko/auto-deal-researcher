"""Local model monitor: load, wait, and unload local LLMs safely.

Wraps :class:`LocalModelCoordinator` with a higher-level policy:

* **Slot accounting** – at most ``max_concurrent_models`` models may be
  resident at once (default 1).  If the slot is full we wait and re-check
  instead of immediately failing.
* **Graceful wait** – poll every ``poll_interval_seconds`` (default 120 s)
  for up to ``wait_timeout_seconds`` (default 3600 s / 1 hour).  Only after
  the timeout do we give up and fall back to cloud providers.
* **Preload** – optionally load the model at startup so the first request
  is fast.
* **Clean unload** – release the model after the job finishes to free VRAM/RAM.

Backend support:
* LM Studio – via the ``lms`` CLI (already implemented in the coordinator).
* Ollama – via ``ollama ps`` / ``ollama stop``.
* llama.cpp – no model management (endpoint only); treated as always-available.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default policy constants.
DEFAULT_MAX_CONCURRENT = 1
DEFAULT_WAIT_TIMEOUT = 3600  # 1 hour
DEFAULT_POLL_INTERVAL = 120  # 2 minutes
DEFAULT_PRELOAD = False
DEFAULT_UNLOAD_AFTER_JOB = True


@dataclass
class MonitorConfig:
    """Configuration for the local model monitor."""

    enabled: bool = True
    policy: str = "wait"  # wait | cloud | never | force
    max_concurrent_models: int = DEFAULT_MAX_CONCURRENT
    wait_timeout_seconds: int = DEFAULT_WAIT_TIMEOUT
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL
    preload: bool = DEFAULT_PRELOAD
    unload_after_job: bool = DEFAULT_UNLOAD_AFTER_JOB
    quiet_seconds: int = 300
    probe_busy: bool = False


@dataclass
class LoadedModelInfo:
    """Snapshot of a single resident model."""

    backend: str  # lmstudio | ollama | llamacpp
    key: str  # model key / name
    our_model: bool = False  # True if it is one of ours


class LocalModelMonitor:
    """High-level monitor for local LLM lifecycle management."""

    def __init__(self, config: MonitorConfig | None = None):
        self.config = config or MonitorConfig()
        self._loaded_ours: set[str] = set()  # model keys we loaded
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _count_loaded(self) -> int:
        """Count how many models are currently resident across all backends."""
        count = 0
        # LM Studio
        count += self._lmstudio_loaded_count()
        # Ollama
        count += self._ollama_loaded_count()
        return count

    def _lmstudio_loaded_count(self) -> int:
        try:
            result = subprocess.run(
                ["lms", "ps"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return 0
            # Count non-empty lines that look like model entries.
            lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
            # Skip header lines.
            model_lines = [ln for ln in lines if not ln.lower().startswith(("model", "name", "---"))]
            return len(model_lines)
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return 0

    def _ollama_loaded_count(self) -> int:
        try:
            result = subprocess.run(
                ["ollama", "ps"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return 0
            lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
            model_lines = [ln for ln in lines if not ln.lower().startswith(("name", "model", "---"))]
            return len(model_lines)
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return 0

    def _is_our_model_loaded(self, model_key: str, backend: str) -> bool:
        """Check if our specific model is already resident."""
        model_key_lower = model_key.strip().lower()
        if backend == "lmstudio":
            try:
                result = subprocess.run(
                    ["lms", "ps"], capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and model_key_lower in result.stdout.lower():
                    return True
            except Exception:
                pass
        elif backend == "ollama":
            try:
                result = subprocess.run(
                    ["ollama", "ps"], capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and model_key_lower in result.stdout.lower():
                    return True
            except Exception:
                pass
        return model_key in self._loaded_ours

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    async def acquire(self, model_key: str, backend: str = "lmstudio") -> tuple[bool, str]:
        """Acquire a slot for *model_key* on *backend*.

        Returns ``(True, reason)`` when the model is loaded and ready, or
        ``(False, reason)`` when we gave up (use cloud fallback).

        * If the model is already loaded → return immediately.
        * If a slot is free (loaded count < max) → load and return.
        * Otherwise → wait, re-checking every ``poll_interval_seconds``,
          for up to ``wait_timeout_seconds``.
        """
        if not self.config.enabled:
            return False, "monitor disabled"

        if self.config.policy == "never":
            return False, "monitor policy 'never'"

        if self.config.policy == "force":
            await self._load(model_key, backend)
            return True, "policy 'force'"

        # Already loaded?
        if self._is_our_model_loaded(model_key, backend):
            logger.info("Model %s already loaded on %s", model_key, backend)
            self._loaded_ours.add(model_key)
            return True, "already loaded"

        # Check slot availability.
        deadline = time.monotonic() + self.config.wait_timeout_seconds
        while True:
            loaded = self._count_loaded()
            if loaded < self.config.max_concurrent_models:
                # Slot free – load our model.
                ok = await self._load(model_key, backend)
                if ok:
                    self._loaded_ours.add(model_key)
                    return True, f"loaded (was {loaded}/{self.config.max_concurrent_models})"
                return False, f"failed to load {model_key}"

            # Slot full – wait.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Waited %ds for a slot for %s, falling back to cloud",
                    self.config.wait_timeout_seconds, model_key,
                )
                return False, f"wait timeout ({self.config.wait_timeout_seconds}s) reached"

            wait = min(self.config.poll_interval_seconds, remaining)
            logger.info(
                "Slot full (%d/%d models loaded), waiting %.0fs for %s ...",
                loaded, self.config.max_concurrent_models, wait, model_key,
            )
            await asyncio.sleep(wait)

    async def _load(self, model_key: str, backend: str) -> bool:
        """Load *model_key* on *backend*. Returns True on success."""
        if backend == "lmstudio":
            try:
                from src.llm.local_coordinator import ensure_lmstudio_model
                return ensure_lmstudio_model(model_key)
            except Exception as exc:
                logger.warning("Failed to load %s on lmstudio: %s", model_key, exc)
                return False
        elif backend == "ollama":
            try:
                result = subprocess.run(
                    ["ollama", "run", model_key, "--verbose"],
                    capture_output=True, text=True, timeout=300,
                    input="",  # non-interactive
                )
                # ollama run may not return cleanly; check if model is now loaded.
                return self._is_our_model_loaded(model_key, backend)
            except Exception as exc:
                logger.warning("Failed to load %s on ollama: %s", model_key, exc)
                return False
        else:
            # llama.cpp: no model management, assume available.
            return True

    async def release(self, model_key: str, backend: str = "lmstudio") -> None:
        """Unload *model_key* from *backend* (if unload_after_job is set)."""
        if not self.config.unload_after_job:
            return
        if model_key not in self._loaded_ours:
            return
        logger.info("Releasing model %s from %s", model_key, backend)
        if backend == "lmstudio":
            try:
                from src.llm.local_coordinator import LocalBackend
                backend_obj = LocalBackend("lmstudio", "http://localhost:1234")
                # Find the loaded model and unload it.
                st = backend_obj.status()
                for m in st.loaded_llms:
                    if m.key.lower() == model_key.strip().lower():
                        backend_obj.unload(m)
                        break
            except Exception as exc:
                logger.warning("Failed to unload %s: %s", model_key, exc)
        elif backend == "ollama":
            try:
                subprocess.run(
                    ["ollama", "stop", model_key],
                    capture_output=True, text=True, timeout=30,
                )
            except Exception as exc:
                logger.warning("Failed to stop %s on ollama: %s", model_key, exc)
        self._loaded_ours.discard(model_key)

    async def preload(self, model_key: str, backend: str = "lmstudio") -> bool:
        """Preload *model_key* at startup. Returns True on success."""
        if not self.config.preload:
            return False
        logger.info("Preloading %s on %s", model_key, backend)
        ok = await self._load(model_key, backend)
        if ok:
            self._loaded_ours.add(model_key)
        return ok

    def status(self) -> dict[str, Any]:
        """Return a status dict for diagnostics."""
        return {
            "config": {
                "enabled": self.config.enabled,
                "policy": self.config.policy,
                "max_concurrent_models": self.config.max_concurrent_models,
                "wait_timeout_seconds": self.config.wait_timeout_seconds,
                "poll_interval_seconds": self.config.poll_interval_seconds,
                "preload": self.config.preload,
                "unload_after_job": self.config.unload_after_job,
            },
            "loaded_count": self._count_loaded(),
            "our_models": sorted(self._loaded_ours),
        }
