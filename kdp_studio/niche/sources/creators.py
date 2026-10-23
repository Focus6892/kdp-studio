"""Amazon Creators API (successor of PA-API 5) as an official book data source.

Docs (fetched 2026-10-23): https://affiliate-program.amazon.com/creatorsapi/docs/en-us/
- Token: POST https://api.amazon.com/auth/o2/token (NA; EU api.amazon.co.uk, FE api.amazon.co.jp)
  JSON {grant_type: client_credentials, client_id, client_secret, scope: "creatorsapi::default"}
- Operations: POST https://creatorsapi.amazon/catalog/v1/searchItems | getItems
  headers Authorization: Bearer <token>, Content-Type: application/json, x-marketplace: www.amazon.com
  body: camelCase (partnerTag, keywords, searchIndex, resources, itemCount<=10, itemPage, marketplace, sortBy)
- Response: searchResult.items[] -> asin, detailPageURL, itemInfo.title.displayValue,
  itemInfo.byLineInfo.{contributors[],manufacturer,brand}, itemInfo.contentInfo.{pagesCount,publicationDate},
  itemInfo.classifications.binding, offersV2.listings[].price.money.amount,
  browseNodeInfo.websiteSalesRank.salesRank, browseNodeInfo.browseNodes[].salesRank
- No customer-review resource exists, so rating counts are unavailable from this source.
Eligibility: approved Associates account with >= 10 qualifying sales in the last 30 days;
initial limit 1 request/second and 8,640/day.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

from ..models import BookObservation, parse_date, parse_float, parse_int

log = logging.getLogger(__name__)

TOKEN_ENDPOINTS = {
    "NA": "https://api.amazon.com/auth/o2/token",
    "EU": "https://api.amazon.co.uk/auth/o2/token",
    "FE": "https://api.amazon.co.jp/auth/o2/token",
}
API_BASE = "https://creatorsapi.amazon/catalog/v1"
DEFAULT_RESOURCES = [
    "itemInfo.title",
    "itemInfo.byLineInfo",
    "itemInfo.contentInfo",
    "itemInfo.classifications",
    "offersV2.listings.price",
    "browseNodeInfo.websiteSalesRank",
    "browseNodeInfo.browseNodes.salesRank",
    "images.primary.medium",
]


def _dv(obj, *path, default=None):
    """Walk nested dicts; return `displayValue` if the leaf is a {displayValue: ...} dict."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    if isinstance(cur, dict) and "displayValue" in cur:
        return cur["displayValue"]
    return cur


def item_to_observation(item: dict, keyword: str, position: int, search_index: str = "Books") -> BookObservation | None:
    asin = item.get("asin")
    if not asin:
        return None
    info = item.get("itemInfo") or {}
    byline = info.get("byLineInfo") or {}
    contributors = byline.get("contributors") or []
    author = next((c.get("name") for c in contributors if str(c.get("roleType", c.get("role", ""))).lower() == "author"), None)
    if author is None and contributors:
        author = contributors[0].get("name")
    publisher = _dv(byline, "manufacturer") or _dv(byline, "brand")

    price = currency = list_price = None
    listings = (item.get("offersV2") or {}).get("listings") or []
    if listings:
        money = (listings[0].get("price") or {}).get("money") or {}
        price = parse_float(money.get("amount"))
        currency = money.get("currency")
        basis = ((listings[0].get("price") or {}).get("savingBasis") or {}).get("money") or {}
        list_price = parse_float(basis.get("amount"))

    bni = item.get("browseNodeInfo") or {}
    wsr = bni.get("websiteSalesRank") or {}
    bsr = parse_int(wsr.get("salesRank"))
    bsr_store = wsr.get("displayName") or wsr.get("contextFreeName") or search_index
    ranks = []
    for bn in bni.get("browseNodes") or []:
        r = parse_int(bn.get("salesRank"))
        if r is not None:
            ranks.append((str(bn.get("displayName") or bn.get("contextFreeName") or bn.get("id")), r))

    return BookObservation(
        keyword=keyword,
        source="creators",
        asin=asin,
        title=str(_dv(info, "title") or ""),
        author=author,
        price=price,
        list_price=list_price,
        currency=currency or "USD",
        bsr=bsr,
        bsr_store=bsr_store,
        category_ranks=ranks,
        pub_date=parse_date(_dv(info, "contentInfo", "publicationDate")),
        pages=parse_int(_dv(info, "contentInfo", "pagesCount")),
        publisher=publisher,
        format=_dv(info, "classifications", "binding"),
        position=position,
        url=item.get("detailPageURL"),
        cover_url=((item.get("images") or {}).get("primary") or {}).get("medium", {}).get("url"),
    )


class CreatorsClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        partner_tag: str | None = None,
        marketplace: str = "www.amazon.com",
        region: str = "NA",
        min_interval_s: float = 1.05,
    ):
        self.client_id = client_id or os.environ.get("CREATORS_CLIENT_ID") or os.environ.get("CREATORS_ACCESS_KEY")
        self.client_secret = client_secret or os.environ.get("CREATORS_CLIENT_SECRET") or os.environ.get("CREATORS_SECRET_KEY")
        self.partner_tag = partner_tag or os.environ.get("CREATORS_PARTNER_TAG")
        if not (self.client_id and self.client_secret and self.partner_tag):
            raise RuntimeError("Creators API needs CREATORS_CLIENT_ID, CREATORS_CLIENT_SECRET and CREATORS_PARTNER_TAG")
        self.marketplace = marketplace
        self.region = region
        self.min_interval_s = min_interval_s
        self._token: str | None = None
        self._token_expiry = 0.0
        self._last_call = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        body = json.dumps({"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret, "scope": "creatorsapi::default"}).encode()
        req = urllib.request.Request(TOKEN_ENDPOINTS[self.region], data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https endpoint
            data = json.load(resp)
        self._token = data["access_token"]
        self._token_expiry = time.time() + float(data.get("expires_in", 3600))
        return self._token

    def _post(self, operation: str, body: dict) -> dict:
        wait = self.min_interval_s - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            f"{API_BASE}/{operation}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json", "x-marketplace": self.marketplace},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https endpoint
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Creators API {operation} failed: HTTP {exc.code} {detail}") from exc
        finally:
            self._last_call = time.time()
        return data

    def search_items(self, keywords: str, search_index: str = "Books", item_page: int = 1, item_count: int = 10, sort_by: str | None = None, resources: list[str] | None = None) -> dict:
        body = {
            "partnerTag": self.partner_tag,
            "keywords": keywords,
            "searchIndex": search_index,
            "itemCount": min(max(item_count, 1), 10),
            "itemPage": item_page,
            "marketplace": self.marketplace,
            "resources": resources or DEFAULT_RESOURCES,
        }
        if sort_by:
            body["sortBy"] = sort_by
        return self._post("searchItems", body)

    def get_items(self, asins: list[str], resources: list[str] | None = None) -> dict:
        body = {
            "itemIds": asins[:10],
            "itemIdType": "ASIN",
            "marketplace": self.marketplace,
            "partnerTag": self.partner_tag,
            "resources": resources or DEFAULT_RESOURCES,
        }
        return self._post("getItems", body)


class CreatorsSource:
    name = "creators"

    def __init__(self, search_index: str = "Books", marketplace: str = "www.amazon.com", client: CreatorsClient | None = None):
        self.search_index = search_index
        self.client = client or CreatorsClient(marketplace=marketplace)

    def search(self, keyword: str, max_books: int) -> list[BookObservation]:
        out: list[BookObservation] = []
        pages = (max_books + 9) // 10
        for page in range(1, pages + 1):
            data = self.client.search_items(keyword, self.search_index, item_page=page)
            items = (data.get("searchResult") or {}).get("items") or []
            for item in items:
                obs = item_to_observation(item, keyword, len(out) + 1, self.search_index)
                if obs:
                    out.append(obs)
            if len(items) < 10:
                break
        return out[:max_books]
