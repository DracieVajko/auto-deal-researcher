"""The report must explain each deal, not just list name/price/link."""

import asyncio
import json
from pathlib import Path

from src.config import load_config
from src.output.domains import detect, get
from src.output.processor import DealAnalysis, ResultProcessor
from src.searcher.adapters.base import Deal

PROMPT = (
    "mini pc barebone with Thunderbolt/OCuLink, DDR5, 32-64GB, "
    "AMD Ryzen 5+/i5+, AMD Radeon iGPU"
)


def _listing_text(deal: Deal) -> str:
    """The same title+metadata string the processor feeds to a profile."""
    return f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}"


def sample_deals():
    return [
        Deal(
            url="https://alza.sk/nuc",
            title="ASUS NUC 14 Pro+ NUC14RVSU9000R2",
            price_eur=854.9,
            condition="new",
            site_name="alza",
            metadata={"source": "alza"},
        ),
        Deal(
            url="https://bazos.sk/zenbook",
            title="ASUS Zenbook S 14 OLED (UX5406S) - NOVY, ZARUKA 2 ROKY",
            price_eur=1149.0,
            condition="used",
            site_name="bazos",
            metadata={"source": "bazos"},
        ),
        Deal(
            url="https://bazos.sk/mini",
            title="Mini PC Ryzen 7 5800H 32GB DDR5 512GB SSD Thunderbolt",
            price_eur=420.0,
            condition="used",
            site_name="bazos",
            metadata={"source": "bazos"},
        ),
    ]


def test_report_filters_laptops_and_explains_each_deal(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)  # no LLM: heuristic path must work

    json_path, md_path = asyncio.run(
        processor.save_results(sample_deals(), str(tmp_path), prompt=PROMPT)
    )

    payload = json.loads(open(json_path, encoding="utf-8").read())
    assert payload["count"] == 2
    assert payload["filtered_out_count"] == 1
    assert {d["title"] for d in payload["deals"]} == {
        "ASUS NUC 14 Pro+ NUC14RVSU9000R2",
        "Mini PC Ryzen 7 5800H 32GB DDR5 512GB SSD Thunderbolt",
    }
    scores = [d["score"] for d in payload["deals"]]
    assert scores == sorted(scores, reverse=True)
    assert payload["filtered_out"][0]["title"].startswith("ASUS Zenbook")

    for deal in payload["deals"]:
        assert deal["pros"]
        assert deal["cons"]
        assert deal["score_breakdown"]
        assert 0 <= deal["score"] <= 100
        assert deal["verdict"] in {"buy", "watch", "skip"}

    used = next(d for d in payload["deals"] if d["site_name"] == "bazos")
    assert used["seller_type"] == "classifieds"
    assert used["specs"]["ram"] == "32 GB DDR5"
    assert used["specs"]["cpu"].startswith("RYZEN 7 5800H")
    assert used["alternatives"] == [] or used["alternatives"][0]["price_eur"] <= used["price_eur"]

    markdown = open(md_path, encoding="utf-8").read()
    assert "## Deal details" in markdown
    assert "Pros" in markdown and "Cons" in markdown
    assert "Score breakdown" in markdown
    assert "Before you buy" in markdown
    assert "## Filtered out" in markdown
    # The laptop is mentioned once (filtered table), never as a deal card.
    assert markdown.count("Zenbook") == 1
    # Cheaper used mini PC is offered as an alternative to the NUC.
    assert "Cheaper by" in markdown


def test_empty_report_is_still_written(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)

    json_path, md_path = asyncio.run(
        processor.save_results([], str(tmp_path), prompt=PROMPT)
    )

    payload = json.loads(open(json_path, encoding="utf-8").read())
    assert payload["deals"] == []
    assert "No deals matching" in open(md_path, encoding="utf-8").read()


def test_alza_description_is_parsed_into_specs():
    """Alza's search card carries a spec line; it must reach the report."""
    deal = Deal(
        url="https://alza.sk/nuc",
        title="ASUS NUC 14 Pro NUC14RVKC3000R2 Slim",
        price_eur=315.81,
        condition="new",
        site_name="alza",
        metadata={
            "description": (
                "Mini PC - firemný barebone, bez pamäte RAM (max. 96 GB), "
                "bez disku, Thunderbolt 4, Intel Core 3 100U, HDMI 2.1"
            )
        },
    )

    specs = get("computer").extract(_listing_text(deal))

    assert specs["cpu"] == "INTEL CORE 3 100U"
    assert specs["ram"] == "No RAM included (barebone)"
    assert specs["storage"] == "No storage included (barebone)"
    assert "Thunderbolt" in specs["connectivity"]


def test_barebone_facts_are_not_repeated_in_llm_bullets():
    merged = ResultProcessor._append_unique(
        ["Barebone: RAM not included - budget for SO-DIMM modules"],
        ["RAM not included", "Thunderbolt 4"],
    )

    assert "RAM not included" not in merged
    assert "Thunderbolt 4" in merged


def test_duplicate_ram_bullets_are_collapsed():
    merged = ResultProcessor._append_unique(
        ["Stated memory: 64 GB RAM"],
        ["64GB RAM included"],
    )

    assert merged == ["Stated memory: 64 GB RAM"]


BIKE_PROMPT = (
    "horsky bicykel 26 palcove kolesa, odpruzeny ram, pre muza 180 cm, pouzite"
)


def test_non_pc_report_has_no_cpu_ram_advice(tmp_path):
    """Bicycle/furniture reports must not inherit mini-PC checklist items."""
    config = load_config()
    processor = ResultProcessor(config)
    bike = Deal(
        url='https://sport.bazos.sk/inzerat/1/horsky-bicykel-giant-terrago.php',
        title='Horský bicykel Giant Terrago - 26"',
        price_eur=85.0,
        condition="used",
        site_name="bazos",
        metadata={"source": "bazos"},
    )

    json_path, md_path = asyncio.run(
        processor.save_results([bike], str(tmp_path), prompt=BIKE_PROMPT)
    )

    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert payload["count"] == 1
    deal = payload["deals"][0]
    bullets = " ".join(deal["pros"] + deal["cons"]).lower()
    assert "cpu" not in bullets
    assert "memory size" not in bullets
    assert "ram" not in bullets
    assert "ssd" not in bullets

    markdown = Path(md_path).read_text(encoding="utf-8")
    card = markdown.split("## Deal details", 1)[1]
    assert "CPU" not in card
    assert "RAM" not in card
    assert "SSD" not in card
    assert "screenshot of the memory" not in card
    assert "Inspect the item in person" in card


def test_pc_prompt_keeps_pc_details_but_bike_frame_does_not():
    assert ResultProcessor._wants_pc_details("generic", "mini pc with 32 GB RAM")
    assert ResultProcessor._wants_pc_details("generic", "laptop with Thunderbolt")
    assert not ResultProcessor._wants_pc_details(
        "generic", "odpruzeny ram horskeho bicykla"
    )
    assert not ResultProcessor._wants_pc_details("bike", "bicykel")
    assert ResultProcessor._wants_pc_details("computer", "horsky bicykel")


class CapturingLLM:
    """Records the prompt and returns an empty batch."""

    def __init__(self):
        self.system = ""
        self.user = ""

    async def _chat(self, system, user, max_tokens=100, **kwargs):
        self.system = system
        self.user = user
        return "[]"


def _analysis(title: str, price: float = 85.0) -> DealAnalysis:
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title=title,
        price_eur=price,
        condition="used",
        site_name="bazos",
    )
    profile = detect(_listing_text(deal))
    return DealAnalysis(deal=deal, domain=profile.name, profile=profile)


def test_bike_analysis_prompt_is_not_pc_specific():
    config = load_config()
    llm = CapturingLLM()
    processor = ResultProcessor(config, llm)

    asyncio.run(
        processor._llm_analyze_batch([_analysis('Horský bicykel 26"')], BIKE_PROMPT)
    )

    assert "PC hardware buyer" not in llm.system
    assert "product buyer" in llm.system
    assert "cpu" not in llm.user.lower()
    assert "barebone" not in llm.user.lower()


def test_pc_analysis_prompt_keeps_pc_rules():
    config = load_config()
    llm = CapturingLLM()
    processor = ResultProcessor(config, llm)

    asyncio.run(
        processor._llm_analyze_batch(
            [_analysis("Mini PC barebone Ryzen 7 32GB DDR5")],
            "mini pc barebone with 32 GB RAM",
        )
    )

    assert "cpu" in llm.user.lower()
    assert "barebone" in llm.user.lower()


def test_bike_specs_are_extracted_from_description():
    """Frame and wheel size live in the description, not the result card."""
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title="Horský bicykel Author",
        price_eur=90.0,
        metadata={
            "description": (
                "Kolesá sú 26 palcové, rám je veľkosti L (19”). "
                "Vhodné pre asi 180cm postavu."
            )
        },
    )

    specs = get("bike").extract(_listing_text(deal))

    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == 'L 19"'


def test_bike_specs_handle_escaped_quotes():
    """json.dumps escapes quotes, so 26\\" must still parse."""
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title="MTB",
        price_eur=100.0,
        metadata={
            "description": (
                '26" kolesá, rám 18", kotúčové brzdy, SRAM'
            )
        },
    )

    specs = get("bike").extract(_listing_text(deal))

    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == '18"'
    assert specs["brakes"] == "Disc brakes"
    assert specs["drivetrain"] == "SRAM"


def test_pc_specs_do_not_get_bike_keys():
    """PC listings mention RAM; that must never become a frame size."""
    deal = Deal(
        url="https://www.alza.sk/mini-pc",
        title="Mini PC barebone",
        price_eur=300.0,
        metadata={"description": "Ryzen 7 32GB DDR5 RAM, 1TB SSD"},
    )

    specs = get("computer").extract(_listing_text(deal))

    assert "frame_size" not in specs
    assert "wheel_size" not in specs
    assert specs["ram"] == "32 GB DDR5"


def test_car_wheels_are_not_bike_specs():
    """A car ad also says "kolesá"; it must not get bike keys."""
    deal = Deal(
        url="https://auto.bazos.sk/inzerat/1/skoda.php",
        title="Škoda Octavia",
        price_eur=3000.0,
        metadata={"description": 'Predám 18" kolesá, letné pneumatiky'},
    )

    specs = get("car").extract(_listing_text(deal))

    assert "wheel_size" not in specs
    assert "frame_size" not in specs


def test_bike_prompt_with_ram_is_not_gated_as_pc():
    """\"odpruzeny ram\" is a frame, not memory; it must not set fit to 15."""
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title="Horský bicykel 26",
        price_eur=90.0,
        metadata={"description": 'rám 18"'},
    )
    specs = get("bike").extract(_listing_text(deal))

    assert ResultProcessor._matches_prompt(BIKE_PROMPT, deal, "bike", specs, False)


def test_pc_prompt_still_rejects_unrelated_listing():
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title="Horský bicykel",
        price_eur=90.0,
    )

    assert not ResultProcessor._matches_prompt(
        "laptop with 32 GB RAM", deal, "computer", {}, False
    )


def test_bike_frame_size_supports_xxs_and_prime_marks():
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title="Kellys Madman 10 bicykel",
        price_eur=280.0,
        metadata={
            "description": (
                "plášte: IMPAC Ridgepac 54-559 (26x2.10) "
                "veľkosť rámu: XXS"
            )
        },
    )

    specs = get("bike").extract(_listing_text(deal))

    assert specs["wheel_size"] == '26"'
    assert specs["frame_size"] == "XXS"


def test_small_frame_is_flagged_for_tall_rider():
    messages, disqualify = get("bike").check(
        {"wheel_size": '26"', "frame_size": "XXS"}, BIKE_PROMPT
    )

    assert disqualify
    assert messages and "too small" in messages[0]


def test_large_frame_is_fine_for_180_cm():
    messages, disqualify = get("bike").check({"frame_size": 'L 19"'}, BIKE_PROMPT)

    assert messages == []
    assert not disqualify


def test_size_note_needs_a_rider_height():
    messages, disqualify = get("bike").check(
        {"frame_size": "XXS"}, "horsky bicykel 26"
    )

    assert messages == []
    assert not disqualify


def test_heuristic_skips_a_too_small_frame(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://sport.bazos.sk/inzerat/1/item.php",
        title="Kellys Madman 10 bicykel",
        price_eur=280.0,
        condition="used",
        site_name="bazos",
        metadata={
            "description": 'veľkosť rámu: XXS, 26" kolesá, Shimano',
        },
    )

    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt=BIKE_PROMPT)
    )

    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    result = payload["deals"][0]
    assert result["verdict"] == "skip"
    assert any("too small" in con for con in result["cons"])


def test_llm_batch_includes_listing_description():
    config = load_config()
    llm = CapturingLLM()
    processor = ResultProcessor(config, llm)
    analysis = _analysis("Horský bicykel Author")
    analysis.deal.metadata["description"] = "rám je veľkosti L (19”), kolesá 26"

    asyncio.run(processor._llm_analyze_batch([analysis], BIKE_PROMPT))

    assert "description:" in llm.user
    assert "veľkosti L (19" in llm.user


def test_llm_batch_truncates_long_description():
    config = load_config()
    llm = CapturingLLM()
    processor = ResultProcessor(config, llm)
    analysis = _analysis("Horský bicykel")
    analysis.deal.metadata["description"] = "x" * 2000

    asyncio.run(processor._llm_analyze_batch([analysis], BIKE_PROMPT))

    assert "x" * 600 in llm.user
    assert "x" * 601 not in llm.user


def test_laptop_search_keeps_laptops(tmp_path):
    """Form-factor filtering is request-specific, not anti-laptop."""
    config = load_config()
    processor = ResultProcessor(config)
    laptop = Deal(
        url="https://bazos.sk/zenbook",
        title="ASUS Zenbook S 14 OLED (UX5406S)",
        price_eur=1149.0,
        condition="used",
        site_name="bazos",
    )

    json_path, md_path = asyncio.run(
        processor.save_results(
            [laptop], str(tmp_path), prompt="gaming laptop under 1200 EUR"
        )
    )

    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["filtered_out_count"] == 0
    assert payload["deals"][0]["is_laptop"] is True
    assert payload["deals"][0]["wrong_form_factor"] is False

    markdown = Path(md_path).read_text(encoding="utf-8")
    assert "Laptop/notebook form factor matches the request" in markdown


class ReorderingLLM:
    """Returns batch objects in reverse order but with correct listing ids."""

    async def _filename_slug_async(self, prompt):
        return "id-merge-test"

    async def _chat(self, system, user, max_tokens=100, **kwargs):
        return json.dumps(
            [
                {
                    "id": "L1",
                    "score": 70,
                    "verdict": "watch",
                    "notes": "Second listing note",
                    "pros": ["Second pro"],
                    "cons": ["Second con"],
                    "specs": {},
                    "alternatives": [],
                },
                {
                    "id": "L0",
                    "score": 30,
                    "verdict": "skip",
                    "notes": "First listing note",
                    "pros": ["First pro"],
                    "cons": ["First con"],
                    "specs": {},
                    "alternatives": [],
                },
            ]
        )


def test_llm_batches_are_merged_by_listing_id_not_row_order(tmp_path):
    config = load_config()
    processor = ResultProcessor(config, ReorderingLLM())
    deals = [
        Deal(
            url="https://alza.sk/one",
            title="ASUS NUC 15 Pro RNUC15CRKU500002 Slim",
            price_eur=535.0,
            condition="new",
            site_name="alza",
        ),
        Deal(
            url="https://bazos.sk/two",
            title="MinisForum MS-A1 Ryzen 7 8700G 32GB DDR5",
            price_eur=700.0,
            condition="used",
            site_name="bazos",
        ),
    ]

    json_path, _ = asyncio.run(
        processor.save_results(deals, str(tmp_path), prompt="mini pc barebone")
    )
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    by_site = {deal["site_name"]: deal for deal in payload["deals"]}

    assert by_site["alza"]["notes"] == "First listing note"
    assert by_site["bazos"]["notes"] == "Second listing note"


def test_report_markdown_shows_domain_and_coverage(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/iphone",
        title="iPhone 13 128GB",
        price_eur=350.0,
        condition="used",
        site_name="bazos",
        metadata={"description": "Batéria 89%, 128 GB."},
    )
    _, md_path = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="iphone 13 pouzity")
    )
    markdown = Path(md_path).read_text(encoding="utf-8")
    assert "Domain: phone" in markdown
    assert "2/4 specs stated" in markdown


def test_phone_report_has_no_bike_keys(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/iphone",
        title="iPhone 13 128GB",
        price_eur=350.0,
        condition="used",
        site_name="bazos",
        metadata={"description": "Batéria 89%, 128 GB, bez škrabancov."},
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="iphone 13 pouzity")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "phone"
    assert "wheel_size" not in result["specs"]
    assert "frame_size" not in result["specs"]
    assert result["spec_coverage"]["stated"]
    # A phone has storage and ram keys, but it is not a computer: no CPU advice.
    assert not any("CPU" in con for con in result["cons"])
    assert not any("memory size" in con for con in result["cons"])


def test_sofa_report_has_no_connectivity_row(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/sedacka",
        title="Sedacia súprava",
        price_eur=200.0,
        condition="used",
        site_name="bazos",
        metadata={"description": "Kožená, rozmery 250x180 cm."},
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="sedacia supravy")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["domain"] == "furniture"
    assert "Connectivity" not in result["score_breakdown"]


def test_bike_report_still_skips_xxs_for_tall_rider(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/kellys",
        title="Kellys Madman 10 bicykel",
        price_eur=280.0,
        condition="used",
        site_name="bazos",
        metadata={"description": 'veľkosť rámu: XXS, 26" kolesá'},
    )
    json_path, _ = asyncio.run(
        processor.save_results(
            [deal], str(tmp_path), prompt="horsky bicykel pre muza 180 cm"
        )
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert result["verdict"] == "skip"
    assert any("too small" in con for con in result["cons"])


def test_report_says_description_unavailable_when_fetch_failed(tmp_path):
    config = load_config()
    processor = ResultProcessor(config)
    deal = Deal(
        url="https://bazos.sk/x",
        title="iPhone 13 128GB",
        price_eur=300.0,
        condition="used",
        site_name="bazos",
        metadata={"detail_failed": True},
    )
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="iphone 13")
    )
    result = json.loads(Path(json_path).read_text(encoding="utf-8"))["deals"][0]
    assert any("could not be fetched" in con for con in result["cons"])


def test_llm_specs_are_restricted_to_the_profile_keys():
    processor = ResultProcessor(load_config())
    analysis = DealAnalysis(
        deal=Deal(
            url="u",
            title="iPhone 13",
            price_eur=300.0,
            condition="used",
            site_name="bazos",
        ),
        domain="phone",
    )
    processor._merge_llm_analysis(
        analysis,
        {
            "id": "L0",
            "specs": {
                "storage_gb": "128",
                "battery_percentage": "89",
                "color": "pink",
                "price_eur": "300",
            },
        },
        "iphone 13",
    )
    assert analysis.specs == {"storage": "128", "battery_health": "89"}


def test_generic_keeps_model_specs_but_never_price_eur():
    processor = ResultProcessor(load_config())
    analysis = DealAnalysis(
        deal=Deal(
            url="u",
            title="Kávovar Delonghi",
            price_eur=120.0,
            condition="used",
            site_name="bazos",
        ),
        domain="generic",
    )
    processor._merge_llm_analysis(
        analysis,
        {
            "id": "L0",
            "specs": {"pressure_bar": "15", "color": "silver", "price_eur": "120"},
        },
        "kavovar",
    )
    assert analysis.specs == {"pressure_bar": "15", "color": "silver"}


def test_llm_prompt_names_the_profile_keys():
    captured = {}

    class CaptureLLM:
        async def _chat(self, system, user, **kwargs):
            captured["user"] = user
            return "[]"

    processor = ResultProcessor(load_config(), llm=CaptureLLM())
    analysis = DealAnalysis(
        deal=Deal(
            url="u",
            title="iPhone 13",
            price_eur=300.0,
            condition="used",
            site_name="bazos",
        ),
        domain="phone",
    )
    asyncio.run(processor._llm_analyze_batch([analysis], "iphone 13"))
    assert "storage, ram, battery_health, screen_size" in captured["user"]
