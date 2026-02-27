import logging
import io
from datetime import datetime, timezone
from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)
import core.db as db
import core.ghostgate as gg
from core.currency import (
    get_currencies, save_currencies, get_base_currency, set_base_currency,
    convert, fmt as cfmt
)
from bot.keyboards import (
    main_admin_kb, settings_kb, back_kb, plan_actions_kb,
    user_actions_kb, sub_actions_kb, node_select_kb,
    order_detail_kb, skip_kb, cancel_kb, currencies_kb,
    method_select_kb, curr_detail_kb, base_select_kb
)
from bot.strings import t
from bot.states import (
    WIZARD_URL, WIZARD_SUPPORT, WIZARD_CARD_NUM, WIZARD_CARD_NAME,
    WIZARD_CRYPTO_MID, WIZARD_CRYPTO_KEY, WIZARD_CURRENCY,
    PLAN_CREATE_NAME, PLAN_CREATE_DATA, PLAN_CREATE_DAYS,
    PLAN_CREATE_IP, PLAN_CREATE_PRICE, PLAN_CREATE_NODES,
    PLAN_EDIT_VALUE,
    ADMIN_ADD_ID, ADMIN_ADD_PERMS,
    ADMIN_MANUAL_SUB_COMMENT, ADMIN_MANUAL_SUB_DATA, ADMIN_MANUAL_SUB_DAYS,
    ADMIN_MANUAL_SUB_IP, ADMIN_MANUAL_SUB_NODES,
    SETTINGS_CARD_NUM, SETTINGS_CARD_NAME,
    SETTINGS_CRYPTO_MID, SETTINGS_CRYPTO_KEY,
    SETTINGS_SUPPORT, SETTINGS_SYNC, SETTINGS_GG_URL,
    USER_SEARCH, SUB_SEARCH,
    ADMIN_REJECT_REASON,
    CURR_ADD_CODE, CURR_ADD_NAME, CURR_ADD_DECIMALS, CURR_ADD_METHODS, CURR_ADD_RATE, CURR_EDIT_RATE,
    SETTINGS_TRIAL_DATA, SETTINGS_TRIAL_EXPIRE, SETTINGS_TRIAL_NODES
)
from config import settings

logger = logging.getLogger(__name__)

async def _is_admin(telegram_id):
    return await db.is_admin(telegram_id, settings.ADMIN_ID)

async def cmd_start_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    if not settings.GHOSTGATE_URL:
        await update.message.reply_text(t("wizard_step1"), parse_mode="Markdown")
        return WIZARD_URL
    await update.message.reply_text(t("admin_menu_title"), reply_markup=main_admin_kb(), parse_mode="Markdown")
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
    await update.message.reply_text(t("admin_menu_title"), reply_markup=main_admin_kb(), parse_mode="Markdown")
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
    await query.edit_message_text(t("admin_menu_title"), reply_markup=main_admin_kb(), parse_mode="Markdown")

async def cb_adm_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plans = await db.list_plans(active_only=False)
    base = await get_base_currency()
    if not plans:
        rows = [[InlineKeyboardButton("➕ Create Plan", callback_data="plan:create")], [InlineKeyboardButton("⬅️ Back", callback_data="adm:back")]]
        await query.edit_message_text(t("no_plans_admin"), reply_markup=InlineKeyboardMarkup(rows))
        return
    rows = []
    for p in plans:
        status = "✅" if p["is_active"] else "❌"
        rows.append([InlineKeyboardButton(f"{status} {p['name']} — {p['price']} {base}", callback_data=f"plan:detail:{p['id']}")])
    rows.append([InlineKeyboardButton("➕ Create Plan", callback_data="plan:create")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:back")])
    await query.edit_message_text(t("plans_title"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_plan_detail_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    base = await get_base_currency()
    text = (
        f"📦 *{plan['name']}*\n"
        f"💾 {plan['data_gb']} GB / 📅 {plan['days']}d / 📱 {plan['ip_limit']} IPs\n"
        f"💰 {plan['price']} {base}\n"
        f"🔗 Nodes: {len(plan['node_ids'])}\n"
        f"Status: {'✅ Active' if plan['is_active'] else '❌ Inactive'}"
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
    await query.edit_message_text(t("plan_deleted"), reply_markup=back_kb("adm:plans"))

async def cb_plan_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📦 *Create Plan*\n\nEnter plan name:", parse_mode="Markdown", reply_markup=cancel_kb())
    return PLAN_CREATE_NAME

async def plan_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["plan_name"] = update.message.text.strip()
    await update.message.reply_text("Enter data limit in GB (e.g. 30):", reply_markup=cancel_kb())
    return PLAN_CREATE_DATA

async def plan_get_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["plan_data"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_DATA
    await update.message.reply_text("Enter duration in days (e.g. 30):", reply_markup=cancel_kb())
    return PLAN_CREATE_DAYS

async def plan_get_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["plan_days"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_DAYS
    await update.message.reply_text("Enter IP limit (e.g. 1):", reply_markup=cancel_kb())
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
    try:
        ctx.user_data["plan_price"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return PLAN_CREATE_PRICE
    ctx.user_data["plan_nodes"] = []
    nodes = await gg.list_nodes()
    if not nodes:
        await update.message.reply_text(t("ghostgate_error"))
        return ConversationHandler.END
    kb = node_select_kb(nodes, [], "plan:nodes_done", "cancel")
    await update.message.reply_text("Select nodes for this plan:", reply_markup=kb)
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

async def cb_plan_edit_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data["editing_plan_id"] = query.data.split(":", 2)[2]
    ctx.user_data["editing_plan_field"] = "price"
    await query.edit_message_text("Enter new price:", reply_markup=cancel_kb())
    return PLAN_EDIT_VALUE

async def cb_plan_edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data["editing_plan_id"] = query.data.split(":", 2)[2]
    ctx.user_data["editing_plan_field"] = "name"
    await query.edit_message_text("Enter new name:", reply_markup=cancel_kb())
    return PLAN_EDIT_VALUE

async def plan_edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    plan_id = ctx.user_data.pop("editing_plan_id", None)
    field = ctx.user_data.pop("editing_plan_field", None)
    if not plan_id or not field:
        return ConversationHandler.END
    val = update.message.text.strip()
    if field=="price":
        try:
            val = float(val)
        except ValueError:
            await update.message.reply_text(t("invalid_input"))
            return PLAN_EDIT_VALUE
    await db.update_plan(plan_id, **{field: val})
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:plans"))
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
    rows = [[InlineKeyboardButton(s.get("comment") or s["id"][:8], callback_data=f"sub:detail:{s['id']}")] for s in page_subs]
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data="subs_page:prev"))
    if start+per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data="subs_page:next"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔍 Search", callback_data="subs:search"), InlineKeyboardButton("➕ Create", callback_data="sub:create")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:back")])
    await query.edit_message_text(f"📋 *Subscriptions* ({total} total)\nPage {page+1}", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_sub_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    sub = await gg.get_subscription(sub_id)
    if not sub:
        await query.edit_message_text(t("sub_removed"))
        return
    data_used = (sub.get("used_bytes") or 0)/1073741824
    data_total = sub.get("data_gb") or 0
    expire = sub.get("expire_at") or "No Expiry"
    text = (
        f"📋 *Subscription*\n"
        f"ID: `{sub_id}`\n"
        f"Comment: {sub.get('comment') or '-'}\n"
        f"Data: {data_used:.2f} GB / {'Unlimited' if data_total==0 else f'{data_total} GB'}\n"
        f"Expires: {expire}\n"
        f"Status: {'✅ Active' if sub.get('enabled', 1) else '❌ Disabled'}"
    )
    await query.edit_message_text(text, reply_markup=sub_actions_kb(sub_id, "adm:subs"), parse_mode="Markdown")

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

async def cb_sub_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_id = query.data.split(":", 2)[2]
    await gg.delete_subscription(sub_id)
    await query.edit_message_text(t("sub_deleted"), reply_markup=back_kb("adm:subs"))

async def cb_sub_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter subscription comment (username or name):", reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_COMMENT

async def manual_sub_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["msub_comment"] = update.message.text.strip()
    await update.message.reply_text("Enter data GB (0 for unlimited):", reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_DATA

async def manual_sub_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["msub_data"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_MANUAL_SUB_DATA
    await update.message.reply_text("Enter duration in days (0 for no expiry):", reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_DAYS

async def manual_sub_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["msub_days"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_MANUAL_SUB_DAYS
    await update.message.reply_text("Enter IP limit (0 for unlimited):", reply_markup=cancel_kb())
    return ADMIN_MANUAL_SUB_IP

async def manual_sub_ip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["msub_ip"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_MANUAL_SUB_IP
    ctx.user_data["msub_nodes"] = []
    nodes = await gg.list_nodes()
    kb = node_select_kb(nodes, [], "msub:nodes_done", "cancel")
    await update.message.reply_text("Select nodes:", reply_markup=kb)
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
    kb = node_select_kb(nodes, selected, "msub:nodes_done", "cancel")
    await query.edit_message_reply_markup(reply_markup=kb)
    return ADMIN_MANUAL_SUB_NODES

async def manual_sub_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    result = await gg.create_subscription(
        comment=ctx.user_data.get("msub_comment", ""),
        data_gb=ctx.user_data.get("msub_data", 0),
        days=ctx.user_data.get("msub_days", 0),
        ip_limit=ctx.user_data.get("msub_ip", 0),
        node_ids=ctx.user_data.get("msub_nodes", [])
    )
    for k in ("msub_comment", "msub_data", "msub_days", "msub_ip", "msub_nodes"):
        ctx.user_data.pop(k, None)
    if not result:
        await query.edit_message_text(t("ghostgate_error"))
        return ConversationHandler.END
    sub_id = result.get("id")
    sub_url = result.get("url", "")
    await query.edit_message_text(t("sub_created_admin", sub_id=sub_id, url=sub_url), reply_markup=back_kb("adm:subs"), parse_mode="Markdown")
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
    users, total = await db.list_users(limit=5)
    text = f"👥 *Users* ({total} total)\n\nRecent users:\n"
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else str(u["telegram_id"])
        text += f"• {u.get('first_name') or ''} {uname}\n"
    rows = [[InlineKeyboardButton("🔍 Search user", callback_data="users:search")], [InlineKeyboardButton("⬅️ Back", callback_data="adm:back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_users_search_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter user ID or @username to search:", reply_markup=cancel_kb())
    return USER_SEARCH

async def users_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    results = await db.search_users(update.message.text.strip().lstrip("@"))
    if not results:
        await update.message.reply_text("No users found.", reply_markup=back_kb("adm:users"))
        return ConversationHandler.END
    rows = []
    for u in results:
        uname = f"@{u['username']}" if u.get("username") else str(u["telegram_id"])
        rows.append([InlineKeyboardButton(f"{u.get('first_name') or ''} {uname}".strip(), callback_data=f"user:detail:{u['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:users")])
    await update.message.reply_text("Search results:", reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

async def cb_user_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    user = await db.get_user_by_id(uid)
    if not user:
        await query.edit_message_text("User not found.")
        return
    uname = f"@{user['username']}" if user.get("username") else "-"
    text = (
        f"👤 *User*\n"
        f"Name: {user.get('first_name') or '-'}\n"
        f"Username: {uname}\n"
        f"Telegram ID: `{user['telegram_id']}`\n"
        f"Status: {'🚫 Banned' if user['is_banned'] else '✅ Active'}\n"
        f"Joined: {user['created_at'][:10]}"
    )
    await query.edit_message_text(text, reply_markup=user_actions_kb(uid, user["is_banned"], "adm:users"), parse_mode="Markdown")

async def cb_user_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    user = await db.get_user_by_id(uid)
    if user:
        await db.ban_user(user["telegram_id"], True)
    await query.edit_message_text(t("user_banned"), reply_markup=back_kb("adm:users"))

async def cb_user_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    user = await db.get_user_by_id(uid)
    if user:
        await db.ban_user(user["telegram_id"], False)
    await query.edit_message_text(t("user_unbanned"), reply_markup=back_kb("adm:users"))

async def cb_user_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split(":", 2)[2]
    orders = await db.get_orders_by_user(uid)
    if not orders:
        await query.edit_message_text("No orders found.", reply_markup=back_kb(f"user:detail:{uid}"))
        return
    rows = [[InlineKeyboardButton(f"{o['plan_name']} — {o['status']} — {o['created_at'][:10]}", callback_data=f"order:detail:{o['id']}")] for o in orders]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"user:detail:{uid}")])
    await query.edit_message_text("📋 User orders:", reply_markup=InlineKeyboardMarkup(rows))

async def cb_adm_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = await db.get_pending_orders()
    rows = [
        [InlineKeyboardButton("⏳ Pending/Waiting", callback_data="orders:list:waiting_confirm")],
        [InlineKeyboardButton("✅ Paid", callback_data="orders:list:paid")],
        [InlineKeyboardButton("❌ Rejected", callback_data="orders:list:rejected")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:back")],
    ]
    await query.edit_message_text(f"💰 *Orders*\n\n⏳ Pending: {len(pending)}", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_orders_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":", 2)[2]
    orders, total = await db.list_orders(status=None if status=="waiting_confirm" else status, limit=20)
    if status=="waiting_confirm":
        orders = [o for o in orders if o["status"] in ("pending", "waiting_confirm")]
    rows = [[InlineKeyboardButton(f"{o.get('plan_name','?')} — {o.get('first_name','?')} — {o['status']}", callback_data=f"order:detail:{o['id']}")] for o in orders[:20]]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:orders")])
    await query.edit_message_text(f"Orders ({len(orders)}):", reply_markup=InlineKeyboardMarkup(rows))

async def cb_order_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split(":", 2)[2]
    order = await db.get_order(order_id)
    if not order:
        await query.edit_message_text(t("order_not_found"))
        return
    user = await db.get_user_by_id(order["user_id"])
    plan = await db.get_plan(order["plan_id"])
    uname = f"@{user['username']}" if user and user.get("username") else str(user["telegram_id"] if user else "?")
    text = (
        f"💰 *Order*\nID: `{order_id}`\nUser: {uname}\n"
        f"Plan: {plan['name'] if plan else '?'}\nAmount: {order['amount']} {order['currency']}\n"
        f"Method: {order['payment_method']}\nStatus: {order['status']}\nCreated: {order['created_at'][:16]}"
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
        await query.answer("Already processed.", show_alert=True)
        return
    plan = await db.get_plan(order["plan_id"])
    user = await db.get_user_by_id(order["user_id"])
    if not plan or not user:
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
    await db.update_order(order_id, ghostgate_sub_id=sub_id, status="paid", paid_at=datetime.now(timezone.utc).isoformat())
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
    rows.append([InlineKeyboardButton("➕ Add Admin", callback_data="admin:add")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:back")])
    await query.edit_message_text(f"👑 *Admins*\nRoot: `{settings.ADMIN_ID}`", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter Telegram user ID of the new admin:", reply_markup=cancel_kb())
    return ADMIN_ADD_ID

async def admin_add_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["new_admin_id"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return ADMIN_ADD_ID
    await update.message.reply_text("Enter permissions (comma-separated: view, manage_subs, manage_plans, manage_users, superadmin):", reply_markup=cancel_kb())
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
        rows.append([InlineKeyboardButton("🗑️ Remove", callback_data=f"admin:remove:{admin_tid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:admins")])
    await query.edit_message_text(f"👑 Admin: `{admin_tid}`", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_admin_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_tid = int(query.data.split(":", 2)[2])
    if admin_tid==settings.ADMIN_ID:
        await query.answer("Cannot remove root admin.", show_alert=True)
        return
    await db.remove_admin(admin_tid)
    await query.edit_message_text(t("admin_removed"), reply_markup=back_kb("adm:admins"))

async def cb_adm_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚙️ *Settings*", reply_markup=settings_kb(), parse_mode="Markdown")

async def cb_set_gg_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    current = settings.GHOSTGATE_URL or "(not set)"
    await query.edit_message_text(f"Current: `{current}`\n\nEnter new GhostGate URL:", reply_markup=cancel_kb(), parse_mode="Markdown")
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
        [InlineKeyboardButton(f"Toggle: {'✅ Enabled' if card_enabled else '❌ Disabled'}", callback_data="set:card_toggle")],
        [InlineKeyboardButton("✏️ Edit Card Number", callback_data="set:card_num")],
        [InlineKeyboardButton("✏️ Edit Holder Name", callback_data="set:card_name")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:settings")],
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
    await query.edit_message_text("Enter new card number:", reply_markup=cancel_kb())
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
    await query.edit_message_text("Enter cardholder name:", reply_markup=cancel_kb())
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
    rows = [
        [InlineKeyboardButton(f"Toggle: {'✅ Enabled' if enabled else '❌ Disabled'}", callback_data="set:crypto_toggle")],
        [InlineKeyboardButton("✏️ Merchant ID", callback_data="set:crypto_mid")],
        [InlineKeyboardButton("✏️ API Key", callback_data="set:crypto_key")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:settings")],
    ]
    await query.edit_message_text(f"🪙 *Cryptomus*\n\nMerchant ID: `{mid}`", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_crypto_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("cryptomus_enabled", "0")=="1"
    await db.set_setting("cryptomus_enabled", "0" if enabled else "1")
    await cb_set_crypto(update, ctx)

async def cb_set_crypto_mid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update.effective_user.id):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter Cryptomus Merchant ID:", reply_markup=cancel_kb())
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
    await query.edit_message_text("Enter Cryptomus API Key:", reply_markup=cancel_kb())
    return SETTINGS_CRYPTO_KEY

async def settings_crypto_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("cryptomus_api_key", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:crypto"))
    return ConversationHandler.END

async def cb_set_requests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    enabled = await db.get_setting("requests_enabled", "0")=="1"
    rows = [
        [InlineKeyboardButton(f"Toggle: {'✅ Enabled' if enabled else '❌ Disabled'}", callback_data="set:req_toggle")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:settings")],
    ]
    await query.edit_message_text("🙋 *Request Flow*", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

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
    await query.edit_message_text(f"Current: {current}\n\nEnter support @username:", reply_markup=cancel_kb())
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
    await query.edit_message_text(f"Current: {settings.SYNC_INTERVAL}s\n\nEnter sync interval in seconds:", reply_markup=cancel_kb())
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

async def cb_set_currencies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    currencies = await get_currencies()
    base = await get_base_currency()
    if not currencies:
        rows = [[InlineKeyboardButton("➕ Add Currency", callback_data="curr:add"), InlineKeyboardButton("📌 Set Base", callback_data="curr:set_base")]]
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:settings")])
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
        await query.edit_message_text("Currency not found.")
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
        await query.answer("No currencies configured.", show_alert=True)
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
    await query.edit_message_text("Enter subscription ID or comment to search:", reply_markup=cancel_kb())
    return SUB_SEARCH

async def subs_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_str = update.message.text.strip()
    subs = await gg.list_subscriptions(per_page=0)
    results = [s for s in subs if query_str.lower() in (s.get("comment") or "").lower() or query_str in s.get("id", "")]
    if not results:
        await update.message.reply_text("No subscriptions found.", reply_markup=back_kb("adm:subs"))
        return ConversationHandler.END
    rows = [[InlineKeyboardButton(s.get("comment") or s["id"][:12], callback_data=f"sub:detail:{s['id']}")] for s in results[:20]]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:subs")])
    await update.message.reply_text("Search results:", reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

async def cb_set_trial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await _is_admin(query.from_user.id):
        return
    enabled = await db.get_setting("trial_enabled", "0")=="1"
    data_gb = await db.get_setting("trial_data_gb", "0.5")
    expire_h = int(await db.get_setting("trial_expire_seconds", "86400"))//3600
    node_ids = json.loads(await db.get_setting("trial_node_ids", "[]"))
    await query.edit_message_text(
        t("trial_settings", status="✅ Enabled" if enabled else "❌ Disabled", data_gb=data_gb, expire_h=expire_h, node_count=len(node_ids)),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Toggle: {'✅ Enabled' if enabled else '❌ Disabled'}", callback_data="set:trial_toggle")],
            [InlineKeyboardButton("✏️ Set Data GB", callback_data="set:trial_data")],
            [InlineKeyboardButton("✏️ Set Expire Time", callback_data="set:trial_expire")],
            [InlineKeyboardButton("🖥️ Configure Nodes", callback_data="set:trial_nodes")],
            [InlineKeyboardButton("⬅️ Back", callback_data="adm:settings")],
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
        hours = int(update.message.text.strip())
        if hours<=0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t("invalid_input"))
        return SETTINGS_TRIAL_EXPIRE
    await db.set_setting("trial_expire_seconds", str(hours*3600))
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_set_trial_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    nodes = await gg.list_nodes()
    stored = json.loads(await db.get_setting("trial_node_ids", "[]"))
    ctx.user_data["trial_nodes"]=list(stored)
    await query.edit_message_text("🎁 Select nodes for trial subscription:", reply_markup=node_select_kb(nodes, stored, "trial:nodes_done", "cancel"))
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
    await query.edit_message_text("🎁 Select nodes for trial subscription:", reply_markup=node_select_kb(nodes, selected, "trial:nodes_done", "cancel"))
    return SETTINGS_TRIAL_NODES

async def trial_nodes_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = ctx.user_data.pop("trial_nodes", [])
    await db.set_setting("trial_node_ids", json.dumps(selected))
    await query.edit_message_text(t("setting_saved"), reply_markup=back_kb("set:trial"))
    return ConversationHandler.END

async def cb_cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    for k in ("plan_name", "plan_data", "plan_days", "plan_ip", "plan_price", "plan_nodes",
              "msub_comment", "msub_data", "msub_days", "msub_ip", "msub_nodes",
              "new_admin_id", "editing_plan_id", "editing_plan_field",
              "new_curr_code", "new_curr_name", "new_curr_decimals", "new_curr_methods", "editing_curr_code",
              "rejecting_order_id", "pending_order_id", "request_order_id", "trial_nodes"):
        ctx.user_data.pop(k, None)
    await query.edit_message_text("❌ Cancelled.", reply_markup=back_kb("adm:back"))
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
        PLAN_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_edit_value)],
        ADMIN_ADD_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_id)],
        ADMIN_ADD_PERMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_perms)],
        ADMIN_MANUAL_SUB_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_comment)],
        ADMIN_MANUAL_SUB_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_data)],
        ADMIN_MANUAL_SUB_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_days)],
        ADMIN_MANUAL_SUB_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_ip)],
        ADMIN_MANUAL_SUB_NODES: [CallbackQueryHandler(manual_sub_toggle_node, pattern=r"^node_toggle:"), CallbackQueryHandler(manual_sub_done, pattern=r"^msub:nodes_done$")],
        SETTINGS_GG_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_gg_url)],
        SETTINGS_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_card_num)],
        SETTINGS_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_card_name)],
        SETTINGS_CRYPTO_MID: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_crypto_mid)],
        SETTINGS_CRYPTO_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_crypto_key)],
        SETTINGS_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_support)],
        SETTINGS_SYNC: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_sync)],
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
        SETTINGS_TRIAL_NODES: [CallbackQueryHandler(trial_toggle_node, pattern=r"^node_toggle:"), CallbackQueryHandler(trial_nodes_done, pattern=r"^trial:nodes_done$")],
    }
    entry_points = [
        CommandHandler("start", cmd_start_admin),
        CallbackQueryHandler(cb_plan_create, pattern=r"^plan:create$"),
        CallbackQueryHandler(cb_plan_edit_price, pattern=r"^plan:edit_price:"),
        CallbackQueryHandler(cb_plan_edit_name, pattern=r"^plan:edit_name:"),
        CallbackQueryHandler(cb_sub_create, pattern=r"^sub:create$"),
        CallbackQueryHandler(cb_admin_add, pattern=r"^admin:add$"),
        CallbackQueryHandler(cb_users_search_prompt, pattern=r"^users:search$"),
        CallbackQueryHandler(cb_subs_search_prompt, pattern=r"^subs:search$"),
        CallbackQueryHandler(cb_set_gg_url, pattern=r"^set:gg_url$"),
        CallbackQueryHandler(cb_set_card_num, pattern=r"^set:card_num$"),
        CallbackQueryHandler(cb_set_card_name, pattern=r"^set:card_name$"),
        CallbackQueryHandler(cb_set_crypto_mid, pattern=r"^set:crypto_mid$"),
        CallbackQueryHandler(cb_set_crypto_key, pattern=r"^set:crypto_key$"),
        CallbackQueryHandler(cb_set_support, pattern=r"^set:support$"),
        CallbackQueryHandler(cb_set_sync, pattern=r"^set:sync$"),
        CallbackQueryHandler(cb_curr_add, pattern=r"^curr:add$"),
        CallbackQueryHandler(cb_set_trial_data, pattern=r"^set:trial_data$"),
        CallbackQueryHandler(cb_set_trial_expire, pattern=r"^set:trial_expire$"),
        CallbackQueryHandler(cb_set_trial_nodes, pattern=r"^set:trial_nodes$"),
        CallbackQueryHandler(cb_curr_edit_rate, pattern=r"^curr:edit_rate:"),
        CallbackQueryHandler(cb_reject_order, pattern=r"^order:reject:"),
    ]
    return ConversationHandler(entry_points=entry_points, states=states, fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern=r"^cancel$")], per_message=False, name="admin_main")

def get_handlers():
    return [
        get_main_conv_handler(),
        CallbackQueryHandler(cb_adm_back, pattern=r"^adm:back$"),
        CallbackQueryHandler(cb_adm_plans, pattern=r"^adm:plans$"),
        CallbackQueryHandler(cb_plan_detail_admin, pattern=r"^plan:detail:"),
        CallbackQueryHandler(cb_plan_toggle, pattern=r"^plan:toggle:"),
        CallbackQueryHandler(cb_plan_delete, pattern=r"^plan:delete:"),
        CallbackQueryHandler(cb_adm_subs, pattern=r"^adm:subs$"),
        CallbackQueryHandler(cb_sub_detail, pattern=r"^sub:detail:"),
        CallbackQueryHandler(cb_sub_stats, pattern=r"^sub:stats:"),
        CallbackQueryHandler(cb_sub_delete, pattern=r"^sub:delete:"),
        CallbackQueryHandler(cb_subs_page, pattern=r"^subs_page:"),
        CallbackQueryHandler(cb_adm_users, pattern=r"^adm:users$"),
        CallbackQueryHandler(cb_user_detail, pattern=r"^user:detail:"),
        CallbackQueryHandler(cb_user_ban, pattern=r"^user:ban:"),
        CallbackQueryHandler(cb_user_unban, pattern=r"^user:unban:"),
        CallbackQueryHandler(cb_user_orders, pattern=r"^user:orders:"),
        CallbackQueryHandler(cb_adm_orders, pattern=r"^adm:orders$"),
        CallbackQueryHandler(cb_orders_list, pattern=r"^orders:list:"),
        CallbackQueryHandler(cb_order_detail, pattern=r"^order:detail:"),
        CallbackQueryHandler(cb_confirm_order, pattern=r"^order:confirm:"),
        CallbackQueryHandler(cb_adm_admins, pattern=r"^adm:admins$"),
        CallbackQueryHandler(cb_admin_detail, pattern=r"^admin:detail:"),
        CallbackQueryHandler(cb_admin_remove, pattern=r"^admin:remove:"),
        CallbackQueryHandler(cb_adm_settings, pattern=r"^adm:settings$"),
        CallbackQueryHandler(cb_set_card, pattern=r"^set:card$"),
        CallbackQueryHandler(cb_card_toggle, pattern=r"^set:card_toggle$"),
        CallbackQueryHandler(cb_set_crypto, pattern=r"^set:crypto$"),
        CallbackQueryHandler(cb_crypto_toggle, pattern=r"^set:crypto_toggle$"),
        CallbackQueryHandler(cb_set_requests, pattern=r"^set:requests$"),
        CallbackQueryHandler(cb_req_toggle, pattern=r"^set:req_toggle$"),
        CallbackQueryHandler(cb_set_currencies, pattern=r"^set:currencies$"),
        CallbackQueryHandler(cb_curr_detail, pattern=r"^curr:detail:"),
        CallbackQueryHandler(cb_curr_delete, pattern=r"^curr:delete:"),
        CallbackQueryHandler(cb_curr_set_base_prompt, pattern=r"^curr:set_base$"),
        CallbackQueryHandler(cb_curr_make_base, pattern=r"^curr:make_base:"),
        CallbackQueryHandler(cb_set_trial, pattern=r"^set:trial$"),
        CallbackQueryHandler(cb_trial_toggle, pattern=r"^set:trial_toggle$"),
    ]
