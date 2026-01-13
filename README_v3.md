# 🛒 Pazarmetre v3.0 - Fiyat Karşılaştırma Platformu

[![Version](https://img.shields.io/badge/version-3.0-blue.svg)](https://github.com)
[![Python](https://img.shields.io/badge/python-3.11-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-red.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-Proprietary-orange.svg)](LICENSE)

**Sakarya'nın en kapsamlı market fiyat karşılaştırma platformu**

> Hendek'te başladık, tüm Sakarya'ya yayılacağız! 🚀

---

## 🎯 Proje Vizyonu

Pazarmetre, tüketicilerin market fiyatlarını kolayca karşılaştırmasını ve en uygun alışverişi yapmasını sağlayan bir platformdur.

### Ana Özellikler

✅ **Master Product List** - Standardize ürün listesi  
✅ **Multi-Business Support** - İşletmeler kendi fiyatlarını yönetir  
✅ **Admin Panel** - Kapsamlı yönetim arayüzü  
✅ **JWT Authentication** - Güvenli giriş sistemi  
✅ **Responsive Design** - Mobil uyumlu arayüz  
✅ **Real-time Updates** - Anlık fiyat güncellemeleri  

---

## 📋 İçindekiler

- [Özellikler](#-özellikler)
- [Kurulum](#-kurulum)
- [Kullanım](#-kullanım)
- [API Referansı](#-api-referansı)
- [Veritabanı](#-veritabanı)
- [Deployment](#-deployment)
- [Katkıda Bulunma](#-katkıda-bulunma)

---

## ✨ Özellikler

### 1. Master Product List 🏪
- **Standardize ürün isimleri** - "Süt" vs "süt" karmaşası yok
- **Kategori sistemi** - 7 ana kategori
- **Standart birimler** - 1kg, 1L, 500g, vb.
- **39 temel ürün** - Seed data ile başlangıç

### 2. İşletme Paneli 🏢
- **Kayıt & Giriş** - JWT ile güvenli authentication
- **Fiyat Yönetimi** - Kendi fiyatlarını ekle/sil
- **Dashboard** - Özet istatistikler
- **Ürün Önerisi** - Yeni ürün öner

### 3. Admin Paneli 👨‍💼
- **Ürün Yönetimi** - CRUD işlemleri
- **İşletme Yönetimi** - Onaylama ve yönetim
- **İstatistikler** - Ziyaretçi analitiği
- **Seed İşlemleri** - Toplu veri yükleme

### 4. Kullanıcı Arayüzü 🎨
- **Fiyat Karşılaştırma** - En ucuz ürünü bul
- **Lokasyon Tabanlı** - İlçe/mahalle bazlı filtreleme
- **Responsive** - Mobil, tablet, desktop uyumlu
- **Temiz Tasarım** - Tailwind CSS ile modern UI

---

## 🚀 Kurulum

### Gereksinimler

- Python 3.11+
- pip
- virtualenv (önerilir)

### Adım Adım Kurulum

```bash
# 1. Proje dizinine git
cd /home/ubuntu/pazarmetre_gelistirilmis

# 2. Virtual environment oluştur (opsiyonel ama önerilir)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# veya
venv\Scripts\activate  # Windows

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. .env dosyasını oluştur
cp .env.example .env

# 5. .env dosyasını düzenle
nano .env
# Şunları ayarla:
# - PAZARMETRE_ADMIN=güvenli_şifre
# - SECRET_KEY=güvenli_random_key
# - PAZAR_DB=sqlite:///pazarmetre.db

# 6. Veritabanını oluştur (otomatik)
# İlk çalıştırmada otomatik oluşur

# 7. Seed data yükle (opsiyonel)
python -c "from app import seed_products; seed_products()"

# 8. Sunucuyu başlat
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### Hızlı Başlangıç

```bash
# Tek komutla başlat
uvicorn app:app --reload --port 8000

# Tarayıcıda aç
# http://localhost:8000
```

---

## 💻 Kullanım

### Admin Olarak

#### 1. Giriş Yap
```
URL: http://localhost:8000/admin/login
Şifre: .env dosyasındaki PAZARMETRE_ADMIN
```

#### 2. Ürünleri Yükle
```
Admin Panel > Seed & Setup > "Ürünleri Yükle"
```

#### 3. İşletmeleri Onayla
```
Admin Panel > İşletme Yönetimi > Bekleyen İşletmeler
```

### İşletme Olarak

#### 1. Kayıt Ol
```
URL: http://localhost:8000/business/register
Formu doldur ve kayıt ol
Admin onayını bekle
```

#### 2. Giriş Yap
```
URL: http://localhost:8000/business/login
E-posta ve şifre ile giriş
```

#### 3. Fiyat Ekle
```
Dashboard > Fiyat Ekle
Master listeden ürün seç
Fiyat gir ve ekle
```

### Kullanıcı Olarak

#### 1. Lokasyon Seç
```
Ana sayfa > Şehir/İlçe dropdown'larından seç
```

#### 2. Ürün Ara
```
Arama çubuğuna ürün adı yaz
veya
Kategorilerden seç
```

#### 3. Fiyatları Karşılaştır
```
En ucuz fiyatı gör
Mağaza bilgilerini incele
```

---

## 🗄️ Veritabanı

### Modeller

#### Product (Master Product List)
```python
{
    "id": 1,
    "name": "Süt (Tam Yağlı)",
    "unit": "1L",
    "category": "Süt Ürünleri",
    "description": "Tam yağlı süt",
    "is_active": true,
    "featured": false,
    "created_by": "admin",
    "created_at": "2026-01-12T10:00:00"
}
```

#### Business
```python
{
    "id": 1,
    "email": "magaza@example.com",
    "business_name": "Örnek Market",
    "contact_person": "Ahmet Yılmaz",
    "phone": "0532 123 45 67",
    "city": "Sakarya",
    "district": "Hendek",
    "is_approved": true,
    "is_active": true
}
```

#### Offer
```python
{
    "id": 1,
    "product_id": 1,
    "store_id": 1,
    "price": 45.90,
    "business_id": 1,
    "created_at": "2026-01-12T10:00:00"
}
```

### ERD (Entity Relationship Diagram)

```
┌─────────────────┐       ┌─────────────────┐
│    Product      │       │    Business     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ name            │       │ email           │
│ unit            │       │ business_name   │
│ category        │       │ is_approved     │
│ description     │       └─────────────────┘
│ is_active       │                │
└─────────────────┘                │
         │                         │
         │                         │
         ▼                         ▼
┌─────────────────┐       ┌─────────────────┐
│     Offer       │───────│     Store       │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ product_id (FK) │       │ name            │
│ store_id (FK)   │       │ business_id (FK)│
│ business_id(FK) │       │ city            │
│ price           │       │ district        │
└─────────────────┘       └─────────────────┘
```

---

## 🌐 API Referansı

### Public Endpoints

#### GET `/`
Ana sayfa - Fiyat listesi

**Query Parameters:**
- `q` - Arama terimi
- `city` - Şehir
- `district` - İlçe

**Response:** HTML

---

### Business Endpoints

#### POST `/business/register`
İşletme kaydı

**Body:**
```json
{
  "business_name": "Örnek Market",
  "contact_person": "Ahmet Yılmaz",
  "email": "magaza@example.com",
  "phone": "0532 123 45 67",
  "city": "Sakarya",
  "district": "Hendek",
  "password": "güvenli_şifre",
  "password_confirm": "güvenli_şifre"
}
```

**Response:** Redirect to dashboard

#### POST `/business/login`
İşletme girişi

**Body:**
```json
{
  "email": "magaza@example.com",
  "password": "güvenli_şifre"
}
```

**Response:** JWT cookie + redirect

#### GET `/business/dashboard` 🔒
İşletme dashboard (Auth gerekli)

**Headers:**
```
Cookie: business_token=<jwt_token>
```

**Response:** HTML

#### POST `/business/price/add` 🔒
Fiyat ekleme (Auth gerekli)

**Body:**
```json
{
  "product_id": 1,
  "store_id": 1,
  "price": 45.90
}
```

**Response:** Redirect to dashboard

---

### Admin Endpoints

#### POST `/admin/login`
Admin girişi

**Body:**
```json
{
  "password": "admin_şifresi"
}
```

**Response:** Cookie + redirect

#### GET `/admin/products` 🔒
Ürün listesi (Admin)

**Response:** HTML (Tablo)

#### POST `/admin/product/add` 🔒
Yeni ürün ekle (Admin)

**Body:**
```json
{
  "name": "Süt (Tam Yağlı)",
  "category": "Süt Ürünleri",
  "unit": "1L",
  "description": "Tam yağlı süt",
  "featured": false
}
```

**Response:** Redirect

#### GET `/admin/businesses` 🔒
İşletme listesi (Admin)

**Response:** HTML (Tablo)

#### GET `/admin/business/approve/{id}` 🔒
İşletme onayla (Admin)

**Response:** Redirect

---

## 🚢 Deployment

### Production Kurulum

#### 1. Sunucu Hazırlığı
```bash
# Sistem güncellemeleri
sudo apt update && sudo apt upgrade -y

# Python ve bağımlılıkları
sudo apt install python3.11 python3-pip python3-venv nginx -y

# Firewall ayarları
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 22
sudo ufw enable
```

#### 2. Proje Kurulumu
```bash
# Proje dizini
cd /var/www/pazarmetre

# Virtual environment
python3 -m venv venv
source venv/bin/activate

# Bağımlılıklar
pip install -r requirements.txt
pip install gunicorn

# .env dosyası
cp .env.example .env
nano .env
# Production değerlerini gir
```

#### 3. Systemd Service
```bash
# /etc/systemd/system/pazarmetre.service
sudo nano /etc/systemd/system/pazarmetre.service
```

```ini
[Unit]
Description=Pazarmetre FastAPI Application
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/var/www/pazarmetre
Environment="PATH=/var/www/pazarmetre/venv/bin"
ExecStart=/var/www/pazarmetre/venv/bin/gunicorn app:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120

[Install]
WantedBy=multi-user.target
```

```bash
# Service başlat
sudo systemctl daemon-reload
sudo systemctl enable pazarmetre
sudo systemctl start pazarmetre
sudo systemctl status pazarmetre
```

#### 4. Nginx Reverse Proxy
```bash
# /etc/nginx/sites-available/pazarmetre
sudo nano /etc/nginx/sites-available/pazarmetre
```

```nginx
server {
    listen 80;
    server_name pazarmetre.com www.pazarmetre.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /var/www/pazarmetre/static/;
    }
}
```

```bash
# Aktifleştir
sudo ln -s /etc/nginx/sites-available/pazarmetre /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 5. SSL (Let's Encrypt)
```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d pazarmetre.com -d www.pazarmetre.com
```

---

## 🔧 Konfigürasyon

### Environment Variables (.env)

```bash
# Veritabanı
PAZAR_DB=sqlite:///pazarmetre.db
# Veya PostgreSQL:
# PAZAR_DB=postgresql://user:pass@localhost/pazarmetre

# Admin şifresi
PAZARMETRE_ADMIN=güvenli_admin_şifresi

# JWT Secret
SECRET_KEY=çok_güvenli_ve_uzun_random_key

# Token geçerlilik süresi (dakika)
ACCESS_TOKEN_EXPIRE_MINUTES=10080  # 7 gün

# Fiyat eskime süreleri
DAYS_STALE=2
DAYS_HARD_DROP=7

# Analytics
PAZAR_SALT=güvenli_salt_değeri
```

### Production Best Practices

1. **Güvenlik**
   - `SECRET_KEY` değerini güçlü yapın
   - `PAZARMETRE_ADMIN` şifresini değiştirin
   - HTTPS kullanın
   - Firewall aktif tutun

2. **Performance**
   - Gunicorn worker sayısını ayarlayın
   - PostgreSQL kullanın (production için)
   - Nginx caching ekleyin
   - CDN kullanın (statik dosyalar için)

3. **Monitoring**
   - Log dosyalarını izleyin
   - Uptime monitoring
   - Error tracking (Sentry)

4. **Backup**
   - Veritabanı yedekleri
   - Günlük otomatik backup
   - Off-site backup

---

## 📊 Teknoloji Yığını

### Backend
- **FastAPI** - Modern, hızlı web framework
- **SQLModel** - ORM (SQLAlchemy + Pydantic)
- **Python 3.11** - Programlama dili

### Frontend
- **Tailwind CSS** - Utility-first CSS framework
- **Vanilla JS** - Hafif JavaScript
- **HTML5** - Modern markup

### Database
- **SQLite** - Development
- **PostgreSQL** - Production (önerilir)

### Authentication
- **JWT** - JSON Web Tokens
- **Passlib** - Password hashing (bcrypt)

### Deployment
- **Gunicorn** - WSGI HTTP Server
- **Nginx** - Reverse proxy
- **Systemd** - Service management
- **Let's Encrypt** - SSL certificates

---

## 🧪 Test

### Manuel Test
```bash
# Sunucuyu başlat
uvicorn app:app --reload --port 8000

# Testleri çalıştır
pytest tests/

# Coverage
pytest --cov=app tests/
```

### Test Senaryoları

#### 1. Admin Flow
- [ ] Admin login
- [ ] Ürün ekleme
- [ ] İşletme onaylama
- [ ] Seed data yükleme

#### 2. Business Flow
- [ ] İşletme kaydı
- [ ] Admin onay bekleme
- [ ] Giriş yapma
- [ ] Fiyat ekleme
- [ ] Ürün önerme

#### 3. User Flow
- [ ] Lokasyon seçme
- [ ] Ürün arama
- [ ] Fiyat karşılaştırma
- [ ] Detay sayfası

---

## 📈 Performans

### Benchmarks (Örnek)

| Endpoint | Response Time | RPS |
|----------|---------------|-----|
| GET `/` | ~50ms | 1000+ |
| GET `/admin` | ~30ms | 500+ |
| POST `/business/price/add` | ~100ms | 200+ |

### Optimizasyon İpuçları

1. **Database Indexing**
```sql
CREATE INDEX idx_product_name ON product(name);
CREATE INDEX idx_offer_created ON offer(created_at);
```

2. **Caching**
```python
# Redis ile caching eklenebilir
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
```

3. **Query Optimization**
```python
# Eager loading
products = s.exec(
    select(Product)
    .options(joinedload(Product.offers))
).all()
```

---

## 🤝 Katkıda Bulunma

### Nasıl Katkıda Bulunulur?

1. **Fork edin**
2. **Branch oluşturun** (`git checkout -b feature/amazing-feature`)
3. **Commit edin** (`git commit -m 'Add amazing feature'`)
4. **Push edin** (`git push origin feature/amazing-feature`)
5. **Pull Request açın**

### Kod Standartları

- **PEP 8** - Python style guide
- **Type hints** kullanın
- **Docstring** ekleyin
- **Test** yazın

### Örnek PR Template

```markdown
## Değişiklikler
- Özellik X eklendi
- Bug Y düzeltildi

## Test
- [ ] Manuel test yapıldı
- [ ] Unit testler eklendi

## Screenshots
(Varsa ekran görüntüleri)
```

---

## 📝 Sürüm Geçmişi

### v3.0 (12 Ocak 2026) - Master Product List
- ✅ Master Product List sistemi
- ✅ İşletme paneli entegrasyonu
- ✅ JWT authentication
- ✅ Admin ürün/işletme yönetimi
- ✅ Ürün önerisi sistemi
- ✅ 39 seed ürün

### v2.0 (Önceki)
- İşletme routes hazırlığı
- PostgreSQL desteği
- Deployment iyileştirmeleri

### v1.0 (İlk Release)
- Temel fiyat karşılaştırma
- Admin fiyat girişi
- Lokasyon tabanlı filtreleme

---

## ⚖️ Lisans

Bu proje **Proprietary** lisansı altındadır. Tüm hakları saklıdır.

© 2026 Pazarmetre

---

## 📞 İletişim

**Pazarmetre Ekibi**

- 🌐 Website: [https://pazarmetre.com](https://pazarmetre.com)
- 📧 E-posta: pazarmetre1@gmail.com
- 🐛 Issues: [GitHub Issues](https://github.com/pazarmetre/issues)

---

## 🙏 Teşekkürler

Pazarmetre'yi kullanan herkese teşekkür ederiz!

**Özel Teşekkürler:**
- Hendek halkına
- İlk işletme partnerlerimize
- Açık kaynak topluluğuna

---

## 🔮 Gelecek Planları

### 2026 Q1
- [ ] Mobil uygulama
- [ ] E-posta bildirimleri
- [ ] Toplu işlem desteği

### 2026 Q2
- [ ] API v2
- [ ] Sepet karşılaştırma
- [ ] Fiyat tahmin algoritması

### 2026 Q3-Q4
- [ ] Tüm Sakarya'ya yayılma
- [ ] İstatistik ve raporlar
- [ ] Gelişmiş özellikler

---

**⭐ Projeyi beğendiyseniz yıldız verin!**

**📢 Fiyatları karşılaştırın, tasarruf edin!**
