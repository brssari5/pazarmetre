# -*- coding: utf-8 -*-
"""
Pazarmetre – Geliştirilmiş Versiyon v2.0
- İşletme admin paneli eklendi
- PostgreSQL desteği
- İyileştirilmiş deployment desteği
- Mobil responsive geliştirmeler

Çalıştır (lokal):  uvicorn app:app --reload --port 8000
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from pathlib import Path
import os, json, sqlite3, hashlib
from urllib.parse import quote, unquote

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlalchemy import func, or_
from itertools import zip_longest
import uuid
import traceback
from passlib.context import CryptContext
from jose import JWTError, jwt
from dotenv import load_dotenv


# Load environment variables
load_dotenv()



# ================== Ayarlar ==================
# PostgreSQL bağlantı URL'i - environment variable'dan al, yoksa Internal URL kullan
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://pazarmetre_db_user:V7fFm1Z1HZ7Jh8EBrJE9QKoUciq0biXAadpg-d5kb5qngi27c739n5mi0-a/pazarmetre_db"
)
# Render.com genellikle postgres:// kullanır, postgresql:// olarak düzelt
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
# Yerel geliştirme için SQLite kullanabilirsin
DB_URL = os.environ.get("PAZAR_DB", DATABASE_URL)
ADMIN_PASSWORD = os.environ.get("PAZARMETRE_ADMIN", "pazarmetre123")
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 gün
DAYS_STALE = int(os.environ.get("DAYS_STALE", "2"))
DAYS_HARD_DROP = int(os.environ.get("DAYS_HARD_DROP", "7"))
ANALYTICS_SALT = os.environ.get("PAZAR_SALT", "pazarmetre_salt")  # IP hash için

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ================== Modeller ==================
class Product(SQLModel, table=True):
    """Master Product List - Ana Ürün Listesi"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    unit: Optional[str] = "kg"
    featured: bool = Field(default=False)
    category: Optional[str] = None  # Kategori: Süt Ürünleri, Et Ürünleri, vb.
    description: Optional[str] = None  # Ürün açıklaması
    is_active: bool = Field(default=True)  # Aktif mi?
    created_by: str = Field(default="admin")  # Kim oluşturdu
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

class ProductSuggestion(SQLModel, table=True):
    """İşletmelerin yeni ürün önerileri"""
    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id")
    product_name: str
    category: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    status: str = Field(default="pending")  # pending, approved, rejected
    admin_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None

class Store(SQLModel, table=True):
    """Kanonik mağaza (ilçe başına tek satır) -> FİYAT buraya girilir"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    neighborhood: Optional[str] = None
    # İşletme bağlantısı (opsiyonel)
    business_id: Optional[int] = Field(default=None, foreign_key="business.id")

class Business(SQLModel, table=True):
    """İşletme hesapları - kendi fiyatlarını girebilirler"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    business_name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    
    # Onay durumu
    is_approved: bool = Field(default=False)
    is_active: bool = Field(default=True)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    # Notlar (admin için)
    admin_notes: Optional[str] = None

class Offer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    store_id: int = Field(foreign_key="store.id")
    price: float
    currency: str = "TRY"
    quantity: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved: bool = True
    
    # İşletme tarafından girilmişse
    business_id: Optional[int] = Field(default=None, foreign_key="business.id")

    # senin girdiğin link
    source_url: Optional[str] = None

    # senin az önce eklediğin gramaj bilgisi
    source_weight_g: Optional[float] = None
    source_unit: Optional[str] = None

    # Market/şube adresi (her satır için opsiyonel)
    branch_address: Optional[str] = None

    # ↓↓↓ PRICE WATCHER’ın dolduracağı alanlar ↓↓↓
    # kaynaktan okunan saf fiyat (ör: 149.90)
    source_price: Optional[float] = None
    # watcher en son ne zaman baktı
    source_checked_at: Optional[datetime] = None
    # bizim fiyatla kaynaktaki fiyat çelişiyor mu?
    source_mismatch: bool = Field(default=False)
    
    # Fiyat güncellendiğinde otomatik güncellenen alan
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class Branch(SQLModel, table=True):
    """Şubeler (fiyat bağlamaz) – liste/harita/mesafe için"""
    id: Optional[int] = Field(default=None, primary_key=True)
    brand: str
    city: str
    district: str
    name: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    business_id: Optional[int] = Field(default=None, foreign_key="business.id")
class PriceChange(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int
    store_id: int
    old_price: float
    new_price: float
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    source_url: Optional[str] = None

# --- Basit analytics ---
class Visit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    path: str
    ip_hash: str
    visitor_hash: Optional[str] = None
    ua: Optional[str] = None
    ts: datetime = Field(default_factory=datetime.utcnow)

# ================ DB & App =====================
engine = create_engine(DB_URL, echo=False)
SQLModel.metadata.create_all(engine)

def ensure_featured_column():
    db_path = DB_URL.replace("sqlite:///", "", 1)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(product)")
        cols = [r[1].lower() for r in cur.fetchall()]
        if "featured" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN featured BOOLEAN DEFAULT 0")
            con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass
def ensure_product_category_column():
    db_path = DB_URL.replace("sqlite:///", "", 1)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(product)")
        cols = [r[1].lower() for r in cur.fetchall()]
        if "category" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN category TEXT")
        if "description" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN description TEXT")
        if "is_active" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN is_active BOOLEAN DEFAULT 1")
        if "created_by" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN created_by TEXT DEFAULT 'admin'")
        if "created_at" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN created_at TEXT")
        if "updated_at" not in cols:
            cur.execute("ALTER TABLE product ADD COLUMN updated_at TEXT")
        con.commit()
    except Exception as e:
        print("WARN ensure_product_category_column:", e)
    finally:
        try:
            con.close()
        except Exception:
            pass
# --- YENİ: offer tablosuna source_url sütunu ekleyen helper
def ensure_source_url_column():
    db_path = DB_URL.replace("sqlite:///", "", 1)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(offer)")
        cols = [r[1].lower() for r in cur.fetchall()]
        if "source_url" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN source_url TEXT")
            con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass
def ensure_source_price_columns():
    db_path = DB_URL.replace("sqlite:///", "", 1)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(offer)")
        cols = [r[1].lower() for r in cur.fetchall()]

        if "source_price" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN source_price REAL")
        if "source_checked_at" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN source_checked_at TEXT")
        if "source_mismatch" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN source_mismatch INTEGER DEFAULT 0")
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except:
            pass
def ensure_source_weight_columns():
    db_path = DB_URL.replace("sqlite:///", "", 1)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(offer)")
        cols = [r[1].lower() for r in cur.fetchall()]
        if "source_weight_g" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN source_weight_g REAL")
        if "source_unit" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN source_unit TEXT")
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass

def ensure_branch_address_column():
    db_path = DB_URL.replace("sqlite:///", "", 1)
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(offer)")
        cols = [r[1].lower() for r in cur.fetchall()]
        if "branch_address" not in cols:
            cur.execute("ALTER TABLE offer ADD COLUMN branch_address TEXT")
            con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass


def ensure_visit_schema():
    """
    visit tablosu yoksa oluşturur; varsa eksik kolonları ekler.
    Eski şema yüzünden INSERT patlamasın diye.
    """
    db_path = DB_URL.replace("sqlite:///", "", 1)

    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        # Tablo var mı?
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visit'")
        exists = cur.fetchone() is not None

        if not exists:
            cur.execute("""
                CREATE TABLE visit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT,
                    ip_hash TEXT,
                    visitor_hash TEXT,
                    ua TEXT,
                    ts TEXT
                )
            """)
            con.commit()
        else:
            cur.execute("PRAGMA table_info(visit)")
            cols = [r[1].lower() for r in cur.fetchall()]

            if "path" not in cols:
                cur.execute("ALTER TABLE visit ADD COLUMN path TEXT")
            if "ip_hash" not in cols:
                cur.execute("ALTER TABLE visit ADD COLUMN ip_hash TEXT")
            if "visitor_hash" not in cols:
                cur.execute("ALTER TABLE visit ADD COLUMN visitor_hash TEXT")
            if "ua" not in cols:
                cur.execute("ALTER TABLE visit ADD COLUMN ua TEXT")
            if "ts" not in cols:
                cur.execute("ALTER TABLE visit ADD COLUMN ts TEXT")

            con.commit()
    except Exception as e:
        print("WARN ensure_visit_schema:", e)
    finally:
        try:
            con.close()
        except Exception:
            pass


# Şema yükseltmelerini çağır
ensure_featured_column()
ensure_source_url_column()
ensure_source_weight_columns()  # ← yeni
ensure_source_price_columns()   # ← YENİ
ensure_product_category_column()  # ← ET / TAVUK sütunu
ensure_branch_address_column()  # ← Market adresi sütunu
ensure_visit_schema()  # ← Ziyaret tablosu garanti
        

app = FastAPI(title="Pazarmetre")

# Templates dizini
if Path("templates").exists():
    templates = Jinja2Templates(directory="templates")
else:
    templates = None

# Opsiyonel statik
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

def get_session():
    return Session(engine)

# ================== Middleware: basit ziyaret kaydı ==================
def _client_ip(request: Request) -> str:
    # Reverse proxy arkasında X-Forwarded-For kullanılabilir
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"

def _hash_ip(ip: str) -> str:
    return hashlib.sha256((ip + ANALYTICS_SALT).encode("utf-8")).hexdigest()

@app.middleware("http")
async def log_visit(request: Request, call_next):
    path = request.url.path or "/"
    existing_sess = request.cookies.get("pz_sess")

    response = await call_next(request)

    try:
        if request.method != "GET":
            return response

        accept = (request.headers.get("accept") or "").lower()
        if "text/html" not in accept:
            return response

        if (
            path.startswith("/static")
            or path.startswith("/healthz")
            or path in ("/favicon.ico", "/robots.txt", "/sitemap.xml")
        ):
            return response

        if existing_sess:
            return response

        import uuid
        sess = uuid.uuid4().hex

        response.set_cookie(
            "pz_sess",
            sess,
            samesite="lax",
            path="/",
            httponly=True,
        )

        ip = _client_ip(request)
        ip_h = _hash_ip(ip)
        visitor_h = hashlib.sha256((sess + ANALYTICS_SALT).encode("utf-8")).hexdigest()

        from datetime import datetime as _dt
        with get_session() as s:
            s.add(Visit(
                path=path,
                ip_hash=ip_h,
                visitor_hash=visitor_h,
                ua=(request.headers.get("user-agent", "")[:255]),
                ts=_dt.utcnow()
            ))
            s.commit()

    except Exception as e:
        print("WARN log_visit:", repr(e))
        traceback.print_exc()

    return response
# Basit sağlık kontrolü
@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")
@app.head("/healthz")
def healthz_head():
    # HEAD isteği için sadece 200 dönmesi yeterli, body boş olabilir
    return PlainTextResponse("")

# =============== Mini lokasyon verisi ===============
LOC_JSON = {
    "provinces": [
        {
            "name": "Sakarya",
            "districts": [
                {"name": "Adapazarı"},
                {"name": "Akyazı"},
                {"name": "Arifiye"},
                {"name": "Erenler"},
                {"name": "Ferizli"},
                {"name": "Geyve"},
                {"name": "Hendek"},
                {"name": "Karapürçek"},
                {"name": "Karasu"},
                {"name": "Kaynarca"},
                {"name": "Kocaali"},
                {"name": "Pamukova"},
                {"name": "Sapanca"},
                {"name": "Serdivan"},
                {"name": "Söğütlü"},
                {"name": "Taraklı"},
            ],
        }
    ]
}

# =============== Türkçe Case-Insensitive Yardımcısı ===============
def turkish_lower(s: str) -> str:
    """Türkçe karakterler için case-insensitive dönüşüm"""
    if not s:
        return ""
    # Türkçe harfleri küçük harfe çevir
    tr_map = {
        'İ': 'i', 'I': 'ı',  # I -> ı (Türkçe için özel)
        'Ş': 'ş', 'Ğ': 'ğ', 'Ü': 'ü', 'Ö': 'ö', 'Ç': 'ç',
    }
    result = []
    for c in s:
        if c in tr_map:
            result.append(tr_map[c])
        else:
            result.append(c.lower())
    return ''.join(result)

# ==== Türkçe Tarih Formatı ====
TURKISH_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık"
}

def format_turkish_date(dt) -> str:
    """Tarihi Türkçe formatında döndürür: '15 Ocak 2026'"""
    if not dt:
        return ""
    # Eğer string ise datetime'a çevir
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace(' ', 'T').split('.')[0])
        except:
            return ""
    return f"{dt.day} {TURKISH_MONTHS.get(dt.month, '')} {dt.year}"

def format_turkish_date_short(dt) -> str:
    """Kısa Türkçe tarih: '15 Oca'"""
    if not dt:
        return ""
    # Eğer string ise datetime'a çevir
    if isinstance(dt, str):
        try:
            # ISO format: 2026-01-15T12:30:00 veya 2026-01-15 12:30:00
            dt = datetime.fromisoformat(dt.replace(' ', 'T').split('.')[0])
        except:
            return ""
    month_short = TURKISH_MONTHS.get(dt.month, "")[:3]
    return f"{dt.day} {month_short}"

# =============== Yardımcılar ===============
def get_loc(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    # Cookie'ler URL-encode yazıldığı için burada decode ediyoruz.
    def _get(key):
        v = request.cookies.get(key)
        return unquote(v) if v else None
    return (_get("city"), _get("district"), _get("nb"))

def is_admin(request: Request) -> bool:
    return request.cookies.get("adm", "") == ADMIN_PASSWORD

def require_admin(request: Request):
    if is_admin(request):
        return None

    # 🔴 fetch / POST istekleri için
    if request.method == "POST":
        return PlainTextResponse("UNAUTHORIZED", status_code=401)

    # 🟢 normal sayfa istekleri için
    return RedirectResponse("/admin/login", status_code=302)
def dedupe_by_brand_latest(rows: List[tuple]) -> List[tuple]:
    """
    Aynı şehir/ilçedeki aynı mağaza adını tekilleştirir.
    Her mağaza için EN YENİ kaydı bırakır, SONRA fiyatı küçükten büyüğe sıralar.
    """
    latest = {}
    # En yeni kayıt öne gelsin ki o kalsın
    for o, st in sorted(rows, key=lambda t: t[0].created_at, reverse=True):
        key = (
            (st.name or "").casefold().strip(),
            (st.city or "").casefold().strip(),
            (st.district or "").casefold().strip(),
        )
        if key not in latest:
            latest[key] = (o, st)

    # Tekilleştirilmiş listeyi fiyata göre sırala (en ucuz üstte)
    return sorted(latest.values(), key=lambda t: t[0].price)

def only_fresh_and_latest(rows: List[tuple], days_stale: int = 7, per_brand: bool = True) -> List[tuple]:
    """
    - Aynı marka/store için sadece en yeni fiyat kalır.
    - Eski fiyatlar filtrelenmez, sadece her marka için en yeni kayıt tutulur.
    """
    if not rows:
        return []

    latest = {}
    for o, st in sorted(rows, key=lambda t: t[0].created_at, reverse=True):
        key = (
            (o.product_id, (st.name or "").casefold().strip())
            if per_brand else
            (o.product_id, st.id)
        )
        if key not in latest:
            latest[key] = (o, st)

    return sorted(latest.values(), key=lambda t: t[0].price)

TAILWIND_CDN = "https://cdn.tailwindcss.com"

def header_right_html(request: Request) -> str:
    city, dist, nb = get_loc(request)

    districts = [d["name"] for d in LOC_JSON["provinces"][0]["districts"]]
    dist_opts = "".join(f"<option value='{d}'>{d}</option>" for d in districts)

    js = """
    <script>
    (function(){
      const qs=id=>document.getElementById(id);
      const cookies = Object.fromEntries(
        document.cookie.split('; ').filter(Boolean).map(s=>s.split('='))
      );
      const citySel = qs('cityQuick');
      const distSel = qs('distQuick');

      if(cookies.city) citySel.value = decodeURIComponent(cookies.city);
      if(cookies.district) distSel.value = decodeURIComponent(cookies.district);

      function go(){
        const next = encodeURIComponent(location.pathname + location.search);
        location.href =
          `/setloc?city=${encodeURIComponent(citySel.value)}&district=${encodeURIComponent(distSel.value)}&next=${next}`;
      }

      citySel.addEventListener('change', go);
      distSel.addEventListener('change', go);
    })();
    </script>
    """

    return f"""
      <div class="flex items-center gap-2 mr-2">
        <select id="cityQuick" class="border rounded p-1 text-sm max-w-[120px]">
          <option>Sakarya</option>
        </select>
        <select id="distQuick" class="border rounded p-1 text-sm max-w-[140px]">
          {dist_opts}
        </select>
      </div>

      <a href="/admin"
         class="text-sm px-3 py-2 bg-indigo-600 text-white rounded-lg
                hover:bg-indigo-700 shadow transition">
        Üye Girişi
      </a>

      {js}
    """

def layout(req: Request, body: str, title: str = "Pazarmetre") -> HTMLResponse:
    right = header_right_html(req)
    
    # Get visitor count from database - only show for admin
    visitor_count_html = ""
    if is_admin(req):
        try:
            with get_session() as s:
                visitor_count = s.exec(select(func.count()).select_from(Visit)).one() or 0
            visitor_count_html = f"""
      <span class="text-gray-500 block mt-2">
        👥 Toplam Ziyaretçi: <span class="font-semibold text-emerald-600">{visitor_count:,}</span>
      </span>
            """
        except Exception as e:
            print(f"WARN: Could not fetch visitor count: {e}")
    
    html = f"""<!doctype html>
<html lang="tr"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script src="{TAILWIND_CDN}"></script>
  <script>tailwind.config = {{
    theme: {{ extend: {{ colors: {{ brand: {{"50":"#ecfdf5","100":"#d1fae5","600":"#059669","700":"#047857"}}, accent: {{"50":"#eef2ff","600":"#4f46e5","700":"#4338ca"}} }} }} }}
  }}</script>
  <style>
    .card{{border-radius:1rem; box-shadow:0 6px 14px rgba(0,0,0,.06)}}
    .card:hover{{transform:translateY(-2px); box-shadow:0 10px 20px rgba(0,0,0,.10)}}
    .chip{{padding:.2rem .55rem; border-radius:.5rem; font-weight:700; font-size:.85rem}}
  </style>
</head>
<body class="bg-gradient-to-b from-brand-50 to-white text-gray-900">
  <div class="max-w-6xl mx-auto p-4">
    <div class="flex items-center justify-between mb-5 flex-wrap gap-2">
      <a href="/" class="text-2xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-emerald-600 to-indigo-600">Pazarmetre</a>
      <div class="flex items-center gap-2">{right}</div>
    </div>
    {body}
    <footer class="mt-10 text-xs text-gray-400 text-center">
      <a href="/iletisim" class="text-indigo-600 hover:underline mr-3">İletişim</a>
      <a href="/hukuk" class="text-indigo-600 hover:underline mr-3">Hukuki Bilgilendirme</a>
      <a href="/cerez-politikasi" class="text-indigo-600 hover:underline mr-3">Çerez Politikası</a>
      <a href="/kvkk-aydinlatma" class="text-indigo-600 hover:underline mr-3">KVKK Aydınlatma</a>
      <span class="text-gray-400 block mt-2">
        © {datetime.utcnow().year} Pazarmetre · Fiyatlar bilgilendirme amaçlıdır.
      </span>
      {visitor_count_html}
    </footer>

    <!-- Çerez Bannerı -->
    <div id="cookieBanner"
         class="fixed bottom-4 left-1/2 -translate-x-1/2 max-w-xl w-[95%] bg-white shadow-xl border rounded-2xl px-4 py-3
                flex flex-col md:flex-row items-start md:items-center gap-3 text-sm text-gray-800"
         style="display:none; z-index:50;">
      <div class="flex-1">
        🔔 Pazarmetre deneyiminizi iyileştirmek için zorunlu çerezler ve anonim ziyaret istatistikleri kullanır.
        Detaylar için
        <a href="/cerez-politikasi" class="text-indigo-600 underline">Çerez Politikası</a> ve
        <a href="/kvkk-aydinlatma" class="text-indigo-600 underline">KVKK Aydınlatma Metni</a>'ni inceleyebilirsiniz.
      </div>
      <div class="flex gap-2">
        <button id="cookieAccept"
                class="px-3 py-1 rounded-lg bg-indigo-600 text-white text-xs md:text-sm">
          Kabul Ediyorum
        </button>
      </div>
    </div>

    <script>
      (function(){{
        try {{
          var key = "pz_cookie_ok_v1";
          if (!localStorage.getItem(key)) {{
            var b = document.getElementById("cookieBanner");
            if (b) b.style.display = "flex";
          }}
          var btn = document.getElementById("cookieAccept");
          if (btn) {{
            btn.addEventListener("click", function() {{
              localStorage.setItem(key, "1");
              var b = document.getElementById("cookieBanner");
              if (b) b.style.display = "none";
            }});
          }}
        }} catch(e) {{
          // localStorage yoksa sessiz geç
        }}
      }})();
    </script>

  </div>
</body></html>"""
    return HTMLResponse(html)

# =============== Lokasyon ===============
@app.get("/lokasyon", response_class=HTMLResponse)
async def location_form(request: Request):
    city, dist, nb = get_loc(request)

    loc_json = json.dumps(LOC_JSON, ensure_ascii=False)
    current_json = json.dumps(
        {"city": city or "", "dist": dist or "", "nb": nb or ""},
        ensure_ascii=False
    )

    body = f"""
    <div class="bg-white card p-6 max-w-2xl mx-auto">
      <h2 class="text-xl font-bold mb-1">Lokasyon Seç</h2>
      <p class="text-sm text-gray-500 mb-4">
        İl seçince ilçe; ilçe seçince mahalle otomatik dolar. Mahalle opsiyoneldir.
      </p>

      <form method="post" action="/lokasyon" id="locForm" class="grid md:grid-cols-3 gap-3">
        <select class="border rounded-lg p-2" name="city" id="citySel" required></select>
        <select class="border rounded-lg p-2" name="district" id="distSel" required></select>
        <select class="border rounded-lg p-2" name="nb" id="nbSel"></select>
        <button class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg md:col-span-3">
          Kaydet
        </button>
      </form>
    </div>

    <script>
    (function(){{
      const LOC = {loc_json};
      const CUR = {current_json};

      const citySel = document.getElementById("citySel");
      const distSel = document.getElementById("distSel");
      const nbSel   = document.getElementById("nbSel");

      function setOptions(sel, items, placeholder, selected){{
        sel.innerHTML = "";
        const ph = document.createElement("option");
        ph.value = "";
        ph.textContent = placeholder;
        ph.disabled = true;
        ph.selected = !selected;
        sel.appendChild(ph);

        (items || []).forEach(v => {{
          const opt = document.createElement("option");
          opt.value = v;
          opt.textContent = v;
          if (selected && v.toLowerCase() === selected.toLowerCase()) opt.selected = true;
          sel.appendChild(opt);
        }});
      }}

      function getProvince(cityName){{
        return (LOC.provinces || []).find(
          p => (p.name || "").toLowerCase() === (cityName || "").toLowerCase()
        );
      }}

      function loadCities(){{
        setOptions(
          citySel,
          LOC.provinces.map(p => p.name),
          "İl",
          CUR.city
        );
      }}

      function loadDistricts(){{
        const prov = getProvince(citySel.value || CUR.city);
        const dists = prov ? prov.districts.map(d => d.name) : [];
        setOptions(distSel, dists, "İlçe", CUR.dist);
      }}

      function loadNeighborhoods(){{
        nbSel.innerHTML = "<option value=''>Mahalle (opsiyonel)</option>";
      }}

      citySel.addEventListener("change", () => {{
        CUR.city = citySel.value;
        CUR.dist = "";
        loadDistricts();
        loadNeighborhoods();
      }});

      distSel.addEventListener("change", () => {{
        CUR.dist = distSel.value;
        loadNeighborhoods();
      }});

      // INIT
      loadCities();

      // cookie yoksa: ilk ili otomatik seç (Sakarya)
      if (!CUR.city) {{
        citySel.selectedIndex = 1; // 0 placeholder, 1 ilk il
        CUR.city = citySel.value;
      }}

      loadDistricts();

      // cookie yoksa: ilk ilçeyi otomatik seç
      if (!CUR.dist) {{
        distSel.selectedIndex = 1; // 0 placeholder, 1 ilk ilçe
        CUR.dist = distSel.value;
      }}

      loadNeighborhoods();
    }})();
    </script>
    """

    return layout(request, body, "Lokasyon – Pazarmetre")

@app.post("/lokasyon")
async def location_set(
    city: str = Form(...),
    district: str = Form(...),
    nb: str = Form("")
):
    # Cookie'lere UTF-8 güvenli yazım
    resp = RedirectResponse("/", status_code=302)
    max_age = 60 * 60 * 24 * 90
    resp.set_cookie("city", quote(city, safe=""), max_age=max_age, samesite="lax")
    resp.set_cookie("district", quote(district, safe=""), max_age=max_age, samesite="lax")
    if nb:
        resp.set_cookie("nb", quote(nb, safe=""), max_age=max_age, samesite="lax")
    else:
        resp.delete_cookie("nb")
    return resp

@app.get("/setloc")
async def setloc(city: str, district: str, nb: str = "", next: str = "/"):
    resp = RedirectResponse(next or "/", status_code=302)
    max_age = 60 * 60 * 24 * 90
    resp.set_cookie("city", quote(city, safe=""), max_age=max_age, samesite="lax")
    resp.set_cookie("district", quote(district, safe=""), max_age=max_age, samesite="lax")
    if nb:
        resp.set_cookie("nb", quote(nb, safe=""), max_age=max_age, samesite="lax")
    else:
        resp.delete_cookie("nb")
    return resp

@app.get("/l/{city}/{district}")
async def loc_short_no_nb(city: str, district: str):
    return await setloc(city, district)

@app.get("/l/{city}/{district}/{nb}")
async def loc_short(city: str, district: str, nb: str):
    return await setloc(city, district, nb)

# =============== Ana Sayfa (Vitrin) ===============
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    city, dist, nb = get_loc(request)
    if not city or not dist:
        return RedirectResponse("/lokasyon", status_code=302)

    # URL'den kategori filtresi
    selected_cat = request.query_params.get("cat", "hepsi").lower()
    if selected_cat not in ("hepsi", "et", "tavuk", "diger"):
        selected_cat = "hepsi"

    # Sekme butonları
    tabs = []
    for slug, label in [
        ("hepsi", "Hepsi"),
        ("et", "Kırmızı Et"),
        ("tavuk", "Tavuk"),
        ("diger", "Temel Gıdalar"),
    ]:
        active = (
            "bg-emerald-600 text-white border-emerald-600"
            if selected_cat == slug
            else "bg-white text-gray-700 border-gray-200"
        )
        href = "/" if slug == "hepsi" else f"/?cat={slug}"
        tabs.append(
            f'<a href="{href}" class="px-3 py-1 rounded-full border text-sm {active}">{label}</a>'
        )

    tabs_html = '<div class="flex gap-2 mb-4">' + "".join(tabs) + "</div>"

    # Kategorilere göre kart listeleri
    cards_by_cat = {
        "et": [],      # (fiyat, html)
        "tavuk": [],   # (fiyat, html)
        "diger": [],   # (fiyat, html)
    }

    with get_session() as s:
        q = select(Product).where(Product.featured == True)
        if selected_cat in ("et", "tavuk", "diger"):
            q = q.where(Product.category == selected_cat)

        prods = s.exec(q).all()
        if not prods:
            body = """
            <div class="bg-white card p-6 text-gray-600 text-center">
                Şu an vitrinimizde ürün bulunmuyor.
                <br>Yeni ürünler çok yakında burada olacak.
            </div>
            """
            return layout(request, body, "Pazarmetre | Vitrin")

        # Türkçe case-insensitive ürün gruplama
        # Aynı isme sahip ürünleri (Dana Kıyma, dana kıyma, DANA KIYMA) tek ürün olarak ele al
        product_groups = {}  # key: turkish_lower(name), value: list of products
        
        for p in prods:
            cat_key = (p.category or "").lower()
            if cat_key not in cards_by_cat:
                continue
            if selected_cat != "hepsi" and cat_key != selected_cat:
                continue
            
            norm_name = turkish_lower(p.name)
            if norm_name not in product_groups:
                product_groups[norm_name] = []
            product_groups[norm_name].append(p)
        
        # Her ürün grubu için tek bir kart oluştur
        for norm_name, group_prods in product_groups.items():
            # Grubun ilk ürününü referans olarak kullan (display için)
            ref_prod = group_prods[0]
            cat_key = (ref_prod.category or "").lower()
            
            # Gruptaki TÜM ürünlerin tekliflerini topla
            all_rows = []
            for p in group_prods:
                q_off = (
                    select(Offer, Store)
                    .join(Store, Offer.store_id == Store.id)
                    .where(
                        Offer.product_id == p.id,
                        Offer.approved == True,
                        Store.city == city,
                        Store.district == dist,
                    )
                    .order_by(Offer.price.asc(), Offer.created_at.desc())
                )
                rows = s.exec(q_off).all()
                all_rows.extend(rows)

            # Bu lokasyonda hiç teklif yoksa ürünü vitrine koyma
            if not all_rows:
                continue

            # Mahalle filtresi (varsa)
            if nb:
                rows_nb = [
                    (o, st) for (o, st) in all_rows
                    if (st.neighborhood or "").lower() == nb.lower()
                ]
                if rows_nb:
                    all_rows = rows_nb

            # Marka bazında en yeni teklifi tut
            all_rows = dedupe_by_brand_latest(all_rows)

            # ✅ GERÇEK FİYAT FİLTRESİ (boş / 0 / saçma fiyatlar kart basmasın)
            clean_rows = []
            for o, st in all_rows:
                try:
                    price = float(o.price or 0)
                    if price > 0:
                        clean_rows.append((o, st))
                except Exception:
                    pass

            all_rows = clean_rows
            if not all_rows:
                continue

            # En ucuz fiyata göre sırala
            all_rows = sorted(all_rows, key=lambda t: t[0].price)
            
            off, st = all_rows[0]
            best_price = off.price

            is_new = (datetime.utcnow() - off.created_at).total_seconds() < 86400
            new_dot = (
                '<span class="inline-block w-2 h-2 bg-emerald-500 rounded-full mr-2"></span>'
                if is_new else ""
            )
            loc_label = (st.neighborhood or st.district) if nb else st.district
            unit = (ref_prod.unit or "kg").strip()
            
            # Birim gösterimi için formatlama
            unit_display = f"1 {unit}" if unit else ""
            
            # Display name olarak referans ürün adını kullan
            display_name = ref_prod.name
            
            # Tarih bilgisi - updated_at varsa onu, yoksa created_at kullan
            price_date = getattr(off, 'updated_at', None) or off.created_at
            date_display = format_turkish_date_short(price_date)

            card_html = f"""
              <a href="/urun?name={quote(display_name)}" class="bg-white card p-4 block hover:shadow-lg transition">
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <div class="font-semibold text-gray-900 mb-1">{new_dot}{display_name}</div>
                    <div class="text-sm text-gray-600 mb-1">{unit_display}</div>
                    <div class="text-sm text-gray-500">{st.name} · {loc_label}</div>
                  </div>
                  <div class="text-right shrink-0">
                    <div class="chip bg-accent-50 text-accent-700">{off.price:.2f} {off.currency}</div>
                    <div class="text-xs text-gray-400 mt-1">{date_display}</div>
                  </div>
                </div>
              </a>
            """

            cards_by_cat[cat_key].append((best_price, card_html))
    
    # Kategori başlığı ve kartları gösterme fonksiyonu
    def make_section(title: str, emoji: str, cards: list):
        if not cards:
            return ""
        
        # Başlık renkleri
        if title.lower().strip() == "kırmızı et":
            color_class = "text-red-700"
            pill_bg = "bg-red-100"
        elif title.lower().strip() == "tavuk":
            color_class = "text-amber-700"
            pill_bg = "bg-amber-100"
        else:
            color_class = "text-slate-800"
            pill_bg = "bg-slate-100"

        return f"""
        <div class="mb-8">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-full {pill_bg} flex items-center justify-center text-xl">
              {emoji}
            </div>
            <h2 class="font-bold text-2xl tracking-tight {color_class}">{title}</h2>
          </div>
          <div class="h-[1px] bg-gray-200 mt-2 mb-4"></div>

          <div class="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {''.join(html for _price, html in cards)}
          </div>
        </div>
        """

    if selected_cat == "et":
        sections_html = make_section("Kırmızı Et", "🥩", cards_by_cat["et"])
    elif selected_cat == "tavuk":
        sections_html = make_section("Tavuk", "🍗", cards_by_cat["tavuk"])
    elif selected_cat == "diger":
        sections_html = make_section("Temel Gıdalar", "🛒", cards_by_cat["diger"])
    else:
        sec_et = make_section("Kırmızı Et", "🥩", cards_by_cat["et"])
        sec_tavuk = make_section("Tavuk", "🍗", cards_by_cat["tavuk"])
        sec_diger = make_section("Temel Gıdalar", "🛒", cards_by_cat["diger"])
        sections_html = sec_et + sec_tavuk + sec_diger

    if not sections_html.strip():
        body = "<div class='bg-white card p-6 text-gray-600'>Bu vitrinde şu anda ürün yok.</div>"
    else:
        body = f"""
        <div class="max-w-6xl mx-auto">
          {tabs_html}
          {sections_html}
        </div>
        """

    return layout(request, body, "Pazarmetre – Vitrin")
# =============== Ürün Detay ===============
@app.get("/urun", response_class=HTMLResponse)
async def product_detail(request: Request, name: str):
    # URL’den gelen ismi çözüp normalize edelim
    name = unquote(name).strip()

    city, dist, nb = get_loc(request)

    with get_session() as s:
        # Türkçe karakter uyumluluğu için önce tüm ürünleri çekip Python'da filtrele
        # SQLite'ın lower() fonksiyonu Türkçe karakterleri doğru işlemez (ş, ğ, ü, ö, ç, ı)
        all_rows = s.exec(
            select(Offer, Store, Product)
            .join(Store, Offer.store_id == Store.id)
            .join(Product, Offer.product_id == Product.id)
            .where(
                Offer.approved == True,
                Store.city == city,
                Store.district == dist,
            )
            .order_by(Offer.price.asc(), Offer.created_at.desc())
        ).all()
        
        # Python'da Türkçe karaktere duyarlı case-insensitive karşılaştırma
        name_normalized = turkish_lower(name)
        rows = [
            (o, st, p) for (o, st, p) in all_rows 
            if turkish_lower(p.name) == name_normalized
        ]

    # Hiç satır yoksa: bu lokasyonda bu isimle ürün yok
    if not rows:
        return layout(
            request,
            "<div class='bg-white card p-6'>Bu lokasyonda teklif yok.</div>",
            name,
        )

    # İlk satırdan Product’ı al
    prod = rows[0][2]

    # Sadece (Offer, Store) ikililerini kullanacağız
    rows_os = [(o, st) for (o, st, _p) in rows]

    # Mahalle filtresi varsa uygula
    if nb:
        rows_nb = [
            (o, st)
            for (o, st) in rows_os
            if (st.neighborhood or "").lower() == nb.lower()
        ]
        if rows_nb:
            rows_os = rows_nb

    # Tazelik ve marka kırpması
    rows_os = only_fresh_and_latest(rows_os, days_stale=DAYS_HARD_DROP)
    rows_os = dedupe_by_brand_latest(rows_os)

    if not rows_os:
        return layout(
            request,
            "<div class='bg-white card p-6'>Bu ürün için geçerli fiyat bulunamadı.</div>",
            prod.name,
        )

    best_price = min(o.price for (o, _st) in rows_os)
    is_adm = is_admin(request)

    # --- UYARI BANDI (kısa ve net) ---
    note_html = """
    <div class="mt-2 mb-3 p-3 rounded-lg bg-blue-50 text-blue-800 text-sm">
      Ürünlerin bileşim oranlarında (ör. yağ oranı, katkılar, gramaj) markalar arasında farklılıklar olabilir.
      Detaylar için ilgili mağazanın ürün sayfasına bakınız.
    </div>

    <div class="mt-2 mb-4 p-3 rounded-lg bg-blue-50 text-blue-800 text-sm">
      Marketlerdeki fiyatlar farklı gramajlara ait olabilir.
      <b>Pazarmetre’deki fiyatlar 1&nbsp;kg’a çevrilmiş bilgilendirme fiyatlarıdır.</b>
    </div>
    """

    trs = []
    for off, st in rows_os:
        is_best = (off.price == best_price)
        badge = "<span class='ml-6 text-emerald-600 font-medium whitespace-nowrap'>🟢 En Ucuz</span>" if is_best else ""
        tr_cls = "bg-emerald-50" if is_best else "odd:bg-gray-50"
        nb_text = (st.neighborhood or "") if nb else ""
        addr_left = (nb_text + " – ") if nb_text else ""

        # branch_address varsa onu göster, yoksa store.address
        display_addr = getattr(off, "branch_address", None) or st.address or ""

        addr_extra = (
            f"<span class='text-[11px] ml-2'><a class='text-indigo-600 hover:underline' href='{off.source_url}' target='_blank' rel='noopener'>Kaynak ↗</a></span>"
            if getattr(off, "source_url", None) else ""
        )

        if is_adm:
            # JS içinde güvenli kullanmak için değerleri JSON string yap
            url_js = json.dumps(off.source_url or "")
            addr_js = json.dumps(getattr(off, "branch_address", None) or "")

            admin_cell = (
                "<td class='py-2'>"
                f"<button type='button' onclick='editOffer({off.id}, {off.price}, {url_js}, {addr_js})' "
                "class='text-blue-600 hover:underline text-sm mr-2'>Düzenle</button>"
                f"<button type='button' onclick='showDelModal({off.id}, this)' "
                "class='text-red-600 hover:underline text-sm'>Sil</button>"
                "</td>"
            )
        else:
            admin_cell = ""
        # Tarih bilgisi - updated_at varsa onu, yoksa created_at kullan
        price_date = getattr(off, 'updated_at', None) or off.created_at
        date_display = format_turkish_date_short(price_date)
        
        trs.append(
            f"<tr class='{tr_cls} border-b'>"
            f"<td class='py-2 font-medium'>{st.name}</td>"
            f"<td class='py-2 text-gray-600'>{addr_left}{display_addr}{addr_extra}</td>"
            f"<td class='py-2 text-right font-semibold'>{off.price:.2f} {off.currency}</td>"
            f"<td class='py-2 text-center text-xs text-gray-500'>{date_display}</td>"
            f"<td class='py-2'>{badge}</td>"
            f"{admin_cell}"
            f"</tr>"
        )

    extra_js = """
        <script>
        /* =======================
        MODAL: SİL
        ======================= */
        function showDelModal(id, btn){
        const old = document.getElementById("pm-del-modal");
        if(old) old.remove();

        const wrap = document.createElement("div");
        wrap.id = "pm-del-modal";
        wrap.className = "fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4";

        wrap.innerHTML = `
            <div class="w-full max-w-md rounded-2xl bg-white shadow-xl p-5">
            <div class="text-lg font-semibold mb-2">Silme işlemi nasıl uygulansın?</div>
            <div class="text-sm text-gray-600 mb-4">
                <b>Bu ilçe</b> sadece seçili ilçedeki kaydı siler.<br/>
                <b>Bütün ilçeler</b> aynı kaydı tüm ilçelerden kaldırır.
            </div>

            <div class="flex flex-col gap-2">
                <button id="pm-del-local"
                class="w-full rounded-xl px-4 py-2 bg-gray-900 text-white hover:bg-gray-800">
                Bu ilçe
                </button>

                <button id="pm-del-all"
                class="w-full rounded-xl px-4 py-2 bg-red-600 text-white hover:bg-red-700">
                Bütün ilçeler
                </button>

                <button id="pm-del-cancel"
                class="w-full rounded-xl px-4 py-2 bg-gray-100 text-gray-800 hover:bg-gray-200">
                Vazgeç
                </button>
            </div>
            </div>
        `;

        wrap.addEventListener("click", (e) => {
            if(e.target === wrap) wrap.remove();
        });

        document.body.appendChild(wrap);

        document.getElementById("pm-del-cancel").onclick = () => wrap.remove();

        document.getElementById("pm-del-local").onclick = async () => {
            wrap.remove();
            await delOffer(id, btn, "local");
        };

        document.getElementById("pm-del-all").onclick = async () => {
            const ok = confirm("Emin misin?\\nBu kayıt TÜM ilçelerde silinecek!");
            if(!ok) return;
            wrap.remove();
            await delOffer(id, btn, "all");
        };
        }

        async function delOffer(id, btn, scope){
        const fd = new FormData();
        fd.append("offer_id", id);
        fd.append("scope", scope);

        const r = await fetch("/admin/del", {
            method: "POST",
            body: fd,
            credentials: "same-origin"
        });

        if(r.status === 401){
            alert("Admin oturumu yok / süre dolmuş. Giriş ekranına yönlendiriyorum.");
            location.href = "/admin/login";
            return;
        }

        if(r.ok){
            if(scope === "local"){
            const tr = btn.closest("tr");
            if(tr) tr.remove();
            } else {
            location.reload();
            }
        } else {
            alert("Silinemedi");
        }
        }

        /* =======================
        MODAL: DÜZENLE (scope seçimi)
        ======================= */
        function showEditModal(payload){
        // payload: {id, price, url, addr}
        const old = document.getElementById("pm-edit-modal");
        if(old) old.remove();

        const wrap = document.createElement("div");
        wrap.id = "pm-edit-modal";
        wrap.className = "fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4";

        wrap.innerHTML = `
            <div class="w-full max-w-md rounded-2xl bg-white shadow-xl p-5">
            <div class="text-lg font-semibold mb-2">Düzenleme nasıl uygulansın?</div>
            <div class="text-sm text-gray-600 mb-4">
                <b>Bu ilçe</b> sadece seçili ilçedeki kaydı günceller.<br/>
                <b>Bütün ilçeler</b> aynı ürün + aynı market için tüm ilçeleri günceller.
            </div>

            <div class="flex flex-col gap-2">
                <button id="pm-edit-local"
                class="w-full rounded-xl px-4 py-2 bg-gray-900 text-white hover:bg-gray-800">
                Bu ilçe
                </button>

                <button id="pm-edit-all"
                class="w-full rounded-xl px-4 py-2 bg-indigo-600 text-white hover:bg-indigo-700">
                Bütün ilçeler
                </button>

                <button id="pm-edit-cancel"
                class="w-full rounded-xl px-4 py-2 bg-gray-100 text-gray-800 hover:bg-gray-200">
                Vazgeç
                </button>
            </div>
            </div>
        `;

        wrap.addEventListener("click", (e) => {
            if(e.target === wrap) wrap.remove();
        });

        document.body.appendChild(wrap);

        document.getElementById("pm-edit-cancel").onclick = () => wrap.remove();

        document.getElementById("pm-edit-local").onclick = async () => {
            wrap.remove();
            await applyEdit(payload, "local");
        };

        document.getElementById("pm-edit-all").onclick = async () => {
            const ok = confirm("Emin misin?\\nBu değişiklik TÜM ilçelere uygulanacak!");
            if(!ok) return;
            wrap.remove();
            await applyEdit(payload, "all");
        };
        }

        async function applyEdit(payload, scope){
        const fd = new FormData();
        fd.append("offer_id", payload.id);
        fd.append("price", payload.price);
        fd.append("source_url", payload.url);
        fd.append("branch_address", payload.addr);
        fd.append("scope", scope);

        const r = await fetch("/admin/edit", {
            method: "POST",
            body: fd,
            credentials: "same-origin"
        });

        if(r.status === 401){
            alert("Admin oturumu yok / süre dolmuş. Giriş ekranına yönlendiriyorum.");
            location.href = "/admin/login";
            return;
        }

        if(r.ok){
            location.reload();
        } else {
            alert("Güncellenemedi");
        }
        }

        /* =======================
        DÜZENLE (eski akış aynı: prompt prompt prompt -> sonra scope sor)
        ======================= */
        async function editOffer(id, currentPrice, currentUrl, currentAddr){
        // 1) Fiyat
        let p = prompt("Yeni fiyat (örn: 459.90):", String(currentPrice ?? ""));
        if(p === null) return;
        p = p.trim().replace(",", ".");
        if(!p || isNaN(parseFloat(p))){
            alert("Geçerli bir sayı gir lütfen.");
            return;
        }

        // 2) Adres
        let a = prompt("Şube adresi (boş bırakabilirsin):", currentAddr || "");
        if(a === null) return;
        a = a.trim();

        // 3) URL
        let u = prompt("Kaynak URL (boş bırakabilirsin):", currentUrl || "");
        if(u === null) return;
        u = u.trim();

        // 4) en sonda scope seçtir
        showEditModal({ id: id, price: p, url: u, addr: a });
        }
        </script>
        """
    body = f"""
    <div class="bg-white card p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="text-lg font-bold">{prod.name}</div>
        <a href="/" class="text-sm text-indigo-600">← Vitrine dön</a>
      </div>
      {note_html}
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead><tr class="text-left text-gray-500">
            <th>Mağaza</th><th>Adres</th><th class="text-right">Fiyat</th><th class="text-center">Tarih</th><th></th>{'<th></th>' if is_adm else ''}
          </tr></thead>
          <tbody class="divide-y">{''.join(trs)}</tbody>
        </table>
      </div>
    </div>
    {extra_js}
    """
    return layout(request, body, f"{prod.name} – Pazarmetre")

# =============== Mağazalar (isteğe bağlı, link yok) ===============
@app.get("/magazalar", response_class=HTMLResponse)
async def brands_home(request: Request):
    city, dist, _ = get_loc(request)
    if not city or not dist:
        return RedirectResponse("/lokasyon", status_code=302)

    brands = ["Migros", "A101", "BİM"]
    cards = []
    with get_session() as s:
        for brand in brands:
            st = s.exec(select(Store).where(
                func.lower(Store.name)==brand.casefold(),
                Store.city==city, Store.district==dist
            )).first()
            price_html = "<div class='text-sm text-gray-500'>Fiyat yok</div>"
            if st:
                offs = s.exec(select(Offer)
                    .where(Offer.store_id==st.id, Offer.approved==True)
                    .order_by(Offer.price.asc(), Offer.created_at.desc())
                ).all()
                rows = only_fresh_and_latest([(o, st) for o in offs])
                if rows:
                    off = rows[0][0]
                    price_html = f"<div class='chip bg-accent-50 text-accent-700'>{off.price:.2f} {off.currency}</div>"

            cards.append(f"""
              <div class="bg-white card p-4 flex items-center justify-between">
                <div>
                  <div class="text-lg font-bold">{brand}</div>
                  <div class="text-xs text-gray-500">{city} / {dist}</div>
                </div>
                <div class="text-right">
                  {price_html}
                  <div class="mt-2"><a class="text-indigo-600 text-sm" href="/magaza/{brand}">Şubeleri gör →</a></div>
                </div>
              </div>
            """)

    body = f"""
    <div class="bg-white card p-5 mb-4">
      <div class="font-semibold">Lokasyon: {city} / {dist}</div>
      <div class="text-sm text-gray-500">Markayı seç; fiyat tek, şubeler listelenir.</div>
    </div>
    <div class="grid md:grid-cols-2 gap-3">{''.join(cards)}</div>
    """
    return layout(request, body, "Mağazalar – Pazarmetre")

# =============== Marka sayfası (tek fiyat + şubeler + harita) ===============
@app.get("/magaza/{brand}", response_class=HTMLResponse)
async def brand_view(request: Request, brand: str):
    city, dist, _ = get_loc(request)
    if not city or not dist:
        return RedirectResponse("/lokasyon", status_code=302)

    # 1) TEK FİYAT
    best_html = "<div class='text-sm text-gray-500'>Bu ilçede fiyat yok.</div>"
    with get_session() as s:
        st = s.exec(select(Store).where(
            func.lower(Store.name)==brand.casefold(),
            Store.city==city, Store.district==dist
        )).first()
        if st:
            offs = s.exec(select(Offer)
                .where(Offer.store_id==st.id, Offer.approved==True)
                .order_by(Offer.price.asc(), Offer.created_at.desc())
            ).all()
            rows = only_fresh_and_latest([(o, st) for o in offs])
            if rows:
                off = rows[0][0]
                best_html = f"""
                <div class="flex items-center justify-between">
                  <div>
                    <div class="text-lg font-bold">{brand}</div>
                    <div class="text-xs text-gray-500">{city} / {dist}</div>
                  </div>
                  <div class="text-right">
                    <div class="chip bg-accent-50 text-accent-700">{off.price:.2f} {off.currency}</div>
                  </div>
                </div>"""

        # 2) ŞUBELER
        branches = s.exec(select(Branch).where(
            func.lower(Branch.brand)==brand.casefold(),
            Branch.city==city, Branch.district==dist
        )).all()

    # Sol liste
    left_list = []
    for b in branches:
        maps_q = f"{(b.address or '').replace(' ','+')},+{city}+{dist}"
        maps = f"https://www.google.com/maps/search/?api=1&query={maps_q}"
        left_list.append(f"""
          <div class="p-3 border rounded-lg">
            <div class="font-medium">{b.name}</div>
            <div class="text-sm text-gray-600">{b.address or ''}</div>
            <div class="mt-1">
              <a class="text-indigo-600 text-sm" href="{maps}" target="_blank" rel="noopener">Yol tarifi al →</a>
            </div>
            <div class="text-xs text-gray-500 mt-1" data-lat="{b.lat or ''}" data-lng="{b.lng or ''}"></div>
          </div>
        """)

    # Harita verisi
    js_data = json.dumps([
        {"name": b.name, "address": b.address, "lat": b.lat, "lng": b.lng}
        for b in branches if b.lat and b.lng
    ], ensure_ascii=False)

    leaflet_head = """
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
      <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    """

    map_js = """
    <script>
      const BR = __DATA__;
      let map, markers=[];
      function initMap(){
        const center = BR.length ? [BR[0].lat, BR[0].lng] : [40.78, 30.40];
        map = L.map('map').setView(center, 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19, attribution: '&copy; OpenStreetMap'
        }).addTo(map);
        BR.forEach(p=>{
          const m = L.marker([p.lat, p.lng]).addTo(map)
            .bindPopup(`<b>${p.name}</b><br>${p.address||''}`);
          markers.push(m);
        });
        if (markers.length > 1){
          const g = L.featureGroup(markers); map.fitBounds(g.getBounds().pad(0.2));
        }
      }
      function distKm(lat1, lon1, lat2, lon2){
        if(!lat1||!lon1||!lat2||!lon2) return null;
        const R=6371, toRad=d=>d*Math.PI/180;
        const dLat=toRad(lat2-lat1), dLon=toRad(lon2-lon1);
        const a=Math.sin(dLat/2)**2 + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)**2;
        return R*2*Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      }
      function showNearby(){
        if(!navigator.geolocation){ alert('Konum desteklenmiyor'); return; }
        navigator.geolocation.getCurrentPosition(pos=>{
          const myLat=pos.coords.latitude, myLng=pos.coords.longitude;
          if(map) map.setView([myLat,myLng], 13);
          document.querySelectorAll('[data-lat]').forEach(el=>{
            const lat=parseFloat(el.getAttribute('data-lat')), lng=parseFloat(el.getAttribute('data-lng'));
            if(!isNaN(lat) && !isNaN(lng)){
              const d=distKm(myLat,myLng,lat,lng);
              if(d) el.textContent = '📍 Size uzaklık: ~' + d.toFixed(1) + ' km';
            }
          });
        }, ()=>alert('Konum alınamadı'));
      }
      window.addEventListener('load', initMap);
    </script>
    """.replace("__DATA__", js_data)

    # --- UYARI BANDI (kısa ve net) ---
    note_html = """
    <div class="mt-2 mb-2 p-3 rounded-lg bg-amber-50 text-amber-800 text-sm">
      Ürünlerin bileşim oranlarında (ör. yağ oranı, katkılar, gramaj) markalar/şubeler arasında farklılıklar olabilir.
      Detaylar için ilgili mağazanın ürün sayfasına bakınız.
    </div>
    """

    body = f"""
    <div class="bg-white card p-6">
      {best_html}
      {note_html}
      <div class="grid md:grid-cols-2 gap-4 mt-4">
        <div>
          <div class="flex items-center justify-between mb-2">
            <div class="text-sm text-gray-600">Bu ilçedeki {brand} şubeleri</div>
            <button onclick="showNearby()" class="text-sm px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg">Yakındaki {brand}’ları göster</button>
          </div>
          <div class="space-y-2">
            {''.join(left_list) if left_list else "<div class='text-sm text-gray-500'>Şube bulunamadı.</div>"}
          </div>
        </div>
        <div>
          <div id="map" style="height:520px;border-radius:14px;overflow:hidden;border:1px solid #eee"></div>
        </div>
      </div>
    </div>
    {map_js}
    """

    html = layout(request, body, f"{brand} – Şubeler & Fiyat").body.decode("utf-8")
    html = html.replace("</head>", f"{leaflet_head}\n</head>")
    return HTMLResponse(html)

# =============== Admin ===========================
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    body = """
    <div class="bg-white card p-6 max-w-md mx-auto">
      <h2 class="text-xl font-bold mb-3">Admin Giriş</h2>
      <form method="post" action="/admin/login" class="space-y-3">
        <input class="w-full border rounded-lg p-2" type="password" name="password" placeholder="Şifre" required>
        <button class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg">Giriş</button>
      </form>
    </div>"""
    return layout(request, body, "Admin Giriş")

@app.post("/admin/login")
async def admin_login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        resp = RedirectResponse("/admin", status_code=302)
        resp.set_cookie("adm", ADMIN_PASSWORD, httponly=True, samesite="lax")
        return resp
    return PlainTextResponse("Hatalı şifre", status_code=401)

@app.get("/admin/logout")
async def admin_logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("adm")
    return resp
@app.get("/admin/fiyat-uyari", response_class=HTMLResponse)
async def admin_fiyat_uyari(request: Request):
    red = require_admin(request)
    if red:
        return red

    with get_session() as s:
        rows = s.exec(
            select(Offer, Product, Store)
            .join(Product, Offer.product_id == Product.id)
            .join(Store, Offer.store_id == Store.id)
            .where(Offer.source_mismatch == True)
            .order_by(Offer.source_checked_at.desc())
        ).all()

    if not rows:
        body = "<div class='bg-white card p-6'>Kaynağı değişmiş fiyat yok.</div>"
        return layout(request, body, "Fiyat Uyarıları")

    lis = []
    for off, prod, st in rows:
        lis.append(f"""
        <tr class="border-b">
          <td class="py-2">{prod.name}</td>
          <td class="py-2">{st.name} – {st.city}/{st.district}</td>
          <td class="py-2 text-right">{off.price:.2f} TL (senin)</td>
          <td class="py-2 text-right">{(off.source_price or 0):.2f} TL (kaynak)</td>
          <td class="py-2 text-xs text-gray-500">{off.source_checked_at or ''}</td>
          <td class="py-2 text-xs max-w-[220px] truncate">
            <a class="text-indigo-600 underline" href="{off.source_url}" target="_blank" rel="noopener">Kaynağı aç</a>
          </td>
        </tr>
        """)

    body = f"""
    <div class="bg-white card p-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-bold">Kaynağı değişmiş fiyatlar</h2>
        <a href="/admin" class="text-sm text-gray-500">← Admin</a>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b">
              <th>Ürün</th>
              <th>Mağaza</th>
              <th>Senin Fiyat</th>
              <th>Kaynak Fiyat</th>
              <th>Kontrol</th>
              <th>Kaynak URL</th>
            </tr>
          </thead>
          <tbody>
            {''.join(lis)}
          </tbody>
        </table>
      </div>
    </div>
    """
    return layout(request, body, "Fiyat Uyarıları")
@app.get("/admin", response_class=HTMLResponse)
async def admin_step1(request: Request):
    red = require_admin(request)
    if red:
        return red

    with get_session() as s:
        try:
            bad_count = (
                s.exec(
                    select(func.count())
                    .select_from(Offer)
                    .where((Offer.source_mismatch == True) | (Offer.source_mismatch == 1))
                ).one()
                or 0
            )
        except Exception as e:
            print("WARN /admin bad_count:", e)
            bad_count = 0

        try:
            now = datetime.utcnow()
            today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
            yesterday_start = today_start - timedelta(days=1)

            # SQLite'da ts TEXT olarak saklandigindan string'e ceviriyoruz
            # Format: 'YYYY-MM-DD HH:MM:SS' (bosluk ile, T degil)
            today_start_str = today_start.strftime('%Y-%m-%d %H:%M:%S')
            yesterday_start_str = yesterday_start.strftime('%Y-%m-%d %H:%M:%S')

            # Bugunku ziyaret sayisi
            today_visits = s.exec(
                select(func.count()).select_from(Visit).where(Visit.ts >= today_start_str)
            ).one() or 0

            # Dunku ziyaret sayisi
            yesterday_visits = s.exec(
                select(func.count()).select_from(Visit)
                .where(Visit.ts >= yesterday_start_str)
                .where(Visit.ts < today_start_str)
            ).one() or 0

            # Toplam ziyaret sayisi
            total_visits = s.exec(
                select(func.count()).select_from(Visit)
            ).one() or 0

        except Exception as e:
            print("WARN /admin stats:", e)
            traceback.print_exc()
            today_visits = yesterday_visits = total_visits = 0

    warn_html = ""
    if bad_count:
        warn_html = f"""
        <div class="mb-4 p-3 rounded-lg bg-amber-50 text-amber-800 text-sm">
          ⚠️ Kaynağı değişmiş <b>{bad_count}</b> fiyat var.
          <a class="underline" href="/admin/fiyat-uyari">Listeyi gör</a>
        </div>
        """

    # Tarih gösterimi için
    today_date = now.strftime('%d.%m.%Y')
    yesterday_date = (now - timedelta(days=1)).strftime('%d.%m.%Y')

    body = f"""
    <div class="max-w-6xl mx-auto">
      <div class="mb-6 bg-white card p-6">
        <h2 class="text-2xl font-bold mb-4">Admin Paneli</h2>
        
        <div class="grid grid-cols-3 gap-3 mb-6">
          <div class="p-3 rounded-lg bg-emerald-50 text-center">
            <div class="text-xs text-emerald-600 font-medium">Bugünkü Ziyaret</div>
            <div class="text-xs text-gray-500 mt-1">{today_date}</div>
            <div class="text-2xl font-bold text-emerald-700 mt-1">{today_visits:,}</div>
          </div>
          <div class="p-3 rounded-lg bg-blue-50 text-center">
            <div class="text-xs text-blue-600 font-medium">Dünkü Ziyaret</div>
            <div class="text-xs text-gray-500 mt-1">{yesterday_date}</div>
            <div class="text-2xl font-bold text-blue-700 mt-1">{yesterday_visits:,}</div>
          </div>
          <div class="p-3 rounded-lg bg-indigo-50 text-center">
            <div class="text-xs text-indigo-600 font-medium">Toplam Ziyaret</div>
            <div class="text-xs text-gray-500 mt-1">Tüm zamanlar</div>
            <div class="text-2xl font-bold text-indigo-700 mt-1">{total_visits:,}</div>
          </div>
        </div>

        {warn_html}
        
        <div class="grid md:grid-cols-2 gap-4 mb-6">
          <div class="p-4 border rounded-lg hover:shadow-lg transition">
            <h3 class="font-bold text-lg mb-2">🏪 Ürün Yönetimi</h3>
            <p class="text-sm text-gray-600 mb-3">Master Product List - Tüm ürünleri yönetin</p>
            <div class="flex gap-2">
              <a href="/admin/products" class="text-sm bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg">
                Ürünler
              </a>
              <a href="/admin/product/add" class="text-sm border border-gray-300 hover:bg-gray-50 px-4 py-2 rounded-lg">
                + Yeni Ürün
              </a>
              <a href="/admin/product/suggestions" class="text-sm bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-lg">
                📋 Öneriler
              </a>
            </div>
          </div>
          
          <div class="p-4 border rounded-lg hover:shadow-lg transition">
            <h3 class="font-bold text-lg mb-2">🏢 İşletme Yönetimi</h3>
            <p class="text-sm text-gray-600 mb-3">İşletme kayıtlarını onaylayın ve yönetin</p>
            <div class="flex gap-2">
              <a href="/admin/businesses" class="text-sm bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg">
                İşletmeler
              </a>
            </div>
          </div>
          
          <div class="p-4 border rounded-lg hover:shadow-lg transition">
            <h3 class="font-bold text-lg mb-2">🌱 Seed & Setup</h3>
            <p class="text-sm text-gray-600 mb-3">Temel verileri yükleyin</p>
            <div class="flex gap-2">
              <a href="/admin/seed/products" class="text-sm bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg">
                Ürünleri Yükle
              </a>
              <a href="/admin/seed" class="text-sm border border-gray-300 hover:bg-gray-50 px-4 py-2 rounded-lg">
                Şubeleri Yükle
              </a>
            </div>
          </div>
          
          <div class="p-4 border rounded-lg hover:shadow-lg transition">
            <h3 class="font-bold text-lg mb-2">📊 Raporlar & İstatistikler</h3>
            <p class="text-sm text-gray-600 mb-3">Ziyaretçi istatistikleri ve raporlar</p>
            <div class="flex gap-2">
              <a href="/admin/stats" class="text-sm bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg">
                İstatistikler
              </a>
            </div>
          </div>
        </div>
        
        <div class="border-t pt-4">
          <h2 class="text-lg font-bold mb-3">Manuel Fiyat Girişi</h2>
          <form method="get" action="/admin/bulk" class="space-y-3">
            <input class="w-full border rounded-lg p-2" name="store_name"
                   placeholder="Örn: Migros Hendek, Kutsallar Kasap" required>
            <label class="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" name="featured" value="1"> Eklenen ürünleri vitrine ekle
            </label>
            <button class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg">
              Fiyat Gir
            </button>
          </form>
          <p class="text-xs text-gray-500 mt-2">
            Manuel olarak fiyat girişi yapmak için mağaza adını girin.
          </p>
        </div>
      </div>
    </div>
    """
    return layout(request, body, "Admin – Adım 1")
@app.get("/admin/bulk", response_class=HTMLResponse)
async def admin_bulk_form(request: Request, store_name: str, featured: str = "0"):
    red = require_admin(request)
    if red:
        return red
    city, dist, nb = get_loc(request)
    feat_flag = 1 if str(featured).lower() in ("1", "on", "true", "yes") else 0
    rows = "".join([_row() for _ in range(5)])

    addrow_script = """
    <script>
      function addRow(){
        const c = document.getElementById('rows');
        const w = document.createElement('div');
        w.innerHTML = "__ROW__";
        c.appendChild(w.firstElementChild);
      }
    </script>
    """.replace("__ROW__", _row_js())

    loc_line = f"{city or '-'} / {dist or '-'}" + (f" / {nb}" if nb else "")

    # İlçe checkbox’ları
    districts = [d["name"] for d in LOC_JSON["provinces"][0]["districts"]]
    checks = []
    for dname in districts:
        checked = "checked" if (dist and dname.lower() == (dist or "").lower()) else ""
        checks.append(
            f"<label class='inline-flex items-center gap-2 mr-3 mb-2'>"
            f"<input type='checkbox' name='districts' value='{dname}' {checked}> {dname}"
            f"</label>"
        )
    checks_html = "".join(checks)
    all_toggle_js = """
      <script>
        function toggleAllDistricts(chk){
          document.querySelectorAll('input[name="districts"]').forEach(c=> c.checked = chk.checked);
        }
      </script>
    """

    body = f"""
    <div class="bg-white card p-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-bold">2) Çoklu Satır (Ürün / Fiyat / Adres)</h2>
        <a class="text-sm text-gray-600" href="/admin">Geri</a>
      </div>
      <div class="text-xs text-gray-600 mb-3">
        Öneri: Ürün adını net yazın (örn: <b>Dana kıyma</b>, <b>Dana kuşbaşı</b>, <b>Piliç bonfile</b>).
      </div>
      <form method="post" action="/admin/bulk" id="bulkform">
        <input type="hidden" name="featured" value="{feat_flag}">
        <div class="text-sm text-gray-600 mb-2">Seçili lokasyon: <b>{loc_line}</b></div>

        <div class="mt-2 p-3 border rounded-lg">
          <div class="text-sm font-medium mb-2">Hangi ilçelere uygula?</div>
          <div class="flex flex-wrap">
            {checks_html}
          </div>
          <label class="inline-flex items-center gap-2 mt-2 block text-sm">
            <input type="checkbox" onclick="toggleAllDistricts(this)"> Tüm ilçeleri seç
          </label>
        </div>

        <div class="mt-3">
          <label class="block text-sm font-medium mb-1">Mağaza adı</label>
          <input class="border rounded-lg p-2 w-full"
                 name="store_name_single"
                 value="{store_name}"
                 placeholder="Örn: Migros Hendek, Kutsallar Kasap"
                 required>
          <p class="text-xs text-gray-500 mt-1">
            Aşağıdaki tüm ürünler bu mağazaya kaydedilir.
          </p>
        </div>

        <div id="rows" class="space-y-2 mt-3">{rows}</div>
        <div class="mt-3 flex items-center gap-2">
          <button type="button" onclick="addRow()" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg">Satır Ekle</button>
          <button class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg">Kaydet</button>
        </div>
      </form>
    </div>
    {addrow_script}
    {all_toggle_js}
    """
    return layout(request, body, "Admin – Adım 2")

def _row():
    return """
    <div class="grid md:grid-cols-7 gap-2">
      <input class="border rounded-lg p-2" name="product_name" placeholder="Ürün adı (örn: Dana kıyma)">
      <input class="border rounded-lg p-2" name="price" placeholder="Fiyat">
      <select class="border rounded-lg p-2 text-sm" name="unit">
        <option value="kg" selected>kg</option>
        <option value="adet">adet</option>
        <option value="litre">litre</option>
      </select>
      <input class="border rounded-lg p-2" name="store_address" placeholder="Market adresi (opsiyonel)">
      <input class="border rounded-lg p-2" name="source_url" placeholder="Kaynak URL (opsiyonel)">
      <input class="border rounded-lg p-2" name="source_weight_g" placeholder="Orijinal gram (örn: 400)">
      <select class="border rounded-lg p-2 text-sm" name="category">
        <option value="">Tür</option>
        <option value="tavuk">Tavuk</option>
        <option value="et">Et</option>
        <option value="diger">Diger</option>
      </select>
    </div>"""

def _row_js():
    return _row().replace('"', '\\"').replace("\n", "")

@app.post("/admin/bulk", response_class=HTMLResponse)
async def admin_bulk_save(
    request: Request,
    store_name_single: str = Form(...),
    featured: int = Form(0),
    product_name: List[str] = Form([]),
    price: List[str] = Form([]),
    unit: List[str] = Form([]),
    store_address: List[str] = Form([]),
    source_url: List[str] = Form([]),
    category: List[str] = Form([]),
    source_weight_g: List[str] = Form([]),
    source_unit: List[str] = Form([]),
    districts: List[str] = Form([]),
):
    red = require_admin(request)
    if red:
        return red

    city, dist, nb = get_loc(request)
    if not city or not dist:
        return RedirectResponse("/lokasyon", status_code=302)

    store_label = (store_name_single or "").strip()
    if not store_label:
        return layout(
            request,
            "<div class='bg-white card p-4 text-amber-800 bg-amber-50'>Mağaza adı zorunlu.</div>",
            "Admin – Kayıt",
        )

     # SATIRLARI ÜRÜN + FİYAT OLARAK TOPLA
    # (ürün adı, fiyat, birim, adres, url, gram, unit, kategori)
    entries: List[Tuple[str, float, str, str, str, float | None, str | None, str | None]] = []

    for pn, pr, un, addr, src, sw_raw, su_raw, cat in zip_longest(
        product_name,
        price,
        unit,
        store_address,
        source_url,
        source_weight_g,
        source_unit,
        category,
        fillvalue="",
    ):
        pn = (pn or "").strip()
        pr = (pr or "").strip()
        un = (un or "kg").strip().lower()  # varsayılan: kg
        addr = (addr or "").strip()
        src = (src or "").strip()
        sw_raw = (sw_raw or "").strip()
        su_raw = (su_raw or "").strip()
        cat = (cat or "").strip().lower()

        # geçersiz birim → kg
        if un not in ("kg", "adet", "litre"):
            un = "kg"

        # geçersiz kategori → None
        if cat not in ("et", "tavuk","diger"):
            cat = None

        if not (pn and pr):
            continue

        try:
            pv = float(pr.replace(",", "."))
        except ValueError:
            continue

        sw: float | None = None
        if sw_raw:
            try:
                sw = float(sw_raw)
            except ValueError:
                sw = None

        su: str | None = su_raw or None

        entries.append((pn, pv, un, addr, src, sw, su, cat))

    if not entries:
        return layout(
            request,
            "<div class='bg-white card p-4 text-amber-800 bg-amber-50'>Geçerli satır yok (Ürün + Fiyat zorunlu).</div>",
            "Admin – Kayıt",
        )

    BRAND_CANON = {"migros": "Migros", "a101": "A101", "bim": "BİM"}

    store_key = store_label.casefold()
    store_clean = BRAND_CANON.get(store_key, store_label)

    with get_session() as s:
        # Hedef ilçeler: tiklenenler, yoksa seçili ilçe
        target_districts = [d for d in (districts or []) if d] or [dist]

        for target_dist in target_districts:
            # İLÇE BAŞINA TEK KANONİK MAĞAZA
            st = s.exec(
                select(Store).where(
                    func.lower(Store.name) == store_clean.casefold(),
                    Store.city == city,
                    Store.district == target_dist,
                    Store.neighborhood == None,
                )
            ).first()

            if not st:
                # varsa ilk dolu adresi mağazaya yaz
                first_addr = next(
                    (addr for _pn, _pv, _un, addr, _src, _sw, _su, _cat in entries if addr),
                    None,
                )
                st = Store(
                    name=store_clean,
                    address=first_addr,
                    city=city,
                    district=target_dist,
                    neighborhood=None,
                )
                s.add(st)
                s.commit()
                s.refresh(st)

            # HER SATIR İÇİN: ÜRÜN BUL/OLUŞTUR → BU MAĞAZAYA FİYAT YAZ
            for pn, pv, un, addr, src, sw, su, cat in entries:
                p = s.exec(select(Product).where(Product.name == pn)).first()
                if not p:
                    # yeni ürün: kategori ve birim ile birlikte oluştur
                    p = Product(
                        name=pn,
                        unit=un,
                        featured=bool(featured),
                        category=cat,
                    )
                    s.add(p)
                    s.commit()
                    s.refresh(p)
                else:
                    # mevcut ürün: gerekiyorsa featured / category / unit güncelle
                    updated = False
                    if featured and not p.featured:
                        p.featured = True
                        updated = True
                    if cat and not p.category:
                        p.category = cat
                        updated = True
                    if un and p.unit != un:
                        p.unit = un
                        updated = True
                    if updated:
                        s.add(p)
                        s.commit()

                off = Offer(
                    product_id=p.id,
                    store_id=st.id,
                    price=pv,
                    quantity=1.0,
                    currency="TRY",
                    approved=True,
                    source_url=(src or None),
                    source_weight_g=sw,
                    source_unit=su,
                    branch_address=(addr or None),
                )
                s.add(off)

        s.commit()

    return RedirectResponse("/", status_code=302)

# =============== Hukuki Bilgilendirme ===============
@app.get("/hukuk", response_class=HTMLResponse)
async def hukuk(request: Request):
    body = """
    <div class="max-w-4xl mx-auto bg-white p-6 rounded-xl shadow">
      <h1 class="text-2xl font-bold mb-6 text-center">Hukuki Bilgilendirme</h1>

      <div class="text-center text-xs text-gray-500 mb-6">
        Yayın Tarihi: 01.11.2025 · Son Güncelleme: 01.11.2025
      </div>

      <div class="tabs flex gap-4 mb-4 border-b overflow-x-auto">
        <button class="tab active" onclick="showTab('gizlilik')">🔒 Gizlilik Politikası</button>
        <button class="tab" onclick="showTab('kullanim')">⚖️ Kullanım Koşulları</button>
        <button class="tab" onclick="showTab('sorumluluk')">🧾 Sorumluluk Reddi</button>
        <button class="tab" onclick="showTab('kaynak')">📊 Veri Kaynağı</button>
      </div>

      <!-- GİZLİLİK -->
      <div id="gizlilik" class="tab-content">
        <h2 class="text-xl font-semibold mb-2">Gizlilik Politikası</h2>
        <p class="text-gray-700 mb-3">
          Pazarmetre, kullanıcılarından doğrudan isim, T.C. kimlik no vb. hassas kişisel veri talep etmez.
          Sitemizdeki fiyatlar; kamuya açık market siteleri ve yerel işletmelerin bildirdiği fiyatlardan derlenir.
        </p>
        <p class="text-gray-700 mb-3">
          Ziyaretiniz sırasında sistem güvenliği ve istatistik amaçlı olarak IP adresiniz (karma / hash’lenmiş şekilde),
          tarayıcı bilgisi ve ziyaret ettiğiniz sayfa yolu kaydedilebilir. Bu veriler kimliğinizi doğrudan belirlemeye
          yönelik kullanılmaz ve üçüncü kişilerle pazarlama amacıyla paylaşılmaz.
        </p>
        <p class="text-gray-700 mb-2">
          Kullanılan çerezler ve benzeri teknolojiler hakkında detay için
          <a href="/cerez-politikasi" class="text-indigo-600 underline">Çerez Politikası</a>’nı,
          kişisel verilerin işlenmesine ilişkin detaylar için
          <a href="/kvkk-aydinlatma" class="text-indigo-600 underline">KVKK Aydınlatma Metni</a>’ni inceleyebilirsiniz.
        </p>
        <p class="text-gray-700">
          📧 İletişim:
          <a href="mailto:pazarmetre1@gmail.com" class="text-indigo-600 underline">pazarmetre1@gmail.com</a>
        </p>
      </div>

      <!-- KULLANIM KOŞULLARI -->
      <div id="kullanim" class="tab-content hidden">
        <h2 class="text-xl font-semibold mb-2">Kullanım Koşulları</h2>
        <p class="text-gray-700 mb-2">
          Pazarmetre’de yer alan fiyat bilgileri iki ana kaynaktan derlenir:
        </p>
        <ul class="list-disc ml-5 text-gray-700">
          <li>Resmî marketlerin web siteleri (Migros, BİM, A101 vb.)</li>
          <li>Yerel kasap, şarküteri veya tedarikçilerin kendi beyan ettikleri fiyatlar</li>
        </ul>
        <p class="text-gray-700 mt-3">
          Fiyatlar bilgilendirme amaçlıdır; doğruluk ve güncellikten doğabilecek farklılıklardan Pazarmetre sorumlu değildir.
          Kullanıcı, fiyatın geçerliliğini ilgili işletmeden teyit etmekle yükümlüdür.
        </p>
      </div>

      <!-- SORUMLULUK REDDİ -->
      <div id="sorumluluk" class="tab-content hidden">
        <h2 class="text-xl font-semibold mb-2">Sorumluluk Reddi</h2>
        <p class="text-gray-700 mb-3">
          Pazarmetre’de gösterilen fiyatlar işletmelerin kendi beyanlarına dayanmaktadır.
          Bu fiyatlar sözlü (telefon) veya yazılı (e-posta, WhatsApp vb.) yollarla alınabilir.
        </p>
        <p class="text-gray-700 mb-3">
          Pazarmetre yalnızca bilgilendirme sağlar, satış veya ticari temsilcilik yapmaz.
          Fiyat değişikliklerinden veya üçüncü taraf sitelerdeki hatalardan sorumlu değildir.
        </p>
      </div>

      <!-- VERİ KAYNAĞI -->
      <div id="kaynak" class="tab-content hidden">
        <h2 class="text-xl font-semibold mb-2">Veri Kaynağı</h2>
        <p class="text-gray-700 mb-3">
          Pazarmetre’deki fiyat verileri şu kaynaklardan derlenmektedir:
        </p>
        <ul class="list-disc ml-5 text-gray-700">
          <li>Market zincirlerinin resmî internet siteleri</li>
          <li>Yerel işletmelerin günlük veya haftalık olarak paylaştığı fiyat bilgileri</li>
          <li>Telefon veya mesaj yoluyla bildirilen fiyatlar (işletme beyanı)</li>
        </ul>
        <p class="text-gray-700 mt-3">
          Soru, düzeltme veya kaldırma talepleri için
          <a href="mailto:pazarmetre1@gmail.com" class="text-indigo-600 underline">pazarmetre1@gmail.com</a>
          adresine ulaşabilirsiniz.
        </p>
      </div>

      <style>
        .tab {
          padding: 8px 14px;
          border-bottom: 2px solid transparent;
          font-weight: 500;
          color: #475569;
          white-space: nowrap;
        }
        .tab.active {
          border-color: #4f46e5;
          color: #1e1b4b;
        }
        .tab:hover { color: #312e81; }
        .hidden { display: none; }
      </style>

      <script>
        function showTab(id) {
          document.querySelectorAll('.tab').forEach(btn => btn.classList.remove('active'));
          document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
          const btn = document.querySelector(`.tab[onclick="showTab('${id}')"]`);
          if (btn) btn.classList.add('active');
          const el = document.getElementById(id);
          if (el) el.classList.remove('hidden');
        }
      </script>
    </div>
    """
    return layout(request, body, "Pazarmetre – Hukuki Bilgilendirme")
@app.get("/iletisim", response_class=HTMLResponse)
async def iletisim(request: Request):
    # en üstte tanımladığımız değişkenleri kullanıyorsan:
    email = "pazarmetre1@gmail.com"

    body = f"""
    <div class="max-w-lg mx-auto bg-white p-6 rounded-xl shadow">
      <h1 class="text-2xl font-bold mb-4">İletişim</h1>
      <p class="text-gray-700 mb-4">
        Fiyat bildirmek, iş birliği yapmak veya hata bildirmek için bize ulaşabilirsiniz.
      </p>
      <ul class="space-y-2 text-gray-800">
        <li>📧 Bilgi / İletişim: <a href="mailto:{email}" class="text-indigo-600 underline">{email}</a></li>
      </ul>
      <p class="text-xs text-gray-500 mt-6">
        Gönderilen bilgiler yalnızca iletişim amacıyla kullanılacaktır.
      </p>
    </div>
    """
    return layout(request, body, "Pazarmetre – İletişim")
@app.get("/cerez-politikasi", response_class=HTMLResponse)
async def cerez_politikasi(request: Request):
    body = """
    <div class="max-w-4xl mx-auto bg-white p-6 rounded-xl shadow">
      <h1 class="text-2xl font-bold mb-4">Çerez Politikası</h1>

      <p class="text-gray-700 mb-3">
        Bu Çerez Politikası, Pazarmetre (<b>pazarmetre.com.tr</b>) web sitesini ziyaret ettiğinizde
        kullanılan çerezler ve benzeri teknolojiler hakkında sizi bilgilendirmek amacıyla hazırlanmıştır.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">1. Çerez Nedir?</h2>
      <p class="text-gray-700 mb-3">
        Çerezler, bir web sitesini ziyaret ettiğinizde tarayıcınıza kaydedilen küçük metin dosyalarıdır.
        Ziyaret deneyiminizi iyileştirmek, tercihlerinizi hatırlamak ve istatistik üretmek için kullanılır.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">2. Hangi Çerezleri Kullanıyoruz?</h2>
      <ul class="list-disc ml-6 text-gray-700 mb-3">
        <li><b>Zorunlu çerezler:</b> Lokasyon seçiminizi (il, ilçe, mahalle) hatırlamak için kullanılan
            ve site işleyişi için gerekli olan çerezler.</li>
        <li><b>Admin / Üye çerezleri:</b> Yönetim paneline giriş yaptığınızda oturumunuzu doğrulamak için
            kullanılan çerezler.</li>
        <li><b>Teknik kayıtlar:</b> Ziyaret istatistikleri için IP adresiniz, tarayıcı bilginiz ve
            ziyaret ettiğiniz sayfa bilgisi, <b>anonimleştirilmiş/karma (hash)</b> şekilde saklanır.
            Bu kayıtlar kimliğinizi belirlemeye yönelik değildir.</li>
      </ul>

      <p class="text-gray-700 mb-3">
        Pazarmetre şu anda reklam veya üçüncü taraf pazarlama amaçlı çerez kullanmamaktadır.
        Kullanılması durumunda bu politika güncellenecektir.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">3. Üçüncü Taraf Hizmetler</h2>
      <p class="text-gray-700 mb-3">
        Hizmet sürekliliğini izlemek için uptime/izleme servisleri kullanılabilir.
        Bu servisler, sitenin çalışıp çalışmadığını kontrol etmek için teknik istekte bulunabilir.
        Kişisel verileriniz pazarlama amacıyla paylaşılmaz.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">4. Çerezleri Nasıl Kontrol Edebilirsiniz?</h2>
      <p class="text-gray-700 mb-3">
        Çoğu tarayıcı, çerezleri kabul etme, reddetme veya mevcut çerezleri silme imkanı sunar.
        Tarayıcınızın ayarlar bölümünden çerez tercihlerinizi dilediğiniz zaman değiştirebilirsiniz.
        Zorunlu çerezleri devre dışı bırakmanız, sitenin düzgün çalışmamasına neden olabilir.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">5. İletişim</h2>
      <p class="text-gray-700">
        Çerezler ve kişisel verilerle ilgili sorularınız için
        <a href="mailto:pazarmetre1@gmail.com" class="text-indigo-600 underline">pazarmetre1@gmail.com</a>
        adresinden bizimle iletişime geçebilirsiniz.
      </p>
    </div>
    """
    return layout(request, body, "Pazarmetre – Çerez Politikası")
@app.get("/kvkk-aydinlatma", response_class=HTMLResponse)
async def kvkk_aydinlatma(request: Request):
    body = f"""
    <div class="max-w-4xl mx-auto bg-white p-6 rounded-xl shadow">
      <h1 class="text-2xl font-bold mb-4">Kişisel Verilerin Korunması Hakkında Aydınlatma Metni</h1>

      <p class="text-gray-700 mb-3">
        Bu metin, 6698 sayılı Kişisel Verilerin Korunması Kanunu ("KVKK") uyarınca,
        Pazarmetre tarafından işlenen kişisel verilere ilişkin bilgilendirme amacıyla hazırlanmıştır.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">1. Veri Sorumlusu</h2>
      <p class="text-gray-700 mb-3">
        Veri Sorumlusu: Pazarmetre<br>
        İletişim: <a href="mailto:pazarmetre1@gmail.com" class="text-indigo-600 underline">pazarmetre1@gmail.com</a>
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">2. İşlenen Kişisel Veriler</h2>
      <ul class="list-disc ml-6 text-gray-700 mb-3">
        <li>IP adresi (istatistik amaçlı, <b>hash</b>’lenmiş şekilde)</li>
        <li>Tarayıcı ve cihaz bilgisi (user-agent)</li>
        <li>Ziyaret edilen sayfa bilgisi (URL yolu)</li>
        <li>Lokasyon tercihi çerezleri (il / ilçe / mahalle seçimi)</li>
        <li>Admin paneli oturum bilgisi (sadece yetkili kullanıcı için)</li>
      </ul>

      <h2 class="text-lg font-semibold mt-4 mb-2">3. Kişisel Verilerin İşlenme Amaçları</h2>
      <ul class="list-disc ml-6 text-gray-700 mb-3">
        <li>Web sitesinin güvenliğinin sağlanması</li>
        <li>Hizmet sürekliliğinin ve performansının izlenmesi</li>
        <li>İçerik ve lokasyon bazlı gösterimlerin çalışması</li>
        <li>Kötüye kullanım ve saldırı girişimlerinin tespiti</li>
      </ul>

      <h2 class="text-lg font-semibold mt-4 mb-2">4. Hukuki Sebep</h2>
      <p class="text-gray-700 mb-3">
        Veriler, KVKK m.5/2 (f) uyarınca <b>meşru menfaat</b> kapsamında ve m.5/2 (c) uyarınca
        hizmetin sunulması için zorunlu olduğu ölçüde işlenmektedir.
        Pazarlama amaçlı profil çıkarımı yapılmamaktadır.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">5. Saklama Süresi</h2>
      <p class="text-gray-700 mb-3">
        Teknik erişim kayıtları ve ziyaret istatistikleri, güvenlik ve raporlama amaçlarıyla makul süreyle
        saklanır; ihtiyaç kalmadığında silinir veya anonim hale getirilir.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">6. Verilerin Aktarılması</h2>
      <p class="text-gray-700 mb-3">
        Veriler, yalnızca hizmet aldığımız barındırma/altyapı sağlayıcıları ve yasal zorunluluk halleri dışında
        üçüncü kişilere aktarılmaz.
      </p>

      <h2 class="text-lg font-semibold mt-4 mb-2">7. KVKK Kapsamındaki Haklarınız</h2>
      <p class="text-gray-700 mb-3">
        KVKK m.11 kapsamında; verilerinize erişme, düzeltilmesini veya silinmesini talep etme,
        işlenmesine itiraz etme gibi haklara sahipsiniz.
        Talepleriniz için <a href="mailto:pazarmetre1@gmail.com" class="text-indigo-600 underline">
        pazarmetre1@gmail.com</a> adresine yazabilirsiniz.
      </p>
    </div>
    """
    return layout(request, body, "Pazarmetre – KVKK Aydınlatma Metni")

# ---- Teklif Sil (Admin) ----
@app.post("/admin/del")
async def admin_delete_offer(
    request: Request,
    offer_id: int = Form(...),
    scope: str = Form("local"),
):
    red = require_admin(request)
    if red:
        return red

    scope = (scope or "local").lower().strip()

    with get_session() as s:
        off = s.get(Offer, offer_id)
        if not off:
            return PlainTextResponse("NOT_FOUND", status_code=404)

        # 🔹 SADECE BU İLÇE
        if scope == "local":
            s.delete(off)
            s.commit()
            return PlainTextResponse("OK")

        # 🔹 BÜTÜN İLÇELER
        if scope == "all":
            st = s.get(Store, off.store_id)
            if not st:
                # güvenli fallback
                s.delete(off)
                s.commit()
                return PlainTextResponse("OK")

            store_name = (st.name or "").strip()
            city = st.city

            # aynı şehir + aynı mağaza adı
            store_ids = s.exec(
                select(Store.id).where(
                    Store.city == city,
                    func.lower(Store.name) == store_name.casefold(),
                )
            ).all()

            store_ids = [
                x[0] if isinstance(x, tuple) else x
                for x in store_ids
            ]

            if store_ids:
                offers = s.exec(
                    select(Offer).where(
                        Offer.product_id == off.product_id,
                        Offer.store_id.in_(store_ids),
                    )
                ).all()

                for o in offers:
                    s.delete(o)

                s.commit()
                return PlainTextResponse("OK")

        return PlainTextResponse("INVALID_SCOPE", status_code=400)
# ---- Teklif Güncelle (Admin) ----
@app.post("/admin/edit")
async def admin_edit_offer(
    request: Request,
    offer_id: int = Form(...),
    price: str = Form(...),
    source_url: str = Form(""),
    branch_address: str = Form(""),
    scope: str = Form("local"),   # <-- EKLENDİ
):
    red = require_admin(request)
    if red:
        return red

    # price'ı float'a çevir (senin sistem nasıl tutuyorsa ona göre)
    try:
        new_price = float(str(price).replace(",", ".").strip())
    except:
        return PlainTextResponse("bad price", status_code=400)

    with get_session() as s:
        off = s.get(Offer, offer_id)
        if not off:
            return PlainTextResponse("not found", status_code=404)

        if scope == "all":
            # Aynı ürün + aynı market adı (tüm ilçeler)
            st = s.get(Store, off.store_id)
            if not st:
                return PlainTextResponse("store not found", status_code=404)

            store_name = st.name
            product_id = off.product_id

            q = (
                select(Offer)
                .join(Store, Store.id == Offer.store_id)
                .where(Offer.product_id == product_id)
                .where(Store.name == store_name)
            )
            offers = s.exec(q).all()

            for o in offers:
                o.price = new_price
                o.source_url = source_url
                o.branch_address = branch_address

            s.commit()
            return PlainTextResponse("OK")

        # local (sadece bu ilçe)
        off.price = new_price
        off.source_url = source_url
        off.branch_address = branch_address
        s.commit()
        return PlainTextResponse("OK")
# ---- Admin Stats (ziyaretler) ----
@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(request: Request):
    red = require_admin(request)
    if red:
        return red

    now = datetime.utcnow()
    since_30 = now - timedelta(days=30)
    since_1 = now - timedelta(days=1)

    with get_session() as s:
        # Sayılar tek int olarak
        total  = s.exec(select(func.count()).select_from(Visit)).one()[0]
        last24 = s.exec(select(func.count()).where(Visit.ts >= since_1)).one()[0]
        uniq30 = s.exec(
            select(func.count(func.distinct(Visit.ip_hash))).where(Visit.ts >= since_30)
        ).one()[0]

        # Günlük özet (30 gün)
        daily = s.exec(
            select(
                func.date(Visit.ts).label("d"),
                func.count().label("pv"),
                func.count(func.distinct(Visit.ip_hash)).label("uv"),
            )
            .where(Visit.ts >= since_30)
            .group_by(func.date(Visit.ts))
            .order_by(func.date(Visit.ts).desc())
        ).all()

        # En çok görüntülenen path'ler (30 gün)
        top_paths = s.exec(
            select(Visit.path, func.count().label("c"))
            .where(Visit.ts >= since_30)
            .group_by(Visit.path)
            .order_by(func.count().desc())
            .limit(10)
        ).all()

    daily_rows = "".join(
        f"<tr class='border-b'><td class='py-1'>{d}</td>"
        f"<td class='py-1 text-right'>{pv}</td>"
        f"<td class='py-1 text-right'>{uv}</td></tr>"
        for d, pv, uv in daily
    )
    top_rows = "".join(
        f"<tr class='border-b'><td class='py-1'>{p}</td>"
        f"<td class='py-1 text-right'>{c}</td></tr>"
        for p, c in top_paths
    )

    body = f"""
    <div class="bg-white card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="text-lg font-bold">Ziyaret İstatistikleri</div>
        <a class="text-sm text-gray-600" href="/admin">← Admin</a>
      </div>
      <div class="grid md:grid-cols-3 gap-3 mb-4">
        <div class="p-3 rounded-lg bg-gray-50">
          <div class="text-xs text-gray-500">Toplam Sayfa Görüntüleme</div>
          <div class="text-2xl font-bold">{total}</div>
        </div>
        <div class="p-3 rounded-lg bg-gray-50">
          <div class="text-xs text-gray-500">Son 24 Saat</div>
          <div class="text-2xl font-bold">{last24}</div>
        </div>
        <div class="p-3 rounded-lg bg-gray-50">
          <div class="text-xs text-gray-500">Son 30 günde Tekil Ziyaretçi</div>
          <div class="text-2xl font-bold">{uniq30}</div>
        </div>
      </div>

      <div class="grid md:grid-cols-2 gap-6">
        <div>
          <div class="font-medium mb-2">Günlük (30 gün)</div>
          <div class="overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead><tr class="text-left text-gray-500"><th>Tarih (UTC)</th><th class="text-right">PV</th><th class="text-right">UV</th></tr></thead>
              <tbody>{daily_rows or "<tr><td colspan='3' class='py-2 text-gray-500'>Kayıt yok</td></tr>"}</tbody>
            </table>
          </div>
        </div>
        <div>
          <div class="font-medium mb-2">En Çok Görüntülenen Sayfalar (30 gün)</div>
          <div class="overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead><tr class="text-left text-gray-500"><th>Path</th><th class="text-right">Görüntüleme</th></tr></thead>
              <tbody>{top_rows or "<tr><td colspan='2' class='py-2 text-gray-500'>Kayıt yok</td></tr>"}</tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="text-xs text-gray-500 mt-4">IP adresleri <b>hash</b>’lenerek saklanır (salt={ANALYTICS_SALT}).</div>
    </div>
    """
    return layout(request, body, "Admin – Stats")

# =============== Seed – örnek: Migros Hendek şubeleri ===============
MIGROS_BRANCHES = {
    "Hendek": [
        {"name":"HENDEK SAKARYA M MİGROS","address":"Yeni Mah. Osmangazi Sok. No:42 A-B", "lat":40.7993, "lng":30.7489},
        {"name":"YENİMAHALLE HENDEK SAKARYA MM","address":"Yeni Mahalle Yıldırım Beyazıt Caddesi Dış Kapı", "lat":40.8004, "lng":30.7516},
    ],
    # Diğer ilçeleri aynı formatta ekleyebilirsin.
}

@app.get("/admin/seed", response_class=HTMLResponse)
async def seed_ui(request: Request):
    red = require_admin(request)
    if red: return red
    body = """
    <div class="bg-white card p-6 max-w-md mx-auto">
      <h2 class="text-lg font-bold mb-3">Seed: Migros Şubeleri</h2>
      <form method="post" action="/admin/seed/migros_branches">
        <button class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg">Yükle</button>
      </form>
      <p class="text-xs text-gray-500 mt-3">Yalnızca örnek: Hendek’teki 2 Migros şubesini ekler ve kanonik Migros mağazalarını oluşturur.</p>
    </div>
    """
    return layout(request, body, "Seed")

@app.post("/admin/seed/migros_branches")
async def seed_migros_branches(request: Request):
    red = require_admin(request)
    if red:
        return red

    city = "Sakarya"
    brand = "Migros"
    added_store = 0
    added_branch = 0

    with get_session() as s:
        # İlçe başına tek kanonik 'Migros' store
        for dist in MIGROS_BRANCHES.keys():
            st = s.exec(
                select(Store).where(func.lower(Store.name)==brand.casefold(), Store.city==city, Store.district==dist)
            ).first()
            if not st:
                s.add(Store(name=brand, city=city, district=dist))
                added_store += 1
        s.commit()

        # Şubeler
        for dist, lst in MIGROS_BRANCHES.items():
            for b in lst:
                ex = s.exec(
                    select(Branch).where(
                        func.lower(Branch.brand)==brand.casefold(), Branch.city==city, Branch.district==dist, Branch.name==b["name"]
                    )
                ).first()
                if not ex:
                    s.add(Branch(
                        brand=brand, city=city, district=dist,
                        name=b["name"], address=b.get("address"),
                        lat=b.get("lat"), lng=b.get("lng")
                    ))
                    added_branch += 1
        s.commit()

    return JSONResponse({"ok": True, "added_store": added_store, "added_branch": added_branch})


# ============================================
# CATEGORY DEFINITIONS & SEED DATA
# ============================================

PRODUCT_CATEGORIES = [
    "Süt Ürünleri",
    "Et Ürünleri",
    "Temel Gıda",
    "Sebze-Meyve",
    "Temizlik Ürünleri",
    "Kişisel Bakım",
    "Diğer"
]

SEED_PRODUCTS = [
    # Süt Ürünleri
    {"name": "Süt (Tam Yağlı)", "category": "Süt Ürünleri", "unit": "1L", "description": "Tam yağlı süt"},
    {"name": "Süt (Yarım Yağlı)", "category": "Süt Ürünleri", "unit": "1L", "description": "Yarım yağlı süt"},
    {"name": "Yumurta", "category": "Süt Ürünleri", "unit": "10 adet", "description": "Orta boy yumurta"},
    {"name": "Beyaz Peynir", "category": "Süt Ürünleri", "unit": "1kg", "description": "Tam yağlı beyaz peynir"},
    {"name": "Kaşar Peyniri", "category": "Süt Ürünleri", "unit": "1kg", "description": "Kaşar peyniri"},
    {"name": "Yoğurt", "category": "Süt Ürünleri", "unit": "1kg", "description": "Süzme olmayan yoğurt"},
    {"name": "Tereyağı", "category": "Süt Ürünleri", "unit": "500g", "description": "Tereyağı"},
    
    # Et Ürünleri
    {"name": "Dana Kıyma", "category": "Et Ürünleri", "unit": "1kg", "description": "Dana kıyma"},
    {"name": "Kuzu Kıyma", "category": "Et Ürünleri", "unit": "1kg", "description": "Kuzu kıyma"},
    {"name": "Tavuk But", "category": "Et Ürünleri", "unit": "1kg", "description": "Tavuk but"},
    {"name": "Tavuk Göğüs", "category": "Et Ürünleri", "unit": "1kg", "description": "Tavuk göğüs"},
    {"name": "Tavuk Bütün", "category": "Et Ürünleri", "unit": "1kg", "description": "Bütün tavuk"},
    {"name": "Dana Kuşbaşı", "category": "Et Ürünleri", "unit": "1kg", "description": "Dana kuşbaşı"},
    
    # Temel Gıda
    {"name": "Ekmek (Somun)", "category": "Temel Gıda", "unit": "1 adet", "description": "200g somun ekmek"},
    {"name": "Pirinç", "category": "Temel Gıda", "unit": "1kg", "description": "Baldo pirinç"},
    {"name": "Makarna (Burgu)", "category": "Temel Gıda", "unit": "500g", "description": "Burgu makarna"},
    {"name": "Bulgur (İnce)", "category": "Temel Gıda", "unit": "1kg", "description": "İnce bulgur"},
    {"name": "Un (Beyaz)", "category": "Temel Gıda", "unit": "1kg", "description": "Beyaz un"},
    {"name": "Şeker (Kristal)", "category": "Temel Gıda", "unit": "1kg", "description": "Kristal şeker"},
    {"name": "Tuz", "category": "Temel Gıda", "unit": "1kg", "description": "İyotlu tuz"},
    {"name": "Ayçiçek Yağı", "category": "Temel Gıda", "unit": "1L", "description": "Ayçiçek yağı"},
    {"name": "Zeytinyağı", "category": "Temel Gıda", "unit": "1L", "description": "Zeytinyağı"},
    {"name": "Zeytin (Siyah)", "category": "Temel Gıda", "unit": "1kg", "description": "Siyah zeytin"},
    {"name": "Domates Salçası", "category": "Temel Gıda", "unit": "800g", "description": "Domates salçası"},
    
    # Sebze-Meyve
    {"name": "Domates", "category": "Sebze-Meyve", "unit": "1kg", "description": "Yerli domates"},
    {"name": "Salatalık", "category": "Sebze-Meyve", "unit": "1kg", "description": "Yerli salatalık"},
    {"name": "Patates", "category": "Sebze-Meyve", "unit": "1kg", "description": "Yerli patates"},
    {"name": "Soğan (Kuru)", "category": "Sebze-Meyve", "unit": "1kg", "description": "Kuru soğan"},
    {"name": "Limon", "category": "Sebze-Meyve", "unit": "1kg", "description": "Yerli limon"},
    {"name": "Portakal", "category": "Sebze-Meyve", "unit": "1kg", "description": "Yerli portakal"},
    {"name": "Muz", "category": "Sebze-Meyve", "unit": "1kg", "description": "İthal muz"},
    {"name": "Elma", "category": "Sebze-Meyve", "unit": "1kg", "description": "Yerli elma"},
    
    # Temizlik Ürünleri
    {"name": "Bulaşık Deterjanı", "category": "Temizlik Ürünleri", "unit": "750ml", "description": "Bulaşık deterjanı"},
    {"name": "Çamaşır Deterjanı", "category": "Temizlik Ürünleri", "unit": "3kg", "description": "Toz çamaşır deterjanı"},
    {"name": "Yumuşatıcı", "category": "Temizlik Ürünleri", "unit": "1.5L", "description": "Çamaşır yumuşatıcı"},
    {"name": "Yüzey Temizleyici", "category": "Temizlik Ürünleri", "unit": "1L", "description": "Yüzey temizleyici"},
    
    # Kişisel Bakım
    {"name": "Şampuan", "category": "Kişisel Bakım", "unit": "500ml", "description": "Şampuan"},
    {"name": "Sabun", "category": "Kişisel Bakım", "unit": "4x90g", "description": "Banyo sabunu"},
    {"name": "Diş Macunu", "category": "Kişisel Bakım", "unit": "100ml", "description": "Diş macunu"},
]

def seed_products():
    """Temel ürünleri veritabanına ekle"""
    with get_session() as s:
        count = 0
        for p in SEED_PRODUCTS:
            existing = s.exec(select(Product).where(
                func.lower(Product.name) == p["name"].lower()
            )).first()
            
            if not existing:
                product = Product(
                    name=p["name"],
                    category=p["category"],
                    unit=p["unit"],
                    description=p.get("description"),
                    is_active=True,
                    created_by="system",
                    created_at=datetime.utcnow()
                )
                s.add(product)
                count += 1
        
        s.commit()
    return count

# ============================================
# BUSINESS AUTHENTICATION FUNCTIONS
# ============================================

def verify_password_business(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash_business(password: str) -> str:
    return pwd_context.hash(password)

def create_business_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_business(request: Request) -> Optional[Business]:
    """Cookie'den işletme bilgisini al"""
    token = request.cookies.get("business_token")
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        business_id: int = payload.get("sub")
        if business_id is None:
            return None
    except JWTError:
        return None
    
    with get_session() as s:
        business = s.exec(select(Business).where(Business.id == business_id)).first()
        return business

def require_business_auth(request: Request):
    """İşletme authentication gerektirir"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    if not business.is_approved:
        return RedirectResponse("/business/pending", status_code=302)
    if not business.is_active:
        return RedirectResponse("/business/inactive", status_code=302)
    return business

# ============================================
# BUSINESS ROUTES - REGISTRATION & LOGIN
# ============================================

@app.get("/business/register", response_class=HTMLResponse)
async def business_register_form(request: Request):
    """İşletme kayıt formu"""
    error = request.query_params.get("error", "")
    success = request.query_params.get("success", "")
    
    error_msg = ""
    if error == "email_exists":
        error_msg = '<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Bu e-posta adresi zaten kayıtlı.</div>'
    elif error == "password_mismatch":
        error_msg = '<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Şifreler eşleşmiyor.</div>'
    elif error == "password_too_short":
        error_msg = '<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Şifre en az 6 karakter olmalıdır.</div>'
    elif error:
        error_msg = f'<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Bir hata oluştu: {error}</div>'
    
    success_msg = ""
    if success == "registered":
        success_msg = '''
        <div class="p-4 mb-4 bg-emerald-50 text-emerald-800 rounded-lg">
          <strong>Kayıt başarılı!</strong><br>
          Hesabınız oluşturuldu. Admin onayından sonra giriş yapabileceksiniz.
          <br>E-posta adresinize bilgilendirme gelecektir.
        </div>
        '''
    
    districts = [d["name"] for d in LOC_JSON["provinces"][0]["districts"]]
    district_opts = "".join(f'<option value="{d}">{d}</option>' for d in districts)
    
    body = f"""
    <div class="bg-white card p-6 max-w-2xl mx-auto">
      <h2 class="text-2xl font-bold mb-2">İşletme Kayıt</h2>
      <p class="text-sm text-gray-600 mb-4">
        Pazarmetre'ye işletme olarak kayıt olun ve kendi fiyatlarınızı yönetin.
      </p>
      
      {error_msg}
      {success_msg}
      
      <form method="post" action="/business/register" class="space-y-4">
        <div class="grid md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium mb-1">İşletme Adı *</label>
            <input type="text" name="business_name" required
                   class="w-full border rounded-lg p-2"
                   placeholder="Örn: Kutsallar Kasabı">
          </div>
          
          <div>
            <label class="block text-sm font-medium mb-1">Yetkili Kişi *</label>
            <input type="text" name="contact_person" required
                   class="w-full border rounded-lg p-2"
                   placeholder="Ad Soyad">
          </div>
        </div>
        
        <div class="grid md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium mb-1">E-posta *</label>
            <input type="email" name="email" required
                   class="w-full border rounded-lg p-2"
                   placeholder="isletme@example.com">
          </div>
          
          <div>
            <label class="block text-sm font-medium mb-1">Telefon *</label>
            <input type="tel" name="phone" required
                   class="w-full border rounded-lg p-2"
                   placeholder="0532 123 45 67">
          </div>
        </div>
        
        <div>
          <label class="block text-sm font-medium mb-1">Adres</label>
          <input type="text" name="address"
                 class="w-full border rounded-lg p-2"
                 placeholder="İşletme adresi">
        </div>
        
        <div class="grid md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium mb-1">Şehir *</label>
            <select name="city" required class="w-full border rounded-lg p-2">
              <option value="Sakarya">Sakarya</option>
            </select>
          </div>
          
          <div>
            <label class="block text-sm font-medium mb-1">İlçe *</label>
            <select name="district" required class="w-full border rounded-lg p-2">
              <option value="">Seçiniz...</option>
              {district_opts}
            </select>
          </div>
        </div>
        
        <div class="grid md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium mb-1">Şifre *</label>
            <input type="password" name="password" required minlength="6"
                   class="w-full border rounded-lg p-2"
                   placeholder="En az 6 karakter">
          </div>
          
          <div>
            <label class="block text-sm font-medium mb-1">Şifre Tekrar *</label>
            <input type="password" name="password_confirm" required minlength="6"
                   class="w-full border rounded-lg p-2"
                   placeholder="Şifreyi tekrar girin">
          </div>
        </div>
        
        <div class="p-3 bg-blue-50 rounded-lg text-sm text-blue-800">
          <strong>📋 Kayıt Sonrası:</strong><br>
          - Hesabınız admin tarafından incelenerek onaylanacaktır<br>
          - Onay sonrası giriş yapıp kendi fiyatlarınızı girebileceksiniz<br>
          - Ücretsiz dijital fiyat vitrini hizmeti sunuyoruz
        </div>
        
        <div class="flex gap-3">
          <button type="submit"
                  class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-medium">
            Kayıt Ol
          </button>
          <a href="/business/login"
             class="flex-1 text-center border border-gray-300 hover:bg-gray-50 px-6 py-3 rounded-lg font-medium">
            Zaten Hesabım Var
          </a>
        </div>
      </form>
    </div>
    """
    
    return layout(request, body, "İşletme Kayıt – Pazarmetre")

@app.post("/business/register")
async def business_register(
    request: Request,
    business_name: str = Form(...),
    contact_person: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    address: str = Form(""),
    city: str = Form(...),
    district: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...)
):
    """İşletme kaydı işle"""
    
    # Şifre kontrolü
    if password != password_confirm:
        return RedirectResponse("/business/register?error=password_mismatch", status_code=302)
    
    if len(password) < 6:
        return RedirectResponse("/business/register?error=password_too_short", status_code=302)
    
    with get_session() as s:
        # E-posta kontrolü
        existing = s.exec(select(Business).where(Business.email == email)).first()
        if existing:
            return RedirectResponse("/business/register?error=email_exists", status_code=302)
        
        # Yeni işletme oluştur
        hashed_pw = get_password_hash_business(password)
        business = Business(
            email=email,
            hashed_password=hashed_pw,
            business_name=business_name,
            contact_person=contact_person,
            phone=phone,
            address=address,
            city=city,
            district=district,
            is_approved=False,  # Admin onayı gerekli
            is_active=True,
            created_at=datetime.utcnow()
        )
        
        s.add(business)
        s.commit()
    
    return RedirectResponse("/business/register?success=registered", status_code=302)

@app.get("/business/login", response_class=HTMLResponse)
async def business_login_form(request: Request):
    """İşletme giriş formu"""
    error = request.query_params.get("error", "")
    
    error_msg = ""
    if error == "invalid_credentials":
        error_msg = '<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">E-posta veya şifre hatalı.</div>'
    elif error == "not_approved":
        error_msg = '<div class="p-3 mb-4 bg-amber-50 text-amber-800 rounded-lg">Hesabınız henüz onaylanmamış. Lütfen bekleyin.</div>'
    elif error == "inactive":
        error_msg = '<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Hesabınız devre dışı bırakılmış. Lütfen iletişime geçin.</div>'
    elif error == "login_required":
        error_msg = '<div class="p-3 mb-4 bg-amber-50 text-amber-800 rounded-lg">Bu sayfaya erişmek için giriş yapmalısınız.</div>'
    
    body = f"""
    <div class="bg-white card p-6 max-w-md mx-auto">
      <h2 class="text-2xl font-bold mb-2">İşletme Girişi</h2>
      <p class="text-sm text-gray-600 mb-4">
        İşletme hesabınızla giriş yapın.
      </p>
      
      {error_msg}
      
      <form method="post" action="/business/login" class="space-y-4">
        <div>
          <label class="block text-sm font-medium mb-1">E-posta</label>
          <input type="email" name="email" required
                 class="w-full border rounded-lg p-2"
                 placeholder="isletme@example.com">
        </div>
        
        <div>
          <label class="block text-sm font-medium mb-1">Şifre</label>
          <input type="password" name="password" required
                 class="w-full border rounded-lg p-2"
                 placeholder="Şifreniz">
        </div>
        
        <button type="submit"
                class="w-full bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-medium">
          Giriş Yap
        </button>
      </form>
      
      <div class="mt-4 text-center">
        <a href="/business/register" class="text-sm text-indigo-600 hover:underline">
          Henüz hesabınız yok mu? Kayıt olun
        </a>
      </div>
      
      <div class="mt-6 p-3 bg-blue-50 rounded-lg text-sm text-blue-800">
        <strong>💡 İpucu:</strong> Kayıt olduktan sonra admin onayı beklemeniz gerekir.
        Onay sonrası bu sayfadan giriş yapabilirsiniz.
      </div>
    </div>
    """
    
    return layout(request, body, "İşletme Girişi – Pazarmetre")

@app.post("/business/login")
async def business_login(
    email: str = Form(...),
    password: str = Form(...)
):
    """İşletme girişi işle"""
    
    with get_session() as s:
        business = s.exec(select(Business).where(Business.email == email)).first()
        
        if not business or not verify_password_business(password, business.hashed_password):
            return RedirectResponse("/business/login?error=invalid_credentials", status_code=302)
        
        if not business.is_approved:
            return RedirectResponse("/business/login?error=not_approved", status_code=302)
        
        if not business.is_active:
            return RedirectResponse("/business/login?error=inactive", status_code=302)
        
        # JWT token oluştur
        access_token = create_business_access_token(
            data={"sub": business.id},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        response = RedirectResponse("/business/dashboard", status_code=302)
        response.set_cookie(
            key="business_token",
            value=access_token,
            httponly=True,
            samesite="lax",
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        
        return response

@app.get("/business/logout")
async def business_logout():
    """İşletme çıkışı"""
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("business_token")
    return response

@app.get("/business/pending", response_class=HTMLResponse)
async def business_pending(request: Request):
    """Onay bekleyen işletme sayfası"""
    body = """
    <div class="bg-white card p-6 max-w-lg mx-auto text-center">
      <div class="text-6xl mb-4">⏳</div>
      <h2 class="text-2xl font-bold mb-2">Hesabınız Onay Bekliyor</h2>
      <p class="text-gray-600 mb-4">
        Kaydınız başarıyla alındı. Admin tarafından incelendikten sonra
        hesabınız aktif hale gelecektir.
      </p>
      <p class="text-sm text-gray-500">
        Genellikle 24 saat içinde onaylanır. E-posta adresinize bilgilendirme yapılacaktır.
      </p>
      <div class="mt-6">
        <a href="/" class="text-indigo-600 hover:underline">Ana Sayfaya Dön</a>
      </div>
    </div>
    """
    return layout(request, body, "Onay Bekliyor – Pazarmetre")

@app.get("/business/inactive", response_class=HTMLResponse)
async def business_inactive(request: Request):
    """Devre dışı işletme sayfası"""
    body = """
    <div class="bg-white card p-6 max-w-lg mx-auto text-center">
      <div class="text-6xl mb-4">⛔</div>
      <h2 class="text-2xl font-bold mb-2">Hesabınız Devre Dışı</h2>
      <p class="text-gray-600 mb-4">
        Hesabınız yönetici tarafından devre dışı bırakılmıştır.
      </p>
      <p class="text-sm text-gray-500">
        Daha fazla bilgi için lütfen bizimle iletişime geçin:<br>
        <a href="mailto:pazarmetre1@gmail.com" class="text-indigo-600 hover:underline">
          pazarmetre1@gmail.com
        </a>
      </p>
      <div class="mt-6">
        <a href="/" class="text-indigo-600 hover:underline">Ana Sayfaya Dön</a>
      </div>
    </div>
    """
    return layout(request, body, "Hesap Devre Dışı – Pazarmetre")
# ===========================================
# BUSINESS DASHBOARD
# ===========================================

@app.get("/business/dashboard", response_class=HTMLResponse)
async def business_dashboard(request: Request):
    """İşletme dashboard"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    
    if not business.is_approved:
        return RedirectResponse("/business/pending", status_code=302)
    
    if not business.is_active:
        return RedirectResponse("/business/inactive", status_code=302)
    
    # İşletmenin girdiği fiyat sayısı
    with get_session() as s:
        offer_count = s.exec(
            select(func.count()).select_from(Offer).where(Offer.business_id == business.id)
        ).one() or 0
        
        # Son fiyatlar
        recent_offers = s.exec(
            select(Offer, Product, Store)
            .where(Offer.business_id == business.id)
            .join(Product, Offer.product_id == Product.id)
            .join(Store, Offer.store_id == Store.id)
            .order_by(Offer.created_at.desc())
            .limit(10)
        ).all()
        
        offer_rows = ""
        for off, prod, st in recent_offers:
            offer_rows += f"""
            <tr class="border-b">
                <td class="py-2">{prod.name}</td>
                <td class="py-2">{st.name}</td>
                <td class="py-2 text-right font-semibold">{off.price:.2f} ₺</td>
                <td class="py-2 text-sm text-gray-500">{off.created_at.strftime('%d.%m.%Y %H:%M')}</td>
                <td class="py-2">
                    <a href="/business/price/delete/{off.id}" 
                       onclick="return confirm('Bu fiyatı silmek istediğinizden emin misiniz?')"
                       class="text-red-600 hover:underline text-sm">Sil</a>
                </td>
            </tr>
            """
        
        if not offer_rows:
            offer_rows = '<tr><td colspan="5" class="py-4 text-center text-gray-500">Henüz fiyat girmediniz.</td></tr>'
    
    body = f"""
    <div class="max-w-5xl mx-auto">
        <div class="bg-white card p-6 mb-6">
            <div class="flex items-center justify-between mb-4">
                <div>
                    <h2 class="text-2xl font-bold">{business.business_name}</h2>
                    <p class="text-sm text-gray-600">{business.email}</p>
                </div>
                <div class="flex gap-2">
                    <a href="/business/price/add" 
                       class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg">
                        + Fiyat Ekle
                    </a>
                    <a href="/business/logout" 
                       class="border border-gray-300 hover:bg-gray-50 px-4 py-2 rounded-lg">
                        Çıkış
                    </a>
                </div>
            </div>
            
            <div class="grid md:grid-cols-3 gap-4">
                <div class="p-4 bg-emerald-50 rounded-lg">
                    <div class="text-sm text-gray-600">Toplam Fiyat</div>
                    <div class="text-3xl font-bold text-emerald-600">{offer_count}</div>
                </div>
                <div class="p-4 bg-blue-50 rounded-lg">
                    <div class="text-sm text-gray-600">İlçe</div>
                    <div class="text-xl font-bold text-blue-600">{business.district}</div>
                </div>
                <div class="p-4 bg-indigo-50 rounded-lg">
                    <div class="text-sm text-gray-600">Durum</div>
                    <div class="text-xl font-bold text-indigo-600">{'✅ Aktif' if business.is_active else '⛔ Pasif'}</div>
                </div>
            </div>
        </div>
        
        <div class="bg-white card p-6">
            <h3 class="text-lg font-bold mb-4">Son Eklenen Fiyatlar</h3>
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="py-2 px-4 text-left text-sm font-medium">Ürün</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Mağaza</th>
                            <th class="py-2 px-4 text-right text-sm font-medium">Fiyat</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Tarih</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">İşlem</th>
                        </tr>
                    </thead>
                    <tbody>
                        {offer_rows}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    
    return layout(request, body, f"Dashboard – {business.business_name}")

@app.get("/business/price/add", response_class=HTMLResponse)
async def business_price_add_form(request: Request):
    """İşletme fiyat ekleme formu"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    
    if not business.is_approved or not business.is_active:
        return RedirectResponse("/business/dashboard", status_code=302)
    
    error = request.query_params.get("error", "")
    success = request.query_params.get("success", "")
    
    error_msg = ""
    if error:
        error_msg = f'<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Hata: {error}</div>'
    
    success_msg = ""
    if success == "added":
        success_msg = '<div class="p-3 mb-4 bg-emerald-50 text-emerald-800 rounded-lg">✅ Fiyat başarıyla eklendi!</div>'
    
    # Ürün listesini kategoriye göre getir
    with get_session() as s:
        products = s.exec(
            select(Product)
            .where(Product.is_active == True)
            .order_by(Product.category, Product.name)
        ).all()
        
        # Mağaza listesi - İşletmenin ilçesindeki mağazalar + kendi mağazası
        stores = s.exec(
            select(Store)
            .where(
                or_(
                    Store.district == business.district,
                    Store.business_id == business.id
                )
            )
            .order_by(Store.name)
        ).all()
        
        # Eğer işletmenin kendi mağazası yoksa oluştur
        own_store = None
        for st in stores:
            if st.business_id == business.id:
                own_store = st
                break
        
        if not own_store:
            own_store = Store(
                name=business.business_name,
                city=business.city,
                district=business.district,
                address=business.address,
                business_id=business.id
            )
            s.add(own_store)
            s.commit()
            s.refresh(own_store)
            stores.append(own_store)
    
    # Kategori bazlı ürün dropdown
    product_opts_by_cat = {}
    for p in products:
        cat = p.category or "Diğer"
        if cat not in product_opts_by_cat:
            product_opts_by_cat[cat] = []
        product_opts_by_cat[cat].append(f'<option value="{p.id}">{p.name} ({p.unit})</option>')
    
    product_opts = ""
    for cat in sorted(product_opts_by_cat.keys()):
        product_opts += f'<optgroup label="{cat}">'
        product_opts += "".join(product_opts_by_cat[cat])
        product_opts += '</optgroup>'
    
    store_opts = "".join(
        f'<option value="{st.id}" {"selected" if st.business_id == business.id else ""}>{st.name}</option>'
        for st in stores
    )
    
    body = f"""
    <div class="max-w-2xl mx-auto">
        <div class="bg-white card p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Yeni Fiyat Ekle</h2>
                <a href="/business/dashboard" class="text-sm text-gray-600 hover:underline">← Dashboard</a>
            </div>
            
            {error_msg}
            {success_msg}
            
            <form method="post" action="/business/price/add" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium mb-1">Ürün *</label>
                    <select name="product_id" required class="w-full border rounded-lg p-2">
                        <option value="">Ürün seçiniz...</option>
                        {product_opts}
                    </select>
                    <p class="text-xs text-gray-500 mt-1">
                        Listede olmayan bir ürün mü? <a href="/business/product/suggest" class="text-indigo-600 hover:underline">Ürün öner</a>
                    </p>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Mağaza *</label>
                    <select name="store_id" required class="w-full border rounded-lg p-2">
                        {store_opts}
                    </select>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Fiyat (₺) *</label>
                    <input type="number" name="price" required step="0.01" min="0"
                           class="w-full border rounded-lg p-2"
                           placeholder="Örn: 45.90">
                </div>
                
                <div class="p-3 bg-blue-50 rounded-lg text-sm text-blue-800">
                    <strong>💡 Not:</strong> Girdiğiniz fiyatlar hemen yayınlanır ve tüm kullanıcılar görebilir.
                    Yanlış fiyat girmeniz durumunda dashboard'dan silebilirsiniz.
                </div>
                
                <div class="flex gap-3">
                    <button type="submit"
                            class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-medium">
                        Fiyat Ekle
                    </button>
                    <a href="/business/dashboard"
                       class="flex-1 text-center border border-gray-300 hover:bg-gray-50 px-6 py-3 rounded-lg font-medium">
                        İptal
                    </a>
                </div>
            </form>
        </div>
    </div>
    """
    
    return layout(request, body, "Fiyat Ekle – Pazarmetre")

@app.post("/business/price/add")
async def business_price_add(
    request: Request,
    product_id: int = Form(...),
    store_id: int = Form(...),
    price: float = Form(...)
):
    """İşletme fiyat ekleme"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    
    if not business.is_approved or not business.is_active:
        return RedirectResponse("/business/dashboard", status_code=302)
    
    with get_session() as s:
        # Ürün kontrolü
        product = s.get(Product, product_id)
        if not product or not product.is_active:
            return RedirectResponse("/business/price/add?error=invalid_product", status_code=302)
        
        # Mağaza kontrolü
        store = s.get(Store, store_id)
        if not store:
            return RedirectResponse("/business/price/add?error=invalid_store", status_code=302)
        
        # Fiyat ekle
        offer = Offer(
            product_id=product_id,
            store_id=store_id,
            price=price,
            business_id=business.id,
            created_at=datetime.utcnow(),
            approved=True  # İşletme fiyatları otomatik onaylı
        )
        
        s.add(offer)
        s.commit()
    
    return RedirectResponse("/business/price/add?success=added", status_code=302)

@app.get("/business/price/delete/{offer_id}")
async def business_price_delete(request: Request, offer_id: int):
    """İşletme fiyat silme"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    
    with get_session() as s:
        offer = s.get(Offer, offer_id)
        if not offer:
            return RedirectResponse("/business/dashboard?error=not_found", status_code=302)
        
        # Sadece kendi fiyatlarını silebilir
        if offer.business_id != business.id:
            return RedirectResponse("/business/dashboard?error=unauthorized", status_code=302)
        
        s.delete(offer)
        s.commit()
    
    return RedirectResponse("/business/dashboard?success=deleted", status_code=302)

@app.get("/business/product/suggest", response_class=HTMLResponse)
async def business_product_suggest_form(request: Request):
    """Yeni ürün önerisi formu"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    
    if not business.is_approved or not business.is_active:
        return RedirectResponse("/business/dashboard", status_code=302)
    
    error = request.query_params.get("error", "")
    success = request.query_params.get("success", "")
    
    error_msg = ""
    if error:
        error_msg = f'<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Hata: {error}</div>'
    
    success_msg = ""
    if success == "suggested":
        success_msg = '''
        <div class="p-3 mb-4 bg-emerald-50 text-emerald-800 rounded-lg">
            ✅ Ürün öneriniz başarıyla gönderildi! Admin incelemesinden sonra listeye eklenecektir.
        </div>
        '''
    
    category_opts = "".join(f'<option value="{cat}">{cat}</option>' for cat in PRODUCT_CATEGORIES)
    
    body = f"""
    <div class="max-w-2xl mx-auto">
        <div class="bg-white card p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Yeni Ürün Öner</h2>
                <a href="/business/price/add" class="text-sm text-gray-600 hover:underline">← Geri</a>
            </div>
            
            {error_msg}
            {success_msg}
            
            <form method="post" action="/business/product/suggest" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium mb-1">Ürün Adı *</label>
                    <input type="text" name="product_name" required
                           class="w-full border rounded-lg p-2"
                           placeholder="Örn: Zeytin (Yeşil)">
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Kategori *</label>
                    <select name="category" required class="w-full border rounded-lg p-2">
                        <option value="">Kategori seçiniz...</option>
                        {category_opts}
                    </select>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Birim *</label>
                    <input type="text" name="unit" required
                           class="w-full border rounded-lg p-2"
                           placeholder="Örn: 1kg, 500g, 1L">
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Açıklama</label>
                    <textarea name="description"
                              class="w-full border rounded-lg p-2"
                              rows="3"
                              placeholder="Ürün hakkında detaylı bilgi (opsiyonel)"></textarea>
                </div>
                
                <div class="p-3 bg-amber-50 rounded-lg text-sm text-amber-800">
                    <strong>⚠️ Önemli:</strong><br>
                    - Ürün öneriniz admin tarafından incelenecektir<br>
                    - Onaylandıktan sonra tüm kullanıcılar bu ürün için fiyat girebilecektir<br>
                    - Gereksiz veya mükerrer öneriler reddedilecektir
                </div>
                
                <div class="flex gap-3">
                    <button type="submit"
                            class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-medium">
                        Ürün Öner
                    </button>
                    <a href="/business/price/add"
                       class="flex-1 text-center border border-gray-300 hover:bg-gray-50 px-6 py-3 rounded-lg font-medium">
                        İptal
                    </a>
                </div>
            </form>
        </div>
    </div>
    """
    
    return layout(request, body, "Ürün Öner – Pazarmetre")

@app.post("/business/product/suggest")
async def business_product_suggest(
    request: Request,
    product_name: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    description: str = Form("")
):
    """Yeni ürün önerisi gönder"""
    business = get_current_business(request)
    if not business:
        return RedirectResponse("/business/login?error=login_required", status_code=302)
    
    if not business.is_approved or not business.is_active:
        return RedirectResponse("/business/dashboard", status_code=302)
    
    with get_session() as s:
        suggestion = ProductSuggestion(
            business_id=business.id,
            product_name=product_name,
            category=category,
            unit=unit,
            description=description,
            status="pending",
            created_at=datetime.utcnow()
        )
        
        s.add(suggestion)
        s.commit()
    
    return RedirectResponse("/business/product/suggest?success=suggested", status_code=302)

# ===========================================
# ADMIN - PRODUCT MANAGEMENT
# ===========================================

@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products_list(request: Request):
    """Admin ürün listesi"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        products = s.exec(
            select(Product).order_by(Product.category, Product.name)
        ).all()
        
        product_rows = ""
        for p in products:
            status_badge = '✅ Aktif' if p.is_active else '❌ Pasif'
            product_rows += f"""
            <tr class="border-b hover:bg-gray-50">
                <td class="py-2 px-4">{p.name}</td>
                <td class="py-2 px-4">{p.category or '-'}</td>
                <td class="py-2 px-4">{p.unit}</td>
                <td class="py-2 px-4">{status_badge}</td>
                <td class="py-2 px-4 text-sm">
                    <a href="/admin/product/edit/{p.id}" class="text-indigo-600 hover:underline mr-2">Düzenle</a>
                    <a href="/admin/product/delete/{p.id}" 
                       onclick="return confirm('Bu ürünü silmek istediğinizden emin misiniz?')"
                       class="text-red-600 hover:underline">Sil</a>
                </td>
            </tr>
            """
    
    body = f"""
    <div class="max-w-6xl mx-auto">
        <div class="bg-white card p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Ürün Yönetimi</h2>
                <div class="flex gap-2">
                    <a href="/admin/product/add" 
                       class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg">
                        + Yeni Ürün
                    </a>
                    <a href="/admin/product/suggestions" 
                       class="bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-lg">
                        📋 Öneriler
                    </a>
                    <a href="/admin" 
                       class="border border-gray-300 hover:bg-gray-50 px-4 py-2 rounded-lg">
                        ← Admin Panel
                    </a>
                </div>
            </div>
            
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="py-2 px-4 text-left text-sm font-medium">Ürün Adı</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Kategori</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Birim</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Durum</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">İşlem</th>
                        </tr>
                    </thead>
                    <tbody>
                        {product_rows or '<tr><td colspan="5" class="py-4 text-center text-gray-500">Henüz ürün yok</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    
    return layout(request, body, "Ürün Yönetimi – Admin")

@app.get("/admin/product/add", response_class=HTMLResponse)
async def admin_product_add_form(request: Request):
    """Admin yeni ürün ekleme formu"""
    red = require_admin(request)
    if red:
        return red
    
    error = request.query_params.get("error", "")
    success = request.query_params.get("success", "")
    
    error_msg = ""
    if error:
        error_msg = f'<div class="p-3 mb-4 bg-red-50 text-red-800 rounded-lg">Hata: {error}</div>'
    
    success_msg = ""
    if success == "added":
        success_msg = '<div class="p-3 mb-4 bg-emerald-50 text-emerald-800 rounded-lg">✅ Ürün başarıyla eklendi!</div>'
    
    category_opts = "".join(f'<option value="{cat}">{cat}</option>' for cat in PRODUCT_CATEGORIES)
    
    body = f"""
    <div class="max-w-2xl mx-auto">
        <div class="bg-white card p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Yeni Ürün Ekle</h2>
                <a href="/admin/products" class="text-sm text-gray-600 hover:underline">← Ürün Listesi</a>
            </div>
            
            {error_msg}
            {success_msg}
            
            <form method="post" action="/admin/product/add" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium mb-1">Ürün Adı *</label>
                    <input type="text" name="name" required
                           class="w-full border rounded-lg p-2"
                           placeholder="Örn: Süt (Tam Yağlı)">
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Kategori *</label>
                    <select name="category" required class="w-full border rounded-lg p-2">
                        <option value="">Kategori seçiniz...</option>
                        {category_opts}
                    </select>
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Birim *</label>
                    <input type="text" name="unit" required
                           class="w-full border rounded-lg p-2"
                           placeholder="Örn: 1kg, 500g, 1L, 10 adet">
                </div>
                
                <div>
                    <label class="block text-sm font-medium mb-1">Açıklama</label>
                    <textarea name="description"
                              class="w-full border rounded-lg p-2"
                              rows="3"
                              placeholder="Ürün hakkında detaylı bilgi (opsiyonel)"></textarea>
                </div>
                
                <div>
                    <label class="flex items-center gap-2">
                        <input type="checkbox" name="featured" value="1">
                        <span class="text-sm">Öne çıkan ürün olarak işaretle</span>
                    </label>
                </div>
                
                <div class="flex gap-3">
                    <button type="submit"
                            class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-medium">
                        Ürün Ekle
                    </button>
                    <a href="/admin/products"
                       class="flex-1 text-center border border-gray-300 hover:bg-gray-50 px-6 py-3 rounded-lg font-medium">
                        İptal
                    </a>
                </div>
            </form>
        </div>
    </div>
    """
    
    return layout(request, body, "Yeni Ürün – Admin")

@app.post("/admin/product/add")
async def admin_product_add(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    description: str = Form(""),
    featured: str = Form("0")
):
    """Admin yeni ürün ekleme"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        # Aynı isimde ürün var mı?
        existing = s.exec(
            select(Product).where(func.lower(Product.name) == name.lower())
        ).first()
        
        if existing:
            return RedirectResponse("/admin/product/add?error=already_exists", status_code=302)
        
        product = Product(
            name=name,
            category=category,
            unit=unit,
            description=description,
            featured=(featured == "1"),
            is_active=True,
            created_by="admin",
            created_at=datetime.utcnow()
        )
        
        s.add(product)
        s.commit()
    
    return RedirectResponse("/admin/product/add?success=added", status_code=302)

@app.get("/admin/product/edit/{product_id}", response_class=HTMLResponse)
async def admin_product_edit_form(request: Request, product_id: int):
    """Admin ürün düzenleme formu"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        product = s.get(Product, product_id)
        if not product:
            return RedirectResponse("/admin/products?error=not_found", status_code=302)
        
        category_opts = "".join(
            f'<option value="{cat}" {"selected" if cat == product.category else ""}>{cat}</option>' 
            for cat in PRODUCT_CATEGORIES
        )
        
        body = f"""
        <div class="max-w-2xl mx-auto">
            <div class="bg-white card p-6">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-2xl font-bold">Ürün Düzenle</h2>
                    <a href="/admin/products" class="text-sm text-gray-600 hover:underline">← Ürün Listesi</a>
                </div>
                
                <form method="post" action="/admin/product/edit/{product_id}" class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium mb-1">Ürün Adı *</label>
                        <input type="text" name="name" required value="{product.name}"
                               class="w-full border rounded-lg p-2">
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium mb-1">Kategori *</label>
                        <select name="category" required class="w-full border rounded-lg p-2">
                            {category_opts}
                        </select>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium mb-1">Birim *</label>
                        <input type="text" name="unit" required value="{product.unit}"
                               class="w-full border rounded-lg p-2">
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium mb-1">Açıklama</label>
                        <textarea name="description" class="w-full border rounded-lg p-2" rows="3">{product.description or ''}</textarea>
                    </div>
                    
                    <div>
                        <label class="flex items-center gap-2">
                            <input type="checkbox" name="featured" value="1" {"checked" if product.featured else ""}>
                            <span class="text-sm">Öne çıkan ürün</span>
                        </label>
                    </div>
                    
                    <div>
                        <label class="flex items-center gap-2">
                            <input type="checkbox" name="is_active" value="1" {"checked" if product.is_active else ""}>
                            <span class="text-sm">Aktif</span>
                        </label>
                    </div>
                    
                    <div class="flex gap-3">
                        <button type="submit"
                                class="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white px-6 py-3 rounded-lg font-medium">
                            Kaydet
                        </button>
                        <a href="/admin/products"
                           class="flex-1 text-center border border-gray-300 hover:bg-gray-50 px-6 py-3 rounded-lg font-medium">
                            İptal
                        </a>
                    </div>
                </form>
            </div>
        </div>
        """
        
        return layout(request, body, f"Düzenle: {product.name} – Admin")

@app.post("/admin/product/edit/{product_id}")
async def admin_product_edit(
    request: Request,
    product_id: int,
    name: str = Form(...),
    category: str = Form(...),
    unit: str = Form(...),
    description: str = Form(""),
    featured: str = Form("0"),
    is_active: str = Form("0")
):
    """Admin ürün düzenleme"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        product = s.get(Product, product_id)
        if not product:
            return RedirectResponse("/admin/products?error=not_found", status_code=302)
        
        product.name = name
        product.category = category
        product.unit = unit
        product.description = description
        product.featured = (featured == "1")
        product.is_active = (is_active == "1")
        product.updated_at = datetime.utcnow()
        
        s.add(product)
        s.commit()
    
    return RedirectResponse("/admin/products?success=updated", status_code=302)

@app.get("/admin/product/delete/{product_id}")
async def admin_product_delete(request: Request, product_id: int):
    """Admin ürün silme"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        product = s.get(Product, product_id)
        if product:
            s.delete(product)
            s.commit()
    
    return RedirectResponse("/admin/products?success=deleted", status_code=302)

# ===========================================
# ADMIN - PRODUCT SUGGESTIONS
# ===========================================

@app.get("/admin/product/suggestions", response_class=HTMLResponse)
async def admin_product_suggestions(request: Request):
    """Admin ürün önerileri listesi"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        suggestions = s.exec(
            select(ProductSuggestion, Business)
            .join(Business, ProductSuggestion.business_id == Business.id)
            .where(ProductSuggestion.status == "pending")
            .order_by(ProductSuggestion.created_at.desc())
        ).all()
        
        suggestion_rows = ""
        for sug, bus in suggestions:
            suggestion_rows += f"""
            <tr class="border-b hover:bg-gray-50">
                <td class="py-2 px-4">
                    <div class="font-semibold">{sug.product_name}</div>
                    <div class="text-xs text-gray-500">{sug.category} • {sug.unit}</div>
                </td>
                <td class="py-2 px-4 text-sm">{sug.description or '-'}</td>
                <td class="py-2 px-4 text-sm">{bus.business_name}</td>
                <td class="py-2 px-4 text-xs text-gray-500">{sug.created_at.strftime('%d.%m.%Y')}</td>
                <td class="py-2 px-4 text-sm">
                    <a href="/admin/product/suggestion/approve/{sug.id}" 
                       class="text-emerald-600 hover:underline mr-2">✅ Onayla</a>
                    <a href="/admin/product/suggestion/reject/{sug.id}" 
                       onclick="return confirm('Bu öneriyi reddetmek istediğinizden emin misiniz?')"
                       class="text-red-600 hover:underline">❌ Reddet</a>
                </td>
            </tr>
            """
    
    body = f"""
    <div class="max-w-6xl mx-auto">
        <div class="bg-white card p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Ürün Önerileri</h2>
                <a href="/admin/products" 
                   class="border border-gray-300 hover:bg-gray-50 px-4 py-2 rounded-lg">
                    ← Ürün Listesi
                </a>
            </div>
            
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="py-2 px-4 text-left text-sm font-medium">Ürün</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Açıklama</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">İşletme</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Tarih</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">İşlem</th>
                        </tr>
                    </thead>
                    <tbody>
                        {suggestion_rows or '<tr><td colspan="5" class="py-4 text-center text-gray-500">Bekleyen öneri yok</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    
    return layout(request, body, "Ürün Önerileri – Admin")

@app.get("/admin/product/suggestion/approve/{suggestion_id}")
async def admin_product_suggestion_approve(request: Request, suggestion_id: int):
    """Admin ürün önerisi onaylama"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        suggestion = s.get(ProductSuggestion, suggestion_id)
        if not suggestion:
            return RedirectResponse("/admin/product/suggestions?error=not_found", status_code=302)
        
        # Ürünü oluştur
        product = Product(
            name=suggestion.product_name,
            category=suggestion.category,
            unit=suggestion.unit,
            description=suggestion.description,
            is_active=True,
            created_by=f"suggestion_{suggestion.business_id}",
            created_at=datetime.utcnow()
        )
        
        s.add(product)
        
        # Öneriyi onayla
        suggestion.status = "approved"
        suggestion.reviewed_at = datetime.utcnow()
        s.add(suggestion)
        
        s.commit()
    
    return RedirectResponse("/admin/product/suggestions?success=approved", status_code=302)

@app.get("/admin/product/suggestion/reject/{suggestion_id}")
async def admin_product_suggestion_reject(request: Request, suggestion_id: int):
    """Admin ürün önerisi reddetme"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        suggestion = s.get(ProductSuggestion, suggestion_id)
        if not suggestion:
            return RedirectResponse("/admin/product/suggestions?error=not_found", status_code=302)
        
        suggestion.status = "rejected"
        suggestion.reviewed_at = datetime.utcnow()
        s.add(suggestion)
        s.commit()
    
    return RedirectResponse("/admin/product/suggestions?success=rejected", status_code=302)

# ===========================================
# ADMIN - BUSINESS MANAGEMENT
# ===========================================

@app.get("/admin/businesses", response_class=HTMLResponse)
async def admin_businesses_list(request: Request):
    """Admin işletme listesi"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        businesses = s.exec(
            select(Business).order_by(Business.created_at.desc())
        ).all()
        
        business_rows = ""
        for b in businesses:
            status_badge = ""
            if not b.is_approved:
                status_badge = '<span class="text-xs bg-amber-100 text-amber-800 px-2 py-1 rounded">⏳ Bekliyor</span>'
            elif not b.is_active:
                status_badge = '<span class="text-xs bg-red-100 text-red-800 px-2 py-1 rounded">⛔ Pasif</span>'
            else:
                status_badge = '<span class="text-xs bg-emerald-100 text-emerald-800 px-2 py-1 rounded">✅ Aktif</span>'
            
            business_rows += f"""
            <tr class="border-b hover:bg-gray-50">
                <td class="py-2 px-4">
                    <div class="font-semibold">{b.business_name}</div>
                    <div class="text-xs text-gray-500">{b.email}</div>
                </td>
                <td class="py-2 px-4 text-sm">{b.contact_person or '-'}</td>
                <td class="py-2 px-4 text-sm">{b.district}</td>
                <td class="py-2 px-4">{status_badge}</td>
                <td class="py-2 px-4 text-xs text-gray-500">{b.created_at.strftime('%d.%m.%Y')}</td>
                <td class="py-2 px-4 text-sm">
                    {'<a href="/admin/business/approve/' + str(b.id) + '" class="text-emerald-600 hover:underline mr-2">✅ Onayla</a>' if not b.is_approved else ''}
                    <a href="/admin/business/toggle/{b.id}" 
                       class="text-indigo-600 hover:underline mr-2">{'Pasifleştir' if b.is_active else 'Aktifleştir'}</a>
                    <a href="/admin/business/delete/{b.id}" 
                       onclick="return confirm('Bu işletmeyi silmek istediğinizden emin misiniz?')"
                       class="text-red-600 hover:underline">Sil</a>
                </td>
            </tr>
            """
    
    body = f"""
    <div class="max-w-6xl mx-auto">
        <div class="bg-white card p-6">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">İşletme Yönetimi</h2>
                <a href="/admin" 
                   class="border border-gray-300 hover:bg-gray-50 px-4 py-2 rounded-lg">
                    ← Admin Panel
                </a>
            </div>
            
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="py-2 px-4 text-left text-sm font-medium">İşletme</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Yetkili</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">İlçe</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Durum</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">Kayıt</th>
                            <th class="py-2 px-4 text-left text-sm font-medium">İşlem</th>
                        </tr>
                    </thead>
                    <tbody>
                        {business_rows or '<tr><td colspan="6" class="py-4 text-center text-gray-500">Henüz işletme yok</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    
    return layout(request, body, "İşletme Yönetimi – Admin")

@app.get("/admin/business/approve/{business_id}")
async def admin_business_approve(request: Request, business_id: int):
    """Admin işletme onaylama"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        business = s.get(Business, business_id)
        if business:
            business.is_approved = True
            business.updated_at = datetime.utcnow()
            s.add(business)
            s.commit()
    
    return RedirectResponse("/admin/businesses?success=approved", status_code=302)

@app.get("/admin/business/toggle/{business_id}")
async def admin_business_toggle(request: Request, business_id: int):
    """Admin işletme aktif/pasif toggle"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        business = s.get(Business, business_id)
        if business:
            business.is_active = not business.is_active
            business.updated_at = datetime.utcnow()
            s.add(business)
            s.commit()
    
    return RedirectResponse("/admin/businesses", status_code=302)

@app.get("/admin/business/delete/{business_id}")
async def admin_business_delete(request: Request, business_id: int):
    """Admin işletme silme"""
    red = require_admin(request)
    if red:
        return red
    
    with get_session() as s:
        business = s.get(Business, business_id)
        if business:
            s.delete(business)
            s.commit()
    
    return RedirectResponse("/admin/businesses?success=deleted", status_code=302)

# ===========================================
# ADMIN - SEED PRODUCTS
# ===========================================

@app.get("/admin/seed/products", response_class=HTMLResponse)
async def admin_seed_products_page(request: Request):
    """Admin seed products sayfası"""
    red = require_admin(request)
    if red:
        return red
    
    body = """
    <div class="bg-white card p-6 max-w-md mx-auto">
        <h2 class="text-lg font-bold mb-3">Seed: Temel Ürünler</h2>
        <p class="text-sm text-gray-600 mb-4">
            40+ temel ürünü veritabanına ekler (süt, et, temel gıda, sebze-meyve, vb.)
        </p>
        <form method="post" action="/admin/seed/products">
            <button class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg w-full">
                Ürünleri Yükle
            </button>
        </form>
        <a href="/admin" class="block text-center text-sm text-gray-600 hover:underline mt-3">← Admin Panel</a>
    </div>
    """
    
    return layout(request, body, "Seed Ürünler – Admin")

@app.post("/admin/seed/products")
async def admin_seed_products_post(request: Request):
    """Admin seed products işlemi"""
    red = require_admin(request)
    if red:
        return red
    
    count = seed_products()
    
    return JSONResponse({"ok": True, "added": count, "message": f"{count} ürün eklendi"})