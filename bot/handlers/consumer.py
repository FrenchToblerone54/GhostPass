import json
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import core.db as db
import core.ghostgate as gg
from core.currency import get_base_currency, fmt_price_for_method, price_for_method, fmt
from decimal import Decimal
from bot.keyboards import main_consumer_kb, plans_kb, plan_buy_kb, back_kb, subs_list_kb, sub_detail_kb
from bot.strings import t
from bot.guards import ensure_force_join
from config import settings

logger = logging.getLogger(__name__)

async def _plans_page_size():
    raw=await db.get_setting("plans_page_size_consumer", "8")
    try:
        val=int(raw)
    except Exception:
        return 8
    if val<1:
        return 1
    if val>50:
        return 50
    return val

async def _ensure_user(update):
    u = update.effective_user
    return await db.upsert_user(u.id, u.username or "", u.first_name or "")

async def _check_banned(update):
    user = await db.get_user_by_telegram(update.effective_user.id)
    return user and user.get("is_banned")

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await _ensure_user(update)
    if await _check_banned(update):
        await update.message.reply_text(t("banned"))
        return
    if not await ensure_force_join(update, ctx):
        return
    show_trial = await db.get_setting("trial_enabled", "0")=="1" and not await db.has_trial_claim(uid)
    await update.message.reply_text(t("welcome"), reply_markup=main_consumer_kb(show_trial))

async def cmd_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update)
    if await _check_banned(update):
        return
    if not await ensure_force_join(update, ctx):
        return
    ctx.user_data["consumer_plans_page"]=0
    await _show_plans(update, ctx)

async def _show_plans(update, ctx):
    plans = await db.list_plans(active_only=True)
    base = await get_base_currency()
    per_page=await _plans_page_size()
    total=len(plans)
    max_page=max((total-1)//per_page, 0)
    page=int(ctx.user_data.get("consumer_plans_page", 0))
    page=max(0, min(page, max_page))
    ctx.user_data["consumer_plans_page"]=page
    if not plans:
        target = update.message or update.callback_query.message
        await target.reply_text(t("no_plans"))
        return
    start=page*per_page
    show=plans[start:start+per_page]
    text = t("plans_header") + "\n"
    for p in show:
        price=str(p["price"])
        if base=="IRT":
            try:
                i=int(float(p["price"]))
                if float(p["price"])==i and i>=1000 and i%1000==0:
                    price=f"{i//1000}k"
            except Exception:
                pass
        data_text=t("adm_unlimited") if float(p["data_gb"])==0 else f"{p['data_gb']} GB"
        days_text=t("adm_no_expiry") if int(p["days"])==0 else f"{p['days']}d"
        ip_text=t("adm_unlimited") if int(p["ip_limit"])==0 else str(p["ip_limit"])
        text += f"\n*{p['name']}* — {data_text} / {days_text} / {ip_text} — {price} {base}"
    if total>per_page:
        text += f"\n\n{t('plans_page_info', page=page+1, pages=max_page+1)}"
    kb = plans_kb(show, base, page, total, per_page)
    if update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def _show_subs_list(update, ctx, uid=None):
    if uid is None:
        uid = await _ensure_user(update)
    orders = await db.get_user_paid_orders(uid)
    trial = await db.get_user_trial_claim(uid)
    if trial and trial.get("ghostgate_sub_id"):
        orders.append({"plan_name": t("trial_plan_name"), "ghostgate_sub_id": trial.get("ghostgate_sub_id")})
    subs = [o for o in orders if o.get("ghostgate_sub_id")]
    if not subs:
        if update.message:
            await update.message.reply_text(t("no_active_subs"))
        else:
            await update.callback_query.edit_message_text(t("no_active_subs"))
        return
    if update.message:
        await update.message.reply_text(t("subs_list_header"), reply_markup=subs_list_kb(subs), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(t("subs_list_header"), reply_markup=subs_list_kb(subs), parse_mode="Markdown")

async def _show_sub_detail(query, sub_id):
    uid = await db.upsert_user(query.from_user.id, query.from_user.username or "", query.from_user.first_name or "")
    orders = await db.get_user_paid_orders(uid)
    trial = await db.get_user_trial_claim(uid)
    plan_name = None
    for order in orders:
        if order.get("ghostgate_sub_id")==sub_id:
            plan_name = order["plan_name"]
            break
    if plan_name is None and trial and trial.get("ghostgate_sub_id")==sub_id:
        plan_name = t("trial_plan_name")
    if plan_name is None:
        await query.edit_message_text(t("sub_removed"))
        return
    stats = await gg.get_subscription_stats(sub_id)
    if not stats:
        await query.edit_message_text(t("sub_removed"), reply_markup=back_kb("sub:list"))
        return
    data_used_gb = (stats.get("used_bytes") or 0)/1073741824
    data_total_gb = stats.get("data_gb") or 0
    expire_at = stats.get("expire_at") or t("adm_no_expiry")
    base = settings.GHOSTGATE_URL.rsplit("/", 1)[0] if "/" in settings.GHOSTGATE_URL else settings.GHOSTGATE_URL
    sub_url = f"{base}/sub/{sub_id}"
    data_str = t("adm_unlimited") if data_total_gb==0 else f"{data_total_gb} GB"
    enabled = stats.get("enabled", True)
    text = (
        f"📦 *{plan_name}*\n"
        f"📊 Data: {data_used_gb:.2f} GB / {data_str}\n"
        f"⏰ Expires: {expire_at}\n"
        f"🔗 Link: `{sub_url}`"
    )
    await query.edit_message_text(text, reply_markup=sub_detail_kb(sub_id, enabled), parse_mode="Markdown")

async def cmd_mystatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await _ensure_user(update)
    if await _check_banned(update):
        return
    if not await ensure_force_join(update, ctx):
        return
    await _show_subs_list(update, ctx, uid)

async def cb_regen_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_yes"), callback_data=f"sub:regen_yes:{sub_id}"),
        InlineKeyboardButton(t("btn_no"), callback_data=f"sub:regen_no:{sub_id}"),
    ]])
    await query.edit_message_text(t("regen_confirm"), reply_markup=kb)

async def cb_regen_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    old_sub_id = query.data.split(":", 2)[2]
    result = await gg.regen_subscription_id(old_sub_id)
    if not result:
        await query.edit_message_text(t("regen_fail"))
        return
    new_id = result["new_id"]
    new_url = result["url"]
    await db.update_ghostgate_sub_id(old_sub_id, new_id)
    await query.edit_message_text(t("regen_success", url=new_url), parse_mode="Markdown")

async def cb_regen_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    await _show_sub_detail(query, sub_id)

async def cb_toggle_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    sub = await gg.get_subscription(sub_id)
    if not sub:
        await query.edit_message_text(t("sub_toggle_fail"))
        return
    new_enabled = not sub.get("enabled", True)
    ok = await gg.update_subscription(sub_id, enabled=new_enabled)
    if not ok:
        await query.edit_message_text(t("sub_toggle_fail"))
        return
    await _show_sub_detail(query, sub_id)

async def cb_sub_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    await _show_sub_detail(query, sub_id)

async def cb_sub_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_subs_list(update, ctx)

async def cb_delete_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_yes"), callback_data=f"sub:delete_yes:{sub_id}"),
        InlineKeyboardButton(t("btn_no"), callback_data=f"sub:delete_no:{sub_id}"),
    ]])
    await query.edit_message_text(t("sub_delete_confirm"), reply_markup=kb)

async def cb_delete_sub_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    ok = await gg.delete_subscription(sub_id)
    if ok:
        await db.nullify_ghostgate_sub_id(sub_id)
        await query.edit_message_text(t("sub_deleted"))
    else:
        await query.edit_message_text(t("ghostgate_error"))

async def cb_delete_sub_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    await _show_sub_detail(query, sub_id)

async def cmd_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, ctx):
        return
    support = await db.get_setting("support_username", "")
    if support:
        await update.message.reply_text(t("support_contact", support=support))
    else:
        await update.message.reply_text(t("support_no_contact"))

async def cb_plan_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return
    plan_id = query.data.split(":", 1)[1]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    card_enabled = await db.get_setting("card_enabled", "0")=="1"
    crypto_enabled = (await db.get_setting("cryptomus_enabled", "0")=="1") or (await db.get_setting("ghostpayments_enabled", "0")=="1")
    requests_enabled = await db.get_setting("requests_enabled", "0")=="1"
    manual_enabled = await db.get_setting("manual_enabled", "1")=="1"
    support = await db.get_setting("support_username", "")
    data_text=t("adm_unlimited") if float(plan["data_gb"])==0 else f"{plan['data_gb']} GB"
    days_text=t("adm_no_expiry") if int(plan["days"])==0 else str(plan["days"])
    ip_text=t("adm_unlimited") if int(plan["ip_limit"])==0 else str(plan["ip_limit"])
    text = t("plan_detail", name=plan["name"], data_text=data_text, days_text=days_text, ip_text=ip_text)
    prices = ""
    if card_enabled:
        prices += f"\n{t('plan_price_line_card', price=await fmt_price_for_method(plan['price'], 'card'))}"
    if crypto_enabled:
        prices += f"\n{t('plan_price_line_crypto', price=await fmt_price_for_method(plan['price'], 'crypto'))}"
    if requests_enabled:
        prices += f"\n{t('plan_price_line_request', price=await fmt_price_for_method(plan['price'], 'request'))}"
    if manual_enabled:
        prices += f"\n{t('plan_price_line_manual', price=await fmt_price_for_method(plan['price'], 'manual'))}"
    if not prices:
        base = await get_base_currency()
        prices = "\n" + t("plan_price_fallback", price=f"{fmt(Decimal(str(plan['price'])), 0, base)} {base}")
    text += prices
    if not card_enabled and not crypto_enabled and not requests_enabled and not manual_enabled:
        if support:
            text += t("support_purchase", support=support)
        else:
            text += t("support_purchase_no_contact")
        await query.edit_message_text(text, reply_markup=back_kb("consumer:plans"), parse_mode="Markdown")
        return
    kb = plan_buy_kb(plan_id, card_enabled, crypto_enabled, requests_enabled, manual_enabled)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def cb_consumer_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return
    ctx.user_data["consumer_plans_page"]=0
    await _show_plans(update, ctx)

async def cb_consumer_plans_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return
    direction=query.data.split(":", 2)[2]
    page=int(ctx.user_data.get("consumer_plans_page", 0))
    ctx.user_data["consumer_plans_page"]=page-1 if direction=="prev" else page+1
    await _show_plans(update, ctx)

async def cmd_trial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = await _ensure_user(update)
    if await _check_banned(update):
        return
    if not await ensure_force_join(update, ctx):
        return
    if await db.get_setting("trial_enabled", "0")!="1":
        await update.message.reply_text(t("trial_not_available"))
        return
    if await db.has_trial_claim(uid):
        await update.message.reply_text(t("trial_already_claimed"))
        return
    data_gb = await db.get_setting("trial_data_gb", "0.5")
    expire_h = int(await db.get_setting("trial_expire_seconds", "86400"))//3600
    await update.message.reply_text(
        t("trial_info", data_gb=data_gb, expire_h=expire_h),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("btn_trial_claim"), callback_data="trial:claim")],
            [InlineKeyboardButton(t("btn_back"), callback_data="trial:back")],
        ]),
        parse_mode="Markdown"
    )

async def cb_trial_claim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await ensure_force_join(update, ctx):
        return
    uid = await db.upsert_user(query.from_user.id, query.from_user.username or "", query.from_user.first_name or "")
    if await db.get_setting("trial_enabled", "0")!="1":
        await query.edit_message_text(t("trial_not_available"))
        return
    if await db.has_trial_claim(uid):
        await query.edit_message_text(t("trial_already_claimed"))
        return
    data_gb = float(await db.get_setting("trial_data_gb", "0.5"))
    expire_s = int(await db.get_setting("trial_expire_seconds", "86400"))
    node_ids = json.loads(await db.get_setting("trial_node_ids", "[]"))
    trial_start_after_use=await db.get_setting("trial_start_after_use", "1")
    result = await gg.create_subscription(
        comment=f"Trial-{query.from_user.id}",
        data_gb=data_gb,
        days=3650 if trial_start_after_use=="1" else max(1, (expire_s+86399)//86400),
        ip_limit=1,
        node_ids=node_ids,
        expire_after_first_use_seconds=expire_s if trial_start_after_use=="1" else None
    )
    if not result or not result.get("id"):
        await query.edit_message_text(t("service_unavailable"))
        return
    await db.create_trial_claim(uid, result["id"])
    await ctx.bot.send_message(
        chat_id=query.from_user.id,
        text=t("trial_claimed", url=result.get("url", "")),
        reply_markup=main_consumer_kb(show_trial=False),
        parse_mode="Markdown"
    )
    await query.delete_message()

async def cb_trial_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.delete_message()

async def handle_menu_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text==t("btn_consumer_plans"):
        await cmd_plans(update, ctx)
    elif text==t("btn_consumer_status"):
        await cmd_mystatus(update, ctx)
    elif text==t("btn_consumer_support"):
        await cmd_support(update, ctx)
    elif text==t("btn_consumer_trial"):
        await cmd_trial(update, ctx)

def get_handlers():
    return [
        CommandHandler("start", cmd_start),
        CommandHandler("plans", cmd_plans),
        CommandHandler("mystatus", cmd_mystatus),
        CommandHandler("support", cmd_support),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons),
        CallbackQueryHandler(cb_plan_detail, pattern=r"^plan:[A-Za-z0-9_-]{20}$"),
        CallbackQueryHandler(cb_consumer_plans, pattern=r"^consumer:plans$"),
        CallbackQueryHandler(cb_consumer_plans_page, pattern=r"^consumer:plans_page:(prev|next)$"),
        CallbackQueryHandler(cb_trial_claim, pattern=r"^trial:claim$"),
        CallbackQueryHandler(cb_trial_back, pattern=r"^trial:back$"),
        CallbackQueryHandler(cb_sub_list, pattern=r"^sub:list$"),
        CallbackQueryHandler(cb_sub_detail, pattern=r"^sub:detail:"),
        CallbackQueryHandler(cb_delete_sub_confirm, pattern=r"^sub:delete_yes:"),
        CallbackQueryHandler(cb_delete_sub_cancel, pattern=r"^sub:delete_no:"),
        CallbackQueryHandler(cb_delete_sub, pattern=r"^sub:delete:"),
        CallbackQueryHandler(cb_regen_sub, pattern=r"^sub:regen:[^_]"),
        CallbackQueryHandler(cb_regen_confirm, pattern=r"^sub:regen_yes:"),
        CallbackQueryHandler(cb_regen_cancel, pattern=r"^sub:regen_no:"),
        CallbackQueryHandler(cb_toggle_sub, pattern=r"^sub:toggle:"),
    ]
