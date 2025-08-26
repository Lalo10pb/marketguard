import json
import time
from mercari_scraper import get_mercari_resale_data
import os

# Constants
MIN_VOLUME = 10         # 🔐 Minimum 10 units sold
MIN_PROFIT = 20.0       # 💰 At least $20 profit to flip
FEES_PERCENT = 0.13     # Mercari fees (~10% + shipping buffer)

def analyze_item(item):
    title = item["title"]
    buy_price = item["price"]

    resale_data = get_mercari_resale_data(title)
    if resale_data["volume_30d"] < MIN_VOLUME:
        return {
            "title": title,
            "buy_price": buy_price,
            "avg_resale": resale_data["avg_resale_price"],
            "volume": resale_data["volume_30d"],
            "estimated_profit": 0.0,
            "roi_percent": 0.0,
            "flip": False,
            "url": item["url"],
            "category": item.get("category", "Unknown")
        }
    if resale_data["avg_resale_price"] == 0.0 or resale_data["volume_30d"] < MIN_VOLUME:
        return {
            "title": title,
            "buy_price": buy_price,
            "avg_resale": resale_data["avg_resale_price"],
            "volume": resale_data["volume_30d"],
            "estimated_profit": 0.0,
            "roi_percent": 0.0,
            "flip": False,
            "url": item["url"]
        }

    avg_resale = resale_data["avg_resale_price"]
    volume = resale_data["volume_30d"]

    estimated_profit = round(avg_resale * (1 - FEES_PERCENT) - buy_price, 2)
    roi = round(estimated_profit / buy_price * 100, 1) if buy_price > 0 else 0

    flip = volume >= MIN_VOLUME and estimated_profit >= MIN_PROFIT
    item["category"] = item.get("category", "Unknown")

    return {
        "title": title,
        "buy_price": buy_price,
        "avg_resale": avg_resale,
        "volume": volume,
        "estimated_profit": estimated_profit,
        "roi_percent": roi,
        "flip": flip,
        "url": item["url"],
        "category": item.get("category", "Unknown")
    }

def run_analysis():
    if not os.path.exists("results.json"):
        print("⚠️ 'results.json' not found. Please run ebay_scraper.py first.")
        return

    with open("results.json", "r") as f:
        items = json.load(f)

    report = []
    for item in items:
        title = item.get("title", "(no title)")
        buying_options = set(item.get("buying_options", []))
        if "AUCTION" in buying_options and "FIXED_PRICE" not in buying_options:
            print(f"⏩ Skipping auction-only listing: {title}")
            continue

        print(f"🔎 Analyzing: {title}")
        result = analyze_item(item)
        result["category"] = item.get("category", "Unknown")
        report.append(result)
        time.sleep(2)  # Respectful delay to avoid Mercari rate limits

    with open("flip_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"✅ Analysis complete. Saved to flip_report.json")
    return report

if __name__ == "__main__":
    run_analysis()