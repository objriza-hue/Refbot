import asyncio
import time

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

import os
from config import ADMIN_IDS, REQUIRED_CHANNELS

BOT_TOKEN = os.getenv("BOT_TOKEN")

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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

BTN_LINK = "🔗 Referral link"
BTN_STATS = "📊 Statistika"
BTN_TOP = "🏆 Top 10"
BTN_CHECK = "✅ A'zolikni tekshirish"

ADM_EXPORT = "📥 Statistika (.txt)"
ADM_STOP = "🛑 Stop konkurs"

# ---------- Keyboard ----------

def main_kb(is_admin: bool = False):
    rows = [
        [types.KeyboardButton(text=BTN_LINK)],
        [types.KeyboardButton(text=BTN_STATS), types.KeyboardButton(text=BTN_TOP)]
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


def share_kb(ref_link: str):
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(
                text="📨 Ulashish",
                switch_inline_query=ref_link
            )]
        ]
    )


# ---------- Utils ----------

async def build_start_text(user_id: int):
    cnt = await referral_count(user_id)
    return f"Xush kelibsiz!\n\nSiz taklif qilganlar: {cnt}"


async def get_ref_link(user_id: int):
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start={user_id}"


async def is_member_all_channels(user_id: int):
    if not REQUIRED_CHANNELS:
        return True

    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in ("left", "kicked"):
                return False
        except:
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

    if already_ref is not None:
        return

    if not pending_ref:
        return

    if pending_ref == user_id:
        return

    if not await is_member_all_channels(user_id):
        return

    ts = int(time.time())

    ok = await confirm_referral(
        invited_id=user_id,
        referrer_id=pending_ref,
        ts=ts
    )

    if ok:
        try:
            new_cnt = await referral_count(pending_ref)
            await bot.send_message(
                pending_ref,
                f"Sizda yangi referral bor! ✅\nJami: {new_cnt}"
            )
        except:
            pass


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
        text = "Konkurs to‘xtatilgan.\n\n" + await build_start_text(user_id)
        return await message.answer(text, reply_markup=main_kb(is_admin))

    # Referral parse
    ref_id = None
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) == 2:
        try:
            ref_id = int(parts[1])
        except:
            ref_id = None

    if ref_id and ref_id != user_id and await referrer_exists(ref_id):
        user = await get_user(user_id)

        pending = user[3] if user else None
        already = user[4] if user else None

        if already is None and pending is None:
            await set_pending_referrer(user_id, ref_id)

    if not await is_member_all_channels(user_id):
        txt = "Davom etish uchun kanalga a’zo bo‘ling:\n"
        txt += "\n".join(REQUIRED_CHANNELS)
        txt += "\n\nA’zo bo‘lgach: tekshirish tugmasini bosing."

        return await message.answer(txt, reply_markup=check_kb())

    await try_confirm_pending(user_id)

    text = await build_start_text(user_id)

    await message.answer(
        text,
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

    await message.answer(
        "A’zolik tasdiqlandi. ✅",
        reply_markup=main_kb(is_admin)
    )

    await message.answer(await build_start_text(user_id))


@dp.message(lambda m: m.text == BTN_LINK)
async def my_link(message: types.Message):
    user_id = message.from_user.id

    link = await get_ref_link(user_id)
    cnt = await referral_count(user_id)

    await message.answer(
        f"Referral linkingiz:\n{link}\n\nTakliflar: {cnt}",
        reply_markup=share_kb(link)
    )


@dp.message(lambda m: m.text == BTN_STATS)
async def stats(message: types.Message):
    cnt = await referral_count(message.from_user.id)
    await message.answer(f"Sizning statistika:\nTakliflar: {cnt}")


@dp.message(lambda m: m.text == BTN_TOP)
async def top10(message: types.Message):
    rows = await top_referrers(10)

    if not rows:
        return await message.answer("TOP hali yo‘q.")

    text = "🏆 TOP 10\n\n"

    for i, (uid, username, full_name, cnt) in enumerate(rows, start=1):
        name = f"@{username}" if username else (full_name or str(uid))
        text += f"{i}) {name} — {cnt}\n"

    await message.answer(text)


# ---------- Runner ----------

async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
