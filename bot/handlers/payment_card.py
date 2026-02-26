import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
import core.db as db
from core.currency import price_for_method, fmt
from bot.strings import t
from bot.keyboards import cancel_kb
from bot.states import CARD_WAIT_RECEIPT

logger = logging.getLogger(__name__)

async def cb_buy_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return ConversationHandler.END
    card_number = await db.get_setting("card_number", "")
    card_holder = await db.get_setting("card_holder", "")
    amount, code, decimals = await price_for_method(plan["price"], "card")
    price_str = f"{fmt(amount, decimals)} {code}"
    u = update.effective_user
    uid = await db.upsert_user(u.id, u.username or "", u.first_name or "")
    order_id = await db.create_order(uid, plan_id, "card", float(amount), code)
    ctx.user_data["pending_order_id"] = order_id
    text = t("card_payment_info", price=price_str, card_number=card_number, card_holder=card_holder)
    await query.edit_message_text(text, reply_markup=cancel_kb(), parse_mode="Markdown")
    return CARD_WAIT_RECEIPT

async def handle_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data.get("pending_order_id")
    if not order_id:
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text(t("invalid_input"))
        return CARD_WAIT_RECEIPT
    order = await db.get_order(order_id)
    if not order:
        return ConversationHandler.END
    file_id = update.message.photo[-1].file_id
    await db.update_order(order_id, receipt_file_id=file_id, status="waiting_confirm")
    await update.message.reply_text(t("receipt_received"))
    plan = await db.get_plan(order["plan_id"])
    u = update.effective_user
    amount_str = f"{order['amount']} {order['currency']}"
    caption = t(
        "receipt_caption",
        first_name=u.first_name or "",
        username=f"@{u.username}" if u.username else str(u.id),
        telegram_id=u.id,
        plan_name=plan["name"] if plan else order["plan_id"],
        amount=amount_str
    )
    from bot.keyboards import confirm_reject_kb
    from config import settings
    admin_ids = await db.get_all_admin_ids(settings.ADMIN_ID)
    for admin_id in admin_ids:
        try:
            await ctx.bot.send_photo(admin_id, file_id, caption=caption, reply_markup=confirm_reject_kb(order_id))
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)
    ctx.user_data.pop("pending_order_id", None)
    return ConversationHandler.END

async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = ctx.user_data.pop("pending_order_id", None)
    if order_id:
        await db.update_order(order_id, status="cancelled")
    await query.edit_message_text("❌ Cancelled.")
    return ConversationHandler.END

def get_card_conv_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_buy_card, pattern=r"^buy:card:")],
        states={CARD_WAIT_RECEIPT: [MessageHandler(filters.PHOTO, handle_receipt)]},
        fallbacks=[CallbackQueryHandler(cb_cancel, pattern=r"^cancel$")],
        per_message=False
    )

def get_handlers():
    return [get_card_conv_handler()]
