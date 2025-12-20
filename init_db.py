#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veritabanı Başlatma Scripti
Bu script veritabanını başlatır ancak mevcut verilere dokunmaz.
İlk kurulumda veya tablolar eksikse kullanılır.
"""

import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine

# app.py'den model tanımlarını import et
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def init_database():
    """Veritabanını başlat (mevcut verilere dokunmadan)"""
    
    # Veritabanı URL'ini al
    DB_URL = os.environ.get("PAZAR_DB", "sqlite:///pazarmetre.db")
    
    print(f"🔧 Veritabanı başlatılıyor: {DB_URL}")
    
    # Veritabanı dosyasının var olup olmadığını kontrol et
    if DB_URL.startswith("sqlite:///"):
        db_path = DB_URL.replace("sqlite:///", "")
        db_exists = Path(db_path).exists()
        
        if db_exists:
            print(f"✅ Veritabanı dosyası zaten mevcut: {db_path}")
            print("ℹ️  Mevcut veriler korunacak, sadece eksik tablolar oluşturulacak.")
        else:
            print(f"🆕 Yeni veritabanı dosyası oluşturulacak: {db_path}")
    
    # Engine oluştur
    engine = create_engine(DB_URL, echo=True)
    
    # Tabloları oluştur (mevcut tablolara dokunmaz)
    print("\n📋 Tablolar kontrol ediliyor ve eksikler oluşturuluyor...")
    SQLModel.metadata.create_all(engine)
    
    print("\n✅ Veritabanı hazır!")
    
    # Veritabanı bilgilerini göster
    if DB_URL.startswith("sqlite:///"):
        db_path = DB_URL.replace("sqlite:///", "")
        db_size = Path(db_path).stat().st_size if Path(db_path).exists() else 0
        print(f"\n📊 Veritabanı Bilgileri:")
        print(f"   Dosya: {db_path}")
        print(f"   Boyut: {db_size / 1024:.2f} KB")

if __name__ == "__main__":
    try:
        init_database()
    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
