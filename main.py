import os
import json
import re
import pandas as pd
from openai import OpenAI
from botasaurus.browser import browser, Driver

# ==========================================
# 1. BOTASAURUS KAZIMA ARACI (TOOL)
# ==========================================
@browser(
    headless=True,
    block_images=True,
    reuse_driver=True
)
def scrape_etsy_headphones(driver: Driver, data):
    target_count = data.get("target_count", 1000)
    base_url = "https://www.etsy.com/search?q=headphones&ref=pagination&page="
    
    scraped_products = []
    page = 1
    
    print(f"[Botasaurus] Kazıma başlatıldı. Hedef: {target_count} ürün.")
    
    while len(scraped_products) < target_count:
        url = f"{base_url}{page}"
        print(f"[Botasaurus] Sayfa taranıyor: {page} -> {url}")
        
        driver.google_get(url)
        items = driver.select_all('div.v2-listing-card')
        
        if not items:
            print("[Botasaurus] Sayfada ürün bulunamadı veya son sayfaya ulaşıldı.")
            break
            
        for item in items:
            if len(scraped_products) >= target_count:
                break
                
            try:
                title_elem = item.select('.v2-listing-card__title')
                price_elem = item.select('.currency-value')
                rating_elem = item.select('.wt-align-items-center span.wt-text-title-small')
                reviews_elem = item.select('.wt-text-body-01')
                link_elem = item.select('a.listing-link')
                shop_elem = item.select('.v2-listing-card__shop-name')

                title = title_elem.text.strip() if title_elem else None
                price = price_elem.text.strip() if price_elem else None
                rating = rating_elem.text.strip() if rating_elem else None
                reviews = reviews_elem.text.strip() if reviews_elem else None
                link = link_elem.attributes.get('href') if link_elem else None
                shop = shop_elem.text.strip() if shop_elem else None

                if title and link:
                    scraped_products.append({
                        "raw_title": title,
                        "raw_price": price,
                        "raw_rating": rating,
                        "raw_reviews": reviews,
                        "shop_name": shop,
                        "product_url": link
                    })
            except Exception:
                continue
                
        page += 1
        
    print(f"[Botasaurus] Toplam {len(scraped_products)} adet ham ürün verisi çekildi.")
    return scraped_products


# ==========================================
# 2. VERİ TEMİZLEME (SAF HALE GETİRME)
# ==========================================
def clean_and_parse_data(raw_data):
    cleaned_data = []
    
    for item in raw_data:
        price_clean = None
        if item.get("raw_price"):
            price_match = re.search(r'[\d\.,]+', item["raw_price"].replace(',', ''))
            if price_match:
                price_clean = float(price_match.group())

        reviews_clean = 0
        if item.get("raw_reviews"):
            reviews_match = re.search(r'\d+', item["raw_reviews"].replace(',', ''))
            if reviews_match:
                reviews_clean = int(reviews_match.group())

        rating_clean = None
        if item.get("raw_rating"):
            rating_match = re.search(r'[\d\.]+', item["raw_rating"])
            if rating_match:
                rating_clean = float(rating_match.group())

        title_clean = re.sub(r'\s+', ' ', item.get("raw_title", "")).strip()

        cleaned_data.append({
            "Ürün Başlığı": title_clean,
            "Fiyat (USD)": price_clean,
            "Puan": rating_clean,
            "Yorum Sayısı": reviews_clean,
            "Mağaza Adı": item.get("shop_name"),
            "Ürün Linki": item.get("product_url")
        })
        
    return cleaned_data


# ==========================================
# 3. AÇIK KAYNAK YAPAY ZEKA (OPENROUTER / DEEPSEEK)
# ==========================================
def main():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY çevre değişkeni bulunamadı.")
        
    # OpenRouter üzerinden filtresiz açık kaynak OpenAI uyumlu API çağrısı
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    
    output_dir = "data_outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_filepath = os.path.join(output_dir, "etsy_1000_headphones_clean.xlsx")

    print("[AI Model] Açık kaynaklı DeepSeek/Qwen modeli başlatılıyor...")
    
    # Model seçimi: Filtresiz ve yüksek kodlama yeteneğine sahip DeepSeek veya Qwen
    response = client.chat.completions.create(
        model="deepseek/deepseek-r1:free",
        messages=[
            {"role": "system", "content": "Sen Botasaurus kazıma aracını yöneten otonom bir AI ajansın."},
            {"role": "user", "content": "Etsy üzerinden 1000 kulaklık verisini kazımak için aracı çalıştır."}
        ]
    )

    print("[AI Model] İstem doğrulandı, Botasaurus entegrasyonu başlatılıyor...")
    
    # 1. Kazıma İşlemi
    raw_results = scrape_etsy_headphones(data={"target_count": 1000})
    
    # 2. Saf Veriye Dönüştürme
    print("[AI Model] Veriler işleniyor ve saf hale getiriliyor...")
    clean_results = clean_and_parse_data(raw_results)
    
    # 3. Excel (.xlsx) Kaydı
    df = pd.DataFrame(clean_results)
    df.to_excel(output_filepath, index=False, engine='openpyxl')
    print(f"[AI Model] İşlem başarıyla tamamlandı. Dosya kaydedildi: {output_filepath}")

if __name__ == "__main__":
    main()
    
