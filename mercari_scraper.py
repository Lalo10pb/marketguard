import requests
from bs4 import BeautifulSoup
import re
import json
import os
from datetime import datetime, timedelta
import time
import random

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketGuardBot/1.0)"
}

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
]
CLOUD = os.getenv("MG_CLOUD", "0") == "1"
REQUEST_TIMEOUT = 30 if CLOUD else 20
RETRY_ATTEMPTS = 4 if CLOUD else 2
BASE_DELAY = 1.2 if CLOUD else 0.5

CACHE_FILE = "mercari_cache.json"
CACHE_TTL_HOURS = 24

def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

def clean_price(text):
    return float(re.sub(r'[^\d.]', '', text))

def get_mercari_resale_data(query):
    key = (query or "").strip().lower()
    now = datetime.utcnow()
    cache = load_cache()

    # Serve fresh cache (<= 24h)
    entry = cache.get(key)
    if entry:
        try:
            ts = datetime.fromisoformat(entry.get("ts", ""))
            if ts and (now - ts) <= timedelta(hours=CACHE_TTL_HOURS):
                return {
                    "avg_resale_price": float(entry.get("avg_resale_price", 0.0)),
                    "volume_30d": int(entry.get("volume_30d", 0))
                }
        except Exception:
            pass

    # No fresh cache → scrape Mercari sold listings
    search_url = f"https://www.mercari.com/search/?keyword={query.replace(' ', '%20')}&status=sold"
    prices = []
    try:
        response = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                hdrs = HEADERS.copy()
                if CLOUD:
                    hdrs["User-Agent"] = random.choice(USER_AGENTS)
                response = requests.get(search_url, headers=hdrs, timeout=REQUEST_TIMEOUT)
                if response.status_code == 200:
                    break
                time.sleep(BASE_DELAY * (attempt + 1))
            except Exception:
                time.sleep(BASE_DELAY * (attempt + 1))

        if response and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            cards = soup.select('li[data-testid="item-cell"]')
            for card in cards[:15]:
                price_tag = card.select_one('div[data-testid="item-price"]')
                if price_tag:
                    try:
                        price = clean_price(price_tag.text)
                        prices.append(price)
                    except Exception:
                        continue
        else:
            # HTTP/network fallback to stale cache if available
            if entry:
                return {
                    "avg_resale_price": float(entry.get("avg_resale_price", 0.0)),
                    "volume_30d": int(entry.get("volume_30d", 0))
                }
    except Exception:
        if entry:
            return {
                "avg_resale_price": float(entry.get("avg_resale_price", 0.0)),
                "volume_30d": int(entry.get("volume_30d", 0))
            }

    if prices:
        avg_price = round(sum(prices) / len(prices), 2)
        vol = len(prices)
    else:
        avg_price = 0.0
        vol = 0

    # Write fresh cache
    cache[key] = {
        "avg_resale_price": avg_price,
        "volume_30d": vol,
        "ts": now.isoformat()
    }
    save_cache(cache)

    return {
        "avg_resale_price": avg_price,
        "volume_30d": vol
    }

# ---------------- Mercari BUY-SIDE live scan -----------------

BRAND_WHITELIST = [
    "milwaukee", "dewalt", "makita", "ryobi", "bosch", "fluke",
    "klein", "leatherman", "craftsman", "snap-on", "snap on", "snapon"
]
_extra_brands = os.getenv("BRAND_WHITELIST_EXTRA", "").strip()
if _extra_brands:
    BRAND_WHITELIST.extend([s.strip().lower() for s in _extra_brands.split(",") if s.strip()])

GENERIC_BATTERY_RE = re.compile(r"\b(?:\d+(?:\.\d+)?\s*ah|[234]pack)\b.*\bfor\s+(?:" + "|".join(BRAND_WHITELIST) + r")\b.*\bbattery\b", re.I)
PARTS_AI_RE = re.compile(r"\bparts\s*ai\d+\b", re.I)

ACCESSORY_TERMS = [
    "hard case", "carrying case", "travel case", "case for ",
    "bag", "pouch", "holster",
    "cover", "sleeve",
    "holder", "bit holder", "bit set", "flex shaft", "attachment",
    "adapter", "battery adapter", "mount", "strap",
    "organizer", "insert tray", "tray insert", "insert organizer", "insert for",
    "replacement housing", "replacement shell"
]

BAD_TERMS = [
    "for parts", "parts only", "as-is", "as is", "not working", "doesn't work", "does not work",
    "broken", "defective", "faulty", "no power", "untested", "shell", "housing", "sticker",
    "skin", "decal", "wrap", "faceplate", "bezel", "repair", "spares", "scrap", "junk", "damaged"
]

def _is_brand_ok(title: str) -> bool:
    t = (title or "").lower()
    return any(b in t for b in BRAND_WHITELIST)


def _is_quality_title_mercari(title: str) -> bool:
    t = (title or "").lower()
    if any(b in t for b in BAD_TERMS):
        return False
    if any(a in t for a in ACCESSORY_TERMS):
        return False
    if GENERIC_BATTERY_RE.search(t) or PARTS_AI_RE.search(t):
        return False
    # accessory phrasing like "for <brand>" + accessory word
    if " for " in t and any(f"for {b}" in t for b in BRAND_WHITELIST) and any(w in t for w in [
        "case", "cover", "adapter", "holder", "holster", "mount", "strap", "sticker", "skin", "decal", "wrap", "organizer", "tray", "insert"
    ]):
        return False
    return True


def _to_search_query_basic(title: str) -> str:
    """Minimal normalizer (brand + model tokens) for comps while scanning live."""
    t = (title or "").lower()
    # remove capacity Ah and fluff
    t = re.sub(r"\b\d+(?:\.\d+)?\s*ah\b", " ", t)
    t = re.sub(r"\b(tool\s*only|bare\s*tool|no\s*batter(?:y|ies)|no\s*charger|tested|works?|working|free\s*shipping)\b", " ", t)
    t = re.sub(r"[/|,]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    brand = None
    for b in BRAND_WHITELIST:
        if b in t:
            brand = b
            break

    pats = [r"\b\d{3,4}-\d{2}\b", r"\b[a-z]{2,}\d{2,}\b", r"\b\d{2,}[a-z]{1,}\b", r"\b\d{3,}\b", r"\bbl\d{4}\w*\b"]
    models = []
    for p in pats:
        models += re.findall(p, t)
    seen = set(); models = [m for m in models if not (m in seen or seen.add(m))]

    if brand and models:
        return f"{brand} " + " ".join(models[:3])
    return (brand or t)


def scan_mercari_live(keyword: str, max_pages: int = 1, min_price: float = None, max_price: float = None):
    """Yield live on-sale Mercari listings for a keyword, filtered for flip quality.
    Returns a list of dicts compatible with results.json items.
    """
    try:
        if min_price is None:
            try:
                min_price = float(os.getenv("MIN_PRICE", "15"))
            except Exception:
                min_price = 15.0
        if max_price is None:
            try:
                max_price = float(os.getenv("MAX_PRICE", "300"))
            except Exception:
                max_price = 300.0
        if max_price < min_price:
            min_price, max_price = max_price, min_price

        pages = max(1, int(max_pages or 1))
        out = []
        for pg in range(1, pages + 1):
            search_url = f"https://www.mercari.com/search/?keyword={keyword.replace(' ', '%20')}&status=on_sale&page={pg}"
            response = None
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    hdrs = HEADERS.copy()
                    if CLOUD:
                        hdrs["User-Agent"] = random.choice(USER_AGENTS)
                    response = requests.get(search_url, headers=hdrs, timeout=REQUEST_TIMEOUT)
                    if response.status_code == 200:
                        break
                    time.sleep(BASE_DELAY * (attempt + 1))
                except Exception:
                    time.sleep(BASE_DELAY * (attempt + 1))
            if not response or response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            cards = soup.select('li[data-testid="item-cell"]')
            for card in cards:
                title_tag = card.select_one('[data-testid="item-name"]') or card.select_one('a[title]')
                price_tag = card.select_one('div[data-testid="item-price"]')
                link_tag = card.select_one('a[href]')
                if not (title_tag and price_tag and link_tag):
                    continue
                try:
                    title = title_tag.get_text(strip=True)
                    price = clean_price(price_tag.get_text(strip=True))
                except Exception:
                    continue
                if price < min_price or price > max_price:
                    continue
                if not _is_brand_ok(title) or not _is_quality_title_mercari(title):
                    continue
                url = link_tag.get("href", "")
                if url and url.startswith("/"):
                    url = "https://www.mercari.com" + url

                # Optional quick comp using our sold scraper
                query = _to_search_query_basic(title)
                resale = get_mercari_resale_data(query)

                out.append({
                    "title": title,
                    "price": price,
                    "shipping_cost": 0.0,
                    "total_price": price,
                    "url": url,
                    "source": "mercari",
                    "marketplace": "mercari",
                    "resale_hint": resale,
                    "scanned_at": datetime.utcnow().isoformat()
                })

            # be nice between pages
            time.sleep(BASE_DELAY)
        return out
    except Exception:
        return []

if __name__ == "__main__":
    print(get_mercari_resale_data("Fluke 117 Multimeter"))