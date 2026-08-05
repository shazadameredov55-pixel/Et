import os
import json
import pandas as pd
import requests as standard_requests
from botasaurus.browser import browser, Driver

# ==========================================
# 1. BOTASAURUS ILE ETSI KAZIMA MOTORU
# ==========================================
# Headless modu GitHub Actions'ta varsayılan olarak çalışır.
# Botasaurus Cloudflare'i ve anti-bot sistemlerini kendi stealth Chrome katmanıyla aşar.
@browser(
    headless=True,
    block_images=True,  # Hız kazanmak için görselleri engeller
    reuse_driver=True   # Sürücüyü yeniden kullanarak tarayıcı başlatma yükünü azaltır
)
def scrape_etsy_headphones_task(driver: Driver, data):
    target_count = 1000
    scraped_products = []
    page = 1

    print(f"[Botasaurus Agent] Otonom kazıma başlatıldı. Hedef: {target_count} ürün.")

    while len(scraped_products) < target_count:
        url = f"https://www.etsy.com/search?q=headphones&page={page}&ref=pagination"
        print(f"[Botasaurus] Sayfa {page} taranıyor -> {url}")

        try:
            # Google Referer taklidi ile Cloudflare/Akamai engelini aşma
            driver.google_get(url)
            driver.sleep(2) # İnsan davranış taklidi beklemesi

            # Sayfadaki kart elemanlarını seç
            cards = driver.select_all('div.v2-listing-card, li.wt-list-unstyled, div[data-search-results] li')
            
            if not cards:
                print(f"[Botasaurus] Sayfa {page}'de kart bulunamadı. Bloklanmış veya son sayfada olabilir.")
                if page > 3:
                    break
            
            page_items = 0
            for card in cards:
                if len(scraped_products) >= target_count:
                    break
                
                try:
                    title_elem = card.select('h3, .v2-listing-card__title, .wt-text-title-01')
                    link_elem = card.select('a.listing-link, a[href*="/listing/"]')
                    price_elem = card.select('.currency-value, .lc-price, .wt-text-title-01')
                    rating_elem = card.select('.wt-align-items-center span.wt-text-title-small, .wt-rating span')
                    shop_elem = card.select('.v2-listing-card__shop-name, .wt-text-caption')

                    title = title_elem.text.strip() if title_elem else ""
                    link = link_elem.attributes.get('href', '') if link_elem else ""
                    price = price_elem.text.strip() if price_elem else ""
                    rating = rating_elem.text.strip() if rating_elem else ""
                    shop = shop_elem.text.strip() if shop_elem else ""

                    if title:
                        scraped_products.append({
                            "raw_title": title,
                            "raw_price": price,
                            "raw_rating": rating,
                            "shop_name": shop,
                            "product_url": link
                        })
                        page_items += 1
                except Exception:
                    continue

            print(f"[Botasaurus] Sayfa {page}'den {page_items} ürün alındı. Toplam: {len(scraped_products)}")

        except Exception as e:
            print(f"[Botasaurus Hata] Sayfa {page} işlenirken hata oluştu: {str(e)}")
            if page > 5:
                break

        page += 1

    print(f"[Botasaurus] Toplam {len(scraped_products)} adet ham ürün verisi çekildi.")
    return scraped_products

# ==========================================
# 2. API GEREKTİRMEYEN ÜCRETSİZ AI KOD & VERİ İŞLEYİCİ
# ==========================================
def clean_data_with_free_ai(raw_batch):
    """API anahtarı gerektirmeyen Pollinations Qwen LLM Entegrasyonu"""
    url = "https://text.pollinations.ai/"
    
    prompt = f"""
    Sen uzman bir veri analisti ve kod yazıcı ajanısın. Sana verilen ham Etsy ürün verisini temizle ve SADECE geçerli bir JSON listesi olarak döndür.
    
    Kurallar:
    - Fiyat bilgisini sayısal (float) formata çevir.
    - Puan (rating) değerini float yap.
    - Başlıktaki gereksiz karakterleri ve fazla boşlukları temizle.
    - Yanıtında markdown bloğu veya açıklama yazma, SADECE saf JSON array döndür.
    
    Veri:
    {json.dumps(raw_batch, ensure_ascii=False)}
    """
    
    try:
        response = standard_requests.post(
            url,
            json={
                "messages": [
                    {"role": "system", "content": "Sen sadece geçerli JSON döndüren otonom bir veri işleme yapay zekasısın."},
                    {"role": "user", "content": prompt}
                ],
                "model": "qwen-coder",
                "jsonMode": True
            },
            timeout=60
        )
        if response.status_code == 200:
            return json.loads(response.text)
    except Exception as e:
        print(f"[AI Uyarısı] AI temizleme adımında hata: {str(e)}")
    
    return raw_batch

# ==========================================
# 3. OTONOM ÇALIŞTIRICI SÜREÇ
# ==========================================
def main():
    output_dir = "data_outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_filepath = os.path.join(output_dir, "etsy_1000_headphones_clean.xlsx")

    # 1. Botasaurus ile Çekme
    print("[1/3] Botasaurus ile 1000 kulaklık kazınıyor...")
    raw_results = scrape_etsy_headphones_task()

    if not raw_results:
        print("[Uyarı] Kazılan ham veri bulunamadı.")
        return

    # 2. Ücretsiz LLM ile Temizleme
    print(f"[2/3] Çekilen {len(raw_results)} adet veri API'siz Yapay Zeka (Qwen Coder) ile işleniyor...")
    all_cleaned_data = []
    
    batch_size = 50
    for i in range(0, len(raw_results), batch_size):
        batch = raw_results[i:i + batch_size]
        print(f"[AI İşlem] {i+1} ile {i+len(batch)} arasındaki ürünler temizleniyor...")
        cleaned_batch = clean_data_with_free_ai(batch)
        all_cleaned_data.extend(cleaned_batch)

    # 3. Excel Kaydı
    print(f"[3/3] Temizlenen veriler Excel dosyasına aktarılıyor: {output_filepath}")
    df = pd.DataFrame(all_cleaned_data)
    df.to_excel(output_filepath, index=False, engine='openpyxl')

    print(f"✅ [BAŞARILI] İşlem tamamlandı! Dosya depoya yazılmaya hazır: {output_filepath}")

if __name__ == "__main__":
    main()
    
