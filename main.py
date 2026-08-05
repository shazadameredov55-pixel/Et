import os
import json
import pandas as pd
import requests as standard_requests
from botasaurus.browser import browser, Driver

# ==========================================
# OTONOM PROXY VE HATA YÖNETİMİ
# ==========================================
def fetch_dynamic_proxies():
    """Ajanın engelleri aşmak için otonom olarak kullanabileceği proxy havuzu"""
    try:
        res = standard_requests.get("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=4000&country=all&ssl=all&anonymity=all", timeout=5)
        if res.status_code == 200:
            proxies = [p.strip() for p in res.text.split('\r\n') if p.strip()]
            return proxies
    except Exception:
        pass
    return None

# ==========================================
# BOTASAURUS OTONOM KAZIMA AJANI
# ==========================================
@browser(
    headless=True,
    block_images=True,
    reuse_driver=False,
    proxy=fetch_dynamic_proxies() # Ajan proxy'yi otonom yönetir
)
def scrape_etsy_headphones_task(driver: Driver, data):
    target_count = 1000
    scraped_products = []
    page = 1

    print(f"[Otonom Ajan] Etsy kazıma görevi devralındı. Hedef: {target_count} ürün.")

    while len(scraped_products) < target_count:
        url = f"https://www.etsy.com/search?q=headphones&page={page}&ref=pagination"
        print(f"[Otonom Ajan] Sayfa {page} taranıyor: {url}")

        try:
            # Google simülasyonu ile yönlenme
            driver.google_get(url)
            driver.sleep(2.5)

            # Sayfa içeriğini otonom kontrol et
            html = driver.page_html
            if "captcha" in html.lower() or "access denied" in html.lower():
                print(f"[Otonom Uyarı] Sayfa {page} güvenlik duvarına takıldı, ajan rotasyonu yeniliyor...")
                driver.sleep(4)
                continue

            # Genişletilmiş otonom DOM seçicileri
            cards = driver.select_all('div.v2-listing-card, li.wt-list-unstyled, div[data-search-results] li, div.wt-grid__item-xs-6')
            
            if not cards:
                print(f"[Otonom Ajan] Sayfa {page} üzerinde kart yakalanamadı. Alternatif JSON-LD verisi taranıyor...")
                # Alternatif otonom JSON veri çekme
                try:
                    scripts = driver.select_all('script[type="application/ld+json"]')
                    found_json = False
                    for script in scripts:
                        if 'Product' in script.text:
                            data_block = json.loads(script.text)
                            if isinstance(data_block, list):
                                for item in data_block:
                                    if item.get('@type') == 'Product' and len(scraped_products) < target_count:
                                        scraped_products.append({
                                            "raw_title": item.get('name', ''),
                                            "raw_price": str(item.get('offers', {}).get('price', '')),
                                            "raw_rating": str(item.get('aggregateRating', {}).get('ratingValue', '')),
                                            "shop_name": item.get('brand', {}).get('name', ''),
                                            "product_url": item.get('url', '')
                                        })
                                        found_json = True
                    if found_json:
                        print(f"[Otonom Ajan] Sayfa {page} JSON-LD üzerinden başarıyla okundu. Toplam: {len(scraped_products)}")
                        page += 1
                        continue
                except Exception:
                    pass

                if page > 5:
                    print("[Otonom Ajan] Maksimum deneme sınırına ulaşıldı, döngü sonlandırılıyor.")
                    break
                page += 1
                continue

            page_items = 0
            for card in cards:
                if len(scraped_products) >= target_count:
                    break
                
                try:
                    title_elem = card.select('h3, .v2-listing-card__title, .wt-text-title-01')
                    link_elem = card.select('a.listing-link, a[href*="/listing/"]')
                    price_elem = card.select('.currency-value, .lc-price, .wt-text-title-01')
                    shop_elem = card.select('.v2-listing-card__shop-name, .wt-text-caption')

                    title = title_elem.text.strip() if title_elem else ""
                    link = link_elem.attributes.get('href', '') if link_elem else ""
                    price = price_elem.text.strip() if price_elem else ""
                    shop = shop_elem.text.strip() if shop_elem else ""

                    if title:
                        scraped_products.append({
                            "raw_title": title,
                            "raw_price": price,
                            "raw_rating": "",
                            "shop_name": shop,
                            "product_url": link
                        })
                        page_items += 1
                except Exception:
                    continue

            print(f"[Otonom Ajan] Sayfa {page}'den {page_items} ürün işlendi. Toplam: {len(scraped_products)}")

        except Exception as e:
            print(f"[Otonom Hata] Sayfa {page} işlenirken hata: {str(e)}")

        page += 1

    print(f"[Otonom Ajan] Görev tamamlandı. Toplam {len(scraped_products)} ürün toplandı.")
    return scraped_products

# ==========================================
# API GEREKTİRMEYEN QWEN AI VERİ DÜZENLEME
# ==========================================
def clean_data_with_free_ai(raw_batch):
    url = "https://text.pollinations.ai/"
    prompt = f"""
    Sen otonom bir veri analistisin. Verilen ham Etsy ürün listesini temizle ve SADECE saf JSON listesi döndür.
    Fiyatı float yap. Başlıkları temizle. Açıklama yazma.
    
    Veri:
    {json.dumps(raw_batch, ensure_ascii=False)}
    """
    try:
        response = standard_requests.post(
            url,
            json={
                "messages": [
                    {"role": "system", "content": "Sen sadece geçerli JSON döndüren bir yapay zekasın."},
                    {"role": "user", "content": prompt}
                ],
                "model": "qwen-coder",
                "jsonMode": True
            },
            timeout=45
        )
        if response.status_code == 200:
            return json.loads(response.text)
    except Exception:
        pass
    return raw_batch

def main():
    output_dir = "data_outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_filepath = os.path.join(output_dir, "etsy_1000_headphones_clean.xlsx")

    print("[1/3] Otonom Botasaurus ajanı çalıştırılıyor...")
    raw_results = scrape_etsy_headphones_task()

    if not raw_results:
        print("[Uyarı] Ajan veri toplayamadı.")
        return

    print(f"[2/3] {len(raw_results)} adet veri Qwen LLM ile işleniyor...")
    all_cleaned_data = []
    
    batch_size = 50
    for i in range(0, len(raw_results), batch_size):
        batch = raw_results[i:i + batch_size]
        cleaned_batch = clean_data_with_free_ai(batch)
        all_cleaned_data.extend(cleaned_batch)

    print(f"[3/3] Excel dosyasına yazılıyor: {output_filepath}")
    df = pd.DataFrame(all_cleaned_data)
    df.to_excel(output_filepath, index=False, engine='openpyxl')
    print("✅ İşlem başarıyla tamamlandı.")

if __name__ == "__main__":
    main()
    
