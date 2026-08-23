"""
Etsy Trend Tracker - v3 (Google Trends + Gerçek Etsy Verisi)
==============================================================

MANTIK:
1. Google Trends'ten (pytrends) popülerlik sinyali topla:
   - Genel "şu an trend olanlar" (trending-now RSS)
   - Bizim niş tohum kelimelerimizle (planner, svg, printable, t-shirt
     design, mug design vb.) ilgili "yükselen aramalar"
2. Bu kelimeleri omkarcloud Etsy Scraper API'sine gönderip GERÇEK Etsy
   verisi al: favori sayısı, bestseller etiketi, digital/physical bayrağı.
3. SADECE dijital ürünleri ve POD (baskı-üstüne-talep: tişört, kupa,
   havlu vb.) ürünlerini tut - el yapımı fiziksel ürünleri (takı, mum,
   seramik) ELE.
4. Puanla ve 3 kategoriye ayır: trend / seasonal / evergreen.
   Her kategoride ne kadar gerçekten kalifiye ürün varsa o kadarını
   göster (max 15, zorla doldurma yok).

GEREKEN AYARLAR (GitHub Secrets):
- ETSY_SCRAPER_API_KEY  -> omkar.cloud'da ücretsiz hesap açıp alınır
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID -> opsiyonel (rapor bildirimi için)
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import requests

try:
    from pytrends.request import TrendReq
    HAS_TRENDS = True
except ImportError:
    HAS_TRENDS = False

# ---- Ayarlar ------------------------------------------------------------

ETSY_API_KEY = os.environ.get("ETSY_SCRAPER_API_KEY", "")
ETSY_API_BASE = "https://etsy-scraper.omkar.cloud/etsy"

HISTORY_FILE = Path("history.json")
OUTPUT_DIR = Path("reports")
EVERGREEN_WEEKS_THRESHOLD = 4
MAX_PER_CATEGORY = 15  # üst sınır - zorla doldurma yok, kalifiye olan kadarı gösterilir
MIN_FAVORITES_TO_QUALIFY = 20  # bu altındaki ürünler "kalifiye" sayılmaz

# Sadece dijital ürün + POD (baskı üstüne talep) dünyamıza uygun tohum
# kelimeler. Fiziksel el yapımı kategoriler (takı, mum, seramik vb.)
# BİLİNÇLİ OLARAK YOK - kullanıcı sadece dijital + POD satıyor.
SEED_KEYWORDS = [
    "budget planner template",
    "digital planner",
    "printable planner",
    "svg bundle",
    "inventory tracker template",
    "spreadsheet template",
    "excel template",
    "notion template",
    "wall art printable",
    "clipart bundle",
    "custom t-shirt design",
    "personalized mug design",
    "printable wall decor",
    "digital download gift",
    "canva template",
]

SEASONAL_KEYWORDS = [
    "christmas", "halloween", "valentine", "easter", "thanksgiving",
    "mother's day", "mothers day", "father's day", "fathers day",
    "back to school", "graduation", "new year", "hanukkah", "diwali",
    "spooky", "fall", "autumn", "summer", "winter", "spring", "holiday",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TrendResearchBot/1.0)"}


# ---- Adım 1: Google Trends'ten popüler kelime topla ---------------------

def get_trending_now(geo: str = "US") -> list[str]:
    """Google'ın 'şu an trend olanlar' RSS beslemesinden genel popüler
    terimleri çeker (statik XML, JS render sorunu yok)."""
    try:
        url = f"https://trends.google.com/trending/rss?geo={geo}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        # RSS <title> etiketlerini basitçe ayıkla
        titles = re.findall(r"<title>(.*?)</title>", resp.text)
        return [t.strip() for t in titles[1:] if t.strip()]  # ilk title kanal adı
    except requests.RequestException as e:
        print(f"  [uyarı] Google Trends RSS alınamadı: {e}")
        return []


def get_rising_queries_for_seed(pytrends, seed: str) -> list[str]:
    """Bir tohum kelimeyle ilgili yükselen aramaları döndürür."""
    if not HAS_TRENDS:
        return []
    try:
        pytrends.build_payload([seed], timeframe="today 3-m")
        related = pytrends.related_queries()
        rising = related.get(seed, {}).get("rising")
        if rising is None or rising.empty:
            return []
        return rising["query"].tolist()[:5]
    except Exception as e:
        print(f"  [uyarı] '{seed}' için yükselen arama alınamadı: {e}")
        return []


def collect_candidate_keywords() -> dict:
    """Genel trend + niş tohum kelimelerden aday kelime havuzu oluşturur.
    Döner: {"general_trending": [...], "niche_rising": {seed: [...]}}"""
    result = {"general_trending": [], "niche_rising": {}}

    print("Google Trends - genel trend listesi çekiliyor...")
    result["general_trending"] = get_trending_now()
    print(f"  -> {len(result['general_trending'])} genel trend terimi bulundu")

    if HAS_TRENDS:
        pytrends = TrendReq(hl="en-US", tz=0)
        for seed in SEED_KEYWORDS:
            print(f"Niş kelime işleniyor: '{seed}'...")
            rising = get_rising_queries_for_seed(pytrends, seed)
            result["niche_rising"][seed] = rising
            print(f"  -> {len(rising)} yükselen arama")
            time.sleep(1)
    else:
        print("  [uyarı] pytrends kurulu değil, niş yükselen arama adımı atlanıyor")

    return result


# ---- Adım 2: omkarcloud Etsy API ile gerçek veri doğrulama --------------

def search_etsy(keyword: str) -> list[dict]:
    """Bir kelimeyle Etsy'de arama yapar, listing_id + name döner."""
    if not ETSY_API_KEY:
        print("  [uyarı] ETSY_SCRAPER_API_KEY tanımlı değil, arama atlanıyor")
        return []
    try:
        resp = requests.get(
            f"{ETSY_API_BASE}/search",
            params={"keyword": keyword},
            headers={"API-Key": ETSY_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("listings", [])[:5]  # her kelimeden ilk 5 sonuç
    except requests.RequestException as e:
        print(f"  [uyarı] '{keyword}' için Etsy araması başarısız: {e}")
        return []


def get_listing_details(listing_id: str) -> dict | None:
    """Bir listing_id için tam detay (favori, bestseller, digital vb.) çeker."""
    if not ETSY_API_KEY:
        return None
    try:
        resp = requests.get(
            f"{ETSY_API_BASE}/listing",
            params={"listing_id": listing_id},
            headers={"API-Key": ETSY_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"  [uyarı] listing {listing_id} detayı alınamadı: {e}")
        return None


def is_relevant_product(details: dict) -> bool:
    """Sadece dijital ürünleri VEYA POD (tişört/kupa/havlu vb.) ürünlerini kabul eder.
    El yapımı fiziksel ürünleri (takı, mum, seramik) eler."""
    flags = details.get("flags", {})
    if flags.get("digital"):
        return True

    # POD ürünleri dijital bayrağı taşımaz ama kategori/isimden anlaşılır
    pod_hints = ["t-shirt", "tshirt", "mug", "towel", "tumbler", "poster",
                 "sweatshirt", "hoodie", "tote bag", "phone case"]
    name = details.get("name", "").lower()
    categories = " ".join(details.get("categories", [])).lower()
    return any(hint in name or hint in categories for hint in pod_hints)


def gather_etsy_data(keywords: list[str]) -> list[dict]:
    """Kelime listesini Etsy'de arar, detaylarını çeker, dijital/POD
    olmayanları eler. Sonuç: her ürün için detay + hangi kelimeden
    geldiği bilgisi."""
    results = []
    seen_ids = set()

    for kw in keywords:
        print(f"Etsy'de aranıyor: '{kw}'...")
        search_hits = search_etsy(kw)
        for hit in search_hits:
            listing_id = hit.get("listing_id")
            if not listing_id or listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            details = get_listing_details(listing_id)
            time.sleep(0.5)
            if not details:
                continue
            if not is_relevant_product(details):
                continue

            details["_source_keyword"] = kw
            results.append(details)

        time.sleep(0.5)

    print(f"\nToplam {len(results)} dijital/POD uygun ürün bulundu")
    return results


# ---- Adım 3: Kategorize etme (trend / seasonal / evergreen) ------------

def load_history() -> dict:
    return json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else {}


def save_history(history: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def is_seasonal(name: str) -> bool:
    lower = name.lower()
    return any(k in lower for k in SEASONAL_KEYWORDS)


def classify(listing: dict, history: dict, run_date: str) -> str:
    key = str(listing.get("listing_id"))
    if key not in history:
        history[key] = {"first_seen": run_date, "seen_dates": [run_date]}
    elif run_date not in history[key]["seen_dates"]:
        history[key]["seen_dates"].append(run_date)

    weeks_seen = len(history[key]["seen_dates"])
    name = listing.get("name", "")

    if is_seasonal(name):
        return "seasonal"
    if weeks_seen >= EVERGREEN_WEEKS_THRESHOLD:
        return "evergreen"
    return "trend"


def qualifies(listing: dict) -> bool:
    """Minimum kalite eşiği: yeterince favori almış olmalı."""
    return listing.get("favorites_count", 0) >= MIN_FAVORITES_TO_QUALIFY


def score(listing: dict) -> float:
    """Sıralama skoru: favori sayısı + bestseller bonusu."""
    base = listing.get("favorites_count", 0)
    if listing.get("flags", {}).get("bestseller"):
        base += 500  # bestseller etiketi güçlü bir sinyal, öne çıkar
    if listing.get("flags", {}).get("top_rated"):
        base += 200
    return base


# ---- Ana akış ------------------------------------------------------------

def main():
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = load_history()

    # 1) Aday kelimeleri topla
    candidates = collect_candidate_keywords()
    all_keywords = list(SEED_KEYWORDS)  # tohum kelimeler zaten aranacak
    all_keywords += candidates["general_trending"][:10]  # genel trendden ilk 10
    for rising_list in candidates["niche_rising"].values():
        all_keywords += rising_list
    all_keywords = list(dict.fromkeys(all_keywords))  # tekrarları temizle, sırayı koru

    print(f"\nToplam {len(all_keywords)} benzersiz kelime ile Etsy'de aranacak\n")

    # 2) Etsy'de gerçek veriyle doğrula
    listings = gather_etsy_data(all_keywords)

    # 3) Kalite eşiğini geçenleri kategorize et
    qualifying = [l for l in listings if qualifies(l)]
    print(f"{len(qualifying)} ürün minimum kalite eşiğini geçti "
          f"(min {MIN_FAVORITES_TO_QUALIFY} favori)")

    for l in qualifying:
        l["category_tag"] = classify(l, history, run_date)
    save_history(history)

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"{run_date}.json").write_text(
        json.dumps(qualifying, indent=2, ensure_ascii=False)
    )

    analysis = {
        cat: analyze_category([l for l in qualifying if l["category_tag"] == cat])
        for cat in ("trend", "seasonal", "evergreen")
    }
    (OUTPUT_DIR / f"{run_date}_analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False)
    )

    write_markdown_report(qualifying, analysis, run_date)
    print(f"\nRapor hazır: reports/{run_date}.md")


def analyze_category(listings: list[dict]) -> dict:
    if not listings:
        return {"count": 0, "items": []}

    sorted_listings = sorted(listings, key=score, reverse=True)[:MAX_PER_CATEGORY]
    return {
        "count": len(sorted_listings),
        "avg_favorites": round(mean(l.get("favorites_count", 0) for l in sorted_listings), 1),
        "items": sorted_listings,
    }


def write_markdown_report(listings: list[dict], analysis: dict, run_date: str) -> None:
    lines = [f"# Etsy Trend Raporu — {run_date}\n"]
    labels = {"trend": "🔥 Trend (yeni)", "seasonal": "🍂 Sezonluk", "evergreen": "♻️ Evergreen"}

    for cat, label in labels.items():
        info = analysis[cat]
        lines.append(f"\n## {label} — {info['count']} ürün\n")
        if info["count"] == 0:
            lines.append("_Bu hafta kalifiye ürün bulunamadı._")
            continue
        lines.append(f"Ortalama favori sayısı: **{info['avg_favorites']}**\n")

        for l in info["items"]:
            flags = l.get("flags", {})
            badge = " 🏆bestseller" if flags.get("bestseller") else ""
            lines.append(
                f"- **{l['name'][:80]}**{badge} — favori: {l.get('favorites_count', 0)} | "
                f"fiyat: {l.get('currency', '')}{l.get('price_usd', l.get('price', ''))} | "
                f"kelime: _{l.get('_source_keyword', '')}_"
            )
            lines.append(f"  - [Etsy linki]({l.get('url', '')})")
            img = l.get("images", {}).get("full") or l.get("images", {}).get("thumbnail")
            if img:
                lines.append(f"  ![görsel]({img})")

    (OUTPUT_DIR / f"{run_date}.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
