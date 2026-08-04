# ============================================================
# ZENROWS ETSY SCRAPER
# ============================================================

import logging
import re
from datetime import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("etsy_scraper")

ZENROWS_API_KEY = "5212e3289eb56186aabd91031d908efdb093262b"
SEARCH_KEYWORDS = ["digital planner", "canva template"]
PAGES_PER_KEYWORD = 3
OUTPUT_XLSX = "etsy_digital_products.xlsx"
OUTPUT_CSV = "etsy_digital_products.csv"

def parse_review_count(raw_text: str) -> str:
    if not raw_text:
        return ""
    match = re.search(r"[\d.,]+", raw_text)
    return match.group(0).replace(",", "").replace(".", "") if match else ""

def scrape_search_page(session, keyword: str, page: int) -> list:
    results = []
    target_url = f"https://www.etsy.com/search?q={keyword.replace(' ', '+')}&page={page}"
    
    # ZenRows API endpoint (js_render ve antibot aktif)
    api_url = f"https://api.zenrows.com/v1/?apikey={ZENROWS_API_KEY}&url={target_url}&js_render=true&antibot=true"

    try:
        logger.info(f"ZenRows üzerinden çekiliyor: {keyword} - Sayfa {page}")
        response = session.get(api_url, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"HTTP Hata Kodu: {response.status_code} -> {target_url}")
            return results

    except Exception as e:
        logger.error(f"Bağlantı hatası: {target_url} -> {e}")
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("div.v2-listing-card, div[data-listing-id], li[data-listing-id], a.listing-link")
    
    if not cards:
        logger.warning(f"'{keyword}' - sayfa {page}: Ürün kartı bulunamadı.")
        return results

    logger.info(f"'{keyword}' - sayfa {page}: {len(cards)} ürün bulundu.")

    for card in cards:
        try:
            title_elem = card.select_one("h3, h2, p.wt-text-title-01")
            title = title_elem.get_text(strip=True) if title_elem else card.get("title", "")

            price_elem = card.select_one("span.currency-value, p.wt-text-title-01, span.wt-text-title-01")
            price = price_elem.get_text(strip=True) if price_elem else ""

            shop_elem = card.select_one("p.wt-text-caption, span.wt-text-caption, p.wt-text-body-01")
            shop_name = shop_elem.get_text(strip=True) if shop_elem else ""

            review_elem = card.select_one("span.wt-text-caption span, span.wt-badge")
            review_count = parse_review_count(review_elem.get_text(strip=True) if review_elem else "")

            link_elem = card if card.name == "a" else card.select_one("a.listing-link, a")
            product_url = link_elem.get("href", "") if link_elem else ""

            if product_url.startswith("//"):
                product_url = "https:" + product_url
            elif product_url.startswith("/"):
                product_url = "https://www.etsy.com" + product_url

            if title or product_url:
                results.append({
                    "Keyword": keyword,
                    "Page": page,
                    "Product Title": title,
                    "Price": price,
                    "Shop Name": shop_name,
                    "Review Count": review_count,
                    "Product URL": product_url,
                    "Scraped At": datetime.utcnow().isoformat(),
                })
        except Exception:
            continue

    return results

def main():
    session = requests.Session()
    all_results = []
    for keyword in SEARCH_KEYWORDS:
        for page in range(1, PAGES_PER_KEYWORD + 1):
            all_results.extend(scrape_search_page(session, keyword, page))
            
    if all_results:
        df = pd.DataFrame(all_results)
        df.drop_duplicates(subset=["Product URL"], inplace=True)
        df.to_excel(OUTPUT_XLSX, index=False)
        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        logger.info(f"Tamamlandı. Toplam {len(df)} benzersiz ürün kaydedildi.")
    else:
        logger.warning("Veri çekilemedi.")

if __name__ == "__main__":
    main()
            
