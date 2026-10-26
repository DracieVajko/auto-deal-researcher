import pytest

from src.output.domains import detect, get


def test_unknown_text_falls_back_to_generic():
    assert detect("Predám kávovar, 2 roky starý").name == "generic"


def test_generic_has_no_key_specs():
    assert get("generic").key_specs == ()


def test_override_wins_over_detection():
    assert detect("Predám bicykel", override="generic").name == "generic"


def test_unknown_override_raises():
    with pytest.raises(KeyError):
        get("nope")


def test_detect_accepts_none_prompt():
    assert detect("Predám kávovar", override=None).name == "generic"


def test_extractor_returning_whitespace_counts_as_missing():
    from src.output.domains import DomainProfile

    profile = DomainProfile(
        name="probe", key_specs=("thing",), extractors={"thing": lambda text: "   "}
    )
    assert profile.extract("anything") == {}


def test_extractor_that_raises_counts_as_missing():
    from src.output.domains import DomainProfile

    def boom(text: str) -> str:
        raise RuntimeError("bad pattern")  # noqa: TRY003 - simulating a broken extractor

    profile = DomainProfile(name="probe", key_specs=("thing",), extractors={"thing": boom})
    assert profile.extract("anything") == {}


def test_listing_matching_two_domains_picks_one_deterministically():
    from src.output.domains import DomainProfile

    coffee = DomainProfile(name="coffee_probe", strong_keywords=("kavovar",))
    mixer = DomainProfile(name="mixer_probe", strong_keywords=("mixer",))
    text = "Predám kávovar a mixer"
    first = detect(text, extra=[coffee, mixer])
    second = detect(text, extra=[coffee, mixer])
    assert first.name == second.name
    assert first.name in {"coffee_probe", "mixer_probe"}


def test_detect_folds_case_and_diacritics():
    from src.output.domains import DomainProfile

    probe = DomainProfile(name="probe", strong_keywords=("kavovar",))
    assert detect("KÁVOVAR", extra=[probe]).name == "probe"
    assert detect("kávovar", extra=[probe]).name == "probe"


def test_normalise_specs_maps_aliases_and_drops_unknown():
    from src.output.domains import DomainProfile

    profile = DomainProfile(
        name="probe", key_specs=("storage",), aliases={"storage_gb": "storage"}
    )
    assert profile.normalise_specs(
        {"storage_gb": "128", "price_eur": "300", "color": "pink"}
    ) == {"storage": "128"}
