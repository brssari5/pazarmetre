# 🚀 Pazarmetre Deployment Rehberi

## 📋 İçindekiler

1. [GitHub Deployment Sorunu Çözümü](#github-deployment-sorunu-çözümü)
2. [Local Development](#local-development)
3. [Production Deployment](#production-deployment)
   - [Render.com](#rendercom)
   - [Railway.app](#railwayapp)
   - [Heroku](#heroku)
   - [VPS (Linux Server)](#vps-linux-server)
4. [PostgreSQL Kurulumu](#postgresql-kurulumu)
5. [Domain ve SSL](#domain-ve-ssl)
6. [Monitoring & Backup](#monitoring--backup)

---

## ⚠️ GitHub Deployment Sorunu Çözümü

### Problem

Önceki versiyonda her GitHub'a push yaptığınızda:
- ❌ Tüm market ve fiyat bilgileri siliniyor
- ❌ Veritabanı sıfırlanıyor
- ❌ Girdiğiniz veriler kayboluyor

### Neden Oluyordu?

1. `pazarmetre.db` dosyası Git'e commit ediliyordu
2. Her deployment'ta Git'teki eski (boş) veritabanı kopyalanıyordu
3. Production ortamında kalıcı storage kullanılmıyordu

### ✅ Çözüm (3 Adımlı)

#### Adım 1: .gitignore Dosyasını Kontrol Edin

Proje dizininde `.gitignore` dosyası olmalı:

```gitignore
# ========================================
# PAZARMETRE .gitignore
# ========================================

# *** KRİTİK: Veritabanı dosyaları ***
# SQLite veritabanları GİT'E ASLA COMMIT EDİLMEMELİ
*.db
*.db-journal
*.db-shm
*.db-wal
pazarmetre.db*

# Environment Variables (hassas bilgiler içerir)
.env
.env.local
.env.production

# Python
__pycache__/
*.pyc
venv/
```

⚠️ **ÖNEMLİ**: Bu dosya zaten projede mevcut. Kontrol edin!

#### Adım 2: Mevcut DB'yi Git'ten Kaldırın

Eğer daha önce `pazarmetre.db` commit ettiyseniz:

```bash
# 1. Git cache'den kaldır (dosya lokal olarak kalır)
git rm --cached pazarmetre.db
git rm --cached .env

# 2. Commit et
git add .gitignore
git commit -m "fix: veritabanı ve env dosyalarını git'ten kaldır"

# 3. Push et
git push origin main
```

#### Adım 3: Production Veritabanı Kullanın

Production ortamında **SQLite yerine PostgreSQL** kullanmalısınız!

**Neden PostgreSQL?**
- ✅ Kalıcı veri saklama
- ✅ Backup desteği
- ✅ Daha iyi performans
- ✅ Çoklu kullanıcı desteği
- ✅ Deployment platformlarında ücretsiz

---

## 💻 Local Development

### Kurulum

```bash
# 1. Clone
git clone https://github.com/username/pazarmetre.git
cd pazarmetre

# 2. Virtual Environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Bağımlılıklar
pip install -r requirements.txt

# 4. Environment Variables
cp .env.example .env
# .env dosyasını düzenleyin

# 5. Çalıştır
uvicorn app:app --reload --port 8000
```

### Local'de Test Etme

```bash
# Tarayıcıda açın
http://localhost:8000

# Admin paneli
http://localhost:8000/admin
# Şifre: .env dosyasındaki PAZARMETRE_ADMIN değeri

# İşletme kayıt
http://localhost:8000/business/register
```

---

## 🌐 Production Deployment

### Platform Karşılaştırması

| Platform | Fiyat | PostgreSQL | SSL | Kolay | Önerilen |
|----------|-------|------------|-----|-------|----------|
| **Render** | Ücretsiz | ✅ Ücretsiz | ✅ | ✅✅✅ | ⭐⭐⭐ |
| **Railway** | $5/ay | ✅ Dahil | ✅ | ✅✅ | ⭐⭐ |
| **Heroku** | $5/ay | ✅ | ✅ | ✅✅✅ | ⭐⭐ |
| **VPS** | $5-20/ay | ❌ Kendin kur | ❌ Kendin kur | ❌ | ⭐ |

**Öneri**: Başlangıç için **Render.com** kullanın (tamamen ücretsiz!)

---

## 🔷 Render.com Deployment

### Avantajları
- ✅ Tamamen ücretsiz
- ✅ PostgreSQL dahil (ücretsiz)
- ✅ Otomatik SSL
- ✅ GitHub entegrasyonu
- ✅ Kolay kullanım

### Adım Adım Kurulum

#### 1. Render'a Kaydolun

🌐 https://render.com → Sign Up → GitHub ile giriş yapın

#### 2. PostgreSQL Veritabanı Oluşturun

1. Render Dashboard → **New +** → **PostgreSQL**
2. Ayarlar:
   ```
   Name: pazarmetre-db
   Database: pazarmetre
   User: pazarmetre_user
   Region: Frankfurt (size yakın olan)
   Instance Type: Free
   ```
3. **Create Database** butonuna tıklayın
4. ⚠️ **Internal Database URL**'yi kopyalayın (sonra lazım olacak)

#### 3. Web Service Oluşturun

1. Dashboard → **New +** → **Web Service**
2. GitHub reponuzu seçin: `username/pazarmetre`
3. Ayarlar:
   ```
   Name: pazarmetre
   Region: Frankfurt
   Branch: main
   Root Directory: (boş bırakın)
   Runtime: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: uvicorn app:app --host 0.0.0.0 --port $PORT
   Instance Type: Free
   ```

#### 4. Environment Variables Ekleyin

Web Service ayarlarında **Environment** sekmesine gidin:

```bash
# Veritabanı (adım 2'den aldığınız Internal URL)
PAZAR_DB=postgresql://pazarmetre_user:******@dpg-xxx.frankfurt-postgres.render.com/pazarmetre

# Admin şifresi (değiştirin!)
PAZARMETRE_ADMIN=super_guvenli_sifre_123

# JWT Secret (rastgele 32+ karakter)
SECRET_KEY=xK8n2Vp9Rq4Lm7Tz6Uw3Ys5Gh1Fj0Cd8Bv4

# Analytics salt (rastgele string)
PAZAR_SALT=analytics_salt_random_abc123

# Diğer ayarlar
DAYS_STALE=2
DAYS_HARD_DROP=7
```

⚠️ **ÖNEMLİ**: `PAZAR_DB` değerini Adım 2'deki **Internal Database URL** ile değiştirin!

#### 5. Deploy Edin

**Create Web Service** butonuna tıklayın. Render otomatik olarak:
- ✅ Kodu çeker
- ✅ Bağımlılıkları yükler
- ✅ Uygulamayı başlatır
- ✅ HTTPS sertifikası oluşturur

İlk deploy 5-10 dakika sürebilir.

#### 6. Test Edin

Deploy tamamlandığında:

```
Your service is live 🎉
https://pazarmetre.onrender.com
```

Tarayıcıda açın ve test edin!

### Otomatik Deployment

Artık her GitHub push'unda otomatik deploy olur:

```bash
git add .
git commit -m "feat: yeni özellik"
git push origin main
# → Render otomatik deploy eder
```

---

## 🚂 Railway.app Deployment

### Kurulum

1. 🌐 https://railway.app → Sign Up → GitHub ile giriş
2. **New Project** → **Deploy from GitHub repo**
3. Reponuzu seçin: `username/pazarmetre`
4. **Add PostgreSQL** butonuna tıklayın
5. **Variables** sekmesinden environment variables ekleyin:

```bash
PAZAR_DB=${{Postgres.DATABASE_URL}}
PAZARMETRE_ADMIN=your_admin_password
SECRET_KEY=your_random_32_char_secret
PAZAR_SALT=your_random_salt
```

6. **Settings** → **Generate Domain** ile public URL alın
7. Deploy!

**Maliyet**: İlk $5 ücretsiz, sonra $5/ay

---

## 🟣 Heroku Deployment

### Kurulum

```bash
# 1. Heroku CLI yükleyin
curl https://cli-assets.heroku.com/install.sh | sh

# 2. Giriş yapın
heroku login

# 3. Uygulama oluşturun
heroku create pazarmetre

# 4. PostgreSQL ekleyin
heroku addons:create heroku-postgresql:mini

# 5. Environment variables
heroku config:set PAZARMETRE_ADMIN=your_password
heroku config:set SECRET_KEY=your_secret
heroku config:set PAZAR_SALT=your_salt

# 6. Procfile oluşturun
echo "web: uvicorn app:app --host 0.0.0.0 --port \$PORT" > Procfile

# 7. Deploy
git add Procfile
git commit -m "Add Procfile for Heroku"
git push heroku main

# 8. Açın
heroku open
```

**Maliyet**: $5/ay (Eco Dynos)

---

## 🖥️ VPS (Linux Server) Deployment

### Gereksinimler
- Ubuntu 20.04+ veya Debian 11+
- En az 1GB RAM
- Python 3.10+
- PostgreSQL 14+
- Nginx

### Kurulum

```bash
# 1. Sunucuya bağlanın
ssh root@your-server-ip

# 2. Sistem güncellemeleri
apt update && apt upgrade -y

# 3. Python ve gerekli araçları yükleyin
apt install python3 python3-pip python3-venv postgresql nginx -y

# 4. PostgreSQL kullanıcısı oluşturun
sudo -u postgres psql
CREATE DATABASE pazarmetre;
CREATE USER pazarmetre_user WITH PASSWORD 'strong_password';
GRANT ALL PRIVILEGES ON DATABASE pazarmetre TO pazarmetre_user;
\q

# 5. Projeyi klonlayın
cd /var/www
git clone https://github.com/username/pazarmetre.git
cd pazarmetre

# 6. Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 7. .env dosyası oluşturun
cp .env.example .env
nano .env
# PostgreSQL connection string'i girin:
# PAZAR_DB=postgresql://pazarmetre_user:strong_password@localhost:5432/pazarmetre

# 8. Systemd service oluşturun
nano /etc/systemd/system/pazarmetre.service
```

**Pazarmetre service dosyası**:

```ini
[Unit]
Description=Pazarmetre FastAPI Application
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/pazarmetre
Environment="PATH=/var/www/pazarmetre/venv/bin"
EnvironmentFile=/var/www/pazarmetre/.env
ExecStart=/var/www/pazarmetre/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# 9. Service'i başlatın
systemctl daemon-reload
systemctl start pazarmetre
systemctl enable pazarmetre
systemctl status pazarmetre

# 10. Nginx konfigürasyonu
nano /etc/nginx/sites-available/pazarmetre
```

**Nginx config**:

```nginx
server {
    listen 80;
    server_name pazarmetre.com.tr www.pazarmetre.com.tr;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# 11. Nginx'i etkinleştirin
ln -s /etc/nginx/sites-available/pazarmetre /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx

# 12. SSL sertifikası (Let's Encrypt)
apt install certbot python3-certbot-nginx -y
certbot --nginx -d pazarmetre.com.tr -d www.pazarmetre.com.tr

# 13. Firewall
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

---

## 🐘 PostgreSQL Kurulumu

### Local PostgreSQL (Development)

```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib

# macOS
brew install postgresql
brew services start postgresql

# Windows
# PostgreSQL installer'ı indirin: https://www.postgresql.org/download/windows/
```

### Veritabanı Oluşturma

```bash
sudo -u postgres psql

CREATE DATABASE pazarmetre;
CREATE USER pazarmetre_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE pazarmetre TO pazarmetre_user;

\q
```

### .env Dosyasını Güncelleyin

```bash
PAZAR_DB=postgresql://pazarmetre_user:your_password@localhost:5432/pazarmetre
```

### SQLite'dan PostgreSQL'e Migrasyon

Eğer SQLite'dan geçiş yapıyorsanız:

```bash
# 1. SQLite verilerini export edin
sqlite3 pazarmetre.db .dump > dump.sql

# 2. PostgreSQL'e import edin
psql -U pazarmetre_user -d pazarmetre -f dump.sql
```

---

## 🌐 Domain ve SSL

### Domain Ayarları

1. Domain sağlayıcınıza gidin (GoDaddy, Namecheap, vs.)
2. DNS ayarlarını güncelleyin:

**Render için**:
```
Type: CNAME
Name: @
Value: pazarmetre.onrender.com

Type: CNAME
Name: www
Value: pazarmetre.onrender.com
```

**VPS için**:
```
Type: A
Name: @
Value: your.server.ip.address

Type: A
Name: www
Value: your.server.ip.address
```

### SSL Sertifikası

**Render/Railway/Heroku**: Otomatik SSL, yapmanız gereken bir şey yok! ✅

**VPS (Let's Encrypt)**:
```bash
certbot --nginx -d pazarmetre.com.tr -d www.pazarmetre.com.tr
```

### SSL Otomatik Yenileme

```bash
# Certbot otomatik yenileme testi
certbot renew --dry-run

# Crontab'a ekle (her gün 2'de kontrol et)
crontab -e
0 2 * * * certbot renew --quiet
```

---

## 📊 Monitoring & Backup

### Monitoring

**1. Uptime Monitoring (Ücretsiz)**

- **UptimeRobot**: https://uptimerobot.com
  - 50 monitor ücretsiz
  - 5 dakikada bir kontrol
  - E-posta bildirimleri

- **Freshping**: https://www.freshworks.com/website-monitoring/
  - 50 site ücretsiz
  - 1 dakikada bir kontrol

**2. Error Tracking**

```bash
# Sentry.io entegrasyonu
pip install sentry-sdk[fastapi]
```

```python
# app.py'ye ekleyin
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn="YOUR_SENTRY_DSN",
    integrations=[FastApiIntegration()],
)
```

**3. Log Monitoring**

```bash
# VPS'de logları izleyin
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
journalctl -u pazarmetre -f
```

### Backup

**PostgreSQL Otomatik Backup**

```bash
#!/bin/bash
# /usr/local/bin/backup-pazarmetre.sh

BACKUP_DIR="/var/backups/pazarmetre"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="pazarmetre_backup_${DATE}.sql.gz"

mkdir -p $BACKUP_DIR

# Backup oluştur
pg_dump -U pazarmetre_user pazarmetre | gzip > "$BACKUP_DIR/$FILENAME"

# 30 günden eski backupları sil
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: $FILENAME"
```

```bash
# Çalıştırılabilir yap
chmod +x /usr/local/bin/backup-pazarmetre.sh

# Crontab'a ekle (her gün saat 3'te)
crontab -e
0 3 * * * /usr/local/bin/backup-pazarmetre.sh
```

**Render.com Backup**

Render Dashboard → Database → **Snapshots** → Manuel snapshot alabilirsiniz.

---

## 🔧 Troubleshooting

### Veritabanı Bağlantı Hatası

```bash
# Connection string'i kontrol edin
echo $PAZAR_DB

# PostgreSQL çalışıyor mu?
systemctl status postgresql

# Firewall kontrolü
sudo ufw status
```

### 502 Bad Gateway (Nginx)

```bash
# Uygulama çalışıyor mu?
systemctl status pazarmetre

# Logları kontrol edin
journalctl -u pazarmetre -n 50

# Port dinliyor mu?
sudo netstat -tlnp | grep 8000
```

### Yavaş Çalışıyor

```python
# app.py'de log ekleyin
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    print(f"{request.url.path}: {duration:.2f}s")
    return response
```

### Render Free Tier 15 Dakika Sonra Uyuyor

**Çözüm**: Cron job ile her 10 dakikada bir ping atın:

```bash
# crontab -e
*/10 * * * * curl https://pazarmetre.onrender.com/healthz
```

Veya UptimeRobot kullanın (5 dakikada bir kontrol eder).

---

## ✅ Deployment Checklist

Deploy etmeden önce kontrol edin:

- [ ] `.gitignore` dosyası mevcut ve `*.db` içeriyor
- [ ] `.env` dosyası Git'e commit edilmemiş
- [ ] `pazarmetre.db` Git'e commit edilmemiş
- [ ] PostgreSQL bağlantı string'i doğru
- [ ] Environment variables ayarlanmış
- [ ] `SECRET_KEY` rastgele ve güçlü (32+ karakter)
- [ ] `PAZARMETRE_ADMIN` şifresi güçlü
- [ ] `requirements.txt` güncel
- [ ] Local'de test edilmiş
- [ ] SSL sertifikası aktif (HTTPS)
- [ ] Domain ayarları yapılmış
- [ ] Backup sistemi kurulmuş
- [ ] Monitoring kurulmuş

---

## 🎉 Başarılı Deployment!

Tebrikler! Pazarmetre başarıyla deploy edildi. Artık:

✅ Veritabanınız kalıcı olarak saklanıyor
✅ Her push'ta veriler kaybolmuyor
✅ SSL ile güvenli
✅ Otomatik deploy çalışıyor
✅ Backup sistemi aktif

---

## 📞 Destek

Sorun yaşarsanız:
- **Email**: pazarmetre1@gmail.com
- **GitHub Issues**: https://github.com/username/pazarmetre/issues

---

*Son Güncelleme: Ocak 2026*
