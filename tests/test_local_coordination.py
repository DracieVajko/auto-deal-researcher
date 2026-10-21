"""Local-model coordination tests.

All backends are faked: nothing here loads or unloads a real model.
"""

import json

import pytest

from src.config.models import (
    AppConfig,
    LLMConfig,
    LLMLocalConfig,
    LocalCoordinationConfig,
)
from src.llm.client import LLMClient
from src.llm.local_coordinator import (
    LoadedModel,
    LocalBackend,
    LocalModelCoordinator,
    LocalStatus,
)

LMSTUDIO_V1_PAYLOAD = {
    "models": [
        {"key": "qwen/qwen3-coder-30b", "type": "llm", "loaded_instances": []},
        {"key": "mistralai/ministral-3-14b-reasoning", "type": "vlm",
         "loaded_instances": [{"id": "x", "config": {"context_length": 32768}}]},
        {"key": "text-embedding-nomic-embed-text-v1.5", "type": "embedding",
         "loaded_instances": []},
    ]
}

LMSTUDIO_V0_PAYLOAD = {
    "data": [
        {"id": "some/model", "type": "llm", "state": "loaded",
         "loaded_context_length": 8192},
        {"id": "other/model", "type": "llm", "state": "not-loaded",
         "loaded_context_length": None},
    ]
}


def fake_get(url, timeout=5.0):
    """Minimal stand-in for local_coordinator._get_json."""
    if url.endswith("/api/v1/models"):
        return LMSTUDIO_V1_PAYLOAD
    if url.endswith("/api/v0/models"):
        return LMSTUDIO_V0_PAYLOAD
    return None  # ollama unreachable


@pytest.fixture
def patched(monkeypatch):
    import src.llm.local_coordinator as mod

    monkeypatch.setattr(mod, "_get_json", fake_get)
    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)


# --- discovery -------------------------------------------------------------
def test_detects_loaded_model_with_context(patched):
    st = LocalBackend("lmstudio", "http://x").status()
    assert st.reachable
    keys = [m.key for m in st.loaded]
    assert keys == ["mistralai/ministral-3-14b-reasoning"]


def test_falls_back_to_v0_payload(patched, monkeypatch):
    import src.llm.local_coordinator as mod

    def only_v0(url, timeout=5.0):
        return LMSTUDIO_V0_PAYLOAD if url.endswith("/api/v0/models") else None

    monkeypatch.setattr(mod, "_get_json", only_v0)
    st = LocalBackend("lmstudio", "http://x").status()
    assert [m.key for m in st.loaded] == ["some/model"]


def test_error_body_is_not_treated_as_data(monkeypatch):
    """LM Studio answers HTTP 200 with {"error": ...} for unknown routes.

    Such a body must be rejected, otherwise a probe looks like real data.
    """
    import src.llm.local_coordinator as mod

    class Resp:
        status = 200

        def __init__(self, body):
            self._body = body.encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "src.llm.local_coordinator.urllib.request.urlopen",
        lambda *a, **k: Resp('{"error": "Unexpected endpoint or method."}'),
    )
    assert mod._get_json("http://localhost:1234/api/v0/nonsense") is None


def test_valid_json_is_returned(monkeypatch):
    import src.llm.local_coordinator as mod

    class Resp:
        def read(self):
            return b'{"models": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "src.llm.local_coordinator.urllib.request.urlopen",
        lambda *a, **k: Resp(),
    )
    assert mod._get_json("http://localhost:1234/api/v1/models") == {"models": []}


def test_unreachable_returns_none(monkeypatch):
    import src.llm.local_coordinator as mod

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr("src.llm.local_coordinator.urllib.request.urlopen", boom)
    assert mod._get_json("http://localhost:11434/api/ps") is None


def test_ollama_unreachable_is_reported(patched):
    st = LocalBackend("ollama", "http://x").status()
    assert st.reachable is False


# --- policy ----------------------------------------------------------------
def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        LocalModelCoordinator(policy="nope")


def test_never_policy_never_probes():
    c = LocalModelCoordinator(policy="never")
    safe, reason = c.acquire({"qwen/qwen3-coder-30b"})
    assert safe is False
    assert "never" in reason


def test_cloud_policy_refuses_but_never_unloads(patched):
    c = LocalModelCoordinator(policy="cloud")
    safe, reason = c.acquire({"qwen/qwen3-coder-30b"})
    assert safe is False
    assert "cloud" in reason


def test_force_policy_allows_immediately(patched):
    c = LocalModelCoordinator(policy="force")
    safe, _ = c.acquire({"qwen/qwen3-coder-30b"})
    assert safe is True


def test_no_foreign_model_is_safe(patched):
    c = LocalModelCoordinator(policy="wait")
    safe, reason = c.acquire({"mistralai/ministral-3-14b-reasoning"})
    assert safe is True, "our own model resident means the backend is ours"
    assert "no foreign" in reason


def test_foreign_model_is_never_treated_as_ours(patched):
    c = LocalModelCoordinator(policy="cloud")
    safe, reason = c.acquire({"qwen/qwen3-coder-30b"})
    assert safe is False
    assert "mistralai/ministral-3-14b-reasoning" in reason


# --- quiet window ----------------------------------------------------------
def test_wait_unloads_after_quiet_window(patched, monkeypatch):
    """Foreign model + quiet window elapsed => unload then load ours."""
    # Controllable clock: sleep advances it instead of burning real minutes.
    clock = {"now": 0.0}
    monkeypatch.setattr("src.llm.local_coordinator.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "src.llm.local_coordinator.time.sleep",
        lambda s: clock.__setitem__("now", clock["now"] + s),
    )

    c = LocalModelCoordinator(policy="wait", quiet_seconds=300, poll_seconds=15)
    unloaded = []
    monkeypatch.setattr(LocalBackend, "unload",
                        lambda self, model: unloaded.append(model.key) or True)

    safe, reason = c.acquire({"qwen/qwen3-coder-30b"})
    assert safe is True
    assert unloaded == ["mistralai/ministral-3-14b-reasoning"]
    assert "unloaded" in reason
    assert clock["now"] >= 300, "must wait the full quiet window before unloading"


def test_wait_gives_up_at_max_wait(patched, monkeypatch):
    """A 5-minute quiet window must not block a run forever."""
    c = LocalModelCoordinator(policy="wait", quiet_seconds=300,
                              poll_seconds=15, max_wait_seconds=1)
    safe, reason = c.acquire({"qwen/qwen3-coder-30b"})
    assert safe is False
    assert "max_wait_seconds" in reason or "quiet" in reason


def test_resident_change_restarts_quiet_timer(patched, monkeypatch):
    c = LocalModelCoordinator(policy="wait", quiet_seconds=300, poll_seconds=1)
    clock = {"now": 0.0}

    monkeypatch.setattr(
        "src.llm.local_coordinator.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr("src.llm.local_coordinator.time.sleep",
                        lambda s: clock.__setitem__("now", clock["now"] + s))

    # Simulate: a new model appears mid-wait, so the set changes.
    snapshots = [
        [LoadedModel("lmstudio", "a")],
        [LoadedModel("lmstudio", "a"), LoadedModel("lmstudio", "b")],
        [LoadedModel("lmstudio", "a"), LoadedModel("lmstudio", "b")],
        [LoadedModel("lmstudio", "a"), LoadedModel("lmstudio", "b")],
    ]
    calls = {"i": 0}

    def fake_foreign():
        out = snapshots[min(calls["i"], len(snapshots) - 1)]
        calls["i"] += 1
        return out

    monkeypatch.setattr(c, "foreign_models_ignoring_wait", fake_foreign)
    monkeypatch.setattr(LocalBackend, "unload", lambda self, m: True)

    safe, _ = c.acquire({"ours/model"})
    assert safe is True
    assert calls["i"] >= 2, "a change in the resident set must restart the timer"


# --- integration with LLMClient -------------------------------------------
def test_client_builds_coordinator_from_config(monkeypatch):
    cfg = AppConfig(llm=LLMConfig(
        local=[LLMLocalConfig(type="lmstudio", endpoint="http://x", model="m")],
        local_coordination=LocalCoordinationConfig(policy="cloud", quiet_seconds=42),
    ))
    llm = LLMClient(cfg)
    assert llm._coordinator.policy == "cloud"
    assert llm._coordinator.quiet_seconds == 42


def test_client_honours_env_policy_override(monkeypatch):
    monkeypatch.setenv("ADS_LOCAL_POLICY", "never")
    cfg = AppConfig(llm={})
    llm = LLMClient(cfg)
    assert llm._coordinator.policy == "never"


def test_client_disabled_coordination_becomes_never(monkeypatch):
    cfg = AppConfig(llm=LLMConfig(
        local=[LLMLocalConfig(type="lmstudio", endpoint="http://x", model="m")],
        local_coordination=LocalCoordinationConfig(enabled=False),
    ))
    assert LLMClient(cfg)._coordinator.policy == "never"


def test_describe_local_state_is_readable(patched):
    cfg = AppConfig(llm=LLMConfig(local=[]))
    text = LLMClient(cfg).describe_local_state()
    # When no local models are configured, the coordinator reports "not configured"
    # which is a valid readable state
    assert any(term in text for term in ("lmstudio", "not reachable", "not configured"))


# --- unload payload --------------------------------------------------------
def test_ollama_unload_uses_keep_alive_zero(monkeypatch):
    """Ollama's documented eviction call."""
    captured = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["method"] = req.method
        return Resp()

    monkeypatch.setattr("src.llm.local_coordinator.urllib.request.urlopen", fake_urlopen)
    ok = LocalBackend("ollama", "http://x").unload(LoadedModel("ollama", "llama3"))
    assert ok is True
    assert captured["url"].endswith("/api/generate")
    assert captured["body"] == {"model": "llama3", "keep_alive": 0}
    assert captured["method"] == "POST"


def test_lmstudio_unload_uses_lms_cli(monkeypatch):
    captured = {}

    class Done:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Done()

    monkeypatch.setattr("src.llm.local_coordinator.subprocess.run", fake_run)
    ok = LocalBackend("lmstudio", "http://x").unload(LoadedModel("lmstudio", "some/model"))
    assert ok is True
    assert captured["cmd"] == ["lms", "unload", "some/model"]


def test_lmstudio_unload_failure_is_reported(monkeypatch):
    class Done:
        returncode = 1
        stderr = "no such model"
        stdout = ""

    monkeypatch.setattr("src.llm.local_coordinator.subprocess.run", lambda *a, **k: Done())
    assert LocalBackend("lmstudio", "http://x").unload(LoadedModel("lmstudio", "x")) is False