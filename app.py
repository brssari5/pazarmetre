# -*- coding: utf-8 -*-
"""
Pazarmetre – Lokasyona Göre Fiyat Vitrini (tek dosya, modern UI)
Çalıştır (lokal):  uvicorn app:app --reload --port 8000
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from pathlib import Path
import os, json, sqlite3, hashlib
from urllib.parse import quote, unquote

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlalchemy import func
from datetime import datetime, timedelta
from itertools import zip_longest



# ================== Ayarlar ==================
DB_URL = os.environ.get("PAZAR_DB", "sqlite:///pazarmetre.db")
ADMIN_PASSWORD = os.environ.get("PAZARMETRE_ADMIN", "pazarmetre123")
DAYS_STALE = 2  # eski fiyatları gizleme eşiği (gün)
DAYS_HARD_DROP = 7  # 7 günden eski fiyatlar tamamen düşer
ANALYTICS_SALT = os.environ.get("PAZAR_SALT", "pazarmetre_salt")  # IP hash için

# ================== Modeller ==================
class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    unit: Optional[str] = "kg"
    featured: bool = Field(default=False)

class Store(SQLModel, table=True):
    """Kanonik mağaza (ilçe başına tek satır) -> FİYAT buraya girilir"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    neighborhood: Optional[str] = None

class Offer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    store_id: int = Field(foreign_key="store.id")
    price: float
    currency: str = "TRY"
    quantity: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved: bool = True

    # senin girdiğin link
    source_url: Optional[str] = None

    # senin az önce eklediğin gramaj bilgisi
    source_weight_g: Optional[float] = None
    source_unit: Optional[str] = None

    # ↓↓↓ PRICE WATCHER’ın dolduracağı alanlar ↓↓↓
    # kaynaktan okunan saf fiyat (ör: 149.90)
    source_price: Optional[float] = None
    # watcher en son ne zaman baktı
    source_checked_at: Optional[datetime] = None
    # bizim fiyatla kaynaktaki fiyat çelişiyor mu?
    source_mismatch: bool = Field(default=False)

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
# Şema yükseltmelerini çağır
ensure_featured_column()
ensure_source_url_column()
ensure_source_weight_columns()  # ← yeni
ensure_source_price_columns()  # ← YENİ

app = FastAPI(title="Pazarmetre")

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
    response = await call_next(request)
    try:
        p = request.url.path or "/"
        # admin ve statik istekleri sayma
        if p.startswith("/admin") or p.startswith("/static") or p.startswith("/healthz"):
            return response
        with get_session() as s:
            s.add(Visit(
                path=p,
                ip_hash=_hash_ip(_client_ip(request)),
                ua=request.headers.get("user-agent", "")[:255]
            ))
            s.commit()
    except Exception:
        # analytics asla uygulamayı bozmasın
        pass
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
    if not is_admin(request):
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
    - 'days_stale' gün içinde girilmiş fiyatları 'taze' kabul eder.
    - Aynı marka (veya istersen aynı store_id) için sadece en yeni fiyat kalır.
    - 'days_stale' gününden daha eski kayıtlar gizlenir.
    """
    if not rows:
        return []

    today = datetime.utcnow().date()
    keep_from = today - timedelta(days=days_stale)

    # 'days_stale' gününden eski olanları ele
    fresh = [(o, st) for (o, st) in rows if o.created_at.date() >= keep_from]
    if not fresh:
        return []

    # Aynı marka/store için en yeni teklifi bırak
    latest = {}
    # en yeniler öne gelsin diye tarihe göre tersten sırala
    for o, st in sorted(fresh, key=lambda t: t[0].created_at, reverse=True):
        key = (
            (o.product_id, (st.name or "").casefold().strip())  # marka bazında tekille
            if per_brand else
            (o.product_id, st.id)                               # store_id bazında tekille
        )
        if key not in latest:
            latest[key] = (o, st)

    # En ucuz üstte
    return sorted(latest.values(), key=lambda t: t[0].price)

TAILWIND_CDN = "https://cdn.tailwindcss.com"

def header_right_html(request: Request) -> str:
    city, dist, nb = get_loc(request)
    loc_text = f"📍 {city or 'İl'} / {dist or 'İlçe'}" + (f" / {nb}" if nb else "")
    districts = [d["name"] for d in LOC_JSON["provinces"][0]["districts"]]
    dist_opts = "".join(f"<option value='{d}'>{d}</option>" for d in districts)
    js = """
    <script>
    (function(){
      const qs=id=>document.getElementById(id);
      const cookies = Object.fromEntries(document.cookie.split('; ').filter(Boolean).map(s=>s.split('=')));
      const citySel = qs('cityQuick'), distSel=qs('distQuick');
      if(cookies.city) citySel.value = decodeURIComponent(cookies.city);
      if(cookies.district) distSel.value = decodeURIComponent(cookies.district);
      function go(){
        const next = encodeURIComponent(location.pathname + location.search);
        location.href = `/setloc?city=${encodeURIComponent(citySel.value)}&district=${encodeURIComponent(distSel.value)}&next=${next}`;
      }
      citySel.addEventListener('change', go);
      distSel.addEventListener('change', go);
    })();
    </script>
    """
    # Mağazalar kaldırıldı; lokasyon pili tıklanamaz etiket.
    return f"""
      <div class="hidden md:flex items-center gap-2 mr-2">
        <select id="cityQuick" class="border rounded p-1 text-sm">
          <option>Sakarya</option>
        </select>
        <select id="distQuick" class="border rounded p-1 text-sm">
          {dist_opts}
        </select>
      </div>
      <a href="/admin" class="text-sm px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 shadow transition">Üye Girişi</a>
      <span class="text-sm px-3 py-2 bg-gray-100 text-gray-700 rounded-lg select-none cursor-default" title="Seçili lokasyon">{loc_text}</span>
      {js}
    """

def layout(req: Request, body: str, title: str = "Pazarmetre") -> HTMLResponse:
    right = header_right_html(req)
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
    <div class="flex items-center justify-between mb-5">
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
    city_s = (city or "").replace('"', '\\"')
    dist_s = (dist or "").replace('"', '\\"')
    nb_s = (nb or "").replace('"', '\\"')

    script_js = """
    <script>
      const LOC = __LOC__;
      const CURRENT = { city: "__CITY__", dist: "__DIST__", nb: "__NB__" };
      const citySel = document.getElementById('citySel');
      const distSel = document.getElementById('distSel');
      const nbSel   = document.getElementById('nbSel');

      function clearSel(sel, ph){ sel.innerHTML = ""; const o = document.createElement('option'); o.value=""; o.textContent=ph; sel.appendChild(o); }
      function fillCities(){
        clearSel(citySel,"İl");
        (LOC.provinces||[]).forEach(p=>{
          const o=document.createElement('option'); o.value=p.name; o.textContent=p.name;
          if(CURRENT.city && p.name.toLowerCase()===(CURRENT.city||"").toLowerCase()) o.selected=true;
          citySel.appendChild(o);
        });
        if(citySel.value) fillDistricts(citySel.value);
      }
      function fillDistricts(city){
        clearSel(distSel,"İlçe"); clearSel(nbSel,"Mahalle (opsiyonel)");
        const prov=(LOC.provinces||[]).find(p=>p.name.toLowerCase()===city.toLowerCase());
        if(!prov) return;
        (prov.districts||[]).forEach(d=>{
          const o=document.createElement('option'); o.value=d.name; o.textContent=d.name;
          if(CURRENT.dist && d.name.toLowerCase()===(CURRENT.dist||"").toLowerCase()) o.selected=true;
          distSel.appendChild(o);
        });
        if(distSel.value) fillNB(citySel.value, distSel.value);
      }
      function fillNB(city, dist){
        clearSel(nbSel,"Mahalle (opsiyonel)");
        const prov=(LOC.provinces||[]).find(p=>p.name.toLowerCase()===city.toLowerCase());
        const d=(prov?.districts||[]).find(x=>x.name.toLowerCase()===dist.toLowerCase());
        (d?.neighborhoods||[]).forEach(n=>{
          const o=document.createElement('option'); o.value=n; o.textContent=n;
          if(CURRENT.nb && n.toLowerCase()===(CURRENT.nb||"").toLowerCase()) o.selected=true;
          nbSel.appendChild(o);
        });
      }
      citySel.addEventListener('change', ()=>{ CURRENT.dist=""; CURRENT.nb=""; fillDistricts(citySel.value); });
      distSel.addEventListener('change', ()=>{ CURRENT.nb=""; fillNB(citySel.value, distSel.value); });
      fillCities();
    </script>
    """.replace("__LOC__", loc_json).replace("__CITY__", city_s).replace("__DIST__", dist_s).replace("__NB__", nb_s)

    body = f"""
    <div class="bg-white card p-6 max-w-2xl mx-auto">
      <h2 class="text-xl font-bold mb-1">Lokasyon Seç</h2>
      <p class="text-sm text-gray-500 mb-4">İl seçince ilçe; ilçe seçince mahalle otomatik dolar. Mahalle opsiyoneldir.</p>

      <form method="post" action="/lokasyon" id="locForm" class="grid md:grid-cols-3 gap-3">
        <select class="border rounded-lg p-2" name="city" id="citySel" required><option value="">İl</option></select>
        <select class="border rounded-lg p-2" name="district" id="distSel" required><option value="">İlçe</option></select>
        <select class="border rounded-lg p-2" name="nb" id="nbSel"><option value="">Mahalle (opsiyonel)</option></select>
        <button class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg md:col-span-3">Kaydet</button>
      </form>

      <div class="mt-6">
        <div class="text-sm text-gray-600 mb-2">Hızlı Seç:</div>
        <div class="flex flex-wrap gap-2">
          <a href="/setloc?city=Sakarya&district=Hendek&nb=Merkez" class="px-3 py-1 rounded-lg bg-gray-100 hover:bg-gray-200 text-sm border">Sakarya / Hendek / Merkez</a>
        </div>
      </div>
    </div>
    {script_js}
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

    items: List[Tuple[float, str]] = []

    with get_session() as s:
        prods = s.exec(select(Product).where(Product.featured == True)).all()
        if not prods:
            body = """
            <div class="bg-white card p-6 text-gray-600 text-center">
                Şu an vitrinimizde ürün bulunmuyor.
                <br>Yeni ürünler çok yakında burada olacak.
            </div>
            """
            return layout(request, body, "Pazarmetre | Vitrin")

        for p in prods:
            q = (
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
            rows = s.exec(q).all()

            # Mahalle filtresi (varsa)
            if nb:
                rows_nb = [(o, st) for (o, st) in rows if (st.neighborhood or "").lower() == nb.lower()]
                if rows_nb:
                    rows = rows_nb

            # Sadece taze ve aynı gün olanları bırak
            rows = only_fresh_and_latest(rows)
            if not rows:
                continue

            off, st = rows[0]
            best_price = off.price

            is_new = (datetime.utcnow() - off.created_at).total_seconds() < 86400
            new_dot = '<span class="inline-block w-2 h-2 bg-emerald-500 rounded-full mr-2"></span>' if is_new else ""
            loc_label = (st.neighborhood or st.district) if nb else st.district
            unit = (p.unit or "").strip()

            # TEK KART (tamamı tıklanır) – kart içinde ek link YOK
            card_html = f"""
              <a href="/urun?name={quote(p.name, safe='')}" class="block bg-white card p-4 transition hover:ring-1 hover:ring-emerald-100" role="link">
                <div class="flex items-start justify-between gap-4">
                  <div class="flex items-start gap-3">
                    <div class="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center text-xl">🥩</div>
                    <div>
                      <div class="text-lg font-bold flex items-center">{new_dot}{p.name}</div>
                      <div class="text-[11px] text-gray-500 mt-1">{('1 ' + unit) if unit else ''}</div>
                      <div class="text-[12px] text-slate-500 mt-1">{(st.name or '').title()} · {loc_label}</div>
                      <div class="text-[10px] text-gray-400 mt-1">{off.created_at.strftime('%d.%m.%Y')}</div>
                    </div>
                  </div>
                  <div class="text-right shrink-0">
                    <div class="chip bg-accent-50 text-accent-700">{off.price:.2f} {off.currency}</div>
                  </div>
                </div>
              </a>
            """
            items.append((best_price, card_html))

    if not items:
        body = "<div class='bg-white card p-6 text-gray-600'>Bu lokasyonda taze vitrin ürünü yok. Admin’den ekleyin veya <span class='text-indigo-600'>/lokasyon</span> sayfasından değiştirin.</div>"
    else:
        items.sort(key=lambda t: t[0])  # en ucuz üstte
        body = f"<div class='max-w-6xl mx-auto grid gap-4 md:grid-cols-2 lg:grid-cols-3'>{''.join(html for _, html in items)}</div>"

    return layout(request, body, "Pazarmetre – Vitrin")

# =============== Ürün Detay ===============
@app.get("/urun", response_class=HTMLResponse)
async def product_detail(request: Request, name: str):
    # URL’den gelen ismi çözüp normalize edelim
    name = unquote(name).strip()

    city, dist, nb = get_loc(request)
    with get_session() as s:
        # küçük/büyük harf duyarsız arama (daha sağlam)
        prod = s.exec(
            select(Product).where(func.lower(Product.name) == name.lower())
        ).first()
        if not prod:
            return layout(request, "<div class='bg-white card p-6'>Ürün bulunamadı.</div>", name)

        rows = s.exec(
            select(Offer, Store)
            .join(Store, Offer.store_id == Store.id)
            .where(
                Offer.product_id == prod.id,
                Offer.approved == True,
                Store.city == city,
                Store.district == dist,
            )
            .order_by(Offer.price.asc(), Offer.created_at.desc())
        ).all()

    if not rows:
        return layout(request, "<div class='bg-white card p-6'>Bu lokasyonda teklif yok.</div>", prod.name)

    if nb:
        rows_nb = [(o, st) for (o, st) in rows if (st.neighborhood or "").lower() == nb.lower()]
        if rows_nb:
            rows = rows_nb

    rows = only_fresh_and_latest(rows)
    rows = dedupe_by_brand_latest(rows)
    if not rows:
        return layout(request, "<div class='bg-white card p-6'>Taze (son gün veya son 2 gün) fiyat bulunamadı.</div>", prod.name)

    best_price = min(o.price for (o, _st) in rows)
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
    for off, st in rows:
        is_best = (off.price == best_price)
        badge = "🟢 En Ucuz" if is_best else ""
        tr_cls = "bg-emerald-50" if is_best else "odd:bg-gray-50"
        nb_text = (st.neighborhood or "") if nb else ""
        addr_left = (nb_text + " – ") if nb_text else ""

        addr_extra = (
            f"<div class='text-[11px] mt-1'><a class='text-indigo-600 hover:underline' href='{off.source_url}' target='_blank' rel='noopener'>Kaynak ↗</a></div>"
            if getattr(off, "source_url", None) else ""
        )

        del_btn = (
            f"<button type='button' onclick='delOffer({off.id}, this)' class='text-xs px-2 py-1 rounded border text-red-700 border-red-200 hover:bg-red-50'>Sil</button>"
        ) if is_adm else ""

        trs.append(
            f"<tr class='{tr_cls} border-b'>"
            f"<td class='py-2 font-medium'>{st.name}</td>"
            f"<td class='py-2 text-gray-600'>{addr_left}{st.address or ''}{addr_extra}</td>"
            f"<td class='py-2 text-right font-semibold'>{off.price:.2f} {off.currency}</td>"
            f"<td class='py-2 text-xs text-gray-500'>{off.created_at.strftime('%d.%m.%Y')}</td>"
            f"<td class='py-2'>{badge}</td>"
            f"{f'<td class=\"py-2 text-right\">{del_btn}</td>' if is_adm else ''}"
            f"</tr>"
        )

    extra_js = """
    <script>
      async function delOffer(id, btn){
        if(!confirm('Silinsin mi?')) return;
        const fd = new FormData(); fd.append('offer_id', id);
        const r = await fetch('/admin/del', { method: 'POST', body: fd });
        if(r.ok){ const tr = btn.closest('tr'); if(tr) tr.remove(); } else { alert('Silinemedi'); }
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
            <th>Mağaza</th><th>Adres</th><th class="text-right">Fiyat</th><th>Tarih</th><th></th>{'<th></th>' if is_adm else ''}
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
                    <div class="text-[10px] text-gray-400 mt-1">{off.created_at.strftime('%d.%m.%Y')}</div>
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
        # --- Kaynağı değişmiş fiyat sayısı ---
        try:
            bad_count = (
                s.exec(
                    select(func.count())
                    .select_from(Offer)
                    .where((Offer.source_mismatch == True) | (Offer.source_mismatch == 1))
                ).one()[0]
                or 0
            )
        except Exception as e:
            print("WARN /admin bad_count:", e)
            bad_count = 0

        # --- Mini ziyaret sayaçları ---
        try:
            total_visits = s.exec(
                select(func.count()).select_from(Visit)
            ).one()[0]

            last24_visits = s.exec(
                select(func.count())
                .where(Visit.ts >= datetime.utcnow() - timedelta(days=1))
            ).one()[0]
        except Exception as e:
            # Visit tablosu yoksa vs. admin paneli çökmesin
            print("WARN /admin stats:", e)
            total_visits = 0
            last24_visits = 0

    warn_html = ""
    if bad_count:
        warn_html = f"""
        <div class="mb-4 p-3 rounded-lg bg-amber-50 text-amber-800 text-sm">
          ⚠️ Kaynağı değişmiş <b>{bad_count}</b> fiyat var.
          <a class="underline" href="/admin/fiyat-uyari">Listeyi gör</a>
        </div>
        """

    body = f"""
    <div class="bg-white card p-6 max-w-xl mx-auto">

      <!-- Ziyaret Sayaçları -->
      <div class="grid grid-cols-2 gap-3 mb-4">
        <div class="p-3 rounded-lg bg-gray-50 text-center">
          <div class="text-xs text-gray-500">Toplam Ziyaret</div>
          <div class="text-2xl font-bold text-gray-800">{total_visits}</div>
        </div>
        <div class="p-3 rounded-lg bg-gray-50 text-center">
          <div class="text-xs text-gray-500">Son 24 Saat</div>
          <div class="text-2xl font-bold text-gray-800">{last24_visits}</div>
        </div>
      </div>

      {warn_html}

      <h2 class="text-lg font-bold mb-3">1) Ürün Adını Gir</h2>
      <form method="get" action="/admin/bulk" class="space-y-3">
        <input class="w-full border rounded-lg p-2" name="product_name"
               placeholder="Örn: dana kıyma" required>
        <label class="inline-flex items-center gap-2 text-sm">
          <input type="checkbox" name="featured" value="1"> Vitrine ekle
        </label>
        <button class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg">
          İlerle
        </button>
      </form>
      <p class="text-xs text-gray-500 mt-2">
        Kayıtlar, ziyaretçinin seçtiği lokasyona göre listelenir.
      </p>
    </div>
    """
    return layout(request, body, "Admin – Adım 1")
@app.get("/admin/bulk", response_class=HTMLResponse)
async def admin_bulk_form(request: Request, product_name: str, featured: str = "0"):
    red = require_admin(request)
    if red: return red
    city, dist, nb = get_loc(request)
    feat_flag = 1 if str(featured).lower() in ("1","on","true","yes") else 0
    rows = "".join([_row() for _ in range(5)])

    addrow_script = """
    <script>
      function addRow(){ const c=document.getElementById('rows'); const w=document.createElement('div'); w.innerHTML="__ROW__"; c.appendChild(w.firstElementChild); }
    </script>
    """.replace("__ROW__", _row_js())

    loc_line = f"{city or '-'} / {dist or '-'}" + (f" / {nb}" if nb else "")

    # İlçe checkbox’ları
    districts = [d["name"] for d in LOC_JSON["provinces"][0]["districts"]]
    checks = []
    for dname in districts:
        checked = "checked" if (dist and dname.lower()==(dist or "").lower()) else ""
        checks.append(f"<label class='inline-flex items-center gap-2 mr-3 mb-2'><input type='checkbox' name='districts' value='{dname}' {checked}> {dname}</label>")
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
        <h2 class="text-lg font-bold">2) Çoklu Satır (Mağaza / Fiyat / Adres)</h2>
        <a class="text-sm text-gray-600" href="/admin">Geri</a>
      </div>
      <div class="text-xs text-gray-600 mb-3">Öneri: Mağaza adı net yazın (örn: Migros Hendek Şubesi değil; sadece <b>Migros</b> – çünkü ilçe başına tek kanonik mağaza)</div>
      <form method="post" action="/admin/bulk" id="bulkform">
        <input type="hidden" name="product_name" value="{product_name}">
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
    <div class="grid md:grid-cols-5 gap-2">
      <input class="border rounded-lg p-2" name="store_name" placeholder="Mağaza adı (örn: Migros)">
      <input class="border rounded-lg p-2" name="price" placeholder="Fiyat (KG)">
      <input class="border rounded-lg p-2" name="store_address" placeholder="Market adresi (opsiyonel)">
      <input class="border rounded-lg p-2" name="source_url" placeholder="Kaynak URL (opsiyonel)">
      <input class="border rounded-lg p-2" name="source_weight_g" placeholder="Orijinal gram (örn: 400)">
    </div>"""

def _row_js():
    return _row().replace('"', '\\"').replace("\n", "")

@app.post("/admin/bulk", response_class=HTMLResponse)
async def admin_bulk_save(
    request: Request,
    product_name: str = Form(...),
    featured: int = Form(0),
    store_name: List[str] = Form([]),
    price: List[str] = Form([]),
    store_address: List[str] = Form([]),
    source_url: List[str] = Form([]),
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

    p_name = product_name.strip()

    entries: List[Tuple[str, float, str, str, float | None, str | None]] = []

    # ⚙️ HATA KAYNAĞI BURADAYDI → zip yerine zip_longest kullandık
    for nm, pr, addr, src, sw_raw, su_raw in zip_longest(
        store_name,
        price,
        store_address,
        source_url,
        source_weight_g,
        source_unit,
        fillvalue=""
    ):
        nm = (nm or "").strip()
        pr = (pr or "").strip()
        addr = (addr or "").strip()
        src = (src or "").strip()
        sw_raw = (sw_raw or "").strip()
        su_raw = (su_raw or "").strip()

        if not (nm and pr):
            continue

        try:
            pv = float(pr.replace(",", "."))
        except ValueError:
            continue

        # gramaj sayıya çevrilir
        sw: float | None = None
        if sw_raw:
            try:
                sw = float(sw_raw)
            except ValueError:
                sw = None

        su: str | None = su_raw or None

        entries.append((nm, pv, addr, src, sw, su))

    if not entries:
        return layout(
            request,
            "<div class='bg-white card p-4 text-amber-800 bg-amber-50'>Geçerli satır yok (Mağaza + Fiyat zorunlu).</div>",
            "Admin – Kayıt",
        )

    BRAND_CANON = {"migros": "Migros", "a101": "A101", "bim": "BİM"}

    with get_session() as s:
        p = s.exec(select(Product).where(Product.name == p_name)).first()
        if not p:
            p = Product(name=p_name, unit="kg", featured=bool(featured))
            s.add(p)
            s.commit()
            s.refresh(p)
        else:
            if featured and not p.featured:
                p.featured = True
                s.add(p)
                s.commit()

        target_districts = [d for d in (districts or []) if d] or [dist]

        for target_dist in target_districts:
            for nm, pv, addr, src, sw, su in entries:
                nm_clean = BRAND_CANON.get(nm.casefold(), nm)

                # mağaza bul/oluştur
                if addr:
                    st = s.exec(
                        select(Store).where(
                            func.lower(Store.name) == nm_clean.casefold(),
                            Store.address == addr,
                            Store.city == city,
                            Store.district == target_dist,
                            Store.neighborhood == None,
                        )
                    ).first()
                else:
                    st = s.exec(
                        select(Store).where(
                            func.lower(Store.name) == nm_clean.casefold(),
                            Store.city == city,
                            Store.district == target_dist,
                            Store.neighborhood == None,
                            Store.address == None,
                        )
                    ).first()

                if not st:
                    st = Store(
                        name=nm_clean,
                        address=(addr or None),
                        city=city,
                        district=target_dist,
                        neighborhood=None,
                    )
                    s.add(st)
                    s.commit()
                    s.refresh(st)

                # Teklif oluştur
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
async def admin_delete_offer(request: Request, offer_id: int = Form(...)):
    red = require_admin(request)
    if red:
        return red
    with get_session() as s:
        off = s.get(Offer, offer_id)
        if off:
            s.delete(off)
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