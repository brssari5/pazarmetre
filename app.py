# -*- coding: utf-8 -*-
"""
Pazarmetre – Lokasyona Göre Fiyat Vitrini (tek dosya, modern UI)
Çalıştır (lokal):  uvicorn app:app --reload --port 8000
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Tuple
from pathlib import Path
import os, json, sqlite3

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select

# ================== Ayarlar ==================
# Not: PAZAR_DB ortam değişkeni verilirse onu kullanır (ör. sqlite:////var/data/pazarmetre.db)
DB_URL = os.environ.get("PAZAR_DB", "sqlite:///pazarmetre.db")
ADMIN_PASSWORD = os.environ.get("PAZARMETRE_ADMIN", "pazarmetre123")  # ortam değişkeniyle değiştir
DAYS_STALE = 2  # eski fiyatları gizleme eşiği (gün)

# ================== Modeller ==================
class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    unit: Optional[str] = "kg"
    featured: bool = Field(default=False)

class Store(SQLModel, table=True):
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

# ================ DB & App =====================
engine = create_engine(DB_URL, echo=False)
SQLModel.metadata.create_all(engine)

def ensure_featured_column():
    # sqlite:///... -> gerçek dosya yolu
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

ensure_featured_column()

app = FastAPI(title="Pazarmetre")

# Opsiyonel statik
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

def get_session():
    return Session(engine)

# Basit sağlık kontrolü (deploy platformları için)
@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")

# =============== Mini lokasyon verisi (tek lokasyon) ===============
LOC_JSON = {
    "provinces": [
        {
            "name": "Sakarya",
            "districts": [
                {"name": "Hendek", "neighborhoods": ["Merkez", "Akova", "Bayraktepe", "Yeni Mah."]}
            ],
        }
    ]
}

# =============== Yardımcılar ===============
def get_loc(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    return (request.cookies.get("city"), request.cookies.get("district"), request.cookies.get("nb"))

def is_admin(request: Request) -> bool:
    return request.cookies.get("adm", "") == ADMIN_PASSWORD

def require_admin(request: Request):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

def only_fresh_and_latest(rows: List[tuple], days_stale: int = DAYS_STALE) -> List[tuple]:
    if not rows:
        return []
    today = datetime.utcnow().date()
    fresh = [(o, st) for (o, st) in rows if (today - o.created_at.date()).days <= days_stale]
    if not fresh:
        return []
    latest_day = max(o.created_at.date() for (o, _st) in fresh)
    latest = [(o, st) for (o, st) in fresh if o.created_at.date() == latest_day]
    latest.sort(key=lambda t: (t[0].price, -t[0].created_at.timestamp()))
    return latest

TAILWIND_CDN = "https://cdn.tailwindcss.com"

def header_right_html(request: Request) -> str:
    city, dist, nb = get_loc(request)
    if city and dist:
        loc_text = f"📍 {city} / {dist}" + (f" / {nb}" if nb else "")
    else:
        loc_text = "📍 Lokasyon Seç"
    return f"""
      <a href="/admin" class="text-sm px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 shadow transition">Admin</a>
      <a href="/lokasyon" class="text-sm px-3 py-2 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition">{loc_text}</a>
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
    <footer class="mt-10 text-xs text-gray-400">© {datetime.utcnow().year} Pazarmetre</footer>
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
async def location_set(city: str = Form(...), district: str = Form(...), nb: str = Form("")):
    resp = RedirectResponse("/", status_code=302)
    max_age = 60 * 60 * 24 * 90
    resp.set_cookie("city", city, max_age=max_age, samesite="lax")
    resp.set_cookie("district", district, max_age=max_age, samesite="lax")
    if nb:
        resp.set_cookie("nb", nb, max_age=max_age, samesite="lax")
    else:
        resp.delete_cookie("nb")
    return resp

@app.get("/setloc")
async def setloc(city: str, district: str, nb: str = "", next: str = "/"):
    resp = RedirectResponse(next, status_code=302)
    max_age = 60 * 60 * 24 * 90
    resp.set_cookie("city", city, max_age=max_age, samesite="lax")
    resp.set_cookie("district", district, max_age=max_age, samesite="lax")
    if nb:
        resp.set_cookie("nb", nb, max_age=max_age, samesite="lax")
    else:
        resp.delete_cookie("nb")
    return resp

@app.get("/l/{city}/{district}")
async def loc_short_no_nb(city: str, district: str):
    return await setloc(city, district)

@app.get("/l/{city}/{district}/{nb}")
async def loc_short(city: str, district: str, nb: str):
    return await setloc(city, district, nb)

# =============== Ana Sayfa ===============
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    city, dist, nb = get_loc(request)
    if not city or not dist:
        return RedirectResponse("/lokasyon", status_code=302)

    with get_session() as s:
        prods = s.exec(select(Product).where(Product.featured == True)).all()
        cards = []
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

            if nb:
                rows_nb = [(o, st) for (o, st) in rows if (st.neighborhood or "").lower() == nb.lower()]
                if rows_nb:
                    rows = rows_nb

            rows = only_fresh_and_latest(rows)
            if not rows:
                continue

            off, st = rows[0]
            is_new = (datetime.utcnow() - off.created_at).total_seconds() < 86400
            new_dot = '<span class="inline-block w-2 h-2 bg-emerald-500 rounded-full mr-2"></span>' if is_new else ""

            # Mahalle sadece kullanıcı mahalle seçtiyse gösterilir (Merkez dahil)
            loc_label = st.district
            if nb:
                loc_label = st.neighborhood or st.district

            cards.append(
                f"""
              <a href="/urun?name={p.name}" class="block bg-white card p-4 transition">
                <div class="flex items-start justify-between">
                  <div>
                    <div class="text-lg font-bold flex items-center">{new_dot}{p.name}</div>
                    <div class="text-[11px] text-gray-500 mt-1">1 {p.unit}</div>
                  </div>
                  <div class="text-right">
                    <div class="chip bg-accent-50 text-accent-700">{off.price:.2f} {off.currency}</div>
                    <div class="chip bg-gray-100 text-gray-700 mt-1">{st.name} · {loc_label}</div>
                    <div class="text-[10px] text-gray-400 mt-1">{off.created_at.strftime('%d.%m.%Y')}</div>
                  </div>
                </div>
              </a>
            """
            )
    body = (
        "<div class='bg-white card p-6 text-gray-600'>Bu lokasyonda vitrin ürünü yok. Admin’den ekleyin veya <a class='text-indigo-600' href='/lokasyon'>lokasyonu değiştirin</a>.</div>"
        if not cards else f"<div class='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>{''.join(cards)}</div>"
    )
    return layout(request, body, "Pazarmetre – Vitrin")

# =============== Ürün Detay ===============
@app.get("/urun", response_class=HTMLResponse)
async def product_detail(request: Request, name: str):
    city, dist, nb = get_loc(request)
    with get_session() as s:
        prod = s.exec(select(Product).where(Product.name == name)).first()
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
        return layout(request, "<div class='bg-white card p-6'>Bu lokasyonda teklif yok.</div>", name)

    if nb:
        rows_nb = [(o, st) for (o, st) in rows if (st.neighborhood or "").lower() == nb.lower()]
        if rows_nb:
            rows = rows_nb

    rows = only_fresh_and_latest(rows)
    if not rows:
        return layout(request, "<div class='bg-white card p-6'>Taze (son gün veya son 2 gün) fiyat bulunamadı.</div>", name)

    best_price = min(o.price for (o, _st) in rows)
    is_adm = is_admin(request)

    trs = []
    for off, st in rows:
        is_best = (off.price == best_price)
        badge = "🟢 En Ucuz" if is_best else ""
        tr_cls = "bg-emerald-50" if is_best else "odd:bg-gray-50"
        nb_text = (st.neighborhood or "") if nb else ""
        addr_left = (nb_text + " – ") if nb_text else ""

        # Sil butonu: fetch ile satır sil
        del_btn = (
            f"<button type='button' onclick='delOffer({off.id}, this)' class='text-xs px-2 py-1 rounded border text-red-700 border-red-200 hover:bg-red-50'>Sil</button>"
        ) if is_adm else ""

        trs.append(
            f"<tr class='{tr_cls} border-b'>"
            f"<td class='py-2 font-medium'>{st.name}</td>"
            f"<td class='py-2 text-gray-600'>{addr_left}{st.address or ''}</td>"
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
        if(r.ok){
          const tr = btn.closest('tr'); if(tr) tr.remove();
        } else {
          alert('Silinemedi');
        }
      }
    </script>
    """

    body = f"""
    <div class="bg-white card p-4">
      <div class="flex items-center justify-between mb-3">
        <div class="text-lg font-bold">{name}</div>
        <a href="/" class="text-sm text-indigo-600">← Vitrine dön</a>
      </div>
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
    return layout(request, body, f"{name} – Pazarmetre")

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

@app.get("/admin", response_class=HTMLResponse)
async def admin_step1(request: Request):
    red = require_admin(request)
    if red: return red
    body = """
    <div class="bg-white card p-6 max-w-xl mx-auto">
      <h2 class="text-lg font-bold mb-3">1) Ürün Adını Gir</h2>
      <form method="get" action="/admin/bulk" class="space-y-3">
        <input class="w-full border rounded-lg p-2" name="product_name" placeholder="Örn: dana kıyma" required>
        <label class="inline-flex items-center gap-2 text-sm"><input type="checkbox" name="featured" value="1"> Vitrine ekle</label>
        <button class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg">İlerle</button>
      </form>
      <p class="text-xs text-gray-500 mt-2">Kayıtlar, ziyaretçinin seçtiği lokasyona göre listelenir.</p>
    </div>"""
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

    body = f"""
    <div class="bg-white card p-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-bold">2) Çoklu Satır (Mağaza / Fiyat / Adres)</h2>
        <a class="text-sm text-gray-600" href="/admin">Geri</a>
      </div>
      <div class="text-xs text-gray-600 mb-3">Öneri: Mağaza adı net yazın (örn: Migros Hendek Şubesi)</div>
      <form method="post" action="/admin/bulk" id="bulkform">
        <input type="hidden" name="product_name" value="{product_name}">
        <input type="hidden" name="featured" value="{feat_flag}">
        <div class="text-sm text-gray-600 mb-2">Seçili lokasyon: <b>{loc_line}</b></div>
        <div id="rows" class="space-y-2">{rows}</div>
        <div class="mt-3 flex items-center gap-2">
          <button type="button" onclick="addRow()" class="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg">Satır Ekle</button>
          <button class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg">Kaydet</button>
        </div>
      </form>
    </div>
    {addrow_script}
    """
    return layout(request, body, "Admin – Adım 2")

def _row():
    return """
    <div class="grid md:grid-cols-3 gap-2">
      <input class="border rounded-lg p-2" name="store_name" placeholder="Mağaza adı (örn: Migros)">
      <input class="border rounded-lg p-2" name="price" placeholder="Fiyat (KG)">
      <input class="border rounded-lg p-2" name="store_address" placeholder="Market adresi (opsiyonel)">
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
):
    red = require_admin(request)
    if red: return red
    city, dist, nb = get_loc(request)
    if not city or not dist:
        return RedirectResponse("/lokasyon", status_code=302)

    p_name = product_name.strip()
    entries = []
    for nm, pr, addr in zip(store_name, price, store_address):
        nm = (nm or "").strip()
        pr = (pr or "").strip()
        addr = (addr or "").strip()  # opsiyonel
        if not (nm and pr):
            continue
        try:
            pv = float(pr.replace(",", "."))
        except ValueError:
            continue
        entries.append((nm, pv, addr))

    if not entries:
        return layout(request, "<div class='bg-white card p-4 text-amber-800 bg-amber-50'>Geçerli satır yok (Mağaza + Fiyat zorunlu).</div>", "Admin – Kayıt")

    with get_session() as s:
        p = s.exec(select(Product).where(Product.name == p_name)).first()
        if not p:
            p = Product(name=p_name, unit="kg", featured=bool(featured))
            s.add(p); s.commit(); s.refresh(p)
        else:
            if featured and not p.featured:
                p.featured = True; s.add(p); s.commit()

        for nm, pv, addr in entries:
            # adres varsa eşleşmeye kat; yoksa ad+lokasyon ile eşleş
            if addr:
                st = s.exec(select(Store).where(
                    Store.name==nm, Store.address==addr, Store.city==city,
                    Store.district==dist, Store.neighborhood==(nb or None)
                )).first()
            else:
                st = s.exec(select(Store).where(
                    Store.name==nm, Store.city==city,
                    Store.district==dist, Store.neighborhood==(nb or None),
                    Store.address==None
                )).first()
            if not st:
                st = Store(name=nm, address=(addr or None), city=city, district=dist, neighborhood=(nb or None))
                s.add(st); s.commit(); s.refresh(st)
            off = Offer(product_id=p.id, store_id=st.id, price=pv, quantity=1.0, currency="TRY", approved=True)
            s.add(off)
        s.commit()

    return RedirectResponse("/", status_code=302)

# ---- Teklif Sil (Admin) - fetch ile satır siler, "OK" döner ----
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