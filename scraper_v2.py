"""
Etsy Trend Scraper - v2 (Çoklu Kaynak + Analiz)
=================================================

KAYNAKLAR:
1. Alura - Trending Etsy Listings  (alura.io/trending-etsy-listings)
2. Alura - Best Selling Etsy Items (alura.io/best-selling-etsy-items)
   -> İkisi de yapılandırılmış (tablo) veri, güvenilir parse edilebiliyor.
3. Google Trends (pytrends, resmi olmayan ama yaygın kullanılan kütüphane)
   -> Her ürünün ana anahtar kelimesi için arama ilgisi (0-100) skoru.
   -> Bu, "gerçekten mi trend, yoksa Alura'da tesadüfen mi öyle görünüyor"
      sorusuna ikinci bir bağımsız sinyal katıyor.

BİLİNÇLİ OLARAK EKLEMEDİKLERİM (ve neden):
- Etsy'nin kendi trending_products sayfası: JS ile render oluyor, bot
  korumalı. Zaten Alura'nın verisi Etsy'den geliyor, aynı bilgiye
  dolaylı ve daha güvenli yoldan ulaşıyoruz.
- eRank / Printify blog yazıları: Serbest metin (tablo değil), regex ile
  güvenilir yapılandırılmış veri çıkarmak pratik değil. Bunun yerine
  Google Trends ile bağımsız doğrulama yapıyoruz.

ANALİZ (bu script'in asıl istenen kısmı):
Her ürün trend/seasonal/evergreen olarak etiketlendikten sonra, her
kategori için:
  - "en iyi" ürün  -> en yüksek aylık satış + en yüksek Trends skoru
  - "ortalama"      -> o kategorideki ürünlerin ortalama aylık satışı/geliri
hesaplanıp rapora yazılıyor.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import requests
from bs4 import BeautifulSoup

try:
    from pytrends.request import TrendReq
    HAS_TRENDS = True
except ImportError:
    HAS_TRENDS = False  # requirements.txt kurulmadıysa Trends adımı atlanır

# ---- Ayarlar ----------------------------------------------------------

SOURCES = {
    "trending": "https://www.alura.io/trending-etsy-listings",
    "best_selling": "https://www.alura.io/best-selling-etsy-items",
}
PAGES_PER_SOURCE = 3
SLEEP_SECONDS = 2
HISTORY_FILE = Path("history.json")
OUTPUT_DIR = Path("reports")
EVERGREEN_WEEKS_THRESHOLD = 4
IMAGE_FETCH_LIMIT = 30
TRENDS_FETCH_LIMIT = 20  # Google Trends rate-limit'e takılmamak için sınırlı

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrendResearchBot/1.0; "
                  "+personal-research-tool)"
}

SEASONAL_KEYWORDS = [
    "christmas", "halloween", "valentine", "easter", "thanksgiving",
    "mother's day", "mothers day", "father's day", "fathers day",
    "back to school", "graduation", "new year", "hanukkah", "diwali",
    "spooky", "fall", "autumn", "summer", "winter", "spring",
    "wedding season", "holiday",
]

LISTING_PATTERN = re.compile(
    r"^(.*?)\s+(\d{2,7})\s+(\d{2,6})\s+([A-Z]{3})(\d{2,10})\s+([A-Za-z &,]+)$"
)

# ---- Adım 1: Alura kaynaklarını çek ------------------------------------

def fetch_page(base_url: str, page_num: int) -> str:
    url = base_url if page_num == 1 else f"{base_url}?7e6c5e59_page={page_num}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text

    # --- TEŞHİS (DEBUG) ---
    # 0 ürün geldiği için, gerçekte ne indirdiğimizi workflow loglarına yazdırıyoruz.
    # Bu blok sorunu bulduktan sonra kaldırılabilir.
    print(f"    [debug] HTTP {resp.status_code}, {len(html)} karakter indirildi")
    anchor_count = html.count('href="#"')
    print(f"    [debug] html içinde href=\"#\" sayısı: {anchor_count}")
    # Sayfada gerçekten satış rakamı benzeri bir şey var mı diye kaba kontrol
    sample_has_digits_pattern = bool(re.search(r"\d{3,7}\s+\d{2,6}\s+[A-Z]{3}\d", html))
    print(f"    [debug] beklenen sayı deseni bulundu mu: {sample_has_digits_pattern}")
    if anchor_count == 0:
        # İlk 500 karakteri logla ki neyle karşılaştığımızı görelim
        print(f"    [debug] HTML örneği (ilk 500 karakter):\n{html[:500]}")
    # --- TEŞHİS SONU ---

    return html


def parse_listings(html: str, source_name: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    listings = []
    debug_samples = []  # TEŞHİS için

    for a in soup.find_all("a", href="#"):
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 20:
            continue

        # --- TEŞHİS (DEBUG) ---
        if len(debug_samples) < 3:
            debug_samples.append(text)
            print(f"    [debug] örnek metin #{len(debug_samples)} (repr): {text!r}")
        # --- TEŞHİS SONU ---

        match = LISTING_PATTERN.match(text)
        if not match:
            continue

        title, total_sales, monthly_sales, currency, revenue, category = match.groups()
        listings.append({
            "title": title.strip(),
            "total_sales": int(total_sales),
            "monthly_sales": int(monthly_sales),
            "currency": currency,
            "revenue": int(revenue),
            "category": category.strip(),
            "source": source_name,
            "listing_url": a.get("data-href") or None,
        })

    return listings


def fetch_all_sources() -> list[dict]:
    all_listings = []
    for source_name, base_url in SOURCES.items():
        for page in range(1, PAGES_PER_SOURCE + 1):
            print(f"[{source_name}] sayfa {page} çekiliyor...")
            html = fetch_page(base_url, page)
            page_listings = parse_listings(html, source_name)
            print(f"  -> {len(page_listings)} ürün")
            all_listings.extend(page_listings)
            time.sleep(SLEEP_SECONDS)
    return all_listings


def dedupe_across_sources(listings: list[dict]) -> list[dict]:
    """Aynı ürün iki kaynakta da çıkabilir (aynı Etsy listing'i); başlığa göre
    birleştirip hangi kaynaklarda göründüğünü not ediyoruz (güven sinyali)."""
    merged: dict[str, dict] = {}
    for l in listings:
        key = l["title"].strip().lower()
        if key not in merged:
            merged[key] = {**l, "seen_in_sources": {l["source"]}}
        else:
            merged[key]["seen_in_sources"].add(l["source"])
            # en yüksek satış rakamını tut (güncel görünen kaynağı baz al)
            if l["monthly_sales"] > merged[key]["monthly_sales"]:
                merged[key].update({
                    "monthly_sales": l["monthly_sales"],
                    "total_sales": l["total_sales"],
                    "revenue": l["revenue"],
                    "currency": l["currency"],
                })
    result = []
    for item in merged.values():
        item["source_count"] = len(item["seen_in_sources"])
        item["seen_in_sources"] = sorted(item["seen_in_sources"])
        result.append(item)
    return result


# ---- Adım 2: Görsel çekme (öncekiyle aynı) -----------------------------

def fetch_product_images(listing_url: str | None, title: str) -> list[str]:
    images = []
    target_url = listing_url or (
        "https://www.etsy.com/search?q=" + requests.utils.quote(title[:60])
    )
    try:
        resp = requests.get(target_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            images.append(og_image["content"])

        for img in soup.select("img[src*='il_'], img[data-src*='il_']")[:3]:
            src = img.get("src") or img.get("data-src")
            if src and src not in images:
                images.append(src)
            if len(images) >= 2:
                break
    except requests.RequestException:
        pass
    return images[:2]


# ---- Adım 3: Google Trends doğrulaması ---------------------------------

def get_trends_score(keyword: str) -> int | None:
    """Son 3 aydaki ortalama arama ilgisini (0-100) döndürür. Kütüphane
    yoksa ya da hata olursa None döner (script çökmez, sadece o alan boş kalır)."""
    if not HAS_TRENDS:
        return None
    try:
        pytrends = TrendReq(hl="en-US", tz=0)
        pytrends.build_payload([keyword[:80]], timeframe="today 3-m")
        data = pytrends.interest_over_time()
        if data.empty:
            return None
        return int(data[keyword[:80]].mean())
    except Exception:
        return None


def simplify_keyword(title: str) -> str:
    """Trends sorgusu için başlığı kısaltır (ilk 3-4 anlamlı kelime)."""
    words = re.split(r"[,\-|]", title)[0].split()
    return " ".join(words[:4])


# ---- Adım 4: Kategorize etme -------------------------------------------

def load_history() -> dict:
    return json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else {}


def save_history(history: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def is_seasonal(title: str) -> bool:
    lower = title.lower()
    return any(k in lower for k in SEASONAL_KEYWORDS)


def classify(listing: dict, history: dict, run_date: str) -> str:
    key = listing["title"].strip().lower()
    if key not in history:
        history[key] = {"first_seen": run_date, "seen_dates": [run_date]}
    elif run_date not in history[key]["seen_dates"]:
        history[key]["seen_dates"].append(run_date)

    weeks_seen = len(history[key]["seen_dates"])
    if is_seasonal(listing["title"]):
        return "seasonal"
    if weeks_seen >= EVERGREEN_WEEKS_THRESHOLD:
        return "evergreen"
    return "trend"


# ---- Adım 5: Analiz (en iyi / ortalama) --------------------------------

def analyze_category(listings: list[dict]) -> dict:
    if not listings:
        return {"count": 0}

    best = max(
        listings,
        key=lambda l: l["monthly_sales"] + (l.get("trends_score") or 0) * 10,
    )
    return {
        "count": len(listings),
        "avg_monthly_sales": round(mean(l["monthly_sales"] for l in listings), 1),
        "avg_revenue": round(mean(l["revenue"] for l in listings), 0),
        "best_product": {
            "title": best["title"],
            "category": best["category"],
            "monthly_sales": best["monthly_sales"],
            "revenue": f"{best['currency']}{best['revenue']}",
            "trends_score": best.get("trends_score"),
            "seen_in_sources": best.get("seen_in_sources", []),
            "images": best.get("images", []),
        },
    }


# ---- Ana akış ------------------------------------------------------------

def main():
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = load_history()

    raw_listings = fetch_all_sources()
    listings = dedupe_across_sources(raw_listings)
    print(f"\nToplam {len(raw_listings)} ham kayıt -> {len(listings)} benzersiz ürün")

    for l in listings:
        l["category_tag"] = classify(l, history, run_date)
    save_history(history)

    # Görseller (ilk N ürün için)
    for l in listings[:IMAGE_FETCH_LIMIT]:
        l["images"] = fetch_product_images(l.get("listing_url"), l["title"])
        time.sleep(SLEEP_SECONDS)

    # Google Trends doğrulaması (ilk N ürün için, en yüksek satışlılardan başla)
    top_for_trends = sorted(listings, key=lambda l: -l["monthly_sales"])[:TRENDS_FETCH_LIMIT]
    for l in top_for_trends:
        l["trends_score"] = get_trends_score(simplify_keyword(l["title"]))
        time.sleep(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"{run_date}.json").write_text(
        json.dumps(listings, indent=2, ensure_ascii=False)
    )

    analysis = {
        cat: analyze_category([l for l in listings if l["category_tag"] == cat])
        for cat in ("trend", "seasonal", "evergreen")
    }
    (OUTPUT_DIR / f"{run_date}_analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False)
    )

    write_markdown_report(listings, analysis, run_date)
    print(f"\nRapor hazır: reports/{run_date}.md")


def write_markdown_report(listings: list[dict], analysis: dict, run_date: str) -> None:
    lines = [f"# Etsy Trend Raporu — {run_date}\n"]
    labels = {"trend": "🔥 Trend (yeni)", "seasonal": "🍂 Sezonluk", "evergreen": "♻️ Evergreen"}

    for cat, label in labels.items():
        info = analysis[cat]
        lines.append(f"\n## {label} — {info['count']} ürün\n")
        if info["count"] == 0:
            continue
        lines.append(f"- Ortalama aylık satış: **{info['avg_monthly_sales']}**")
        lines.append(f"- Ortalama tahmini gelir: **{info['avg_revenue']}**")
        best = info["best_product"]
        lines.append(f"\n**🏆 Bu kategorideki en iyi ürün:** {best['title']}")
        lines.append(
            f"  - Kategori: {best['category']} | Aylık satış: {best['monthly_sales']} | "
            f"Gelir: {best['revenue']} | Trends skoru: {best['trends_score']}"
        )
        lines.append(f"  - Görüldüğü kaynaklar: {', '.join(best['seen_in_sources'])}")
        for img in best.get("images", []):
            lines.append(f"  ![görsel]({img})")

        lines.append("\n**Kategorideki diğer ürünler (ilk 15):**")
        cat_listings = sorted(
            [l for l in listings if l["category_tag"] == cat],
            key=lambda x: -x["monthly_sales"],
        )[:15]
        for l in cat_listings:
            trends = f" | Trends: {l['trends_score']}" if l.get("trends_score") is not None else ""
            lines.append(f"  - {l['title']} — aylık satış: {l['monthly_sales']}{trends}")
            for img in l.get("images", []):
                lines.append(f"    ![görsel]({img})")

    (OUTPUT_DIR / f"{run_date}.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
           
