import requests
from bs4 import BeautifulSoup
import re
import json
import os
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketGuardBot/1.0)"
}

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
        response = requests.get(search_url, headers=HEADERS, timeout=20)
        if response.status_code == 200:
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
            # On HTTP error, fall back to stale cache if available
            if entry:
                return {
                    "avg_resale_price": float(entry.get("avg_resale_price", 0.0)),
                    "volume_30d": int(entry.get("volume_30d", 0))
                }
    except Exception:
        # On network error, fall back to stale cache if available
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

if __name__ == "__main__":
    print(get_mercari_resale_data("Fluke 117 Multimeter"))