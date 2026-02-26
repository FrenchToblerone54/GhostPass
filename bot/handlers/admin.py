import logging
import io
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)
import core.db as db
import core.ghostgate as gg
from bot.keyboards import (
    main_admin_kb, settings_kb, back_kb, plan_actions_kb,
    user_actions_kb, sub_actions_kb, node_select_kb,
    order_detail_kb, skip_kb, cancel_kb
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
    SETTINGS_SUPPORT, SETTINGS_CURRENCY, SETTINGS_SYNC, SETTINGS_GG_URL,
    USER_SEARCH, SUB_SEARCH,
    ADMIN_BROADCAST
)
from config import settings

logger = logging.getLogger(__name__)

async def _is_admin(telegram_id):
    return await db.is_admin(telegram_id, settings.ADMIN_ID)

async def _require_admin(update):
    if not await _is_admin(update.effective_user.id):
        return False
    return True

async def cmd_start_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update):
        return
    gg_url = settings.GHOSTGATE_URL
    if not gg_url:
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
    await query.edit_message_text(t("wizard_step3a"))
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
    await query.edit_message_text(t("wizard_step3c"))
    return WIZARD_CRYPTO_MID

async def wizard_skip_card_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["wizard_card_name"] = ""
    await query.edit_message_text(t("wizard_step3c"))
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
    currency = update.message.text.strip()
    await _wizard_save(ctx, currency, update)
    await update.message.reply_text(t("wizard_done"))
    await update.message.reply_text(t("admin_menu_title"), reply_markup=main_admin_kb(), parse_mode="Markdown")
    return ConversationHandler.END

async def _wizard_save(ctx, currency, update):
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
    await db.set_setting("currency", currency)
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
    if not plans:
        rows = [[InlineKeyboardButton("➕ Create Plan", callback_data="plan:create")]]
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:back")])
        await query.edit_message_text(t("no_plans_admin"), reply_markup=InlineKeyboardMarkup(rows))
        return
    currency = await db.get_setting("currency", "USD")
    rows = []
    for p in plans:
        status = "✅" if p["is_active"] else "❌"
        rows.append([InlineKeyboardButton(f"{status} {p['name']} — {p['price']} {currency}", callback_data=f"plan:detail:{p['id']}")])
    rows.append([InlineKeyboardButton("➕ Create Plan", callback_data="plan:create")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:back")])
    await query.edit_message_text(t("plans_title"), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_plan_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    plan = await db.get_plan(plan_id)
    if not plan:
        await query.edit_message_text(t("order_not_found"))
        return
    currency = await db.get_setting("currency", "USD")
    text = (
        f"📦 *{plan['name']}*\n"
        f"💾 {plan['data_gb']} GB / 📅 {plan['days']} days / 📱 {plan['ip_limit']} IPs\n"
        f"💰 {plan['price']} {currency}\n"
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
    await cb_plan_detail(update, ctx)

async def cb_plan_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    await db.delete_plan(plan_id)
    await query.edit_message_text(t("plan_deleted"), reply_markup=back_kb("adm:plans"))

async def cb_plan_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text("Enter price (e.g. 50000):", reply_markup=cancel_kb())
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
    plan_id = await db.create_plan(
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
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    ctx.user_data["editing_plan_id"] = plan_id
    ctx.user_data["editing_plan_field"] = "price"
    await query.edit_message_text("Enter new price:", reply_markup=cancel_kb())
    return PLAN_EDIT_VALUE

async def cb_plan_edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_id = query.data.split(":", 2)[2]
    ctx.user_data["editing_plan_id"] = plan_id
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
    rows = []
    for s in page_subs:
        label = s.get("comment") or s["id"][:8]
        rows.append([InlineKeyboardButton(label, callback_data=f"sub:detail:{s['id']}")])
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
    rows = [
        [InlineKeyboardButton("🔍 Search user", callback_data="users:search")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:back")],
    ]
    users, total = await db.list_users(limit=5)
    text = f"👥 *Users* ({total} total)\n\nRecent users:\n"
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else str(u["telegram_id"])
        text += f"• {u.get('first_name') or ''} {uname}\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_users_search_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter user ID or @username to search:", reply_markup=cancel_kb())
    return USER_SEARCH

async def users_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_str = update.message.text.strip().lstrip("@")
    results = await db.search_users(query_str)
    if not results:
        await update.message.reply_text("No users found.", reply_markup=back_kb("adm:users"))
        return ConversationHandler.END
    rows = []
    for u in results:
        uname = f"@{u['username']}" if u.get("username") else str(u["telegram_id"])
        label = f"{u.get('first_name') or ''} {uname}".strip()
        rows.append([InlineKeyboardButton(label, callback_data=f"user:detail:{u['id']}")])
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
    rows = []
    for o in orders:
        label = f"{o['plan_name']} — {o['status']} — {o['created_at'][:10]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"order:detail:{o['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"user:detail:{uid}")])
    await query.edit_message_text("📋 User orders:", reply_markup=InlineKeyboardMarkup(rows))

async def cb_adm_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = [
        [InlineKeyboardButton("⏳ Pending/Waiting", callback_data="orders:list:waiting_confirm")],
        [InlineKeyboardButton("✅ Paid", callback_data="orders:list:paid")],
        [InlineKeyboardButton("❌ Rejected", callback_data="orders:list:rejected")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:back")],
    ]
    pending = await db.get_pending_orders()
    await query.edit_message_text(f"💰 *Orders*\n\n⏳ Pending: {len(pending)}", reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_orders_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split(":", 2)[2]
    orders, total = await db.list_orders(status=status if status!="waiting_confirm" else None, limit=20)
    if status=="waiting_confirm":
        orders = [o for o in orders if o["status"] in ("pending", "waiting_confirm")]
        total = len(orders)
    rows = []
    for o in orders[:20]:
        label = f"{o.get('plan_name','?')} — {o.get('first_name','?')} — {o['status']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"order:detail:{o['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:orders")])
    await query.edit_message_text(f"Orders ({total}):", reply_markup=InlineKeyboardMarkup(rows))

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
        f"💰 *Order*\n"
        f"ID: `{order_id}`\n"
        f"User: {uname}\n"
        f"Plan: {plan['name'] if plan else '?'}\n"
        f"Amount: {order['amount']} {order['currency']}\n"
        f"Method: {order['payment_method']}\n"
        f"Status: {order['status']}\n"
        f"Created: {order['created_at'][:16]}"
    )
    if order.get("receipt_file_id") and order["status"] in ("pending", "waiting_confirm"):
        await query.message.reply_photo(order["receipt_file_id"])
    await query.edit_message_text(text, reply_markup=order_detail_kb(order_id, order["status"], "adm:orders"), parse_mode="Markdown")

async def cb_adm_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admins = await db.list_admins()
    rows = []
    for a in admins:
        perms = ", ".join(a.get("permissions", ["view"]) if isinstance(a.get("permissions"), list) else [a.get("permissions", "view")])
        rows.append([InlineKeyboardButton(f"👑 {a['telegram_id']} — {perms[:20]}", callback_data=f"admin:detail:{a['telegram_id']}")])
    rows.append([InlineKeyboardButton("➕ Add Admin", callback_data="admin:add")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:back")])
    text = f"👑 *Admins*\nRoot: `{settings.ADMIN_ID}`"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def cb_admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter new card number:", reply_markup=cancel_kb())
    return SETTINGS_CARD_NUM

async def settings_card_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("card_number", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:card"))
    return ConversationHandler.END

async def cb_set_card_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter Cryptomus Merchant ID:", reply_markup=cancel_kb())
    return SETTINGS_CRYPTO_MID

async def settings_crypto_mid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("cryptomus_merchant_id", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("set:crypto"))
    return ConversationHandler.END

async def cb_set_crypto_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("support_username", "(not set)")
    await query.edit_message_text(f"Current: {current}\n\nEnter support @username:", reply_markup=cancel_kb())
    return SETTINGS_SUPPORT

async def settings_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("support_username", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await db.get_setting("currency", "USD")
    await query.edit_message_text(f"Current: {current}\n\nEnter currency (IRR, USD, USDT...):", reply_markup=cancel_kb())
    return SETTINGS_CURRENCY

async def settings_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await db.set_setting("currency", update.message.text.strip())
    await update.message.reply_text(t("setting_saved"), reply_markup=back_kb("adm:settings"))
    return ConversationHandler.END

async def cb_set_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = settings.SYNC_INTERVAL
    await query.edit_message_text(f"Current: {current}s\n\nEnter sync interval in seconds:", reply_markup=cancel_kb())
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

async def cb_cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Cancelled.", reply_markup=back_kb("adm:back"))
    return ConversationHandler.END

async def cb_subs_search_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    rows = []
    for s in results[:20]:
        label = s.get("comment") or s["id"][:12]
        rows.append([InlineKeyboardButton(label, callback_data=f"sub:detail:{s['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm:subs")])
    await update.message.reply_text("Search results:", reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

def _admin_filter():
    async def _f(update, ctx):
        return await _is_admin(update.effective_user.id) if update.effective_user else False
    from telegram.ext import filters as tfilters
    return tfilters.UpdateFilter(_f)

def get_main_conv_handler():
    wizard_states = {
        WIZARD_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_url)],
        WIZARD_SUPPORT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_support),
            CallbackQueryHandler(wizard_skip_support, pattern=r"^wizard:skip_support$"),
        ],
        WIZARD_CARD_NUM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_card_num),
            CallbackQueryHandler(wizard_skip_card, pattern=r"^wizard:skip_card$"),
        ],
        WIZARD_CARD_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_card_name),
            CallbackQueryHandler(wizard_skip_card_name, pattern=r"^wizard:skip_card_name$"),
        ],
        WIZARD_CRYPTO_MID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_crypto_mid),
            CallbackQueryHandler(wizard_skip_crypto, pattern=r"^wizard:skip_crypto$"),
        ],
        WIZARD_CRYPTO_KEY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_crypto_key),
            CallbackQueryHandler(wizard_skip_crypto, pattern=r"^wizard:skip_crypto$"),
        ],
        WIZARD_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_currency)],
        PLAN_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_name)],
        PLAN_CREATE_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_data)],
        PLAN_CREATE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_days)],
        PLAN_CREATE_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_ip)],
        PLAN_CREATE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_get_price)],
        PLAN_CREATE_NODES: [
            CallbackQueryHandler(plan_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(plan_nodes_done, pattern=r"^plan:nodes_done$"),
        ],
        PLAN_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_edit_value)],
        ADMIN_ADD_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_id)],
        ADMIN_ADD_PERMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_perms)],
        ADMIN_MANUAL_SUB_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_comment)],
        ADMIN_MANUAL_SUB_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_data)],
        ADMIN_MANUAL_SUB_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_days)],
        ADMIN_MANUAL_SUB_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_sub_ip)],
        ADMIN_MANUAL_SUB_NODES: [
            CallbackQueryHandler(manual_sub_toggle_node, pattern=r"^node_toggle:"),
            CallbackQueryHandler(manual_sub_done, pattern=r"^msub:nodes_done$"),
        ],
        SETTINGS_GG_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_gg_url)],
        SETTINGS_CARD_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_card_num)],
        SETTINGS_CARD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_card_name)],
        SETTINGS_CRYPTO_MID: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_crypto_mid)],
        SETTINGS_CRYPTO_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_crypto_key)],
        SETTINGS_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_support)],
        SETTINGS_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_currency)],
        SETTINGS_SYNC: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_sync)],
        USER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, users_search)],
        SUB_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, subs_search)],
    }
    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start_admin)],
        states=wizard_states,
        fallbacks=[CallbackQueryHandler(cb_cancel_conv, pattern=r"^cancel$")],
        per_message=False,
        name="admin_main"
    )

def get_handlers():
    return [
        get_main_conv_handler(),
        CallbackQueryHandler(cb_adm_back, pattern=r"^adm:back$"),
        CallbackQueryHandler(cb_adm_plans, pattern=r"^adm:plans$"),
        CallbackQueryHandler(cb_plan_detail, pattern=r"^plan:detail:"),
        CallbackQueryHandler(cb_plan_toggle, pattern=r"^plan:toggle:"),
        CallbackQueryHandler(cb_plan_delete, pattern=r"^plan:delete:"),
        CallbackQueryHandler(cb_plan_create, pattern=r"^plan:create$"),
        CallbackQueryHandler(cb_plan_edit_price, pattern=r"^plan:edit_price:"),
        CallbackQueryHandler(cb_plan_edit_name, pattern=r"^plan:edit_name:"),
        CallbackQueryHandler(cb_adm_subs, pattern=r"^adm:subs$"),
        CallbackQueryHandler(cb_sub_detail, pattern=r"^sub:detail:"),
        CallbackQueryHandler(cb_sub_stats, pattern=r"^sub:stats:"),
        CallbackQueryHandler(cb_sub_delete, pattern=r"^sub:delete:"),
        CallbackQueryHandler(cb_sub_create, pattern=r"^sub:create$"),
        CallbackQueryHandler(cb_subs_page, pattern=r"^subs_page:"),
        CallbackQueryHandler(cb_subs_search_prompt, pattern=r"^subs:search$"),
        CallbackQueryHandler(cb_adm_users, pattern=r"^adm:users$"),
        CallbackQueryHandler(cb_users_search_prompt, pattern=r"^users:search$"),
        CallbackQueryHandler(cb_user_detail, pattern=r"^user:detail:"),
        CallbackQueryHandler(cb_user_ban, pattern=r"^user:ban:"),
        CallbackQueryHandler(cb_user_unban, pattern=r"^user:unban:"),
        CallbackQueryHandler(cb_user_orders, pattern=r"^user:orders:"),
        CallbackQueryHandler(cb_adm_orders, pattern=r"^adm:orders$"),
        CallbackQueryHandler(cb_orders_list, pattern=r"^orders:list:"),
        CallbackQueryHandler(cb_order_detail, pattern=r"^order:detail:"),
        CallbackQueryHandler(cb_adm_admins, pattern=r"^adm:admins$"),
        CallbackQueryHandler(cb_admin_add, pattern=r"^admin:add$"),
        CallbackQueryHandler(cb_admin_detail, pattern=r"^admin:detail:"),
        CallbackQueryHandler(cb_admin_remove, pattern=r"^admin:remove:"),
        CallbackQueryHandler(cb_adm_settings, pattern=r"^adm:settings$"),
        CallbackQueryHandler(cb_set_gg_url, pattern=r"^set:gg_url$"),
        CallbackQueryHandler(cb_set_card, pattern=r"^set:card$"),
        CallbackQueryHandler(cb_card_toggle, pattern=r"^set:card_toggle$"),
        CallbackQueryHandler(cb_set_card_num, pattern=r"^set:card_num$"),
        CallbackQueryHandler(cb_set_card_name, pattern=r"^set:card_name$"),
        CallbackQueryHandler(cb_set_crypto, pattern=r"^set:crypto$"),
        CallbackQueryHandler(cb_crypto_toggle, pattern=r"^set:crypto_toggle$"),
        CallbackQueryHandler(cb_set_crypto_mid, pattern=r"^set:crypto_mid$"),
        CallbackQueryHandler(cb_set_crypto_key, pattern=r"^set:crypto_key$"),
        CallbackQueryHandler(cb_set_requests, pattern=r"^set:requests$"),
        CallbackQueryHandler(cb_req_toggle, pattern=r"^set:req_toggle$"),
        CallbackQueryHandler(cb_set_support, pattern=r"^set:support$"),
        CallbackQueryHandler(cb_set_currency, pattern=r"^set:currency$"),
        CallbackQueryHandler(cb_set_sync, pattern=r"^set:sync$"),
    ]
