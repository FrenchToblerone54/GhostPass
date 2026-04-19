import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, ConversationHandler, filters
import core.db as db
import core.ghostgate as gg
from core.currency import price_for_method, fmt
from bot.strings import t
from bot.keyboards import skip_kb, cancel_kb
from bot.states import REQUEST_REASON
from bot.guards import ensure_force_join
from bot.notifications import admin_event

logger = logging.getLogger(__name__)

async def cb_buy_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return ConversationHandler.END
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return ConversationHandler.END
    discount_pct = ctx.user_data.get(f"discount_pct:{plan_id}", 0)
    discount_max = ctx.user_data.get(f"discount_max:{plan_id}", 0)
    if not discount_pct:
        offer = await db.get_active_offer_for_plan(plan_id)
        if offer:
            discount_pct = offer["discount_percent"]
            discount_max = 0
    if discount_pct:
        discount = Decimal(str(plan["price"])) * Decimal(str(discount_pct)) / 100
        if discount_max > 0:
            discount = min(discount, Decimal(str(discount_max)))
        effective_price = float(Decimal(str(plan["price"])) - discount)
    else:
        effective_price = plan["price"]
    discount_code_used = ctx.user_data.pop(f"discount_code:{plan_id}", None)
    ctx.user_data.pop(f"discount_pct:{plan_id}", None)
    ctx.user_data.pop(f"discount_max:{plan_id}", None)
    u = update.effective_user
    uid = await db.upsert_user(u.id, u.username or "", u.first_name or "")
    wallet_use = ctx.user_data.pop(f"wallet_use:{plan_id}", False)
    wallet_deduct = 0.0
    if wallet_use:
        wallet_balance = await db.get_wallet_balance(uid)
        wallet_deduct = min(wallet_balance, effective_price)
        effective_price = max(0.0, effective_price-wallet_deduct)
    amount, code, decimals = await price_for_method(effective_price, "request")
    order_id = await db.create_order(uid, plan_id, "request", float(amount), code)
    if discount_code_used:
        await db.update_order(order_id, discount_code=discount_code_used)
    if wallet_deduct>0:
        await db.update_order(order_id, wallet_credit_used=wallet_deduct)
    ctx.user_data["request_order_id"] = order_id
    await query.edit_message_text(t("reason_prompt"), reply_markup=skip_kb("request:skip_reason"))
    asyncio.create_task(admin_event(ctx.bot, "notify_payment_link", f"🔗 User *{u.first_name}* (`{u.id}`) submitted a subscription request for plan *{plan['name']}*"))
    return REQUEST_REASON

async def handle_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data.pop("request_order_id", None)
    if not order_id:
        return ConversationHandler.END
    await _notify_admins(order_id, update.message.text.strip(), update, ctx)
    await update.message.reply_text(t("request_created"))
    return ConversationHandler.END

async def cb_skip_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = ctx.user_data.pop("request_order_id", None)
    if not order_id:
        return ConversationHandler.END
    await _notify_admins(order_id, "", update, ctx)
    await query.edit_message_text(t("request_created"))
    return ConversationHandler.END

async def _notify_admins(order_id, reason, update, ctx):
    order = await db.get_order(order_id)
    if not order:
        return
    plan = await db.get_plan(order["plan_id"])
    u = update.effective_user
    caption = t(
        "request_caption",
        first_name=u.first_name or "",
        username=f"@{u.username.lstrip('@')}" if u.username else str(u.id),
        telegram_id=u.id,
        plan_name=plan["name"] if plan else order["plan_id"],
        reason=reason or t("request_no_reason")
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"req:approve:{order_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"req:decline:{order_id}"),
    ]])
    from config import settings
    admin_ids = await db.get_all_admin_ids(settings.ADMIN_ID)
    for admin_id in admin_ids:
        try:
            await ctx.bot.send_message(admin_id, caption, reply_markup=kb)
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)

async def cb_approve_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    order = await db.get_order(order_id)
    if not order or order["status"]!="pending":
        await query.edit_message_text(t("adm_already_processed"))
        return
    plan = await db.get_plan(order["plan_id"])
    user = await db.get_user_by_id(order["user_id"])
    if not plan or not user:
        return
    expire_after_first_use_seconds=None
    if int(plan["days"])>0 and await db.get_setting("plan_start_after_use", "0")=="1":
        expire_after_first_use_seconds=int(plan["days"])*86400
    paid_note=await db.get_setting("paid_note", "") or None
    result = await gg.create_subscription(
        comment=user.get("first_name") or str(user["telegram_id"]),
        data_gb=plan["data_gb"],
        days=3650 if expire_after_first_use_seconds else plan["days"],
        ip_limit=plan["ip_limit"],
        node_ids=plan["node_ids"],
        expire_after_first_use_seconds=expire_after_first_use_seconds,
        note=paid_note
    )
    if not result:
        await query.edit_message_text(t("ghostgate_error"))
        return
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    await db.update_order(order_id, ghostgate_sub_id=sub_id, status="paid", paid_at=datetime.now(timezone.utc).isoformat())
    if order.get("discount_code"):
        await db.use_discount_code(order["discount_code"])
    if order.get("wallet_credit_used", 0)>0:
        await db.adjust_wallet(order["user_id"], -order["wallet_credit_used"])
    from bot.handlers.admin import _credit_referral_commission
    asyncio.create_task(_credit_referral_commission(order["user_id"], plan["price"], ctx.bot))
    asyncio.create_task(admin_event(ctx.bot, "notify_purchase", f"💰 *Request approved*\n\n👤 {user.get('first_name','')} (`{user['telegram_id']}`)\n📦 Plan: *{plan['name']}*"))
    await query.edit_message_text(f"{query.message.text}\n\n✅ Approved", reply_markup=None)
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        import io
        await ctx.bot.send_photo(user["telegram_id"], photo=io.BytesIO(qr_bytes), caption=t("request_approved", url=sub_url), parse_mode="Markdown")
    else:
        await ctx.bot.send_message(user["telegram_id"], t("request_approved", url=sub_url), parse_mode="Markdown")

async def cb_decline_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    order = await db.get_order(order_id)
    if not order or order["status"]!="pending":
        await query.edit_message_text(t("adm_already_processed"))
        return
    await db.update_order(order_id, status="rejected")
    user = await db.get_user_by_id(order["user_id"])
    if user:
        await ctx.bot.send_message(user["telegram_id"], t("request_declined"))
    await query.edit_message_text(f"{query.message.text}\n\n❌ Declined", reply_markup=None)

def get_request_conv_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_buy_request, pattern=r"^buy:request:")],
        states={REQUEST_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason)]},
        fallbacks=[CallbackQueryHandler(cb_skip_reason, pattern=r"^request:skip_reason$")],
        per_message=False
    )

def get_handlers():
    return [
        get_request_conv_handler(),
        CallbackQueryHandler(cb_approve_request, pattern=r"^req:approve:"),
        CallbackQueryHandler(cb_decline_request, pattern=r"^req:decline:"),
    ]
