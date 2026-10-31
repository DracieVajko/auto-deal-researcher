"""Tests for the site registry (no network)."""

from src.searcher.site_registry import SITES, by_id, by_status, sites_for, summary


def test_registry_has_working_sites():
    working = by_status("working")
    assert {s.id for s in working} == {"alza", "bazos"}


def test_drone_is_not_searched_on_irrelevant_sites():
    """Category filtering must keep pharmacies and bookshops out of a drone run."""
    sites = sites_for("electronics", "any")
    ids = {s.id for s in sites}
    assert "alza" in ids
    assert "bazos" in ids
    # no site in the registry advertises only "general" or a non-electronics
    # category without electronics, so a drone never lands on, e.g., a book site
    for s in sites:
        assert "electronics" in s.categories or "general" in s.categories


def test_category_filter_drops_auto_only_sites_for_electronics():
    # a site that only supports 'auto' must not appear for an electronics search
    auto_only = [s for s in SITES if s.categories == ("auto",)]
    # none in the current catalogue, but the filter must still exclude them
    filtered = sites_for("electronics")
    for s in auto_only:
        assert s not in filtered


def test_condition_filter():
    refurbished = sites_for("electronics", "refurbished")
    # aukro also advertises refurbished; it was missing from the original list
    assert {s.id for s in refurbished} == {"backmarket", "ebay", "heureka", "idealo", "amazon_de", "aukro"}


def test_used_filter_excludes_new_only_sites():
    used = sites_for("electronics", "used")
    assert "alza" not in {s.id for s in used}, "alza is new/open_box only"
    assert "bazos" in {s.id for s in used}


def test_by_id_missing():
    assert by_id("does-not-exist") is None


def test_by_id_returns_spec():
    spec = by_id("alza")
    assert spec is not None
    assert spec.status == "working"
    assert spec.adapter_class == "alza"


def test_summary_counts():
    s = summary()
    assert s["working"] == 2
    assert s["blocked"] == 4
    assert s["needs_login"] == 1
    assert s["planned"] == 23
    assert sum(s.values()) == len(SITES)


def test_no_duplicate_ids():
    ids = [s.id for s in SITES]
    assert len(ids) == len(set(ids))


def test_working_sites_have_verified_status_note():
    for s in by_status("working"):
        assert s.notes, f"{s.id} has no notes"
        assert len(s.notes) > 20


def test_planned_sites_have_adapter_class():
    for s in by_status("planned"):
        assert s.adapter_class, f"{s.id} has no adapter_class"


def test_categories_are_known():
    known = {"electronics", "appliances", "auto", "home", "hobby", "general"}
    for s in SITES:
        assert set(s.categories) <= known, f"{s.id}: unknown category"
        assert set(s.conditions) <= {"new", "used", "refurbished", "open_box",
                                      "marketplace", "any"}, f"{s.id}: unknown condition"


def test_every_site_has_a_country_and_currency():
    for s in SITES:
        assert s.country, f"{s.id}: no country"
        assert s.currency in {"EUR", "CZK", "USD", "GBP"}, f"{s.id}: unknown currency"


def test_czech_sites_quote_in_the_right_currency():
    # The Autobazar family bills in EUR even on its CZ domain, the rest of
    # the CZ market bills in CZK.
    eur_cz = {"autobazar_cz"}
    for s in SITES:
        if s.country != "CZ":
            continue
        expected = "EUR" if s.id in eur_cz else "CZK"
        assert s.currency == expected, f"{s.id}: expected {expected}"


def test_new_site_groups_are_registered():
    ids = {s.id for s in SITES}
    auto = {"autobazar_sk", "autobazar_eu", "autobazar_cz", "mobile_de"}
    home = {"obi_sk", "merkurymarket_sk", "bauhaus_sk", "hornbach_sk",
            "jysk_sk", "favi_sk", "ikea_sk", "decathlon_sk"}
    assert auto <= ids
    assert home <= ids
    for site_id in auto:
        assert "auto" in next(s for s in SITES if s.id == site_id).categories