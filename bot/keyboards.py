from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

def main_consumer_kb():
    return ReplyKeyboardMarkup([["📦 Plans", "📊 My Status"], ["💬 Support"]], resize_keyboard=True)

def main_admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Subscriptions", callback_data="adm:subs"), InlineKeyboardButton("🗂️ Plans", callback_data="adm:plans")],
        [InlineKeyboardButton("👥 Users", callback_data="adm:users"), InlineKeyboardButton("👑 Admins", callback_data="adm:admins")],
        [InlineKeyboardButton("💰 Orders", callback_data="adm:orders"), InlineKeyboardButton("⚙️ Settings", callback_data="adm:settings")],
    ])

def back_kb(target):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])

def confirm_reject_kb(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"order:confirm:{order_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"order:reject:{order_id}"),
    ]])

def plan_buy_kb(plan_id, card_enabled, crypto_enabled, requests_enabled):
    rows = []
    if card_enabled:
        rows.append([InlineKeyboardButton("💳 Pay by Card Transfer", callback_data=f"buy:card:{plan_id}")])
    if crypto_enabled:
        rows.append([InlineKeyboardButton("🪙 Pay with Crypto", callback_data=f"buy:crypto:{plan_id}")])
    if requests_enabled:
        rows.append([InlineKeyboardButton("🙋 Request Subscription", callback_data=f"buy:request:{plan_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="consumer:plans")])
    return InlineKeyboardMarkup(rows)

def plans_kb(plans):
    rows = [[InlineKeyboardButton(f"{p['name']} — {p['price']} ", callback_data=f"plan:{p['id']}")] for p in plans]
    return InlineKeyboardMarkup(rows)

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 GhostGate Connection", callback_data="set:gg_url")],
        [InlineKeyboardButton("💳 Card-to-Card", callback_data="set:card")],
        [InlineKeyboardButton("🪙 Cryptomus", callback_data="set:crypto")],
        [InlineKeyboardButton("🙋 Request Flow", callback_data="set:requests")],
        [InlineKeyboardButton("📝 Support Contact", callback_data="set:support")],
        [InlineKeyboardButton("💱 Currency", callback_data="set:currency")],
        [InlineKeyboardButton("🔄 Sync Interval", callback_data="set:sync")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:back")],
    ])

def paginate_kb(items, page, per_page, prefix, back_cb):
    total = len(items)
    start = page*per_page
    page_items = items[start:start+per_page]
    rows = [[InlineKeyboardButton(item["label"], callback_data=f"{prefix}:{item['id']}")] for item in page_items]
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"{prefix}_page:{page-1}"))
    if start+per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"{prefix}_page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def node_select_kb(nodes, selected_ids, done_cb, back_cb):
    rows = []
    for node in nodes:
        for inbound in node.get("inbounds", []):
            label = inbound.get("name") or f"Inbound #{inbound['id']}"
            check = "✅" if inbound["id"] in selected_ids else "⬜"
            rows.append([InlineKeyboardButton(f"{check} {node['name']} / {label}", callback_data=f"node_toggle:{inbound['id']}")])
    rows.append([InlineKeyboardButton("✅ Done", callback_data=done_cb), InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def skip_kb(skip_cb, back_cb=None):
    row = [InlineKeyboardButton("⏭️ Skip", callback_data=skip_cb)]
    if back_cb:
        row.append(InlineKeyboardButton("⬅️ Back", callback_data=back_cb))
    return InlineKeyboardMarkup([row])

def yes_no_kb(yes_cb, no_cb):
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data=yes_cb), InlineKeyboardButton("❌ No", callback_data=no_cb)]])

def toggle_kb(label, enabled, toggle_cb, back_cb):
    status = "✅ Enabled" if enabled else "❌ Disabled"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Toggle: {status}", callback_data=toggle_cb)],
        [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)],
    ])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])

def sub_actions_kb(sub_id, back_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats & QR", callback_data=f"sub:stats:{sub_id}")],
        [InlineKeyboardButton("🗑️ Delete", callback_data=f"sub:delete:{sub_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)],
    ])

def user_actions_kb(uid, is_banned, back_cb):
    ban_label = "🔓 Unban" if is_banned else "🚫 Ban"
    ban_cb = f"user:unban:{uid}" if is_banned else f"user:ban:{uid}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ban_label, callback_data=ban_cb)],
        [InlineKeyboardButton("📋 Orders", callback_data=f"user:orders:{uid}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)],
    ])

def plan_actions_kb(plan_id, is_active):
    toggle_label = "❌ Deactivate" if is_active else "✅ Activate"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"plan:toggle:{plan_id}")],
        [InlineKeyboardButton("✏️ Edit Price", callback_data=f"plan:edit_price:{plan_id}"), InlineKeyboardButton("✏️ Edit Name", callback_data=f"plan:edit_name:{plan_id}")],
        [InlineKeyboardButton("🗑️ Delete", callback_data=f"plan:delete:{plan_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="adm:plans")],
    ])

def order_detail_kb(order_id, status, back_cb):
    rows = []
    if status in ("pending", "waiting_confirm"):
        rows.append([InlineKeyboardButton("✅ Confirm", callback_data=f"order:confirm:{order_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"order:reject:{order_id}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)
