import json
import os
import requests
from collections import defaultdict
from datetime import datetime

import random
import subprocess

# Helpers to inspect environment variables at runtime
def get_env(key, default=""):
    return os.getenv(key, default)

def show_token_info():
    t = get_env("TELEGRAM_BOT_TOKEN")
    c = get_env("TELEGRAM_CHAT_ID")
    t_mask = (t[:8] + "…") if t else "MISSING"
    print(f"🔐 Telegram env → TOKEN: {t_mask} | CHAT_ID: {c if c else 'MISSING'}")

def send_telegram_message(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping send")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code != 200:
            print("❌ Failed to send message:", response.text)
    except Exception as e:
        print(f"❌ Telegram send error: {e}")

def format_alert(item):
    return f"""
🚀 *Flip Opportunity* 🚀

*{item['title']}*
Buy: ${item['buy_price']} | Resale: ${item['avg_resale']}
Profit: ${item['estimated_profit']} | ROI: {item['roi_percent']}%
📦 Volume: {item['volume']} sold

[View Listing]({item['url']})
""".strip()

def build_daily_summary(report_path: str = "flip_report.json", results_path: str = "results.json") -> str:
    analyzed = 0
    flips = []
    # Load report (from resale_estimator)
    try:
        with open(report_path, "r") as rf:
            report = json.load(rf)
            if isinstance(report, list):
                analyzed = len(report)
                flips = [r for r in report if r.get("flip")]
            else:
                report = []
    except Exception:
        report = []

    # Count skipped auctions from raw results
    skipped_auctions = 0
    try:
        with open(results_path, "r") as resf:
            results = json.load(resf)
            if isinstance(results, list):
                for it in results:
                    opts = set(it.get("buying_options", []))
                    if ("AUCTION" in opts) and ("FIXED_PRICE" not in opts):
                        skipped_auctions += 1
                    elif it.get("is_auction") and ("FIXED_PRICE" not in opts):
                        skipped_auctions += 1
    except Exception:
        pass

    # Build summary message
    lines = []
    lines.append("📊 *MarketGuard Daily Summary*")
    lines.append(f"Analyzed: {analyzed} | Skipped auctions: {skipped_auctions} | Flips: {len(flips)}")

    if flips:
        # Top 5 by estimated profit
        top = sorted(flips, key=lambda r: (r.get("estimated_profit") or r.get("profit_estimate") or 0), reverse=True)[:5]
        lines.append("")
        lines.append("*Top flips:*")
        for i, x in enumerate(top, 1):
            buy = x.get("buy_price")
            resale = x.get("avg_resale") or x.get("avg_resale_price")
            profit = x.get("estimated_profit") or x.get("profit_estimate")
            title = x.get("title", "(no title)")
            url = x.get("url") or x.get("buy_url") or ""
            try:
                buy_s = f"{float(buy):.2f}" if buy is not None else "-"
            except Exception:
                buy_s = str(buy)
            try:
                resale_s = f"{float(resale):.2f}" if resale is not None else "-"
            except Exception:
                resale_s = str(resale)
            try:
                profit_s = f"{float(profit):.2f}" if profit is not None else "-"
            except Exception:
                profit_s = str(profit)
            link = f" [Buy]({url})" if url else ""
            lines.append(f"{i}) ${buy_s} → ${resale_s} (profit ~${profit_s}) – {title}{link}")

    return "\n".join(lines)

def run_bot():
    with open("flip_report.json", "r") as f:
        items = json.load(f)

    for item in items:
        if item.get("flip"):
            msg = format_alert(item)
            send_telegram_message(msg)

if __name__ == "__main__":
    # Show Telegram env status
    show_token_info()
    # Show how many keywords will be scanned (if watchlist.json exists)
    try:
        with open("watchlist.json", "r") as wf:
            wl = json.load(wf)
            if isinstance(wl, list):
                count = len([s for s in wl if isinstance(s, str) and s.strip()])
                print(f"📄 Watchlist loaded: {count} keywords")
            else:
                print("ℹ️ watchlist.json is not a list. Falling back to defaults in ebay_scraper.py")
    except Exception:
        print("ℹ️ No valid watchlist.json found. Using defaults in ebay_scraper.py")

    use_api = bool(os.getenv("EBAY_CLIENT_ID") and os.getenv("EBAY_CLIENT_SECRET"))
    if use_api:
        try:
            proc = subprocess.run(["python3", "ebay_scraper.py"], capture_output=True, text=True, timeout=300)
            combined = f"{proc.stdout}\n{proc.stderr}".strip()
            if (proc.returncode != 0) or ("OAuth" in combined) or ("invalid_client" in combined) or ("Cannot proceed without eBay access token" in combined):
                print("ℹ️ eBay scan failed — skipping fresh scan and using existing results.json")
                if combined:
                    print(combined)
            else:
                if proc.stdout:
                    print(proc.stdout, end="")
                if proc.stderr:
                    print(proc.stderr, end="")
        except Exception as e:
            print(f"ℹ️ eBay scan error — skipping fresh scan and using existing results.json: {e}")
    else:
        print("ℹ️ EBAY keys not set — skipping eBay scan and using existing results.json")

    # Always run estimator (it will use category_results.json or results.json if present)
    os.system("python3 resale_estimator.py")

    try:
        summary_msg = build_daily_summary()
        print(summary_msg)
        send_telegram_message(summary_msg)
    except Exception as e:
        print(f"⚠️ Failed to build/send daily summary: {e}")

    if os.path.exists("flip_report.json"):
        with open("flip_report.json", "r") as f:
            items = json.load(f)

        profitable_items = [item for item in items if item.get("flip")]

        # 🔍 Summary by category
        category_summary = defaultdict(int)

        for item in profitable_items:
            category = item.get("category", "Unknown")
            category_summary[category] += 1

        if category_summary:
            summary_lines = ["🔥 *Top Flipping Categories Today:*"]
            for category, count in sorted(category_summary.items(), key=lambda x: x[1], reverse=True):
                summary_lines.append(f"• {category} — {count} flips")
            summary_message = "\n".join(summary_lines)
            print(summary_message)
            send_telegram_message(summary_message)
        else:
            print("ℹ️ No categories to summarize.")

        # 🌟 AI-Suggested Category of the Day
        seasonal_tags = {
            "Winter": ["Heaters", "Snow Gear", "Jackets"],
            "Spring": ["Garden Tools", "Home Improvement", "Cleaning Supplies"],
            "Summer": ["Air Conditioners", "Pool Equipment", "Outdoor Gear"],
            "Fall": ["Power Tools", "Backpacks", "Decorations"]
        }

        month = datetime.now().month
        if month in [12, 1, 2]:
            season = "Winter"
        elif month in [3, 4, 5]:
            season = "Spring"
        elif month in [6, 7, 8]:
            season = "Summer"
        else:
            season = "Fall"

        # Pick the top profitable category that matches season tags
        matched_categories = [cat for cat in category_summary if any(tag.lower() in cat.lower() for tag in seasonal_tags[season])]

        if matched_categories:
            suggested_category = matched_categories[0]
        else:
            suggested_category = max(category_summary, key=category_summary.get, default="Unknown")

        if suggested_category != "Unknown":
            suggestion_message = f"🧠 *AI-Suggested Category of the Day:* `{suggested_category}`\nBased on {season} trends + resale volume."
            print(suggestion_message)
            send_telegram_message(suggestion_message)
        else:
            print("🧠 No valid category suggestion available.")

        if profitable_items:
            print(f"✅ {len(profitable_items)} items found. Sending alerts...")
            for item in profitable_items:
                msg = format_alert(item)
                send_telegram_message(msg)
        else:
            print("⚠️ No profitable items found.")
            send_telegram_message("⚠️ No profitable items found today.")
    else:
        print("❌ flip_report.json not found.")
        send_telegram_message("❌ flip_report.json not found. MarketGuard was unable to run a report.")