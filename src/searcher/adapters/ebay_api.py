"""eBay Browse API adapter (official, replaces the HTML scraper).

Scraping ebay.de is unreliable: the site rate-limits automated searches and
serves decoy result pages to suspected scrapers (placeholder cards such as
"Shop on eBay"). The Browse API is the supported path and returns structured
data instead of HTML.

Credentials come from the environment (see .env.example):
    EBAY_APP_ID, EBAY_CERT_ID   -> OAuth2 client-credentials grant
    EBAY_SANDBOX                -> use sandbox.ebay.com when truthy
    EBAY_MARKETPLACE_ID         -> e.g. EBAY_DE (defaults to EBAY_DE)

NOTE: EBAY_DEV_ID / EBAY_RU_NAME are not used by the client-credentials
flow; they belong to other eBay auth flows and are listed in .env.example
only for completeness.

This adapter ignores the Playwright `page` argument so it can be driven by the
same PlaywrightSearcher loop as the HTML adapters.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, ClassVar

import requests

from .base import BaseAdapter, Deal, SiteBlockedError

logger = logging.getLogger(__name__)

PROD_HOST = "https://api.ebay.com"
SANDBOX_HOST = "https://api.sandbox.ebay.com"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"
TOKEN_PATH = "/identity/v1/oauth2/token"
SCOPE = "https://api.ebay.com/oauth/api_scope"

# Browse API condition ids mapped to the project's vocabulary.
CONDITION_MAP = {
    "NEW": "new",
    "LIKE_NEW": "new",
    "NEW_OTHER": "new",
    "NEW_WITH_DEFECTS": "new",
    "CERTIFIED_REFURBISHED": "refurbished",
    "EXCELLENT_REFURBISHED": "refurbished",
    "VERY_GOOD_REFURBISHED": "refurbished",
    "GOOD_REFURBISH": "refurbished",
    "SELLER_REFURBISHED": "refurbished",
    "USED_EXCELLENT": "used",
    "USED_VERY_GOOD": "used",
    "USED_GOOD": "used",
    "USED_ACCEPTABLE": "used",
    "FOR_PARTS_OR_NOT_WORKING": "used",
}


class EbayApiAdapter(BaseAdapter):
    name = "ebay_api"
    base_url = "https://www.ebay.de"
    results_selector = ""   # N/A: JSON API, no CSS selectors
    item_selector = ""      # N/A: JSON API, no CSS selectors
    supported_conditions: ClassVar[list[str]] = ["new", "used", "refurbished", "open_box"]
    supported_categories: ClassVar[list[str]] = ["electronics", "appliances", "auto", "general"]

    _token: str = ""
    _token_expires_at: float = 0.0

    def __init__(self) -> None:
        self.app_id = os.environ.get("EBAY_APP_ID", "").strip()
        self.cert_id = os.environ.get("EBAY_CERT_ID", "").strip()
        self.sandbox = os.environ.get("EBAY_SANDBOX", "").strip().lower() in {"1", "true", "yes"}
        self.marketplace = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_DE").strip() or "EBAY_DE"
        self.host = SANDBOX_HOST if self.sandbox else PROD_HOST
        self.request_timeout = float(os.environ.get("EBAY_TIMEOUT", "30"))

    # === auth ==============================================================
    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.cert_id)

    def _access_token(self) -> str:
        """Fetch (and cache) an OAuth2 client-credentials access token."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        if not self.configured:
            msg = "eBay API not configured: set EBAY_APP_ID and EBAY_CERT_ID in .env"
            raise SiteBlockedError(msg)

        basic = base64.b64encode(f"{self.app_id}:{self.cert_id}".encode()).decode()
        resp = requests.post(
            f"{self.host}{TOKEN_PATH}",
            data={
                "grant_type": "client_credentials",
                "scope": SCOPE,
            },
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=self.request_timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + float(payload.get("expires_in", 7200))
        return self._token

    # === search ============================================================
    async def search(self, page, query: str, max_results: int = 20) -> list[Deal]:
        """Search eBay through the official API. `page` is ignored."""
        token = self._access_token()
        params: dict[str, Any] = {"q": query, "limit": str(min(max_results, 50))}

        resp = requests.get(
            f"{self.host}{SEARCH_PATH}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                "Content-Type": "application/json",
            },
            timeout=self.request_timeout,
        )
        if resp.status_code == 401:
            # Token rejected: drop it so the next call re-authenticates.
            self._token = ""
            self._token_expires_at = 0.0
            msg = "eBay API rejected credentials (401)"
            raise SiteBlockedError(msg)
        resp.raise_for_status()

        items = resp.json().get("itemSummaries", []) or []
        deals = []
        for item in items[:max_results]:
            deal = self.to_deal(item)
            if deal:
                deals.append(deal)
        logger.info(f"[{self.name}] '{query}' -> {len(deals)} deals")
        return deals

    @staticmethod
    def to_deal(item: dict) -> Deal | None:
        """Map one Browse API itemSummary onto the project's Deal model."""
        url = item.get("itemWebUrl") or item.get("itemHref")
        title = item.get("title")
        price = (item.get("price") or {}).get("value")
        if not url or not title or price is None:
            return None

        try:
            price_eur = float(price)
        except (TypeError, ValueError):
            return None

        currency = (item.get("price") or {}).get("currency", "EUR")
        condition = CONDITION_MAP.get(
            (item.get("condition") or "").upper(), "used"
        )
        seller = item.get("seller") or {}

        return Deal(
            url=url,
            title=" ".join(title.split()),
            price_eur=price_eur,
            currency=currency,
            condition=condition,
            category="electronics",
            site_name="ebay_api",
            metadata={
                "source": "ebay_browse_api",
                "item_id": item.get("itemId", ""),
                "seller": seller.get("username", ""),
                "feedback_score": seller.get("feedbackScore", 0),
                "feedback_percentage": seller.get("feedbackPercentage", ""),
                "shipping": (item.get("shippingOptions") or [{}])[0].get("shippingCost", {}).get("value")
                if item.get("shippingOptions") else None,
                "item_location": (item.get("itemLocation") or {}).get("country", ""),
            },
        )

    async def extract_deal(self, page, element) -> Deal | None:
        """Not applicable: the API adapter has no HTML elements."""
        return None