import asyncio
import time
import os
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramRetryAfter

from config import ADMIN_IDS, REQUIRED_CHANNELS
from db import (
    init_db,
    get_setting,
    upsert_user,
    get_user,
    referrer_exists,
    set_pending_referrer,
    confirm_referral,
    referral_count,
    top_referrers
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("BOT_TOKEN not found")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- Buttons ----------

BTN_LINK = "🔗 Referral link"
BTN_STATS = "📊 Statistika"
BTN_TOP = "🏆 Top 10"
BTN_CHECK = "✅ A'zolikni tekshirish"

ADM_EXPORT = "📥 Statistika (.txt)"
ADM_STOP = "🛑 Stop konkurs"


# ---------- Safe Send ----------

async def safe_send(chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)

    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.send_message(chat_id, text, **kwargs)

    except Exception:
        pass


# ---------- Keyboard ----------

def main_kb(is_admin: bool = False):

    rows = [
        [types.KeyboardButton(text=BTN_LINK)],
        [types.KeyboardButton(text=BTN_STATS),
         types.KeyboardButton(text=BTN_TOP)]
    ]

    if is_admin:
        rows.append([
            types.KeyboardButton(text=ADM_EXPORT),
            types.KeyboardButton(text=ADM_STOP)
        ])

    return types.ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True
    )


def check_kb():

    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=BTN_CHECK)]],
        resize_keyboard=True
    )


# ---------- Utils ----------

async def is_member_all_channels(user_id: int):

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


async def try_confirm_pending(user_id: int):

    contest = await get_setting("contest_status") or "running"

    if contest != "running":
        return

    user = await get_user(user_id)
    if not user:
        return

    pending_ref = user[3]
    already_ref = user[4]

    if not pending_ref:
        return

    if already_ref is not None:
        return

    if pending_ref == user_id:
        return

    if not await is_member_all_channels(user_id):
        return

    try:
        await confirm_referral(
            invited_id=user_id,
            referrer_id=pending_ref,
            ts=int(time.time())
        )
    except Exception:
        pass


# ---------- Handlers ----------

@dp.message(CommandStart())
async def start(message: types.Message):

    ts = int(time.time())

    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    await upsert_user(
        user_id,
        message.from_user.username or "",
        message.from_user.full_name or "",
        ts
    )

    contest = await get_setting("contest_status") or "running"

    ref_id = None
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) == 2:
        try:
            ref_id = int(parts[1])
        except Exception:
            ref_id = None

    if contest == "running":

        if ref_id and ref_id != user_id and await referrer_exists(ref_id):

            user = await get_user(user_id)

            pending = user[3] if user else None
            already = user[4] if user else None

            if pending is None and already is None:
                await set_pending_referrer(user_id, ref_id)

    if not await is_member_all_channels(user_id):

        txt = "Davom etish uchun kanalga a’zo bo‘ling:\n"
        txt += "\n".join(REQUIRED_CHANNELS)

        return await message.answer(txt, reply_markup=check_kb())

    await try_confirm_pending(user_id)

    cnt = await referral_count(user_id)

    await safe_send(
        user_id,
        f"Xush kelibsiz!\n\nTakliflar: {cnt}",
        reply_markup=main_kb(is_admin)
    )


@dp.message(lambda m: m.text == BTN_CHECK)
async def check_sub(message: types.Message):

    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    if not await is_member_all_channels(user_id):

        txt = "Hali ham a’zo emassiz.\n\n"
        txt += "\n".join(REQUIRED_CHANNELS)

        return await message.answer(txt, reply_markup=check_kb())

    await try_confirm_pending(user_id)

    await safe_send(
        user_id,
        "A’zolik tasdiqlandi. ✅",
        reply_markup=main_kb(is_admin)
    )


@dp.message(lambda m: m.text == BTN_LINK)
async def my_link(message: types.Message):

    user_id = message.from_user.id

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={user_id}"

    cnt = await referral_count(user_id)

    await safe_send(
        user_id,
        f"Referral linkingiz:\n{link}\n\nTakliflar: {cnt}"
    )


@dp.message(lambda m: m.text == BTN_STATS)
async def stats(message: types.Message):

    cnt = await referral_count(message.from_user.id)

    await safe_send(
        message.from_user.id,
        f"Sizning statistika:\nTakliflar: {cnt}"
    )


@dp.message(lambda m: m.text == BTN_TOP)
async def top10(message: types.Message):

    rows = await top_referrers(10)

    if not rows:
        return await message.answer("TOP hali yo‘q.")

    text = "🏆 TOP 10\n\n"

    for i, (uid, username, full_name, cnt) in enumerate(rows, start=1):

        name = f"@{username}" if username else (full_name or str(uid))
        text += f"{i}) {name} — {cnt}\n"

    await safe_send(message.from_user.id, text)


# ---------- Runner ----------

async def main():

    await init_db()

    while True:
        try:
            await dp.start_polling(bot)
        except Exception:
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())

