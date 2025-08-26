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

if __name__ == "__main__":
    print(get_mercari_resale_data("Fluke 117 Multimeter"))