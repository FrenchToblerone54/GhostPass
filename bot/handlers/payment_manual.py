import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
import core.db as db
from core.currency import price_for_method, fmt
from bot.strings import t
from bot.keyboards import confirm_reject_kb
from decimal import Decimal

logger = logging.getLogger(__name__)

async def cb_buy_manual(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 2)[2]
    plan=await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    amount, code, decimals=await price_for_method(plan["price"], "manual")
    u=update.effective_user
    uid=await db.upsert_user(u.id, u.username or "", u.first_name or "")
    order_id=await db.create_order(uid, plan_id, "manual", float(amount), code)
    amount_str=f"{fmt(Decimal(str(amount)), decimals, code)} {code}"
    caption=t(
        "manual_request_caption",
        first_name=u.first_name or "",
        username=f"@{u.username.lstrip('@')}" if u.username else str(u.id),
        telegram_id=u.id,
        plan_name=plan["name"],
        amount=amount_str
    )
    from config import settings
    admin_ids=await db.get_all_admin_ids(settings.ADMIN_ID)
    for admin_id in admin_ids:
        try:
            await ctx.bot.send_message(admin_id, caption, reply_markup=confirm_reject_kb(order_id))
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)
    await query.edit_message_text(t("manual_request_created"))

def get_handlers():
    return [CallbackQueryHandler(cb_buy_manual, pattern=r"^buy:manual:")]
