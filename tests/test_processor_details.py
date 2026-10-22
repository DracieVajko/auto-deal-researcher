"""The report must explain each deal, not just list name/price/link."""

import asyncio
import json
from pathlib import Path

from src.config import load_config
from src.output.processor import ResultProcessor
from src.searcher.adapters.base import Deal

PROMPT = (
    "mini pc barebone with Thunderbolt/OCuLink, DDR5, 32-64GB, "
    "AMD Ryzen 5+/i5+, AMD Radeon iGPU"
)


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

    specs = ResultProcessor._extract_specs(deal)

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
