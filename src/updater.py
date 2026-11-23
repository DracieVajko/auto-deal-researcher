"""Auto-update helpers for pulling the latest code from GitHub.

The application is distributed as a git checkout, so "updating" means
fetching the configured branch from ``origin`` (GitHub) and fast-forwarding
the local working tree, optionally reinstalling dependencies afterwards.

All subprocess calls go through the module-level ``subprocess`` so tests can
monkeypatch ``src.updater.subprocess.run``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/DracieVajko/auto-deal-researcher.git"
DEFAULT_BRANCH = "master"
DEFAULT_REMOTE = "origin"


def _repo_root() -> Path:
    """Best-effort location of the project root (directory containing .git)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    # Fallback: three levels up from src/updater.py
    return here.parents[2]


@dataclass
class UpdateResult:
    """Outcome of an update check or update attempt."""

    update_available: bool = False
    current_commit: str = ""
    latest_commit: str = ""
    branch: str = DEFAULT_BRANCH
    remote: str = DEFAULT_REMOTE
    message: str = ""
    success: bool = True
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:  # allows `if result:`
        return bool(self.update_available or self.success)


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = False,
    timeout: int = 120,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )


def get_repo_root(repo_dir: str | Path | None = None) -> Path:
    if repo_dir is not None:
        return Path(repo_dir).resolve()
    env = os.environ.get("ADS_REPO_DIR")
    if env:
        return Path(env).resolve()
    return _repo_root()


def _git(repo_dir: Path, *args: str, check: bool = False, timeout: int = 120) -> subprocess.CompletedProcess:
    return _run(["git", *args], cwd=repo_dir, check=check, timeout=timeout)


def current_commit(repo_dir: str | Path | None = None, branch: str = DEFAULT_BRANCH) -> str:
    root = get_repo_root(repo_dir)
    try:
        cp = _git(root, "rev-parse", "HEAD")
        return (cp.stdout or "").strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("current_commit failed: %s", exc)
        return ""


def remote_commit(
    repo_dir: str | Path | None = None,
    branch: str = DEFAULT_BRANCH,
    remote: str = DEFAULT_REMOTE,
) -> str:
    root = get_repo_root(repo_dir)
    try:
        cp = _git(root, "ls-remote", remote, f"refs/heads/{branch}", timeout=60)
        line = (cp.stdout or "").strip().splitlines()
        if line:
            return line[0].split()[0].strip()
    except Exception as exc:
        logger.debug("remote_commit failed: %s", exc)
    # Fallback: fetch + rev-parse
    try:
        _git(root, "fetch", remote, branch, timeout=120)
        cp = _git(root, "rev-parse", f"{remote}/{branch}")
        return (cp.stdout or "").strip()
    except Exception as exc:
        logger.debug("remote_commit fallback failed: %s", exc)
    return ""


def check_for_updates(
    repo_dir: str | Path | None = None,
    branch: str = DEFAULT_BRANCH,
    remote: str = DEFAULT_REMOTE,
) -> UpdateResult:
    """Check whether a newer commit is available on the remote branch."""
    root = get_repo_root(repo_dir)
    result = UpdateResult(branch=branch, remote=remote)
    try:
        cur = current_commit(root, branch)
        lat = remote_commit(root, branch, remote)
        result.current_commit = cur
        result.latest_commit = lat
        if cur and lat:
            result.update_available = cur != lat
            result.message = (
                "Update available." if result.update_available else "Already up to date."
            )
        elif not cur:
            result.success = False
            result.error = "Not a git repository or unable to read HEAD."
            result.message = result.error
        else:
            result.success = False
            result.error = "Unable to reach remote."
            result.message = result.error
    except Exception as exc:
        result.success = False
        result.error = str(exc)
        result.message = str(exc)
    return result


def has_update(*args: Any, **kwargs: Any) -> bool:
    return bool(check_for_updates(*args, **kwargs).update_available)


def is_update_available(*args: Any, **kwargs: Any) -> bool:
    return has_update(*args, **kwargs)


def _ensure_clean_or_stash(root: Path, stash: bool) -> tuple[bool, str]:
    cp = _git(root, "status", "--porcelain")
    dirty = (cp.stdout or "").strip()
    if not dirty:
        return True, ""
    if not stash:
        return False, "Working tree has uncommitted changes; pass stash=True to stash them."
    st = _git(root, "stash", "push", "-m", "auto-update", timeout=60)
    if st.returncode != 0:
        return False, (st.stderr or st.stdout or "stash failed").strip()
    return True, "stashed"


def update_from_github(
    repo_dir: str | Path | None = None,
    branch: str = DEFAULT_BRANCH,
    remote: str = DEFAULT_REMOTE,
    install_deps: bool = True,
    stash: bool = False,
    fast_forward_only: bool = True,
) -> UpdateResult:
    """Fetch and fast-forward the local checkout to the remote branch."""
    root = get_repo_root(repo_dir)
    result = check_for_updates(root, branch, remote)
    result.details = {"install_deps": install_deps, "stash": stash}

    if not result.success and result.error and "Unable to reach" in (result.error or ""):
        # allow proceeding to pull anyway
        pass

    if not result.update_available and result.current_commit and result.latest_commit:
        result.message = "Already up to date."
        # Still allow forced pull? We'll return.
        result.success = True
        return result

    ok, msg = _ensure_clean_or_stash(root, stash)
    if not ok:
        result.success = False
        result.error = msg
        result.message = msg
        return result

    try:
        fetch = _git(root, "fetch", remote, branch, timeout=300)
        if fetch.returncode != 0:
            raise RuntimeError((fetch.stderr or fetch.stdout or "fetch failed").strip())

        if fast_forward_only:
            pull = _git(root, "pull", "--ff-only", remote, branch, timeout=300)
        else:
            pull = _git(root, "pull", remote, branch, timeout=300)
        if pull.returncode != 0:
            raise RuntimeError((pull.stderr or pull.stdout or "pull failed").strip())

        result.current_commit = current_commit(root, branch)
        result.latest_commit = remote_commit(root, branch, remote) or result.latest_commit
        result.update_available = False
        result.success = True
        result.message = "Updated successfully."

        if install_deps:
            req = root / "requirements.txt"
            if req.exists():
                try:
                    dep = _run(
                        [sys.executable, "-m", "pip", "install", "-r", str(req)],
                        cwd=root,
                        timeout=600,
                    )
                    result.details["deps_returncode"] = dep.returncode
                    result.details["deps_stdout"] = (dep.stdout or "")[-2000:]
                    if dep.returncode != 0:
                        result.details["deps_stderr"] = (dep.stderr or "")[-2000:]
                        logger.warning("Dependency reinstall failed: %s", dep.stderr)
                except Exception as exc:
                    result.details["deps_error"] = str(exc)
                    logger.warning("Dependency reinstall error: %s", exc)
    except Exception as exc:
        result.success = False
        result.error = str(exc)
        result.message = str(exc)
    return result


def pull_updates(*args: Any, **kwargs: Any) -> UpdateResult:
    return update_from_github(*args, **kwargs)


def perform_update(*args: Any, **kwargs: Any) -> UpdateResult:
    return update_from_github(*args, **kwargs)


def auto_update(*args: Any, **kwargs: Any) -> UpdateResult:
    return update_from_github(*args, **kwargs)


class GitHubUpdater:
    """Object-oriented wrapper around the module functions."""

    def __init__(
        self,
        repo_dir: str | Path | None = None,
        remote_url: str = REPO_URL,
        branch: str = DEFAULT_BRANCH,
        remote: str = DEFAULT_REMOTE,
    ) -> None:
        self.repo_dir = repo_dir
        self.remote_url = remote_url
        self.branch = branch
        self.remote = remote

    def check_for_updates(self) -> UpdateResult:
        return check_for_updates(self.repo_dir, self.branch, self.remote)

    def has_update(self) -> bool:
        return has_update(self.repo_dir, self.branch, self.remote)

    def update(self, **kwargs: Any) -> UpdateResult:
        kwargs.setdefault("branch", self.branch)
        kwargs.setdefault("remote", self.remote)
        kwargs.setdefault("repo_dir", self.repo_dir)
        return update_from_github(**kwargs)

    # aliases
    check = check_for_updates
    pull = update
    run = update


# Back-compat alias names
Updater = GitHubUpdater
AutoUpdater = GitHubUpdater
AutoUpdate = GitHubUpdater


__all__ = [
    "UpdateResult",
    "GitHubUpdater",
    "Updater",
    "AutoUpdater",
    "AutoUpdate",
    "check_for_updates",
    "has_update",
    "is_update_available",
    "update_from_github",
    "pull_updates",
    "perform_update",
    "auto_update",
    "current_commit",
    "remote_commit",
    "get_repo_root",
    "REPO_URL",
    "DEFAULT_BRANCH",
    "DEFAULT_REMOTE",
]
