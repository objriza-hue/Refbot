import asyncio
import shutil
import os
import time

# Bu fayl bot.py tomonidan import qilinadi

DB_NAME = "bot.db"
BACKUP_DIR = "backups"


def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def make_backup() -> str:
    """
    bot.db ni backups/ papkasiga nusxalaydi.
    Fayl nomi: backup_YYYYMMDD_HHMMSS.db
    Qaytaradi: backup fayl yo'li
    """
    _ensure_backup_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"backup_{ts}.db")
    shutil.copy2(DB_NAME, dest)
    return dest


def cleanup_old_backups(keep: int = 30):
    """
    Eng oxirgi `keep` ta backupni saqlaydi, qolganlarini o'chiradi.
    """
    _ensure_backup_dir()
    files = sorted([
        os.path.join(BACKUP_DIR, f)
        for f in os.listdir(BACKUP_DIR)
        if f.startswith("backup_") and f.endswith(".db")
    ])
    for old in files[:-keep]:
        try:
            os.remove(old)
        except Exception:
            pass
