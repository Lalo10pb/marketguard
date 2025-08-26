import requests
import os
import base64
import json
import re
from datetime import datetime


CATEGORIES = [
    "Milwaukee M18 Drill",
    "DeWalt Impact Driver",
    "Fluke Multimeter",
    "Ryobi Battery",
    "Makita Circular Saw",
    "Bosch Laser Level",
    "Snap-On Wrench",
    "Craftsman Toolbox",
    "Klein Tools",
    "Leatherman Multi Tool"
]


def get_ebay_access_token():
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("❌ Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET")
        return None
    creds = f"{client_id}:{client_secret}".encode("utf-8")
    b64 = base64.b64encode(creds).decode("utf-8")
    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    r = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=data, timeout=20)
    if r.status_code != 200:
        print("❌ eBay OAuth failed:", r.text)
        return None
    return r.json().get("access_token")

def is_quality_title(title: str) -> bool:
    """Return True if the title looks like a real, sellable item (not parts-only, broken, skins, etc.)."""
    t = title.lower()
    bad_terms = [
        "for parts", "parts only", "as-is", "as is", "not working", "doesn't work", "does not work",
        "broken", "defective", "faulty", "no power", "untested", "shell", "housing", "sticker",
        "skin", "decal", "wrap", "vinyl", "case only", "bag only", "cover only", "faceplate",
        "bezel", "repair", "spares", "scrap", "junk", "damaged"
    ]
    # Allow common legit phrases
    # (we are not excluding these; they are not in bad_terms)
    # e.g., "bare tool", "tool only" often indicate legit listings without batteries/charger
    return not any(b in t for b in bad_terms)

def search_ebay_api(query, token, limit=50):
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "limit": str(limit),
        "sort": "newlyListed",
        "filter": "buyingOptions:{FIXED_PRICE|BEST_OFFER|AUCTION},price:[15..300],conditions:{NEW|USED|OPEN_BOX|CERTIFIED_REFURBISHED|SELLER_REFURBISHED},itemLocationCountry:US"
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json"
    }
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if r.status_code != 200:
        print(f"❌ API search failed for '{query}':", r.text)
        return []
    data = r.json()
    items = data.get("itemSummaries", []) or []
    results = []
    seen_urls = set()
    seen_titles = set()
    for it in items:
        price_val = it.get("price", {}).get("value")
        title = it.get("title")
        weburl = it.get("itemWebUrl")
        if not (price_val and title and weburl):
            continue

        # Quality gate: drop junk/parts-only/etc.
        if not is_quality_title(title):
            continue

        # Simple dedupe by URL and normalized title
        norm_title = " ".join(title.lower().split())
        if weburl in seen_urls or norm_title in seen_titles:
            continue

        try:
            price = float(price_val)
        except Exception:
            continue
        seen_urls.add(weburl)
        seen_titles.add(norm_title)
        results.append({
            "title": title,
            "price": price,
            "url": weburl,
            "item_id": it.get("itemId"),
            "condition": it.get("condition"),
            "scanned_at": datetime.now().isoformat()
        })
    return results


def load_watchlist(path="watchlist.json"):
    """Load product keywords from a JSON file. Fallback to CATEGORIES if missing/invalid."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
        keywords = [s.strip() for s in data if isinstance(s, str) and s.strip()]
        if keywords:
            print(f"📄 Loaded {len(keywords)} keywords from {path}")
            return keywords
        else:
            raise ValueError("Empty watchlist")
    except Exception as e:
        print(f"⚠️ Could not load {path} ({e}). Using built-in defaults.")
        return CATEGORIES

if __name__ == "__main__":
    keywords = load_watchlist()

    token = get_ebay_access_token()
    if not token:
        print("❌ Cannot proceed without eBay access token. Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET.")
        raise SystemExit(1)

    all_results = []
    for keyword in keywords:
        print(f"🔎 API scanning: {keyword}")
        found = search_ebay_api(keyword, token, limit=50)
        all_results.extend(found)

    with open("results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"✅ Saved {len(all_results)} items to results.json")