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

async def ensure_force_join(update, ctx):
    enabled=await db.get_setting("force_join_enabled", "0")
    if enabled!="1":
        return True
    channel=(await db.get_setting("force_join_channel", "") or "").strip()
    if not channel:
        return True
    uid=update.effective_user.id if update.effective_user else 0
    if not uid:
        return True
    try:
        m=await ctx.bot.get_chat_member(channel, uid)
        if m.status in ("member", "administrator", "creator"):
            return True
    except Exception:
        pass
    url=_join_url(channel)
    kb=None
    if url:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_join_channel"), url=url)]])
    if update.callback_query:
        await update.callback_query.answer(t("force_join_alert"), show_alert=True)
        await update.callback_query.message.reply_text(t("force_join_required", channel=channel), reply_markup=kb)
    elif update.effective_message:
        await update.effective_message.reply_text(t("force_join_required", channel=channel), reply_markup=kb)
    return False
