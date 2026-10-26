from src.output.dedup import collapse_duplicates
from src.searcher.adapters.base import Deal


def _deal(url: str, title: str, price: float, site: str = "bazos") -> Deal:
    return Deal(url=url, title=title, price_eur=price, site_name=site)


def test_identical_titles_collapse_to_the_cheapest():
    deals = [
        _deal("a", "iPhone 13 Pink BATERIE 100% TOP", 320),
        _deal("b", "iPhone 13  Pink  BATERIE 100% TOP", 300),
        _deal("c", "iPhone 13 Blue BATERIE 100% TOP", 340),
    ]
    kept, collapsed = collapse_duplicates(deals)
    assert collapsed == 1
    assert [d.url for d in kept] == ["b", "c"]
    assert kept[0].metadata["duplicates"] == [
        {"url": "a", "price_eur": 320.0}
    ]


def test_same_title_on_different_sites_is_not_a_duplicate():
    deals = [
        _deal("a", "iPhone 13", 300, "bazos"),
        _deal("b", "iPhone 13", 280, "alza"),
    ]
    kept, collapsed = collapse_duplicates(deals)
    assert collapsed == 0
    assert len(kept) == 2


def test_diacritics_do_not_prevent_a_duplicate():
    deals = [_deal("a", "Kožená sedačka", 200), _deal("b", "Kozena sedacka", 180)]
    kept, collapsed = collapse_duplicates(deals)
    assert collapsed == 1
    assert kept[0].url == "b"


def test_unknown_price_never_beats_a_known_one():
    deals = [_deal("a", "iPhone 13", 0.0), _deal("b", "iPhone 13", 250.0)]
    kept, _ = collapse_duplicates(deals)
    assert kept[0].url == "b"
