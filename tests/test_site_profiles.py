"""Site profile schema, loading and sanitisation."""

from datetime import date

import pytest
from pydantic import ValidationError

from src.searcher.site_profiles import (
    FilterSpec,
    SearchSpec,
    SiteProfile,
    load_profile,
    load_profiles,
    sanitize_profile_data,
    save_profile,
)


def _profile(**overrides):
    data = {
        "site_id": "alza",
        "base_url": "https://www.alza.sk",
        "status": "validated",
        "last_verified": date(2026, 10, 22),
        "search": {
            "url_template": "https://www.alza.sk/search.htm?exps={query}",
            "query_param": "exps",
        },
        "filters": {
            "price_max": {
                "url": {"param": "max", "value_map": {}},
                "ui": {"kind": "input", "selector": "input[name='max']"},
                "source": "heuristic",
                "confidence": 0.8,
            }
        },
        "extraction": {
            "item_selector": ".browsingitem",
            "title_selector": ".name",
            "price_selector": ".price",
            "link_selector": "a",
        },
    }
    data.update(overrides)
    return SiteProfile.model_validate(data)


def test_profile_round_trip(tmp_path):
    profile = _profile()
    path = save_profile(profile, tmp_path)
    assert path.exists()
    loaded = load_profile("alza", tmp_path)
    assert loaded is not None
    assert loaded.site_id == "alza"
    assert loaded.search.url_template.endswith("{query}")
    assert loaded.filters.price_max is not None
    assert loaded.filters.price_max.url is not None
    assert loaded.filters.price_max.url.param == "max"


def test_missing_profile_returns_none(tmp_path):
    assert load_profile("does-not-exist", tmp_path) is None


def test_load_profiles_ignores_broken_yaml(tmp_path):
    good = _profile()
    save_profile(good, tmp_path)
    (tmp_path / "broken.yaml").write_text("site_id: [unclosed", encoding="utf-8")
    profiles = load_profiles(tmp_path)
    assert set(profiles) == {"alza"}


def test_rejects_filter_without_url_or_ui():
    with pytest.raises(ValidationError):
        FilterSpec()


def test_rejects_unknown_status():
    with pytest.raises(ValidationError):
        _profile(status="working")


def test_rejects_extra_top_level_key():
    with pytest.raises(ValidationError):
        _profile(cookies=[{"name": "sid"}])


def test_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        FilterSpec(url={"param": "max"}, confidence=2.0)


def test_sanitizer_strips_secret_keys_and_query_params():
    raw = {
        "site_id": "x",
        "base_url": "https://x.test/search?token=abc&q=1",
        "cookies": [{"name": "sid"}],
        "headers": {"authorization": "Bearer x"},
        "storage_state": "state.json",
        "search": {"url_template": "https://x.test/search?q={query}"},
        "notes": "contact me at seller@example.com",
    }
    clean = sanitize_profile_data(raw)
    assert "cookies" not in clean
    assert "headers" not in clean
    assert "storage_state" not in clean
    assert "token=" not in clean["base_url"]
    assert "q=1" in clean["base_url"]
    assert "seller@example.com" not in clean["notes"]


def test_sanitizer_drops_secret_url_params_recursively():
    raw = {
        "search": {
            "url_template": "https://x.test/s?q={query}&session=abc&key=secret"
        }
    }
    clean = sanitize_profile_data(raw)
    url = clean["search"]["url_template"]
    assert "session=" not in url
    assert "key=" not in url
    assert "q={query}" in url


def test_save_profile_does_not_write_secret_url_params(tmp_path):
    profile = _profile(
        base_url="https://www.alza.sk/?token=abc",
        search=SearchSpec(url_template="https://www.alza.sk/s?q={query}&auth=xyz"),
    )
    path = save_profile(profile, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "token=" not in text
    assert "auth=" not in text


def test_runtime_ready_requires_query_url_and_item_selector():
    assert _profile().is_runtime_ready
    assert not _profile(search=SearchSpec(url_template="https://www.alza.sk/fixed")).is_runtime_ready
    assert not _profile(extraction={}).is_runtime_ready


def test_profile_accepts_category_urls():
    profile = _profile(
        search=SearchSpec(
            query_param="q",
            category_urls={"electronics": "https://x.test/e"},
        )
    )
    assert profile.search.category_urls["electronics"] == "https://x.test/e"
