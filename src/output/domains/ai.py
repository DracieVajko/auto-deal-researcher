"""Ask the LLM to name an unknown product domain, and validate what it returns.

Spec section 7: the model proposes a domain, its keywords and the specs worth
tracking. The proposal is only ever trusted after `validate_proposal`, and it
becomes a draft file, never source code.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from src.output.domains.base import DomainProfile
from src.output.domains.registry import DOMAIN_REGISTRY
from src.text.normalize import fold

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9_]{2,32}$")
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

_SYSTEM = (
    "You classify a second-hand listing into a product domain that a fixed "
    "registry does not know. Reply with exactly one JSON object and nothing "
    "else."
)


@dataclass
class DomainProposal:
    """A model's answer for an unknown product type, already validated."""

    domain: str
    keywords: list[str] = field(default_factory=list)
    key_specs: list[str] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)


def _reject(reason: str) -> None:
    logger.warning("AI domain proposal rejected: %s", reason)


def validate_proposal(payload: dict) -> DomainProposal | None:
    """Enforce spec section 7.3; return None (and log why) on any violation."""
    if not isinstance(payload, dict):
        _reject("payload is not a JSON object")
        return None

    domain = payload.get("domain")
    if not isinstance(domain, str) or not _NAME_RE.match(domain):
        _reject(f"invalid domain name {domain!r}")
        return None
    if domain in DOMAIN_REGISTRY:
        _reject(f"{domain} is a built-in name")
        return None

    raw_keywords = payload.get("keywords")
    if not isinstance(raw_keywords, list) or not raw_keywords:
        _reject("keywords must be a non-empty list")
        return None
    keywords: list[str] = []
    for item in raw_keywords:
        if not isinstance(item, str):
            _reject("a keyword is not a string")
            return None
        folded = fold(item)
        if folded and folded not in keywords:
            keywords.append(folded)
    if not 1 <= len(keywords) <= 6:
        _reject(f"{len(keywords)} keywords, expected 1-6")
        return None
    if any(not 2 <= len(word) <= 32 for word in keywords):
        _reject("a keyword is shorter than 2 or longer than 32 characters")
        return None

    raw_specs = payload.get("key_specs")
    if not isinstance(raw_specs, list):
        _reject("key_specs must be a list")
        return None
    key_specs: list[str] = []
    for item in raw_specs:
        if not isinstance(item, str) or not _SNAKE_RE.match(item):
            _reject(f"invalid spec key {item!r}")
            return None
        if item not in key_specs:
            key_specs.append(item)
    if not 2 <= len(key_specs) <= 12:
        _reject(f"{len(key_specs)} key specs, expected 2-12")
        return None

    specs = payload.get("specs")
    if not isinstance(specs, dict):
        _reject("specs must be an object")
        return None
    for key, value in specs.items():
        if not isinstance(value, str) or not value.strip():
            _reject(f"spec {key!r} has an empty value")
            return None
        if len(value) > 60 or "\n" in value:
            _reject(f"spec {key!r} is too long or multi-line")
            return None
    if not any(key in specs for key in key_specs):
        _reject("key_specs shares no key with the stated specs")
        return None

    return DomainProposal(
        domain=domain, keywords=keywords, key_specs=key_specs, specs=dict(specs)
    )


def _parse_object(response: str) -> dict | None:
    """Take the first JSON object out of a model reply, tolerating fences."""
    if not response:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.strip(), flags=re.IGNORECASE)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def propose_domain(
    llm, text: str, prompt: str | None
) -> DomainProposal | None:
    """One model call that names the domain of an unrecognised listing."""
    user = (
        f"Listing text:\n{text[:1000]}\n\n"
        + (f"User request: {prompt}\n\n" if prompt else "")
        + 'Return {"domain": "...", "keywords": ["..."], "key_specs": ["..."], '
        '"specs": {"key": "value"}} where domain is a short snake_case product '
        "type, keywords are 1-6 words that identify this product type in a "
        "listing - use words exactly as they appear in the listing text above, "
        "at least one keyword must be a single word taken from it; a phrase "
        "keyword is only accepted in addition to such a word. key_specs are "
        "2-12 snake_case specifications a buyer of this product type cares "
        "about, and specs contains ONLY values stated in the listing."
    )
    try:
        response = await llm._chat(_SYSTEM, user, max_tokens=600, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 - a failed proposal is not an error
        logger.debug("AI domain proposal call failed: %s", exc)
        return None
    payload = _parse_object(response)
    if payload is None:
        _reject("model reply was not a JSON object")
        return None
    return validate_proposal(payload)


def proposal_to_profile(proposal: DomainProposal) -> DomainProfile:
    """Turn a validated proposal into a profile with no deterministic extractors."""
    return DomainProfile(
        name=proposal.domain,
        strong_keywords=tuple(proposal.keywords),
        key_specs=tuple(proposal.key_specs),
        source="ai",
    )
