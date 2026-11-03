"""Conservative cross-site product links (never collapse variants)."""

import asyncio

from src.config import load_config
from src.output.cross_site import cross_site_groups, product_key
from src.output.processor import DealAnalysis, ResultProcessor
from src.searcher.adapters.base import Deal


def _deal(url, title, price, site):
    return Deal(url=url, title=title, price_eur=price, site_name=site)


def test_product_key_ignores_condition_noise():
    assert product_key("Samsung 30Q 18650 NEW") == product_key(
        "Samsung 30Q 18650 used"
    )


def test_cross_site_groups_need_two_sites():
    deals = [
        _deal("a", "Samsung 30Q 18650 battery", 5, "alza"),
        _deal("b", "Samsung 30Q 18650 battery", 4, "nkon_nl"),
        _deal("c", "Samsung 30Q 18650 battery", 3, "alza"),
        _deal("d", "Completely different product", 9, "bazos"),
    ]
    groups = cross_site_groups(deals)
    assert len(groups) == 1
    assert {deal.site_name for deal in next(iter(groups.values()))} == {
        "alza",
        "nkon_nl",
    }


def test_report_shows_also_at_links():
    processor = ResultProcessor(load_config())
    analyses = [
        DealAnalysis(
            deal=_deal("https://a/1", "Samsung 30Q 18650 battery", 5, "alza"),
            domain="generic",
            score=90,
            verdict="buy",
        ),
        DealAnalysis(
            deal=_deal("https://b/1", "Samsung 30Q 18650 battery", 4, "nkon_nl"),
            domain="generic",
            score=80,
            verdict="watch",
        ),
    ]

    markdown = processor._to_markdown("x", analyses, [], "2026-11-03", set())

    assert "Also at" in markdown
    assert "https://b/1" in markdown
    assert "https://a/1" in markdown


def test_also_at_is_not_written_to_json_until_analysis_runs(tmp_path):
    processor = ResultProcessor(load_config())
    deal = _deal("https://a/1", "Samsung 30Q 18650 battery", 5, "alza")
    json_path, _ = asyncio.run(
        processor.save_results([deal], str(tmp_path), prompt="x")
    )
    import json

    payload = json.loads(open(json_path, encoding="utf-8").read())
    assert payload["deals"][0]["also_at"] == []
