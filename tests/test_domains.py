import asyncio
import json
from pathlib import Path

import pytest

from src.config import load_config
from src.output.domains import detect, get
from src.output.domains.ai import DomainProposal, propose_domain, validate_proposal
from src.output.domains.cache import load_drafts, save_draft
from src.output.processor import DealAnalysis, ResultProcessor
from src.searcher.adapters.base import Deal


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


def _analysis_for(title: str, domain: str, specs: dict[str, str]):
    deal = Deal(url="u", title=title, price_eur=200.0, condition="used", site_name="bazos")
    return DealAnalysis(deal=deal, domain=domain, specs=specs, seller_type="classifieds")


def test_furniture_has_no_connectivity_row():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for("Sedačka", "furniture", {"dimensions": "200x90 cm"})
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert "Connectivity" not in breakdown


def test_computer_keeps_connectivity_row():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for("Mini PC", "computer", {"cpu": "RYZEN 7"})
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert "Connectivity" in breakdown


def test_base_weights_are_0_95_and_connectivity_completes_the_scale():
    assert sum(ResultProcessor.BASE_WEIGHTS.values()) == pytest.approx(0.95)
    assert (
        sum(ResultProcessor.BASE_WEIGHTS.values())
        + ResultProcessor.CONNECTIVITY_WEIGHT
    ) == pytest.approx(1.0)


def test_weights_normalise_when_a_row_is_missing():
    processor = ResultProcessor.__new__(ResultProcessor)
    breakdown = {label: 100.0 for label in ResultProcessor.BASE_WEIGHTS}
    # No Connectivity row: the five base rows are rescaled from 0.95 to 1.00.
    assert processor._weighted_score(breakdown, get("furniture")) == 100.0
    # A computer does have the row; a breakdown without it loses its 0.05.
    assert processor._weighted_score(breakdown, get("computer")) == pytest.approx(95.0)


def test_phone_spec_match_is_coverage():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for(
        "iPhone", "phone", {"storage": "128 GB", "battery_health": "89%"}
    )
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert breakdown["Spec match"] == 50  # 2 of 4 key specs


def test_generic_spec_match_is_neutral():
    processor = ResultProcessor.__new__(ResultProcessor)
    analysis = _analysis_for("Kávovar", "generic", {})
    breakdown = processor._score_breakdown(analysis, 200.0, [analysis])
    assert breakdown["Spec match"] == 50
    assert "Connectivity" not in breakdown


def test_validate_rejects_a_builtin_name():
    assert validate_proposal(
        {
            "domain": "bike",
            "keywords": ["bicykel"],
            "key_specs": ["a", "b"],
            "specs": {"a": "1"},
        }
    ) is None


def test_validate_rejects_too_many_key_specs():
    payload = {
        "domain": "camera",
        "keywords": ["camera"],
        "key_specs": [f"k{i}" for i in range(13)],
        "specs": {"k0": "1"},
    }
    assert validate_proposal(payload) is None


def test_validate_rejects_a_proposal_without_keywords():
    assert validate_proposal(
        {"domain": "camera", "key_specs": ["a", "b"], "specs": {"a": "1"}}
    ) is None


def test_validate_rejects_a_single_key_spec():
    assert validate_proposal(
        {
            "domain": "camera",
            "keywords": ["camera"],
            "key_specs": ["megapixels"],
            "specs": {"megapixels": "24"},
        }
    ) is None


def test_validate_rejects_an_empty_spec_value():
    assert validate_proposal(
        {
            "domain": "camera",
            "keywords": ["camera"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": ""},
        }
    ) is None


def test_validate_accepts_a_valid_proposal():
    proposal = validate_proposal(
        {
            "domain": "camera",
            "keywords": ["camera", "fotoaparat"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": "24"},
        }
    )
    assert proposal is not None
    assert proposal.domain == "camera"
    assert proposal.keywords == ["camera", "fotoaparat"]


def test_validate_folds_keywords_before_storing_them():
    proposal = validate_proposal(
        {
            "domain": "camera",
            "keywords": ["Fotoaparát", "kamera"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": "24"},
        }
    )
    assert proposal is not None
    assert proposal.keywords == ["fotoaparat", "kamera"]


def test_validate_deduplicates_keywords_after_folding():
    proposal = validate_proposal(
        {
            "domain": "camera",
            "keywords": ["fotoaparát", "fotoaparat"],
            "key_specs": ["megapixels", "shutter_count"],
            "specs": {"megapixels": "24"},
        }
    )
    assert proposal is not None
    assert proposal.keywords == ["fotoaparat"]


@pytest.mark.asyncio
async def test_propose_domain_parses_a_model_reply():
    class FakeLLM:
        async def _chat(self, system, user, **kwargs):
            return json.dumps(
                {
                    "domain": "camera",
                    "keywords": ["camera", "fotoaparat"],
                    "key_specs": ["megapixels", "shutter_count"],
                    "specs": {"megapixels": "24"},
                }
            )

    proposal = await propose_domain(FakeLLM(), "Canon EOS 5D, 24 MP", None)
    assert proposal is not None
    assert proposal.domain == "camera"
    assert proposal.specs == {"megapixels": "24"}


def test_draft_round_trip(tmp_path):
    proposal = DomainProposal(
        domain="camera",
        keywords=["camera", "fotoaparat"],
        key_specs=["megapixels", "shutter_count"],
        specs={},
    )
    save_draft(proposal, "Canon EOS 5D", tmp_path)
    drafts = load_drafts(tmp_path)
    assert drafts["camera"].key_specs == ("megapixels", "shutter_count")
    assert drafts["camera"].strong_keywords == ("camera", "fotoaparat")


def test_cached_draft_is_used_for_detection(tmp_path):
    proposal = DomainProposal(
        domain="camera",
        keywords=["camera", "fotoaparat"],
        key_specs=["megapixels", "shutter_count"],
        specs={},
    )
    save_draft(proposal, "Canon EOS 5D", tmp_path)
    drafts = load_drafts(tmp_path)
    profile = detect("Predám fotoaparát Canon EOS", extra=drafts.values())
    assert profile.name == "camera"


def test_cached_draft_reaches_the_report(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    processor.draft_dir = tmp_path
    save_draft(
        DomainProposal(
            domain="camera",
            keywords=["camera", "fotoaparat"],
            key_specs=["megapixels", "shutter_count"],
            specs={"megapixels": "24"},
        ),
        "Canon EOS 5D",
        tmp_path,
    )
    deal = Deal(
        url="https://bazos.sk/canon",
        title="Predám fotoaparát Canon EOS 5D",
        price_eur=400.0,
        condition="used",
        site_name="bazos",
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="fotoaparat")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "camera"
    assert result["spec_coverage"]["missing"] == ["megapixels", "shutter_count"]


def test_corrupt_draft_is_ignored(tmp_path):
    (tmp_path / "camera.yaml").write_text(":::not yaml", encoding="utf-8")
    assert load_drafts(tmp_path) == {}


def test_draft_with_an_invalid_shape_is_ignored(tmp_path):
    (tmp_path / "camera.yaml").write_text(
        "name: camera\nsource: ai\nkeywords: []\nkey_specs: [a, b]\n",
        encoding="utf-8",
    )
    assert load_drafts(tmp_path) == {}


def test_domain_override_reaches_the_report(tmp_path):
    config = load_config()
    config.output.domain = "computer"
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/x",
        title="Predám bicykel",
        price_eur=90.0,
        condition="used",
        site_name="bazos",
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="nieco")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "computer"


def test_proposal_that_misses_its_own_listing_is_discarded(tmp_path):
    """A draft that cannot name the listing that produced it is write-only."""

    class FakeLLM:
        async def _chat(self, system, user, **kwargs):
            if "classify" in system:
                return json.dumps(
                    {
                        "domain": "tent",
                        # A phrase absent from the listing text.
                        "keywords": ["vystavny stan"],
                        "key_specs": ["capacity", "pole"],
                        "specs": {"capacity": "4 people"},
                    }
                )
            return "[]"

    config = load_config()
    processor = ResultProcessor(config, FakeLLM())
    processor.draft_dir = tmp_path
    deal = Deal(
        url="https://bazos.sk/stan",
        title="Penzion s vlastnym stanom",
        price_eur=50.0,
        condition="used",
        site_name="bazos",
    )
    json_path, _ = asyncio.run(processor.save_results([deal], str(tmp_path)))
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "generic"
    assert list(tmp_path.glob("*.yaml")) == []


def test_price_is_neutral_with_fewer_than_four_distinct_prices():
    processor = ResultProcessor.__new__(ResultProcessor)
    analyses = [_analysis_for(f"Deal {i}", "generic", {}) for i in range(3)]
    for analysis, price in zip(analyses, (100.0, 200.0, 300.0), strict=True):
        analysis.deal.price_eur = price

    processor._add_cross_alternatives(analyses)

    assert all(a.score_breakdown["Price"] == 50 for a in analyses)


def test_price_uses_the_median_with_four_distinct_prices():
    processor = ResultProcessor.__new__(ResultProcessor)
    analyses = [_analysis_for(f"Deal {i}", "generic", {}) for i in range(4)]
    for analysis, price in zip(analyses, (100.0, 200.0, 300.0, 400.0), strict=True):
        analysis.deal.price_eur = price

    processor._add_cross_alternatives(analyses)

    assert analyses[0].score_breakdown["Price"] == 95
    assert analyses[3].score_breakdown["Price"] == 25


def test_price_claim_cons_are_dropped():
    processor = ResultProcessor(load_config())
    analysis = _analysis_for("iPhone 13", "phone", {})
    processor._merge_llm_analysis(
        analysis,
        {
            "id": "L0",
            "cons": [
                "price far exceeds reasonable used market value",
                "storage not stated",
            ],
        },
        "iphone 13",
    )
    assert not any("market" in con for con in analysis.cons)
    assert any("storage" in con for con in analysis.cons)
