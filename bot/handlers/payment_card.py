import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
import core.db as db
import core.ghostgate as gg
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
    currency = await db.get_setting("currency", "USD")
    card_number = await db.get_setting("card_number", "")
    card_holder = await db.get_setting("card_holder", "")
    u = update.effective_user
    uid = await db.upsert_user(u.id, u.username or "", u.first_name or "")
    order_id = await db.create_order(uid, plan_id, "card", plan["price"], currency)
    ctx.user_data["pending_order_id"] = order_id
    text = t("card_payment_info", price=plan["price"], currency=currency, card_number=card_number, card_holder=card_holder)
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
    caption = t(
        "receipt_caption",
        first_name=u.first_name or "",
        username=f"@{u.username}" if u.username else str(u.id),
        telegram_id=u.id,
        plan_name=plan["name"] if plan else order["plan_id"],
        amount=order["amount"],
        currency=order["currency"]
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

async def cb_confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    order = await db.get_order(order_id)
    if not order:
        await query.edit_message_text(t("order_not_found"))
        return
    if order["status"] not in ("pending", "waiting_confirm"):
        await query.edit_message_text("Already processed.")
        return
    plan = await db.get_plan(order["plan_id"])
    if not plan:
        await query.edit_message_text("Plan not found.")
        return
    user = await db.get_user_by_id(order["user_id"])
    if not user:
        await query.edit_message_text("User not found.")
        return
    result = await gg.create_subscription(
        comment=user.get("first_name") or str(user["telegram_id"]),
        data_gb=plan["data_gb"],
        days=plan["days"],
        ip_limit=plan["ip_limit"],
        node_ids=plan["node_ids"]
    )
    if not result:
        await query.edit_message_text(t("ghostgate_error"))
        return
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    now = datetime.now(timezone.utc).isoformat()
    await db.update_order(order_id, ghostgate_sub_id=sub_id, status="paid", paid_at=now)
    admin_name = update.effective_user.first_name or str(update.effective_user.id)
    await query.edit_message_caption(
        caption=f"{query.message.caption or ''}\n\n{t('admin_confirmed', admin=admin_name, sub_id=sub_id)}",
        reply_markup=None
    )
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        from telegram import InputFile
        import io
        await ctx.bot.send_photo(user["telegram_id"], photo=io.BytesIO(qr_bytes), caption=t("sub_confirmed", url=sub_url), parse_mode="Markdown")
    else:
        await ctx.bot.send_message(user["telegram_id"], t("sub_confirmed", url=sub_url), parse_mode="Markdown")

async def cb_reject_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    ctx.user_data["rejecting_order_id"] = order_id
    from bot.keyboards import skip_kb
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(t("reject_reason_prompt"), reply_markup=skip_kb("reject:skip"))
    ctx.user_data["reject_msg_id"] = query.message.message_id

async def handle_reject_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data.pop("rejecting_order_id", None)
    if not order_id:
        return
    reason = update.message.text.strip()
    await _do_reject(order_id, reason, update, ctx)

async def cb_reject_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = ctx.user_data.pop("rejecting_order_id", None)
    if not order_id:
        return
    await _do_reject(order_id, "", update, ctx)

async def _do_reject(order_id, reason, update, ctx):
    order = await db.get_order(order_id)
    if not order:
        return
    await db.update_order(order_id, status="rejected")
    user = await db.get_user_by_id(order["user_id"])
    admin_name = update.effective_user.first_name or str(update.effective_user.id)
    if user:
        if reason:
            await ctx.bot.send_message(user["telegram_id"], t("reject_notif", reason=reason))
        else:
            await ctx.bot.send_message(user["telegram_id"], t("sub_rejected"))
    if update.callback_query:
        await update.callback_query.edit_message_caption(
            caption=f"{update.callback_query.message.caption or ''}\n\n{t('admin_rejected', admin=admin_name)}",
            reply_markup=None
        )

def get_card_conv_handler():
    from telegram.ext import ConversationHandler
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_buy_card, pattern=r"^buy:card:")],
        states={CARD_WAIT_RECEIPT: [MessageHandler(filters.PHOTO, handle_receipt)]},
        fallbacks=[CallbackQueryHandler(cb_cancel, pattern=r"^cancel$")],
        per_message=False
    )

def get_handlers():
    return [
        get_card_conv_handler(),
        CallbackQueryHandler(cb_confirm_order, pattern=r"^order:confirm:"),
        CallbackQueryHandler(cb_reject_order, pattern=r"^order:reject:"),
        CallbackQueryHandler(cb_reject_skip, pattern=r"^reject:skip$"),
    ]
