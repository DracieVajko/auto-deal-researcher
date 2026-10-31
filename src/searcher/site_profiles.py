"""Site mapping profiles: search URL, filter descriptors and extraction selectors.

Profiles are deliberately data-only. They contain no cookies, headers, HTML,
screenshots or credentials; raw discovery recordings stay under ``flows/``.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse, urlunparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

PROFILE_DIR = Path(__file__).resolve().parent / "site_profiles"

ProfileStatus = Literal["draft", "validated", "failed", "needs_login", "blocked", "needs_manual"]
FilterSource = Literal["heuristic", "llm", "manual", "adapter"]
UiKind = Literal["input", "select", "checkbox", "radio", "button"]

SECRET_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "csrf",
    "header",
    "headers",
    "html",
    "key",
    "password",
    "screenshot",
    "screenshots",
    "session",
    "sid",
    "signature",
    "storage_state",
    "token",
}
SECRET_QUERY_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "cookie",
    "csrf",
    "key",
    "password",
    "session",
    "sid",
    "signature",
    "token",
}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _sanitize_url(value: str) -> str:
    if not value.lower().startswith(("http://", "https://")):
        return value
    parsed = urlparse(value)
    if parsed.query:
        kept = []
        for part in parsed.query.split("&"):
            name = part.split("=", 1)[0].strip().lower()
            if name and name not in SECRET_QUERY_KEYS:
                kept.append(part)
        query = "&".join(kept)
    else:
        query = ""
    netloc = parsed.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment))


def _redact_pii(value: str) -> str:
    return EMAIL_RE.sub("[redacted-email]", value)


def _sanitize_value(value):
    if isinstance(value, dict):
        return sanitize_profile_data(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_pii(_sanitize_url(value))
    return value


def sanitize_profile_data(data: dict) -> dict:
    """Return a copy of *data* without credentials, raw page data or PII."""
    if not isinstance(data, dict):
        return {}
    clean: dict = {}
    for key, value in data.items():
        key_text = str(key)
        if key_text.strip().lower() in SECRET_KEYS:
            continue
        clean[key_text] = _sanitize_value(value)
    return clean


class UrlFilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    param: str = Field(min_length=1)
    value_map: dict[str, str] = Field(default_factory=dict)


class UiFilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: UiKind
    selector: str = Field(min_length=1)
    value_map: dict[str, str] = Field(default_factory=dict)
    wait_selector: str | None = None


class FilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: UrlFilterSpec | None = None
    ui: UiFilterSpec | None = None
    source: FilterSource = "heuristic"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sample_value: str | None = None

    @model_validator(mode="after")
    def _has_target(self):
        if self.url is None and self.ui is None:
            msg = "FilterSpec needs at least one of url or ui"
            raise ValueError(msg)
        return self


class ProfileFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_min: FilterSpec | None = None
    price_max: FilterSpec | None = None
    condition: FilterSpec | None = None
    brand: FilterSpec | None = None
    location: FilterSpec | None = None
    shipping: FilterSpec | None = None
    seller_type: FilterSpec | None = None
    sort: FilterSpec | None = None
    extras: dict[str, FilterSpec] = Field(default_factory=dict)


class SearchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url_template: str | None = None
    query_param: str | None = None
    input_selector: str | None = None
    submit_selector: str | None = None
    category_urls: dict[str, str] = Field(default_factory=dict)


class ExtractionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_selector: str | None = None
    title_selector: str | None = None
    price_selector: str | None = None
    link_selector: str | None = None
    image_selector: str | None = None
    condition_selector: str | None = None
    seller_selector: str | None = None
    seller_type_selector: str | None = None
    location_selector: str | None = None
    shipping_selector: str | None = None
    brand_selector: str | None = None
    next_page_selector: str | None = None


class SiteProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    site_id: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    status: ProfileStatus = "draft"
    last_verified: date | None = None
    # Currency the shop lists prices in (EUR, CZK, ...). Used to convert
    # prices that carry no symbol in the listing text.
    currency: str = "EUR"
    search: SearchSpec = Field(default_factory=SearchSpec)
    filters: ProfileFilters = Field(default_factory=ProfileFilters)
    extraction: ExtractionSpec = Field(default_factory=ExtractionSpec)
    notes: str = ""

    @property
    def is_runtime_ready(self) -> bool:
        """True when a generic adapter can build a query URL and parse cards."""
        has_query_url = bool(self.search.query_param) or any(
            "{query}" in url
            for url in (self.search.category_urls or {}).values()
        ) or "{query}" in (self.search.url_template or "")
        return self.status == "validated" and has_query_url and bool(self.extraction.item_selector)


def _profile_path(site_id: str, directory: Path | None = None) -> Path:
    return (directory or PROFILE_DIR) / f"{site_id}.yaml"


def load_profile(site_id: str, directory: Path | None = None) -> SiteProfile | None:
    """Load one profile, returning None for missing, broken or unsafe data."""
    path = _profile_path(site_id, directory)
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        clean = sanitize_profile_data(raw)
        return SiteProfile.model_validate(clean)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("Ignoring invalid site profile %s: %s", path, exc)
        return None


def load_profiles(directory: Path | None = None) -> dict[str, SiteProfile]:
    """Load every valid profile in *directory*; broken files are skipped."""
    root = directory or PROFILE_DIR
    if not root.is_dir():
        return {}
    profiles: dict[str, SiteProfile] = {}
    for path in sorted(root.glob("*.yaml")):
        profile = load_profile(path.stem, root)
        if profile is None:
            continue
        if profile.site_id in profiles:
            logger.warning(
                "Duplicate site_id %r in %s; keeping first occurrence",
                profile.site_id, path,
            )
            continue
        profiles[profile.site_id] = profile
    return profiles


def save_profile(profile: SiteProfile, directory: Path | None = None) -> Path:
    """Write a sanitised profile YAML and return its path."""
    path = _profile_path(profile.site_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(mode="json", exclude_none=True)
    clean = sanitize_profile_data(data)
    path.write_text(
        yaml.safe_dump(clean, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path
