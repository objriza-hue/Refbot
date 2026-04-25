import asyncio
import glob
import time
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import BOT_TOKEN, ADMIN_IDS, REQUIRED_CHANNELS
from backup import make_backup, cleanup_old_backups

from db import (
    init_db,
    get_setting,
    set_setting,
    upsert_user,
    get_user,
    referrer_exists,
    set_pending_referrer,
    confirm_referral,
    deactivate_referral,
    referral_count,
    top_referrers,
    export_all_ranked,
    get_all_user_ids,
    get_all_confirmed_referrals,
    reset_all_referrals,
    is_in_blacklist,
    clear_blacklist
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

BTN_LINK    = "Referral link"
BTN_STATS   = "Statistika"
BTN_TOP     = "Top 10"
BTN_CHECK   = "Azzolikni tekshirish"

ADM_EXPORT  = "Statistika txt"
ADM_STOP    = "Konkursni tugatish"
ADM_START   = "Konkursni boshlash"
ADM_RESET   = "Qayta boshlash"
ADM_TOP     = "Top 10 ni korish"


def main_kb(is_admin=False):
    rows = [
        [types.KeyboardButton(text=BTN_LINK)],
        [types.KeyboardButton(text=BTN_STATS), types.KeyboardButton(text=BTN_TOP)]
    ]
    if is_admin:
        rows.append([types.KeyboardButton(text=ADM_EXPORT)])
        rows.append([types.KeyboardButton(text=ADM_STOP), types.KeyboardButton(text=ADM_START)])
        rows.append([types.KeyboardButton(text=ADM_RESET), types.KeyboardButton(text=ADM_TOP)])
    return types.ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def check_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=BTN_CHECK)]],
        resize_keyboard=True
    )


def share_kb(ref_link):
    return types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="Ulashish", switch_inline_query=ref_link)
        ]]
    )


# ---------- Backup ----------

async def do_backup():
    try:
        make_backup()
        cleanup_old_backups(keep=30)
    except Exception:
        pass


async def send_daily_backup():
    while True:
        now = time.localtime()
        seconds_until_midnight = (23 - now.tm_hour) * 3600 + (59 - now.tm_min) * 60 + (60 - now.tm_sec)
        await asyncio.sleep(seconds_until_midnight)
        try:
            files = sorted(glob.glob("backups/backup_*.db"))
            if not files:
                continue
            latest = files[-1]
            doc = types.FSInputFile(latest)
            ts_str = time.strftime("%Y-%m-%d")
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_document(admin_id, doc, caption="Kunlik backup " + ts_str)
                    await asyncio.sleep(1)
                except Exception:
                    pass
        except Exception:
            pass


# ---------- Utils ----------

async def build_start_text(user_id):
    cnt = await referral_count(user_id)
    return "Xush kelibsiz!\n\nSiz taklif qilganlar: " + str(cnt)


async def get_ref_link(user_id):
    me = await bot.get_me()
    return "https://t.me/" + me.username + "?start=" + str(user_id)


async def is_member_all_channels(user_id):
    if not REQUIRED_CHANNELS:
        return True
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True


async def try_confirm_pending(user_id):
    contest = await get_setting("contest_status") or "running"
    if contest != "running":
        return

    user = await get_user(user_id)
    if not user:
        return

    pending_ref = user[3]
    already_ref = user[4]

    if already_ref is not None:
        return

    if not await is_member_all_channels(user_id):
        return

    ts = int(time.time())

    if pending_ref and pending_ref != user_id:
        ok = await confirm_referral(invited_id=user_id, referrer_id=pending_ref, ts=ts)
        if ok:
            try:
                new_cnt = await referral_count(pending_ref)
                await bot.send_message(pending_ref, "Yangi referral qoshildi!\nJami: " + str(new_cnt))
            except Exception:
                pass
            await do_backup()
        return

    import aiosqlite
    from db import DB_NAME
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT referrer_id, active FROM referrals WHERE invited_id=?", (user_id,))
        row = await cur.fetchone()

    if row and row[1] == 0:
        old_referrer = row[0]
        ok = await confirm_referral(invited_id=user_id, referrer_id=old_referrer, ts=ts)
        if ok:
            try:
                new_cnt = await referral_count(old_referrer)
                await bot.send_message(old_referrer, "Foydalanuvchi qaytib keldi! Referral qayta faollashdi.\nJami: " + str(new_cnt))
            except Exception:
                pass
            await do_backup()


# ---------- Handlers ----------

@dp.message(CommandStart())
async def start(message: types.Message):
    ts = int(time.time())
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    await upsert_user(
        user_id=user_id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
        ts=ts
    )

    contest = await get_setting("contest_status") or "running"

    if contest != "running":
        text = "Konkurs tugatilgan.\n\n" + await build_start_text(user_id)
        return await message.answer(text, reply_markup=main_kb(is_admin))

    ref_id = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2:
        try:
            ref_id = int(parts[1])
        except Exception:
            ref_id = None

    if ref_id and ref_id != user_id and await referrer_exists(ref_id):
        user = await get_user(user_id)
        pending = user[3] if user else None
        already = user[4] if user else None
        if already is None and pending is None and not await is_in_blacklist(user_id):
            await set_pending_referrer(user_id, ref_id)

    if not await is_member_all_channels(user_id):
        txt = "Davom etish uchun kanalga azo boling:\n"
        txt += "\n".join(REQUIRED_CHANNELS)
        txt += "\n\nAzo bolgach tekshirish tugmasini bosing."
        try:
            return await message.answer(txt, reply_markup=check_kb())
        except Exception:
            return

    await try_confirm_pending(user_id)
    text = await build_start_text(user_id)
    try:
        await message.answer(text, reply_markup=main_kb(is_admin))
    except Exception:
        pass


@dp.message(lambda m: m.text == BTN_CHECK)
async def check_sub(message: types.Message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    if not await is_member_all_channels(user_id):
        txt = "Hali ham azo emassiz.\n\n"
        txt += "\n".join(REQUIRED_CHANNELS)
        return await message.answer(txt, reply_markup=check_kb())

    await try_confirm_pending(user_id)
    await message.answer("Azolik tasdiqlandi.", reply_markup=main_kb(is_admin))
    await message.answer(await build_start_text(user_id))


@dp.message(lambda m: m.text == BTN_LINK)
async def my_link(message: types.Message):
    user_id = message.from_user.id
    link = await get_ref_link(user_id)
    cnt = await referral_count(user_id)
    await message.answer(
        "Referral linkingiz:\n" + link + "\n\nTakliflar: " + str(cnt),
        reply_markup=share_kb(link)
    )


@dp.message(lambda m: m.text == BTN_STATS)
async def stats(message: types.Message):
    cnt = await referral_count(message.from_user.id)
    await message.answer("Sizning statistika:\nTakliflar: " + str(cnt))


@dp.message(lambda m: m.text == BTN_TOP)
async def top10(message: types.Message):
    rows = await top_referrers(10)
    if not rows:
        return await message.answer("TOP hali yoq.")
    text = "TOP 10\n\n"
    for i, (uid, username, full_name, cnt) in enumerate(rows, start=1):
        name = "@" + username if username else (full_name or str(uid))
        text += str(i) + ") " + name + " - " + str(cnt) + "\n"
    await message.answer(text)


# ---------- ADMIN: Export ----------

@dp.message(lambda m: m.text == ADM_EXPORT)
async def adm_export(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    rows = await export_all_ranked()
    lines = ["Statistika (referral soni boyicha)\n", "=" * 40 + "\n"]
    for i, (full_name, username, cnt) in enumerate(rows, start=1):
        name = "@" + username if username else (full_name or "Noma'lum")
        lines.append(str(i) + ". " + name + " - " + str(cnt) + " ta\n")

    content = "".join(lines)
    filename = "statistika_" + str(int(time.time())) + ".txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    doc = types.FSInputFile(filename)
    await message.answer_document(doc, caption="Toliq statistika")
    try:
        os.remove(filename)
    except Exception:
        pass


# ---------- ADMIN: Tugatish ----------

@dp.message(lambda m: m.text == ADM_STOP)
async def adm_stop(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await set_setting("contest_status", "stopped")
    await message.answer(
        "Konkurs tugatildi!\n\nTop 10 ni korish uchun tugmani bosing.",
        reply_markup=main_kb(is_admin=True)
    )


# ---------- ADMIN: Top 10 korish (faqat admin) ----------

@dp.message(lambda m: m.text == ADM_TOP)
async def adm_show_top(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    rows = await top_referrers(10)
    if not rows:
        return await message.answer("TOP hali yoq.")

    text = "TOP 10 - Korib chiqing\n\n"
    for i, (uid, username, full_name, cnt) in enumerate(rows, start=1):
        name = "@" + username if username else (full_name or str(uid))
        text += str(i) + ") " + name + " - " + str(cnt) + "\n"
    text += "\nYuborish uchun quyidagi tugmani bosing."

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="Tasdiqlash - Yuborish", callback_data="confirm_top10")
        ]]
    )
    await message.answer(text, reply_markup=kb)


@dp.callback_query(lambda c: c.data == "confirm_top10")
async def confirm_top10(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    rows = await top_referrers(10)
    if not rows:
        await callback.answer("Top yoq!")
        return

    text = "KONKURS YAKUNIY TOP 10\n\n"
    for i, (uid, username, full_name, cnt) in enumerate(rows, start=1):
        name = "@" + username if username else (full_name or str(uid))
        text += str(i) + ") " + name + " - " + str(cnt) + " ta referral\n"

    for admin_id in ADMIN_IDS:
        try:
            await callback.bot.send_message(admin_id, text)
        except Exception:
            pass

    await callback.answer("Top 10 yuborildi!")
    await callback.message.edit_reply_markup(reply_markup=None)


# ---------- ADMIN: Boshlash ----------

@dp.message(lambda m: m.text == ADM_START)
async def adm_start_contest(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await clear_blacklist()
    await set_setting("contest_status", "running")
    await message.answer("Yangi konkurs boshlandi! Barcha qatnasha oladi.", reply_markup=main_kb(is_admin=True))


# ---------- ADMIN: Qayta boshlash ----------

@dp.message(lambda m: m.text == ADM_RESET)
async def adm_reset(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="Ha, qayta boshlash", callback_data="confirm_reset"),
            types.InlineKeyboardButton(text="Bekor", callback_data="cancel_reset")
        ]]
    )
    await message.answer(
        "Diqqat!\n\nBarcha referrallar 0ga tushadi.\nAvval qatnashgan userlar qayta hisoblanmaydi.\n\nDavom etasizmi?",
        reply_markup=kb
    )


@dp.callback_query(lambda c: c.data == "confirm_reset")
async def confirm_reset(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await reset_all_referrals()
    await set_setting("contest_status", "running")
    await callback.answer("Qayta boshlandi!")
    await callback.message.edit_text(
        "Konkurs qayta boshlandi!\n\nBarcha referrallar 0ga tushdi.\nAvval qatnashganlar qayta hisoblanmaydi."
    )


@dp.callback_query(lambda c: c.data == "cancel_reset")
async def cancel_reset(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer("Bekor qilindi.")
    await callback.message.edit_reply_markup(reply_markup=None)


# ---------- ADMIN: /AllUserMessage ----------

@dp.message(Command("AllUserMessage"))
async def all_user_message(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.answer("Xabar matnini kiriting.\nMisol: /AllUserMessage Salom barchaga!")

    text = parts[1].strip()
    user_ids = await get_all_user_ids()

    await message.answer("Xabar yuborilmoqda... (" + str(len(user_ids)) + " ta user)")

    sent = 0
    blocked = 0

    for i, uid in enumerate(user_ids):
        try:
            await bot.send_message(uid, text)
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            blocked += 1
        except Exception:
            blocked += 1

        if (i + 1) % 25 == 0:
            await asyncio.sleep(1)

    await message.answer(
        "Xabar yuborish yakunlandi.\n\n"
        "Yetkazildi: " + str(sent) + "\n"
        "Bloklagan/xatolik: " + str(blocked)
    )


# ---------- Fon: kanal tekshirish ----------

async def revoke_left_users():
    referrals = await get_all_confirmed_referrals()
    for invited_id, referrer_id in referrals:
        still_member = await is_member_all_channels(invited_id)
        if not still_member:
            await deactivate_referral(invited_id)
            try:
                new_cnt = await referral_count(referrer_id)
                await bot.send_message(
                    referrer_id,
                    "Bir foydalanuvchi kanaldan chiqib ketdi.\n"
                    "Referral vaqtincha bekor qilindi.\n"
                    "Qaytib kirsa avtomatik tiklanadi.\n"
                    "Hozircha jami: " + str(new_cnt)
                )
            except Exception:
                pass


async def check_channel_membership_loop():
    while True:
        await asyncio.sleep(30 * 60)
        try:
            await revoke_left_users()
        except Exception:
            pass


# ---------- Global Error Handler ----------

@dp.errors()
async def global_error_handler(event, exception):
    """Barcha xatolarni jimgina tutib oladi - bot to'xtatmaydi"""
    if isinstance(exception, (TelegramForbiddenError, TelegramBadRequest)):
        return True  # Jimgina o'tkazib yuboramiz
    return False  # Boshqa xatolarni standart tartibda ko'rsatadi


# ---------- Runner ----------

async def main():
    await init_db()
    asyncio.create_task(check_channel_membership_loop())
    asyncio.create_task(send_daily_backup())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
