# ============================================================
# GEREKLİ KÜTÜPHANELER:
# pip install requests beautifulsoup4 pandas openpyxl
# ============================================================

import time
import random
import re
import logging
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------
# LOGLAMA
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("etsy_scraper")

# ------------------------------------------------------------
# AYARLAR
# ------------------------------------------------------------
SCRAPER_API_KEY = "319f682bebc62e5843428a13a10c8137"

SEARCH_KEYWORDS = ["digital planner", "canva template"]
PAGES_PER_KEYWORD = 3  # Kota tasarrufu için her kelimeden 3 sayfa
OUTPUT_XLSX = "etsy_digital_products.xlsx"
OUTPUT_CSV = "etsy_digital_products.csv"


def parse_review_count(raw_text: str) -> str:
    if not raw_text:
        return ""
    match = re.search(r"[\d.,]+", raw_text)
    if match:
        return match.group(0).replace(",", "").replace(".", "")
    return ""


def get_scraperapi_url(target_url: str) -> str:
    """İsteği ScraperAPI üzerinden konut IP'si ile yönlendirir."""
    return f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true"


def scrape_search_page(session, keyword: str, page: int) -> list:
    results = []
    target_url = f"https://www.etsy.com/search?q={keyword.replace(' ', '+')}&page={page}"
    api_url = get_scraperapi_url(target_url)

    try:
        logger.info(f"ScraperAPI üzerinden sayfa çekiliyor: {keyword} - Sayfa {page}")
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

    logger.info(f"'{keyword}' - sayfa {page}: {len(cards)} ürün kartı bulundu.")

    for card in cards:
        try:
            title_elem = card.select_one("h3, h2, p.wt-text-title-01")
            title = title_elem.get_text(strip=True) if title_elem else card.get("title", "")

            price_elem = card.select_one("span.currency-value, p.wt-text-title-01, span.wt-text-title-01")
            price = price_elem.get_text(strip=True) if price_elem else ""

            shop_elem = card.select_one("p.wt-text-caption, span.wt-text-caption, p.wt-text-body-01")
            shop_name = shop_elem.get_text(strip=True) if shop_elem else ""

            review_elem = card.select_one("span.wt-text-caption span, span.wt-badge")
            review_raw = review_elem.get_text(strip=True) if review_elem else ""
            review_count = parse_review_count(review_raw)

            if card.name == "a":
                product_url = card.get("href", "")
            else:
                link_elem = card.select_one("a.listing-link, a")
                product_url = link_elem.get("href", "") if link_elem else ""

            if product_url.startswith("//"):
                product_url = "https:" + product_url
            elif product_url.startswith("/"):
                product_url = "https://www.etsy.com" + product_url

            if not title and not product_url:
                continue

            results.append(
                {
                    "Keyword": keyword,
                    "Page": page,
                    "Product Title": title,
                    "Price": price,
                    "Shop Name": shop_name,
                    "Review Count": review_count,
                    "Product URL": product_url,
                    "Scraped At": datetime.utcnow().isoformat(),
                }
            )
        except Exception:
            continue

    return results


def scrape_all(keywords, pages_per_keyword) -> list:
    all_results = []
    session = requests.Session()

    for keyword in keywords:
        logger.info(f"===== '{keyword}' aramasına başlanıyor =====")
        for page in range(1, pages_per_keyword + 1):
            try:
                page_results = scrape_search_page(session, keyword, page)
                all_results.extend(page_results)
            except Exception as e:
                logger.error(f"'{keyword}' sayfa {page} işlenirken hata: {e}")

    return all_results


def save_results(data: list):
    if not data:
        logger.warning("Kaydedilecek veri bulunamadı.")
        return

    try:
        df = pd.DataFrame(data)
        df.drop_duplicates(subset=["Product URL"], keep="first", inplace=True)

        try:
            df.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")
            logger.info(f"Excel dosyası kaydedildi: {OUTPUT_XLSX}")
        except Exception as e:
            logger.error(f"Excel hatası: {e}")

        try:
            df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            logger.info(f"CSV dosyası kaydedildi: {OUTPUT_CSV}")
        except Exception as e:
            logger.error(f"CSV hatası: {e}")

        logger.info(f"Toplam {len(df)} benzersiz ürün kaydedildi.")

    except Exception as e:
        logger.error(f"Kaydetme hatası: {e}")


def main():
    logger.info("Etsy scraping işlemi (ScraperAPI) başlıyor...")
    results = scrape_all(SEARCH_KEYWORDS, PAGES_PER_KEYWORD)
    save_results(results)
    logger.info("İşlem tamamlandı.")


if __name__ == "__main__":
    main()
    
