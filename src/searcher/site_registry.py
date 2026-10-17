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

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SiteSpec:
    id: str
    name: str
    base_url: str
    adapter_class: str
    categories: tuple[str, ...]
    conditions: tuple[str, ...]
    status: str  # working | blocked | needs_auth | planned
    notes: str = ""


# fmt: off
SITES: list[SiteSpec] = [
    # --- verified working -------------------------------------------------
    SiteSpec("alza", "Alza.sk/cz", "https://www.alza.sk", "alza",
             ("electronics", "appliances"), ("new", "open_box"), "working",
             "Search via /search.htm?exps=. Cards are .browsingitem."),
    SiteSpec("bazos", "Bazos.sk/cz", "https://www.bazos.sk", "bazos",
             ("electronics", "appliances", "auto", "general"), ("used",), "working",
             "Classifieds. Grouped 5-div layout. TermsFeed cookie consent."),

    # --- blocked ---------------------------------------------------------
    SiteSpec("backmarket", "BackMarket.sk", "https://www.backmarket.sk", "backmarket",
             ("electronics",), ("refurbished",), "blocked",
             "Cloudflare interstitial never clears for automated sessions. "
             "Correct path is /sk-sk/search; adapter fails fast."),
    SiteSpec("ebay", "eBay.de/co.uk", "https://www.ebay.de", "ebay",
             ("electronics", "appliances", "auto", "general"),
             ("used", "refurbished", "new", "open_box"), "blocked",
             "Rate-limited and serves decoy listings. Official Browse API is the "
             "supported route; HTML scraper kept as fallback only."),

    # --- needs auth ------------------------------------------------------
    SiteSpec("facebook", "Facebook Marketplace", "https://www.facebook.com/marketplace",
             "facebook", ("electronics", "appliances", "auto", "general"),
             ("used", "marketplace"), "needs_auth",
             "Requires a logged-in CDP session. Use scripts/login.py first."),

    # --- planned / not yet implemented -----------------------------------
    SiteSpec("mall", "Mall.sk/cz", "https://www.mall.sk", "mall",
             ("electronics", "appliances", "auto", "general"), ("new", "open_box"), "planned",
             "Big SK/CZ retailer. Adapter not written yet."),
    SiteSpec("nay", "Nay.sk", "https://www.nay.sk", "nay",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             "Electronics retailer."),
    SiteSpec("datart", "Datart.sk/cz", "https://www.datart.sk", "datart",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             "Electronics retailer."),
    SiteSpec("heureka", "Heureka.sk", "https://www.heureka.sk", "heureka",
             ("electronics", "appliances", "auto", "general"), ("new", "used", "refurbished"), "planned",
             "Price comparison. Adapter can read the lowest offer per product."),
    SiteSpec("idealo", "Idealo.de", "https://www.idealo.de", "idealo",
             ("electronics", "appliances", "auto"), ("new", "used", "refurbished"), "planned",
             "German price comparison; useful for cross-border deals."),
    SiteSpec("aukro", "Aukro.cz", "https://aukro.cz", "aukro",
             ("electronics", "appliances", "auto", "general"),
             ("new", "used", "refurbished", "open_box"), "planned",
             "CZ auction marketplace. Adapter needs bid logic."),
    SiteSpec("sbazar", "Sbazar.cz", "https://www.sbazar.cz", "sbazar",
             ("electronics", "appliances", "auto", "general"), ("used",), "planned",
             "CZ classifieds (Seznam)."),
    SiteSpec("bazos_cz", "Bazos.cz", "https://www.bazos.cz", "bazos",
             ("electronics", "appliances", "auto", "general"), ("used",), "planned",
             "CZ Bazos; reuses the bazos adapter with a different base_url."),
    SiteSpec("amazon_de", "Amazon.de", "https://www.amazon.de", "amazon",
             ("electronics", "appliances", "auto", "general"),
             ("new", "used", "refurbished", "open_box"), "planned",
             "Official Product Advertising API is the supported route."),
    SiteSpec("alza_cz", "Alza.cz", "https://www.alza.cz", "alza",
             ("electronics", "appliances"), ("new", "open_box"), "planned",
             "CZ Alza; reuses the alza adapter with a different base_url."),
]
# fmt: on


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