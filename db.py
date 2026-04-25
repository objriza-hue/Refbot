import aiosqlite

DB_NAME = "bot.db"


# ---------- DB INIT ----------

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            pending_referrer_id INTEGER,
            referrer_id INTEGER,
            joined_at INTEGER
        )
        """)

        # active: 1 = hisoblangan, 0 = kanaldan chiqib ketdi (lekin saqlanadi)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            invited_id INTEGER PRIMARY KEY,
            referrer_id INTEGER NOT NULL,
            created_at INTEGER,
            active INTEGER NOT NULL DEFAULT 1
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)

        await db.execute("""
        INSERT OR IGNORE INTO settings(key,value)
        VALUES('contest_status','running')
        """)

        # Eski bazadan migrate: active ustuni yo'q bo'lsa qo'shamiz
        try:
            await db.execute("ALTER TABLE referrals ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass

        await db.commit()


# ---------- SETTINGS ----------

async def get_setting(key: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO settings(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        await db.commit()


# ---------- USERS ----------

async def upsert_user(user_id: int, username: str, full_name: str, ts: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO users(user_id, username, full_name, joined_at)
        VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        full_name=excluded.full_name
        """, (user_id, username, full_name, ts))
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("""
        SELECT user_id, username, full_name,
        pending_referrer_id, referrer_id
        FROM users WHERE user_id=?
        """, (user_id,))
        return await cur.fetchone()


async def referrer_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None


async def set_pending_referrer(invited_id: int, pending_referrer_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        UPDATE users SET pending_referrer_id=? WHERE user_id=?
        """, (pending_referrer_id, invited_id))
        await db.commit()


async def get_all_user_ids() -> list:
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]


# ---------- REFERRALS ----------

async def confirm_referral(invited_id: int, referrer_id: int, ts: int) -> bool:
    """
    Yangi referral qo'shadi YOKI eski o'chirilgan referralni qayta faollashtiradi.
    """
    if invited_id == referrer_id:
        return False

    async with aiosqlite.connect(DB_NAME) as db:
        # Avval bu invited_id uchun yozuv bormi tekshiramiz
        cur = await db.execute(
            "SELECT referrer_id, active FROM referrals WHERE invited_id=?",
            (invited_id,)
        )
        existing = await cur.fetchone()

        if existing:
            existing_referrer, is_active = existing
            if is_active == 1:
                # Allaqachon aktiv — hech narsa qilmaymiz
                return False
            else:
                # O'chirilgan edi — qayta faollashtiramiz
                await db.execute("""
                UPDATE referrals SET active=1, created_at=? WHERE invited_id=?
                """, (ts, invited_id))
                await db.execute("""
                UPDATE users SET referrer_id=?, pending_referrer_id=NULL WHERE user_id=?
                """, (existing_referrer, invited_id))
        else:
            # Yangi referral
            await db.execute("""
            INSERT INTO referrals(invited_id, referrer_id, created_at, active)
            VALUES(?,?,?,1)
            """, (invited_id, referrer_id, ts))
            await db.execute("""
            UPDATE users SET referrer_id=?, pending_referrer_id=NULL WHERE user_id=?
            """, (referrer_id, invited_id))

        await db.commit()
    return True


async def deactivate_referral(invited_id: int):
    """
    Referralni o'chirmaydi — faqat active=0 qiladi.
    Qaytib kelsa qayta faollashadi.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        UPDATE referrals SET active=0 WHERE invited_id=?
        """, (invited_id,))
        await db.execute("""
        UPDATE users SET referrer_id=NULL WHERE user_id=?
        """, (invited_id,))
        await db.commit()


async def get_all_confirmed_referrals() -> list:
    """Faqat aktiv referrallar (invited_id, referrer_id)"""
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT invited_id, referrer_id FROM referrals WHERE active=1"
        )
        return await cur.fetchall()


async def referral_count(user_id: int) -> int:
    """Faqat aktiv referrallar hisoblanadi"""
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("""
        SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND active=1
        """, (user_id,))
        (cnt,) = await cur.fetchone()
        return cnt


async def top_referrers(limit: int = 10):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("""
        SELECT r.referrer_id, COUNT(*) cnt
        FROM referrals r
        WHERE r.active=1
        GROUP BY r.referrer_id
        ORDER BY cnt DESC
        LIMIT ?
        """, (limit,))
        rows = await cur.fetchall()

        result = []
        for uid, cnt in rows:
            cur2 = await db.execute(
                "SELECT username, full_name FROM users WHERE user_id=?", (uid,)
            )
            u = await cur2.fetchone()
            username, full_name = (u[0] or "", u[1] or "") if u else ("", "")
            result.append((uid, username, full_name, cnt))

        return result



async def reset_all_referrals():
    """
    Konkursni qayta boshlash:
    - Barcha referrallar o'chiriladi (active=0 emas, to'liq delete)
    - users jadvalidagi referrer_id va pending_referrer_id NULL ga tushadi
    - Shunday qilib avval qatnashgan userlar qayta hisoblanmaydi
      (chunki referrals jadvalida yozuv yo'q, lekin invited_id blacklist da saqlanadi)
    """
    async with aiosqlite.connect(DB_NAME) as db:
        # Qatnashgan userlarni blacklistga saqlash uchun settings ga yozamiz
        cur = await db.execute("SELECT invited_id FROM referrals")
        rows = await cur.fetchall()
        blacklist = ",".join(str(r[0]) for r in rows)
        
        await db.execute("DELETE FROM referrals")
        await db.execute("UPDATE users SET referrer_id=NULL, pending_referrer_id=NULL")
        
        # Blacklistni saqlaymiz
        await db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("referral_blacklist", blacklist)
        )
        await db.commit()


async def is_in_blacklist(user_id: int) -> bool:
    """User avval referral sifatida qatnashdimi?"""
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", ("referral_blacklist",))
        row = await cur.fetchone()
        if not row or not row[0]:
            return False
        blacklist = row[0].split(",")
        return str(user_id) in blacklist


async def clear_blacklist():
    """Blacklistni tozalash (yangi konkurs boshlananda)"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("referral_blacklist", "")
        )
        await db.commit()

async def export_all_ranked():
    """Statistika uchun — faqat aktiv referrallar hisoblanadi"""
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("""
        SELECT u.full_name, u.username,
        COALESCE(t.cnt, 0)
        FROM users u
        LEFT JOIN (
            SELECT referrer_id, COUNT(*) cnt
            FROM referrals
            WHERE active=1
            GROUP BY referrer_id
        ) t ON t.referrer_id = u.user_id
        ORDER BY cnt DESC
        """)
        return await cur.fetchall()
