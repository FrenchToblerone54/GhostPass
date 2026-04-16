import json
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import core.db as db
from bot.strings import t

def _join_url(channel):
    c=(channel or "").strip()
    if not c:
        return ""
    if c.startswith("https://t.me/") or c.startswith("http://t.me/"):
        return c
    if c.startswith("@"):
        return f"https://t.me/{c[1:]}"
    return ""

async def _get_force_join_channels():
    raw=await db.get_setting("force_join_channels", "")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    single=(await db.get_setting("force_join_channel", "") or "").strip()
    return [single] if single else []

async def check_force_join(bot, uid):
    enabled=await db.get_setting("force_join_enabled", "0")
    if enabled!="1":
        return True
    channels=await _get_force_join_channels()
    if not channels:
        return True
    for channel in channels:
        try:
            m=await bot.get_chat_member(channel, uid)
            if m.status in ("member", "administrator", "creator"):
                continue
        except Exception:
            pass
        return False
    return True

async def ensure_force_join(update, ctx):
    enabled=await db.get_setting("force_join_enabled", "0")
    if enabled!="1":
        return True
    channels=await _get_force_join_channels()
    if not channels:
        return True
    uid=update.effective_user.id if update.effective_user else 0
    if not uid:
        return True
    not_joined=[]
    for channel in channels:
        try:
            m=await ctx.bot.get_chat_member(channel, uid)
            if m.status in ("member", "administrator", "creator"):
                continue
        except Exception:
            pass
        not_joined.append(channel)
    if not not_joined:
        return True
    buttons=[[InlineKeyboardButton(f"{t('btn_join_channel')} {ch}", url=u)] for ch in not_joined if (u:=_join_url(ch))]
    buttons.append([InlineKeyboardButton(t("btn_i_have_joined"), callback_data="force_join:check")])
    kb=InlineKeyboardMarkup(buttons)
    msg=t("force_join_required", channel=", ".join(not_joined))
    if update.callback_query:
        await update.callback_query.answer(t("force_join_alert"), show_alert=True)
        await update.callback_query.message.reply_text(msg, reply_markup=kb)
    elif update.effective_message:
        await update.effective_message.reply_text(msg, reply_markup=kb)
    return False
