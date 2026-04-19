import asyncio
import logging
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)
import core.db as db
import core.ghostgate as gg
from core.updater import Updater, VERSION
from core.currency import (
    get_currencies, save_currencies, get_base_currency, set_base_currency,
    convert, fmt as cfmt, get_gp_pairs, save_gp_pairs, ALL_GP_PAIRS
)
from bot.keyboards import (
    main_admin_kb, settings_kb, back_kb, plan_actions_kb,
    user_actions_kb, sub_actions_kb, node_select_kb,
    order_detail_kb, skip_kb, cancel_kb, currencies_kb,
    method_select_kb, curr_detail_kb, base_select_kb, subs_bulk_note_kb, logs_kb,
    referral_settings_kb, referral_pkg_admin_kb, notifications_kb, wallet_adjust_kb
)
from bot.strings import t
from bot.notifications import admin_event
from bot.states import (
    WIZARD_URL, WIZARD_SUPPORT, WIZARD_CARD_NUM, WIZARD_CARD_NAME,
    WIZARD_CRYPTO_MID, WIZARD_CRYPTO_KEY, WIZARD_CURRENCY,
    PLAN_CREATE_NAME, PLAN_CREATE_DATA, PLAN_CREATE_DAYS,
    PLAN_CREATE_IP, PLAN_CREATE_PRICE, PLAN_CREATE_NODES,
    PLAN_EDIT_VALUE, PLAN_EDIT_NODES, PLAN_BULK_NODES, PLAN_BULK_CREATE_NODES, PLAN_BULK_CREATE_MATRIX, PLAN_BULK_DELETE, PLAN_BULK_NODES_PLANS,
    ADMIN_ADD_ID, ADMIN_ADD_PERMS,
    ADMIN_MANUAL_SUB_COMMENT, ADMIN_MANUAL_SUB_DATA, ADMIN_MANUAL_SUB_DAYS,
    ADMIN_MANUAL_SUB_IP, ADMIN_MANUAL_SUB_NODES, ADMIN_MANUAL_SUB_NOTE,
    SETTINGS_CARD_NUM, SETTINGS_CARD_NAME,
    SETTINGS_CRYPTO_MID, SETTINGS_CRYPTO_KEY,
    SETTINGS_SUPPORT, SETTINGS_SYNC, SETTINGS_GG_URL, SETTINGS_UPDATE_HTTP_PROXY, SETTINGS_UPDATE_HTTPS_PROXY, SETTINGS_FORCE_JOIN_CHANNEL, SETTINGS_GHOSTPAY_URL, SETTINGS_GHOSTPAY_KEY, SETTINGS_PLAN_PAGE_SIZE_CONSUMER, SETTINGS_PLAN_PAGE_SIZE_ADMIN,
    USER_SEARCH, SUB_SEARCH,
    ADMIN_REJECT_REASON,
    CURR_ADD_CODE, CURR_ADD_NAME, CURR_ADD_DECIMALS, CURR_ADD_METHODS, CURR_ADD_RATE, CURR_EDIT_RATE,
    SETTINGS_TRIAL_DATA, SETTINGS_TRIAL_EXPIRE, SETTINGS_TRIAL_NODES,
    SETTINGS_TRIAL_NOTE, SETTINGS_PAID_NOTE,
    SETTINGS_USDT_TRC20, SETTINGS_USDT_BSC, SETTINGS_USDT_POLYGON,
    SETTINGS_GP_PAIR_RATE,
    SETTINGS_USDT_TRC20_RATE, SETTINGS_USDT_BSC_RATE, SETTINGS_USDT_POL_RATE,
    ADMIN_SUB_BULK_NOTE_SELECT, ADMIN_SUB_BULK_NOTE_INPUT,
    SETTINGS_TRIAL_DISABLED_MSG, SETTINGS_TRIAL_MAX_CLAIMS,
    SETTINGS_DISCOUNT_CODE_CODE, SETTINGS_DISCOUNT_CODE_PCT, SETTINGS_DISCOUNT_CODE_MAXUSES, SETTINGS_DISCOUNT_CODE_PLANS, SETTINGS_DISCOUNT_CODE_MAX_AMOUNT,
    PLAN_BULK_ENABLE_DISABLE, PLAN_BULK_PRICE_MULTIPLY, PLAN_BULK_PRICE_FACTOR,
    OFFER_CREATE_NAME, OFFER_CREATE_DISCOUNT, OFFER_CREATE_PLANS,
    SETTINGS_START_MSG,
    REF_PKG_CREATE_NAME, REF_PKG_CREATE_CREDITS, REF_PKG_CREATE_DATA,
    REF_PKG_CREATE_DAYS, REF_PKG_CREATE_IP, REF_PKG_CREATE_NODES,
    REF_PKG_EDIT_NODES, REF_PKG_BULK_NODES_PKGS, REF_PKG_BULK_NODES,
    ADMIN_BROADCAST_INPUT, SETTINGS_NOTIF_SUB_MSG,
    ADMIN_WALLET_ADD, ADMIN_WALLET_REMOVE, SETTINGS_REF_COMMISSION_PCT
)
from config import settings

logger = logging.getLogger(__name__)

async def _get_page_size_setting(key, default_value):
    raw=await db.get_setting(key, str(default_value))
    try:
        val=int(raw)
    except Exception:
        return default_value
    if val<1:
        return 1
    if val>50:
        return 50
    return val

def _fmt_plan_price_display(price, base):
    if base=="IRT":
        try:
            i=int(float(price))
            if float(price)==i and i>=1000 and i%1000==0:
                return f"{i//1000}k"
        except Exception:
            pass
    return str(price)

def _plan_select_kb(plans, selected_ids, done_cb, back_cb, all_cb, none_cb):
    rows=[]
    for p in plans:
        mark="✅" if p["id"] in selected_ids else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {p['name']}", callback_data=f"plan_select:{p['id']}")])
    rows.append([InlineKeyboardButton(t("btn_select_all"), callback_data=all_cb), InlineKeyboardButton(t("btn_unselect_all"), callback_data=none_cb)])
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data=done_cb), InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def _all_node_ids(nodes):
    return [inbound["id"] for node in nodes for inbound in node.get("inbounds", [])]

async def _parse_plan_price_input(raw):
    base=await get_base_currency()
    norm=raw.strip().lower().replace(",", "")
    if base=="IRT" and norm.endswith("k"):
        norm=str(Decimal(norm[:-1])*Decimal("1000"))
    try:
        val=Decimal(norm)
    except Exception:
        return None
    if val<=0:
        return None
    if base=="IRT":
        if val!=val.to_integral_value():
            return None
        iv=int(val)
        if iv<1000 or iv%1000!=0:
            return None
        return float(iv)
    return float(val)

async def _is_admin(telegram_id):
    return await db.is_admin(telegram_id, settings.ADMIN_ID)

async def cmd_start_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    if not settings.GHOSTGATE_URL:
        await update.message.reply_text(t("wizard_step1"), parse_mode="Markdown")
        return WIZARD_URL
    await update.message.reply_text(t("admin_menu_title", version=VERSION), reply_markup=main_admin_kb(), parse_mode="Markdown")
    return ConversationHandler.END

async def wizard_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip().rstrip("/")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/api/status")
            r.raise_for_status()
    except Exception as e:
        await update.message.reply_text(t("wizard_step1_fail", error=str(e)))
        return WIZARD_URL
    ctx.user_data["wizard_url"] = url
    await update.message.reply_text(t("wizard_step2"), reply_markup=skip_kb("wizard:skip_support"))
    return WIZARD_SUPPORT

async def wizard_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["wizard_support"] = update.message.text.strip()
    await update.message.reply_text(t("wizard_step3a"), reply_markup=skip_kb("wizard:skip_card"))
    return WIZARD_CARD_NUM

async def wizard_skip_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["wizard_support"] = ""
    await query.edit_message_text(t("wizard_step3a"), reply_markup=skip_kb("wizard:skip_card"))
    return WIZARD_CARD_NUM

async def wizard_card_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["wizard_card_num"] = update.message.text.strip()
    await update.message.reply_text(t("wizard_step3b"), reply_markup=skip_kb("wizard:skip_card_name"))
    return WIZARD_CARD_NAME

async def wizard_card_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["wizard_card_name"] = update.message.text.strip()
    await update.message.reply_text(t("wizard_step3c"), reply_markup=skip_kb("wizard:skip_crypto"))
    return WIZARD_CRYPTO_MID

async def wizard_skip_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["wizard_card_num"] = ""
    ctx.user_data["wizard_card_name"] = ""
    await query.edit_message_text(t("wizard_step3c"), reply_markup=skip_kb("wizard:skip_crypto"))
    return WIZARD_CRYPTO_MID

async def wizard_skip_card_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["wizard_card_name"] = ""
    await query.edit_message_text(t("wizard_step3c"), reply_markup=skip_kb("wizard:skip_crypto"))
    return WIZARD_CRYPTO_MID

async def wizard_crypto_mid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["wizard_crypto_mid"] = update.message.text.strip()
    await update.message.reply_text(t("wizard_step3d"), reply_markup=skip_kb("wizard:skip_crypto"))
    return WIZARD_CRYPTO_KEY

async def wizard_crypto_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["wizard_crypto_key"] = update.message.text.strip()
    await update.message.reply_text(t("wizard_step4"))
    return WIZARD_CURRENCY

async def wizard_skip_crypto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["wizard_crypto_mid"] = ""
    ctx.user_data["wizard_crypto_key"] = ""
    await query.edit_message_text(t("wizard_step4"))
    return WIZARD_CURRENCY

async def wizard_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    await _wizard_save(ctx, currency)
    await update.message.reply_text(t("wizard_done"))
    await update.message.reply_text(t("admin_menu_title", version=VERSION), reply_markup=main_admin_kb(), parse_mode="Markdown")
    return ConversationHandler.END

async def _wizard_save(ctx, base_currency):
    url = ctx.user_data.get("wizard_url", "")
    support = ctx.user_data.get("wizard_support", "")
    card_num = ctx.user_data.get("wizard_card_num", "")
    card_name = ctx.user_data.get("wizard_card_name", "")
    crypto_mid = ctx.user_data.get("wizard_crypto_mid", "")
    crypto_key = ctx.user_data.get("wizard_crypto_key", "")
    from dotenv import set_key as dotenv_set
    dotenv_set("/opt/ghostpass/.env", "GHOSTGATE_URL", url)
    settings.GHOSTGATE_URL = url
    await db.set_setting("support_username", support)
    await set_base_currency(base_currency)
    default_currencies = [{"code": base_currency, "name": base_currency, "decimals": 0, "methods": ["card", "request"], "rate": "1"}]
    await save_currencies(default_currencies)
    if card_num:
        await db.set_setting("card_number", card_num)
        await db.set_setting("card_holder", card_name)
        await db.set_setting("card_enabled", "1")
    if crypto_mid and crypto_key:
        await db.set_setting("cryptomus_merchant_id", crypto_mid)
        await db.set_setting("cryptomus_api_key", crypto_key)
        await db.set_setting("cryptomus_enabled", "1")
    for k in ("wizard_url", "wizard_support", "wizard_card_num", "wizard_card_name", "wizard_crypto_mid", "wizard_crypto_key"):
        ctx.user_data.pop(k, None)

async def cb_adm_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("admin_menu_title", version=VERSION), reply_markup=main_admin_kb(), parse_mode="Markdown")

async def cb_adm_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    if not await _is_admin(query.from_user.id):
        return
    await query.edit_message_text(t("adm_update_checking"), reply_markup=back_kb("adm:back"))
    http_proxy=settings.AUTO_UPDATE_HTTP_PROXY or ""
    https_proxy=settings.AUTO_UPDATE_HTTPS_PROXY or ""
    updater=Updater(check_interval=settings.UPDATE_CHECK_INTERVAL, check_on_startup=settings.CHECK_ON_STARTUP, http_proxy=http_proxy, https_proxy=https_proxy)
    new_version=await updater.check_for_update()
    if not new_version:
        await query.edit_message_text(t("adm_update_none"), reply_markup=back_kb("adm:back"))
        return
    await query.edit_message_text(t("adm_update_starting", version=new_version), reply_markup=back_kb("adm:back"))
    success=await updater.download_update(new_version)
    if not success:
        await query.edit_message_text(t("adm_update_failed"), reply_markup=back_kb("adm:back"))

async def cb_adm_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plans = await db.list_plans(active_only=False)
    base = await get_base_currency()
    per_page=await _get_page_size_setting("plans_page_size_admin", 10)
    total=len(plans)
    max_page=max((total-1)//per_page, 0)
    page=int(ctx.user_data.get("adm_plans_page", 0))
    page=max(0, min(page, max_page))
    ctx.user_data["adm_plans_page"]=page
    if not plans:
        rows = [[InlineKeyboardButton(t("adm_create_plan_btn"), callback_data="plan:create")], [InlineKeyboardButton(t("btn_back"), callback_data="adm:back")]]
        await query.edit_message_text(t("no_plans_admin"), reply_markup=InlineKeyboardMarkup(rows))
        return
    start=page*per_page
    page_plans=plans[start:start+per_page]
    rows = []
    for p in page_plans:
        status = "✅" if p["is_active"] else "❌"
        rows.append([InlineKeyboardButton(f"{status} {p['name']} — {_fmt_plan_price_display(p['price'], base)} {base}", callback_data=f"plan:detail:{p['id']}")])
    nav=[]
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data="adm:plans_page:prev"))
    if (page+1)*per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data="adm:plans_page:next"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("adm_create_plan_btn"), callback_data="plan:create")])
    rows.append([InlineKeyboardButton(t("adm_bulk_create_btn"), callback_data="plan:bulk_create")])
    rows.append([InlineKeyboardButton(t("adm_bulk_nodes_btn"), callback_data="plans:bulk_nodes")])
    rows.append([InlineKeyboardButton(t("adm_bulk_delete_btn"), callback_data="plans:bulk_delete")])
    rows.append([InlineKeyboardButton(t("adm_bulk_enable_btn"), callback_data="plans:bulk_enable"), InlineKeyboardButton(t("adm_bulk_disable_btn"), callback_data="plans:bulk_disable")])
    rows.append([InlineKeyboardButton(t("adm_bulk_price_multiply_btn"), callback_data="plans:bulk_price_multiply"), InlineKeyboardButton(t("adm_bulk_price_divide_btn"), callback_data="plans:bulk_price_divide")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    title=t("plans_title")
    if total>per_page:
        title += f"\n\n{t('plans_page_info', page=page+1, pages=max_page+1)}"
    await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_adm_plans_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    direction=query.data.split(":", 2)[2]
    page=int(ctx.user_data.get("adm_plans_page", 0))
    ctx.user_data["adm_plans_page"]=page-1 if direction=="prev" else page+1
    await cb_adm_plans(update, ctx)

async def cb_plan_detail_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    base = await get_base_currency()
    data_label=t("adm_unlimited") if float(plan["data_gb"])==0 else f"{plan['data_gb']} GB"
    days_label=t("adm_no_expiry") if int(plan["days"])==0 else f"{plan['days']}d"
    ip_label=t("adm_unlimited") if int(plan["ip_limit"])==0 else f"{plan['ip_limit']} IPs"
    text = (
        f"📦 *{plan['name']}*\n"
        f"💾 {data_label} / 📅 {days_label} / 📱 {ip_label}\n"
        f"💰 {_fmt_plan_price_display(plan['price'], base)} {base}\n"
        f"🔗 Nodes: {len(plan['node_ids'])}\n" +
        t("adm_plan_status", status=t("adm_active") if plan['is_active'] else t("adm_inactive"))
    )
    await query.edit_message_text(text, reply_markup=plan_actions_kb(plan_id, plan["is_active"]), parse_mode="Markdown")

async def cb_plan_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        return
    await db.update_plan(plan_id, is_active=0 if plan["is_active"] else 1)
    await cb_plan_detail_admin(update, ctx)

async def cb_plan_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    await db.delete_plan(plan_id)
    await db.log_admin_action(update.effective_user.id, "delete_plan", plan_id)
    await query.edit_message_text(t("plan_deleted"), reply_markup=back_kb("adm:plans"))

async def cb_plan_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_plan_name_prompt"), parse_mode="Markdown", reply_markup=cancel_kb())
    return PLAN_CREATE_NAME

async def plan_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["plan_name"] = update.message.text.strip()
    await update.message.reply_text(t("adm_plan_data_prompt"), reply_markup=cancel_kb())
    return PLAN_CREATE_DATA

async def plan_get_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["plan_data"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_DATA
    await update.message.reply_text(t("adm_plan_days_prompt"), reply_markup=cancel_kb())
    return PLAN_CREATE_DAYS

async def plan_get_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["plan_days"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_DAYS
    await update.message.reply_text(t("adm_plan_ip_prompt"), reply_markup=cancel_kb())
    return PLAN_CREATE_IP

async def plan_get_ip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["plan_ip"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_IP
    base = await get_base_currency()
    await update.message.reply_text(t("plan_price_enter", base=base), reply_markup=cancel_kb())
    return PLAN_CREATE_PRICE

async def plan_get_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    price=await _parse_plan_price_input(update.message.text.strip())
    if price is None:
        base=await get_base_currency()
        if base=="IRT":
            await update.message.reply_text(t("irt_price_step"))
        else:
            await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_PRICE
    ctx.user_data["plan_price"] = price
    ctx.user_data["plan_nodes"] = []
    nodes = await gg.list_nodes()
    if not nodes:
        await update.message.reply_text(t("ghostgate_error"))
        return ConversationHandler.END
    kb = node_select_kb(nodes, [], "plan:nodes_done", "cancel")
    await update.message.reply_text(t("adm_plan_nodes_prompt"), reply_markup=kb)
    return PLAN_CREATE_NODES

async def plan_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    node_id = int(query.data.split(":", 1)[1])
    selected = ctx.user_data.get("plan_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["plan_nodes"] = selected
    nodes = await gg.list_nodes()
    kb = node_select_kb(nodes, selected, "plan:nodes_done", "cancel")
    await query.edit_message_reply_markup(reply_markup=kb)
    return PLAN_CREATE_NODES

async def plan_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await db.create_plan(
        name=ctx.user_data["plan_name"],
        data_gb=ctx.user_data["plan_data"],
        days=ctx.user_data["plan_days"],
        ip_limit=ctx.user_data["plan_ip"],
        price=ctx.user_data["plan_price"],
        node_ids=ctx.user_data.get("plan_nodes", [])
    )
    for k in ("plan_name", "plan_data", "plan_days", "plan_ip", "plan_price", "plan_nodes"):
        ctx.user_data.pop(k, None)
    await query.edit_message_text(t("plan_created"), reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_plan_bulk_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    if not nodes:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    ctx.user_data["bulk_create_nodes"]=[]
    await query.edit_message_text(t("adm_bulk_create_nodes_prompt"), reply_markup=node_select_kb(nodes, [], "plan:bulk_create_nodes_done", "adm:plans", "plan:bulk_create_nodes_all", "plan:bulk_create_nodes_none"))
    return PLAN_BULK_CREATE_NODES

async def plan_bulk_create_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    node_id=int(query.data.split(":", 1)[1])
    selected=ctx.user_data.get("bulk_create_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["bulk_create_nodes"]=selected
    nodes=await gg.list_nodes()
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "plan:bulk_create_nodes_done", "adm:plans", "plan:bulk_create_nodes_all", "plan:bulk_create_nodes_none"))
    return PLAN_BULK_CREATE_NODES

async def plan_bulk_create_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    selected=_all_node_ids(nodes)
    ctx.user_data["bulk_create_nodes"]=selected
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "plan:bulk_create_nodes_done", "adm:plans", "plan:bulk_create_nodes_all", "plan:bulk_create_nodes_none"))
    return PLAN_BULK_CREATE_NODES

async def plan_bulk_create_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    ctx.user_data["bulk_create_nodes"]=[]
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "plan:bulk_create_nodes_done", "adm:plans", "plan:bulk_create_nodes_all", "plan:bulk_create_nodes_none"))
    return PLAN_BULK_CREATE_NODES

async def plan_bulk_create_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_bulk_create_matrix_prompt"), reply_markup=cancel_kb(), parse_mode="Markdown")
    return PLAN_BULK_CREATE_MATRIX

def _parse_data_token(token):
    s=token.strip().lower().replace(",", "")
    mult=Decimal("1")
    if s.endswith("tb"):
        s=s[:-2]
        mult=Decimal("1000")
    elif s.endswith("t"):
        s=s[:-1]
        mult=Decimal("1000")
    elif s.endswith("gb"):
        s=s[:-2]
    elif s.endswith("g"):
        s=s[:-1]
    try:
        v=Decimal(s)*mult
    except Exception:
        return None
    if v<0:
        return None
    return float(v)

def _parse_price_token(token, base):
    s=token.strip().lower().replace(",", "")
    if base=="IRT" and s.endswith("k"):
        try:
            s=str(Decimal(s[:-1])*Decimal("1000"))
        except Exception:
            return None
    try:
        v=Decimal(s)
    except Exception:
        return None
    if v<=0:
        return None
    if base=="IRT":
        if v!=v.to_integral_value():
            return None
        iv=int(v)
        if iv<1000 or iv%1000!=0:
            return None
        return float(iv)
    return float(v)

def _parse_bulk_matrix(text, base):
    rows={}
    ip_count=0
    for raw in text.splitlines():
        line=raw.strip()
        if not line:
            continue
        line=line.replace("|", " ").replace("\t", " ").replace("،", ",")
        if ":" in line:
            left,right=line.split(":", 1)
            data_token=left.strip()
            parts=[p for p in re.split(r"[,\s]+", right.strip()) if p]
        else:
            parts=[p for p in re.split(r"[,\s]+", line.strip()) if p]
            if len(parts)<2:
                return None, 0, "bad_data"
            data_token=parts[0]
            parts=parts[1:]
        data=_parse_data_token(data_token)
        if data is None:
            return None, 0, "bad_data"
        if ip_count==0:
            ip_count=len(parts)
        if len(parts)!=ip_count:
            return None, 0, "bad_price"
        prices=[]
        for p in parts:
            v=_parse_price_token(p, base)
            if v is None:
                return None, 0, "bad_price"
            prices.append(v)
        rows[data]=prices
    if not rows:
        return None, 0, "bad_data"
    return rows, ip_count, None

async def plan_bulk_create_matrix_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    base=await get_base_currency()
    rows, ip_count, err=_parse_bulk_matrix(update.message.text.strip(), base)
    if err=="bad_data":
        await update.message.reply_text(t("adm_bulk_create_bad_data"))
        return PLAN_BULK_CREATE_MATRIX
    if err=="bad_price":
        await update.message.reply_text(t("adm_bulk_create_bad_price"))
        return PLAN_BULK_CREATE_MATRIX
    node_ids=ctx.user_data.pop("bulk_create_nodes", [])
    plans=await db.list_plans(active_only=False)
    existing={}
    for p in plans:
        key=(float(p["data_gb"]), int(p["days"]), int(p["ip_limit"]))
        existing[key]=p
    created=0
    updated=0
    for data in sorted(rows.keys()):
        prices=rows[data]
        for ip in range(1, ip_count+1):
            price=prices[ip-1]
            key=(float(data), 30, ip)
            label_data=t("adm_unlimited") if float(data)==0 else ("1 TB" if float(data)==1000 else f"{int(data) if float(data).is_integer() else data} GB")
            label_ip=t("adm_unlimited") if ip==0 else f"{ip} IP"
            name=f"{label_data} • {label_ip} • 30D"
            if key in existing:
                await db.update_plan(existing[key]["id"], name=name, price=price, node_ids=node_ids)
                updated+=1
            else:
                await db.create_plan(name=name, data_gb=float(data), days=30, ip_limit=ip, price=price, node_ids=node_ids)
                created+=1
    await update.message.reply_text(t("adm_bulk_create_done", created=created, updated=updated), reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_plan_edit_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data["editing_plan_id"] = query.data.split(":", 2)[2]
    ctx.user_data["editing_plan_field"] = "price"
    await query.edit_message_text(t("adm_enter_price"), reply_markup=cancel_kb())
    return PLAN_EDIT_VALUE

async def cb_plan_edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data["editing_plan_id"] = query.data.split(":", 2)[2]
    ctx.user_data["editing_plan_field"] = "name"
    await query.edit_message_text(t("adm_enter_name"), reply_markup=cancel_kb())
    return PLAN_EDIT_VALUE

async def plan_edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    plan_id = ctx.user_data.pop("editing_plan_id", None)
    field = ctx.user_data.pop("editing_plan_field", None)
    if not plan_id or not field:
        return ConversationHandler.END
    val = update.message.text.strip()
    if field=="price":
        val=await _parse_plan_price_input(val)
        if val is None:
            base=await get_base_currency()
            if base=="IRT":
                await update.message.reply_text(t("irt_price_step"))
            else:
                await update.message.reply_text(t("invalid_input"))
            return PLAN_EDIT_VALUE
    await db.update_plan(plan_id, **{field: val})
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_plan_edit_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 3)[3]
    plan=await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return ConversationHandler.END
    nodes=await gg.list_nodes()
    if not nodes:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    selected=list(plan.get("node_ids", []))
    ctx.user_data["editing_plan_nodes_id"]=plan_id
    ctx.user_data["editing_plan_nodes"]=selected
    await query.edit_message_text(t("adm_plan_nodes_edit_prompt"), reply_markup=node_select_kb(nodes, selected, "plan:edit_nodes_done", f"plan:detail:{plan_id}", "plan:edit_nodes_all", "plan:edit_nodes_none"))
    return PLAN_EDIT_NODES

async def plan_edit_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    node_id=int(query.data.split(":", 1)[1])
    selected=ctx.user_data.get("editing_plan_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["editing_plan_nodes"]=selected
    nodes=await gg.list_nodes()
    plan_id=ctx.user_data.get("editing_plan_nodes_id", "")
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "plan:edit_nodes_done", f"plan:detail:{plan_id}", "plan:edit_nodes_all", "plan:edit_nodes_none"))
    return PLAN_EDIT_NODES

async def plan_edit_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    selected=_all_node_ids(nodes)
    ctx.user_data["editing_plan_nodes"]=selected
    plan_id=ctx.user_data.get("editing_plan_nodes_id", "")
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "plan:edit_nodes_done", f"plan:detail:{plan_id}", "plan:edit_nodes_all", "plan:edit_nodes_none"))
    return PLAN_EDIT_NODES

async def plan_edit_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    ctx.user_data["editing_plan_nodes"]=[]
    plan_id=ctx.user_data.get("editing_plan_nodes_id", "")
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "plan:edit_nodes_done", f"plan:detail:{plan_id}", "plan:edit_nodes_all", "plan:edit_nodes_none"))
    return PLAN_EDIT_NODES

async def plan_edit_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=ctx.user_data.pop("editing_plan_nodes_id", None)
    selected=ctx.user_data.pop("editing_plan_nodes", [])
    if not plan_id:
        return ConversationHandler.END
    await db.update_plan(plan_id, node_ids=selected)
    await query.edit_message_text(t("setting_saved"), reply_markup=back_kb(f"plan:detail:{plan_id}"))
    return ConversationHandler.END

async def cb_plans_bulk_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    if not plans:
        await query.edit_message_text(t("no_plans_admin"), reply_markup=back_kb("adm:plans"))
        return ConversationHandler.END
    ctx.user_data["bulk_node_plan_ids"]=[]
    await query.edit_message_text(t("adm_bulk_nodes_select_plans_prompt"), reply_markup=_plan_select_kb(plans, [], "plans:bulk_nodes_plans_done", "adm:plans", "plans:bulk_nodes_plans_all", "plans:bulk_nodes_plans_none"))
    return PLAN_BULK_NODES_PLANS

async def plans_bulk_nodes_toggle_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 1)[1]
    selected=ctx.user_data.get("bulk_node_plan_ids", [])
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    ctx.user_data["bulk_node_plan_ids"]=selected
    plans=await db.list_plans(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_nodes_plans_done", "adm:plans", "plans:bulk_nodes_plans_all", "plans:bulk_nodes_plans_none"))
    return PLAN_BULK_NODES_PLANS

async def plans_bulk_nodes_plans_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    selected=[p["id"] for p in plans]
    ctx.user_data["bulk_node_plan_ids"]=selected
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_nodes_plans_done", "adm:plans", "plans:bulk_nodes_plans_all", "plans:bulk_nodes_plans_none"))
    return PLAN_BULK_NODES_PLANS

async def plans_bulk_nodes_plans_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    ctx.user_data["bulk_node_plan_ids"]=[]
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, [], "plans:bulk_nodes_plans_done", "adm:plans", "plans:bulk_nodes_plans_all", "plans:bulk_nodes_plans_none"))
    return PLAN_BULK_NODES_PLANS

async def plans_bulk_nodes_plans_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected_plans=ctx.user_data.get("bulk_node_plan_ids", [])
    if not selected_plans:
        await query.answer(t("invalid_input"), show_alert=True)
        return PLAN_BULK_NODES_PLANS
    nodes=await gg.list_nodes()
    if not nodes:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    ctx.user_data["bulk_plan_nodes"]=[]
    await query.edit_message_text(t("adm_plan_nodes_bulk_prompt"), reply_markup=node_select_kb(nodes, [], "plans:bulk_nodes_done", "adm:plans", "plans:bulk_nodes_all", "plans:bulk_nodes_none"))
    return PLAN_BULK_NODES

async def plans_bulk_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    node_id=int(query.data.split(":", 1)[1])
    selected=ctx.user_data.get("bulk_plan_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["bulk_plan_nodes"]=selected
    nodes=await gg.list_nodes()
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "plans:bulk_nodes_done", "adm:plans", "plans:bulk_nodes_all", "plans:bulk_nodes_none"))
    return PLAN_BULK_NODES

async def plans_bulk_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    selected=_all_node_ids(nodes)
    ctx.user_data["bulk_plan_nodes"]=selected
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "plans:bulk_nodes_done", "adm:plans", "plans:bulk_nodes_all", "plans:bulk_nodes_none"))
    return PLAN_BULK_NODES

async def plans_bulk_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    ctx.user_data["bulk_plan_nodes"]=[]
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "plans:bulk_nodes_done", "adm:plans", "plans:bulk_nodes_all", "plans:bulk_nodes_none"))
    return PLAN_BULK_NODES

async def plans_bulk_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected=ctx.user_data.pop("bulk_plan_nodes", [])
    target_ids=ctx.user_data.pop("bulk_node_plan_ids", [])
    plans=await db.list_plans(active_only=False)
    count=0
    for plan in plans:
        if plan["id"] in target_ids:
            await db.update_plan(plan["id"], node_ids=selected)
            count+=1
    await query.edit_message_text(t("adm_plan_nodes_bulk_done", count=count), reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_plans_bulk_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    if not plans:
        await query.edit_message_text(t("no_plans_admin"), reply_markup=back_kb("adm:plans"))
        return ConversationHandler.END
    ctx.user_data["bulk_delete_plan_ids"]=[]
    await query.edit_message_text(t("adm_bulk_delete_prompt"), reply_markup=_plan_select_kb(plans, [], "plans:bulk_delete_done", "adm:plans", "plans:bulk_delete_all", "plans:bulk_delete_none"))
    return PLAN_BULK_DELETE

async def plans_bulk_delete_toggle_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 1)[1]
    selected=ctx.user_data.get("bulk_delete_plan_ids", [])
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    ctx.user_data["bulk_delete_plan_ids"]=selected
    plans=await db.list_plans(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_delete_done", "adm:plans", "plans:bulk_delete_all", "plans:bulk_delete_none"))
    return PLAN_BULK_DELETE

async def plans_bulk_delete_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    selected=[p["id"] for p in plans]
    ctx.user_data["bulk_delete_plan_ids"]=selected
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_delete_done", "adm:plans", "plans:bulk_delete_all", "plans:bulk_delete_none"))
    return PLAN_BULK_DELETE

async def plans_bulk_delete_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    ctx.user_data["bulk_delete_plan_ids"]=[]
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, [], "plans:bulk_delete_done", "adm:plans", "plans:bulk_delete_all", "plans:bulk_delete_none"))
    return PLAN_BULK_DELETE

async def plans_bulk_delete_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected=ctx.user_data.pop("bulk_delete_plan_ids", [])
    if not selected:
        await query.answer(t("invalid_input"), show_alert=True)
        return PLAN_BULK_DELETE
    for plan_id in selected:
        await db.delete_plan(plan_id)
    await query.edit_message_text(t("adm_bulk_delete_done", count=len(selected)), reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_plans_bulk_enable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    if not plans:
        await query.edit_message_text(t("no_plans_admin"), reply_markup=back_kb("adm:plans"))
        return ConversationHandler.END
    ctx.user_data["bulk_enable_plan_ids"]=[]
    ctx.user_data["bulk_enable_mode"]="enable"
    await query.edit_message_text(t("adm_bulk_enable_prompt"), reply_markup=_plan_select_kb(plans, [], "plans:bulk_toggle_done", "adm:plans", "plans:bulk_toggle_all", "plans:bulk_toggle_none"))
    return PLAN_BULK_ENABLE_DISABLE

async def cb_plans_bulk_disable(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    if not plans:
        await query.edit_message_text(t("no_plans_admin"), reply_markup=back_kb("adm:plans"))
        return ConversationHandler.END
    ctx.user_data["bulk_enable_plan_ids"]=[]
    ctx.user_data["bulk_enable_mode"]="disable"
    await query.edit_message_text(t("adm_bulk_disable_prompt"), reply_markup=_plan_select_kb(plans, [], "plans:bulk_toggle_done", "adm:plans", "plans:bulk_toggle_all", "plans:bulk_toggle_none"))
    return PLAN_BULK_ENABLE_DISABLE

async def plans_bulk_toggle_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 1)[1]
    selected=ctx.user_data.get("bulk_enable_plan_ids", [])
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    ctx.user_data["bulk_enable_plan_ids"]=selected
    plans=await db.list_plans(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_toggle_done", "adm:plans", "plans:bulk_toggle_all", "plans:bulk_toggle_none"))
    return PLAN_BULK_ENABLE_DISABLE

async def plans_bulk_toggle_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    selected=[p["id"] for p in plans]
    ctx.user_data["bulk_enable_plan_ids"]=selected
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_toggle_done", "adm:plans", "plans:bulk_toggle_all", "plans:bulk_toggle_none"))
    return PLAN_BULK_ENABLE_DISABLE

async def plans_bulk_toggle_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    ctx.user_data["bulk_enable_plan_ids"]=[]
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, [], "plans:bulk_toggle_done", "adm:plans", "plans:bulk_toggle_all", "plans:bulk_toggle_none"))
    return PLAN_BULK_ENABLE_DISABLE

async def plans_bulk_toggle_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected=ctx.user_data.pop("bulk_enable_plan_ids", [])
    mode=ctx.user_data.pop("bulk_enable_mode", "enable")
    if not selected:
        await query.answer(t("invalid_input"), show_alert=True)
        return PLAN_BULK_ENABLE_DISABLE
    val=1 if mode=="enable" else 0
    for plan_id in selected:
        await db.update_plan(plan_id, is_active=val)
    msg=t("adm_bulk_enable_done", count=len(selected)) if mode=="enable" else t("adm_bulk_disable_done", count=len(selected))
    await query.edit_message_text(msg, reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_plans_bulk_price_multiply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    if not plans:
        await query.edit_message_text(t("no_plans_admin"), reply_markup=back_kb("adm:plans"))
        return ConversationHandler.END
    ctx.user_data["bulk_price_plan_ids"]=[]
    ctx.user_data["bulk_price_op"]="multiply"
    await query.edit_message_text(t("adm_bulk_price_select_plans"), reply_markup=_plan_select_kb(plans, [], "plans:bulk_price_done", "adm:plans", "plans:bulk_price_all", "plans:bulk_price_none"))
    return PLAN_BULK_PRICE_MULTIPLY

async def cb_plans_bulk_price_divide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    if not plans:
        await query.edit_message_text(t("no_plans_admin"), reply_markup=back_kb("adm:plans"))
        return ConversationHandler.END
    ctx.user_data["bulk_price_plan_ids"]=[]
    ctx.user_data["bulk_price_op"]="divide"
    await query.edit_message_text(t("adm_bulk_price_select_plans"), reply_markup=_plan_select_kb(plans, [], "plans:bulk_price_done", "adm:plans", "plans:bulk_price_all", "plans:bulk_price_none"))
    return PLAN_BULK_PRICE_MULTIPLY

async def plans_bulk_price_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plan_id=query.data.split(":", 1)[1]
    selected=ctx.user_data.get("bulk_price_plan_ids", [])
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    ctx.user_data["bulk_price_plan_ids"]=selected
    plans=await db.list_plans(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_price_done", "adm:plans", "plans:bulk_price_all", "plans:bulk_price_none"))
    return PLAN_BULK_PRICE_MULTIPLY

async def plans_bulk_price_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    selected=[p["id"] for p in plans]
    ctx.user_data["bulk_price_plan_ids"]=selected
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "plans:bulk_price_done", "adm:plans", "plans:bulk_price_all", "plans:bulk_price_none"))
    return PLAN_BULK_PRICE_MULTIPLY

async def plans_bulk_price_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    plans=await db.list_plans(active_only=False)
    ctx.user_data["bulk_price_plan_ids"]=[]
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, [], "plans:bulk_price_done", "adm:plans", "plans:bulk_price_all", "plans:bulk_price_none"))
    return PLAN_BULK_PRICE_MULTIPLY

async def plans_bulk_price_factor_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected=ctx.user_data.get("bulk_price_plan_ids", [])
    if not selected:
        await query.answer(t("invalid_input"), show_alert=True)
        return PLAN_BULK_PRICE_MULTIPLY
    await query.edit_message_text(t("adm_bulk_price_factor_prompt"), reply_markup=cancel_kb())
    return PLAN_BULK_PRICE_FACTOR

async def plans_bulk_price_factor_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        factor=Decimal(update.message.text.strip().replace(",", ""))
        if factor<=0:
            raise ValueError
    except Exception:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_BULK_PRICE_FACTOR
    selected=ctx.user_data.pop("bulk_price_plan_ids", [])
    op=ctx.user_data.pop("bulk_price_op", "multiply")
    base=await get_base_currency()
    count=0
    for plan_id in selected:
        plan=await db.get_plan(plan_id)
        if not plan:
            continue
        old=Decimal(str(plan["price"]))
        new=old*factor if op=="multiply" else old/factor
        new=new.quantize(Decimal("1") if base=="IRT" else Decimal("0.01"))
        if base=="IRT":
            iv=int(new)
            iv=max(1000, (iv//1000)*1000)
            new=Decimal(iv)
        await db.update_plan(plan_id, price=float(new))
        count+=1
    await update.message.reply_text(t("adm_bulk_price_done", count=count), reply_markup=back_kb("adm:plans"))
    return ConversationHandler.END

async def cb_adm_subs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(ctx.user_data.get("subs_page", 0))
    subs = await gg.list_subscriptions(per_page=0)
    total = len(subs)
    per_page = 10
    start = page*per_page
    page_subs = subs[start:start+per_page]
    rows = [[InlineKeyboardButton(s.get("comment") or s["id"][:8], callback_data=f"adm:sub:detail:{s['id']}")] for s in page_subs]
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data="subs_page:prev"))
    if start+per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data="subs_page:next"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("adm_search_btn"), callback_data="subs:search"), InlineKeyboardButton(t("adm_create_btn"), callback_data="sub:create")])
    rows.append([InlineKeyboardButton(t("btn_subs_bulk_note"), callback_data="subs:bulk_note")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    await query.edit_message_text(f"📋 *Subscriptions* ({total} total)\nPage {page+1}", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_sub_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 3)[3]
    sub = await gg.get_subscription(sub_id)
    if not sub:
        await query.edit_message_text(t("sub_removed"))
        return
    data_used = (sub.get("used_bytes") or 0)/1073741824
    data_total = sub.get("data_gb") or 0
    expire = sub.get("expire_at") or t("adm_no_expiry")
    text = t("adm_sub_detail",
        sub_id=sub_id,
        comment=sub.get("comment") or "-",
        data_used=data_used,
        data_total=t("adm_unlimited") if data_total==0 else f"{data_total} GB",
        expire=expire,
        status=t("adm_active") if sub.get("enabled", 1) else t("adm_disabled")
    )
    await query.edit_message_text(text, reply_markup=sub_actions_kb(sub_id, "adm:subs"), parse_mode="Markdown")
    base = settings.GHOSTGATE_URL.rsplit("/", 1)[0] if "/" in settings.GHOSTGATE_URL else settings.GHOSTGATE_URL
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        await query.message.reply_photo(photo=io.BytesIO(qr_bytes), caption=f"🔗 `{base}/sub/{sub_id}`", parse_mode="Markdown")

async def cb_sub_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    base = settings.GHOSTGATE_URL.rsplit("/", 1)[0] if "/" in settings.GHOSTGATE_URL else settings.GHOSTGATE_URL
    sub_url = f"{base}/sub/{sub_id}"
    if qr_bytes:
        await query.message.reply_photo(photo=io.BytesIO(qr_bytes), caption=f"🔗 `{sub_url}`", parse_mode="Markdown")
    else:
        await query.message.reply_text(f"🔗 `{sub_url}`", parse_mode="Markdown")

async def cb_sub_configs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    configs = await gg.get_subscription_configs(sub_id)
    if not configs:
        await query.message.reply_text(t("ghostgate_error"))
        return
    for c in configs:
        await query.message.reply_text(f"*{c['node']}*\n`{c['config']}`", parse_mode="Markdown")

async def cb_sub_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 3)[3]
    await gg.delete_subscription(sub_id)
    await db.log_admin_action(update.effective_user.id, "delete_sub", sub_id)
    await query.edit_message_text(t("sub_deleted"), reply_markup=back_kb("adm:subs"))

async def cb_sub_reset_traffic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sub_id = query.data.split(":", 4)[4]
    ok = await gg.reset_subscription_traffic(sub_id)
    await query.answer(t("sub_traffic_reset") if ok else t("sub_traffic_reset_fail"), show_alert=True)

async def cb_sub_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_sub_comment_prompt"), reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_COMMENT

async def manual_sub_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["msub_comment"] = update.message.text.strip()
    await update.message.reply_text(t("adm_sub_data_prompt"), reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_DATA

async def manual_sub_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["msub_data"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_MANUAL_SUB_DATA
    await update.message.reply_text(t("adm_sub_days_prompt"), reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_DAYS

async def manual_sub_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["msub_days"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_MANUAL_SUB_DAYS
    await update.message.reply_text(t("adm_sub_ip_prompt"), reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_IP

async def manual_sub_ip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["msub_ip"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_MANUAL_SUB_IP
    ctx.user_data["msub_nodes"] = []
    nodes = await gg.list_nodes()
    kb = node_select_kb(nodes, [], "msub:nodes_done", "cancel", "msub:nodes_all", "msub:nodes_none")
    await update.message.reply_text(t("adm_sub_nodes_prompt"), reply_markup=kb)
    return ADMIN_MANUAL_SUB_NODES

async def manual_sub_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    node_id = int(query.data.split(":", 1)[1])
    selected = ctx.user_data.get("msub_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["msub_nodes"] = selected
    nodes = await gg.list_nodes()
    kb = node_select_kb(nodes, selected, "msub:nodes_done", "cancel", "msub:nodes_all", "msub:nodes_none")
    await query.edit_message_reply_markup(reply_markup=kb)
    return ADMIN_MANUAL_SUB_NODES

async def manual_sub_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    ctx.user_data["msub_nodes"] = _all_node_ids(nodes)
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, ctx.user_data["msub_nodes"], "msub:nodes_done", "cancel", "msub:nodes_all", "msub:nodes_none"))
    return ADMIN_MANUAL_SUB_NODES

async def manual_sub_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    ctx.user_data["msub_nodes"] = []
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "msub:nodes_done", "cancel", "msub:nodes_all", "msub:nodes_none"))
    return ADMIN_MANUAL_SUB_NODES

async def manual_sub_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_sub_note_prompt"), reply_markup=skip_kb("msub:note_skip"))
    return ADMIN_MANUAL_SUB_NOTE

async def manual_sub_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["msub_note"] = update.message.text.strip()
    result = await gg.create_subscription(
        comment=ctx.user_data.get("msub_comment", ""),
        data_gb=ctx.user_data.get("msub_data", 0),
        days=ctx.user_data.get("msub_days", 0),
        ip_limit=ctx.user_data.get("msub_ip", 0),
        node_ids=ctx.user_data.get("msub_nodes", []),
        note=ctx.user_data.get("msub_note") or None
    )
    for k in ("msub_comment", "msub_data", "msub_days", "msub_ip", "msub_nodes", "msub_note"):
        ctx.user_data.pop(k, None)
    if not result:
        await update.message.reply_text(t("ghostgate_error"))
        return ConversationHandler.END
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    await update.message.reply_text(t("sub_created_admin", sub_id=sub_id, url=sub_url), reply_markup=back_kb("adm:subs"), parse_mode="Markdown")
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        await update.message.reply_photo(photo=io.BytesIO(qr_bytes), caption=f"🔗 `{sub_url}`", parse_mode="Markdown")
    return ConversationHandler.END

async def manual_sub_note_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    result = await gg.create_subscription(
        comment=ctx.user_data.get("msub_comment", ""),
        data_gb=ctx.user_data.get("msub_data", 0),
        days=ctx.user_data.get("msub_days", 0),
        ip_limit=ctx.user_data.get("msub_ip", 0),
        node_ids=ctx.user_data.get("msub_nodes", [])
    )
    for k in ("msub_comment", "msub_data", "msub_days", "msub_ip", "msub_nodes", "msub_note"):
        ctx.user_data.pop(k, None)
    if not result:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    await query.edit_message_text(t("sub_created_admin", sub_id=sub_id, url=sub_url), reply_markup=back_kb("adm:subs"), parse_mode="Markdown")
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        await query.message.reply_photo(photo=io.BytesIO(qr_bytes), caption=f"🔗 `{sub_url}`", parse_mode="Markdown")
    return ConversationHandler.END

async def cb_subs_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    direction = query.data.split(":", 1)[1]
    page = int(ctx.user_data.get("subs_page", 0))
    ctx.user_data["subs_page"] = page-1 if direction=="prev" else page+1
    await cb_adm_subs(update, ctx)

async def cb_adm_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _show_users_page(query, 0)

async def _show_users_page(query, page):
    per_page = 10
    users, total = await db.list_users(offset=page*per_page, limit=per_page)
    pages = max(1, (total+per_page-1)//per_page)
    text = t("adm_users_list", total=total, page=page+1, pages=pages)
    for u in users:
        uname = f"@{u['username'].replace('_', '\\_')}" if u.get("username") else str(u["telegram_id"])
        text += f"• {u.get('first_name') or ''} {uname}\n"
    rows = [[InlineKeyboardButton(t("adm_search_user_btn"), callback_data="users:search")]]
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"users:page:{page-1}"))
    if (page+1)*per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"users:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_users_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":", 2)[2])
    await _show_users_page(query, page)

async def cb_users_search_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_user_search_prompt"), reply_markup=cancel_kb())
    return USER_SEARCH

async def users_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    results = await db.search_users(update.message.text.strip().lstrip("@"))
    if not results:
        await update.message.reply_text(t("adm_no_users"), reply_markup=back_kb("adm:users"))
        return ConversationHandler.END
    rows = []
    for u in results:
        uname = f"@{u['username']}" if u.get("username") else str(u["telegram_id"])
        rows.append([InlineKeyboardButton(f"{u.get('first_name') or ''} {uname}".strip(), callback_data=f"user:detail:{u['id']}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:users")])
    await update.message.reply_text(t("adm_search_results"), reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

async def cb_user_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    user = await db.get_user_by_id(uid)
    if not user:
        await query.edit_message_text(t("adm_user_not_found"))
        return
    uname = f"@{user['username']}" if user.get("username") else "-"
    text = t("adm_user_detail",
        name=user.get("first_name") or "-",
        username=uname,
        telegram_id=user["telegram_id"],
        status=t("adm_banned") if user["is_banned"] else t("adm_active"),
        joined=user["created_at"][:10]
    )
    await query.edit_message_text(text, reply_markup=user_actions_kb(uid, user["is_banned"], "adm:users"), parse_mode="Markdown")

async def cb_user_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    user = await db.get_user_by_id(uid)
    if user:
        await db.ban_user(user["telegram_id"], True)
        await db.log_admin_action(update.effective_user.id, "ban_user", str(user["telegram_id"]))
    await query.edit_message_text(t("user_banned"), reply_markup=back_kb("adm:users"))

async def cb_user_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    user = await db.get_user_by_id(uid)
    if user:
        await db.ban_user(user["telegram_id"], False)
        await db.log_admin_action(update.effective_user.id, "unban_user", str(user["telegram_id"]))
    await query.edit_message_text(t("user_unbanned"), reply_markup=back_kb("adm:users"))

async def cb_user_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    orders = await db.get_orders_by_user(uid)
    if not orders:
        await query.edit_message_text(t("adm_no_orders"), reply_markup=back_kb(f"user:detail:{uid}"))
        return
    rows = [[InlineKeyboardButton(f"{o['plan_name']} — {o['status']} — {o['created_at'][:10]}", callback_data=f"order:detail:{o['id']}")] for o in orders]
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=f"user:detail:{uid}")])
    await query.edit_message_text(t("adm_user_orders_title"), reply_markup=InlineKeyboardMarkup(rows))

async def cb_user_reset_trial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    count = await db.reset_trial_claim_for_user(uid)
    if count:
        await db.log_admin_action(update.effective_user.id, "reset_trial", uid)
        await query.answer(t("adm_trial_reset_user_done"), show_alert=True)
    else:
        await query.answer(t("adm_trial_no_claim"), show_alert=True)

async def cb_user_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    balance = await db.get_wallet_balance(uid)
    await query.edit_message_text(t("adm_wallet_title", balance=balance), reply_markup=wallet_adjust_kb(uid, f"user:detail:{uid}"), parse_mode="Markdown")

async def cb_user_wallet_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    ctx.user_data["wallet_adjust_uid"] = uid
    await query.edit_message_text(t("adm_wallet_add_prompt"), reply_markup=cancel_kb())
    return ADMIN_WALLET_ADD

async def handle_wallet_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = ctx.user_data.pop("wallet_adjust_uid", None)
    if not uid:
        return ConversationHandler.END
    try:
        amount = float(update.message.text.strip())
        if amount<=0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("adm_wallet_invalid"))
        return ConversationHandler.END
    new_bal = await db.adjust_wallet(uid, amount)
    await db.log_admin_action(update.effective_user.id, "wallet_add", f"uid:{uid} amount:{amount}")
    await update.message.reply_text(t("adm_wallet_adjusted", balance=new_bal))
    return ConversationHandler.END

async def cb_user_wallet_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    balance = await db.get_wallet_balance(uid)
    ctx.user_data["wallet_adjust_uid"] = uid
    await query.edit_message_text(t("adm_wallet_remove_prompt", balance=balance), reply_markup=cancel_kb())
    return ADMIN_WALLET_REMOVE

async def handle_wallet_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = ctx.user_data.pop("wallet_adjust_uid", None)
    if not uid:
        return ConversationHandler.END
    try:
        amount = float(update.message.text.strip())
        if amount<=0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("adm_wallet_invalid"))
        return ConversationHandler.END
    balance = await db.get_wallet_balance(uid)
    if amount>balance:
        await update.message.reply_text(t("adm_wallet_insufficient"))
        return ConversationHandler.END
    new_bal = await db.adjust_wallet(uid, -amount)
    await db.log_admin_action(update.effective_user.id, "wallet_remove", f"uid:{uid} amount:{amount}")
    await update.message.reply_text(t("adm_wallet_adjusted", balance=new_bal))
    return ConversationHandler.END

async def cb_adm_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = await db.get_pending_orders()
    rows = [
        [InlineKeyboardButton(t("adm_orders_pending_waiting"), callback_data="orders:list:waiting_confirm")],
        [InlineKeyboardButton(t("adm_orders_paid"), callback_data="orders:list:paid")],
        [InlineKeyboardButton(t("adm_orders_rejected"), callback_data="orders:list:rejected")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:back")],
    ]
    await query.edit_message_text(t("adm_orders_title", count=len(pending)), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

_ORDERS_PER_PAGE = 10

async def cb_orders_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":", 2)[2]
    ctx.user_data["orders_list_status"] = status
    ctx.user_data["orders_list_page"] = 0
    await _show_orders_page(query, ctx)

async def cb_orders_list_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    direction = query.data.split(":", 2)[2]
    page = ctx.user_data.get("orders_list_page", 0)
    ctx.user_data["orders_list_page"] = max(0, page+(1 if direction=="next" else -1))
    await _show_orders_page(query, ctx)

async def _show_orders_page(query, ctx):
    status = ctx.user_data.get("orders_list_status", "waiting_confirm")
    page = ctx.user_data.get("orders_list_page", 0)
    orders, total = await db.list_orders(status=status, offset=page*_ORDERS_PER_PAGE, limit=_ORDERS_PER_PAGE)
    rows = [[InlineKeyboardButton(f"{o.get('plan_name') or t('wallet_topup_label')} — {o.get('first_name','?')} — {o['status']}", callback_data=f"order:detail:{o['id']}")] for o in orders]
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data="orders:page:prev"))
    if (page+1)*_ORDERS_PER_PAGE<total:
        nav.append(InlineKeyboardButton("▶️", callback_data="orders:page:next"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:orders")])
    await query.edit_message_text(t("adm_orders_count", count=total), reply_markup=InlineKeyboardMarkup(rows))

async def cb_order_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    order = await db.get_order(order_id)
    if not order:
        await query.edit_message_text(t("order_not_found"))
        return
    user = await db.get_user_by_id(order["user_id"])
    plan = await db.get_plan(order["plan_id"]) if order.get("plan_id") else None
    uname = f"@{user['username']}" if user and user.get("username") else str(user["telegram_id"] if user else "?")
    text = t("adm_order_detail",
        order_id=order_id,
        user=uname,
        plan=plan["name"] if plan else t("wallet_topup_label"),
        amount=f"{cfmt(Decimal(str(order['amount'])), 0, order['currency'])} {order['currency']}",
        method=order["payment_method"],
        status=order["status"],
        created=order["created_at"][:16]
    )
    if order.get("receipt_file_id") and order["status"] in ("pending", "waiting_confirm"):
        await query.message.reply_photo(order["receipt_file_id"])
    await query.edit_message_text(text, reply_markup=order_detail_kb(order_id, order["status"], "adm:orders"), parse_mode="Markdown")

async def cb_confirm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    order = await db.get_order(order_id)
    if not order or order["status"] not in ("pending", "waiting_confirm"):
        await query.answer(t("adm_already_processed"), show_alert=True)
        return
    if not order.get("plan_id"):
        await db.adjust_wallet(order["user_id"], order["amount"])
        await db.update_order(order_id, status="paid", paid_at=datetime.now(timezone.utc).isoformat())
        user = await db.get_user_by_id(order["user_id"])
        new_balance = await db.get_wallet_balance(order["user_id"])
        asyncio.create_task(admin_event(ctx.bot, "notify_purchase", f"💳 *Wallet top-up confirmed*\n\n👤 {user.get('first_name','') if user else ''} (`{user['telegram_id'] if user else '?'}`)\n💰 Amount: {order['amount']} {order['currency']}"))
        try:
            await ctx.bot.send_message(user["telegram_id"], t("wallet_topup_confirmed", amount=order["amount"], balance=new_balance))
        except Exception:
            pass
        try:
            await query.edit_message_text(t("adm_wallet_adjusted", balance=new_balance), reply_markup=None)
        except Exception:
            pass
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
    asyncio.create_task(_credit_referral_commission(order["user_id"], plan["price"], ctx.bot))
    asyncio.create_task(admin_event(ctx.bot, "notify_purchase", f"💰 *Purchase confirmed*\n\n👤 {user.get('first_name','')} (`{user['telegram_id']}`)\n📦 Plan: *{plan['name']}*\n💵 Amount: {order.get('amount','')} {order.get('currency','')}"))
    await db.log_admin_action(update.effective_user.id, "confirm_order", f"order:{order_id} sub:{sub_id}")
    admin_name = update.effective_user.first_name or str(update.effective_user.id)
    try:
        await query.edit_message_caption(caption=f"{query.message.caption or ''}\n\n{t('admin_confirmed', admin=admin_name, sub_id=sub_id)}", reply_markup=None)
    except Exception:
        await query.edit_message_text(t("admin_confirmed", admin=admin_name, sub_id=sub_id), reply_markup=None)
    qr_bytes = await gg.get_subscription_qr_bytes(sub_id)
    if qr_bytes:
        await ctx.bot.send_photo(user["telegram_id"], photo=io.BytesIO(qr_bytes), caption=t("sub_confirmed", url=sub_url), parse_mode="Markdown")
    else:
        await ctx.bot.send_message(user["telegram_id"], t("sub_confirmed", url=sub_url), parse_mode="Markdown")

async def cb_reject_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    ctx.user_data["rejecting_order_id"] = order_id
    await query.message.reply_text(t("reject_reason_prompt"), reply_markup=skip_kb("reject:skip"))
    return ADMIN_REJECT_REASON

async def handle_reject_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    order_id = ctx.user_data.pop("rejecting_order_id", None)
    if not order_id:
        return ConversationHandler.END
    await _do_reject(order_id, update.message.text.strip(), update, ctx)
    return ConversationHandler.END

async def cb_reject_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = ctx.user_data.pop("rejecting_order_id", None)
    if not order_id:
        return ConversationHandler.END
    await _do_reject(order_id, "", update, ctx)
    return ConversationHandler.END

async def _do_reject(order_id, reason, update, ctx):
    order = await db.get_order(order_id)
    if not order:
        return
    await db.update_order(order_id, status="rejected")
    await db.log_admin_action(update.effective_user.id, "reject_order", f"order:{order_id}")
    user = await db.get_user_by_id(order["user_id"])
    if user:
        if reason:
            await ctx.bot.send_message(user["telegram_id"], t("reject_notif", reason=reason))
        else:
            await ctx.bot.send_message(user["telegram_id"], t("sub_rejected"))
    admin_name = update.effective_user.first_name or str(update.effective_user.id)
    if update.callback_query:
        await update.callback_query.edit_message_text(t("admin_rejected", admin=admin_name), reply_markup=None)
    else:
        await update.message.reply_text(t("admin_rejected", admin=admin_name))

async def cb_adm_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admins = await db.list_admins()
    rows = [[InlineKeyboardButton(f"👑 {a['telegram_id']}", callback_data=f"admin:detail:{a['telegram_id']}")] for a in admins]
    rows.append([InlineKeyboardButton(t("adm_add_admin_btn"), callback_data="admin:add")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    await query.edit_message_text(t("adm_admins_title", root_id=settings.ADMIN_ID), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_admin_id_prompt"), reply_markup=cancel_kb())
    return ADMIN_ADD_ID

async def admin_add_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["new_admin_id"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_ADD_ID
    await update.message.reply_text(t("adm_admin_perms_prompt"), reply_markup=cancel_kb())
    return ADMIN_ADD_PERMS

async def admin_add_perms(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    new_id = ctx.user_data.pop("new_admin_id", None)
    if not new_id:
        return ConversationHandler.END
    perms = [p.strip() for p in update.message.text.split(",")]
    await db.add_admin(new_id, update.effective_user.id, perms)
    await update.message.reply_text(t("admin_added"), reply_markup=back_kb("adm:admins"))
    return ConversationHandler.END

async def cb_admin_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_tid = int(query.data.split(":", 2)[2])
    rows = []
    if admin_tid!=settings.ADMIN_ID:
        rows.append([InlineKeyboardButton(t("adm_remove_btn"), callback_data=f"admin:remove:{admin_tid}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:admins")])
    await query.edit_message_text(f"👑 Admin: `{admin_tid}`", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_admin_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_tid = int(query.data.split(":", 2)[2])
    if admin_tid==settings.ADMIN_ID:
        await query.answer(t("adm_cannot_remove_root"), show_alert=True)
        return
    await db.remove_admin(admin_tid)
    await query.edit_message_text(t("admin_removed"), reply_markup=back_kb("adm:admins"))

async def cb_adm_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_settings_title"), reply_markup=settings_kb(), parse_mode="Markdown")

async def cb_set_gg_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    current = settings.GHOSTGATE_URL or "(not set)"
    await query.edit_message_text(t("adm_gg_url_prompt", current=current), reply_markup=cancel_kb(), parse_mode="Markdown")
    return SETTINGS_GG_URL

async def settings_gg_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip().rstrip("/")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/api/status")
            r.raise_for_status()
    except Exception as e:
        await update.message.reply_text(t("wizard_step1_fail", error=str(e)))
        return SETTINGS_GG_URL
    from dotenv import set_key as dotenv_set
    dotenv_set("/opt/ghostpass/.env", "GHOSTGATE_URL", url)
    settings.GHOSTGATE_URL = url
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    card_num = await db.get_setting("card_number", "(not set)")
    card_name = await db.get_setting("card_holder", "(not set)")
    card_enabled = await db.get_setting("card_enabled", "0")=="1"
    rows = [
        [InlineKeyboardButton(t("adm_toggle_btn", status=t("adm_enabled") if card_enabled else t("adm_disabled")), callback_data="set:card_toggle")],
        [InlineKeyboardButton(t("btn_edit_card_num"), callback_data="set:card_num")],
        [InlineKeyboardButton(t("btn_edit_card_name"), callback_data="set:card_name")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")],
    ]
    await query.edit_message_text(f"💳 *Card-to-Card*\n\nCard: `{card_num}`\nHolder: {card_name}", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_card_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("card_enabled", "0")=="1"
    await db.set_setting("card_enabled", "0" if enabled else "1")
    await cb_set_card(update, ctx)

async def cb_set_card_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_card_num"), reply_markup=cancel_kb())
    return SETTINGS_CARD_NUM

async def settings_card_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("card_number", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:card"))
    return ConversationHandler.END

async def cb_set_card_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_card_name"), reply_markup=cancel_kb())
    return SETTINGS_CARD_NAME

async def settings_card_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("card_holder", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:card"))
    return ConversationHandler.END

async def cb_set_crypto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mid = await db.get_setting("cryptomus_merchant_id", "(not set)")
    enabled = await db.get_setting("cryptomus_enabled", "0")=="1"
    gp_enabled = await db.get_setting("ghostpayments_enabled", "0")=="1"
    gp_url = await db.get_setting("ghostpayments_url", settings.GHOSTPAYMENTS_URL or "(not set)")
    rows = [
        [InlineKeyboardButton(t("adm_toggle_btn", status=f"Cryptomus {t('adm_enabled') if enabled else t('adm_disabled')}"), callback_data="set:crypto_toggle")],
        [InlineKeyboardButton(t("adm_toggle_btn", status=f"GhostPayments {t('adm_enabled') if gp_enabled else t('adm_disabled')}"), callback_data="set:gp_toggle")],
        [InlineKeyboardButton(t("btn_edit_mid"), callback_data="set:crypto_mid")],
        [InlineKeyboardButton(t("btn_edit_api_key"), callback_data="set:crypto_key")],
        [InlineKeyboardButton(t("btn_edit_gp_url"), callback_data="set:gp_url")],
        [InlineKeyboardButton(t("btn_edit_gp_key"), callback_data="set:gp_key")],
        [InlineKeyboardButton(t("btn_set_gp_pairs"), callback_data="set:gp_pairs")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")],
    ]
    await query.edit_message_text(f"🪙 *Crypto Providers*\n\nCryptomus MID: `{mid}`\nGhostPayments URL: `{gp_url}`", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_crypto_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("cryptomus_enabled", "0")=="1"
    await db.set_setting("cryptomus_enabled", "0" if enabled else "1")
    await cb_set_crypto(update, ctx)

async def cb_gp_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("ghostpayments_enabled", "0")=="1"
    await db.set_setting("ghostpayments_enabled", "0" if enabled else "1")
    await cb_set_crypto(update, ctx)

async def cb_set_crypto_mid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_crypto_mid"), reply_markup=cancel_kb())
    return SETTINGS_CRYPTO_MID

async def settings_crypto_mid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("cryptomus_merchant_id", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:crypto"))
    return ConversationHandler.END

async def cb_set_crypto_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_crypto_key"), reply_markup=cancel_kb())
    return SETTINGS_CRYPTO_KEY

async def settings_crypto_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("cryptomus_api_key", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:crypto"))
    return ConversationHandler.END

async def cb_set_gp_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_gp_url"), reply_markup=cancel_kb())
    return SETTINGS_GHOSTPAY_URL

async def settings_gp_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("ghostpayments_url", update.message.text.strip().rstrip("/"))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:crypto"))
    return ConversationHandler.END

async def cb_set_gp_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_gp_key"), reply_markup=cancel_kb())
    return SETTINGS_GHOSTPAY_KEY

async def settings_gp_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("ghostpayments_api_key", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:crypto"))
    return ConversationHandler.END

async def cb_set_gp_pairs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pairs = await get_gp_pairs()
    base = await get_base_currency()
    rows = []
    for p in pairs:
        status = "✅" if p.get("enabled") else "❌"
        rate = p.get("rate", "")
        rate_info = f"1 {base}={rate} {p['token']}" if rate else t("adm_gp_pair_no_rate")
        rows.append([InlineKeyboardButton(f"{status} {p['chain']}/{p['token']} — {rate_info}", callback_data=f"gp_pair:detail:{p['chain']}:{p['token']}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="set:crypto")])
    await query.edit_message_text(t("adm_gp_pairs_title"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_gp_pair_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 3)
    chain, token = parts[2], parts[3]
    pairs = await get_gp_pairs()
    pair = next((p for p in pairs if p["chain"]==chain and p["token"]==token), None)
    if not pair:
        return
    base = await get_base_currency()
    enabled = pair.get("enabled", False)
    rate = pair.get("rate", "")
    text = t("adm_gp_pair_detail", chain=chain, token=token, status=t("adm_enabled") if enabled else t("adm_disabled"), rate=rate if rate else t("adm_gp_pair_no_rate"), base=base)
    rows = [
        [InlineKeyboardButton(t("adm_toggle_btn", status=t("adm_enabled") if enabled else t("adm_disabled")), callback_data=f"gp_pair:toggle:{chain}:{token}")],
        [InlineKeyboardButton(t("btn_edit_rate"), callback_data=f"gp_pair:rate:{chain}:{token}")],
        [InlineKeyboardButton(t("btn_back"), callback_data="set:gp_pairs")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_gp_pair_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 3)
    chain, token = parts[2], parts[3]
    pairs = await get_gp_pairs()
    for p in pairs:
        if p["chain"]==chain and p["token"]==token:
            p["enabled"] = not p.get("enabled", False)
            break
    await save_gp_pairs(pairs)
    await cb_gp_pair_detail(update, ctx)

async def cb_gp_pair_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 3)
    chain, token = parts[2], parts[3]
    ctx.user_data["gp_pair_rate_chain"] = chain
    ctx.user_data["gp_pair_rate_token"] = token
    base = await get_base_currency()
    await query.edit_message_text(t("adm_gp_pair_rate_prompt", token=token, base=base), reply_markup=cancel_kb())
    return SETTINGS_GP_PAIR_RATE

async def gp_pair_rate_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chain = ctx.user_data.pop("gp_pair_rate_chain", None)
    token = ctx.user_data.pop("gp_pair_rate_token", None)
    if not chain or not token:
        return ConversationHandler.END
    try:
        exchange = Decimal(update.message.text.strip().replace(",", ""))
        if exchange<=0:
            raise ValueError
        rate = str(Decimal("1")/exchange)
    except Exception:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_GP_PAIR_RATE
    pairs = await get_gp_pairs()
    found = False
    for p in pairs:
        if p["chain"]==chain and p["token"]==token:
            p["rate"] = rate
            found = True
            break
    if not found:
        pairs.append({"chain": chain, "token": token, "enabled": False, "rate": rate})
    await save_gp_pairs(pairs)
    await update.message.reply_text(t("adm_gp_pair_rate_updated", chain=chain, token=token), reply_markup=back_kb("set:gp_pairs"))
    return ConversationHandler.END

async def cb_set_requests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("requests_enabled", "0")=="1"
    rows = [
        [InlineKeyboardButton(t("adm_toggle_btn", status=t("adm_enabled") if enabled else t("adm_disabled")), callback_data="set:req_toggle")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")],
    ]
    await query.edit_message_text(t("adm_requests_title"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_req_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("requests_enabled", "0")=="1"
    await db.set_setting("requests_enabled", "0" if enabled else "1")
    await cb_set_requests(update, ctx)

async def cb_set_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("support_username", "(not set)")
    await query.edit_message_text(t("adm_support_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_SUPPORT

async def settings_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("support_username", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_sync_prompt", current=settings.SYNC_INTERVAL), reply_markup=cancel_kb())
    return SETTINGS_SYNC

async def settings_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_SYNC
    from dotenv import set_key as dotenv_set
    dotenv_set("/opt/ghostpass/.env", "SYNC_INTERVAL", str(val))
    settings.SYNC_INTERVAL = val
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_plan_pagination(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    consumer=await _get_page_size_setting("plans_page_size_consumer", 8)
    admin=await _get_page_size_setting("plans_page_size_admin", 10)
    rows=[
        [InlineKeyboardButton(t("adm_plan_page_size_consumer_btn"), callback_data="set:plan_page_size_consumer")],
        [InlineKeyboardButton(t("adm_plan_page_size_admin_btn"), callback_data="set:plan_page_size_admin")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")],
    ]
    await query.edit_message_text(t("adm_plan_pagination_title", consumer=consumer, admin=admin), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_set_plan_page_size_consumer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    current=await _get_page_size_setting("plans_page_size_consumer", 8)
    await query.edit_message_text(t("adm_plan_page_size_consumer_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_PLAN_PAGE_SIZE_CONSUMER

async def settings_plan_page_size_consumer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val=int(update.message.text.strip())
        if val<1 or val>50:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_PLAN_PAGE_SIZE_CONSUMER
    await db.set_setting("plans_page_size_consumer", str(val))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:plan_pagination"))
    return ConversationHandler.END

async def cb_set_plan_page_size_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    current=await _get_page_size_setting("plans_page_size_admin", 10)
    await query.edit_message_text(t("adm_plan_page_size_admin_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_PLAN_PAGE_SIZE_ADMIN

async def settings_plan_page_size_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val=int(update.message.text.strip())
        if val<1 or val>50:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_PLAN_PAGE_SIZE_ADMIN
    await db.set_setting("plans_page_size_admin", str(val))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:plan_pagination"))
    return ConversationHandler.END

async def _get_force_join_channels_admin():
    raw=await db.get_setting("force_join_channels", "")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    single=(await db.get_setting("force_join_channel", "") or "").strip()
    return [single] if single else []

async def cb_set_force_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled=await db.get_setting("force_join_enabled", "0")=="1"
    channels=await _get_force_join_channels_admin()
    rows=[[InlineKeyboardButton(t("adm_toggle_btn", status=t("adm_enabled") if enabled else t("adm_disabled")), callback_data="set:force_join_toggle")]]
    for i, ch in enumerate(channels):
        rows.append([InlineKeyboardButton(t("adm_force_join_remove_btn", channel=ch), callback_data=f"set:force_join_remove:{i}")])
    rows.append([InlineKeyboardButton(t("adm_force_join_set_channel"), callback_data="set:force_join_channel")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")])
    channels_text="\n".join(f"`{ch}`" for ch in channels) if channels else t("adm_force_join_no_channels")
    await query.edit_message_text(t("adm_force_join_title", status=t("adm_enabled") if enabled else t("adm_disabled"), channels=channels_text), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_force_join_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled=await db.get_setting("force_join_enabled", "0")=="1"
    await db.set_setting("force_join_enabled", "0" if enabled else "1")
    await cb_set_force_join(update, ctx)

async def cb_force_join_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    idx=int(query.data.split(":", 2)[2])
    channels=await _get_force_join_channels_admin()
    if 0<=idx<len(channels):
        channels.pop(idx)
    await db.set_setting("force_join_channels", json.dumps(channels))
    await cb_set_force_join(update, ctx)

async def cb_set_force_join_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_force_join_prompt"), reply_markup=cancel_kb(), parse_mode="Markdown")
    return SETTINGS_FORCE_JOIN_CHANNEL

async def settings_force_join_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val=update.message.text.strip()
    if val:
        try:
            me=await ctx.bot.get_me()
            await ctx.bot.get_chat_member(val, me.id)
        except Exception:
            await update.message.reply_text(t("invalid_input"))
            return SETTINGS_FORCE_JOIN_CHANNEL
    if val:
        channels=await _get_force_join_channels_admin()
        if val not in channels:
            channels.append(val)
        await db.set_setting("force_join_channels", json.dumps(channels))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:force_join"))
    return ConversationHandler.END

async def cb_set_plan_start_after_use(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    enabled=await db.get_setting("plan_start_after_use", "0")=="1"
    await db.set_setting("plan_start_after_use", "0" if enabled else "1")
    status=t("adm_enabled") if not enabled else t("adm_disabled")
    await query.answer(t("adm_plan_after_use_status", status=status), show_alert=True)
    await cb_adm_settings(update, ctx)

async def cb_set_trial_start_after_use(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    enabled=await db.get_setting("trial_start_after_use", "1")=="1"
    await db.set_setting("trial_start_after_use", "0" if enabled else "1")
    status=t("adm_enabled") if not enabled else t("adm_disabled")
    await query.answer(t("adm_trial_after_use_status", status=status), show_alert=True)
    await cb_adm_settings(update, ctx)

async def cb_set_update_http_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    current = settings.AUTO_UPDATE_HTTP_PROXY or ""
    await query.edit_message_text(t("adm_update_http_proxy_prompt", current=current or "-"), reply_markup=cancel_kb(), parse_mode="Markdown")
    return SETTINGS_UPDATE_HTTP_PROXY

async def settings_update_http_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val=="-":
        val=""
    from dotenv import set_key as dotenv_set
    dotenv_set("/opt/ghostpass/.env", "AUTO_UPDATE_HTTP_PROXY", val)
    settings.AUTO_UPDATE_HTTP_PROXY = val or None
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_update_https_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    current = settings.AUTO_UPDATE_HTTPS_PROXY or ""
    await query.edit_message_text(t("adm_update_https_proxy_prompt", current=current or "-"), reply_markup=cancel_kb(), parse_mode="Markdown")
    return SETTINGS_UPDATE_HTTPS_PROXY

async def settings_update_https_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val=="-":
        val=""
    from dotenv import set_key as dotenv_set
    dotenv_set("/opt/ghostpass/.env", "AUTO_UPDATE_HTTPS_PROXY", val)
    settings.AUTO_UPDATE_HTTPS_PROXY = val or None
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_usdt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    manual_enabled = await db.get_setting("manual_enabled", "1")=="1"
    trc20 = await db.get_setting("usdt_trc20_address", settings.USDT_TRC20_ADDRESS or "-")
    bsc = await db.get_setting("usdt_bsc_address", settings.USDT_BSC_ADDRESS or "-")
    polygon = await db.get_setting("usdt_polygon_address", settings.USDT_POLYGON_ADDRESS or "-")
    raw_rates = await db.get_setting("manual_chain_rates", None)
    rates = json.loads(raw_rates) if raw_rates else {}
    nr = t("adm_gp_pair_no_rate")
    rows = [
        [InlineKeyboardButton(t("adm_toggle_btn", status=f"Manual {t('adm_enabled') if manual_enabled else t('adm_disabled')}"), callback_data="set:manual_toggle")],
        [InlineKeyboardButton("TRC20 Address", callback_data="set:usdt_trc20"), InlineKeyboardButton(f"TRC20 Rate: {rates.get('TRC20', nr)}", callback_data="set:usdt_trc20_rate")],
        [InlineKeyboardButton("BSC Address", callback_data="set:usdt_bsc"), InlineKeyboardButton(f"BSC Rate: {rates.get('BSC', nr)}", callback_data="set:usdt_bsc_rate")],
        [InlineKeyboardButton("POLYGON Address", callback_data="set:usdt_polygon"), InlineKeyboardButton(f"POL Rate: {rates.get('POLYGON', nr)}", callback_data="set:usdt_pol_rate")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")],
    ]
    await query.edit_message_text(t("adm_usdt_title", status=t("adm_enabled") if manual_enabled else t("adm_disabled"), trc20=trc20, bsc=bsc, polygon=polygon), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_set_usdt_trc20(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_usdt_trc20"), reply_markup=cancel_kb())
    return SETTINGS_USDT_TRC20

async def settings_usdt_trc20(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("usdt_trc20_address", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:usdt"))
    return ConversationHandler.END

async def cb_set_usdt_bsc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_usdt_bsc"), reply_markup=cancel_kb())
    return SETTINGS_USDT_BSC

async def settings_usdt_bsc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("usdt_bsc_address", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:usdt"))
    return ConversationHandler.END

async def cb_set_usdt_polygon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_enter_usdt_polygon"), reply_markup=cancel_kb())
    return SETTINGS_USDT_POLYGON

async def settings_usdt_polygon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("usdt_polygon_address", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:usdt"))
    return ConversationHandler.END

async def cb_manual_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("manual_enabled", "1")=="1"
    await db.set_setting("manual_enabled", "0" if enabled else "1")
    await cb_set_usdt(update, ctx)

async def _save_manual_chain_rate(update, chain, err_state):
    try:
        exchange = Decimal(update.message.text.strip().replace(",", ""))
        if exchange<=0:
            raise ValueError
        rate = str(Decimal("1")/exchange)
    except Exception:
        await update.message.reply_text(t("invalid_input"))
        return err_state
    raw = await db.get_setting("manual_chain_rates", None)
    rates = json.loads(raw) if raw else {}
    rates[chain] = rate
    await db.set_setting("manual_chain_rates", json.dumps(rates))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:usdt"))
    return ConversationHandler.END

async def cb_set_usdt_trc20_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    base = await get_base_currency()
    await query.edit_message_text(t("adm_usdt_rate_prompt", chain="TRC20", base=base), reply_markup=cancel_kb())
    return SETTINGS_USDT_TRC20_RATE

async def settings_usdt_trc20_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _save_manual_chain_rate(update, "TRC20", SETTINGS_USDT_TRC20_RATE)

async def cb_set_usdt_bsc_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    base = await get_base_currency()
    await query.edit_message_text(t("adm_usdt_rate_prompt", chain="BSC", base=base), reply_markup=cancel_kb())
    return SETTINGS_USDT_BSC_RATE

async def settings_usdt_bsc_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _save_manual_chain_rate(update, "BSC", SETTINGS_USDT_BSC_RATE)

async def cb_set_usdt_pol_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    base = await get_base_currency()
    await query.edit_message_text(t("adm_usdt_rate_prompt", chain="POLYGON", base=base), reply_markup=cancel_kb())
    return SETTINGS_USDT_POL_RATE

async def settings_usdt_pol_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _save_manual_chain_rate(update, "POLYGON", SETTINGS_USDT_POL_RATE)

async def cb_set_currencies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    currencies = await get_currencies()
    base = await get_base_currency()
    if not currencies:
        rows = [[InlineKeyboardButton(t("btn_curr_add"), callback_data="curr:add"), InlineKeyboardButton(t("btn_curr_set_base"), callback_data="curr:set_base")]]
        rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")])
        await query.edit_message_text(t("curr_no_currencies", base=base), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")
        return
    await query.edit_message_text(t("curr_title", base=base), reply_markup=currencies_kb(currencies, base, "adm:settings"), parse_mode="Markdown")

async def cb_curr_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 2)[2]
    currencies = await get_currencies()
    base = await get_base_currency()
    c = next((x for x in currencies if x["code"]==code), None)
    if not c:
        await query.edit_message_text(t("adm_currency_not_found"))
        return
    methods_str = ", ".join(c.get("methods", [])) or "-"
    rate_str = c.get("rate", "1")
    text = t("curr_detail", code=c["code"], name=c["name"], decimals=c.get("decimals", 0), methods=methods_str, base=base, rate=rate_str)
    await query.edit_message_text(text, reply_markup=curr_detail_kb(code, code==base, "set:currencies"), parse_mode="Markdown")

async def cb_curr_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 2)[2]
    currencies = await get_currencies()
    currencies = [c for c in currencies if c["code"]!=code]
    await save_currencies(currencies)
    await query.edit_message_text(t("curr_deleted"), reply_markup=back_kb("set:currencies"))

async def cb_curr_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("curr_add_code"), reply_markup=cancel_kb())
    return CURR_ADD_CODE

async def curr_add_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_curr_code"] = update.message.text.strip().upper()
    await update.message.reply_text(t("curr_add_name"), reply_markup=cancel_kb())
    return CURR_ADD_NAME

async def curr_add_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_curr_name"] = update.message.text.strip()
    await update.message.reply_text(t("curr_add_decimals"), reply_markup=cancel_kb())
    return CURR_ADD_DECIMALS

async def curr_add_decimals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["new_curr_decimals"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return CURR_ADD_DECIMALS
    ctx.user_data["new_curr_methods"] = []
    kb = method_select_kb([], "curr:methods_done", "cancel")
    await update.message.reply_text(t("curr_add_methods"), reply_markup=kb)
    return CURR_ADD_METHODS

async def curr_toggle_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.split(":", 1)[1]
    selected = ctx.user_data.get("new_curr_methods", [])
    if method in selected:
        selected.remove(method)
    else:
        selected.append(method)
    ctx.user_data["new_curr_methods"] = selected
    kb = method_select_kb(selected, "curr:methods_done", "cancel")
    await query.edit_message_reply_markup(reply_markup=kb)
    return CURR_ADD_METHODS

async def curr_methods_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = ctx.user_data.get("new_curr_code", "")
    base = await get_base_currency()
    currencies = await get_currencies()
    if not currencies or code==base:
        await _save_new_currency(ctx, "1")
        await query.edit_message_text(t("curr_added", code=code), reply_markup=back_kb("set:currencies"))
        return ConversationHandler.END
    await query.edit_message_text(t("curr_add_rate_prompt", code=code, base=base), reply_markup=cancel_kb())
    return CURR_ADD_RATE

async def curr_add_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = ctx.user_data.get("new_curr_code", "")
    try:
        exchange = Decimal(update.message.text.strip().replace(",", ""))
        if exchange<=0:
            raise ValueError
        rate = str(Decimal("1")/exchange)
    except Exception:
        await update.message.reply_text(t("invalid_input"))
        return CURR_ADD_RATE
    await _save_new_currency(ctx, rate)
    await update.message.reply_text(t("curr_added", code=code), reply_markup=back_kb("set:currencies"))
    return ConversationHandler.END

async def _save_new_currency(ctx, rate):
    code = ctx.user_data.pop("new_curr_code", "")
    name = ctx.user_data.pop("new_curr_name", code)
    decimals = ctx.user_data.pop("new_curr_decimals", 2)
    methods = ctx.user_data.pop("new_curr_methods", [])
    currencies = await get_currencies()
    currencies = [c for c in currencies if c["code"]!=code]
    currencies.append({"code": code, "name": name, "decimals": decimals, "methods": methods, "rate": rate})
    await save_currencies(currencies)

async def cb_curr_edit_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 2)[2]
    base = await get_base_currency()
    ctx.user_data["editing_curr_code"] = code
    await query.edit_message_text(t("curr_add_rate_prompt", code=code, base=base), reply_markup=cancel_kb())
    return CURR_EDIT_RATE

async def curr_edit_rate_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = ctx.user_data.pop("editing_curr_code", None)
    if not code:
        return ConversationHandler.END
    try:
        exchange = Decimal(update.message.text.strip().replace(",", ""))
        if exchange<=0:
            raise ValueError
        rate = str(Decimal("1")/exchange)
    except Exception:
        await update.message.reply_text(t("invalid_input"))
        return CURR_EDIT_RATE
    currencies = await get_currencies()
    for c in currencies:
        if c["code"]==code:
            c["rate"] = rate
            break
    await save_currencies(currencies)
    await update.message.reply_text(t("curr_rate_updated"), reply_markup=back_kb("set:currencies"))
    return ConversationHandler.END

async def cb_curr_set_base_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    currencies = await get_currencies()
    if not currencies:
        await query.answer(t("adm_no_currencies_configured"), show_alert=True)
        return
    await query.edit_message_text(t("curr_set_base_prompt"), reply_markup=base_select_kb(currencies, "set:currencies"))

async def cb_curr_make_base(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 2)[2]
    await set_base_currency(code)
    currencies = await get_currencies()
    for c in currencies:
        if c["code"]==code:
            c["rate"] = "1"
            break
    await save_currencies(currencies)
    await query.edit_message_text(t("curr_base_set", code=code), reply_markup=back_kb("set:currencies"))

async def cb_subs_search_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_sub_search_prompt"), reply_markup=cancel_kb())
    return SUB_SEARCH

async def subs_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_str = update.message.text.strip()
    subs = await gg.list_subscriptions(per_page=0)
    results = [s for s in subs if query_str.lower() in (s.get("comment") or "").lower() or query_str in s.get("id", "")]
    if not results:
        await update.message.reply_text(t("adm_no_subs_found"), reply_markup=back_kb("adm:subs"))
        return ConversationHandler.END
    rows = [[InlineKeyboardButton(s.get("comment") or s["id"][:12], callback_data=f"adm:sub:detail:{s['id']}")] for s in results[:20]]
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:subs")])
    await update.message.reply_text(t("adm_search_results"), reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

async def cb_set_trial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await _is_admin(query.from_user.id):
        return
    enabled = await db.get_setting("trial_enabled", "0")=="1"
    data_gb = await db.get_setting("trial_data_gb", "0.5")
    expire_s_raw = int(await db.get_setting("trial_expire_seconds", "86400"))
    expire_h_val = expire_s_raw/3600
    expire_h = str(int(expire_h_val)) if expire_h_val==int(expire_h_val) else f"{expire_h_val:.1f}"
    node_ids = json.loads(await db.get_setting("trial_node_ids", "[]"))
    start_after_use = await db.get_setting("trial_start_after_use", "1")=="1"
    max_claims = await db.get_setting("trial_max_claims", "0")
    claim_count = await db.count_trial_claims()
    await query.edit_message_text(
        t("trial_settings", status=t("adm_enabled") if enabled else t("adm_disabled"), data_gb=data_gb, expire_h=expire_h, node_count=len(node_ids))+f"\n{t('adm_trial_after_use_status', status=t('adm_enabled') if start_after_use else t('adm_disabled'))}\n🔢 Claims: {claim_count}/{max_claims if max_claims!='0' else '∞'}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("adm_toggle_btn", status=t("adm_enabled") if enabled else t("adm_disabled")), callback_data="set:trial_toggle")],
            [InlineKeyboardButton(t("adm_trial_set_data"), callback_data="set:trial_data")],
            [InlineKeyboardButton(t("adm_trial_set_expire"), callback_data="set:trial_expire")],
            [InlineKeyboardButton(t("adm_trial_set_nodes"), callback_data="set:trial_nodes")],
            [InlineKeyboardButton(t("adm_trial_set_note"), callback_data="set:trial_note")],
            [InlineKeyboardButton(t("adm_trial_set_disabled_msg"), callback_data="set:trial_disabled_msg")],
            [InlineKeyboardButton(t("adm_trial_set_max_claims"), callback_data="set:trial_max_claims")],
            [InlineKeyboardButton(t("adm_trial_reset_claims_btn"), callback_data="set:trial_reset_claims")],
            [InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")],
        ]),
        parse_mode="Markdown"
    )

async def cb_trial_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await _is_admin(query.from_user.id):
        return
    enabled = await db.get_setting("trial_enabled", "0")=="1"
    await db.set_setting("trial_enabled", "0" if enabled else "1")
    await cb_set_trial(update, ctx)

async def cb_set_trial_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("trial_data_prompt"), reply_markup=cancel_kb())
    return SETTINGS_TRIAL_DATA

async def settings_trial_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if val<=0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_TRIAL_DATA
    await db.set_setting("trial_data_gb", str(val))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_set_trial_expire(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("trial_expire_prompt"), reply_markup=cancel_kb())
    return SETTINGS_TRIAL_EXPIRE

async def settings_trial_expire(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        hours = float(update.message.text.strip())
        if hours<=0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_TRIAL_EXPIRE
    await db.set_setting("trial_expire_seconds", str(int(hours*3600)))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_set_trial_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    stored = json.loads(await db.get_setting("trial_node_ids", "[]"))
    ctx.user_data["trial_nodes"]=list(stored)
    await query.edit_message_text(t("adm_trial_nodes_prompt"), reply_markup=node_select_kb(nodes, stored, "trial:nodes_done", "cancel", "trial:nodes_all", "trial:nodes_none"))
    return SETTINGS_TRIAL_NODES

async def trial_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nid = int(query.data.split(":", 1)[1])
    selected = ctx.user_data.get("trial_nodes", [])
    if nid in selected:
        selected.remove(nid)
    else:
        selected.append(nid)
    ctx.user_data["trial_nodes"]=selected
    nodes = await gg.list_nodes()
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "trial:nodes_done", "cancel", "trial:nodes_all", "trial:nodes_none"))
    return SETTINGS_TRIAL_NODES

async def trial_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    ctx.user_data["trial_nodes"]=_all_node_ids(nodes)
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, ctx.user_data["trial_nodes"], "trial:nodes_done", "cancel", "trial:nodes_all", "trial:nodes_none"))
    return SETTINGS_TRIAL_NODES

async def trial_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    ctx.user_data["trial_nodes"]=[]
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "trial:nodes_done", "cancel", "trial:nodes_all", "trial:nodes_none"))
    return SETTINGS_TRIAL_NODES

async def trial_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = ctx.user_data.pop("trial_nodes", [])
    await db.set_setting("trial_node_ids", json.dumps(selected))
    await query.edit_message_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_set_trial_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("trial_note", "") or "-"
    await query.edit_message_text(t("trial_note_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_TRIAL_NOTE

async def settings_trial_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    new_note = "" if val=="-" else val
    await db.set_setting("trial_note", new_note)
    trials = await db.list_trial_claims()
    sub_ids = [tc["ghostgate_sub_id"] for tc in trials if tc.get("ghostgate_sub_id")]
    if sub_ids:
        await gg.bulk_note(sub_ids, note=new_note or None)
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_set_trial_disabled_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("trial_disabled_message", "") or "-"
    await query.edit_message_text(t("adm_trial_disabled_msg_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_TRIAL_DISABLED_MSG

async def settings_trial_disabled_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    await db.set_setting("trial_disabled_message", "" if val=="-" else val)
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_set_trial_max_claims(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("trial_max_claims", "0")
    await query.edit_message_text(t("adm_trial_max_claims_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_TRIAL_MAX_CLAIMS

async def settings_trial_max_claims(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val<0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_TRIAL_MAX_CLAIMS
    await db.set_setting("trial_max_claims", str(val))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_trial_reset_claims(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    count = await db.reset_trial_claims()
    await query.answer(t("adm_trial_reset_claims_done", count=count), show_alert=True)
    await cb_set_trial(update, ctx)

async def cb_set_paid_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("paid_note", "") or "-"
    await query.edit_message_text(t("paid_note_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_PAID_NOTE

async def settings_paid_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    new_note = "" if val=="-" else val
    await db.set_setting("paid_note", new_note)
    orders = await db.get_paid_orders_with_sub()
    sub_ids = [o["ghostgate_sub_id"] for o in orders if o.get("ghostgate_sub_id")]
    if sub_ids:
        await gg.bulk_note(sub_ids, note=new_note or None)
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_start_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("start_msg", "") or "-"
    await query.edit_message_text(t("adm_start_msg_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_START_MSG

async def settings_start_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    await db.set_setting("start_msg", "" if val=="-" else val)
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def _show_snote_page(query, ctx):
    per_page = 10
    subs = ctx.user_data.get("snote_subs", [])
    selected = ctx.user_data.get("snote_selected", [])
    page = int(ctx.user_data.get("snote_page", 0))
    total = len(subs)
    max_page = max((total-1)//per_page, 0) if total>0 else 0
    page = max(0, min(page, max_page))
    ctx.user_data["snote_page"] = page
    start = page*per_page
    page_subs = subs[start:start+per_page]
    title = t("subs_bulk_note_title")
    if total>per_page:
        title += f"\n{t('plans_page_info', page=page+1, pages=max_page+1)}"
    await query.edit_message_text(title, reply_markup=subs_bulk_note_kb(page_subs, selected, page, total, per_page), parse_mode="Markdown")

async def cb_sub_bulk_note_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    subs = await gg.list_subscriptions(per_page=0)
    ctx.user_data["snote_subs"] = subs
    ctx.user_data["snote_selected"] = []
    ctx.user_data["snote_page"] = 0
    await _show_snote_page(query, ctx)
    return ADMIN_SUB_BULK_NOTE_SELECT

async def sub_bulk_note_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 1)[1]
    selected = ctx.user_data.get("snote_selected", [])
    if sub_id in selected:
        selected.remove(sub_id)
    else:
        selected.append(sub_id)
    ctx.user_data["snote_selected"] = selected
    await _show_snote_page(query, ctx)
    return ADMIN_SUB_BULK_NOTE_SELECT

async def sub_bulk_note_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["snote_selected"] = [s["id"] for s in ctx.user_data.get("snote_subs", [])]
    await _show_snote_page(query, ctx)
    return ADMIN_SUB_BULK_NOTE_SELECT

async def sub_bulk_note_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["snote_selected"] = []
    await _show_snote_page(query, ctx)
    return ADMIN_SUB_BULK_NOTE_SELECT

async def sub_bulk_note_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    direction = query.data.split(":", 1)[1]
    page = int(ctx.user_data.get("snote_page", 0))
    ctx.user_data["snote_page"] = page-1 if direction=="prev" else page+1
    await _show_snote_page(query, ctx)
    return ADMIN_SUB_BULK_NOTE_SELECT

async def sub_bulk_note_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = ctx.user_data.get("snote_selected", [])
    if not selected:
        await query.answer(t("adm_cancelled"), show_alert=True)
        return ADMIN_SUB_BULK_NOTE_SELECT
    await query.edit_message_text(t("subs_bulk_note_input"), reply_markup=cancel_kb())
    return ADMIN_SUB_BULK_NOTE_INPUT

async def sub_bulk_note_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    selected = ctx.user_data.pop("snote_selected", [])
    ctx.user_data.pop("snote_subs", None)
    ctx.user_data.pop("snote_page", None)
    await gg.bulk_note(selected, note=note or None)
    await update.message.reply_text(t("subs_bulk_note_done", count=len(selected)), reply_markup=back_kb("adm:subs"))
    return ConversationHandler.END

async def cb_cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    for k in ("plan_name", "plan_data", "plan_days", "plan_ip", "plan_price", "plan_nodes",
              "bulk_create_nodes",
              "msub_comment", "msub_data", "msub_days", "msub_ip", "msub_nodes", "msub_note",
              "new_admin_id", "editing_plan_id", "editing_plan_field", "editing_plan_nodes_id", "editing_plan_nodes", "bulk_plan_nodes", "bulk_node_plan_ids", "bulk_delete_plan_ids",
              "new_curr_code", "new_curr_name", "new_curr_decimals", "new_curr_methods", "editing_curr_code",
              "rejecting_order_id", "pending_order_id", "request_order_id", "trial_nodes",
              "snote_subs", "snote_selected", "snote_page"):
        ctx.user_data.pop(k, None)
    await query.edit_message_text(t("adm_cancelled"), reply_markup=back_kb("adm:back"))
    return ConversationHandler.END

async def cb_adm_offers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offers = await db.list_offers()
    if offers:
        lines = [t("adm_offer_item", name=o["name"], pct=o["discount_percent"], plan_count=len(o["plan_ids"]) if o["plan_ids"] else "all", status=t("adm_active") if o["is_active"] else t("adm_inactive")) for o in offers]
        list_text = "\n".join(lines)
    else:
        list_text = t("adm_offer_none")
    rows = [[InlineKeyboardButton(t("adm_offer_add_btn"), callback_data="offer:add")]]
    for o in offers:
        rows.append([InlineKeyboardButton(f"{'✅' if o['is_active'] else '❌'} {o['name']} — {o['discount_percent']}%", callback_data=f"offer:toggle:{o['id']}"), InlineKeyboardButton("🗑️", callback_data=f"offer:delete:{o['id']}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    await query.edit_message_text(t("adm_offers_title", list=list_text), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def cb_offer_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_offer_name_prompt"), reply_markup=cancel_kb())
    return OFFER_CREATE_NAME

async def offer_name_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_offer_name"] = update.message.text.strip()
    await update.message.reply_text(t("adm_offer_pct_prompt"), reply_markup=cancel_kb())
    return OFFER_CREATE_DISCOUNT

async def offer_pct_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if val<=0 or val>100:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return OFFER_CREATE_DISCOUNT
    ctx.user_data["new_offer_pct"] = val
    plans = await db.list_plans(active_only=False)
    ctx.user_data["new_offer_plan_ids"] = []
    await update.message.reply_text(t("adm_offer_plans_prompt"), reply_markup=_plan_select_kb(plans, [], "offer:plans_done", "cancel", "offer:plans_all", "offer:plans_none"))
    return OFFER_CREATE_PLANS

async def offer_plan_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 1)[1]
    selected = ctx.user_data.get("new_offer_plan_ids", [])
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    ctx.user_data["new_offer_plan_ids"] = selected
    plans = await db.list_plans(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "offer:plans_done", "cancel", "offer:plans_all", "offer:plans_none"))
    return OFFER_CREATE_PLANS

async def offer_plans_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plans = await db.list_plans(active_only=False)
    selected = [p["id"] for p in plans]
    ctx.user_data["new_offer_plan_ids"] = selected
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "offer:plans_done", "cancel", "offer:plans_all", "offer:plans_none"))
    return OFFER_CREATE_PLANS

async def offer_plans_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plans = await db.list_plans(active_only=False)
    ctx.user_data["new_offer_plan_ids"] = []
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, [], "offer:plans_done", "cancel", "offer:plans_all", "offer:plans_none"))
    return OFFER_CREATE_PLANS

async def offer_plans_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = ctx.user_data.pop("new_offer_name", "")
    pct = ctx.user_data.pop("new_offer_pct", 0)
    plan_ids = ctx.user_data.pop("new_offer_plan_ids", [])
    await db.create_offer(name, pct, plan_ids)
    await query.edit_message_text(t("adm_offer_created", name=name), reply_markup=back_kb("adm:offers"))
    return ConversationHandler.END

async def cb_offer_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offer_id = query.data.split(":", 2)[2]
    await db.toggle_offer(offer_id)
    await cb_adm_offers(update, ctx)

async def cb_offer_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offer_id = query.data.split(":", 2)[2]
    await db.delete_offer(offer_id)
    await cb_adm_offers(update, ctx)

async def cb_adm_discounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    codes = await db.list_discount_codes()
    plans_lookup = {p["id"]: p["name"] for p in await db.list_plans(active_only=False)}
    if codes:
        lines = []
        for c in codes:
            plan_ids = c.get("plan_ids") or []
            plans_str = ", ".join(plans_lookup.get(pid, pid) for pid in plan_ids) if plan_ids else t("adm_all_plans")
            max_amount = c.get("max_discount_amount") or 0
            lines.append(t("adm_discount_item", code=c["code"], pct=c["discount_percent"], max_amount=max_amount if max_amount else "∞", uses=c["uses"], max_uses=c["max_uses"] if c["max_uses"] else "∞", plans=plans_str, status=t("adm_active") if c["is_active"] else t("adm_inactive")))
        list_text = "\n".join(lines)
    else:
        list_text = t("adm_discount_none")
    rows = [[InlineKeyboardButton(t("adm_discount_add_btn"), callback_data="discount:add")]]
    for c in codes:
        rows.append([InlineKeyboardButton(f"{'✅' if c['is_active'] else '❌'} {c['code']} — {c['discount_percent']}% | toggle", callback_data=f"discount:toggle:{c['code']}"), InlineKeyboardButton("🗑️", callback_data=f"discount:delete:{c['code']}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    await query.edit_message_text(t("adm_discounts_title", list=list_text), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_discount_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_discount_code_prompt"), reply_markup=cancel_kb())
    return SETTINGS_DISCOUNT_CODE_CODE

async def discount_code_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip().upper()
    if not val.isalnum():
        await update.message.reply_text(t("adm_discount_invalid_code"))
        return SETTINGS_DISCOUNT_CODE_CODE
    existing = await db.get_discount_code(val)
    if existing:
        await update.message.reply_text(t("adm_discount_exists"))
        return SETTINGS_DISCOUNT_CODE_CODE
    ctx.user_data["new_discount_code"] = val
    await update.message.reply_text(t("adm_discount_pct_prompt"), reply_markup=cancel_kb())
    return SETTINGS_DISCOUNT_CODE_PCT

async def discount_pct_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if val<=0 or val>100:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_DISCOUNT_CODE_PCT
    ctx.user_data["new_discount_pct"] = val
    await update.message.reply_text(t("adm_discount_max_uses_prompt"), reply_markup=cancel_kb())
    return SETTINGS_DISCOUNT_CODE_MAXUSES

async def discount_maxuses_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val<0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_DISCOUNT_CODE_MAXUSES
    ctx.user_data["new_discount_maxuses"] = val
    ctx.user_data["new_discount_plan_ids"] = []
    plans = await db.list_plans(active_only=False)
    await update.message.reply_text(t("adm_discount_plans_prompt"), reply_markup=_plan_select_kb(plans, [], "discount:plans_done", "cancel", "discount:plans_all", "discount:plans_none"))
    return SETTINGS_DISCOUNT_CODE_PLANS

async def discount_plan_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 1)[1]
    selected = ctx.user_data.get("new_discount_plan_ids", [])
    if plan_id in selected:
        selected.remove(plan_id)
    else:
        selected.append(plan_id)
    ctx.user_data["new_discount_plan_ids"] = selected
    plans = await db.list_plans(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "discount:plans_done", "cancel", "discount:plans_all", "discount:plans_none"))
    return SETTINGS_DISCOUNT_CODE_PLANS

async def discount_plans_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plans = await db.list_plans(active_only=False)
    selected = [p["id"] for p in plans]
    ctx.user_data["new_discount_plan_ids"] = selected
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, selected, "discount:plans_done", "cancel", "discount:plans_all", "discount:plans_none"))
    return SETTINGS_DISCOUNT_CODE_PLANS

async def discount_plans_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plans = await db.list_plans(active_only=False)
    ctx.user_data["new_discount_plan_ids"] = []
    await query.edit_message_reply_markup(reply_markup=_plan_select_kb(plans, [], "discount:plans_done", "cancel", "discount:plans_all", "discount:plans_none"))
    return SETTINGS_DISCOUNT_CODE_PLANS

async def discount_plans_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_discount_max_amount_prompt"), reply_markup=cancel_kb())
    return SETTINGS_DISCOUNT_CODE_MAX_AMOUNT

async def discount_max_amount_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if val<0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_DISCOUNT_CODE_MAX_AMOUNT
    code = ctx.user_data.pop("new_discount_code", "")
    pct = ctx.user_data.pop("new_discount_pct", 0)
    max_uses = ctx.user_data.pop("new_discount_maxuses", 0)
    plan_ids = ctx.user_data.pop("new_discount_plan_ids", [])
    await db.create_discount_code(code, pct, max_uses, plan_ids, val)
    await update.message.reply_text(t("adm_discount_created", code=code), reply_markup=back_kb("adm:discounts"), parse_mode="Markdown")
    return ConversationHandler.END

async def cb_discount_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 2)[2]
    await db.toggle_discount_code(code)
    await cb_adm_discounts(update, ctx)

async def cb_discount_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":", 2)[2]
    await db.delete_discount_code(code)
    await cb_adm_discounts(update, ctx)

_LOG_PER_PAGE = 10

async def cb_adm_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["logs_page"] = 0
    await _show_logs(query, ctx)

async def cb_adm_logs_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    direction = query.data.split(":", 2)[2]
    page = ctx.user_data.get("logs_page", 0)
    ctx.user_data["logs_page"] = max(0, page + (1 if direction == "next" else -1))
    await _show_logs(query, ctx)

async def _show_logs(query, ctx):
    page = ctx.user_data.get("logs_page", 0)
    logs, total = await db.list_admin_logs(offset=page * _LOG_PER_PAGE, limit=_LOG_PER_PAGE)
    if logs:
        lines = "\n".join(t("adm_log_entry", created_at=l["created_at"][:16], admin_id=l["admin_id"], action=l["action"], details=f" — {(l['details'] or '').replace('_', chr(92)+'_')}" if l.get("details") else "") for l in logs)
    else:
        lines = t("adm_logs_empty")
    await query.edit_message_text(t("adm_logs_title", entries=lines), reply_markup=logs_kb(page, total, _LOG_PER_PAGE), parse_mode="Markdown")

async def cb_set_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("referral_enabled", "0")=="1"
    packages = await db.list_referral_packages()
    commission_enabled = await db.get_setting("referral_commission_enabled", "0")=="1"
    commission_pct = float(await db.get_setting("referral_commission_pct", "0") or "0")
    pkg_lines = "\n".join(t("adm_referral_pkg_item", name=p["name"], credits=p["credits_required"], data=p["data_gb"], days=p["days"], ip=p["ip_limit"], status=t("adm_active") if p["is_active"] else t("adm_inactive")) for p in packages) or t("adm_referral_pkg_none")
    text = t("adm_referral_title", status=t("adm_enabled") if enabled else t("adm_disabled"), packages=pkg_lines) + t("referral_commission_info", status=t("adm_enabled") if commission_enabled else t("adm_disabled"), pct=commission_pct)
    await query.edit_message_text(text, reply_markup=referral_settings_kb(enabled, packages, commission_enabled, commission_pct), parse_mode="Markdown")

async def cb_referral_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("referral_enabled", "0")=="1"
    await db.set_setting("referral_enabled", "0" if enabled else "1")
    await cb_set_referral(update, ctx)

async def cb_referral_commission_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("referral_commission_enabled", "0")=="1"
    await db.set_setting("referral_commission_enabled", "0" if enabled else "1")
    await cb_set_referral(update, ctx)

async def cb_referral_commission_pct_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_referral_commission_prompt"), reply_markup=cancel_kb())
    return SETTINGS_REF_COMMISSION_PCT

async def handle_referral_commission_pct(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if val<0 or val>100:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ConversationHandler.END
    await db.set_setting("referral_commission_pct", str(val))
    await update.message.reply_text(t("adm_wallet_adjusted", balance=val))
    return ConversationHandler.END

async def _credit_referral_commission(user_id, plan_price, bot):
    if await db.get_setting("referral_commission_enabled", "0")!="1":
        return
    try:
        pct = float(await db.get_setting("referral_commission_pct", "0") or "0")
    except Exception:
        return
    if pct<=0:
        return
    referrer_id = await db.get_referrer_for_user(user_id)
    if not referrer_id:
        return
    amount = round(float(plan_price)*pct/100, 2)
    if amount<=0:
        return
    await db.adjust_wallet(referrer_id, amount)
    referrer = await db.get_user_by_id(referrer_id)
    if referrer:
        try:
            await bot.send_message(int(referrer["telegram_id"]), t("referral_commission_earned", amount=amount))
        except Exception:
            pass

async def cb_ref_pkg_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data["ref_pkg"] = {}
    await query.edit_message_text(t("adm_referral_pkg_name_prompt"), reply_markup=cancel_kb())
    return REF_PKG_CREATE_NAME

async def ref_pkg_name_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ref_pkg"]["name"] = update.message.text.strip()
    await update.message.reply_text(t("adm_referral_pkg_credits_prompt"), reply_markup=cancel_kb())
    return REF_PKG_CREATE_CREDITS

async def ref_pkg_credits_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val<1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return REF_PKG_CREATE_CREDITS
    ctx.user_data["ref_pkg"]["credits"] = val
    await update.message.reply_text(t("adm_referral_pkg_data_prompt"), reply_markup=cancel_kb())
    return REF_PKG_CREATE_DATA

async def ref_pkg_data_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip())
        if val<0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return REF_PKG_CREATE_DATA
    ctx.user_data["ref_pkg"]["data_gb"] = val
    await update.message.reply_text(t("adm_referral_pkg_days_prompt"), reply_markup=cancel_kb())
    return REF_PKG_CREATE_DAYS

async def ref_pkg_days_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val<0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return REF_PKG_CREATE_DAYS
    ctx.user_data["ref_pkg"]["days"] = val
    await update.message.reply_text(t("adm_referral_pkg_ip_prompt"), reply_markup=cancel_kb())
    return REF_PKG_CREATE_IP

async def ref_pkg_ip_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val<0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return REF_PKG_CREATE_IP
    ctx.user_data["ref_pkg"]["ip_limit"] = val
    nodes = await gg.list_nodes()
    ctx.user_data["ref_pkg"]["node_ids"] = []
    await update.message.reply_text(t("adm_referral_pkg_nodes_prompt"), reply_markup=node_select_kb(nodes, [], "ref_pkg:nodes_done", "cancel", "ref_pkg:nodes_all", "ref_pkg:nodes_none"))
    return REF_PKG_CREATE_NODES

async def ref_pkg_node_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nid = int(query.data.split(":", 1)[1])
    ids = ctx.user_data["ref_pkg"].setdefault("node_ids", [])
    if nid in ids:
        ids.remove(nid)
    else:
        ids.append(nid)
    nodes = await gg.list_nodes()
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, ids, "ref_pkg:nodes_done", "cancel", "ref_pkg:nodes_all", "ref_pkg:nodes_none"))
    return REF_PKG_CREATE_NODES

async def ref_pkg_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    ctx.user_data["ref_pkg"]["node_ids"] = _all_node_ids(nodes)
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, ctx.user_data["ref_pkg"]["node_ids"], "ref_pkg:nodes_done", "cancel", "ref_pkg:nodes_all", "ref_pkg:nodes_none"))
    return REF_PKG_CREATE_NODES

async def ref_pkg_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["ref_pkg"]["node_ids"] = []
    nodes = await gg.list_nodes()
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "ref_pkg:nodes_done", "cancel", "ref_pkg:nodes_all", "ref_pkg:nodes_none"))
    return REF_PKG_CREATE_NODES

async def ref_pkg_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg = ctx.user_data.pop("ref_pkg", {})
    await db.create_referral_package(pkg["name"], pkg["credits"], pkg["data_gb"], pkg["days"], pkg["ip_limit"], pkg.get("node_ids", []))
    await query.edit_message_text(t("adm_referral_pkg_created"), reply_markup=back_kb("set:referral"))
    return ConversationHandler.END

async def cb_ref_pkg_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg_id = query.data.split(":", 2)[2]
    pkg = await db.get_referral_package(pkg_id)
    if not pkg:
        await query.edit_message_text(t("order_not_found"), reply_markup=back_kb("set:referral"))
        return
    data_text = t("adm_unlimited") if float(pkg["data_gb"])==0 else f"{pkg['data_gb']} GB"
    days_text = t("adm_no_expiry") if int(pkg["days"])==0 else f"{pkg['days']}d"
    ip_text = t("adm_unlimited") if int(pkg["ip_limit"])==0 else str(pkg["ip_limit"])
    await query.edit_message_text(t("adm_referral_pkg_detail", name=pkg["name"], data_text=data_text, days_text=days_text, ip_text=ip_text, credits=pkg["credits_required"], status=t("adm_active") if pkg["is_active"] else t("adm_inactive")), reply_markup=referral_pkg_admin_kb(pkg_id, pkg["is_active"]), parse_mode="Markdown")

async def cb_ref_pkg_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg_id = query.data.split(":", 2)[2]
    await db.toggle_referral_package(pkg_id)
    await cb_ref_pkg_detail(update, ctx)

async def cb_ref_pkg_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg_id = query.data.split(":", 2)[2]
    await db.delete_referral_package(pkg_id)
    await query.edit_message_text(t("adm_referral_pkg_deleted"), reply_markup=back_kb("set:referral"))

def _ref_pkg_select_kb(pkgs, selected_ids, done_cb, back_cb, all_cb, none_cb):
    rows=[]
    for p in pkgs:
        mark="✅" if p["id"] in selected_ids else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {p['name']}", callback_data=f"ref_pkg_select:{p['id']}")])
    rows.append([InlineKeyboardButton(t("btn_select_all"), callback_data=all_cb), InlineKeyboardButton(t("btn_unselect_all"), callback_data=none_cb)])
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data=done_cb), InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

async def cb_ref_pkg_edit_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    pkg_id=query.data.split(":", 3)[3]
    pkg=await db.get_referral_package(pkg_id)
    if not pkg:
        await query.edit_message_text(t("order_not_found"))
        return ConversationHandler.END
    nodes=await gg.list_nodes()
    if not nodes:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    selected=list(pkg.get("node_ids", []))
    ctx.user_data["editing_ref_pkg_nodes_id"]=pkg_id
    ctx.user_data["editing_ref_pkg_nodes"]=selected
    await query.edit_message_text(t("adm_referral_pkg_nodes_prompt"), reply_markup=node_select_kb(nodes, selected, "ref_pkg:edit_nodes_done", f"ref_pkg:detail:{pkg_id}", "ref_pkg:edit_nodes_all", "ref_pkg:edit_nodes_none"))
    return REF_PKG_EDIT_NODES

async def ref_pkg_edit_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    node_id=int(query.data.split(":", 1)[1])
    selected=ctx.user_data.get("editing_ref_pkg_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["editing_ref_pkg_nodes"]=selected
    nodes=await gg.list_nodes()
    pkg_id=ctx.user_data.get("editing_ref_pkg_nodes_id", "")
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "ref_pkg:edit_nodes_done", f"ref_pkg:detail:{pkg_id}", "ref_pkg:edit_nodes_all", "ref_pkg:edit_nodes_none"))
    return REF_PKG_EDIT_NODES

async def ref_pkg_edit_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    selected=_all_node_ids(nodes)
    ctx.user_data["editing_ref_pkg_nodes"]=selected
    pkg_id=ctx.user_data.get("editing_ref_pkg_nodes_id", "")
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "ref_pkg:edit_nodes_done", f"ref_pkg:detail:{pkg_id}", "ref_pkg:edit_nodes_all", "ref_pkg:edit_nodes_none"))
    return REF_PKG_EDIT_NODES

async def ref_pkg_edit_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    ctx.user_data["editing_ref_pkg_nodes"]=[]
    pkg_id=ctx.user_data.get("editing_ref_pkg_nodes_id", "")
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "ref_pkg:edit_nodes_done", f"ref_pkg:detail:{pkg_id}", "ref_pkg:edit_nodes_all", "ref_pkg:edit_nodes_none"))
    return REF_PKG_EDIT_NODES

async def ref_pkg_edit_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    pkg_id=ctx.user_data.pop("editing_ref_pkg_nodes_id", None)
    selected=ctx.user_data.pop("editing_ref_pkg_nodes", [])
    if not pkg_id:
        return ConversationHandler.END
    await db.update_referral_package(pkg_id, selected)
    await query.edit_message_text(t("setting_saved"), reply_markup=back_kb(f"ref_pkg:detail:{pkg_id}"))
    return ConversationHandler.END

async def cb_ref_pkgs_bulk_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query=update.callback_query
    await query.answer()
    pkgs=await db.list_referral_packages(active_only=False)
    if not pkgs:
        await query.edit_message_text(t("adm_referral_pkg_none"), reply_markup=back_kb("set:referral"))
        return ConversationHandler.END
    ctx.user_data["bulk_node_ref_pkg_ids"]=[]
    await query.edit_message_text(t("adm_referral_bulk_nodes_select_pkgs_prompt"), reply_markup=_ref_pkg_select_kb(pkgs, [], "ref_pkgs:bulk_nodes_pkgs_done", "set:referral", "ref_pkgs:bulk_nodes_pkgs_all", "ref_pkgs:bulk_nodes_pkgs_none"))
    return REF_PKG_BULK_NODES_PKGS

async def ref_pkgs_bulk_toggle_pkg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    pkg_id=query.data.split(":", 1)[1]
    selected=ctx.user_data.get("bulk_node_ref_pkg_ids", [])
    if pkg_id in selected:
        selected.remove(pkg_id)
    else:
        selected.append(pkg_id)
    ctx.user_data["bulk_node_ref_pkg_ids"]=selected
    pkgs=await db.list_referral_packages(active_only=False)
    await query.edit_message_reply_markup(reply_markup=_ref_pkg_select_kb(pkgs, selected, "ref_pkgs:bulk_nodes_pkgs_done", "set:referral", "ref_pkgs:bulk_nodes_pkgs_all", "ref_pkgs:bulk_nodes_pkgs_none"))
    return REF_PKG_BULK_NODES_PKGS

async def ref_pkgs_bulk_pkgs_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    pkgs=await db.list_referral_packages(active_only=False)
    selected=[p["id"] for p in pkgs]
    ctx.user_data["bulk_node_ref_pkg_ids"]=selected
    await query.edit_message_reply_markup(reply_markup=_ref_pkg_select_kb(pkgs, selected, "ref_pkgs:bulk_nodes_pkgs_done", "set:referral", "ref_pkgs:bulk_nodes_pkgs_all", "ref_pkgs:bulk_nodes_pkgs_none"))
    return REF_PKG_BULK_NODES_PKGS

async def ref_pkgs_bulk_pkgs_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    pkgs=await db.list_referral_packages(active_only=False)
    ctx.user_data["bulk_node_ref_pkg_ids"]=[]
    await query.edit_message_reply_markup(reply_markup=_ref_pkg_select_kb(pkgs, [], "ref_pkgs:bulk_nodes_pkgs_done", "set:referral", "ref_pkgs:bulk_nodes_pkgs_all", "ref_pkgs:bulk_nodes_pkgs_none"))
    return REF_PKG_BULK_NODES_PKGS

async def ref_pkgs_bulk_pkgs_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected_pkgs=ctx.user_data.get("bulk_node_ref_pkg_ids", [])
    if not selected_pkgs:
        await query.answer(t("invalid_input"), show_alert=True)
        return REF_PKG_BULK_NODES_PKGS
    nodes=await gg.list_nodes()
    if not nodes:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    ctx.user_data["bulk_ref_pkg_nodes"]=[]
    await query.edit_message_text(t("adm_plan_nodes_bulk_prompt"), reply_markup=node_select_kb(nodes, [], "ref_pkgs:bulk_nodes_done", "set:referral", "ref_pkgs:bulk_nodes_all", "ref_pkgs:bulk_nodes_none"))
    return REF_PKG_BULK_NODES

async def ref_pkgs_bulk_toggle_node(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    node_id=int(query.data.split(":", 1)[1])
    selected=ctx.user_data.get("bulk_ref_pkg_nodes", [])
    if node_id in selected:
        selected.remove(node_id)
    else:
        selected.append(node_id)
    ctx.user_data["bulk_ref_pkg_nodes"]=selected
    nodes=await gg.list_nodes()
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "ref_pkgs:bulk_nodes_done", "set:referral", "ref_pkgs:bulk_nodes_all", "ref_pkgs:bulk_nodes_none"))
    return REF_PKG_BULK_NODES

async def ref_pkgs_bulk_nodes_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    selected=_all_node_ids(nodes)
    ctx.user_data["bulk_ref_pkg_nodes"]=selected
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, selected, "ref_pkgs:bulk_nodes_done", "set:referral", "ref_pkgs:bulk_nodes_all", "ref_pkgs:bulk_nodes_none"))
    return REF_PKG_BULK_NODES

async def ref_pkgs_bulk_nodes_none(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    nodes=await gg.list_nodes()
    ctx.user_data["bulk_ref_pkg_nodes"]=[]
    await query.edit_message_reply_markup(reply_markup=node_select_kb(nodes, [], "ref_pkgs:bulk_nodes_done", "set:referral", "ref_pkgs:bulk_nodes_all", "ref_pkgs:bulk_nodes_none"))
    return REF_PKG_BULK_NODES

async def ref_pkgs_bulk_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    selected=ctx.user_data.pop("bulk_ref_pkg_nodes", [])
    target_ids=ctx.user_data.pop("bulk_node_ref_pkg_ids", [])
    pkgs=await db.list_referral_packages(active_only=False)
    count=0
    for pkg in pkgs:
        if pkg["id"] in target_ids:
            await db.update_referral_package(pkg["id"], selected)
            count+=1
    await query.edit_message_text(t("adm_referral_pkg_nodes_bulk_done", count=count), reply_markup=back_kb("set:referral"))
    return ConversationHandler.END

async def cb_adm_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(t("adm_broadcast_prompt"), reply_markup=cancel_kb())
    return ADMIN_BROADCAST_INPUT

async def broadcast_message_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    telegram_ids = await db.get_all_user_telegram_ids()
    total = len(telegram_ids)
    sent = 0
    for tid in telegram_ids:
        try:
            await ctx.bot.send_message(tid, update.message.text, parse_mode="Markdown")
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(t("adm_broadcast_done", sent=sent, total=total))
    return ConversationHandler.END

async def cb_adm_notifications(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keys = ["notify_discount", "notify_payment_link", "notify_purchase", "notify_trial", "notify_sub_start"]
    s = {k: await db.get_setting(k, "0") for k in keys}
    await query.edit_message_text(t("adm_notifications_title"), reply_markup=notifications_kb(s), parse_mode="Markdown")

async def cb_notif_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    current = await db.get_setting(key, "0")
    await db.set_setting(key, "0" if current=="1" else "1")
    keys = ["notify_discount", "notify_payment_link", "notify_purchase", "notify_trial", "notify_sub_start"]
    s = {k: await db.get_setting(k, "0") for k in keys}
    await query.edit_message_reply_markup(reply_markup=notifications_kb(s))

async def cb_notif_sub_start_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("sub_start_msg", "") or t("adm_notif_sub_start_msg_default")
    await query.edit_message_text(t("adm_notif_sub_start_msg_prompt", current=current), reply_markup=cancel_kb())
    return SETTINGS_NOTIF_SUB_MSG

async def notif_sub_start_msg_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    await db.set_setting("sub_start_msg", t("adm_notif_sub_start_msg_default") if text=="-" else text)
    await update.message.reply_text(t("setting_saved"))
    return ConversationHandler.END

def get_main_conv_handler():
    states = {
        WIZARD_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_url)],
        WIZARD_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_support), CallbackQueryHandler(wizard_skip_support, pattern=r"^wizard:skip_support$")],
        WIZARD_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_card_num), CallbackQueryHandler(wizard_skip_card, pattern=r"^wizard:skip_card$")],
        WIZARD_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_card_name), CallbackQueryHandler(wizard_skip_card_name, pattern=r"^wizard:skip_card_name$")],
        WIZARD_CRYPTO_MID: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_crypto_mid), CallbackQueryHandler(wizard_skip_crypto, pattern=r"^wizard:skip_crypto$")],
        WIZARD_CRYPTO_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_crypto_key), CallbackQueryHandler(wizard_skip_crypto, pattern=r"^wizard:skip_crypto$")],
        WIZARD_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_currency)],
        PLAN_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_name)],
        PLAN_CREATE_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_data)],
        PLAN_CREATE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_days)],
        PLAN_CREATE_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_ip)],
        PLAN_CREATE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_price)],
        PLAN_CREATE_NODES: [CallbackQueryHandler(plan_toggle_node, pattern=r"^node_toggle:"), CallbackQueryHandler(plan_nodes_done, pattern=r"^plan:nodes_done$")],
        PLAN_BULK_CREATE_NODES: [
            CallbackQueryHandler(plan_bulk_create_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(plan_bulk_create_nodes_all, pattern=r"^plan:bulk_create_nodes_all$"),
            CallbackQueryHandler(plan_bulk_create_nodes_none, pattern=r"^plan:bulk_create_nodes_none$"),
            CallbackQueryHandler(plan_bulk_create_nodes_done, pattern=r"^plan:bulk_create_nodes_done$")
        ],
        PLAN_BULK_CREATE_MATRIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_bulk_create_matrix_save)],
        PLAN_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_edit_value)],
        PLAN_EDIT_NODES: [
            CallbackQueryHandler(plan_edit_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(plan_edit_nodes_all, pattern=r"^plan:edit_nodes_all$"),
            CallbackQueryHandler(plan_edit_nodes_none, pattern=r"^plan:edit_nodes_none$"),
            CallbackQueryHandler(plan_edit_nodes_done, pattern=r"^plan:edit_nodes_done$")
        ],
        PLAN_BULK_NODES_PLANS: [
            CallbackQueryHandler(plans_bulk_nodes_toggle_plan, pattern=r"^plan_select:"),
            CallbackQueryHandler(plans_bulk_nodes_plans_all, pattern=r"^plans:bulk_nodes_plans_all$"),
            CallbackQueryHandler(plans_bulk_nodes_plans_none, pattern=r"^plans:bulk_nodes_plans_none$"),
            CallbackQueryHandler(plans_bulk_nodes_plans_done, pattern=r"^plans:bulk_nodes_plans_done$")
        ],
        PLAN_BULK_NODES: [
            CallbackQueryHandler(plans_bulk_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(plans_bulk_nodes_all, pattern=r"^plans:bulk_nodes_all$"),
            CallbackQueryHandler(plans_bulk_nodes_none, pattern=r"^plans:bulk_nodes_none$"),
            CallbackQueryHandler(plans_bulk_nodes_done, pattern=r"^plans:bulk_nodes_done$")
        ],
        PLAN_BULK_DELETE: [
            CallbackQueryHandler(plans_bulk_delete_toggle_plan, pattern=r"^plan_select:"),
            CallbackQueryHandler(plans_bulk_delete_all, pattern=r"^plans:bulk_delete_all$"),
            CallbackQueryHandler(plans_bulk_delete_none, pattern=r"^plans:bulk_delete_none$"),
            CallbackQueryHandler(plans_bulk_delete_done, pattern=r"^plans:bulk_delete_done$")
        ],
        ADMIN_ADD_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_id)],
        ADMIN_ADD_PERMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_perms)],
        ADMIN_MANUAL_SUB_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_comment)],
        ADMIN_MANUAL_SUB_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_data)],
        ADMIN_MANUAL_SUB_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_days)],
        ADMIN_MANUAL_SUB_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_ip)],
        ADMIN_MANUAL_SUB_NODES: [CallbackQueryHandler(manual_sub_toggle_node, pattern=r"^node_toggle:"), CallbackQueryHandler(manual_sub_nodes_all, pattern=r"^msub:nodes_all$"), CallbackQueryHandler(manual_sub_nodes_none, pattern=r"^msub:nodes_none$"), CallbackQueryHandler(manual_sub_done, pattern=r"^msub:nodes_done$")],
        ADMIN_MANUAL_SUB_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_note), CallbackQueryHandler(manual_sub_note_skip, pattern=r"^msub:note_skip$")],
        SETTINGS_GG_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_gg_url)],
        SETTINGS_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_card_num)],
        SETTINGS_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_card_name)],
        SETTINGS_CRYPTO_MID: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_crypto_mid)],
        SETTINGS_CRYPTO_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_crypto_key)],
        SETTINGS_GHOSTPAY_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_gp_url)],
        SETTINGS_GHOSTPAY_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_gp_key)],
        SETTINGS_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_support)],
        SETTINGS_SYNC: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_sync)],
        SETTINGS_FORCE_JOIN_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_force_join_channel)],
        SETTINGS_UPDATE_HTTP_PROXY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_update_http_proxy)],
        SETTINGS_UPDATE_HTTPS_PROXY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_update_https_proxy)],
        SETTINGS_PLAN_PAGE_SIZE_CONSUMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_plan_page_size_consumer)],
        SETTINGS_PLAN_PAGE_SIZE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_plan_page_size_admin)],
        SETTINGS_USDT_TRC20: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usdt_trc20)],
        SETTINGS_USDT_BSC: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usdt_bsc)],
        SETTINGS_USDT_POLYGON: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usdt_polygon)],
        SETTINGS_USDT_TRC20_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usdt_trc20_rate)],
        SETTINGS_USDT_BSC_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usdt_bsc_rate)],
        SETTINGS_USDT_POL_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_usdt_pol_rate)],
        USER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, users_search)],
        SUB_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, subs_search)],
        ADMIN_REJECT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reject_reason), CallbackQueryHandler(cb_reject_skip, pattern=r"^reject:skip$")],
        CURR_ADD_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, curr_add_code)],
        CURR_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, curr_add_name)],
        CURR_ADD_DECIMALS: [MessageHandler(filters.TEXT & ~filters.COMMAND, curr_add_decimals)],
        CURR_ADD_METHODS: [CallbackQueryHandler(curr_toggle_method, pattern=r"^meth_toggle:"), CallbackQueryHandler(curr_methods_done, pattern=r"^curr:methods_done$")],
        CURR_ADD_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, curr_add_rate)],
        CURR_EDIT_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, curr_edit_rate_save)],
        SETTINGS_TRIAL_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_trial_data)],
        SETTINGS_TRIAL_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_trial_expire)],
        SETTINGS_TRIAL_NODES: [CallbackQueryHandler(trial_toggle_node, pattern=r"^node_toggle:"), CallbackQueryHandler(trial_nodes_all, pattern=r"^trial:nodes_all$"), CallbackQueryHandler(trial_nodes_none, pattern=r"^trial:nodes_none$"), CallbackQueryHandler(trial_nodes_done, pattern=r"^trial:nodes_done$")],
        SETTINGS_TRIAL_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_trial_note)],
        SETTINGS_TRIAL_DISABLED_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_trial_disabled_msg)],
        SETTINGS_TRIAL_MAX_CLAIMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_trial_max_claims)],
        SETTINGS_PAID_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_paid_note)],
        SETTINGS_START_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_start_msg)],
        ADMIN_SUB_BULK_NOTE_SELECT: [
            CallbackQueryHandler(sub_bulk_note_toggle, pattern=r"^snote_toggle:"),
            CallbackQueryHandler(sub_bulk_note_all, pattern=r"^snote:all$"),
            CallbackQueryHandler(sub_bulk_note_none, pattern=r"^snote:none$"),
            CallbackQueryHandler(sub_bulk_note_page, pattern=r"^snote_page:"),
            CallbackQueryHandler(sub_bulk_note_prompt, pattern=r"^snote:done$"),
        ],
        ADMIN_SUB_BULK_NOTE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub_bulk_note_save)],
        SETTINGS_GP_PAIR_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, gp_pair_rate_save)],
        REF_PKG_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ref_pkg_name_input)],
        REF_PKG_CREATE_CREDITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ref_pkg_credits_input)],
        REF_PKG_CREATE_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ref_pkg_data_input)],
        REF_PKG_CREATE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ref_pkg_days_input)],
        REF_PKG_CREATE_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, ref_pkg_ip_input)],
        REF_PKG_CREATE_NODES: [
            CallbackQueryHandler(ref_pkg_node_toggle, pattern=r"^node_toggle:"),
            CallbackQueryHandler(ref_pkg_nodes_all, pattern=r"^ref_pkg:nodes_all$"),
            CallbackQueryHandler(ref_pkg_nodes_none, pattern=r"^ref_pkg:nodes_none$"),
            CallbackQueryHandler(ref_pkg_nodes_done, pattern=r"^ref_pkg:nodes_done$"),
        ],
        REF_PKG_EDIT_NODES: [
            CallbackQueryHandler(ref_pkg_edit_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(ref_pkg_edit_nodes_all, pattern=r"^ref_pkg:edit_nodes_all$"),
            CallbackQueryHandler(ref_pkg_edit_nodes_none, pattern=r"^ref_pkg:edit_nodes_none$"),
            CallbackQueryHandler(ref_pkg_edit_nodes_done, pattern=r"^ref_pkg:edit_nodes_done$"),
        ],
        REF_PKG_BULK_NODES_PKGS: [
            CallbackQueryHandler(ref_pkgs_bulk_toggle_pkg, pattern=r"^ref_pkg_select:"),
            CallbackQueryHandler(ref_pkgs_bulk_pkgs_all, pattern=r"^ref_pkgs:bulk_nodes_pkgs_all$"),
            CallbackQueryHandler(ref_pkgs_bulk_pkgs_none, pattern=r"^ref_pkgs:bulk_nodes_pkgs_none$"),
            CallbackQueryHandler(ref_pkgs_bulk_pkgs_done, pattern=r"^ref_pkgs:bulk_nodes_pkgs_done$"),
        ],
        REF_PKG_BULK_NODES: [
            CallbackQueryHandler(ref_pkgs_bulk_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(ref_pkgs_bulk_nodes_all, pattern=r"^ref_pkgs:bulk_nodes_all$"),
            CallbackQueryHandler(ref_pkgs_bulk_nodes_none, pattern=r"^ref_pkgs:bulk_nodes_none$"),
            CallbackQueryHandler(ref_pkgs_bulk_nodes_done, pattern=r"^ref_pkgs:bulk_nodes_done$"),
        ],
        SETTINGS_DISCOUNT_CODE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, discount_code_input)],
        SETTINGS_DISCOUNT_CODE_PCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, discount_pct_input)],
        SETTINGS_DISCOUNT_CODE_MAXUSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, discount_maxuses_input)],
        SETTINGS_DISCOUNT_CODE_PLANS: [
            CallbackQueryHandler(discount_plan_toggle, pattern=r"^plan_select:"),
            CallbackQueryHandler(discount_plans_all, pattern=r"^discount:plans_all$"),
            CallbackQueryHandler(discount_plans_none, pattern=r"^discount:plans_none$"),
            CallbackQueryHandler(discount_plans_done, pattern=r"^discount:plans_done$"),
        ],
        SETTINGS_DISCOUNT_CODE_MAX_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, discount_max_amount_input)],
        PLAN_BULK_ENABLE_DISABLE: [
            CallbackQueryHandler(plans_bulk_toggle_plan, pattern=r"^plan_select:"),
            CallbackQueryHandler(plans_bulk_toggle_all, pattern=r"^plans:bulk_toggle_all$"),
            CallbackQueryHandler(plans_bulk_toggle_none, pattern=r"^plans:bulk_toggle_none$"),
            CallbackQueryHandler(plans_bulk_toggle_done, pattern=r"^plans:bulk_toggle_done$"),
        ],
        PLAN_BULK_PRICE_MULTIPLY: [
            CallbackQueryHandler(plans_bulk_price_toggle, pattern=r"^plan_select:"),
            CallbackQueryHandler(plans_bulk_price_all, pattern=r"^plans:bulk_price_all$"),
            CallbackQueryHandler(plans_bulk_price_none, pattern=r"^plans:bulk_price_none$"),
            CallbackQueryHandler(plans_bulk_price_factor_prompt, pattern=r"^plans:bulk_price_done$"),
        ],
        PLAN_BULK_PRICE_FACTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, plans_bulk_price_factor_save)],
        OFFER_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_name_input)],
        OFFER_CREATE_DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_pct_input)],
        OFFER_CREATE_PLANS: [
            CallbackQueryHandler(offer_plan_toggle, pattern=r"^plan_select:"),
            CallbackQueryHandler(offer_plans_all, pattern=r"^offer:plans_all$"),
            CallbackQueryHandler(offer_plans_none, pattern=r"^offer:plans_none$"),
            CallbackQueryHandler(offer_plans_done, pattern=r"^offer:plans_done$"),
        ],
        ADMIN_BROADCAST_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message_input)],
        SETTINGS_NOTIF_SUB_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, notif_sub_start_msg_input)],
    }
    entry_points = [
        CommandHandler("start", cmd_start_admin),
        CallbackQueryHandler(cb_plan_create, pattern=r"^plan:create$"),
        CallbackQueryHandler(cb_plan_bulk_create, pattern=r"^plan:bulk_create$"),
        CallbackQueryHandler(cb_plan_edit_price, pattern=r"^plan:edit_price:"),
        CallbackQueryHandler(cb_plan_edit_name, pattern=r"^plan:edit_name:"),
        CallbackQueryHandler(cb_plan_edit_nodes, pattern=r"^plan:edit_nodes:"),
        CallbackQueryHandler(cb_plans_bulk_nodes, pattern=r"^plans:bulk_nodes$"),
        CallbackQueryHandler(cb_plans_bulk_delete, pattern=r"^plans:bulk_delete$"),
        CallbackQueryHandler(cb_plans_bulk_enable, pattern=r"^plans:bulk_enable$"),
        CallbackQueryHandler(cb_plans_bulk_disable, pattern=r"^plans:bulk_disable$"),
        CallbackQueryHandler(cb_plans_bulk_price_multiply, pattern=r"^plans:bulk_price_multiply$"),
        CallbackQueryHandler(cb_plans_bulk_price_divide, pattern=r"^plans:bulk_price_divide$"),
        CallbackQueryHandler(cb_discount_add, pattern=r"^discount:add$"),
        CallbackQueryHandler(cb_offer_add, pattern=r"^offer:add$"),
        CallbackQueryHandler(cb_sub_create, pattern=r"^sub:create$"),
        CallbackQueryHandler(cb_admin_add, pattern=r"^admin:add$"),
        CallbackQueryHandler(cb_users_search_prompt, pattern=r"^users:search$"),
        CallbackQueryHandler(cb_subs_search_prompt, pattern=r"^subs:search$"),
        CallbackQueryHandler(cb_set_gg_url, pattern=r"^set:gg_url$"),
        CallbackQueryHandler(cb_set_card_num, pattern=r"^set:card_num$"),
        CallbackQueryHandler(cb_set_card_name, pattern=r"^set:card_name$"),
        CallbackQueryHandler(cb_set_crypto_mid, pattern=r"^set:crypto_mid$"),
        CallbackQueryHandler(cb_set_crypto_key, pattern=r"^set:crypto_key$"),
        CallbackQueryHandler(cb_set_gp_url, pattern=r"^set:gp_url$"),
        CallbackQueryHandler(cb_set_gp_key, pattern=r"^set:gp_key$"),
        CallbackQueryHandler(cb_gp_pair_rate, pattern=r"^gp_pair:rate:"),
        CallbackQueryHandler(cb_set_support, pattern=r"^set:support$"),
        CallbackQueryHandler(cb_set_sync, pattern=r"^set:sync$"),
        CallbackQueryHandler(cb_set_plan_page_size_consumer, pattern=r"^set:plan_page_size_consumer$"),
        CallbackQueryHandler(cb_set_plan_page_size_admin, pattern=r"^set:plan_page_size_admin$"),
        CallbackQueryHandler(cb_set_force_join, pattern=r"^set:force_join$"),
        CallbackQueryHandler(cb_force_join_toggle, pattern=r"^set:force_join_toggle$"),
        CallbackQueryHandler(cb_set_force_join_channel, pattern=r"^set:force_join_channel$"),
        CallbackQueryHandler(cb_set_plan_start_after_use, pattern=r"^set:plan_start_after_use$"),
        CallbackQueryHandler(cb_set_trial_start_after_use, pattern=r"^set:trial_start_after_use$"),
        CallbackQueryHandler(cb_set_update_http_proxy, pattern=r"^set:update_http_proxy$"),
        CallbackQueryHandler(cb_set_update_https_proxy, pattern=r"^set:update_https_proxy$"),
        CallbackQueryHandler(cb_set_usdt_trc20, pattern=r"^set:usdt_trc20$"),
        CallbackQueryHandler(cb_set_usdt_bsc, pattern=r"^set:usdt_bsc$"),
        CallbackQueryHandler(cb_set_usdt_polygon, pattern=r"^set:usdt_polygon$"),
        CallbackQueryHandler(cb_set_usdt_trc20_rate, pattern=r"^set:usdt_trc20_rate$"),
        CallbackQueryHandler(cb_set_usdt_bsc_rate, pattern=r"^set:usdt_bsc_rate$"),
        CallbackQueryHandler(cb_set_usdt_pol_rate, pattern=r"^set:usdt_pol_rate$"),
        CallbackQueryHandler(cb_curr_add, pattern=r"^curr:add$"),
        CallbackQueryHandler(cb_set_trial_data, pattern=r"^set:trial_data$"),
        CallbackQueryHandler(cb_set_trial_expire, pattern=r"^set:trial_expire$"),
        CallbackQueryHandler(cb_set_trial_nodes, pattern=r"^set:trial_nodes$"),
        CallbackQueryHandler(cb_set_trial_note, pattern=r"^set:trial_note$"),
        CallbackQueryHandler(cb_set_trial_disabled_msg, pattern=r"^set:trial_disabled_msg$"),
        CallbackQueryHandler(cb_set_trial_max_claims, pattern=r"^set:trial_max_claims$"),
        CallbackQueryHandler(cb_set_paid_note, pattern=r"^set:paid_note$"),
        CallbackQueryHandler(cb_set_start_msg, pattern=r"^set:start_msg$"),
        CallbackQueryHandler(cb_sub_bulk_note_start, pattern=r"^subs:bulk_note$"),
        CallbackQueryHandler(cb_curr_edit_rate, pattern=r"^curr:edit_rate:"),
        CallbackQueryHandler(cb_reject_order, pattern=r"^order:reject:"),
        CallbackQueryHandler(cb_ref_pkg_create, pattern=r"^ref_pkg:create$"),
        CallbackQueryHandler(cb_ref_pkg_edit_nodes, pattern=r"^ref_pkg:edit_nodes:"),
        CallbackQueryHandler(cb_ref_pkgs_bulk_nodes, pattern=r"^ref_pkgs:bulk_nodes$"),
        CallbackQueryHandler(cb_adm_broadcast, pattern=r"^adm:broadcast$"),
        CallbackQueryHandler(cb_notif_sub_start_msg, pattern=r"^notif:sub_start_msg$"),
    ]
    return ConversationHandler(entry_points=entry_points, states=states, fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern=r"^cancel$")], per_message=False, name="admin_main")

def get_handlers():
    return [
        get_main_conv_handler(),
        CallbackQueryHandler(cb_adm_back, pattern=r"^adm:back$"),
        CallbackQueryHandler(cb_adm_plans, pattern=r"^adm:plans$"),
        CallbackQueryHandler(cb_adm_plans_page, pattern=r"^adm:plans_page:(prev|next)$"),
        CallbackQueryHandler(cb_plan_detail_admin, pattern=r"^plan:detail:"),
        CallbackQueryHandler(cb_plan_toggle, pattern=r"^plan:toggle:"),
        CallbackQueryHandler(cb_plan_delete, pattern=r"^plan:delete:"),
        CallbackQueryHandler(cb_adm_subs, pattern=r"^adm:subs$"),
        CallbackQueryHandler(cb_sub_detail, pattern=r"^adm:sub:detail:"),
        CallbackQueryHandler(cb_sub_stats, pattern=r"^sub:stats:"),
        CallbackQueryHandler(cb_sub_configs, pattern=r"^sub:configs:"),
        CallbackQueryHandler(cb_sub_delete, pattern=r"^adm:sub:delete:"),
        CallbackQueryHandler(cb_sub_reset_traffic, pattern=r"^adm:sub:reset_traffic:"),
        CallbackQueryHandler(cb_subs_page, pattern=r"^subs_page:"),
        CallbackQueryHandler(cb_adm_users, pattern=r"^adm:users$"),
        CallbackQueryHandler(cb_users_page, pattern=r"^users:page:"),
        CallbackQueryHandler(cb_user_detail, pattern=r"^user:detail:"),
        CallbackQueryHandler(cb_user_ban, pattern=r"^user:ban:"),
        CallbackQueryHandler(cb_user_unban, pattern=r"^user:unban:"),
        CallbackQueryHandler(cb_user_orders, pattern=r"^user:orders:"),
        CallbackQueryHandler(cb_user_reset_trial, pattern=r"^user:reset_trial:"),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(cb_user_wallet_add, pattern=r"^user:wallet_add:")],
            states={ADMIN_WALLET_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_add)]},
            fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern=r"^cancel$")],
            per_message=False,
        ),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(cb_user_wallet_remove, pattern=r"^user:wallet_remove:")],
            states={ADMIN_WALLET_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_remove)]},
            fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern=r"^cancel$")],
            per_message=False,
        ),
        CallbackQueryHandler(cb_user_wallet, pattern=r"^user:wallet:[A-Za-z0-9_-]{20}$"),
        CallbackQueryHandler(cb_adm_orders, pattern=r"^adm:orders$"),
        CallbackQueryHandler(cb_orders_list, pattern=r"^orders:list:"),
        CallbackQueryHandler(cb_orders_list_page, pattern=r"^orders:page:(prev|next)$"),
        CallbackQueryHandler(cb_order_detail, pattern=r"^order:detail:"),
        CallbackQueryHandler(cb_confirm_order, pattern=r"^order:confirm:"),
        CallbackQueryHandler(cb_adm_admins, pattern=r"^adm:admins$"),
        CallbackQueryHandler(cb_admin_detail, pattern=r"^admin:detail:"),
        CallbackQueryHandler(cb_admin_remove, pattern=r"^admin:remove:"),
        CallbackQueryHandler(cb_adm_settings, pattern=r"^adm:settings$"),
        CallbackQueryHandler(cb_set_plan_pagination, pattern=r"^set:plan_pagination$"),
        CallbackQueryHandler(cb_set_card, pattern=r"^set:card$"),
        CallbackQueryHandler(cb_card_toggle, pattern=r"^set:card_toggle$"),
        CallbackQueryHandler(cb_set_crypto, pattern=r"^set:crypto$"),
        CallbackQueryHandler(cb_crypto_toggle, pattern=r"^set:crypto_toggle$"),
        CallbackQueryHandler(cb_gp_toggle, pattern=r"^set:gp_toggle$"),
        CallbackQueryHandler(cb_set_gp_pairs, pattern=r"^set:gp_pairs$"),
        CallbackQueryHandler(cb_gp_pair_detail, pattern=r"^gp_pair:detail:"),
        CallbackQueryHandler(cb_gp_pair_toggle, pattern=r"^gp_pair:toggle:"),
        CallbackQueryHandler(cb_set_requests, pattern=r"^set:requests$"),
        CallbackQueryHandler(cb_req_toggle, pattern=r"^set:req_toggle$"),
        CallbackQueryHandler(cb_set_usdt, pattern=r"^set:usdt$"),
        CallbackQueryHandler(cb_manual_toggle, pattern=r"^set:manual_toggle$"),
        CallbackQueryHandler(cb_set_currencies, pattern=r"^set:currencies$"),
        CallbackQueryHandler(cb_curr_detail, pattern=r"^curr:detail:"),
        CallbackQueryHandler(cb_curr_delete, pattern=r"^curr:delete:"),
        CallbackQueryHandler(cb_curr_set_base_prompt, pattern=r"^curr:set_base$"),
        CallbackQueryHandler(cb_curr_make_base, pattern=r"^curr:make_base:"),
        CallbackQueryHandler(cb_set_trial, pattern=r"^set:trial$"),
        CallbackQueryHandler(cb_trial_toggle, pattern=r"^set:trial_toggle$"),
        CallbackQueryHandler(cb_adm_update, pattern=r"^adm:update$"),
        CallbackQueryHandler(cb_force_join_remove, pattern=r"^set:force_join_remove:\d+$"),
        CallbackQueryHandler(cb_trial_reset_claims, pattern=r"^set:trial_reset_claims$"),
        CallbackQueryHandler(cb_adm_discounts, pattern=r"^adm:discounts$"),
        CallbackQueryHandler(cb_discount_toggle, pattern=r"^discount:toggle:"),
        CallbackQueryHandler(cb_discount_delete, pattern=r"^discount:delete:"),
        CallbackQueryHandler(cb_adm_offers, pattern=r"^adm:offers$"),
        CallbackQueryHandler(cb_offer_toggle, pattern=r"^offer:toggle:"),
        CallbackQueryHandler(cb_offer_delete, pattern=r"^offer:delete:"),
        CallbackQueryHandler(cb_adm_logs, pattern=r"^adm:logs$"),
        CallbackQueryHandler(cb_adm_logs_page, pattern=r"^adm:logs_page:"),
        CallbackQueryHandler(cb_set_referral, pattern=r"^set:referral$"),
        CallbackQueryHandler(cb_referral_toggle, pattern=r"^set:referral_toggle$"),
        CallbackQueryHandler(cb_referral_commission_toggle, pattern=r"^set:referral_commission_toggle$"),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(cb_referral_commission_pct_prompt, pattern=r"^set:referral_commission_pct$")],
            states={SETTINGS_REF_COMMISSION_PCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_referral_commission_pct)]},
            fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern=r"^cancel$")],
            per_message=False,
        ),
        CallbackQueryHandler(cb_ref_pkg_detail, pattern=r"^ref_pkg:detail:"),
        CallbackQueryHandler(cb_ref_pkg_toggle, pattern=r"^ref_pkg:toggle:"),
        CallbackQueryHandler(cb_ref_pkg_delete, pattern=r"^ref_pkg:delete:"),
        CallbackQueryHandler(cb_adm_notifications, pattern=r"^adm:notifications$"),
        CallbackQueryHandler(cb_notif_toggle, pattern=r"^notif_toggle:"),
    ]
