def test_product_card_parse():
    from src.browser.pom.components.product_card import ProductCard
    assert ProductCard.extract_from_html("<div></div>") is not None


def test_registry_has_all_sites():
    from src.browser.pom.registry import POM_REGISTRY
    assert set(POM_REGISTRY) >= {"alza", "bazos", "backmarket", "ebay", "facebook"}
