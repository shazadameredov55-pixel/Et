import os
import json
import time
import requests
import pandas as pd

# ==========================================
# 1. ETSY ARAMA MOTORU (Direct JSON Endpoint Scraper)
# ==========================================
def scrape_etsy_headphones_api(target_count=1000):
    scraped_products = []
    page = 1
    
    # Gerçek bir tarayıcı başlığı taklidi
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.etsy.com/search?q=headphones"
    }
    
    print(f"[Etsy Scraper] API tabanlı kazıma başlatıldı. Hedef: {target_count} ürün.")
    
    while len(scraped_products) < target_count:
        # Etsy'nin iç JSON Arama Endpoint'i
        url = f"https://www.etsy.com/api/v3/ajax/bespoke/member/nebula/search?query=headphones&page={page}&ref=pagination"
        
        print(f"[Etsy Scraper] Sayfa {page} çekiliyor -> {url}")
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            
            # Eğer API direkt yanıt vermezse HTML arama yedek isteğine düş
            if response.status_code != 200:
                print(f"[Uyarı] HTTP {response.status_code} alındı. HTML Arama isteği deneniyor...")
                alt_url = f"https://www.etsy.com/search?q=headphones&page={page}"
                response = requests.get(alt_url, headers=headers, timeout=15)
                
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Etsy JSON yapısından ürün listesini ayıkla
                    listings = data.get('results', {}).get('listings', [])
                    
                    if not listings:
                        print(f"[Etsy Scraper] Sayfa {page}'de ürün bulunamadı. Son sayfaya ulaşılmış olabilir.")
                        if page > 2:
                            break
                    else:
                        print(f"[Etsy Scraper] Sayfa {page}'den {len(listings)} ürün başarıyla çekildi.")
                        
                    for item in listings:
                        if len(scraped_products) >= target_count:
                            break
                        
                        title = item.get('title', '')
                        price = item.get('price', {}).get('amount', '') or item.get('price_string', '')
                        rating = item.get('rating', {}).get('rating', '')
                        reviews = item.get('rating', {}).get('count', '')
                        url = item.get('url', '')
                        shop = item.get('shop_name', '')
                        
                        if title:
                            scraped_products.append({
                                "raw_title": title,
                                "raw_price": price,
                                "raw_rating": rating,
                                "raw_reviews": reviews,
                                "shop_name": shop,
                                "product_url": url
                            })
                except json.JSONDecodeError:
                    print(f"[Hata] Sayfa {page} JSON olarak ayrıştırılamadı (Cloudflare JS Engeli).")
                    if page > 3:
                        break
            else:
                print(f"[Hata] Etsy erişim engeli döndürdü: Status Code {response.status_code}")
                break
                
        except Exception as e:
            print(f"[Sistem Hatası] İstek sırasında bir sorun oluştu: {str(e)}")
            break
            
        page += 1
        time.sleep(2)  # Sunucuyu yormamak için kısa bekleme
        
    print(f"[Etsy Scraper] Toplam {len(scraped_products)} adet ham ürün verisi çekildi.")
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
            return json.loads(response.text)
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

    print("[1/3] Etsy API üzerinden 1000 kulaklık verisi çekiliyor...")
    raw_results = scrape_etsy_headphones_api(target_count=1000)
    
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
    
