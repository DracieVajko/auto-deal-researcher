"""POM registry mapping website name to page classes."""

from src.browser.pom.pages import (
    AlzaHome,
    AlzaProductDetail,
    AlzaSearchResults,
    BackMarketHome,
    BackMarketProductDetail,
    BackMarketSearchResults,
    BazosHome,
    BazosListingDetail,
    BazosSearchResults,
    EbayHome,
    EbayItemDetail,
    EbaySearchResults,
    FacebookListingDetail,
    FacebookMarketplaceHome,
    FacebookSearchResults,
)

POM_REGISTRY = {
    "alza": {"Home": AlzaHome, "SearchResults": AlzaSearchResults, "ProductDetail": AlzaProductDetail},
    "bazos": {"Home": BazosHome, "SearchResults": BazosSearchResults, "ProductDetail": BazosListingDetail},
    "backmarket": {"Home": BackMarketHome, "SearchResults": BackMarketSearchResults, "ProductDetail": BackMarketProductDetail},
    "ebay": {"Home": EbayHome, "SearchResults": EbaySearchResults, "ProductDetail": EbayItemDetail},
    "facebook": {"Home": FacebookMarketplaceHome, "SearchResults": FacebookSearchResults, "ProductDetail": FacebookListingDetail},
}
