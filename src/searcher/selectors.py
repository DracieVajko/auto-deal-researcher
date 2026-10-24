"""Site-specific CSS/XPath selectors for each supported marketplace.

Every site appears exactly once: duplicate keys would silently keep only the
last definition and drop the richer selector lists of the earlier ones.
"""

SELECTORS = {
    "alza": {
        "listing": ".browsingitem",
        "title": ".name",
        "price": ".price-box__price, .price-box__price--final",
        "link": ".browsinglink, a[href*='/d']",
        "image": ".browsingitem img",
        "condition": ".badge--opened, .label--opened",
        "seller": ".seller-name, .seller-info",
        "price_pattern": r"([\d\s.,]+)\s*€",
        "pagination": ".paging a.next, .paging a[rel='next']",
        "search_url_template": "https://www.alza.sk/search.htm?exps={query}",
    },
    "bazos": {
        "listing": ".inzeraty > div",
        "title": ".nadpis a, a[href*='inzerat']",
        "price": "span, b, strong",
        "link": ".nadpis a, a[href*='inzerat']",
        "image": "img",
        "price_pattern": r"([\d\s.,]+)\s*€",
        "pagination": ".strankovani a, .strankovani a.next",
        "search_url_template": "https://www.bazos.sk/search.php?hledat={query}",
    },
    "backmarket": {
        "listing": '[data-testid="product-card"]',
        "title": '[data-testid="product-title"]',
        "price": '[data-testid="product-price"]',
        "link": 'a[href*="/p/"]',
        "image": 'img[data-testid="product-image"]',
        "condition": "refurbished",
        "pagination": ".pagination a.next, a[rel='next']",
        "search_url_template": "https://www.backmarket.sk/sk-sk/search?q={query}",
    },
    "ebay": {
        "listing": ".s-card, .s-item, .srp-results .s-item",
        "title": ".s-card__title, .s-item__title, h3",
        "price": ".s-card__price, .s-item__price, .x-price-primary",
        "link": "a[href*='/itm/'], a.s-item__link, .s-card__link",
        "image": "img.s-item__image-img, img.s-card__image",
        "condition": ".s-item__subtitle, .SECONDARY_INFO, .x-item-condition",
        "price_pattern": r"(?:EUR\s*)?([\d\s.,]+)",
        "pagination": ".pagination__next, a.pagination__next, a[aria-label='Next']",
        "search_url_template": "https://www.ebay.de/sch/i.html?_nkw={query}&_sacat=0",
    },
    "heureka": {
        "listing": '[data-testid="product-card"], .product-card, .product-item',
        "title": '[data-testid="product-title"], .product-title, h3',
        "price": '[data-testid="product-price"], .price, .product-price',
        "link": 'a[href*="/p/"], a.product-link',
        "shop": '[data-testid="shop-name"], .shop-name',
        "condition": "[data-condition], .condition",
        "pagination": ".pagination a.next, a[rel='next']",
        "search_url_template": "https://www.heureka.sk/sk-sk/search?q={query}",
    },
    "mall": {
        "listing": ".product-item, .product-card, .product-tile",
        "title": ".product-title, .product-name, h3 a",
        "price": ".price, .product-price, .price-final",
        "link": "a.product-link, h3 a",
        "condition": ".condition, .product-condition",
        "pagination": ".pagination a.next, a[rel='next']",
        "search_url_template": "https://www.mall.sk/search?q={query}",
    },
    "nay": {
        "listing": ".product-box, .product-item, [data-product-id]",
        "title": ".product-box__name, .product-item__name, h2 a, h3 a",
        # .item-price .actual holds "Cena s DPH: 1 759,00 €"; a loose .price
        # matches screen-size badges and returns the wrong number.
        "price": ".item-price .actual, .item-price",
        "link": "h2 a, h3 a, a[href*='/p/']",
        "image": "img",
        "condition": ".badge, .label",
        "seller": ".seller, .shop",
        "price_pattern": r"([\d\s.,]+)\s*€",
        "pagination": ".paging a.next, a[rel='next']",
        "search_url_template": "https://www.nay.sk/vyhladavanie?q={query}",
    },
    "idealo": {
        "listing": ".product-card, .product-item, .offer",
        "title": ".product-title, .product-name, h3 a",
        "price": ".price, .price-value, .offer-price",
        "link": "a[href*='/angebot/'], a.product-link",
        "shop": ".shop-name, .merchant-name",
        "condition": ".condition, .offer-condition",
        "pagination": ".pagination a.next",
        "search_url_template": "https://www.idealo.de/preisvergleich/SearchProduct?query={query}",
    },
    "facebook": {
        "listing": '[role="feed"] > div > div > div > div > a',
        "title": 'span[dir="auto"]',
        "price": 'span:has-text("€")',
        "link": "a",
        "condition": "used",
        "pagination": "infinite scroll",
        "search_url_template": "https://www.facebook.com/marketplace/search/?query={query}",
    },
}

# Default fallback selectors for unknown sites
DEFAULT_SELECTORS = {
    "listing": ".product, .item, .product-card, .item-card, [data-product]",
    "title": "h1, h2, h3, .title, .product-title, .name",
    "price": ".price, .price-box__price, .product-price, [class*='price']",
    "link": "a[href]",
    "image": "img",
    "condition": ".condition, .badge, .label",
    "seller": ".seller, .shop, .merchant",
    "pagination": ".pagination a.next, a.next, a[rel='next']",
}


def get_selectors(site_id: str) -> dict:
    """Get selectors for a site, with fallback to defaults."""
    return SELECTORS.get(site_id.lower(), DEFAULT_SELECTORS)


def _extract_price(text: str) -> float | None:
    """Extract price in EUR from text."""
    if not text:
        return None
    # Remove currency symbols and normalize
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = text.replace("EUR", "").replace("€", "").strip()
    # Handle European format: 1.299,50 -> 1299.50
    text = text.replace(" ", "")
    if "," in text and "." in text:
        # European: 1.299,50 -> 1299.50
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        parts = text.rsplit(",", 1)
        if len(parts[1]) <= 2:
            text = parts[0].replace(".", "") + "." + parts[1]
        else:
            text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None
