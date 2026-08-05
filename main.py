import os
import json
import time
import requests
import pandas as pd
from botasaurus.browser import browser, Driver

# ==========================================
# 1. BOTASAURUS KAZIMA MOTORU (Anti-Bot Güçlendirilmiş)
# ==========================================
@browser(
    headless=True,
    block_images=True,
    reuse_driver=True,
    wait=4,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
def scrape_etsy_headphones(driver: Driver, data):
    target_count = data.get("target_count", 1000)
    base_url = "https://www.etsy.com/search?q=headphones&ref=pagination&page="
    
    scraped_products = []
    page = 1
    
    print(f"[Botasaurus] Otonom kazıma başlatıldı. Hedef: {target_count} ürün.")
    
    while len(scraped_products) < target_count:
        url = f"{base_url}{page}"
        print(f"[Botasaurus] Sayfa taranıyor: {page} -> {url}")
        
        driver.google_get(url)
        time.sleep(3)
        
        # Etsy listeleme kartları için alternatif selector yapıları
        items = driver.select_all('div.v2-listing-card')
        if not items:
            items = driver.select_all('li.wt-list-unstyled')
        if not items:
            items = driver.select_all('div[data-search-results] div.listing-link')
        if not items:
            items = driver.select_all('ol.responsive-listing-grid > li')
            
        if not items:
            print(f"[Botasaurus] Sayfa {page}'de ürün bulunamadı veya son sayfaya ulaşıldı.")
            if page > 1:
                break
            page += 1
            continue
            
        print(f"[Botasaurus] Sayfa {page}'de {len(items)} adet kart bulundu.")
        
        for item in items:
            if len(scraped_products) >= target_count:
                break
                
            try:
                title_elem = item.select('.v2-listing-card__title, h3, .wt-text-title-01')
                price_elem = item.select('.currency-value, .lc-price, .wt-text-title-01')
                rating_elem = item.select('.wt-align-items-center span.wt-text-title-small, .wt-rating span')
                reviews_elem = item.select('.wt-text-body-01, .wt-text-caption')
                link_elem = item.select('a.listing-link, a[href*="/listing/"]')
                shop_elem = item.select('.v2-listing-card__shop-name, .wt-text-caption')

                title = title_elem.text.strip() if title_elem else ""
                price = price_elem.text.strip() if price_elem else ""
                rating = rating_elem.text.strip() if rating_elem else ""
                reviews = reviews_elem.text.strip() if reviews_elem else ""
                
                link = ""
                if link_elem:
                    link = link_elem.attributes.get('href', '')
                elif item.name == 'a':
                    link = item.attributes.get('href', '')

                shop = shop_elem.text.strip() if shop_elem else ""

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
# 2. ÜCRETSİZ & FİLTRESİZ YAPAY ZEKA TEMİZLEME MOTORU
# ==========================================
def clean_data_with_free_ai(raw_batch):
    url = "https://text.pollinations.ai/"
    
    prompt = f"""
    Sen uzman bir veri analisti yapay zekasın. Sana verilen ham web kazıma verilerini analiz et ve saf (clean) JSON formatında döndür.
    
    Kurallar:
    - Fiyatı sadece sayısal (float) yap.
    - Puanı sayısal (float) yap.
    - Yorum sayısını tam sayı (int) yap.
    - Ürün başlığını gereksiz boşluklardan temizle.
    - SADECE geçerli bir JSON listesi döndür, başka hiçbir açıklama yazma.
    
    Ham Veri:
    {json.dumps(raw_batch, ensure_ascii=False)}
    """
    
    try:
        response = requests.post(
            url,
            json={
                "messages": [
                    {"role": "system", "content": "Sen sadece saf JSON yanıtı veren bir veri düzenleme yapay zekasısın."},
                    {"role": "user", "content": prompt}
                ],
                "model": "qwen-coder",
                "jsonMode": True
            },
            timeout=60
        )
        
        if response.status_code == 200:
            cleaned_json = json.loads(response.text)
            return cleaned_json
        else:
            return raw_batch
    except Exception:
        return raw_batch


# ==========================================
# 3. ANA ÇALIŞTIRICI
# ==========================================
def main():
    output_dir = "data_outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_filepath = os.path.join(output_dir, "etsy_1000_headphones_clean.xlsx")

    print("[1/3] Botasaurus ile 1000 kulaklık kazınıyor...")
    raw_results = scrape_etsy_headphones(data={"target_count": 1000})
    
    if not raw_results:
        print("[Uyarı] Kazılan ham veri bulunamadı.")
        return

    print("[2/3] Yapay Zeka (Qwen LLM) ham verileri analiz edip temizliyor...")
    all_cleaned_data = []
    
    batch_size = 50
    for i in range(0, len(raw_results), batch_size):
        batch = raw_results[i:i + batch_size]
        print(f"[AI Analiz] {i+1} ile {i+len(batch)} arasındaki ürünler Yapay Zekaya işletiliyor...")
        cleaned_batch = clean_data_with_free_ai(batch)
        all_cleaned_data.extend(cleaned_batch)
    
    print(f"[3/3] Temizlenen veriler Excel dosyasına yazılıyor: {output_filepath}")
    df = pd.DataFrame(all_cleaned_data)
    df.to_excel(output_filepath, index=False, engine='openpyxl')
    
    print(f"✅ [BAŞARILI] İşlem tamamlandı ve dosya kaydedildi: {output_filepath}")

if __name__ == "__main__":
    main()
    
