#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veritabanı Yedekleme ve Geri Yükleme Scripti
"""

import os
import sys
import shutil
import argparse
from datetime import datetime
from pathlib import Path

def get_db_path():
    """Veritabanı dosya yolunu al"""
    DB_URL = os.environ.get("PAZAR_DB", "sqlite:///pazarmetre.db")
    if DB_URL.startswith("sqlite:///"):
        return DB_URL.replace("sqlite:///", "")
    else:
        print("❌ Hata: Sadece SQLite veritabanları destekleniyor")
        sys.exit(1)

def ensure_backup_dir():
    """Backup klasörünü oluştur"""
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    return backup_dir

def backup_database(db_path: str, backup_dir: Path):
    """Veritabanını yedekle"""
    db_file = Path(db_path)
    
    if not db_file.exists():
        print(f"❌ Veritabanı dosyası bulunamadı: {db_path}")
        return False
    
    # Timestamp ile yedek dosya adı oluştur
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"pazarmetre_{timestamp}.db"
    backup_path = backup_dir / backup_name
    
    try:
        # Veritabanını kopyala
        shutil.copy2(db_file, backup_path)
        
        # Dosya boyutunu hesapla
        size_kb = backup_path.stat().st_size / 1024
        
        print(f"✅ Yedekleme başarılı!")
        print(f"   Kaynak: {db_path}")
        print(f"   Hedef: {backup_path}")
        print(f"   Boyut: {size_kb:.2f} KB")
        
        # Eski yedekleri listele
        list_backups(backup_dir)
        
        return True
    except Exception as e:
        print(f"❌ Yedekleme hatası: {e}")
        return False

def list_backups(backup_dir: Path):
    """Mevcut yedekleri listele"""
    backups = sorted(backup_dir.glob("pazarmetre_*.db"), reverse=True)
    
    if not backups:
        print("\n📦 Henüz yedek bulunamadı.")
        return
    
    print(f"\n📦 Mevcut Yedekler ({len(backups)} adet):")
    print("-" * 60)
    
    for i, backup in enumerate(backups, 1):
        size_kb = backup.stat().st_size / 1024
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        print(f"{i}. {backup.name}")
        print(f"   Tarih: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Boyut: {size_kb:.2f} KB")
        if i < len(backups):
            print()

def restore_database(backup_file: str, db_path: str):
    """Veritabanını yedekten geri yükle"""
    backup_path = Path(backup_file)
    
    if not backup_path.exists():
        print(f"❌ Yedek dosyası bulunamadı: {backup_file}")
        return False
    
    db_file = Path(db_path)
    
    # Mevcut veritabanını yedekle
    if db_file.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_backup = f"{db_path}.before_restore_{timestamp}"
        shutil.copy2(db_file, safety_backup)
        print(f"🔒 Güvenlik yedegi oluşturuldu: {safety_backup}")
    
    try:
        # Yedekten geri yükle
        shutil.copy2(backup_path, db_file)
        
        size_kb = db_file.stat().st_size / 1024
        
        print(f"✅ Geri yükleme başarılı!")
        print(f"   Kaynak: {backup_path}")
        print(f"   Hedef: {db_path}")
        print(f"   Boyut: {size_kb:.2f} KB")
        
        return True
    except Exception as e:
        print(f"❌ Geri yükleme hatası: {e}")
        return False

def cleanup_old_backups(backup_dir: Path, keep: int = 10):
    """Eski yedekleri temizle"""
    backups = sorted(backup_dir.glob("pazarmetre_*.db"), reverse=True)
    
    if len(backups) <= keep:
        print(f"ℹ️  {len(backups)} yedek var, temizlemeye gerek yok (limit: {keep})")
        return
    
    to_delete = backups[keep:]
    print(f"🧹 {len(to_delete)} eski yedek silinecek...")
    
    for backup in to_delete:
        try:
            backup.unlink()
            print(f"   ✓ Silindi: {backup.name}")
        except Exception as e:
            print(f"   ✗ Silinemedi: {backup.name} ({e})")

def main():
    parser = argparse.ArgumentParser(
        description="Pazarmetre Veritabanı Yedekleme ve Geri Yükleme",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  # Yedek al
  python backup.py --backup
  
  # Yedekleri listele
  python backup.py --list
  
  # Yedekten geri yükle
  python backup.py --restore backups/pazarmetre_20231220_143022.db
  
  # Eski yedekleri temizle (son 5'i sakla)
  python backup.py --cleanup 5
        """
    )
    
    parser.add_argument("--backup", "-b", action="store_true", 
                       help="Veritabanını yedekle")
    parser.add_argument("--restore", "-r", metavar="FILE",
                       help="Veritabanını yedekten geri yükle")
    parser.add_argument("--list", "-l", action="store_true",
                       help="Mevcut yedekleri listele")
    parser.add_argument("--cleanup", "-c", type=int, metavar="N",
                       help="Eski yedekleri temizle (son N yedek saklanır)")
    
    args = parser.parse_args()
    
    # Hiç argüman verilmemişse help göster
    if not any([args.backup, args.restore, args.list, args.cleanup]):
        parser.print_help()
        sys.exit(0)
    
    db_path = get_db_path()
    backup_dir = ensure_backup_dir()
    
    # Yedek al
    if args.backup:
        print("🔄 Veritabanı yedekleniyor...")
        backup_database(db_path, backup_dir)
    
    # Yedekleri listele
    if args.list:
        list_backups(backup_dir)
    
    # Geri yükle
    if args.restore:
        print("🔄 Veritabanı geri yükleniyor...")
        restore_database(args.restore, db_path)
    
    # Temizle
    if args.cleanup:
        cleanup_old_backups(backup_dir, keep=args.cleanup)

if __name__ == "__main__":
    main()
