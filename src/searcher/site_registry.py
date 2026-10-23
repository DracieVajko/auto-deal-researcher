"""Catalogue of sites the project knows about, with the categories each one
actually carries.

Adding a site to a user's config.yaml is not enough: searching for "drone"
on a pharmacy site wastes a request and pollutes the results. This module is
the single source of truth for *which* sites make sense for *which* category,
so the searcher can skip the irrelevant ones before opening a browser tab.

Status values:
  working  - adapter verified against the live DOM
  blocked  - anti-bot wall (Cloudflare / decoy); disabled by default
  needs_auth - requires a logged-in session (facebook)
  planned  - no adapter yet; listed so the user knows it is on the roadmap
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSpec:
    id: str
    name: str
    base_url: str
    adapter_class: str
    categories: tuple[str, ...]
    conditions: tuple[str, ...]
    status: str  # working | blocked | needs_auth | planned
    seller_type: str = "retailer"   # retailer | marketplace | classifieds | auction
    has_warranty: bool = False
    warranty_note: str = ""
    notes: str = ""
    discovery_queries: tuple[str, ...] = ()
    country: str = "SK"              # market the site belongs to: SK | CZ | DE | EU
    currency: str = "EUR"            # currency the site lists prices in


# fmt: off
SITES: list[SiteSpec] = [
    # --- verified working -------------------------------------------------
    SiteSpec("alza", "Alza.sk/cz", "https://www.alza.sk", "alza",
             ("electronics", "appliances"), ("new", "open_box"), "working",
             seller_type="retailer", has_warranty=True,
             warranty_note="New items carry the manufacturer warranty; open-box carries Alza's warranty.",
             notes="Search via /search.htm?exps=. Cards are .browsingitem.",
             country="SK", currency="EUR"),
    SiteSpec("bazos", "Bazos.sk/cz", "https://www.bazos.sk", "bazos",
             ("electronics", "appliances", "auto", "general"), ("used",), "working",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers; warranty only if they hand over the receipt.",
             notes="Classifieds. Grouped 5-div layout. TermsFeed cookie consent.",
             country="SK", currency="EUR"),

    # --- blocked ---------------------------------------------------------
    SiteSpec("backmarket", "BackMarket.sk", "https://www.backmarket.sk", "backmarket",
             ("electronics",), ("refurbished",), "blocked",
             seller_type="marketplace", has_warranty=True,
             warranty_note="BackMarket provides its own warranty on refurbished items.",
             notes="Cloudflare interstitial never clears for automated sessions. "
             "Correct path is /sk-sk/search; adapter fails fast.",
             country="SK", currency="EUR"),
    SiteSpec("ebay", "eBay.de/co.uk", "https://www.ebay.de", "ebay",
             ("electronics", "appliances", "auto", "general"),
             ("used", "refurbished", "new", "open_box"), "blocked",
             seller_type="marketplace", has_warranty=False,
             warranty_note="eBay Money Back Guarantee; manufacturer warranty only if the seller provides it.",
             notes="Rate-limited and serves decoy listings. HTML scraper kept as fallback only.",
             country="DE", currency="EUR"),

    # --- needs auth ------------------------------------------------------
    SiteSpec("facebook", "Facebook Marketplace", "https://www.facebook.com/marketplace",
             "facebook", ("electronics", "appliances", "auto", "general"),
             ("used", "marketplace"), "needs_auth",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers; warranty depends on the seller.",
             notes="Requires a logged-in CDP session. Use scripts/login.py first.",
             country="EU", currency="EUR"),

    # --- planned / not yet implemented -----------------------------------
    SiteSpec("mall", "Mall.sk/cz", "https://www.mall.sk", "mall",
             ("electronics", "appliances", "auto", "general"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new and open-box items.",
             notes="Big SK/CZ retailer. Adapter not written yet.",
             country="SK", currency="EUR"),
    SiteSpec("nay", "Nay.sk", "https://www.nay.sk", "nay",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Electronics retailer.",
             country="SK", currency="EUR"),
    SiteSpec("datart", "Datart.sk/cz", "https://www.datart.sk", "datart",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Electronics retailer.",
             country="SK", currency="EUR"),
    SiteSpec("heureka", "Heureka.sk", "https://www.heureka.sk", "heureka",
             ("electronics", "appliances", "auto", "general"), ("new", "used", "refurbished"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Warranty depends on the underlying shop.",
             notes="Price comparison. Adapter can read the lowest offer per product.",
             country="SK", currency="EUR"),
    SiteSpec("idealo", "Idealo.de", "https://www.idealo.de", "idealo",
             ("electronics", "appliances", "auto"), ("new", "used", "refurbished"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Warranty depends on the underlying shop.",
             notes="German price comparison; useful for cross-border deals.",
             country="DE", currency="EUR"),
    SiteSpec("aukro", "Aukro.cz", "https://aukro.cz", "aukro",
             ("electronics", "appliances", "auto", "general"),
             ("new", "used", "refurbished", "open_box"), "planned",
             seller_type="auction", has_warranty=False,
             warranty_note="Auction; warranty only if the seller provides it.",
             notes="CZ auction marketplace. Adapter needs bid logic.",
             country="CZ", currency="CZK"),
    SiteSpec("sbazar", "Sbazar.cz", "https://www.sbazar.cz", "sbazar",
             ("electronics", "appliances", "auto", "general"), ("used",), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers; warranty depends on the seller.",
             notes="CZ classifieds (Seznam).",
             country="CZ", currency="CZK"),
    SiteSpec("bazos_cz", "Bazos.cz", "https://www.bazos.cz", "bazos",
             ("electronics", "appliances", "auto", "general"), ("used",), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers; warranty only if they hand over the receipt.",
             notes="CZ Bazos; reuses the bazos adapter with a different base_url.",
             country="CZ", currency="CZK"),
    SiteSpec("amazon_de", "Amazon.de", "https://www.amazon.de", "amazon",
             ("electronics", "appliances", "auto", "general"),
             ("new", "used", "refurbished", "open_box"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Amazon's own returns; third-party warranty varies.",
             notes="Official Product Advertising API is the supported route.",
             country="DE", currency="EUR"),
    SiteSpec("alza_cz", "Alza.cz", "https://www.alza.cz", "alza",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="New items carry the manufacturer warranty; open-box carries Alza's warranty.",
             notes="CZ Alza; reuses the alza adapter with a different base_url.",
             country="CZ", currency="CZK"),
    SiteSpec("aliexpress", "AliExpress", "https://www.aliexpress.com", "aliexpress",
             ("electronics", "appliances", "auto", "general"),
             ("new",), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="AliExpress buyer protection only; no manufacturer warranty.",
             notes="Official Affiliate API is the supported route; scraping is blocked.",
             country="EU", currency="EUR"),
    SiteSpec("prisiel", "Prisiel.sk", "https://www.prisiel.sk", "prisiel",
             ("electronics",), ("new", "used"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Depends on the seller.",
             notes="SK classifieds.",
             country="SK", currency="EUR"),
    SiteSpec("bazar_sk", "Bazar.sk", "https://www.bazar.sk", "bazar_sk",
             ("electronics", "appliances", "auto", "general"), ("used",), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers; warranty only with receipt.",
             notes="SK classifieds.",
             country="SK", currency="EUR"),
    SiteSpec("sauto", "Sauto.cz", "https://www.sauto.cz", "sauto",
             ("auto",), ("used", "new"), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Depends on the seller.",
             notes="CZ auto classifieds; only auto category.",
             country="CZ", currency="CZK"),
    SiteSpec("sreality", "Sreality.cz", "https://www.sreality.cz", "sreality",
             ("general",), ("new", "used"), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="n/a",
             notes="CZ real estate; general category only.",
             country="CZ", currency="CZK"),
    SiteSpec("mimibazar", "Mimibazar.sk", "https://www.mimibazar.sk", "mimibazar",
             ("electronics", "appliances", "auto", "general"), ("used",), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers.",
             notes="SK classifieds; lots of used electronics.",
             country="SK", currency="EUR"),

    # --- auto markets: Slovakia ------------------------------------------
    SiteSpec("autobazar_sk", "Autobazar.sk", "https://www.autobazar.sk", "autobazar",
             ("auto",), ("used", "new"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Dealer warranty varies by seller.",
             notes="Ringier SK auto portal. Prices in EUR.",
             country="SK", currency="EUR"),
    SiteSpec("autobazar_eu", "Autobazar.EU", "https://www.autobazar.eu", "autobazar",
             ("auto",), ("used", "new"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Dealer warranty varies by seller.",
             notes="310k+ listings across SK/CZ/PL. Prices in EUR.",
             country="EU", currency="EUR"),

    # --- auto markets: Czech Republic ------------------------------------
    SiteSpec("autobazar_cz", "Autobazar.cz", "https://www.autobazar.cz", "autobazar",
             ("auto",), ("used", "new"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Dealer warranty varies by seller.",
             notes="Redirects to Autobazar.EU. Prices in EUR.",
             country="CZ", currency="EUR"),
    SiteSpec("garaz_cz", "Garaz.cz", "https://www.garaz.cz", "garaz",
             ("auto",), ("used", "new"), "planned",
             seller_type="classifieds", has_warranty=False,
             warranty_note="Private sellers or dealers; warranty depends on the seller.",
             notes="Seznam's garage. Prices in CZK.",
             country="CZ", currency="CZK"),
    SiteSpec("tipcars_cz", "TipCars.com", "https://www.tipcars.com", "tipcars",
             ("auto",), ("used", "new"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Dealer warranty varies by seller.",
             notes="Largest CZ auto ad aggregator, mostly newer cars. Prices in CZK.",
             country="CZ", currency="CZK"),
    SiteSpec("auto_cz", "Auto.cz", "https://www.auto.cz", "auto_cz",
             ("auto",), ("used", "new"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Dealer warranty varies by seller.",
             notes="Seznam's auto portal. Prices in CZK.",
             country="CZ", currency="CZK"),

    # --- auto markets: Germany -------------------------------------------
    SiteSpec("mobile_de", "mobile.de", "https://www.mobile.de", "mobile_de",
             ("auto",), ("used", "new"), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Dealer warranty varies by seller.",
             notes="Germany's largest vehicle marketplace. Prices in EUR.",
             country="DE", currency="EUR"),

    # --- home, furniture, DIY: Slovakia ----------------------------------
    SiteSpec("obi_sk", "OBI Slovensko", "https://www.obi.sk", "obi",
             ("home", "hobby"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new and open-box items.",
             notes="Everything for home, flat, garden and building.",
             country="SK", currency="EUR"),
    SiteSpec("merkurymarket_sk", "Merkury Market", "https://www.merkurymarket.sk", "merkurymarket",
             ("home", "hobby"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Building supplies, furniture, garden and tools.",
             country="SK", currency="EUR"),
    SiteSpec("dek_sk", "Stavebniny DEK", "https://dek.sk", "dek",
             ("home", "hobby"), ("new",), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Building materials chain.",
             country="SK", currency="EUR"),
    SiteSpec("bauhaus_sk", "BAUHAUS Slovensko", "https://www.bauhaus.sk", "bauhaus",
             ("home", "hobby"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new and open-box items.",
             notes="Workshop, house and garden specialist.",
             country="SK", currency="EUR"),
    SiteSpec("hornbach_sk", "Hornbach Slovensko", "https://www.hornbach.sk", "hornbach",
             ("home", "hobby"), ("new", "open_box"), "blocked",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new and open-box items.",
             notes="Serves a 'Client Challenge' bot wall; blocked for automated sessions.",
             country="SK", currency="EUR"),
    SiteSpec("jysk_sk", "JYSK Slovensko", "https://jysk.sk", "jysk",
             ("home",), ("new",), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Furniture, mattresses, textiles and garden.",
             country="SK", currency="EUR"),
    SiteSpec("favi_sk", "FAVI.sk", "https://favi.sk", "favi",
             ("home",), ("new",), "planned",
             seller_type="marketplace", has_warranty=False,
             warranty_note="Furniture sold by third-party shops; warranty varies.",
             notes="Furniture and decor search engine that links out to the shops.",
             country="SK", currency="EUR"),
    SiteSpec("ikea_sk", "IKEA Slovensko", "https://www.ikea.com/sk/sk/", "ikea",
             ("home",), ("new",), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="IKEA warranty on new items.",
             notes="Furniture and home accessories.",
             country="SK", currency="EUR"),
    SiteSpec("herman_sk", "HERMAN Professional", "https://www.herman.sk", "herman",
             ("hobby",), ("new",), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Manufacturer warranty on new tools.",
             notes="Professional tools and machinery.",
             country="SK", currency="EUR"),

    # --- home and hobby: Czech Republic ---------------------------------
    SiteSpec("hobbyshop_cz", "Hobbyshop.cz", "https://www.hobbyshop.cz", "hobbyshop",
             ("hobby",), ("new",), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Models, RC, camping and hobby supplies. Prices in CZK.",
             country="CZ", currency="CZK"),
    SiteSpec("decathlon_sk", "Decathlon Slovensko", "https://www.decathlon.sk", "decathlon",
             ("hobby",), ("new",), "blocked",
             seller_type="retailer", has_warranty=True,
             warranty_note="Retailer warranty on new items.",
             notes="Sport and outdoor gear. Sits behind a Cloudflare wall.",
             country="SK", currency="EUR"),

    # --- electronics: Czech Republic -------------------------------------
    SiteSpec("mironet_cz", "Mironet.cz", "https://www.mironet.cz", "mironet",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             seller_type="retailer", has_warranty=True,
             warranty_note="Manufacturer warranty on new items.",
             notes="CZ electronics and appliances retailer. Prices in CZK.",
             country="CZ", currency="CZK"),
]
# fmt: on


# Discovery seeds. A real query is better than a site's empty search page:
# it forces the search form and result cards to render so the recorder can
# classify them.
DEFAULT_DISCOVERY_QUERIES = {
    "electronics": "notebook",
    "appliances": "washing machine",
    "auto": "car",
    "home": "stol",
    "hobby": "náradie",
    "general": "deal",
}

SITE_DISCOVERY_OVERRIDES = {
    "sreality": {"general": "byt"},
    "sauto": {"auto": "octavia"},
    "mimibazar": {"electronics": "notebook"},
    "autobazar_sk": {"auto": "skoda fabia"},
    "autobazar_eu": {"auto": "skoda fabia"},
    "autobazar_cz": {"auto": "skoda fabia"},
    "garaz_cz": {"auto": "skoda fabia"},
    "tipcars_cz": {"auto": "skoda kodiaq"},
    "auto_cz": {"auto": "skoda kodiaq"},
    "mobile_de": {"auto": "vw golf"},
    "jysk_sk": {"home": "postel"},
    "favi_sk": {"home": "stol"},
    "ikea_sk": {"home": "stol"},
    "herman_sk": {"hobby": "vrtak"},
    "hobbyshop_cz": {"hobby": "rc auto"},
    "mironet_cz": {"electronics": "notebook"},
    "hornbach_sk": {"home": "vrtak", "hobby": "vrtak"},
    "bauhaus_sk": {"home": "vrtak", "hobby": "vrtak"},
    "obi_sk": {"home": "vrtak", "hobby": "vrtak"},
    "merkurymarket_sk": {"home": "vrtak", "hobby": "vrtak"},
    "dek_sk": {"home": "cement", "hobby": "vrtak"},
    "decathlon_sk": {"hobby": "bicykel"},
}


def seed_query(site_id: str, category: str = "any") -> str:
    """Return a useful search seed for a site/category."""
    spec = by_id(site_id)
    if spec and spec.discovery_queries:
        return spec.discovery_queries[0]
    overrides = SITE_DISCOVERY_OVERRIDES.get(site_id, {})
    if category in overrides:
        return overrides[category]
    if overrides:
        return next(iter(overrides.values()))
    return DEFAULT_DISCOVERY_QUERIES.get(category, DEFAULT_DISCOVERY_QUERIES["general"])


def sites_for(category: str, condition: str = "any") -> list[SiteSpec]:
    """Sites that actually carry a category/condition, so we never search a
    pharmacy site for a drone. Status is ignored; enabled/disabled is a
    runtime concern handled by config.yaml."""
    out = []
    for spec in SITES:
        if category not in ("any",) and category not in spec.categories:
            continue
        if condition not in ("any",) and condition not in spec.conditions:
            continue
        out.append(spec)
    return out


def by_id(site_id: str) -> SiteSpec | None:
    for spec in SITES:
        if spec.id == site_id:
            return spec
    return None


def by_status(status: str) -> list[SiteSpec]:
    return [s for s in SITES if s.status == status]


def summary() -> dict[str, int]:
    out: dict[str, int] = {}
    for spec in SITES:
        out[spec.status] = out.get(spec.status, 0) + 1
    return out