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

# Brand whitelist — only accept listings that mention at least one of these
BRAND_WHITELIST = [
    "milwaukee", "dewalt", "makita", "ryobi", "bosch", "fluke",
    "klein", "leatherman", "craftsman", "snap-on", "snap on", "snapon"
]
# Optional: extend via env var BRAND_WHITELIST_EXTRA="ridgid, dremel, metabo"
_extra_brands = os.getenv("BRAND_WHITELIST_EXTRA", "").strip()
if _extra_brands:
    BRAND_WHITELIST.extend([s.strip().lower() for s in _extra_brands.split(",") if s.strip()])

# Extra API-level discard patterns (belt-and-suspenders in addition to is_quality_title)
GENERIC_BATTERY_RE = re.compile(r"\b(?:\d+(?:\.\d+)?\s*ah|[234]pack)\b.*\bfor\s+(?:" + "|".join(BRAND_WHITELIST) + r")\b.*\bbattery\b", re.I)
PARTS_AI_RE = re.compile(r"\bparts\s*ai\d+\b", re.I)

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
    """Return True if the title looks like a real, sellable item (not parts-only, broken, or accessories)."""
    t = title.lower()

    # Obvious junk / broken / parts-only
    bad_terms = [
        "for parts", "parts only", "as-is", "as is", "not working", "doesn't work", "does not work",
        "broken", "defective", "faulty", "no power", "untested", "shell", "housing", "sticker",
        "skin", "decal", "wrap", "vinyl", "faceplate", "bezel", "repair", "spares", "scrap", "junk", "damaged",
        # Frequently accessory-only phrases we never want
        "case only", "bag only", "cover only"
    ]

    # Accessory keywords that typically aren't flips
    accessory_terms = [
        "hard case", "carrying case", "travel case", "case for ",
        "bag", "pouch", "holster",
        "cover", "sleeve",
        "holder", "bit holder", "bit set", "flex shaft", "right angle flex shaft",
        "attachment", "adapter", "battery adapter", "mount", "strap",
        "organizer", "insert tray", "tray insert", "insert organizer", "insert for",
        "replacement housing", "replacement shell"
    ]

    if any(b in t for b in bad_terms):
        return False
    if any(a in t for a in accessory_terms):
        return False

    # Heuristic: third‑party accessories with "for <brand>" + accessory word
    if " for " in t:
        if any(f"for {b}" in t for b in BRAND_WHITELIST) and any(w in t for w in [
            "case", "cover", "adapter", "holder", "holster", "mount", "strap", "sticker", "skin", "decal", "wrap", "organizer", "tray", "insert"
        ]):
            return False

    # Generic/aftermarket battery filter: drop non-OEM "for <brand>" batteries
    oem_tokens = ["oem", "genuine", "original", "authentic", "factory"]

    # e.g., "9.0Ah For RYOBI P108 18V High Capacity Battery ...", "2PACK ... For RYOBI 18V Battery ..."
    has_for_brand = any(f"for {b}" in t for b in BRAND_WHITELIST)
    has_battery = "battery" in t
    has_capacity = bool(re.search(r"\b\d+(\.\d+)?\s*ah\b", t))

    if has_battery and has_for_brand and not any(tok in t for tok in oem_tokens):
        return False
    if has_battery and has_for_brand and has_capacity and not any(tok in t for tok in oem_tokens):
        return False
    if has_battery and has_for_brand and ("compatible with" in t or t.startswith("compatible with") or "fits " in t):
        return False

    # Drop eBay liquidation shorthand like "Parts Ai32", "Parts Ai39" etc.
    if re.search(r"\bparts\s*ai\d+\b", t):
        return False

    # Enforce brand whitelist: title must mention an approved brand
    if not any(b in t for b in BRAND_WHITELIST):
        return False

    # Allow legit phrases like "bare tool" / "tool only" (not an accessory)
    return True

def search_ebay_api(query, token, limit=50):
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    # Build price window from env (defaults 15..300)
    try:
        min_price = int(os.getenv("MIN_PRICE", "15"))
    except Exception:
        min_price = 15
    try:
        max_price = int(os.getenv("MAX_PRICE", "300"))
    except Exception:
        max_price = 300

    # Optional shipping ceiling (treat missing as unlimited)
    try:
        max_shipping = float(os.getenv("MAX_SHIPPING", ""))
    except Exception:
        max_shipping = None
    if max_shipping is not None and max_shipping < 0:
        max_shipping = None

    # Ensure sane order
    if max_price < min_price:
        min_price, max_price = max_price, min_price

    price_filter = f"price:[{min_price}..{max_price}]"

    filter_str = (
        "buyingOptions:{FIXED_PRICE|BEST_OFFER|AUCTION},"
        f"{price_filter},"
        "conditions:{NEW|USED|OPEN_BOX|CERTIFIED_REFURBISHED|SELLER_REFURBISHED},"
        "itemLocationCountry:US"
    )

    # Optional debug logging
    if os.getenv("QUERY_LOG", "0") == "1":
        print(f"🔎 API search '{query}' | {price_filter} | limit={limit}")

    params = {
        "q": query,
        "limit": str(limit),
        "sort": "newlyListed",
        "filter": filter_str,
        "fieldgroups": "EXTENDED",
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
        opts = it.get("buyingOptions", []) or []

        if not (price_val and title and weburl):
            continue

        # API-level prefilter (some noisy titles sneak past otherwise)
        t = title.lower()
        if GENERIC_BATTERY_RE.search(t) or PARTS_AI_RE.search(t):
            # print(f"⏩ API filter: dropping noisy battery/parts listing: {title}")
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

        # Extract shipping cost (requires fieldgroups=EXTENDED)
        shipping_cost = None
        ship_opts = it.get("shippingOptions") or []
        for opt in ship_opts:
            sc = (opt or {}).get("shippingCost", {}).get("value")
            try:
                if sc is not None:
                    sc = float(sc)
                    shipping_cost = sc if shipping_cost is None else min(shipping_cost, sc)
            except Exception:
                pass

        # If a shipping ceiling is configured, drop items that exceed it (when known)
        if max_shipping is not None and shipping_cost is not None and shipping_cost > max_shipping:
            continue

        total_price = price + (shipping_cost or 0.0)

        is_auction = ("AUCTION" in opts and "FIXED_PRICE" not in opts)

        seen_urls.add(weburl)
        seen_titles.add(norm_title)
        results.append({
            "title": title,
            "price": price,
            "url": weburl,
            "item_id": it.get("itemId"),
            "condition": it.get("condition"),
            "scanned_at": datetime.now().isoformat(),
            "buying_options": opts,
            "is_auction": is_auction,
            "shipping_cost": shipping_cost,
            "total_price": total_price
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