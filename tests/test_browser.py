def test_product_card_parse():
    from src.browser.pom.components.product_card import ProductCard
    assert ProductCard.extract_from_html("<div></div>") is not None
