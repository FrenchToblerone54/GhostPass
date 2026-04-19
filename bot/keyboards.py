from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from bot.strings import t

def _fmt_plan_price(price, base_currency):
    if base_currency=="IRT":
        try:
            i=int(float(price))
            if float(price)==i and i>=1000 and i%1000==0:
                return f"{i//1000}k"
        except Exception:
            pass
    return str(price)

def main_consumer_kb():
    return ReplyKeyboardMarkup([[t("btn_consumer_trial")], [t("btn_consumer_plans"), t("btn_consumer_status")], [t("btn_consumer_referral"), t("btn_consumer_support")]], resize_keyboard=True)

def main_admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_adm_subs"), callback_data="adm:subs"), InlineKeyboardButton(t("btn_adm_plans"), callback_data="adm:plans")],
        [InlineKeyboardButton(t("btn_adm_users"), callback_data="adm:users"), InlineKeyboardButton(t("btn_adm_admins"), callback_data="adm:admins")],
        [InlineKeyboardButton(t("btn_adm_orders"), callback_data="adm:orders"), InlineKeyboardButton(t("btn_adm_settings"), callback_data="adm:settings")],
        [InlineKeyboardButton(t("btn_adm_discounts"), callback_data="adm:discounts"), InlineKeyboardButton(t("btn_adm_offers"), callback_data="adm:offers")],
        [InlineKeyboardButton(t("btn_adm_broadcast"), callback_data="adm:broadcast")],
        [InlineKeyboardButton(t("btn_adm_notifications"), callback_data="adm:notifications")],
        [InlineKeyboardButton(t("btn_adm_logs"), callback_data="adm:logs"), InlineKeyboardButton(t("btn_adm_update"), callback_data="adm:update")],
    ])

def back_kb(target):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_back"), callback_data=target)]])

def confirm_reject_kb(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_confirm"), callback_data=f"order:confirm:{order_id}"),
        InlineKeyboardButton(t("btn_reject"), callback_data=f"order:reject:{order_id}"),
    ]])

def plan_buy_kb(plan_id, card_enabled, crypto_enabled, requests_enabled, manual_enabled, discount_pct=0, wallet_balance=0, wallet_use=False, wallet_covers_full=False):
    rows = []
    if wallet_covers_full:
        rows.append([InlineKeyboardButton(t("btn_wallet_use", amount=wallet_balance), callback_data=f"buy:wallet:{plan_id}")])
    if card_enabled:
        rows.append([InlineKeyboardButton(t("btn_pay_card"), callback_data=f"buy:card:{plan_id}")])
    if crypto_enabled:
        rows.append([InlineKeyboardButton(t("btn_pay_crypto"), callback_data=f"buy:crypto:{plan_id}")])
    if requests_enabled:
        rows.append([InlineKeyboardButton(t("btn_request_sub"), callback_data=f"buy:request:{plan_id}")])
    if manual_enabled:
        rows.append([InlineKeyboardButton(t("btn_pay_manual"), callback_data=f"buy:manual:{plan_id}")])
    code_label = t("btn_discount_applied", pct=discount_pct) if discount_pct else t("btn_discount_use")
    rows.append([InlineKeyboardButton(code_label, callback_data=f"buy:discount:{plan_id}")])
    if wallet_balance > 0:
        if wallet_use:
            rows.append([InlineKeyboardButton(t("btn_wallet_use", amount=wallet_balance), callback_data=f"buy:wallet_toggle:{plan_id}")])
        else:
            rows.append([InlineKeyboardButton(t("btn_wallet_enable", amount=wallet_balance), callback_data=f"buy:wallet_toggle:{plan_id}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="consumer:plans")])
    return InlineKeyboardMarkup(rows)

def plans_kb(plans, base_currency="IRT", page=0, total=0, per_page=0):
    rows = [[InlineKeyboardButton(f"{t('btn_buy_plan', name=p['name'])} — {_fmt_plan_price(p['price'], base_currency)} {base_currency}", callback_data=f"plan:{p['id']}")] for p in plans]
    if per_page>0 and total>per_page:
        nav=[]
        if page>0:
            nav.append(InlineKeyboardButton("◀️", callback_data="consumer:plans_page:prev"))
        if (page+1)*per_page<total:
            nav.append(InlineKeyboardButton("▶️", callback_data="consumer:plans_page:next"))
        if nav:
            rows.append(nav)
    return InlineKeyboardMarkup(rows)

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_set_gg"), callback_data="set:gg_url")],
        [InlineKeyboardButton(t("btn_set_card"), callback_data="set:card")],
        [InlineKeyboardButton(t("btn_set_crypto"), callback_data="set:crypto")],
        [InlineKeyboardButton(t("btn_set_requests"), callback_data="set:requests")],
        [InlineKeyboardButton(t("btn_set_support"), callback_data="set:support")],
        [InlineKeyboardButton(t("btn_set_currencies"), callback_data="set:currencies")],
        [InlineKeyboardButton(t("btn_set_usdt"), callback_data="set:usdt")],
        [InlineKeyboardButton(t("btn_set_trial"), callback_data="set:trial")],
        [InlineKeyboardButton(t("btn_set_paid_note"), callback_data="set:paid_note")],
        [InlineKeyboardButton(t("btn_set_start_msg"), callback_data="set:start_msg")],
        [InlineKeyboardButton(t("btn_set_sync"), callback_data="set:sync")],
        [InlineKeyboardButton(t("btn_set_plans_pagination"), callback_data="set:plan_pagination")],
        [InlineKeyboardButton(t("btn_set_force_join"), callback_data="set:force_join")],
        [InlineKeyboardButton(t("btn_set_plan_start_after_use"), callback_data="set:plan_start_after_use")],
        [InlineKeyboardButton(t("btn_set_trial_start_after_use"), callback_data="set:trial_start_after_use")],
        [InlineKeyboardButton(t("btn_set_update_http_proxy"), callback_data="set:update_http_proxy"), InlineKeyboardButton(t("btn_set_update_https_proxy"), callback_data="set:update_https_proxy")],
        [InlineKeyboardButton(t("btn_set_referral"), callback_data="set:referral")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:back")],
    ])

def currencies_kb(currencies, base_currency, back_cb):
    rows = [[InlineKeyboardButton(f"{'📌 ' if c['code']==base_currency else ''}{c['code']} — {c['name']}", callback_data=f"curr:detail:{c['code']}")] for c in currencies]
    rows.append([InlineKeyboardButton(t("btn_curr_add"), callback_data="curr:add"), InlineKeyboardButton(t("btn_curr_set_base"), callback_data="curr:set_base")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def method_select_kb(selected_methods, done_cb, back_cb):
    all_methods = [("card", t("btn_method_card")), ("crypto", t("btn_method_crypto")), ("request", t("btn_method_request")), ("manual", t("btn_method_manual"))]
    rows = []
    for code, label in all_methods:
        check = "✅" if code in selected_methods else "⬜"
        rows.append([InlineKeyboardButton(f"{check} {label}", callback_data=f"meth_toggle:{code}")])
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data=done_cb), InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def node_select_kb(nodes, selected_ids, done_cb, back_cb, all_cb="", none_cb=""):
    rows = []
    for node in nodes:
        for inbound in node.get("inbounds", []):
            label = inbound.get("name") or f"Inbound #{inbound['id']}"
            check = "✅" if inbound["id"] in selected_ids else "⬜"
            rows.append([InlineKeyboardButton(f"{check} {node['name']} / {label}", callback_data=f"node_toggle:{inbound['id']}")])
    if all_cb and none_cb:
        rows.append([InlineKeyboardButton(t("btn_select_all"), callback_data=all_cb), InlineKeyboardButton(t("btn_unselect_all"), callback_data=none_cb)])
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data=done_cb), InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def skip_kb(skip_cb, back_cb=None):
    row = [InlineKeyboardButton(t("btn_skip"), callback_data=skip_cb)]
    if back_cb:
        row.append(InlineKeyboardButton(t("btn_back"), callback_data=back_cb))
    return InlineKeyboardMarkup([row])

def yes_no_kb(yes_cb, no_cb):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_yes"), callback_data=yes_cb), InlineKeyboardButton(t("btn_no"), callback_data=no_cb)]])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_cancel"), callback_data="cancel")]])

def subs_list_kb(subs):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"📦 {s['plan_name']}", callback_data=f"sub:detail:{s['ghostgate_sub_id']}")] for s in subs if s.get("ghostgate_sub_id")])

def sub_detail_kb(sub_id, enabled):
    toggle_label = t("btn_sub_disable") if enabled else t("btn_sub_enable")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_regen_link"), callback_data=f"sub:regen:{sub_id}"), InlineKeyboardButton(toggle_label, callback_data=f"sub:toggle:{sub_id}")],
        [InlineKeyboardButton(t("btn_sub_configs"), callback_data=f"sub:configs_user:{sub_id}")],
        [InlineKeyboardButton(t("btn_delete"), callback_data=f"sub:delete:{sub_id}")],
        [InlineKeyboardButton(t("btn_back"), callback_data="sub:list")],
    ])

def sub_actions_kb(sub_id, back_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_sub_stats"), callback_data=f"sub:stats:{sub_id}"), InlineKeyboardButton(t("btn_sub_configs"), callback_data=f"sub:configs:{sub_id}")],
        [InlineKeyboardButton(t("btn_sub_reset_traffic"), callback_data=f"adm:sub:reset_traffic:{sub_id}")],
        [InlineKeyboardButton(t("btn_delete"), callback_data=f"adm:sub:delete:{sub_id}")],
        [InlineKeyboardButton(t("btn_back"), callback_data=back_cb)],
    ])

def user_actions_kb(uid, is_banned, back_cb):
    ban_label = t("btn_unban") if is_banned else t("btn_ban")
    ban_cb = f"user:unban:{uid}" if is_banned else f"user:ban:{uid}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ban_label, callback_data=ban_cb)],
        [InlineKeyboardButton(t("btn_adm_orders"), callback_data=f"user:orders:{uid}")],
        [InlineKeyboardButton(t("btn_wallet_adjust"), callback_data=f"user:wallet:{uid}")],
        [InlineKeyboardButton(t("btn_reset_trial"), callback_data=f"user:reset_trial:{uid}")],
        [InlineKeyboardButton(t("btn_back"), callback_data=back_cb)],
    ])

def wallet_adjust_kb(uid, back_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_wallet_add"), callback_data=f"user:wallet_add:{uid}")],
        [InlineKeyboardButton(t("btn_wallet_remove"), callback_data=f"user:wallet_remove:{uid}")],
        [InlineKeyboardButton(t("btn_back"), callback_data=back_cb)],
    ])

def plan_actions_kb(plan_id, is_active):
    toggle_label = t("btn_deactivate") if is_active else t("btn_activate")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"plan:toggle:{plan_id}")],
        [InlineKeyboardButton(t("btn_edit_price"), callback_data=f"plan:edit_price:{plan_id}"), InlineKeyboardButton(t("btn_edit_name"), callback_data=f"plan:edit_name:{plan_id}")],
        [InlineKeyboardButton(t("btn_edit_nodes"), callback_data=f"plan:edit_nodes:{plan_id}")],
        [InlineKeyboardButton(t("btn_delete"), callback_data=f"plan:delete:{plan_id}")],
        [InlineKeyboardButton(t("btn_back"), callback_data="adm:plans")],
    ])

def order_detail_kb(order_id, status, back_cb):
    rows = []
    if status in ("pending", "waiting_confirm"):
        rows.append([InlineKeyboardButton(t("btn_confirm"), callback_data=f"order:confirm:{order_id}"), InlineKeyboardButton(t("btn_reject"), callback_data=f"order:reject:{order_id}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def curr_detail_kb(code, is_base, back_cb):
    rows = []
    if not is_base:
        rows.append([InlineKeyboardButton(t("btn_edit_rate"), callback_data=f"curr:edit_rate:{code}")])
    rows.append([InlineKeyboardButton(t("btn_delete"), callback_data=f"curr:delete:{code}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def base_select_kb(currencies, back_cb):
    rows = [[InlineKeyboardButton(f"{c['code']} — {c['name']}", callback_data=f"curr:make_base:{c['code']}")] for c in currencies]
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def logs_kb(page, total, per_page):
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data="adm:logs_page:prev"))
    if (page+1)*per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data="adm:logs_page:next"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    return InlineKeyboardMarkup(rows)

def referral_panel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_referral_redeem"), callback_data="ref:packages")]])

def referral_packages_kb(packages, available):
    rows=[[InlineKeyboardButton(t("referral_pkg_item", name=p["name"], credits=p["credits_required"]), callback_data=f"ref:pkg:{p['id']}")] for p in packages]
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="ref:back")])
    return InlineKeyboardMarkup(rows)

def referral_pkg_detail_kb(pkg_id, can_redeem):
    rows=[]
    if can_redeem:
        rows.append([InlineKeyboardButton(t("btn_referral_redeem"), callback_data=f"ref:redeem:{pkg_id}")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="ref:packages")])
    return InlineKeyboardMarkup(rows)

def referral_redeem_confirm_kb(pkg_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_yes"), callback_data=f"ref:confirm:{pkg_id}"), InlineKeyboardButton(t("btn_no"), callback_data=f"ref:pkg:{pkg_id}")]])

def referral_settings_kb(enabled, packages, commission_enabled=False, commission_pct=0):
    rows=[[InlineKeyboardButton(t("adm_toggle_btn", status=t("adm_enabled") if enabled else t("adm_disabled")), callback_data="set:referral_toggle")]]
    for p in packages:
        status="✅" if p["is_active"] else "❌"
        rows.append([InlineKeyboardButton(f"{status} {p['name']} ({p['credits_required']} cr)", callback_data=f"ref_pkg:detail:{p['id']}")])
    rows.append([InlineKeyboardButton(t("adm_referral_add_pkg"), callback_data="ref_pkg:create")])
    rows.append([InlineKeyboardButton(t("adm_bulk_nodes_btn"), callback_data="ref_pkgs:bulk_nodes")])
    rows.append([InlineKeyboardButton(t("btn_referral_commission_toggle"), callback_data="set:referral_commission_toggle")])
    rows.append([InlineKeyboardButton(t("btn_referral_commission_set_pct"), callback_data="set:referral_commission_pct")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:settings")])
    return InlineKeyboardMarkup(rows)

def referral_pkg_admin_kb(pkg_id, is_active):
    toggle_label=t("btn_deactivate") if is_active else t("btn_activate")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"ref_pkg:toggle:{pkg_id}")],
        [InlineKeyboardButton(t("btn_edit_nodes"), callback_data=f"ref_pkg:edit_nodes:{pkg_id}")],
        [InlineKeyboardButton(t("btn_delete"), callback_data=f"ref_pkg:delete:{pkg_id}")],
        [InlineKeyboardButton(t("btn_back"), callback_data="set:referral")],
    ])

def notifications_kb(s):
    events = [
        ("notify_discount", "notif_label_discount"),
        ("notify_payment_link", "notif_label_payment_link"),
        ("notify_purchase", "notif_label_purchase"),
        ("notify_trial", "notif_label_trial"),
        ("notify_sub_start", "notif_label_sub_start"),
    ]
    rows = [[InlineKeyboardButton(f"{'✅' if s.get(k)=='1' else '❌'} {t(label_key)}", callback_data=f"notif_toggle:{k}")] for k, label_key in events]
    rows.append([InlineKeyboardButton(t("notif_btn_sub_start_msg"), callback_data="notif:sub_start_msg")])
    rows.append([InlineKeyboardButton(t("btn_back"), callback_data="adm:back")])
    return InlineKeyboardMarkup(rows)

def subs_bulk_note_kb(page_subs, selected_ids, page, total, per_page):
    rows = []
    for s in page_subs:
        label = s.get("comment") or s["id"][:8]
        check = "✅" if s["id"] in selected_ids else "⬜"
        rows.append([InlineKeyboardButton(f"{check} {label}", callback_data=f"snote_toggle:{s['id']}")])
    rows.append([InlineKeyboardButton(t("btn_select_all"), callback_data="snote:all"), InlineKeyboardButton(t("btn_unselect_all"), callback_data="snote:none")])
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("◀️", callback_data="snote_page:prev"))
    if (page+1)*per_page<total:
        nav.append(InlineKeyboardButton("▶️", callback_data="snote_page:next"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("btn_done"), callback_data="snote:done"), InlineKeyboardButton(t("btn_cancel"), callback_data="cancel")])
    return InlineKeyboardMarkup(rows)
