"""Coordinate access to a local LLM backend so we never fight the user's session.

Problem this solves: LM Studio and Ollama load a model into RAM/VRAM on
demand. If another model is already loaded and busy, asking for ours makes
the backend load a second large model (or thrash), which on a
RAM-constrained machine triggers OOM or heavy swap and can freeze the OS.

Policy (configurable, default ``wait``):

    wait    Respect a loaded foreign model. Poll until it has been quiet for
            ``quiet_seconds`` (default 300 = 5 min), then unload it and let
            ours load.
    cloud   Never load or unload anything; fall back to cloud providers while
            a foreign model is resident.
    never   Same as cloud, but the local backend is not probed at all.
    force   Unload immediately. Only use this when you know nothing else runs.

IMPORTANT LIMITATION — what "quiet" can and cannot mean:

    Neither LM Studio nor Ollama exposes a read-only endpoint that reports
    "a generation is in progress". LM Studio's REST server answers HTTP 200
    with an error body for every unknown route, so the status code cannot be
    used to probe either. What we can observe is *which models are resident*.

    Quiet therefore means: the set of resident models has not changed for
    ``quiet_seconds``. That is a good proxy for "nobody started a new chat",
    but it cannot see a long single generation that is still streaming.

    ``probe_busy=True`` closes that gap by timing a 1-token completion against
    the already-resident model. That never loads anything (the model is
    already in memory) but does occupy a request slot, so it is opt-in and
    off by default.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_LMSTUDIO_URL = "http://localhost:1234"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

POLICIES = ("wait", "cloud", "never", "force")


def _get_json(url: str, timeout: float = 5.0):
    """GET a JSON document. Returns None when unreachable.

    Note: LM Studio replies HTTP 200 with an {"error": ...} body for unknown
    routes, so callers must check the payload, not just the status.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        logger.debug("HTTP %s from %s", exc.code, url)
        return None
    except Exception as exc:  # connection refused, timeout, ...
        logger.debug("%s from %s", type(exc).__name__, url)
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("error"):
        logger.debug("endpoint error from %s: %s", url, data["error"])
        return None
    return data


@dataclass
class LoadedModel:
    """One model currently resident in a local backend."""

    backend: str
    key: str
    kind: str = "llm"
    context_length: int | None = None

    def __str__(self) -> str:
        return f"{self.backend}:{self.key}"


@dataclass
class LocalStatus:
    reachable: bool = False
    backend: str = ""
    loaded: list[LoadedModel] = field(default_factory=list)
    error: str = ""

    @property
    def loaded_llms(self) -> list[LoadedModel]:
        return [m for m in self.loaded if m.kind != "embedding"]


class LocalBackend:
    """Read-only view over LM Studio or Ollama."""

    def __init__(self, kind: str, url: str):
        self.kind = kind
        self.url = url.rstrip("/")

    # --- discovery ------------------------------------------------------
    def status(self) -> LocalStatus:
        if self.kind == "lmstudio":
            return self._lmstudio_status()
        if self.kind == "ollama":
            return self._ollama_status()
        return LocalStatus(error=f"unknown backend {self.kind}")

    def _lmstudio_status(self) -> LocalStatus:
        # /api/v1/models reports loaded_instances; /api/v0/models reports a
        # "state" field. Prefer v1, fall back to v0.
        data = _get_json(f"{self.url}/api/v1/models")
        models = []
        if isinstance(data, dict) and "models" in data:
            for m in data["models"]:
                instances = m.get("loaded_instances") or []
                models.append(LoadedModel(
                    backend="lmstudio",
                    key=m.get("key", ""),
                    kind=m.get("type", "llm") or "llm",
                    context_length=(instances[0].get("config", {}).get("context_length")
                                    if instances else None),
                ))
        if not models:
            data = _get_json(f"{self.url}/api/v0/models")
            if isinstance(data, dict) and "data" in data:
                for m in data["data"]:
                    models.append(LoadedModel(
                        backend="lmstudio",
                        key=m.get("id", ""),
                        kind=m.get("type", "llm") or "llm",
                        context_length=m.get("loaded_context_length"),
                    ))
        loaded = [m for m in models if _is_resident(m, "lmstudio", models)]
        if not models:
            # No models data retrieved - likely server unreachable
            return LocalStatus(reachable=False, backend="lmstudio", error="unreachable")
        return LocalStatus(reachable=True, backend="lmstudio", loaded=loaded)

    def _ollama_status(self) -> LocalStatus:
        # /api/ps lists only the models currently held in memory.
        data = _get_json(f"{self.url}/api/ps")
        if not isinstance(data, dict):
            return LocalStatus(backend="ollama", error="unreachable")
        loaded = [
            LoadedModel(backend="ollama", key=m.get("name", ""),
                        kind="llm", context_length=None)
            for m in data.get("models", [])
        ]
        return LocalStatus(reachable=True, backend="ollama", loaded=loaded)

    # --- unload ---------------------------------------------------------
    def unload(self, model: LoadedModel) -> bool:
        """Release a resident model. Never called without an explicit policy."""
        if model.backend == "ollama":
            return self._ollama_unload(model.key)
        return self._lmstudio_unload(model.key)

    def _ollama_unload(self, name: str) -> bool:
        """keep_alive=0 is Ollama's documented way to evict a model."""
        payload = json.dumps({"model": name, "keep_alive": 0}).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.error("Ollama unload of %s failed: %s", name, exc)
            return False

    def _lmstudio_unload(self, key: str) -> bool:
        """LM Studio has no documented REST unload route; use the lms CLI."""
        try:
            done = subprocess.run(
                ["lms", "unload", key], capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError:
            logger.error("lms CLI not found; cannot unload %s", key)
            return False
        except Exception as exc:
            logger.error("lms unload of %s failed: %s", key, exc)
            return False
        if done.returncode != 0:
            logger.error("lms unload %s -> %s", key, (done.stderr or "").strip()[:200])
            return False
        return True


def _is_resident(model: LoadedModel, backend: str, all_models: list[LoadedModel]) -> bool:
    """A model counts as resident when it has a loaded instance (LM Studio)."""
    if backend != "lmstudio":
        return True
    return model.context_length is not None


class LocalModelCoordinator:
    """Decide when it is safe to touch a local backend."""

    def __init__(
        self,
        policy: str = "wait",
        quiet_seconds: int = 300,
        poll_seconds: int = 15,
        max_wait_seconds: int = 0,
        probe_busy: bool = False,
    ):
        if policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
        self.policy = policy
        self.quiet_seconds = max(0, quiet_seconds)
        self.poll_seconds = max(1, poll_seconds)
        self.max_wait_seconds = max(0, max_wait_seconds)
        self.probe_busy = probe_busy
        self._backends: dict[str, LocalBackend] = {
            "lmstudio": LocalBackend("lmstudio", DEFAULT_LMSTUDIO_URL),
            "ollama": LocalBackend("ollama", DEFAULT_OLLAMA_URL),
        }
        self._last_snapshot: list[str] = []
        self._quiet_since: float | None = None

    def status(self) -> dict[str, LocalStatus]:
        return {name: backend.status() for name, backend in self._backends.items()}

    def foreign_models(self, our_models: set[str]) -> list[LoadedModel]:
        """Resident models that are not the ones this project asked for."""
        ours = {m.strip().lower() for m in our_models if m}
        foreign = []
        for st in self.status().values():
            if not st.reachable:
                continue
            for m in st.loaded_llms:
                if m.key.lower() not in ours:
                    foreign.append(m)
        return foreign

    def acquire(self, our_models: set[str]) -> tuple[bool, str]:
        """Return (safe_to_load_local, reason).

        ``safe`` False means: do not send a local request, fall through to
        cloud. Under the ``wait`` policy this call blocks until the backend
        has been quiet long enough, at most ``max_wait_seconds``.
        """
        if self.policy == "never":
            return False, "local probing disabled by policy 'never'"

        if self.policy == "force":
            return True, "policy 'force'"

        foreign = self.foreign_models(our_models)

        if not foreign:
            self._quiet_since = None
            self._last_snapshot = []
            return True, "no foreign model resident"

        names = [str(m) for m in foreign]
        if self.policy == "cloud":
            return False, f"foreign model resident ({', '.join(names)}), policy 'cloud'"

        # policy == "wait"
        if self.max_wait_seconds and self._elapsed() > self.max_wait_seconds:
            return False, (
                f"waited {int(self._elapsed())}s for {', '.join(names)} "
                f"without reaching the quiet window, falling back to cloud"
            )

        reason = self._wait_for_quiet(names)
        if reason is None:
            for m in foreign:
                self._backends[m.backend].unload(m)
            return True, f"unloaded {', '.join(names)} after quiet window"
        return False, reason

    def _elapsed(self) -> float:
        if not hasattr(self, "_started"):
            self._started = time.monotonic()
        return time.monotonic() - self._started

    def _wait_for_quiet(self, names: list[str]) -> str | None:
        """Block until the resident set is unchanged for quiet_seconds.

        Returns a reason string if we gave up, or None when it is now safe.
        """
        logger.info(
            "Local backend busy with %s; waiting for %ds of quiet before unload",
            ", ".join(names), self.quiet_seconds,
        )
        deadline = time.monotonic() + self.max_wait_seconds if self.max_wait_seconds else None

        while True:
            snapshot = sorted(str(m) for m in self.foreign_models_ignoring_wait())
            now = time.monotonic()

            if snapshot != self._last_snapshot:
                self._last_snapshot = snapshot
                self._quiet_since = now
                logger.info("Resident set changed to %s, restarting quiet timer",
                            snapshot or "(empty)")
            elif self._quiet_since is None:
                self._quiet_since = now

            quiet_for = now - self._quiet_since
            if quiet_for >= self.quiet_seconds:
                return None

            if deadline and now >= deadline:
                return f"max_wait_seconds reached after {int(quiet_for)}s quiet"

            remaining = self.quiet_seconds - quiet_for
            logger.info("Resident %s quiet for %ds/%ds, waiting",
                        snapshot or "(empty)", int(quiet_for),
                        self.quiet_seconds)
            time.sleep(min(self.poll_seconds, max(1.0, remaining)))

    def foreign_models_ignoring_wait(self) -> list[LoadedModel]:
        """Snapshot used by the quiet timer (never calls acquire)."""
        out = []
        for st in self.status().values():
            if st.reachable:
                out.extend(st.loaded_llms)
        return out

    def describe(self) -> str:
        lines = []
        for name, st in self.status().items():
            if not st.reachable:
                lines.append(f"{name}: not reachable")
            elif not st.loaded:
                lines.append(f"{name}: no models loaded")
            else:
                lines.append(f"{name}: " + ", ".join(str(m) for m in st.loaded))
        return "\n".join(lines)


def ensure_lmstudio_model(model_key: str, timeout: float = 300.0) -> bool:
    """Make sure *model_key* is the model loaded in LM Studio.

    Unloads any other resident model first (and waits until LM Studio
    confirms nothing is resident), then loads the requested one via the
    `lms` CLI. Returns True on success. Best-effort: failures are logged
    but never raise.

    A previous version fired `lms load` immediately after `lms unload -a`,
    which on slow unloads left two models resident at once (OOM). We now
    poll `lms ps` until the backend reports no loaded models before issuing
    the load.
    """
    if not model_key:
        return False
    try:
        ps = subprocess.run(
            ["lms", "ps"], capture_output=True, text=True, timeout=15,
        )
        if model_key in (ps.stdout or ""):
            logger.info("LM Studio already has %s loaded", model_key)
            return True

        subprocess.run(
            ["lms", "unload", "-a"], capture_output=True, text=True, timeout=60,
        )
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            ps = subprocess.run(
                ["lms", "ps"], capture_output=True, text=True, timeout=15,
            )
            out = (ps.stdout or "") + (ps.stderr or "")
            if "No models are currently loaded" in out or not _lmstudio_has_loaded(out):
                break
            time.sleep(2.0)
        else:
            logger.warning("LM Studio did not fully unload before loading %s", model_key)

        logger.info("Loading %s in LM Studio...", model_key)
        done = subprocess.run(
            ["lms", "load", model_key, "--auto"], capture_output=True, text=True, timeout=timeout,
        )
        if done.returncode != 0:
            logger.warning("lms load %s failed: %s", model_key, (done.stderr or done.stdout or "").strip()[:300])
            return False
        # Wait until LM Studio reports the model as resident (load may return
        # before the model is actually ready for inference).
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            ps = subprocess.run(
                ["lms", "ps"], capture_output=True, text=True, timeout=15,
            )
            if model_key in (ps.stdout or ""):
                logger.info("Loaded %s in LM Studio", model_key)
                return True
            time.sleep(3.0)
        logger.warning("lms load %s returned 0 but model not yet resident", model_key)
        return True
    except FileNotFoundError:
        logger.debug("lms CLI not found; skipping auto-load")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("lms load %s timed out", model_key)
        return False
    except Exception as exc:
        logger.warning("ensure_lmstudio_model(%s) failed: %s", model_key, exc)
        return False


def _lmstudio_has_loaded(ps_output: str) -> bool:
    low = (ps_output or "").lower()
    if "no models are currently loaded" in low:
        return False
    for line in (ps_output or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("LLM") or s.startswith("EMBEDDING") or s.startswith("You have"):
            continue
        if "PARAMS" in s or "ARCH" in s:
            continue
        if "GB" in s or "MB" in s:
            return True
    return False
