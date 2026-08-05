import os
import json
import re
import pandas as pd
from anthropic import Anthropic
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
    """
    Etsy üzerinde 'headphones' aramasını yapıp belirtilen miktarda 
    ürünün verilerini kazır.
    """
    target_count = data.get("target_count", 1000)
    base_url = "https://www.etsy.com/search?q=headphones&ref=pagination&page="
    
    scraped_products = []
    page = 1
    
    print(f"[Tool] Kazıma başlatıldı. Hedef: {target_count} ürün.")
    
    while len(scraped_products) < target_count:
        url = f"{base_url}{page}"
        print(f"[Tool] Sayfa taranıyor: {page} -> {url}")
        
        driver.google_get(url)
        
        items = driver.select_all('div.v2-listing-card')
        if not items:
            print("[Tool] Daha fazla ürün bulunamadı veya sayfa yapısı değişti.")
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
            except Exception as e:
                continue
                
        page += 1
        
    print(f"[Tool] Toplam {len(scraped_products)} adet ham ürün verisi toplandı.")
    return scraped_products


# ==========================================
# 2. VERİ TEMİZLEME VE SAF HALE GETİRME
# ==========================================
def clean_and_parse_data(raw_data):
    """
    Ham verileri süzerek sayısal değerlere dönüştürür ve saf metin haline getirir.
    """
    cleaned_data = []
    
    for item in raw_data:
        # Fiyatı float yapma
        price_clean = None
        if item.get("raw_price"):
            price_match = re.search(r'[\d\.,]+', item["raw_price"].replace(',', ''))
            if price_match:
                price_clean = float(price_match.group())

        # Yorum sayısını int yapma
        reviews_clean = 0
        if item.get("raw_reviews"):
            reviews_match = re.search(r'\d+', item["raw_reviews"].replace(',', ''))
            if reviews_match:
                reviews_clean = int(reviews_match.group())

        # Derecelendirmeyi float yapma
        rating_clean = None
        if item.get("raw_rating"):
            rating_match = re.search(r'[\d\.]+', item["raw_rating"])
            if rating_match:
                rating_clean = float(rating_match.group())

        # Başlığı temizleme
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
# 3. CLAUDE 3.5 SONNET YAPAY ZEKA AJANI
# ==========================================
TOOLS_SPEC = [
    {
        "name": "run_etsy_scraper",
        "description": "Etsy üzerinden belirtilen miktarda kulaklık ürün verisini kazımak için Botasaurus aracını çalıştırır.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_count": {
                    "type": "integer",
                    "description": "Kazınacak toplam ürün sayısı (Örn: 1000)"
                }
            },
            "required": ["target_count"]
        }
    }
]

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY çevre değişkeni bulunamadı.")
        
    client = Anthropic(api_key=api_key)
    
    # Çıktı klasörünü oluşturma (Depo altında ayrı bir klasör)
    output_dir = "data_outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_filepath = os.path.join(output_dir, "etsy_1000_headphones_clean.xlsx")

    prompt = """
    GÖREVİNİZ:
    1. Etsy üzerinden genel olarak kazınabilir tüm kulaklık (headphones) verilerini topla.
    2. 'run_etsy_scraper' aracını çağırarak 1000 adet ürün hedefle.
    3. Elde edilen ham verileri temizle, sayısal değerleri dönüştür.
    4. Temizlenmiş veriyi Excel (.xlsx) formatında kaydet.
    """

    print("[AI Agent] Yapay zeka başlatıldı ve görev analiz ediliyor...")
    
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2000,
        tools=TOOLS_SPEC,
        messages=[{"role": "user", "content": prompt}]
    )

    tool_calls = [c for c in response.content if c.type == "tool_use"]
    
    if tool_calls:
        for tool_call in tool_calls:
            if tool_call.name == "run_etsy_scraper":
                count = tool_call.input.get("target_count", 1000)
                print(f"[AI Agent] Tool onaylandı. {count} ürün için Botasaurus tetikleniyor...")
                
                # 1. Kazıma
                raw_results = scrape_etsy_headphones(data={"target_count": count})
                
                # 2. Temizleme
                print("[AI Agent] Ham veriler işleniyor ve saf (clean) hale getiriliyor...")
                clean_results = clean_and_parse_data(raw_results)
                
                # 3. Excel (.xlsx) Formatında Kayıt
                print(f"[AI Agent] Veriler Excel formatına dönüştürülüyor -> {output_filepath}")
                df = pd.DataFrame(clean_results)
                df.to_excel(output_filepath, index=False, engine='openpyxl')
                    
                print(f"[AI Agent] İşlem başarıyla tamamlandı. Dosya kaydedildi: {output_filepath}")
    else:
        print("[AI Agent] Tool çağrısı tetiklenmedi:")
        print(response.content[0].text)

if __name__ == "__main__":
    main()
    
