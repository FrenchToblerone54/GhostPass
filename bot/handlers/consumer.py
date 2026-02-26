import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import core.db as db
import core.ghostgate as gg
from core.currency import get_base_currency, fmt_price_for_method, price_for_method, fmt
from bot.keyboards import main_consumer_kb, plans_kb, plan_buy_kb, back_kb
from bot.strings import t
from config import settings

logger = logging.getLogger(__name__)

async def _ensure_user(update):
    u = update.effective_user
    return await db.upsert_user(u.id, u.username or "", u.first_name or "")

async def _check_banned(update):
    user = await db.get_user_by_telegram(update.effective_user.id)
    return user and user.get("is_banned")

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    if await _check_banned(update):
        await update.message.reply_text(t("banned"))
        return
    await update.message.reply_text(t("welcome"), reply_markup=main_consumer_kb())

async def cmd_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    if await _check_banned(update):
        return
    await _show_plans(update, ctx)

async def _show_plans(update, ctx):
    plans = await db.list_plans(active_only=True)
    base = await get_base_currency()
    if not plans:
        target = update.message or update.callback_query.message
        await target.reply_text(t("no_plans"))
        return
    text = t("plans_header") + "\n"
    for p in plans:
        text += f"\n*{p['name']}* — {p['data_gb']} GB / {p['days']}d — {p['price']} {base}"
    kb = plans_kb(plans, base)
    if update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def cmd_mystatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await _ensure_user(update)
    if await _check_banned(update):
        return
    orders = await db.get_user_paid_orders(uid)
    if not orders:
        await update.message.reply_text(t("no_active_subs"))
        return
    for order in orders:
        sub_id = order.get("ghostgate_sub_id")
        if not sub_id:
            continue
        stats = await gg.get_subscription_stats(sub_id)
        if not stats:
            await update.message.reply_text(f"📦 *{order['plan_name']}*\n{t('sub_removed')}", parse_mode="Markdown")
            continue
        data_used_gb = (stats.get("used_bytes") or 0)/1073741824
        data_total_gb = stats.get("data_gb") or 0
        expire_at = stats.get("expire_at") or "No Expiry"
        base = settings.GHOSTGATE_URL.rsplit("/", 1)[0] if "/" in settings.GHOSTGATE_URL else settings.GHOSTGATE_URL
        sub_url = f"{base}/sub/{sub_id}"
        data_str = "Unlimited" if data_total_gb==0 else f"{data_total_gb} GB"
        text = (
            f"📦 *{order['plan_name']}*\n"
            f"📊 Data: {data_used_gb:.2f} GB / {data_str}\n"
            f"⏰ Expires: {expire_at}\n"
            f"🔗 Link: `{sub_url}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    support = await db.get_setting("support_username", "")
    if support:
        await update.message.reply_text(t("support_contact", support=support))
    else:
        await update.message.reply_text(t("support_no_contact"))

async def cb_plan_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 1)[1]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    card_enabled = await db.get_setting("card_enabled", "0")=="1"
    crypto_enabled = await db.get_setting("cryptomus_enabled", "0")=="1"
    requests_enabled = await db.get_setting("requests_enabled", "0")=="1"
    support = await db.get_setting("support_username", "")
    text = t("plan_detail", name=plan["name"], data_gb=plan["data_gb"], days=plan["days"], ip_limit=plan["ip_limit"])
    prices = ""
    if card_enabled:
        prices += f"\n{t('plan_price_line_card', price=await fmt_price_for_method(plan['price'], 'card'))}"
    if crypto_enabled:
        prices += f"\n{t('plan_price_line_crypto', price=await fmt_price_for_method(plan['price'], 'crypto'))}"
    if requests_enabled:
        prices += f"\n{t('plan_price_line_request', price=await fmt_price_for_method(plan['price'], 'request'))}"
    if not prices:
        base = await get_base_currency()
        prices = "\n" + t("plan_price_fallback", price=f"{plan['price']} {base}")
    text += prices
    if not card_enabled and not crypto_enabled and not requests_enabled:
        if support:
            text += t("support_purchase", support=support)
        else:
            text += t("support_purchase_no_contact")
        await query.edit_message_text(text, reply_markup=back_kb("consumer:plans"), parse_mode="Markdown")
        return
    kb = plan_buy_kb(plan_id, card_enabled, crypto_enabled, requests_enabled)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def cb_consumer_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_plans(update, ctx)

async def handle_menu_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text=="📦 Plans":
        await cmd_plans(update, ctx)
    elif text=="📊 My Status":
        await cmd_mystatus(update, ctx)
    elif text=="💬 Support":
        await cmd_support(update, ctx)

def get_handlers():
    return [
        CommandHandler("start", cmd_start),
        CommandHandler("plans", cmd_plans),
        CommandHandler("mystatus", cmd_mystatus),
        CommandHandler("support", cmd_support),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons),
        CallbackQueryHandler(cb_plan_detail, pattern=r"^plan:"),
        CallbackQueryHandler(cb_consumer_plans, pattern=r"^consumer:plans$"),
    ]
