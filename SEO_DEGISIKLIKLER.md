# Pazarmetre SEO İyileştirmeleri

## 📅 Tarih: 24 Ocak 2026

## 📋 Yapılan Değişiklikler

### 1. SEO Konfigürasyonu (Satır 597-694)

Yeni eklenen global değişkenler ve fonksiyonlar:

```python
SITE_URL = "https://www.pazarmetre.com.tr"
SITE_NAME = "Pazarmetre"
DEFAULT_OG_IMAGE = f"{SITE_URL}/static/og-image.png"

SEO_DATA = {
    "home": {...},   # Ana sayfa meta verileri
    "kasap": {...},  # Kasap sayfası meta verileri
    "pazar": {...}   # Pazar sayfası meta verileri
}
```

### 2. Schema.org Fonksiyonları

- `get_schema_org_website()` - WebSite schema
- `get_schema_org_organization()` - Organization schema
- `get_schema_org_product()` - Product schema (ürün sayfaları için)
- `get_schema_org_breadcrumb()` - BreadcrumbList schema

### 3. Layout Fonksiyonu Güncellendi (Satır 746-915)

`layout()` fonksiyonu artık SEO parametreleri alıyor:

```python
def layout(
    req: Request, 
    body: str, 
    title: str = "Pazarmetre",
    description: str = None,      # Meta description
    keywords: str = None,         # Meta keywords
    canonical_path: str = None,   # Canonical URL
    og_image: str = None,         # Open Graph resmi
    schema_json: str = None,      # Schema.org JSON-LD
    noindex: bool = False         # robots noindex
) -> HTMLResponse:
```

**Eklenen Meta Taglar:**
- `<meta name="description">`
- `<meta name="keywords">`
- `<meta name="robots">`
- `<link rel="canonical">`
- Open Graph tagları (og:type, og:url, og:title, og:description, og:image, og:site_name, og:locale)
- Twitter Card tagları (twitter:card, twitter:url, twitter:title, twitter:description, twitter:image)
- Favicon linkleri

### 4. robots.txt Endpoint (Satır 457-478)

**URL:** `/robots.txt`

```
User-agent: *
Allow: /
Disallow: /admin
Disallow: /admin/
Disallow: /api/
Disallow: /setloc
Disallow: /lokasyon

Sitemap: https://www.pazarmetre.com.tr/sitemap.xml
Crawl-delay: 1
```

### 5. sitemap.xml Endpoint (Satır 480-541)

**URL:** `/sitemap.xml`

Dinamik olarak oluşturulan sitemap:
- Statik sayfalar (/, /iletisim, /hukuk, /cerez-politikasi, /kvkk-aydinlatma)
- Tüm featured ürün sayfaları
- İlçe bazlı sayfalar (16 ilçe)

### 6. Ana Sayfa SEO (Satır 1375-1386)

```
Title: "Market, Kasap ve Pazar Fiyatları Karşılaştırma | Pazarmetre"
Description: "Sakarya'da market, kasap ve pazar fiyatlarını karşılaştır..."
Keywords: "market fiyatları, kasap fiyatları, pazar fiyatları..."
Schema: WebSite
```

### 7. Ürün Sayfaları SEO (Satır 1737-1759)

Her ürün sayfası için dinamik SEO:

```
Title: "[Ürün Adı] Fiyatları 2026 | Pazarmetre"
Description: "[Ürün Adı] en uygun fiyatlar. [Şehir]/[İlçe] bölgesinde..."
Keywords: "[ürün adı], [ürün adı] fiyat, [ürün adı] fiyatları..."
Schema: Product (AggregateOffer ile)
```

---

## 📁 Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `/home/ubuntu/Uploadskod/app.py` | SEO iyileştirmeleri eklenmiş app.py |
| `/home/ubuntu/Uploadskod/app.py.backup` | Orijinal app.py yedeği |
| `/home/ubuntu/Uploadskod/SEO_DEGISIKLIKLER.md` | Bu dosya |

---

## ✅ Kontrol Listesi

- [x] Meta description eklendi (tüm sayfalar)
- [x] Meta keywords eklendi (tüm sayfalar)
- [x] Canonical URL'ler eklendi
- [x] Open Graph tagları eklendi
- [x] Twitter Card tagları eklendi
- [x] robots.txt endpoint'i eklendi
- [x] sitemap.xml endpoint'i eklendi
- [x] Schema.org WebSite verisi eklendi
- [x] Schema.org Organization verisi eklendi
- [x] Schema.org Product verisi eklendi (ürün sayfaları)
- [x] Favicon link'leri eklendi
- [x] Mevcut kod yapısı korundu
- [x] Syntax kontrolü yapıldı

---

## 🔧 Önerilen Ek İyileştirmeler

1. **og-image.png oluştur:** `/static/og-image.png` dosyası eklenmeli (1200x630px önerilir)
2. **favicon.ico ekle:** `/static/favicon.ico` dosyası eklenmeli
3. **apple-touch-icon.png ekle:** `/static/apple-touch-icon.png` dosyası eklenmeli (180x180px)
4. **logo.png ekle:** `/static/logo.png` dosyası eklenmeli (Schema.org için)
5. **Google Search Console:** Siteyi Google Search Console'a ekle ve sitemap.xml'i gönder
6. **Bing Webmaster Tools:** Siteyi Bing'e de kaydet

---

## 📊 SEO Etki Değerlendirmesi

| Öğe | Önceki | Sonraki |
|-----|--------|---------|
| Meta Description | ❌ Yok | ✅ Tüm sayfalarda |
| Canonical URL | ❌ Yok | ✅ Tüm sayfalarda |
| Open Graph | ❌ Yok | ✅ Tüm sayfalarda |
| Twitter Cards | ❌ Yok | ✅ Tüm sayfalarda |
| robots.txt | ❌ Yok | ✅ Mevcut |
| sitemap.xml | ❌ Yok | ✅ Dinamik |
| Schema.org | ❌ Yok | ✅ WebSite, Organization, Product |

---

**Not:** Bu değişiklikler mevcut kod yapısını bozmadan eklenmiştir. Tüm route'lar ve fonksiyonlar çalışmaya devam etmektedir.
