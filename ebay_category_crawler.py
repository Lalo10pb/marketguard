import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketGuardBot/1.0)"
}

def crawl_category(category_url, max_pages=3):
    results = []
    
    for page in range(1, max_pages + 1):
        join_char = '&' if '?' in category_url else '?'
        url = f"{category_url}{join_char}_pgn={page}"
        print(f"🔍 Crawling: {url}")
        
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, "html.parser")
        
        listings = soup.select("li.s-item")

        for item in listings:
            # Skip empty or placeholder listings
            if "data-view" not in item.attrs:
                continue

            title_tag = item.select_one("h3.s-item__title")
            price_tag = item.select_one("span.s-item__price")
            link_tag = item.select_one("a.s-item__link")

            if title_tag and price_tag and link_tag:
                title = title_tag.get_text(strip=True)
                price = price_tag.get_text(strip=True)
                url = link_tag["href"]

                if "Shop on eBay" in title or title == "New Listing":
                    continue  # skip ads or placeholders

                results.append({
                    "title": title,
                    "price": price,
                    "url": url,
                    "scanned_at": datetime.now().isoformat()
                })

    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("❌ Please provide a category URL as an argument.")
        sys.exit(1)

    category_url = sys.argv[1]
    items = crawl_category(category_url)

    with open("category_results.json", "w") as f:
        json.dump(items, f, indent=2)

    print(f"✅ Saved {len(items)} items to category_results.json")