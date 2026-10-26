import pytest

from src.output.requirements import apply_requirement_guard, extract_requirements


@pytest.mark.parametrize(
    ("prompt", "key", "value"),
    [
        ("iPhone 13 128 GB, batéria aspoň 85%", "storage_gb", 128),
        ("iPhone 13 128GB, battery at least 85%", "min_battery_percent", 85),
        ("iPhone 13, Akku mindestens 85 %", "min_battery_percent", 85),
        ("iPhone 13, baterie alespoň 85 %", "min_battery_percent", 85),
        ("iPhone 13 do 300 eur", "max_price_eur", 300),
        ("iPhone 13 unter 300 Euro", "max_price_eur", 300),
    ],
)
def test_extract_requirements_in_four_languages(prompt, key, value):
    assert extract_requirements(prompt)[key] == value


def test_guard_drops_a_false_not_stated_con():
    kept, rescued = apply_requirement_guard(
        ["storage not stated", "no mention of physical condition"],
        {"storage": "128 GB"},
        {"storage_gb": 128},
    )
    assert kept == ["no mention of physical condition"]
    assert rescued is True


def test_guard_does_not_rescue_a_different_rejection():
    kept, rescued = apply_requirement_guard(
        ["cracked screen"], {"storage": "128 GB"}, {"storage_gb": 128}
    )
    assert kept == ["cracked screen"]
    assert rescued is False


def test_guard_matches_the_no_mention_wording():
    kept, rescued = apply_requirement_guard(
        ["no mention of storage capacity"], {"storage": "128 GB"}, {"storage_gb": 128}
    )
    assert kept == []
    assert rescued is True


def test_hard_defect_remains_after_the_false_con_is_dropped():
    from src.output.requirements import has_hard_defect

    kept, rescued = apply_requirement_guard(
        ["storage not stated", "cracked screen"],
        {"storage": "128 GB"},
        {"storage_gb": 128},
    )
    assert kept == ["cracked screen"]
    # The false "not stated" con is gone, but the caller must not flip the
    # requirement flag while an independent defect remains.
    assert rescued is True
    assert has_hard_defect(kept) is True


def test_guard_respects_a_battery_below_the_minimum():
    kept, rescued = apply_requirement_guard(
        ["battery not stated"], {"battery_health": "79%"}, {"min_battery_percent": 85}
    )
    assert kept == ["battery not stated"]
    assert rescued is False


def test_guard_only_drops_cons_about_the_guarded_attribute():
    # Spec 16.2: the guard only ever removes a con about *that* requirement.
    kept, rescued = apply_requirement_guard(
        ["barva neuvedena"], {"storage": "128 GB"}, {"storage_gb": 128}
    )
    assert kept == ["barva neuvedena"]
    assert rescued is False
