import json
import time
from mercari_scraper import get_mercari_resale_data
import os

# Tunable thresholds via environment variables (fallbacks shown)
MIN_VOLUME = int(os.getenv("MIN_VOLUME_30D", os.getenv("MIN_VOLUME", "10")))
MIN_PROFIT = float(os.getenv("MIN_PROFIT", "20"))
MIN_ROI_PCT = float(os.getenv("MIN_ROI_PCT", "20"))
FEES_PERCENT = float(os.getenv("FEES_PERCENT", "0.13"))  # ~10% fee + ship buffer

# Near-miss tuning (for logging/inspection only)
NEAR_MISS_DOLLARS = float(os.getenv("NEAR_MISS_DOLLARS", "5"))
NEAR_MISS_ROI_PCT = float(os.getenv("NEAR_MISS_ROI_PCT", "5"))

def analyze_item(item):
    title = item["title"]
    buy_price = item["price"]

    resale_data = get_mercari_resale_data(title)
    avg_resale = resale_data.get("avg_resale_price", 0.0)
    volume = resale_data.get("volume_30d", 0)

    # Guard: no resale signal
    if avg_resale == 0.0 or volume == 0:
        return {
            "title": title,
            "buy_price": buy_price,
            "avg_resale": avg_resale,
            "volume": volume,
            "estimated_profit": 0.0,
            "roi_percent": 0.0,
            "flip": False,
            "near_miss": False,
            "near_miss_reasons": [],
            "url": item["url"],
            "category": item.get("category", "Unknown")
        }

    # Economics
    estimated_profit = round(avg_resale * (1 - FEES_PERCENT) - buy_price, 2)
    roi = round((estimated_profit / buy_price * 100), 1) if buy_price > 0 else 0.0

    # Flip decision based on thresholds
    flip = (volume >= MIN_VOLUME) and (estimated_profit >= MIN_PROFIT) and (roi >= MIN_ROI_PCT)

    # Near-miss logic for visibility (not a flip)
    near_miss = False
    reasons = []
    if not flip and volume >= max(1, MIN_VOLUME - 1):
        if estimated_profit >= (MIN_PROFIT - NEAR_MISS_DOLLARS):
            near_miss = True
            reasons.append(f"profit within ${NEAR_MISS_DOLLARS} of min")
        if roi >= (MIN_ROI_PCT - NEAR_MISS_ROI_PCT):
            near_miss = True
            reasons.append(f"ROI within {NEAR_MISS_ROI_PCT}% of min")

    item["category"] = item.get("category", "Unknown")

    return {
        "title": title,
        "buy_price": buy_price,
        "avg_resale": avg_resale,
        "volume": volume,
        "estimated_profit": estimated_profit,
        "roi_percent": roi,
        "flip": flip,
        "near_miss": near_miss,
        "near_miss_reasons": reasons,
        "url": item["url"],
        "category": item.get("category", "Unknown")
    }

def run_analysis():
    if not os.path.exists("results.json"):
        print("⚠️ 'results.json' not found. Please run ebay_scraper.py first.")
        return

    with open("results.json", "r") as f:
        items = json.load(f)

        # Limit & sort for faster first pass (cheapest first)
        limit = int(os.getenv("ANALYZE_LIMIT", "60"))
        items = sorted(items, key=lambda it: float(it.get("price") or 0))
        items = items[:limit]
        total = len(items)

    report = []
    for idx, item in enumerate(items, 1):
        title = item.get("title", "(no title)")
        buying_options = set(item.get("buying_options", []))
        if "AUCTION" in buying_options and "FIXED_PRICE" not in buying_options:
            print(f"⏩ Skipping auction-only listing: {title}")
            continue

        print(f"🔎 [{idx}/{total}] {title}")
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