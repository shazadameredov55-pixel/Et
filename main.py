# ============================================================
# GEREKLİ KÜTÜPHANELER (GitHub Actions workflow içinde çalıştırın):
# pip install selenium pandas openpyxl requests
# ============================================================

import time
import random
import re
import os
import logging
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException,
)

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
SEARCH_KEYWORDS = ["digital planner", "canva template"]
PAGES_PER_KEYWORD = 5          # Her anahtar kelime için kaç sayfa taranacak
BASE_URL = "https://www.etsy.com/search"
REQUEST_DELAY_MIN = 3
REQUEST_DELAY_MAX = 6
PAGE_LOAD_TIMEOUT = 25
OUTPUT_XLSX = "etsy_digital_products.xlsx"
OUTPUT_CSV = "etsy_digital_products.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def build_driver() -> webdriver.Chrome:
    """GitHub Actions (Ubuntu-latest) üzerinde headless Chrome örneği oluşturur."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--lang=en-US,en;q=0.9")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        driver = webdriver.Chrome(options=options)
    except WebDriverException as e:
        logger.error(f"Chrome driver başlatılamadı: {e}")
        raise

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """
            },
        )
    except Exception:
        pass

    return driver


def safe_get_text(element, css_selector, default=""):
    """Bir alt elementten güvenli şekilde metin çeker, bulunamazsa default döner."""
    try:
        found = element.find_element(By.CSS_SELECTOR, css_selector)
        return found.text.strip()
    except (NoSuchElementException, StaleElementReferenceException):
        return default


def safe_get_attr(element, css_selector, attr, default=""):
    """Bir alt elementten güvenli şekilde attribute çeker."""
    try:
        found = element.find_element(By.CSS_SELECTOR, css_selector)
        value = found.get_attribute(attr)
        return value.strip() if value else default
    except (NoSuchElementException, StaleElementReferenceException):
        return default


def parse_review_count(raw_text: str) -> str:
    """'(1,234)' gibi metinlerden sadece sayıyı çıkarır."""
    if not raw_text:
        return ""
    match = re.search(r"[\d.,]+", raw_text)
    if match:
        return match.group(0).replace(",", "").replace(".", "")
    return ""


def extract_listing_cards(driver):
    """
    Arama sonuçları sayfasındaki ürün kartlarını bulur.
    Etsy sık sık HTML/CSS yapısını değiştirdiği için birden fazla
    selector denenir (fallback mekanizması).
    """
    candidate_selectors = [
        "div.v2-listing-card",
        "li.wt-list-unstyled div.v2-listing-card",
        "div[data-listing-id]",
        "li[data-listing-id]",
    ]

    for selector in candidate_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                logger.info(f"'{selector}' selector ile {len(elements)} ürün kartı bulundu.")
                return elements
        except Exception:
            continue

    logger.warning("Hiçbir ürün kartı selector'ı sonuç vermedi.")
    return []


def scrape_search_page(driver, keyword: str, page: int) -> list:
    """Belirli bir arama kelimesi ve sayfa numarası için ürünleri çeker."""
    results = []
    url = f"{BASE_URL}?q={keyword.replace(' ', '+')}&page={page}"

    try:
        logger.info(f"Sayfa yükleniyor: {url}")
        driver.get(url)
    except TimeoutException:
        logger.error(f"Sayfa zaman aşımına uğradı: {url}")
        return results
    except WebDriverException as e:
        logger.error(f"Sayfa yüklenirken hata oluştu: {url} -> {e}")
        return results

    try:
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # Ürün sonuçları ya da bir listing kartı görünene kadar bekle
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            lambda d: len(extract_listing_cards(d)) > 0
            or "no results" in d.page_source.lower()
        )
    except TimeoutException:
        logger.warning(f"'{keyword}' - sayfa {page}: Ürün elementleri zamanında yüklenmedi.")
        return results

    time.sleep(random.uniform(1.5, 3.0))  # dinamik içerik için ek bekleme

    cards = extract_listing_cards(driver)
    if not cards:
        logger.warning(f"'{keyword}' - sayfa {page}: Ürün kartı bulunamadı.")
        return results

    for card in cards:
        try:
            title = safe_get_text(card, "h3") or safe_get_attr(card, "a", "title")
            price = safe_get_text(card, "span.currency-value")
            if not price:
                price = safe_get_text(card, "p.wt-text-title-01")

            shop_name = safe_get_text(card, "p.wt-text-caption")
            if not shop_name:
                shop_name = safe_get_text(card, "span.wt-text-caption")

            review_raw = safe_get_text(card, "span.wt-text-caption span")
            review_count = parse_review_count(review_raw)

            product_url = safe_get_attr(card, "a", "href")
            if product_url and product_url.startswith("//"):
                product_url = "https:" + product_url
            elif product_url and product_url.startswith("/"):
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
        except StaleElementReferenceException:
            logger.warning("Stale element - kart atlandı.")
            continue
        except Exception as e:
            logger.warning(f"Ürün ayrıştırılırken beklenmeyen hata: {e}")
            continue

    logger.info(f"'{keyword}' - sayfa {page}: {len(results)} ürün çekildi.")
    return results


def scrape_all(keywords, pages_per_keyword) -> list:
    """Tüm anahtar kelimeler ve sayfalar için scraping döngüsünü yürütür."""
    driver = None
    all_results = []

    try:
        driver = build_driver()

        for keyword in keywords:
            logger.info(f"===== '{keyword}' aramasına başlanıyor =====")
            for page in range(1, pages_per_keyword + 1):
                try:
                    page_results = scrape_search_page(driver, keyword, page)
                    all_results.extend(page_results)
                except Exception as e:
                    logger.error(f"'{keyword}' sayfa {page} işlenirken hata: {e}")
                finally:
                    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                    logger.info(f"{delay:.1f} saniye bekleniyor...")
                    time.sleep(delay)

    except Exception as e:
        logger.error(f"Genel scraping hatası: {e}")

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    return all_results


def save_results(data: list):
    """Toplanan verileri xlsx ve csv olarak kaydeder."""
    if not data:
        logger.warning("Kaydedilecek veri bulunamadı. Boş dosyalar oluşturulmayacak.")
        return

    try:
        df = pd.DataFrame(data)
        df.drop_duplicates(subset=["Product URL"], keep="first", inplace=True)

        try:
            df.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")
            logger.info(f"Excel dosyası kaydedildi: {OUTPUT_XLSX}")
        except Exception as e:
            logger.error(f"Excel dosyası kaydedilirken hata: {e}")

        try:
            df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            logger.info(f"CSV dosyası kaydedildi: {OUTPUT_CSV}")
        except Exception as e:
            logger.error(f"CSV dosyası kaydedilirken hata: {e}")

        logger.info(f"Toplam {len(df)} benzersiz ürün kaydedildi.")

    except Exception as e:
        logger.error(f"DataFrame oluşturulurken/kaydedilirken hata: {e}")


def main():
    logger.info("Etsy scraping işlemi başlıyor...")
    results = scrape_all(SEARCH_KEYWORDS, PAGES_PER_KEYWORD)
    save_results(results)
    logger.info("İşlem tamamlandı.")


if __name__ == "__main__":
    main()
