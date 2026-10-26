"""The on-disk cache of AI-proposed domain drafts.

Drafts live in `data/domains/ai/` (git-ignored). A draft records *which* specs
matter for an unknown product type, not how to extract them; a human promotes
it to a real profile module by adding extractors.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.output.domains.base import DomainProfile
from src.output.domains.registry import DOMAIN_REGISTRY
from src.text.normalize import fold

logger = logging.getLogger(__name__)

AI_DRAFT_DIR = Path("data/domains/ai")

_NAME_RE = re.compile(r"^[a-z0-9_]{2,32}$")
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower())


def save_draft(proposal, example_title: str, directory: Path) -> Path:
    """Write (or refresh) `data/domains/ai/<domain>.yaml` for one proposal."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slug(proposal.domain)}.yaml"

    created_at = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    examples: list[str] = []
    if path.exists():
        try:
            stored = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            stored = None
        if isinstance(stored, dict):
            # A refreshed draft keeps its history; only the age of the first
            # sighting and the example titles survive.
            created_at = stored.get("created_at") or created_at
            existing = stored.get("examples") or []
            if isinstance(existing, list):
                examples = [str(item) for item in existing]

    if example_title and example_title not in examples:
        examples.append(example_title)
    examples = examples[-3:]

    data = {
        "name": proposal.domain,
        "source": "ai",
        "created_at": created_at,
        "keywords": list(proposal.keywords),
        "key_specs": list(proposal.key_specs),
        "examples": examples,
    }
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _profile_from_draft(data) -> DomainProfile | None:
    """Validate the stored shape directly; a live proposal has extra rules."""
    if not isinstance(data, dict):
        return None

    name = data.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    if name in DOMAIN_REGISTRY:
        # A draft must never shadow a built-in profile.
        return None

    raw_keywords = data.get("keywords")
    if not isinstance(raw_keywords, list):
        return None
    keywords: list[str] = []
    for item in raw_keywords:
        if not isinstance(item, str):
            return None
        folded = fold(item)
        if folded and folded not in keywords:
            keywords.append(folded)
    if not 1 <= len(keywords) <= 6:
        return None
    if any(not 2 <= len(word) <= 32 for word in keywords):
        return None

    raw_specs = data.get("key_specs")
    if not isinstance(raw_specs, list):
        return None
    key_specs: list[str] = []
    for item in raw_specs:
        if not isinstance(item, str) or not _SNAKE_RE.match(item):
            return None
        if item not in key_specs:
            key_specs.append(item)
    if not 2 <= len(key_specs) <= 12:
        return None

    return DomainProfile(
        name=name,
        strong_keywords=tuple(keywords),
        key_specs=tuple(key_specs),
        source="ai",
    )


def load_drafts(directory: Path) -> dict[str, DomainProfile]:
    """Read every `*.yaml` draft; files that fail to parse are skipped."""
    drafts: dict[str, DomainProfile] = {}
    if not directory or not directory.is_dir():
        return drafts
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("skipping corrupt draft %s: %s", path.name, exc)
            continue
        profile = _profile_from_draft(data)
        if profile is None:
            # Spec section 10: a draft that does not validate is a warning,
            # not silence - an empty cache should be visible to the operator.
            logger.warning("draft %s does not validate; ignored", path.name)
            continue
        drafts[profile.name] = profile
    return drafts
