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

        await db.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            invited_id INTEGER PRIMARY KEY,
            referrer_id INTEGER NOT NULL,
            created_at INTEGER
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

        await db.commit()


# ---------- SETTINGS ----------

async def get_setting(key: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,)
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO settings(key,value)
        VALUES(?,?)
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

        cur = await db.execute(
            "SELECT 1 FROM users WHERE user_id=?",
            (user_id,)
        )

        return await cur.fetchone() is not None


async def set_pending_referrer(invited_id: int, pending_referrer_id: int):
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        UPDATE users
        SET pending_referrer_id=?
        WHERE user_id=?
        """, (pending_referrer_id, invited_id))

        await db.commit()


# ---------- REFERRALS ----------

async def confirm_referral(invited_id: int, referrer_id: int, ts: int) -> bool:

    if invited_id == referrer_id:
        return False

    async with aiosqlite.connect(DB_NAME) as db:

        try:
            await db.execute("""
                INSERT OR IGNORE INTO referrals(invited_id, referrer_id, created_at)
                VALUES(?,?,?)
            """, (invited_id, referrer_id, ts))

            await db.execute("""
                UPDATE users
                SET referrer_id=?, pending_referrer_id=NULL
                WHERE user_id=?
            """, (referrer_id, invited_id))

            await db.commit()

            return True

        except:
            return False


async def referral_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute("""
        SELECT COUNT(*) FROM referrals
        WHERE referrer_id=?
        """, (user_id,))

        (cnt,) = await cur.fetchone()
        return cnt


async def top_referrers(limit: int = 10):
    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute("""
        SELECT r.referrer_id, COUNT(*) cnt
        FROM referrals r
        GROUP BY r.referrer_id
        ORDER BY cnt DESC
        LIMIT ?
        """, (limit,))

        rows = await cur.fetchall()

        result = []

        for uid, cnt in rows:
            cur2 = await db.execute("""
            SELECT username, full_name
            FROM users WHERE user_id=?
            """, (uid,))

            u = await cur2.fetchone()

            if u:
                username, full_name = u
            else:
                username, full_name = "", ""

            result.append((uid, username or "", full_name or "", cnt))

        return result


async def export_all_ranked():
    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute("""
        SELECT u.full_name, u.username,
        COALESCE(t.cnt,0)
        FROM users u
        LEFT JOIN (
            SELECT referrer_id, COUNT(*) cnt
            FROM referrals
            GROUP BY referrer_id
        ) t ON t.referrer_id=u.user_id
        ORDER BY cnt DESC
        """)

        return await cur.fetchall()

import shutil
import asyncio

DB_NAME = "bot.db"


async def backup_task():

    while True:
        try:
            backup_file = "bot_backup.db"

            shutil.copy(DB_NAME, backup_file)

        except:
            pass

        await asyncio.sleep(600)  # 10 minut
