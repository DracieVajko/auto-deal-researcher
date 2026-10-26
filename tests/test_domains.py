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


def test_computer_extracts_cpu_ram_storage():
    specs = get("computer").extract(
        "mini pc ryzen 7 5800h 32gb ddr5 512gb ssd thunderbolt"
    )
    assert specs["cpu"] == "RYZEN 7 5800H"
    assert specs["ram"] == "32 GB DDR5"
    assert specs["storage"] == "512 GB SSD"


def test_bike_extracts_specs_from_description():
    specs = get("bike").extract(
        'horský bicykel 26" kolesá, rám 18", kotúčové brzdy, sram'
    )
    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == '18"'
    assert specs["brakes"] == "Disc brakes"
    assert specs["drivetrain"] == "SRAM"


def test_bike_detected_from_keyword():
    assert detect("Predám horský bicykel Author").name == "bike"


def test_computer_detected_from_keyword():
    assert detect("Mini PC barebone NUC").name == "computer"


def test_bike_rejects_xxs_frame_for_tall_rider():
    messages, disqualify = get("bike").check(
        {"frame_size": "XXS"}, "horsky bicykel pre muza 180 cm"
    )
    assert disqualify is True
    assert any("too small" in message for message in messages)


def test_bike_accepts_large_frame_for_tall_rider():
    messages, disqualify = get("bike").check(
        {"frame_size": 'L 19"'}, "horsky bicykel pre muza 180 cm"
    )
    assert disqualify is False
    assert messages == []


def test_bike_keywords_match_uppercase():
    assert detect("Predám Horský Bicykel Author").name == "bike"


def test_bike_detected_in_german_czech_english():
    assert detect("Verkaufe Mountainbike, 26 Zoll").name == "bike"
    assert detect("Prodám horský bicykl, rám 18").name == "bike"
    assert detect("Selling a mountain bike, 26 inch").name == "bike"


def test_bike_keyword_does_not_match_motorbike():
    assert detect("Predám motorbike helmet, nový").name == "generic"


def test_bike_extracts_german_specs():
    specs = get("bike").extract(
        "fahrrad 26 zoll, rahmen 18 zoll, scheibenbremsen, sram"
    )
    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == '18"'
    assert specs["brakes"] == "Disc brakes"


def test_computer_detected_in_german():
    assert detect("Verkaufe Laptop, 32 GB RAM").name == "computer"
    assert detect("Gebrauchter Rechner, i5").name == "computer"


def test_bike_check_without_prompt_does_not_disqualify():
    messages, disqualify = get("bike").check({"frame_size": "XXS"}, None)
    assert disqualify is False
    assert messages == []


def test_phone_extracts_specs_in_four_languages():
    cases = [
        "iphone 13 128gb, bateria 89%, 6.1 palca",        # sk
        "iphone 13 128 gb, baterie 89 %, 6,1 palce",       # cs
        "iphone 13 128 gb, akku 89 %, 6,1 zoll",           # de
        "iphone 13 128gb, battery 89%, 6.1 inch",          # en
    ]
    for text in cases:
        specs = get("phone").extract(text)
        assert specs["storage"] == "128 GB", text
        assert specs["battery_health"] == "89%", text
        assert specs["screen_size"] == '6.1"', text


def test_phone_does_not_match_on_the_word_telefon_alone():
    assert detect("Kontakt: telefón 0900 000 000").name == "generic"
    assert detect("Kontakt: Telefon 0900 000 000").name == "generic"


def test_phone_aliases_map_llm_keys():
    specs = get("phone").normalise_specs(
        {"storage_gb": "128", "battery_percentage": "89", "price_eur": "219"}
    )
    assert specs == {"storage": "128", "battery_health": "89"}


def test_car_needs_a_brand_or_two_regular_keywords():
    assert detect("Predám kolesá, 18 palcov").name == "generic"
    assert detect("Predám auto, 180 000 km").name == "generic"
    assert detect("Predám auto, rok 2015, 180 000 km").name == "car"
    assert detect("Škoda Octavia 2015, 180 000 km").name == "car"


def test_car_detected_in_german_and_czech():
    assert detect("Verkaufe VW Golf, Baujahr 2015, 180000 km").name == "car"
    assert detect("Prodám Škoda Octavia, rok 2015, najeto 180 000 km").name == "car"


def test_car_extracts_specs_in_german():
    specs = get("car").extract(
        "vw golf baujahr 2015, 180000 km, diesel, automatik"
    )
    assert specs["year"] == "2015"
    assert specs["mileage"] == "180000 km"
    assert specs["fuel"] == "Diesel"
    assert specs["transmission"] == "Automatic"


def test_furniture_extracts_specs_in_four_languages():
    cases = [
        "sedacia súprava, rozmery 250x180 cm, koža",
        "sedací souprava, rozměry 250 x 180 cm, kůže",
        "sofa, masse 250 x 180 cm, leder",
        "couch, dimensions 250×180 cm, leather",  # noqa: RUF001 - multiplication sign is the point
    ]
    for text in cases:
        specs = get("furniture").extract(text)
        assert specs["dimensions"] == "250x180 cm", text
        assert specs["material"] == "Leather", text


def test_generic_is_not_selected_for_a_known_domain():
    assert detect("Gauč, koža, 200x90 cm").name == "furniture"
