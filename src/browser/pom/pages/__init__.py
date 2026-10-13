"""Site page aliases."""

from src.browser.pom.pages.site_base import SiteHome, SiteProductDetail, SiteSearchResults

AlzaHome = SiteHome
AlzaSearchResults = SiteSearchResults
AlzaProductDetail = SiteProductDetail

BazosHome = SiteHome
BazosSearchResults = SiteSearchResults
BazosListingDetail = SiteProductDetail

BackMarketHome = SiteHome
BackMarketSearchResults = SiteSearchResults
BackMarketProductDetail = SiteProductDetail

EbayHome = SiteHome
EbaySearchResults = SiteSearchResults
EbayItemDetail = SiteProductDetail

FacebookMarketplaceHome = SiteHome
FacebookSearchResults = SiteSearchResults
FacebookListingDetail = SiteProductDetail

__all__ = [
    "AlzaHome", "AlzaSearchResults", "AlzaProductDetail",
    "BazosHome", "BazosSearchResults", "BazosListingDetail",
    "BackMarketHome", "BackMarketSearchResults", "BackMarketProductDetail",
    "EbayHome", "EbaySearchResults", "EbayItemDetail",
    "FacebookMarketplaceHome", "FacebookSearchResults", "FacebookListingDetail",
]
